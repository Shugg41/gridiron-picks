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
    # A game that has been played is not a 74% chance of anything. The
    # first version of this re-randomised finished games, so on a
    # Saturday morning it was still rolling dice for Thursday night —
    # Dallas had already lost and the simulation kept giving them 74%.
    # A decided game gets probability 1 on the team that actually won,
    # which keeps it in every card's score where it belongs.
    done = {}
    for a, h, asc, hsc in conn.execute(
            "SELECT away_code, home_code, away_score, home_score FROM game "
            "WHERE season=? AND week=? AND away_score IS NOT NULL",
            (SEASON, WEEK)):
        done[(a, h)] = a if asc > hsc else h
    if done:
        print(f"{len(done)} game(s) already final: "
              + ", ".join(f"{a}@{h} won by {t}"
                          for (a, h), t in done.items()))

    # chalk must stay the team the market favoured, never the team that
    # turned out to win. Deriving it from the probabilities broke the
    # moment decided games were given probability 1: "chalk" silently
    # became perfect hindsight on every finished game, and the chalk
    # card's chance of winning the week leapt from 0% to 49%. It also
    # listed Dallas and Washington — two favourites the entry backed
    # and lost with — as departures from chalk.
    probs, shares, rows, chalk = {}, {}, [], {}
    for g, ev in linked:
        key = (g.away_code, g.home_code)
        hp, ap = espn.win_probability(ev)
        if hp is not None:
            chalk[key] = g.home_code if hp >= ap else g.away_code
        if key in done:
            won = done[key]
            other = g.away_code if won == g.home_code else g.home_code
            probs[key] = {won: 1.0, other: 0.0}
            chalk.setdefault(key, won)      # no line: nothing better to say
            continue
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

    # win% and pool% are different quantities and their difference is
    # not an edge. A straight-up pool backs favourites about 87% of the
    # time while favourites win about 70%, so win% minus pool% is
    # negative on nearly every game by construction — an earlier
    # version of this script printed exactly that and called the
    # biggest gaps "the pool over-backs a shaky favourite", which only
    # ever meant "this is a large favourite". The honest per-game
    # reading is the two numbers side by side: how likely the favourite
    # is, and how much of the field will be on it. Whether departing
    # pays is a question about the whole card, and is answered by
    # simulation below rather than by arithmetic here.
    print(f"{'game':<13} {'fav':>5} {'line':>5} {'win%':>5} {'pool%':>6}"
          f"  line move")
    for r in sorted(rows, key=lambda r: r["line"]):
        move = (f"moved {r['move']:g} to {r['toward']}"
                if r["move"] and r["move"] >= 2 else "")
        print(f"{r['key'][0]+'@'+r['key'][1]:<13} {r['fav']:>5} "
              f"{r['line']:>5g} {r['p_fav']:>5.0%} {r['share']:>6.0%}"
              f"  {move}")

    # ── what the app proposed, versus chalk ───────────────────────────
    # What was actually entered beats what the app suggested: the two
    # differ every week, and simulating the suggestion answers a
    # question nobody asked.
    mine = {(r["away_code"], r["home_code"]): r["team"] for r in conn.execute(
        "SELECT away_code, home_code, team FROM entry "
        "WHERE season=? AND week=? AND team IS NOT NULL", (SEASON, WEEK))}
    source = "entered"
    if not mine:
        mine = {(r["away_code"], r["home_code"]): r["team"]
                for r in conn.execute(
                    "SELECT away_code, home_code, team FROM proposal "
                    "WHERE season=? AND week=?", (SEASON, WEEK))}
        source = "proposed (no entry recorded)"
    mine = {k: v for k, v in mine.items() if k in probs}
    print(f"\nmy card: {len(mine)} priced games, {source}")
    chalk = {k: v for k, v in chalk.items() if k in probs}
    # Only undecided games are a live choice; a flip on a game that has
    # finished is a result, not a decision.
    diff = [k for k in mine
            if k not in done and chalk.get(k) and mine[k] != chalk[k]]

    field = habit_field(shares, offsets)
    print(f"\nfield: {len(field)} real rivals, cards drawn from their own "
          f"measured habits\n")

    for label, card in (("your card", mine), ("pure chalk", chalk)):
        o = simulate.simulate(card, probs, field, trials=TRIALS)
        print(f"  {label:<16} wins {o.win:>6.1%}  ties {o.tie:>5.1%}  "
              f"top3 {o.top3:>6.1%}  score {o.p10}/{o.p50}/{o.p90} "
              f"(mean {o.mean:.1f})")

    print(f"\nyour card departs from chalk on {len(diff)}: "
          + ", ".join(f"{a}@{h} -> {mine[(a,h)]}" for a, h in diff))

    # And what each departure is worth on its own: the same card with
    # that one game put back on the favourite.
    if diff:
        print("\nvalue of each flip, measured by taking it back out:")
        full = simulate.simulate(mine, probs, field, trials=TRIALS)
        for k in diff:
            without = dict(mine)
            without[k] = chalk[k]
            o = simulate.simulate(without, probs, field, trials=TRIALS)
            print(f"  {k[0]}@{k[1]:<6} keep {mine[k]:<5} "
                  f"wins {full.win:.1%}/top3 {full.top3:.1%}   "
                  f"revert to {chalk[k]:<5} "
                  f"wins {o.win:.1%}/top3 {o.top3:.1%}   "
                  f"delta {full.win - o.win:+.1%} / "
                  f"{full.top3 - o.top3:+.1%}")

    print(f"\nNOTE: {len(probs)} of {len(board)} games carry a price this "
          f"far out, so every score above is out of {len(probs)}, not "
          f"{len(board)}. The comparison between cards is sound; the "
          f"absolute win and tie rates are not, because a short week "
          f"produces far more ties than a full one.")
    conn.close()


if __name__ == "__main__":
    main()
