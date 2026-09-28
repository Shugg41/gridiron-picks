"""ESPN as enrichment — and above all, link().

Every import bug this project has had lived at this seam. The rules under
test are the two that make the seam safe: every board game survives
whether or not it matches, and no ESPN event is ever claimed twice.

No network: ESPN is unreachable from here anyway, so payloads are built
by hand in the shape the real API returns.

    python tests/test_espn.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from gridiron import espn, splash                              # noqa: E402

HERE = os.path.dirname(__file__)


def event(eid, away, home, league="NFL", details=None, ou=None,
          hml=None, aml=None, completed=False):
    """A scoreboard event shaped the way ESPN returns one."""
    def team(t):
        code, loc, name = t
        return {"id": "1", "abbreviation": code, "shortDisplayName": name,
                "displayName": f"{loc} {name}", "location": loc}
    odds = {}
    if details:
        odds["details"] = details
    if ou:
        odds["overUnder"] = ou
    if hml is not None:
        odds["homeTeamOdds"] = {"moneyLine": hml}
    if aml is not None:
        odds["awayTeamOdds"] = {"moneyLine": aml}
    return espn.parse_event({
        "id": eid, "date": "2026-09-27T17:00Z",
        "status": {"type": {"completed": completed, "shortDetail": "Sun 1:00"}},
        "competitions": [{
            "competitors": [dict(homeAway="home", score=None, team=team(home)),
                            dict(homeAway="away", score=None, team=team(away))],
            "odds": [odds] if odds else []}]}, league)


# ── parsing ESPN's payloads ─────────────────────────────────────────────
e = event("1", ("ATL", "Atlanta", "Falcons"), ("GB", "Green Bay", "Packers"),
          details="GB -3.5", ou=47.5, hml=-180, aml=150)
assert e["event_id"] == "1" and e["league"] == "NFL"
assert e["home"]["abbr"] == "GB" and e["away"]["name"] == "Falcons"
assert (e["fav_abbr"], e["line"]) == ("GB", 3.5), e
assert e["over_under"] == 47.5
print("parse_event OK")

# missing keys must degrade, never raise — ESPN drops them without notice
bare = espn.parse_event({}, "NFL")
assert bare["event_id"] == "" and bare["line"] is None and bare["home"] == {}
assert espn.parse_event({"competitions": [{}]}, "CFB")["over_under"] is None
assert espn.parse_power({}) == {"fpi": None, "rank": None,
                                "epa_off": None, "epa_def": None}
assert espn.parse_stats({}) == {}
assert espn._spread("EVEN") == (None, None)
assert espn._spread(None) == (None, None)
assert espn._spread("BUF -3.5") == ("BUF", -3.5), "the sign has to survive"
assert espn._spread("BUF +3.5") == ("BUF", 3.5)

# a positive number names the UNDERDOG, so the favorite is the other side.
# Reading that sign off wrong backs the wrong team.
dog_named = event("d", ("ATL", "Atlanta", "Falcons"),
                  ("GB", "Green Bay", "Packers"), details="GB +3.5")
assert (dog_named["fav_abbr"], dog_named["line"]) == ("ATL", 3.5), dog_named
fav_named = event("f", ("ATL", "Atlanta", "Falcons"),
                  ("GB", "Green Bay", "Packers"), details="GB -3.5")
assert (fav_named["fav_abbr"], fav_named["line"]) == ("GB", 3.5), fav_named
assert espn.win_probability(dog_named)[1] > espn.win_probability(dog_named)[0], \
    "Atlanta is the favorite here, so the away probability must be higher"
print("missing and odd payloads degrade quietly OK")

# ── probabilities ───────────────────────────────────────────────────────
hp, ap = espn.win_probability(e)
assert hp and ap and abs(hp + ap - 1) < 1e-9, (hp, ap)
assert hp > ap, "Green Bay is favored at -180"
# the book's margin is removed: raw implied odds sum past 100%
raw = espn._implied(-180) + espn._implied(150)
assert raw > 1.0, raw
# with no moneyline the spread is used instead
spread_only = event("2", ("MIA", "Miami", "Dolphins"),
                    ("BUF", "Buffalo", "Bills"), details="BUF -7")
hp2, ap2 = espn.win_probability(spread_only)
assert 0.65 < hp2 < 0.75, hp2
# a college seven-point favorite is less certain than an NFL one
cfb = event("3", ("UNC", "North Carolina", "Tar Heels"),
            ("CLEM", "Clemson", "Tigers"), league="CFB", details="CLEM -7")
assert espn.win_probability(cfb)[0] < hp2
assert espn.win_probability(None) == (None, None)
assert espn.win_probability(
    event("4", ("MIA", "Miami", "Dolphins"), ("BUF", "Buffalo", "Bills"))) \
    == (None, None), "no odds at all means no probability, not a guess"
print("win_probability OK")

# ── link(): the seam where every import bug lived ───────────────────────
MATRIX = open(os.path.join(HERE, "fixtures", "picks_by_week4.txt")).read()
board, _entries = splash.parse_picks_by_week(MATRIX)
games = [splash.Game(away_code=a, home_code=h) for a, h in board]
assert [g.away_code for g in games][:3] == ["ATL", "ARMY", "NAVY"]

# ESPN's own spellings, which differ from Splash's on purpose here
espn_games = [
    event("e1", ("ATL", "Atlanta", "Falcons"), ("GB", "Green Bay", "Packers")),
    event("e2", ("ARMY", "Army", "Black Knights"), ("TEM", "Temple", "Owls"), "CFB"),
    event("e3", ("NAVY", "Navy", "Midshipmen"), ("UAB", "UAB", "Blazers"), "CFB"),
    event("e4", ("CLEM", "Clemson", "Tigers"), ("CAL", "California", "Golden Bears"), "CFB"),
    event("e5", ("SDSU", "San Diego State", "Aztecs"), ("TOL", "Toledo", "Rockets"), "CFB"),
    event("e6", ("TEX", "Texas", "Longhorns"), ("TENN", "Tennessee", "Volunteers"), "CFB"),
    event("e7", ("UCLA", "UCLA", "Bruins"), ("MD", "Maryland", "Terrapins"), "CFB"),
    event("e8", ("MISS", "Ole Miss", "Rebels"), ("FLA", "Florida", "Gators"), "CFB"),
    event("e9", ("SEA", "Seattle", "Seahawks"), ("WSH", "Washington", "Commanders")),
    event("e10", ("LAC", "Los Angeles", "Chargers"), ("BUF", "Buffalo", "Bills")),
    event("e11", ("ARI", "Arizona", "Cardinals"), ("SF", "San Francisco", "49ers")),
    event("e12", ("PHI", "Philadelphia", "Eagles"), ("CHI", "Chicago", "Bears")),
    # decoys that share codes or derived aliases with the real ones
    event("d1", ("MIA", "Miami", "Hurricanes"), ("WAKE", "Wake Forest", "Demon Deacons"), "CFB"),
    event("d2", ("WASH", "Washington", "Huskies"), ("CSU", "Colorado State", "Rams"), "CFB"),
    event("d3", ("ARMY", "Army", "Black Knights"), ("NAVY", "Navy", "Midshipmen"), "CFB"),
]

linked = espn.link(games, espn_games)
assert len(linked) == len(games), "every board game must come back"
by_code = {g.away_code + "@" + g.home_code: ev for g, ev in linked}
assert by_code["ATL@GB"]["event_id"] == "e1"
assert by_code["SEA@WAS"]["event_id"] == "e9", "Splash WAS must reach ESPN's WSH"
assert by_code["ARMY@TEM"]["event_id"] == "e2", "not the Army/Navy decoy"
assert by_code["NAVY@UAB"]["event_id"] == "e3"
assert all(ev is not None for ev in by_code.values()), \
    [k for k, v in by_code.items() if v is None]

# no ESPN event claimed twice
ids = [ev["event_id"] for ev in by_code.values()]
assert len(ids) == len(set(ids)), ids
assert "d1" not in ids and "d2" not in ids and "d3" not in ids, ids
print(f"link matched {len(ids)}/{len(games)}, no event reused, no decoys OK")

# ── the rule that matters most: a game with no match still exists ───────
orphan = splash.Game(away_code="ZZZ", home_code="QQQ", away="Nowhere",
                     home="Nobody")
out = espn.link(games + [orphan], espn_games)
assert len(out) == len(games) + 1, "the unmatched game was dropped"
assert out[-1][0] is orphan and out[-1][1] is None, out[-1]
# and with ESPN entirely unavailable, the whole board still comes back
blind = espn.link(games, [])
assert len(blind) == len(games) and all(ev is None for _g, ev in blind)
print("an unmatched game keeps its place with no line OK")

# ── exact spelling always beats a derived guess ─────────────────────────
# "LA" derives to Los Angeles, which both the Rams and Chargers answer to;
# the Chargers' own code must claim the Chargers.
two_la = [event("lar", ("LAR", "Los Angeles", "Rams"), ("DEN", "Denver", "Broncos")),
          event("lac", ("LAC", "Los Angeles", "Chargers"), ("BUF", "Buffalo", "Bills"))]
asked = [splash.Game(away_code="LAC", home_code="BUF"),
         splash.Game(away_code="LA", home_code="DEN")]
got = {g.away_code: (ev or {}).get("event_id") for g, ev in espn.link(asked, two_la)}
assert got == {"LAC": "lac", "LA": "lar"}, got
print("exact spellings win their event before guesses OK")

# ── line movement, against the payload shape CI actually returned ──────
# Notre Dame at North Carolina, week 5: opened ND -24.5, now ND -21. The
# home side's handicap went +24.5 -> +21, so the market came toward UNC.
REAL = {"items": [{
    "provider": {"name": "Draft Kings"},
    "details": "ND -21",
    "homeTeamOdds": {
        "favorite": False,
        "open": {"favorite": False,
                 "pointSpread": {"alternateDisplayValue": "+24.5",
                                 "american": "+24.5"}},
        "current": {"pointSpread": {"alternateDisplayValue": "+21",
                                    "american": "+21"}}},
    "awayTeamOdds": {
        "favorite": True,
        "open": {"favorite": True,
                 "pointSpread": {"american": "-24.5"}},
        "current": {"pointSpread": {"american": "-21"}}}}]}

pts, toward = espn.movement(REAL, "UNC", "ND")
assert pts == 3.5 and toward == "UNC", (pts, toward)

# Alabama at Mississippi State: opened ALA -3, now ALA -6. Home handicap
# +3 -> +6, so the market went the other way, toward the favorite.
OTHER = {"items": [{"homeTeamOdds": {
    "open": {"pointSpread": {"american": "+3"}},
    "current": {"pointSpread": {"american": "+6"}}}}]}
pts, toward = espn.movement(OTHER, "MSST", "ALA")
assert pts == 3.0 and toward == "ALA", (pts, toward)
print("line movement reads the real payload, both directions OK")

# a line that never moved is not a move, and neither is a missing opener
assert espn.movement({"items": [{"homeTeamOdds": {
    "open": {"pointSpread": {"american": "-3"}},
    "current": {"pointSpread": {"american": "-3"}}}}]}, "H", "A") == (None, None)
assert espn.movement({"items": [{"homeTeamOdds": {
    "current": {"pointSpread": {"american": "-3"}}}}]}, "H", "A") == (None, None)
assert espn.movement({"items": []}, "H", "A") == (None, None)
assert espn.movement({}, "H", "A") == (None, None)
assert espn.movement(None, "H", "A") == (None, None)
# half a point of drift is noise, not a signal
assert espn.movement({"items": [{"homeTeamOdds": {
    "open": {"pointSpread": {"american": "+3"}},
    "current": {"pointSpread": {"american": "+3.2"}}}}]}, "H", "A") == (None, None)
print("no move, no opener, and noise all report nothing OK")

# ── the cache is a cache, and can be emptied ────────────────────────────
calls = []
espn.clear_cache()
val = espn.cached(60, "k", lambda: calls.append(1) or "first")
assert val == "first" and espn.cached(60, "k", lambda: "second") == "first"
assert len(calls) == 1
espn.clear_cache()
assert espn.cached(60, "k", lambda: "third") == "third"
print("cache OK")

print("\nALL ESPN TESTS PASS")
