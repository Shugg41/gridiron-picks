"""Picking the week, and deciding how brave to be.

The strategy test runs against the user's real standings, because the
whole point of the dial is that it answers a question about a specific
season rather than a hypothetical one.

    python tests/test_model.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from gridiron import espn, model, splash                       # noqa: E402

HERE = os.path.dirname(__file__)
STAND = open(os.path.join(HERE, "fixtures", "standings_week4.txt")).read()


def ev(away, home, league="NFL", details=None, ou=None, hml=None, aml=None):
    def team(code):
        return {"id": "1", "abbreviation": code, "shortDisplayName": code,
                "displayName": code, "location": code}
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
        "id": f"{away}{home}", "date": "2026-10-03T17:00Z",
        "status": {"type": {"completed": False, "shortDetail": ""}},
        "competitions": [{"competitors": [
            dict(homeAway="home", score=None, team=team(home)),
            dict(homeAway="away", score=None, team=team(away))],
            "odds": [odds] if odds else []}]}, league)


# ── the plain words ─────────────────────────────────────────────────────
assert model.confidence(None) == "No line yet"
assert model.confidence(0.95) == "Safe" and model.confidence(0.78) == "Safe"
assert model.confidence(0.77) == "Should win" and model.confidence(0.60) == "Should win"
assert model.confidence(0.59) == "Close call" and model.confidence(0.10) == "Close call"
print("confidence wording OK")

# ── who is favored ──────────────────────────────────────────────────────
heavy = ev("MIA", "BUF", details="BUF -10")
fav, dog, p = model.favorite(heavy)
assert (fav, dog) == ("BUF", "MIA") and p > 0.7, (fav, dog, p)
assert abs(model.dog_chance(heavy) - (1 - p)) < 1e-9
assert model.favorite(None) == (None, None, None)
assert model.favorite(ev("MIA", "BUF")) == (None, None, None), "no odds, no guess"
print("favorite OK")

# ── FPI's second opinion ────────────────────────────────────────────────
close = ev("GB", "MIN", details="GB -1.5")
# FPI rating the home side 8 points better must like them more than a
# market that has them as a small underdog
edge = model.fpi_edge(close, fpi_home=8.0, fpi_away=0.0)
assert edge is not None and edge > 0.1, edge
assert model.fpi_edge(close, None, 2.0) is None
assert model.fpi_edge(None, 1.0, 2.0) is None
print("fpi_edge OK")

# ── the dial, on the real standings ─────────────────────────────────────
rows, _size = splash.parse_standings(STAND)
s = model.strategy(rows, weeks_left=16)
assert s.mode == "chalk", s
assert s.flips == model.CHALK_FLIPS
assert s.gap == 6, s.gap                      # third place is 69, user 63
assert s.per_week < 0.5, s.per_week
assert "season is live" in s.why.lower(), s.why
print("strategy on the real standings:", s.why)

# same gap, almost no season left -> the maths flips it
late = model.strategy(rows, weeks_left=2)
assert late.mode == "hunt" and late.flips == model.HUNT_FLIPS, late
assert "not happening on chalk" in late.why, late.why

# already in a paying place
top = model.strategy(rows, weeks_left=16, paying=20)
assert top.mode == "chalk" and top.gap == 0, top
assert "holding a paying spot" in top.why, top.why

# no standings at all -> straight, and says so rather than guessing
blank = model.strategy([], weeks_left=16)
assert blank.mode == "chalk" and "No standings" in blank.why, blank
assert model.strategy(rows, weeks_left=0).mode == "chalk"
print("strategy dial OK")


# ── picking a week ──────────────────────────────────────────────────────
def game(a, h):
    return splash.Game(away_code=a, home_code=h)


linked = [
    (game("MIA", "BUF"), ev("MIA", "BUF", details="BUF -10")),     # chalk
    (game("GB", "MIN"), ev("GB", "MIN", details="MIN -1")),        # coin flip
    (game("NYJ", "NE"), ev("NYJ", "NE", details="NE -0.5")),       # coin flip
    (game("DAL", "PHI"), ev("DAL", "PHI", details="PHI -1")),      # coin flip
    (game("SEA", "SF"), ev("SEA", "SF", details="SF -14")),        # chalk
    (game("ZZZ", "QQQ"), None),                                    # no line
]
picks = model.propose(linked, strat=model.Strategy())
assert len(picks) == len(linked), "every game must get a pick slot"
by = {(p.away, p.home): p for p in picks}
assert by[("MIA", "BUF")].team == "BUF" and by[("MIA", "BUF")].basis == "line"
assert by[("SEA", "SF")].team == "SF"
# ── the pick is said in Splash's spelling, not ESPN's ─────────────────
# ESPN calls South Carolina SC and Splash calls them SCAR. The pick was
# being written down as SC: a code that appears nowhere on the board,
# so the field's share of it was always None, the advice tracker could
# never match it against the entry, and the list the user types from
# named a team Splash does not use.
crossed = [(game("UK", "SCAR"), ev("UK", "SC", details="SC -7")),
           (game("LA", "PHI"), ev("LAR", "PHI", details="LAR -3"))]
xp = {(p.away, p.home): p for p in model.propose(crossed,
                                                 strat=model.Strategy())}
assert xp[("UK", "SCAR")].team == "SCAR", xp[("UK", "SCAR")].team
assert xp[("UK", "SCAR")].other == "UK"
assert xp[("LA", "PHI")].team == "LA", xp[("LA", "PHI")].team
assert xp[("LA", "PHI")].other == "PHI"

# and the field's share is found, which it never was while the pick
# was named in the other vocabulary
xfield = {("UK", "SCAR"): {"SCAR": 0.8, "UK": 0.2}}
xf = model.propose(crossed, field=xfield, strat=model.Strategy())[0]
assert xf.field_on_team == 0.8, xf.field_on_team
print("picks are named the way Splash names them OK")

# a game with no odds gets no pick, and is not quietly dropped
assert by[("ZZZ", "QQQ")].team is None and by[("ZZZ", "QQQ")].basis == "none"

flips = [p for p in picks if p.basis == "flip"]
assert len(flips) == model.CHALK_FLIPS, [(f.away, f.home) for f in flips]
# a flip is picking the side with under an even chance, on purpose
assert all(f.prob is not None and f.prob < 0.5 for f in flips), \
    [(f.team, f.prob) for f in flips]
assert all(f.other_prob > f.prob for f in flips)
# a flip takes the underdog, and the heavy favorites are never touched
assert by[("GB", "MIN")].team == "GB", by[("GB", "MIN")]
assert by[("MIA", "BUF")].basis == "line" and by[("SEA", "SF")].basis == "line"
print(f"proposed {len(picks)} games, {len(flips)} flips, chalk untouched OK")

# asking for six when only three games are close cannot invent three more
hunted = model.propose(linked, strat=model.Strategy("hunt", model.HUNT_FLIPS))
assert len([p for p in hunted if p.basis == "flip"]) == 3, \
    "only three games are close enough to flip"

# and a chalky week yields fewer flips than asked for, rather than
# reaching down into spots where the points stop being cheap
chalky = [(game("MIA", "BUF"), ev("MIA", "BUF", details="BUF -10")),
          (game("SEA", "SF"), ev("SEA", "SF", details="SF -14")),
          (game("NYJ", "NE"), ev("NYJ", "NE", details="NE -6"))]
few = model.propose(chalky, strat=model.Strategy())
assert [p for p in few if p.basis == "flip"] == [], \
    "nothing here is close; the right number of flips is zero"
print("a chalky week produces no flips rather than bad ones OK")

# ── the crowd decides WHICH coin flips, when it is known ────────────────
field = {("GB", "MIN"): {"MIN": 0.55},      # pool is split
         ("NYJ", "NE"): {"NE": 0.95},       # pool is piled on the favorite
         ("DAL", "PHI"): {"PHI": 0.60}}
# and after flipping, the share follows the team actually picked
one_flip = model.propose(linked, field=field, strat=model.Strategy("chalk", 1))
picked = [p for p in one_flip if p.basis == "flip"]
assert len(picked) == 1 and (picked[0].away, picked[0].home) == ("NYJ", "NE"), \
    "the flip should go where the crowd is most exposed"
assert picked[0].team == "NYJ", picked[0]
assert abs(picked[0].field_on_team - 0.05) < 1e-9, picked[0].field_on_team
print("the crowd picks which coin flip to take OK")

# ── chalk is always recoverable from a proposal ─────────────────────────
for p in picks:
    if p.basis == "flip":
        assert model.chalk_of(p) != p.team
    else:
        assert model.chalk_of(p) == p.team
print("chalk_of OK")

# ── tiebreaker ──────────────────────────────────────────────────────────
assert model.tiebreaker(ev("PHI", "CHI", ou=44.5)) == 44
assert model.tiebreaker(ev("PHI", "CHI")) is None
assert model.tiebreaker(None) is None
print("tiebreaker OK")

# ── is the advice actually working ──────────────────────────────────────
# eight games: the app flipped two, one flip won and one lost; the user
# overrode one chalk pick and got it wrong
proposals = {("A" + str(i), "H" + str(i)): ("H" + str(i), "line") for i in range(6)}
proposals[("A6", "H6")] = ("A6", "flip")     # flip that wins
proposals[("A7", "H7")] = ("A7", "flip")     # flip that loses
winners = {("A" + str(i), "H" + str(i)): "H" + str(i) for i in range(6)}
winners[("A6", "H6")] = "A6"
winners[("A7", "H7")] = "H7"
entries = {k: (v[0], None) for k, v in proposals.items()}
entries[("A0", "H0")] = ("A0", None)         # the user's own override, wrong

rep = model.advice_report(proposals, entries, winners)
assert rep.graded == 8, rep
assert rep.app == 7, rep        # six chalk + the winning flip
assert rep.chalk == 7, rep      # six chalk + the losing flip's favorite
assert rep.actual == 6, rep     # the override cost one
assert "Too early" in rep.verdict, rep.verdict

big = model.advice_report({**proposals, **{(f"B{i}", f"C{i}"): (f"C{i}", "line")
                                           for i in range(20)}},
                          entries,
                          {**winners, **{(f"B{i}", f"C{i}"): f"C{i}"
                                         for i in range(20)}})
assert big.graded == 28 and big.app == 27, big
assert "paying" in big.verdict or "Level" in big.verdict, big.verdict
print("advice_report OK —", rep.verdict)

print("\nALL MODEL TESTS PASS")
