"""提案 A：零成本体检门禁（回填前拦截）。

指标 r = 汉字数 / 英文词数。本书（Harari 智人之上）实测全局 ~1.9，
故判定区间取 [1.0, 3.0]；小节 bad rate > 20% → FAIL → 不进入回填（降级）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import os

# 自适应区间系数（相对本节非公式段 r 中位数）：宽→误判少但漏真错，窄→反之
_RLO_K = float(os.environ.get("BIL_RLO_K", "0.45"))
_RHI_K = float(os.environ.get("BIL_RHI_K", "1.8"))

_MATHY_RE = re.compile(r"\$[^$]{2,}\$|\\[a-zA-Z]{2,}|\\frac|\\sum|\\int|\\tag")
_CODEY_RE = re.compile(r"(?:^\s*>>>|^\s*(?:import|from|def|class|plt\.|np\.|tf\.)"
                       r"|\w+\s*=\s*\w+\(|\{\s*\w+\s*:)", re.M)


def _formulaish(en_paras, zh_paras, p) -> bool:
    """该 pair 是否含公式/代码 —— 含则「汉字数/英文词数」没有意义。

    金标准校准（2026-09-16，prob ch2 手工判定 24 条）：体检判坏的 24 条里
    有 12 条是 ratio 类，其中 8 条经人审确认**配对完全正确**（中文精简 +
    公式被拆成独立块 → r 天然 < 1）。而 DP 恰恰靠合并把 r 撑进区间。
    ⇒ 这两类段必须退出 ratio 判定，否则尺子在奖励「凑长度」而不是「配得对」。
    """
    et = " ".join(en_paras[i].text for i in (p.en or []))
    zt = " ".join(zh_paras[j].text for j in (p.zh or []))

    def _h(t: str) -> bool:
        t = t or ""
        if not t:
            return False
        if sum(len(x) for x in _MATHY_RE.findall(t)) / max(1, len(t)) > 0.15:
            return True
        return bool(_CODEY_RE.search(t))

    return _h(et) or _h(zt)


@dataclass
class AuditResult:
    total: int = 0
    bad: int = 0
    only_en: int = 0
    only_zh: int = 0
    multi: int = 0
    bad_items: list = field(default_factory=list)
    rate: float = 0.0
    verdict: str = "PASS"
    # v2（2026-09-16 校准）：把「错」拆开报，别混成一个数字
    ratio_bad: int = 0        # 长度比异常（已排除公式/代码段，且按节自适应区间）
    cover_bad: int = 0        # 正文级覆盖缺口（英文有中文无 / 反之）
    struct_diff: int = 0      # 结构差异：脚注行 / 碎段 —— **不算错**，单列
    r_med: float = 0.0        # 本节非公式段的 r 中位数（自适应区间的依据）

    def as_row(self):
        return {
            "total": self.total, "bad": self.bad, "only_en": self.only_en,
            "only_zh": self.only_zh, "multi": self.multi,
            "ratio_bad": self.ratio_bad, "cover_bad": self.cover_bad,
            "struct_diff": self.struct_diff,
            "rate": round(self.rate, 3), "verdict": self.verdict,
        }


# 脚注行：`[1] xxx` / `1 xxx` / 注释区条目 —— 中文版常整体不译，属结构差异
_NOTE_LINE_RE = re.compile(r"^\s*[\[（(]?\s*\d{1,3}\s*[\]）)]?\s+\S")


def _struct_kind(t: str) -> str:
    """结构差异分类：'note'（脚注行）/ 'frag'（碎段）/ ''（正文）。"""
    t = (t or "").strip()
    if not t:
        return "frag"
    if _NOTE_LINE_RE.match(t):        # ⚠ 不设长度上限：脚注正文常 400+ 字
        return "note"
    if len(t) <= 12:                 # 「where」「最后，我们有」这类残句
        return "frag"
    return ""


def audit_pairs(pairs, en_paras, zh_paras,
                r_lo=1.0, r_hi=3.0, fail_rate=0.20,
                adaptive=True, mode: str | None = None) -> AuditResult:
    """mode="legacy" = 2026-09-16 之前的旧口径（绝对区间、公式段也判）。

    ⚠ **为什么要有 legacy**：同一把尺子既当「决策」（DP 候选 vs LLM 候选谁赢）
    又当「评价」（报告里的 bad/rate），那么**一改尺子就会悄悄改掉对齐结果本身**
    —— 实测：把尺子改成自适应后，ml 的候选比选翻了盘，pairs 287→204、
    缺中文 52→11，而抽样发现其中有过合并和脚注错配。⇒ **决策用尺必须冻结**，
    校准过的新尺子只用于评价/报告/闸门。这是本轮最重要的教训之一。
    """
    if mode is None:
        mode = "calibrated" if adaptive else "legacy"
    legacy = (mode == "legacy")
    """逐对体检。

    ⚠ 2026-09-16 金标准校准（`tests/gold/prob_ch2_pairs.md`，24 条人工判定）：
    旧的绝对区间 [1.0, 3.0] 在含公式的书上**只有 33% 的精确率** —— 中文精简 +
    公式被拆成独立块使 r 天然 < 1，而 DP 恰好靠合并把 r 撑进区间（藏分）。
    改为三条：
      ① 公式/代码段退出 ratio 判定；
      ② 区间**按本节自适应**（非公式段 r 的中位数 ×[0.45, 2.2]，上下限保底），
         因为不同书/不同节的 r 基准本来就不同；
      ③ 脚注行/碎段归入 `struct_diff`（结构差异），**不计入 bad**。
    剩余 bad = 正文级比率异常 + 正文级覆盖缺口，才是真信号。
    """
    res = AuditResult(total=len(pairs))
    if legacy:
        for idx, p in enumerate(pairs):
            kind = ""
            if not p.en or not p.zh:
                if p.en:
                    res.only_en += 1
                    kind = "only_en"
                else:
                    res.only_zh += 1
                    kind = "only_zh"
            else:
                if len(p.zh) > 1 or len(p.en) > 1:
                    res.multi += 1
                if not (r_lo <= p.r <= r_hi):
                    kind = "ratio"
                    res.ratio_bad += 1
            if kind:
                res.bad += 1
                res.bad_items.append((idx, kind, round(p.r, 2)))
        res.rate = res.bad / max(1, res.total)
        res.verdict = "FAIL" if res.rate > fail_rate else "PASS"
        return res
    # ① 先取本节非公式段 r，算中位数（自适应区间基准）
    rs = [p.r for p in pairs
          if p.en and p.zh and not _formulaish(en_paras, zh_paras, p)]
    if adaptive and len(rs) >= 5:
        rs.sort()
        res.r_med = rs[len(rs) // 2]
        # 系数可用环境变量 A/B 调（金标准在 tests/gold/prob_ch2_pairs.md）：
        # 宽 → 误判少但漏真错；窄 → 抓得全但误报多。当前取 0.5 / 1.8。
        # 下限走相对（中文精简是常态，绝对 1.0 会误杀正确配对）；
        # 上限保留 absolute 3.0 硬顶 —— 相对上限会被 r_med 抬高而漏掉
        # 「内容完全换了个话题」那种高比率真错位（金标准里的 8/14 r=3.10）。
        lo = max(0.30, _RLO_K * res.r_med)
        hi = min(r_hi, _RHI_K * res.r_med)
    else:
        lo, hi = r_lo, r_hi
    for idx, p in enumerate(pairs):
        kind = ""
        val = p.r
        if not p.en or not p.zh:
            if p.en:
                res.only_en += 1
                side = en_paras[p.en[0]].text if p.en else ""
            else:
                res.only_zh += 1
                side = ""
                try:
                    side = zh_paras[p.zh[0]].text if p.zh else ""
                except Exception:            # noqa: BLE001
                    side = ""
            sk = _struct_kind(side)
            if sk:
                res.struct_diff += 1
                kind = f"{'only_en' if p.en else 'only_zh'}:{sk}"
            else:
                res.cover_bad += 1
                kind = "only_en" if p.en else "only_zh"
        else:
            if len(p.zh) > 1 or len(p.en) > 1:
                res.multi += 1
            if _formulaish(en_paras, zh_paras, p):
                continue
            if not (lo <= p.r <= hi):
                res.ratio_bad += 1
                kind = "ratio"
        if kind:
            if kind.endswith((":note", ":frag")):
                # 结构差异：记进 bad_items 供人看，但**不计入 bad**（不是错）
                res.bad_items.append((idx, kind, round(val, 2)))
                continue
            res.bad += 1
            res.bad_items.append((idx, kind, round(val, 2)))
    res.rate = res.bad / max(1, res.total)
    res.verdict = "FAIL" if res.rate > fail_rate else "PASS"
    return res
