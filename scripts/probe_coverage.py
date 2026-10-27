#!/usr/bin/env python3
"""Why does college football come back 18 games short?

The week-9 board carries sixteen college games and ESPN's
types/2/weeks/9 listing holds eighteen events, only five of which are
on it. Pagination was the obvious suspect and was wrong — the listing
is one page and genuinely that short. So either the week number does
not mean what it looks like, or this endpoint is not the full slate.

Asks four questions and prints the answers rather than guessing:
  1. What dates are actually in CFB weeks 8, 9 and 10?
  2. How many events does each hold?
  3. Does the date-keyed events endpoint hold more for Oct 31?
  4. Does the site scoreboard, which the Streamlit host can reach
     even though CI cannot, hold more still?

Run via .github/workflows/data-probe.yml.
"""
import json
import sys
import urllib.error
import urllib.request
from collections import Counter

CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues"
SITE = "https://site.api.espn.com/apis/site/v2/sports/football"
SEASON = 2026


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "gridiron-probe"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def week_listing(week):
    url = (f"{CORE}/college-football/seasons/{SEASON}/types/2/weeks/{week}/"
           f"events?limit=100")
    try:
        data = get(url)
    except urllib.error.HTTPError as exc:
        print(f"  week {week}: HTTP {exc.code}")
        return
    items = data.get("items", [])
    print(f"  week {week}: count={data.get('count')} pageCount="
          f"{data.get('pageCount')} items={len(items)}")
    days = Counter()
    for it in items[:100]:
        try:
            ev = get(it["$ref"])
        except Exception:
            continue
        days[(ev.get("date") or "")[:10]] += 1
    print(f"    dates: {dict(sorted(days.items()))}")


def by_date(day):
    url = f"{CORE}/college-football/events?dates={day}&limit=300"
    try:
        data = get(url)
    except urllib.error.HTTPError as exc:
        print(f"  core by-date {day}: HTTP {exc.code}")
        return
    print(f"  core by-date {day}: count={data.get('count')} "
          f"pageCount={data.get('pageCount')} items={len(data.get('items', []))}")


def site_scoreboard(day):
    url = (f"{SITE}/college-football/scoreboard"
           f"?dates={day}&groups=80&limit=300")
    try:
        data = get(url)
    except urllib.error.HTTPError as exc:
        print(f"  site scoreboard {day}: HTTP {exc.code}")
        return
    except Exception as exc:
        print(f"  site scoreboard {day}: {type(exc).__name__} {exc}")
        return
    print(f"  site scoreboard {day}: {len(data.get('events') or [])} events")


print("1-2. core week listings")
for w in (8, 9, 10):
    week_listing(w)
print("\n3. core, keyed by date")
for d in ("20261030", "20261031"):
    by_date(d)
print("\n4. site scoreboard, keyed by date")
for d in ("20261030", "20261031"):
    site_scoreboard(d)
