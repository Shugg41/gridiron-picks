#!/usr/bin/env python3
"""Where does ESPN actually keep FPI and team statistics?

power_index() and team_stats() were written against remembered URLs and
never once called, so nothing has ever checked them. Both fail. The
last probe reported "HTTPError" without a status code, which does not
distinguish a wrong path from a refused caller — so this one prints the
code and tries the plausible shapes side by side rather than guessing
one at a time.

Discovery, not verification: the point is to come back with a URL that
answers, or the knowledge that none of them do from here.

Run via .github/workflows/data-probe.yml.
"""
import json
import sys
import urllib.error
import urllib.request

CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues"
SITE = "https://site.api.espn.com/apis"
SEASON = 2026


def try_url(label, url):
    req = urllib.request.Request(url, headers={"User-Agent": "gridiron-probe"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = json.load(r)
    except urllib.error.HTTPError as exc:
        print(f"  {label:<34} HTTP {exc.code}")
        return None
    except Exception as exc:
        print(f"  {label:<34} {type(exc).__name__}")
        return None
    keys = sorted(body)[:8] if isinstance(body, dict) else f"list({len(body)})"
    print(f"  {label:<34} OK   keys={keys}")
    return body


def team_id(league):
    """Any real team id for this league, taken from a live event."""
    try:
        wk = 4 if league == "nfl" else 5
        listing = json.load(urllib.request.urlopen(urllib.request.Request(
            f"{CORE}/{league}/seasons/{SEASON}/types/2/weeks/{wk}/events?limit=1",
            headers={"User-Agent": "gridiron-probe"}), timeout=20))
        event = json.load(urllib.request.urlopen(urllib.request.Request(
            listing["items"][0]["$ref"],
            headers={"User-Agent": "gridiron-probe"}), timeout=20))
        comp = (event.get("competitions") or [])[0]
        ref = (comp["competitors"][0].get("team") or {})["$ref"]
        team = json.load(urllib.request.urlopen(urllib.request.Request(
            ref, headers={"User-Agent": "gridiron-probe"}), timeout=20))
        return str(team.get("id")), team.get("abbreviation")
    except Exception as exc:
        print(f"could not find a team id: {type(exc).__name__}: {exc}")
        return None, None


def main():
    for league in ("nfl", "college-football"):
        tid, abbr = team_id(league)
        print(f"\n{'=' * 74}\n{league} — team {abbr} (id {tid})\n{'=' * 74}")
        if not tid:
            continue
        # what the code currently asks for, first, so its failure is on
        # the record next to whatever does work
        try_url("types/2/teams/{id}/powerindex",
                f"{CORE}/{league}/seasons/{SEASON}/types/2/teams/{tid}/powerindex")
        try_url("teams/{id}/powerindex",
                f"{CORE}/{league}/seasons/{SEASON}/teams/{tid}/powerindex")
        try_url("powerindex/{id}",
                f"{CORE}/{league}/seasons/{SEASON}/powerindex/{tid}")
        try_url("types/2/powerindex/{id}",
                f"{CORE}/{league}/seasons/{SEASON}/types/2/powerindex/{tid}")
        try_url("types/2/teams/{id}/statistics",
                f"{CORE}/{league}/seasons/{SEASON}/types/2/teams/{tid}/statistics")
        try_url("types/2/teams/{id}/record",
                f"{CORE}/{league}/seasons/{SEASON}/types/2/teams/{tid}/record")
        try_url("teams/{id} (plain)",
                f"{CORE}/{league}/seasons/{SEASON}/teams/{tid}")
        # the site API is refused to CI outright; included so the
        # distinction between "wrong path" and "wrong caller" is visible
        try_url("site fitt powerindex",
                f"{SITE}/fitt/v3/sports/football/{league}/powerindex?limit=5")


if __name__ == "__main__":
    main()
