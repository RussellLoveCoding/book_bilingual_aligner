# tests/ —— 测试数据

这个目录**入库**（`.workbuddy/` 整个被 gitignore，测试数据放那里等于不存在）。
**源书不在仓库里**（版权 + 体积），仍留在 `.workbuddy/tmp/books/`，需自备。

## `tests/gold/` —— 金标准（ground truth）

> 定调：**金标准由我逐条推理产出，不外包给 LLM。** 这里的 `.md` 是确定性解析 +
> 人工核对的结果，`.yaml` 是逐条推理出的配对。

| 文件 | 是什么 | 怎么生成 |
|---|---|---|
| `GOLD_ALL.md` | **四本书「章 + 小节」全量清单**（合订，含章级对照表/逐章小节/汇总） | `tools/mk_gold_doc.py` |
| `TOC_<book>.md` | 同上，单本：`prob` / `ml` / `think2` / `nexus` | 同上 |
| `prob_gold.yaml` | prob 章+小节金标准（我逐条核过 717 条） | 人工 |
| `think2_ml_nexus_gold.yaml` | think2 / ml / nexus 的章级金标准 | 人工 |
| `gold_toc.md` | 金标准目录的可读稿（章级配对 + 例外说明） | 人工 |
| `nexus_toc.md` | Nexus 两侧章+小节目录（含 nav/ncx 实况） | `tools/dbg_nexus_toc.py` |
| `<book>_<side>_L<2\|3\|5>.txt` | 紧凑清单 `编号\|层级\|front\|文本`，喂给章级评估 | `tools/dbg_gold.py --dump --max-level N` |

**章级评估**（`tools/dbg_align_eval.py --all`）读的就是 `*_L2/_L3/_L5.txt`。

## `tests/t2/` —— T2（章内小节对齐）的报文与 LLM 输出

| 文件 | 是什么 |
|---|---|
| `T2_REPORT_v2.md` | **当前版本**的报告（四本书各抽 1 章，40/40 与金标准一致） |
| `<book>_ch<N>_payload.txt` | 发给 LLM 的完整报文（system + user），供人审 |
| `<book>_ch<N>_result.json` | LLM 的原始 JSON 输出 |
| `T2_REPORT.md` / `GOLD.yaml` | v1 的遗留件（旧工具生成，仅留档） |

抽测章固定在 `tools/t2_test.py` 的 `SAMPLE`：`nexus:1 · think2:5 · prob:8 · ml:4`。
**每本只跑 1 章**——不要写成"全量"，更不要在没报预估并获准的情况下整书跑。

## `tests/t1/` —— T1（章级标题对齐）四源合并 → LLM → 与金标准对分

| 文件 | 是什么 |
|---|---|
| `T1_REPORT.md` | 四本书的报告：token/价格估算 + 配对结果 + 与金标准对分的 TP/FP/FN + 漏配明细 |
| `<book>_result.json` | LLM 的原始配对输出 |
| `_estimate.txt` | 发请求前的估算留档 |

**v3 起改用项目自带的 `cli.map_titles()` 内核**（只传「序号|标题|段数」，
回 index mapping；四本合计 2.28 秒 / 3,819 输入 + 890 输出 token ≈ ¥0.0015）。
v2 手搓报文（整本四源候选 + 自造 schema）已被判定为错误做法，四本要 7.5 分钟
且 prob 输出会被截断 —— 细节见 `docs/性能记录.md`。
**未启用等分切割（T3）**。

## `tests/t2/` —— T2（章内小节对齐）

| 文件 | 是什么 |
|---|---|
| `T2_REPORT.md` | 每本的章对数 / 配出对 / **精度** / **覆盖**（表格） |
| `T2_SECTIONS.tsv` | **一行一章对，9 列**：`book ei zj label st np tp fp cap` |
| `<book>_ch<N>_*.txt/json` | v1 遗留件（旧工具生成，仅留档） |

指标定义（都在 `tools/t2_test.py::score`）：
- **精度** = LLM 配出的对里，两侧都在金标准里的比例（**四本已全 100%**）
- **覆盖** = `min(tp, cap) / cap`，`cap = min(EN金标准, ZH金标准)`。
  ⚠ 用 `min` 是因为两版结构可能不对称（ml 第2章英文 35 条、中文 13 条）；
  用**配对级**是因为 LLM 可以合法做多对一合并。

## 工具（本轮新增）
```
tools/t1_align.py     T1 章级：units() 出标题表 → cli.map_titles → 对分
tools/t2_test.py      T2 节级：section_candidates → cli.map_sections_many(16 线程) → 对分
tools/dbg_t2_fp.py    打印 T2 匹配失败明细（连候选标签 h3/h5/css，判断是噪音还是真错配）
tools/dbg_time.py     逐步计时（量「非 LLM 的活」到底花在哪）
tools/mk_gold_doc.py  四本书章+小节全量目录
tools/dbg_doc_order.py 按文档顺序导出标题候选
```

## 重跑

```bash
P=/mnt/c/Users/abc/WorkBuddy/2026-09-12-13-08-31
wsl.exe -- bash $P/tools/_run.sh mk_gold_doc.py          # 重新生成 tests/gold/TOC_*.md（免费）
wsl.exe -- bash $P/tools/_run.sh dbg_align_eval.py --all # 章级评估（免费）
wsl.exe -- bash $P/tools/_run.sh t2_test.py --all --dry  # 只出报文（免费）
wsl.exe -- bash $P/tools/_run.sh t2_test.py --all --llm  # T2 真调 LLM（4 次 ≈ ¥0.02）
wsl.exe -- bash $P/tools/_run.sh t1_align.py --all        # T1 只估算 token/价格（免费）
wsl.exe -- bash $P/tools/_run.sh t1_align.py --all --llm  # T1 真调 LLM（4 次 ≈ ¥0.2）
```
