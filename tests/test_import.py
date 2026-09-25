"""Loading the Splash board — every failure this has actually had.

The board arrives as the whole Safari page via the clipboard. Four things
have gone wrong here in real use, and each one is a test below:

  1. cross-league code collisions inventing games (MIA, HOU, IND)
  2. two-letter codes (SF, KC, LA, TB, NE, GB, NO, LV) being invisible
  3. teams Splash spells differently than ESPN (JAC/WAS/LA vs JAX/WSH/LAR)
     silently costing a game
  4. a short import passing quietly, which is the worst one — picks get
     entered off this list

    python tests/test_import.py
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
exec(src[:src.index("# SETTINGS")], ns)          # helpers only, no UI
match = ns["match_paste_lines"]
expected_games, code_like = ns["expected_games"], ns["code_like"]


def side(abbr, loc, nm):
    return {"id": "1", "abbr": abbr, "name": nm, "full_name": f"{loc} {nm}",
            "location": loc, "rank": None, "record": "", "score": None, "winner": False}


def game(eid, away, home, league="NFL"):
    return {"league": league, "event_id": eid, "name": f"{away['abbr']} @ {home['abbr']}",
            "date": "2026-09-26T19:30Z", "completed": False, "status_detail": "",
            "neutral_site": False, "broadcast": "", "home": home, "away": away,
            "fav_abbr": None, "line": None, "over_under": None,
            "home_ml_prob": None, "away_ml_prob": None}


NFL = {"ARI": ("Arizona", "Cardinals"), "ATL": ("Atlanta", "Falcons"),
       "BAL": ("Baltimore", "Ravens"), "BUF": ("Buffalo", "Bills"),
       "CAR": ("Carolina", "Panthers"), "CHI": ("Chicago", "Bears"),
       "CIN": ("Cincinnati", "Bengals"), "CLE": ("Cleveland", "Browns"),
       "DAL": ("Dallas", "Cowboys"), "DEN": ("Denver", "Broncos"),
       "DET": ("Detroit", "Lions"), "GB": ("Green Bay", "Packers"),
       "HOU": ("Houston", "Texans"), "IND": ("Indianapolis", "Colts"),
       "JAX": ("Jacksonville", "Jaguars"), "KC": ("Kansas City", "Chiefs"),
       "LV": ("Las Vegas", "Raiders"), "LAC": ("Los Angeles", "Chargers"),
       "LAR": ("Los Angeles", "Rams"), "MIA": ("Miami", "Dolphins"),
       "MIN": ("Minnesota", "Vikings"), "NE": ("New England", "Patriots"),
       "NO": ("New Orleans", "Saints"), "NYG": ("New York", "Giants"),
       "NYJ": ("New York", "Jets"), "PHI": ("Philadelphia", "Eagles"),
       "PIT": ("Pittsburgh", "Steelers"), "SF": ("San Francisco", "49ers"),
       "SEA": ("Seattle", "Seahawks"), "TB": ("Tampa Bay", "Buccaneers"),
       "TEN": ("Tennessee", "Titans"), "WSH": ("Washington", "Commanders")}
CFB = {"UNC": ("North Carolina", "Tar Heels"), "CLEM": ("Clemson", "Tigers"),
       "ASU": ("Arizona State", "Sun Devils"), "KU": ("Kansas", "Jayhawks"),
       "WYO": ("Wyoming", "Cowboys"), "CMU": ("Central Michigan", "Chippewas"),
       "TEM": ("Temple", "Owls"), "TOL": ("Toledo", "Rockets"),
       "SMU": ("SMU", "Mustangs"), "LOU": ("Louisville", "Cardinals"),
       "FLA": ("Florida", "Gators"), "AUB": ("Auburn", "Tigers"),
       "VT": ("Virginia Tech", "Hokies"), "MD": ("Maryland", "Terrapins"),
       "LSU": ("LSU", "Tigers"), "MISS": ("Ole Miss", "Rebels"),
       "COLO": ("Colorado", "Buffaloes"), "NW": ("Northwestern", "Wildcats"),
       "APPST": ("Appalachian State", "Mountaineers"), "NCST": ("NC State", "Wolfpack"),
       # never on the board — planted to share loose aliases with teams that are
       "CSU": ("Colorado State", "Rams"), "WASH": ("Washington", "Huskies"),
       "NEB": ("Nebraska", "Cornhuskers"), "MIAF": ("Miami", "Hurricanes"),
       "UL": ("Louisiana", "Ragin Cajuns"), "LT": ("Louisiana Tech", "Bulldogs"),
       "WAKE": ("Wake Forest", "Demon Deacons"), "IU": ("Indiana", "Hoosiers"),
       "HOUC": ("Houston", "Cougars"), "TENN": ("Tennessee", "Volunteers")}

BOARD_NFL = [("DET", "BUF"), ("CLE", "TB"), ("NO", "BAL"), ("GB", "NYJ"),
             ("CAR", "ATL"), ("MIN", "CHI"), ("PIT", "NE"), ("PHI", "TEN"),
             ("CIN", "HOU"), ("JAX", "DEN"), ("LV", "LAC"), ("WSH", "DAL"),
             ("SEA", "ARI"), ("MIA", "SF"), ("IND", "KC"), ("NYG", "LAR")]
BOARD_CFB = [("UNC", "CLEM"), ("ASU", "KU"), ("WYO", "CMU"), ("TEM", "TOL"),
             ("SMU", "LOU"), ("FLA", "AUB"), ("VT", "MD"), ("LSU", "MISS"),
             ("COLO", "NW"), ("APPST", "NCST")]
DECOYS = [("CSU", "WASH"), ("NEB", "MIAF"), ("UL", "LT"), ("WAKE", "IU"),
          ("HOUC", "TENN")]
GAMES = ([game(f"nfl-{a}-{h}", side(a, *NFL[a]), side(h, *NFL[h])) for a, h in BOARD_NFL]
         + [game(f"cfb-{a}-{h}", side(a, *CFB[a]), side(h, *CFB[h]), "CFB")
            for a, h in BOARD_CFB]
         + [game(f"DECOY-{a}-{h}", side(a, *CFB[a]), side(h, *CFB[h]), "CFB")
            for a, h in DECOYS])
BOARD_SIZE = len(BOARD_NFL) + len(BOARD_CFB)

# Splash's spellings, which are not always ESPN's
SPLASH = {"JAX": "JAC", "WSH": "WAS", "LAR": "LA", "APPST": "APP"}


def page(pairs_by_day, with_names=True):
    """The Safari page as innerText renders it: a code, record, win
    percentage and status per team, day headers carrying the game count, and
    the sort listing at the bottom that repeats every team by name."""
    out = ["Make picks", "Entry 1", "Rules"]
    for day, pairs in pairs_by_day:
        n = len(pairs)
        out.append(f"{day} {n} game" + ("s" if n != 1 else ""))
        for a, h in pairs:
            for code in (a, h):
                out += [SPLASH.get(code, code), "1-1", "44.0%", "FINAL",
                        "Winner", "1 pick"]
    out += ["Tiebreaker", "Predict the total combined score.",
            "Sort", "Start Time", "League", "All Leagues"]
    if with_names:
        for a, h in [p for _d, ps in pairs_by_day for p in ps]:
            tbl = NFL if a in NFL else CFB
            for code in (a, h):
                loc, nm = tbl[code]
                out += [nm if tbl is NFL else loc, SPLASH.get(code, code)]
    return "\n".join(out)


BOARD = page([("Thursday, Sep 24", BOARD_NFL[:1]),
              ("Saturday, Sep 26", BOARD_CFB),
              ("Sunday, Sep 27", BOARD_NFL[1:])])

# ── the board states its own size, and the app checks against it ─────────
assert expected_games(BOARD) == BOARD_SIZE, expected_games(BOARD)
assert expected_games("no counts here") is None
print("expected_games OK")

# ── the whole page: everything found, nothing invented ───────────────────
matched, unmatched = match(BOARD, GAMES)
got = {g["event_id"] for _l, g in matched}
missing = [g["event_id"] for g in GAMES
           if not g["event_id"].startswith("DECOY") and g["event_id"] not in got]
phantom = sorted(e for e in got if e.startswith("DECOY"))
assert not missing, f"board games lost: {missing}"
assert not phantom, f"games invented: {phantom}"
assert len(got) == BOARD_SIZE
assert not [u for u in unmatched if code_like(u)], \
    [u for u in unmatched if code_like(u)]
print(f"whole page: {len(got)}/{BOARD_SIZE} found, no phantoms OK")

# ── codes alone (no names) must still resolve, Splash spellings and all ──
codes_only = page([("Thursday, Sep 24", BOARD_NFL[:1]),
                   ("Saturday, Sep 26", BOARD_CFB),
                   ("Sunday, Sep 27", BOARD_NFL[1:])], with_names=False)
matched2, _u = match(codes_only, GAMES)
got2 = {g["event_id"] for _l, g in matched2}
assert not [e for e in got2 if e.startswith("DECOY")], sorted(got2)
# JAC/WAS/LA/APP resolve through the derived aliases, not a hand-kept table
for eid in ("nfl-JAX-DEN", "nfl-WSH-DAL", "nfl-NYG-LAR", "cfb-APPST-NCST"):
    assert eid in got2, f"{eid} lost when only codes are sent"
# two-letter codes stay visible
for eid in ("nfl-MIA-SF", "nfl-IND-KC", "nfl-CLE-TB", "nfl-NO-BAL", "nfl-PIT-NE",
            "nfl-GB-NYJ", "nfl-LV-LAC"):
    assert eid in got2, f"two-letter code game lost: {eid}"
print(f"codes only: {len(got2)}/{BOARD_SIZE} found OK")

# ── a team nothing can derive is REPORTED, never dropped silently ────────
mystery = BOARD.replace("CMU", "CHIPS").replace("Central Michigan", "Chippewa U")
m3, u3 = match(mystery, GAMES)
stray = [u for u in u3 if code_like(u)]
assert len({g["event_id"] for _l, g in m3}) == BOARD_SIZE - 1
assert "CHIPS" in stray, stray
print("an unknown team is surfaced, not dropped OK")

# ── page furniture is not mistaken for a missing team ────────────────────
for junk in ("FINAL", "LIVE", "Winner", "1 pick", "44.0%", "Sat, Sep 26 3:30 PM",
             "AM", "PM", "ET", "OT", "TBD", "VS", "AT"):
    assert not code_like(junk), junk
for real in ("MIA", "SF", "CLEM", "APP", "MSU", "TEX A&M"):
    assert code_like(real), real
print("code_like separates teams from furniture OK")

# ── a tidy "A vs B" list still works — one line naming both teams ────────
tidy = "Ohio State vs Texas\nPackers vs Vikings"
tidy_games = [game("t1", side("OSU", "Ohio State", "Buckeyes"),
                   side("TEX", "Texas", "Longhorns"), "CFB"),
              game("t2", side("GB", *NFL["GB"]), side("MIN", *NFL["MIN"]))]
assert len(match(tidy, tidy_games)[0]) == 2
# but one word cannot be both sides of a game
assert not match("Louisville", [game("x", side("UL", *CFB["UL"]),
                                     side("LT", *CFB["LT"]), "CFB")])[0]
print("tidy list OK, self-pairing rejected OK")

# ── a stray mention far from its opponent is not a game ──────────────────
stray_page = "\n".join(["MIA"] + [f"filler {i}" for i in range(40)] + ["SF"])
assert not match(stray_page, GAMES)[0], "teams 40 lines apart are not a game"
print("distant mentions rejected OK")

print("\nALL IMPORT TESTS PASS")
