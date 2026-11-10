"""Research on every game, from data rather than from search results.

The chaos list used to be built by reading a price table and then
searching the web for whatever looked interesting. That found five
winners in week 10, and it also put the wrong team favourite in one
game, surfaced a year-old concussion as news, and left half the board
unread. Search summaries are the weak link; ESPN's own records are not.

So this asks ESPN for the things that actually move a game and reads
them the same way for every game on the slate:

    who is playing    the passer in each side's last two games against
                      the season's leading passer, and in the NFL the
                      injury list with ESPN's dated note
    form              record, streak, the last three margins
    the spot          rest, a bye, a run of road games, a ranked win
                      just behind or a ranked opponent just ahead
    the game's shape  the total, option teams, how much each side
                      gives the ball away
    the market        how the line has moved, and whether FPI agrees

Each of those becomes a plain-language reason FOR the underdog or
AGAINST it. Nothing here estimates a probability or claims an edge:
the output is a reading list with the reasons already attached, and a
person chooses from it.

Everything in this file is a pure function of payloads already
fetched, so it is tested against shapes copied from a real probe run
(scripts/probe_research.py) rather than against the network.
"""
import datetime

# A side priced outside this band is not a chaos candidate: above it
# the game is a coin flip and a deviation buys nothing, below it the
# underdog is a lottery ticket.
BAND = (0.22, 0.47)
OPTION_TEAMS = {"ARMY", "NAVY", "AFA"}
LOW_TOTAL = {"CFB": 41.5, "NFL": 38.5}
# An "opening" line can be a summer look-ahead number. A move bigger
# than this is far more likely to be that than money this week.
STALE_MOVE = 7.0
UNRANKED = 99


def _when(text):
    try:
        return datetime.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _score(value):
    if isinstance(value, dict):
        value = value.get("value", value.get("displayValue"))
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ── a team's season, from its schedule ─────────────────────────────────
def parse_schedule(payload, team_id):
    """Every game on a team's schedule, oldest first, from its own side."""
    out = []
    for ev in (payload or {}).get("events") or []:
        comp = (ev.get("competitions") or [{}])[0]
        mine = theirs = None
        for c in comp.get("competitors") or []:
            if str((c.get("team") or {}).get("id")) == str(team_id):
                mine = c
            else:
                theirs = c
        when = _when(ev.get("date"))
        if not mine or not theirs or not when:
            continue
        status = ((comp.get("status") or {}).get("type") or {})
        pf, pa = _score(mine.get("score")), _score(theirs.get("score"))
        done = bool(status.get("completed")) and pf is not None and pa is not None
        rank = ((theirs.get("curatedRank") or {}).get("current")) or UNRANKED
        out.append({
            "event_id": str(ev.get("id")), "when": when, "done": done,
            "home": mine.get("homeAway") == "home",
            "opp": (theirs.get("team") or {}).get("abbreviation") or "?",
            "opp_rank": rank if rank < UNRANKED else None,
            "pf": pf if done else None, "pa": pa if done else None,
            "won": (pf > pa) if done else None,
        })
    out.sort(key=lambda g: g["when"])
    return out


def form(games, kickoff):
    """What a team brings into a game kicking off at `kickoff`."""
    played = [g for g in games if g["done"] and g["when"] < kickoff]
    ahead = [g for g in games if g["when"] > kickoff + datetime.timedelta(hours=12)]
    wins = sum(g["won"] for g in played)
    streak = 0
    for g in reversed(played):
        if streak == 0:
            streak = 1 if g["won"] else -1
        elif (streak > 0) == g["won"]:
            streak += 1 if g["won"] else -1
        else:
            break
    last = played[-1] if played else None
    # Rest is measured from the last game on the schedule, finished or
    # not. Measured from the last RESULT, a team playing on Monday night
    # looked like it was coming off a bye until that game went final.
    before = [g for g in games if g["when"] < kickoff]
    prior = before[-1] if before else None
    recent = played[-3:]
    road = 0
    for g in reversed(played):
        if g["home"]:
            break
        road += 1
    return {
        "wins": wins, "losses": len(played) - wins, "streak": streak,
        "last": last,
        "rest": (kickoff - prior["when"]).days if prior else None,
        "margin3": (sum(g["pf"] - g["pa"] for g in recent) / len(recent)
                    if recent else None),
        "road_run": road,
        "next": ahead[0] if ahead else None,
        "last_ids": [g["event_id"] for g in played[-2:]],
    }


# ── who is actually playing quarterback ────────────────────────────────
def passers(summary, team_id):
    """Who threw for a team in a finished game, most attempts first."""
    out = []
    for side in ((summary or {}).get("boxscore") or {}).get("players") or []:
        if str((side.get("team") or {}).get("id")) != str(team_id):
            continue
        for stat in side.get("statistics") or []:
            if stat.get("name") != "passing":
                continue
            for a in stat.get("athletes") or []:
                try:
                    att = int(str((a.get("stats") or ["0/0"])[0]).split("/")[1])
                except (IndexError, ValueError):
                    att = 0
                who = a.get("athlete") or {}
                out.append({"id": str(who.get("id")),
                            "name": who.get("displayName") or "?",
                            "att": att})
    out.sort(key=lambda p: -p["att"])
    return out


def season_passer(summary, team_id):
    """The season's leading passer, from the summary of an unplayed game."""
    for side in (summary or {}).get("leaders") or []:
        if str((side.get("team") or {}).get("id")) != str(team_id):
            continue
        for cat in side.get("leaders") or []:
            if cat.get("name") == "passingYards":
                top = (cat.get("leaders") or [{}])[0]
                who = top.get("athlete") or {}
                if who.get("id"):
                    return {"id": str(who["id"]),
                            "name": who.get("displayName") or "?"}
    return None


def quarterback(leader, last_boxes):
    """Who has been under centre, against who led the season.

    `last_boxes` is the passer lists of the last two games, most recent
    first. Returns None when nothing has changed or nothing is known.
    A change that has stood for two games is old news and the price
    knows it; one that happened last week may not be fully in yet, so
    the two are worded differently.
    """
    if not leader or not last_boxes or not last_boxes[0]:
        return None
    now = last_boxes[0][0]
    if now["id"] == leader["id"] or now["att"] < 8:
        return None
    # If the season's leader threw a pass in that game he played, and
    # the other man out-throwing him is a blowout, not a change: Wake
    # Forest won 77-0 and the backup had most of the attempts.
    if any(p["id"] == leader["id"] for p in last_boxes[0]):
        return None
    before = last_boxes[1][0] if len(last_boxes) > 1 and last_boxes[1] else None
    settled = bool(before and before["id"] == now["id"])
    return {"now": now["name"], "leader": leader["name"], "settled": settled}


def nfl_injuries(payload):
    """The league injury list as {team_id: [player, ...]}."""
    out = {}
    for group in (payload or {}).get("injuries") or []:
        rows = []
        for i in group.get("injuries") or []:
            who = i.get("athlete") or {}
            rows.append({
                "name": who.get("displayName") or "?",
                "pos": (who.get("position") or {}).get("abbreviation") or "",
                "status": i.get("status") or "",
                "date": str(i.get("date") or "")[:10],
                "note": " ".join(str(i.get("shortComment") or "").split()),
            })
        out[str(group.get("id"))] = rows
    return out


def qb_report(injuries, names):
    """Injury-list entries for the quarterbacks that matter to a team."""
    wanted = {n for n in names if n}
    return [r for r in injuries or []
            if r["pos"] == "QB" and r["name"] in wanted
            and r["status"].lower() != "active"]


# ── reasons ────────────────────────────────────────────────────────────
def _streak_text(n):
    if abs(n) == 1:
        return "won last time out" if n > 0 else "lost last time out"
    return f"won {n} straight" if n > 0 else f"lost {-n} straight"


def reasons(ctx):
    """Reasons for and against the underdog in one game.

    `ctx` has league, total, moved, toward, market (dog), fpi (dog), and
    `dog` / `fav` dicts each holding abbr, form, qb, qb_inj, giveaways,
    rush. Returns (for_, against), lists of (kind, text). The kinds are
    the ledger's, so a reason can be carried straight into it.
    """
    dog, fav = ctx["dog"], ctx["fav"]
    f, a = [], []

    # quarterback
    # One reason per side however many facts feed it: a starter ruled
    # out, his backup questionable and a change at quarterback are one
    # piece of news, not three.
    for side, bucket in ((fav, f), (dog, a)):
        q = side.get("qb")
        listed = ", ".join(f"{r['name']} {r['status']} ({r['date']})"
                           for r in side.get("qb_inj") or [])
        if q:
            age = ("at least two games running" if q["settled"]
                   else "new last week")
            text = (f"{side['abbr']} are on {q['now']}, not season leader "
                    f"{q['leader']} ({age})")
            bucket.append(("quarterback",
                           text + (f"; listed: {listed}" if listed else "")))
        elif listed:
            bucket.append(("injury", f"{side['abbr']} QB listed: {listed}"))

    # form
    ds, fs = dog["form"]["streak"], fav["form"]["streak"]
    if ds >= 3:
        f.append(("form", f"{dog['abbr']} have {_streak_text(ds)}"))
    if fs <= -2:
        f.append(("form", f"{fav['abbr']} have {_streak_text(fs)}"))
    if ds <= -3:
        a.append(("form", f"{dog['abbr']} have {_streak_text(ds)}"))
    if fs >= 4:
        a.append(("form", f"{fav['abbr']} have {_streak_text(fs)}"))
    dm, fm = dog["form"]["margin3"], fav["form"]["margin3"]
    if dm is not None and fm is not None and dm - fm >= 7:
        f.append(("form", f"last three games: {dog['abbr']} {dm:+.0f} a "
                          f"game, {fav['abbr']} {fm:+.0f}"))

    # the spot
    dr, fr = dog["form"]["rest"], fav["form"]["rest"]
    if dr is not None and fr is not None:
        if fr <= 5 and dr - fr >= 2:
            f.append(("situation", f"{fav['abbr']} on {fr} days' rest, "
                                   f"{dog['abbr']} on {dr}"))
        if dr >= 13 and fr < 13:
            f.append(("situation", f"{dog['abbr']} are off a bye"))
        if dr <= 5 and fr - dr >= 2:
            a.append(("situation", f"{dog['abbr']} on {dr} days' rest, "
                                   f"{fav['abbr']} on {fr}"))
        if fr >= 13 and dr < 13:
            a.append(("situation", f"{fav['abbr']} are off a bye"))
    fl = fav["form"]["last"]
    if fl and fl["won"] and fl["opp_rank"]:
        f.append(("situation", f"{fav['abbr']} come off beating "
                               f"#{fl['opp_rank']} {fl['opp']}"))
    fn = fav["form"]["next"]
    if fn and fn["opp_rank"] and fn["opp_rank"] <= 15:
        f.append(("situation", f"{fav['abbr']} have #{fn['opp_rank']} "
                               f"{fn['opp']} next"))
    if fav["form"]["road_run"] >= 2 and not ctx["fav_home"]:
        f.append(("situation", f"third straight road game for {fav['abbr']}"))

    # the shape of the game
    total = ctx.get("total")
    if total is not None and total <= LOW_TOTAL[ctx["league"]]:
        f.append(("style", f"total of {total:g}: few possessions, less "
                           f"room for the better team"))
    if dog["abbr"] in OPTION_TEAMS:
        f.append(("style", f"{dog['abbr']} run the option, which shortens "
                           f"the game"))
    fg, dg = fav.get("giveaways"), dog.get("giveaways")
    if fg is not None and dg is not None and fg - dg >= 0.6:
        f.append(("style", f"{fav['abbr']} give it away {fg:.1f} times a "
                           f"game, {dog['abbr']} {dg:.1f}"))

    # the market
    moved, toward = ctx.get("moved"), ctx.get("toward")
    if moved is not None and 1.5 <= moved <= STALE_MOVE:
        if toward == dog["espn"]:
            f.append(("line", f"line has moved {moved:g} toward {dog['abbr']}"))
        elif toward == fav["espn"]:
            a.append(("line", f"line has moved {moved:g} toward {fav['abbr']}"))
    mkt, fpi = ctx.get("market"), ctx.get("fpi")
    if mkt is not None and fpi is not None:
        if fpi >= 0.5:
            f.append(("line", f"FPI makes {dog['abbr']} the favourite "
                              f"({fpi:.0%})"))
        elif fpi - mkt >= 0.08:
            f.append(("line", f"FPI gives {dog['abbr']} {fpi:.0%}, the "
                              f"market {mkt:.0%}"))
    return f, a


def in_band(price):
    return price is not None and BAND[0] <= price <= BAND[1]


def weight(reason):
    """How much a reason counts toward the reading order.

    Who is playing quarterback is the one thing here that changes a
    game outright, so news about it counts double — unless it has stood
    for two games, by which time the price has it.
    """
    kind, text = reason
    if kind == "injury":
        return 2
    if kind == "quarterback":
        return 1 if "two games running" in text else 2
    return 1


def score(row):
    return (sum(weight(r) for r in row["for"])
            - sum(weight(r) for r in row["against"]))


def rank_games(rows):
    """Underdogs in the band whose reasons outweigh the reasons against.

    This is a reading order, not a rating. It decides what gets read
    first and what is left in the table at the bottom; it says nothing
    about how likely anybody is to win.
    """
    live = [r for r in rows if in_band(r["price"]) and score(r) >= 1]
    live.sort(key=lambda r: (-score(r), -len(r["for"]), r["kickoff"]))
    return live


# ── the page ───────────────────────────────────────────────────────────
def _record(side):
    fm = side["form"]
    last = fm["last"]
    bits = [f"{fm['wins']}-{fm['losses']}"]
    if abs(fm["streak"]) > 1:
        bits.append(_streak_text(fm["streak"]))
    if last:
        res = "beat" if last["won"] else "lost to"
        bits.append(f"last: {res} {last['opp']} {last['pf']:g}-{last['pa']:g}")
    return ", ".join(bits)


def render(week, rows, made, source):
    """The research page as markdown."""
    live = rank_games(rows)
    out = [f"# Week {week} research", "",
           f"Built {made} from ESPN data ({source}). {len(rows)} games read, "
           f"{len(live)} underdogs priced {BAND[0]:.0%}-{BAND[1]:.0%} whose "
           f"reasons outweigh the reasons against.", "",
           "Reasons are observations, not a rating. Check anything about "
           "who is playing against a dated source before acting on it.", "",
           "## Underdogs with reasons", ""]
    for r in live:
        dog, fav = r["dog"], r["fav"]
        out.append(f"### {dog['abbr']} over {fav['abbr']} — "
                   f"{r['price']:.0%} · {r['away']} @ {r['home']} · "
                   f"{r['when']}")
        out.append(f"- {dog['abbr']}: {_record(dog)}")
        out.append(f"- {fav['abbr']}: {_record(fav)}")
        for kind, text in r["for"]:
            out.append(f"- **for** ({kind}): {text}")
        for kind, text in r["against"]:
            out.append(f"- *against* ({kind}): {text}")
        for side in (fav, dog):
            for inj in side.get("qb_inj") or []:
                if len(inj["note"]) > 25:      # "out" is not a note
                    out.append(f"- ESPN, {inj['date']}: {inj['note']}")
        out.append("")
    out += ["## Every game", "",
            "| game | when | favourite | dog % | total | move | for | against |",
            "|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: r["kickoff"]):
        move = ("" if r["moved"] is None
                else f"{r['moved']:g} to {r['toward_abbr']}")
        out.append(
            f"| {r['away']} @ {r['home']} | {r['when']} | {r['fav']['abbr']} "
            f"| {'' if r['price'] is None else format(r['price'], '.0%')} "
            f"| {'' if r['total'] is None else format(r['total'], 'g')} "
            f"| {move} | {len(r['for'])} | {len(r['against'])} |")
    return "\n".join(out) + "\n"


def latest_page(folder):
    """The newest research page on disk as (week, text), or (None, "").

    Only the part a person reads: the underdogs and their reasons. The
    table of every game stays in the file.
    """
    import glob
    import os
    import re
    best = None
    for path in glob.glob(os.path.join(folder, "research_week*.md")):
        m = re.search(r"research_week(\d+)\.md$", path)
        if m and (best is None or int(m.group(1)) > best[0]):
            best = (int(m.group(1)), path)
    if not best:
        return None, ""
    with open(best[1]) as f:
        text = f.read()
    return best[0], text.split("## Every game")[0].strip()
