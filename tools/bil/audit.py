"""提案 A：零成本体检门禁（回填前拦截）。

指标 r = 汉字数 / 英文词数。本书（Harari 智人之上）实测全局 ~1.9，
故判定区间取 [1.0, 3.0]；小节 bad rate > 20% → FAIL → 不进入回填（降级）。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AuditResult:
    total: int = 0
    bad: int = 0
    only_en: int = 0
    only_zh: int = 0
    multi: int = 0
    bad_items: list = field(default_factory=list)
    rate: float = 0.0
    verdict: str = "PASS"

    def as_row(self):
        return {
            "total": self.total, "bad": self.bad, "only_en": self.only_en,
            "only_zh": self.only_zh, "multi": self.multi,
            "rate": round(self.rate, 3), "verdict": self.verdict,
        }


def audit_pairs(pairs, en_paras, zh_paras,
                r_lo=1.0, r_hi=3.0, fail_rate=0.20) -> AuditResult:
    res = AuditResult(total=len(pairs))
    for idx, p in enumerate(pairs):
        bad = None
        if not p.en or not p.zh:
            if p.en:
                # 禁止翻译类（参考文献/纯符号/极短标记）不计 bad：它们本就
                # 不该有中文，报了反而是噪音（用户 2026-09-14 定）
                _txt = " ".join(en_paras[i].text for i in p.en
                                if isinstance(i, int) and 0 <= i < len(en_paras))
                try:
                    from . import epubparse as _E
                    if _E.no_translate_reason(_txt):
                        res.total_nt = getattr(res, "total_nt", 0) + 1
                        continue
                except Exception:                                  # noqa: BLE001
                    pass
                res.only_en += 1
                bad = ("only_en", p.r)
            else:
                res.only_zh += 1
                bad = ("only_zh", p.r)
        else:
            if len(p.zh) > 1 or len(p.en) > 1:
                res.multi += 1
            if not (r_lo <= p.r <= r_hi):
                bad = ("ratio", p.r)
        if bad:
            res.bad += 1
            res.bad_items.append((idx, bad[0], round(bad[1], 2)))
    res.rate = res.bad / max(1, res.total)
    res.verdict = "FAIL" if res.rate > fail_rate else "PASS"
    return res
