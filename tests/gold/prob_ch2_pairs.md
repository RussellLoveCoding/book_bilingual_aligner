# 金标准：prob 第2章（key `chapter8`）段落配对 —— 体检指标校准用

> 2026-09-16 由我（助手）逐条人工判定，**不外包 LLM**（定调①）。
> 用途：回答「`bad` 这个指标准不准」。样本 = DP 结果里被体检判坏的**全部 24 条**
> （`dbg_pairs.py prob chapter8 --bad`，重现命令见文末）。

## 判定口径

- **正确**：中英两段就是同一内容的对应段（长短、是否含公式都不影响）。
- **真错位**：配对关系本身错（译文在邻位/别的小节、或英文残句悬空）。
- **结构差异**：两侧结构本就不同（中文独有段、英文脚注中文版没有）——
  **不是对齐错误**，不该计入「错」。
- **误判**：配对正确，但被体检判成坏。

## 逐条判定

| pair | r | 体检标记 | 判定 | 依据（原文要点） |
|---|---|---|---|---|
| 1/20 | 0.92 | ratio | **正确（误判）** | "and then in the plausibility (BC\|D)…" ↔ "最后，对合情性 BC\|D 再次应用(2.1)，得到" |
| 1/27 | 0.92 | ratio | **正确（误判）** | "denoting the left-hand sides of (2.17),(2.18) by U,V…" ↔ "分别用 U 和 V 表示 (2.17) 和 (2.18) 的左侧…" |
| 1/30 | — | only_en | **真错位** | EN 只有一个 "where"，中文把"其中"并进前段（残句悬空） |
| 2/3 | 0.88 | ratio | **半错（边界）** | EN "where D is any new proposition…" ↔ ZH 里混着上一段的尾巴"时 (2.40) 必须成立" |
| 2/22 | 0.69 | ratio | **正确（误判）** | EN 多带上句尾巴 "for some positive m."，主体 "the product rule itself can be written equally well as" ↔ "当然，乘法规则也可以写成" |
| 2/29 | — | only_zh | **结构残句** | ZH 只有"最后，我们有"，对应 EN 被并到别处 |
| 3/4 | 0.65 | ratio | **正确（误判）** | "respectively. But from (2.68)…" ↔ "从 (2.68) 我们得到…(2.70) 简化为" |
| 3/8 | 0.82 | ratio | **正确（误判）** | "But from (2.68), p(B\|AC)=1…" ↔ "但是，根据(2.68)有 p(B\|AC)=1…" |
| 4/5 | 0.92 | ratio | **正确（误判）** | "Applying (2.66) again, we obtain seven terms…" ↔ "再次应用 (2.66) 得到七项，分组如下：" |
| 4/19 | — | only_en | **真错位** | EN 残句 "In equations, this statement is"，译文在邻段末尾 |
| 4/20 | 0.81 | ratio | **正确（误判）** | "which we shall call the symmetry equations…" ↔ "称为对称方程．结合(2.88)…" |
| 4/26 | 0.82 | ratio | **正确（误判）** | "From (2.92) and (2.93) we obtain n equations…" ↔ "根据 (2.92) 和 (2.93)，我们得到形如" |
| 8/14 | 3.10 | ratio | **真错位** | EN 讲"未来科学转向信息内容、哥德尔结果"，ZH 讲"不会发现不一致、考克斯定理" |
| 8/16 | — | only_zh | **结构差异** | 中文独有段（英文版此处内容不同） |
| 8/17 | — | only_zh | **结构差异** | 同上 |
| 8/19 | — | only_zh | **真错位** | 该中文段的英文其实是 9/11（跨小节错位） |
| 9/6 | — | only_en | **真错位** | EN "are simply declarative statements of fact…" 与 ZH[6] 是同句拆分 |
| 9/10 | 0.73 | ratio | **真错位** | EN "Even when both A and B can be resolved…" ↔ ZH 讲"我们的概率系统与柯尔莫哥洛夫不同" |
| 9/11 | — | only_en | **真错位** | EN "So, rather than saying that the Venn diagram…" 译文在 8/19 |
| 10/0 | — | only_en | **真错位** | 边界错一格：EN Kolmogorov 首段悬空，其译文在 10/1 |
| 10/1 | 0.67 | ratio | **真错位** | ZH 是 10/0 的译文 |
| 10/2 | — | only_en | **结构差异** | 英文脚注 [1]，中文版无 |
| 10/3 | — | only_en | **结构差异** | 英文脚注 [2]，中文版无 |
| 10/4 | — | only_en | **结构差异** | 英文脚注 [3]，中文版无 |

## 汇总（尺子准不准）

```
真错位  10/24 = 42%      ← bad 标记里真正是错的
误判     8/24 = 33%      ← 配对正确却被判坏
结构差异 6/24 = 25%      ← 两侧结构本就不同，不该算错
```

**分类别精确率**

| 标记类型 | 条数 | 真错 | 精确率 | 结论 |
|---|---|---|---|---|
| `ratio`（r ∉ [1,3]） | 12 | 4 | **33%** | ⚠ 其中 **r < 1 的 9 条里 8 条是误判** → **下限 1.0 在含公式的书上是噪声** |
| `only_en` | 8 | 6 | 75% | 有意义（覆盖缺口），但含脚注类结构差异 |
| `only_zh` | 4 | 1 | 25% | 多为中文独有段（结构差异） |

**为什么 DP 的 bad 低**：DP 的目标函数就是拟合长度，它靠**合并相邻块**把 r 撑进
[1,3]（prob ch2 多对 44/197）。LLM 给出更细的 1:1 语义对齐后，这些被藏起来的
r 异常立刻暴露 → 用这把尺子看，LLM「更差」。**尺子奖励的是凑长度，不是配得对。**

## 已据此做的修正（2026-09-16）

1. `bil/audit.py`：含公式/代码的 pair **退出 ratio 判定**（只保留 only_en/only_zh 覆盖信号）。
   效果：prob warn 24→20、ml 148→136。
2. 采纳 LLM 细化结果默认**关闭**（`BIL_ACCEPT_LLM=0`）——验收尺子校准通过前不许用。
3. 下一轮应做的：把 ratio 的下限按书校准（prob 建议 0.5）、把「结构差异」从 bad 里
   单列（脚注/中文独有段），并把 skew（LLM 校对）纳入验收。

## 重现命令

```bash
P=/mnt/c/Users/abc/WorkBuddy/2026-09-12-13-08-31
wsl.exe -- bash $P/tools/_run.sh dbg_pairs.py prob chapter8 --bad     # 本文样本（24 条）
wsl.exe -- bash $P/tools/_run.sh dbg_pairs.py prob chapter8 --sample 12
```
