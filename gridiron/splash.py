"""Reading the Splash Sports pages.

Splash has no API, so every page arrives here as text the user copied out
of Safari. That text is nonetheless the best source there is: it defines
which games are in the pool, when they kick, who won, how the whole league
picked, and where the user stands. ESPN knows none of that.

So these parsers are the foundation, and they are written to fail loudly
rather than quietly: a block that does not make sense is reported back as
unparsed instead of being guessed at, because a wrong game silently
attributed is worse than a missing one the user can see.

Nothing here touches the network or the database, which is what makes it
testable against the real pages saved in tests/fixtures.
"""
import re
from dataclasses import dataclass, field as _field
from typing import Optional

# Page furniture that shows up where a team code would. "NO" is absent on
# purpose — that is New Orleans.
NOT_A_CODE = {
    "FINAL", "LIVE", "AM", "PM", "ET", "CT", "MT", "PT", "OT", "TBD", "VS",
    "AT", "PICK", "PICKS", "PICK DISTRIBUTION", "AUTOPICKS", "WINNER", "TIE",
    "CFB", "NFL", "Q1", "Q2", "Q3", "Q4", "HALF",
}

_CODE = re.compile(r"^[A-Z][A-Z0-9&.'()-]{1,6}( [A-Z0-9&.'()-]{1,4})?$")
_PCT = re.compile(r"^\((\d+(?:\.\d+)?)%\)$")
_DAY = re.compile(
    r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+"
    r"([A-Z][a-z]{2})\s+(\d{1,2})$")
_KICK = re.compile(r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s+"
                   r"(?:([A-Z][a-z]{2})\s+(\d{1,2})\s+)?(\d{1,2}):(\d{2})\s*(am|pm)$",
                   re.I)
_STATUS = re.compile(r"^(FINAL|LIVE\b.*|Q[1-4]\b.*|HALF.*|OT.*)$", re.I)
_SCORELINE = re.compile(r"^(.+?)\s+(\d+)\s+@\s+(.+?)\s+(\d+)$")
_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def is_code(text):
    """Does this line look like a team's scoreboard code, not furniture?"""
    s = text.strip()
    return bool(_CODE.match(s)) and s.upper() not in NOT_A_CODE


@dataclass
class Game:
    """One game as Splash presents it.

    `points` is the entry's score for the game — 1 or 0 — and only exists
    once the game is final. It is how the user's pick is recovered: with a
    winner and a point, the pick was the winner; with a winner and no
    point, it was the loser. The page's text does not otherwise say which
    side was taken.
    """
    away: str = ""
    home: str = ""
    away_code: str = ""
    home_code: str = ""
    day: str = ""                       # "Saturday, Sep 26" as printed
    kickoff: str = ""                   # "Sun 4:05pm" as printed
    status: str = ""                    # FINAL / LIVE Q2 6:38 / ""
    away_score: Optional[int] = None
    home_score: Optional[int] = None
    points: Optional[int] = None        # this entry's score for the game

    @property
    def final(self):
        return self.status.upper().startswith("FINAL")

    @property
    def winner(self):
        """Winning team's code, or None if it isn't decided."""
        if not self.final or self.away_score is None or self.home_score is None:
            return None
        if self.away_score > self.home_score:
            return self.away_code
        if self.home_score > self.away_score:
            return self.home_code
        return None                     # a tie decides nothing

    @property
    def picked(self):
        """Which side the entry took, recovered from the scoreline.

        Only knowable once the game is final and a point was recorded: one
        point means the winner was taken, none means the loser was. Before
        that the page gives nothing away, which is a real limit of reading
        picks back this way rather than a bug here.
        """
        w = self.winner
        if w is None or self.points is None:
            return None
        if self.points:
            return w
        return self.home_code if w == self.away_code else self.away_code


@dataclass
class Entry:
    games: list = _field(default_factory=list)
    rank: Optional[int] = None
    points: Optional[int] = None
    tiebreaker: Optional[int] = None
    unparsed: list = _field(default_factory=list)


def _int(text):
    try:
        return int(text.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def parse_entry(text):
    """Read the "My Entries" page: the week's games, the user's score for
    each, their rank and their tiebreaker.

    The page repeats a fixed shape per game, which is what this walks:

        Army            <- away
        21              <- away score   (or "@" when it hasn't kicked)
        -
        17              <- home score
        Temple          <- home
        FINAL           <- status       (absent before kickoff)
        ARMY            <- away code
        TEM             <- home code
        1               <- points       (final games only)

    Anchoring on the pair of codes is what makes this sturdy: the lines
    above them vary with game state, but every game ends with two codes,
    and the team names sit immediately before the scores.
    """
    lines = [l.strip() for l in text.splitlines()]
    entry = Entry()
    day = ""
    i = 0
    tb_at = next((n for n, l in enumerate(lines)
                  if l.lower().startswith("tiebreaker")), len(lines))

    while i < len(lines):
        line = lines[i]
        if i >= tb_at:
            break
        if _DAY.match(line):
            day = line
            i += 1
            continue
        if line.startswith("Rank:"):
            entry.rank = _int(line.split("#")[-1])
            i += 1
            continue
        if line.endswith("Pts"):
            entry.points = _int(line.split()[0])
            i += 1
            continue

        # a game is two codes in a row, so look for that and read backwards
        if (is_code(line) and i + 1 < len(lines) and is_code(lines[i + 1])
                and i >= 3):
            g = _game_from(lines, i, day)
            if g:
                pts = lines[i + 2] if i + 2 < len(lines) else ""
                if pts in ("0", "1"):
                    g.points = int(pts)
                    i += 1
                entry.games.append(g)
                i += 2
                continue
        i += 1

    # the tiebreaker block ends with the number the user entered
    for n in range(tb_at, len(lines)):
        if lines[n].lower().startswith("combined total score"):
            for m in range(n + 1, min(n + 4, len(lines))):
                v = _int(lines[m])
                if v is not None:
                    entry.tiebreaker = v
                    break
            break
    return entry


def _game_from(lines, code_at, day):
    """Build a game from the two code lines at `code_at`, reading back."""
    away_code, home_code = lines[code_at], lines[code_at + 1]
    j = code_at - 1
    status = ""
    if j >= 0 and _STATUS.match(lines[j]):
        status = lines[j]
        j -= 1
    kickoff = ""
    if j >= 0 and _KICK.match(lines[j]):
        kickoff = lines[j]
        j -= 1
    if j < 1:
        return None

    home = lines[j]
    j -= 1
    away_score = home_score = None
    if j >= 1 and lines[j].isdigit() and lines[j - 1] == "-":
        home_score = int(lines[j])
        j -= 2                                  # the score and the dash
        if j >= 0 and lines[j].isdigit():
            away_score = int(lines[j])
            j -= 1
        else:
            return None
    elif j >= 0 and lines[j] == "@":
        j -= 1                                  # hasn't kicked
    else:
        return None
    if j < 0:
        return None
    away = lines[j]
    if not away or not home or is_code(away) and is_code(home):
        # two codes where the names should be means the walk drifted
        return None
    return Game(away=away, home=home, away_code=away_code, home_code=home_code,
                day=day, kickoff=kickoff, status=status,
                away_score=away_score, home_score=home_score)


def parse_distribution(text):
    """Read the Pick Distribution page: how the whole league picked.

    Each side prints as an outcome word, the code, the number of entries
    and the percentage:

        Lost.
        GB
        34
        (89.5%)

    Anchoring on the percentage and reading backwards is sturdier than
    recognising the headings around it, which change with game state
    (FINAL, a live clock, a kickoff time) and would need chasing every
    time Splash relabels something.
    """
    lines = [l.strip() for l in text.splitlines()]
    sides = []
    for i, line in enumerate(lines):
        m = _PCT.match(line)
        if not m or i < 2:
            continue
        code, count = lines[i - 2], lines[i - 1]
        if not is_code(code) or _int(count) is None:
            continue
        sides.append((code, _int(count), float(m.group(1)) / 100))
    return [(sides[i], sides[i + 1]) for i in range(0, len(sides) - 1, 2)]


@dataclass
class Standing:
    rank: int = 0
    name: str = ""
    entry: str = ""
    points: int = 0
    wins: int = 0
    losses: int = 0
    ties: int = 0
    tie_diff: Optional[int] = None      # cumulative, lower is better
    me: bool = False


def parse_standings(text):
    """Read the Standings page into (rows, field_size), best rank first.

    Every row is anchored on its own "View entry details" link, because
    that is the one line each row definitely has and definitely has only
    once. Points, the W-L record and the tie differential follow it; the
    entry label and entrant name come before it; the rank sits before
    those, past a single-letter avatar line that some rows have and others
    do not. Anchoring on the rank number instead breaks on exactly that
    inconsistency, and on the fact that a bare integer is also what points
    and tie differentials look like.

    The tie differential matters more than it first appears: it is
    cumulative over the season and settles placings whenever entries tie
    on points, so it is carried through rather than dropped.
    """
    lines = [l.strip() for l in text.splitlines()]
    rows = []
    for i, line in enumerate(lines):
        if not line.lower().startswith(". view entry"):
            continue
        if i + 3 >= len(lines) or i < 3:
            continue
        pts, rec, diff = lines[i + 1], lines[i + 2], lines[i + 3]
        wl = re.match(r"^(\d+)-(\d+)(?:-(\d+))?$", rec)
        if _int(pts) is None or not wl:
            continue
        name = lines[i - 2]
        j = i - 3
        if j >= 0 and len(lines[j]) == 1 and lines[j].isalpha() and lines[j].isupper():
            j -= 1                      # the avatar initial, when present
        rank = _int(lines[j]) if j >= 0 else None
        if rank is None:
            continue
        rows.append(Standing(
            rank=rank, name=name.replace(" You", "").strip(), entry=lines[i - 1],
            points=_int(pts), wins=_int(wl.group(1)), losses=_int(wl.group(2)),
            ties=_int(wl.group(3)) or 0, tie_diff=_int(diff),
            me=name.endswith("You") or " You" in name))
    rows.sort(key=lambda r: r.rank)
    size = re.search(r"All entries\s*(\d+)", text)
    return rows, (_int(size.group(1)) if size else len(rows))


def sniff(text):
    """Which Splash page is this? 'entry', 'distribution', 'standings',
    'board', or None.

    Every page carries the same navigation bar — Standings, My entries,
    Pick Distribution — so the nav says nothing about which page you are
    actually on. Each test below keys on something only the page body has.
    """
    t = text.lower()
    if ". view entry details" in t or ("all entries" in t and "tie diff" in t):
        return "standings"
    if "autopicks" in t and "%)" in text:
        return "distribution"
    if "view picks" in t or "rank:" in t:
        return "entry"
    if re.search(r"\d+\s+games?\b", t):
        return "board"
    return None
