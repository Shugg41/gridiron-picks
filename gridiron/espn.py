"""ESPN, used only to decorate games Splash has already defined.

This is the module where the app's longest-running bug class dies. It used
to be the other way round: ESPN decided which games existed and the pasted
board tried to select from them by matching team codes. Any code Splash
spelled differently — JAC for JAX, WAS for WSH, LA for LAR — lost a game,
and codes that collide across leagues invented one.

Now the board is the truth and this only attaches a line to it. `link()`
is deliberately built so that **a game that cannot be matched keeps
existing with no odds**, and no ESPN event is ever used twice. Missing a
line is a cosmetic problem; losing a game off the card is not.

No streamlit import, so this runs in the app, in tests, and in a script
Claude runs on the user's behalf. The cache is a small TTL dict rather
than st.cache_data for the same reason.
"""
import math
import re
import time

import requests

SITE = "https://site.api.espn.com/apis/site/v2/sports/football"
CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues"
PATH = {"CFB": "college-football", "NFL": "nfl"}
CORE_PATH = {"CFB": "college-football", "NFL": "nfl"}

# Margins are roughly normal around the spread; these are the usual
# season-long standard deviations for each sport.
MARGIN_SD = {"CFB": 16.5, "NFL": 13.2}

_cache = {}


def cached(ttl, key, build):
    """Tiny TTL cache. Deliberately not st.cache_data: this module has to
    work outside Streamlit too, and Streamlit's cache has already caused
    one bug here by outliving a corrected credential."""
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    value = build()
    _cache[key] = (now, value)
    return value


def clear_cache():
    _cache.clear()


# ── talking to ESPN ─────────────────────────────────────────────────────
def _get(url, params=None, timeout=15):
    r = requests.get(url, params=params or {}, timeout=timeout)
    r.raise_for_status()
    return r.json()


def scoreboard(league, ttl=900):
    """Every game ESPN knows about this week, already parsed."""
    def build():
        data = _get(f"{SITE}/{PATH[league]}/scoreboard", {"limit": 400})
        return [parse_event(ev, league) for ev in data.get("events", [])]
    return cached(ttl, ("scoreboard", league), build)


def summary(event_id, league, ttl=1800):
    """Predictor, injuries and recent form for one game."""
    def build():
        return _get(f"{SITE}/{PATH[league]}/summary", {"event": event_id})
    return cached(ttl, ("summary", league, event_id), build)


def power_index(team_id, league, season, ttl=86400):
    """FPI and EPA. Preseason-informed, which is what makes it worth
    anything in September when box scores are a two-game sample."""
    def build():
        url = (f"{CORE}/{CORE_PATH[league]}/seasons/{season}/types/2/teams/"
               f"{team_id}/powerindex")
        return parse_power(_get(url))
    return cached(ttl, ("fpi", league, season, team_id), build)


def team_stats(team_id, league, season, ttl=86400):
    def build():
        url = (f"{CORE}/{CORE_PATH[league]}/seasons/{season}/types/2/teams/"
               f"{team_id}/statistics")
        return parse_stats(_get(url))
    return cached(ttl, ("stats", league, season, team_id), build)


# ── turning ESPN's payloads into something plain ────────────────────────
def parse_event(ev, league):
    """One scoreboard event, defensively. ESPN drops keys without warning,
    so everything here degrades to None rather than raising."""
    comp = (ev.get("competitions") or [{}])[0]
    sides = {}
    for c in comp.get("competitors", []):
        team = c.get("team") or {}
        sides[c.get("homeAway", "?")] = {
            "id": str(team.get("id", "")),
            "abbr": team.get("abbreviation", "") or "",
            "name": team.get("shortDisplayName") or team.get("displayName", "") or "",
            "full_name": team.get("displayName", "") or "",
            "location": team.get("location", "") or "",
            "score": _num(c.get("score")),
        }
    odds = (comp.get("odds") or [{}])[0]
    named, signed = _spread(odds.get("details"))
    # "GB -3.5" names the favorite; "GB +3.5" names the underdog, so the
    # favorite is the other side. Reading the sign off is the difference
    # between backing the right team and the wrong one.
    fav = line = None
    if named and signed is not None:
        line = abs(signed)
        if signed < 0:
            fav = named
        else:
            other = [s for s in (sides.get("home", {}), sides.get("away", {}))
                     if s.get("abbr") and s.get("abbr") != named]
            fav = other[0]["abbr"] if other else None
            if fav is None:
                line = None
    return {
        "league": league,
        "event_id": str(ev.get("id", "")),
        "date": ev.get("date", ""),
        "completed": bool(((ev.get("status") or {}).get("type") or {})
                          .get("completed")),
        "status": (((ev.get("status") or {}).get("type") or {})
                   .get("shortDetail", "")),
        "home": sides.get("home", {}),
        "away": sides.get("away", {}),
        "fav_abbr": fav,
        "line": line,
        "over_under": _num(odds.get("overUnder")),
        "home_ml": _num((odds.get("homeTeamOdds") or {}).get("moneyLine")),
        "away_ml": _num((odds.get("awayTeamOdds") or {}).get("moneyLine")),
    }


def parse_power(payload):
    out = {}
    for item in (payload or {}).get("predictives") or []:
        name, value = item.get("name"), _num(item.get("value"))
        if name:
            out[name] = value
    return {"fpi": out.get("fpi"), "rank": out.get("fpirank"),
            "epa_off": out.get("epaoffense"), "epa_def": out.get("epadefense")}


def parse_stats(payload):
    out = {}
    cats = ((payload or {}).get("splits") or {}).get("categories") or []
    for cat in cats:
        for stat in cat.get("stats") or []:
            if stat.get("name"):
                out[f"{cat.get('name', '')}.{stat['name']}"] = _num(stat.get("value"))
    return out


def _num(v):
    try:
        return float(v) if v is not None and str(v).strip() != "" else None
    except (TypeError, ValueError):
        return None


def _spread(details):
    """"BUF -3.5" -> ("BUF", -3.5), keeping the sign, because it says which
    side of the game the named team is on. "EVEN" and anything else that
    does not fit -> (None, None)."""
    if not details:
        return None, None
    m = re.match(r"^\s*([A-Z][A-Z0-9&.'()-]{1,6})\s+([+-]?\d+(?:\.\d+)?)\s*$",
                 details.strip())
    if not m:
        return None, None
    return m.group(1), float(m.group(2))


# ── line movement ───────────────────────────────────────────────────────
def odds_history(event_id, league, ttl=3600):
    """The opening and current line for one game.

    Only the core API carries an opening line; the scoreboard gives the
    current one alone. Confirmed from CI before this was written — the
    direct competition path works, so it is one request per game rather
    than walking week -> events -> event -> odds at three.
    """
    def build():
        path = CORE_PATH[league]
        return _get(f"{CORE}/{path}/events/{event_id}/competitions/"
                    f"{event_id}/odds")
    return cached(ttl, ("odds_history", league, event_id), build)


def _point_spread(block):
    """ESPN prints the handicap as a signed string from that team's own
    point of view: "+24.5" means getting 24.5, "-21" means laying 21."""
    ps = ((block or {}).get("pointSpread") or {})
    raw = ps.get("american")
    if raw is None:
        return None
    try:
        return float(str(raw).replace("+", ""))
    except ValueError:
        return None


def movement(payload, home_code, away_code):
    """How far the line has moved since it opened, and toward whom.

    A line drifting toward the underdog is money disagreeing with the
    public, which is the interesting direction: the crowd piles onto
    favorites, so a favorite getting cheaper is usually sharper money
    taking the other side.

    Returns (points, team_code) or (None, None) when there is nothing to
    compare — plenty of games never move, and a game with no opening
    price is not a game that moved zero.
    """
    items = (payload or {}).get("items") or []
    if not items:
        return None, None
    home = items[0].get("homeTeamOdds") or {}
    opened = _point_spread(home.get("open"))
    now = _point_spread(home.get("current"))
    if opened is None or now is None:
        return None, None
    # The home handicap shrinking means the market came toward the home
    # side; growing means it went the other way.
    shift = opened - now
    if abs(shift) < 0.25:
        return None, None
    return abs(shift), (home_code if shift > 0 else away_code)


# ── matching a Splash game to an ESPN event ─────────────────────────────
def _norm(s):
    s = re.sub(r"[^a-z0-9& ]", " ", (s or "").lower())
    return " " + re.sub(r"\s+", " ", s).strip() + " "


def aliases(side):
    """Names ESPN itself uses for a team."""
    out = set()
    for a in (side.get("full_name"), side.get("location"), side.get("name")):
        if a and len(a) >= 3:
            out.add(_norm(a).strip())
    abbr = side.get("abbr")
    if abbr and len(abbr) >= 2:
        out.add(_norm(abbr).strip())
    return {a for a in out if a}


def loose_aliases(side):
    """Codes other scoreboards use where ESPN does not. Splash writes JAC,
    WAS and LA for teams ESPN calls JAX, WSH and LAR, and clips college
    names the same way. Deriving these beats a hand-kept table that rots
    the first time a code changes."""
    import itertools
    out = set()
    for a in (side.get("location"), side.get("name")):
        if not a:
            continue
        words = re.sub(r"[^a-z ]", " ", a.lower()).split()
        if not words:
            continue
        squash = "".join(words)
        out.update(squash[:n] for n in (3, 4) if len(squash) > n)
        if len(words) > 1:
            for combo in itertools.product(
                    *[[w[:k] for k in (1, 2, 3) if len(w) >= k] for w in words]):
                joined = "".join(combo)
                if 2 <= len(joined) <= 5:
                    out.add(joined)
    return {a for a in out if len(a) >= 2} - aliases(side)


def _score_side(splash_code, splash_name, espn_side):
    """3 for ESPN's own spelling, 2 for the printed name, 1 for a derived
    code, 0 for no. Tiers matter: an exact hit must always beat a guess."""
    code = _norm(splash_code).strip()
    name = _norm(splash_name).strip()
    exact = aliases(espn_side)
    if code and code in exact:
        return 3
    if name and name in exact:
        return 2
    if code and code in loose_aliases(espn_side):
        return 1
    return 0


def link(splash_games, espn_games):
    """Attach an ESPN event to each Splash game, best effort.

    Returns a list the same length and order as `splash_games`, of
    (splash_game, espn_event or None). Two rules make this safe:

    * every Splash game comes back, matched or not — the card is defined
      by the board, and a missing line is cosmetic where a missing game is
      not;
    * an ESPN event is used at most once, and both teams must match, so
      the cross-league code collisions (MIA, HOU, IND) cannot invent a
      pairing.

    Candidates are scored and taken best-first, so an exact spelling
    always claims its event ahead of a derived guess.
    """
    pairs = []
    for si, sg in enumerate(splash_games):
        for ei, eg in enumerate(espn_games):
            a = _score_side(sg.away_code, sg.away, eg.get("away", {}))
            h = _score_side(sg.home_code, sg.home, eg.get("home", {}))
            if a and h:
                pairs.append((min(a, h), a + h, si, ei))
    pairs.sort(key=lambda p: (-p[0], -p[1], p[2]))

    taken_s, taken_e, linked = set(), set(), {}
    for _tier, _total, si, ei in pairs:
        if si in taken_s or ei in taken_e:
            continue
        taken_s.add(si)
        taken_e.add(ei)
        linked[si] = espn_games[ei]
    return [(sg, linked.get(i)) for i, sg in enumerate(splash_games)]


# ── what the odds actually mean ─────────────────────────────────────────
def win_probability(event):
    """(home, away) true win probabilities, or (None, None).

    Moneylines carry the book's margin and sum past 100%, so they are
    normalised back to a fair 100. With no moneyline the spread is used
    instead: P(favorite) = the normal CDF of line / sd.
    """
    if not event:
        return None, None
    hp, ap = _implied(event.get("home_ml")), _implied(event.get("away_ml"))
    if hp and ap:
        return hp / (hp + ap), ap / (hp + ap)
    line, fav = event.get("line"), event.get("fav_abbr")
    if line is not None and fav:
        sd = MARGIN_SD.get(event.get("league"), 14.5)
        p = 0.5 * (1 + math.erf((line / sd) / math.sqrt(2)))
        home_is_fav = fav == (event.get("home") or {}).get("abbr")
        return (p, 1 - p) if home_is_fav else (1 - p, p)
    return None, None


def _implied(moneyline):
    """American odds to the probability they imply, vig included."""
    if moneyline is None:
        return None
    return (-moneyline) / (-moneyline + 100) if moneyline < 0 else 100 / (moneyline + 100)
