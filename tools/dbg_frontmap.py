# -*- coding: utf-8 -*-
"""前置/后置单元映射探针 —— 待办 §3.1 的尺子（只读、零 LLM、秒级）。

为什么需要它：§3.1 写的是「zh 前置粒度与 EN 不同」，实测**两侧都错**，且**尾部同族**：

  · EN 侧：`structure.key_of_en` 没有前置词表，只认 `_EN_HEAD_KINDS` 前缀
    → `02_half-title`、`04_copyright`、`07_fm-chapter`("Editor's foreword")、
    `08_fm-chapter1`("History") 全判 `other`，于是都进了章级位置 DP。
  · ZH 侧：`txtimport.load_md` 只在
    `is_chapter = (level <= top_level or _is_heading(title, lang))` 时开新单元，
    而 `_ZH_HEAD_RE` **缺 `编者序`**，也缺尾部 `人名索引 / 术语索引 / 符号`
    → 前置被并成「出版信息」一块（含内容提要/版权声明/编者序），
      尾部被并成「致谢」一块（含人名索引/术语索引/符号）。
  · 章级位置 DP（`_map_chapters_sequential`）**只看长度比** → 大块配大块：
    EN References(529 段) ↔ zh 附录C(1076 段)、EN Subject index ↔ zh 致谢(500 段)。

本探针把「切分」与「配对」两步并排打出来，改代码前后各跑一次即可判断有没有修好。

用法：
  _run.sh dbg_frontmap.py prob                      # 现状（改前基线）
  _run.sh dbg_frontmap.py prob --dry-fix split      # 只预演「zh 切分补词」
  _run.sh dbg_frontmap.py prob --dry-fix split+en   # 再叠加「EN 前置归类」
  _run.sh dbg_frontmap.py prob --head 12 --tail 6
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE), str(_HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import eval_align as EA                                  # noqa: E402
from bil import structure as S                            # noqa: E402
from bil import txtimport as TX                           # noqa: E402
from bil import sectmine as SM                            # noqa: E402

# 「本该独立成单元」的词表：既有切分正则 + 前后置词表 + skip 表，
# 外加 2026-09-17 实测**缺失**的几个（编者序 / 人名索引 / 术语索引 / 符号 / 后记）。
# 这里刻意写死：它就是「切分应该认得、但目前认不得」的那份名单，改完代码要能从这里消失。
_MISSING_WORDS = {"编者序", "人名索引", "术语索引", "符号", "后记", "出版信息",
                  "内容提要", "版权声明", "扉页", "书名页", "目录", "参考文献"}


def _unit_words(text: str) -> bool:
    """这个标题「看起来像」一个独立单元吗（不依赖当前切分正则）。"""
    t = (text or "").strip().rstrip(":：")
    if not t or len(t) > 80:
        return False
    low = t.lower()
    return bool(TX._is_heading(t, "zh") or TX._is_heading(t, "en")
                or low in SM.FRONT or low in SM.BACK
                or SM.SKIP.match(t) or t in _MISSING_WORDS)


def _heads(blocks) -> list[str]:
    return [b.text for b in blocks if b.type == "heading"]


def _title(blocks) -> str:
    h = _heads(blocks)
    return h[0] if h else "(无标题)"


def _dump_units(tag: str, docs: dict, keyf) -> None:
    print(f"=== {tag} 单位（{len(docs)} 个）===")
    print(f"  {'单元':26s} {'kind':9s} {'段数':>5s} {'标题数':>5s}  首个标题")
    for p, b in docs.items():
        k = keyf(b, p) if keyf is S.key_of_en else keyf(b)
        hs = _heads(b)
        print(f"  {p[:26]:26s} {k.kind:9s} {len(b):5d} {len(hs):5d}  {_title(b)[:30]}")
    print()


def _apply_dry_fix(mode: str) -> list[str]:
    """在**内存里**预演修复方案：不碰真代码、不污染真缓存、零 LLM。

    mode ∈ {"split", "split+en"}（含 "split" 即生效；"en" 为叠加项）。

    为什么要它：§3.1 的四步修复**全部会改解析切分 → `fastcache._V += 1`
    → 全书 prompt 失效**，按定调要攒到半价时段。所以先用零成本预演回答
    「改了之后映射会变成什么样、够不够」，再决定动手。

    ⚠ 两个关键点：
    1. **必须让旧解析缓存失效**，否则改了正则也读回旧结果 —— 所以内存里 `_V += 1`。
    2. **缓存目录要指到项目内 scratch**，绝不能写 `~/.cache/bil`：万一正式实现与
       预演不完全一致，同键的脏结果会被后来当成有效缓存（缓存=钱，但脏缓存更贵）。
    """
    from bil import fastcache as FC

    notes: list[str] = []
    scratch = (Path(__file__).resolve().parent.parent
               / ".workbuddy" / "tmp" / "parse_dryfix")
    FC.CACHE = scratch
    FC._V = FC._V + 1
    notes.append(f"fastcache._V {FC._V - 1} → {FC._V}（仅内存）· 解析缓存改到 {scratch}")

    # ① zh 切分：把「本该独立成单元但正则不认」的词补进 _ZH_HEAD_RE。
    #    用「在最后一个 ) 前插入」而不是重抄整条正则 —— 原正则改了也不会漂。
    #    mode 里带 editor = 只加 `编者序`（交接单 §3.1 原方案①的最小版）；
    #    mode 里带 split  = 再叠加尾部 `人名索引|术语索引|符号`（影响面更大，含内容决策）。
    words = []
    if "editor" in mode:
        words.append("编者序")
    if "split" in mode:
        words += ["人名索引", "术语索引", "符号"]
    if words:
        pat = TX._ZH_HEAD_RE.pattern
        i = pat.rindex(")")
        TX._ZH_HEAD_RE = re.compile(pat[:i] + "|" + "|".join(words) + pat[i:])
        notes.append(f"_ZH_HEAD_RE 补词: {'|'.join(words)}")

    # ② EN 前置归类：key_of_en 原来没有前置词表 → half-title/copyright 被判 other
    #    混进位置 DP。这里只补**明确该 skip**的（不动 References/Index：那是内容决策）。
    if "en" in mode:
        orig = S.key_of_en

        def _patched(blocks):                                # noqa: ANN001
            k = orig(blocks)
            if k.kind != "other":
                return k
            heads = [b.text for b in blocks if b.type == "heading"]
            h0 = (heads[0] if heads else "").strip()
            low = h0.lower()
            total = sum(len(b.text or "") for b in blocks)
            if re.match(r"^half[- ]?title|^title page|^copyright|^dedicat", low) \
                    or (not h0 and total < 900):
                return S.ChapterKey("skip", 0, h0[:40])
            if "foreword" in low or low.startswith("preface"):
                return S.ChapterKey("front", 0, h0[:40])
            return k

        S.key_of_en = _patched
        notes.append("key_of_en: half-title/title page/copyright/dedication → skip；"
                     "foreword/preface → front")

    return notes


def main() -> None:
    argv = sys.argv[1:]
    book = next((a for a in argv if not a.startswith("--")), "prob")
    head = tail = 8
    for i, a in enumerate(argv):
        if a == "--head" and i + 1 < len(argv):
            head = int(argv[i + 1])
        if a == "--tail" and i + 1 < len(argv):
            tail = int(argv[i + 1])

    mode = ""
    if "--dry-fix" in argv:
        j = argv.index("--dry-fix")
        mode = argv[j + 1] if j + 1 < len(argv) and not argv[j + 1].startswith("--") else "split"
        print("[预演模式] 只改内存，不写代码、不写真缓存\n")
        for n in _apply_dry_fix(mode):
            print(f"  · {n}")
        print()

    en_docs, zh_docs, pairs = EA.load(book)
    print(f"[书] {book} · EN {len(en_docs)} 单元 / ZH {len(zh_docs)} 单元 "
          f"/ 配对 {len(pairs)} 组\n")

    _dump_units("EN", en_docs, S.key_of_en)
    _dump_units("ZH", zh_docs, S.key_of_zh)

    def row(cp) -> str:
        return (f"  {cp.key:10s} src={getattr(cp, 'map_src', '?'):4s} "
                f"| {(cp.en_title or '∅')[:30]:30s} | {(cp.zh_title or '∅')[:24]}")

    print(f"=== 章映射 · 前 {head} 组（位置 DP 的产物）===")
    for cp in pairs[:head]:
        print(row(cp))
    print(f"\n=== 章映射 · 后 {tail} 组 ===")
    for cp in pairs[-tail:]:
        print(row(cp))
    print()

    # ── 诊断小结：直接回答「哪一步错了」 ──
    print("=== 诊断 ===")
    merged = []
    for tag, docs in (("EN", en_docs), ("ZH", zh_docs)):
        for p, b in docs.items():
            hs = _heads(b)
            if len(hs) < 2:
                continue
            # 本单元里「除首标题外还有本该独立成单元的标题」→ 切分不足。
            # 注意**不能**用「首标题不是单元词」当条件：md001 的首标题「出版信息」
            # 本身就是单元词，但它照样吞掉了 编者序 —— 漏过这种才是最要命的。
            swallowed = [h for h in hs[1:] if _unit_words(h)]
            if swallowed:
                merged.append((tag, p, hs[0], len(b), swallowed))
    if merged:
        print(f"  ⚠ {len(merged)} 个单元吞掉了本该独立的标题（**切分不足**，这就是 §3.1 的根因）：")
        for tag, p, first, n, sw in merged:
            print(f"      [{tag}] {p} 「{first}」({n} 段) 吞: {sw}")
    else:
        print("  ✅ 没有单元吞掉本该独立的标题（切分粒度已对齐）")

    en_other_front = [(p, _title(b), len(b)) for p, b in list(en_docs.items())[:9]
                      if S.key_of_en(b, p).kind == "other"]
    if en_other_front:
        print(f"  ⚠ EN 侧前置区仍有 {len(en_other_front)} 个单元判 other（该 skip/front，"
              f"会污染位置 DP）：")
        for p, t, n in en_other_front:
            print(f"      {p} 「{t}」({n} 段)")

    # ⚠ 这里只列**容器名**（被并块的首标题），不能把 编者序/致谢 这类**合法单元名**
    #   也算进来 —— 切分修好后它们会正常出现在标题位，那样就成了误报。
    container = {"出版信息", "内容提要", "版权声明", "封面", "扉页", "书名页"}
    bad = [(cp.key, cp.en_title, cp.zh_title) for cp in pairs
           if cp.en_title and cp.zh_title and cp.zh_title in container]
    if bad:
        print(f"  ⚠ {len(bad)} 组标题疑似错配（zh 侧标题取了被并块的首标题）：")
        for k, e, z in bad:
            print(f"      {k}: EN「{e}」↔ ZH「{z}」")


if __name__ == "__main__":
    main()
