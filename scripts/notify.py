#!/usr/bin/env python3
"""Push notifications for Gridiron Picks via ntfy.sh.

Runs in GitHub Actions with the repo checked out (the picks DB lives in the
repo thanks to the app's GitHub sync). Uses only the standard library so the
workflow needs no pip install.

    python scripts/notify.py remind   # Sat AM: nag if picks are missing/unentered
    python scripts/notify.py recap    # Sat night / Sun AM: this week's record

Env: NTFY_TOPIC (required to send; exits quietly if unset).
"""
import json
import os
import sqlite3
import sys
import urllib.parse
import urllib.request

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "football_picks.db")
BASE = "https://site.api.espn.com/apis/site/v2/sports/football"


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


def fetch_scoreboard(league="college-football", year=None, week=None):
    url = f"{BASE}/{league}/scoreboard?limit=400"
    if league == "college-football":
        url += "&groups=80"
        if year and week:
            url += f"&dates={year}&seasontype=2&week={week}"
    # NFL uses its own week numbers, so always take its current week — the
    # recap crons run while the pool week is still NFL's current week.
    with urllib.request.urlopen(url, timeout=20) as r:
        return json.load(r)


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
    season, week = latest_week(conn, "picks")
    if not season:
        print("No picks recorded — nothing to recap.")
        return
    picks = conn.execute(
        "SELECT event_id, pick_abbr FROM picks WHERE season=? AND week=?",
        (season, week)).fetchall()
    if not picks:
        return
    events = []
    for league in ("college-football", "nfl"):
        try:
            data = fetch_scoreboard(league, season, week)
            events += data.get("events") or []
        except Exception as e:
            print(f"ESPN {league} fetch failed: {e}")

    finals = {}
    for ev in events:
        if not (ev.get("status") or {}).get("type", {}).get("completed"):
            continue
        comp = (ev.get("competitions") or [{}])[0]
        for c in comp.get("competitors") or []:
            abbr = (c.get("team") or {}).get("abbreviation")
            if abbr:
                finals.setdefault(str(ev.get("id")), {})[abbr] = bool(c.get("winner"))

    w = l = p = 0
    for eid, pick_abbr in picks:
        res = finals.get(str(eid))
        if not res or pick_abbr not in res:
            continue
        if res[pick_abbr]:
            w += 1
        elif any(res.values()):
            l += 1
        else:
            p += 1  # nobody flagged winner on a completed game → tie
    done = w + l + p
    if not done:
        print("No completed pool games yet. Silent.")
        return
    left = len(picks) - done
    msg = f"Week {week}: {w}–{l}" + (f"–{p}" if p else "")
    if left:
        msg += f" so far, {left} game(s) left."
    else:
        msg += " final."
    send("🏈 Pick results", msg)


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
