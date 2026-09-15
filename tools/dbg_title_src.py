"""四源标题提取 → 打印「准备发给 LLM 对齐」的报文（只提取，不对齐）。

用法：
  wsl.exe -- bash tools/_run.sh dbg_title_src.py --all --head 30
  wsl.exe -- bash tools/_run.sh dbg_title_src.py --book prob --head 60

产出：
  控制台 = 每本书两侧的源统计 + 报文前 N 行
  文件   = .workbuddy/tmp/title_payload/<book>.txt （完整报文，供人审）
零 LLM、零外网。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE), str(_HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from bil import titlesrc as TS          # noqa: E402

ROOT = _HERE.parent
OUT = ROOT / ".workbuddy/tmp/title_payload"

BOOKS = {
    "think2": ("思考，快与慢（第二版）",
               ".workbuddy/tmp/books/think2_en.epub",
               ".workbuddy/tmp/books/think2_zh.epub"),
    "ml": ("机器学习实战（第3版）",
           ".workbuddy/tmp/books/ml_en.epub",
           ".workbuddy/tmp/books/ml_zh.epub"),
    "prob": ("概率论沉思录",
             ".workbuddy/tmp/books/prob_en.epub",
             ".workbuddy/tmp/books/prob_zh.md"),
    "nexus": ("智人之上：从石器时代到AI时代的信息网络简史",
              ".workbuddy/tmp/books/nexus_en.epub",          # 用户提供的**原始**版
              "build/智人之上：从石器时代到AI时代的信息网络简史_中文.epub"),
}


def one(key: str, head: int, gate_a: int = 0) -> str:
    name, en_p, zh_p = BOOKS[key]
    print("=" * 78)
    print(f"【{key}】{name}" + (f"　[闸门A={gate_a}]" if gate_a else ""))
    en = TS.collect(ROOT / en_p, prefix="E", drop_repeats=gate_a)
    zh = TS.collect(ROOT / zh_p, prefix="Z", drop_repeats=gate_a)
    for tag, d in (("EN", en), ("ZH", zh)):
        st = d["stats"]
        print(f"  {tag} [{d['kind']}] {d['path'].split('/')[-1]}")
        print(f"     源：S1/S2(目录) {st.get('S1/S2', 0)} · S3(<title>) "
              f"{st.get('S3', 0)} · S4(正文) {st.get('S4', 0)}"
              f"｜CSS 类候选 {st.get('css类', 0)} → 进候选 {st.get('css候选', 0)}"
              f"，频次挡掉 {st.get('css被频次挡掉', 0)}，留下 {st.get('css反查', 0)}")
        print(f"     合并后 {st['合并后']} 条（front matter {st['front matter']}）"
              f" · 去重后 {st['去重后']} 个不同标题"
              + (f"　[闸门A丢掉 {st.get('闸门A丢掉', 0)}]"
                 if st.get("闸门A丢掉") else ""))
    payload = TS.build_payload(en, zh, name, name)
    lines = payload.splitlines()
    print(f"  ── 报文共 {len(lines)} 行 / {len(payload)} 字符"
          f"（约 {len(payload)//3} token）──")
    for ln in lines[:head]:
        print("   | " + ln)
    if len(lines) > head:
        print(f"   | …（还有 {len(lines)-head} 行，见文件）")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{key}.txt").write_text(payload, encoding="utf-8")
    return payload


def titles_file(key: str, name: str) -> Path:
    """把两侧标题按「文档顺序」和「去重·字典序」分别列全，写成可读清单。"""
    _n, en_p, zh_p = BOOKS[key]
    en = TS.collect(ROOT / en_p, prefix="E")
    zh = TS.collect(ROOT / zh_p, prefix="Z")
    out: list[str] = [f"# {name}", ""]
    for tag, src, d in (("英文", en_p, en), ("中文", zh_p, zh)):
        rows = d["ordered"]
        out.append(f"## {tag}侧 · 文档顺序（{len(rows)} 条）")
        out.append(f"　源文件：{src}")
        out.append("")
        for i, r in enumerate(rows, 1):
            mark = "  ←front" if r.get("front") else ""
            out.append(f"{i:>4}. {r['text']}{mark}")
        out.append("")
        out.append(f"## {tag}侧 · 去重后按字典序（{len(d['uniq'])} 条）")
        out.append("")
        for i, t in enumerate(d["uniq"], 1):
            out.append(f"{i:>4}. {t}")
        out.append("")
    p = OUT / f"{key}_titles.md"
    p.write_text("\n".join(out), encoding="utf-8")
    return p


TIERS = [("T1 (nav+ncx)", {"S1", "S2"}),
         ("T1+<title>", {"S1", "S2", "S3"}),
         ("全集 (含正文S4)", None)]


def tiers(key: str, gate_a: int = 0) -> None:
    """分层看规模：T1 只靠目录、T1+ 加 <title>、全集含正文。"""
    name, en_p, zh_p = BOOKS[key]
    print("=" * 78)
    print(f"【{key}】{name}")
    for label, only in TIERS:
        parts = []
        total_tok = 0
        for tag, p in (("EN", en_p), ("ZH", zh_p)):
            d = TS.collect(ROOT / p, prefix="E", only=only,
                           drop_repeats=gate_a)
            tok = len(TS.build_payload(d, d, name, name)) // 3
            total_tok += tok
            parts.append(f"{tag} {len(d['ordered']):>4}条/{tok:>5}tok")
        print(f"   {label:16s} " + "　".join(parts)
              + f"　→ 合计 ≈ {total_tok:,} tok")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", choices=sorted(BOOKS), default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--head", type=int, default=30, help="控制台打印前 N 行")
    ap.add_argument("--list", action="store_true",
                    help="只出标题清单文件（文档顺序 + 字典序）")
    ap.add_argument("--gate-a", type=int, default=0, metavar="N",
                    help="启用闸门A：同文本出现在 ≥N 个文件即判页眉（建议 3）")
    ap.add_argument("--tiers", action="store_true",
                    help="分层对比 T1 / T1+<title> / 全集的规模")
    args = ap.parse_args()
    keys = sorted(BOOKS) if (args.all or not args.book) else [args.book]
    if args.tiers:
        for k in keys:
            tiers(k, args.gate_a)
        return 0
    if args.list:
        for k in keys:
            p = titles_file(k, BOOKS[k][0])
            print(f"  {k:7s} → {p}")
        print(f"\n清单目录：{OUT}")
        return 0
    for k in keys:
        one(k, args.head, gate_a=args.gate_a)
    print(f"\n完整报文目录：{OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
