"""Pure factor functions. Input: snapshot dict. Output: plain dicts of floats.

Conventions:
- index 0 = most recent annual period, 1 = prior year, ...
- any missing input -> the metric is None (never guessed, never zero-filled)
"""

from __future__ import annotations


class Annual:
    """Read-only accessor over snapshot['annual']."""

    def __init__(self, snap: dict):
        a = snap["annual"]
        self.periods: list[str] = a["periods"]
        self._s = {"income": a["income"], "balance": a["balance"], "cashflow": a["cashflow"]}

    def __len__(self) -> int:
        return len(self.periods)

    def get(self, stmt: str, field: str, i: int = 0) -> float | None:
        col = self._s[stmt].get(field)
        if col is None or i >= len(col):
            return None
        return col[i]

    # frequently used, with sensible fallbacks
    def revenue(self, i=0):
        return self.get("income", "Total Revenue", i)

    def gross_profit(self, i=0):
        gp = self.get("income", "Gross Profit", i)
        if gp is not None:
            return gp
        return sub(self.revenue(i), self.get("income", "Cost Of Revenue", i))

    def ebit(self, i=0):
        # Prefer operating income: yfinance's "EBIT" includes non-operating
        # one-offs (e.g. gains on debt extinguishment) that can make a
        # loss-making business look cheap.
        v = self.get("income", "Operating Income", i)
        return v if v is not None else self.get("income", "EBIT", i)

    def net_income(self, i=0):
        return self.get("income", "Net Income", i)

    def total_assets(self, i=0):
        return self.get("balance", "Total Assets", i)

    def cfo(self, i=0):
        return self.get("cashflow", "Operating Cash Flow", i)

    def shares(self, i=0):
        return self.get("balance", "Ordinary Shares Number", i)


def div(a, b):
    if a is None or b is None or b == 0:
        return None
    return a / b


def sub(a, b):
    if a is None or b is None:
        return None
    return a - b


def gt(a, b):
    """a > b, or None if either side is unknown."""
    if a is None or b is None:
        return None
    return a > b
