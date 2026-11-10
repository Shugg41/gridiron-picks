#!/usr/bin/env python3
"""Research the coming weekend and write it down.

    python scripts/research.py

Reads every game with a line — the board's games if this week's board
is loaded, otherwise the whole slate — and writes

    data/research_week<N>.md     the page a person reads
    data/research_week<N>.json   the same thing for a program

What it looks at and why is in gridiron/research.py. This file only
fetches. It has to run where ESPN can be reached, which is GitHub
Actions (data-probe.yml, scope=research); the workflow commits what it
writes.

A game that fails to load is skipped and named on stderr rather than
stopping the run: ESPN drops the odd request, and thirty-three games
researched is worth more than none.
"""
import datetime
import json
import os
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from gridiron import espn, lookahead, research, splash, store   # noqa: E402

SEASON = 2026
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DB = os.path.join(ROOT, "football_picks.db")
ET = ZoneInfo("America/New_York")
UTC = datetime.timezone.utc


def kickoff_of(event):
    return datetime.datetime.fromisoformat(event["kickoff"]).replace(tzinfo=UTC)


def board_for(conn, events):
    """This weekend's board, if it has been loaded: (week, {event_id: game}).

    The newest board in the database is this weekend's only if its games
    are among this weekend's events. Before Splash posts, the newest
    board is last week's, nothing links, and the whole slate is used.
    """
    week = conn.execute("SELECT MAX(week) FROM game WHERE season=?",
                        (SEASON,)).fetchone()[0]
    if not week:
        return 1, {}
    rows = store.week_games(conn, SEASON, week)
    games = [splash.Game(away_code=r["away_code"], home_code=r["home_code"],
                         away=r["away"] or "", home=r["home"] or "")
             for r in rows]
    linked = {ev["event_id"]: g for g, ev in espn.link(games, events) if ev}
    if len(linked) >= max(3, len(games) // 2):
        return week, linked
    return week + 1, {}


def side_of(team, league, kickoff, upcoming, injuries):
    """Everything known about one team going into this game."""
    sched = research.parse_schedule(
        espn.team_schedule(team["id"], league, SEASON), team["id"])
    fm = research.form(sched, kickoff)
    boxes = []
    for eid in reversed(fm["last_ids"]):
        try:
            boxes.append(research.passers(espn.summary(eid, league),
                                          team["id"]))
        except Exception:
            boxes.append([])
    leader = research.season_passer(upcoming, team["id"])
    names = [leader["name"] if leader else None,
             boxes[0][0]["name"] if boxes and boxes[0] else None]
    giveaways = None
    try:
        stats = espn.team_stats(team["id"], league, SEASON)
        played = fm["wins"] + fm["losses"]
        total = stats.get("miscellaneous.totalGiveaways")
        if played and total is not None:
            giveaways = total / played
    except Exception:
        pass
    return {"espn": team["abbr"], "abbr": team["abbr"], "form": fm,
            "qb": research.quarterback(leader, boxes),
            "qb_inj": research.qb_report(injuries.get(str(team["id"])), names),
            "giveaways": giveaways}


def study(event, injuries, game=None):
    """One game, or None when there is no line to define an underdog."""
    league = event["league"]
    mkt_home = lookahead.market_home(event)
    if mkt_home is None:
        return None
    fpi_home = lookahead.fpi_home(event)
    total, moved, toward = lookahead.line_detail(event)
    kickoff = kickoff_of(event)
    upcoming = espn.summary(event["event_id"], league)
    home = side_of(event["home"], league, kickoff, upcoming, injuries)
    away = side_of(event["away"], league, kickoff, upcoming, injuries)
    if game:                       # the board's spelling, where it exists
        home["abbr"], away["abbr"] = game.home_code, game.away_code
    home_dog = mkt_home < 0.5
    dog, fav = (home, away) if home_dog else (away, home)
    price = mkt_home if home_dog else 1 - mkt_home
    fpi = None if fpi_home is None else (fpi_home if home_dog
                                         else 1 - fpi_home)
    ctx = {"league": league, "total": total, "moved": moved,
           "toward": toward, "market": price, "fpi": fpi,
           "dog": dog, "fav": fav, "fav_home": not home_dog}
    for_, against = research.reasons(ctx)
    toward_abbr = {home["espn"]: home["abbr"],
                   away["espn"]: away["abbr"]}.get(toward, toward)
    return {"league": league, "away": away["abbr"], "home": home["abbr"],
            "kickoff": event["kickoff"],
            "when": kickoff.astimezone(ET).strftime("%a %-I:%M%p").replace(
                "AM", "am").replace("PM", "pm"),
            "dog": dog, "fav": fav, "price": price, "fpi": fpi,
            "total": total, "moved": moved, "toward_abbr": toward_abbr,
            "for": for_, "against": against}


def plain(row):
    """A row the JSON file can hold: no datetimes, no nested schedule."""
    def side(s):
        fm = s["form"]
        return {"abbr": s["abbr"], "record": f"{fm['wins']}-{fm['losses']}",
                "streak": fm["streak"], "rest": fm["rest"], "qb": s["qb"],
                "qb_inj": s["qb_inj"]}
    return {"league": row["league"], "away": row["away"], "home": row["home"],
            "kickoff": row["kickoff"], "when": row["when"],
            "dog": side(row["dog"]), "fav": side(row["fav"]),
            "price": row["price"], "fpi": row["fpi"], "total": row["total"],
            "moved": row["moved"], "toward": row["toward_abbr"],
            "for": [list(r) for r in row["for"]],
            "against": [list(r) for r in row["against"]]}


def main():
    conn = store.connect(DB)
    events = lookahead.collect(lookahead.weekend(), everything=True)
    week, board = board_for(conn, events)
    if board:
        events = [e for e in events if e["event_id"] in board]
        source = f"the {len(board)} games on the week {week} board"
    else:
        source = "the whole slate; this week's board is not loaded yet"
    print(f"# week {week}: {len(events)} events, {source}", file=sys.stderr)
    try:
        injuries = research.nfl_injuries(espn.league_injuries("NFL"))
    except Exception as exc:
        print(f"# no NFL injury list: {type(exc).__name__}", file=sys.stderr)
        injuries = {}

    rows = []
    for ev in events:
        label = f"{ev['away']['abbr']}@{ev['home']['abbr']}"
        try:
            row = study(ev, injuries if ev["league"] == "NFL" else {},
                        board.get(ev["event_id"]))
        except Exception as exc:
            print(f"# skipped {label}: {type(exc).__name__}: {exc}",
                  file=sys.stderr)
            continue
        if row:
            rows.append(row)
    if not rows:
        sys.exit("nothing could be researched")

    made = datetime.datetime.now(UTC).astimezone(ET).strftime(
        "%a %b %-d, %-I:%M%p ET")
    page = research.render(week, rows, made, source)
    base = os.path.join(ROOT, "data", f"research_week{week}")
    with open(base + ".md", "w") as f:
        f.write(page)
    with open(base + ".json", "w") as f:
        json.dump({"week": week, "made": made, "source": source,
                   "games": [plain(r) for r in rows]}, f, indent=1)
    print(page.split("## Every game")[0])
    print(f"# wrote {base}.md with {len(rows)} games", file=sys.stderr)


if __name__ == "__main__":
    main()
