"""The chaos ledger: what was flagged, at what price, and how it went.

The record only means something if it is kept the same way every week
and nothing can quietly rewrite it, so that is what this protects.

    python tests/test_chaos.py
"""
import importlib.util
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
from gridiron import chaos                                    # noqa: E402


def load(name):
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(HERE, "..", "scripts", name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tmp = tempfile.mkdtemp()
path = os.path.join(tmp, "chaos.tsv")

# ── flagging ──────────────────────────────────────────────────────────
rows = chaos.read(path)
assert rows == [], "no file yet is an empty ledger, not an error"
rows = chaos.add(rows, 2026, 10, "NEB", "ILL", "ILL", 0.3925, "form",
                 "won 3 straight,\tNEB lost 3\nstraight", "2026-11-04")
rows = chaos.add(rows, 2026, 10, "ORE", "OSU", "ORE", 0.3247, "quarterback",
                 "both starters out", "2026-11-04")
rows = chaos.add(rows, 2026, 10, "UGA", "MISS", "MISS", 0.4160, "situation",
                 "road night game after Florida", "2026-11-04")
chaos.write(rows, path)
back = chaos.read(path)
assert len(back) == 3, back
assert "\t" not in back[0]["reason"] and "\n" not in back[0]["reason"]
assert back[0]["reason"] == "won 3 straight, NEB lost 3 straight", back[0]
print("a candidate survives the file, and a reason cannot break a row OK")

# The same game flagged again replaces the row rather than doubling it.
again = chaos.add(back, 2026, 10, "NEB", "ILL", "ILL", 0.41, "form",
                  "a better reason", "2026-11-05")
assert len(again) == 3
assert chaos.for_game(again, 2026, 10, "NEB", "ILL")["price"] == "0.4100"
print("flagging a game twice keeps one row OK")

for bad in (dict(team="KC"), dict(kind="vibes"), dict(price=1.4)):
    kw = dict(team="ILL", kind="form", price=0.39)
    kw.update(bad)
    try:
        chaos.add([], 2026, 10, "NEB", "ILL", kw["team"], kw["price"],
                  kw["kind"], "x", "2026-11-04")
    except ValueError:
        continue
    raise AssertionError(f"accepted {bad}")
print("a team not in the game, an unknown kind and a bad price are refused OK")

# ── the phone message ─────────────────────────────────────────────────
title, body = chaos.text(back, 2026, 10)
assert title == "Week 10 chaos list: 3", title
assert "ILL over NEB (39%)" in body, body
assert "ORE over OSU (32%)" in body, body
assert "MISS over UGA (42%)" in body, body
assert chaos.text(back, 2026, 11) is None, "a week with nothing flagged is silent"
print("the list reads as one line a game, team over opponent OK")

# ── settling ──────────────────────────────────────────────────────────
winners = {("NEB", "ILL"): "ILL", ("ORE", "OSU"): "ORE"}
picks = {("NEB", "ILL"): "ILL", ("ORE", "OSU"): "OSU", ("UGA", "MISS"): "UGA"}
n = chaos.settle(back, 2026, 10, winners, picks)
assert n == 5, n          # two results, three taken-or-not
ill = chaos.for_game(back, 2026, 10, "NEB", "ILL")
ore = chaos.for_game(back, 2026, 10, "ORE", "OSU")
miss = chaos.for_game(back, 2026, 10, "UGA", "MISS")
assert (ill["result"], ill["taken"]) == ("W", "Y")
assert (ore["result"], ore["taken"]) == ("W", "N")
assert (miss["result"], miss["taken"]) == ("", "N"), "not finished, not graded"
assert chaos.settle(back, 2026, 10, winners, picks) == 0, "settling is once"
print("a result is filled once, and taken is recorded apart from it OK")

# The open list shrinks as games finish.
title, body = chaos.text(back, 2026, 10)
assert title.endswith(": 1") and "MISS" in body and "ILL" not in body, body

# A tie is a loss, as it is for every pick in this pool.
chaos.settle(back, 2026, 10, {("UGA", "MISS"): None})
assert miss["result"] == "L"
print("a tie is a loss for the candidate OK")

# ── the record ────────────────────────────────────────────────────────
s = chaos.summary(back)
assert (s["flagged"], s["hits"]) == (3, 2), s
assert abs(s["expected"] - (0.3925 + 0.3247 + 0.4160)) < 1e-6, s
assert (s["taken"], s["taken_hits"]) == (1, 1), s
assert s["kinds"] == {"form": (1, 1), "quarterback": (1, 1),
                      "situation": (0, 1)}, s["kinds"]
assert chaos.recap_line(back, 2026, 10) == \
    " Chaos list: 2 of 3 hit, you took 1."
assert chaos.recap_line(back, 2026, 11) == ""
print("the record counts hits against the price, by kind OK")

# ── the price comes from the recorded market, not from memory ─────────
cli = load("chaos")
op = os.path.join(tmp, "opinions.tsv")
with open(op, "w") as f:
    f.write("week\taway\thome\tsplash_home\tmarket_home\tfpi_home\n"
            "10\tNEB\tILL\t0.3900\t0.3925\t0.3549\n"
            "10\tAFA\tARMY\t0.6200\t0.5721\t0.5962\n"
            "10\tXX\tYY\t0.5000\t\t0.5000\n")
assert abs(cli.market_price(10, "NEB", "ILL", "ILL", op) - 0.3925) < 1e-9
assert abs(cli.market_price(10, "AFA", "ARMY", "AFA", op) - 0.4279) < 1e-9
assert cli.market_price(10, "XX", "YY", "XX", op) is None, "unpriced is None"
assert cli.market_price(11, "NEB", "ILL", "ILL", op) is None
print("the away side's price is one minus the home side's OK")

# ── opinions are kept, and a later run of a week replaces the earlier ─
so = load("second_opinion")
rec = os.path.join(tmp, "kept.tsv")
so.record(9, [["9", "A", "B", "0.5", "0.6", "0.7"]], rec)
so.record(10, [["10", "C", "D", "0.5", "0.6", "0.7"],
               ["10", "E", "F", "0.4", "0.3", "0.2"]], rec)
so.record(10, [["10", "C", "D", "0.5", "0.9", "0.7"]], rec)
lines = open(rec).read().splitlines()
assert lines[0].split("\t") == so.HEADER
assert len(lines) == 3, lines
assert lines[1].startswith("9\tA") and lines[2] == "10\tC\tD\t0.5\t0.9\t0.7"
print("a week's opinions are stored once, latest run winning OK")

print("\nALL CHAOS TESTS PASS")
