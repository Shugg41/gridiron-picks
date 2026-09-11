#!/usr/bin/env python3
"""Push notifications for Gridiron Picks via ntfy.sh.

Runs in GitHub Actions with the repo checked out (the picks DB lives in the
repo thanks to the app's GitHub sync). Uses only the standard library so the
workflow needs no pip install.

    python scripts/notify.py remind   # Sat AM: nag if picks are missing/unentered
    python scripts/notify.py recap    # weekend: the week's record

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

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "football_picks.db")


def send(title, message, tags="football"):
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        print("NTFY_TOPIC not set — nothing sent.")
        return
    req = urllib.request.Request(
        f"https://ntfy.sh/{urllib.parse.quote(topic)}",
        data=message.encode(),
        headers={"Title": title, "Tags": tags})
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
    if not unpicked and not unentered:
        print(f"Week {week}: all {len(slate_ids)} picks made and entered. Silent.")
        return
    bits = []
    if unpicked:
        bits.append(f"{unpicked} game(s) still unpicked")
    if unentered:
        bits.append(f"{unentered} pick(s) not entered in Splash")
    send("⏰ Picks lock at noon!", f"Week {week}: " + " and ".join(bits) + ".",
         tags="alarm_clock,football")


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
    if mode not in ("remind", "recap"):
        sys.exit("usage: notify.py remind|recap")
    if not os.path.exists(DB_PATH):
        print("No picks DB in repo yet — nothing to do.")
        return
    conn = sqlite3.connect(DB_PATH)
    (remind if mode == "remind" else recap)(conn)


if __name__ == "__main__":
    main()
