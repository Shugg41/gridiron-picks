"""The chaos ledger: every underdog flagged, what it cost, how it went.

Week 10 flagged six underdogs and five of them won. That is either
scouting or a good Saturday, and one week cannot tell the two apart.
The only thing that can is a record kept the same way every week:
what was flagged, the price it was flagged at, why, whether it was
taken, and whether it won.

Until now none of that was kept. The candidates lived in a free-text
note on the proposal row and the prices were printed to a CI log and
thrown away. So this is a plain text file, one candidate per line —
a text file for the same reason announced.txt is one: two writers on
a binary database is how a week gets lost, and a collision here is a
one-line merge.

`price` is the market's probability for the flagged team when it was
flagged, which is what makes the record mean something. Five wins out
of six at an average price of 39% is 2.4 expected; that comparison,
over a couple of dozen candidates, is the whole point.

`kind` is the type of reason, so that in a month it is possible to
say which kinds of reason actually land.
"""
import csv
import os

FIELDS = ["season", "week", "away", "home", "team", "price", "kind",
          "reason", "flagged", "taken", "result"]
KINDS = ("quarterback", "form", "style", "situation", "injury",
         "coaching", "line")
PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                    "data", "chaos.tsv")


def _clean(text):
    """One line, no tabs: this is a cell in a tab-separated file."""
    return " ".join(str(text or "").split())


def read(path=None):
    try:
        with open(path or PATH, newline="") as f:
            return [dict(r) for r in csv.DictReader(f, delimiter="\t")]
    except FileNotFoundError:
        return []


def write(rows, path=None):
    path = path or PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rows = sorted(rows, key=lambda r: (int(r["season"]), int(r["week"]),
                                       r["away"], r["home"]))
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, FIELDS, delimiter="\t", lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: _clean(r.get(k)) for k in FIELDS})


def _same(row, season, week, away, home):
    return (int(row["season"]) == int(season) and int(row["week"]) == int(week)
            and row["away"] == away and row["home"] == home)


def week_rows(rows, season, week):
    return [r for r in rows
            if int(r["season"]) == int(season) and int(r["week"]) == int(week)]


def add(rows, season, week, away, home, team, price, kind, reason, flagged):
    """Flag one underdog. A game holds one candidate, so flagging it
    again replaces the reason and the price rather than adding a row."""
    if team not in (away, home):
        raise ValueError(f"{team} is not playing in {away}@{home}")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    price = float(price)
    if not 0 < price < 1:
        raise ValueError("price is a probability between 0 and 1")
    kept = [r for r in rows if not _same(r, season, week, away, home)]
    kept.append({"season": season, "week": week, "away": away, "home": home,
                 "team": team, "price": f"{price:.4f}", "kind": kind,
                 "reason": _clean(reason), "flagged": flagged,
                 "taken": "", "result": ""})
    return kept


def settle(rows, season, week, winners, picks=None):
    """Fill in how each of the week's candidates went.

    `winners` maps (away, home) to the winning code, or None for a tie.
    A tie is a loss, as it is for every pick in this pool. `picks` is
    the entry, when it is known, so the record can say whether the
    candidate was actually taken — a list that hits five times and is
    used once has a delivery problem, not a scouting one.

    Returns how many rows changed, so the caller knows whether to save.
    """
    changed = 0
    for r in week_rows(rows, season, week):
        key = (r["away"], r["home"])
        if key in winners and not r.get("result"):
            r["result"] = "W" if winners[key] == r["team"] else "L"
            changed += 1
        if picks and key in picks and not r.get("taken"):
            r["taken"] = "Y" if picks[key] == r["team"] else "N"
            changed += 1
    return changed


def summary(rows):
    """The record so far, over settled candidates only."""
    done = [r for r in rows if r.get("result") in ("W", "L")]
    hits = [r for r in done if r["result"] == "W"]
    taken = [r for r in done if r.get("taken") == "Y"]
    kinds = {}
    for r in done:
        k = kinds.setdefault(r["kind"], [0, 0])
        k[0] += r["result"] == "W"
        k[1] += 1
    return {"flagged": len(done), "hits": len(hits),
            "expected": sum(float(r["price"]) for r in done),
            "taken": len(taken),
            "taken_hits": sum(r["result"] == "W" for r in taken),
            "kinds": {k: tuple(v) for k, v in sorted(kinds.items())}}


def for_game(rows, season, week, away, home):
    for r in rows:
        if _same(r, season, week, away, home):
            return r
    return None


def opponent(row):
    return row["home"] if row["team"] == row["away"] else row["away"]


def text(rows, season, week):
    """The week's open candidates as a phone message, or None.

    One line each: who over whom, the price, the reason. This is the
    form the list has to arrive in — week 10's went out as a long post
    in a chat, it was not read before the card was filled in, and four
    winners went unused.
    """
    live = [r for r in week_rows(rows, season, week) if not r.get("result")]
    if not live:
        return None
    lines = [f"{r['team']} over {opponent(r)} ({float(r['price']):.0%}): "
             f"{r['reason']}" for r in live]
    return (f"Week {week} chaos list: {len(live)}",
            "\n".join(lines) + "\nYour call which to take.")


def recap_line(rows, season, week):
    """One sentence for the weekly recap, or '' with nothing settled."""
    done = [r for r in week_rows(rows, season, week)
            if r.get("result") in ("W", "L")]
    if not done:
        return ""
    hits = sum(r["result"] == "W" for r in done)
    took = sum(r.get("taken") == "Y" for r in done)
    known = any(r.get("taken") for r in done)
    line = f" Chaos list: {hits} of {len(done)} hit"
    return line + (f", you took {took}." if known else ".")
