"""Price-based factors: 12-1 momentum, trend, extension, volatility, drawdown."""

from __future__ import annotations

import math

TRADING_DAYS = 252
SKIP_MONTH = 21


def sma(xs: list[float], n: int):
    return sum(xs[-n:]) / n if len(xs) >= n else None


def atr(high: list[float], low: list[float], close: list[float], n: int = 14):
    if len(close) < n + 1:
        return None
    trs = [
        max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
        for i in range(len(close) - n, len(close))
    ]
    return sum(trs) / n


def momentum_12_1(close: list[float]):
    """Return from t-252 to t-21 (Jegadeesh & Titman; skips the reversal month)."""
    if len(close) < TRADING_DAYS + 1:
        return None
    return close[-1 - SKIP_MONTH] / close[-1 - TRADING_DAYS] - 1


def volatility(close: list[float], n: int = TRADING_DAYS):
    if len(close) < n + 1:
        return None
    window = close[-(n + 1):]
    rets = [math.log(window[i] / window[i - 1]) for i in range(1, len(window))]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(TRADING_DAYS)


def max_drawdown(close: list[float], n: int = TRADING_DAYS):
    if len(close) < 2:
        return None
    window = close[-n:]
    peak, mdd = window[0], 0.0
    for c in window:
        peak = max(peak, c)
        mdd = min(mdd, c / peak - 1)
    return mdd


def compute(prices: dict, bench: dict) -> dict:
    c, h, lo = prices["close"], prices["high"], prices["low"]
    last = c[-1] if c else None
    ma50, ma200, a14 = sma(c, 50), sma(c, 200), atr(h, lo, c)
    mom, bmom = momentum_12_1(c), momentum_12_1(bench["close"])
    return {
        "price": last,
        "ma50": ma50,
        "ma200": ma200,
        "price_vs_ma200": last / ma200 - 1 if last and ma200 else None,
        "atr14": a14,
        # how many ATRs above the 50-day mean we are: the "don't chase" gauge
        "extension_atr": (last - ma50) / a14 if last and ma50 and a14 else None,
        "momentum_12_1": mom,
        "relative_momentum_12_1": mom - bmom if mom is not None and bmom is not None else None,
        "volatility_1y": volatility(c),
        "max_drawdown_1y": max_drawdown(c),
    }
