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
  _run.sh dbg_frontmap.py prob            # 默认 head/tail 各 8 对
  _run.sh dbg_frontmap.py prob --head 12 --tail 6
"""
from __future__ import annotations

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
        k = keyf(b)
        hs = _heads(b)
        print(f"  {p[:26]:26s} {k.kind:9s} {len(b):5d} {len(hs):5d}  {_title(b)[:30]}")
    print()


def main() -> None:
    argv = sys.argv[1:]
    book = next((a for a in argv if not a.startswith("--")), "prob")
    head = tail = 8
    for i, a in enumerate(argv):
        if a == "--head" and i + 1 < len(argv):
            head = int(argv[i + 1])
        if a == "--tail" and i + 1 < len(argv):
            tail = int(argv[i + 1])

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
                      if S.key_of_en(b).kind == "other"]
    if en_other_front:
        print(f"  ⚠ EN 侧前置区仍有 {len(en_other_front)} 个单元判 other（该 skip/front，"
              f"会污染位置 DP）：")
        for p, t, n in en_other_front:
            print(f"      {p} 「{t}」({n} 段)")

    bad = [(cp.key, cp.en_title, cp.zh_title) for cp in pairs
           if cp.en_title and cp.zh_title and cp.zh_title in _MISSING_WORDS]
    if bad:
        print(f"  ⚠ {len(bad)} 组标题疑似错配（zh 侧标题取了被并块的首标题）：")
        for k, e, z in bad:
            print(f"      {k}: EN「{e}」↔ ZH「{z}」")


if __name__ == "__main__":
    main()
