"""Citation-by-construction.

The LLM writes a report *template*: every number is a placeholder such as
`{{ value.earnings_yield | pct }}` that points into metrics.json. `check`
rejects templates with unknown paths or hand-typed numbers; `render`
substitutes the real values. The model can reason about the numbers, but it
never types them, so it cannot misquote them.
"""

from __future__ import annotations

import re

from .scoring import lookup

PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z0-9_.]+)\s*(?:\|\s*(\w+)\s*)?\}\}")

# Hand-typed numbers we refuse: decimals, percentages, $amounts, 12.3x / 4B style.
# Plain integers ("200-day", "12-1 momentum", "2026", "9 checks") are allowed.
BARE_NUMBER = re.compile(
    r"(?<![\w.])(?:\$\s?\d[\d,]*(?:\.\d+)?"          # $123 / $1,234.5
    r"|\d[\d,]*\.\d+\s?(?:%|x|[BMK]\b)?"             # 12.5 / 12.5% / 3.2x / 1.5B
    r"|\d[\d,]*\s?%"                                  # 12%
    r"|\d[\d,]*(?:x|[BMK])\b)"                        # 30x / 3B
)

FORMATS = {
    "pct": lambda v: f"{v * 100:.1f}%",
    "num": lambda v: f"{v:,.2f}",
    "int": lambda v: f"{v:,.0f}",
    "usd": lambda v: f"${v:,.2f}",
    "usd_b": lambda v: f"${v / 1e9:,.1f}B",
    "x": lambda v: f"{v:.1f}x",
}


def fmt(value, kind: str | None) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if kind:
        if kind not in FORMATS:
            raise ValueError(f"unknown format {kind!r}; use one of {sorted(FORMATS)}")
        return FORMATS[kind](value)
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)


def check(template: str, metrics: dict) -> dict:
    unresolved, bad_formats, bare = [], [], []
    for m in PLACEHOLDER.finditer(template):
        path, kind = m.group(1), m.group(2)
        try:
            v = lookup(metrics, path)
            if isinstance(v, (dict, list)):
                unresolved.append(f"{path} (is a {type(v).__name__}, cite a leaf value)")
        except KeyError:
            unresolved.append(path)
        if kind and kind not in FORMATS:
            bad_formats.append(f"{path} | {kind}")
    in_code = False
    for n, line in enumerate(template.splitlines(), 1):
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        stripped = PLACEHOLDER.sub("", line)
        stripped = re.sub(r"`[^`]*`", "", stripped)  # inline code is exempt
        for tok in BARE_NUMBER.findall(stripped):
            bare.append({"line": n, "token": tok.strip()})
    return {
        "ok": not (unresolved or bad_formats or bare),
        "placeholders": len(PLACEHOLDER.findall(template)),
        "unresolved": unresolved,
        "bad_formats": bad_formats,
        "bare_numbers": bare,
    }


def render(template: str, metrics: dict) -> str:
    return PLACEHOLDER.sub(lambda m: fmt(lookup(metrics, m.group(1)), m.group(2)), template)
