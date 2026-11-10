import copy
import math

import pytest

from conftest import GOOD, make_snapshot
from stockledger.factors import Annual, price, quality, risk, value


def test_piotroski_all_pass_for_improving_company(snap):
    p = quality.piotroski(Annual(snap))
    assert p["checks"] == {k: True for k in p["checks"]}
    assert (p["score"], p["evaluated"], p["ratio"]) == (9, 9, 1.0)


def test_piotroski_all_fail_when_everything_deteriorates():
    bad = copy.deepcopy(GOOD)
    bad["income"]["Net Income"] = [-50.0, 120.0, 100.0]
    bad["income"]["Total Revenue"] = [800.0, 1000.0, 900.0]
    bad["income"]["Gross Profit"] = [300.0, 450.0, 400.0]
    bad["cashflow"]["Operating Cash Flow"] = [-60.0, 150.0, 120.0]
    bad["balance"]["Long Term Debt"] = [600.0, 400.0, 400.0]
    bad["balance"]["Current Assets"] = [500.0, 700.0, 650.0]
    bad["balance"]["Ordinary Shares Number"] = [120.0, 100.0, 100.0]
    p = quality.piotroski(Annual(make_snapshot(annual=bad)))
    assert p["score"] == 0 and p["evaluated"] == 9


def test_piotroski_missing_inputs_are_none_not_false():
    partial = copy.deepcopy(GOOD)
    partial["balance"]["Ordinary Shares Number"] = [None, None, None]
    partial["balance"]["Current Assets"] = [None, None, None]
    p = quality.piotroski(Annual(make_snapshot(annual=partial)))
    assert p["checks"]["no_dilution"] is None
    assert p["checks"]["current_ratio_improving"] is None
    assert p["evaluated"] == 7 and p["ratio"] == 1.0


def test_gross_profitability_and_roc(snap):
    a = Annual(snap)
    assert quality.gross_profitability(a) == pytest.approx(600 / 2000)
    # NWC ex-cash = (800-200) - (400-50) = 250 ; + PPE 600 = 850
    assert quality.return_on_capital(a) == pytest.approx(300 / 850)


def test_value_rebuilds_market_cap_and_ev_from_snapshot(snap):
    v = value.compute(Annual(snap), price=50.0)
    assert v["market_cap"] == 5000.0
    assert v["enterprise_value"] == 5000 + 350 - 200
    assert v["earnings_yield"] == pytest.approx(300 / 5150)
    assert v["fcf_yield"] == pytest.approx(200 / 5000)
    assert v["pe"] == pytest.approx(25.0)


def test_value_uses_earnings_price_for_financials(snap):
    v = value.compute(Annual(snap), price=50.0, sector="Financial Services")
    assert v["enterprise_value"] is None and v["fcf_yield"] is None
    assert v["earnings_yield"] == pytest.approx(200 / 5000)


def test_pe_undefined_for_losses():
    loss = copy.deepcopy(GOOD)
    loss["income"]["Net Income"][0] = -10.0
    assert value.compute(Annual(make_snapshot(annual=loss)), 50.0)["pe"] is None


def test_altman_z2_matches_hand_calculation(snap):
    z = risk.altman_z2(Annual(snap), "Technology")
    expected = 6.56 * (400 / 2000) + 3.26 * (500 / 2000) + 6.72 * (300 / 2000) + 1.05 * (1100 / 900)
    assert z["value"] == pytest.approx(expected)
    assert z["zone"] == "safe"


def test_altman_not_applicable_to_financials(snap):
    assert risk.altman_z2(Annual(snap), "Financial Services")["zone"] == "n/a"


def test_momentum_12_1_on_geometric_series():
    closes = [100 * 1.001 ** i for i in range(300)]
    # from index -253 to -22 is 231 steps
    assert price.momentum_12_1(closes) == pytest.approx(1.001 ** 231 - 1)
    assert price.momentum_12_1(closes[:200]) is None


def test_volatility_zero_for_constant_growth_and_drawdown():
    closes = [100 * 1.001 ** i for i in range(300)]
    assert price.volatility(closes) == pytest.approx(0.0, abs=1e-9)
    assert price.max_drawdown(closes) == 0.0
    assert price.max_drawdown([100, 120, 60, 90]) == pytest.approx(-0.5)


def test_atr_and_sma():
    assert price.sma([1, 2, 3, 4], 2) == 3.5
    assert price.sma([1], 2) is None
    h, lo, c = [11] * 20, [9] * 20, [10] * 20
    assert price.atr(h, lo, c) == pytest.approx(2.0)


def test_price_compute_relative_momentum(snap):
    p = price.compute(snap["prices"], snap["benchmark"])
    assert p["relative_momentum_12_1"] == pytest.approx(1.001 ** 231 - 1.0005 ** 231)
    assert p["price_vs_ma200"] > 0
    assert not math.isnan(p["extension_atr"])


def test_ebit_prefers_operating_income_over_one_off_gains():
    a = copy.deepcopy(GOOD)
    a["income"]["EBIT"][0] = 500.0             # inflated by a non-operating gain
    a["income"]["Operating Income"][0] = -40.0  # the business actually lost money
    assert Annual(make_snapshot(annual=a)).ebit(0) == -40.0
    a["income"]["Operating Income"][0] = None
    assert Annual(make_snapshot(annual=a)).ebit(0) == 500.0
