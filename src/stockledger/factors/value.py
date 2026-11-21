"""Valuation. Market cap and EV are rebuilt from the snapshot (price x shares),
not taken from yfinance's live `info`, so a back-dated snapshot stays point-in-time.

Foreign filers (e.g. TSM: statements in TWD, ADS quoted in USD) pass a
`bridge` from `snapshot.currency_bridge`. Statement amounts are converted into
the quote currency at the as-of FX rate, and the ordinary share count is
divided by the ADS ratio before multiplying by the ADS price. Without both a
rate and a ratio, every valuation metric is None: mixing currencies would
silently inflate yields by the exchange rate (about 33x for TWD).
"""

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


class _Converted(Annual):
    """Annual statements restated in the quote currency, shares in quote units."""

    def __init__(self, a: Annual, fx: float, shares_per_unit: float):
        self.periods, self._s = a.periods, a._s
        self._fx, self._per = fx, shares_per_unit

    def get(self, stmt, field, i=0):
        v = super().get(stmt, field, i)
        if v is None:
            return None
        if field == "Ordinary Shares Number":
            return v / self._per
        return v * self._fx


def _unavailable(basis: str, reason: str, bridge: dict) -> dict:
    return {"basis": basis, "market_cap": None, "enterprise_value": None,
            "earnings_yield": None, "fcf_yield": None, "pe": None,
            "currency": {**bridge, "converted": False, "reason": reason}}


def compute(a: Annual, price: float | None, sector: str | None = None,
            bridge: dict | None = None) -> dict:
    if bridge is not None:
        basis = "earnings/price (financials)" if sector in FINANCIAL_SECTORS else "EBIT/EV"
        if not bridge.get("fx_rate"):
            return _unavailable(basis, f"no {bridge['financial']}->{bridge['price']} rate on or before as-of", bridge)
        if not bridge.get("shares_per_price_unit"):
            return _unavailable(basis, "shares per quoted unit (ADS ratio) unknown", bridge)
        out = compute(_Converted(a, bridge["fx_rate"], bridge["shares_per_price_unit"]), price, sector)
        out["currency"] = {**bridge, "converted": True, "reason": None}
        return out

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
