r"""漂移尺子的编号抽取不许被「标记造成的空白」骗（§6.58）—— 常驻回归。

背景（2026-09-19，§6.16(3) 第 7 次「尺子自己错了」）：
`dbg_drift.py` 报 ML 全书「B 漂移 103」，抽样第一眼就是

    EN: Equation 2-1.  Root mean square error (RMSE)
    ZH: 公  式  2  -  1  ：  均  方  根  误  差

——**这对是对的**。成因：`_clean` 把标记换成空格，而中文侧的公式号是
**逐字符 span 包裹**的，于是 `公式 4-10` 在文本里成了 `公 式 4 - 1 0`：
不光分隔符被切开，**多位数 `10` 也被切成 `1 0`**。
`_NUM_RE` 要求编号中间无空白 → 抽不到 / 抽出错的 `4.1` → 把正确配对误报成漂移。

实测：ML 全书 DRIFT **103 → 26**（77 格、75% 是这一条造成的假警报）。

修法：编号抽取前，只合并 `[0-9.\-–—]` **之间**的空白；不做全量去空白
（那会把 `Figure 3-5. The` 的句号与下一句粘成假编号）。
⚠ 必须**两侧同时**生效 —— 只放宽中文侧会凭空造出 MISATTR 假警报。

本测试同时守**两个方向**：假警报要消掉，真漂移仍要报出来（防「修过头」）。

退出码：0 = 全对；1 = 有误判。
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
import dbg_drift as D          # noqa: E402

FAILS: list[str] = []


def check(name: str, got, want) -> None:
    if got != want:
        FAILS.append(f"{name}\n     got  = {got!r}\n     want = {want!r}")


def nums(t: str) -> set:
    return D._sig_of(t)["num"]


# ---------------------------------------------------------------- ① 抽取层
# 标记把「分隔符」和「多位数的各位」都切开了 —— 都必须能还原
check("公式号（中文，逐字符 span）", nums("公  式  4  -  1  0  ：  Lasso"), {"4.10"})
check("公式号（英文，连字符）", nums("Equation 4-10.  Lasso regression"), {"4.10"})
check("图号（中文，无空格）", nums("图2-13告诉你，房价与地理位置"), {"2.13"})
check("图号（中文，被切开）", nums("图  2  -  1  3  告诉你"), {"2.13"})
check("小节号（中文，带空格）", nums("3  .  3  .  4    准  确  率"), {"3.3.4"})
check("纯英文基线（回归）", nums("See Figure 3-5 and Table 2.1"), {"3.5", "2.1"})

# 反向：不许把「句末句号 + 下一句」粘成假编号
check("句号不许粘下一句", nums("Figure 3-5. The next step"), {"3.5"})
check("小数点不许跨句", nums("about 3.  Then we go"), set())
check("无编号就是无编号", nums("这一节没有任何编号"), set())

# ---------------------------------------------------------------- ② 判定层
HTML = """<html><body>
<div class="pair"><p class="en">Equation 2-1.  Root mean square error (RMSE)</p>
<p class="zh zh_transed"><span>公</span><span>式</span> 2 - 1 ： 均方根误差</p></div>
<div class="pair"><p class="en">A plain paragraph with no numbering at all here.</p>
<p class="zh zh_transed">一段没有任何编号的中文正文，长度也够。</p></div>
<div class="pair"><p class="en">See Figure 9-9 for the architecture overview.</p>
<p class="zh zh_transed">这一段的中文和上面的英文毫无关系，是别处的译文。</p></div>
<div class="pair"><p class="en">Unrelated english paragraph number four.</p>
<p class="zh zh_transed">图9-9：与上面英文无关的图注，编号落在邻格。</p></div>
</body></html>"""

cells = D.parse(HTML)
check("解析出 4 个 pair", len(cells), 4)

verdicts = D.judge(cells, win=2, kinds=("num", "eq", "quot"))
flagged = {c.i: k for k, _, c in verdicts if k in ("DRIFT", "MISATTR")}

# ① 号 pair 是**正确配对**（公式 2-1 ↔ 公式 2-1）→ 绝不许点名
if 0 in flagged:
    FAILS.append(f"假警报未消：pair0（公式 2-1 正确配对）被报成 {flagged[0]}")
# ② 号 pair 无编号 → 不许点名
if 1 in flagged:
    FAILS.append(f"假警报：pair1（无编号）被报成 {flagged[1]}")
# ③ 号 pair 的 EN 编号 9-9 落在 ④ 号 pair 的 ZH 里 → **必须**报 DRIFT
if flagged.get(2) != "DRIFT":
    FAILS.append(f"真漂移漏报：pair2 应为 DRIFT，实得 {flagged.get(2)}")

if FAILS:
    print(f"✗ 漂移尺子：{len(FAILS)} 项不合格\n")
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print("✓ 漂移尺子编号抽取：8 项抽取 + 4 项判定，全部通过")
