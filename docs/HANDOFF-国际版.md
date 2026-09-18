# 交接给「国际版 WorkBuddy」——第一句话 + 目录差异说明

> 本文写给**下一位接手人**（用**国际版 WorkBuddy**，会在项目根建 `.workbuddy-ai/`）。
> 上一台用的是**中文版 WorkBuddy**（目录 `.workbuddy/`）。两者**并存、不冲突**，
> 但**项目数据一律在 `.workbuddy/`，不在 `.workbuddy-ai/`**。
>
> 入库版（git），跨机器可读。最后更新：2026-09-18 23:5x。

---

## 一、把下面这段话**原样发给新 AI**（第一句话）

```
这个项目（双语 epub 对齐流水线）上一台是用中文版 WorkBuddy 做的，项目数据都在
.workbuddy/ 目录里（源书 .workbuddy/tmp/books/、历史日志 .workbuddy/memory/）。
你会在根目录建 .workbuddy-ai/ —— 那是你自己的会话状态，跟项目数据无关。

请先做三件事，不要改任何代码：
1. 读 docs/HANDOFF.md（已入库的交接单，唯一权威：开工三步 §0、当前指标 §2、
   未完成清单 §3、环境坑 §4、以及 §6 里几十个已修缺陷的归因）。
2. 读 docs/HANDOFF-国际版.md（你手上这份）—— 目录差异 + 搬家清单。
3. 读 CODEBUDDY.md（项目铁律，尤其是「跑法 = WSL + tools/_run.sh」和
   「改解析/对齐行为必须 fastcache._V += 1」）。

有疑问先问我，不要猜。
```

> ⚠ 为什么必须这么说：新 AI 的默认行为是**在 `.workbuddy-ai/` 里找上下文**，
> 但本项目的源书和日志**不在那儿**。不先讲清楚，它会找不到源书、以为项目没数据，
> 甚至**重新去下载/复制一份源书**（浪费且可能拿错版本）。
> 另一个必须点明的是：**`.workbuddy/memory/` 是 gitignored 的** ——
> 如果换机器，那份日志不会跟过来，只有 `docs/HANDOFF.md` 在库里。

---

## 二、两个目录的分工（一句话记住）

| 目录 | 谁用 | 装什么 | 入库？ |
|---|---|---|---|
| **`.workbuddy/`** | **项目本身**（代码/脚本写死引用它） | `tmp/books/`（源书）· `memory/`（日志）· `tmp/`（诊断产物） | ❌ gitignored（第 6 行） |
| **`.workbuddy-ai/`** | **国际版 AI 自己** | 它自己的会话状态、缓存、草稿 | ❌ gitignored（末行） |

**规则：项目数据只认 `.workbuddy/`。** 别把源书塞进 `.workbuddy-ai/`，
也别把 `.workbuddy-ai/` 的内容当成交接资料。

### 代码里到底哪些地方写死了 `.workbuddy/`

（新 AI 若想「迁移到 .workbuddy-ai」会踩这些；**建议别迁，照旧用 `.workbuddy/`**）

- **运行脚本**：`tools/run_p22.sh`、`tools/gates_p22.sh`
  （`--en $PROJECT/.workbuddy/tmp/books/prob_en.epub` 等）
- **诊断脚本**：`tools/dbg_eq.py` / `dbg_latex.py` / `dbg_latex2.py` / `dbg_md_check.py`
  （`MD = _HERE.parent / ".workbuddy/tmp/books/prob_zh.md"`）、
  `tools/_judgestat.py` / `_probediag.py` / `_slackdist.py`（日志落 `.workbuddy/tmp/`）
- **文档引用**：`CODEBUDDY.md`、`docs/HANDOFF.md` 多处（`.workbuddy/tmp/…` 作为证据路径）

⇒ 迁目录是**改十几处 + 重跑验收**的活，收益为零（两个目录都 gitignored，
不影响复现）。**保持 `.workbuddy/` 不动**是正确选择。

---

## 三、新机器 / 新账号的「最小携带清单」

按重要性排序。**① 缺了整条流水线跑不起来；② 缺了无法复现成品。**

| # | 东西 | 在库里？ | 怎么带 |
|---|---|---|---|
| ① | **`.env`**（LLM key + `LLM_MODEL=qwen3.7-flash`） | ❌ | **手动复制到项目根**。缺 key → `--llm` / `--ai-fill-missing` 全废；模型名含在缓存键里，**换模型＝缓存全失效、结果大变** |
| ② | **源书** `.workbuddy/tmp/books/`（`prob_en.epub`、`prob_zh.md`、`nexus_*.epub`、`think2_*.epub`） | ❌ | 手动复制（版权 + 体积，故意不入库） |
| ③ | 历史日志 `.workbuddy/memory/` | ❌ | 可选，便于查「上一轮为什么这么改」 |
| ④ | 代码 | ✅ git | 已经在了 |
| ⑤ | 缓存（解析/公式/LLM 三级） | ❌ | **不用搬**：在 WSL `~/.cache/bil`，同一台机器自动共享。**缓存＝钱，永远别清** |
| ⑥ | 成品 `diag/*` | ❌ | 可由 `run_book --all --build` 复现（全缓存命中 ≈ ¥0、约 2 分钟） |

**⚠ 最容易漏的是 ①**：`.env` 不在库里（`.gitignore` 第 2 行），只有
`.env.example`。新账号第一步就要确认 `.env` 存在且 `LLM_MODEL` 正确。

---

## 四、跑法（唯一入口，别自己发明）

```bash
# 从 Windows 侧调（主路径）
wsl.exe -- bash /mnt/c/Users/abc/WorkBuddy/2026-09-12-13-08-31/tools/_run.sh <脚本> [参数]

# 已在 WSL 里就直接
bash tools/_run.sh <脚本> [参数]
```

- **WSL 是唯一正解**。Windows 原生 bash 会吃掉变量和重定向。
- `_run.sh` 用 `~/.venvs/bil/bin/python`，并 `cd` 到 `tools/`（**cwd 必须是 `tools/`**，
  否则相对路径缓存全 miss）。
- `_run.sh` 有**越界护栏**（项目根不在允许清单 → exit 3）。若项目搬到了新目录，
  把新路径加进 `_run.sh` 里那行 `case "$PROJECT" in ...`（注释里写了「唯一的硬编码，故意的」）。

### 开工自检（10 分钟，零成本）

```bash
# 1) 确定性基线（零 LLM，免费）
wsl.exe -- bash /mnt/c/<项目>/tools/_run.sh regress.py

# 2) 复现当前整本成品（全缓存命中 ≈ ¥0，约 2 分钟）
wsl.exe -- bash /mnt/c/<项目>/tools/run_p22.sh     # 看脚本里的路径，按需改输出目录

# 3) 五把门禁（人眼级，不看 stdout 指标）
python tools/dbg_bookscan.py <成品.epub>       # 应全 0
python tools/dbg_qa.py      <成品.html> 20     # 当前 17 类
python tools/dbg_order.py   <成品.html>        # 对内顺序（en 在前 应 0）
python tools/dbg_order.py   <成品.html> --heads # 标题次序（**scan 扫不到标题**）
python tools/dbg_eqcheck.py <成品.epub>        # 公式守恒，应 exit 0
python tools/dbg_drift.py   <成品.html> --sig num,eq   # 语义漂移链
```

---

## 五、当前状态（一句话）

现行成品 **`diag/prob_p22/Probability Theory the Logic of Science_双语.{epub,html}`**
（22:16 起跑、23:24 产出），`_V = 27`，门禁全绿。
最新改动是 **§6.37 补译前哨**（修 AI 补译幻觉「22. 传播理论导论」）。
细节见 `docs/HANDOFF.md` §2（指标表）与 §6.37–§6.40。

未完成清单在 **`docs/HANDOFF.md` §3**（唯一权威，含新增第 13 项
「统一架构：沉浸式翻译式同构插入」——用户定调**日后做、现在不管**）。

---

## 六、上一台留下的「用户定调」（必须尊重，逐条见 `docs/HANDOFF.md` §0）

1. **只碰项目目录**（含通过 WSL），项目外只许只读 + 装包。
2. **缓存是钱**，`tools/.cache`（→ `~/.cache/bil`）**永不删**。
3. **别用 `git rm` / `git stash`** —— 本环境这两个破坏性写操作都被打断过并留下半成品状态。
   删文件用 `rm` + `git add`；对比 HEAD 用 `git worktree add`。
4. **改解析/对齐行为必须 `fastcache._V += 1`**（当前 27），否则旧缓存冒充新结果。
5. **LLM 跑前报预估、跑完报实销**（读 `tools/.cache/llm/trace.jsonl`）；预估超 ¥0.5 先问。
6. **版式一律照抄英文原版**；非 LLM 的活必须 1 秒内完成。
7. **DOM 次序：中文在前**；任何新增元素类型都必须带侧别 token（`en`/`zh`）。
8. **报「门禁全绿」之前，先证明尺子能测出该缺陷。**
