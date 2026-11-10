from datetime import date

import pytest

from conftest import make_snapshot, price_series
from stockledger import ledger, scoring, snapshot


def _metrics(asof="2025-01-02", action="BUY"):
    return {
        "ticker": "TEST", "asof": asof, "price": {"price": 100.0},
        "action": {"final": action, "raw": action}, "score": {"total": 70.0},
        "rules": {"version": "v1", "sha256": "abc"}, "generator": "test",
    }


def test_record_is_idempotent_and_classifies_mode(tmp_path):
    c1, new1 = ledger.record(_metrics(), tmp_path, today=date(2025, 1, 3))
    c2, new2 = ledger.record(_metrics(), tmp_path, today=date(2025, 1, 3))
    assert (new1, new2) == (True, False)
    assert c1["mode"] == "live"
    old, _ = ledger.record(_metrics(asof="2024-01-02"), tmp_path, today=date(2025, 1, 3))
    assert old["mode"] == "backfill"
    assert len(ledger.read_calls(tmp_path)) == 2


def test_settle_one_excess_and_hit():
    px = {"dates": [f"2025-01-{d:02d}" for d in range(1, 11)], "close": [100.0] * 5 + [110.0] * 5}
    bench = {"dates": px["dates"], "close": [100.0] * 5 + [105.0] * 5}
    call = {"id": "x", "ticker": "T", "asof": "2025-01-02", "action": "BUY", "mode": "live", "rules_version": "v1"}
    r = ledger.settle_one(call, px, bench, horizon=5)
    assert r["return"] == pytest.approx(0.10) and r["excess"] == pytest.approx(0.05)
    assert r["hit"] is True
    assert ledger.settle_one({**call, "action": "AVOID"}, px, bench, 5)["hit"] is False
    assert ledger.settle_one({**call, "action": "HOLD"}, px, bench, 5)["hit"] is None
    assert ledger.settle_one(call, px, bench, horizon=9) is None  # still open


def test_settle_all_and_track_record(tmp_path):
    ledger.record(_metrics(asof="2024-06-03"), tmp_path, today=date(2026, 1, 1))
    series = price_series(n=400, start_date=date(2024, 6, 3))
    rows = ledger.settle_all(ledger.read_calls(tmp_path), lambda t, s: series)
    assert {r["horizon"] for r in rows} == {63, 126, 252}
    md = ledger.track_record_md(ledger.read_calls(tmp_path), rows)
    assert "Backfilled" in md and "| 63d | BUY | 1 |" in md


def test_trim_to_asof_applies_reporting_lag():
    s = make_snapshot()  # latest fiscal year ends 2025-12-31
    early = snapshot.trim_to_asof(s, "2026-02-15")   # 46 days later: 10-K not assumed out yet
    assert early["annual"]["periods"][0] == "2024-12-31"
    late = snapshot.trim_to_asof(s, "2026-04-15")
    assert late["annual"]["periods"][0] == "2025-12-31"


def test_trim_to_asof_drops_future_prices():
    s = make_snapshot()
    t = snapshot.trim_to_asof(s, "2024-12-31")
    assert t["prices"]["dates"][-1] <= "2024-12-31"
    assert t["benchmark"]["dates"][-1] <= "2024-12-31"
    assert scoring.compute_metrics(t)["asof"] == "2024-12-31"
