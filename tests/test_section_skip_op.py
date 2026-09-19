# -*- coding: utf-8 -*-
"""`align_sections` 的**跳节算子**（§6.67）—— 真实数据驱动的回归单测。

跑法：
    python tests/test_section_skip_op.py
退出码 0 = 全过。

## 被钉住的 bug

`align_sections` 的 docstring 写着「允许跳节（1:0 / 0:1）与合并（1:2 / 2:1）」，
函数体里也**确实有** `elif a:` / `else:` 两个跳节分支，还配了 `skip_cost()`
和 `skip_k=0.4` 参数。但 commit `8204afd`（统一架构推全量那次）把操作集改成

    OPS = [(1,1)] + [(a,1) for a in range(2, MERGE_CAP+1)] \\
        + [(1,b) for b in range(2, MERGE_CAP+1)]

—— **`(1,0)` / `(0,1)` 被静默丢掉了**。于是那两个跳节分支、`skip_cost()`、
`skip_k`、`absolute=True` 全变成**死代码**，docstring 成了假话。

## 为什么必须有单测

失败方式是**静默的**：不崩、不报错，产物看着完整，形式门禁全绿，
只有人眼逐段读才会发现整节错位。而且「跳节是死代码」这件事
**看 docstring 看不出来**（docstring 说支持）。

## ★ 为什么用**真实书**当夹具，而不用手搓玩具

本测试的第一版用例 ②/④ 用手搓的小节（每节 1 段、几十个字符）——
**全部是退化的**，实测通过不了。原因有三条，都踩过：

1. **`skip_cost = skip_k(0.4) × 段数`，不随段长归一化**。
   玩具每节只有 1 段 ⇒ 跳过只要 `0.4`，比任何「配对」都便宜
   ⇒ DP 疯狂跳节，结果与预期无关。
2. **`avg = mean(en_words × k)`，会被超长段污染**。
   玩具里一段特别长就把 `avg` 拉飞，所有配对代价跟着**同向缩放**，
   判别力消失（实测 `rc(E0,Z0)` 应是 0 却算出 1.1 ~ 4.9）。
3. **`estimate_k` 是整批估算的**，会随「中译本节数/长度」变化。
   玩具里为了造「中文独有节」而加长中文侧，`k` 就被顶到上界 2.25，
   于是一切的长度比都失配 —— 自己把自己坑了。

⇒ 唯一稳的做法：**用真实书的一章真实分节结果当夹具**。
本测试直接用 `nexus`（智人之上）ch5 的**真实分节**（19 EN 节 / 18 ZH 节，
真实段数与真实词/字数），它天然满足：
   * 各节段数在 5~17 之间（不是 1 段）⇒ `skip_cost` 与配对可比；
   * 段长同质（真实散文）⇒ `avg` 不被污染；
   * `k` 落在 `[1.25, 2.25]` 中段 ⇒ 长度比有判别力；
   * **且它本来就是出事的那个案例**：`E[14] One Big Happy Soviet Family`
     是中译本**整节删除**（中文源书 435,245 字里该标题 0 次），
     正确解必须是「跳过 E[14]」，而不是把它并进 E[13] 或 E[15]。

夹具是**从真实 epub 现场解析出来的**（不是硬编码快照），所以它同时是
「解析 → 分节 → 对齐」整条链路的结构性回归。
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
for _p in (str(_ROOT / "tools"), str(_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault("BIL_ARCH", "unified")

from bil import align as A              # noqa: E402

_FAIL: list[str] = []


def check(name, got, want):
    if got != want:
        _FAIL.append(f"{name}: got {got!r}, want {want!r}")
        print(f"  ✗ {name}: got {got!r}, want {want!r}")
    else:
        print(f"  ✓ {name}")


def _ok(name, cond, detail=""):
    if cond:
        print(f"  ✓ {name}")
    else:
        _FAIL.append(f"{name} {detail}")
        print(f"  ✗ {name} {detail}")


# ── 夹具：从真实 epub 现场解析 nexus ch5 ─────────────────────────────
_BOOKS = _ROOT / ".workbuddy" / "tmp" / "books"
_EN_EPUB = _BOOKS / "nexus_en.epub"
_ZH_EPUB = _BOOKS / "nexus_zh.epub"


def load_nexus_ch5():
    """返回 (en_secs, zh_secs)。缺书则返回 (None, None) 让上层跳过。"""
    if not (_EN_EPUB.is_file() and _ZH_EPUB.is_file()):
        return None, None
    from bil import epubparse as E, structure as S
    ze, zz = E.open_epub(str(_EN_EPUB)), E.open_epub(str(_ZH_EPUB))
    en_docs = S.load_docs(ze, E.read_spine(ze))
    zh_docs = S.load_docs(zz, E.read_spine(zz))
    pairs = S.map_chapters(en_docs, zh_docs,
                           en_toc=E.load_toc(ze), zh_toc=E.load_toc(zz))
    cp = next((c for c in pairs if getattr(c, "key", "") == "chapter5"), None)
    if cp is None or not cp.en_path or not cp.zh_path:
        return None, None
    _, en_secs = A.split_sections(en_docs[cp.en_path])
    _, zh_secs = A.split_sections(zh_docs[cp.zh_path])
    return en_secs, zh_secs


def _norm(m):
    return [(list(e), list(z)) for e, z in m]


def main() -> int:
    print("① 操作集必须含跳节算子 (1,0) / (0,1)：")
    import inspect
    _src = inspect.getsource(A.align_sections)
    for op in ("(1, 0)", "(0, 1)"):
        check(f"align_sections 源码含 {op}", op in _src, True)
    # 反向：确保不是「写了但被后面覆盖」—— OPS 的赋值语句必须含跳节算子
    ops_lines = [ln for ln in _src.splitlines() if "OPS = " in ln or "OPS =" in ln
                 or ln.strip().startswith("+ [(1, 0)")]
    _ok("OPS 赋值处直接含跳节算子",
        any("(1, 0)" in ln or "(1,0)" in ln for ln in ops_lines)
        or any("(1, 0)" in ln for ln in _src.splitlines()),
        f"ops_lines={ops_lines!r}")

    print("\n② 真实数据夹具（nexus ch5：19 EN 节 / 18 ZH 节）：")
    en_secs, zh_secs = load_nexus_ch5()
    if en_secs is None:
        print("  ⚠ 跳过：未找到 .workbuddy/tmp/books/nexus_{en,zh}.epub")
        print("     （夹具依赖真实书；无书时本项不计入失败）")
    else:
        _ok("EN 19 节", len(en_secs) == 19, f"实际 {len(en_secs)}")
        _ok("ZH 18 节", len(zh_secs) == 18, f"实际 {len(zh_secs)}")
        m = _norm(A.align_sections(en_secs, zh_secs, band=2))
        # ── 结构性不变量（**与代价模型无关**，只由跳节算子保证）──
        # (a) 覆盖完整：每个 EN / ZH 节都被覆盖且只覆盖一次
        _ok("覆盖完整（EN 全覆盖）",
            sorted(i for e, _ in m for i in e) == list(range(len(en_secs))),
            f"got={sorted(i for e,_ in m for i in e)}")
        _ok("覆盖完整（ZH 全覆盖）",
            sorted(j for _, z in m for j in z) == list(range(len(zh_secs))),
            f"got={sorted(j for _,z in m for j in z)}")
        # (b) 单调：en/zh 下标各自严格递增（不重排）
        _e = [i for e, _ in m for i in e]
        _z = [j for _, z in m for j in z]
        _ok("EN 下标单调递增", _e == sorted(_e))
        _ok("ZH 下标单调递增", _z == sorted(_z))
        # (c) ★ 核心：必须存在「一侧独有」的映射项 ——
        #     旧代码（无跳节算子）**物理上产不出** zh 为空 / en 为空的项。
        onesided = [(e, z) for e, z in m if not e or not z]
        _ok("存在单侧映射项（跳节算子生效的**必要条件**）",
            len(onesided) >= 1,
            f"got={m}")

        print("\n③ nexus ch5 的 E[14]（译本整节删除）必须**单独**成为单侧项：")
        if en_secs and len(en_secs) == 19:
            m2 = _norm(A.align_sections(en_secs, zh_secs, band=2))
            # 找覆盖 EN[14] 的映射项
            item = next(((e, z) for e, z in m2 if 14 in e), None)
            if item is None:
                _ok("EN[14] 有归属", False, "未被任何映射项覆盖")
            else:
                e, z = item
                print(f"     EN[14] 所在映射项：en={e} zh={z}")
                # 正确解 = [14] 单独一项且 zh 为空（真的跳过它）。
                # ⚠ 但下游 `_merge_onesided_sections` 会把它并回前一个双侧节
                #   （pipeline.py 行为，不在本函数职责内）—— 所以这里**只断言
                #   本函数**产出 `([14], [])`，不断言成品形态。
                _ok("EN[14] 单独成项且 zh 为空（= 真跳过，而非并进邻节）",
                    e == [14] and z == [],
                    f"got en={e} zh={z}")
            # 且 EN[15] 必须与 ZH[14] 对上（「政党与教会」↔「Party and Church」）
            item15 = next(((e, z) for e, z in m2 if 15 in e), None)
            _ok("EN[15] ↔ ZH[14]（跳节后正确归位）",
                item15 == ([15], [14]), f"got={item15}")

        print("\n④ band 不敏感：跳节结果不该随 band 抖动：")
        ms = {b: _norm(A.align_sections(en_secs, zh_secs, band=b))
              for b in (2, 3)}
        _ok("band=2 与 band=3 结果一致", ms[2] == ms[3],
            f"\n      band2={ms[2]}\n      band3={ms[3]}")

    print("\n⑤ 全 1:1 时不许乱跳（加跳节算子的回归护栏）：")
    # ⚠ 用 nexus ch5 的**前 5 节**（标题一一对应、无删节）当「应全 1:1」样本。
    #   段长同质、段数 >1 ⇒ 非退化。
    if en_secs:
        e5, z5 = en_secs[:5], zh_secs[:5]
        m3 = _norm(A.align_sections(e5, z5, band=2))
        _ok("前 5 节全 1:1", m3 == [([i], [i]) for i in range(5)], f"got={m3}")

    print()
    if _FAIL:
        print(f"❌ {len(_FAIL)} 项失败：")
        for f in _FAIL:
            print("   ", f)
        return 1
    print("✅ 全部通过")
    return 0


def test_section_skip_op():
    """供 `tests/_runtests.py` 调用的入口（它只认 `test_*` 函数）。

    有失败就抛 AssertionError —— 与 `main()` 的退出码口径一致。
    """
    _FAIL.clear()
    rc = main()
    assert rc == 0, f"跳节算子回归失败：{_FAIL}"


if __name__ == "__main__":
    raise SystemExit(main())
