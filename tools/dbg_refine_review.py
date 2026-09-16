"""LLM 细化候选 × 语义校对：**人工审视材料**（用户 2026-09-16 要求亲自审视）。

对每个触发细化的节：
  1. 跑 _refine_windowed 拿 LLM 候选（与生产路径同一缓存）；
  2. 找出「候选 ≠ 现状」的英文段组；
  3. 对**现状**与**候选**分别调 flag_errors（语义校对，与生产同一批大小），
     打印每一条判定原话（skew/missing/offset + 说明）；
  4. 连同覆盖率、散文 bad 一起写进 markdown，供人工判断"校对得对不对"。

用法（tools/ 下）：
  _run.sh dbg_refine_review.py prob chapter6 [输出.md]
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for _p in (str(HERE), str(HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from bil import llm as L          # noqa: E402
from bil import pipeline as P     # noqa: E402
from bil import audit as AU       # noqa: E402

BOOKS = {
    "ml": ("ml_en.epub", "ml_zh.epub"),
    "prob": ("prob_en.epub", "prob_zh.md"),
    "think2": ("think2_en.epub", "think2_zh.epub"),
}
TH = 0.10          # 与 apply_llm 同闸门


def _items(s, pairs, keys):
    out = []
    for p in pairs:
        k = ",".join(map(str, p.en))
        if not (p.en and p.zh) or k not in keys:
            continue
        out.append({
            "i": k,
            "en": " ".join(s.en_paras[i].text for i in p.en)[:1200],
            "zh": " ".join(s.zh_paras[j].text for j in p.zh)[:1200],
        })
    return out


def _fmt_verdicts(got: dict, keys) -> str:
    # ⚠ flag_errors 的键是 **int(条号)**，且多段组（"12,13"）会被它丢弃——
    #   用字符串键 .get() 永远 None → 全显示成 ok（曾把 4/32 的判定全藏掉）。
    lines = []
    for k in keys:
        try:
            v = got.get(int(k))
        except ValueError:
            v = None
        if v is None:
            lines.append(f"    - `[{k}]` ok")
        elif isinstance(v, (list, tuple)) and v:
            lines.append(f"    - `[{k}]` **{v[0]}**：{v[1] if len(v) > 1 else ''}")
    return "\n".join(lines) or "    - （全部 ok）"


def main() -> None:
    book, ch = sys.argv[1], sys.argv[2]
    out_md = Path(sys.argv[3]) if len(sys.argv) > 3 else \
        HERE.parent / "diag" / f"refine_review_{book}_{ch}.md"
    en_f, zh_f = BOOKS[book]
    import run_book as RB
    llm = L.get_client()
    en_docs, zh_docs, cpairs = RB.load_all(
        HERE.parent / ".workbuddy" / "tmp" / "books" / en_f,
        HERE.parent / ".workbuddy" / "tmp" / "books" / zh_f, llm=llm)
    cp = next(c for c in cpairs if c.key == ch)
    res = P.process_chapter(en_docs[cp.en_path], zh_docs[cp.zh_path],
                            key=ch, llm=llm)

    md = [f"# LLM 细化候选审视：{book} {ch}", "",
          "> 每组只列「候选 ≠ 现状」的英文段组。"
          "校对判定来自 `llm.flag_errors`（与生产同一批大小 batch=20），"
          "判定类型：skew=中英相对漂移 · missing=漏译 · offset=注释错位。"
          "语言取舍按设计记 ok。", ""]
    n_sec = n_rej = 0
    for si, s in enumerate(res.sections):
        if not s.pairs:
            continue
        _sus, _why = P._structural_suspicion(s)
        if P._narrow_deterministic(s) and s.audit.rate <= TH:
            continue
        if P.SUSPECT_GATE and s.audit.rate <= TH and not _sus:
            continue
        if not s.zh_paras or len(s.en_paras) > 300:
            continue
        n_sec += 1
        md.append(f"## [{si}] {s.en_title or '(章首)'}  "
                  f"rate={s.audit.rate:.2f} 疑点={_why or '仅rate'}"
                  f"（EN {len(s.en_paras)} / ZH {len(s.zh_paras)}）")
        out = P._refine_windowed(llm, s)
        if not out:
            md.append("- LLM 窗口无可用结果（守卫拒收/输出为空）——"
                      "没有候选可审视。")
            md.append("")
            n_rej += 1
            continue
        cand = [P.A.Pair(en=[i], zh=list(zs)) for i, zs in out]
        for p in cand:
            P._metrics(p, s.en_paras, s.zh_paras)

        cur_map = {tuple(p.en): tuple(p.zh) for p in s.pairs}
        diff = {tuple(p.en) for p in cand
                if cur_map.get(tuple(p.en)) != tuple(p.zh)}
        keys = {",".join(map(str, e)) for e in diff}
        cov_old = sum(len(p.en) for p in s.pairs)
        cov_new = sum(len(p.en) for p in cand)

        def _prose(pairs):
            return sum(1 for p in pairs for j in p.zh
                       if not P._is_codeish(s.zh_paras[j].text))

        md.append(f"- 覆盖率：EN {cov_old}→{cov_new} · "
                  f"中文散文段 {_prose(s.pairs)}→{_prose(cand)} · "
                  f"bad {s.audit.bad}→{AU.audit_pairs(cand, s.en_paras, s.zh_paras).bad}")
        cur_items = _items(s, s.pairs, keys)
        new_items = _items(s, cand, keys)
        got_cur = llm.flag_errors(cur_items, title=s.en_title or "")
        got_new = llm.flag_errors(new_items, title=s.en_title or "")
        bad_cur = sum(1 for v in got_cur.values()
                      if isinstance(v, (list, tuple)) and v and v[0] != "ok")
        bad_new = sum(1 for v in got_new.values()
                      if isinstance(v, (list, tuple)) and v and v[0] != "ok")
        md.append(f"- **语义校对：现状 {bad_cur} 处被挑错 → 候选 {bad_new} 处**"
                  f"（校对只看这 {len(keys)} 个有分歧的组）")
        md.append("")
        by_en_cur = {it["i"]: it for it in cur_items}
        by_en_new = {it["i"]: it for it in new_items}
        # 现状覆盖：EN 下标 → 现状 pair（候选把合并对拆开时，现状显示的
        # 应该是「覆盖这些下标的那条现状对」，而不是误写成"未配对"）
        cov_cur: dict[int, object] = {}
        for p in s.pairs:
            for i in p.en:
                cov_cur[i] = p
        for k in sorted(keys, key=lambda x: [int(t) for t in x.split(",")]):
            md.append(f"### 差异组 `[{k}]`")
            itn = by_en_new.get(k)
            idxs = [int(t) for t in k.split(",")]
            pc = cov_cur.get(idxs[0])
            itc = by_en_cur.get(k)
            if itc is None and pc is not None:
                zh_cur = " ".join(s.zh_paras[j].text for j in pc.zh)[:260]
                md.append(f"- EN：{itn['en'][:220] if itn else ''}…")
                md.append(f"- **现状 ZH**（现状对 en={list(pc.en)}，"
                          f"候选把组拆/并了）：{zh_cur}…")
            else:
                md.append(f"- EN：{itc['en'][:220] if itc else (itn['en'][:220] if itn else '')}…")
                md.append(f"- **现状 ZH**：{itc['zh'][:260] if itc else '（未配对）'}…")
            md.append(f"- **候选 ZH**：{itn['zh'][:260] if itn else '（未配对）'}…")
            md.append("- 校对判定：")
            md.append(f"  - 现状：\n{_fmt_verdicts(got_cur, [k])}")
            md.append(f"  - 候选：\n{_fmt_verdicts(got_new, [k])}")
            md.append("")
        n_rej += 1
    out_md.write_text("\n".join(md), encoding="utf-8")
    print(f"审视材料已写：{out_md}（{n_sec} 个触发节，其中 {n_rej} 个有候选材料）")
    if llm is not None:
        print(llm.cost().report())
        llm.close()


if __name__ == "__main__":
    main()
