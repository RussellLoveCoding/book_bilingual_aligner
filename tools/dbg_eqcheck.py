"""成品公式验收：张数守恒 / 编号唯一 / 无冒名图 / 引用不死链。

用法（tools/ 下）：
  _run.sh dbg_eqcheck.py <成品html或epub内的xhtml> [英文原版doc路径]

判定（HANDOFF §2.6 的验收口径）：
  张数 == 不同编号数（一个编号只出一张表）
  无重复编号
  公式表里的图全部来自英文原版（eqn*/equ*，没有装饰线/自渲染混入）
  正文 `(2.x)` 引用的锚点都有落地 id
"""
from __future__ import annotations

import re
import sys
import html as _html
from collections import Counter
from pathlib import Path


def _load(p: Path) -> str:
    if p.suffix.lower() == ".epub":
        import zipfile
        z = zipfile.ZipFile(p)
        doc = sys.argv[2] if len(sys.argv) > 2 else ""
        if not doc:
            docs = [n for n in z.namelist() if n.endswith((".xhtml", ".html"))]
            doc = max(docs, key=lambda n: z.getinfo(n).file_size)
            print(f"[提示] 未给 doc 路径，取最大的：{doc}")
        return z.read(doc).decode("utf-8", "ignore")
    h = p.read_text(encoding="utf-8")
    return h[h.index("<body"):] if "<body" in h else h


def main() -> None:
    body = _load(Path(sys.argv[1]))
    labs = re.findall(r'<td class="eqno">\(([^)]+)\)</td>', body)
    cnt = Counter(labs)
    dup = {k: v for k, v in cnt.items() if v > 1}
    ok = len(labs) == len(cnt)

    imgs = re.findall(
        r'<table class="eqtable".*?<img class="eqimg" src="([^"]+)"',
        body, re.S)
    # HTML 预览是内联 data URI（同一张原版图），不算"非原版"；epub 里才是路径
    foreign = [s for s in set(imgs)
               if not s.startswith("data:")
               and not re.search(r"(?:eqn|equ)[\w-]*\.(?:jpe?g|png)$", s, re.I)]

    hrefs = set(re.findall(r'href="[^"]*#(eq-[0-9a-f]+)"', body))
    ids = set(re.findall(r'id="(eq-[0-9a-f]+)"', body))
    dead = hrefs - ids

    print(f"编号公式表 {len(labs)} 张 · 不同编号 {len(cnt)} 个 "
          f"· {'✅ 张数守恒' if ok else f'⚠ 多 {len(labs) - len(cnt)} 张'}")
    print(f"重复编号 {len(dup)} 个 {'✅' if not dup else dup}")
    print(f"公式表里的非原版图 {len(foreign)} 张 "
          f"{'✅' if not foreign else foreign[:6]}")
    print(f"正文引用锚点 {len(hrefs)} 个 · 死链 {len(dead)} 个 "
          f"{'✅' if not dead else sorted(dead)[:6]}")
    sys.exit(0 if (ok and not dup and not foreign and not dead) else 1)


if __name__ == "__main__":
    _html  # noqa: B018  (保留 import：个别成品里实体需人工看)
    main()
