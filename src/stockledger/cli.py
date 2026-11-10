"""stockledger CLI.

  stockledger analyze AAPL [--asof 2025-06-30] [--snapshot file.json]
  stockledger check  report.template.md --metrics out/AAPL_2026-11-10.metrics.json
  stockledger render report.template.md --metrics ... [-o report.md]
  stockledger record out/AAPL_2026-11-10.metrics.json
  stockledger settle
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from . import ledger, render, scoring, snapshot


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")


def cmd_analyze(args) -> int:
    if args.snapshot:
        snap = snapshot.load(Path(args.snapshot))
    else:
        years = 3
        if args.asof:
            years += max(0, (date.today() - date.fromisoformat(args.asof)).days // 365 + 1)
        snap = snapshot.fetch(args.ticker, years_of_prices=years)
    if args.asof:
        snap = snapshot.trim_to_asof(snap, args.asof)
    rules = scoring.load_rules(Path(args.rules) if args.rules else None)
    m = scoring.analyze(snap, rules)

    out = Path(args.out)
    stem = f"{m['ticker']}_{m['asof']}"
    snapshot.save(snap, out / f"{stem}.snapshot.json")
    _write_json(out / f"{stem}.metrics.json", m)

    a = m["action"]
    fired = [g["id"] for g in a["guardrails"] if g["triggered"]]
    print(f"{m['ticker']} asof {m['asof']}: score {m['score']['total']} "
          f"(coverage {m['score']['coverage']:.0%}) -> {a['raw']}"
          + (f" -> {a['final']} [guardrails: {', '.join(fired)}]" if a["final"] != a["raw"] or fired else ""))
    for name, d in m["score"]["dimensions"].items():
        print(f"  {name:<9} {d['score']}")
    print(f"metrics: {out / (stem + '.metrics.json')}")
    return 0


def _load_metrics(p) -> dict:
    return json.loads(Path(p).read_text(encoding="utf-8"))


def cmd_check(args) -> int:
    res = render.check(Path(args.template).read_text(encoding="utf-8"), _load_metrics(args.metrics))
    print(json.dumps(res, indent=2))
    return 0 if res["ok"] else 1


def cmd_render(args) -> int:
    tpl = Path(args.template).read_text(encoding="utf-8")
    m = _load_metrics(args.metrics)
    res = render.check(tpl, m)
    if not res["ok"]:
        print(json.dumps(res, indent=2), file=sys.stderr)
        print("refusing to render: fix the template first (see `stockledger check`)", file=sys.stderr)
        return 1
    text = render.render(tpl, m)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"rendered {res['placeholders']} values -> {args.output}")
    else:
        sys.stdout.write(text)
    return 0


def cmd_record(args) -> int:
    call, new = ledger.record(_load_metrics(args.metrics), Path(args.ledger))
    print(("recorded " if new else "already recorded ") + json.dumps(call))
    return 0


def cmd_settle(args) -> int:
    n_calls, n_rows = ledger.write_settlement(Path(args.ledger), ledger.yfinance_closes)
    print(f"{n_calls} calls, {n_rows} settled (call x horizon) -> {Path(args.ledger) / 'TRACK_RECORD.md'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="stockledger", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("analyze", help="fetch data, compute factors, score -> metrics.json")
    a.add_argument("ticker")
    a.add_argument("--asof", help="YYYY-MM-DD: only use information knowable on this date")
    a.add_argument("--snapshot", help="use a saved snapshot instead of fetching (offline, reproducible)")
    a.add_argument("--rules", help="alternative rules YAML")
    a.add_argument("--out", default="out")
    a.set_defaults(func=cmd_analyze)

    for name, fn, hlp in (("check", cmd_check, "validate a report template against metrics"),
                          ("render", cmd_render, "fill a report template with metric values")):
        c = sub.add_parser(name, help=hlp)
        c.add_argument("template")
        c.add_argument("--metrics", required=True)
        if name == "render":
            c.add_argument("-o", "--output")
        c.set_defaults(func=fn)

    r = sub.add_parser("record", help="append the call in a metrics.json to the ledger")
    r.add_argument("metrics")
    r.add_argument("--ledger", default="ledger")
    r.set_defaults(func=cmd_record)

    s = sub.add_parser("settle", help="score past calls vs SPY, regenerate TRACK_RECORD.md")
    s.add_argument("--ledger", default="ledger")
    s.set_defaults(func=cmd_settle)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
