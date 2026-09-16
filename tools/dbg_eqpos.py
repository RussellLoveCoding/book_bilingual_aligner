"""公式位置核对：**按公式编号**比原版与成品的「前面那段英文」是否一致。

用法（tools/ 下）：
  _run.sh dbg_eqpos.py prob <成品html> <原版doc>
"""
from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

BOOKS = "/mnt/c/Users/abc/WorkBuddy/2026-09-12-13-08-31/.workbuddy/tmp/books"


def _norm(s: str, n: int = 30) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = re.sub(r"\s+", " ", s).strip()
    return s[:n]


def main() -> None:
    book, built, doc = sys.argv[1], sys.argv[2], sys.argv[3]
    src = zipfile.ZipFile(f"{BOOKS}/{book}_en.epub")
    t = src.read(doc).decode("utf-8", "ignore")

    # 原版：eqn02_68 → 编号 2.68，记录它前面最近的正文段
    # ⚠ class 白名单必须含 exercise-para（Exercise 引导段是正文段）：
    #   漏了它会把 (2.67) 的「前段」错记成上一条正文 → 104/105 里唯一
    #   的"不一致"就是它（2026-09-16 实测，成品其实是对的）。
    events = []
    for m in re.finditer(r'<table[^>]*id="eqn(\d+)_(\d+)"'
                         r'|<p class="(?:para\d?|noindent\d?|list[ab]?\d?'
                         r'|exercise-para\d?)"[^>]*>(.*?)</p>', t, re.S):
        if m.group(1):
            events.append((f"{int(m.group(1))}.{int(m.group(2))}", "", ""))
        else:
            events.append(("", "", _norm(m.group(3))))
    prev, orig = "", {}
    for num, _, txt in events:
        if num:
            orig[num] = prev
        else:
            prev = txt

    h = Path(built).read_text(encoding="utf-8")
    body = h[h.index("<body"):]
    ours, cur = {}, ""
    lastnum = None
    # ⚠ 用前缀匹配：EN 段的 class 可能带后缀（如 `en en_original exercise`）
    for m in re.finditer(r'<p class="en en_original[^"]*">(.*?)</p>'
                         r'|<td class="eqno">\((\d+\.\d+)\)</td>', body, re.S):
        if m.group(2) is not None:
            ours.setdefault(m.group(2), cur)
        else:
            cur = _norm(m.group(1))

    common = [k for k in ours if k in orig]
    ok = bad = 0
    print(f"原版 {len(orig)} 条 · 成品 {len(ours)} 条 · 共有编号 {len(common)} 条")
    for k in sorted(common, key=lambda s: tuple(int(x) for x in s.split("."))):
        if ours[k][:16] == orig[k][:16]:
            ok += 1
        else:
            bad += 1
            if bad <= 10:
                print(f"  \u2717 ({k}) 成品前段: {ours[k][:40]}")
                print(f"      原版前段: {orig[k][:40]}")
    only_ours = sorted(set(ours) - set(orig))
    only_orig = sorted(set(orig) - set(ours))
    print(f"一致 {ok} · 不一致 {bad}")
    print(f"成品独有编号 {len(only_ours)}: {only_ours[:8]}")
    print(f"原版独有编号 {len(only_orig)}: {only_orig[:8]}")


if __name__ == "__main__":
    main()
