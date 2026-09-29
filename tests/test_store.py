"""The database, and the two-writer problem.

The sync tests matter most. The file lives in a GitHub repo and both the
running app and Claude write to it, so the two failure modes worth
proving are: an outside write becomes visible, and neither writer can
silently flatten the other.

    python tests/test_store.py
"""
import base64
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from gridiron import splash, store                             # noqa: E402

HERE = os.path.dirname(__file__)
MATRIX = open(os.path.join(HERE, "fixtures", "picks_by_week4.txt")).read()
STAND = open(os.path.join(HERE, "fixtures", "standings_week4.txt")).read()
ENTRY = open(os.path.join(HERE, "fixtures", "entry_week4.txt")).read()


def fresh():
    path = tempfile.mktemp(suffix=".db")
    return store.connect(path), path


# ── the board ───────────────────────────────────────────────────────────
conn, path = fresh()
e = splash.parse_entry(ENTRY)
assert store.save_games(conn, 2026, 4, e.games) == 21
rows = store.week_games(conn, 2026, 4)
assert len(rows) == 21

# re-pasting the same board updates rather than duplicating — identity is
# the two codes, not the row's position, so a reordered paste is harmless
assert store.save_games(conn, 2026, 4, e.games) == 21
assert len(store.week_games(conn, 2026, 4)) == 21
assert store.save_games(conn, 2026, 4, list(reversed(e.games))) == 21
assert len(store.week_games(conn, 2026, 4)) == 21
print("board saves and re-saves without duplicating OK")

# an ESPN id arriving on a later pass fills in without wiping anything
store.save_games(conn, 2026, 4, e.games[:1], links={0: {"event_id": "e99",
                                                        "date": "2026-09-25T23:00Z"}})
first = [g for g in store.week_games(conn, 2026, 4) if g["away_code"] == "ARMY"][0]
assert first["espn_id"] == "e99" and first["kickoff"] == "2026-09-25T23:00Z"
assert first["away"] == "Army", "the name must survive an enrichment pass"
store.save_games(conn, 2026, 4, e.games[:1])          # no link this time
again = [g for g in store.week_games(conn, 2026, 4) if g["away_code"] == "ARMY"][0]
assert again["espn_id"] == "e99", "a later pass must not blank the ESPN id"
print("enrichment fills in and is never blanked by a re-paste OK")

# ── a missing pick is stored as a missing pick ──────────────────────────
games, entries = splash.parse_picks_by_week(MATRIX)
mine = [x for x in entries if x.me][0]
rows = [{"away_code": a, "home_code": h,
         "team": mine.picks[i][0],
         "result": {"W": "W", "L": "L"}.get(mine.picks[i][1])}
        for i, (a, h) in enumerate(games)]
store.save_entry(conn, 2026, 4, rows)
ent = store.week_entry(conn, 2026, 4)
assert ent[("ATL", "GB")] == (None, None), ent[("ATL", "GB")]
assert ent[("UCLA", "MD")] == ("MD", "L"), ent[("UCLA", "MD")]
assert ent[("ARMY", "TEM")] == ("ARMY", "W")
missing = [k for k, (team, _r) in ent.items() if team is None]
assert missing == [("ATL", "GB")], missing
print("a missing pick is recorded as one, not left out OK")

# ── proposals stay apart from what was entered ──────────────────────────
store.save_proposals(conn, 2026, 4, [("UCLA", "MD", "UCLA", "line"),
                                     ("ATL", "GB", "GB", "line")])
prop = dict(conn.execute("SELECT away_code || '@' || home_code, team "
                         "FROM proposal WHERE season=2026 AND week=4"))
assert prop["UCLA@MD"] == "UCLA", prop
# the app said UCLA, the entry says MD — that difference is the whole
# point of keeping the two tables apart
assert ent[("UCLA", "MD")][0] == "MD"
print("proposal and entry are kept apart OK")

# ── the field, and the standings ────────────────────────────────────────
dist = splash.distribution_from_matrix(games, entries)
store.save_field(conn, 2026, 4, [
    (games[i][0], games[i][1], side[0], side[1], side[2], None)
    for i in range(len(games)) for side in dist[i]])
fld = store.week_field(conn, 2026, 4)
assert fld[("ATL", "GB")]["GB"] == 0.5, fld[("ATL", "GB")]   # 2 of 4 entries
srows, size = splash.parse_standings(STAND)
store.save_standings(conn, 2026, None, srows)
me_row = conn.execute("SELECT rank, points, tie_diff FROM standing "
                      "WHERE me=1").fetchone()
assert me_row == ("16", 63, 21), me_row
print("field and standings store OK")

# ── the upsert helper, and the NULL that broke it ──────────────────────
u = store.connect(":memory:")
u.executescript("CREATE TABLE t (a TEXT, b TEXT, v TEXT, PRIMARY KEY (a, b));")
assert store.upsert(u, "t", {"a": "1", "b": "x"}, {"v": "first"}) == 1
assert store.upsert(u, "t", {"a": "1", "b": "x"}, {"v": "second"}) == 0
assert u.execute("SELECT COUNT(*), v FROM t").fetchone() == (1, "second")

# a NULL key has to match, which "=" never does. Season-long standings
# are stored with no week, so with "=" the update always missed, the
# insert always ran, and because NULLs do not collide in a primary key
# the rows piled up silently on every paste.
assert store.upsert(u, "t", {"a": "2", "b": None}, {"v": "one"}) == 1
assert store.upsert(u, "t", {"a": "2", "b": None}, {"v": "two"}) == 0
rows = u.execute("SELECT COUNT(*) FROM t WHERE a='2'").fetchone()[0]
assert rows == 1, f"a NULL key duplicated the row {rows} times"

# `keep` protects an existing value from being blanked by a new NULL
store.upsert(u, "t", {"a": "3", "b": "y"}, {"v": "kept"})
store.upsert(u, "t", {"a": "3", "b": "y"}, {"v": None}, keep=("v",))
assert u.execute("SELECT v FROM t WHERE a='3'").fetchone()[0] == "kept"
store.upsert(u, "t", {"a": "3", "b": "y"}, {"v": None})
assert u.execute("SELECT v FROM t WHERE a='3'").fetchone()[0] is None
print("upsert helper OK, including NULL keys")

# and the real case it was hiding: standings pasted twice
srows2, _ = splash.parse_standings(STAND)
conn3, path3 = fresh()
store.save_standings(conn3, 2026, None, srows2)
store.save_standings(conn3, 2026, None, srows2)
n = conn3.execute("SELECT COUNT(*) FROM standing").fetchone()[0]
assert n == len(srows2), f"re-pasting standings duplicated: {n} rows"
me2 = conn3.execute("SELECT COUNT(*) FROM standing WHERE me=1").fetchone()[0]
assert me2 == 1, f"{me2} rows claim to be me"
print("standings can be pasted twice without duplicating OK")

# ── migrating the old tables ────────────────────────────────────────────
old, old_path = fresh()
old.executescript("""
CREATE TABLE slate (season INTEGER, week INTEGER, event_id TEXT, matchup TEXT);
CREATE TABLE picks (season INTEGER, week INTEGER, event_id TEXT, matchup TEXT,
                    pick_abbr TEXT, result TEXT);
INSERT INTO slate VALUES (2026,3,'401','UNC @ CLEM'),(2026,3,'402','BAL VS DAL'),
                         (2026,3,'403','no separator here');
INSERT INTO picks VALUES (2026,3,'401','UNC @ CLEM','CLEM','W'),
                         (2026,3,'402','BAL VS DAL','BAL','L');
""")
old.commit()
g, p = store.migrate_legacy(old)
assert (g, p) == (2, 2), (g, p)          # the unparseable row is skipped
got = store.week_games(old, 2026, 3)
assert {(x["away_code"], x["home_code"]) for x in got} == {("UNC", "CLEM"),
                                                           ("BAL", "DAL")}
assert store.week_entry(old, 2026, 3)[("UNC", "CLEM")] == ("CLEM", "W")
assert old.execute("SELECT COUNT(*) FROM slate").fetchone()[0] == 3, \
    "the old tables must survive the migration"

# a week Splash has already defined is left alone. The old tables spell
# teams ESPN's way, so merging the two sources does not overwrite — it
# duplicates, which is how week 4 came to hold 38 games in a 31-game
# week, seven of them second copies under a different spelling.
old.execute("DELETE FROM game")
old.execute("DELETE FROM entry")
store.save_games(old, 2026, 3, [splash.Game(away_code="UNC", home_code="CLEM")])
g2, p2 = store.migrate_legacy(old)
assert (g2, p2) == (0, 0), (g2, p2)
assert len(store.week_games(old, 2026, 3)) == 1, store.week_games(old, 2026, 3)
print("legacy migration OK, old tables untouched, Splash never overwritten")

# ── sync: the two-writer problem ────────────────────────────────────────
class FakeGitHub:
    """Stands in for the contents API, tracking sha like the real one."""

    def __init__(self, content=b"v1"):
        self.content, self.sha, self.puts = content, "sha1", 0

    def get(self, url, headers=None, timeout=None):
        return self._resp(200, {"sha": self.sha,
                                "content": base64.b64encode(self.content).decode()})

    def put(self, url, headers=None, json=None, timeout=None):
        self.puts += 1
        if json.get("sha") not in (self.sha, None):
            return self._resp(409, {"message": "does not match"})
        self.content = base64.b64decode(json["content"])
        self.sha = self.sha + "+"
        return self._resp(200, {"content": {"sha": self.sha}})

    @staticmethod
    def _resp(code, body):
        class R:
            status_code = code
            def json(self): return body
            text = ""
        return R()


conn2, path2 = fresh()
gh = FakeGitHub()
sync = store.Sync("owner/repo", "tok", db_path=path2)
store.requests = gh                       # swap the module's transport

assert sync.enabled
assert store.Sync("", "", db_path=path2).enabled is False

# an outside write moves the sha, and that is what makes it visible.
# The file is swapped wholesale, so the connection has to be reopened
# around it — open_synced does that, and the test proves the data from
# the remote actually lands.
other, other_path = fresh()
store.save_games(other, 2026, 9, [splash.Game(away_code="XXX", home_code="YYY")])
other.commit()
other.close()
gh.content = open(other_path, "rb").read()
gh.sha = "written-by-claude"

conn2.close()
conn2 = store.open_synced(path2, sync)
assert store.week_games(conn2, 2026, 9), "the outside write never arrived"
assert store.meta_get(conn2, "remote_sha") == "written-by-claude"
# and a second open with nothing new does not re-pull
assert sync.pull_if_changed("written-by-claude") is None
print("an outside write is pulled in and visible OK")

# pushing succeeds and records the new sha
assert sync.push(conn2, "test") is True, sync.reason
assert store.meta_get(conn2, "remote_sha") == gh.sha

# now the OTHER writer commits, moving the sha underneath us
gh.sha = "somebody-else"
before = gh.content
assert sync.push(conn2, "test") is False, "this push should have been refused"
assert "pull first" in (sync.reason or ""), sync.reason
assert gh.content == before, "the other writer's content was overwritten"
print("a push that would flatten the other writer is refused OK")

# after re-pulling, pushing works again
conn2.close()
conn2 = store.open_synced(path2, sync)
assert sync.push(conn2, "test") is True, sync.reason
print("re-pull then push OK")

# failures report GitHub's own words rather than a shrug
class Broken(FakeGitHub):
    def get(self, url, headers=None, timeout=None):
        return self._resp(401, {"message": "Bad credentials"})


store.requests = Broken()
bad = store.Sync("owner/repo", "nope", db_path=path2)
assert bad.remote() == (None, None)
assert bad.reason == "401 Bad credentials", bad.reason
print("a rejected token says why OK")

for p in (path, path2, old_path, other_path, path3):
    if os.path.exists(p):
        os.unlink(p)
print("\nALL STORE TESTS PASS")
