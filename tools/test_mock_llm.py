"""不花 token 验证 LLM 接入链路：用假 client 跑通 小节映射 / 窗口细化 / 补译标记。

  python tools/test_mock_llm.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE), str(_HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from bil import pipeline as P
from bil import build as B
from run_book import load_all


class MockLLM:
    """实现与 bil.llm.LLM 相同的三个方法，返回合法输出。"""

    enabled = True
    calls = {"map": 0, "refine": 0, "translate": 0}

    def map_sections(self, en_titles, zh_titles, en_counts=None, zh_counts=None):
        self.calls["map"] += 1
        # 模拟：英文第 14 节在中文版缺失
        out = []
        e = z = 0
        while e < len(en_titles) or z < len(zh_titles):
            if e == 14 and len(en_titles) != len(zh_titles):
                out.append([e, None])
                e += 1
                continue
            out.append([e, z])
            e += 1
            z += 1
        return [(a if a is None else [a], b if b is None else [b]) for a, b in out]

    def refine_window(self, en_lines, zh_lines, locked_before="", locked_after=""):
        self.calls["refine"] += 1
        out = []
        for i in range(max(len(en_lines), len(zh_lines))):
            e = [i + 1] if i < len(en_lines) else []
            z = [i + 1] if i < len(zh_lines) else []
            if e or z:
                out.append([e, z])
        return out

    def translate(self, en_texts, context="", title=""):
        self.calls["translate"] += 1
        return [f"［模拟译文］{t[:24]}…" for t in en_texts]


def main():
    en_docs, zh_docs, pairs = load_all()
    cp = [c for c in pairs if c.key == "chapter5"][0]
    llm = MockLLM()
    res = P.process_chapter(en_docs[cp.en_path], zh_docs[cp.zh_path],
                            key="chapter5", llm=llm)
    before = P.summarize(res)
    st = P.apply_llm(res, llm, title="Chapter 5")
    after = P.summarize(res)
    P.print_report(res)

    print(f"\n小节映射来源：{res.stats['section_map']}")
    print(f"LLM 调用：{llm.calls}")
    print(f"补译前 缺中文 {before['only_en']} → 补译后 缺中文 "
          f"{sum(1 for s in res.sections for p in s.pairs if p.en and not p.zh and not p.mt)}"
          f"（已由 mt 填充 {st['mt']} 段）")

    mt_pairs = [(s.en_title, p) for s in res.sections for p in s.pairs if p.mt]
    assert mt_pairs, "补译未生效"
    html = B.render_chapter(res)
    assert "AI译" in html, "渲染缺少 AI译 标记"
    assert "待补译" not in html, "仍有未补译段落漏出（应为 0）"
    print(f"\n渲染检查：AI译标记 {html.count('AI译')} 处；"
          f"待补译占位 {html.count('待补译')} 处")
    print("OK：LLM 链路（映射 → 细化 → 补译 → 标记）跑通。")


if __name__ == "__main__":
    main()
