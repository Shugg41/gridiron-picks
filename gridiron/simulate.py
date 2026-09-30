"""Simulating the week against the actual field.

Expected wins is the wrong number for a winner-take-all weekly prize. A
card that averages 22 correct and never finishes first is worth less than
one that averages 21 and wins outright twice a season. The only way to
tell them apart is to play the week out many times against the people you
are actually up against — which is possible here because the Picks by
Week page gives every entry's card, not just a percentage.

The important detail is that every entry is scored against the *same*
drawn outcome within a trial. Entries in a pick 'em pool are massively
correlated — thirty-one games where nearly everyone takes the same
favorites — so simulating each entry independently would invent
separation that does not exist and wildly overstate the chance of
winning.

No network, no database, no Streamlit.
"""
import random
from dataclasses import dataclass, field as _field


@dataclass
class Outlook:
    trials: int = 0
    mean: float = 0.0
    p10: int = 0
    p50: int = 0
    p90: int = 0
    win: float = 0.0            # finishing strictly first
    tie: float = 0.0            # tied at the top
    top3: float = 0.0
    field_size: int = 0

    @property
    def any_win(self):
        """First outright, plus a share of the ties — the pool splits, and
        a tie is not a loss."""
        return self.win + self.tie


def simulate(my_picks, probs, rivals=None, trials=10000, seed=1):
    """Play the week out `trials` times.

    my_picks : {game_key: team}          what I have
    probs    : {game_key: {team: p}}     each side's chance, summing to 1
    rivals   : {entry_name: {game_key: team}}   everyone else's cards

    A game with no probability is treated as a coin flip, and a game an
    entry never picked simply scores nothing for them — which is exactly
    what a missed pick costs.
    """
    rng = random.Random(seed)
    rivals = rivals or {}
    games = list(probs.keys())
    names = list(rivals.keys())

    mine, best_gap, scores = [], [], []
    wins = ties = top3 = 0
    for _ in range(trials):
        winners = {}
        for key in games:
            sides = probs.get(key) or {}
            if len(sides) != 2:
                continue
            (a, pa), (b, _pb) = list(sides.items())
            winners[key] = a if rng.random() < pa else b

        my_score = sum(1 for k, t in my_picks.items() if winners.get(k) == t)
        mine.append(my_score)
        rival_scores = [
            sum(1 for k, t in card.items() if winners.get(k) == t)
            for card in rivals.values()
        ]
        if rival_scores:
            top = max(rival_scores)
            if my_score > top:
                wins += 1
            elif my_score == top:
                ties += 1
            better = sum(1 for s in rival_scores if s > my_score)
            if better < 3:
                top3 += 1
            best_gap.append(my_score - top)
        scores.append(my_score)

    mine.sort()
    n = len(mine) or 1
    return Outlook(
        trials=trials,
        mean=sum(mine) / n,
        p10=mine[int(n * 0.10)], p50=mine[int(n * 0.50)],
        p90=mine[min(int(n * 0.90), n - 1)],
        win=wins / n, tie=ties / n, top3=top3 / n,
        field_size=len(names))


def probabilities(linked, picks):
    """{game_key: {team: p}} from the linked ESPN events.

    A game with no line becomes a straight coin flip rather than being
    dropped: it still has to be played, and pretending it does not exist
    would make every card look more certain than it is.
    """
    from . import espn
    out = {}
    for (game, event), pick in zip(linked, picks):
        key = (game.away_code, game.home_code)
        hp, ap = espn.win_probability(event)
        if hp is None:
            out[key] = {game.away_code: 0.5, game.home_code: 0.5}
        else:
            out[key] = {game.home_code: hp, game.away_code: ap}
    return out


def rivals_from_matrix(games, entries, exclude_me=True):
    """{entry: {game_key: team}} from the Picks by Week matrix."""
    out = {}
    for e in entries:
        if exclude_me and e.me:
            continue
        label = f"{e.name}/{e.entry}"
        card = {}
        for i, (away, home) in enumerate(games):
            if i >= len(e.picks):
                break
            team = e.picks[i][0]
            if team:
                card[(away, home)] = team
        out[label] = card
    return out


def estimated_rivals(shares, entries, seed=7):
    """Invent a field from predicted shares, for use before a deadline.

    Splash publishes everyone's picks only after the deadline, which
    is exactly too late to act on. This draws each entry's pick from
    the share the pool is expected to put on each side, so the
    simulation can run while the picks can still be changed.

    Independent draws per entry. Real entrants have persistent habits
    — some never leave the chalk, some chase dogs every week — and
    this cannot know them, so it will understate how alike the field
    really is and therefore how hard it is to finish alone at the top.
    Treat the result as the optimistic end of a range, and replace it
    with the real cards the moment Picks by Week is available.
    """
    rng = random.Random(seed)
    field = {}
    for i in range(entries):
        card = {}
        for key, sides in (shares or {}).items():
            if len(sides) != 2:
                continue
            (a, pa), (b, _pb) = list(sides.items())
            card[key] = a if rng.random() < pa else b
        if card:
            field[f"estimated {i + 1}"] = card
    return field


def what_flips_are_worth(picks, probs, rivals, trials=10000, seed=1):
    """Simulate the same week twice: as proposed, and as pure chalk.

    This is the number the whole strategy rests on. Flipping costs
    expected wins — that part is certain — and only pays if it raises the
    chance of finishing first often enough to be worth it. Rather than
    argue about that, play both cards against the same field and the same
    drawn outcomes and read the difference off.
    """
    from .model import chalk_of
    mine = {(p.away, p.home): p.team for p in picks if p.team}
    chalk = {(p.away, p.home): chalk_of(p) for p in picks if p.team}
    return (simulate(mine, probs, rivals, trials, seed),
            simulate(chalk, probs, rivals, trials, seed))
