"""The whole week, driven through the real app with the real pages.

This is the test that would have caught every bug the old app shipped,
because it does what the user does: paste the board, read the card, paste
the entry back, paste the field, and check the app agrees with reality.

    python tests/test_app.py
"""
import os
import re
import shutil
import sys
import tempfile

import sqlite3 as _sq

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from gridiron import espn                                      # noqa: E402

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
MATRIX = open(os.path.join(HERE, "fixtures", "picks_by_week4.txt")).read()
STAND = open(os.path.join(HERE, "fixtures", "standings_week4.txt")).read()
ENTRY = open(os.path.join(HERE, "fixtures", "entry_week4.txt")).read()
BOARD = open(os.path.join(HERE, "fixtures", "board_week5.txt")).read()

# ── a fake ESPN, covering the fixture's games ───────────────────────────
TEAMS = {
    "ATL": ("Atlanta", "Falcons"), "GB": ("Green Bay", "Packers"),
    "ARMY": ("Army", "Black Knights"), "TEM": ("Temple", "Owls"),
    "NAVY": ("Navy", "Midshipmen"), "UAB": ("UAB", "Blazers"),
    "CLEM": ("Clemson", "Tigers"), "CAL": ("California", "Golden Bears"),
    "SDSU": ("San Diego State", "Aztecs"), "TOL": ("Toledo", "Rockets"),
    "TEX": ("Texas", "Longhorns"), "TENN": ("Tennessee", "Volunteers"),
    "UCLA": ("UCLA", "Bruins"), "MD": ("Maryland", "Terrapins"),
    "MISS": ("Ole Miss", "Rebels"), "FLA": ("Florida", "Gators"),
    "SEA": ("Seattle", "Seahawks"), "WSH": ("Washington", "Commanders"),
    "LAC": ("Los Angeles", "Chargers"), "BUF": ("Buffalo", "Bills"),
    "ARI": ("Arizona", "Cardinals"), "SF": ("San Francisco", "49ers"),
    "PHI": ("Philadelphia", "Eagles"), "CHI": ("Chicago", "Bears"),
    # week 5, so the current week has lines like the live app will
    "PIT": ("Pittsburgh", "Steelers"), "CLE": ("Cleveland", "Browns"),
    "DEN": ("Denver", "Broncos"), "NYG": ("New York", "Giants"),
}
# away, home, spread, over/under — three deliberately near coin flips
SLATE = [
    ("ATL", "GB", "GB -3", None), ("ARMY", "TEM", "ARMY -7", None),
    ("NAVY", "UAB", "NAVY -14", None), ("CLEM", "CAL", "CLEM -1", None),
    ("SDSU", "TOL", "TOL -10", None), ("TEX", "TENN", "TEX -4", None),
    ("UCLA", "MD", "UCLA -1", None), ("MISS", "FLA", "FLA -0.5", None),
    ("SEA", "WSH", "SEA -6", None), ("LAC", "BUF", "BUF -5", None),
    ("ARI", "SF", "SF -3", None), ("PHI", "CHI", "PHI -5.5", 44.5),
]
# Week 5 kicks in October, so that week is still open — which is what
# lets the app record its own advice for it without being asked.
# Kickoffs match the real board, because ESPN's timestamp is preferred
# over the one derived from the page and inventing a different one here
# would only be testing the fake.
WEEK5 = [("PIT", "CLE", "PIT -5.5", 41.5, "2026-10-02T00:15Z"),
         ("ARI", "NYG", "ARI -1.5", 42.5, "2026-10-04T17:00Z"),
         ("LAC", "SEA", "SEA -2.5", 43.5, "2026-10-04T20:25Z"),
         ("DEN", "SF", "SF -3", 44.5, "2026-10-04T20:25Z")]


def _team(code):
    loc, name = TEAMS[code]
    return {"id": code, "abbreviation": code, "shortDisplayName": name,
            "displayName": f"{loc} {name}", "location": loc}


def _events():
    out = []
    for i, (a, h, details, ou) in enumerate(SLATE):
        odds = {"details": details}
        if ou:
            odds["overUnder"] = ou
        out.append({
            "id": f"x{i}", "date": f"2026-09-2{6 if i < 9 else 7}T17:00Z",
            "status": {"type": {"completed": False, "shortDetail": ""}},
            "competitions": [{"competitors": [
                dict(homeAway="home", score=None, team=_team(h)),
                dict(homeAway="away", score=None, team=_team(a))],
                "odds": [odds]}]})
    for i, (a, h, details, ou, when) in enumerate(WEEK5):
        out.append({
            "id": f"w5-{i}", "date": when,
            "status": {"type": {"completed": False, "shortDetail": ""}},
            "competitions": [{"competitors": [
                dict(homeAway="home", score=None, team=_team(h)),
                dict(homeAway="away", score=None, team=_team(a))],
                "odds": [{"details": details, "overUnder": ou}]}]})
    return out


class Fake:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload

    def raise_for_status(self):
        pass


# FPI per team, so the second opinion is exercised rather than
# silently absent. NYG is rated far above ARI, where the market has
# ARI favored — so FPI likes the underdog and the card should say so.
FPI = {"NYG": 8.0, "ARI": 0.0}


def fake_get(url, params=None, **kw):
    if "/powerindex/" in url:
        code = url.rstrip("/").split("/")[-1]
        return Fake({"predictives": [{"name": "fpi",
                                      "value": FPI.get(code, 0.0)}]})
    if "scoreboard" in url and "/nfl/" in url:
        return Fake({"events": _events()})
    return Fake({"events": []})


requests.get = fake_get
espn.clear_cache()

WORK = tempfile.mkdtemp(prefix="gp_app_")
shutil.copy(os.path.join(ROOT, "streamlit_app.py"),
            os.path.join(WORK, "app.py"))
shutil.copytree(os.path.join(ROOT, "gridiron"), os.path.join(WORK, "gridiron"))
os.chdir(WORK)

from streamlit.testing.v1 import AppTest                       # noqa: E402


def run():
    at = AppTest.from_file(os.path.join(WORK, "app.py"), default_timeout=90)
    at.run()
    return at


def paste(at, text, week=4):
    at.text_area[0].set_value(text)
    at.number_input[0].set_value(week)
    at.button(key="FormSubmitter:paste-Load it").click().run()
    return at


def boom(at, label):
    if at.exception:
        print(f"EXCEPTION {label}:", [e.value for e in at.exception])
        sys.exit(1)


def games_in_week(week):
    db = _sq.connect(os.path.join(WORK, "football_picks.db"))
    n = db.execute("SELECT COUNT(*) FROM game WHERE season=2026 AND week=?",
                   (week,)).fetchone()[0]
    db.close()
    return n


def cards(at):
    out = []
    for m in at.markdown:
        if "<div class='card" not in m.value:
            continue
        num = re.search(r"num'>(\d+)\.", m.value)
        team = re.search(r"team'>([A-Z0-9]+)<", m.value)
        out.append((int(num.group(1)) if num else None,
                    team.group(1) if team else None, m.value))
    return out


# ── an empty app tells you what to do ───────────────────────────────────
at = run()
boom(at, "on an empty database")
assert any("Paste this week's board" in i.value for i in at.info), \
    [i.value for i in at.info]
assert any("No standings loaded" in m.value for m in at.markdown)
print("empty state OK")

# ── paste the board (the picks matrix defines the week) ─────────────────
at = paste(at, MATRIX)
boom(at, "after the board")
assert any("12 games" in s.value and "you never picked" in s.value
           for s in at.success), [s.value for s in at.success]
print("board loaded:", [s.value for s in at.success][0])

at = run()
boom(at, "after reload")
rows = cards(at)
assert len(rows) == 12, len(rows)
assert [n for n, _t, _h in rows] == list(range(1, 13))

# and they run in kickoff order, which is the order Splash lists the
# board — the app and the page have to be scrollable side by side
_db = _sq.connect(os.path.join(WORK, "football_picks.db"))
kicks = [k for (k,) in _db.execute(
    "SELECT kickoff FROM game WHERE season=2026 AND week=4 "
    "ORDER BY COALESCE(kickoff,'9999'), seq")]
assert kicks == sorted(kicks), "the card list is not in kickoff order"
print(f"{len(rows)} cards rendered, numbered 1-12, in kickoff order OK")

# ── the strategy line, and the flips it implies ─────────────────────────
at = paste(at, STAND)
boom(at, "after the standings")
at = run()
mode = [m.value for m in at.markdown
        if "gp-mode'>" in m.value and "<style>" not in m.value]
assert mode and "Chalk" in mode[0], mode
assert "season is live" in mode[0], mode[0]
print("strategy line:", re.sub("<[^>]+>", "", mode[0]).strip())

# ── a missing pick is impossible to miss ────────────────────────────────
missing = [h for _n, _t, h in cards(at) if "No pick made" in h]
assert len(missing) == 1 and "ATL" in missing[0], missing
errs = [e.value for e in at.error]
assert any("no pick" in e for e in errs), errs
print("the missed game is flagged on the card and in the review OK")

# ── results came across with the entry ──────────────────────────────────
won = [h for _n, _t, h in cards(at) if "card won" in h]
lost = [h for _n, _t, h in cards(at) if "card lost" in h]
# ARMY, CLEM, TOL, TEX won; NAVY, MD, MISS lost; the rest are still live
assert (len(won), len(lost)) == (4, 3), (len(won), len(lost))
print(f"{len(won)} won, {len(lost)} lost carried over from Splash OK")

# the season line, and the game that was never picked kept visible in it
season = [m.value for m in at.markdown if "Season " in m.value]
assert season, "no season record rendered"
assert "4-3" in season[0], season[0]
assert "1 never picked" in season[0] and "4-4" in season[0], season[0]
print("season record shows both the pick record and Splash's OK")

# ── the simulation, now that the field is loaded ───────────────────────
import sqlite3 as _sq2                                         # noqa: E402
_d = _sq2.connect(os.path.join(WORK, "football_picks.db"))
n_rivals = _d.execute("SELECT COUNT(DISTINCT entrant) FROM field_card "
                      "WHERE season=2026 AND week=4").fetchone()[0]
assert n_rivals == 3, f"rival cards not stored: {n_rivals}"   # 4 entries, minus me
sim = " ".join(m.value for m in at.markdown)
assert "correct is the middle of it" in sim, "no score range rendered"
assert "to win outright" in sim, "no odds against the field"
print(f"simulation runs against {n_rivals} stored rival cards OK")

# ── the field, and what being alone cost ────────────────────────────────
review = " ".join(m.value for m in at.markdown)
assert "against the crowd" in review, "the field summary never rendered"
print("field review renders OK")

# ── a fresh week starts from the board, before anything is picked ──────
# The real Week 5 board, through the real app: recognise the page, parse
# it, store it, draw it. It failed at the first of those once, live, an
# hour before a deadline, so the whole path is under test and not just
# the parser.
at2 = run()
at2 = paste(at2, BOARD, week=5)
boom(at2, "after the board")
assert any("36 games loaded" in x.value for x in at2.success), \
    [x.value for x in at2.success] + [w.value for w in at2.warning]

at2 = run()
boom(at2, "on the new week")
weeks = at2.selectbox[0]
assert "Week 5" in weeks.options and "Week 4" in weeks.options, weeks.options
fresh = cards(at2)
# ESPN here is still week 4's slate, so most of these match nothing — and
# every one of them still has to be on the screen, in the right place.
assert len(fresh) == 36, f"the board lost or invented games: {len(fresh)}"
assert [n for n, _t, _h in fresh] == list(range(1, 37))
assert not any("card won" in h or "card lost" in h for _n, _t, h in fresh), \
    "nothing on a fresh board has been graded"

_d5 = _sq.connect(os.path.join(WORK, "football_picks.db"))
k5 = [k for (k,) in _d5.execute(
    "SELECT kickoff FROM game WHERE season=2026 AND week=5 "
    "ORDER BY COALESCE(kickoff,'9999'), seq")]
assert len(k5) == 36 and all(k5), "a game was stored with no kickoff"
assert k5 == sorted(k5) and k5[0].startswith("2026-10-02"), k5[:2]
assert k5[-1].startswith("2026-10-06"), k5[-1]     # Monday night, last
# and that date is what makes the Thursday game lock at kickoff rather
# than at Saturday noon, with no ESPN match anywhere in sight
from gridiron import view                                      # noqa: E402
assert view.lock_time(k5[0]).isoformat().startswith("2026-10-02T00:15"), \
    view.lock_time(k5[0])
assert view.lock_time(k5[-1]).isoformat().startswith("2026-10-03T16:00"), \
    view.lock_time(k5[-1])
print(f"the real Week 5 board: {len(fresh)} cards, dated and in order OK")

# a week with no entry says the late-change watch is off, rather than
# leaving a feature quietly doing nothing
assert any("Late-change alerts are off" in c.value for c in at2.caption), \
    [c.value for c in at2.caption]
print("a week with no entry says why the watch is silent OK")

# ── the advice records itself ──────────────────────────────────────────
# It used to need a button press. Miss it and the week's advice is gone
# for good, and the one thing the user asked to be able to answer — is
# this working — has nothing to answer with.
def proposals(week):
    db = _sq.connect(os.path.join(WORK, "football_picks.db"))
    n = db.execute("SELECT COUNT(*) FROM proposal WHERE season=2026 "
                   "AND week=?", (week,)).fetchone()[0]
    db.close()
    return n


assert proposals(5) > 0, "the week's advice was never recorded"

# ── the second opinion reaches the card ───────────────────────────────
# power_index spent a fortnight 404ing behind tests that only ever fed
# fake payloads to the parser, so the wiring gets checked end to end:
# team id out of the event, FPI fetched, compared with the market, and
# said out loud on the flip it chose.
page = " ".join(m.value for m in at2.markdown)
assert "Flip" in page, "no flips were offered at all"
assert "FPI rates" in page, f"the second opinion never reached the card"
assert "NYG" in page, "FPI should have moved the flip onto the Giants"
print("FPI is fetched, compared and explained on the card OK")

# and it keeps up as lines arrive: a record frozen at the first look
# would cover the handful of games that had odds on a Tuesday
_before = proposals(5)
_p = _sq.connect(os.path.join(WORK, "football_picks.db"))
_p.execute("DELETE FROM proposal WHERE season=2026 AND week=5 "
           "AND rowid IN (SELECT rowid FROM proposal LIMIT 2)")
_p.commit()
_p.close()
assert proposals(5) == _before - 2
run()
assert proposals(5) == _before, \
    "the recorded advice did not grow when more games had lines"
# and week 4 is over and already entered, so no advice is invented for
# it after the fact — that would read as though the app had called it
assert proposals(4) == 0, "advice was recorded for a week already played"
print(f"{proposals(5)} proposals recorded, none back-dated OK")

# ── the card keeps talking after the picks are in ─────────────────────
# Picks go in fast and get revisited, and the revisit is the one where
# a line has moved and there is still time. The flips used to vanish
# the moment an entry existed, which made the second visit useless.
from datetime import datetime, timedelta, timezone                # noqa: E402

# Dated forward from now, not pinned to a date in the fixture. The
# first version of this used the board's real kickoffs, which were in
# the future the day it was written and in the past four days later —
# so the whole section quietly stopped testing anything.
_soon = (datetime.now(timezone.utc) + timedelta(days=3)).strftime(
    "%Y-%m-%dT%H:%MZ")
_e = _sq.connect(os.path.join(WORK, "football_picks.db"))
_e.execute("DELETE FROM entry WHERE season=2026 AND week=5")
_e.executemany(
    "INSERT INTO entry (season, week, away_code, home_code, team) "
    "VALUES (2026, 5, ?, ?, ?)",
    [("ARI", "NYG", "ARI"), ("PIT", "CLE", "PIT")])
_e.executemany(
    "UPDATE game SET kickoff=? WHERE season=2026 AND week=5 "
    "AND away_code=? AND home_code=?",
    [(_soon, "ARI", "NYG"), (_soon, "PIT", "CLE")])
_e.commit()
_e.close()

at8 = run()
boom(at8, "with an entry already in")
page8 = " ".join(m.value for m in at8.markdown)
assert "Flip" in page8, "the flips vanished once the picks were entered"
assert "Still worth a look" in page8, page8[:400]
# it names both sides of the disagreement, and only for games that can
# still be changed
assert "you have " in page8 and "the card says" in page8
caps = " ".join(c.value for c in at8.caption)
assert "not locked" in caps, caps
print("suggestions survive the entry, and say where they differ OK")

# ── ESPN being unreachable must not cost a single game ──────────────────
def dead(url, params=None, **kw):
    raise requests.ConnectionError("no route to host")


requests.get = dead
espn.clear_cache()
import streamlit as _st                                        # noqa: E402
_st.cache_data.clear()                     # Streamlit's cache outlives a run
_st.cache_resource.clear()
at3 = run()
boom(at3, "with ESPN unreachable")
at3.selectbox[0].select(4).run()     # the app opens on the latest week
boom(at3, "with ESPN unreachable, week 4")
blind = cards(at3)
assert len(blind) == 12, f"games vanished when ESPN went away: {len(blind)}"
assert all("No line" in h or "No pick" in h or t for _n, t, h in blind)
assert any("No lines right now" in c.value for c in at3.caption), \
    [c.value for c in at3.caption]
print("ESPN down: all 12 games survive, the card is intact OK")

# ── the week box is a default, not an instruction ──────────────────────
# Pasting an older page without touching the week box would otherwise
# file its games under the current week, silently. Last, because it
# deliberately writes an old page's games into the database.
before5 = games_in_week(5)
at4 = run()
at4 = paste(at4, ENTRY, week=5)          # ENTRY is week 4's page
boom(at4, "after pasting an older page under the wrong week")
msg = [x.value for x in at4.success] + [x.value for x in at4.warning]
assert any("week 4" in m for m in msg), msg
assert games_in_week(5) == before5, "an old page overwrote the current week"
print("a page pasted under the wrong week goes where the page says OK")

# ── a deploy that adds a function must not break the page ──────────────
# Streamlit Cloud re-reads the main script on every rerun but keeps
# imported packages in sys.modules, so the new script can end up
# calling the old module. That took the live app down on an
# AttributeError the first time it happened.
#
# This has to modify the module the app genuinely imports — a copy in
# the temp directory is not on its path and would prove nothing — so
# the file is put back in a finally.
import gridiron.store as _live                                 # noqa: E402

_path = _live.__file__
_original = open(_path).read()
try:
    with open(_path, "w") as fh:
        fh.write(_original + "\n\ndef shipped_after_start():\n    return 42\n")
    assert not hasattr(_live, "shipped_after_start"), \
        "the loaded module already has it, so this proves nothing"

    at5 = run()
    boom(at5, "after a module changed under a running app")
    assert hasattr(_live, "shipped_after_start"), \
        "a rerun did not pick the new code up"
    assert _live.shipped_after_start() == 42

    # And the case that actually took the app down: the container is
    # stale AND has no recorded mtimes, because the script that would
    # have recorded them is the old one. The first version of this fix
    # recorded and reloaded nothing, so it did not fix anything.
    import gridiron                                            # noqa: E402
    delattr(gridiron, "_mtimes")
    with open(_path, "w") as fh:
        fh.write(_original + "\n\ndef shipped_while_stale():\n    return 7\n")
    assert not hasattr(_live, "shipped_while_stale")
    at6 = run()
    boom(at6, "on the first rerun after a deploy")
    assert hasattr(_live, "shipped_while_stale"), \
        "the first rerun after a deploy did not reload a stale module"
    assert _live.shipped_while_stale() == 7
finally:
    with open(_path, "w") as fh:
        fh.write(_original)
    import importlib                                           # noqa: E402
    importlib.reload(_live)
assert open(_path).read() == _original, "the source file was not restored"
# reload() re-executes a module into its existing namespace, so it adds
# and updates but never removes. A deploy that deletes or renames a
# function would leave the old one reachable until the container
# restarts — fine for adding, worth knowing before relying on it.
assert hasattr(_live, "shipped_after_start"), \
    "reload has started deleting attributes; the comment above is stale"
print("a module changed under a running app is reloaded OK")

# ── a deploy that replaces the database file ───────────────────────────
# A deploy checks out a fresh football_picks.db, and the cached
# connection goes on reading the file it opened — now unlinked. The
# live app served a week-4, 31-13 season out of a database holding
# five weeks and 71-33, and no commit could ever reach it.
_dbp = os.path.join(WORK, "football_picks.db")
_replacement = os.path.join(WORK, "replacement.db")
from gridiron import splash as _splash, store as _store          # noqa: E402

_fresh = _store.connect(_replacement)
_store.save_games(_fresh, 2026, 9,
                  [_splash.Game(away_code="AAA", home_code="BBB")])
_fresh.commit()
_fresh.close()
os.replace(_replacement, _dbp)          # a new inode, as a checkout gives

at7 = run()
boom(at7, "after the database file was replaced")
# The replacement holds one week, so there is no week selector — the
# header is where it shows. Reading the old file would still say Week 5.
# match the div, not the stylesheet — the CSS block contains
# ".gp-head" too, and picking [0] gets you the stylesheet
head = [m.value for m in at7.markdown if "<div class='gp-head'>" in m.value]
assert head and "Week 9" in head[0], \
    f"the app is still reading the file it opened: {head}"
assert not at7.selectbox, "the replacement has only one week"
print("a replaced database file is reopened, not read from the grave OK")

print("\nALL APP TESTS PASS")
