"""核对英中两侧 heading 下标计数 —— §6.66。

背景：`pipeline.py:2746-2764` 用 `_off + _n` 记标题位置，
计数器**只跳过 `is_visual` 块**。而 `Block.is_visual` 只含
`figure / image / table / formula` —— **不含 `code`**。

若某侧有代码块而另一侧没有（中译本常把代码块内容删掉或合并），
两侧的 `_off + _n` 就会**整体偏移**，导致「小节标题挂错 pair」
（§6.60 与 ch4 §3.3 的 4 连漂移疑似同源）。

用法: python probe_head_idx.py <en.epub> <zh.epub> --doc ch4
"""
import os
import re
import sys
import zipfile
import argparse

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(__file__))


def dump(path, label, doc_filter):
    from bil import epubparse as EP
    print("#" * 80)
    print(f"# {label}  {os.path.basename(path)}")
    print("#" * 80)
    with zipfile.ZipFile(path) as z:
        spine = EP.read_spine(z)
        hits = 0
        for sp in spine:
            if doc_filter and doc_filter not in sp:
                continue
            try:
                blocks = EP.read_doc(z, sp, strict=False)
            except Exception as e:
                print(f"  [{sp}] 读取失败: {e}")
                continue
            hits += 1
            print(f"\n--- {sp}  ({len(blocks)} 块) ---")
            n = 0
            for b in blocks:
                vis = bool(getattr(b, "is_visual", False))
                idx = "-" if vis else str(n)
                if not vis:
                    n += 1
                txt = re.sub(r"\s+", " ", (getattr(b, "text", "") or ""))[:58]
                mark = "  ←HEADING" if b.type == "heading" else ""
                print(f"   [{idx:>3s}]{'V' if vis else ' '} {b.type:9s} | {txt}{mark}")
            if hits >= 3:
                break
        if hits == 0:
            print(f"  （没有文件名含 {doc_filter!r} 的文档）")
            print("  spine 前 12 项:")
            for sp in spine[:12]:
                print("    ", sp)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("en")
    ap.add_argument("zh")
    ap.add_argument("--doc", default="ch4")
    args = ap.parse_args()
    dump(args.en, "EN", args.doc)
    print()
    dump(args.zh, "ZH", args.doc)
