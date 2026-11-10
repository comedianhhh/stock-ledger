"""Snapshot tests: recorded real-world snapshots -> metrics must not drift.

If you change a factor or the rules on purpose, regenerate with
    UPDATE_GOLDEN=1 uv run pytest tests/test_golden.py
and review the diff in tests/golden/ like any other code change.
"""

import json
import os
from pathlib import Path

import pytest

from stockledger import scoring, snapshot

HERE = Path(__file__).parent
FIXTURES = sorted((HERE / "fixtures").glob("*.snapshot.json"))


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.name.split(".")[0])
def test_metrics_match_golden(path):
    got = json.loads(json.dumps(scoring.analyze(snapshot.load(path)), default=str))
    golden = HERE / "golden" / path.name.replace(".snapshot.json", ".metrics.json")
    if os.environ.get("UPDATE_GOLDEN") or not golden.exists():
        golden.parent.mkdir(exist_ok=True)
        golden.write_text(json.dumps(got, indent=2), encoding="utf-8")
        pytest.skip("golden written")
    assert got == json.loads(golden.read_text(encoding="utf-8"))
