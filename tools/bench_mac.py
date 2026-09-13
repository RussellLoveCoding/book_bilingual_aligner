"""在 MAC 语料上评测我们的对齐算法（对标文献数字）。

MAC（bfsujason/mac）是人工对齐的中英文学平行语料，专门用于评测句子对齐器：
Gale-Church 0.455 / Hunalign 0.607 / Bleualign 0.676 / Vecalign 0.873 /
Bertalign 0.909（link-level F1，见 aligner-eval 仓库）。

我们的对照：
  * 旧算法 = Gale-Church 一族（纯长度 + 数字锚点）
  * 新算法 = L0 锚点分段 + L1 自动对译词表（Hunalign 思路，零下载）

数据准备：把 test/tsv/*.tsv 放到 --data 目录（每行「中文<TAB>英文」）。
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bil import align as A                                          # noqa: E402
from bil.epubparse import Block                                     # noqa: E402


def load_tsv(path: Path):
    zh, en, n_null = [], [], 0
    for line in path.read_text(encoding="utf-8").split("\n"):
        if not line.strip():
            continue
        cols = line.split("\t")
        if len(cols) < 2:
            continue
        z, e = cols[0].strip(), cols[1].strip()
        if not z or not e:                    # 空单元 = 未对齐（漏译）
            n_null += 1
            continue
        zh.append(z)
        en.append(e)
    return en, zh, n_null


def links_of(pairs):
    return {(i, j) for p in pairs for i in p.en for j in p.zh}


def prf(pred, gold):
    tp = len(pred & gold)
    p = tp / max(1, len(pred))
    r = tp / max(1, len(gold))
    return p, r, 2 * p * r / max(1e-9, p + r)


def evaluate(en, zh, flags):
    A.USE_ANCHORS, A.USE_LEXICON = flags
    en_ps = [Block(text=t, type="para", html=t) for t in en]
    zh_ps = [Block(text=t, type="para", html=t) for t in zh]
    lex = None
    if flags[1]:
        first = A.align_section(en_ps, zh_ps)
        lex = A.build_lexicon(en_ps, zh_ps,
                              [p for p in first if p.en and p.zh])
    pairs = A.align_section(en_ps, zh_ps, lex=lex)
    gold = {(i, i) for i in range(min(len(en), len(zh)))}
    return prf(links_of(pairs), gold), len(pairs), len(lex or {})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=".workbuddy/tmp/align_mac")
    args = ap.parse_args()
    files = sorted(Path(args.data).glob("*.tsv"))
    if not files:
        raise SystemExit(f"{args.data} 下没有 tsv，先下载 MAC 语料")
    VARIANTS = [("旧算法（纯长度）", (False, False)),
                ("新算法（L0+L1）", (True, True)),
                ("只 L0 锚点", (True, False)),
                ("只 L1 词典", (False, True))]
    print(f"MAC 语料 {len(files)} 个文件\n")
    print(f"{'文件':<12}{'句对':>6}{'漏译行':>7}   变体")
    agg = {v[0]: [0.0, 0.0, 0.0] for v in VARIANTS}
    for f in files:
        en, zh, n_null = load_tsv(f)
        print(f"{f.stem:<12}{len(en):>6}{n_null:>7}")
        for label, flags in VARIANTS:
            (p, r, f1), npair, nlex = evaluate(en, zh, flags)
            agg[label][0] += p; agg[label][1] += r; agg[label][2] += f1
            extra = f"  词典 {nlex} 条" if flags[1] else ""
            print(f"    {label:<18} P {p:.3f}  R {r:.3f}  F1 {f1:.3f}"
                  f"  （{npair} 对）{extra}")
    n = len(files)
    print("\n=== 汇总（宏平均）===")
    print(f"{'变体':<20}{'P':>8}{'R':>8}{'F1':>8}")
    for label, _ in VARIANTS:
        p, r, f1 = agg[label]
        print(f"{label:<20}{p/n:>8.3f}{r/n:>8.3f}{f1/n:>8.3f}")
    print("\n文献参考（同一语料，link-level F1）："
          "Gale-Church 0.455 · Hunalign 0.607 · Bleualign 0.676 · "
          "Vecalign 0.873 · Bertalign 0.909")


if __name__ == "__main__":
    main()
