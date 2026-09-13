"""对齐鲁棒性基准：拿真实中英段落对做基料，施加已知扰动后比对新旧算法。

为什么要这样测：本书本身是「忠实译本」，新旧算法都能对上，区分不出高下。
真正困难的是译本**删段、并段、调序**的场景 —— 这里用真实文本 + 人工扰动
造出这些场景，金标准完全可控（扰动是我们自己做的，对应关系精确已知）。

用法：
    python tools/bench_align.py                 # 用 build/ 里的双语 epub
    python tools/bench_align.py --chapter ch10  # 指定章节
"""
import argparse
import html as _html
import random
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bil import align as A                                          # noqa: E402
from bil.epubparse import Block                                     # noqa: E402

PAIR_RE = re.compile(r'<div class="pair">(.*?)</div>', re.S)
EN_RE = re.compile(r'<p class="en">(.*?)</p>', re.S)
ZH_RE = re.compile(r'<p class="zh">(.*?)</p>', re.S)


def strip(s: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", "", s))).strip()


def load_pairs(epub: Path, chapter: str, limit: int = 200) -> list:
    """从成品 epub 里抽出真实的中英段落对（只跳过缺中文的段）。"""
    z = zipfile.ZipFile(epub)
    name = f"OEBPS/{chapter}.xhtml"
    if name not in z.namelist():
        raise SystemExit(f"包里没有 {name}")
    text = z.read(name).decode("utf-8")
    out = []
    for body in PAIR_RE.findall(text):
        em, zm = EN_RE.search(body), ZH_RE.search(body)
        if not em or not zm or 'class="zh miss"' in body:
            continue
        en, zh = strip(em.group(1)), strip(zm.group(1))
        if len(en) < 40 or len(zh) < 20:
            continue
        out.append((en, zh))
        if len(out) >= limit:
            break
    return out


def perturb(pairs: list, rng: random.Random):
    """对中文侧做删/并/调序扰动，返回 (en_texts, zh_texts, gold_links)。

    gold_links = {(en_idx, zh_idx)}，是扰动后真实成立的对应关系。
    """
    keep = list(range(len(pairs)))
    # 1) 删掉 3 段中文（模拟审查删改）
    for i in rng.sample(keep, 3):
        pairs[i] = (pairs[i][0], None)
    # 2) 把 2 组合并的中文合成一段（模拟译者并段）
    merged_at = []
    for _ in range(2):
        i = rng.randrange(0, len(pairs) - 1)
        if pairs[i][1] and pairs[i + 1][1]:
            pairs[i] = (pairs[i][0], pairs[i][1] + pairs[i + 1][1])
            pairs[i + 1] = (pairs[i + 1][0], None)
            merged_at.append(i)
    # 3) 调换相邻两段中文的顺序（模拟译文顺序漂移）
    swap_at = rng.randrange(0, len(pairs) - 2)
    if pairs[swap_at][1] and pairs[swap_at + 1][1]:
        a, b = pairs[swap_at], pairs[swap_at + 1]
        pairs[swap_at] = (a[0], b[1])
        pairs[swap_at + 1] = (b[0], a[1])

    en_texts = [p[0] for p in pairs]
    zh_texts, zh_of = [], {}
    for i, (_, zt) in enumerate(pairs):
        if zt is None:
            continue
        zh_of[i] = len(zh_texts)
        zh_texts.append(zt)
    gold = {(i, zh_of[i]) for i in range(len(pairs)) if i in zh_of}
    return en_texts, zh_texts, gold, merged_at


def score(pred_pairs, gold: set) -> tuple:
    links = set()
    for p in pred_pairs:
        for i in p.en:
            for j in p.zh:
                links.add((i, j))
    tp = len(links & gold)
    prec = tp / max(1, len(links))
    rec = tp / max(1, len(gold))
    f1 = 2 * prec * rec / max(1e-9, prec + rec)
    sil = len({ij for ij in links - gold})            # 错配（两边都非空）
    return prec, rec, f1, sil


def run_case(pairs, seed: int, flags: tuple) -> tuple:
    """flags = (用锚点, 用词典)。词典按真实流程两遍构建：先粗对齐再统计。"""
    A.USE_ANCHORS, A.USE_LEXICON = flags
    rng = random.Random(seed)
    en_t, zh_t, gold, _ = perturb([list(p) for p in pairs], rng)
    en_ps = [Block(text=t, type="para", html=t) for t in en_t]
    zh_ps = [Block(text=t, type="para", html=t) for t in zh_t]
    lex = None
    if flags[1]:
        first = A.align_section(en_ps, zh_ps)
        lex = A.build_lexicon(en_ps, zh_ps,
                              [p for p in first if p.en and p.zh])
    pairs_out = A.align_section(en_ps, zh_ps, lex=lex)
    return score(pairs_out, gold)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epub", default=None)
    ap.add_argument("--chapter", default="ch10")
    ap.add_argument("--seeds", type=int, default=8)
    args = ap.parse_args()

    if args.epub:
        epub = Path(args.epub)
    else:
        # build/ 下可能有多个产物（用户手跑的小样本等），挑真正含目标章节的
        cands = [p for p in sorted(Path("build").glob("*_双语.epub"))
                 if f"OEBPS/{args.chapter}.xhtml"
                 in zipfile.ZipFile(p).namelist()]
        if not cands:
            raise SystemExit("找不到含该章节的成品 epub，先跑一次 --build")
        epub = max(cands, key=lambda p: p.stat().st_size)
    sample = load_pairs(epub, args.chapter)
    print(f"基料：{epub.name} · {args.chapter} · 真实段落对 {len(sample)}")
    print(f"{'情形':<26}{'P':>7}{'R':>7}{'F1':>7}{'错配':>7}")
    cases = [("旧算法（纯长度）", (False, False)),
             ("新算法（+L1 词典，默认）", (False, True)),
             ("再叠加 L0 软锚点（实验）", (True, True)),
             ("只 L0 软锚点（实验）", (True, False))]
    for label, flags in cases:
        agg = [0.0, 0.0, 0.0, 0]
        for seed in range(args.seeds):
            p, r, f, sil = run_case(sample, seed, flags)
            agg[0] += p; agg[1] += r; agg[2] += f; agg[3] += sil
        n = args.seeds
        print(f"{label:<26}{agg[0]/n:>7.3f}{agg[1]/n:>7.3f}"
              f"{agg[2]/n:>7.3f}{agg[3]/n:>7.1f}")


if __name__ == "__main__":
    main()
