#!/usr/bin/env python3
"""Compact: exact stat names available per category, plus FPI shape.

Confirmed so far: sports.core.api.espn.com serves CI fine (site.api does
not), team statistics live at .../teams/{id}/statistics, and FPI lives at
.../seasons/{yr}/powerindex/{id} on a net-points scale.
"""
import json
import urllib.error
import urllib.request

CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues"
UA = {"User-Agent": "Mozilla/5.0"}
WANT = ("yardsperplay", "yardspergame", "thirddown", "fourthdown", "redzone",
        "turnover", "pointspergame", "sack", "possession", "firstdown",
        "completionpct", "rushingyardspergame", "passingyardspergame",
        "totalpointspergame", "yardsperrushattempt", "yardsperpassattempt",
        "totalyards", "penalt", "interception", "fumble", "gamesplayed")


def get(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        print(f"    HTTP {e.code}  {url[:110]}")
    except Exception as e:
        print(f"    {type(e).__name__}  {url[:110]}")
    return None


for league, tid in (("college-football", "99"), ("nfl", "12")):
    print("\n" + "=" * 70)
    print(f"{league} — team {tid}")
    print("=" * 70)
    for yr in (2026, 2025):
        st = get(f"{CORE}/{league}/seasons/{yr}/types/2/teams/{tid}/statistics")
        if not st:
            continue
        cats = (st.get("splits") or {}).get("categories") or []
        print(f"\n  season {yr}: categories = {[c.get('name') for c in cats]}")
        for c in cats:
            hits = []
            for s in c.get("stats") or []:
                nm = (s.get("name") or "")
                if any(w in nm.lower() for w in WANT):
                    hits.append(f"{nm}={s.get('displayValue')}"
                                + (f"(pg {s.get('perGameValue')})"
                                   if s.get("perGameValue") is not None else ""))
            if hits:
                print(f"    [{c.get('name')}] " + " | ".join(hits))

    fpi = get(f"{CORE}/{league}/seasons/2026/powerindex/{tid}")
    if fpi:
        preds = {p.get("name"): p.get("value") for p in fpi.get("predictives") or []}
        print(f"\n  FPI predictives: {json.dumps(preds)}")
        print(f"  other keys: {[k for k in fpi if k != 'predictives']}")
        for k in ("stats", "categories"):
            if k in fpi:
                print(f"  {k}: {json.dumps(fpi[k])[:400]}")
print("\nPROBE COMPLETE")
