"""Playing the week out against the real field.

The property that matters most is correlation: everyone picks the same
favorites, so entries move together. A simulation that treated them as
independent would invent separation and wildly overstate the chance of
winning a week. There is a test for exactly that below.

    python tests/test_simulate.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from gridiron import model, simulate, splash                          # noqa: E402

HERE = os.path.dirname(__file__)
MATRIX = open(os.path.join(HERE, "fixtures", "picks_by_week4.txt")).read()

# ── a week nobody can lose ─────────────────────────────────────────────
certain = {("A", "B"): {"A": 1.0, "B": 0.0},
           ("C", "D"): {"C": 1.0, "D": 0.0}}
me = {("A", "B"): "A", ("C", "D"): "C"}
out = simulate.simulate(me, certain, trials=500)
assert out.mean == 2.0 and out.p10 == 2 and out.p90 == 2, out
print("a certain week is certain OK")

wrong = {("A", "B"): "B", ("C", "D"): "D"}
assert simulate.simulate(wrong, certain, trials=500).mean == 0.0
print("a card that cannot win scores nothing OK")

# ── coin flips land near the middle, and spread ────────────────────────
coins = {(f"A{i}", f"B{i}"): {f"A{i}": 0.5, f"B{i}": 0.5} for i in range(20)}
card = {k: k[0] for k in coins}
out = simulate.simulate(card, coins, trials=4000, seed=7)
assert 9.5 < out.mean < 10.5, out.mean
assert out.p10 < out.p50 < out.p90, out
print(f"20 coin flips: mean {out.mean:.1f}, 10th-90th {out.p10}-{out.p90} OK")

# ── the same seed gives the same answer ────────────────────────────────
a = simulate.simulate(card, coins, trials=500, seed=3)
b = simulate.simulate(card, coins, trials=500, seed=3)
assert (a.mean, a.win, a.p50) == (b.mean, b.win, b.p50)
assert simulate.simulate(card, coins, trials=500, seed=4).mean != a.mean
print("seeded runs are reproducible OK")

# ── correlation: an identical card can never beat the field ────────────
# Thirty entries holding exactly my card. However the games fall, we all
# score the same, so finishing FIRST outright is impossible — it is always
# a tie. Simulating entries independently would report a healthy win rate
# here, which is the error this guards.
clones = {f"clone{i}": dict(card) for i in range(30)}
out = simulate.simulate(card, coins, clones, trials=2000, seed=5)
assert out.win == 0.0, f"beat 30 copies of my own card {out.win:.1%} of the time"
assert out.tie == 1.0, out.tie
assert out.any_win == 1.0, out.any_win
print("identical cards always tie, never win outright OK")

# ── one differing game is the only thing that can separate you ─────────
key = ("A0", "B0")
rivals = {f"chalk{i}": {**card, key: "B0"} for i in range(30)}
out = simulate.simulate(card, coins, rivals, trials=4000, seed=11)
# I win exactly when my side of that one game comes in, and lose when it
# does not — a clean 50/50, with no ties possible
assert 0.45 < out.win < 0.55, out.win
assert out.tie == 0.0, out.tie
print(f"one differing coin flip decides it: win {out.win:.0%} OK")

# ── a rival who missed a pick cannot score it ──────────────────────────
sure = {("A", "B"): {"A": 1.0, "B": 0.0}}
out = simulate.simulate({("A", "B"): "A"}, sure,
                        {"lazy": {}}, trials=200)
assert out.win == 1.0, "a missed pick must cost the rival the game"
print("a missing pick scores nothing OK")

# ── against the real field from the matrix ─────────────────────────────
games, entries = splash.parse_picks_by_week(MATRIX)
rivals = simulate.rivals_from_matrix(games, entries)
assert len(rivals) == 3, list(rivals)          # four entries, minus me
assert all("/" in name for name in rivals), list(rivals)
mine_entry = [e for e in entries if e.me][0]
my_card = {}
for i, (a, h) in enumerate(games):
    team = mine_entry.picks[i][0]
    if team:
        my_card[(a, h)] = team
assert len(my_card) == len(games) - 1, "the missed game must not be in my card"

probs = {(a, h): {a: 0.5, h: 0.5} for a, h in games}
out = simulate.simulate(my_card, probs, rivals, trials=2000, seed=2)
assert out.field_size == 3
assert 0 <= out.win <= 1 and 0 <= out.any_win <= 1
# I am a game down on the field before a ball is thrown, so I should win
# outright less often than an even share of a four-way pool
assert out.win < 0.25, out.win
print(f"against the real field: win {out.win:.0%}, "
      f"any share {out.any_win:.0%}, mean {out.mean:.1f}")

# ── what the flips are worth, played both ways ─────────────────────────
from gridiron.model import Pick                                # noqa: E402

picks = [Pick(away="A0", home="B0", team="B0", other="A0", basis="flip",
              prob=0.48, other_prob=0.52)]
picks += [Pick(away=f"A{i}", home=f"B{i}", team=f"A{i}", other=f"B{i}",
               basis="line", prob=0.52, other_prob=0.48) for i in range(1, 20)]
chalky = {f"c{i}": {(p.away, p.home): (p.other if p.basis == "flip" else p.team)
                    for p in picks} for i in range(20)}
probs20 = {(p.away, p.home): {p.team: p.prob, p.other: p.other_prob}
           for p in picks}
flipped, chalk = simulate.what_flips_are_worth(picks, probs20, chalky,
                                               trials=4000, seed=13)
# Chalk is everyone else's card, so playing it can only ever tie
assert chalk.win == 0.0 and chalk.tie == 1.0, (chalk.win, chalk.tie)
# The flip gives up a little expected score to buy a real chance of
# finishing alone at the top — which is the entire argument for flipping
assert flipped.mean < chalk.mean, (flipped.mean, chalk.mean)
assert flipped.win > 0.4, flipped.win
print(f"flipping: mean {flipped.mean:.2f} vs chalk {chalk.mean:.2f}, "
      f"outright wins {flipped.win:.0%} vs {chalk.win:.0%} OK")

# ── probabilities from linked events, including a game with no line ────
from gridiron import espn                                      # noqa: E402


def ev(a, h, details=None):
    def team(c):
        return {"id": c, "abbreviation": c, "shortDisplayName": c,
                "displayName": c, "location": c}
    odds = {"details": details} if details else {}
    return espn.parse_event({
        "id": a + h, "date": "2026-10-03T17:00Z",
        "status": {"type": {"completed": False, "shortDetail": ""}},
        "competitions": [{"competitors": [
            dict(homeAway="home", score=None, team=team(h)),
            dict(homeAway="away", score=None, team=team(a))],
            "odds": [odds] if odds else []}]}, "NFL")


linked = [(splash.Game(away_code="MIA", home_code="BUF"),
           ev("MIA", "BUF", "BUF -7")),
          (splash.Game(away_code="ZZZ", home_code="QQQ"), None)]
p = simulate.probabilities(linked, [None, None])
assert p[("MIA", "BUF")]["BUF"] > 0.6, p
assert abs(sum(p[("MIA", "BUF")].values()) - 1) < 1e-9
assert p[("ZZZ", "QQQ")] == {"ZZZ": 0.5, "QQQ": 0.5}, \
    "a game with no line is a coin flip, not an absent game"
print("probabilities from events OK")


# ── a field estimated before the deadline ─────────────────────────────
# Splash publishes everyone's picks only after picks lock, so without
# this the one question worth asking cannot be asked while it can
# still be acted on.
shares = {("AA", "BB"): {"BB": 0.95, "AA": 0.05},
          ("CC", "DD"): {"DD": 0.55, "CC": 0.45}}
field = simulate.estimated_rivals(shares, 37)
assert len(field) == 37, len(field)
assert all(len(card) == 2 for card in field.values())

# the drawn shares track the predicted ones, within sampling noise
on_bb = sum(1 for c in field.values() if c[("AA", "BB")] == "BB") / 37
on_dd = sum(1 for c in field.values() if c[("CC", "DD")] == "DD") / 37
assert 0.85 <= on_bb <= 1.0, on_bb
assert 0.35 <= on_dd <= 0.75, on_dd
# and it is repeatable, because an estimate that moves every reload is
# not something anyone can act on
assert simulate.estimated_rivals(shares, 37) == field

# a game with no usable share is left out rather than guessed
half = simulate.estimated_rivals({("AA", "BB"): {"BB": 1.0}}, 5)
assert half == {}, half
assert simulate.estimated_rivals({}, 5) == {}
assert simulate.estimated_rivals(None, 5) == {}
print("a field can be estimated before the deadline OK")

# the curve it rests on, and its stated error
assert 0.75 < model.expected_share(1) < 0.82, model.expected_share(1)
assert 0.95 < model.expected_share(14) < 0.99
assert model.expected_share(None) is None
# the sign of the line must not matter — a favorite is a favorite
assert model.expected_share(-7) == model.expected_share(7)
assert model.FIELD_RMS > 0.1, "the fit is worse than it looks; say so"
print("the crowd curve is monotone, sign-blind and honest about error OK")

print("\nALL SIMULATE TESTS PASS")