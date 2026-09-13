# book_bilingual_aligner

把一本**英文 epub** 和它的**中文译本 epub** 合成一本**段段对照的双语 epub** ——
英文当结构骨架，中文填血肉，逐段对齐，缺译的地方用 LLM 补上并明确标记。

![流水线](https://img.shields.io/badge/python-3.10%2B-blue)
![依赖](https://img.shields.io/badge/依赖-仅标准库-success)

---

## 这是什么

你手上有：

- 《Nexus: A Brief History of Information Networks from the Stone Age to AI》
- 它的中译本《智人之上》

想要的是：**一段英文、一段中文**，对照着读，而不是两个文件来回切。

这个工具做的就是这件事。它不是简单的"把两个 epub 拼起来"——中文译本常常
**章节结构被重排、段落被合并或拆分、注释不全、偶尔还漏译整段**。所以核心是
一套**跨语言对齐**算法，把两边按段落对上，再逐段渲染。

## 三个入口，按需选

| 入口 | 命令 | 适合 |
|---|---|---|
| **本地网页** | `python tools/app.py` → `http://127.0.0.1:8765` | 点按钮、看进度、下载，有文档侧边栏 |
| **命令行** | `python tools/run_book.py --all --llm --build` | 批量、脚本化、CI |
| **单文件** | `python tools/pack.py` → `dist/bilingual-epub.pyz` | 拷给同事 / 换机器，无需装依赖 |

## 快速开始

```bash
# 1) 配置 LLM（可选。不配也能跑，只是少了补译和勘误）
cp .env.example .env
#    编辑 .env，填 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL

# 2) 网页版（推荐先试这个）
python tools/app.py
#    浏览器打开 http://127.0.0.1:8765
#    页面上可以「LLM 设置」里直接填 key，不用改 .env

# 3) 或命令行跑全书
python tools/run_book.py --all --llm --build

# 4) 只看结构，不花钱
python tools/run_book.py --probe
```

产物在 `build/`，**文件名带书名**（`<书名>` = 中文版书名，如「智人之上：从石器时代到AI时代的信息网络简史」）：

| 文件 | 内容 |
|---|---|
| `<书名>_bilingual.epub` | **中英对照**（主产物） |
| `<书名>_中文.epub` | 仅中文（英文元素已物理删除，非 CSS 隐藏） |
| `<书名>_English.epub` | 仅英文（中文元素已物理删除） |
| `<书名>_bilingual.html` | 网页预览版，含三档阅读模式切换 |

元数据与封面**沿用中文版**：作者、出版社、出版日期、ISBN、封面图都从你上传的
中文 epub 里读出来原样带过去，不写死；书名自动加「（中英双语版）」后缀
（单语分册则是「（中文版）」/「（英文版）」）。

对照版里内置 **中英对照 / 仅中文 / 仅英文** 三档阅读模式，阅读器顶部一键切。

## 测试用小样本

不想每次跑 5MB 全书？从《智人之上》抽第 5 章做一个精简测试集：

```bash
python tools/make_test_ch5.py --build
```

产出 `build/test/`：

- `en_chapter5.epub` — 仅英文第 5 章（234 段）
- `zh_chapter5.epub` — 仅中文第 5 章（325 段）
- 加 `--build` 再生成双语成品

这两个文件直接拖进网页版就能跑，统计结果与全书一致
（脚注 126 / 切注 108 / 覆盖 214-214），但速度快很多。

## 不花钱也能验证

```bash
python tools/test_mock_llm.py
```

用假 LLM 跑通「小节映射 → 窗口细化 → 补译标记」全链路，零 token 消耗。

## 文档

启动网页版后，**左侧边栏 → 文档** 里可以直接读：

- 项目总览（本文件）
- 使用说明 — 三种用法的完整参数、常见问题
- 工具说明 — 模块划分、每层算法
- 技术设计 — 22 节设计文档，含对齐算法的取舍

## 项目结构

```
.
├── tools/
│   ├── run_book.py            CLI 主入口
│   ├── app.py                 本地网页版（标准库 http.server）
│   ├── pack.py                打包成单文件 .pyz / .exe
│   ├── probe_book.py          全书结构体检（不跑 LLM）
│   ├── make_test_ch5.py       抽取单章做测试样本
│   ├── test_mock_llm.py       假 LLM 跑通链路
│   └── bil/                   核心流水线
│       ├── epubparse.py       解压 / 分块
│       ├── structure.py       章级映射 + 小节映射
│       ├── align.py           段落对齐（DP + 比例校验）
│       ├── notes.py           注释回填（零 LLM 成本）
│       ├── llm.py             OpenAI 兼容客户端 + 缓存 + 限速
│       ├── pipeline.py        单章编排
│       ├── build.py           渲染 HTML / EPUB
│       └── pricing.py         成本估算
├── docs/使用说明.md
├── bilingual-epub-design-v2.md
├── .env.example               配置模板
└── build/                     产物（已 gitignore）
```

## 已知边界

- **中文译本的注释常不全**，某章实测只有 108/126 条。缺的用英文原注兜底并标记。
- **PDF 来源的中文版**（很多盗版电子书是 OCR 的）章节结构会很乱，`--probe` 先看一眼。
- 对齐不是 100% 完美的，个别小节会 FAIL。报告里会标出来，不是静默出错。
- 需要 **Python 3.10+**（用了 `X | None` 语法）。除此之外**零第三方依赖**。

## 许可

仅供个人学术研究使用。请自行确认对所处理书籍的使用权利。
