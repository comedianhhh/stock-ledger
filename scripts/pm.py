"""Polymarket read-only explorer. Public APIs only: no account, no key, no orders.

Usage:
  python pm.py top [N]             hottest open events by 24h volume
  python pm.py search <words>      find open events, e.g. "nvidia", "fed rate"
  python pm.py event <slug>        every market in one event, with Yes probability
  python pm.py book <slug> [i]     order book of market i (default 0) in that event
  python pm.py wallet <0xaddr>     any wallet's value and open positions

Add --json to any command to print raw JSON instead of a table.
"""

import json
import sys
import urllib.parse
import urllib.request

GAMMA = "https://gamma-api.polymarket.com"
DATA = "https://data-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
UA = {"User-Agent": "pm-readonly/0.1", "Accept": "application/json"}

RAW = "--json" in sys.argv
ARGS = [a for a in sys.argv[1:] if a != "--json"]


def get(base, path, **params):
    q = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    url = f"{base}{path}" + (f"?{q}" if q else "")
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
        return json.load(r)


def jlist(value):
    """Gamma returns some arrays as JSON strings."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return []
    return value or []


def yes_prob(market):
    prices = jlist(market.get("outcomePrices"))
    return float(prices[0]) if prices else None


def money(x):
    x = float(x or 0)
    return f"${x / 1e6:.1f}M" if x >= 1e6 else f"${x / 1e3:.0f}K" if x >= 1e3 else f"${x:.0f}"


def pct(p):
    return "  -  " if p is None else f"{p * 100:5.1f}%"


def live_markets(event):
    # Placeholder slots ("Candidate T" at 50%) are active=False / not accepting orders.
    ms = [m for m in event.get("markets") or []
          if not m.get("closed") and m.get("active") and m.get("acceptingOrders", True)]
    return sorted(ms, key=lambda m: -(yes_prob(m) or 0))


def show_events(events):
    for e in events:
        ms = live_markets(e)
        lead = ms[0] if ms else {}
        name = lead.get("groupItemTitle") or lead.get("question") or ""
        print(f"{money(e.get('volume24hr')):>8}  {e.get('title')}")
        if lead:
            print(f"{'':10}top: {pct(yes_prob(lead))}  {name[:70]}   ({len(ms)} markets)")
        print(f"{'':10}slug: {e.get('slug')}")


def find_event(slug):
    return get(GAMMA, f"/events/slug/{urllib.parse.quote(slug)}")


def cmd_top(n="10"):
    events = get(GAMMA, "/events", closed="false", active="true", limit=int(n),
                 order="volume24hr", ascending="false")
    return events, lambda: show_events(events)


def cmd_search(*words):
    d = get(GAMMA, "/public-search", q=" ".join(words), limit_per_type=10,
            events_status="active")
    events = [e for e in d.get("events") or [] if not e.get("closed")]
    return events, lambda: show_events(events) if events else print("no open events")


def cmd_event(slug):
    e = find_event(slug)

    def out():
        print(e.get("title"))
        print(f"24h volume {money(e.get('volume24hr'))}   ends {str(e.get('endDate'))[:10]}\n")
        for i, m in enumerate(live_markets(e)):
            label = m.get("groupItemTitle") or m.get("question")
            print(f"[{i:>2}] {pct(yes_prob(m))}  {label[:80]}")
    return e, out


def cmd_book(slug, idx="0"):
    m = live_markets(find_event(slug))[int(idx)]
    token = jlist(m.get("clobTokenIds"))[0]  # the "Yes" side
    b = get(CLOB, "/book", token_id=token)

    def out():
        print(m.get("question"), "  (Yes side)")
        asks = sorted(b.get("asks") or [], key=lambda r: float(r["price"]))[:5]
        bids = sorted(b.get("bids") or [], key=lambda r: -float(r["price"]))[:5]
        for r in reversed(asks):
            print(f"   ask {float(r['price']):.3f}  x {float(r['size']):>10.1f}")
        print("   ------------------------")
        for r in bids:
            print(f"   bid {float(r['price']):.3f}  x {float(r['size']):>10.1f}")
        if asks and bids:
            mid = (float(asks[0]["price"]) + float(bids[0]["price"])) / 2
            print(f"\nmid {mid:.3f}  spread {float(asks[0]['price']) - float(bids[0]['price']):.3f}")
    return b, out


def cmd_wallet(addr):
    # Data API v1 is retired; v2 wraps results in {"data": ...} and uses snake_case.
    value = get(DATA, "/v2/value", user=addr).get("data") or {}
    pos = get(DATA, "/v2/positions", user=addr, status="OPEN", limit=25,
              sort_by="CURRENT_VALUE", sort_direction="DESC").get("data") or []

    def out():
        print(f"positions value: {money(value.get('value'))}\n")
        for p in pos:
            print(f"{money(p.get('current_value')):>8}  {p.get('outcome', ''):<4}"
                  f" @ {float(p.get('avg_price') or 0):.3f} -> {float(p.get('current_price') or 0):.3f}"
                  f"  pnl {float(p.get('percent_pnl') or 0):+6.1f}%  {p.get('title', '')[:55]}")
    return {"value": value, "positions": pos}, out


COMMANDS = {"top": cmd_top, "search": cmd_search, "event": cmd_event,
            "book": cmd_book, "wallet": cmd_wallet}

if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if not ARGS or ARGS[0] not in COMMANDS:
        print(__doc__)
        sys.exit(1)
    data, render = COMMANDS[ARGS[0]](*ARGS[1:])
    print(json.dumps(data, indent=2, ensure_ascii=False)) if RAW else render()
