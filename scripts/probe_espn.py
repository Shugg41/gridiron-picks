#!/usr/bin/env python3
"""Dump the shape of ESPN's odds payloads, from CI.

This sandbox cannot reach ESPN, and GitHub's runners are refused by
site.api while being served by sports.core.api. So before a parser is
written against an endpoint it gets probed here, and the parser is
written against what actually came back — every parser bug this project
has had came from writing against a remembered shape.

The question this one is asking: does a provider carry an OPENING line
as well as the current one? A line that has moved toward the underdog
since it opened is sharp money disagreeing with the public, which is a
real flip signal — but only if ESPN actually serves it.

Run via .github/workflows/data-probe.yml (workflow_dispatch), read logs.
"""
import json
import sys
import urllib.request

CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "gridiron-probe"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def shape(obj, path="", depth=0, out=None):
    """Keys, types and a sample value — the structure, not the data."""
    out = [] if out is None else out
    if depth > 4:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            here = f"{path}.{k}" if path else k
            if isinstance(v, (dict, list)):
                out.append(f"{here}: {type(v).__name__}({len(v)})")
                shape(v, here, depth + 1, out)
            else:
                out.append(f"{here} = {v!r}"[:160])
    elif isinstance(obj, list) and obj:
        shape(obj[0], f"{path}[0]", depth + 1, out)
    return out


def probe(league="nfl", season=2026, week=5):
    print(f"\n{'=' * 70}\n{league.upper()} week {week}\n{'=' * 70}")

    events_url = (f"{CORE}/{league}/seasons/{season}/types/2/weeks/{week}/"
                  f"events?limit=5")
    try:
        events = get(events_url)
    except Exception as exc:
        print(f"events: FAILED {type(exc).__name__}: {exc}")
        return
    refs = [e["$ref"] for e in events.get("items", [])][:2]
    print(f"events: {events.get('count')} total, probing {len(refs)}")

    for ref in refs:
        try:
            event = get(ref)
        except Exception as exc:
            print(f"  event FAILED {type(exc).__name__}")
            continue
        print(f"\n--- {event.get('name')} ({event.get('date')}) ---")
        comps = event.get("competitions") or []
        if not comps:
            continue
        odds_ref = (comps[0].get("odds") or {}).get("$ref")
        if not odds_ref:
            print("  no odds ref on this competition")
            continue
        try:
            odds = get(odds_ref)
        except Exception as exc:
            print(f"  odds FAILED {type(exc).__name__}")
            continue
        items = odds.get("items") or []
        print(f"  odds providers: {len(items)}")
        if not items:
            continue
        first = items[0]
        print(f"  provider: {(first.get('provider') or {}).get('name')}")
        for key in ("details", "overUnder", "spread", "overOdds", "underOdds"):
            if key in first:
                print(f"    {key} = {first[key]!r}")
        for side in ("homeTeamOdds", "awayTeamOdds"):
            block = first.get(side) or {}
            print(f"    {side}: {sorted(block)}")
            for sub in ("open", "current", "close"):
                if sub in block:
                    print(f"      {sub}: {json.dumps(block[sub])[:220]}")
        for sub in ("open", "current", "close"):
            if sub in first:
                print(f"    {sub}: {json.dumps(first[sub])[:300]}")
        if "--full" in sys.argv:
            print("\n".join("      " + line for line in shape(first)))


if __name__ == "__main__":
    for lg in ("nfl", "college-football"):
        try:
            probe(lg)
        except Exception as exc:
            print(f"{lg}: probe blew up: {type(exc).__name__}: {exc}")
