import copy

import pytest

from conftest import make_snapshot, price_series
from stockledger import scoring


@pytest.fixture
def rules():
    return scoring.load_rules()


@pytest.mark.parametrize("x,expected", [(-1, 0), (0.3, 0), (0.55, 50), (0.8, 100), (5, 100)])
def test_interpolate_ascending(x, expected):
    assert scoring.interpolate(x, [[0.3, 0], [0.8, 100]]) == pytest.approx(expected)


def test_interpolate_descending_curve():
    curve = [[0.20, 100], [0.60, 0]]
    assert scoring.interpolate(0.40, curve) == pytest.approx(50)
    assert scoring.interpolate(0.10, curve) == 100


def test_rules_have_version_and_hash(rules):
    assert rules["version"] == "v1"
    assert len(rules["_sha256"]) == 12


def test_missing_metric_renormalises_weights_and_lowers_coverage(rules):
    m = scoring.compute_metrics(make_snapshot())
    full = scoring.score(m, rules)
    m["value"]["fcf_yield"] = None
    part = scoring.score(m, rules)
    assert full["coverage"] == 1.0
    assert part["coverage"] == pytest.approx(1 - 0.25 * 0.4)
    ey_only = [c for c in part["dimensions"]["value"]["components"] if c["value"] is not None]
    assert part["dimensions"]["value"]["score"] == pytest.approx(ey_only[0]["points"])


def test_action_bands(rules):
    assert scoring.raw_action(80, rules) == "BUY"
    assert scoring.raw_action(65, rules) == "BUY"
    assert scoring.raw_action(50, rules) == "HOLD"
    assert scoring.raw_action(10, rules) == "AVOID"
    assert scoring.raw_action(None, rules) == "HOLD"


def _guard(m, rules, action):
    sc = scoring.score(m, rules)
    final, gs = scoring.apply_guardrails(action, m, sc, rules)
    return final, {g["id"] for g in gs if g["triggered"]}


def test_below_trend_caps_buy_at_hold(rules):
    falling = make_snapshot(prices=price_series(daily=-0.001))
    m = scoring.compute_metrics(falling)
    assert _guard(m, rules, "BUY") == ("HOLD", {"below_trend"})


def test_guardrails_never_upgrade(rules):
    falling = make_snapshot(prices=price_series(daily=-0.001))
    m = scoring.compute_metrics(falling)
    assert _guard(m, rules, "AVOID")[0] == "AVOID"


def test_overextended_caps_buy(rules):
    px = price_series()
    px["close"][-1] *= 1.5
    px["high"][-1] = px["close"][-1]
    m = scoring.compute_metrics(make_snapshot(prices=px))
    final, fired = _guard(m, rules, "BUY")
    assert final == "HOLD" and "overextended" in fired


def test_distress_requires_both_conditions(rules):
    m = scoring.compute_metrics(make_snapshot())
    m["risk"]["altman_z2"]["zone"] = "distress"
    assert "distress" not in _guard(m, rules, "BUY")[1]  # Piotroski 9 -> not distressed
    m["quality"]["piotroski"]["score"] = 2
    final, fired = _guard(m, rules, "BUY")
    assert final == "AVOID" and "distress" in fired


def test_analyze_is_deterministic(rules):
    s = make_snapshot()
    assert scoring.analyze(copy.deepcopy(s), rules) == scoring.analyze(copy.deepcopy(s), rules)
