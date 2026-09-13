# 双语电子书流水线（bilingual-epub）

把「英文 epub（骨架）+ 中文 epub（血肉）」合成**段段对照的双语 epub**。
零第三方依赖，纯标准库；LLM 可选（没有 key 也能跑，缺的段落标记为「待补译」）。

> 完整使用说明见 [`docs/使用说明.md`](../docs/使用说明.md)；
> 技术设计与算法推导见 [`bilingual-epub-design-v2.md`](../bilingual-epub-design-v2.md)（22 节）。

## 三个入口

```bash
# ① 命令行
python tools/run_book.py --all --llm --build --title "智人之上 中英双语版"

# ② 本地网页版（点按钮、看进度、下载）
python tools/app.py                 # → http://127.0.0.1:8765

# ③ 单文件（打包后换机器也能跑）
python tools/pack.py --zipapp       # → dist/bilingual-epub.pyz（63 KB）
python dist/bilingual-epub.pyz web
```

## 快速开始

```bash
# 1) 结构体检：看两本书的章能不能对上、每章差多少段
python tools/probe_book.py

# 2) 只跑一章试试（不调 LLM）
python tools/run_book.py --chapters chapter1 --build

# 3) 全书 + LLM 细化与补译（会先打成本预估，跑完打结算）
cp .env.example .env      # 填入 LLM_API_KEY
python tools/run_book.py --all --llm --build --title "智人之上 中英双语版"

# 4) 换书
python tools/run_book.py --en /path/en.epub --zh /path/zh.epub --all --build

# 5) 出对照稿人工抽查
python tools/run_book.py --chapters chapter1,chapter5 --dump   # → review.md

# 6) 不花 token 验证 LLM 链路
python tools/test_mock_llm.py
```

输出（一次四个文件）：

- `build/bilingual.html` —— 浏览器预览，顶部「阅读模式」切 **中英对照 / 仅中文 / 仅英文**
- `build/bilingual.epub` —— 段段对照
- `build/chinese.epub` —— **仅中文**（生成时直接删掉英文元素，非 CSS 隐藏）
- `build/english.epub` —— **仅英文**（同理，中文元素已删除）

**注意**：必须在项目根目录执行（`.env` 按 CWD 解析，放 `tools/` 下读不到）。
章节 key 是 `chapter1` 而非 `ch1`，写错会静默跑 0 章。

## 流水线分层

| 层 | 做什么 | 是否要 LLM |
|---|---|---|
| 章级映射 | `Chapter N` ↔ `第N章`、序言/结语/致谢/Part 页；Notes/Index 跳过 | 不需要（对不上时才需要） |
| 注释区切分 | 从中文章尾反扫出尾注区（中文版常把尾注内联在正文里） | 不需要 |
| 小节映射 | 允许跳节 / 合并 / 拆分 | 数量不一致时调用 LLM，否则两层 DP |
| 段落对齐 | 单调 DP，信号 = 长度比 + 数字锚点；允许 1:1 / 1:N / N:1 / 1:0 / 0:1 | 不需要 |
| 体检门禁 | `r = 汉字数 / 英文词数`，越界即告警；小节失败率 > 20% 判 FAIL | 不需要 |
| 窗口细化 | 体检不达标的小节整节重对 | 需要 |
| 内容审查勘误 | 逐对判 `censor`/`skew`/`ok`，被删改的忠实补全 | 需要 |
| 补译 | 中文版删减/缺失的段落，单阶段直译，成品打「AI译」标记 | 需要 |
| 图位锚定 | 视觉元素按序位 `Visual(after=N)` 挂载，中英按序配对，缺图降级用英文原图 | 不需要 |
| 注释回填 | 从英文侧提取 `[n]` 位置，按比例映射 + 标点吸附插回中文段落 | **不需要，成本 ¥0** |

## 模块

- `tools/bil/epubparse.py` epub 解析 → 块序列（保留内层 HTML、抽取脚注引用）
- `tools/bil/structure.py` 章级映射与不变量
- `tools/bil/align.py` 注释边界检测、段落 DP、两层小节 DP
- `tools/bil/audit.py` 长度比体检门禁
- `tools/bil/notes.py` 注释标记提取与偏移量回填（零 LLM，见下）
- `tools/bil/pricing.py` 成本预估 / 结算（含高峰/空闲分档、别名归一）
- `tools/bil/llm.py` OpenAI 兼容客户端 + 磁盘缓存 + 三种能力（映射/细化/补译）
- `tools/bil/pipeline.py` 单章编排 + 守恒式对账
- `tools/bil/build.py` 渲染 epub / HTML 预览

入口与工具：

- `tools/run_book.py` CLI 主入口
- `tools/app.py` 本地网页版（标准库 `http.server`）
- `tools/pack.py` 打包为 `.pyz` / `.exe`
- `tools/probe_book.py` 结构体检；`tools/test_mock_llm.py` 自测

## 注释回填（zero-cost）

中文版注释区常不完整（逆向来源）。做法**完全不经过 LLM**：

1. 从英文章节的 `<a role="doc-noteref">` 提取 `(注释号, 纯文本偏移, 目标 id)`
2. 按段落长度比例把偏移映射到中文段，向前吸附到最近的句末标点
3. 中文段插入 `<a class="noteref" href="#chNnM"><sup>[M]</sup></a>`
4. 每章注释号从 1 重数，锚点带章前缀 `ch{i}` 防跨章撞车
5. 中文缺的注释条目用英文原注兜底，标「英文原注」

实测（《智人之上》）：577 个标记、404 段覆盖、610 个锚点、**0 悬空链接、¥0**。

## 成本控制

- 每次运行**先打印预估**（pair 数 / 请求数 / token / 金额）
- 输入命中磁盘缓存时结算显示 **¥0（未消耗额度）**
- 非工作日高峰时段自动按**半价**计（DeepSeek 分时定价）
- 所有翻译**单阶段完成，不做二次润色**（省 token）

## 已知边界

- 段落 DP 是单调的，**倒装（crossing）**只能靠 LLM 窗口细化修正（细化阶段允许非单调）。
- 中文源必须是「同一译本、章序一致」；扫描版 PDF 需先经 MinerU 转 md 再走同一 IR。
- 公式/代码较多的书（如《概率论沉思录》）仍需单独做渲染档位。
- `pairs` 数是「配对对象」数，不等于段落数（多对一会折叠），看 `覆盖 N/N` 才准。
