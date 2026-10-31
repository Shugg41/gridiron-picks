#!/usr/bin/env python3
"""Announce each pick as it finalises, from CI, with nothing else running.

The app already does this and it has never once worked. Two reasons,
and both are structural rather than bad luck:

  * NTFY_TOPIC is a GitHub Actions secret. Streamlit's secrets are a
    separate store and the app has never had it, so every per-game
    push since the feature was written has returned early. Six games
    graded in week 9 and not one notification left the building.
  * Even with the secret, the app only pushes when something loads it,
    and keep-awake manages every four to six hours. Results would
    arrive in batches, hours late, which is not what a result
    notification is for.

So this runs in Actions, where the topic already lives, every fifteen
minutes through the weekend. It reads the board and the entry out of
the database but never writes to it — grading stays the app's job and
two writers on a binary file is how a week gets lost.

What it does write is data/announced.txt, one game per line, which is
how it knows what it has already said. A text file rather than a row
in the database precisely so that a collision with the app is a
three-line merge instead of a corrupted week.

Scores come from ESPN's scoreboard. The comment in espn.scoreboard
says that endpoint refuses GitHub's runners; the coverage probe got
forty-seven college games out of it from a runner, so that is no
longer true and this depends on it.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from gridiron import espn, splash, store                      # noqa: E402
import notify                                                 # noqa: E402

SEASON = 2026
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DB = os.path.join(ROOT, "football_picks.db")
SEEN = os.path.join(ROOT, "data", "announced.txt")


def already_said():
    try:
        with open(SEEN) as f:
            return {l.strip() for l in f if l.strip()}
    except FileNotFoundError:
        return set()


def remember(keys):
    os.makedirs(os.path.dirname(SEEN), exist_ok=True)
    with open(SEEN, "a") as f:
        for k in sorted(keys):
            f.write(k + "\n")


def winner(event):
    """The side that won, or None for a tie or an unfinished game.

    A tie is None rather than a team because Splash scores one as a
    loss for everybody — week 6's 27-27 came back marked incorrect on
    both sides of the room.
    """
    if not event.get("completed"):
        return None
    h, a = event.get("home") or {}, event.get("away") or {}
    hs, as_ = h.get("score"), a.get("score")
    if hs is None or as_ is None or hs == as_:
        return None
    return h["abbr"] if hs > as_ else a["abbr"]


def main():
    conn = store.connect(DB)
    week = conn.execute("SELECT MAX(week) FROM game WHERE season=?",
                        (SEASON,)).fetchone()[0]
    if not week:
        print("no board loaded")
        return
    rows = store.week_games(conn, SEASON, week)
    picks = {(a, h): t for a, h, t in conn.execute(
        "SELECT away_code, home_code, team FROM entry "
        "WHERE season=? AND week=? AND team IS NOT NULL", (SEASON, week))}
    if not picks:
        print(f"week {week}: no entry recorded, nothing to grade")
        return

    games = [splash.Game(away_code=r["away_code"], home_code=r["home_code"],
                         away=r["away"] or "", home=r["home"] or "",
                         kickoff_iso=r["kickoff"])
             for r in rows]
    days = espn.window([r["kickoff"] for r in rows])
    pool, failed = [], []
    for league in ("CFB", "NFL"):
        for day in days:
            try:
                pool += espn.scoreboard(league, day)
            except Exception as exc:
                failed.append(f"{league} {day}: {type(exc).__name__}")
    if failed:
        print("# could not reach ESPN for:", "; ".join(failed), file=sys.stderr)
    if not pool:
        print("no scores available")
        return

    seen = already_said()
    done, fresh, left = [], [], 0
    for g, ev in espn.link(games, pool):
        key = (g.away_code, g.home_code)
        pick = picks.get(key)
        if not pick:
            continue
        if not ev or not ev.get("completed"):
            left += 1
            continue
        win = winner(ev)
        result = "W" if win == pick else "L"
        done.append((key, pick, ev, win, result))
        marker = f"{SEASON}:{week}:{g.away_code}:{g.home_code}"
        if marker not in seen:
            fresh.append((marker, key, pick, ev, win, result))

    w = sum(1 for *_, r in done if r == "W")
    l = len(done) - w
    print(f"week {week}: {w}-{l} with {left} to play, "
          f"{len(fresh)} new to announce")

    said = []
    for marker, (a, h), pick, ev, win, result in fresh:
        score = (f"{a} {ev['away'].get('score')}, "
                 f"{h} {ev['home'].get('score')}")
        body = (f"{score} — a tie, which Splash scores as a loss for both."
                if win is None else f"{score}. You had {pick}.")
        body += f" Week {week}: {w}-{l}"
        body += f", {left} to play." if left else " — final."
        notify.send("Correct: " + pick if result == "W" else "Wrong: " + pick,
                    body,
                    tags="white_check_mark" if result == "W" else "x")
        said.append(marker)
        print(f"  announced {a}@{h}: {result}")
    if said:
        remember(said)


if __name__ == "__main__":
    main()
