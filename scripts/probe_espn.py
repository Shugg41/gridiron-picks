#!/usr/bin/env python3
"""Hunt for two data sources the app doesn't have yet:

  1. PUBLIC PICK PERCENTAGES — what everyone else picked. In a weekly-prize
     pool this is the real edge: an underdog is only worth taking if the
     field is piled on the favorite. Splash's on-board percentages turn out
     to be win probabilities, not pick distribution, so we need another
     source. ESPN's Pick'em (gambit) API is the main candidate.
  2. OPENING LINES — open vs current shows where money moved. If ESPN won't
     serve it, the fallback is sampling the line ourselves every few hours.

Established constraints: site.api.espn.com 403s GitHub runners;
sports.core.api.espn.com does not. So try core first, and try the others
through a real browser, which has worked before where urllib was refused.
"""
import json
import urllib.error
import urllib.request

CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"}


def get(url, label):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        print(f"    HTTP {e.code}  [{label}]")
    except Exception as e:
        print(f"    {type(e).__name__}  [{label}]")
    return None


def banner(t):
    print("\n" + "=" * 72 + f"\n{t}\n" + "=" * 72)


# ── 1. find a live event id via the core API (site API is blocked here) ──
banner("find an upcoming event id from the core API")
EVENT = {}
for league in ("nfl", "college-football"):
    wk = get(f"{CORE}/{league}/seasons/2026/types/2/weeks/4/events?limit=5", f"{league} week events")
    if wk and wk.get("items"):
        ref = wk["items"][0]["$ref"].replace("http://", "https://")
        ev = get(ref, "event detail")
        if ev:
            EVENT[league] = ev.get("id")
            print(f"  {league}: event {ev.get('id')} — {ev.get('shortName', ev.get('name'))}")

# ── 2. opening lines on the core odds endpoint ──
banner("OPENING LINES — core odds endpoint")
for league, eid in EVENT.items():
    comp = get(f"{CORE}/{league}/events/{eid}/competitions/{eid}/odds", f"{league} odds")
    if not comp:
        continue
    for item in (comp.get("items") or [])[:2]:
        prov = (item.get("provider") or {}).get("name", "?")
        keys = sorted(item.keys())
        print(f"\n  [{league}] provider={prov}")
        print(f"    keys: {keys}")
        for k in ("open", "current", "close", "spread", "overUnder", "details"):
            if k in item:
                print(f"    {k} = {json.dumps(item[k])[:260]}")

# ── 3. public pick percentages — ESPN Pick'em (gambit) and friends ──
banner("PUBLIC PICK % — candidate endpoints")
CANDIDATES = [
    ("gambit nfl propositions",
     "https://gambit-api.fantasy.espn.com/apis/v1/propositions?challengeId=nfl-pigskin-pickem-2026&platform=chui&view=chui_default"),
    ("gambit cfb propositions",
     "https://gambit-api.fantasy.espn.com/apis/v1/propositions?challengeId=college-football-pickem-2026&platform=chui&view=chui_default"),
    ("gambit challenge list",
     "https://gambit-api.fantasy.espn.com/apis/v1/challenges?platform=chui&view=chui_default"),
    ("core nfl predictor",
     f"{CORE}/nfl/events/{EVENT.get('nfl')}/competitions/{EVENT.get('nfl')}/predictor"
     if EVENT.get("nfl") else None),
    ("core nfl probabilities",
     f"{CORE}/nfl/events/{EVENT.get('nfl')}/competitions/{EVENT.get('nfl')}/probabilities?limit=1"
     if EVENT.get("nfl") else None),
]
for label, url in CANDIDATES:
    if not url:
        continue
    print(f"\n  -- {label}")
    d = get(url, label)
    if d:
        print(f"     OK top-level keys: {list(d)[:14]}")
        blob = json.dumps(d)
        for word in ("percent", "pickPercent", "picksCount", "consensus", "votes"):
            if word.lower() in blob.lower():
                i = blob.lower().index(word.lower())
                print(f"     >>> contains '{word}': ...{blob[max(0,i-120):i+200]}...")
                break
        else:
            print(f"     no pick-percentage fields; sample: {blob[:300]}")
print("\nPROBE COMPLETE")
