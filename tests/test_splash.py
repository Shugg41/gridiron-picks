"""Reading the Splash pages — tested against the real thing.

The fixtures under tests/fixtures are verbatim copies of pages the user
actually pasted, not an idea of what they look like. Every parser bug this
project has had came from writing against a remembered shape, so these
tests only trust the saved pages.

    python tests/test_splash.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from gridiron import splash                                   # noqa: E402

HERE = os.path.dirname(__file__)
ENTRY = open(os.path.join(HERE, "fixtures", "entry_week4.txt")).read()
DIST = open(os.path.join(HERE, "fixtures", "distribution_week4.txt")).read()
STAND = open(os.path.join(HERE, "fixtures", "standings_week4.txt")).read()

# ── which page is this? ─────────────────────────────────────────────────
assert splash.sniff(ENTRY) == "entry", splash.sniff(ENTRY)
assert splash.sniff(DIST) == "distribution", splash.sniff(DIST)
assert splash.sniff(STAND) == "standings", splash.sniff(STAND)
# every page carries the same nav bar, so the nav must not decide it
for page in (ENTRY, DIST, STAND):
    assert "Pick Distribution" in page and "Standings" in page
assert splash.sniff("") is None
assert splash.sniff("just some text") is None
print("sniff tells the pages apart OK")

# ── team codes vs page furniture ────────────────────────────────────────
for good in ("MIA", "SF", "CLEM", "TXAM", "MSST", "TEX A&M", "LA"):
    assert splash.is_code(good), good
for junk in ("FINAL", "LIVE", "AUTOPICKS", "PICK DISTRIBUTION", "Q2", "PM",
             "Winner", "1 pick", "44.0%", "Saturday, Sep 26"):
    assert not splash.is_code(junk), junk
assert splash.is_code("NO"), "New Orleans is a real team code"
print("is_code separates teams from furniture OK")

# ── the entry page ──────────────────────────────────────────────────────
e = splash.parse_entry(ENTRY)
assert e.rank == 16, e.rank
assert e.points == 63, e.points
assert e.tiebreaker == 42, e.tiebreaker
assert len(e.games) == 21, len(e.games)

first = e.games[0]
assert (first.away, first.home) == ("Army", "Temple"), first
assert (first.away_code, first.home_code) == ("ARMY", "TEM"), first
assert (first.away_score, first.home_score) == (21, 17), first
assert first.day == "Friday, Sep 25", first.day
assert first.final and first.winner == "ARMY"
print("entry page: names, codes, scores, day, rank, tiebreaker OK")

# ── the pick is recovered from the scoreline, since the text never says ─
picked = {g.away_code + "/" + g.home_code: g.picked for g in e.games if g.final}
assert picked["ARMY/TEM"] == "ARMY", picked        # won, scored -> took winner
assert picked["NAVY/UAB"] == "NAVY", picked        # lost, no point -> took loser
assert picked["UCLA/MD"] == "MD", picked           # the expensive contrarian one
assert picked["MISS/FLA"] == "MISS", picked
assert picked["IOWA/MICH"] == "MICH", picked
assert picked["OKST/WVU"] == "WVU", picked
assert picked["SDSU/TOL"] == "TOL", picked
# 15 final games, 10 of them scored
final = [g for g in e.games if g.final]
assert len(final) == 15, len(final)
assert sum(g.points for g in final) == 10, sum(g.points for g in final)
print("picks recovered from the scoreline OK (10-5 on the week)")

# ── games not yet decided give nothing away, and must not pretend to ────
live = [g for g in e.games if g.status.upper().startswith("LIVE")]
upcoming = [g for g in e.games if not g.status and not g.final]
assert live and upcoming, (len(live), len(upcoming))
for g in live + upcoming:
    assert g.picked is None, (g.away_code, g.picked)
    assert g.winner is None, g.away_code
assert upcoming[0].away_code == "ARI" and upcoming[0].home_code == "SF"
assert upcoming[0].away_score is None, upcoming[0]
assert "4:05" in upcoming[0].kickoff, upcoming[0].kickoff
print("live and unstarted games stay unknown OK")

# ── the distribution page ───────────────────────────────────────────────
rows = splash.parse_distribution(DIST)
assert len(rows) == 7, len(rows)
(code, n, pct), (code2, n2, pct2) = rows[0]
assert (code, n) == ("GB", 34) and abs(pct - 0.895) < 1e-9, rows[0]
assert (code2, n2) == ("ATL", 1) and abs(pct2 - 0.026) < 1e-9, rows[0]
assert rows[2][1] == ("UAB", 0, 0.0), rows[2]      # nobody took UAB
assert rows[-1][0][0] == "SEA", rows[-1]           # a live game parses too
# the week tabs at the top are dates and numbers, not teams
assert not any(c in ("CFB", "NFL", "Sep") for (c, _n, _p), _b in rows)
print("distribution page OK")

# ── the finding that matters: the entry page HIDES games you didn't pick
entry_codes = {g.away_code for g in e.games} | {g.home_code for g in e.games}
dist_codes = {s[0] for pair in rows for s in pair}
missing = dist_codes - entry_codes
assert missing == {"GB", "ATL"}, missing
print("entry page omits unpicked games — reconcile against the board OK")

# ── the standings page ──────────────────────────────────────────────────
rows, size = splash.parse_standings(STAND)
assert size == 38, size
assert len(rows) == 8, len(rows)          # the fixture is trimmed to 8 shapes
assert [r.rank for r in rows] == sorted(r.rank for r in rows)

top = rows[0]
assert (top.rank, top.name, top.points) == (1, "KB-778", 70), top
assert (top.wins, top.losses, top.tie_diff) == (70, 20, 18), top

mine = [r for r in rows if r.me]
assert len(mine) == 1, mine
me = mine[0]
assert (me.rank, me.name, me.points) == (16, "MJSMITH1642", 63), me
assert me.tie_diff == 21, me
assert "You" not in me.name, "the marker should be stripped from the name"

# rows with no avatar initial, and the same entrant twice under different
# entry names — both real shapes on the page, both easy to get wrong
no_avatar = [r for r in rows if r.rank == 6][0]
assert no_avatar.name == "Godfather-CFP", no_avatar
twice = [r for r in rows if r.name == "toddbuckeye"]
assert len(twice) == 2 and {t.entry for t in twice} == {"Kylefootball", "Toddfootballc"}
print("standings page OK")

# ── what the standings are actually FOR: how alive the season is ────────
leader = rows[0].points
gap = leader - me.points
played = me.wins + me.losses + me.ties
assert (gap, played) == (7, 90), (gap, played)
# 4 weeks of 20 done, so ~360 games left; 7 points is well inside one
# standard deviation of that, which is what keeps the app in chalk mode
import math
games_left = played / 4 * 16
sd = math.sqrt(games_left * 0.7 * 0.3)
assert gap < sd, (gap, sd)
print(f"contention: {gap} pts behind, ~{games_left:.0f} games left, 1 SD = {sd:.1f} OK")

# ── nothing here may raise on junk ──────────────────────────────────────
for junk in ("", "\n\n\n", "no games here", "1\n2\n3\n", ENTRY[:120],
             DIST[:80], "FINAL\nFINAL\nFINAL"):
    splash.parse_entry(junk)
    splash.parse_distribution(junk)
    splash.parse_standings(junk)
    splash.sniff(junk)
assert splash.parse_entry("").games == []
assert splash.parse_distribution("") == []
assert splash.parse_standings("") == ([], 0)
print("junk input degrades quietly OK")

# ── a truncated page keeps the games it did see ─────────────────────────
half = ENTRY[:ENTRY.index("Sunday, Sep 27")]
h = splash.parse_entry(half)
assert len(h.games) == 15, len(h.games)
assert h.rank == 16 and h.tiebreaker is None
print("a half-copied page keeps what it got OK")

print("\nALL SPLASH TESTS PASS")
