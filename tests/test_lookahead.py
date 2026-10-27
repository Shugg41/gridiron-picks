"""Rating a weekend with no board — against a fake ESPN, not the real one.

The point of the module is that it works before Splash has posted
anything, so the tests give it no board and no database.

    python tests/test_lookahead.py
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from gridiron import espn, lookahead                          # noqa: E402


def side(abbr, team_id):
    return {"id": team_id, "abbr": abbr, "full_name": abbr,
            "location": abbr, "name": abbr}


def game(away, home, league, rank=None, kick="2026-11-07T20:30", eid="1"):
    return {"away": side(*away), "home": side(*home), "rank": rank or {},
            "event_id": eid, "kickoff": kick, "league": league}


# ── the weekend is Thursday to Monday, from any day of the week ────────
mon = lookahead.weekend(datetime.date(2026, 11, 2))
assert mon[0] == "20261105", mon            # Monday -> that Thursday
assert mon == ["20261105", "20261106", "20261107", "20261108", "20261109"]
thu = lookahead.weekend(datetime.date(2026, 11, 5))
assert thu[0] == "20261105", thu            # Thursday -> today, not next week
fri = lookahead.weekend(datetime.date(2026, 11, 6))
assert fri[0] == "20261112", fri            # Friday -> the NEXT Thursday
print("the weekend window is Thursday to Monday OK")

# ── which games are worth rating ───────────────────────────────────────
assert lookahead.worth_rating(game(("KC", "1"), ("DEN", "2"), "NFL"))
assert not lookahead.worth_rating(game(("UMASS", "3"), ("AKR", "4"), "CFB"))
assert lookahead.worth_rating(
    game(("UGA", "5"), ("MISS", "6"), "CFB", rank={"away": 3}))
print("every NFL game, and college only when someone is ranked OK")

# ── the home handicap, read without matching a team name ──────────────
# The bug this replaces: "AFA -2.5" was matched against ESPN's spelling
# of the home team, and when the spelling did not match, the line was
# taken to be the away team's and the sign flipped. UConn came out
# favoured over an Air Force side the whole market had by three, and it
# was reported to the user as the app's mistake rather than this one's.
def odds(**kw):
    return {"items": [kw]}


# Laying 2.5 at home: the home team is favoured.
assert lookahead.home_handicap(
    odds(homeTeamOdds={"current": {"pointSpread": {"american": "-2.5"}}})) == -2.5
# Getting 3 at home: the home team is the underdog.
assert lookahead.home_handicap(
    odds(homeTeamOdds={"current": {"pointSpread": {"american": "+3"}}})) == 3.0
# No "current" block yet — the opening price still answers.
assert lookahead.home_handicap(
    odds(homeTeamOdds={"pointSpread": {"american": "-7"}})) == -7.0
# Neither, but ESPN's signed spread field is there.
assert lookahead.home_handicap(odds(spread=-4.5)) == -4.5
# Only the printed string, and it names the home team.
assert lookahead.home_handicap(
    odds(details="AFA -2.5",
         homeTeamOdds={"team": {"abbreviation": "AFA"}})) == -2.5
# Only the printed string, naming somebody this code cannot identify.
# None, never a guess: a flipped sign is worse than a missing number.
assert lookahead.home_handicap(
    odds(details="CONN -2.5",
         homeTeamOdds={"team": {"abbreviation": "AFA"}})) is None
assert lookahead.home_handicap(odds(details="AFA -2.5")) is None
assert lookahead.home_handicap({}) is None
print("the home handicap is read, not inferred from a name OK")

# A home favourite must come out above even money, which is the whole
# point of the bug above.
espn.clear_cache()
espn.odds_history = lambda eid, lg: odds(
    homeTeamOdds={"current": {"pointSpread": {"american": "-2.5"}}})
p_home = lookahead.market_home(game(("CONN", "9"), ("AFA", "8"), "CFB"))
assert p_home > 0.5, p_home
print(f"a home team laying 2.5 reads as {p_home:.0%} to win OK")

# ── rating with both signals, one signal, and neither ──────────────────
espn.clear_cache()
# Signed from the HOME team: Denver lays 3.5, Denver gets 7.
MARKET = {"both": "-3.5", "mkt": "+7"}
FPI = {"1": {"fpi": 10.0}, "2": {"fpi": 4.0}, "3": None}
espn.odds_history = lambda eid, lg: (
    {"items": [{"homeTeamOdds": {"current": {"pointSpread":
                                             {"american": MARKET[eid]}}}}]}
    if eid in MARKET else {"items": []})
espn.power_index = lambda tid, lg, season: FPI.get(tid)

both = game(("KC", "1"), ("DEN", "2"), "NFL", eid="both")
mkt_only = game(("KC", "1"), ("DEN", "3"), "NFL", eid="mkt")
fpi_only = game(("KC", "1"), ("DEN", "2"), "NFL", eid="none")
neither = game(("KC", "3"), ("DEN", "3"), "NFL", eid="none")

rows = {r["event"]["event_id"] + r["home"]: r
        for r in lookahead.rate([both, mkt_only, fpi_only, neither])}
assert len(rows) == 3, "a game neither source can price must be dropped"

r = rows["bothDEN"]
assert r["sources"] == ("market", "fpi"), r["sources"]
# Denver lays 3.5 so the market likes them; FPI has Kansas City 6 better
# than Denver before a 2-point home edge, so FPI likes Kansas City.
assert r["market"] > 0.5 and r["fpi"] < 0.5, (r["market"], r["fpi"])
assert r["split"], "two signals pointing at different teams is a split"
assert 0 < r["confidence"] <= 1

assert rows["mktDEN"]["sources"] == ("market",)
assert not rows["mktDEN"]["split"], "one signal cannot disagree with itself"
assert rows["noneDEN"]["sources"] == ("fpi",)
print("both signals, one signal, and a game with neither OK")

# ── the pick always names a team that is actually in the game ──────────
for r in rows.values():
    assert r["pick"] in (r["away"], r["home"]), r
    want = r["home"] if r["blend"] >= 0.5 else r["away"]
    assert r["pick"] == want and r["confidence"] >= 0.5, r
print("the pick and its confidence agree with the blend OK")

# ── collect() asks ESPN by date and skips the games nobody would carry ─
espn.clear_cache()
CARD = {
    ("nfl", "20261105"): [game(("JAX", "1"), ("BAL", "2"), "NFL", eid="n1")],
    ("college-football", "20261107"): [
        game(("UGA", "1"), ("MISS", "2"), "CFB", rank={"away": 3}, eid="c1"),
        game(("UMASS", "1"), ("AKR", "2"), "CFB", eid="c2"),
        game(("UGA", "1"), ("MISS", "2"), "CFB", rank={"away": 3}, eid="c1"),
    ],
}
espn.events_on = lambda league, day, ttl=3600: CARD.get((league, day), [])
got = lookahead.collect(["20261105", "20261107"])
assert [g["event_id"] for g in got] == ["n1", "c1"], [g["event_id"] for g in got]
print("collect takes the NFL game and the ranked one, once each OK")

print("\nALL LOOKAHEAD TESTS PASS")
