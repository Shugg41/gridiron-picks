#!/usr/bin/env python3
"""A full read of one week, run where ESPN can be reached.

The card the app shows is per-game: a pick, a confidence word, a line.
This asks the questions that only make sense across the whole week,
and that need the five weeks of real rival cards now in the database:

  * What is each game actually worth, in win probability and in how
    much of the pool will be on the other side?
  * Which games is the pool wrong about, as opposed to merely split?
  * Given 37 real rivals with known habits, what is the chance this
    card finishes first? Against the chance pure chalk does?

The field model is the part worth explaining. simulate.estimated_rivals
invents entries by drawing each pick independently from the predicted
crowd share, and says in its own docstring that it will understate how
alike the field is. There is no longer any need to guess: weeks 1-5
hold 5,087 real picks from 37 named rivals, and 75 of those games have
a recovered closing line. So each rival gets measured — how often do
they take the favourite, relative to the pool — and their week-6 card
is drawn from their own habit rather than from the average one. A
rival who has never left the chalk stays on it here.

Run via .github/workflows/data-probe.yml with scope=deepdive.
"""
import json
import math
import os
import sqlite3
import sys
import urllib.error
import urllib.request
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from gridiron import espn, model, simulate                     # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DB = os.path.join(ROOT, "football_picks.db")
LINES = os.path.join(ROOT, "data", "closing_lines.tsv")
CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues"
SEASON, WEEK = 2026, 6
TRIALS = 20000

_cache = {}


def get(url):
    if url in _cache:
        return _cache[url]
    req = urllib.request.Request(url, headers={"User-Agent": "gridiron-probe"})
    with urllib.request.urlopen(req, timeout=25) as r:
        _cache[url] = json.load(r)
    return _cache[url]


def abbr_of(ref):
    try:
        return get(ref).get("abbreviation")
    except Exception:
        return None


def events_for(league, week):
    out = []
    try:
        listing = get(f"{CORE}/{league}/seasons/{SEASON}/types/2/weeks/{week}/"
                      f"events?limit=200")
    except urllib.error.HTTPError as exc:
        print(f"# {league} week {week}: HTTP {exc.code}", file=sys.stderr)
        return out
    for item in listing.get("items", []):
        try:
            event = get(item["$ref"])
            comp = (event.get("competitions") or [])[0]
        except Exception:
            continue
        sides = {}
        for c in comp.get("competitors") or []:
            ref = (c.get("team") or {}).get("$ref")
            if ref:
                sides[c.get("homeAway")] = abbr_of(ref)
        if not sides.get("home") or not sides.get("away"):
            continue
        tag = "NFL" if league == "nfl" else "CFB"
        ev = {"away": {"abbr": sides["away"]}, "home": {"abbr": sides["home"]},
              "event_id": str(event.get("id")), "league": tag}
        try:
            odds = espn.odds_history(ev["event_id"], tag)
            details = ((odds.get("items") or [{}])[0]).get("details")
            named, value = espn._spread(details)
            if named and value is not None:
                ev["line"] = abs(value)
                ev["fav_abbr"] = named if value < 0 else (
                    sides["away"] if named == sides["home"] else sides["home"])
            pts, toward = espn.movement(odds, sides["home"], sides["away"])
            ev["move"], ev["move_toward"] = pts, toward
        except Exception:
            pass
        out.append(ev)
    return out


# ── how chalky is each rival, measured rather than assumed ────────────
def rival_offsets(conn):
    """{rival: logit offset} from their favourite-rate over priced games."""
    fav = {}
    for line in open(LINES):
        f = line.rstrip("\n").split("\t")
        if f[0] == "week" or len(f) < 6:
            continue
        fav[(int(f[0]), f[1], f[2])] = f[4]

    took = defaultdict(lambda: [0, 0])
    for r in conn.execute(
            "SELECT week, away_code, home_code, entrant, team FROM field_card "
            "WHERE season=?", (SEASON,)):
        key = (r[0], r[1], r[2])
        if key not in fav:
            continue
        took[r[3]][0] += 1
        took[r[3]][1] += (r[4] == fav[key])

    pool_n = sum(v[0] for v in took.values())
    pool_k = sum(v[1] for v in took.values())
    base = pool_k / pool_n

    def logit(p):
        p = min(max(p, 0.01), 0.99)
        return math.log(p / (1 - p))

    out = {}
    for name, (n, k) in took.items():
        if n < 20:
            continue
        # shrink toward the pool: 37 rivals x ~75 games is a lot in
        # total and not much each, so a rival who happened to go 70/70
        # is not certain to be a 100% chalk player.
        rate = (k + 8 * base) / (n + 8)
        out[name] = logit(rate) - logit(base)
    return out, base, pool_n


def habit_field(shares, offsets, seed=11):
    """Draw each real rival's card from their own measured chalkiness."""
    import random
    rng = random.Random(seed)
    field = {}
    for name, delta in offsets.items():
        card = {}
        for key, sides in shares.items():
            if len(sides) != 2:
                continue
            (a, pa), (b, _) = list(sides.items())
            # sides is {favourite: share, dog: share} from the curve;
            # shift that share by this rival's own offset
            p = 1 / (1 + math.exp(-(math.log(max(pa, .01) / max(1 - pa, .01))
                                    + delta)))
            card[key] = a if rng.random() < p else b
        field[name] = card
    return field


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    from gridiron import splash
    board = [splash.Game(away_code=r["away_code"], home_code=r["home_code"],
                         away=r["away"] or "", home=r["home"] or "",
                         kickoff=r["kickoff"] or "")
             for r in conn.execute(
                 "SELECT away_code, home_code, away, home, kickoff FROM game "
                 "WHERE season=? AND week=? ORDER BY kickoff", (SEASON, WEEK))]
    print(f"week {WEEK}: {len(board)} games on the board")

    pool = events_for("nfl", WEEK - 1) + events_for("college-football", WEEK)
    linked = espn.link(board, pool)
    priced = sum(1 for _g, ev in linked if ev and ev.get("line") is not None)
    print(f"linked {sum(1 for _g,ev in linked if ev)} of {len(board)}, "
          f"{priced} with a line\n")

    offsets, base, obs = rival_offsets(conn)
    print(f"rival habits measured on {obs} picks over priced games; "
          f"pool takes the favourite {base:.1%} of the time")
    ranked = sorted(offsets.items(), key=lambda kv: -kv[1])
    def rate(d):
        return 1 / (1 + math.exp(-(math.log(base / (1 - base)) + d)))
    print("  chalkiest:", ", ".join(f"{n.split('/')[0]} {rate(d):.0%}"
                                    for n, d in ranked[:4]))
    print("  loosest:  ", ", ".join(f"{n.split('/')[0]} {rate(d):.0%}"
                                    for n, d in ranked[-4:]))
    print()

    # ── per-game table ────────────────────────────────────────────────
    probs, shares, rows = {}, {}, []
    for g, ev in linked:
        key = (g.away_code, g.home_code)
        hp, ap = espn.win_probability(ev)
        if hp is None:
            continue
        sides = {}
        home_code, away_code = g.home_code, g.away_code
        sides[home_code], sides[away_code] = hp, ap
        probs[key] = sides
        line = (ev or {}).get("line")
        share_fav = model.expected_share(line)
        if share_fav is None:
            continue
        fav_code = home_code if hp >= ap else away_code
        dog_code = away_code if fav_code == home_code else home_code
        shares[key] = {fav_code: share_fav, dog_code: 1 - share_fav}
        rows.append({
            "key": key, "fav": fav_code, "dog": dog_code,
            "line": line, "p_fav": max(hp, ap), "share": share_fav,
            "move": (ev or {}).get("move"),
            "toward": (ev or {}).get("move_toward"),
            "kick": g.kickoff,
        })

    print(f"{'game':<13} {'fav':>5} {'line':>5} {'win%':>5} "
          f"{'pool%':>6} {'edge':>6}  note")
    for r in sorted(rows, key=lambda r: -(r["p_fav"] - r["share"])):
        edge = r["p_fav"] - r["share"]
        note = ""
        if edge > 0.04:
            note = "pool UNDER-backs a real favourite"
        elif edge < -0.12:
            note = "pool OVER-backs a shaky favourite"
        if r["move"] and r["move"] >= 2:
            note += f" | line moved {r['move']:g} to {r['toward']}"
        print(f"{r['key'][0]+'@'+r['key'][1]:<13} {r['fav']:>5} "
              f"{r['line']:>5g} {r['p_fav']:>5.0%} {r['share']:>6.0%} "
              f"{edge:>+6.0%}  {note}")

    # ── what the app proposed, versus chalk ───────────────────────────
    mine = {(r["away_code"], r["home_code"]): r["team"] for r in conn.execute(
        "SELECT away_code, home_code, team FROM proposal "
        "WHERE season=? AND week=?", (SEASON, WEEK))}
    mine = {k: v for k, v in mine.items() if k in probs}
    chalk = {k: max(v, key=v.get) for k, v in probs.items()}
    diff = [k for k in mine if chalk.get(k) and mine[k] != chalk[k]]

    field = habit_field(shares, offsets)
    print(f"\nfield: {len(field)} real rivals, cards drawn from their own "
          f"measured habits\n")

    for label, card in (("the app's card", mine), ("pure chalk", chalk)):
        o = simulate.simulate(card, probs, field, trials=TRIALS)
        print(f"  {label:<16} wins {o.win:>6.1%}  ties {o.tie:>5.1%}  "
              f"top3 {o.top3:>6.1%}  score {o.p10}/{o.p50}/{o.p90} "
              f"(mean {o.mean:.1f})")

    print(f"\nthe app departs from chalk on {len(diff)}: "
          + ", ".join(f"{a}@{h} -> {mine[(a,h)]}" for a, h in diff))
    conn.close()


if __name__ == "__main__":
    main()
