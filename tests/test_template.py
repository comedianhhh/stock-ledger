"""Eval: the shipped report template must pass `check` and fully render for every
golden metrics file (incl. a bank with null EV and a distressed loss-maker)."""

import json
from pathlib import Path

import pytest

from stockledger import render

ROOT = Path(__file__).parents[1]
TEMPLATE = (ROOT / "skills/stock-analysis/references/report-template.md").read_text(encoding="utf-8")
GOLDEN = sorted((ROOT / "tests/golden").glob("*.metrics.json"))


@pytest.mark.parametrize("path", GOLDEN, ids=lambda p: p.name.split(".")[0])
def test_template_checks_and_renders(path):
    m = json.loads(path.read_text(encoding="utf-8"))
    res = render.check(TEMPLATE, m)
    assert res["ok"], res
    out = render.render(TEMPLATE, m)
    assert "{{" not in out and m["ticker"] in out
