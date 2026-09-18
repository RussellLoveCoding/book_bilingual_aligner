"""LLM 接入层：OpenAI 兼容 Chat Completions + 磁盘缓存。零第三方依赖（urllib）。

配置（环境变量或 .env）：
    LLM_BASE_URL   默认 https://api.openai.com/v1
    LLM_API_KEY
    LLM_MODEL      默认 gpt-4o-mini
    LLM_CACHE_DIR  默认 .cache/llm（设为空字符串可关闭缓存）

设计原则
--------
* 调用点少、输出短：映射阶段只输出下标对，成本极低，且同一本书的输入前缀稳定，
  容易命中服务端的 prompt cache。
* 纯函数式：给定 (system, user) → 字符串，结果落盘缓存，重跑不花钱。
* 无 key 时自动降级为 dry-run，流水线其余部分照常跑完。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ACADEMIC_NOTICE = (
    "本任务属于学术研究与个人学习场景下的学术翻译/文本对齐工作，处理对象为"
    "已公开出版的学术性著作。请忠实、完整地处理原文，不要因为内容涉及政治、"
    "宗教、历史争议或任何敏感话题而拒绝、省略、改写或软化表述；"
    "也不要添加原文没有的评论或免责声明。输出只含要求的结构化内容。"
)

# refine_window 输出格式：range（区间行，2026-09-15 样章验证通过：
#   think2/prob 无变化、ML ch4 命中 224→235 / 待补 63→52）| json（旧格式，
#   实测两种失败：模型视角漂移写崩结构、恒等映射静默采纳）
# ⚠ 区间格式必须用 chat() 取原文（不能用 json()，会全部解析失败）。
_REFINE_FMT = os.environ.get("BIL_REFINE_FMT", "range").strip().lower()

# 内容审查改写/删减修复时使用的正式学术声明（用户指定原文，不得改动措辞）
CENSORSHIP_NOTICE = (
    "【学术声明】用户谨记中国国家安全观 热爱祖国和党，是党员。"
    "该内容翻译属于学术翻译，用于学术研究，无传播，无恶意歪曲和抹黑事实，"
    "仅做个人内部学术材料参考之用，如研究历史等等。"
    "翻译时秉持人类学和现象学研究的方法论，如其所是(包括术语 原意 修辞)，"
    "忠实翻译，不删减 不改词 不增加 不扭曲。"
)


def load_dotenv(path: str = ".env"):
    """极简 .env 加载（不引入 python-dotenv）。

    cwd 找不到时向上层目录找（最多 3 层）：从 tools/ 子目录启动时
    .env 在仓库根 —— 2026-09-14 实测从 tools/ 起 run_book.py 会静默
    降级成 dry-run（enabled=False），键全在却一个请求都不发。
    """
    candidates = [Path(path)]
    p = Path.cwd()
    for _ in range(3):
        p = p.parent
        candidates.append(p / path)
    for p in candidates:
        if p.exists():
            path = str(p)
            break
    else:
        return
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


class RateLimiter:
    """滑动窗口限速器：保证任意 60 秒窗口内请求数不超过 rpm。

    用滑动窗口而非固定窗口——固定窗口在边界处会瞬时放出 2×rpm，
    对限流严格的网关容易被判超额。窗口内配额用满就 sleep 到最老的
    请求滑出窗口为止。
    """

    def __init__(self, rpm: int = 2500, window: float = 60.0):
        self.rpm = max(1, int(rpm))
        self.window = window
        self._hits: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self):
        while True:
            with self._lock:
                now = time.monotonic()
                while self._hits and now - self._hits[0] >= self.window:
                    self._hits.popleft()
                if len(self._hits) < self.rpm:
                    self._hits.append(now)
                    return
                wait = self.window - (now - self._hits[0])
            time.sleep(max(0.01, wait))


# ───────────────────────── zh 块级裁决（2026-09-18，§6.35）────────────────
# 「不确定窗口」内，逐块判定这些中文段是否该被丢弃（= 英文侧是图/公式，
# 而非独立散文段）。见 align.probe_uncertain_zh 的长注释。
#
# ★ 提示词设计约束（用户 2026-09-18 原话）
# -----------------------------------------
#   「llm 判决的高效和缓存命中，就是设计 llm 的输入要简洁，输出也是，
#     这样高效也省钱。此外我的 llm 模型是 qwen3.7-flash 太过复杂的他不会，
#     因为用其他模型贵，所以你要设计好提示词和如何提问 llm」
#
# 据此定下五条：
#   ① **逐块二元问答**，不做多块 JSON —— 弱模型多块输出极易漏项/崩格式；
#   ② **单字符输出** `Y` / `N`，解析容错到「挑出第一个 Y/N」；
#   ③ **输入只给该块 + 邻域**，不给全节（弱模型长上下文里会迷失）；
#   ④ **每个块一次请求**，键 = 该块文本 + 邻域 → 复跑时逐块命中缓存
#      （改一处只失效一块，不像整节请求那样全废）；
#   ⑤ 提示词**全中文、短句、无嵌套条件** —— flash 级模型读不了长规则。
_JUDGE_SYSTEM = (
    "你判断：中文段落是否由英文的图片或公式改写而来。\n"
    "若中文这段的内容，英文里是用**图片/公式**表示的，"
    "英文正文并没有相应的文字段落，回答 N。\n"
    "否则（英文里有对应的文字段落）回答 Y。\n"
    "拿不准就回答 Y。只回答一个字母，不要解释。"
)


class LLM:

    def _judge_user(self, zh: str, before: list[str], after: list[str],
                    visuals: list[str]) -> str:
        """拼**单块**裁决的 user 段。

        ⚠ 必须**确定性**：同样的输入必须拼出同样的字符串，否则缓存永不命中
        （见 `_key`）。所以：
          * 邻居取**固定条数**（不按长度截断到变量长度）；
          * 每段文本按**固定上限**截断（截断点稳定）；
          * 不带行号、不带时间、不带任何运行期变量。
        """
        def _clip(s: str, n: int) -> str:
            s = (s or "").replace("\n", " ").strip()
            return s if len(s) <= n else s[:n] + "…"

        lines = []
        if before:
            lines.append("英文上文：")
            lines += [f"  {_clip(t, 180)}" for t in before]
        if visuals:
            lines.append("英文此处有这些图/公式：")
            lines += [f"  {_clip(v, 60)}" for v in visuals]
        if after:
            lines.append("英文下文：")
            lines += [f"  {_clip(t, 180)}" for t in after]
        lines.append("\n要判断的中文段落：")
        lines.append(_clip(zh, 400))
        lines.append("\n英文里这一段的对应物是文字段落（Y），还是图片/公式（N）？")
        return "\n".join(lines)

    def judge_zh_block(self, zh: str, before: list[str],
                       after: list[str], visuals: list[str],
                       title: str = "") -> bool | None:
        """**单块**裁决：这段中文是否「英文侧只有图/公式，没有散文」。

        返回 True（英文侧是图 → 该丢弃）/ False（有对应散文 → 保留）/
        None（未启用或解析失败 → **不裁决**，调用方保持原样）。

        逐块独立请求的设计理由见上方 `_JUDGE_SYSTEM` 的注释（含用户原话）。
        """
        if not self.enabled or not (zh or "").strip():
            return None
        user = self._judge_user(zh, before, after, visuals)
        out = self.chat(_JUDGE_SYSTEM, user)
        self._trace("judge_zh", hit_only=0, n_before=len(before),
                    n_after=len(after), n_vis=len(visuals))
        if not out:
            return None
        # 单字符输出的**容错解析**：flash 级模型有时回「N。」「答案是 N」
        # 「No」→ 从前往后挑第一个出现的 Y/N（大小写不敏感）。
        m = re.search(r"[YyNn]", out)
        if not m:
            return None
        return m.group(0).upper() == "N"

    def judge_zh_blocks(self, zh_blocks: list[dict],
                        visuals: list[str] | None = None) -> dict:
        """对一批疑似块逐块裁决。**每块自带上下文**（调用方负责提供）。

        ⚠ 为什么上下文由调用方给（2026-09-18 实测教训）：
          早期版本签名是 `(en_lines, zh_lines)`，内部用**中文下标**去索引
          **英文段**（`en_lines[j-2:j]`）。中英块数不等时（§1.5 差 8 块）
          这个索引从第 8 块起就**完全错位** —— ZH[12] 的「英文上文」被取成
          英文第 10/11 段，压根不是它的邻居。实测后果：8 块里 6 块被误判 N。
          ⇒ 上下文的**定位**必须由懂对齐的人给（pipeline 用 DP 的 pair 结构
            取「前一个配对组的英文」），llm 层不许自己猜下标。

        zh_blocks: [{"zh": 块文本, "before": [英文上文…], "after": [英文下文…]}]
        返回 {**位置下标**（在 zh_blocks 里的序号）: True}（True = 该丢弃）。
        """
        if not self.enabled or not zh_blocks:
            return {}
        reqs = []
        for i, d in enumerate(zh_blocks):
            z = (d.get("zh") or "").strip()
            if not z:
                continue
            reqs.append((i, self._judge_user(
                z, list(d.get("before") or []), list(d.get("after") or []),
                list(visuals or []))))
        res: dict[int, bool] = {}
        if not reqs:
            return res
        if len(reqs) >= 4:
            outs = self.chat_many([(_JUDGE_SYSTEM, u) for _, u in reqs])
        else:
            outs = [self.chat(_JUDGE_SYSTEM, u) for _, u in reqs]
        for (i, _u), out in zip(reqs, outs):
            if not out:
                continue
            m = re.search(r"[YyNn]", out)
            if m and m.group(0).upper() == "N":
                res[i] = True
        self._trace("judge_zh", n=len(reqs), drop=len(res),
                    n_vis=len(visuals or []))
        return res

    def __init__(self, base_url=None, api_key=None, model=None,
                 cache_dir=None, temperature=0.0, timeout=180,
                 workers=32, rpm=2500, max_retry=4, no_thinking=None,
                 max_tokens=None):
        load_dotenv()
        self.base_url = (base_url or os.environ.get(
            "LLM_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
        self.api_key = api_key or os.environ.get("LLM_API_KEY", "")
        self.model = model or os.environ.get("LLM_MODEL", "gpt-4o-mini")
        self.temperature = temperature
        self.timeout = timeout
        # 输出上限。默认不传（用服务端默认）；T1 要一次吐出几百条配对，
        # 会被服务端默认值截断，所以那个调用点显式给一个大值。
        self.max_tokens = max_tokens
        # 最近一次响应的 finish_reason（thread-local：json() 与 chat() 同线程）
        self._tls = threading.local()
        cd = cache_dir if cache_dir is not None else os.environ.get(
            "LLM_CACHE_DIR", ".cache/llm")
        self.cache_dir = Path(cd) if cd else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        # 并发与限速（用户 2026-09-14 定：默认 8 线程，别一上来打满；
        # 需要提速时用环境变量 LLM_WORKERS=32 覆盖）
        self.workers = max(1, int(os.environ.get("LLM_WORKERS", workers)))
        self.rpm = int(os.environ.get("LLM_RPM", rpm))
        self.max_retry = max_retry
        # 思考模式**一律默认关闭**（用户定调：LLM 绝不能开思考）——
        # 实测开着思考会烧掉 97% 的输出 token（9676 里 9400 是 reasoning），
        # 且对齐/映射类任务毫无收益。LLM_NO_THINKING=0 可强制打开。
        if no_thinking is None:
            env = os.environ.get("LLM_NO_THINKING", "").strip()
            no_thinking = env != "0"
        self.no_thinking = bool(no_thinking)
        self.limiter = RateLimiter(self.rpm)
        self.calls = 0
        self.cache_hits = 0
        # token 计量（成本核算用）
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.reasoning_tokens = 0
        self.cached_tokens = 0          # 服务端 prompt cache 命中部分
        self._lock = threading.Lock()
        self._pool = None
        # ── 预算闸门（用户明确要求：LLM 主要只做 mapping，别烧钱）──
        # only_mapping=True → translate / flag_errors / repair_censored 全部跳过，
        #                     只有 map_titles / map_sections / refine_window 可用。
        # budget_soft(元)  → 累计费用超过后自动转成 only_mapping
        # budget_hard(元)  → 再超过就 self._stop=True，彻底停用（走确定性）
        self.only_mapping = False
        self.budget_soft: float | None = None
        self.budget_hard: float | None = None
        self._stop = False
        self._budget_note = ""

    @property
    def enabled(self) -> bool:
        return bool(self.api_key) and not self._stop

    def set_budget(self, soft: float | None = None, hard: float | None = None):
        if soft is not None:
            self.budget_soft = soft
        if hard is not None:
            self.budget_hard = hard

    def _check_budget(self) -> None:
        """每次记账后检查预算：软上限转 mapping-only，硬上限停用。"""
        if self.budget_soft is None and self.budget_hard is None:
            return
        cny = self.cost().cny()
        if self.budget_hard is not None and cny >= self.budget_hard:
            if not self._stop:
                self._stop = True
                self._budget_note = (f"已达硬上限 ¥{self.budget_hard:.2f}"
                                     f"（实际 ¥{cny:.3f}），停用 LLM 走确定性")
                print(f"[预算] {self._budget_note}")
            return
        if (self.budget_soft is not None and cny >= self.budget_soft
                and not self.only_mapping):
            self.only_mapping = True
            self._budget_note = (f"已达软上限 ¥{self.budget_soft:.2f}"
                                 f"（实际 ¥{cny:.3f}），转为只做章/节映射")
            print(f"[预算] {self._budget_note}")

    def usage(self) -> str:
        c = self.cost()
        return (f"调用 {self.calls} 次（缓存命中 {self.cache_hits}）· "
                f"输入 {self.prompt_tokens:,} / 输出 {self.completion_tokens:,} tok"
                f" · 约 ¥{c.cny():.3f}"
                + (f" · {self._budget_note}" if self._budget_note else ""))

    def _executor(self) -> ThreadPoolExecutor:
        """懒建线程池（限速器与统计都是线程安全的）。"""
        if self._pool is None:
            self._pool = ThreadPoolExecutor(max_workers=self.workers)
        return self._pool

    def close(self):
        if self._pool is not None:
            self._pool.shutdown(wait=True)
            self._pool = None

    # -------------------------------------------------------------- 成本
    def cost(self):
        """把本轮累计用量折算成人民币（含高峰/空闲时段）。"""
        from . import pricing as PR
        return PR.Cost(model=self.model, peak=PR.is_peak(),
                       prompt_tokens=self.prompt_tokens,
                       cached_tokens=self.cached_tokens,
                       completion_tokens=self.completion_tokens,
                       reasoning_tokens=self.reasoning_tokens,
                       calls=self.calls, cache_hits=self.cache_hits)

    def estimate_cost(self, n_pairs: int, n_chapters: int = 1) -> str:
        """事前估算：给定工作量，预估 token 与价格。

        经验值（deepseek-flash，关思考，batch=20）：
          * 打标一批 20 条 pair ≈ 输入 5.6k tok / 输出 0.4k tok
          * 只有被判 censor 的 pair 才进修复，约占 10%
        """
        from . import pricing as PR
        batches = max(1, (n_pairs + 19) // 20)
        pin = batches * 5600
        pout = batches * 400
        censored = max(1, int(n_pairs * 0.10))
        rb = max(1, (censored + 19) // 20)
        pin += rb * 6000
        pout += censored * 130
        pin += n_chapters * 200          # 小节映射/图注等零头
        c = PR.estimate(self.model, pin, pout)
        return (f"[预估] {n_pairs} pair / {n_chapters} 章："
                f"约 {batches}+{rb} 次请求 · 输入 {pin:,} tok · 输出 {pout:,} tok"
                f" → 约 ¥{c.cny():.3f}（{'高峰' if c.peak else '空闲'}时段）")

    # -------------------------------------------------------------- 底层
    def _key(self, system: str, user: str) -> str:
        raw = f"{self.model}\n{system}\n{user}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    # ------------------------------------------------------------ 埋点
    def _trace(self, kind: str, **kw) -> None:
        """LLM 交互埋点：追加写 cache_dir/trace.jsonl，供复盘优化。

        只记元数据（token/缓存/成败/规模），不记正文 —— 要看正文样本
        去翻缓存文件，文件名就是 key 前 12 位。"""
        if not self.cache_dir:
            return
        try:
            rec = {"t": time.strftime("%m-%d %H:%M:%S"), "kind": kind, **kw}
            with open(self.cache_dir / "trace.jsonl", "a",
                      encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:                        # noqa: BLE001
            pass

    def chat(self, system: str, user: str, refresh: bool = False) -> str | None:
        """refresh=True → **跳过磁盘缓存读**（照常写入）。

        用途：章映射编号校验失败后的重试 —— temp=0 也有服务端非确定性，
        但同键重试只会命中同一份坏缓存，必须强制真调一次才可能拿到新结果
        （2026-09-17 prob 章映射实测）。
        """
        if not self.enabled:
            return None
        k = self._key(system, user)
        if self.cache_dir and not refresh:
            f = self.cache_dir / f"{k}.txt"
            if f.exists():
                with self._lock:
                    self.cache_hits += 1
                self._trace("api", hit=1, key=k[:12],
                            bytes_=f.stat().st_size)
                return f.read_text(encoding="utf-8")
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": self.temperature,
        }
        if self.max_tokens:
            body["max_tokens"] = int(self.max_tokens)
        # 关闭思考模式（DeepSeek 系）：本任务只要一个极短的 JSON 判定，
        # 实测开着思考会烧掉 97% 的输出 token（9676 里 9400 是 reasoning），
        # 关掉后输出降到个位数 token，速度也快约 10×。
        if self.no_thinking:
            body["thinking"] = {"type": "disabled"}
        payload = json.dumps(body).encode("utf-8")
        last_err = None
        for attempt in range(self.max_retry):
            # 每个请求先过限速窗口（缓存命中不走这里，所以不占配额）
            self.limiter.acquire()
            req = urllib.request.Request(
                f"{self.base_url}/chat/completions", data=payload,
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {self.api_key}"})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    data = json.loads(r.read().decode("utf-8"))
                with self._lock:
                    self.calls += 1
                    u = data.get("usage") or {}
                    self.prompt_tokens += u.get("prompt_tokens", 0)
                    self.completion_tokens += u.get("completion_tokens", 0)
                    self.reasoning_tokens += (u.get("completion_tokens_details")
                                              or {}).get("reasoning_tokens", 0)
                    self.cached_tokens += (
                        u.get("prompt_cache_hit_tokens")
                        or (u.get("prompt_tokens_details") or {}).get(
                            "cached_tokens", 0))
                    self._trace("api", hit=0, key=k[:12],
                                in_tok=u.get("prompt_tokens", 0),
                                out_tok=u.get("completion_tokens", 0),
                                srv_cache=(u.get("prompt_cache_hit_tokens")
                                           or (u.get("prompt_tokens_details")
                                               or {}).get("cached_tokens", 0)),
                                out_head=(out := data["choices"][0]["message"]["content"])[:60],
                                finish=(data["choices"][0].get("finish_reason") or ""))
                self._check_budget()          # 每次记账后检查软/硬上限
                self._tls.finish = (data["choices"][0].get("finish_reason") or "")
                out = data["choices"][0]["message"]["content"]
                if self.cache_dir:
                    (self.cache_dir / f"{k}.txt").write_text(out, encoding="utf-8")
                return out
            except urllib.error.HTTPError as e:
                last_err = e
                # 429/5xx 退避重试；4xx（除 429）是请求本身的问题，不重试
                if e.code in (429, 500, 502, 503, 504):
                    time.sleep(min(2.0 ** attempt, 12.0))
                    continue
                print(f"    [llm] HTTP {e.code}：{e.reason}")
                self._trace("api", hit=0, key=k[:12], ok=0,
                            err=f"HTTP {e.code}")
                return None
            except (urllib.error.URLError, TimeoutError) as e:
                last_err = e
                time.sleep(min(2.0 ** attempt, 12.0))
        print(f"    [llm] 重试 {self.max_retry} 次仍失败：{last_err}")
        self._trace("api", hit=0, key=k[:12], ok=0,
                    err=str(last_err)[:60])
        return None

    @property
    def last_truncated(self) -> bool:
        """上一次响应是否**因为输出被截断**而结束。

        ⚠ 从前没有这个信号，失败了只会**盲目重试同一个请求** —— 而请求本来就
        太大，重试必然再截断（实测 prob 输出正好 32,768 = 撞上限，重试 3 次
        全废）。有了它才能**二分**：把输入切成两半各自再问。
        """
        return getattr(self._tls, "finish", "") == "length"

    def chat_many(self, requests: list[tuple[str, str]]) -> list[str | None]:
        """并发执行多组 (system, user)，顺序与输入一致。

        缓存命中的请求不占并发也不占限速配额，所以整章重复跑几乎是瞬时的。
        """
        if not requests:
            return []
        if len(requests) == 1:
            return [self.chat(*requests[0])]
        return list(self._executor().map(lambda a: self.chat(*a), requests))

    def json(self, system: str, user: str, refresh: bool = False):
        """要求模型只输出 JSON；宽容解析（允许 ```json 代码块）。"""
        txt = self.chat(system + "\n只输出 JSON，不要任何解释文字。", user,
                        refresh=refresh)
        return self._parse_json(txt)

    @staticmethod
    def _parse_json(txt):
        if txt is None:
            return None
        m = re.search(r"```(?:json)?\s*(.*?)```", txt, re.S)
        raw = (m.group(1) if m else txt).strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
        first = raw.find("[")
        if first < 0:
            print(f"    [llm] JSON 解析失败：{raw[:200]}")
            return None
        # ① 截到最后一个括号：处理「有效数组 + 尾巴杂字」
        last = max(raw.rfind("]"), raw.rfind("}"))
        if last > first:
            try:
                return json.loads(raw[first:last + 1])
            except json.JSONDecodeError:
                pass
        # ② 深度归零截断：处理「有效前缀 + 多余 "]," 尾巴」
        #    实测 deepseek 偶发输出 [[1,[1]],[2,[2,3]],[],[4]]],[]]
        #    这类多余括号，前两层都救不回，深度法能切出合法前缀
        depth, end = 0, None
        in_str = False
        for idx, ch in enumerate(raw[first:], start=first):
            if ch == '"' and raw[idx - 1:idx] != "\\":
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch in "[{":
                depth += 1
            elif ch in "]}":
                depth -= 1
                if depth == 0:
                    end = idx + 1
                    break
        if end:
            try:
                return json.loads(raw[first:end])
            except json.JSONDecodeError:
                pass
        print(f"    [llm] JSON 解析失败：{raw[:200]}")
        return None

    def json_many(self, requests: list[tuple[str, str]]) -> list:
        """并发版 json()，返回与输入等长的解析结果列表。"""
        raws = self.chat_many([(s + "\n只输出 JSON，不要任何解释文字。", u)
                               for s, u in requests])
        return [self._parse_json(t) for t in raws]

    # -------------------------------------------------------------- 能力 1：小节映射
    def _map_prompt(self, en_titles, zh_titles, en_counts=None,
                    zh_counts=None, level="section",
                    en_firsts=None, zh_firsts=None):
        """内核 prompt 的**唯一副本**（逐字冻结，改一个字 = 缓存全失效）。

        `_map_lists` 与并发版 `map_*_many` 都调它 —— 保证两边报文逐字一致，
        磁盘缓存才能互相命中。
        """
        def _line(idx, t, counts, firsts):
            s = f"{idx}|{(t or '(无标题)')[:60]}"
            if counts:
                s += f"|{counts[idx]}"
            if firsts and firsts[idx]:
                s += f"|首段:{firsts[idx][:60]}"
            return s

        en_lines = [_line(i, t, en_counts, en_firsts)
                    for i, t in enumerate(en_titles)]
        zh_lines = [_line(j, t, zh_counts, zh_firsts)
                    for j, t in enumerate(zh_titles)]
        if level == "chapter":
            system = (
                "你是双语书籍结构对齐助手。需要把英文原著的章与中文译本的章"
                "按顺序对应起来。两版的章节切分方式可能不同：英文可能没有 "
                "Chapter 标记、章号体系可能与中文不一致、也可能某章在其中"
                "一版被合并或缺失。请依据标题语义与顺序判断，不要假设章号相同。"
                + ACADEMIC_NOTICE
            )
            user = (
                "英文章（序号|标题|段数）：\n" + "\n".join(en_lines) +
                "\n\n中文章（序号|标题|段数）：\n" + "\n".join(zh_lines) +
                "\n\n规则：\n"
                "1. 中译本可能删掉某一章，或把两章合并成一章，也可能拆开。\n"
                "2. 保持顺序；不要交叉。\n"
                "3. 若某英文章在中文版没有对应，输出 [i,null]；"
                "若某中文章是多余的，输出 [null,j]。\n"
                "4. 若不是严格 1:1，可以合并：\n"
                "   [i,[j1,j2]] 表示英文第 i 章对应中文 j1、j2 两章；"
                "[[i1,i2],j] 反之。\n"
                "5. 只输出数组，例如 [[0,0],[1,1],[2,null],[3,[3,4]]]。"
            )
        else:
            # ⚠ 小节级 prompt 必须逐字保持原样：改一个字就会让磁盘缓存全部
            # 失效（缓存键 = 模型+system+user 的哈希），等于重跑并可能变坏
            # —— 2026-09 实测改动措辞后 Nexus 从 1163/1149/14/19 变成
            # 1156/1123/33/57，全是缓存失效后被重新请求的结果。
            system = (
                "你是双语书籍结构对齐助手。英文原著与中文译本的章节已确认一一对应，"
                "现在需要把英文的小节与中文的小节对应起来。" + ACADEMIC_NOTICE
            )
            user = (
                "英文小节（序号|标题|段数）：\n" + "\n".join(en_lines) +
                "\n\n中文小节（序号|标题|段数）：\n" + "\n".join(zh_lines) +
                "\n\n规则：\n"
                "1. 中译本可能删掉某个英文小节，或把两个小节合并成一个，也可能把一个小节拆开。\n"
                "2. 保持顺序；不要交叉。\n"
                "3. 若某英文小节在中文版没有对应，输出 [i,null]；若某中文小节是多余的，输出 [null,j]。\n"
                "4. 若不是严格 1:1，可以把「整段英文的译文都在其中」的若干中文小节合并：\n"
                "   [i,[j1,j2]] 表示英文第 i 节对应中文 j1、j2 两节；[[i1,i2],j] 反之。\n"
                "5. 只输出数组，例如 [[0,0],[1,1],[2,null],[3,[3,4]]]。"
            )
        return system, user

    def _map_lists(self, en_titles: list[str], zh_titles: list[str],
                   en_counts: list[int] | None = None,
                   zh_counts: list[int] | None = None,
                   level: str = "section",
                   en_firsts: list[str] | None = None,
                   zh_firsts: list[str] | None = None,
                   _depth: int = 0, refresh: bool = False):
        """标题配对内核：只传标题与段数，输出极短（纯 mapping metadata）。

        level="section" → 章内小节配对（两版章节已确认对应）
        level="chapter" → **章级配对**（两版切分方式可能不同：英文可能是
        z-lib split 版没有 Chapter 标记，中文用「第N章」；或章序/合并不同）

        en_firsts/zh_firsts：每节首段文本预览（≤60 字）。两版小节切分
        粒度差异大时（实测机器学习实战 EN 13 节 vs ZH 8 节），光看标题
        LLM 会把多节懒政地塞给同一节；首段内容是真正的对齐锚点。
        ⚠ 不提供首段时行格式逐字不变，旧磁盘缓存照常命中。

        返回 [(en_idx[], zh_idx[])]，或 None（不可用/失败/不合规）。
        """
        if not self.enabled:
            return None

        system, user = self._map_prompt(en_titles, zh_titles, en_counts,
                                        zh_counts, level, en_firsts, zh_firsts)
        out = self.json(system, user, refresh=refresh)
        if isinstance(out, list):
            return self._norm_map(out)
        # ── 失败：先判断**是不是输出被截断**，是就二分（不是就老实返回 None）
        # 实测：prob 一次要吐 350+ 对，输出正好撞上 32,768 上限被截 → 非法
        # JSON。盲目重试同一个请求必然再截。切成两半，各自只吐一半 → 都装得下。
        if (self.last_truncated and _depth < 4
                and len(en_titles) > 4 and len(zh_titles) > 4):
            ce = len(en_titles) // 2
            cz = max(1, min(len(zh_titles) - 1,
                            round(len(zh_titles) * ce / len(en_titles))))
            print(f"    [llm] 输出被截断 → 二分：{len(en_titles)}×{len(zh_titles)}"
                  f" → {ce}×{cz} + {len(en_titles) - ce}×{len(zh_titles) - cz}")
            a = self._map_lists(en_titles[:ce], zh_titles[:cz],
                                (en_counts[:ce] if en_counts else None),
                                (zh_counts[:cz] if zh_counts else None),
                                level,
                                (en_firsts[:ce] if en_firsts else None),
                                (zh_firsts[:cz] if zh_firsts else None),
                                _depth + 1)
            b = self._map_lists(en_titles[ce:], zh_titles[cz:],
                                (en_counts[ce:] if en_counts else None),
                                (zh_counts[cz:] if zh_counts else None),
                                level,
                                (en_firsts[ce:] if en_firsts else None),
                                (zh_firsts[cz:] if zh_firsts else None),
                                _depth + 1)
            if a is not None and b is not None:
                merged = list(a) + [([i + ce for i in ea], [j + cz for j in zb])
                                    for ea, zb in b]
                seen, uniq = set(), []          # 边界那对可能两半都报 → 去重
                for ea, zb in merged:
                    key = (tuple(ea), tuple(zb))
                    if key not in seen:
                        seen.add(key)
                        uniq.append((ea, zb))
                return uniq
        return None

    @staticmethod
    def _norm_map(out: list):
        """把内核的 `[[0,0],[1,null]…]` 规整成 [(en_idx[], zh_idx[])]。"""
        norm = []
        for item in out:
            if not isinstance(item, list) or len(item) != 2:
                return None
            a, b = item
            ea = [] if a is None else ([a] if isinstance(a, int) else list(a))
            zb = [] if b is None else ([b] if isinstance(b, int) else list(b))
            if any(not isinstance(x, int) for x in ea + zb):
                return None
            norm.append((ea, zb))
        return norm

    def map_sections_many(self, jobs: list[tuple[list, list]],
                          level: str = "section") -> list:
        """**并发版**：jobs = [(en_titles, zh_titles), …] → 与输入等长的结果列表。

        每项是 `[(en_idx[], zh_idx[])]` 或 `None`（该章失败）。
        几十个章一次并发跑（`LLM_WORKERS`，默认 16）—— 单章报文只有几百 token，
        串行跑是浪费；并发后墙钟 ≈ 最慢那一个。
        """
        if not jobs:
            return []
        reqs = [self._map_prompt(en, zh, level=level) for en, zh in jobs]
        raws = self.chat_many(reqs)
        out = []
        for t in raws:
            v = self._parse_json(t)
            out.append(self._norm_map(v) if isinstance(v, list) else None)
        return out

    def map_sections(self, en_titles: list[str], zh_titles: list[str],
                     en_counts: list[int] | None = None,
                     zh_counts: list[int] | None = None,
                     en_firsts: list[str] | None = None,
                     zh_firsts: list[str] | None = None):
        """章**内**小节配对（两版章节已确认对应）。返回 [(en_idx[], zh_idx[])] 或 None。"""
        return self._map_lists(en_titles, zh_titles, en_counts, zh_counts,
                               level="section",
                               en_firsts=en_firsts, zh_firsts=zh_firsts)

    def map_titles(self, en_titles: list[str], zh_titles: list[str],
                   en_counts: list[int] | None = None,
                   zh_counts: list[int] | None = None,
                   refresh: bool = False):
        """**章级**配对（两版章号体系/切分可能不同）。返回 [(en_idx[], zh_idx[])] 或 None。

        只在确定性章级映射不可信时调用 —— 输入只有几十个标题，输出只有 mapping，
        单次约 2k token，是整套 LLM 能力里最便宜的一个。
        refresh=True → 跳过缓存读强制真调（编号校验失败后的重试用）。
        """
        return self._map_lists(en_titles, zh_titles, en_counts, zh_counts,
                               level="chapter", refresh=refresh)

    # -------------------------------------------------------------- 能力 2：窗口细化
    def refine_window(self, en_lines: list[str], zh_lines: list[str],
                      locked_before: str = "", locked_after: str = ""):
        """对一小段窗口重新对齐，返回 [([en下标],[zh下标])…] 或 None。

        输出格式由 BIL_REFINE_FMT 控制（默认 json）：
        * json  —— 旧格式：[[en行号,[zh行号…]]…]（基线/缓存与其绑定）
        * range —— v3 区间行格式（token 省 5~10 倍、逐行容错、难写崩）：
            1-15:0        EN 1-15 无中文对应（0=空）
            16:27-28      EN 16 ↔ ZH 27-28（1:N）
            18,19:30      EN 18+19 ↔ ZH 30（N:1）
            21-40:31-50   两侧数量相等 → 逐段对应
          ⚠ 2026-09-14 实测：range 格式在 think2 全书回归上**变差**
          （missing 38→68），未验证通过前**默认不启用**；先在单章小样
          （prob ch2）验证后再切。
        """
        if not self.enabled:
            return None
        system = (
            "你是双语书籍段落对齐助手。给你同一小节的英文段落与中文段落"
            "（行号从 1 开始），请输出对应关系。" + ACADEMIC_NOTICE
        )
        if _REFINE_FMT == "range":
            user = (
                ("前文（已锁定，仅供参考）：\n" + locked_before + "\n\n" if locked_before else "") +
                "英文：\n" + "\n".join(f"{i+1}|{t}" for i, t in enumerate(en_lines)) +
                "\n\n中文：\n" + "\n".join(f"{j+1}|{t}" for j, t in enumerate(zh_lines)) +
                (("\n\n后文（已锁定）：\n" + locked_after) if locked_after else "") +
                "\n\n输出规则（严格遵守，每行一条，不要解释、不要代码块）：\n"
                "格式 = 英文行号:中文行号\n"
                "1. 区间用连字符（18-40），并列用逗号（18,19）。\n"
                "2. 两侧数量相等（如 21-40:31-50）= 逐段一一对应；"
                "数量不等 = 这些英文段合并对应这些中文段。\n"
                "3. 英文段没有中文对应：右边写 0（如 1-15:0）。\n"
                "4. 英文每个行号最多出现一次，按英文顺序输出；"
                "没提到的中文段 = 中文独有（不必输出）。\n"
                "5. 不要改写任何文本，只做匹配。\n"
            )
            # ⚠ 区间格式是**纯文本行**，不能走 self.json（它会当 JSON 解析，
            # 实测全部报「JSON 解析失败：1:1」）→ 必须用 chat 取原文。
            out = self.chat(system, user)
            pairs = self._parse_range_map(out, len(en_lines), len(zh_lines))
            self._trace("refine", fmt="range", n_en=len(en_lines),
                        n_zh=len(zh_lines), ok=int(bool(pairs)),
                        rules=len(pairs) if pairs else 0)
            return pairs

        user = (
            ("前文（已锁定，仅供参考）：\n" + locked_before + "\n\n" if locked_before else "") +
            "英文：\n" + "\n".join(f"{i+1}|{t}" for i, t in enumerate(en_lines)) +
            "\n\n中文：\n" + "\n".join(f"{j+1}|{t}" for j, t in enumerate(zh_lines)) +
            (("\n\n后文（已锁定）：\n" + locked_after) if locked_after else "") +
            "\n\n规则：\n"
            "1. 输出 [[en行号,...],[zh行号,...]] 的数组，行号从 1 开始。\n"
            "2. 允许 1:1、1:N（中文拆开）、N:1（中文合并）；允许中文倒装（不要求单调）。\n"
            "3. 每个英文行号、中文行号都必须恰好出现一次。\n"
            "4. 没有中文对应的英文行输出 [n,[]]；多余的中文行输出 [[],m]。\n"
            "5. 不要改写任何文本，只做匹配。只输出数组。"
        )
        out = self.json(system, user)
        pairs = None
        if isinstance(out, list):
            pairs = []
            for item in out:
                if not isinstance(item, list) or len(item) != 2:
                    pairs = None
                    break
                a, b = item
                a = [a] if isinstance(a, int) else list(a or [])
                b = [b] if isinstance(b, int) else list(b or [])
                if any(not isinstance(x, int) for x in a + b):
                    pairs = None
                    break
                pairs.append(([x - 1 for x in a], [x - 1 for x in b]))
        self._trace("refine", fmt="json", n_en=len(en_lines),
                    n_zh=len(zh_lines), ok=int(bool(pairs)),
                    rules=len(pairs) if pairs else 0)
        return pairs

    @staticmethod
    def _parse_side(s: str):
        """'1-15' / '18,19' / '0' → 行号列表；空/非法 → None。"""
        s = (s or "").strip()
        if s in ("", "无"):
            return None
        if s in ("0", "-"):
            return []
        out: list[int] = []
        for part in re.split(r"[,，]", s):
            part = part.strip()
            m = re.match(r"^(\d+)\s*[-–—~]\s*(\d+)$", part)
            if m:
                a, b = int(m.group(1)), int(m.group(2))
                if a > b:
                    return None
                out.extend(range(a, b + 1))
            elif part.isdigit():
                out.append(int(part))
            else:
                return None
        return out

    def _parse_range_map(self, txt, n_en: int, n_zh: int):
        """解析区间行格式。逐行容错：坏行跳过；整体守三条底线：
        ① EN 行**显式提及率** ≥50%（太低 = 懒输出，整窗拒收）；
        ② 空对（[]）占比 ≤60%（含按规则补的 0）；
        ③ 行号不得重复。
        触线整窗拒收（返回 None → 回退 DP），防「恒等映射+大量空对」静默进成品。

        ⚠ 2026-09-17 修（prob 2.6.4 §4-9 破案）：模型对「英文无对应」的段
        经常**整行省略**而不是按规则 3 写 0（实测 2.6.4 返回 1:1/2:2/3:3，
        脚注 4-6 不提）。旧覆盖率守卫 ≥80% 把这种**语义完全正确**的输出整窗
        拒掉 →「窗口无可用结果」。现在改为：显式提及率 ≥50% 的前提下，
        省略的英文行补成空对（=无对应），交给下游覆盖率守卫 + skew 校对把关。
        """
        if not txt or not isinstance(txt, str):
            return None
        pairs: list[tuple[list[int], list[int]]] = []
        en_seen: set[int] = set()
        zh_seen: set[int] = set()
        n_empty = 0
        for ln in txt.splitlines():
            ln = ln.strip().strip("`").strip().rstrip(",").strip()
            # 容错：模型有时无视区间格式、输出 JSON 对象（"1": "1"）——
            # 去掉引号后语义等价，照样解析（2026-09-17 实测）
            ln = ln.strip('"').strip()
            if not ln or ":" not in ln or ln.startswith(("#", "-", "输出", "格式")):
                continue
            lhs, _, rhs = ln.partition(":")
            L, R = self._parse_side(lhs), self._parse_side(rhs)
            if L is None or R is None:
                continue
            L = [x for x in L if 1 <= x <= n_en]
            R = [x for x in R if 1 <= x <= n_zh]
            if not L or any(x in en_seen for x in L):
                continue                      # 越界/重复 → 丢弃该行（逐行容错）
            en_seen.update(L)
            zh_seen.update(R)
            if not R:
                n_empty += len(L)
                pairs.append(([x - 1 for x in L], []))
                continue
            if len(L) == len(R):
                pairs.extend(([a - 1], [b - 1]) for a, b in zip(L, R))
            else:
                pairs.append(([x - 1 for x in L], [x - 1 for x in R]))
        cov = len(en_seen) / max(1, n_en)
        if cov < 0.4:                     # 显式提及率过低 = 懒输出
            # 0.40：章尾脚注多的节（1.8.2：5 正文+6 脚注）正确输出也只有
            # 5/11=45% 显式行——0.5 会把整类「尾部脚注」窗口拒掉（2026-09-17）
            return None
        # 补全：模型省略的英文行 = 判无对应（规则 3 的隐式版，2026-09-17）
        _missing = [i for i in range(1, n_en + 1) if i not in en_seen]
        n_empty += len(_missing)
        if n_empty / max(1, n_en) > 0.6:      # 空对占比（含补 0）不超六成
            return None
        pairs.extend(([i - 1], []) for i in _missing)
        return pairs

    # -------------------------------------------------------------- 能力 3：补译（两步）
    def translate(self, en_texts: list[str], context: str = "",
                  title: str = "") -> list[str] | None:
        """先直译再润色。返回与 en_texts 等长的中文列表，或 None。

        ⚠ only_mapping 模式下直接跳过：翻译是「输出大段文本」的能力，
        与「只输出 mapping 元数据」的定位相反，预算受限时第一个砍掉。
        """
        if not self.enabled or not en_texts or self.only_mapping:
            return None
        numbered = "\n".join(f"{i+1}|{t}" for i, t in enumerate(en_texts))
        system = ("你是学术著作的中文译者（英译中）。" + ACADEMIC_NOTICE)
        user1 = (
            f"书名/章节：{title}\n上下文：{context}\n\n"
            "请把下列英文段落逐段直译为简体中文（学术语体，忠实、完整）：\n"
            f"{numbered}\n\n只输出 JSON 数组：[\"译文1\",\"译文2\",...]，顺序与数量一致。"
        )
        draft = self.json(system, user1)
        if not isinstance(draft, list) or len(draft) != len(en_texts):
            return None
        user2 = (
            f"书名/章节：{title}\n\n下面是初译稿，请在不改变原意、不增删信息的前提下润色，"
            "使中文自然、学术、与前后文风格一致；保留专名与数字的原文形式：\n"
            + "\n".join(f"{i+1}|{d}" for i, d in enumerate(draft)) +
            "\n\n只输出 JSON 数组：[\"润色后1\",\"润色后2\",...]。"
        )
        polished = self.json(system, user2)
        if isinstance(polished, list) and len(polished) == len(en_texts) \
                and all(isinstance(x, str) and x.strip() for x in polished):
            return [x.strip() for x in polished]
        return [str(x).strip() for x in draft]

    def translate_many(self, groups: list[dict]) -> list[list[str] | None]:
        """并发执行多组补译（每组一段/一批），顺序与输入一致。

        每组含 en_texts / context / title / 以及 step1/step2 两段 prompt。
        两阶段都并发：先全部直译，再全部润色，避免串行等待。

        ⚠ only_mapping 模式下返回等长的 None 列表（跳过补译，保留调用方逻辑）。
        """
        if not groups:
            return []
        if not self.enabled or self.only_mapping:
            return [None] * len(groups)
        sys_t = "你是学术著作的中文译者（英译中）。" + ACADEMIC_NOTICE
        reqs1, reqs2 = [], []
        for g in groups:
            n = len(g["en_texts"])
            numbered = "\n".join(f"{i+1}|{t}"
                                 for i, t in enumerate(g["en_texts"]))
            reqs1.append((sys_t,
                          f"书名/章节：{g.get('title','')}\n"
                          f"上下文：{g.get('context','')}\n\n"
                          "请把下列英文段落逐段直译为简体中文"
                          f"（学术语体，忠实、完整）：\n{numbered}\n\n"
                          f"只输出 JSON 数组：[\"译文1\",...]，共 {n} 项。"))
            reqs2.append((sys_t, g))  # 占位，第二阶段再补内容
        drafts = self.json_many(reqs1)
        # 第二阶段：只对直译成功的组做润色
        stage2_idx, stage2_req = [], []
        for i, (g, d) in enumerate(zip(groups, drafts)):
            if not isinstance(d, list) or len(d) != len(g["en_texts"]):
                continue
            stage2_idx.append(i)
            stage2_req.append((sys_t,
                               f"书名/章节：{g.get('title','')}\n\n"
                               "下面是初译稿，请在不改变原意、不增删信息的前提下"
                               "润色，使中文自然、学术、与前后文风格一致；"
                               "保留专名与数字的原文形式：\n"
                               + "\n".join(f"{j+1}|{x}"
                                           for j, x in enumerate(d)) +
                               f"\n\n只输出 JSON 数组，共 {len(d)} 项。"))
        polished = self.json_many(stage2_req) if stage2_req else []
        pol_map = dict(zip(stage2_idx, polished))
        out = []
        for i, (g, d) in enumerate(zip(groups, drafts)):
            if not isinstance(d, list) or len(d) != len(g["en_texts"]):
                out.append(None)
                continue
            p = pol_map.get(i)
            if isinstance(p, list) and len(p) == len(d) \
                    and all(isinstance(x, str) and x.strip() for x in p):
                out.append([x.strip() for x in p])
            else:
                out.append([str(x).strip() for x in d])
        return out

    # -------------------------------------------- 能力 4：勘误打标（新增两类）
    def fix_tex(self, tex: str, err: str = "") -> str | None:
        """公式 LaTeX 语法纠错（渲染失败时的兜底；磁盘缓存命中零成本）。

        用户 2026-09-17 定调：公式有语法错误时让 LLM 校对修改，而不是
        把坏 tex 原样吐进成品。只返回**改动过**的 tex（没把握就返回 None，
        交给上层用可读占位或直接放弃）。
        """
        if not self.enabled or self.only_mapping or not (tex or "").strip():
            return None
        system = ("你是 LaTeX 公式修复助手。给定一条渲染失败的 LaTeX 公式，"
                  "只修语法（缺花括号、环境名被吃掉空格、\\left/\\right 不配对、"
                  "多余或缺失 $ 等），**不改变数学含义、不增删符号**。" +
                  ACADEMIC_NOTICE)
        user = (f"渲染错误：{err or '未知'}\n\n原公式：\n{tex}\n\n"
                "只输出修复后的 LaTeX 源码，不要解释、不要代码块标记。")
        out = (self.chat(system, user) or "").strip()
        out = out.strip("`").strip()
        if out.startswith("latex"):
            out = out[len("latex"):].strip()
        out = out.strip()
        if not out or out == (tex or "").strip() or "$" in out:
            return None
        return out

    def flag_errors(self, items: list[dict], title: str = "",
                    batch: int = 20, check_censor: bool = False) -> dict:
        """对 chapter 内的 pair 逐批打标，返回 {pair序号: 标记}。

        items: [{"i": 全局序号, "en": 英文, "zh": 中文}]，判定类型：
          * "skew"    中英**相对漂移**：这段中文是上一段/下一段英文的内容，
                      或中文在段内多出/少掉一句（边界偏移、累积错位）
          * "missing" 漏翻译：英文有整句/整段内容，中文完全没有（参考文献除外）
          * "offset"  注释对齐偏移：正文 [n] 编号与注释区条目的对应关系错了
          * "censor"  仅当 check_censor=True 才检查（默认关闭，见下）
          * "ok"      正常（**语言上的取舍算 ok**）

        ⚠ check_censor 默认 False：技术书/科普书不存在审查删改，让 LLM 判它
        只会误判（把「语言取舍导致少一句」当成审查改动）。只有涉华的国外
        史政社科书才由人开启。
        返回 {i: (标记, 说明)}；"ok" 不返回。
        """
        if not self.enabled or not items or self.only_mapping:
            return {}
        out: dict[int, tuple] = {}
        system = (
            "你是双语书籍的段落级勘误审校助手。给你同一段落的英文原文与中文译文，"
            "逐条判断是否存在下列问题（**语言上的取舍不算问题**）：\n"
            "A. skew（中英相对漂移）：这段中文明显是上一段或下一段英文的内容"
            "（段落边界整体偏移）；或中文在段内多出一句、少掉一句、重复一句，"
            "即中英的相对位置发生了漂移。\n"
            "B. missing（漏翻译）：英文的整句/整段内容在中文里完全没有出现"
            "（同一段内少了句子，不是措辞不同）。参考文献/注释条目类文本不判此条。\n"
            "C. offset（注释对齐偏移）：正文里的 [n] 注释编号与注释区第 n 条"
            "对不上（编号整体错位、或指到了别的注释内容）。\n"
        )
        if check_censor:
            system += (
                "D. censor（敏感审查改动）：**仅当**删改是「因为宗教/伦理/道德/"
                "政治等敏感内容而做的审查处理」才算。判断标准很严：必须是"
                "「内容因敏感话题被拿掉或改写」。**仅仅因为语言取舍**（省略废话、"
                "合并句子、换用成语、语体调整，且在该段上下文语境里仍保留原意）"
                "**一律不算** censor，记 ok。\n"
            ) + CENSORSHIP_NOTICE
        else:
            system += (
                "⚠ 特别注意：**不要**判定任何「内容审查/敏感内容」类问题。"
                "中文比英文短、少一句、措辞不同，只要在本段语境下仍表达原意，"
                "一律记 ok。\n"
            )
        system += "以上类型都没有 → 记 ok。"
        # 先切批，再并发发送（每批一次请求，32 线程可同时压满 RPM）
        chunks = [items[s:s + batch] for s in range(0, len(items), batch)]
        reqs = []
        for chunk in chunks:
            lines = []
            for it in chunk:
                lines.append(f"### 第 {it['i']} 条\n[EN] {it['en'][:1400]}\n"
                             f"[ZH] {(it['zh'] or '（中文版缺失）')[:1400]}")
            _kinds = ("skew / missing / offset / censor / ok。" if check_censor
                      else "skew / missing / offset / ok。")
            reqs.append((system,
                         f"书名/章节：{title}\n\n" + "\n\n".join(lines) +
                         "\n\n只输出 JSON 对象。⚠ **只列有问题的条目，"
                         "ok 的条目一律不要输出**（2026-09-17 输出压缩："
                         "整本 90% 是 ok，全量输出纯属浪费 token 和生成时间）。"
                         "值为二元素数组 [类型, 理由]，理由 ≤20 字、一句话，"
                         "类型取 " + _kinds +
                         '例如 {"12":["skew","中文是下一段的内容"],'
                         '"13":["missing","末句未译"]}。'))
        for got in self.json_many(reqs):
            if not isinstance(got, dict):
                continue
            for k, v in got.items():
                try:
                    key = int(k)
                except (TypeError, ValueError):
                    continue
                if not isinstance(v, (list, tuple)) or not v:
                    continue
                kind = str(v[0]).strip().lower()
                why = str(v[1]).strip() if len(v) > 1 else ""
                if kind in ("skew", "missing", "offset") or (
                        kind == "censor" and check_censor):
                    out[key] = (kind, why)
        self._trace("flag", n=len(items), flagged=len(out))
        return out

    # -------------------------------------------- 能力 5：审查删减内容修复
    def repair_censored(self, items: list[dict], title: str = "",
                        batch: int = 20) -> dict:
        """对被删减/改换的段落，参照英文原文补全中文，返回 {序号: 修复后中文}。

        items: [{"i": 序号, "en": 英文原文, "zh": 现译文, "why": 问题说明}]
        要求忠实原文、不删减不改词不增加不扭曲。
        """
        if not self.enabled or not items or self.only_mapping:
            return {}
        out: dict[int, str] = {}
        system = (
            "你是学术著作的中文译者与校勘者（英译中）。中文译本因内容审查"
            "删减或改换了部分内容，现在需要依据英文原文把中文补全、改回。\n"
            "铁律：忠实原文，如其所是。不删减、不改词、不增加、不扭曲；"
            "专名、数字、术语保持原文所指；只输出修复后的完整中文段落，"
            "不要输出任何说明、道歉或额外评论。" + CENSORSHIP_NOTICE
        )
        chunks = [items[s:s + batch] for s in range(0, len(items), batch)]
        reqs = []
        for chunk in chunks:
            lines = []
            for it in chunk:
                lines.append(
                    f"### 第 {it['i']} 条\n"
                    f"[英文原文] {it['en']}\n"
                    f"[现有译文] {it.get('zh') or '（缺失）'}\n"
                    f"[问题] {it.get('why') or '译文删改或缺失'}")
            reqs.append((system,
                         f"书名/章节：{title}\n\n" + "\n\n".join(lines) +
                         "\n\n请逐条输出修复后的完整中文译文，用 JSON 对象表示，"
                         '键为条号，值为译文，例如 {"12":"……","13":"……"}。'
                         "译文中如出现被审查删改的词句，必须如实补回，不得回避。"))
        for got in self.json_many(reqs):
            if not isinstance(got, dict):
                continue
            for k, v in got.items():
                try:
                    key = int(k)
                except (TypeError, ValueError):
                    continue
                if isinstance(v, str) and v.strip():
                    out[key] = v.strip()
                elif isinstance(v, (list, tuple)) and v:
                    txt = " ".join(str(x) for x in v if x)
                    if txt.strip():
                        out[key] = txt.strip()
        return out


def get_client(**kw) -> LLM:
    """按 `.env` 建客户端。`kw` 透传给 `LLM()`（如 `max_tokens=`）。"""
    return LLM(**kw)
