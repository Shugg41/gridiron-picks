#!/usr/bin/env python3
"""Dump the SHAPE of ESPN's football endpoints so parsers are written
against reality instead of guesswork. Runs in CI (open internet); the
dev sandbox has no egress to ESPN. Standard library only.

    python scripts/probe_espn.py
"""
import json
import sys
import urllib.error
import urllib.request

SITE = "https://site.api.espn.com/apis/site/v2/sports/football"
CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues"
WEB = "https://site.web.api.espn.com/apis"

LEAGUES = [("college-football", "CFB", "&groups=80"), ("nfl", "NFL", "")]


def get(url, label):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        print(f"  [{label}] HTTP {e.code} — {url[:110]}")
    except Exception as e:
        print(f"  [{label}] {type(e).__name__}: {e} — {url[:110]}")
    return None


def shape(obj, indent=4, depth=0, max_depth=3, max_keys=40):
    """Print keys/types with one sample value, recursing a few levels."""
    pad = " " * indent
    if isinstance(obj, dict):
        for i, (k, v) in enumerate(obj.items()):
            if i >= max_keys:
                print(f"{pad}… {len(obj) - max_keys} more keys")
                break
            if isinstance(v, (dict, list)):
                n = len(v)
                print(f"{pad}{k}: {type(v).__name__}({n})")
                if depth < max_depth and n:
                    shape(v[0] if isinstance(v, list) else v,
                          indent + 2, depth + 1, max_depth, max_keys)
            else:
                s = str(v)
                print(f"{pad}{k} = {s[:70]}")
    elif isinstance(obj, list) and obj:
        print(f"{pad}[0] of {len(obj)}:")
        shape(obj[0], indent + 2, depth + 1, max_depth, max_keys)


def banner(t):
    print("\n" + "=" * 72)
    print(t)
    print("=" * 72)


for path, tag, grp in LEAGUES:
    banner(f"{tag}: scoreboard — find an upcoming game")
    sb = get(f"{SITE}/{path}/scoreboard?limit=400{grp}", f"{tag} scoreboard")
    if not sb:
        continue
    season = (sb.get("season") or {}).get("year")
    week = (sb.get("week") or {}).get("number")
    print(f"  season={season} week={week} events={len(sb.get('events') or [])}")

    ev = None
    for e in sb.get("events") or []:
        if not (e.get("status") or {}).get("type", {}).get("completed"):
            ev = e
            break
    ev = ev or (sb.get("events") or [None])[0]
    if not ev:
        continue
    eid = ev["id"]
    comp = (ev.get("competitions") or [{}])[0]
    teams = {c.get("homeAway"): (c.get("team") or {}) for c in comp.get("competitors") or []}
    print(f"  probing event {eid}: {ev.get('shortName')}")
    print(f"  team ids: home={teams.get('home', {}).get('id')} away={teams.get('away', {}).get('id')}")

    banner(f"{tag}: scoreboard odds block (line movement?)")
    shape(comp.get("odds") or [], max_depth=3)

    banner(f"{tag}: /summary?event={eid} — TOP-LEVEL KEYS")
    s = get(f"{SITE}/{path}/summary?event={eid}", f"{tag} summary")
    if s:
        for k, v in s.items():
            n = f"({len(v)})" if isinstance(v, (dict, list)) else ""
            print(f"  {k}: {type(v).__name__}{n}")
        for key in ("predictor", "againstTheSpread", "headToHeadGames",
                    "lastFiveGames", "injuries", "boxscore", "teamStats",
                    "winprobability", "odds", "standings", "leaders"):
            if key in s:
                banner(f"{tag}: summary.{key}")
                shape(s[key], max_depth=3)

    hid = teams.get("home", {}).get("id")
    if hid:
        for yr in (season, (season or 2026) - 1):
            banner(f"{tag}: core team statistics — team {hid}, season {yr}")
            st = get(f"{CORE}/{path}/seasons/{yr}/types/2/teams/{hid}/statistics",
                     f"{tag} stats {yr}")
            if st:
                cats = ((st.get("splits") or {}).get("categories") or [])
                print(f"  categories: {[c.get('name') for c in cats]}")
                for c in cats:
                    names = [(x.get('name'), x.get('displayValue'))
                             for x in (c.get('stats') or [])]
                    print(f"\n  -- {c.get('name')} ({len(names)} stats)")
                    for n, dv in names:
                        print(f"     {n} = {dv}")

        banner(f"{tag}: FPI / power index candidates — team {hid}")
        for url in (
            f"{CORE}/{path}/seasons/{season}/types/2/teams/{hid}/powerindex",
            f"{CORE}/{path}/seasons/{season}/teams/{hid}/powerindex",
            f"{WEB}/fitt/v3/sports/football/{path}/powerindex?season={season}",
            f"{WEB}/site/v2/sports/football/{path}/teams/{hid}",
        ):
            r = get(url, "fpi")
            if r:
                print(f"  OK {url[:110]}")
                shape(r, max_depth=2, max_keys=25)
                break
print("\nPROBE COMPLETE")
