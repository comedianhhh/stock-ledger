"""metrics (pure) -> score -> action -> guardrails. No I/O except reading the rules file."""

from __future__ import annotations

import hashlib
from importlib import resources
from pathlib import Path

import yaml

from . import __version__
from . import snapshot as snapshot_mod
from .factors import Annual, price, quality, risk, value

ACTION_ORDER = ["AVOID", "HOLD", "BUY"]


# ---------- rules ----------

def load_rules(path: Path | None = None) -> dict:
    text = Path(path).read_text(encoding="utf-8") if path else \
        resources.files("stockledger.rules").joinpath("v1.yaml").read_text(encoding="utf-8")
    rules = yaml.safe_load(text)
    rules["_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return rules


# ---------- metrics ----------

def compute_metrics(snap: dict) -> dict:
    a = Annual(snap)
    p = price.compute(snap["prices"], snap["benchmark"])
    info = snap.get("info", {})
    return {
        "ticker": snap["ticker"],
        "name": info.get("name"),
        "sector": info.get("sector"),
        "asof": snapshot_mod.asof_date(snap),
        "data": {
            "latest_fiscal_year_end": a.periods[0] if a.periods else None,
            "annual_periods": len(a),
            "price_bars": len(snap["prices"]["close"]),
        },
        "quality": quality.compute(a),
        "value": value.compute(a, p["price"], info.get("sector")),
        "risk": risk.compute(a, info.get("sector")),
        "price": p,
    }


def lookup(metrics: dict, path: str):
    cur = metrics
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise KeyError(path)
        cur = cur[part]
    return cur


# ---------- scoring ----------

def interpolate(x: float, curve: list[list[float]]) -> float:
    pts = sorted(curve)
    if x <= pts[0][0]:
        return float(pts[0][1])
    if x >= pts[-1][0]:
        return float(pts[-1][1])
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    raise AssertionError("unreachable")


def score(metrics: dict, rules: dict) -> dict:
    dims, total_w, total, used_w = {}, 0.0, 0.0, 0.0
    for name, d in rules["dimensions"].items():
        comps, pts_sum, w_sum, w_all = [], 0.0, 0.0, 0.0
        for c in d["components"]:
            v = lookup(metrics, c["metric"])
            w_all += c["weight"]
            if v is None:
                comps.append({"metric": c["metric"], "value": None, "points": None, "weight": c["weight"]})
                continue
            pts = interpolate(v, c["curve"])
            comps.append({"metric": c["metric"], "value": v, "points": round(pts, 2), "weight": c["weight"]})
            pts_sum += pts * c["weight"]
            w_sum += c["weight"]
        dim_score = pts_sum / w_sum if w_sum else None
        dims[name] = {"score": None if dim_score is None else round(dim_score, 2),
                      "weight": d["weight"], "components": comps}
        total_w += d["weight"]
        if dim_score is not None:
            coverage = w_sum / w_all
            total += dim_score * d["weight"] * coverage
            used_w += d["weight"] * coverage
    return {
        "total": round(total / used_w, 2) if used_w else None,
        "coverage": round(used_w / total_w, 3) if total_w else 0.0,
        "dimensions": dims,
    }


def raw_action(total: float | None, rules: dict) -> str:
    if total is None:
        return "HOLD"
    if total >= rules["actions"]["BUY"]:
        return "BUY"
    if total >= rules["actions"]["HOLD"]:
        return "HOLD"
    return "AVOID"


def apply_guardrails(action: str, metrics: dict, sc: dict, rules: dict) -> tuple[str, list[dict]]:
    g = rules["guardrails"]
    p = metrics["price"]
    z = metrics["risk"]["altman_z2"]
    pio = metrics["quality"]["piotroski"]

    def fired(gid, cond, reason):
        return {"id": gid, "cap": g[gid]["cap"], "triggered": bool(cond), "reason": reason}

    results = [
        fired("below_trend",
              p["price_vs_ma200"] is not None and p["price_vs_ma200"] < g["below_trend"]["max_price_vs_ma200"],
              "price is below its 200-day moving average"),
        fired("overextended",
              p["extension_atr"] is not None and p["extension_atr"] > g["overextended"]["max_extension_atr"],
              f"price is more than {g['overextended']['max_extension_atr']} ATRs above its 50-day average"),
        fired("distress",
              z["zone"] == g["distress"]["zone"] and pio["score"] <= g["distress"]["max_piotroski"],
              "Altman Z'' in distress zone AND weak Piotroski score"),
        fired("low_coverage",
              sc["coverage"] < g["low_coverage"]["min_coverage"],
              f"scoring input coverage {sc['coverage']:.0%} is below "
              f"{g['low_coverage']['min_coverage']:.0%}"),
    ]
    final = action
    for r in results:
        if r["triggered"] and ACTION_ORDER.index(r["cap"]) < ACTION_ORDER.index(final):
            final = r["cap"]
    return final, results


def analyze(snap: dict, rules: dict | None = None) -> dict:
    """Full deterministic pipeline: snapshot -> metrics.json dict."""
    rules = rules or load_rules()
    m = compute_metrics(snap)
    sc = score(m, rules)
    raw = raw_action(sc["total"], rules)
    final, guards = apply_guardrails(raw, m, sc, rules)
    m["score"] = sc
    m["action"] = {"raw": raw, "final": final, "guardrails": guards}
    m["rules"] = {"version": rules["version"], "sha256": rules["_sha256"]}
    m["generator"] = f"stockledger {__version__}"
    return m
