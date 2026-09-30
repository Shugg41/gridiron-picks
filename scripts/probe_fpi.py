#!/usr/bin/env python3
"""Does FPI actually come back, and does it ever disagree with the line?

Every pick the app makes comes from one number: the betting line.
power_index() and fpi_edge() have been written and tested since the
rebuild and are called by nothing, so the card is a line-reader with a
statistics module bolted on the side and unplugged.

Before plugging it in, two things have to be true, and neither is
obvious:

  1. The endpoint returns FPI for these teams, this season. It is on
     the core API, which CI can reach, so this is answerable here.
  2. FPI disagrees with the market often enough and by enough to be
     worth acting on. If every edge is a point of win probability, it
     is noise dressed as insight and wiring it in would make the card
     look cleverer without being righter.

Prints the edge for every game on the slate so the distribution is
visible, not just the handful that flatter the idea.

Run via .github/workflows/data-probe.yml.
"""
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from gridiron import espn, model                               # noqa: E402

CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "gridiron-probe"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def team_of(competitor):
    ref = (competitor.get("team") or {}).get("$ref")
    if not ref:
        return None, None
    data = get(ref)
    return str(data.get("id")), data.get("abbreviation")


def probe(league, week, season=2026, limit=20):
    tag = "NFL" if league == "nfl" else "CFB"
    print(f"\n{'=' * 74}\n{tag} week {week}\n{'=' * 74}")
    try:
        listing = get(f"{CORE}/{league}/seasons/{season}/types/2/weeks/{week}/"
                      f"events?limit={limit}")
    except urllib.error.HTTPError as exc:
        print(f"listing failed: HTTP {exc.code}")
        return []

    edges = []
    for item in listing.get("items", []):
        try:
            event = get(item["$ref"])
            comps = (event.get("competitions") or [])[0]
        except Exception as exc:
            print(f"  event failed: {type(exc).__name__}")
            continue

        sides = {}
        for c in comps.get("competitors") or []:
            tid, abbr = team_of(c)
            sides[c.get("homeAway")] = (tid, abbr)
        (hid, habbr), (aid, aabbr) = sides.get("home", (None, None)), \
            sides.get("away", (None, None))
        if not hid or not aid:
            continue

        try:
            fh = espn.power_index(hid, tag, season)
            fa = espn.power_index(aid, tag, season)
        except Exception as exc:
            print(f"  {aabbr}@{habbr}: FPI failed {type(exc).__name__}")
            continue

        # the market's view, from the same odds the card already uses
        try:
            odds = espn.odds_history(str(event.get("id")), tag)
            first = (odds.get("items") or [{}])[0]
            details = first.get("details")
        except Exception:
            details = None
        # "ARI -1.5" names the team laying the points; "GB +3.5" names
        # the one getting them. Getting that backwards is what once had
        # the card recommending the wrong side, so it is spelled out.
        shim = {"league": tag, "home": {"abbr": habbr}, "away": {"abbr": aabbr}}
        named, value = espn._spread(details)
        if named and value is not None:
            shim["fav_abbr"] = named if value < 0 else (
                aabbr if named == habbr else habbr)
            shim["line"] = abs(value)
        edge = model.fpi_edge(shim, fh.get("fpi"), fa.get("fpi"))
        print(f"  {str(aabbr):>5}@{str(habbr):<5} "
              f"FPI {str(fa.get('fpi')):>7} / {str(fh.get('fpi')):<7} "
              f"line={details!r:>12}  edge={edge if edge is None else round(edge, 3)}")
        if edge is not None:
            edges.append(abs(edge))
    return edges


def verdict(edges):
    if not edges:
        print("\nNo edges computed at all — FPI or the odds shim is not "
              "returning what this needs.")
        return
    edges.sort()
    mid = edges[len(edges) // 2]
    big = [e for e in edges if e >= 0.05]
    print(f"\n{len(edges)} games with an edge. median {mid:.3f}, "
          f"max {edges[-1]:.3f}")
    print(f"{len(big)} disagree with the market by 5 points of win "
          f"probability or more.")
    print("If that count is near zero, FPI is agreeing with the line and "
          "wiring it in buys nothing.")


if __name__ == "__main__":
    all_edges = probe("nfl", 4) + probe("college-football", 5, limit=12)
    verdict(all_edges)
