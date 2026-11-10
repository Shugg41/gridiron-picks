#!/usr/bin/env python3
"""What ESPN will actually hand over for game research. Probe, then build.

Every parser in this repo that was written from memory was wrong at
least once, so this prints the real shapes first: a team's schedule,
the injury lists, a finished game's passing box, and what the summary
of a game that has not been played yet carries.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from gridiron import espn                                     # noqa: E402


def show(label, value, limit=1800):
    text = json.dumps(value, default=str)[:limit]
    print(f"\n### {label}\n{text}")


def keys(d):
    return sorted(d.keys()) if isinstance(d, dict) else type(d).__name__


def attempt(label, fn):
    try:
        return fn()
    except Exception as exc:
        print(f"\n### {label}\nFAILED {type(exc).__name__}: {str(exc)[:200]}")
        return None


def main():
    for league, path, done_day, next_day in (
            ("NFL", "nfl", "20261108", "20261115"),
            ("CFB", "college-football", "20261107", "20261114")):
        print(f"\n\n================ {league} ================")
        done = attempt("events done", lambda: espn.events_on(path, done_day))
        nxt = attempt("events next", lambda: espn.events_on(path, next_day))
        if not done or not nxt:
            continue
        ev_done, ev_next = done[0], nxt[0]
        team = ev_next["home"]
        print(f"done: {ev_done['away']['abbr']}@{ev_done['home']['abbr']} "
              f"{ev_done['event_id']}  next: {ev_next['away']['abbr']}@"
              f"{ev_next['home']['abbr']} {ev_next['event_id']}  "
              f"team: {team['abbr']} {team['id']}")

        # 1. schedule
        sched = attempt("schedule", lambda: espn._get(
            f"{espn.SITE}/{path}/teams/{team['id']}/schedule",
            {"season": 2026}))
        if sched:
            show("schedule keys", keys(sched))
            evs = sched.get("events") or []
            print("events:", len(evs))
            if evs:
                e = evs[0]
                show("schedule event keys", keys(e))
                comp = (e.get("competitions") or [{}])[0]
                show("schedule competition", {
                    "date": e.get("date"), "week": e.get("week"),
                    "status": (comp.get("status") or {}).get("type"),
                    "competitors": [{k: c.get(k) for k in
                                     ("homeAway", "winner", "score",
                                      "curatedRank", "record")}
                                    | {"abbr": (c.get("team") or {}).get(
                                        "abbreviation")}
                                    for c in comp.get("competitors") or []]})
            show("schedule team", {k: (sched.get("team") or {}).get(k)
                                   for k in ("recordSummary", "standingSummary",
                                             "abbreviation")})
            show("byeWeek/requested", {k: sched.get(k) for k in
                                       ("byeWeek", "requestedSeason")})

        # 2. injuries
        inj = attempt("league injuries", lambda: espn._get(
            f"{espn.SITE}/{path}/injuries"))
        if inj:
            show("league injuries keys", keys(inj))
            groups = inj.get("injuries") or []
            print("teams with injuries:", len(groups))
            if groups:
                g = groups[0]
                show("injury group keys", keys(g))
                items = g.get("injuries") or []
                if items:
                    i = items[0]
                    show("injury item keys", keys(i))
                    show("injury item", {
                        "status": i.get("status"), "date": i.get("date"),
                        "type": i.get("type"),
                        "details": i.get("details"),
                        "shortComment": i.get("shortComment"),
                        "athlete": {k: (i.get("athlete") or {}).get(k)
                                    for k in ("displayName", "position")}})
                qbs = []
                for g in groups:
                    for i in g.get("injuries") or []:
                        pos = ((i.get("athlete") or {}).get("position")
                               or {}).get("abbreviation")
                        if pos == "QB":
                            qbs.append((g.get("displayName"),
                                        (i.get("athlete") or {}).get(
                                            "displayName"),
                                        i.get("status"), i.get("date")))
                show("QBs on the list", qbs, 2500)
        core_inj = attempt("core team injuries", lambda: espn._get(
            f"{espn.CORE}/{path}/teams/{team['id']}/injuries"))
        if core_inj:
            show("core injuries", {"count": core_inj.get("count"),
                                   "first": (core_inj.get("items") or [None])[0]})

        # 3. summary of a game not yet played
        s = attempt("summary next", lambda: espn.summary(
            ev_next["event_id"], league))
        if s:
            show("summary(next) keys", keys(s))
            for k in ("injuries", "lastFiveGames", "leaders",
                      "againstTheSpread", "predictor", "pickcenter"):
                v = s.get(k)
                if isinstance(v, list) and v:
                    show(f"summary(next).{k}[0]", v[0], 2200)
                else:
                    show(f"summary(next).{k}", v, 800)

        # 4. summary of a finished game: who threw the passes
        s = attempt("summary done", lambda: espn.summary(
            ev_done["event_id"], league))
        if s:
            box = s.get("boxscore") or {}
            show("boxscore keys", keys(box))
            for side in box.get("players") or []:
                for stat in side.get("statistics") or []:
                    if stat.get("name") == "passing":
                        show(f"passing {(side.get('team') or {}).get('abbreviation')}",
                             {"labels": stat.get("labels"),
                              "athletes": [
                                  {"name": (a.get("athlete") or {}).get(
                                      "displayName"),
                                   "id": (a.get("athlete") or {}).get("id"),
                                   "stats": a.get("stats")}
                                  for a in stat.get("athletes") or []]})

        # 5. season leaders for the team
        lead = attempt("core leaders", lambda: espn._get(
            f"{espn.CORE}/{path}/seasons/2026/types/2/teams/{team['id']}/leaders"))
        if lead:
            cats = lead.get("categories") or []
            show("leader categories", [c.get("name") for c in cats])
            for c in cats:
                if c.get("name") in ("passingYards", "passingLeader"):
                    show("passing leader", (c.get("leaders") or [None])[0])

        # 6. the stats this repo already parses
        st = attempt("team stats", lambda: espn.team_stats(
            team["id"], league, 2026))
        if st:
            show("stat names (rush/pass/points/turnover)", sorted(
                k for k in st if any(w in k.lower() for w in
                                     ("rushingyardspergame", "yardspergame",
                                      "pointspergame", "turnover",
                                      "giveaway", "takeaway",
                                      "yardsperrush", "totalpoints"))), 2500)
            print("stat count:", len(st))

        # 7. the team itself
        t = attempt("team", lambda: espn._get(
            f"{espn.SITE}/{path}/teams/{team['id']}"))
        if t:
            tt = t.get("team") or {}
            show("team keys", keys(tt))
            show("team record", tt.get("record"), 900)
            show("team nextEvent", [
                {"date": e.get("date"), "name": e.get("shortName")}
                for e in tt.get("nextEvent") or []])


if __name__ == "__main__":
    main()
