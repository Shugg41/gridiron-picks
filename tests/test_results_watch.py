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
assert rw.winner(event("CAR", "GB", 19, 27)) == "home"
assert rw.winner(event("CAR", "GB", 27, 19)) == "away"
assert rw.winner(event("CAR", "GB", 20, 20)) is None, "a tie has no winner"
assert rw.winner(event("CAR", "GB", 0, 0, completed=False)) is None
print("a finished game has a winner, a tie does not OK")

# ── a result is announced once and only once ──────────────────────────
tmp = tempfile.mkdtemp()
rw.DB = os.path.join(tmp, "picks.db")
rw.SEEN = os.path.join(tmp, "announced.txt")

rw.chaos.PATH = os.path.join(tmp, "chaos.tsv")
# Two flagged underdogs: one in a game he took the other side of, one in
# a game still being played.
led = rw.chaos.add([], 2026, 9, "CAR", "GB", "CAR", 0.33, "form", "x", "d")
led = rw.chaos.add(led, 2026, 9, "MIN", "DET", "MIN", 0.41, "style", "y", "d")
rw.chaos.write(led)

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

assert "CAR was on the chaos list and did not come in." in body, body
led = rw.chaos.read()
car = rw.chaos.for_game(led, 2026, 9, "CAR", "GB")
mn = rw.chaos.for_game(led, 2026, 9, "MIN", "DET")
assert (car["result"], car["taken"]) == ("L", "N"), car
assert (mn["result"], mn["taken"]) == ("", "Y"), mn
print("the ledger is settled when the game ends, not before OK")

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

# ── ESPN and Splash spelling the same team differently ────────────────
# This is the bug that sent week 9 out as 16-13. ESPN says LAR, JAX and
# WSH; Splash says LA, JAC and WAS. Grading by abbreviation marked all
# three wins as losses.
tmp2 = tempfile.mkdtemp()
rw.chaos.PATH = os.path.join(tmp2, "chaos.tsv")
rw.DB = os.path.join(tmp2, "picks.db")
rw.SEEN = os.path.join(tmp2, "announced.txt")
SENT.clear()

conn = store.connect(rw.DB)
store.save_games(conn, 2026, 9, [
    splash.Game(away="Chargers", home="Rams", away_code="LAC",
                home_code="LA", day="Sun", kickoff="Sun 4:05pm",
                kickoff_iso="2026-11-01T21:05Z"),
    splash.Game(away="Colts", home="Jaguars", away_code="IND",
                home_code="JAC", day="Sun", kickoff="Sun 1:00pm",
                kickoff_iso="2026-11-01T18:00Z"),
    splash.Game(away="Eagles", home="Commanders", away_code="PHI",
                home_code="WAS", day="Sun", kickoff="Sun 1:00pm",
                kickoff_iso="2026-11-01T18:00Z")])
store.save_entry(conn, 2026, 9, [
    {"away_code": "LAC", "home_code": "LA", "team": "LA"},
    {"away_code": "IND", "home_code": "JAC", "team": "JAC"},
    {"away_code": "PHI", "home_code": "WAS", "team": "WAS"}])
conn.commit()

def side(abbr, location, name, score):
    return {"abbr": abbr, "location": location, "name": name,
            "full_name": f"{location} {name}", "score": score}


def real(away, home):
    return {"league": "NFL", "completed": True,
            "event_id": away["abbr"] + home["abbr"],
            "away": away, "home": home}


espn.clear_cache()
rw.espn.scoreboard = lambda league, day=None, ttl=900: (
    [real(side("LAC", "Los Angeles", "Chargers", 9),
          side("LAR", "Los Angeles", "Rams", 24)),
     real(side("IND", "Indianapolis", "Colts", 7),
          side("JAX", "Jacksonville", "Jaguars", 42)),
     real(side("PHI", "Philadelphia", "Eagles", 10),
          side("WSH", "Washington", "Commanders", 27))]
    if league == "NFL" else [])
rw.main()
titles = sorted(t for t, _ in SENT)
assert titles == ["Correct: JAC", "Correct: LA", "Correct: WAS"], titles
assert all("3-0" in b for _, b in SENT), SENT
print("a win is a win even when ESPN spells the team differently OK")

print("\nALL RESULTS-WATCH TESTS PASS")
