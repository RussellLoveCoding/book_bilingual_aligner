"""逐文档打印 epub 里挖到的标题（真实 h1-h6 + class 类标题）。

用法：
  wsl.exe -- bash tools/_run.sh dbg_html_heads.py <epub> [文件名过滤] [打印条数]
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent))

from bil import epubparse as E          # noqa: E402


def main() -> int:
    p = Path(sys.argv[1])
    filt = sys.argv[2] if len(sys.argv) > 2 else ""
    top = int(sys.argv[3]) if len(sys.argv) > 3 else 8
    with zipfile.ZipFile(p) as z:
        spine = E.read_spine(z)
        if filt:
            spine = [s for s in spine if filt in s]
        print(f"{p.name}　spine {len(spine)} 个文档"
              + (f"（过滤 '{filt}'）" if filt else ""))
        tot = 0
        for sp in spine:
            try:
                blocks = E.read_doc(z, sp)
            except Exception as e:                            # noqa: BLE001
                print(f"  [跳过] {sp}: {e}")
                continue
            hs = [b for b in blocks if b.type == "heading"]
            if not hs:
                continue
            tot += len(hs)
            print(f"\n  ── {sp.split('/')[-1]}　({len(blocks)} 块，标题 {len(hs)})")
            for b in hs[:top]:
                tag = getattr(b, "tag", "") or ""
                cls = getattr(b, "cls", "") or ""
                print(f"     L{b.level or 1}  <{tag} class='{cls}'>  "
                      f"{(b.text or '')[:70]}")
            if len(hs) > top:
                print(f"     … 另有 {len(hs)-top} 条")
        print(f"\n合计挖到标题 {tot} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
