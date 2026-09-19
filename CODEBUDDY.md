# CODEBUDDY.md — 双语 epub 流水线 · 接手须知

> ## 🟦 国际版 WorkBuddy 接手（必读，先看这段）
>
> 你（国际版）会在本项目根建 **`.workbuddy-ai/`**；而本项目的**代码/脚本/文档
> 到处写死的是 `.workbuddy/`**（上一台是中文版 WorkBuddy）。两者是**不同目录**，
> 但下面这些东西**必须继续用 `.workbuddy/`，不要去 `.workbuddy-ai/` 找**：
>
> | 东西 | 位置（**固定**） | 说明 |
> |---|---|---|
> | **源书** | `.workbuddy/tmp/books/` | `prob_en.epub` / `prob_zh.md` / `nexus_*` / `think2_*`。**gitignored，必须手动搬** |
> | **历史日志** | `.workbuddy/memory/*.md` | 上一台的全部逐日工作记录（**gitignored**，不在库里！） |
> | 诊断临时产物 | `.workbuddy/tmp/` | 一堆 `*.log` / 验收脚本 |
>
> ⇒ **你的 `.workbuddy-ai/` 只管你自己的会话状态；`.workbuddy/` 是项目数据，
> 照旧读写，别另起炉灶、别把源书复制进 `.workbuddy-ai/`。**
> 两者都已在 `.gitignore` 里（`.workbuddy/` 第 6 行、`.workbuddy-ai/` 末行）。
>
> ⚠ **`.workbuddy/memory/` 不在 git 里** —— 如果你拿到的是**另一台机器/另一次
> clone**，那份日志可能没跟过来。**这时以 `docs/HANDOFF.md`（已入库）为唯一权威**，
> 它把跨会话必须知道的东西全写进去了（当前指标、未完成、坑、`_V` 版本表）。
>
> **搬项目到新机器时的最小清单**：① 复制 `.env`（LLM key，含 `LLM_MODEL=qwen3.7-flash`）
> ② 复制 `.workbuddy/tmp/books/`（源书，版权+体积，不入库）
> ③（可选）复制 `.workbuddy/memory/`（日志，便于查历史）。
> **缓存不用搬**：在 WSL `~/.cache/bil`，同一台机器自动共享；缓存＝钱，别清。
>
> 详细流程见 **`docs/HANDOFF-国际版.md`**。

把「英文原书 + 中译本」合成**段段对照的双语 epub**（输入 epub/txt/md 皆可，成品格式随输入）。
核心难点是跨语言对齐：中译本常重排章节、合并/拆分段落、漏译整段。

**接手第一件事：读这三份，别急着改代码。**
1. `docs/HANDOFF.md`（入库版交接单：§0 开工三步 · §1 钉死配置 · §2 当前指标 · §3 未完成 · §4 环境坑）
2. `.workbuddy/memory/HANDOFF.md`（更细，含公式漂移的五种机制）
3. `.workbuddy/memory/<今天>.md`（最近一轮做了什么）

## 怎么跑（唯一入口）

**主路径 = WSL。** 从 Windows 侧调时写成：

```bash
wsl.exe -- bash /mnt/c/Users/abc/WorkBuddy/2026-09-12-13-08-31/tools/_run.sh <脚本> [参数]
```

已经在 WSL 里（终端直接在 WSL）就 `bash tools/_run.sh <脚本> [参数]`，**不需要** `wsl.exe` 中转。

- 它负责 `cd` 到 `tools/`，并用 `~/.venvs/bil/bin/python`（3.12）。
- ⚠ **cwd 必须是 `tools/`**：缓存目录是**相对路径**（`.cache/llm`、`.cache/parse`），
  而 `tools/.cache` 是软链 → `~/.cache/bil`。在项目根直接跑 `python tools/xxx.py`
  会让 cwd 错位 → 缓存**全部 miss**（既花钱又让结果漂移）。
- ⚠ `wsl.exe -- bash -lc '…$VAR…'` 的变量会被 Windows 层吃掉 → 参数写绝对路径、别写变量。

### 备用路径 = Windows 原生（**只许做只读诊断**）

WSL 不可用时（本机 `wsl.exe` 曾被安全策略拉黑过）可以退到 Windows 原生，但**只能读不能建**：

```bash
# 活缓存在 WSL 里，用 UNC 只读访问（wsl.localhost 别名不通，必须 wsl$ + 发行版全名）
Copy-Item '\\wsl$\Ubuntu-24.04\home\abc\.cache\bil\{llm,eq}' .cache-win\ -Recurse
# 两条软链在 Windows 上是断链 → 必须显式指缓存目录，否则可能误建 C:\home\...
export PARSE_CACHE_DIR=.cache-win/parse LLM_CACHE_DIR=.cache-win/llm BIL_EQ_CACHE=.cache-win/eq
```

- ✅ **能用**：`dbg_bookscan` / `dbg_qa` / `dbg_eqcheck` / `dbg_chmap_src` / `dbg_sec` /
  `regress.py` —— 结果与 WSL **逐位一致**（2026-09-17 实测）。
- ❌ **不能用**：`--build` 整本构建。`tools/eqrender/node_modules` 是断链 → 没有 `sharp`
  → 公式渲染不可用 → 产物降级成裸 LaTeX（实测 bookscan 泄漏 0→746、qa 32→33），
  **而 stdout 的「段落对/命中/AI补译」指标照样漂亮**。
  → **指标一致 ≠ 产物一致**；构建完必须跑门禁 + 核产物新鲜度。
- ⚠ 别在 Windows 上 `npm i` 补依赖：会顶掉指向 WSL 的软链，反过来把 WSL 弄坏。

## 开工自检（免费、分钟级）

```bash
bash tools/_run.sh regress.py                   # 三本小样：think2 33/33/0/1 · ml 212/197/15/18 · prob 408/371/37/38
bash tools/_run.sh dbg_bookscan.py <成品.epub>  # 期望：前缀 0 / 泄漏 0 / 缺中文 0
bash tools/_run.sh dbg_qa.py <成品.html> 20     # 当前 32 项（连续同侧长段为主）
bash tools/_run.sh dbg_eqcheck.py <成品.html>   # exit 0 = 全绿（张数守恒/编号唯一/无死链）
```

⚠ `regress.py` 比对的是 `tools/regress_baseline_sample.json`，**不是** `docs/HANDOFF §2`
（那个文件对 ml/prob 是过期的，环境完全正确也会报 diff）。以 HANDOFF §2 为准。

## 铁律（都是踩过血的）

1. **缓存就是钱**：`~/.cache/bil`（解析/公式/LLM 三级）永不删；`build/`、`diag/` 是用户的，
   别删，只许新增文件。
2. **禁用 `git rm` / `git stash`**：本机实测这两个被中断后会损坏仓库、连带清掉工作区
   56 个文件。要删文件用 `rm <路径>` + `git add <路径>`。
3. **改完必跑门禁，并核对「产物新鲜度」**——只看 stdout 指标会漏掉「构建崩在写盘前、
   指标照常、产物停在旧版」的事故（发生过，用户拿旧成品报了一整轮）。
4. **模型钉死** `.env: LLM_MODEL=qwen3.7-flash`。缓存键含模型名 → 换模型＝缓存全废、结果大变。
5. **花钱纪律**：LLM 跑前报预估、跑完报实销（读 `tools/.cache/llm/trace.jsonl` 的
   `in_tok/out_tok/hit`），单次 >¥0.5 先问；单章 ¥0.03–0.15 是日常粒度；禁止整书重跑。
   ⚠ **没有半价时段**（2026-09-18 作废旧规则）：`qwen3.7-flash` 全天一价。
   解析/结构类改动**立刻做**，别拿时段当拖延借口。
6. **改解析行为必须 `fastcache._V += 1`**（当前 **36**），否则旧缓存冒充新结果。
7. **版式/编号一律照抄英文原版**（自创被抓过两次）；非 LLM 的活必须 1 秒内完成。
8. 别擅自起长驻服务；临时验证完立刻 kill 并确认端口关闭。
9. **WSL 里只碰项目目录**；允许的例外（缓存 / venv / node 依赖）见 `CODEBUDDY.local.md`。
   输出结构上不用 `max_tokens` 兜底——要 32K 说明结构设计有问题。
10. **LLM 裁决类机制必须有「信号量下限」**（2026-09-18 §6.36）：疑点计数低于阈值
    不许调 LLM。§6.35 的 `judge_zh` 只要 `slack>0` 就放行 → p18 全书触发 91 次、
    弃 207 段（设计预期 8 段），其中两次 `n=81/n_vis=0` 裸判 → ch31 参考文献重复段。
    **别拿必然噪声当疑点问 LLM** —— 既烧钱又丢内容。
11. **判「是不是标题」用结构性信号（对侧有没有标题），不要用词表**（2026-09-18 §6.36）：
    `_FRAG_START` 这类中文词表必然按书调参，换本书就冒新词。正解 = 看英文侧
    同位置有没有登记标题（`en_heads_at`）。
12. **`dbg_qa` 类数 +1 要先跑「多版本逐项 diff」再定性**（2026-09-18 §6.36）：
    可能是既有缺陷被新内容暴露（相位移动），不是本轮引入。别急着改代码。
