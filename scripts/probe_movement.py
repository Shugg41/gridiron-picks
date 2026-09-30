#!/usr/bin/env python3
"""Is the line movement the app reports real?

The live card recommends exactly one flip — the Giants over Arizona —
and justifies it with "the line has moved 8.5 points toward ARI since
it opened". Eight and a half points is an enormous move for an NFL
game. Either something happened, or the opening price being compared
against is not what it looks like, and the user is about to act on it
either way.

The arithmetic is sign-consistent — both prices are read from the home
side's own point of view — so this asks the only remaining question:
what does ESPN actually serve for open and current?

Printing every game's movement, not just the one, is deliberate. A
single 8.5 might be real news; a whole slate of them is a bug, and
that difference is only visible in the distribution.

Note the numbering: the pool's "week 5" is NFL week 4. Run via
.github/workflows/data-probe.yml.
"""
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from gridiron import espn                                      # noqa: E402

CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "gridiron-probe"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def sides(event):
    """(away_abbr, home_abbr) for a core-API event."""
    out = {}
    for comp in (event.get("competitions") or [])[:1]:
        for c in comp.get("competitors") or []:
            ref = (c.get("team") or {}).get("$ref")
            if not ref:
                continue
            try:
                out[c.get("homeAway")] = get(ref).get("abbreviation")
            except Exception:
                out[c.get("homeAway")] = "?"
    return out.get("away"), out.get("home")


def probe(league, week, season=2026, limit=20):
    print(f"\n{'=' * 72}\n{league} week {week}\n{'=' * 72}")
    try:
        listing = get(f"{CORE}/{league}/seasons/{season}/types/2/weeks/{week}/"
                      f"events?limit={limit}")
    except urllib.error.HTTPError as exc:
        print(f"listing failed: HTTP {exc.code}")
        return
    moves = []
    for item in listing.get("items", []):
        try:
            event = get(item["$ref"])
        except Exception as exc:
            print(f"  event failed: {type(exc).__name__}")
            continue
        eid = str(event.get("id"))
        away, home = sides(event)
        try:
            odds = espn.odds_history(eid, "NFL" if league == "nfl" else "CFB")
        except Exception as exc:
            print(f"  {away}@{home}: odds failed {type(exc).__name__}")
            continue
        items = odds.get("items") or []
        if not items:
            print(f"  {away}@{home}: no odds")
            continue
        first = items[0]
        hb = first.get("homeTeamOdds") or {}
        opened = espn._point_spread(hb.get("open"))
        now = espn._point_spread(hb.get("current"))
        pts, team = espn.movement(odds, home, away)
        provider = (first.get("provider") or {}).get("name")
        print(f"  {str(away):>5}@{str(home):<5} details={first.get('details')!r:>12}"
              f"  home open={opened} current={now}"
              f"  -> moved {pts} toward {team}   [{provider}]")
        if pts:
            moves.append(pts)
    if moves:
        moves.sort()
        print(f"\n  {len(moves)} games moved. median "
              f"{moves[len(moves) // 2]}, max {moves[-1]}")
        big = [m for m in moves if m >= 5]
        print(f"  {len(big)} moved 5+ points — if that is most of the slate, "
              f"the opening price is not an opening price")


if __name__ == "__main__":
    # the pool's week 5 is NFL week 4
    probe("nfl", 4)
