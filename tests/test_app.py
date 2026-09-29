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
    return out


class Fake:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload

    def raise_for_status(self):
        pass


def fake_get(url, params=None, **kw):
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
import sqlite3 as _sq
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

print("\nALL APP TESTS PASS")
