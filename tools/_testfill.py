import sys
sys.path.insert(0, "/mnt/c/Users/abc/WorkBuddy/2026-09-12-13-08-31/tools")
from bil.pipeline import _too_short_to_translate as F
CASES = [
    # (英文, 期望跳过?)
    ("and in", True),                 # ★ 截图幻觉源
    ("or", True), ("and", True), ("where", True), ("with", True),
    ("Likewise,", True), ("Now,", True), ("Then", True),
    ("psychology", True),
    ("The proposition", True),
    # 索引条目 → 必须豁免（不跳过）
    ("Aristotle, 4", False),
    ("admissibility, 408", False),
    ("a-priori probabilities, 87", False),
    ("adequate sets, 13, 34, 35, 652", False),
    # 3+ 词 → 不跳过
    ("is equal to", False),
    ("Or, equally well,", False),
    ("For then we have", False),
    ("This is a full sentence.", False),
]
ok = True
for t, want in CASES:
    got = F(t); hit = (got == want); ok &= hit
    print(f"  {'OK ' if hit else 'XX '} {t!r:<36} 跳过={got!s:<6} 期望={want}")
print()
print("✅ 全部符合预期" if ok else "★ 有不符")
