#!/usr/bin/env python3
"""Push notifications for Gridiron Picks via ntfy.sh.

Runs in GitHub Actions with the repo checked out (the picks DB lives in the
repo thanks to the app's GitHub sync). Uses only the standard library so the
workflow needs no pip install.

    python scripts/notify.py remind    # Sat AM: nag if picks are missing/unentered
    python scripts/notify.py locksoon  # games that lock BEFORE Saturday noon
    python scripts/notify.py recap     # weekend: the week's record

Both read only the database. ESPN returns 403 to GitHub's runners, so
scores are graded by the Streamlit app (which ESPN does serve) and land
here through the app's GitHub sync.

Env: NTFY_TOPIC (required to send; exits quietly if unset).
"""
import os
import sqlite3
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "football_picks.db")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from gridiron import store                                    # noqa: E402


def open_db():
    """Open through the store rather than raw sqlite3.

    The tables are created by the store, and the committed database is
    whatever the app last pushed — which, right after a schema change, is
    a file predating the new tables entirely. Opening it raw meant
    querying a table that did not exist, and the lock watcher died every
    three hours on exactly that. Going through the store creates the
    schema and carries the legacy rows over, so the notifier stands on
    its own rather than waiting for the app to push first.
    """
    conn = store.connect(DB_PATH)
    store.migrate_legacy(conn)
    return conn


def header_safe(text):
    """HTTP headers are latin-1 only. An emoji in the title raises
    UnicodeEncodeError inside http.client before anything is sent — which
    is exactly how the Saturday reminder managed to fail silently every
    week while the ASCII-titled recap went through fine. The emoji belongs
    in `tags` anyway: ntfy renders those as emoji beside the title."""
    try:
        text.encode("latin-1")
        return text
    except UnicodeEncodeError:
        return "".join(c for c in text if ord(c) < 256).strip() or "Gridiron Picks"


def send(title, message, tags="football"):
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        print("NTFY_TOPIC not set — nothing sent.")
        return
    req = urllib.request.Request(
        f"https://ntfy.sh/{urllib.parse.quote(topic)}",
        data=message.encode(),                 # the body is UTF-8, emoji fine
        headers={"Title": header_safe(title), "Tags": tags})
    with urllib.request.urlopen(req, timeout=15) as r:
        print(f"ntfy: {r.status}")


def latest_week(conn, table="game"):
    row = conn.execute(
        f"SELECT season, week FROM {table} ORDER BY season DESC, week DESC LIMIT 1"
    ).fetchone()
    return (row[0], row[1]) if row else (None, None)


def has_table(conn, name):
    return bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,)).fetchone())


def remind(conn):
    """Saturday morning, before the noon deadline.

    Picks live in Splash now, not here, so the app cannot know whether
    they were entered — only whether the entry has been pasted back. That
    is the thing to nag about, and the message says so, because a nag you
    cannot silence is one you learn to ignore.
    """
    season, week = latest_week(conn)
    if not season:
        print("No games recorded — nothing to remind about.")
        return
    total = conn.execute("SELECT COUNT(*) FROM game WHERE season=? AND week=?",
                         (season, week)).fetchone()[0]
    picked = conn.execute(
        "SELECT COUNT(*) FROM entry WHERE season=? AND week=? AND team IS NOT NULL",
        (season, week)).fetchone()[0]
    missing = conn.execute(
        "SELECT COUNT(*) FROM entry WHERE season=? AND week=? AND team IS NULL",
        (season, week)).fetchone()[0]
    no_tb = conn.execute(
        "SELECT COUNT(*) FROM tiebreak WHERE season=? AND week=? "
        "AND guess IS NOT NULL", (season, week)).fetchone()[0] == 0

    if not picked:
        send("Picks lock at noon!",
             f"Week {week}: {total} games on the board and no entry pasted "
             f"yet. If they are already in Splash, paste your entry to stop "
             f"this reminder.", tags="alarm_clock,football")
        return
    bits = []
    if missing:
        bits.append(f"{missing} game(s) with no pick")
    if no_tb:
        bits.append("no tiebreaker")
    if not bits:
        print(f"Week {week}: {picked} picks in, nothing to say. Silent.")
        return
    send("Picks lock at noon!", f"Week {week}: " + " and ".join(bits) + ".",
         tags="alarm_clock,football")


def lock_time(kickoff_iso):
    """When a pick stops being changeable: noon ET on the slate's Saturday,
    or kickoff if the game starts before that. Mirrors the app's own rule —
    the week runs Tue-Mon, so Sunday and Monday games belong to the Saturday
    behind them, not the one ahead."""
    try:
        kick = datetime.fromisoformat(kickoff_iso.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None, None
    kick_et = kick.astimezone(ET)
    w = kick_et.weekday()                      # Mon=0 … Sun=6
    days_to_sat = -2 if w == 0 else 5 - w
    sat = (kick_et + timedelta(days=days_to_sat)).date()
    noon = datetime(sat.year, sat.month, sat.day, 12, 0, tzinfo=ET).astimezone(timezone.utc)
    return min(kick, noon), noon


# Alert once per game, without keeping any state: the watcher runs every
# three hours, so a three-hour-wide window catches each game exactly once.
EARLY_WARN_MIN = timedelta(hours=2)
EARLY_WARN_MAX = timedelta(hours=5)


def locksoon(conn, now=None):
    """Games that lock BEFORE the Saturday noon deadline.

    A Thursday night game locks at kickoff, and the Saturday reminder is
    far too late for it. This cost a real game in week four, which is
    why it exists.
    """
    now = now or datetime.now(timezone.utc)
    season, week = latest_week(conn)
    if not season:
        print("No games recorded — nothing to watch.")
        return
    picked = {(a, h) for a, h in conn.execute(
        "SELECT away_code, home_code FROM entry WHERE season=? AND week=? "
        "AND team IS NOT NULL", (season, week))}
    due, soonest = [], None
    for away, home, kickoff in conn.execute(
            "SELECT away_code, home_code, kickoff FROM game "
            "WHERE season=? AND week=?", (season, week)):
        lock, noon = lock_time(kickoff)
        if not lock or lock >= noon:
            continue                       # locks at the normal deadline
        if not EARLY_WARN_MIN <= lock - now <= EARLY_WARN_MAX:
            continue
        if (away, home) in picked:
            continue
        due.append(f"{away} @ {home}")
        soonest = lock if soonest is None else min(soonest, lock)
    if not due:
        print("No early game needs attention right now. Silent.")
        return
    hrs = max(1, round((soonest - now).total_seconds() / 3600))
    send(f"Early game locks in ~{hrs}h",
         f"Week {week}: no pick yet on " + "; ".join(due),
         tags="alarm_clock,football")


def recap(conn):
    """The week's record, from the results Splash graded.

    ESPN returns 403 to GitHub's runners, so nothing here can fetch a
    score. It does not need to: pasting the entry brings Splash's own
    grading with it.
    """
    season, week = latest_week(conn)
    if not season:
        print("No games recorded — nothing to recap.")
        return
    rows = [r[0] for r in conn.execute(
        "SELECT result FROM entry WHERE season=? AND week=?", (season, week))]
    w, l = rows.count("W"), rows.count("L")
    if not (w + l):
        print("Nothing graded yet — staying quiet.")
        return
    left = len([r for r in rows if r is None])
    msg = f"Week {week}: {w}-{l}"
    msg += f" so far, {left} game(s) left." if left else " final."
    send("Pick results", msg)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode not in ("remind", "locksoon", "recap"):
        sys.exit("usage: notify.py remind|locksoon|recap")
    if not os.path.exists(DB_PATH):
        print("No picks DB in repo yet — nothing to do.")
        return
    conn = open_db()
    {"remind": remind, "locksoon": locksoon, "recap": recap}[mode](conn)


if __name__ == "__main__":
    main()
