"""DeepSeek 计费：按 token 用量估算人民币成本。

价格表（元 / 百万 tokens，2026-09 官方）：

| 项目 | deepseek-flash 空闲 | flash 高峰 | v4-pro 空闲 | v4-pro 高峰 |
|---|---|---|---|---|
| 输入·缓存命中 | 0.02 | 0.04 | 0.15 | 0.30 |
| 输入·未命中   | 1.00 | 2.00 | 4.50 | 9.00 |
| 输出          | 4.00 | 8.00 | 13.5 | 27.0 |

高峰时段 = 北京时间周一至周五 9:00–12:00 与 14:00–18:00，其余为空闲（半价）。

注意：`deepseek-v4-flash` / `deepseek-v4-flash-vision-exp` 是已下线的旧名，
请求会被 V4.1-Flash 接走并按 Flash 价格计费，所以价格表按 `deepseek-flash` 归并。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

# (缓存命中输入, 未命中输入, 输出) —— 空闲时段单价
PRICES = {
    # qwen3.7-flash：**阶梯计费**，这里只登记「输入 ≤32k」那一档
    # （用户 2026-09-16 给的价格表）：
    #   输入 ¥0.2/M · 输出 ¥0.8/M · 输入(缓存命中) ¥0.04/M
    #   Batch File：输入 ¥0.1/M · 输出 ¥0.4/M（未用）
    # ⚠ **>32k 那一档的价格用户没给** → 超档时 report() 会显式警告。
    # 旧表（deepseek-flash 1.00/4.00）曾把成本**高估 3.5 倍**，别再拿它算 qwen。
    "qwen3.7-flash": (0.04, 0.20, 0.80),
    "deepseek-flash": (0.02, 1.00, 4.00),
    "deepseek-v4-pro": (0.15, 4.50, 13.5),
    "deepseek-reasoner": (0.02, 1.00, 4.00),
}
DEFAULT_PRICE = PRICES["deepseek-flash"]

# 旧模型名 → 现行计费档
ALIASES = {
    "deepseek-v4-flash": "deepseek-flash",
    "deepseek-v4-flash-vision-exp": "deepseek-flash",
    "deepseek-chat": "deepseek-flash",
}


def price_of(model: str) -> tuple[float, float, float]:
    m = (model or "").strip().lower()
    m = ALIASES.get(m, m)
    if m in PRICES:
        return PRICES[m]
    for key, val in PRICES.items():
        if key in m:
            return val
    return DEFAULT_PRICE


def is_peak(now: datetime | None = None) -> bool:
    """北京时间高峰时段判定（周一至周五 9-12 点、14-18 点）。"""
    t = now or datetime.now()
    if t.weekday() >= 5:          # 周六周日全天空闲
        return False
    return (9 <= t.hour < 12) or (14 <= t.hour < 18)


@dataclass
class Cost:
    model: str = ""
    peak: bool = False
    prompt_tokens: int = 0          # 全部输入
    cached_tokens: int = 0          # 其中缓存命中部分
    completion_tokens: int = 0
    reasoning_tokens: int = 0       # 其中思考（已含在 completion 里）
    prompt_cache_hit_tokens: int = 0
    calls: int = 0
    cache_hits: int = 0             # 本地缓存命中（未发起请求，不计费）

    def cny(self) -> float:
        """返回人民币成本。"""
        hit_p, miss_p, out_p = price_of(self.model)
        if self.peak:
            hit_p, miss_p, out_p = hit_p * 2, miss_p * 2, out_p * 2
        miss = max(0, self.prompt_tokens - self.cached_tokens)
        return (self.cached_tokens * hit_p
                + miss * miss_p
                + self.completion_tokens * out_p) / 1_000_000

    def saved_cny(self) -> float:
        """因缓存命中而省下的钱（相对全部按未命中价计）。"""
        hit_p, miss_p, out_p = price_of(self.model)
        if self.peak:
            hit_p, miss_p, out_p = hit_p * 2, miss_p * 2, out_p * 2
        return self.cached_tokens * (miss_p - hit_p) / 1_000_000

    def report(self) -> str:
        hit_p, miss_p, out_p = price_of(self.model)
        if self.peak:
            hit_p, miss_p, out_p = hit_p * 2, miss_p * 2, out_p * 2
        miss = max(0, self.prompt_tokens - self.cached_tokens)
        # 全部走本地磁盘缓存（未发请求）时，明确说清"这轮没花钱"
        if self.calls == 0 and self.cache_hits:
            return (f"[LLM 成本] 模型 {self.model or '?'} · "
                    f"{'高峰' if self.peak else '空闲'}时段\n"
                    f"  本次 {self.cache_hits} 次请求全部命中本地磁盘缓存，"
                    f"未产生 API 调用 → ¥0（未消耗额度）")
        lines = [
            f"[LLM 成本] 模型 {self.model or '?'} · "
            f"{'高峰时段' if self.peak else '空闲时段'} "
            f"(输入 {hit_p}/{miss_p} · 输出 {out_p} 元/百万)",
            f"  调用 {self.calls} 次（本地缓存命中 {self.cache_hits} 次，不计费）",
            f"  输入 {self.prompt_tokens:,} tok"
            f"（服务端缓存命中 {self.cached_tokens:,} · 未命中 {miss:,}）",
            f"  输出 {self.completion_tokens:,} tok"
            + (f"（其中思考 {self.reasoning_tokens:,}）"
               if self.reasoning_tokens else ""),
            f"  → 合计 ¥{self.cny():.4f}"
            + (f"（缓存已省 ¥{self.saved_cny():.4f}）"
               if self.cached_tokens else ""),
        ]
        if "qwen" in (self.model or "").lower() and self.prompt_tokens > 32000:
            lines.append("  ⚠ 输入超过 32k，已跨出「≤32k」档；该档价格**未确认**，"
                         "上面金额是按 ≤32k 档算的（只能当参考）")
        return "\n".join(lines)


def estimate(model: str, prompt_tokens: int, completion_tokens: int,
             cached_tokens: int = 0, peak: bool | None = None) -> Cost:
    """事前估算：给定预估 token 数，算出预计价格。"""
    return Cost(model=model,
                peak=is_peak() if peak is None else peak,
                prompt_tokens=prompt_tokens,
                cached_tokens=cached_tokens,
                completion_tokens=completion_tokens)
