"""逐章比对插图顺序：中文源文档 vs 双语成品 epub。

用法（在 tools/ 下运行）：
  python check_figs.py --zh ../.workbuddy/tmp/books/think_zh.epub \
      --built "../.workbuddy/tmp/diag/think8/思考，快与慢（第二版）_双语.epub"

判定：成品里属于中文版图片集的 <img>（按章、按出现顺序）必须与
中文源各文档里的内容图（按章映射顺序）完全一致。2026-09-14
图注编号匹配修复的验收脚本（图1-1 == Image00011.jpg 之外的整体对账）。
"""
from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE), str(_HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from bil import epubparse as E
from bil import structure as S


def zh_source_figs(zh_path: str) -> list[list[str]]:
    """中文源：每个含图文档的内容图 src 列表（spine 序）。"""
    z = E.open_epub(zh_path)
    docs = S.load_docs(z, E.read_spine(z))
    out = []
    for path in docs:
        srcs = [b.src.replace("\\", "/").rsplit("/", 1)[-1]
                for b in docs[path]
                if getattr(b, "is_visual", False)
                and getattr(b, "src", "")
                and not getattr(b, "junk", False)]
        if srcs:
            out.append(srcs)
    return out


def built_fig_seqs(built_path: str, zh_images: set[str]) -> list[list[str]]:
    """成品：每个含图章里「属于中文图片集」的 img 文件名列表（spine 序）。"""
    with zipfile.ZipFile(built_path) as z:
        members = set(z.namelist())
        # 从 OPF 读 spine 书序（文件名字母序 ≠ 阅读顺序）
        opf_name = next(n for n in members if n.endswith(".opf"))
        opf = z.read(opf_name).decode("utf-8", "replace")
        opf_dir = opf_name.rsplit("/", 1)[0] + "/" if "/" in opf_name else ""
        id2href = dict(re.findall(
            r'<item\b[^>]*id="([^"]+)"[^>]*href="([^"]+)"', opf))
        spine = re.findall(r'<itemref\b[^>]*idref="([^"]+)"', opf)
        seqs = []
        for idref in spine:
            href = id2href.get(idref, "")
            if not href:
                continue
            name = (opf_dir + href).replace("\\", "/")
            if name not in members:
                # href 可能带目录前缀差异，退化为按尾名匹配
                cand = [n for n in members if n.endswith("/" + href)]
                if not cand:
                    continue
                name = cand[0]
            html = z.read(name).decode("utf-8", "replace")
            srcs = []
            for m in re.finditer(r'<img\b[^>]*src="images/([^"]+)"', html):
                base = m.group(1).split("?")[0]
                if base in zh_images:
                    srcs.append(base)
            if srcs:
                seqs.append(srcs)
        return seqs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zh", required=True)
    ap.add_argument("--built", required=True)
    args = ap.parse_args()

    # 中文图片文件全集（成品里只有它们能证明是中文侧图）
    with zipfile.ZipFile(args.zh) as z:
        zh_images = {n.rsplit("/", 1)[-1] for n in z.namelist()
                     if re.search(r"\.(jpe?g|png|gif|webp)$", n, re.I)}

    src = zh_source_figs(args.zh)
    got = built_fig_seqs(args.built, zh_images)
    print(f"中文源含图文档 {len(src)} 个；成品含中文图章 {len(got)} 个")
    ok = 0
    for i in range(max(len(src), len(got))):
        a = src[i] if i < len(src) else []
        b = got[i] if i < len(got) else []
        mark = "OK " if a == b else "✗✗ "
        if a == b:
            ok += 1
        print(f"  {mark}#{i + 1:02d} 源 {a}")
        if a != b:
            print(f"        成品 {b}")
    print(f"\n{ok}/{max(len(src), len(got))} 一致")
    sys.exit(0 if ok == max(len(src), len(got)) else 1)


if __name__ == "__main__":
    main()
