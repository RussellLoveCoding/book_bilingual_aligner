# 交接单（2026-09-17 16:4x，git `266526b`，写给人也写给下一个账号）

> 这份文件**入库**（`docs/HANDOFF.md`），因为换账号后工作区路径可能变，
> `.workbuddy/memory/`（gitignored）不一定跟得过去。详细日志仍在
> `.workbuddy/memory/HANDOFF.md` 与 `2026-09-17.md`（§1–§17）。

---

## 0. 开工三步（10 分钟）

```bash
# ① 环境自检（WSL 是唯一正解；Windows bash 会吃掉变量/重定向）
wsl.exe -- bash /mnt/c/<项目>/tools/_run.sh regress.py            # 三本小样确定性基线，免费
# ② 复现当前整本成品（全缓存命中 ≈ ¥0，约 2 分钟）
wsl.exe -- bash /mnt/c/<项目>/tools/_run.sh run_book.py \
  --en /mnt/c/<项目>/.workbuddy/tmp/books/prob_en.epub \
  --zh /mnt/c/<项目>/.workbuddy/tmp/books/prob_zh.md \
  --all --build --llm --ai-fill-missing --skip-flag --out <输出目录>
# ③ 门禁（人眼级，不看 stdout 指标）
python tools/dbg_bookscan.py <成品.epub>          # 应全 0
python tools/dbg_qa.py <成品.html> 20            # 当前 32 项
```

**必须先复制 `.env`**：LLM key 不在库里（`.gitignore` 第 2 行 `.env`），
只有 `.env.example` 入库。换账号/换工作区时手动把 `.env` 拷过去，并确认
`LLM_MODEL=qwen3.7-flash`（缓存键含模型名，换模型＝缓存全废、结果大变）。

---

## 1. 钉死的配置（改任何一条都会让结果不可复现）

| 项 | 值 | 为什么钉住 |
|---|---|---|
| `LLM_MODEL` | `qwen3.7-flash` | `llm._key = sha256(model+system+user)` |
| **章级映射** | **seq（默认）**，`BIL_LLM_CHMAP=1` 才走 LLM | LLM 分支会在「校验通过=LLM 键表 / 不过=seq」之间翻转，且失败时 `refresh=True` 绕过缓存重问 → 同一份代码两次重建段落对 5321↔4431 |
| `fastcache._V` | **10** | 改解析行为必须 +1，否则旧缓存冒充新结果 |
| 段落体检尺 | `audit_pairs(mode="legacy")` | 改尺子会悄悄改对齐决策 |
| 决策用 LLM 细化 | `BIL_ACCEPT_LLM=2`（语义校对一锤定音） | 见 `HANDOFF §2.7` |

---

## 2. 当前状态（已验收）

- **成品**：`diag/样章/prob_全书_双语.{epub,html}`（22.8MB / 28.5MB）
  段落对 **5321** · 命中中文 **4752(89%)** · AI补译 552 · 待补 17 · 告警 1253。
- **门禁**：`dbg_bookscan` 全 0（行号前缀 / 标记泄漏 / 缺中文）· `dbg_qa` 32 项 ·
  目录为**小节级**（每章小节全列）· nav 里第18章标题公式已是 `<i>A</i><sub>p</sub>`。
- **小样回归**：think2 33/33/0/1 · ml 212/197/15/18 · prob 408/371/37/38。
- **成本**：本轮全部 ¥0（905 次请求全命中磁盘缓存）。

### 最近两轮修了什么（细节 `2026-09-17.md §16/§17`）
1. AI 补译段的行号前缀（`3|`/`2||`/`1|[5]`）**161 → 0**
2. `![image](cdn…)` 外链图语法残留 **11 → 0**
3. 行内公式残留（`\operatornamevar`、`\pmbΛ`、`\sqrtN`、`<eq>` 标签）**91 → 0**
4. 目录章名被小节名顶替（`load_toc` 砍锚点导致键塌陷）→ 修
5. 目录只列 1~3 条/章 + zh·en 张冠李戴 → 改为小节级、整对取标题
6. 3.8.1 中文小标题丢失/配成「展望」→ 冒号标题 + 邻接锚点配对，现相邻成对
7. 注释正文漏公式渲染 → 接上；合并单元（3.8+3.8.1）标题被吞 → `SectionResult.merged`

---

## 3. 未完成（按优先级，都**没动手**，先定方案再改）

### 3.1 前置部分章映射（用户点名 #2）
zh 前置与 EN 前置**粒度不同**：
`zh = 出版信息 / 内容提要 / 版权声明 / 编者序 / 前言 / 致谢`，
`EN = Half Title / Copyright / Editor's foreword / Preface`。
现状：EN「Editor's foreword」被配到 zh「出版信息」，「致谢」作为单侧单元
**整段跳过（内容不在书里）**。建议两步（都很窄）：
① `txtimport._ZH_HEAD_RE` 加 `编者序`（把 zh 前置切成同粒度单元）；
② 加一张**前置词表**按词配对（half title/title page/copyright/dedication/
contents/editor's foreword/preface/acknowledgments ↔ 扉页/书名页/出版信息/版权/
目录/编者序/前言/致谢），替代位置 zip。

### 3.2 内容级漂移（用户 #3/#5/#10）
3.8 正文 bad 64%（8 处 only_zh）· 3.8.1 有 6 处 only_en+note · 17.5 · 8.11 开头
—— 同族问题：**标题已修好，段落边界没修**。查法：
`_run.sh dbg_sec.py prob chapter9 3.8` 逐对看文本。

### 3.3 第7章注释 29/30 中文对不上
疑似 zh 注释表与 EN 注释号**错位一格**（`note_texts` 按 EN id 取、
`res.notes` 按 zh 顺序）。定位入口：`build.py` 的 `_note_entry` / `note_texts`。

### 3.4 其它
微信读书公式图隐形（等用户 A/B 英文原版）· refine 采纳的确定性门槛（本轮只钉了章映射）。

---

## 4. 环境与坑（浓缩，详版在 `.workbuddy/memory/MEMORY.md`）

- **WSL 唯一**：`wsl.exe -- bash <项目>/tools/_run.sh <脚本> [参数]`；
  `wsl.exe -- bash -lc '...$VAR...'` 的变量会被 Windows 层吃掉。
  `_run.sh` 有护栏：cwd 不在项目内直接 exit 3。**WSL 只许碰项目目录**。
- 缓存：解析缓存在 WSL 原生盘 `~/.cache/bil`（`tools/.cache` 是软链）。
  **`.cache/*` 永不删 = 缓存就是钱**。`build/`、`diag/` 用户自己删。
- node 用 nvm 那份（`tools/eqrender` 要 ≥20.9）；**绝不在 /mnt/c 上 npm i**。
- 截图验证：`msedge --headless=new --disable-gpu --window-size=900,2300
  --screenshot=out.png file:///…`（不启服务）。
- **别用 `git rm`**：本轮实测 `git rm` 被 SIGTERM 打断后 `.git/index.lock` 残留
  + 工作区 56 个文件被连带清掉（含 `_run.sh`/`run_book.py`）。
  恢复配方：`rm -f .git/index.lock` → `git status --porcelain | awk '$1=="D"{print $2}'
  | xargs git checkout HEAD --`。要删文件就用普通 `rm` + `git add <路径>`。
- 代码整理时留下的**零引用探针**（可删，本轮没删是为了避开上面的雷）：
  `tools/dbg_heads2.py dbg_fig.py dbg_fig2.py dbg_wide2.py dbg_skew.py
  dbg_skew_stat.py dbg_eq_demo.py` + 根目录 `book_struct.json`。

---

## 5. 关键工具索引

```
tools/_run.sh             WSL 入口（护栏 + venv）
tools/run_book.py         整本/单章构建（--all --llm --ai-fill-missing --skip-flag）
tools/regress.py          三本小样确定性基线（免费，改代码后必跑）
tools/dbg_bookscan.py     ★ 整本成品扫描门禁（前缀/泄漏/缺中文/nav）
tools/dbg_qa.py           ★ 人眼级门禁（连续同侧段/宽组/标记泄漏/重复标题）
tools/dbg_eqpos.py        公式位置 vs 英文原版（按编号比对）
tools/dbg_eqcheck.py      成品公式守恒/编号唯一/死链（exit 0 = 全绿）
tools/dbg_sec.py          倒出指定小节全部配对全文（人审错位专用）
tools/dbg_hchain.py       小节标题链 + deep 配对（--deep）
tools/dbg_chmap_src.py    章映射 LLM/seq 两条路并排（回答「键表为什么变了」）
tools/.cache/*            解析/公式/LLM 三级缓存
tests/gold/               金标准（人工判定，不外包 LLM）
```
