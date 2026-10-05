"""Deciding the picks, and deciding how brave to be.

Two separate jobs. Picking a side is nearly solved — the betting line,
devigged, beats anything else available for free, and FPI is only worth
consulting where it disagrees sharply. Deciding how many coin flips to
take against the crowd is the part that actually wins or loses a pool,
and it depends on the standings rather than on any single game.

Nothing here touches the network or the database.
"""
import math
from statistics import NormalDist
from dataclasses import dataclass
from typing import Optional

from . import espn

# Where the plain-English confidence lines fall.
SAFE = 0.78
LIKELY = 0.60

# A flip is only worth considering when the underdog is close to a true
# coin flip; below this the points given up stop being cheap. In NFL terms
# this is a spread inside about a point and a half, which is where the
# expected cost of taking the dog is roughly a tenth of a win.
LIVE_DOG = 0.45

CHALK_FLIPS = 3          # protecting a reachable season finish
HUNT_FLIPS = 6           # season gone, chasing a weekly outright
PAYING_PLACES = 3        # season pays a few; a setting, not a law


def confidence(p):
    """Plain English, because a percentage invites second-guessing and a
    word does not."""
    if p is None:
        return "No line yet"
    if p >= SAFE:
        return "Safe"
    if p >= LIKELY:
        return "Should win"
    return "Close call"


def favorite(event):
    """(favorite_code, underdog_code, favorite_probability) or Nones."""
    if not event:
        return None, None, None
    hp, ap = espn.win_probability(event)
    if hp is None:
        return None, None, None
    home = (event.get("home") or {}).get("abbr")
    away = (event.get("away") or {}).get("abbr")
    if not home or not away:
        return None, None, None
    return (home, away, hp) if hp >= ap else (away, home, ap)


def dog_chance(event):
    fav, dog, p = favorite(event)
    return None if p is None else 1 - p


def fpi_edge(event, fpi_home, fpi_away, hfa=None):
    """How far FPI's view of the game sits from the market's, in win
    probability. Positive means FPI likes the home side more than the
    market does. None when either side is unknown."""
    if not event or fpi_home is None or fpi_away is None:
        return None
    hp, _ap = espn.win_probability(event)
    if hp is None:
        return None
    edge = hfa if hfa is not None else (2.0 if event.get("league") == "NFL" else 2.6)
    margin = (fpi_home + edge) - fpi_away
    sd = espn.MARGIN_SD.get(event.get("league"), 14.5)
    import math
    fpi_hp = 0.5 * (1 + math.erf((margin / sd) / math.sqrt(2)))
    return fpi_hp - hp


# ── how brave to be ─────────────────────────────────────────────────────
@dataclass
class Strategy:
    mode: str = "chalk"              # "chalk" | "hunt"
    flips: int = CHALK_FLIPS
    why: str = ""
    gap: Optional[int] = None
    per_week: Optional[float] = None


def strategy(standings, weeks_left, paying=PAYING_PLACES):
    """Chalk while a paying season finish is reachable; hunt once it is not.

    The weekly prize is winner-take-all, so winning one outright needs
    real separation from a field that picks the same favorites. But
    separation costs expected wins, and expected wins are what a season
    placing is made of. So the question is only ever: is the season still
    live? Points behind the last paying place, divided by the weeks left,
    answers it — under a point a week is noise in a thirty-game week, and
    chasing it would be paying for something already within reach.
    """
    me = next((s for s in standings if s.me), None)
    if not me or not standings or not weeks_left:
        return Strategy(why="No standings loaded — playing it straight.")

    ranked = sorted(standings, key=lambda s: -(s.points or 0))
    cutoff = ranked[min(paying, len(ranked)) - 1].points or 0
    gap = max(0, cutoff - (me.points or 0))
    per_week = gap / weeks_left

    if per_week <= 1.0:
        where = ("holding a paying spot" if gap == 0
                 else f"{gap} point{'s' if gap != 1 else ''} off the top {paying}")
        return Strategy("chalk", CHALK_FLIPS, gap=gap, per_week=per_week,
                        why=f"Chalk — {where} with {weeks_left} weeks left, "
                            f"which is {per_week:.1f} points a week. The season "
                            f"is live; protect it.")
    return Strategy("hunt", HUNT_FLIPS, gap=gap, per_week=per_week,
                    why=f"Hunting — {gap} points off the top {paying} with only "
                        f"{weeks_left} weeks left needs {per_week:.1f} a week. "
                        f"That is not happening on chalk; play for a weekly win.")


# ── picking the week ────────────────────────────────────────────────────
@dataclass
class Pick:
    """One game's recommendation.

    Deliberately side-neutral: `team` is whoever is being picked and
    `other` is whoever is not. An earlier version called them favorite and
    underdog, which stopped being true the moment a flip swapped them.
    """
    away: str = ""
    home: str = ""
    team: Optional[str] = None
    other: Optional[str] = None
    basis: str = "line"              # "line" | "flip" | "none"
    prob: Optional[float] = None     # the pick's own win probability
    other_prob: Optional[float] = None
    field_on_team: Optional[float] = None    # league's share, once known
    fpi_lean: Optional[float] = None         # FPI minus market, on this pick

    @property
    def flipped(self):
        return self.basis == "flip"


def _board_codes(game, event, fav, dog):
    """Say the pick in Splash's spelling, not ESPN's.

    favorite() answers with ESPN's abbreviation, and everything
    downstream keys on the board's: the list the user types into
    Splash, the field's shares, and the entry the advice tracker scores
    against. ESPN says SC where Splash says SCAR, so a pick on South
    Carolina was written down as a team that appears nowhere on the
    board — unmatchable by the tracker, and a code the user would have
    to translate by eye.

    Only which side is needed, never a name lookup: link() pairs away
    with away and home with home, so the correspondence is already
    settled by the time this runs.
    """
    if not fav:
        return None, None
    if fav == (event.get("home") or {}).get("abbr"):
        return game.home_code, game.away_code
    return game.away_code, game.home_code


# How far FPI has to differ from the market before it is worth letting
# it break a tie. Two points of win probability: below that the two
# agree, and the median disagreement across a real slate is under three.
FPI_AGREES = 0.02


# How hard this pool backs a favorite, fitted to 75 of its own games
# across weeks 1-5: share = logistic(A + B x line).
#
# The first version of this was fitted to 43 games and was wrong in a
# way that mattered. It had an intercept of 1.138 and a slope of
# 0.157, which says a one-point favorite already draws 78% and the
# price barely moves the crowd after that. With the whole season's
# field in hand, neither half holds: a one-point favorite draws 61%,
# and the line moves this pool a great deal more than it appeared to
# — the slope more than doubles. The old curve was flattered by a
# sample that happened to be short of close games.
#
# The direction of the error is the point. On a near-pick'em the old
# curve claimed 78-80% of the pool would be on the favorite when the
# truth is nearer two thirds, so every contrarian play looked more
# contrarian than it was, and the estimated field was too concentrated
# exactly where a week is actually won or lost.
#
# FIELD_RMS is the residual spread. It improves, 0.125 to 0.103, but
# it is still large and the misses are all one shape: five of them,
# every one a short favorite the pool refused to back. Ohio State laid
# two and a half at Texas and took 40% of the room against a predicted
# 73%. Those games are where a week is won, and by definition a curve
# drawn through the line alone cannot see them coming. Any number
# derived from here should be shown with that admission attached.
FIELD_A, FIELD_B, FIELD_RMS = 0.087, 0.369, 0.103


def expected_share(line):
    """What fraction of the pool will take the favorite, given a line.

    Before a deadline Splash says nothing about the field, so this
    stands in for it. Returns None with no line, because a guess with
    no input is worse than an absence.
    """
    if line is None:
        return None
    return 1 / (1 + math.exp(-(FIELD_A + FIELD_B * abs(line))))


def crowd_split(sides):
    """{team: expected crowd share} from {team: win probability}.

    Works off the probability rather than the line so that every game
    gets a split, including the ones ESPN has stopped quoting odds on
    — which is all of them once a game kicks off.

    That mattered more than it sounds. The estimated field was built
    only from games that still had a line, while the entry was scored
    on all thirty-six, so the imaginary rivals were playing a
    three-game week against a thirty-six-game one and lost every
    trial. The page said 100% to win outright.

    The probability is turned back into a notional margin and run
    through the same fitted curve. A true coin flip splits the pool
    evenly, which is the honest answer when nothing is known.
    """
    if not sides or len(sides) != 2:
        return None
    (a, pa), (b, pb) = list(sides.items())
    fav, other, p = (a, b, pa) if pa >= pb else (b, a, pb)
    if p is None:
        return None
    if abs(p - 0.5) < 1e-6:
        return {fav: 0.5, other: 0.5}
    # One spread, not per-league: `sides` does not say which league it
    # came from, and the curve is shallow enough that the difference
    # between 13.2 and 16.5 moves the share by a point or two.
    line = 14.5 * NormalDist().inv_cdf(min(max(p, 0.001), 0.999))
    share = expected_share(line)
    return {fav: share, other: 1 - share}


def propose(linked, field=None, strat=None, edge=None):
    """Pick every game, then flip the best few underdogs.

    The favorite everywhere is the right baseline and nearly the whole
    answer. The flips are the only deliberate cost, so they go to the
    closest games — and where the league's behaviour is known, to the
    closest games the crowd is most piled against, since a coin flip
    nobody else is fading buys no separation.

    `edge` is an optional callable (game, event) -> FPI's disagreement
    with the market in win probability, positive meaning FPI likes the
    home side more. It is asked only about games already in flip
    range, because it costs a request per team and is used nowhere
    else.

    What it is allowed to do is deliberately narrow. FPI disagreeing
    with the line does not make FPI right — the market is the better
    forecaster and overriding it would cost points. But among games
    that are already coin flips, which one to take was previously
    arbitrary, and "the one an independent model thinks is
    mispriced" beats picking by list order. So it reorders
    candidates; it never changes which games are candidates, and
    never touches the other thirty.
    """
    strat = strat or Strategy()
    field = field or {}
    pairs = list(linked)
    picks = []
    for game, event in pairs:
        fav, dog, p = favorite(event)
        fav, dog = _board_codes(game, event, fav, dog)
        shares = field.get((game.away_code, game.home_code)) or {}
        picks.append(Pick(away=game.away_code, home=game.home_code,
                          team=fav, other=dog,
                          basis="line" if fav else "none",
                          prob=p, other_prob=None if p is None else 1 - p,
                          field_on_team=shares.get(fav) if fav else None))

    # Candidates are judged before anything is flipped, on the underdog's
    # chance and on how exposed the crowd is to losing that game.
    live = [(i, pk) for i, pk in enumerate(picks)
            if pk.other_prob is not None and pk.other_prob >= LIVE_DOG]
    if edge is not None:
        for i, pk in live:
            game, event = pairs[i]
            e = edge(game, event)
            if e is None:
                continue
            # `e` is home-relative; the flip would take pk.other, so
            # turn it into "how much more FPI likes the side we would
            # be taking than the market does".
            pk.fpi_lean = e if pk.other == game.home_code else -e
    # Lexicographic, not weighted: candidates FPI also likes come
    # first, and within each group the old leverage order stands.
    # Blending them would need a weight, and there is no evidence for
    # one — a made-up number would only hide the guess.
    live.sort(key=lambda t: (0 if (t[1].fpi_lean or 0) >= FPI_AGREES else 1,
                             -(t[1].other_prob * (t[1].field_on_team or 0.5))))
    live = [pk for _i, pk in live]
    # However many the strategy asks for, capped by how many games are
    # actually close. A chalky week should produce no flips rather than
    # reach down into spots where the points stop being cheap.
    for pk in live[:strat.flips]:
        pk.team, pk.other = pk.other, pk.team
        pk.prob, pk.other_prob = pk.other_prob, pk.prob
        pk.field_on_team = (1 - pk.field_on_team
                            if pk.field_on_team is not None else None)
        pk.basis = "flip"
    return picks


def chalk_of(pick):
    """What pure chalk would have taken — the flip reverted."""
    return pick.other if pick.flipped else pick.team


def tiebreaker(event):
    """The Vegas total on the last game, rounded. It is the best public
    estimate there is and beats a guess, which is what it replaces."""
    if not event:
        return None
    ou = event.get("over_under")
    return None if ou is None else int(round(ou))


# ── was any of this worth following? ────────────────────────────────────
@dataclass
class Report:
    app: int = 0
    chalk: int = 0
    actual: int = 0
    graded: int = 0

    @property
    def verdict(self):
        if self.graded < 20:
            return f"Too early to tell — {self.graded} graded games so far."
        if self.app > self.chalk:
            return (f"The flips are paying: {self.app} to chalk's {self.chalk} "
                    f"over {self.graded} games.")
        if self.app < self.chalk:
            return (f"The flips are costing you: {self.app} against chalk's "
                    f"{self.chalk} over {self.graded} games.")
        return f"Level with chalk over {self.graded} games."


def advice_report(proposals, entries, winners):
    """Score three cards over the same games: what the app proposed, what
    pure chalk would have been, and what was actually entered.

    Keeping them apart is the only honest way to answer whether the
    advice is worth following — and if it is not, the user should be able
    to see that here rather than take it on trust.
    """
    rep = Report()
    for key, (team, basis) in proposals.items():
        winner = winners.get(key)
        if not winner or not team:
            continue
        rep.graded += 1
        rep.app += int(team == winner)
        chalk = team if basis != "flip" else _other(key, team)
        rep.chalk += int(chalk == winner)
        mine = (entries.get(key) or (None, None))[0]
        rep.actual += int(mine == winner)
    return rep


def _other(key, team):
    away, home = key
    return home if team == away else away
