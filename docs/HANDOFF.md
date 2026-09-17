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

### 换账号「携带清单」（新工作区 ≠ 旧目录时逐项核对）

| 东西 | 在库里？ | 怎么带 |
|---|---|---|
| 代码 | ✅ git | clone / 打开同一 repo |
| `.env`（LLM key） | ❌ gitignored | 手动复制，含 `LLM_MODEL` |
| **源书**（`prob_en.epub` / `prob_zh.md` 等） | ❌ gitignored（版权+体积） | 手动复制 `.workbuddy/tmp/books/` |
| 解析/公式/LLM 三级缓存 | ❌ 在 WSL `~/.cache/bil` | **同一台机器就自动共享**（缓存=钱，别清） |
| 成品（`diag/样章/*`） | ❌ gitignored | 可由 `run_book --all --build` 复现（≈2 分钟 / ¥0） |
| 本机依赖 | — | WSL + `~/.venvs/bil`、nvm 的 node（`tools/eqrender` 要 ≥20.9）、msedge（截图） |

### 三本书的源配对（换账号/换机器时最容易找错，照这张表抄）

| 书 | 英文原书 | 中译本 | 成品 |
|---|---|---|---|
| 概率论沉思录 | `.workbuddy/tmp/books/prob_en.epub` | `.workbuddy/tmp/books/prob_zh.md`（minerU OCR） | `diag/样章/prob_全书_双语.{epub,html}`（最新） |
| 智人之上 (Nexus) | `.workbuddy/tmp/books/nexus_en.epub` | `uploads/zh_zh.epub` | `build/智人之上…_双语.{epub,html}`（09-14 版） |
| 思考，快与慢（第二版） | `.workbuddy/tmp/books/think2_en.epub`（**不是** `think_en.epub`） | `.workbuddy/tmp/books/think2_zh.epub` | `build/思考，快与慢（第二版）_双语.epub`（09-14 版） |

> ⚠ think2 有两份英文：`think2_en.epub`（2.3MB · 59 章片，流水线用这份）与
> `think_en.epub`（3.65MB · 71 章片，z-lib 原版）。拿错会整章对不上。
> nexus 的英文原始来源在用户 D 盘同步盘（项目外），项目内副本就是
> `nexus_en.epub`（另有一份同内容 `nexus_en_原版.epub`）。

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
  ⚠ **这是 ①③ 之前的盘上成品**。§3.1 全部修完（②④）后新成品在
  `.workbuddy/tmp/fix31c/`：段落对 **6067** · 命中中文 **4893** · AI补译 1157 ·
  待补 17 · 告警 **1838**（尾部参考文献带中文评注，结构性差异，见 §6.4）。
- **门禁**：`dbg_bookscan` 全 0（行号前缀 / 标记泄漏 / 缺中文）· `dbg_qa` 32 项 ·
  目录为**小节级**（每章小节全列）· nav 里第18章标题公式已是 `<i>A</i><sub>p</sub>`。
- **小样回归**：think2 33/33/0/1 · ml 212/197/15/18 · prob **539/480/59/42**
  （⚠ 本行旧值 408/371/37/38 是 ①③ 之前的；JSON 基线文件更旧，见 §6.3）。
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

### 3.1 前置部分章映射（用户点名 #2）—— **✅ 四步全修完，详见 §6.4**

> 2026-09-17 21:2x：①③（前置）与 ②④（尾部）**全部修完并验收**。
> 前置 `Editor's foreword ↔ 编者序`、`Preface ↔ 前言` 归位；尾部
> `Appendix03↔附录C`、`References↔引用文献`、`Bibliography↔参考文献`、
> `Author index↔人名索引`、`Subject index↔符号` 全部归位。
> 门禁：bookscan 全 0 ✅ · eqcheck exit 0 ✅ · regress **零变化** ✅；
> qa 32 → 41（**新增 9 项全在尾部**，性质见 §6.4，非错配）。
> 成本 ≈**¥0.11**（整本重建，273 次未命中）。
> ⚠ 副作用：尾部「译者致谢」由「错配保留」变为「zh-only 丢弃」→ 见 §6.4 末尾。

zh 前置与 EN 前置**粒度不同**：
`zh = 出版信息 / 内容提要 / 版权声明 / 编者序 / 前言 / 致谢`，
`EN = Half Title / Copyright / Editor's foreword / Preface`。
现状：EN「Editor's foreword」被配到 zh「出版信息」，「致谢」作为单侧单元
**整段跳过（内容不在书里）**。建议两步（都很窄）：
① `txtimport._ZH_HEAD_RE` 加 `编者序`（把 zh 前置切成同粒度单元）；
② 加一张**前置词表**按词配对（half title/title page/copyright/dedication/
contents/editor's foreword/preface/acknowledgments ↔ 扉页/书名页/出版信息/版权/
目录/编者序/前言/致谢），替代位置 zip。

### 3.2 内容级漂移（用户 #3/#5/#10）—— **原文症状已不复现，见 §6.6**

> 2026-09-17 21:5x 实测（全书 bad 清单在 `.workbuddy/tmp/diag31c.log`）：
> 「3.8 正文 bad 64%」**已不存在** —— 第3章（`chapter7`）现在 bad 14/334 = **4%**，
> 3.8 小节 rate=0.04。原文症状是**更早版本**的（或尺子改过）。
> ⚠ 另外：原文给的查法 `dbg_sec.py prob chapter9 3.8` 里 **chapter9 是第5章**
> （章号随映射漂移过），第3章应写 `chapter7`。
> 仍然存在的是 **23 条「EN 有编号、ZH 没有」的 `X.Y.1` 三级小节** → 见 §6.6。

### 3.3 第7章注释 29/30 中文对不上 —— **无法复现，见 §6.7**

> 2026-09-17 21:5x 实测：第7章（成品 html 里 `id="ch8"`）**既没有注释区、
> 也没有注释锚点**（`ch8n*` 只在 base64 图片里偶然命中）；全书 `<b>[29]</b>`
> 命中 **0 处**。详见 §6.7 —— 那里记了一个**相关的真 bug**：英文兜底被
> `if res.notes:` 挡住，中文版缺注释的章连英文原注也一起不渲染。

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
tools/mk_review_bundle.py 成品 HTML → 给外部模型（Gemini 等）评审的纯文本包
                          （逐对导出 + 章号对照表 + 原书英文全文；秒级零 LLM）
tools/dbg_bookscan.py     ★ 整本成品扫描门禁（前缀/泄漏/缺中文/nav）
tools/dbg_qa.py           ★ 人眼级门禁（连续同侧段/宽组/标记泄漏/重复标题）
tools/dbg_eqpos.py        公式位置 vs 英文原版（按编号比对）
tools/dbg_eqcheck.py      成品公式守恒/编号唯一/死链（exit 0 = 全绿）
tools/dbg_sec.py          倒出指定小节全部配对全文（人审错位专用）
tools/dbg_hchain.py       小节标题链 + deep 配对（--deep）
tools/dbg_chmap_src.py    章映射 LLM/seq 两条路并排（回答「键表为什么变了」）
tools/dbg_frontmap.py     ★ 前置/后置单元映射尺子（§3.1 专用）：并排打 EN/ZH 单位表
                          + 章映射首尾若干组 + 三条自动诊断（切分不足 / EN 前置误判
                          other / 标题错配）。改 §3.1 前后各跑一次即可判断有没有修好。
                          `--dump <子串>` 把单元内部摊开（定位「这 1076 段里到底
                          吞了什么」）、`--dump-from N` 看区间、`--dry-fix <mode>`
                          在内存里预演切分修复（零成本）。
tools/dbg_bookview.py     ★ 成品体检多面手（只读秒级零 LLM）—— 补 `dbg_qa.py` 只给
                          计数、看不到「具体哪几处」的缺口。子命令：`--chapters`
                          列章 id+标题 / `--dupheads` 相邻重复标题 / `--orphans`
                          未配对中文段 / `--stats` 注释区分布 / `--find "文本"`
                          全文搜+上下文 / `--slice a b` 按 offset 切 / `--epubnav`
                          读 epub 的 nav+toc 全部条目。2026-09-17 那轮四个渲染/
                          目录 bug 全靠它定位（详见 §6.8–§6.11）。
tools/dbg_cost.py         ★ LLM 实销核算（铁律 5 的「跑完报实销」）：
                          `_run.sh dbg_cost.py "09-17 21:21:40" "09-17 21:27:30"`。
                          ⚠ trace.jsonl 里**只有未命中记录带 in_tok/out_tok**，
                          命中记录只有 hit/key/bytes_ —— 直接 grep 全文件会误报 ¥0。
tools/.cache/*            解析/公式/LLM 三级缓存
tests/gold/               金标准（人工判定，不外包 LLM）
```

---

## 6. 接手当天（2026-09-17 20:xx）的补正 —— 以本节为准

### 6.1 环境：本机 `wsl.exe` 进过安全黑名单

新账号首次接手时，`wsl.exe` 被 **Security Center → Command Security → Program Blacklist**
拉黑（报 `PROGRAM BLOCKED BY SECURITY POLICY`，命令层无法绕过）→ §0/§4 的「WSL 唯一」
工作流整条不可执行。**用户已移除该条目，现恢复正常。**

期间实测出**备用路径**（WSL 再被禁时可用）：`\\wsl$\Ubuntu-24.04\...` 可**只读**访问
WSL 文件系统（`wsl.localhost` 别名不通），代码零第三方依赖、LLM/公式缓存是内容寻址 →
把 `~/.cache/bil/{llm,eq}` 复制到项目内 `.cache-win/` 后，Windows 的 python 3.13 可跑：

| 用途 | Windows 原生 |
|---|---|
| `dbg_bookscan` / `dbg_qa` / `dbg_eqcheck` / `dbg_chmap_src` / `regress.py` | ✅ 结果与 WSL **逐位一致** |
| 整本 `--build` | ❌ **产物降级**（`tools/eqrender/node_modules` 是断链 → 没 `sharp` → 公式渲染不可用 → 裸 LaTeX 泄漏 0→746、qa 32→33），**而 stdout 指标照样是 5321/4752/552/17/1253** |

⚠ **指标一致 ≠ 产物一致**——这正是 §铁律 3 说的那类事故，构建后必须跑门禁 + 核新鲜度。
⚠ 别在 Windows 上 `npm i` 补依赖：会顶掉指向 WSL 的软链，反过来把 WSL 弄坏。

### 6.2 本节新增的复现证据（三本对照）

| | 盘上成品(16:10) | WSL 复现 | Windows 复现 |
|---|---|---|---|
| html md5 | `1a015f37…` | **完全相同** ✅ | `d175da0b…` ❌ |
| dbg_bookscan | 0 / 0 / 0 | **0 / 0 / 0** ✅ | 746 泄漏 ❌ |
| dbg_qa | 32 | **32** ✅ | 33 ❌ |
| dbg_eqcheck | exit 0 | **exit 0** ✅ | — |
| 耗时 | — | **33s** | 2m18s |

**⇒ WSL 整本构建是位级可复现的（HTML md5 一致）。** 环境健康，可正式开工。

### 6.3 修正 §2：小样回归基线的文件是过期的

`tools/regress_baseline_sample.json` 里 ml/prob 两条是**旧的**
（ml 204/193/0/11/14、prob 392/338/0/54/96），而 **§2 的 212/197/15/18、408/371/37/38
才是实测值**（WSL 与 Windows 两边跑出来都一样）。
`regress.py` 比对的是**那个 JSON**，不是 §2 → **环境完全正确也会报一堆 diff**。
→ 修法：`bash tools/_run.sh regress.py --save` 刷新基线（顺手把只有 think2 的
`regress_baseline.json` 补齐，或删掉）。

另：`run_book` 的「段落对 5321」与 `dbg_qa`/评审包的「pair 5406」是**两个口径**
（README「已知边界」已说明 pairs 是配对对象数），不是不一致。

### 6.4 修正 §3.1：根因比原文更宽，**「两步窄修」不够**

原文说「zh 前置粒度与 EN 不同」，实测根因是**两侧都错**，且**尾部同族**。
（完整证据见 `.workbuddy/memory/2026-09-17.md §24.5`，下面是结论。）

**代码点**
- EN 侧：`structure.key_of_en`（`structure.py:63`）**没有前置词表**，只认
  `_EN_HEAD_KINDS` 前缀 → `02_half-title`、`04_copyright`、`07_fm-chapter`("Editor's
  foreword")、`08_fm-chapter1`("History") 全判 `other` 进了位置 DP。
- ZH 侧：`txtimport.load_md` 的切分条件
  `is_chapter = (level <= top_level or _is_heading(title, lang))`（`txtimport.py:182-183`）
  + `_ZH_HEAD_RE`（`txtimport.py:34-36`）**缺 `编者序`**，也缺尾部 `人名索引/术语索引/符号`。

**后果**
- `md001`「出版信息」其实是 **出版信息+内容提要+概率论沉思录+版权声明+编者序**（51 段）；
  `md032`「致谢」其实是 **致谢+人名索引+术语索引+符号**（500 段）。
- seq 位置 DP 只看长度比 → `EN Editor's foreword ↔ zh 出版信息`、
  **`EN References ↔ zh 附录C`**、**`EN Subject index ↔ zh 致谢`**。
  实证 `diag/review/prob/全本对照/ch27` = EN 参考文献条目 ↔ ZH 卷积数学；
  `ch28` = EN 主题索引 ↔ ZH 人名索引，**内容完全不相干**。
- 成品 ch01 那 6 对**内容其实是对的**，错的是**标题取了块首「出版信息」**；
  且 `出版信息/内容提要/版权声明` 被当「zh-only 正文段」**丢弃**（run_book 会打印
  `[zh-only 丢弃] 1324 段…样本：['[美] 埃德温·汤普森·杰恩斯…', '图书在版编目（CIP）数据'…]`）。

**⇒ 原「两步窄修」不够，实为四步。①③ 已做，②④ 待做：**

| 步 | 内容 | 状态 |
|---|---|---|
| ① | `_ZH_HEAD_RE` 补 `编者序`（`txtimport.py:34`） | ✅ **已做**（`fastcache._V` 10→11） |
| ③ | EN 侧垃圾页判 skip：`key_of_en(blocks, file)` 加**文件名兜底** `_EN_FILE_SKIP`（标题文本认不出：half-title 的标题是书名、copyright 页无标题）；`_ZH_SKIP` 补 `出版信息\|内容提要\|扉页\|书名页` | ✅ **已做**（不动解析层，无需 `_V`） |
| ② | 尾部切分：`_ZH_HEAD_RE` 补 `引用文献/参考文献/人名索引/术语索引/符号`，并新增 **`_bare_head()` 裸标题行识别**（`引用文献`/`参考文献` 在源稿里没有 `#` 标记，只有缩进） | ✅ **已做**（`fastcache._V` 11→12） |
| ④ | 尾部映射归位（**不需要**按词配对——切分修好后位置 DP 自己就配对了） | ✅ **已做**（同一次改动，无额外代码） |

**①③ 的实测结果（2026-09-17 21:1x，prob 整本）**

- 前置：`chapter1 Editor's foreword ↔ 编者序` ✅、`chapter2 Preface ↔ 前言` ✅
  （改前是 `Editor's foreword ↔ 出版信息`，且编者序内容被当 zh-only 丢弃）
- 成品里 `埃德温·汤普森·杰恩斯于1998年4月30日去世`（编者序首句）出现 1 次 ✅；
  `图书在版编目（CIP）数据` / `This publication is in…` 均归 0（垃圾页正确出局）
- 指标：段落对 **5321** · 命中中文 **4752** · AI补译 552 · 待补 17 ·
  告警 **1253 → 1225**（−28）· zh-only 丢弃 1324 → 1258（−66）
- 门禁：`dbg_bookscan` 全 0 ✅ · `dbg_qa` **32 项**（与基线一致，QA 清单零新增零丢失）✅ ·
  `dbg_eqcheck` exit 0 ✅ · `pair 5406 / 元素 11741` 与改前完全相同
- regress 三本小样**零变化**（33/33/0/1 · 212/197/15/18 · 408/371/37/38）✅
- 成本 ≈ **¥0.001**（改动只波及前置/尾部，ch1–22 的 prompt 全部命中缓存）

**②④ 的实测结果（2026-09-17 21:2x，prob 整本 `fix31c`）**

⚠ **先纠正上面一句错话**：原文说「EN 的 References/Bibliography 在中文版里
**没有对应物**，属内容决策」——**不成立**。实测中文版尾部有**两份**：

| zh（md 源） | 形式 | 段数 | 对应 EN |
|---|---|---|---|
| `### 附录 C 卷积和累积量` | 三级标题 | 81 | Appendix03 (80) ✅ |
| ` 引用文献` | **裸行**（无 `#`） | 476 | References (529) |
| ` 参考文献` | **裸行**（无 `#`） | 519 | Bibliography (435) |
| `### 致谢` | 三级标题 | 6 | ∅（中文版独有·译者致谢） |
| `### 人名索引` | 三级标题 | 393 | Author index (244) |
| `### 术语索引` | 三级标题 | **1**（只有标题、无内容） | ∅ |
| `### 符号` | 三级标题 | 100 | Subject index (372) |

所以 ②④ **不是内容决策，是纯切分问题**：`load_md` 的
`is_chapter = (level <= top_level(2) or _is_heading(title))` 让 `###` 级标题
**只有命中 `_ZH_HEAD_RE` 才开新单元**，而 `引用文献/参考文献` 连 `#` 都没有
（`_MD_HEAD_RE` 根本匹配不到）→ 四节全被并进 `md032`（1076 段）。

**改法**（两处，都很窄）
- `txtimport._ZH_HEAD_RE` 补 `(?:引用|参考)文献|人名索引|术语索引|符号`；
- 新增 `txtimport._bare_head()`：**整行恰好等于一个标题词**（`fullmatch`，非前缀）
  时开新单元。⚠ 必须 `fullmatch` —— 正文里「……见参考文献」用前缀匹配会被切成标题。

**效果（fix31b → fix31c）**
- 尾部映射**五组全对**：`Appendix03↔附录C` · `References↔引用文献` ·
  `Bibliography↔参考文献` · `Author index↔人名索引` · `Subject index↔符号`；
  `∅↔致谢` 留作 zh-only（正确）。改前是 `References↔附录C`、`Subject index↔致谢`。
- zh 单元 33 → **38**；段落对 5321 → **6067**；命中中文 4752 → **4893**；
  zh-only 丢弃 1258 → **964**。
- 门禁：`dbg_bookscan` 全 0 ✅ · `dbg_eqcheck` exit 0 ✅（1746 张表守恒、
  0 重复编号、0 死链）· `dbg_qa` 32 → **41 项** · regress **零变化**（与 HEAD 版本
  逐位相同：33/33/0/1 · 212/197/15/18 · 539/480/59/42）· 成本 **¥0.11**。
- **qa 新增的 9 项全在尾部**（元素 9912 起），且**全部是「侧=zh 的连续同侧长段」**，
  内容是参考文献条目 + 中文评注 + 中译本信息（如 `Bloomfield, P. (1976)…`、
  `中译本 斯蒂芬·杰·古尔德. 奇妙的生命…`）。**这是真实结构差异**：中文版参考文献
  **带中文评注**、英文版只有 1 段条目 → zh 侧连续 3~6 段。属 §3.2 段落级范畴，
  **不是映射错**。中部 25 项与 fix31b **逐字相同**（元素序号都没变）→ 无回归。
- 告警 1225 → 1838、AI补译 552 → 1157：同样是尾部新配对章暴露出来的量，不是退化。

⚠ **副作用（待用户拍板）**：尾部「译者致谢」（md035，6 段，含署名「廖海仁」）
改前被**错配**给 EN Subject index 因而**保留**在成品里，改后正确判为 zh-only 章 →
**整章内容（连标题）没进成品**（`致谢`/`廖海仁` 出现次数 1→0）。
`术语索引`（空单元，只有标题）同样不再出现。
根因是 `build.py:1190-1198` 的既有规则：**中文独有正文段直接丢弃**（用户
2026-09-17 定调，针对「公式图的中文译文行」）。整章 zh-only 是否该按同一规则
丢弃、还是保留为中文单侧章节，**需要用户定调**。

**方法论（再次验证）**：`dbg_frontmap.py --dry-fix` 能零成本预演切分效果 ——
本次预演出的「方案 A 尾部五组全对 / 方案 B（12 篇中文文章也各自成块）反而把
`Bibliography` 配给「一位物理学家的观点」」与实测结果**完全一致**，
所以动手前就已经知道该选哪个方案。

⚠ 通用教训（本次实测）：`fastcache._V += 1` 并不等于「全书 prompt 失效」——
改动的**影响面要用 `dbg_frontmap.py` 的改前/改后 diff 量**（这次只差 2 个区域，
ch1–22 全不变 → 成本从「按定调要等半价时段」降到 ¥0.001）。
先量影响面，再决定要不要等时段。

### 6.5 行尾符陷阱（提交前必看）

`.gitattributes` 原来只覆盖 `*.py *.md *.json`。实测过：Windows 侧工具碰过的文件会变
CRLF，而 `git diff` 会显示成**整文件重写**（`book_struct.json` 的 286/286 就是纯噪音，
`--ignore-cr-at-eol` 后 diff 直接消失）。已补 `*.sh` / `.gitignore` / `*.txt` 等规则。
⚠ 判行尾**别用 Git Bash 的 `grep -c $'\r'`**（对纯 LF 文件也报满行命中）→
用 `tr -dc '\r' < f | wc -c`。

### 6.6 修正 §3.2：原文症状已不复现，剩下的是 23 条 `X.Y.1` 小节

**全量 bad 清单怎么拿**（比逐节猜高效）：`run_book.py --all`（**不加 `--build`**
可省掉渲染/写盘，全缓存命中 ≈ 3 分钟、**¥0**），stdout 重定向到文件，
然后看 `pipeline.py:2079` 打的 `[i] <节名> bad=x/y rate=…` 行 + 每章的
`pairs N 匹配 N 缺中文 N … bad N (NN%)` 汇总行。

**实测（`fix31c`，2026-09-17 21:5x）**
- §3.2 原文说的「3.8 正文 bad 64%」**已不存在**：第3章 = `chapter7`，
  bad 14/334 = **4%**；`dbg_sec` 里 3.8 小节 `rate=0.04`。
- **真正突出的是尾部**（②④ 正确配对后才暴露）：
  `References` 596/634 (94%)、`Bibliography` 583/666 (88%)、
  人名索引 393/447 (88%，**匹配 0**)。原因是**索引/参考文献的本质差异** ——
  中文版带中文评注+中译本信息、英文版只有裸条目；索引章两侧排序规则不同
  （英文按字母、中文按拼音）。**这不是映射错**，属 §3.2 段落级范畴。
- 仍待修的一项：**23 条「EN 有编号、ZH 没有」的三级小节**，清一色 `X.Y.1`：
  `3.8.1 4.4.1 4.6.1 5.6.1 5.9.1 6.9.1 6.11.1 7.27.1 8.10.1 9.6.1 9.11.1
  10.3.1 14.6.1 15.8.1 16.8.1 17.5.1 17.8.1 18.11.1 19.2.1 19.7.1 20.4.1
  20.5.1 3.11.1`。
  **根因**：中文版把这类「Digression」小节的标题写成**裸行**、且用词不在
  `_ZH_HEAD_RE` 里。实测样本：`3.8.1 Digression: a sermon on reality vs. models`
  → 源稿第 2406 行 `离题：关于现实与模型的说明`；`4.6.1 Historical digression`
  → `历史题外话`（3469）；`4.4.1` → `离题：另一种推导`（3189）；
  `20.4.1` → `离题：又一次说明`（15797）。
  ⇒ 修法要**区分章级与小节级裸标题**：章级（`引用文献`/`参考文献`）走
  `_bare_head` → `open_doc`；小节级（`离题：…`/`…题外话`）应当只做
  **heading 块**（留在单元内，不开新单元）。⚠ 直接加进 `_ZH_HEAD_RE` 会
  把 `###` 级也判成章、把单元切碎 —— **别那么干**。
  （`SectionResult.merged` 已经在处理「EN 3.8 与 3.8.1 合成一个单元」的
  渲染侧，所以本条影响的是**小节级配对统计与目录**，不是正文错位。）

### 6.11 目录补全：小节级目录正则漏了 h4（2026-09-17 22:4x，commit `8cb98f3`）

**病象**：nav/toc 里有 `3.8 有放回抽样` 却**没有 `3.8.1`** —— 读者从 3.8 直接跳到
3.9。`18.11.1`、`5.9.1` 等同样缺失。

**根因**：`_NAV_H3_RE = r'<h3 class="st ([^"]*)">…'` **只扫 `h3`**。而「原位发」的
子小节标题渲染出来是 **`<h4 class="st …">`**（见 §6.8/§6.10 的 `en_heads_at`/
`zh_heads_at` 路径）⇒ 全部进不了目录。全量统计：`h3.st` 588 个、**`h4.st` 108 个**。

**修法**
1. 正则改 `<h[34] class="st ([^"]*)">(.*?)</h[34]>` —— **group 编号刻意保持不变**
   （1=class，2=文本），下游两个调用点（`_annotate_sections`、`_piece_label`）无需改；
2. `_annotate_sections` 补幂等 id 时**保留原标签名** —— 原样重写成 `h3` 会把子小节
   标题悄悄「升级」成小节标题，层级和样式都变。

**验证**：nav 条目 **332 → 414**（+82）、`toc.ncx` 415 条 · `3.8.1`/`18.11.1`/`5.9.1`
均已在目录里且中英对照 · 指标 6067/4893/1157/17/1838 **不变** · `bookscan` 0/0/0 ·
`eqcheck` exit 0 · `dbg_qa` **40 类不变** · regress **零变化**。

⚠ 这一条顺带解掉了 §6.6 里「23 条 EN 独有 `X.Y.1` 小节」的**用户可见部分** ——
它们的**标题与目录**现在都对了；`dbg_align_eval --sections` 仍会报 23 条，那是
**按编号匹配的统计口径**（中文侧确实没有编号），不是缺陷。

### 6.10 小节标题重复：merged 单元的原位判断（2026-09-17 22:3x，commit `414f84e`）

**病象**：同一行小节标题连着出现两遍（`dbg_qa` 的「④ 相邻重复标题」报 4 处）。
实测：附录 `A.1/B.1/C.1`（**英文**侧）+「参考文献」章里中文版独有的
「一位物理学家的概率观」（**中文**侧）。

**根因**：`merged` 单元（由多个带标题的小节合并而成，`pipeline.py:1514`）在章首
发 `h3`（首个分段标题），而该标题**可能已经在 `en_heads_at`/`zh_heads_at` 里** ——
原位会再发一次 `h4`。中文侧那处更绕：`split_sections` 把「一位物理学家的概率观」
当成了「参考文献」章的 `zh_title`，于是它被发在**章首**（位置也错）。

**修法**：查 `en_heads_at ∪ zh_heads_at` 的标题集合，**只发原位没有的那一侧**
（中英分别判断）。3.8「有放回抽样」那类**原位没有**的照旧发，不会丢。

**验证**：相邻重复标题 **4 → 0** · 标题块 **765 → 761** · `dbg_qa` **41 → 40 类**
（「相邻重复标题」整类消失，这是本轮第一次让 qa 类数下降）· 指标
6067/4893/1157/17/1838 **不变** · `bookscan` 0/0/0 · `eqcheck` exit 0 ·
regress **零变化**。

**排查手法**：`dump_notes.py --dupheads` 列出所有「连续两个标题文本相同」的位置
（`dbg_qa` 只给一个数，示例还取的是 `heads[1]`、容易误导）。

### 6.9 问句式中文小标题归位（2026-09-17 22:2x，commit `f913cac`）

英文原版有一批**问句小节名**：`18.11.1 Is indifference based on knowledge or
ignorance?`、`5.9.1 What is queer?`。中文照译也带问号，而
`pipeline.looks_like_zh_title` 的标点检查 `[。！？；，、.!?;,]` **见问号一律否决**
→ 判成正文段 → 成品里 `18.11.1` 的「无差别是基于知识还是无知？」成了
**带黄线的 `zh-orphan` 孤立段**，而不是 h4 标题。

**修法（写窄）**：豁免前先剥掉**末尾那一个**问号，其余部分仍不许有任何句读 ——
「注意：这样做，是因为……」这类中间带逗号的正文问句照样被否。

**验证**：`zh-orphan` **11 → 10** · 兜底渲染 **14 → 12** · `dbg_qa` 的**标题数
764 → 765**（+1，正是归位的那条）· 指标 6067/4893/1157/17/1838 **不变** ·
`bookscan` 0/0/0 · `eqcheck` exit 0 · regress **零变化**。

⚠ `looks_like_zh_title` 有 **3 个调用点**（`build.py:1185` 渲染层、
`pipeline.py:1134` 摘标题、`pipeline.py:1674` 小节标题链）—— 改它要三处一起想。

**剩下的 10 段 `zh-orphan` 是「真·未配对中文」**（小节末尾总结段、练习条目、
题词等），按设计**故意保留**（带黄线、可人工挑错），不是 bug。

### 6.8 修掉「中文小节标题重复渲染」（2026-09-17 22:1x，commit `82c43b6`）

**病象**：成品里同一句中文小标题出现**两次** —— 一次是 `h4.st.zh-h`（对），
一次是 `p.zh.zh_transed.zh-orphan`（重复）。实测 50 段，典型
`3.8.1「离题：关于现实与模型的说明」`、`1.5「蕴涵关系」`。

**根因**：`pipeline._extract_zh_titles` 把这类标题段**从 `p.zh` 里摘走**
（挂到 EN 原位标题旁渲染），但 `build.py` 的 orphan 判定
`_claimed = {j for _p in sec.pairs for j in (_p.zh or [])}` **只看 pairs** ——
摘走的段不在里面 → 被判「未配对的中文段」→ 兜底再渲染一次。

**修法**（纯渲染层，**不碰对齐决策、不 bump `_V`**）
1. `_claimed` 并入 `sec.zh_heads_at` 的段号；
2. 两处 `_zh_hp` 渲染（`build.py:1171` / `:1268`）补 `_emitted_zh.add(...)` ——
   标题已以 h4 发出，末尾「中文段是否全渲染」的自检不该再报它「丢失」
   （漏这步时自检会从 0 涨到 **36**，是假警报）。

**验证**：兜底渲染 **50 → 14** · 自检报警 **0** · 成品里
`离题：关于现实与模型的说明` 命中 **2 → 1**（且是正确的 h4）·
指标 6067/4893/1157/17/1838 **不变** · `bookscan` 0/0/0 · `eqcheck` exit 0 ·
regress **零变化**。

**排查手法（可复用）**：`grep -c "兜底渲染\|自检!" <build.log>` 两个计数
一起看 —— 单看「兜底渲染变少」会以为修好了，其实自检已经在喊「有段没渲染」；
**两个指标必须同时归零/回落才算真修好**。

### 6.7 修正 §3.3：无法复现，但查出一个相关的真 bug

**复现尝试全部落空**
- 第7章 = 成品 html 的 `id="ch8"`（offset 9214753）。它到下一个
  `<div class="notes">` 之间隔了 **17.7 MB** —— 即第7章**根本没有注释区**。
- 全书 `<div class="notes">` 只有 **2 个**（`ch25` 附录B、`ch29` 人名索引），
  `<b>[29]</b>` 命中 **0 处**。用户正式成品 `diag/样章/prob_全书_双语.html`
  更少（**1 个**，只有 `ch25`）⇒ ②④ 之后**反而多了一个**。
- `ch25` 那个「注释」是 **`cut_notes` 误判**：它的 `[1]` 文本 =
  源稿 17512 行「在本附录中, 我们提供了许多没有参考文献的简短引文…」，
  那是**附录B 正文的最后一段**，被当成注释从正文里摘走了。

**中文版的注释到底在哪**：**源稿里没有**。全书 grep
`^#{1,4} .*注释` 和 `^\s*注释\s*$` 均 **0 命中**；只有 145 处**悬空的**
圈码标记（`$^{①}$`，如源稿 126 行），**没有对应的注释正文**。
⇒ 「注释对不上」更可能是**源数据本身缺注释**，不是编号错位。

**⇒ 查出的真 bug**：`build.py:1424` 的 `if res.notes:` 把**英文兜底也挡在门内**。
该块的设计意图是（`:1428` 注释原文）「中文版注释可能少于英文（逆向版本不全）。
缺的条目用英文原文兜底，避免正文里的 [n] 指向空锚点」，但兜底循环
（`:1458` `for k in range(have, len(ids))`）写在 `if res.notes:` **里面** ——
中文版某章**一条注释都没有**时（`res.notes == []`），整块不渲染，
连 `note_ids` 里的英文原注也一起消失。
**修法**（未做，属内容决策）：`if res.notes or _ids:`，并把两个循环都留在块内。
⚠ 影响面要先估：EN 每章注释 20~30 条，全书 30 章 → 一次性多出近千条英文原注，
**必须先问用户要不要**。
