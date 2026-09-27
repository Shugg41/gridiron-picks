"""The league's own picks, read off Splash's Pick Distribution page.

This is the only place the field is visible, and a weekly prize is won
against the field rather than against the spread — so a parse that drifts
out of step, or quietly attributes one game's numbers to another, would be
worse than having no data at all.

    python tests/test_field.py
"""
import os
import sys
import types

st = types.ModuleType("streamlit")
st.set_page_config = lambda **k: None
st.markdown = lambda *a, **k: None
st.secrets, st.session_state = {}, {}
def _cache_data(**k):
    def deco(f):
        f.clear = lambda: None
        return f
    return deco
st.cache_data = _cache_data
st.cache_resource = lambda f: f
sys.modules["streamlit"] = st

APP = os.path.join(os.path.dirname(__file__), "..", "streamlit_app.py")
src = open(APP).read()
ns = {}
exec(src[:src.index("# SETTINGS")], ns)
parse = ns["parse_distribution"]
match_dist = ns["match_distribution"]
field_share = ns["field_share"]
tendency = ns["field_tendency"]
expected_share = ns["expected_field_share"]


# Never hard-code a date: a past kickoff reads as locked, and locked games
# are filtered out of flip ranking, so the ordering tests would quietly
# assert nothing at all.
from datetime import datetime as _dt, timedelta as _td, timezone as _tz  # noqa: E402

_now = _dt.now(_tz.utc)
KICK = (_now + _td(days=(5 - _now.weekday()) % 7 or 7)).strftime("%Y-%m-%dT23:30Z")


def side(abbr, loc, nm):
    return {"id": "1", "abbr": abbr, "name": nm, "full_name": f"{loc} {nm}",
            "location": loc, "rank": None, "record": "", "score": None, "winner": False}


def game(eid, away, home, hml=None, aml=None):
    return {"league": "NFL", "event_id": eid, "name": f"{away['abbr']} @ {home['abbr']}",
            "date": KICK, "completed": False, "status_detail": "",
            "neutral_site": False, "broadcast": "", "home": home, "away": away,
            "fav_abbr": None, "line": None, "over_under": None,
            "home_ml_prob": hml, "away_ml_prob": aml}


# Verbatim from the real page, including the codes Splash uses rather than
# ESPN's (WAS not WSH) and a game with a live clock instead of FINAL.
PAGE = """Pick Distribution
CFB Week 1
Sep 1-8
Falcons 35 @ Packers 14
FINAL
PICKS
PICK DISTRIBUTION
AUTOPICKS
Lost.
GB
34
(89.5%)
–
Won.
ATL
1
(2.6%)
–
Navy 20 @ UAB 24
FINAL
PICKS
PICK DISTRIBUTION
AUTOPICKS
Lost.
NAVY
37
(97.4%)
–
Won.
UAB
0
(0%)
–
Clemson 24 @ California 10
FINAL
PICKS
PICK DISTRIBUTION
AUTOPICKS
Won.
CLEM
21
(55.3%)
–
Lost.
CAL
16
(42.1%)
–
Seahawks 7 @ Commanders 14
Q2 6:38
PICKS
PICK DISTRIBUTION
AUTOPICKS
Live.
SEA
37
(97.4%)
–
Live.
WAS
0
(0%)
–
"""

rows = parse(PAGE)
assert len(rows) == 4, rows
def close(a, b):
    return a[0] == b[0] and a[1] == b[1] and abs(a[2] - b[2]) < 1e-9

assert close(rows[0][0], ("GB", 34, 0.895)) and close(rows[0][1], ("ATL", 1, 0.026)), rows[0]
assert close(rows[1][0], ("NAVY", 37, 0.974)) and close(rows[1][1], ("UAB", 0, 0.0)), rows[1]
assert rows[3][0][0] == "SEA", rows[3]          # a live game parses too
print("parses the real page OK")

# the week tabs at the top carry dates and numbers; none of it is a team
assert not any(c in ("Sep", "CFB", "NFL") for (c, _n, _p), _b in rows)
print("week navigation is not mistaken for teams OK")

# ── pairing to real games ────────────────────────────────────────────────
ATL = side("ATL", "Atlanta", "Falcons")
GB = side("GB", "Green Bay", "Packers")
NAVY = side("NAVY", "Navy", "Midshipmen")
UAB = side("UAB", "UAB", "Blazers")
CLEM = side("CLEM", "Clemson", "Tigers")
CAL = side("CAL", "California", "Golden Bears")
SEA = side("SEA", "Seattle", "Seahawks")
WSH = side("WSH", "Washington", "Commanders")     # ESPN spells it WSH
games = [game("g1", ATL, GB, hml=0.72, aml=0.33),
         game("g2", NAVY, UAB), game("g3", CLEM, CAL),
         game("g4", SEA, WSH)]

matched, unmatched = match_dist(PAGE, games)
assert len(matched) == 4, (len(matched), unmatched)
assert not unmatched, unmatched
by_id = {g["event_id"]: (a, b) for g, a, b in matched}
assert by_id["g1"][0][0] == "GB", by_id["g1"]
# Splash's WAS resolves to ESPN's WSH through the derived aliases
assert by_id["g4"][1][0] == "WAS", by_id["g4"]
print("pairs to real games, Splash spellings and all OK")

# a pair naming two teams that never played is dropped, not guessed at
BAD = """Nonsense 1 @ Nonsense 2
PICKS
Lost.
GB
34
(89.5%)
–
Won.
UAB
1
(2.6%)
–
"""
m2, u2 = match_dist(BAD, games)
assert not m2 and u2 == ["GB / UAB"], (m2, u2)
print("a drifted pair is reported, not attributed OK")

# ── looking a share up ───────────────────────────────────────────────────
fld = {"g1": {"gb": 0.895, "atl": 0.026}}
assert field_share(fld, games[0], GB) == 0.895
assert field_share(fld, games[0], ATL) == 0.026
assert field_share(fld, games[1], NAVY) is None
print("field_share OK")

# ── learning how chalky the league is ────────────────────────────────────
# favorites only; the league is chalkier than the market at every level
hist = [(0.62, 0.72), (0.65, 0.78), (0.82, 0.92), (0.85, 0.90),
        (0.95, 0.974), (0.38, 0.28)]        # the last is the dog side, ignored
t = tendency(hist)
assert 1 in t and abs(t[1] - 0.75) < 1e-9, t       # 0.60-0.70 bucket
assert 3 in t and abs(t[3] - 0.91) < 1e-9, t       # 0.80-0.90 bucket
assert 0 not in t, "nothing seen in the 50-60 range yet"
assert tendency([]) == {}
assert tendency([(None, 0.9), (0.7, None)]) == {}
print("field_tendency OK")

# a coin flip with no history falls back to the market, harmlessly
coin = game("c", side("A", "A", "Aces"), side("B", "B", "Bears"),
            hml=0.52, aml=0.52)
assert abs(expected_share(coin, {}) - 0.5) < 0.02, expected_share(coin, {})
# a heavy favorite in a bucket we have seen reports what the league does
heavy = game("h", side("A", "A", "Aces"), side("B", "B", "Bears"),
             hml=0.86, aml=0.18)
assert expected_share(heavy, t) == t[3], (expected_share(heavy, t), t)
assert expected_share(game("n", side("A", "A", "A"), side("B", "B", "B")), t) is None
print("expected_field_share OK")

# ── the ordering this is all for ─────────────────────────────────────────
rank = ns["rank_flips"]
ns["fpi_probs"] = lambda g: (None, None)

# Mechanically: with the league's habits known, the game the crowd will
# pile into sorts ahead of an equally live dog the crowd is split on.
mild = game("mild", side("X", "X", "Xs"), side("Y", "Y", "Ys"),
            hml=0.55, aml=0.50)                  # favorite ~52%
steep = game("steep", side("P", "P", "Ps"), side("Q", "Q", "Qs"),
             hml=0.64, aml=0.40)                  # favorite ~62%
lean = {0: 0.55, 1: 0.95}        # the league splits 50-60, piles on 60-70
order = [g["event_id"] for _s, g, _d in rank([mild, steep], lean)]
assert order[0] == "steep", order
assert [g["event_id"] for _s, g, _d in rank([mild, steep])] == ["mild", "steep"], \
    "without a tendency the livelier dog still leads"
# the score handed back is untouched, so recommended_flips' thresholds mean
# what they always did
by_id = {g["event_id"]: sc for sc, g, _d in rank([mild, steep], lean)}
plain = {g["event_id"]: sc for sc, g, _d in rank([mild, steep])}
assert by_id == plain, (by_id, plain)
print("rank_flips leans on the crowd without moving the thresholds OK")

# Honestly, though: real flip candidates are all near coin flips, so they
# land in one bucket and the lean cannot separate them yet. This is what
# accumulating weeks is for, and the test says so out loud rather than
# pretending the feature discriminates today.
a = game("a", side("A", "A", "As"), side("B", "B", "Bs"), hml=0.55, aml=0.50)
b = game("b", side("C", "C", "Cs"), side("D", "D", "Ds"), hml=0.53, aml=0.52)
one_bucket = {0: 0.62}
assert ([g["event_id"] for _s, g, _d in rank([a, b], one_bucket)]
        == [g["event_id"] for _s, g, _d in rank([a, b])]), \
    "same bucket, so the order should be unchanged — not silently shuffled"
print("coin flips in one bucket keep their order (needs more weeks) OK")

print("\nALL FIELD TESTS PASS")
