"""英中块序列并排对比 —— §6.66。

把某一章（英文文档 X ↔ 中文文档 Y）两侧的块序列按**下标**并排打印，
标出类型/下标不一致的位置，用于定位「标题挂错 pair」的偏移点。

用法: python probe_align_side.py <en.epub> <en_doc> <zh.epub> <zh_doc> [--from N --to M]
"""
import os
import re
import sys
import zipfile
import argparse

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(__file__))


def blocks_of(path, doc):
    from bil import epubparse as EP
    with zipfile.ZipFile(path) as z:
        for sp in EP.read_spine(z):
            if doc not in sp:
                continue
            return EP.read_doc(z, sp, strict=False), sp
    return None, None


def index_blocks(blocks):
    """返回 [(n, type, is_visual, text, is_heading)]，n = 非视觉块累计下标。"""
    out, n = [], 0
    for b in blocks:
        vis = bool(getattr(b, "is_visual", False))
        idx = None if vis else n
        if not vis:
            n += 1
        out.append((idx, b.type, vis,
                    re.sub(r"\s+", " ", getattr(b, "text", "") or "")[:52],
                    b.type == "heading"))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("en")
    ap.add_argument("en_doc")
    ap.add_argument("zh")
    ap.add_argument("zh_doc")
    ap.add_argument("--from", dest="frm", type=int, default=0)
    ap.add_argument("--to", dest="to", type=int, default=200)
    args = ap.parse_args()

    eb, epsp = blocks_of(args.en, args.en_doc)
    zb, zpsp = blocks_of(args.zh, args.zh_doc)
    print(f"EN doc: {epsp}  ({len(eb)} 块)")
    print(f"ZH doc: {zpsp}  ({len(zb)} 块)")
    ei = index_blocks(eb)
    zi = index_blocks(zb)

    # 只看非视觉块的并排
    enp = [x for x in ei if x[0] is not None]
    zhp = [x for x in zi if x[0] is not None]
    print(f"EN 非视觉块 {len(enp)} · ZH 非视觉块 {len(zhp)}\n")

    print(f"{'n':>4} | {'EN':<56} | {'ZH':<56}")
    print("-" * 124)
    for k in range(args.frm, min(args.to, max(len(enp), len(zhp)))):
        e = enp[k] if k < len(enp) else (None, "", False, "", False)
        z = zhp[k] if k < len(zhp) else (None, "", False, "", False)
        em = "H" if e[4] else " "
        zm = "H" if z[4] else " "
        flag = ""
        if e[1] and z[1]:
            if e[4] != z[4]:
                flag = "  ⚠标题侧不一致"
            elif e[1] != z[1] and not (e[4] and z[4]):
                flag = f"  ⚠类型 {e[1]}≠{z[1]}"
        print(f"{k:>4} |{em}{e[1]:<8}{e[3]:<47} |{zm}{z[1]:<8}{z[3]:<47}{flag}")


if __name__ == "__main__":
    main()
