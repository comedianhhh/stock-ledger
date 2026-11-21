import gzip
import io
import json

import pytest

from stockledger import cli, macro, render

SPEC = {
    "version": "t1",
    "min_volume_usd": 1000,
    "_sha256": "abc",
    "markets": [
        {"id": "fed", "slug": "fed-dec", "label": "Fed decision"},
        {"id": "recession", "slug": "recession", "label": "Recession"},
        {"id": "spx", "slug": "spx-hit", "label": "SPX levels"},
        {"id": "gone", "slug": "gone", "label": "Missing event"},
    ],
}


def _mkt(title, yes, neg_risk=True, closed=False):
    return {"question": f"{title}?", "groupItemTitle": title, "outcomes": '["Yes", "No"]',
            "outcomePrices": json.dumps([str(yes), str(round(1 - yes, 4))]),
            "closed": closed, "negRisk": neg_risk, "volumeNum": 10}


EVENTS = {
    "fed-dec": {"title": "Fed Decision in December?", "slug": "fed-dec", "closed": False,
                "endDate": "2026-12-10T00:00:00Z", "volume": "50000", "liquidity": "9000",
                "markets": [_mkt("No change", 0.05), _mkt("25 bps increase", 0.9),
                            _mkt("50+ bps increase", 0.05), _mkt("25 bps decrease", 0.0, closed=True)]},
    "recession": {"title": "US recession?", "slug": "recession", "closed": False,
                  "endDate": "2026-12-31", "volume": 500, "liquidity": 100,
                  "markets": [{**_mkt("", 0.03, neg_risk=False), "groupItemTitle": ""}]},
    "spx-hit": {"title": "SPX hit?", "slug": "spx-hit", "closed": False, "endDate": "2026-12-31",
                "volume": 9000, "liquidity": 10,
                "markets": [_mkt("↓ $7,000", 0.56, neg_risk=False), _mkt("↑ $8,000", 0.13, neg_risk=False)]},
}


def _snap(events=None, errors=None):
    return {"schema_version": 1, "source": "polymarket-gamma", "fetched_at": "2026-11-19T20:00:00+00:00",
            "asof": "2026-11-19", "events": {**{"gone": None}, **(events or EVENTS)}, "errors": errors or {}}


@pytest.mark.parametrize("label,key", [
    ("25 bps increase", "25_bps_increase"),
    ("50+ bps increase", "50_plus_bps_increase"),
    ("≤3.3%", "le_3_3_pct"),
    ("≥4.4%", "ge_4_4_pct"),
    ("↓ $7,200", "down_7200"),
    ("$6,000-$6,500", "6000_to_6500"),
    ("-0.2%", "minus_0_2_pct"),
    ("≤-0.3%", "le_minus_0_3_pct"),
    ("No change", "no_change"),
])
def test_outcome_key(label, key):
    assert macro.outcome_key(label) == key


def test_build_exclusive_binary_ladder_and_missing():
    m = macro.build(_snap(), SPEC)
    fed, rec, spx, gone = (m["markets"][k] for k in ("fed", "recession", "spx", "gone"))

    assert fed["kind"] == "multi" and fed["exclusive"] is True
    assert "25_bps_decrease" not in fed["outcomes"]          # closed sub-market dropped
    assert fed["mode"] == "25 bps increase" and fed["mode_p"] == pytest.approx(0.9)
    assert fed["sum_p"] == pytest.approx(1.0)
    assert fed["thin"] is False and fed["end_date"] == "2026-12-10"

    assert rec["kind"] == "binary" and rec["p"] == pytest.approx(0.03)
    assert rec["thin"] is True                                # 500 < 1000

    # overlapping thresholds: never summed, no modal outcome
    assert spx["exclusive"] is False and spx["sum_p"] is None and spx["mode"] is None
    assert spx["outcomes"]["down_7000"]["p"] == pytest.approx(0.56)

    assert gone["status"] == "missing"
    assert m["coverage"] == pytest.approx(0.75)
    assert (m["markets_version"], m["markets_sha256"]) == ("t1", "abc")


def test_build_is_deterministic():
    assert macro.build(_snap(), SPEC) == macro.build(_snap(), SPEC)


def test_fetch_error_is_recorded_not_raised():
    def get_json(url):
        if "slug=gone" in url:
            raise TimeoutError("slow")
        slug = url.split("slug=")[1]
        return [EVENTS[slug]] if slug in EVENTS else []

    snap = macro.fetch(SPEC, get_json=get_json)
    assert snap["errors"] == {"gone": "TimeoutError: slow"}
    m = macro.build(snap, SPEC)
    assert m["markets"]["gone"]["status"] == "error"
    assert m["markets"]["fed"]["status"] == "open"
    # trimmed to the kept fields only
    assert set(snap["events"]["fed-dec"]) == {"title", "slug", "closed", "endDate", "volume",
                                             "liquidity", "markets"}


def test_get_json_handles_gzip(monkeypatch):
    payload = gzip.compress(json.dumps([{"slug": "x"}]).encode())

    class Resp(io.BytesIO):
        headers = {"Content-Encoding": "gzip"}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    seen = {}

    def fake_urlopen(req, timeout):
        seen["enc"] = req.get_header("Accept-encoding")
        return Resp(payload)

    monkeypatch.setattr(macro.urllib.request, "urlopen", fake_urlopen)
    assert macro._get_json("https://example.invalid") == [{"slug": "x"}]
    assert seen["enc"] == "gzip"


def test_record_is_idempotent(tmp_path):
    m = macro.build(_snap(), SPEC)
    e1, new1 = macro.record(m, tmp_path)
    e2, new2 = macro.record(m, tmp_path)
    assert (new1, new2) == (True, False)
    assert e1["id"] == "macro-2026-11-19-t1"
    assert e1["probs"]["recession"] == pytest.approx(0.03)
    assert e1["probs"]["gone"] is None
    assert e1["probs"]["fed"]["25_bps_increase"] == pytest.approx(0.9)
    assert len((tmp_path / "macro.jsonl").read_text(encoding="utf-8").splitlines()) == 1


def test_macro_json_works_with_check_and_render():
    m = macro.build(_snap(), SPEC)
    tpl = ("Fed: {{ markets.fed.mode }} at {{ markets.fed.mode_p | pct }}; "
           "recession {{ markets.recession.p | pct }} (thin: {{ markets.recession.thin }}).")
    assert render.check(tpl, m)["ok"]
    assert render.render(tpl, m) == "Fed: 25 bps increase at 90.0%; recession 3.0% (thin: yes)."


def test_bundled_market_set_loads():
    spec = macro.load_markets()
    assert spec["version"] == "m1" and len(spec["_sha256"]) == 12
    assert {"fed_dec", "recession_2027"} <= {m["id"] for m in spec["markets"]}


def test_market_set_rejects_bad_ids(tmp_path):
    p = tmp_path / "m.yaml"
    p.write_text("version: x\nmarkets:\n  - {id: Bad-Id, slug: s, label: l}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        macro.load_markets(p)


def test_cli_macro_offline(tmp_path, capsys):
    spec_path = tmp_path / "markets.yaml"
    spec_path.write_text(json.dumps({k: v for k, v in SPEC.items() if k != "_sha256"}), encoding="utf-8")
    snap_path = tmp_path / "snap.json"
    snap_path.write_text(json.dumps(_snap(), ensure_ascii=False), encoding="utf-8")

    rc = cli.main(["macro", "--snapshot", str(snap_path), "--markets", str(spec_path),
                   "--out", str(tmp_path / "out"), "--record", "--ledger", str(tmp_path / "ledger")])
    assert rc == 0
    text = capsys.readouterr().out
    assert "most likely: 25 bps increase 90.0%" in text and "recorded macro-2026-11-19-t1" in text
    assert (tmp_path / "out" / "macro_2026-11-19.json").exists()
