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

# ── rating with both signals, one signal, and neither ──────────────────
espn.clear_cache()
MARKET = {"both": "DEN -3.5", "mkt": "KC -7"}
FPI = {"1": {"fpi": 10.0}, "2": {"fpi": 4.0}, "3": None}
espn.odds_history = lambda eid, lg: (
    {"items": [{"details": MARKET[eid]}]} if eid in MARKET else {"items": []})
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
