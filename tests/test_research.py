"""Research from ESPN's records — against shapes copied from a live probe.

Every payload below has the structure scripts/probe_research.py printed
from the real API, cut down to the fields that are read.

    python tests/test_research.py
"""
import datetime
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from gridiron import espn, research                           # noqa: E402

UTC = datetime.timezone.utc


def comp(tid, abbr, home, score, rank=99):
    return {"homeAway": "home" if home else "away",
            "score": None if score is None else
            {"value": float(score), "displayValue": str(score)},
            "curatedRank": {"current": rank},
            "team": {"id": tid, "abbreviation": abbr}}


def sched_event(eid, date, me, opp, done=True):
    """me/opp are (id, abbr, home, score, rank)."""
    return {"id": eid, "date": date,
            "competitions": [{
                "status": {"type": {"completed": done}},
                "competitors": [comp(*me), comp(*opp)]}]}


# Illinois: lost, then four wins; UCLA next on a Friday.
ILL = {"events": [
    sched_event("1", "2026-10-03T16:00Z", ("356", "ILL", True, 10), ("2", "OSU", False, 31, 3)),
    sched_event("2", "2026-10-10T16:00Z", ("356", "ILL", False, 27), ("3", "PUR", True, 20)),
    sched_event("3", "2026-10-24T16:00Z", ("356", "ILL", True, 30), ("4", "RUTG", False, 14)),
    sched_event("4", "2026-10-31T16:00Z", ("356", "ILL", False, 20), ("5", "MD", True, 17)),
    sched_event("5", "2026-11-07T01:00Z", ("356", "ILL", True, 24), ("6", "NEB", False, 13)),
    sched_event("6", "2026-11-14T02:00Z", ("356", "ILL", False, None), ("26", "UCLA", True, None, 8), done=False),
    sched_event("7", "2026-11-21T17:00Z", ("356", "ILL", True, None), ("7", "IU", False, None, 4), done=False),
]}
games = research.parse_schedule(ILL, "356")
assert len(games) == 7 and games[0]["opp"] == "OSU" and games[0]["opp_rank"] == 3
assert games[1]["opp_rank"] is None, "99 is ESPN's unranked, not a rank"
assert games[5]["done"] is False and games[5]["pf"] is None
kick = datetime.datetime(2026, 11, 14, 2, 0, tzinfo=UTC)
fm = research.form(games, kick)
assert (fm["wins"], fm["losses"], fm["streak"]) == (4, 1, 4), fm
assert fm["last"]["opp"] == "NEB" and fm["rest"] == 7, fm
assert fm["next"]["opp"] == "IU" and fm["next"]["opp_rank"] == 4
assert fm["last_ids"] == ["4", "5"]
assert abs(fm["margin3"] - ((16 + 3 + 11) / 3)) < 1e-9
assert fm["road_run"] == 0
print("a schedule becomes a record, a streak, rest and what comes next OK")

# A losing streak counts down, and a bye shows up as long rest.
LOSER = {"events": [
    sched_event("1", "2026-10-10T16:00Z", ("9", "X", True, 30), ("1", "A", False, 3)),
    sched_event("2", "2026-10-17T16:00Z", ("9", "X", False, 3), ("2", "B", True, 30)),
    sched_event("3", "2026-10-24T16:00Z", ("9", "X", False, 7), ("3", "C", True, 20)),
]}
fl = research.form(research.parse_schedule(LOSER, "9"),
                   datetime.datetime(2026, 11, 7, 17, 0, tzinfo=UTC))
assert fl["streak"] == -2 and fl["rest"] == 14 and fl["road_run"] == 2, fl
print("a losing streak, a bye and a run of road games are all read OK")

# A game still being played counts for rest. Buffalo were reported as
# "off a bye" on the night they were playing Minnesota.
MNF = {"events": LOSER["events"] + [
    sched_event("4", "2026-11-03T01:15Z", ("9", "X", True, None), ("4", "D", False, None), done=False)]}
fmnf = research.form(research.parse_schedule(MNF, "9"),
                     datetime.datetime(2026, 11, 7, 17, 0, tzinfo=UTC))
assert fmnf["rest"] == 4 and fmnf["last"]["opp"] == "C", fmnf
print("rest runs from the last game scheduled, not the last one finished OK")

# A game with no team match, or no date, is dropped rather than guessed.
assert research.parse_schedule({"events": [{"id": "x"}]}, "9") == []
assert research.form([], kick)["streak"] == 0

# ── who threw the passes ──────────────────────────────────────────────
def box(tid, *athletes):
    return {"boxscore": {"players": [{
        "team": {"id": tid},
        "statistics": [{"name": "passing",
                        "labels": ["C/ATT", "YDS"],
                        "athletes": [{"athlete": {"id": i, "displayName": n},
                                      "stats": [catt, "100"]}
                                     for i, n, catt in athletes]},
                       {"name": "rushing", "athletes": []}]}]}}


b = research.passers(box("194", ("2", "Luke Fahey", "21/38"),
                         ("9", "Trick Play", "1/1")), "194")
assert [p["name"] for p in b] == ["Luke Fahey", "Trick Play"] and b[0]["att"] == 38
assert research.passers(box("194", ("2", "Luke Fahey", "21/38")), "999") == []
assert research.passers({}, "194") == []

lead = {"leaders": [{"team": {"id": "194"}, "leaders": [
    {"name": "rushingYards", "leaders": [{"athlete": {"id": "7"}}]},
    {"name": "passingYards", "leaders": [
        {"displayValue": "150/210", "athlete": {"id": "1",
                                               "displayName": "Julian Sayin"}}]}]}]}
leader = research.season_passer(lead, "194")
assert leader == {"id": "1", "name": "Julian Sayin"}, leader
assert research.season_passer(lead, "5") is None
assert research.season_passer({"leaders": None}, "194") is None

fahey = [{"id": "2", "name": "Luke Fahey", "att": 38}]
sayin = [{"id": "1", "name": "Julian Sayin", "att": 30}]
new = research.quarterback(leader, [fahey, sayin])
assert new == {"now": "Luke Fahey", "leader": "Julian Sayin", "settled": False}
old = research.quarterback(leader, [fahey, fahey])
assert old["settled"] is True
assert research.quarterback(leader, [sayin, sayin]) is None, "no change"
# Nor is a blowout: the leader played, the backup mopped up.
blowout = [{"id": "2", "name": "Luke Fahey", "att": 15},
           {"id": "1", "name": "Julian Sayin", "att": 12}]
assert research.quarterback(leader, [blowout, sayin]) is None
# A wide receiver's one trick-play throw is not a quarterback change.
assert research.quarterback(leader, [[{"id": "9", "name": "WR", "att": 1}]]) is None
assert research.quarterback(None, [fahey]) is None
assert research.quarterback(leader, []) is None
print("a quarterback change is found, and dated as new or settled OK")

# ── the NFL injury list ───────────────────────────────────────────────
INJ = {"injuries": [{"id": "26", "displayName": "Seattle Seahawks", "injuries": [
    {"status": "Out", "date": "2026-11-09T22:51Z",
     "shortComment": "Darnold  (knee) has been\nruled out.",
     "athlete": {"displayName": "Sam Darnold",
                 "position": {"abbreviation": "QB"}}},
    {"status": "Active", "date": "2026-11-09T20:00Z", "shortComment": "",
     "athlete": {"displayName": "Drew Lock", "position": {"abbreviation": "QB"}}},
    {"status": "Out", "date": "2026-11-09T20:00Z", "shortComment": "x",
     "athlete": {"displayName": "Some Guard", "position": {"abbreviation": "G"}}}]}]}
inj = research.nfl_injuries(INJ)
assert list(inj) == ["26"] and len(inj["26"]) == 3
rep_ = research.qb_report(inj["26"], ["Sam Darnold", "Drew Lock", None])
assert [r["name"] for r in rep_] == ["Sam Darnold"], rep_
assert rep_[0]["date"] == "2026-11-09" and "\n" not in rep_[0]["note"]
assert research.qb_report(None, ["Sam Darnold"]) == []
assert research.qb_report(inj["26"], ["Somebody Else"]) == []
print("only a quarterback who matters, and is not active, is reported OK")

# ── reasons ───────────────────────────────────────────────────────────
def side(abbr, streak=0, rest=7, margin=0.0, last=None, nxt=None, road=0,
         qb=None, qb_inj=None, give=1.0):
    return {"abbr": abbr, "espn": abbr, "qb": qb, "qb_inj": qb_inj or [],
            "giveaways": give,
            "form": {"wins": 5, "losses": 3, "streak": streak, "rest": rest,
                     "margin3": margin, "last": last, "next": nxt,
                     "road_run": road, "last_ids": []}}


def ctx(dog, fav, **kw):
    base = {"league": "CFB", "total": 50.5, "moved": None, "toward": None,
            "market": 0.35, "fpi": 0.33, "dog": dog, "fav": fav,
            "fav_home": True}
    base.update(kw)
    return base


def kinds(pairs):
    return [k for k, _ in pairs]


# Nothing going on: no reasons either way.
f, a = research.reasons(ctx(side("DOG"), side("FAV")))
assert f == [] and a == [], (f, a)

# Week 10's winners, as the code would have seen them.
f, a = research.reasons(ctx(side("ILL", streak=3), side("NEB", streak=-3)))
assert kinds(f) == ["form", "form"] and not a, f
f, a = research.reasons(ctx(side("ORE"), side("OSU", qb=new)))
assert kinds(f) == ["quarterback"] and "new last week" in f[0][1], f
f, a = research.reasons(ctx(side("AFA"), side("ARMY"), moved=2.5, toward="AFA"))
assert kinds(f) == ["style", "line"], f           # option team, line move
f, a = research.reasons(ctx(side("WYO", streak=3, margin=12.0),
                            side("UNLV", margin=1.0), moved=1.0, toward="WYO"))
assert kinds(f) == ["form", "form"], f            # a 1-point move is noise
print("form, a quarterback change, the option and a line move are reasons OK")

# The same facts about the underdog count against it.
f, a = research.reasons(ctx(side("DOG", streak=-4, qb=old), side("FAV", streak=5)))
assert kinds(a) == ["quarterback", "form", "form"] and not f, (f, a)
assert "at least two games running" in a[0][1]

# The spot.
f, a = research.reasons(ctx(side("DOG", rest=10), side("FAV", rest=4)))
assert kinds(f) == ["situation"] and "4 days' rest" in f[0][1], f
f, a = research.reasons(ctx(side("DOG", rest=14), side("FAV", rest=7)))
assert "off a bye" in f[0][1], f
f, a = research.reasons(ctx(side("DOG", rest=7), side("FAV", rest=14)))
assert kinds(a) == ["situation"] and not f
big_win = {"won": True, "opp": "MICH", "opp_rank": 6, "pf": 30, "pa": 20}
f, a = research.reasons(ctx(side("DOG"), side(
    "FAV", last=big_win, nxt={"opp": "OSU", "opp_rank": 2}, road=2),
    fav_home=False))
assert kinds(f) == ["situation"] * 3, f
assert "#6 MICH" in f[0][1] and "#2 OSU next" in f[1][1] and "third" in f[2][1]
# A run of road games only matters if this one is on the road too.
f, a = research.reasons(ctx(side("DOG"), side("FAV", road=2), fav_home=True))
assert f == []
print("rest, a bye, a letdown, a look-ahead and a road run are spots OK")

# The shape of the game.
f, a = research.reasons(ctx(side("DOG", give=0.8), side("FAV", give=1.9),
                            total=38.5))
assert kinds(f) == ["style", "style"], f
f, a = research.reasons(ctx(side("DOG"), side("FAV"), total=41.5, league="NFL"))
assert f == [], "41.5 is low in college and ordinary in the NFL"

# The market.
f, a = research.reasons(ctx(side("DOG"), side("FAV"), moved=3.0, toward="FAV"))
assert kinds(a) == ["line"] and not f
f, a = research.reasons(ctx(side("DOG"), side("FAV"), moved=19.0, toward="DOG"))
assert f == [], "a 19-point 'move' is a stale opener, not money"
f, a = research.reasons(ctx(side("DOG"), side("FAV"), market=0.44, fpi=0.56))
assert "FPI makes DOG the favourite" in f[0][1], f
f, a = research.reasons(ctx(side("DOG"), side("FAV"), market=0.34, fpi=0.44))
assert "FPI gives DOG 44%, the market 34%" in f[0][1], f
f, a = research.reasons(ctx(side("DOG"), side("FAV"), market=0.34, fpi=None))
assert f == []
print("a low total, turnovers, the line and FPI are read without guessing OK")

# An NFL quarterback on the injury list.
f, a = research.reasons(ctx(side("LV"), side("SEA", qb_inj=rep_), league="NFL"))
assert kinds(f) == ["injury"] and "Sam Darnold Out (2026-11-09)" in f[0][1]
# With a change at quarterback as well it is still one reason, not two.
f, a = research.reasons(ctx(side("LV"), side("SEA", qb=new, qb_inj=rep_),
                            league="NFL"))
assert kinds(f) == ["quarterback"], f
assert "listed: Sam Darnold Out" in f[0][1], f

# ── the reading order and the page ────────────────────────────────────
def row(dog, fav, price, n_for, n_against=0, kickoff="2026-11-14T17:00"):
    d, fv = side(dog), side(fav)
    return {"league": "CFB", "away": dog, "home": fav, "kickoff": kickoff,
            "when": "Sat 12:00pm", "dog": d, "fav": fv, "price": price,
            "fpi": None, "total": 50.5, "moved": None, "toward_abbr": None,
            "for": [("form", f"reason {i}") for i in range(n_for)],
            "against": [("line", f"counter {i}") for i in range(n_against)]}


rows = [row("A", "B", 0.40, 1), row("C", "D", 0.30, 3, 1),
        row("E", "F", 0.10, 4),            # too long a shot
        row("G", "H", 0.49, 4),            # a coin flip
        row("I", "J", 0.35, 0),            # nothing to say
        row("K", "L", 0.35, 2, 2)]         # as much against as for
order = [r["dog"]["abbr"] for r in research.rank_games(rows)]
assert order == ["C", "A"], order
# News about who is playing reads first, unless it is two games old.
fresh = row("M", "N", 0.35, 0)
fresh["for"] = [("quarterback", "N are on X, not season leader Y (new last week)")]
stale = row("O", "P", 0.35, 0)
stale["for"] = [("quarterback", "P are on X, not season leader Y "
                                "(at least two games running)")]
two = row("Q", "R", 0.35, 2)
assert research.score(fresh) == 2 and research.score(stale) == 1
assert [r["dog"]["abbr"] for r in research.rank_games([stale, two, fresh])] \
    == ["Q", "M", "O"]
assert research.in_band(0.22) and research.in_band(0.47)
assert not research.in_band(None)
print("only priced-right underdogs with a reason make the list, best-read first OK")

page = research.render(11, rows, "Tue Nov 10, 9:00am ET", "the whole slate")
assert page.startswith("# Week 11 research")
assert "6 games read, 2 underdogs" in page, page[:300]
assert "### C over D — 30%" in page and "**for** (form): reason 0" in page
assert "*against* (line): counter 0" in page
assert page.count("\n| ") == 7, "a header row and one row per game"
assert "E @ F" in page, "every game is in the table, listed or not"
print("the page lists the candidates, then every game OK")

# ── end to end, with ESPN faked ───────────────────────────────────────
spec = importlib.util.spec_from_file_location(
    "research_cli", os.path.join(HERE, "..", "scripts", "research.py"))
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)

espn.clear_cache()
SEA = {"events": [
    sched_event("s1", "2026-11-01T21:00Z", ("26", "SEA", True, 17), ("3", "CHI", False, 34)),
    sched_event("s2", "2026-11-08T21:25Z", ("26", "SEA", True, 17), ("22", "ARI", False, 3)),
    sched_event("g", "2026-11-15T21:05Z", ("26", "SEA", False, None), ("13", "LV", True, None), done=False)]}
LV = {"events": [
    sched_event("l1", "2026-11-01T18:00Z", ("13", "LV", False, 38), ("20", "NYJ", True, 33)),
    sched_event("l2", "2026-11-08T21:25Z", ("13", "LV", False, 17), ("25", "SF", True, 38)),
    sched_event("g", "2026-11-15T21:05Z", ("13", "LV", True, None), ("26", "SEA", False, None), done=False)]}
espn.team_schedule = lambda tid, lg, season: {"26": SEA, "13": LV}[tid]
SUMM = {
    "g": {"leaders": [
        {"team": {"id": "26"}, "leaders": [{"name": "passingYards", "leaders": [
            {"athlete": {"id": "d", "displayName": "Sam Darnold"}}]}]},
        {"team": {"id": "13"}, "leaders": [{"name": "passingYards", "leaders": [
            {"athlete": {"id": "q", "displayName": "Raider QB"}}]}]}]},
    "s1": box("26", ("d", "Sam Darnold", "20/30")),
    "s2": box("26", ("k", "Drew Lock", "15/25")),
    "l1": box("13", ("q", "Raider QB", "22/31")),
    "l2": box("13", ("q", "Raider QB", "19/33")),
}
espn.summary = lambda eid, lg: SUMM[eid]
espn.team_stats = lambda tid, lg, season: {"miscellaneous.totalGiveaways": 4.0}
espn.odds_history = lambda eid, lg: {"items": [{
    "overUnder": 43.5,
    "homeTeamOdds": {"open": {"pointSpread": {"american": "+7"}},
                     "current": {"pointSpread": {"american": "+3"}}}}]}
espn.power_index = lambda tid, lg, season: None
event = {"league": "NFL", "event_id": "g", "kickoff": "2026-11-15T21:05",
         "rank": {},
         "home": {"id": "13", "abbr": "LV"}, "away": {"id": "26", "abbr": "SEA"}}
got = cli.study(event, inj)
assert got["dog"]["abbr"] == "LV" and got["fav"]["abbr"] == "SEA", got["dog"]
assert 0.38 < got["price"] < 0.45, got["price"]
assert got["when"] == "Sun 4:05pm", got["when"]
texts = [t for _, t in got["for"]]
assert any("SEA are on Drew Lock, not season leader Sam Darnold (new last week)"
           in t for t in texts), texts
assert any("listed: Sam Darnold Out" in t for t in texts), texts
assert any("line has moved 4 toward LV" in t for t in texts), texts
assert got["against"] == [], got["against"]
flat = cli.plain(got)
import json                                                   # noqa: E402
json.dumps(flat)                    # nothing unserialisable left in it
assert flat["fav"]["qb"]["now"] == "Drew Lock"

# No line, no underdog, no row.
espn.clear_cache()
espn.odds_history = lambda eid, lg: {"items": []}
assert cli.study(event, inj) is None
print("one game end to end: backup quarterback, injury note and line move OK")

# ── the app shows the newest page, without the table ──────────────────
import tempfile                                               # noqa: E402
d = tempfile.mkdtemp()
assert research.latest_page(d) == (None, "")
for wk in (9, 11, 10):
    with open(os.path.join(d, f"research_week{wk}.md"), "w") as fh:
        fh.write(research.render(wk, rows, "now", "the whole slate"))
wk, text = research.latest_page(d)
assert wk == 11 and text.startswith("# Week 11 research"), (wk, text[:40])
assert "### C over D" in text and "| game |" not in text
print("the newest page is found, 11 ahead of 9, and the table is left out OK")

print("\nALL RESEARCH TESTS PASS")
