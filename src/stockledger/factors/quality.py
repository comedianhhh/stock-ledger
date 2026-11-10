"""Quality factors: Piotroski F-score, gross profitability, return on capital."""

from __future__ import annotations

from . import Annual, div, gt, sub


def _roa(a: Annual, i: int):
    # Piotroski uses beginning-of-year assets.
    return div(a.net_income(i), a.total_assets(i + 1))


def piotroski(a: Annual) -> dict:
    """Piotroski (2000) F-score. Each check is True/False, or None if data is missing.

    `ratio` = passed / evaluated, so a missing input lowers confidence, not the score.
    """
    ltd = lambda i: a.get("balance", "Long Term Debt", i) or 0.0  # noqa: E731  (no LTD == zero LTD)
    cur_ratio = lambda i: div(a.get("balance", "Current Assets", i),  # noqa: E731
                              a.get("balance", "Current Liabilities", i))
    gm = lambda i: div(a.gross_profit(i), a.revenue(i))  # noqa: E731
    turnover = lambda i: div(a.revenue(i), a.total_assets(i + 1))  # noqa: E731
    lev = lambda i: div(ltd(i), a.total_assets(i)) if a.total_assets(i) else None  # noqa: E731

    checks = {
        "roa_positive": gt(_roa(a, 0), 0),
        "cfo_positive": gt(a.cfo(0), 0),
        "roa_improving": gt(_roa(a, 0), _roa(a, 1)),
        "cfo_exceeds_net_income": gt(a.cfo(0), a.net_income(0)),
        "leverage_falling": None if lev(0) is None or lev(1) is None else lev(0) <= lev(1),
        "current_ratio_improving": gt(cur_ratio(0), cur_ratio(1)),
        "no_dilution": None if a.shares(0) is None or a.shares(1) is None else a.shares(0) <= a.shares(1),
        "gross_margin_improving": gt(gm(0), gm(1)),
        "asset_turnover_improving": gt(turnover(0), turnover(1)),
    }
    evaluated = [v for v in checks.values() if v is not None]
    score = sum(1 for v in evaluated if v)
    return {
        "score": score,
        "evaluated": len(evaluated),
        "ratio": div(score, len(evaluated)) if evaluated else None,
        "checks": checks,
    }


def gross_profitability(a: Annual):
    """Novy-Marx (2013): gross profit / total assets."""
    return div(a.gross_profit(0), a.total_assets(0))


def return_on_capital(a: Annual):
    """Greenblatt ROC: EBIT / (net working capital ex-cash + net PP&E)."""
    ca = a.get("balance", "Current Assets")
    cash = a.get("balance", "Cash Cash Equivalents And Short Term Investments") or 0.0
    cl = a.get("balance", "Current Liabilities")
    cur_debt = a.get("balance", "Current Debt") or 0.0
    ppe = a.get("balance", "Net PPE")
    if ca is None or cl is None or ppe is None:
        return None
    nwc = max((ca - cash) - (cl - cur_debt), 0.0)  # negative NWC is a funding source, floor at 0
    return div(a.ebit(0), nwc + ppe)


def compute(a: Annual) -> dict:
    return {
        "piotroski": piotroski(a),
        "gross_profitability": gross_profitability(a),
        "return_on_capital": return_on_capital(a),
        "gross_margin": div(a.gross_profit(0), a.revenue(0)),
        "revenue_growth": div(sub(a.revenue(0), a.revenue(1)), abs(a.revenue(1)) if a.revenue(1) else None),
    }
