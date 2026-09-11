#!/usr/bin/env python3
"""Dump the exact stat field names from ESPN's core API.

Established by earlier runs: site.api.espn.com 403s from GitHub runners,
but sports.core.api.espn.com serves fine — and that's where team stats
live. The app (on Streamlit Cloud) can reach both. This prints the real
category/stat names so the stats parser isn't written from memory.
"""
import json
import urllib.error
import urllib.request

CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues"
UA = {"User-Agent": "Mozilla/5.0"}


def get(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        print(f"    HTTP {e.code}  {url[:120]}")
    except Exception as e:
        print(f"    {type(e).__name__}: {e}  {url[:120]}")
    return None


def banner(t):
    print("\n" + "=" * 72 + f"\n{t}\n" + "=" * 72)


# 99 = LSU (CFB), 12 = Chiefs (NFL) — any real id works for shape discovery
for league, tid, season in (("college-football", "99", 2026), ("nfl", "12", 2026)):
    for yr in (season, season - 1):
        banner(f"{league} team {tid} — season {yr} statistics")
        st = get(f"{CORE}/{league}/seasons/{yr}/types/2/teams/{tid}/statistics")
        if not st:
            continue
        splits = st.get("splits") or {}
        print(f"  splits keys: {list(splits)}")
        for cat in splits.get("categories") or []:
            stats = cat.get("stats") or []
            print(f"\n  ── category '{cat.get('name')}' ({len(stats)} stats)")
            for s in stats:
                print(f"     {s.get('name'):32s} value={s.get('value')!s:12s} "
                      f"display={s.get('displayValue')!s:12s} perGame={s.get('perGameValue')}")

    banner(f"{league} team {tid} — power index (FPI) candidates")
    for url in (f"{CORE}/{league}/seasons/{season}/types/2/teams/{tid}/powerindex",
                f"{CORE}/{league}/seasons/{season}/powerindex/{tid}",
                f"{CORE}/{league}/seasons/{season}/types/2/teams/{tid}/record"):
        r = get(url)
        if r:
            print(f"  OK {url[:120]}")
            print("  " + json.dumps(r, indent=2)[:1500])

banner("does core API expose a season's team list (id -> abbrev map)?")
r = get(f"{CORE}/college-football/seasons/2026/types/2/teams?limit=5")
if r:
    print("  " + json.dumps(r, indent=2)[:600])
print("\nPROBE COMPLETE")
