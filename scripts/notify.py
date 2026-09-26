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


def latest_week(conn, table):
    row = conn.execute(
        f"SELECT season, week FROM {table} ORDER BY season DESC, week DESC LIMIT 1"
    ).fetchone()
    return (row[0], row[1]) if row else (None, None)


def remind(conn):
    season, week = latest_week(conn, "slate")
    if not season:
        print("No slate recorded — nothing to remind about.")
        return
    slate_ids = {r[0] for r in conn.execute(
        "SELECT event_id FROM slate WHERE season=? AND week=?", (season, week))}
    picks = {r[0]: r[1] for r in conn.execute(
        "SELECT event_id, entered_in_splash FROM picks WHERE season=? AND week=?",
        (season, week))}
    unpicked = len(slate_ids - set(picks))
    unentered = sum(1 for eid in slate_ids if eid in picks and not picks[eid])
    # The tiebreaker is its own prize-deciding field and is easy to forget —
    # the app pre-fills a suggestion but it still has to be saved.
    no_tb = conn.execute(
        "SELECT COUNT(*) FROM tiebreaker WHERE season=? AND week=?",
        (season, week)).fetchone()[0] == 0
    if not unpicked and not unentered and not no_tb:
        print(f"Week {week}: all {len(slate_ids)} picks made and entered. Silent.")
        return
    bits = []
    if unpicked:
        bits.append(f"{unpicked} game(s) still unpicked")
    if unentered:
        bits.append(f"{unentered} pick(s) not entered in Splash")
    if no_tb:
        bits.append("no tiebreaker saved")
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
    """Nag about games that lock BEFORE the Saturday noon deadline.

    A Thursday night game locks at kickoff, and the Saturday morning
    reminder is far too late for it — that game is simply gone. Only early
    kickoffs are considered here; the noon deadline is `remind`'s job, and
    handling them separately keeps the two from doubling up."""
    now = now or datetime.now(timezone.utc)
    season, week = latest_week(conn, "slate")
    if not season:
        print("No slate recorded — nothing to watch.")
        return
    picks = {r[0]: r[1] for r in conn.execute(
        "SELECT event_id, entered_in_splash FROM picks WHERE season=? AND week=?",
        (season, week))}
    due, soonest = [], None
    for eid, matchup, kickoff in conn.execute(
            "SELECT event_id, matchup, kickoff FROM slate WHERE season=? AND week=?",
            (season, week)):
        lock, noon = lock_time(kickoff)
        if not lock or lock >= noon:
            continue                       # locks at the normal deadline
        if not EARLY_WARN_MIN <= lock - now <= EARLY_WARN_MAX:
            continue
        if eid not in picks:
            due.append(f"{matchup} — no pick")
        elif not picks[eid]:
            due.append(f"{matchup} — not entered in Splash")
        else:
            continue
        soonest = lock if soonest is None else min(soonest, lock)
    if not due:
        print("No early game needs attention right now. Silent.")
        return
    hrs = max(1, round((soonest - now).total_seconds() / 3600))
    send(f"Early game locks in ~{hrs}h",
         f"Week {week}: " + "; ".join(due), tags="alarm_clock,football")


def recap(conn):
    """Report the week's record from results the APP already graded.

    ESPN returns 403 to GitHub's runners, so this script cannot fetch
    scores itself. The Streamlit app grades finished games on every load
    (and keep-awake loads it every 2 hours), so the database is the
    source of truth here.
    """
    season, week = latest_week(conn, "picks")
    if not season:
        print("No picks recorded — nothing to recap.")
        return
    rows = conn.execute(
        "SELECT result FROM picks WHERE season=? AND week=?", (season, week)).fetchall()
    results = [r[0] for r in rows]
    w = results.count("W")
    l = results.count("L")
    p = results.count("P")
    done = w + l + p
    if not done:
        print("Nothing graded yet — staying quiet.")
        return
    left = len(results) - done
    msg = f"Week {week}: {w}-{l}" + (f"-{p}" if p else "")
    msg += f" so far, {left} game(s) left." if left else " final."
    send("Pick results", msg)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode not in ("remind", "locksoon", "recap"):
        sys.exit("usage: notify.py remind|locksoon|recap")
    if not os.path.exists(DB_PATH):
        print("No picks DB in repo yet — nothing to do.")
        return
    conn = sqlite3.connect(DB_PATH)
    {"remind": remind, "locksoon": locksoon, "recap": recap}[mode](conn)


if __name__ == "__main__":
    main()
