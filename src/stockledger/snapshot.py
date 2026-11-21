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


def price_unit_shares(info: dict) -> float | None:
    """Shares counted in the units the quote trades in, e.g. ADSs for an ADR.

    A foreign filer's balance sheet counts ordinary shares, but its US quote is
    for an ADS that may bundle several of them (one TSM ADS = 5 ordinary shares).
    yfinance has no ADS ratio, so the count is derived from Yahoo's own market
    cap and price, both in the quote's currency and units.
    """
    mc = _clean(info.get("marketCap"))
    px = _clean(info.get("regularMarketPrice") or info.get("currentPrice"))
    return round(mc / px) if mc and px else None


def _fx_series(yf, financial: str, quote: str, period: str) -> dict | None:
    """Daily rate: units of `quote` currency per one unit of `financial` currency."""
    direct = yf.Ticker(f"{financial}{quote}=X").history(period=period, auto_adjust=True)
    if not direct.empty:
        return {"pair": f"{financial}{quote}=X", **_series(direct)}
    inverse = yf.Ticker(f"{quote}{financial}=X").history(period=period, auto_adjust=True)
    if inverse.empty:
        return None
    s = _series(inverse)
    return {"pair": f"1/{quote}{financial}=X", "dates": s["dates"],
            "close": [round(1 / c, 10) for c in s["close"]],
            "high": [round(1 / c, 10) for c in s["low"]],
            "low": [round(1 / c, 10) for c in s["high"]]}


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

    quote_ccy, fin_ccy = info.get("currency"), info.get("financialCurrency")
    foreign = bool(quote_ccy and fin_ccy and quote_ccy != fin_ccy)
    extra = {}
    if foreign:
        extra["fx"] = _fx_series(yf, fin_ccy, quote_ccy, f"{years_of_prices}y")

    balance = _statement(bal, BALANCE_FIELDS, periods)
    unit_shares = price_unit_shares(info) if foreign else None
    ordinary = next((v for v in balance["Ordinary Shares Number"] if v), None)
    per_unit = round(ordinary / unit_shares, 4) if ordinary and unit_shares else None

    return {
        "schema_version": SCHEMA_VERSION,
        "ticker": ticker.upper(),
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "info": {
            "name": info.get("longName") or info.get("shortName"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "currency": quote_ccy,
            "financial_currency": fin_ccy,
            "price_unit_shares": unit_shares,
            "shares_per_price_unit": per_unit,
            "quote_type": info.get("quoteType"),
        },
        "annual": {
            "periods": [p.strftime("%Y-%m-%d") for p in periods],
            "income": _statement(inc, INCOME_FIELDS, periods),
            "balance": balance,
            "cashflow": _statement(cf, CASHFLOW_FIELDS, periods),
        },
        "prices": _series(hist),
        "benchmark": {"ticker": BENCHMARK, **_series(bench)},
        **extra,
    }


def trim_to_asof(snap: dict, asof: str) -> dict:
    """Return a copy containing only information knowable on `asof`.

    Prices after `asof` are dropped; annual periods are dropped unless
    period_end + REPORTING_LAG_DAYS <= asof.
    """
    cutoff = date.fromisoformat(asof)
    out = json.loads(json.dumps(snap))

    for key in ("prices", "benchmark", "fx"):
        s = out.get(key)
        if not s:
            continue
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


def currency_bridge(snap: dict) -> dict | None:
    """How to put statements and the quote in one currency, or None if no bridge is needed.

    Returns {"price": "USD", "financial": "TWD", "fx_rate": 0.0303 | None,
    "fx_date": ..., "fx_pair": ..., "shares_per_price_unit": 5.0 | None}.
    ``shares_per_price_unit`` is the ADS ratio (ordinary shares per traded
    unit), measured once at fetch time and assumed constant; the share count
    itself still comes from the point-in-time balance sheet. ``fx_rate`` is
    the last close on or before the snapshot's as-of date (quote currency per
    financial unit), so a back-dated run never reads a later rate. Snapshots
    written before currencies were recorded have no ``financial_currency``
    and are treated as single-currency, as they always were.
    """
    info = snap.get("info", {})
    quote, fin = info.get("currency"), info.get("financial_currency")
    if not (quote and fin and quote != fin):
        return None
    fx = snap.get("fx") or {}
    cutoff = asof_date(snap)
    rate = rate_date = None
    for d, c in zip(fx.get("dates", []), fx.get("close", [])):
        if d <= cutoff and c and c > 0:
            rate, rate_date = c, d
    return {"price": quote, "financial": fin, "fx_rate": rate, "fx_date": rate_date,
            "fx_pair": fx.get("pair"),
            "shares_per_price_unit": info.get("shares_per_price_unit")}


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
