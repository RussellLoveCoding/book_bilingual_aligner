"""章映射「other 桶」顺序配对的常驻回归（§6.56）。

血账：ML 全书 `diag/ml_full` 的 ch01（Preface）、ch21~24（Appendix A~D）、
ch28（Colophon）**每章都挂着同一段 O'Reilly 宣传语**「O'Reilly以分享创新知识…」，
真实中文 0 段。而 `dbg_bookscan` 报「整篇缺中文 0」—— **指标好 ≠ 内容对**。

根因（`structure.py`）：
    zh_by_key.setdefault((k.kind, k.num), p)     # 一个键只留**一个**中文文档
    zp = zh_by_key.get((k.kind, k.num), "")      # 每个英文 other 章都拿到同一个
`other` = 「认不出章号」的文档（前言 / 附录 / 版本页 / 作者介绍 …），
它们的键**全都是** `("other", 0)` → 7 个英文章全部指向中文书第一页。

修法：other 桶内按**文档出现顺序 1:1 依次配对**（文档顺序是这类文档唯一的结构
信号，符合铁律 11：用结构信号，不用词表去猜「附录」长什么样）。配不完的英文
宁可留空，也不挂错中文。

影响面：只改「章号键匹配」这一支；`_map_chapters_sequential` 的形参 `old_pairs`
从未被使用，走 seq 兜底的书（实测 prob / think2 都是 seq）不受影响。

退出码：0 = 全对；1 = 有误判。
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from bil.structure import map_chapters, key_of_en, key_of_zh   # noqa: E402


class B:
    """最小 block：structure 只用 .type / .text（短文档判定还用 len(text)）。"""

    def __init__(self, type_, text):
        self.type = type_
        self.text = text
        self.is_para = (type_ == "para")
        self.html = ""


def _doc(title, n_para=6, filler="正文"):
    """造一篇文档：1 个标题 + n_para 个长段落（总长 > 400，避免被判 skip）。"""
    bs = [B("heading", title)]
    bs += [B("para", filler * 120) for _ in range(n_para)]
    return bs


def _build():
    """英 15 篇 / 中 15 篇，other 桶两侧各 7 篇且**顺序一一对应**。

    结构照抄 ML：O'Reilly 页 + Preface + 第1~8章 + 附录A~D + Colophon。
    用 8 个章号键是为了让 `usable >= max(3, len(pairs)*0.5)` 成立 → 走 key 支。
    """
    en = {
        "ch00.xhtml": _doc("Hands-On Machine Learning with Scikit-Learn"),
        "ch01.xhtml": _doc("Preface"),
    }
    zh = {
        "z00.xhtml": _doc("O'Reilly Media，Inc. 介绍"),
        "z01.xhtml": _doc("前言"),
    }
    for i in range(1, 9):
        en[f"e{i:02d}.xhtml"] = _doc(f"Chapter {i}. Something about ML")
        zh[f"c{i:02d}.xhtml"] = _doc(f"第{i}章 关于机器学习的一些事")
    for a in "ABCD":
        en[f"ap{a}.xhtml"] = _doc(f"Appendix {a}. Some appendix title")
        zh[f"za{a}.xhtml"] = _doc(f"附录{a} 某个附录标题")
    en["col.xhtml"] = _doc("Colophon")
    zh["zau.xhtml"] = _doc("作者介绍")
    return en, zh


EN, ZH = _build()
PAIRS = map_chapters(EN, ZH)
M = {p.en_path.rsplit("/", 1)[-1]: (p.zh_path.rsplit("/", 1)[-1]
                                    if p.zh_path else "") for p in PAIRS}

fails = []


def ck(name, got, want):
    ok = (got == want)
    if not ok:
        fails.append(f"{name}: 期望 {want!r} 实得 {got!r}")
    print(f"  {'✓' if ok else '✗'} {name}: {got!r}")


print("[章映射来源]", {p.map_src for p in PAIRS})
ck("走的是 key 支（不是 seq）", {p.map_src for p in PAIRS}, {"key"})

print("\n[other 桶 —— 本次修复的核心]")
ck("O'Reilly 页 ↔ O'Reilly 介绍", M.get("ch00.xhtml"), "z00.xhtml")
ck("Preface    ↔ 前言",          M.get("ch01.xhtml"), "z01.xhtml")
ck("Appendix A ↔ 附录A",        M.get("apA.xhtml"), "zaA.xhtml")
ck("Appendix B ↔ 附录B",        M.get("apB.xhtml"), "zaB.xhtml")
ck("Appendix C ↔ 附录C",        M.get("apC.xhtml"), "zaC.xhtml")
ck("Appendix D ↔ 附录D",        M.get("apD.xhtml"), "zaD.xhtml")
ck("Colophon   ↔ 作者介绍",      M.get("col.xhtml"), "zau.xhtml")

print("\n[章号键配对不受影响]")
for i in range(1, 9):
    ck(f"Chapter {i} ↔ 第{i}章", M.get(f"e{i:02d}.xhtml"), f"c{i:02d}.xhtml")

# ── 关键回归：不许再出现「多个英文章共用一个中文文档」──────────────
print("\n[不许挤成一坨]")
seen = {}
dup = []
for p in PAIRS:
    if not p.zh_path:
        continue
    k = p.zh_path.rsplit("/", 1)[-1]
    if k in seen:
        dup.append((seen[k], p.en_path, k))
    seen[k] = p.en_path
ck("没有两个英文章共用同一篇中文", dup, [])

print("\n[英文多、中文少 → 多出来的英文留空，不挂错]")
en2 = dict(EN)
en2["extra.xhtml"] = _doc("Another unnumbered back matter")
P2 = map_chapters(en2, ZH)
M2 = {p.en_path.rsplit("/", 1)[-1]: (p.zh_path.rsplit("/", 1)[-1]
                                     if p.zh_path else "") for p in P2}
ck("多出来的英文 other 章 → 空", M2.get("extra.xhtml"), "")
ck("但它不能抢走别人的中文",     M2.get("col.xhtml"), "zau.xhtml")

print()
if fails:
    print(f"❌ {len(fails)} 项不符：")
    for f in fails:
        print("   -", f)
    sys.exit(1)
print("✅ §6.56 other 桶顺序配对：全部通过")
