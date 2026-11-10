import copy
from datetime import date, timedelta

import pytest

# Two fiscal years plus a third for beginning-of-year assets.
# "good" company: everything improves year over year.
GOOD = {
    "periods": ["2025-12-31", "2024-12-31", "2023-12-31"],
    "income": {
        "Total Revenue": [1200.0, 1000.0, 900.0],
        "Cost Of Revenue": [600.0, 550.0, 500.0],
        "Gross Profit": [600.0, 450.0, 400.0],
        "EBIT": [300.0, 200.0, 150.0],
        "Operating Income": [300.0, 200.0, 150.0],
        "Net Income": [200.0, 120.0, 100.0],
    },
    "balance": {
        "Total Assets": [2000.0, 1900.0, 1800.0],
        "Current Assets": [800.0, 700.0, 650.0],
        "Current Liabilities": [400.0, 400.0, 400.0],
        "Long Term Debt": [300.0, 400.0, 400.0],
        "Total Debt": [350.0, 450.0, 450.0],
        "Current Debt": [50.0, 50.0, 50.0],
        "Cash Cash Equivalents And Short Term Investments": [200.0, 150.0, 100.0],
        "Retained Earnings": [500.0, 400.0, 300.0],
        "Total Liabilities Net Minority Interest": [900.0, 1000.0, 1000.0],
        "Stockholders Equity": [1100.0, 900.0, 800.0],
        "Net PPE": [600.0, 600.0, 600.0],
        "Ordinary Shares Number": [100.0, 100.0, 100.0],
    },
    "cashflow": {
        "Operating Cash Flow": [260.0, 150.0, 120.0],
        "Free Cash Flow": [200.0, 100.0, 80.0],
        "Capital Expenditure": [-60.0, -50.0, -40.0],
    },
}


def price_series(n=400, start=100.0, daily=0.001, start_date=date(2024, 6, 3)):
    """Geometric series on consecutive weekdays."""
    dates, closes, d, px = [], [], start_date, start
    while len(dates) < n:
        if d.weekday() < 5:
            dates.append(d.isoformat())
            closes.append(px)
            px *= 1 + daily
        d += timedelta(days=1)
    return {"dates": dates, "close": closes,
            "high": [c * 1.01 for c in closes], "low": [c * 0.99 for c in closes]}


def make_snapshot(annual=None, prices=None, bench=None, sector="Technology"):
    return {
        "schema_version": 1,
        "ticker": "TEST",
        "info": {"name": "Test Corp", "sector": sector},
        "annual": copy.deepcopy(annual or GOOD),
        "prices": prices or price_series(),
        "benchmark": {"ticker": "SPY", **(bench or price_series(daily=0.0005))},
    }


@pytest.fixture
def snap():
    return make_snapshot()
