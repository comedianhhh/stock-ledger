"""Snapshot = the only I/O boundary.

Everything downstream (factors, scoring, rendering, settlement) is a pure
function of a snapshot dict, so it can be tested offline against recorded
fixtures and re-run bit-for-bit later.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
BENCHMARK = "SPY"
# Annual statements become "known" this many days after period end.
# yfinance has no filing dates, so we lag conservatively to avoid look-ahead.
REPORTING_LAG_DAYS = 90

INCOME_FIELDS = [
    "Total Revenue", "Cost Of Revenue", "Gross Profit", "EBIT",
    "Operating Income", "Net Income",
]
BALANCE_FIELDS = [
    "Total Assets", "Current Assets", "Current Liabilities",
    "Long Term Debt", "Total Debt", "Current Debt",
    "Cash Cash Equivalents And Short Term Investments",
    "Retained Earnings", "Total Liabilities Net Minority Interest",
    "Stockholders Equity", "Net PPE", "Ordinary Shares Number",
]
CASHFLOW_FIELDS = ["Operating Cash Flow", "Free Cash Flow", "Capital Expenditure"]


def _clean(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def _statement(df, fields: list[str], periods: list) -> dict[str, list[float | None]]:
    out = {}
    for f in fields:
        if f in df.index:
            out[f] = [_clean(df.at[f, p]) if p in df.columns else None for p in periods]
        else:
            out[f] = [None] * len(periods)
    return out


def _series(hist) -> dict[str, list]:
    return {
        "dates": [d.strftime("%Y-%m-%d") for d in hist.index],
        "close": [round(float(x), 6) for x in hist["Close"]],
        "high": [round(float(x), 6) for x in hist["High"]],
        "low": [round(float(x), 6) for x in hist["Low"]],
    }


def fetch(ticker: str, years_of_prices: int = 3) -> dict:
    """Fetch a full snapshot from yfinance. Network I/O lives only here."""
    import yfinance as yf

    t = yf.Ticker(ticker)
    inc, bal, cf = t.income_stmt, t.balance_sheet, t.cashflow
    periods = sorted(set(inc.columns) | set(bal.columns), reverse=True)
    info = t.info or {}
    hist = t.history(period=f"{years_of_prices}y", auto_adjust=True)
    bench = yf.Ticker(BENCHMARK).history(period=f"{years_of_prices}y", auto_adjust=True)
    if hist.empty:
        raise ValueError(f"no price history for {ticker!r}")

    return {
        "schema_version": SCHEMA_VERSION,
        "ticker": ticker.upper(),
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "info": {
            "name": info.get("longName") or info.get("shortName"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "currency": info.get("currency"),
            "quote_type": info.get("quoteType"),
        },
        "annual": {
            "periods": [p.strftime("%Y-%m-%d") for p in periods],
            "income": _statement(inc, INCOME_FIELDS, periods),
            "balance": _statement(bal, BALANCE_FIELDS, periods),
            "cashflow": _statement(cf, CASHFLOW_FIELDS, periods),
        },
        "prices": _series(hist),
        "benchmark": {"ticker": BENCHMARK, **_series(bench)},
    }


def trim_to_asof(snap: dict, asof: str) -> dict:
    """Return a copy containing only information knowable on `asof`.

    Prices after `asof` are dropped; annual periods are dropped unless
    period_end + REPORTING_LAG_DAYS <= asof.
    """
    cutoff = date.fromisoformat(asof)
    out = json.loads(json.dumps(snap))

    for key in ("prices", "benchmark"):
        s = out[key]
        keep = [i for i, d in enumerate(s["dates"]) if date.fromisoformat(d) <= cutoff]
        for col in ("dates", "close", "high", "low"):
            s[col] = [s[col][i] for i in keep]

    a = out["annual"]
    keep = [
        i for i, p in enumerate(a["periods"])
        if date.fromisoformat(p) + timedelta(days=REPORTING_LAG_DAYS) <= cutoff
    ]
    a["periods"] = [a["periods"][i] for i in keep]
    for stmt in ("income", "balance", "cashflow"):
        a[stmt] = {k: [v[i] for i in keep] for k, v in a[stmt].items()}
    out["asof"] = asof
    return out


def asof_date(snap: dict) -> str:
    return snap.get("asof") or snap["prices"]["dates"][-1]


def save(snap: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snap, indent=1), encoding="utf-8")


def load(path: Path) -> dict:
    snap = json.loads(Path(path).read_text(encoding="utf-8"))
    if snap.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"unsupported snapshot schema: {snap.get('schema_version')}")
    return snap
