"""Valuation. Market cap and EV are rebuilt from the snapshot (price x shares),
not taken from yfinance's live `info`, so a back-dated snapshot stays point-in-time."""

from __future__ import annotations

from . import Annual, div


def market_cap(a: Annual, price: float | None):
    sh = a.shares(0)
    return None if sh is None or price is None else sh * price


def enterprise_value(a: Annual, price: float | None):
    mc = market_cap(a, price)
    debt = a.get("balance", "Total Debt")
    cash = a.get("balance", "Cash Cash Equivalents And Short Term Investments")
    if mc is None:
        return None
    return mc + (debt or 0.0) - (cash or 0.0)


# For banks/insurers debt is raw material and "free cash flow" is noise from
# lending/deposit flows, so EV and FCF are meaningless. Fall back to E/P.
FINANCIAL_SECTORS = {"Financial Services"}


def compute(a: Annual, price: float | None, sector: str | None = None) -> dict:
    mc = market_cap(a, price)
    ni = a.net_income(0)
    pe = div(mc, ni) if ni and ni > 0 else None  # undefined for losses
    if sector in FINANCIAL_SECTORS:
        return {
            "basis": "earnings/price (financials)",
            "market_cap": mc,
            "enterprise_value": None,
            "earnings_yield": div(ni, mc),
            "fcf_yield": None,
            "pe": pe,
        }
    ev = enterprise_value(a, price)
    return {
        "basis": "EBIT/EV",
        "market_cap": mc,
        "enterprise_value": ev,
        "earnings_yield": div(a.ebit(0), ev) if ev and ev > 0 else None,  # Greenblatt
        "fcf_yield": div(a.get("cashflow", "Free Cash Flow"), mc),
        "pe": pe,
    }
