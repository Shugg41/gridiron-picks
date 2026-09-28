"""The push notifications, which are the only thing watching when nobody is.

They guard a deadline: a game that locks unpicked cannot be fixed
afterwards. They run against the new tables, where the picks come back
from Splash rather than being kept here — so the Saturday nag is about
pasting the entry, which is the only thing this side can actually know.

    python tests/test_notify.py
"""
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from gridiron import store                                     # noqa: E402
import notify                                                  # noqa: E402

SENT = []
ALL_TITLES = []          # never cleared, so the sweep at the end sees them all
_real_send = notify.send


def _capture(title, message, tags="football"):
    SENT.append((title, message))
    ALL_TITLES.append(title)


notify.send = _capture


def sent_for_real(title, message, tags="football"):
    """Run the genuine send() against a fake ntfy, so a title that cannot
    go into an HTTP header fails here instead of in a workflow at 9 AM.
    Stubbing send() itself is how a bug in send() survived a whole season."""
    captured = {}

    class FakeResp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        captured["headers"] = dict(req.header_items())
        captured["body"] = req.data
        return FakeResp()

    real = urllib.request.urlopen
    urllib.request.urlopen = fake_urlopen
    os.environ["NTFY_TOPIC"] = "test-topic"
    try:
        _real_send(title, message, tags)
    finally:
        urllib.request.urlopen = real
        os.environ.pop("NTFY_TOPIC", None)
    return captured


def db():
    return store.connect(":memory:")


def test_opens_a_database_that_predates_the_new_tables():
    """The bug this shipped with, reproduced.

    The committed database is whatever the app last pushed. Right after a
    schema change that is a file with only the OLD tables in it, and
    notify.py opened it with raw sqlite3 and queried `game` — so the lock
    watcher died every three hours with "no such table: game".

    The earlier tests all passed because the test helper built the schema
    itself. That is the gap: they constructed the world instead of using
    the entry point production uses. This one goes through open_db().
    """
    import sqlite3
    import tempfile

    path = tempfile.mktemp(suffix=".db")
    legacy = sqlite3.connect(path)
    legacy.executescript("""
        CREATE TABLE slate (season INTEGER, week INTEGER, event_id TEXT,
                            matchup TEXT);
        CREATE TABLE picks (season INTEGER, week INTEGER, event_id TEXT,
                            matchup TEXT, pick_abbr TEXT, result TEXT);
        INSERT INTO slate VALUES (2026,4,'1','ATL @ GB'),(2026,4,'2','MISS @ FLA');
        INSERT INTO picks VALUES (2026,4,'2','MISS @ FLA','MISS','L');
    """)
    legacy.commit()
    legacy.close()

    real_db = notify.DB_PATH
    notify.DB_PATH = path
    try:
        conn = notify.open_db()                   # must not raise
        SENT.clear()
        notify.locksoon(conn)                     # the call that was dying
        notify.remind(conn)
        notify.recap(conn)
        # and the legacy rows came across rather than being ignored
        assert conn.execute("SELECT COUNT(*) FROM game").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM entry").fetchone()[0] == 1
    finally:
        notify.DB_PATH = real_db
        os.unlink(path)
    print("opens a database that predates the new tables OK")


test_opens_a_database_that_predates_the_new_tables()


def add(conn, away, home, kickoff=None, picked=None, result=None,
        entered=False, week=4):
    conn.execute("INSERT INTO game (season, week, away_code, home_code, kickoff) "
                 "VALUES (2026,?,?,?,?)", (week, away, home, kickoff))
    if entered or picked is not None or result is not None:
        conn.execute("INSERT INTO entry (season, week, away_code, home_code, "
                     "team, result) VALUES (2026,?,?,?,?,?)",
                     (week, away, home, picked, result))


THU = "2026-09-24T00:15Z"        # Wed 8:15 PM ET — locks at kickoff
SAT_LATE = "2026-09-26T23:30Z"   # Sat 7:30 PM ET — locks at noon
SUN = "2026-09-27T17:00Z"

# ── lock_time: the rule everything hangs on ─────────────────────────────
lock, noon = notify.lock_time(THU)
assert lock < noon and lock.isoformat() == "2026-09-24T00:15:00+00:00", lock
assert notify.lock_time(SAT_LATE)[0] == notify.lock_time(SAT_LATE)[1]
assert notify.lock_time(SUN)[1].isoformat() == "2026-09-26T16:00:00+00:00"
assert notify.lock_time("2026-09-28T23:15Z")[1].isoformat() == \
    "2026-09-26T16:00:00+00:00", "a Monday game belongs to the Saturday behind it"
assert notify.lock_time(None) == (None, None)
assert notify.lock_time("nonsense") == (None, None)
print("lock_time OK")

# ── the Thursday hole, which cost a real game in week four ─────────────
now = datetime(2026, 9, 23, 21, 15, tzinfo=timezone.utc)   # 3h before kickoff
conn = db()
add(conn, "ATL", "GB", THU)
add(conn, "MISS", "FLA", SAT_LATE)
SENT.clear()
notify.locksoon(conn, now=now)
assert SENT and "ATL @ GB" in SENT[-1][1], SENT
assert "MISS" not in SENT[-1][1], "Saturday games are the noon reminder's job"
assert "~3h" in SENT[-1][0], SENT[-1][0]
print("locksoon warns on the early game OK")

conn = db()
add(conn, "ATL", "GB", THU, picked="GB")
SENT.clear()
notify.locksoon(conn, now=now)
assert not SENT, "a picked game needs no warning"

# fires once per game: the window is as wide as the three-hourly schedule
conn = db()
add(conn, "ATL", "GB", THU)
for out in (1, 8, 30):
    SENT.clear()
    notify.locksoon(conn, now=notify.lock_time(THU)[0] - timedelta(hours=out))
    assert not SENT, f"{out}h out should be silent"
SENT.clear()
notify.locksoon(conn, now=notify.lock_time(THU)[0] - timedelta(hours=4))
assert SENT
print("locksoon fires exactly once per game OK")

conn = db()
conn.execute("INSERT INTO game (season, week, away_code, home_code) "
             "VALUES (2026,4,'A','B')")
SENT.clear()
notify.locksoon(conn, now=now)
assert not SENT
print("a game with no kickoff recorded does not crash it OK")

# ── the Saturday nag, now about getting the entry back ─────────────────
conn = db()
for i in range(3):
    add(conn, f"A{i}", f"H{i}", SAT_LATE)
SENT.clear()
notify.remind(conn)
assert SENT and "no entry pasted" in SENT[-1][1], SENT
assert "stop this reminder" in SENT[-1][1], "a nag must say how to silence it"
print("remind asks for the entry when none is pasted OK")

conn = db()
add(conn, "A", "B", SAT_LATE, picked="B")
add(conn, "C", "D", SAT_LATE, entered=True)         # pasted, but no pick made
conn.execute("INSERT INTO tiebreak (season, week, guess) VALUES (2026,4,42)")
SENT.clear()
notify.remind(conn)
assert SENT and "1 game(s) with no pick" in SENT[-1][1], SENT
assert "tiebreaker" not in SENT[-1][1], "the tiebreaker is saved"

conn = db()
add(conn, "A", "B", SAT_LATE, picked="B")
SENT.clear()
notify.remind(conn)
assert SENT and "no tiebreaker" in SENT[-1][1], SENT

conn = db()
add(conn, "A", "B", SAT_LATE, picked="B")
conn.execute("INSERT INTO tiebreak (season, week, guess) VALUES (2026,4,42)")
SENT.clear()
notify.remind(conn)
assert not SENT, f"everything done, should be silent: {SENT}"
print("remind reports real gaps and shuts up otherwise OK")

# ── the recap, from Splash's own grading ───────────────────────────────
conn = db()
for code, res in (("A", "W"), ("B", "W"), ("C", "L"), ("D", None)):
    add(conn, code, code + "h", SAT_LATE, picked=code, result=res)
SENT.clear()
notify.recap(conn)
assert SENT and "2-1" in SENT[-1][1] and "1 game(s) left" in SENT[-1][1], SENT
conn.execute("UPDATE entry SET result='W' WHERE away_code='D'")
SENT.clear()
notify.recap(conn)
assert "3-1 final" in SENT[-1][1], SENT

conn = db()
add(conn, "A", "B", SAT_LATE, picked="B")
SENT.clear()
notify.recap(conn)
assert not SENT
print("recap OK")

# ── the wire: an emoji title used to raise before anything was sent ────
cap = sent_for_real("⏰ Picks lock at noon!", "Week 4: 24–7 so far",
                    tags="alarm_clock,football")
assert cap["headers"]["Title"] == "Picks lock at noon!", cap["headers"]
cap["headers"]["Title"].encode("latin-1")            # must not raise
assert cap["headers"]["Tags"] == "alarm_clock,football"
assert "24–7".encode() in cap["body"], "the body is UTF-8 and keeps its dash"
assert notify.header_safe("🔔") == "Gridiron Picks"
print("emoji titles can no longer break a send OK")

assert ALL_TITLES, "no notification fired — the sweep below would prove nothing"
for title in ALL_TITLES:
    title.encode("latin-1")
print(f"all {len(ALL_TITLES)} titles raised in this run are latin-1 clean OK")

print("\nALL NOTIFY TESTS PASS")
