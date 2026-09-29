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
MATRIX = open(os.path.join(HERE, "fixtures", "picks_by_week4.txt")).read()
BOARD = open(os.path.join(HERE, "fixtures", "board_week5.txt")).read()
WEEK1 = open(os.path.join(HERE, "fixtures", "entry_week1.txt")).read()

# ── which page is this? ─────────────────────────────────────────────────
assert splash.sniff(ENTRY) == "entry", splash.sniff(ENTRY)
assert splash.sniff(DIST) == "distribution", splash.sniff(DIST)
assert splash.sniff(STAND) == "standings", splash.sniff(STAND)
# The board reached the app unrecognised once, an hour before a deadline,
# because every marker sniff knew about belonged to some other page.
assert splash.sniff(BOARD) == "board", splash.sniff(BOARD)
assert splash.sniff(MATRIX) == "picks_by_week", splash.sniff(MATRIX)
# every page carries the same nav bar, so the nav must not decide it
for page in (ENTRY, DIST, STAND):
    assert "Pick Distribution" in page and "Standings" in page
# and the matrix page shares the standings furniture too, which is why it
# has to be tested for before standings rather than after
assert "Standings" in MATRIX and "All entries" in MATRIX
assert ". View entry details" in MATRIX
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

# ── the picks matrix: every entry's pick on every game ─────────────────
games, entries = splash.parse_picks_by_week(MATRIX)
assert games[0] == ("ATL", "GB"), games[0]
assert len(games) == 12, len(games)        # the fixture is trimmed
assert len(entries) == 4, [e.name for e in entries]
assert all(len(e.picks) == len(games) for e in entries), \
    [(e.name, len(e.picks)) for e in entries]

lead = entries[0]
assert (lead.rank, lead.name, lead.points) == ("1", "mrainer", 14), lead
assert lead.picks[0] == ("ATL", "W"), lead.picks[0]   # the one who had Atlanta

mine = [e for e in entries if e.me]
assert len(mine) == 1 and mine[0].name == "MJSMITH1642", [e.name for e in entries]
me_picks = mine[0]
assert me_picks.rank == "T15" and me_picks.points == 10, me_picks

# THE finding: the page states a missing pick outright. No other page does
# — the entry page just omits the game, which is how it stayed hidden.
assert me_picks.picks[0] == (None, "missing"), me_picks.picks[0]
assert me_picks.picks[6] == ("MD", "L"), me_picks.picks[6]
assert me_picks.picks[9] == ("BUF", "live_up"), me_picks.picks[9]
assert me_picks.picks[11] == ("PHI", "open"), me_picks.picks[11]

# rows with a custom entry label, and with no avatar initial, both parse
assert [e.entry for e in entries if e.name == "toddbuckeye"] == ["Kylefootball"]
assert [e.rank for e in entries if e.name == "Ttowndoc"] == ["T8"]
print("picks matrix OK — including the missing pick stated outright")

# ── the matrix subsumes the distribution page, and more exactly ─────────
dist = splash.distribution_from_matrix(games, entries)
assert len(dist) == len(games)
(a_code, a_n, _a_pct), (h_code, h_n, _h_pct) = dist[0]
assert (a_code, a_n) == ("ATL", 1), dist[0]       # only the leader had ATL
assert (h_code, h_n) == ("GB", 2), dist[0]        # two took GB, one missed
assert a_n + h_n == len(entries) - 1, "the missing pick must not be counted"
print("distribution derived from the matrix OK")

# ── the board: the only page that exists before the deadline ───────────
b = splash.parse_board(BOARD)
assert b.expected == 36, b.expected
assert len(b.games) == 36, f"{len(b.games)} of the page's own 36"
assert b.tiebreaker is None, "an empty total-score box is not a guess of 0"

pairs = [(g.away_code, g.home_code) for g in b.games]
assert len(set(pairs)) == 36, "a game was read twice"
# the last game is printed again under the Tiebreaker heading, and that
# copy must not become a 37th game
assert pairs.count(("ATL", "NO")) == 1

first, last = b.games[0], b.games[-1]
assert (first.away, first.away_code) == ("Steelers", "PIT")
assert (first.home, first.home_code) == ("Browns", "CLE")
assert (first.day, first.kickoff) == ("Thursday, Oct 1", "Thu 8:15pm")
assert (last.away_code, last.home_code) == ("ATL", "NO"), "NO is New Orleans"
assert last.day == "Monday, Oct 5"

by = {(g.away_code, g.home_code): g for g in b.games}
# a ranked team carries an extra "#7ranked #7" line before its code, on
# one side or both or neither
assert by[("ALA", "MSST")].away == "Alabama"          # both ranked
assert by[("AUB", "TENN")].home == "Tennessee"        # home only
assert by[("WASH", "USC")].away == "Washington"       # home only, again
assert by[("PIT", "CLE")].away == "Steelers"          # neither
# a team name can itself look like a code, so names are never code-tested
assert by[("BYU", "TCU")].away == "BYU"
assert by[("SJSU", "HAW")].home == "Hawai'i"
# CIN is Cincinnati in one game and the Bengals in another the same week
assert ("CIN", "ARIZ") in by and ("JAC", "CIN") in by
assert not any(g.points is not None or g.final for g in b.games), \
    "nothing on the board has been played yet"
print("the board parses, all 36, ranks and repeats and all OK")

# ── the board dates its own games ──────────────────────────────────────
# Without this the card sorts on the text "Mon 8:15pm", which puts Monday
# third (Fri, Mon, Sat, Sun, Thu), and nothing can tell that a Thursday
# game locks at kickoff rather than at Saturday noon.
iso = [g.kickoff_iso for g in b.games]
assert all(iso), f"{sum(1 for x in iso if not x)} games never got a date"
assert iso == sorted(iso), "the board is not in kickoff order"
assert by[("PIT", "CLE")].kickoff_iso == "2026-10-02T00:15Z", \
    by[("PIT", "CLE")].kickoff_iso        # Thu 8:15pm ET is Friday in UTC
assert by[("ATL", "NO")].kickoff_iso == "2026-10-06T00:15Z"
# a game whose printed weekday has rolled past the day header's
assert by[("SJSU", "HAW")].kickoff_iso.startswith("2026-10-04T04:00")
# the year is nowhere near the day headers; it comes off the lock line
assert splash._board_year(BOARD) == 2026
assert splash._board_year("no lock line here") is None
assert splash._board_kickoff("Saturday, Oct 3", "Sat 12:00pm", None) == ""
assert splash._board_kickoff("", "Sat 12:00pm", 2026) == ""
print("every game on the board is dated, and in order OK")

# a board with games missing says so, rather than looking complete
short = BOARD[:BOARD.index("Saturday, Oct 3")] + BOARD[BOARD.index("Tiebreaker"):]
sb = splash.parse_board(short)
assert sb.expected == 36 and len(sb.games) == 4, len(sb.games)
print("a part-copied board keeps its stated count OK")

# the entry page must not be dragged into the board parser, and the board
# must not parse as an entry — the app tries both and takes the larger
assert len(splash.parse_board(ENTRY).games) < len(splash.parse_entry(ENTRY).games)
assert len(splash.parse_entry(BOARD).games) < len(splash.parse_board(BOARD).games)
print("board and entry pages stay told apart OK")

# ── the same page, printed three different ways ────────────────────────
# Week 1's entry page carries the records between the two codes, which
# week 4's did not, and spells the score as "1 points" rather than "1".
# It parsed to zero games — and reported that as a clean empty week.
w1 = splash.parse_entry(WEEK1)
assert len(w1.games) == 17, len(w1.games)
assert sum(g.points or 0 for g in w1.games) == 15, "15-2 on the week"
assert all(g.final and g.points is not None for g in w1.games)

w1by = {(g.away_code, g.home_code): g for g in w1.games}
# the two that were missed, recovered from the scoreline alone
assert w1by[("COLO", "GT")].picked == "GT", "Colorado won it 14-13"
assert w1by[("SJSU", "EMU")].picked == "EMU"
assert w1by[("TOL", "MSU")].picked == "MSU"
# ranks appear above either code, or the first one, or neither
assert w1by[("FRES", "USC")].home == "USC"          # rank on the home side
assert w1by[("MIA", "STAN")].away == "Miami (FL)"   # rank on the away side
assert w1by[("BSU", "ORE")].away == "Boise State"   # both ranked
assert w1by[("M-OH", "PITT")].away == "Miami (OH)"  # a hyphen in the code
assert w1by[("UNLV", "HAW")].home == "Hawai'i"
assert w1.games[0].day == "Thursday, Sep 3"
assert w1.games[-1].day == "Monday, Sep 7"
assert w1.tiebreaker is None, "the total-score box was left empty"
print("week 1's entry page — records, ranks, spelled-out points — OK")

# ── nothing here may raise on junk ──────────────────────────────────────
for junk in ("", "\n\n\n", "no games here", "1\n2\n3\n", ENTRY[:120],
             DIST[:80], "FINAL\nFINAL\nFINAL"):
    splash.parse_entry(junk)
    splash.parse_board(junk)
    splash.parse_distribution(junk)
    splash.parse_standings(junk)
    splash.parse_picks_by_week(junk)
    splash.sniff(junk)
assert splash.parse_entry("").games == []
assert splash.parse_board("").games == []
assert splash.parse_distribution("") == []
assert splash.parse_standings("") == ([], 0)
assert splash.parse_picks_by_week("") == ([], [])
print("junk input degrades quietly OK")

# ── a truncated page keeps the games it did see ─────────────────────────
half = ENTRY[:ENTRY.index("Sunday, Sep 27")]
h = splash.parse_entry(half)
assert len(h.games) == 15, len(h.games)
assert h.rank == 16 and h.tiebreaker is None
print("a half-copied page keeps what it got OK")

print("\nALL SPLASH TESTS PASS")
