#!/usr/bin/env python3
"""Rate a weekend before the board exists.

The board has been the bottleneck: nothing could be priced until
Splash posted a slate and it was pasted in. But Splash does not decide
which games are played, only which thirty are on the card, and they
are drawn from a predictable pool — every NFL game, and the college
games anyone would put on television. ESPN will hand over all of them
keyed by date, days ahead.

So this prices the whole weekend in advance. When the board lands,
nearly every game on it already has a number and the pasting is a
formality rather than the thing that gates the work.

Two numbers per game, neither of them Splash's:

  market  the sportsbook spread ESPN carries, as a win probability
  fpi     ESPN's power index, which never looks at the price

College football runs to about fifty games on a Saturday and the pool
carries sixteen. Ranked teams and games the market has bothered to
price are what survive the filter, which is close to how Splash seems
to choose.

    python scripts/lookahead.py 20261107 20261108 20261109

With no dates, takes the next Thursday through Monday.
Run via .github/workflows/data-probe.yml.
"""
import datetime
import json
import math
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from gridiron import espn                                     # noqa: E402

CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues"
SEASON = 2026
HFA = {"NFL": 2.0, "CFB": 2.6}
# The market's weight in the blend. FPI is the only input that never
# looks at the price, which is what makes it worth a third of the vote
# and not more: it is also the one with no money behind it.
W_MKT = 2 / 3


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "gridiron-probe"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


_TEAM = {}


def team_of(ref):
    if ref not in _TEAM:
        try:
            d = get(ref)
            _TEAM[ref] = {"id": str(d.get("id")), "abbr": d.get("abbreviation"),
                          "name": d.get("displayName") or d.get("name")}
        except Exception:
            _TEAM[ref] = None
    return _TEAM[ref]


def events(league, day):
    out = []
    try:
        listing = get(f"{CORE}/{league}/events?dates={day}&limit=300")
    except urllib.error.HTTPError as exc:
        print(f"# {league} {day}: HTTP {exc.code}", file=sys.stderr)
        return out
    for item in listing.get("items", []):
        try:
            ev = get(item["$ref"])
            comp = (ev.get("competitions") or [])[0]
        except Exception:
            continue
        sides, rank = {}, {}
        for c in comp.get("competitors") or []:
            ref = (c.get("team") or {}).get("$ref")
            if not ref:
                continue
            side = team_of(ref)
            if not side or not side.get("abbr"):
                continue
            sides[c.get("homeAway")] = side
            cr = (c.get("curatedRank") or {}).get("current")
            # 99 is ESPN's "unranked", not a 99th-place team.
            if cr and cr < 99:
                rank[c.get("homeAway")] = cr
        if len(sides) != 2:
            continue
        out.append({"away": sides["away"], "home": sides["home"],
                    "rank": rank, "event_id": str(ev.get("id")),
                    "kick": (ev.get("date") or "")[:16],
                    "league": "NFL" if league == "nfl" else "CFB"})
    print(f"# {league} {day}: {len(out)} games", file=sys.stderr)
    return out


def normal(margin, sd):
    return 0.5 * (1 + math.erf((margin / sd) / math.sqrt(2)))


def market_home(ev):
    try:
        odds = espn.odds_history(ev["event_id"], ev["league"])
        details = ((odds.get("items") or [{}])[0]).get("details")
    except Exception:
        return None
    named, value = espn._spread(details)
    if not named or value is None:
        return None
    home_margin = -value if named == ev["home"]["abbr"] else value
    return normal(home_margin, espn.MARGIN_SD.get(ev["league"], 14.5))


def fpi_home(ev):
    try:
        h = espn.power_index(ev["home"]["id"], ev["league"], SEASON)
        a = espn.power_index(ev["away"]["id"], ev["league"], SEASON)
    except Exception:
        return None
    if not h or not a or h.get("fpi") is None or a.get("fpi") is None:
        return None
    return normal((h["fpi"] + HFA[ev["league"]]) - a["fpi"],
                  espn.MARGIN_SD.get(ev["league"], 14.5))


def next_weekend():
    today = datetime.date.today()
    thu = today + datetime.timedelta((3 - today.weekday()) % 7)
    return [(thu + datetime.timedelta(n)).strftime("%Y%m%d") for n in range(5)]


def main():
    days = sys.argv[1:] or next_weekend()
    print(f"# days: {', '.join(days)}", file=sys.stderr)
    pool, seen = [], set()
    for day in days:
        for league in ("nfl", "college-football"):
            for ev in events(league, day):
                if ev["event_id"] not in seen:
                    seen.add(ev["event_id"])
                    pool.append(ev)

    rows = []
    for ev in pool:
        mkt, fpi = market_home(ev), fpi_home(ev)
        if mkt is None and fpi is None:
            continue
        # A college game with no price and nobody ranked is not going on
        # anyone's card; dropping it keeps the list readable.
        if ev["league"] == "CFB" and mkt is None and not ev["rank"]:
            continue
        if mkt is None:
            blend = fpi
        elif fpi is None:
            blend = mkt
        else:
            blend = W_MKT * mkt + (1 - W_MKT) * fpi
        pick = ev["home"] if blend >= 0.5 else ev["away"]
        rows.append({"ev": ev, "mkt": mkt, "fpi": fpi, "blend": blend,
                     "pick": pick, "conf": max(blend, 1 - blend)})

    rows.sort(key=lambda r: (r["ev"]["kick"], r["ev"]["league"]))
    print("kick\tleague\taway\thome\tranked\tmarket_home\tfpi_home\tpick\tconf")
    for r in rows:
        ev = r["ev"]
        rk = "/".join(f"{k}#{v}" for k, v in sorted(ev["rank"].items())) or ""
        fmt = lambda v: "" if v is None else f"{v:.4f}"
        print(f"{ev['kick']}\t{ev['league']}\t{ev['away']['abbr']}\t"
              f"{ev['home']['abbr']}\t{rk}\t{fmt(r['mkt'])}\t{fmt(r['fpi'])}\t"
              f"{r['pick']['abbr']}\t{r['conf']:.3f}")

    split = [r for r in rows if r["mkt"] is not None and r["fpi"] is not None
             and (r["mkt"] - .5) * (r["fpi"] - .5) < 0]
    print(f"\n# {len(rows)} games rated; market and FPI pick different sides "
          f"in {len(split)}", file=sys.stderr)
    for r in split:
        ev = r["ev"]
        print(f"#   {ev['away']['abbr']}@{ev['home']['abbr']}: "
              f"market {r['mkt']:.0%} home, fpi {r['fpi']:.0%} home",
              file=sys.stderr)


if __name__ == "__main__":
    main()
