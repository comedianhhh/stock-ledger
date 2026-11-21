"""Foreign filers: statements in one currency, quote (often an ADS) in another."""

import copy

import pandas as pd
import pytest

from conftest import make_snapshot, price_series
from stockledger import scoring, snapshot
from stockledger.factors import Annual, value


def _foreign(snap, fx_close=0.5, per_unit=5.0, fx_dates=None):
    """Restate `snap` as if filed in TWD at `fx_close` USD/TWD, quoted as 1 ADS = `per_unit` shares."""
    s = copy.deepcopy(snap)
    for stmt in ("income", "balance", "cashflow"):
        for field, col in s["annual"][stmt].items():
            if field == "Ordinary Shares Number":
                s["annual"][stmt][field] = [None if v is None else v * per_unit for v in col]
            else:
                s["annual"][stmt][field] = [None if v is None else v / fx_close for v in col]
    dates = fx_dates or s["prices"]["dates"]
    s["info"].update({"currency": "USD", "financial_currency": "TWD", "shares_per_price_unit": per_unit})
    s["fx"] = {"pair": "TWDUSD=X", "dates": dates, "close": [fx_close] * len(dates),
               "high": [fx_close] * len(dates), "low": [fx_close] * len(dates)}
    return s


def test_no_bridge_for_single_currency_or_old_snapshots(snap):
    assert snapshot.currency_bridge(snap) is None                       # no financial_currency recorded
    snap["info"].update({"currency": "USD", "financial_currency": "USD"})
    assert snapshot.currency_bridge(snap) is None


def test_converted_valuation_matches_same_company_filed_in_usd(snap):
    home = scoring.compute_metrics(snap)["value"]
    abroad = scoring.compute_metrics(_foreign(snap))["value"]
    for k in ("market_cap", "enterprise_value", "earnings_yield", "fcf_yield", "pe"):
        assert abroad[k] == pytest.approx(home[k]), k
    assert abroad["currency"]["converted"] is True
    assert abroad["currency"]["financial"] == "TWD" and abroad["currency"]["fx_rate"] == 0.5
    assert "currency" not in home                                        # USD filers: output unchanged


def test_unconverted_mix_would_be_wrong(snap):
    """The bug being fixed: reading TWD statements against a USD price."""
    foreign = _foreign(snap)
    naive = value.compute(Annual(foreign), scoring.compute_metrics(foreign)["price"]["price"])
    home = scoring.compute_metrics(snap)["value"]
    assert naive["fcf_yield"] == pytest.approx(home["fcf_yield"] * 2 / 5)  # /fx, then /5 more shares


def test_quality_ratios_are_currency_invariant(snap):
    assert scoring.compute_metrics(_foreign(snap))["quality"] == scoring.compute_metrics(snap)["quality"]


def test_missing_rate_or_ratio_blanks_valuation_not_guesses(snap):
    no_fx = _foreign(snap)
    no_fx["fx"] = None
    v = scoring.compute_metrics(no_fx)["value"]
    assert v["earnings_yield"] is None and v["market_cap"] is None
    assert v["currency"]["converted"] is False and "rate" in v["currency"]["reason"]

    no_ratio = _foreign(snap)
    no_ratio["info"]["shares_per_price_unit"] = None
    v = scoring.compute_metrics(no_ratio)["value"]
    assert v["pe"] is None and "ADS ratio" in v["currency"]["reason"]

    m = scoring.analyze(no_fx)
    assert m["score"]["dimensions"]["value"]["score"] is None           # coverage drops, score not faked


def test_fx_rate_is_point_in_time(snap):
    s = _foreign(snap)
    s["fx"]["close"] = [0.5] * 200 + [0.25] * (len(s["fx"]["dates"]) - 200)
    cutoff = s["prices"]["dates"][150]
    bridge = snapshot.currency_bridge(snapshot.trim_to_asof(s, cutoff))
    assert bridge["fx_rate"] == 0.5 and bridge["fx_date"] == cutoff
    late = snapshot.currency_bridge(s)
    assert late["fx_rate"] == 0.25


def test_price_unit_shares():
    assert snapshot.price_unit_shares({"marketCap": 1_000_000, "regularMarketPrice": 4.0}) == 250_000
    assert snapshot.price_unit_shares({"marketCap": 1_000_000, "currentPrice": 8.0}) == 125_000
    assert snapshot.price_unit_shares({"marketCap": None, "regularMarketPrice": 10}) is None


def test_fx_series_falls_back_to_inverse_pair():
    dates = pd.to_datetime(["2026-11-17", "2026-11-18"])
    frames = {
        "TWDUSD=X": pd.DataFrame(columns=["Close", "High", "Low"]),
        "USDTWD=X": pd.DataFrame({"Close": [32.0, 33.0], "High": [32.5, 33.5], "Low": [31.5, 32.5]}, index=dates),
    }

    class FakeYF:
        class Ticker:
            def __init__(self, sym):
                self.sym = sym

            def history(self, **_):
                return frames[self.sym]

    s = snapshot._fx_series(FakeYF, "TWD", "USD", "3y")
    assert s["pair"] == "1/USDTWD=X"
    assert s["close"] == [pytest.approx(1 / 32), pytest.approx(1 / 33)]
    assert s["high"][0] == pytest.approx(1 / 31.5)                       # inverse swaps high and low


def test_trim_keeps_snapshots_without_fx(snap):
    out = snapshot.trim_to_asof(make_snapshot(prices=price_series()), "2024-12-31")
    assert "fx" not in out
