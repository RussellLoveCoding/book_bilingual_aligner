"""CSS 样式反查探针：看 epub 里到底有多少 CSS、字号分布、选出哪些候选类名。

用法：wsl.exe -- bash tools/_run.sh dbg_css.py <epub路径>
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE), str(_HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from bil import epubparse as E        # noqa: E402
from bil import titlesrc as TS        # noqa: E402


def main() -> int:
    p = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if not p or not p.exists():
        print("用法: dbg_css.py <epub路径>")
        return 2
    with zipfile.ZipFile(p) as z:
        spine = E.read_spine(z)
        man = E.read_manifest(z)
        # ⚠ E.read_manifest() 只返回**图片**项，用它找 CSS 永远是 0。
        # 这里直接扫 zip 名字表（与 titlesrc.epub_css 的做法一致）。
        css_items = [n for n in z.namelist() if n.lower().endswith(".css")]
        css = TS.epub_css(z, spine)
        print(f"[清单] zip 内 {len(z.namelist())} 个文件（其中图片项 "
              f"{len(man)}）、CSS {len(css_items)} 个：")
        for k in css_items[:10]:
            print(f"    {k}  ({len(z.read(k))}B)")
        inline = sum(len(x) for sp in spine
                     for x in __import__("re").findall(
                         r"<style[^>]*>(.*?)</style>",
                         z.read(sp).decode("utf-8", "ignore"), __import__("re").S))
        print(f"[CSS] 外链+内联合计 {len(css)} 字符（内联 <style> {inline} 字符）")

        rules = TS._RULE_RE.findall(css)
        print(f"[规则] 粗略切出 {len(rules)} 条规则")
        sizes: dict = {}
        for _sel, decl in rules:
            m = __import__("re").search(r"font-size\s*:\s*([^;]+)", decl, __import__("re").I)
            if m:
                px = TS._to_px(m.group(1))
                k = round(px * 2) / 2 if px else None
                sizes[k] = sizes.get(k, 0) + 1
        print(f"[字号] 共 {sum(sizes.values())} 条带 font-size，分布（px→条数）：")
        for k in sorted(sizes, key=lambda x: (x is None, x)):
            print(f"    {k} → {sizes[k]}")

        cand, base = TS.heading_classes_from_css(css)
        print(f"[基准] 众数字号 = {base}px")
        print(f"[候选] 命中「不像正文」的类名 {len(cand)} 个：")
        for k, why in list(cand.items())[:25]:
            print(f"    .{k}  ← {why}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
