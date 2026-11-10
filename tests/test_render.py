import pytest

from stockledger import render

M = {
    "ticker": "TEST",
    "value": {"earnings_yield": 0.0583, "pe": 25.0, "market_cap": 2.5e12, "fcf_yield": None},
    "quality": {"piotroski": {"score": 7, "checks": {"no_dilution": True}}},
}


def test_clean_template_passes_and_renders():
    tpl = ("Earnings yield {{ value.earnings_yield | pct }}, P/E {{value.pe|x}}, "
           "cap {{ value.market_cap | usd_b }}, F-score {{ quality.piotroski.score }}/9, "
           "no dilution: {{ quality.piotroski.checks.no_dilution }}. 200-day trend, 12-1 momentum, FY2025.")
    res = render.check(tpl, M)
    assert res["ok"], res
    assert render.render(tpl, M) == (
        "Earnings yield 5.8%, P/E 25.0x, cap $2,500.0B, F-score 7/9, "
        "no dilution: yes. 200-day trend, 12-1 momentum, FY2025.")


def test_none_renders_as_na():
    assert render.render("{{ value.fcf_yield | pct }}", M) == "n/a"


@pytest.mark.parametrize("bad", ["P/E is 25.3", "yield of 6%", "worth $2.5 trillion", "trades at 30x", "cap 2.5B"])
def test_hand_typed_numbers_are_flagged(bad):
    res = render.check(bad, M)
    assert not res["ok"] and res["bare_numbers"], bad


def test_unknown_or_non_leaf_paths_are_flagged():
    res = render.check("{{ value.ev_ebitda }} {{ quality.piotroski }}", M)
    assert res["unresolved"][0] == "value.ev_ebitda"
    assert "cite a leaf value" in res["unresolved"][1]


def test_unknown_format_flagged():
    assert render.check("{{ value.pe | percent }}", M)["bad_formats"]


def test_code_is_exempt():
    tpl = "Run `stockledger analyze --asof 2025-06-30`\n```\nscore 73.4\n```\n"
    assert render.check(tpl, M)["ok"]
