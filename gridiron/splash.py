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
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

# Splash prints its times in the viewer's zone, and the viewer is in the
# East — the same zone the noon deadline is quoted in.
ET = ZoneInfo("America/New_York")

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
_RECORD = re.compile(r"^\d{1,2}-\d{1,2}(?:-\d{1,2})?$")
_RANKED = re.compile(r"^#\d{1,2}ranked\b")
_POINTS = re.compile(r"^(\d+)\s+points?$", re.I)
# A tied placing prints with a T in front of it: "T17".
_RANK = re.compile(r"^(T?)(\d+)$")
_WEEK_LABEL = re.compile(r"\bCFB Week (\d{1,2})\b")
_RANGE = re.compile(r"^([A-Z][a-z]{2})\s+(\d{1,2})"
                    r"(?:\s*-\s*([A-Z][a-z]{2})\s+(\d{1,2}))?$")
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
    kickoff_iso: str = ""               # the same instant, when datable
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
    expected: Optional[int] = None      # the count the page states itself
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

        # A game ends in its two codes, so look for that block and read
        # backwards from it. What sits between and after the codes —
        # ranks, records, the points trailer — varies by page, so none
        # of it is assumed.
        sides = _two_sides(lines, i, tb_at) if is_code(line) and i >= 3 else None
        if sides:
            away_code, home_code, after = sides
            g = _game_from(lines, i, day, away_code, home_code)
            if g:
                g.points, after = _points_at(lines, after)
                entry.games.append(g)
                i = after
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


def _game_from(lines, code_at, day, away_code, home_code):
    """Build a game from the codes block at `code_at`, reading back."""
    j = code_at - 1
    if j >= 0 and _RANKED.match(lines[j]):
        j -= 1                              # a rank above the first code
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
    if not away or not home:
        return None
    if (is_code(away) and is_code(home)
            and (away, home) != (away_code, home_code)):
        # Two codes where the names should be usually means the walk
        # drifted into a neighbouring game — but not when they are this
        # game's own codes, which is simply a team whose name is its
        # code. BYU played TCU and the whole game went missing.
        return None
    return Game(away=away, home=home, away_code=away_code, home_code=home_code,
                day=day, kickoff=kickoff, status=status,
                away_score=away_score, home_score=home_score)


def parse_board(text):
    """Read the pick sheet itself — the page you make the picks on.

    It is the only page that exists before a deadline, and it is shaped
    unlike the entry page: no scores, no status, and the two team codes
    are not adjacent because each one is followed by that team's record.

        Steelers          <- away name
        Browns            <- home name
        Thu 8:15pm        <- kickoff
        #7ranked #7       <- only for a ranked team
        PIT               <- away code
        2-1               <- away record
        CLE               <- home code
        2-1               <- home record

    So this anchors on the kickoff line: it is the one line every game
    has exactly once, it sits between the names and the codes, and it
    cannot be confused with either. Reading out from it in both
    directions is what makes the optional rank lines harmless.

    The page also states its own game count ("/36 picks made"), which is
    kept on `expected` so a short parse can be reported as one rather
    than quietly accepted — a board that loses games is the bug this
    project keeps having.
    """
    lines = [l.strip() for l in text.splitlines()]
    entry = Entry(expected=_board_size(text))
    # Below the tiebreaker heading the last game is printed again, this
    # time followed by the total-score box rather than by codes.
    stop = next((n for n, l in enumerate(lines)
                 if l.lower().startswith("tiebreaker")), len(lines))
    year = _board_year(text)
    day = ""
    i = 0
    while i < stop:
        line = lines[i]
        if _DAY.match(line):
            day = line
            i += 1
            continue
        if _KICK.match(line) and i >= 2:
            g, after = _board_game(lines, i, day, stop, year)
            if g:
                entry.games.append(g)
                i = after
                continue
        i += 1

    for n in range(stop, len(lines)):
        if lines[n].lower().startswith("combined total score"):
            for m in range(n + 1, min(n + 4, len(lines))):
                v = _int(lines[m])
                if v is not None:
                    # zero is the empty box, not a guess of nil-nil
                    entry.tiebreaker = v or None
                    break
            break
    return entry


def _two_sides(lines, i, stop=None):
    """Read "[#7ranked #7] CODE [2-1]" twice, starting at `i`.

    Every page prints the two teams' codes this way and each shows a
    different subset of the optional lines: the board has the records
    and sometimes a rank, week 4's entry page had neither, week 1's had
    both. Reading the optional parts rather than assuming them is what
    lets one function serve all three — the alternative is a parser per
    page, which is how this project got into trouble in the first place.

    Returns (away_code, home_code, index_after) or None.
    """
    stop = len(lines) if stop is None else stop
    j, codes = i, []
    for _ in range(2):
        if j < stop and _RANKED.match(lines[j]):
            j += 1
        if j >= stop or not is_code(lines[j]):
            return None
        codes.append(lines[j])
        j += 1
        if j < stop and _RECORD.match(lines[j]):
            j += 1
    return codes[0], codes[1], j


def _points_at(lines, i):
    """This entry's score for the game: "1", or "1 points" spelled out."""
    for n in range(i, min(i + 2, len(lines))):
        if lines[n] in ("0", "1"):
            return int(lines[n]), n + 1
        m = _POINTS.match(lines[n])
        if m:
            return int(m.group(1)), n + 1
    return None, i


def _board_game(lines, kick_at, day, stop, year=None):
    """Build a game from the kickoff line at `kick_at`.

    Returns (game, index_after) or (None, _) when the shape does not hold
    — a game that does not parse cleanly is left out rather than guessed
    at, and `expected` will show that it went missing.
    """
    away, home = lines[kick_at - 2], lines[kick_at - 1]
    for name in (away, home):
        # "@" is the separator on the pre-deadline entry page, where the
        # shape is name / @ / name / kickoff. Reading back two lines
        # lands on it, and taking it as a team name would write "@" over
        # every away team on the board.
        if (not name or name in ("@", "-", "vs", "VS")
                or _DAY.match(name) or _KICK.match(name)
                or _RECORD.match(name) or _RANKED.match(name)):
            return None, kick_at
    # Team names can themselves look like codes — BYU plays TCU — so the
    # names are not checked against is_code, only the codes are.
    sides = _two_sides(lines, kick_at + 1, stop)
    if not sides:
        return None, kick_at
    away_code, home_code, j = sides
    return Game(away=away, home=home, away_code=away_code, home_code=home_code,
                day=day, kickoff=lines[kick_at],
                kickoff_iso=_board_kickoff(day, lines[kick_at], year)), j


def _board_year(text):
    """The year, which the day headers leave out and the lock line states:
    "Picks lock: / Sat, Oct 3, 2026, 12:00 PM"."""
    m = re.search(r"picks lock:?\s*\n?[^\n]*?(20\d{2})", text, re.I)
    return int(m.group(1)) if m else None


def _board_kickoff(day, kick, year):
    """Turn "Thursday, Oct 1" and "Thu 8:15pm" into a real instant.

    Worth doing even though ESPN also carries kickoff times, because
    everything that matters before a deadline hangs off this: the card is
    ordered by it, and a Thursday game locks at kickoff rather than at
    Saturday noon. Depending on an ESPN match for that means a game that
    failed to match sorts by the text "Mon 8:15pm", which puts Monday
    third, and never warns that it is about to lock.
    """
    d, k = _DAY.match(day or ""), _KICK.match(kick or "")
    if not d or not k or not year:
        return ""
    month = _MONTHS.get(d.group(2))
    if not month:
        return ""
    hour = int(k.group(4)) % 12 + (12 if k.group(6).lower() == "pm" else 0)
    try:
        dt = datetime(year, month, int(d.group(3)), hour, int(k.group(5)),
                      tzinfo=ET)
    except ValueError:
        return ""
    # The header and the kickoff line each name a weekday. When they
    # disagree the game has crossed midnight, so the kickoff line wins.
    want = k.group(1)[:3].lower()
    for shift in (0, 1, -1):
        if (dt + timedelta(days=shift)).strftime("%a").lower() == want:
            dt += timedelta(days=shift)
            break
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def _board_size(text):
    """The game count the board prints about itself: "0 /36 picks made"."""
    m = re.search(r"/\s*(\d+)\s*\n\s*picks made", text, re.I)
    if not m:
        m = re.search(r"(\d+)\s+picks made", text, re.I)
    return int(m.group(1)) if m else None


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
    rank: str = ""                      # "16", or "T17" when tied
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
        rank = _RANK.match(lines[j]) if j >= 0 else None
        if rank is None:
            continue
        rows.append(Standing(
            rank=lines[j], name=name.replace(" You", "").strip(), entry=lines[i - 1],
            points=_int(pts), wins=_int(wl.group(1)), losses=_int(wl.group(2)),
            ties=_int(wl.group(3)) or 0, tie_diff=_int(diff),
            me=name.endswith("You") or " You" in name))
    # Sort on the number, keep the "T" for display: two entries on the
    # same points share a placing, and dropping the T would print two
    # seventeenths as though one of them were eighteenth.
    rows.sort(key=lambda r: int(_RANK.match(r.rank).group(2)))
    size = re.search(r"All entries\s*(\d+)", text)
    return rows, (_int(size.group(1)) if size else len(rows))


@dataclass
class EntryPicks:
    """One entry's whole card for a week, in the page's game order."""
    name: str = ""
    entry: str = ""
    rank: str = ""                      # "1" or "T15" — ties are printed
    points: Optional[int] = None
    picks: list = _field(default_factory=list)   # [(team, state), ...]
    me: bool = False


# How each pick is annotated, and what it means for scoring.
_PICK_STATE = {
    "correct": "W",
    "incorrect": "L",
    "currently winning": "live_up",
    "currently losing": "live_down",
    "not yet graded": "open",
}
_MATCHUP = re.compile(r"^([A-Z][A-Z0-9&.'()-]{1,6})\s+@\s+([A-Z][A-Z0-9&.'()-]{1,6})$")


def parse_picks_by_week(text):
    """Read the Picks by Week page: every entry's pick on every game.

    This is the richest page Splash has. The Pick Distribution page only
    gives percentages; this gives the actual matrix, which is what makes
    real leverage — who exactly is on which side — computable rather than
    estimated. It also states a missing pick outright, which no other page
    does: the entry page simply omits the game.

    The page lists the games once as a header, then repeats that same
    order inside every entry block, so the games are read first and each
    entry's picks are zipped against them positionally.

    Returns (games, entries) where games is [(away, home), ...].
    """
    lines = [l.strip() for l in text.splitlines()]
    games, seen = [], set()
    for line in lines:
        m = _MATCHUP.match(line)
        if m and line not in seen:
            seen.add(line)
            games.append((m.group(1), m.group(2)))

    entries, i = [], 0
    while i < len(lines):
        if not lines[i].startswith("Rank"):
            i += 1
            continue
        e = EntryPicks(rank=lines[i][4:].strip())
        j = i + 1
        if j < len(lines) and len(lines[j]) == 1 and lines[j].isupper():
            j += 1                                  # avatar initial
        e.name = lines[j] if j < len(lines) else ""
        j += 1
        if j < len(lines) and lines[j] == "You":    # the user's own row
            e.me = True
            j += 1
        e.entry = lines[j] if j < len(lines) else ""
        # skip forward to the link that ends every entry's header
        while j < len(lines) and not lines[j].lower().startswith(". view entry"):
            if lines[j].startswith("Pts:"):
                e.points = _int(lines[j].split(":", 1)[1])
            j += 1
        j += 1

        # then the picks, in the header's order, until the next entry
        while j < len(lines) and not lines[j].startswith("Rank"):
            line = lines[j]
            if line in ("▲", "▼", ""):
                j += 1
                continue
            if line == "-" and j + 1 < len(lines) and lines[j + 1] == "Missing pick":
                e.picks.append((None, "missing"))
                j += 2
                continue
            nxt = lines[j + 1] if j + 1 < len(lines) else ""
            if is_code(line) and nxt.startswith("—"):
                state = _PICK_STATE.get(nxt.lstrip("—").strip(), "open")
                e.picks.append((line, state))
                j += 2
                continue
            j += 1
        if e.name and e.picks:
            entries.append(e)
        i = j
    return games, entries


def distribution_from_matrix(games, entries):
    """Collapse the pick matrix into per-side counts and shares.

    Same shape parse_distribution returns, so the rest of the app does not
    care which page the field came from — and this one is exact rather
    than rounded to a tenth of a percent.
    """
    out = []
    for idx, (away, home) in enumerate(games):
        tally = {away: 0, home: 0}
        for e in entries:
            if idx >= len(e.picks):
                continue
            team = e.picks[idx][0]
            if team in tally:
                tally[team] += 1
        total = len(entries) or 1
        out.append(((away, tally[away], tally[away] / total),
                    (home, tally[home], tally[home] / total)))
    return out


def week_of(text):
    """Which week is this page about? The page says, so ask it.

    Every page carries its week as a label — "NFL Week 4 | CFB Week 5",
    or just "CFB Week 1" for a week with no NFL in it — and the CFB
    number is the one this app counts by. The pick sheet and the
    single-entry view carry exactly one label, so there is nothing to
    work out.

    The full page is harder: its week picker lists the whole season, so
    twenty-two labels are present and only one of them is the week on
    screen. Each is followed by its date range, though, and the games
    below carry their own dates, so the first game's day settles it.

    Returns the week number, or None when the page does not say —
    which includes the bowl weeks, whose labels carry no CFB number.

    Worth having because the alternative is the user typing the week
    into a box that defaults to the current one. Pasting an old page
    without changing it would file those games under this week, and
    nothing downstream could tell.
    """
    lines = [l.strip() for l in text.splitlines()]
    labelled = [(n, int(m.group(1)))
                for n, l in enumerate(lines)
                for m in [_WEEK_LABEL.search(l)] if m]
    if not labelled:
        return None
    if len(labelled) == 1:
        return labelled[0][1]

    first = next((_DAY.match(l) for l in lines if _DAY.match(l)), None)
    if not first:
        return None
    day = (_MONTHS.get(first.group(2)), int(first.group(3)))
    if not day[0]:
        return None
    for n, week in labelled:
        rng = _RANGE.match(lines[n + 1]) if n + 1 < len(lines) else None
        if not rng:
            continue
        start = (_MONTHS.get(rng.group(1)), int(rng.group(2)))
        end = ((_MONTHS.get(rng.group(3)), int(rng.group(4)))
               if rng.group(3) else start)
        if not start[0] or not end[0]:
            continue
        if start <= end:
            if start <= day <= end:
                return week
        elif day >= start or day <= end:    # a range over the new year
            return week
    return None


def sniff(text):
    """Which Splash page is this? 'entry', 'distribution', 'standings',
    'board', or None.

    Every page carries the same navigation bar — Standings, My entries,
    Pick Distribution — so the nav says nothing about which page you are
    actually on. Each test below keys on something only the page body has.
    """
    t = text.lower()
    # Check this before standings: the picks matrix carries the standings
    # nav, the "All entries" count and "View entry details" links too, and
    # only the per-pick annotations tell the two apart.
    if "— correct" in text or "— incorrect" in text or "missing pick" in t:
        return "picks_by_week"
    if ". view entry details" in t or ("all entries" in t and "tie diff" in t):
        return "standings"
    if "autopicks" in t and "%)" in text:
        return "distribution"
    if "view picks" in t or "rank:" in t:
        return "entry"
    # The board last: it is the page with the fewest markers of its own,
    # and "picks made" also appears on the entry page as "All picks
    # made", which is why that test has to have run first.
    if ("pick straight up" in t or "picks lock:" in t or "picks made" in t
            or re.search(r"\d+\s+games?\b", t)):
        return "board"
    return None
