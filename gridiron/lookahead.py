"""Rating the coming weekend before a board exists.

Splash decides which thirty games go on the card, not which get
played, and it posts that decision late. Everything in this app used
to wait on it: no board, no games, no numbers, nothing to look at
until a page had been pasted in.

It does not have to. The pool draws from a predictable pool of its
own — every NFL game, and the college games anyone would televise —
and ESPN will hand all of those over keyed by date, days ahead. So
the weekend can be rated first and the board, when it lands, mostly
confirms work already done.

Two numbers per game, neither of them Splash's:

    market   the sportsbook spread ESPN carries, as a win probability
    fpi      ESPN's power index, which never looks at the price

Lines appear only a few days out, so a Monday run is usually FPI
alone and a Thursday run has both. `sources` on each row says which,
because a one-signal rating and a two-signal rating should not look
alike on the screen.
"""
import datetime
import math

from . import espn

HFA = {"NFL": 2.0, "CFB": 2.6}
# The market's share of the blend. FPI gets a real but minority voice:
# it is the only input that never looks at the price, and also the only
# one with no money standing behind it.
W_MARKET = 2 / 3


def weekend(today=None, ahead=5):
    """The ESPN days of the coming Thursday-to-Monday."""
    today = today or datetime.date.today()
    thu = today + datetime.timedelta((3 - today.weekday()) % 7)
    return [(thu + datetime.timedelta(n)).strftime("%Y%m%d")
            for n in range(ahead)]


def _normal(margin, sd):
    return 0.5 * (1 + math.erf((margin / sd) / math.sqrt(2)))


def market_home(event):
    """P(home wins) from the sportsbook spread, or None before it is up."""
    try:
        odds = espn.odds_history(event["event_id"], event["league"])
        details = ((odds.get("items") or [{}])[0]).get("details")
    except Exception:
        return None
    named, value = espn._spread(details)
    if not named or value is None:
        return None
    # "BUF -3.5" names the side laying the points; the sign is theirs.
    home_margin = -value if named == event["home"]["abbr"] else value
    return _normal(home_margin, espn.MARGIN_SD.get(event["league"], 14.5))


def fpi_home(event):
    """P(home wins) from the power index alone."""
    try:
        h = espn.power_index(event["home"]["id"], event["league"], 2026)
        a = espn.power_index(event["away"]["id"], event["league"], 2026)
    except Exception:
        return None
    if not h or not a or h.get("fpi") is None or a.get("fpi") is None:
        return None
    return _normal((h["fpi"] + HFA[event["league"]]) - a["fpi"],
                   espn.MARGIN_SD.get(event["league"], 14.5))


def worth_rating(event):
    """Whether a game is plausibly going on the card.

    Every NFL game is. College runs to fifty on a Saturday and the pool
    carries sixteen, so a ranked side is the filter — it is close to
    how Splash appears to choose, and it keeps the request count to
    something a page load can afford.
    """
    return event["league"] == "NFL" or bool(event["rank"])


def collect(days=None, season_days=None):
    """Every game worth rating across those days, unrated."""
    pool, seen = [], set()
    for day in (days or weekend()):
        for league in ("nfl", "college-football"):
            for ev in espn.events_on(league, day):
                if ev["event_id"] in seen or not worth_rating(ev):
                    continue
                seen.add(ev["event_id"])
                pool.append(ev)
    return pool


def rate(events):
    """Attach market, FPI and a blended pick to each game.

    A game neither source can price is dropped rather than guessed at.
    """
    rows = []
    for ev in events:
        mkt, fpi = market_home(ev), fpi_home(ev)
        if mkt is None and fpi is None:
            continue
        if mkt is None:
            blend, sources = fpi, ("fpi",)
        elif fpi is None:
            blend, sources = mkt, ("market",)
        else:
            blend = W_MARKET * mkt + (1 - W_MARKET) * fpi
            sources = ("market", "fpi")
        home = blend >= 0.5
        rows.append({
            "event": ev,
            "away": ev["away"]["abbr"], "home": ev["home"]["abbr"],
            "kickoff": ev["kickoff"], "league": ev["league"],
            "rank": ev["rank"],
            "market": mkt, "fpi": fpi, "blend": blend,
            "sources": sources,
            "pick": ev["home"]["abbr"] if home else ev["away"]["abbr"],
            "confidence": blend if home else 1 - blend,
            # Both numbers, pointing at different teams. Not a weak
            # signal — two signals that do not agree, which is a
            # different thing and the only place a real read lives.
            "split": (mkt is not None and fpi is not None
                      and (mkt - .5) * (fpi - .5) < 0),
        })
    rows.sort(key=lambda r: (r["kickoff"], r["league"], r["away"]))
    return rows


def preview(days=None):
    """The whole job: collect the weekend and rate it."""
    return rate(collect(days))
