"""文本成品：txt / md 输入对应的 txt / md 输出（中英对照）。

为什么要有它（用户 2026-09-14 定策）：输入是 txt/md 时不该强制出 epub ——
格式随输入。txt 材料的读者要的是**可复制、可搜索的对照文本**，不是电子书。

产出结构（md 风格标题在纯文本里同样可读，故 txt/md 共用一套）：

    # 书名

    ## 第1章 故事中的角色 · The Characters of the Story

    ### 源起 · ORIGINS

    In rough order of complexity, here are some examples ...

    以下是系统1自动运作的例子（大致按复杂程度排序）：

    > 【图】图29-1

    ## 注释 / Notes

    1. 注释正文 …

约定：
* 一段英文紧跟它的中文译文，段间空行 —— 便于逐段对照与检索；
* 图位渲染成引用行「> 【图】图注」（文本装不下图片，保留图注位置）；
* AI 补译段加「【AI译】」前缀，审查修复段加「【审修】」前缀（都与 epub 一致）；
* 禁止翻译的段（参考文献 / 纯符号）只出英文，不重复输出中文（同 epub 决策）。
"""
from __future__ import annotations

import re
from pathlib import Path

from . import epubparse as E


def _one_line(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _head(level: int, *parts: str) -> str:
    txt = " · ".join(p for p in (_one_line(p) for p in parts) if p)
    return f"{'#' * level} {txt}" if txt else ""


def render(results, title: str = "", notes: bool = True) -> str:
    """ChapterResult 列表 → 中英对照文本。"""
    out: list[str] = []
    if title:
        out.append(_head(1, title))
    for res in results:
        heads = list(getattr(res, "en_heads", None) or [])
        en_t = (res.en_title or (heads[-1] if heads else "") or "").strip()
        ch = _head(2, getattr(res, "zh_title", "") or en_t,
                   en_t if getattr(res, "zh_title", "") else "")
        if ch:
            out.append(ch)
        for sec in res.sections:
            st = _head(3, sec.zh_title, sec.en_title)
            if st:
                out.append(st)
            # 图位按 anchor 落回段落之间（同 epub 的决策，只是渲染成图注行）
            figs: dict[int, list] = {}
            for f in (getattr(sec, "figures", None) or []):
                figs.setdefault(f.after, []).append(f)

            def _figs_at(key: int):
                for f in figs.get(key, []):
                    cap = _one_line(f.caption_zh or f.caption_en
                                    or getattr(f, "caption_mt", ""))
                    if cap:
                        out.append(f"> 【图】{cap}")

            _figs_at(-1)
            for pi, p in enumerate(sec.pairs):
                if p.en:
                    en = _one_line(" ".join(sec.en_paras[x].text
                                           for x in p.en))
                    if en:
                        out.append(en)
                _zh_block(out, sec, p)
                _figs_at(pi)
            for k in sorted(figs):           # 锚点越界的图（挂小节末尾）
                if k >= len(sec.pairs):
                    _figs_at(k)
        if notes and getattr(res, "notes", None):
            out.append(_head(3, "注释 / Notes"))
            for n, blk in enumerate(res.notes, 1):
                t = _one_line(re.sub(r"<[^>]+>", "", blk.html or ""))
                if t:
                    out.append(f"{n}. {t}")
    # 折叠多余空行
    txt = "\n\n".join(x for x in out if x.strip())
    return re.sub(r"\n{3,}", "\n\n", txt).strip() + "\n"


def _zh_block(out: list[str], sec, p) -> None:
    """中文侧：修复稿 > AI 补译 > 原译文；禁止翻译的段整段跳过。"""
    if getattr(p, "censored", False) and p.zh_fix:
        out.append(f"【审修】{_one_line(p.zh_fix)}")
        return
    if p.zh:
        en_t = " ".join(sec.en_paras[x].text for x in p.en) if p.en else ""
        if en_t and E.no_translate_reason(en_t):
            return                       # 参考文献/纯符号：只留英文，不重复
        zh = _one_line(" ".join(sec.zh_paras[x].text for x in p.zh))
        if zh:
            out.append(zh)
        return
    if p.mt:
        out.append(f"【AI译】{_one_line(p.mt)}")


def write_text(results, path: Path, title: str = "",
               notes: bool = True) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(results, title=title, notes=notes),
                    encoding="utf-8")
    return path
