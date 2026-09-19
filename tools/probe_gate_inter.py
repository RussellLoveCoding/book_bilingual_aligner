"""成品产物落位快检：数「行间元素排在中文之前」的 pair —— §6.62 验收尺。

⚠ 与 `probe_inter_ab.py` 的区别：那个做**重排前/后**对照（读旧产物）；
这个只**体检已重排过的产物**，用于构建后验收。线性单遍，快。
"""
import os
import re
import sys
import glob

sys.stdout.reconfigure(encoding="utf-8")
os.environ["BIL_ARCH"] = "unified"
sys.path.insert(0, os.path.dirname(__file__))
import bil.build as B  # noqa: E402

VOID = {"img", "br", "hr", "meta", "link", "input", "col"}


def split_top(inner):
    out, depth, start = [], 0, None
    for m in re.finditer(r"<(/)?([a-zA-Z][\w:-]*)([^>]*?)(/?)>", inner):
        tag = m.group(2).lower()
        closing, sc = bool(m.group(1)), bool(m.group(4))
        if closing:
            depth -= 1
            if depth == 0 and start is not None:
                out.append(inner[start:m.end()])
                start = None
            continue
        if tag in VOID or sc:
            if depth == 0:
                out.append(m.group(0))
            continue
        if depth == 0:
            start = m.start()
        depth += 1
    if start is not None:
        out.append(inner[start:])
    return [s for s in out if s.strip()]


def side(k):
    cm = re.search(r'class="([^"]*)"', k)
    cs = (cm.group(1) if cm else "").split()
    if re.match(r"<h6\b", k) and "box-label" in cs:
        return "LABEL"
    if "zh" in cs:
        return "ZH"
    if B._is_inter(k) and "zh" not in cs:
        return "OTHER"
    if "en" in cs:
        return "EN"
    return "OTHER"


def check(path: str) -> dict:
    html = open(path, encoding="utf-8").read()
    stat = {"✓ 行间元素在中文之后": 0, "× 行间元素在中文之前": 0,
            "无中文（代码块等）": 0, "无行间元素": 0,
            "✓ 代码块有高亮CSS": int("pre code.kn" in html)}
    bad = []
    for m in re.finditer(r'<div class="pair">(.*?)</div>(?=\s*<)', html, re.S):
        kids = split_top(m.group(1))
        toks = [side(k) for k in kids]
        if "OTHER" not in toks:
            stat["无行间元素"] += 1
            continue
        zi = [i for i, t in enumerate(toks) if t == "ZH"]
        if not zi:
            stat["无中文（代码块等）"] += 1
            continue
        oi = [i for i, t in enumerate(toks) if t == "OTHER"]
        if all(i > max(zi) for i in oi):
            stat["✓ 行间元素在中文之后"] += 1
        else:
            stat["× 行间元素在中文之前"] += 1
            if len(bad) < 3:
                bad.append(" ".join(toks))
    return stat, bad


if __name__ == "__main__":
    paths = sys.argv[1:] or [
        p for p in glob.glob("../diag/*_v62/*.html") + glob.glob("diag/*_v62/*.html")]
    for p in paths:
        st, bad = check(p)
        print(f"\n=== {os.path.basename(p)[:60]} ===")
        for k, v in st.items():
            print(f"  {k:26s}: {v}")
        for b in bad:
            print(f"    残留形态: {b}")
