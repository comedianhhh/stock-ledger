"""Macro snapshot from Polymarket prediction markets.

Same shape as the stock path: one I/O boundary (`fetch`) that saves a raw
snapshot, then a pure function (`build`) that turns the snapshot into
macro.json. Re-running `build` on a saved snapshot always gives the same
output, so a macro view can be cited in a report and audited later.

What it reports is the crowd's price for each outcome, read as a probability.
It does not score, rate or trade anything, and it never turns odds into a
BUY/HOLD/AVOID: that stays with the factor rules.

Two flags keep the numbers honest:
- `thin`: the event has traded less than `min_volume_usd`, so its prices are
  easy to move and should be read as direction only.
- `exclusive`: the outcomes are mutually exclusive (Polymarket "negRisk"
  events, e.g. one Fed decision out of five). Only then are `sum_p` and the
  modal outcome computed; threshold ladders such as "S&P hits 7,000 / 8,000"
  overlap, and summing them would mean nothing.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path

import yaml

GAMMA_URL = "https://gamma-api.polymarket.com/events"
SCHEMA_VERSION = 1
USER_AGENT = "stockledger-macro/0.1"

# Fields kept from each raw event / market. Everything else in the API
# response is dropped so snapshots stay small and diffable.
_EVENT_FIELDS = ("title", "slug", "closed", "endDate", "volume", "liquidity")
_MARKET_FIELDS = ("question", "groupItemTitle", "outcomes", "outcomePrices",
                  "closed", "negRisk", "volumeNum")


# ---------- market set ----------

def load_markets(path: Path | None = None) -> dict:
    text = (Path(path).read_text(encoding="utf-8") if path else
            resources.files("stockledger.rules").joinpath("macro_m1.yaml").read_text(encoding="utf-8"))
    spec = yaml.safe_load(text)
    ids = [m["id"] for m in spec["markets"]]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate market id in macro market set")
    for i in ids:
        if not re.fullmatch(r"[a-z0-9_]+", i):
            raise ValueError(f"market id {i!r} must be lowercase letters, digits and _")
    spec["_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return spec


# ---------- I/O boundary ----------

def _get_json(url: str, timeout: float = 20.0):
    req = urllib.request.Request(url, headers={"Accept-Encoding": "gzip", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
    return json.loads(body.decode("utf-8"))


def _trim_event(event: dict) -> dict:
    out = {k: event.get(k) for k in _EVENT_FIELDS}
    out["markets"] = [{k: m.get(k) for k in _MARKET_FIELDS} for m in event.get("markets") or []]
    return out


def fetch(spec: dict, get_json=_get_json) -> dict:
    """Fetch every event in the market set. A failed lookup is recorded, not raised."""
    events, errors = {}, {}
    for m in spec["markets"]:
        url = f"{GAMMA_URL}?slug={urllib.parse.quote(m['slug'])}"
        try:
            data = get_json(url)
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            events[m["slug"]], errors[m["slug"]] = None, f"{type(exc).__name__}: {exc}"
            continue
        events[m["slug"]] = _trim_event(data[0]) if data else None
    now = datetime.now(timezone.utc)
    return {
        "schema_version": SCHEMA_VERSION,
        "source": "polymarket-gamma",
        "fetched_at": now.isoformat(timespec="seconds"),
        "asof": now.date().isoformat(),
        "events": events,
        "errors": errors,
    }


def save(snap: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snap, indent=2, ensure_ascii=False), encoding="utf-8")


def load(path: Path) -> dict:
    snap = json.loads(Path(path).read_text(encoding="utf-8"))
    if snap.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"unsupported macro snapshot schema {snap.get('schema_version')!r}")
    return snap


# ---------- pure: snapshot -> macro.json ----------

_SYMBOLS = (("≤", " le "), ("≥", " ge "), ("<", " lt "), (">", " gt "), ("↑", " up "),
            ("↓", " down "), ("+", " plus "), ("%", " pct "), ("–", " to "), ("-", " to "))


def outcome_key(label: str) -> str:
    """Stable, placeholder-safe key for an outcome label.

    '25 bps increase' -> '25_bps_increase', '≤3.3%' -> 'le_3_3_pct',
    '↓ $7,200' -> 'down_7200', '$6,000-$6,500' -> '6000_to_6500',
    '-0.2%' -> 'minus_0_2_pct'.
    """
    s = label.strip()
    s = re.sub(r"(?<=\d),(?=\d)", "", s)  # thousands separators
    s = s.replace("$", "")
    s = re.sub(r"(?<!\d)[-−](?=\d)", " minus ", s)  # a sign, not a range
    for sym, word in _SYMBOLS:
        s = s.replace(sym, word)
    s = re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")
    return s or "outcome"


def _yes_price(market: dict) -> float | None:
    outcomes, prices = market.get("outcomes"), market.get("outcomePrices")
    try:
        outcomes = json.loads(outcomes) if isinstance(outcomes, str) else outcomes
        prices = json.loads(prices) if isinstance(prices, str) else prices
        i = [o.lower() for o in outcomes].index("yes")
        return float(prices[i])
    except (TypeError, ValueError, IndexError, AttributeError):
        return None


def _num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def summarize_event(spec_entry: dict, event: dict | None, min_volume: float, error: str | None = None) -> dict:
    base = {"label": spec_entry["label"], "slug": spec_entry["slug"]}
    if event is None:
        return {**base, "status": "error" if error else "missing", "error": error}
    volume = _num(event.get("volume"))
    out = {
        **base,
        "title": event.get("title"),
        "end_date": (event.get("endDate") or "")[:10] or None,
        "status": "closed" if event.get("closed") else "open",
        "volume_usd": volume,
        "liquidity_usd": _num(event.get("liquidity")),
        "thin": volume is None or volume < min_volume,
    }
    live = [m for m in event.get("markets") or [] if not m.get("closed")]
    if len(event.get("markets") or []) == 1 and not event["markets"][0].get("groupItemTitle"):
        out["kind"] = "binary"
        out["p"] = _yes_price(event["markets"][0])
        return out

    out["kind"] = "multi"
    out["exclusive"] = bool(live) and all(m.get("negRisk") for m in live)
    outcomes = {}
    for m in live:
        label = m.get("groupItemTitle") or m.get("question") or "outcome"
        key = outcome_key(label)
        while key in outcomes:  # identical labels after normalisation
            key += "_2"
        outcomes[key] = {"label": label, "p": _yes_price(m)}
    out["outcomes"] = outcomes
    priced = {k: v["p"] for k, v in outcomes.items() if v["p"] is not None}
    if out["exclusive"] and priced:
        mode = max(priced, key=lambda k: (priced[k], k))
        out["sum_p"] = round(sum(priced.values()), 6)
        out["mode"] = outcomes[mode]["label"]
        out["mode_key"] = mode
        out["mode_p"] = priced[mode]
    else:
        out["sum_p"] = out["mode"] = out["mode_key"] = out["mode_p"] = None
    return out


def build(snap: dict, spec: dict) -> dict:
    min_volume = float(spec.get("min_volume_usd", 0))
    markets = {
        m["id"]: summarize_event(m, snap["events"].get(m["slug"]), min_volume,
                                 snap.get("errors", {}).get(m["slug"]))
        for m in spec["markets"]
    }
    n_ok = sum(1 for v in markets.values() if v["status"] == "open")
    return {
        "kind": "macro",
        "asof": snap["asof"],
        "source": snap["source"],
        "fetched_at": snap["fetched_at"],
        "markets_version": spec["version"],
        "markets_sha256": spec["_sha256"],
        "coverage": round(n_ok / len(markets), 4) if markets else 0.0,
        "markets": markets,
        "generator": "stockledger macro",
    }


# ---------- ledger ----------

def make_entry(macro: dict) -> dict:
    probs = {}
    for mid, m in macro["markets"].items():
        if m["status"] != "open":
            probs[mid] = None
        elif m["kind"] == "binary":
            probs[mid] = m["p"]
        else:
            probs[mid] = {k: o["p"] for k, o in m["outcomes"].items()}
    return {
        "id": f"macro-{macro['asof']}-{macro['markets_version']}",
        "asof": macro["asof"],
        "fetched_at": macro["fetched_at"],
        "markets_version": macro["markets_version"],
        "markets_sha256": macro["markets_sha256"],
        "probs": probs,
    }


def record(macro: dict, ledger_dir: Path) -> tuple[dict, bool]:
    """Append one snapshot per (date, market-set version) to macro.jsonl. Idempotent."""
    entry = make_entry(macro)
    p = Path(ledger_dir) / "macro.jsonl"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip() and json.loads(line)["id"] == entry["id"]:
                return entry, False
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry, True


# ---------- display ----------

def summary_lines(macro: dict) -> list[str]:
    lines = [f"macro asof {macro['asof']} (markets {macro['markets_version']}, "
             f"coverage {macro['coverage']:.0%})"]
    for mid, m in macro["markets"].items():
        tag = " [thin]" if m.get("thin") else ""
        if m["status"] != "open":
            lines.append(f"  {mid:<18} {m['status']}" + (f": {m['error']}" if m.get("error") else ""))
        elif m["kind"] == "binary":
            p = "n/a" if m["p"] is None else f"{m['p']:.1%}"
            lines.append(f"  {mid:<18} yes {p}{tag}")
        elif m["mode"] is not None:
            lines.append(f"  {mid:<18} most likely: {m['mode']} {m['mode_p']:.1%}{tag}")
        else:
            lines.append(f"  {mid:<18} {len(m['outcomes'])} overlapping thresholds{tag}")
    return lines
