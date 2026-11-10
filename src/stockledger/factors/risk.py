"""Balance-sheet risk: Altman Z'' (non-manufacturer / emerging-market variant)."""

from __future__ import annotations

from . import Annual, div

# Altman Z'' does not apply to banks/insurers: their balance sheets are the business.
NOT_APPLICABLE_SECTORS = {"Financial Services", "Real Estate"}
DISTRESS, SAFE = 1.10, 2.60


def altman_z2(a: Annual, sector: str | None) -> dict:
    """Z'' = 6.56 X1 + 3.26 X2 + 6.72 X3 + 1.05 X4 (Altman 1995/2000).

    Chosen over the original 1968 Z because it drops the sales/assets term
    (very industry-dependent) and the market-cap term (keeps it fundamental).
    """
    if sector in NOT_APPLICABLE_SECTORS:
        return {"value": None, "zone": "n/a", "reason": f"not applicable to {sector}"}
    ta = a.total_assets(0)
    wc = None
    ca, cl = a.get("balance", "Current Assets"), a.get("balance", "Current Liabilities")
    if ca is not None and cl is not None:
        wc = ca - cl
    x1 = div(wc, ta)
    x2 = div(a.get("balance", "Retained Earnings"), ta)
    x3 = div(a.ebit(0), ta)
    x4 = div(a.get("balance", "Stockholders Equity"),
             a.get("balance", "Total Liabilities Net Minority Interest"))
    if None in (x1, x2, x3, x4):
        return {"value": None, "zone": "unknown", "reason": "missing inputs"}
    z = 6.56 * x1 + 3.26 * x2 + 6.72 * x3 + 1.05 * x4
    zone = "distress" if z < DISTRESS else "safe" if z > SAFE else "grey"
    return {"value": z, "zone": zone, "components": {"x1": x1, "x2": x2, "x3": x3, "x4": x4}}


def compute(a: Annual, sector: str | None) -> dict:
    return {"altman_z2": altman_z2(a, sector)}
