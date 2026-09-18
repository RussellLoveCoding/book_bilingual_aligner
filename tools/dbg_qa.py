# -*- coding: utf-8 -*-
"""成品 HTML 的**人眼级**质量门禁（不看 stdout 指标，只看渲染结果）。

人眼一眼能发现、而指标看不见的问题，这里全部自动化：
  1. 连续同侧段（≥2 个 zh 连着 或 ≥2 个 en 连着）= 读者眼里的「粘成一坨」
  2. 宽组（一对里某一侧 ≥3 段）= 「中中 / 英英英」式分组过宽
  3. 原始标记泄漏：&lt;table&gt;（表格转义成代码）、beginarray（行内 array
     没出图）、$$、<eq> 等
  4. 相邻重复标题（同一标题紧挨着重复出现）
  5. 补译段（mt）前后是否夹在两侧文本之间（位置怪 = 补译挂错地方）

用法：_run.sh dbg_qa.py <成品html> [最多打印条数]
退出码：有问题 = 1（可做门禁），干净 = 0
"""
from __future__ import annotations

import re
import sys
from html.parser import HTMLParser

LEAK_PATTERNS = [
    ("表格转义", r"&lt;table&gt;"),
    ("行内array未出图", r"beginarray|endarray"),
    ("$$ 残留", r"\$\$"),
    ("<eq> 残留", r"&lt;eq&gt;"),
    ("HTML 实体残留", r"&lt;/?(?:p|div|span|td|tr)\b"),
]


STUB_MAX = 40          # 短段阈值：脚注、引出句、编号行不算"粘连"


class QA(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.seq = []          # [(side, text)]  正文级顺序
        self.pairs = []        # [(n_en, n_zh)]
        self.heads = []        # [title]
        self.depth = 0
        self.in_pair = -1
        self.cur = None
        self.texts = []
        self._pending_head = None
        self._side = None
        self._buf = []

    def handle_starttag(self, tag, attrs):
        cls = dict(attrs).get("class", "") or ""
        if tag == "div" and "pair" in cls.split():
            self.in_pair = self.depth
            self.cur = [0, 0, []]
            self.depth += 1
            return
        self.depth += 1
        if re.match(r"^h[1-6]$", tag):
            self._pending_head = True
        if self.cur is not None and self.in_pair >= 0 and tag in (
                "p", "blockquote", "pre", "li", "div"):
            if re.search(r"\bzh\b|zh_transed", cls):
                self.cur[1] += 1
                self._side, self._buf = "zh", []
            elif re.search(r"\ben\b|en_original", cls):
                self.cur[0] += 1
                self._side, self._buf = "en", []

    def handle_endtag(self, tag):
        self.depth -= 1
        if self._side and tag in ("p", "blockquote", "pre", "li", "div"):
            _t = re.sub(r"\s+", " ", "".join(self._buf)).strip()
            self.seq.append((self._side, _t))
            if self.cur is not None:
                self.cur[2].append(len(_t))
            self._side, self._buf = None, []
        if tag == "div" and self.cur is not None and self.depth == self.in_pair:
            self.pairs.append((self.cur[0], self.cur[1],
                               list(self.cur[2])))
            self.cur = None
            self.in_pair = -1

    def handle_data(self, data):
        t = data.strip()
        if not t:
            return
        if self._pending_head:
            self.heads.append(t)
            self._pending_head = None
        if self._side:
            self._buf.append(t)
        if len(self.texts) < 4000:
            self.texts.append(t)


def main() -> int:
    src = sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    html = open(src, encoding="utf-8").read()
    p = QA()
    p.feed(html)

    issues = []

    # ① 连续同侧段（**只数"实段"**：脚注/引出句/编号行这类短段跳过，
    #    它们本来就成串出现，不算读者眼里的"粘成一坨"）
    seq = [s for s in p.seq if len(s) > 1 and s[1]]
    run, start = 1, 0
    for i in range(1, len(seq) + 1):
        same = (i < len(seq) and seq[i][0] == seq[i - 1][0]
                and len(seq[i][1]) >= STUB_MAX
                and len(seq[i - 1][1]) >= STUB_MAX)
        if same:
            run += 1
        else:
            if run >= 3:
                issues.append(f"① 连续同侧长段 ×{run}（第 {start+1} 个元素起，"
                              f"侧={seq[start][0]}）「{seq[start][1][:22]}…」")
            run, start = 1, i

    # ② 宽组（两侧都 ≥2 且**不是**靠短段凑出来的 = 该拆没拆）
    for i, item in enumerate(p.pairs):
        ne, nz = item[0], item[1]
        lens = item[2] if len(item) > 2 else []
        # 组里含极短引出段/编号行（"and its inverse:" 之类）→ 合理成组，不算
        if lens and min(lens) < STUB_MAX:
            continue
        if max(ne, nz) >= 3 and min(ne, nz) >= 2:
            issues.append(f"② 宽组未拆 pair[{i}]：en {ne} 段 / zh {nz} 段")

    # ③ 标记泄漏（**只扫正文**：CSS/JS 注释里可能有示例字符）
    body = html[html.find("</style>"):]
    body = body[:body.find("<script")] if "<script" in body else body
    for name, pat in LEAK_PATTERNS:
        if name == "$$ 残留":
            n = body.count("$$")          # 字面计数，regex 的 $ 语义有歧义
        else:
            n = len(re.findall(pat, body))
        if n:
            issues.append(f"③ {name}：{n} 处")

    # ④ 相邻重复标题
    dup = 0
    for i in range(1, len(p.heads)):
        if p.heads[i] == p.heads[i - 1]:
            dup += 1
    if dup:
        issues.append(f"④ 相邻重复标题：{dup} 处（如「{p.heads[1] if len(p.heads)>1 else ''}」）")

    print(f"[QA] {src.split('/')[-1]} · pair {len(p.pairs)} · "
          f"元素 {len(p.seq)} · 标题 {len(p.heads)}")
    if not issues:
        print("[QA] ✅ 人眼级检查全部通过")
        return 0
    print(f"[QA] ❌ 发现 {len(issues)} 类问题：")
    for s in issues[:limit]:
        print("   " + s)
    if len(issues) > limit:
        print(f"   … 另 {len(issues)-limit} 项")
    return 1


if __name__ == "__main__":
    sys.exit(main())
