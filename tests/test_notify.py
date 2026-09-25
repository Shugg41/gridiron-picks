"""The push notifications, which are the only thing watching when nobody is.

These live in the repo rather than a scratchpad because they guard a
deadline: a game that locks unpicked cannot be fixed afterwards.

    python tests/test_notify.py
"""
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import notify                                          # noqa: E402

SENT = []
notify.send = lambda title, message, tags="football": SENT.append((title, message))


def db():
    """A slate/picks/tiebreaker database shaped like the app's."""
    conn = sqlite3.connect(":memory:")
    conn.execute("""CREATE TABLE slate (season INTEGER, week INTEGER, event_id TEXT,
        matchup TEXT, added_at TEXT, league TEXT, board_pos INTEGER, kickoff TEXT,
        PRIMARY KEY (season, week, event_id))""")
    conn.execute("""CREATE TABLE picks (season INTEGER, week INTEGER, event_id TEXT,
        matchup TEXT, pick_abbr TEXT, pick_name TEXT, opp_name TEXT, result TEXT,
        entered_in_splash INTEGER DEFAULT 0, PRIMARY KEY (season, week, event_id))""")
    conn.execute("""CREATE TABLE tiebreaker (season INTEGER, week INTEGER, value INTEGER,
        PRIMARY KEY (season, week))""")
    return conn


def add_game(conn, eid, matchup, kickoff, picked=False, entered=False, result=None):
    conn.execute("INSERT INTO slate (season, week, event_id, matchup, kickoff) "
                 "VALUES (2026,4,?,?,?)", (eid, matchup, kickoff))
    if picked:
        conn.execute("INSERT INTO picks (season, week, event_id, matchup, pick_abbr, "
                     "result, entered_in_splash) VALUES (2026,4,?,?,'X',?,?)",
                     (eid, matchup, result, 1 if entered else 0))


# A concrete week: Thursday night, the Saturday bulk, and a Sunday game.
THU = "2026-09-24T00:15Z"      # Wed 8:15 PM ET
SAT_EARLY = "2026-09-26T16:00Z"   # Sat 12:00 PM ET — kicks AT the deadline
SAT_LATE = "2026-09-26T23:30Z"    # Sat 7:30 PM ET
SUN = "2026-09-27T17:00Z"         # Sun 1:00 PM ET

# ── lock_time: the rule the whole thing hangs on ─────────────────────────
lock, noon = notify.lock_time(THU)
assert lock < noon, "a Wednesday/Thursday game must lock at kickoff, not at noon"
assert lock.isoformat() == "2026-09-24T00:15:00+00:00", lock
lock, noon = notify.lock_time(SAT_LATE)
assert lock == noon, "a Saturday night game locks at the noon deadline"
lock, noon = notify.lock_time(SUN)
assert lock == noon, "a Sunday game belongs to the Saturday behind it"
assert noon.isoformat() == "2026-09-26T16:00:00+00:00", noon
lock, noon = notify.lock_time("2026-09-28T23:15Z")    # Monday night
assert lock == noon and noon.isoformat() == "2026-09-26T16:00:00+00:00", noon
assert notify.lock_time(None) == (None, None)
assert notify.lock_time("not a date") == (None, None)
print("lock_time OK")

# ── locksoon: the Thursday hole ──────────────────────────────────────────
# 3 hours before the Thursday kickoff, with no pick made
now = datetime(2026, 9, 23, 21, 15, tzinfo=timezone.utc)
conn = db()
add_game(conn, "thu", "DET @ BUF", THU)
add_game(conn, "sat", "BAMA @ WIS", SAT_LATE)
SENT.clear()
notify.locksoon(conn, now=now)
assert SENT, "an unpicked Thursday game 3h from locking must warn"
title, msg = SENT[-1]
assert "DET @ BUF" in msg and "no pick" in msg, msg
assert "BAMA @ WIS" not in msg, "Saturday games are the noon reminder's job"
assert "~3h" in title, title
print("locksoon warns on the early game OK")

# picked but never entered in Splash is just as lost
conn = db()
add_game(conn, "thu", "DET @ BUF", THU, picked=True, entered=False)
SENT.clear()
notify.locksoon(conn, now=now)
assert SENT and "not entered in Splash" in SENT[-1][1], SENT
print("locksoon warns on unentered OK")

# done properly -> silent
conn = db()
add_game(conn, "thu", "DET @ BUF", THU, picked=True, entered=True)
SENT.clear()
notify.locksoon(conn, now=now)
assert not SENT, SENT

# outside the window -> silent, so the 3-hourly schedule fires once per game
conn = db()
add_game(conn, "thu", "DET @ BUF", THU)
for hours_out in (1, 8, 30):
    SENT.clear()
    notify.locksoon(conn, now=notify.lock_time(THU)[0] - timedelta(hours=hours_out))
    assert not SENT, f"{hours_out}h out should be silent, got {SENT}"
SENT.clear()
notify.locksoon(conn, now=notify.lock_time(THU)[0] - timedelta(hours=4))
assert SENT, "4h out is inside the window and must warn"
print("locksoon fires exactly once per game OK")

# a slate with no kickoffs recorded must not crash
conn = db()
conn.execute("INSERT INTO slate (season, week, event_id, matchup) VALUES (2026,4,'x','A @ B')")
SENT.clear()
notify.locksoon(conn, now=now)
assert not SENT
print("locksoon survives a kickoff-less row OK")

# ── remind: the noon deadline, including the tiebreaker ──────────────────
conn = db()
add_game(conn, "a", "A @ B", SAT_LATE, picked=True, entered=True)
add_game(conn, "b", "C @ D", SAT_LATE, picked=True, entered=True)
conn.execute("INSERT INTO tiebreaker VALUES (2026,4,48)")
SENT.clear()
notify.remind(conn)
assert not SENT, "everything done — should be silent"

conn.execute("DELETE FROM tiebreaker")
SENT.clear()
notify.remind(conn)
assert SENT and "no tiebreaker saved" in SENT[-1][1], SENT
print("remind nags about a missing tiebreaker OK")

conn = db()
add_game(conn, "a", "A @ B", SAT_LATE)
add_game(conn, "b", "C @ D", SAT_LATE, picked=True, entered=False)
SENT.clear()
notify.remind(conn)
msg = SENT[-1][1]
assert "1 game(s) still unpicked" in msg and "1 pick(s) not entered" in msg, msg
assert "no tiebreaker" in msg, msg
print("remind reports all three gaps OK")

# ── recap: grades only what the app already graded ───────────────────────
conn = db()
for eid, res in (("a", "W"), ("b", "W"), ("c", "L"), ("d", None)):
    add_game(conn, eid, f"{eid} @ x", SAT_LATE, picked=True, entered=True, result=res)
SENT.clear()
notify.recap(conn)
assert SENT and "2-1" in SENT[-1][1] and "1 game(s) left" in SENT[-1][1], SENT
conn.execute("UPDATE picks SET result='W' WHERE event_id='d'")
SENT.clear()
notify.recap(conn)
assert "3-1 final" in SENT[-1][1], SENT
print("recap OK")

# nothing graded yet -> silent
conn = db()
add_game(conn, "a", "A @ B", SAT_LATE, picked=True)
SENT.clear()
notify.recap(conn)
assert not SENT
print("recap stays quiet before kickoff OK")

print("\nALL NOTIFY TESTS PASS")
