#!/usr/bin/env python3
"""Keep, send and read the chaos ledger.

    python scripts/chaos.py add 11 NEB ILL ILL form "won 3 straight, NEB lost 3"
    python scripts/chaos.py add 11 NEB ILL ILL form "..." --price 0.39
    python scripts/chaos.py text            # the open list, to the phone
    python scripts/chaos.py settle [WEEK]   # grade from the database
    python scripts/chaos.py report          # the record so far

`add` takes the price from data/opinions.tsv when the week has been
priced, so the number in the ledger is the market's and not one typed
from memory. Pass --price only when the board has not been priced yet.

`text` sends through ntfy, so it only does anything where NTFY_TOPIC
exists — which is GitHub Actions, via .github/workflows/text.yml. With
NOTE_BODY set it sends that instead of the list, which is how a
Saturday-morning change reaches the phone without a second workflow.

Results are normally settled by the results watch as games finish.
`settle` is the same thing by hand, from scores already in the
database, for a week the watch never saw.
"""
import csv
import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
from gridiron import chaos, store                             # noqa: E402
import notify                                                 # noqa: E402

SEASON = 2026
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DB = os.path.join(ROOT, "football_picks.db")
OPINIONS = os.path.join(ROOT, "data", "opinions.tsv")


def market_price(week, away, home, team, path=None):
    """The market's probability for `team`, from the recorded opinions."""
    try:
        with open(path or OPINIONS, newline="") as f:
            for r in csv.DictReader(f, delimiter="\t"):
                if (r["week"] == str(week) and r["away"] == away
                        and r["home"] == home and r["market_home"]):
                    p = float(r["market_home"])
                    return p if team == home else 1 - p
    except FileNotFoundError:
        pass
    return None


def current_week(conn):
    return conn.execute("SELECT MAX(week) FROM game WHERE season=?",
                        (SEASON,)).fetchone()[0]


def cmd_add(args):
    price = None
    if "--price" in args:
        i = args.index("--price")
        price = float(args[i + 1])
        args = args[:i] + args[i + 2:]
    if len(args) != 6:
        sys.exit("usage: chaos.py add WEEK AWAY HOME TEAM KIND REASON "
                 "[--price P]")
    week, away, home, team, kind, reason = args
    if price is None:
        price = market_price(week, away, home, team)
    if price is None:
        sys.exit(f"no market price recorded for week {week} {away}@{home}; "
                 f"price the board first or pass --price")
    rows = chaos.add(chaos.read(), SEASON, int(week), away, home, team,
                     price, kind, reason,
                     datetime.date.today().isoformat())
    chaos.write(rows)
    print(f"flagged {team} in {away}@{home} at {price:.0%} ({kind})")


def cmd_text(args):
    body = os.environ.get("NOTE_BODY", "").strip()
    if body:
        notify.send(os.environ.get("NOTE_TITLE", "").strip()
                    or "Gridiron Picks", body)
        return
    conn = store.connect(DB)
    week = int(args[0]) if args else current_week(conn)
    msg = chaos.text(chaos.read(), SEASON, week)
    if not msg:
        print(f"week {week}: no open candidates, nothing sent")
        return
    notify.send(msg[0], msg[1], tags="tornado,football")


def cmd_settle(args):
    conn = store.connect(DB)
    week = int(args[0]) if args else current_week(conn)
    winners = {}
    for a, h, x, y in conn.execute(
            "SELECT away_code, home_code, away_score, home_score FROM game "
            "WHERE season=? AND week=?", (SEASON, week)):
        if x is None or y is None:
            continue
        winners[(a, h)] = None if x == y else (a if x > y else h)
    picks = {(a, h): t for a, h, t in conn.execute(
        "SELECT away_code, home_code, team FROM entry "
        "WHERE season=? AND week=? AND team IS NOT NULL", (SEASON, week))}
    rows = chaos.read()
    n = chaos.settle(rows, SEASON, week, winners, picks)
    if n:
        chaos.write(rows)
    print(f"week {week}: {n} cell(s) settled")


def cmd_report(args):
    rows = chaos.read()
    s = chaos.summary(rows)
    if not s["flagged"]:
        print("nothing settled yet")
        return
    print(f"flagged {s['flagged']}, hit {s['hits']}, "
          f"expected at the price {s['expected']:.1f}")
    print(f"taken {s['taken']}, of which hit {s['taken_hits']}")
    for kind, (hit, n) in s["kinds"].items():
        print(f"  {kind:12} {hit} of {n}")
    open_ = [r for r in rows if not r.get("result")]
    if open_:
        print(f"{len(open_)} still open")


def main():
    cmds = {"add": cmd_add, "text": cmd_text, "settle": cmd_settle,
            "report": cmd_report}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        sys.exit("usage: chaos.py add|text|settle|report")
    cmds[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    main()
