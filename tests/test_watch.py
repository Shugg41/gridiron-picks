"""Noticing when a picked game changes before it locks.

The bar for a push notification is high: it fires at seven in the
morning and a false one teaches you to ignore the real one. So the tests
are mostly about what must NOT be reported.

    python tests/test_watch.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from gridiron import espn, store, watch                        # noqa: E402


def ev(away, home, details=None):
    def team(c):
        return {"id": c, "abbreviation": c, "shortDisplayName": c,
                "displayName": c, "location": c}
    odds = {"details": details} if details else {}
    return espn.parse_event({
        "id": away + home, "date": "2026-10-03T17:00Z",
        "status": {"type": {"completed": False, "shortDetail": ""}},
        "competitions": [{"competitors": [
            dict(homeAway="home", score=None, team=team(home)),
            dict(homeAway="away", score=None, team=team(away))],
            "odds": [odds] if odds else []}]}, "NFL")


def summary(counts):
    return {"injuries": [{"injuries": [{}] * n} for n in counts]}


# ── a snapshot is the line, the favorite, and the injury count ─────────
snap = watch.snapshot(ev("MIA", "BUF", "BUF -3"), summary([2, 1]))
assert snap == {"line": 3.0, "fav": "BUF", "injuries": 3}, snap
assert watch.snapshot(None) is None
# no summary fetched means injuries are unknown, not zero — the
# difference matters, because unknown must never look like "improved"
assert watch.snapshot(ev("MIA", "BUF", "BUF -3"))["injuries"] is None
print("snapshot OK")

# ── nothing changed, nothing said ──────────────────────────────────────
same = watch.snapshot(ev("MIA", "BUF", "BUF -3"), summary([2]))
assert watch.compare(same, same, "MIA", "BUF") == []
assert watch.compare(None, same, "MIA", "BUF") == []
assert watch.compare(same, None, "MIA", "BUF") == []
print("an unchanged game is silent OK")

# ── small drift is noise, not a notification ───────────────────────────
before = watch.snapshot(ev("MIA", "BUF", "BUF -3"), summary([2]))
half = watch.snapshot(ev("MIA", "BUF", "BUF -3.5"), summary([2]))
assert watch.compare(before, half, "MIA", "BUF") == [], \
    "half a point should not wake anyone up"
print("sub-threshold drift is silent OK")

# ── a real move is reported, with the numbers ──────────────────────────
moved = watch.snapshot(ev("MIA", "BUF", "BUF -6"), summary([2]))
out = watch.compare(before, moved, "MIA", "BUF")
assert len(out) == 1 and out[0].kind == "line", out
assert "3 toward BUF" in out[0].detail, out[0].detail
assert "(3 to 6)" in out[0].detail, out[0].detail
print("a real line move is reported:", out[0])

shrunk = watch.snapshot(ev("MIA", "BUF", "BUF -1"), summary([2]))
out = watch.compare(before, shrunk, "MIA", "BUF")
assert "away from BUF" in out[0].detail, out[0].detail
print("a move the other way says so:", out[0])

# ── the favorite flipping is the strongest version, said differently ───
flipped = watch.snapshot(ev("MIA", "BUF", "MIA -2"), summary([2]))
out = watch.compare(before, flipped, "MIA", "BUF")
assert len(out) == 1 and "favorite flipped from BUF to MIA" in out[0].detail, out
print("a flipped favorite is called out:", out[0])

# ── injuries: more is news, fewer is not ───────────────────────────────
worse = watch.snapshot(ev("MIA", "BUF", "BUF -3"), summary([2, 2]))
out = watch.compare(before, worse, "MIA", "BUF")
assert len(out) == 1 and out[0].kind == "injury", out
assert "2 more players" in out[0].detail, out[0].detail

better = watch.snapshot(ev("MIA", "BUF", "BUF -3"), summary([1]))
assert watch.compare(before, better, "MIA", "BUF") == [], \
    "players coming OFF the report is not something to push about"

unknown = watch.snapshot(ev("MIA", "BUF", "BUF -3"))
assert watch.compare(before, unknown, "MIA", "BUF") == [], \
    "an unfetched summary must not read as an injury change"
assert watch.compare(unknown, before, "MIA", "BUF") == []
print("injury changes OK")

# ── both at once ───────────────────────────────────────────────────────
both = watch.snapshot(ev("MIA", "BUF", "BUF -6"), summary([2, 2]))
out = watch.compare(before, both, "MIA", "BUF")
assert len(out) == 2 and {c.kind for c in out} == {"line", "injury"}, out
print("a game that moved and got hurt reports both OK")

# ── it survives a round trip through the database ──────────────────────
conn = store.connect(":memory:")
watch.record(conn, 2026, 5, "MIA", "BUF", before, when="2026-10-01T12:00")
watch.record(conn, 2026, 5, "NYJ", "NE", None)          # nothing to store
kept = watch.previous(conn, 2026, 5)
assert set(kept) == {("MIA", "BUF")}, kept
assert kept[("MIA", "BUF")]["line"] == 3.0
assert watch.compare(kept[("MIA", "BUF")], moved, "MIA", "BUF")[0].kind == "line"

# re-recording updates rather than duplicating
watch.record(conn, 2026, 5, "MIA", "BUF", moved, when="2026-10-02T12:00")
kept = watch.previous(conn, 2026, 5)
assert len(kept) == 1 and kept[("MIA", "BUF")]["line"] == 6.0, kept
assert watch.compare(kept[("MIA", "BUF")], moved, "MIA", "BUF") == [], \
    "once recorded, the same state must stop being news"
print("snapshots persist and update OK")

print("\nALL WATCH TESTS PASS")
