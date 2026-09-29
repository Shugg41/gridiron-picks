"""One page of pasted text in, one database write out.

This is deliberately not inside the app. The app is the normal way in,
but the same page has to be loadable from a session here — for a page
the app will not parse, for a week being backfilled, or simply because
it is easier that way. Both callers run this identical code, so the
fallback cannot drift from the real thing.

Returns (level, message) rather than raising or printing, because the
caller that matters is on a phone an hour before a deadline and needs to
be told what happened.
"""
from . import simulate, splash, store


def _match_pair(games, a, b):
    """Find the stored game these two codes belong to, either way round."""
    for g in games:
        if {a, b} == {g["away_code"], g["home_code"]}:
            return g["away_code"], g["home_code"]
    return None


def load(conn, season, week, text):
    """Route a pasted page to its parser and store what came back.

    Returns (level, message) rather than drawing anything, so the caller
    can catch a failure and SHOW it. Streamlit redacts the message of an
    uncaught exception — from a phone that reads as "an error occurred,
    see the logs", which is no use at all an hour before a deadline.
    """
    kind = splash.sniff(text)


    if kind in ("board", "entry"):
        # The board and the entry page are shaped differently — the board
        # has records between the two codes and no scores at all — so try
        # the board parser first and fall back, rather than trusting the
        # sniff to have got it right. Whichever sees more games wins.
        parsed = splash.parse_board(text)
        other = splash.parse_entry(text)
        if len(other.games) > len(parsed.games):
            parsed = other
        store.save_games(conn, season, week, parsed.games)
        rows = [{"away_code": g.away_code, "home_code": g.home_code,
                 "team": g.picked,
                 "result": None if g.points is None else
                 ("W" if g.points else "L")} for g in parsed.games]
        if any(r["team"] for r in rows):
            store.save_entry(conn, season, week, rows)
        if parsed.tiebreaker is not None:
            store.upsert(conn, "tiebreak", {"season": season, "week": week},
                         {"guess": parsed.tiebreaker})
        if not parsed.games:
            # Never report a load that found nothing as a load. A page
            # whose shape has changed parses to zero games and would
            # otherwise read as a clean, empty week.
            return "warn", (f"That looks like a {kind} page but no games "
                            f"came out of it — {len(text.splitlines())} lines "
                            f"read. The shape has probably changed; it needs "
                            f"looking at rather than re-pasting.")
        note = f"Week {week}: {len(parsed.games)} games loaded."
        if parsed.expected and parsed.expected != len(parsed.games):
            # The board states its own count, so a short parse can say so
            # instead of looking like a complete week.
            return "warn", (f"{note}  The page says {parsed.expected} — "
                            f"{parsed.expected - len(parsed.games)} did not "
                            f"parse. Paste the whole page, not a selection.")
        return "ok", note

    if kind == "picks_by_week":
        board_games, entries = splash.parse_picks_by_week(text)
        store.save_games(conn, season, week,
                         [splash.Game(away_code=a, home_code=h)
                          for a, h in board_games])
        mine = next((e for e in entries if e.me), None)
        if mine:
            store.save_entry(conn, season, week, [
                {"away_code": a, "home_code": h,
                 "team": (mine.picks[i] if i < len(mine.picks) else (None,))[0],
                 "result": {"W": "W", "L": "L"}.get(
                     mine.picks[i][1] if i < len(mine.picks) else "")}
                for i, (a, h) in enumerate(board_games)])
        store.save_field_cards(conn, season, week,
                               simulate.rivals_from_matrix(board_games, entries))
        dist = splash.distribution_from_matrix(board_games, entries)
        store.save_field(conn, season, week, [
            (board_games[i][0], board_games[i][1], side[0], side[1], side[2],
             None)
            for i in range(len(board_games)) for side in dist[i]])
        if not board_games:
            return "warn", ("That looks like a Picks by Week page but no "
                            "games came out of it — the shape has probably "
                            "changed.")
        missed = sum(1 for p in (mine.picks if mine else []) if p[0] is None)
        note = f"Week {week}: {len(board_games)} games, {len(entries)} entries."
        if missed:
            note += f"  {missed} game(s) you never picked."
        return "ok", note

    if kind == "distribution":
        rows = splash.parse_distribution(text)
        saved = 0
        for (ca, na, pa), (cb, nb, pb) in rows:
            key = _match_pair(store.week_games(conn, season, week), ca, cb)
            if not key:
                continue
            store.save_field(conn, season, week,
                             [(key[0], key[1], ca, na, pa, None),
                              (key[0], key[1], cb, nb, pb, None)])
            saved += 1
        return "ok", f"Field loaded for {saved} of {len(rows)} games."

    if kind == "standings":
        rows, size = splash.parse_standings(text)
        store.save_standings(conn, season, None, rows)
        me = next((r for r in rows if r.me), None)
        return "ok", (f"Standings loaded — {len(rows)} of {size} entries"
                      + (f", you are {me.rank} on {me.points}." if me else "."))

    return "warn", ("Couldn't tell which page that is — paste the whole page "
                    "rather than a selection.")
