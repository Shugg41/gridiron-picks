#!/usr/bin/env python3
"""Three independent opinions per game, recorded every week.

The pool cannot be beaten by picking the favourite — eight weeks of
field data say nobody has ever won a week doing it — and it cannot be
beaten by taking underdogs at random either, which the same eight weeks
say just as clearly. What is left is picking better, and that needs a
view of a game that does not come from the same place as everyone
else's.

Splash states a win probability, but the user established it is derived
from Splash's own line, so it is the market wearing a hat. Two genuinely
separate numbers exist and neither has ever been written down:

  market  the sportsbook spread ESPN carries, devigged
  fpi     ESPN's power index, which is preseason-informed and does not
          look at the price at all

This records all three for every game on the board, week by week, so
that in a month there is a record to measure instead of an argument to
have. Nothing here picks anything. It only writes down what each source
believed before the games were played, which is the one thing that
cannot be reconstructed afterwards.

Appends TSV to data/opinions.tsv via the CI log — the workflow has no
write access, so the rows are read out of the log and committed.

Run via .github/workflows/data-probe.yml.
"""
import datetime
import json
import math
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
# Home advantage in points. The same values fpi_edge() uses, kept here
# rather than imported so a change there cannot silently rewrite history
# already recorded under the old number.
HFA = {"NFL": 2.0, "CFB": 2.6}


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "gridiron-probe"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


_TEAM = {}


def team_of(ref):
    """A side the matcher can actually work with, memoised per team.

    Not just the abbreviation. espn.link derives the codes other
    scoreboards use — Splash's JAC, WAS and LA for ESPN's JAX, WSH and
    LAR — from a team's location and name, so handing it an
    abbreviation alone leaves it nothing to derive from. That cost
    five games on a board where the data was sitting right there:
    Jacksonville, the Rams and Washington in the NFL, Northwestern and
    South Carolina in college.

    The same memo that took the line backfill from timing out at 43
    games to finishing all 75.
    """
    if ref not in _TEAM:
        try:
            d = get(ref)
            _TEAM[ref] = {"id": str(d.get("id")), "abbr": d.get("abbreviation"),
                          "full_name": d.get("displayName"),
                          "location": d.get("location"), "name": d.get("name")}
        except Exception:
            _TEAM[ref] = None
    return _TEAM[ref]


def dates_for(rows):
    """The calendar days the board's kickoffs fall on, in ESPN's terms.

    Both the UTC day and the one before it, because ESPN keys an event
    to its own local date and the board stores kickoffs in UTC: a
    Saturday 11pm Eastern game is Sunday in UTC and Saturday to ESPN.
    Asking for both and letting the matcher discard the surplus is
    cheaper than being clever about time zones twice a year.
    """
    days = set()
    for r in rows:
        iso = r["kickoff"]
        if not iso:
            continue
        d = datetime.datetime.strptime(iso[:10], "%Y-%m-%d")
        days.add(d.strftime("%Y%m%d"))
        days.add((d - datetime.timedelta(days=1)).strftime("%Y%m%d"))
    return sorted(days)


def events_for(league, day):
    """Every event ESPN has on a calendar day.

    NOT the week listing. types/2/weeks/N/events is a curated slate —
    eighteen events for a college Saturday that actually holds
    forty-seven — so five of the board's sixteen college games had no
    price and it looked like the matcher failing. Keyed by date it is
    the whole card.
    """
    out = []
    try:
        listing = get(f"{CORE}/{league}/events?dates={day}&limit=300")
    except urllib.error.HTTPError as exc:
        print(f"# {league} {day}: HTTP {exc.code}", file=sys.stderr)
        return out
    items = listing.get("items", [])
    for item in items:
        try:
            event = get(item["$ref"])
            comp = (event.get("competitions") or [])[0]
        except Exception:
            continue
        sides = {}
        for c in comp.get("competitors") or []:
            ref = (c.get("team") or {}).get("$ref")
            if ref:
                sides[c.get("homeAway")] = team_of(ref)
        if not sides.get("home") or not sides.get("away"):
            continue
        if not sides["home"].get("abbr") or not sides["away"].get("abbr"):
            continue
        out.append({"away": sides["away"], "home": sides["home"],
                    "event_id": str(event.get("id")),
                    "league": "NFL" if league == "nfl" else "CFB"})
    print(f"# {league} {day}: {len(items)} events, {len(out)} usable",
          file=sys.stderr)
    return out


def normal(margin, sd):
    return 0.5 * (1 + math.erf((margin / sd) / math.sqrt(2)))


def market_home(event):
    """P(home wins) from the sportsbook spread, or None.

    The spread rather than the moneyline because it is the field ESPN
    fills in most reliably across both leagues, and because converting
    it needs no devigging.
    """
    try:
        odds = espn.odds_history(event["event_id"], event["league"])
        details = ((odds.get("items") or [{}])[0]).get("details")
    except Exception:
        return None
    named, value = espn._spread(details)
    if not named or value is None:
        return None
    # "BUF -3.5" names the favourite; the sign is relative to that team.
    home_margin = -value if named == event["home"]["abbr"] else value
    return normal(home_margin, espn.MARGIN_SD.get(event["league"], 14.5))


def fpi_home(event):
    """P(home wins) from FPI alone — no price anywhere in it."""
    try:
        h = espn.power_index(event["home"]["id"], event["league"], SEASON)
        a = espn.power_index(event["away"]["id"], event["league"], SEASON)
    except Exception:
        return None
    if not h or not a or h.get("fpi") is None or a.get("fpi") is None:
        return None
    margin = (h["fpi"] + HFA[event["league"]]) - a["fpi"]
    return normal(margin, espn.MARGIN_SD.get(event["league"], 14.5))


def main():
    week = int(sys.argv[1]) if len(sys.argv) > 1 else None
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    if week is None:
        week = conn.execute("SELECT MAX(week) FROM game WHERE season=?",
                            (SEASON,)).fetchone()[0]
    rows = conn.execute(
        "SELECT away_code, home_code, away, home, away_prob, home_prob, "
        "kickoff FROM game WHERE season=? AND week=? ORDER BY seq",
        (SEASON, week)).fetchall()
    games = [splash.Game(away_code=r["away_code"], home_code=r["home_code"],
                         away=r["away"] or "", home=r["home"] or "")
             for r in rows]
    stated = {(r["away_code"], r["home_code"]): r["home_prob"] for r in rows}
    print(f"# week {week}: {len(games)} board games", file=sys.stderr)

    pool = []
    for day in dates_for(rows):
        pool += events_for("nfl", day)
        pool += events_for("college-football", day)
    seen, uniq = set(), []
    for ev in pool:
        if ev["event_id"] not in seen:
            seen.add(ev["event_id"])
            uniq.append(ev)
    pool = uniq
    print(f"# espn events usable: {len(pool)}", file=sys.stderr)

    print("week\taway\thome\tsplash_home\tmarket_home\tfpi_home")
    matched = priced = rated = 0
    for g, ev in espn.link(games, pool):
        if not ev:
            continue
        matched += 1
        mkt, fpi = market_home(ev), fpi_home(ev)
        priced += mkt is not None
        rated += fpi is not None
        sp = stated.get((g.away_code, g.home_code))
        fmt = lambda v: "" if v is None else f"{v:.4f}"
        print(f"{week}\t{g.away_code}\t{g.home_code}\t"
              f"{fmt(sp)}\t{fmt(mkt)}\t{fmt(fpi)}")
    print(f"# matched {matched}/{len(games)}, priced {priced}, fpi {rated}",
          file=sys.stderr)
    conn.close()


if __name__ == "__main__":
    main()
