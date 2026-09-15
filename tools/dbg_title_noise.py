"""四源贡献分解：噪音到底出在哪一源、S4 独占的有多少。

用法：wsl.exe -- bash tools/_run.sh dbg_title_noise.py --all
零 LLM。
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE), str(_HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from bil import titlesrc as TS          # noqa: E402
from dbg_title_src import BOOKS, ROOT   # noqa: E402

NUM_RE = re.compile(r"^\s*(?:\d+(?:[.\-]\d+)+|\d+\s*[.、)]|第\s*\d+\s*章|"
                    r"(?:Chapter|Part|Appendix|App\.?)\s*[\dA-Z]|\d+)\b", re.I)


def analyze(tag: str, path: Path) -> None:
    d = TS.collect(path, prefix="X")
    rows = d["ordered"]
    combos = Counter("+".join(r["srcs"]) for r in rows)
    print(f"  {tag}　合并后 {len(rows)} 条，按来源组合：")
    for k, v in combos.most_common():
        print(f"      {k:12s} {v:>4}")

    s4only = [r for r in rows if r["srcs"] == ["S4"]]
    numbered = [r for r in s4only if NUM_RE.match(r["text"])]
    ids = {id(r) for r in numbered}
    short = [r for r in s4only if id(r) not in ids
             and len(r["text"]) <= 45
             and not r["text"].endswith((".", "。", "？", "！", "?", "!"))]
    ids |= {id(r) for r in short}
    other = [r for r in s4only if id(r) not in ids]
    print(f"      ── 仅正文(S4 独占) {len(s4only)} 条 = "
          f"带编号 {len(numbered)} + 短标题 {len(short)} + 其余 {len(other)}")
    if other:
        print("         其余样例：" + " ／ ".join(
            r["text"][:38] for r in other[:6]))
    dupes = Counter(r["text"] for r in s4only)
    rep = [(t, n) for t, n in dupes.items() if n > 1]
    if rep:
        print(f"         其中同文本重复 {len(rep)} 组，最多重复 "
              f"{max(rep, key=lambda kv: kv[1])[1]} 次")


def gates(tag: str, path: Path) -> None:
    """试算两道闸门能砍掉多少（不改数据，只报告）。

    A 重复度：同一文本出现在 ≥3 个不同文件 → 页眉/页脚（实测 nexus 有一组
      重复 21 次、ml 中文 12 次）。
    B 长句：>45 字且无编号 → 多半是正文句子被误提。
    """
    d = TS.collect(path, prefix="X")
    rows = d["ordered"]
    files: dict[str, set] = {}
    for r in rows:
        files.setdefault(r["text"], set()).add(r["file"])
    drop_a = [r for r in rows if len(files[r["text"]]) >= 3]
    ids_a = {id(r) for r in drop_a}
    rest = [r for r in rows if id(r) not in ids_a]
    drop_b = [r for r in rest
              if len(r["text"]) > 45 and not NUM_RE.match(r["text"])]
    ids_b = {id(r) for r in drop_b}
    keep = [r for r in rest if id(r) not in ids_b]
    print(f"  {tag}　{len(rows)} → 闸门A(页眉重复≥3文件) −{len(drop_a)} "
          f"→ 闸门B(长句无编号) −{len(drop_b)} → 保留 {len(keep)}")
    if drop_a:
        print("      A 丢掉的样例：" + " ／ ".join(
            f"{r['text'][:30]}×{len(files[r['text']])}" for r in drop_a[:4]))
    if drop_b:
        print("      B 丢掉的样例：" + " ／ ".join(
            r["text"][:34] for r in drop_b[:4]))


def repeats(tag: str, path: Path, top: int = 10) -> None:
    """跨文件重复的标题 = 页眉/页脚嫌疑（同一句话出现在很多个 html 里）。"""
    d = TS.collect(path, prefix="X")
    files: dict[str, set] = {}
    for r in d["ordered"]:
        files.setdefault(r["text"], set()).add(r["file"])
    rep = sorted(((len(v), t) for t, v in files.items() if len(v) >= 2),
                 reverse=True)
    total_rep = sum(n - 1 for n, _t in rep)
    print(f"  {tag}　跨文件重复的标题 {len(rep)} 个（净多余 {total_rep} 条）：")
    for n, t in rep[:top]:
        print(f"      ×{n:<3} {t[:60]}")


def doc_titles(tag: str, path: Path, top: int = 12) -> None:
    """S3（<title>）到底有没有用：看它是不是每个 html 都重复同一个书名。"""
    import zipfile
    from collections import Counter
    with zipfile.ZipFile(path) as z:
        spine = TS.E.read_spine(z)
        tt = TS.doc_titles(z, spine)
    c = Counter(tt.values())
    print(f"  {tag}　{len(spine)} 个 html，{len(tt)} 个有 <title>，"
          f"不同取值 {len(c)} 个：")
    for t, n in c.most_common(top):
        print(f"      ×{n:<3} {t[:64]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", choices=sorted(BOOKS), default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--gates", action="store_true", help="试算两道过滤闸门")
    ap.add_argument("--repeats", action="store_true", help="看跨文件重复（页眉嫌疑）")
    ap.add_argument("--doc-titles", action="store_true", help="看 <title> 一源的价值")
    args = ap.parse_args()
    keys = sorted(BOOKS) if (args.all or not args.book) else [args.book]
    if args.doc_titles:
        for k in keys:
            name, en_p, zh_p = BOOKS[k]
            print("=" * 74)
            print(f"【{k}】{name}")
            doc_titles("EN", ROOT / en_p)
            doc_titles("ZH", ROOT / zh_p)
        return 0
    if args.gates:
        for k in keys:
            name, en_p, zh_p = BOOKS[k]
            print("=" * 74)
            print(f"【{k}】{name}")
            gates("EN", ROOT / en_p)
            gates("ZH", ROOT / zh_p)
        return 0
    if args.repeats:
        for k in keys:
            name, en_p, zh_p = BOOKS[k]
            print("=" * 74)
            print(f"【{k}】{name}")
            repeats("EN", ROOT / en_p)
            repeats("ZH", ROOT / zh_p)
        return 0
    for k in keys:
        name, en_p, zh_p = BOOKS[k]
        print("=" * 74)
        print(f"【{k}】{name}")
        analyze("EN", ROOT / en_p)
        analyze("ZH", ROOT / zh_p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
