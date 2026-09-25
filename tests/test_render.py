"""Drive the real app against fixture ESPN data with Streamlit's AppTest.

Covers the things that are only true once the whole screen renders: the
order games come out in, the numbering that ties the app to the Splash
page, the import banners, and grading.

    python tests/test_render.py
"""
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime as dt, timedelta as td, timezone as tz

import requests

APP = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "streamlit_app.py"))

# Fixtures are anchored to the NEXT Saturday, never hard-coded dates — a
# hard-coded September once made every game read as locked and the whole
# suite lied for an afternoon.
_now = dt.now(tz.utc)
_sat = _now + td(days=(5 - _now.weekday()) % 7 or 7)


def when(day_offset, hhmm):
    return f"{(_sat + td(days=day_offset)).strftime('%Y-%m-%d')}T{hhmm}Z"


def event(eid, away, home, date, fav=None, line=None, aml=None, hml=None, ou=None,
          completed=False, ascore=None, hscore=None):
    def comp(abbr, name, ha, score):
        return {"homeAway": ha, "score": score,
                "team": {"id": "99", "abbreviation": abbr, "shortDisplayName": name,
                         "displayName": name, "location": name},
                "records": [{"type": "total", "summary": "2-0"}]}
    odds = {}
    if fav and line is not None:
        odds["details"] = f"{fav} -{line}"
    if ou:
        odds["overUnder"] = ou
    if aml:
        odds["awayTeamOdds"] = {"moneyLine": aml}
    if hml:
        odds["homeTeamOdds"] = {"moneyLine": hml}
    return {"id": eid, "shortName": f"{away[0]} @ {home[0]}", "date": date,
            "status": {"type": {"completed": completed,
                                "shortDetail": "Final" if completed else "Sat 3:30"}},
            "competitions": [{"competitors": [comp(*home, "home", hscore),
                                              comp(*away, "away", ascore)],
                              "odds": [odds] if odds else [],
                              "broadcasts": [{"names": ["ABC"]}]}]}


# Kickoff order here is deliberately NOT the order these are pasted in, and
# not flip order either — that is the whole point of the ordering tests.
CFB = {"week": {"number": 3}, "season": {"year": 2026}, "events": [
    event("1", ("OSU", "Ohio State"), ("TEX", "Texas"), when(0, "19:30"),
          fav="OSU", line=2.5, aml=-140, hml=120, ou=52.5),
    event("2", ("OHIO", "Ohio"), ("WVU", "West Virginia"), when(0, "16:00"),
          fav="WVU", line=10.5),
    event("3", ("BAMA", "Alabama"), ("WIS", "Wisconsin"), when(0, "23:30"),
          fav="BAMA", line=7.0, aml=-310, hml=250),
    event("4", ("USU", "Utah State"), ("UTAH", "Utah"), when(0, "22:00"),
          fav="UTAH", line=21.0),
]}
NFL = {"week": {"number": 2}, "season": {"year": 2026}, "events": [
    event("10", ("GB", "Packers"), ("MIN", "Vikings"), when(1, "17:00"),
          fav="GB", line=1.5, ou=47.5),
]}
SUMMARY = {"predictor": {"homeTeam": {"gameProjection": "44.2"},
                         "awayTeam": {"gameProjection": "55.8"}},
           "lastFiveGames": [{"team": {"abbreviation": "MIN"},
                              "events": [{"gameResult": "W"}, {"gameResult": "L"},
                                         {"gameResult": "W"}, {"gameResult": "W"}]}],
           "injuries": [{"team": {"abbreviation": "GB"}, "injuries": [{}, {}]}]}
FPI = {"predictives": [{"name": "fpi", "value": 3.1}, {"name": "fpirank", "value": 12.0},
                       {"name": "epaoffense", "value": 1.2},
                       {"name": "epadefense", "value": -0.4}]}
TEAMSTATS = {"splits": {"categories": [
    {"name": "general", "stats": [{"name": "gamesPlayed", "value": 13.0}]},
    {"name": "passing", "stats": [{"name": "yardsPerGame", "value": 401.2},
                                  {"name": "yardsPerPassAttempt", "value": 7.9}]},
    {"name": "rushing", "stats": [{"name": "yardsPerRushAttempt", "value": 4.8}]},
    {"name": "defensive", "stats": [{"name": "sacks", "value": 31.0}]},
    {"name": "scoring", "stats": [{"name": "totalPointsPerGame", "value": 31.7}]},
    {"name": "miscellaneous", "stats": [{"name": "thirdDownConvPct", "value": 44.1},
                                        {"name": "redzoneTouchdownPct", "value": 63.2},
                                        {"name": "turnOverDifferential", "value": 6.0}]}]}}


class FakeResp:
    def __init__(self, payload):
        self.payload, self.status_code = payload, 200
    def json(self):
        return self.payload
    def raise_for_status(self):
        pass


def fake_get(url, params=None, **kw):
    if "powerindex" in url:
        return FakeResp(FPI)
    if "sports.core.api" in url:
        return FakeResp(TEAMSTATS)
    if "summary" in url:
        return FakeResp(SUMMARY)
    return FakeResp(NFL if "/nfl/" in url else CFB)


requests.get = fake_get
requests.put = lambda *a, **k: FakeResp({})

from streamlit.testing.v1 import AppTest        # noqa: E402


def fresh(name):
    """A run of the app in its own directory, so each case starts with an
    empty database."""
    work = os.path.join(tempfile.gettempdir(), f"gp_render_{name}")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    shutil.copy(APP, f"{work}/app.py")
    os.chdir(work)
    at = AppTest.from_file(f"{work}/app.py", default_timeout=90)
    at.run()
    return at


def boom(at, label):
    if at.exception:
        print(f"EXCEPTION {label}:", [e.value for e in at.exception])
        sys.exit(1)


def cards(at):
    """(number, team named on the card) for each game card, in render order."""
    out = []
    for m in at.markdown:
        if "<div class='pick-card'>" not in m.value:
            continue
        num = re.search(r"pick-num'>(\d+)\.", m.value)
        team = (re.search(r"pick-team'>([^<]+)<", m.value)
                or re.search(r"pick-opp'> — ([A-Za-z ]+?) at ", m.value))
        out.append((int(num.group(1)) if num else None,
                    team.group(1) if team else "?"))
    return out


def load(at, text):
    at.text_area[0].set_value(text)
    at.button(key="FormSubmitter:import_form-Add these games").click().run()
    return at


PASTE = ("Ohio State vs Texas\nOhio vs West Virginia\nAlabama vs Wisconsin\n"
         "Utah State vs Utah\nPackers vs Vikings")
# 12:00 Ohio/WVU, 3:30 Ohio St/Texas, 6:00 Utah St/Utah, 7:30 Bama/Wisconsin,
# then Sunday's Packers/Vikings
KICKOFF_ORDER = ["West Virginia", "Ohio State", "Utah", "Alabama", "Packers"]

# ── boots clean, imports, picks ──────────────────────────────────────────
at = fresh("main")
boom(at, "on first render")
load(at, PASTE)
boom(at, "after import")
pick_all = [b for b in at.button if "Pick all" in b.label]
assert pick_all, [b.label for b in at.button]
pick_all[0].click().run()
boom(at, "after pick-all")

# ── kickoff order, numbered — the app and the Splash page in step ────────
seq = cards(at)
print("card order:", seq)
assert [n for n, _t in seq] == [1, 2, 3, 4, 5], seq
assert [t for _n, t in seq] == KICKOFF_ORDER, seq
print("cards run in kickoff order, numbered OK")

# ── the standouts sit on top, pointing at a real card number ─────────────
stand = [m.value for m in at.markdown if "<div class='standout'>" in m.value]
assert stand, "a flip was recommended but no standout row rendered"
snum = int(re.search(r"pick-num'>(\d+)\.", stand[0]).group(1))
assert 1 <= snum <= len(seq), snum
assert "Vikings" in stand[0] and "over Packers" in stand[0], stand[0]
assert snum == 5, f"standout points at {snum}, Packers/Vikings is 5"
print("standout block points into the list OK")

# ── the copy list uses the same numbers ──────────────────────────────────
splash = [l for l in at.code[0].value.splitlines() if re.match(r"\s*\d+\.", l)]
assert [int(l.split(".")[0]) for l in splash] == [1, 2, 3, 4, 5], splash
assert "Vikings" in splash[4] or "Packers" in splash[4], splash
print("Splash copy list numbering matches OK")

# ── a game added by hand has no stored page position; it must still slot
#    into its own time slot rather than landing at the end ───────────────
at2 = fresh("handadd")
load(at2, "Ohio State vs Texas\nAlabama vs Wisconsin\nUtah State vs Utah\n"
          "Packers vs Vikings")          # everything except the 12:00 game
add = [b for b in at2.button if b.key == "ad_2"]
assert add, "no hand-add button for the 12:00 game"
add[0].click().run()
boom(at2, "after hand-add")
seq2 = cards(at2)
print("with a hand-added game:", seq2)
assert [n for n, _t in seq2] == [1, 2, 3, 4, 5], seq2
assert seq2[0][1] == "Ohio", f"hand-added 12:00 game did not slot first: {seq2}"
print("hand-added game slots by kickoff OK")

# ── re-importing a board that loaded partially re-slots, never appends ───
at3 = fresh("reimport")
load(at3, "Alabama vs Wisconsin\nPackers vs Vikings")
load(at3, PASTE)
boom(at3, "after re-import")
seq3 = [t for _n, t in cards(at3)]
assert seq3 == ["Ohio", "Ohio State", "Utah State", "Alabama", "Packers"], seq3
print("re-import re-slots the early games OK")

# ── the board's own game count is checked, and a shortfall is named ──────
at4 = fresh("count")
at4.query_params["games"] = ("Saturday, Sep 26 2 games\nOSU 64.1%\nOhio State\n"
                             "TEX 35.9%\nTexas\nGB\nPackers\nMIN\nVikings\n")
at4.run()
boom(at4, "on URL import")
notes = [el.value for el in at4.success]
assert any("Got all 2 games" in n for n in notes), notes
assert not at4.warning, [w.value for w in at4.warning]
assert "games" not in at4.query_params, "param would re-import on refresh"

at5 = fresh("short")
at5.query_params["games"] = "Saturday, Sep 26 3 games\nOSU\nTEX\nGB\nMIN\nZZZ\nQQQ\n"
at5.run()
boom(at5, "on short import")
warns = [w.value for w in at5.warning]
assert any("3 games" in w and "matched 2" in w for w in warns), warns
assert any("ZZZ" in w for w in warns), "unplaced codes not named"
print("count check reports a full board and names a short one OK")

# ── grading: a SQL NULL result arrives as NaN, which is truthy and is not
#    None. The old guard never fired and cards read "nan" ────────────────
import streamlit as strm                                    # noqa: E402

at6 = fresh("grade")
load(at6, "Ohio State vs Texas")
[b for b in at6.button if "Pick all" in b.label][0].click().run()

# Same game, now final 31-24. The scoreboard is cached for an hour, so the
# cache has to be dropped or the app never sees the result.
DONE = dict(CFB, events=[
    event("1", ("OSU", "Ohio State"), ("TEX", "Texas"), when(0, "19:30"),
          fav="OSU", line=2.5, aml=-140, hml=120,
          completed=True, ascore="31", hscore="24")])
requests.get = lambda url, params=None, **kw: FakeResp(
    FPI if "powerindex" in url else
    TEAMSTATS if "sports.core.api" in url else
    SUMMARY if "summary" in url else
    NFL if "/nfl/" in url else DONE)
strm.cache_data.clear()
at6.run()
boom(at6, "after grading")
graded = [m.value for m in at6.markdown if "<div class='pick-card'>" in m.value]
assert graded, "no card rendered after the game finished"
assert "nan" not in graded[0].lower(), graded[0]
assert "✅ Won" in graded[0], graded[0]
assert "OSU 31" in graded[0] and "24 TEX" in graded[0], graded[0]
print("finished games grade instead of rendering nan OK")

print("\nALL RENDER TESTS PASS")
