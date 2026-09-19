"""残留定位（小样本快跑）—— 2026-09-19 §6.62。

全量 60MB 跑一次要 7 分钟以上，定位残留只需要**前 N 个 pair**。
用法：python probe_inter_leftover.py [N]
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


def side_of(k):
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


def main(path, limit):
    html = open(path, encoding="utf-8").read()
    # 只取前 limit 个 pair 的**原始子串**，避免全量重排
    out, pos, n = [], 0, 0
    while n < limit:
        m = B._PAIR_OPEN_RE.search(html, pos)
        if not m:
            break
        depth, i = 1, m.end()
        for t in re.finditer(r"<(/?)div\b[^>]*>", html[m.end():], re.I):
            depth += -1 if t.group(1) else 1
            if depth == 0:
                i = m.end() + t.start()
                break
        out.append(html[m.end():i])
        pos = i + len("</div>")
        n += 1
    print(f"采样 {len(out)} 个 pair（前 {limit}）")

    bad = 0
    for idx, inner in enumerate(out):
        kids = split_top(inner)
        if not any(side_of(k) == "OTHER" for k in kids):
            continue
        new_kids = split_top(B._inject_zh(kids))
        toks = [side_of(k) for k in new_kids]
        oi = [i for i, t in enumerate(toks) if t == "OTHER"]
        zi = [i for i, t in enumerate(toks) if t == "ZH"]
        if not zi or all(i > max(zi) for i in oi):
            continue
        bad += 1
        if bad <= 6:
            print(f"\n--- pair #{idx} 残留 ---")
            print(f"  原始: {' '.join(side_of(k) for k in kids)}")
            print(f"  重排: {' '.join(toks)}")
            for k in new_kids:
                txt = re.sub(r"<[^>]+>", "", k)
                txt = re.sub(r"\s+", " ", txt).strip()[:56]
                head = re.match(r"<([a-zA-Z][\w:-]*)", k)
                cm = re.search(r'class="([^"]*)"', k)
                print(f"     [{side_of(k):5s}] <{head.group(1) if head else '?'}"
                      f" class=\"{cm.group(1) if cm else ''}\"> {txt}")
    print(f"\n采样内残留 {bad} 个")


if __name__ == "__main__":
    lim = int(sys.argv[2]) if len(sys.argv) > 2 else 600
    if len(sys.argv) > 1:
        tgt = sys.argv[1]
    else:
        cand = glob.glob("../diag/*_uni/*.html") + glob.glob("diag/*_uni/*.html")
        cand = [c for c in cand if "ml_full" in c] or cand
        tgt = cand[0]
    main(tgt, lim)
