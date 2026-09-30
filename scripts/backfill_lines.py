#!/usr/bin/env python3
"""Recover the closing line for games already played.

Crowd shares on their own say nothing. "89.5% on Green Bay" is only
interesting next to the price the pool was offered: backing a
three-point favourite that hard is very different from backing a
fourteen-point one, and it is that relationship — how heavily this
pool piles on at a given line — that lets the field be predicted
before a deadline instead of read after it.

The shares are in the database for 71 games. The lines are not, so
they are fetched from the core API, which CI can reach and the dev
sandbox cannot.

Two things worth knowing about the mapping:

  * The pool's week N is CFB week N and NFL week N-1. Week 4 of the
    pool is "NFL Week 3 | CFB Week 4". Both leagues have to be asked,
    under different numbers.
  * Matching is by code pair through espn.link, the same function the
    app uses, so ESPN's spelling of a team is reconciled with
    Splash's exactly once and in one place.

Prints TSV to stdout — week, codes, line, favourite, crowd share on
the favourite — so the result can be read out of the CI log and
stored without giving this workflow write access to the repository.

Run via .github/workflows/data-probe.yml.
"""
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from gridiron import espn, splash                              # noqa: E402

CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues"
DB = os.path.join(os.path.dirname(__file__), "..", "football_picks.db")
SEASON = 2026


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "gridiron-probe"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def abbr_of(ref):
    try:
        return get(ref).get("abbreviation")
    except Exception:
        return None


def events_for(league, week):
    """Parsed-enough events for one ESPN week: codes, id, and the line."""
    out = []
    try:
        listing = get(f"{CORE}/{league}/seasons/{SEASON}/types/2/weeks/{week}/"
                      f"events?limit=60")
    except urllib.error.HTTPError as exc:
        print(f"# {league} week {week}: HTTP {exc.code}", file=sys.stderr)
        return out
    for item in listing.get("items", []):
        try:
            event = get(item["$ref"])
            comp = (event.get("competitions") or [])[0]
        except Exception:
            continue
        sides = {}
        for c in comp.get("competitors") or []:
            ref = (c.get("team") or {}).get("$ref")
            if ref:
                sides[c.get("homeAway")] = abbr_of(ref)
        if not sides.get("home") or not sides.get("away"):
            continue
        tag = "NFL" if league == "nfl" else "CFB"
        details = None
        try:
            odds = espn.odds_history(str(event.get("id")), tag)
            details = ((odds.get("items") or [{}])[0]).get("details")
        except Exception:
            pass
        named, value = espn._spread(details)
        if not named or value is None:
            continue
        # "ARI -1.5" names the team laying the points, "GB +3.5" the
        # one getting them.
        fav = named if value < 0 else (sides["away"] if named == sides["home"]
                                       else sides["home"])
        out.append({"away": {"abbr": sides["away"]}, "home": {"abbr": sides["home"]},
                    "event_id": str(event.get("id")), "fav": fav,
                    "line": abs(value)})
    return out


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    weeks = [r[0] for r in conn.execute(
        "SELECT DISTINCT week FROM field WHERE season=? ORDER BY week",
        (SEASON,))]
    print(f"# weeks with crowd shares: {weeks}", file=sys.stderr)
    print("week\taway\thome\tline\tfav\tfav_share")

    for week in weeks:
        games = [splash.Game(away_code=r["away_code"], home_code=r["home_code"],
                             away=r["away"] or "", home=r["home"] or "")
                 for r in conn.execute(
                     "SELECT away_code, home_code, away, home FROM game "
                     "WHERE season=? AND week=?", (SEASON, week))]
        share = {}
        for r in conn.execute(
                "SELECT away_code, home_code, team, pct FROM field "
                "WHERE season=? AND week=?", (SEASON, week)):
            share[(r["away_code"], r["home_code"], r["team"])] = r["pct"]

        pool = events_for("nfl", week - 1) + events_for("college-football", week)
        hit = 0
        for g, ev in espn.link(games, pool):
            if not ev:
                continue
            pct = share.get((g.away_code, g.home_code, ev["fav"]))
            if pct is None:
                # ESPN's favourite spelled its way; try the board's
                pct = share.get((g.away_code, g.home_code,
                                 g.home_code if ev["fav"] == ev["home"]["abbr"]
                                 else g.away_code))
            if pct is None:
                continue
            fav_code = (g.home_code if ev["fav"] == ev["home"]["abbr"]
                        else g.away_code)
            print(f"{week}\t{g.away_code}\t{g.home_code}\t{ev['line']:g}\t"
                  f"{fav_code}\t{pct:.3f}")
            hit += 1
        print(f"# week {week}: {hit} of {len(games)} games priced",
              file=sys.stderr)
    conn.close()


if __name__ == "__main__":
    main()
