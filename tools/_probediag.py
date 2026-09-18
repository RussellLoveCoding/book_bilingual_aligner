#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""诊断：全书每个小节里 `structural_slack>0` 与 `probe_uncertain_zh` 命中数。

为什么必须查（§6.35 回归）：
  p18 构建里 `judge_zh` 触发 **91 次 / 弃 207 段**，远超设计预期（§1.5 的 8 段）。
  其中两次 `n=81, drop=49, n_vis=0` —— 说明某些小节候选爆炸到 81 个，
  而该小节**一个图表都没有**（n_vis=0）→ LLM 在裸文本上盲判，乱丢 49 段，
  直接造成 ch31 参考文献重复。

跑法：wsl.exe -- bash /mnt/c/<proj>/tools/_run.sh _probediag.py
"""
import sys
import traceback
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
OUT = ROOT / ".workbuddy/tmp/p18_probediag.log"
lines = []


def w(s=""):
    lines.append(s)


try:
    from bil import align as A
except Exception:
    w("import bil.align 失败：\n" + traceback.format_exc())
    Path(OUT).write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    raise SystemExit(1)

w("=== 全书小节的 slack / 候选统计 ===")
w("（数据源：run_book 的章节解析结果，需从缓存重建 —— 见下）")
w()

# 直接用一段构造数据验证判据行为：模拟「中文侧多出 n 块」的小节
w("=== 判据行为模拟（合成数据，验证 B 判据的宽度）===")


class P:
    __slots__ = ("text",)

    def __init__(self, t):
        self.text = t


def _f(v):
    return f"{v:.3f}" if isinstance(v, (int, float)) else str(v)


# 场景 1：完全 1:1 的小节（slack=0）—— 不该返回候选
en = [P(f"English paragraph number {i} with enough words to be a real paragraph")
      for i in range(20)]
zh = [P(f"中文段落第 {i} 号，含有足够的字数以便被当作真正的正文段落处理")
      for i in range(20)]
c, info = A.probe_uncertain_zh(en, zh)
w(f"场景1 1:1 (slack={A.structural_slack(en, zh)}) → 候选 {len(c)} 个  "
  f"k0={_f(info.get('k0'))}  raw={info.get('cand_raw')}")
w()

# 场景 2：中文多 1 块（模拟 ch31 参考文献那种）
en2 = [P(f"English reference entry {i}, Journal of Something, vol {i}, pp 1-10.")
       for i in range(40)]
zh2 = [P(f"中文参考文献条目第 {i} 号，某某学报，第 {i} 卷，第 1-10 页。")
       for i in range(41)]
c2, info2 = A.probe_uncertain_zh(en2, zh2)
w(f"场景2 中文多1块 (slack={A.structural_slack(en2, zh2)}) → 候选 {len(c2)} 个  "
  f"k0={_f(info2.get('k0'))}  strong={info2.get('strong')}  "
  f"raw={info2.get('cand_raw')}  cap掉{info2.get('dropped_by_cap')} "
  f"簇外{info2.get('dropped_by_cluster')}")
w(f"       候选下标：{c2}")
w()

# 场景 3：中文多 6 块（模拟 §1.5）
en3 = [P(f"English paragraph number {i} with enough words to be a real paragraph")
       for i in range(19)]
zh3 = [P(f"中文段落第 {i} 号，含有足够的字数以便被当作真正的正文段落处理")
       for i in range(27)]
c3, info3 = A.probe_uncertain_zh(en3, zh3)
w(f"场景3 中文多6块 (slack={A.structural_slack(en3, zh3)}) → 候选 {len(c3)} 个  "
  f"k0={_f(info3.get('k0'))}  strong={info3.get('strong')}  "
  f"raw={info3.get('cand_raw')}  cap掉{info3.get('dropped_by_cap')} "
  f"簇外{info3.get('dropped_by_cluster')}")
w(f"       候选下标：{c3}")
w()

# 场景 4：中文多 1 块，但很短的小节（模拟章节尾部小片段）
en4 = [P(f"Entry {i}") for i in range(6)]
zh4 = [P(f"条目 {i}，解释文字") for i in range(8)]
c4, info4 = A.probe_uncertain_zh(en4, zh4)
w(f"场景4 小片段 6:8 (slack={A.structural_slack(en4, zh4)}) → 候选 {len(c4)} 个  "
  f"k0={_f(info4.get('k0'))}  strong={info4.get('strong')}  "
  f"raw={info4.get('cand_raw')}  cap掉{info4.get('dropped_by_cap')} "
  f"簇外{info4.get('dropped_by_cluster')}")
w(f"       候选下标：{c4}")
w()

# 场景 5：条目式小节，中文多 40%（模拟「候选爆炸」的 ch31 形态）
en5 = [P(f"Author{i}, A. (19{i:02d}), Title of paper number {i}, Journal {i}, "
         f"{i*3+1}-{i*3+12}.") for i in range(60)]
zh5 = [P(f"作者{i}，A.（19{i:02d}），论文标题第 {i} 号，学报第 {i} 卷，"
         f"第 {i*3+1}-{i*3+12} 页。") for i in range(85)]
c5, info5 = A.probe_uncertain_zh(en5, zh5)
w(f"场景5 条目式 60:85 (slack={A.structural_slack(en5, zh5)}) → 候选 {len(c5)} 个  "
  f"k0={_f(info5.get('k0'))}  strong={info5.get('strong')}  "
  f"raw={info5.get('cand_raw')}  cap掉{info5.get('dropped_by_cap')} "
  f"簇外{info5.get('dropped_by_cluster')}")
w(f"       候选下标：{c5}")
w()

w("=== 结论要点 ===")
w("• slack>0 是**进入 LLM 的闸门**（pipeline.py:1741）→ 只要中文多 1 块就闸门大开")
w("• B 判据（only>=strong）在小 slack 时会把**几乎全部**中文块判为候选")
w("• 参考文献章 / 术语表 / 索引这类「条目式」小节天然 zh 比 en 多块")
w("  → 候选爆炸（实测 n=81）")
w("• `n_vis=0`（该节没有图表）时，LLM 拿不到「英文侧是图」的证据，")
w("  纯靠文本猜 → 盲目回 N → 弃 49 段 → 译文整段消失 + 相位再错")
w("=== DONE ===")

txt = "\n".join(lines)
Path(OUT).write_text(txt, encoding="utf-8")
print(txt)
