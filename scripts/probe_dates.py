#!/usr/bin/env python3
"""Does ESPN's scoreboard serve NEXT week's games, and can we ask for them?

The app calls the site scoreboard with no date, so it gets whatever ESPN
calls "this week". On a Tuesday that is the week just finished, which is
why the live card read "No line yet" on 34 of 36 games two days before a
deadline — the games were not in the payload at all.

The fix is presumably ?dates=YYYYMMDD-YYYYMMDD, but presumably is how
this project keeps shipping bugs, so this asks:

  1. Does site.api answer a GitHub runner at all? The existing probe says
     403, but it identifies itself as "gridiron-probe" — that may be the
     whole reason, and it matters because everything else here is blocked
     on being able to test site.api from CI.
  2. What does the default scoreboard actually contain today?
  3. Does a dates range change that, and to what?
  4. Of the 36 games on the real board, how many does each call cover?

Run via .github/workflows/data-probe.yml, read the logs.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from gridiron import espn, splash                              # noqa: E402

SITE = "https://site.api.espn.com/apis/site/v2/sports/football"
# A real browser's, because "gridiron-probe" may be the entire problem.
BROWSER = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
           "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")
BOARD = os.path.join(os.path.dirname(__file__), "..", "tests", "fixtures",
                     "board_week5.txt")


def get(url, ua):
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def fetch(league, ua, params=""):
    url = f"{SITE}/{league}/scoreboard?limit=400{params}"
    try:
        data = get(url, ua)
    except urllib.error.HTTPError as exc:
        return None, f"HTTP {exc.code}"
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"
    return [espn.parse_event(e, "NFL") for e in data.get("events", [])], None


def summarise(label, events):
    if events is None:
        return
    days = Counter((e.get("date") or "?")[:10] for e in events)
    print(f"  {label}: {len(events)} events  "
          f"dates {dict(sorted(days.items()))}")


def main():
    board = splash.parse_board(open(BOARD).read()).games
    want = {(g.away_code, g.home_code) for g in board}
    print(f"board: {len(board)} games, "
          f"{min(g.kickoff_iso for g in board)[:10]} to "
          f"{max(g.kickoff_iso for g in board)[:10]}")

    dates = (f"&dates={min(g.kickoff_iso for g in board)[:10].replace('-', '')}"
             f"-{max(g.kickoff_iso for g in board)[:10].replace('-', '')}")
    print(f"dates parameter: {dates}\n")

    for ua_name, ua in (("gridiron-probe", "gridiron-probe"),
                        ("browser UA", BROWSER)):
        print(f"=== {ua_name} ===")
        pool = []
        for league in ("nfl", "college-football"):
            for label, params in (("default", ""), ("with dates", dates)):
                events, err = fetch(league, ua, params)
                if err:
                    print(f"  {league} {label}: {err}")
                    continue
                summarise(f"{league} {label}", events)
                if label == "with dates":
                    pool += events
        if pool:
            linked = espn.link(board, pool)
            hit = sum(1 for _g, ev in linked if ev)
            print(f"  --> dates covers {hit} of {len(want)} board games")
            missed = [f"{g.away_code}@{g.home_code}"
                      for g, ev in linked if not ev]
            print(f"  --> missing: {', '.join(missed) if missed else 'none'}")
        print()


if __name__ == "__main__":
    main()
