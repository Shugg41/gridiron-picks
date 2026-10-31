"""Announcing a finished pick, with ESPN and ntfy both faked.

The thing this protects is narrow and was broken for a whole season:
a result has to be announced exactly once, and a tie has to be a loss.

    python tests/test_results_watch.py
"""
import importlib.util
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
from gridiron import espn, splash, store                      # noqa: E402

spec = importlib.util.spec_from_file_location(
    "results_watch", os.path.join(HERE, "..", "scripts", "results_watch.py"))
rw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rw)


def event(away, home, a_score, h_score, completed=True):
    return {"league": "NFL", "event_id": f"{away}{home}", "completed": completed,
            "home": {"abbr": home, "name": home, "full_name": home,
                     "location": home, "score": h_score},
            "away": {"abbr": away, "name": away, "full_name": away,
                     "location": away, "score": a_score}}


# ── who won ───────────────────────────────────────────────────────────
assert rw.winner(event("CAR", "GB", 19, 27)) == "GB"
assert rw.winner(event("CAR", "GB", 27, 19)) == "CAR"
assert rw.winner(event("CAR", "GB", 20, 20)) is None, "a tie has no winner"
assert rw.winner(event("CAR", "GB", 0, 0, completed=False)) is None
print("a finished game has a winner, a tie does not OK")

# ── a result is announced once and only once ──────────────────────────
tmp = tempfile.mkdtemp()
rw.DB = os.path.join(tmp, "picks.db")
rw.SEEN = os.path.join(tmp, "announced.txt")

conn = store.connect(rw.DB)
store.save_games(conn, 2026, 9, [
    splash.Game(away="Panthers", home="Packers", away_code="CAR",
                home_code="GB", day="Thu", kickoff="Thu 8:15pm",
                kickoff_iso="2026-10-30T00:15Z"),
    splash.Game(away="Vikings", home="Lions", away_code="MIN",
                home_code="DET", day="Sun", kickoff="Sun 1:00pm",
                kickoff_iso="2026-11-01T18:00Z")])
store.save_entry(conn, 2026, 9, [
    {"away_code": "CAR", "home_code": "GB", "team": "GB"},
    {"away_code": "MIN", "home_code": "DET", "team": "MIN"}])
conn.commit()

SENT = []
rw.notify.send = lambda title, message, tags="football": SENT.append(
    (title, message))
# Green Bay done, Minnesota still playing.
espn.clear_cache()
rw.espn.scoreboard = lambda league, day=None, ttl=900: (
    [event("CAR", "GB", 19, 27), event("MIN", "DET", 10, 7, completed=False)]
    if league == "NFL" else [])

rw.main()
assert len(SENT) == 1, SENT
title, body = SENT[0]
assert title == "Correct: GB", title
assert "CAR 19, GB 27" in body, body
assert "You had GB" in body, body
assert "1-0" in body and "1 to play" in body, body
print("a finished pick is announced with its score and the record OK")

rw.main()
assert len(SENT) == 1, "announced twice — the marker did not hold"
print("running again announces nothing OK")

# ── Minnesota finishes, and loses ─────────────────────────────────────
rw.espn.scoreboard = lambda league, day=None, ttl=900: (
    [event("CAR", "GB", 19, 27), event("MIN", "DET", 10, 24)]
    if league == "NFL" else [])
rw.main()
assert len(SENT) == 2, SENT
title, body = SENT[1]
assert title == "Wrong: MIN", title
assert "1-1" in body and "final" in body, body
print("a losing pick says so, and the week closes out OK")

# ── a tie is a loss for everybody ─────────────────────────────────────
open(rw.SEEN, "w").close()
SENT.clear()
rw.espn.scoreboard = lambda league, day=None, ttl=900: (
    [event("CAR", "GB", 20, 20), event("MIN", "DET", 10, 24)]
    if league == "NFL" else [])
rw.main()
titles = {t for t, _ in SENT}
assert "Wrong: GB" in titles, titles
assert any("loss for both" in b for _, b in SENT), SENT
print("a tie is announced as a loss for both sides OK")

print("\nALL RESULTS-WATCH TESTS PASS")
