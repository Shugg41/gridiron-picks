import streamlit as st
import sqlite3
import pandas as pd
import requests
import base64
import difflib
import math
import os
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# ─────────────────────────────────────────────
# PAGE CONFIG & THEME
# ─────────────────────────────────────────────
st.set_page_config(page_title="Gridiron Picks", layout="wide", page_icon="🏈")

st.markdown("""
<style>
/* ── Theme: charcoal + gold + field green ── */
:root {
    --bg:           #0d0e10;
    --surface:      #16181c;
    --surface2:     #1c1f24;
    --border:       #2b2f36;
    --accent:       #d9a441;   /* gold — headings, highlights */
    --accent-hover: #e6b95e;
    --field:        #4f8f5b;   /* field green — wins, favorites */
    --loss:         #c15b5b;
    --push:         #b3a878;
    --text:         #e0e0e0;
    --muted:        #8a8f98;
}
html, body, [data-testid="stAppViewContainer"], [data-testid="stMain"] {
    background-color: var(--bg) !important;
    color: var(--text) !important;
}
[data-testid="stSidebar"] { background-color: var(--surface) !important; }
[data-testid="stHeader"]  { background-color: var(--bg) !important; }
.block-container { padding-top: 2.2rem !important; padding-bottom: 2rem !important; }
hr { border-color: var(--border) !important; margin: 0.6rem 0 !important; }
[data-testid="stToolbar"] { display: none !important; }
h1, h2, h3, h4 { color: var(--accent) !important; font-family: 'Georgia', serif; letter-spacing: 1px; }
h2 { font-size: 1.35rem !important; }

.pick-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-left: 3px solid var(--border);
    border-radius: 10px;
    padding: 0.65rem 0.85rem 0.5rem;
    margin: 0.7rem 0 0.3rem;
}
.pick-line  { font-size: 1.12rem; line-height: 1.45; }
.pick-team  { color: var(--accent); font-weight: 700; }
.pick-none  { color: var(--muted); font-weight: 700; }
.pick-opp   { color: var(--text); opacity: 0.72; font-weight: 400; }
.pick-sub   { color: var(--muted); font-size: 0.82rem; margin-top: 0.1rem; }
.chip {
    display: inline-block; font-size: 0.7rem; font-weight: 700;
    border-radius: 999px; padding: 0.08rem 0.5rem; margin-left: 0.45rem;
    vertical-align: middle; white-space: nowrap;
}
.chip-flip { color: var(--accent); border: 1px solid var(--accent); }
.chip-risk { color: var(--loss);  border: 1px solid var(--loss); }
.chip-edge { color: var(--field); border: 1px solid var(--field); }
.chip-close { color: var(--muted); border: 1px solid var(--border); }

.stButton > button {
    background: var(--surface2) !important;
    color: var(--text) !important;
    border: 1px solid var(--border) !important;
    border-radius: 8px !important;
    padding: 0.25rem 0.6rem !important;
    font-size: 0.85rem !important;
}
.stButton > button:hover { border-color: var(--accent) !important; color: var(--accent) !important; }
</style>
""", unsafe_allow_html=True)

ET = ZoneInfo("America/New_York")
DB_PATH = "football_picks.db"

# ─────────────────────────────────────────────
# GITHUB SYNC — the durable copy of the picks DB lives in the repo.
# Streamlit Cloud's disk is ephemeral, so we pull the DB once per server
# boot and push it back after every write (same pattern as the Metal
# Earth tracker). Without secrets the app runs fine in local-only mode.
# ─────────────────────────────────────────────
def secret(name):
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.environ.get(name)

def gh_repo():
    return secret("GITHUB_REPO")

def gh_headers():
    return {"Authorization": f"token {secret('GITHUB_TOKEN')}",
            "Accept": "application/vnd.github.v3+json"}

def sync_enabled():
    return bool(secret("GITHUB_TOKEN") and secret("GITHUB_REPO"))

def pull_db_from_github():
    if not sync_enabled():
        return
    try:
        url = f"https://api.github.com/repos/{gh_repo()}/contents/{DB_PATH}"
        r = requests.get(url, headers=gh_headers(), timeout=15)
        if r.status_code == 200:
            content = base64.b64decode(r.json()["content"])
            with open(DB_PATH, "wb") as f:
                f.write(content)
    except Exception:
        pass  # boot must never crash on a sync hiccup; app falls back to a fresh DB

def _gh_reason(r):
    """GitHub's own explanation for a non-2xx, short enough for a caption."""
    try:
        msg = (r.json() or {}).get("message", "")
    except Exception:
        msg = ""
    return f"{r.status_code} {msg}".strip()

def push_db_to_github():
    """Returns True on success. On failure, records WHY in session state —
    a silent False is what made a bad token indistinguishable from an idle
    app the last time this broke."""
    if not sync_enabled():
        return True  # local-only mode: a local commit is all there is
    url = f"https://api.github.com/repos/{gh_repo()}/contents/{DB_PATH}"
    try:
        r = requests.get(url, headers=gh_headers(), timeout=15)
        if r.status_code not in (200, 404):
            st.session_state["sync_error"] = _gh_reason(r)
            return False
        sha = r.json().get("sha") if r.status_code == 200 else None
        with open(DB_PATH, "rb") as f:
            payload = {"message": f"Update picks db {datetime.now(ET):%Y-%m-%d %H:%M}",
                       "content": base64.b64encode(f.read()).decode()}
        if sha:
            payload["sha"] = sha
        r = requests.put(url, headers=gh_headers(), json=payload, timeout=20)
        if r.status_code in (200, 201):
            st.session_state.pop("sync_error", None)
            return True
        st.session_state["sync_error"] = _gh_reason(r)
        return False
    except requests.RequestException as e:
        st.session_state["sync_error"] = f"couldn't reach GitHub ({type(e).__name__})"
        return False

@st.cache_resource
def verify_token():
    """One call per boot: can this token actually see the repo? Catches a
    typo'd token or repo name immediately instead of at the next save.
    Returns (ok, reason)."""
    if not sync_enabled():
        return False, "no secrets"
    try:
        r = requests.get(f"https://api.github.com/repos/{gh_repo()}",
                         headers=gh_headers(), timeout=15)
    except requests.RequestException as e:
        return False, f"couldn't reach GitHub ({type(e).__name__})"
    return (True, "") if r.status_code == 200 else (False, _gh_reason(r))

@st.cache_resource
def _boot_pull():
    # Once per SERVER boot, not per browser visit — the local DB is always
    # at least as fresh as GitHub's copy after boot.
    pull_db_from_github()
    return True

_boot_pull()

def save(conn):
    """Commit locally, then push to GitHub. Flags the session when the
    remote copy is stale so the user knows a restart would lose data."""
    conn.commit()
    if not push_db_to_github():
        st.session_state["sync_failed"] = True

# ─────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS picks (
            season      INTEGER NOT NULL,
            week        INTEGER NOT NULL,
            event_id    TEXT    NOT NULL,
            matchup     TEXT,
            kickoff     TEXT,
            pick_abbr   TEXT,
            pick_name   TEXT,
            opp_abbr    TEXT,
            opp_name    TEXT,
            pick_type   TEXT,               -- 'SU' straight up, 'ATS' against the spread
            fav_abbr    TEXT,               -- favorite at time of pick
            line        REAL,               -- points laid by the favorite (positive)
            confidence  INTEGER DEFAULT 0,
            result      TEXT,               -- 'W','L','P' or NULL until graded
            final_score TEXT,
            created_at  TEXT,
            PRIMARY KEY (season, week, event_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS slate (
            season   INTEGER NOT NULL,
            week     INTEGER NOT NULL,
            event_id TEXT    NOT NULL,
            matchup  TEXT,
            added_at TEXT,
            PRIMARY KEY (season, week, event_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tiebreaker (
            season INTEGER NOT NULL,
            week   INTEGER NOT NULL,
            value  INTEGER,
            PRIMARY KEY (season, week)
        )
    """)
    for stmt in ("ALTER TABLE picks ADD COLUMN entered_in_splash INTEGER DEFAULT 0",
                 "ALTER TABLE picks ADD COLUMN league TEXT",
                 "ALTER TABLE slate ADD COLUMN league TEXT"):
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass  # column already exists
    return conn

# ─────────────────────────────────────────────
# ESPN API
# ─────────────────────────────────────────────
BASE = "https://site.api.espn.com/apis/site/v2/sports/football"
LEAGUE_PATH = {"CFB": "college-football", "NFL": "nfl"}

@st.cache_data(ttl=300, show_spinner="Fetching games from ESPN…")
def fetch_scoreboard(league="CFB", year=None, week=None, seasontype=2, dates=None):
    params = {"limit": "400"}
    if league == "CFB":
        params["groups"] = "80"   # groups=80 → all of FBS
    if year and week:
        params.update({"dates": str(year), "seasontype": str(seasontype), "week": str(week)})
    elif dates:
        params["dates"] = dates   # YYYYMMDD-YYYYMMDD range (used for NFL history)
    r = requests.get(f"{BASE}/{LEAGUE_PATH[league]}/scoreboard", params=params, timeout=15)
    r.raise_for_status()
    return r.json()

@st.cache_data(ttl=3600, show_spinner="Loading game breakdown…")
def fetch_summary(event_id, league="CFB"):
    r = requests.get(f"{BASE}/{LEAGUE_PATH[league]}/summary",
                     params={"event": event_id}, timeout=15)
    r.raise_for_status()
    return r.json()

def implied_prob(moneyline):
    """American moneyline → implied win probability (0–1), or None."""
    try:
        ml = float(moneyline)
    except (TypeError, ValueError):
        return None
    if ml == 0:
        return None
    return (-ml) / (-ml + 100) if ml < 0 else 100 / (ml + 100)

def parse_game(event, league="CFB"):
    """Flatten one ESPN scoreboard event into a plain dict. Defensive: missing
    fields (odds don't exist for every game) come back as None."""
    comp = (event.get("competitions") or [{}])[0]
    g = {
        "league": league,
        "event_id": str(event.get("id", "")),
        "name": event.get("shortName") or event.get("name", ""),
        "date": event.get("date", ""),
        "completed": bool((event.get("status") or {}).get("type", {}).get("completed")),
        "status_detail": (event.get("status") or {}).get("type", {}).get("shortDetail", ""),
        "neutral_site": bool(comp.get("neutralSite")),
        "broadcast": "",
        "home": None, "away": None,
        "fav_abbr": None, "line": None, "over_under": None,
        "home_ml_prob": None, "away_ml_prob": None,
    }
    for b in comp.get("broadcasts") or []:
        names = b.get("names") or []
        if names:
            g["broadcast"] = names[0]
            break

    for c in comp.get("competitors") or []:
        team = c.get("team") or {}
        rank = (c.get("curatedRank") or {}).get("current")
        recs = {}
        for r in c.get("records") or []:
            key = r.get("type") or r.get("name") or ""
            recs[key] = r.get("summary", "")
        side = {
            "id": str(team.get("id", "")),   # needed for the core stats/FPI API
            "abbr": team.get("abbreviation", "?"),
            "name": team.get("shortDisplayName") or team.get("displayName", "?"),
            "full_name": team.get("displayName", ""),
            "location": team.get("location", ""),
            "rank": rank if rank and rank != 99 else None,
            "record": recs.get("total", ""),
            "score": c.get("score"),
            "winner": bool(c.get("winner")),
        }
        if c.get("homeAway") == "home":
            g["home"] = side
        else:
            g["away"] = side

    odds = (comp.get("odds") or [{}])[0]
    g["over_under"] = odds.get("overUnder")
    # details is e.g. "UGA -7.5" or "EVEN"; the most reliable favorite signal
    details = odds.get("details") or ""
    m = re.match(r"^([A-Z&'.\- ]+?)\s+(-?\d+(?:\.\d+)?)$", details.strip())
    if m:
        g["fav_abbr"] = m.group(1).strip()
        g["line"] = abs(float(m.group(2)))
    g["home_ml_prob"] = implied_prob((odds.get("homeTeamOdds") or {}).get("moneyLine"))
    g["away_ml_prob"] = implied_prob((odds.get("awayTeamOdds") or {}).get("moneyLine"))
    return g

def parse_kick(iso_str):
    try:
        return datetime.strptime(iso_str, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None

def kickoff_local(iso_str):
    dt = parse_kick(iso_str)
    if not dt:
        return iso_str
    dt = dt.astimezone(ET)
    return dt.strftime("%a %m/%d %I:%M %p ET").replace(" 0", " ")

# ─────────────────────────────────────────────
# LOCK TIMES — pool locks Saturday noon ET, or at kickoff if earlier.
# ─────────────────────────────────────────────
def lock_time(kickoff_iso):
    """Lock = min(kickoff, noon ET on this slate week's Saturday). The CFB
    week runs Tue–Mon, so a Sunday/Monday game belongs to the PREVIOUS
    Saturday's slate."""
    kick = parse_kick(kickoff_iso)
    if not kick:
        return None
    kick_et = kick.astimezone(ET)
    w = kick_et.weekday()                       # Mon=0 … Sun=6
    days_to_sat = -2 if w == 0 else 5 - w       # Mon→prev Sat; Sun→prev Sat (−1)
    sat = (kick_et + timedelta(days=days_to_sat)).date()
    sat_noon = datetime(sat.year, sat.month, sat.day, 12, 0, tzinfo=ET)
    return min(kick, sat_noon.astimezone(timezone.utc))

def is_locked(kickoff_iso, now=None):
    lt = lock_time(kickoff_iso)
    now = now or datetime.now(timezone.utc)
    return bool(lt and now >= lt)

def lock_label(kickoff_iso, now=None):
    lt = lock_time(kickoff_iso)
    if not lt:
        return ""
    now = now or datetime.now(timezone.utc)
    if now >= lt:
        return "🔒 locked"
    left = lt - now
    hrs = int(left.total_seconds() // 3600)
    if hrs >= 48:
        return f"locks {lt.astimezone(ET).strftime('%a %I:%M %p ET').replace(' 0', ' ')}"
    if hrs >= 1:
        return f"locks in {hrs}h {int(left.total_seconds() % 3600 // 60)}m"
    return f"locks in {int(left.total_seconds() // 60)}m"

# ─────────────────────────────────────────────
# PASTE-IMPORT MATCHING — match "Team A vs Team B" lines to real games.
# ─────────────────────────────────────────────
def _norm(s):
    s = re.sub(r"[#(].*?[)]|#\d+|\b\d+-\d+\b", " ", s)   # strip ranks & records
    s = re.sub(r"[^a-z0-9& ]", " ", s.lower())
    return " " + re.sub(r"\s+", " ", s).strip() + " "

def _aliases(side):
    out = set()
    for a in (side.get("full_name"), side.get("location"), side.get("name"), side.get("abbr")):
        if a and len(a) >= 3:
            out.add(_norm(a).strip())
    return out

def match_paste_lines(text, games):
    """Each non-empty line → the game it names, by finding team aliases inside
    the line. Score = (# sides matched, total alias length) so 'Ohio State'
    beats 'Ohio' and a line naming both teams beats one naming one."""
    matches, unmatched = {}, []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        line = _norm(raw)
        best, best_score = None, (0, 0)
        for g in games:
            sides_hit, alias_len = 0, 0
            for side in (g["home"], g["away"]):
                hit = max((len(a) for a in _aliases(side) if f" {a} " in line), default=0)
                if hit:
                    sides_hit += 1
                    alias_len += hit
            score = (sides_hit, alias_len)
            if score > best_score:
                best, best_score = g, score
        if best is None:
            # last resort: fuzzy against "away home" strings
            names = {f"{g['away']['name']} {g['home']['name']}": g for g in games}
            close = difflib.get_close_matches(line.strip(), list(names), n=1, cutoff=0.75)
            best = names.get(close[0]) if close else None
        if best:
            matches[best["event_id"]] = (raw.strip(), best)
        else:
            unmatched.append(raw.strip())
    return list(matches.values()), unmatched

# ─────────────────────────────────────────────
# GRADING
# ─────────────────────────────────────────────
def grade_pick(row, game):
    """Return ('W'|'L'|'P', 'AWAY 24–21 HOME') for a completed game, else (None, None)."""
    if not game or not game["completed"]:
        return None, None
    home, away = game["home"], game["away"]
    try:
        hs, as_ = int(home["score"]), int(away["score"])
    except (TypeError, ValueError):
        return None, None
    score_str = f"{away['abbr']} {as_}–{hs} {home['abbr']}"

    pick_is_home = row["pick_abbr"] == home["abbr"]
    pick_pts = hs if pick_is_home else as_
    opp_pts = as_ if pick_is_home else hs

    if row["pick_type"] == "ATS" and row["line"] is not None and row["fav_abbr"]:
        margin = pick_pts - opp_pts
        adj = margin - row["line"] if row["pick_abbr"] == row["fav_abbr"] else margin + row["line"]
        if adj > 0:
            return "W", score_str
        if adj < 0:
            return "L", score_str
        return "P", score_str

    if pick_pts > opp_pts:
        return "W", score_str
    if pick_pts < opp_pts:
        return "L", score_str
    return "P", score_str

# ─────────────────────────────────────────────
# PICK WRITES
# ─────────────────────────────────────────────
def upsert_pick(conn, season, week, g, side, opp, pick_type):
    # A changed pick resets result AND entered_in_splash — the Splash entry
    # no longer matches, so the banner should nag until it's re-entered.
    conn.execute("""
        INSERT INTO picks (season, week, event_id, matchup, kickoff,
            pick_abbr, pick_name, opp_abbr, opp_name, pick_type,
            fav_abbr, line, created_at, entered_in_splash, league)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,0,?)
        ON CONFLICT(season, week, event_id) DO UPDATE SET
            pick_abbr=excluded.pick_abbr, pick_name=excluded.pick_name,
            opp_abbr=excluded.opp_abbr, opp_name=excluded.opp_name,
            pick_type=excluded.pick_type, fav_abbr=excluded.fav_abbr,
            line=excluded.line, result=NULL, final_score=NULL,
            entered_in_splash=0, league=excluded.league
    """, (season, week, g["event_id"], g["name"], g["date"],
          side["abbr"], side["name"], opp["abbr"], opp["name"], pick_type,
          g["fav_abbr"], g["line"], datetime.now().isoformat(timespec="seconds"),
          g.get("league", "CFB")))

def favorite_side(g):
    """(favorite side, underdog side) from the line, falling back to
    moneyline probability; (None, None) when there's no signal."""
    if g["fav_abbr"]:
        if g["fav_abbr"] == g["home"]["abbr"]:
            return g["home"], g["away"]
        if g["fav_abbr"] == g["away"]["abbr"]:
            return g["away"], g["home"]
    hp, ap = g["home_ml_prob"], g["away_ml_prob"]
    if hp is not None and ap is not None and hp != ap:
        return (g["home"], g["away"]) if hp > ap else (g["away"], g["home"])
    return None, None

def fair_probs(g):
    """Best available true win probabilities (home, away).

    Raw moneyline-implied probabilities include the book's vig (they sum to
    ~104-105%), so normalize them to a fair 100%. With no moneyline, derive
    from the spread: margins are roughly normal with sd ≈ 13.2 (NFL) or
    ≈ 16.5 (CFB), so P(favorite wins) = Φ(line/sd)."""
    hp, ap = g["home_ml_prob"], g["away_ml_prob"]
    if hp and ap:
        return hp / (hp + ap), ap / (hp + ap)
    if g["line"] is not None:
        fav, _ = favorite_side(g)
        if fav:
            sd = 13.2 if g.get("league") == "NFL" else 16.5
            p = 0.5 * (1 + math.erf((g["line"] / sd) / math.sqrt(2)))
            return (p, 1 - p) if fav is g["home"] else (1 - p, p)
    return None, None

def recommend(g):
    """(recommended side, its win probability) or (None, None)."""
    hp, ap = fair_probs(g)
    if hp is None:
        fav, _ = favorite_side(g)
        return fav, None
    return (g["home"], hp) if hp >= ap else (g["away"], ap)


# ─────────────────────────────────────────────
# TEAM STRENGTH — ESPN's core API (verified live via scripts/probe_espn.py)
#
# FPI is a net-points rating: expected margin vs an average opponent on a
# neutral field, and it carries preseason priors — which is exactly what
# September needs, when box-score stats are a 2-game sample against
# whoever happened to be on the schedule. The same payload carries EPA
# per game for offense, defense and special teams.
#
# Note: ESPN's *box score* stats for the current season come back as zeros
# early in the year, so stat_pack() falls back to last season and says so.
# ─────────────────────────────────────────────
CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues"
HFA = {"CFB": 2.6, "NFL": 2.0}        # home-field worth, in points
MARGIN_SD = {"CFB": 16.5, "NFL": 13.2}  # sd of final margin around the spread
EDGE_MIN = 0.06                        # win-prob gap that counts as disagreement

def _core_get(url):
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=12)
        if r.status_code == 200:
            return r.json()
    except requests.RequestException:
        pass
    return None

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_power(league, team_id, season):
    """FPI + EPA for one team. {} when unavailable."""
    if not team_id:
        return {}
    d = _core_get(f"{CORE}/{LEAGUE_PATH[league]}/seasons/{season}/powerindex/{team_id}")
    if not d:
        return {}
    p = {x.get("name"): x.get("value") for x in d.get("predictives") or []}
    return {k: p.get(k) for k in
            ("fpi", "fpirank", "epaoffense", "epadefense", "epaspecialteams")}

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_team_stats(league, team_id, season):
    """Flatten core-API team statistics to {'category.statName': value}."""
    if not team_id:
        return {}
    d = _core_get(f"{CORE}/{LEAGUE_PATH[league]}/seasons/{season}/types/2/teams/{team_id}/statistics")
    if not d:
        return {}
    out = {}
    for cat in ((d.get("splits") or {}).get("categories") or []):
        cname = cat.get("name")
        for s in cat.get("stats") or []:
            out[f"{cname}.{s.get('name')}"] = s.get("value")
    return out

def stat_pack(league, team_id, season):
    """This season's stats if they've been populated, else last season's.
    Always reports which season and how many games it's based on."""
    cur = fetch_team_stats(league, team_id, season)
    games = cur.get("general.gamesPlayed") or 0
    if games and games > 0:
        return {"season": season, "games": int(games), "stats": cur, "current": True}
    prev = fetch_team_stats(league, team_id, season - 1)
    return {"season": season - 1, "games": int(prev.get("general.gamesPlayed") or 0),
            "stats": prev, "current": False}

def margin_to_prob(margin, league):
    """Point margin → win probability, normal around the margin."""
    sd = MARGIN_SD.get(league, 15.0)
    return 0.5 * (1 + math.erf((margin / sd) / math.sqrt(2)))

def fpi_probs(g):
    """(home, away) win probability from FPI alone — the second opinion."""
    season = int(g.get("season") or datetime.now().year)
    league = g.get("league", "CFB")
    h = fetch_power(league, g["home"].get("id"), season)
    a = fetch_power(league, g["away"].get("id"), season)
    if h.get("fpi") is None or a.get("fpi") is None:
        return None, None
    edge = h["fpi"] - a["fpi"] + (0 if g["neutral_site"] else HFA.get(league, 2.5))
    p_home = margin_to_prob(edge, league)
    return p_home, 1 - p_home

def market_vs_model(g):
    """Where FPI and the betting market disagree, and by how much.
    Returns (side FPI prefers, win-prob gap) or (None, None)."""
    mh, ma = fair_probs(g)
    fh, fa = fpi_probs(g)
    if mh is None or fh is None:
        return None, None
    gap = fh - mh                      # >0: FPI likes the home side more
    side = g["home"] if gap > 0 else g["away"]
    return side, abs(gap)

# ─────────────────────────────────────────────
# PLAIN ENGLISH — turn numbers into words a human reads once
# ─────────────────────────────────────────────
LEVERAGE_DOG_P = 0.45   # underdog win chance that makes a flip nearly free

def dog_prob(g):
    """The underdog's fair win probability, or None."""
    hp, ap = fair_probs(g)
    return min(hp, ap) if hp is not None else None

def confidence_word(p):
    if p is None:
        return "No line yet"
    if p >= 0.78:
        return "Safe"
    if p >= 0.60:
        return "Should win"
    return "Close call"

def worth_flipping(g):
    dp = dog_prob(g)
    return dp is not None and dp >= LEVERAGE_DOG_P and not g["completed"]

def why_text(g, summary=None):
    """The case for the underdog, in sentences. `summary` may be None or
    missing any key — every lookup degrades quietly."""
    fav, dog = favorite_side(g)
    if not dog:
        return []
    dp = dog_prob(g)
    out = []
    pct = f" — about {dp:.0%} to win outright" if dp else ""
    if g["line"] is not None:
        out.append(f"**{dog['name']}** are only a {g['line']:g}-point underdog{pct}.")
    elif dp:
        out.append(f"**{dog['name']}** are about {dp:.0%} to win outright.")
    if dog is g["home"] and not g["neutral_site"]:
        out.append("They're at home, usually worth about 2–3 points.")
    s = summary or {}
    key = "homeTeam" if dog is g["home"] else "awayTeam"
    proj = ((s.get("predictor") or {}).get(key) or {}).get("gameProjection")
    try:
        if proj is not None:
            out.append(f"ESPN's prediction model gives them {float(proj):.0f}%.")
    except (TypeError, ValueError):
        pass
    for block in s.get("lastFiveGames") or []:
        evs = block.get("events") or []
        if not evs:
            continue
        abbr = (block.get("team") or {}).get("abbreviation")
        who = dog["name"] if abbr == dog["abbr"] else fav["name"] if abbr == fav["abbr"] else None
        if who:
            wins = sum(1 for e in evs if str(e.get("gameResult", "")).upper().startswith("W"))
            out.append(f"{who} have won {wins} of their last {len(evs)}.")
    for block in s.get("injuries") or []:
        n = len(block.get("injuries") or [])
        if n and (block.get("team") or {}).get("abbreviation") == fav["abbr"]:
            out.append(f"{fav['name']} have {n} player(s) on the injury report.")
    return out


def fpi_lines(g):
    """FPI's read on the game, as sentences. Never raises."""
    try:
        season = int(g.get("season") or datetime.now().year)
        league = g.get("league", "CFB")
        h = fetch_power(league, g["home"].get("id"), season)
        a = fetch_power(league, g["away"].get("id"), season)
    except Exception:
        return []
    if h.get("fpi") is None or a.get("fpi") is None:
        return []
    out = []
    for side, pw in ((g["home"], h), (g["away"], a)):
        rank = f" (#{int(pw['fpirank'])})" if pw.get("fpirank") else ""
        out.append(f"{side['name']}: FPI {pw['fpi']:+.1f}{rank}"
                   + (f", EPA {pw['epaoffense']:+.1f} off / {pw['epadefense']:+.1f} def"
                      if pw.get("epaoffense") is not None else ""))
    side, gap = market_vs_model(g)
    if side and gap and gap >= EDGE_MIN:
        out.append(f"**FPI likes {side['name']} more than the betting line does** "
                   f"— about {gap:.0%} more likely to win than the market implies.")
    elif side:
        out.append("FPI and the betting line agree on this one.")
    return out

STAT_ROWS = [
    ("Points / game", "scoring.totalPointsPerGame", "{:.1f}"),
    ("Yards / game", "passing.yardsPerGame", "{:.1f}"),
    ("Yards / pass att", "passing.yardsPerPassAttempt", "{:.1f}"),
    ("Yards / rush att", "rushing.yardsPerRushAttempt", "{:.1f}"),
    ("3rd down %", "miscellaneous.thirdDownConvPct", "{:.1f}%"),
    ("Red zone TD %", "miscellaneous.redzoneTouchdownPct", "{:.1f}%"),
    ("Turnover margin", "miscellaneous.turnOverDifferential", "{:+.0f}"),
    ("Sacks (defense)", "defensive.sacks", "{:.0f}"),
]

def render_stats(g):
    """Side-by-side numbers, honest about what season they're from."""
    league = g.get("league", "CFB")
    season = int(g.get("season") or datetime.now().year)
    try:
        packs = {side["abbr"]: stat_pack(league, side.get("id"), season)
                 for side in (g["away"], g["home"])}
    except Exception as e:
        st.caption(f"Couldn't load stats: {e}")
        return

    for ln in fpi_lines(g):
        st.markdown(f"- {ln}")

    rows = []
    for label, key, fmt in STAT_ROWS:
        row = {"": label}
        any_val = False
        for side in (g["away"], g["home"]):
            v = packs[side["abbr"]]["stats"].get(key)
            try:
                row[side["abbr"]] = fmt.format(float(v))
                any_val = True
            except (TypeError, ValueError):
                row[side["abbr"]] = "—"
        if any_val:
            rows.append(row)
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        notes = []
        for side in (g["away"], g["home"]):
            pk = packs[side["abbr"]]
            if pk["games"]:
                notes.append(f"{side['abbr']}: {pk['season']} season, {pk['games']} games"
                             + ("" if pk["current"] else " (this season's box scores "
                                                         "aren't populated yet)"))
        if notes:
            st.caption(" · ".join(notes))
    else:
        st.caption("ESPN has no box-score stats for these teams yet.")


def flip_score(g):
    """How live the underdog really is: the market's read on the dog,
    blended 50/50 with FPI's when FPI has an opinion. Higher = the flip
    costs less. None when there's nothing to go on."""
    dp = dog_prob(g)
    if dp is None:
        return None
    _fav, dog = favorite_side(g)
    if dog is None:
        return None
    try:
        fh, fa = fpi_probs(g)
    except Exception:
        fh = fa = None
    if fh is None:
        return dp
    fpi_dog = fh if dog is g["home"] else fa
    return 0.5 * dp + 0.5 * fpi_dog

def rank_flips(candidates):
    """Flip candidates, best first, as (score, game, underdog)."""
    scored = []
    for g in candidates:
        if g["completed"] or is_locked(g["date"]):
            continue      # can't act on it anyway
        sc = flip_score(g)
        if sc is None:
            continue
        scored.append((sc, g, favorite_side(g)[1]))
    scored.sort(key=lambda t: -t[0])
    return scored

FLIP_TAKE = 3          # never recommend more than this
FLIP_STRONG = 0.47     # a genuine coin flip
FLIP_FLOOR = 0.45      # the least you'd accept if nothing is a true 50/50

def recommended_flips(scored):
    """The 2-3 flips actually worth making. Fewer when the week is chalky."""
    strong = [t for t in scored if t[0] >= FLIP_STRONG][:FLIP_TAKE]
    if strong:
        return strong
    return scored[:1] if scored and scored[0][0] >= FLIP_FLOOR else []

# ─────────────────────────────────────────────
# SETTINGS — tucked in the sidebar, closed by default on a phone
# ─────────────────────────────────────────────
now = datetime.now()
default_season = now.year if now.month >= 8 else now.year - 1
PICK_TYPE = "SU"   # this league is straight up

with st.sidebar:
    st.markdown("## Settings")
    show_numbers = st.toggle("Show percentages", value=False,
                             help="Adds win % next to every pick.")
    edit_locked = st.toggle("Edit locked picks", value=False,
                            help="Change picks after the Saturday-noon lock.")
    st.divider()
    use_current = st.toggle("This week (automatic)", value=True)
    season = st.number_input("Season", 2020, 2030, default_season, disabled=use_current)
    week = st.selectbox("Week", list(range(1, 17)), disabled=use_current)
    if st.button("🔄 Reload games"):
        fetch_scoreboard.clear()
        fetch_summary.clear()
        st.rerun()
    st.divider()
    if not sync_enabled():
        st.caption("⚠️ Picks are not backed up — add GITHUB_TOKEN and "
                   "GITHUB_REPO in this app's Secrets.")
    else:
        _ok, _why = verify_token()
        st.caption("☁️ Picks saved to GitHub."
                   if _ok else f"⚠️ GitHub rejected the token — {_why}")

# ─────────────────────────────────────────────
# LOAD GAMES
# ─────────────────────────────────────────────
try:
    data = fetch_scoreboard("CFB") if use_current else fetch_scoreboard("CFB", int(season), int(week))
except requests.RequestException as e:
    st.error(f"Couldn't reach ESPN: {e}")
    st.stop()

api_week = (data.get("week") or {}).get("number")
api_season = ((data.get("season") or {}).get("year")) or ((data.get("leagues") or [{}])[0].get("season") or {}).get("year")
cur_season = int(api_season) if use_current and api_season else int(season)
cur_week = int(api_week) if use_current and api_week else int(week)

games = [parse_game(e, "CFB") for e in data.get("events") or []]

# NFL runs on its own week numbers, so for the current pool just take its
# current week; when browsing history, fetch by the CFB week's date span.
try:
    if use_current:
        nfl_data = fetch_scoreboard("NFL")
    else:
        kicks = sorted(k for k in (parse_kick(g["date"]) for g in games) if k)
        nfl_data = {"events": []}
        if kicks:
            span = f"{kicks[0]:%Y%m%d}-{kicks[-1] + timedelta(days=2):%Y%m%d}"
            nfl_data = fetch_scoreboard("NFL", dates=span)
    games += [parse_game(e, "NFL") for e in nfl_data.get("events") or []]
except requests.RequestException:
    st.caption("⚠️ NFL games unavailable right now — showing college only.")

games = [g for g in games if g["home"] and g["away"]]
for g in games:
    g["season"] = cur_season          # the stats/FPI endpoints are season-scoped
games_by_id = {g["event_id"]: g for g in games}

conn = get_conn()

@st.cache_resource
def _ensure_remote_copy():
    """No database in the repo yet (first boot after the secrets go in)?
    Push one now — otherwise a working token looks exactly like a broken
    one until something happens to be saved."""
    if not sync_enabled():
        return "off"
    try:
        r = requests.get(f"https://api.github.com/repos/{gh_repo()}/contents/{DB_PATH}",
                         headers=gh_headers(), timeout=15)
    except requests.RequestException:
        return "unreachable"
    if r.status_code == 404:
        return "created" if push_db_to_github() else "failed"
    return "present" if r.status_code == 200 else _gh_reason(r)

_ensure_remote_copy()

pick_rows = pd.read_sql_query(
    "SELECT * FROM picks WHERE season=? AND week=?", conn, params=(cur_season, cur_week))
picks_by_id = {r["event_id"]: r for _, r in pick_rows.iterrows()}
slate_rows = pd.read_sql_query(
    "SELECT * FROM slate WHERE season=? AND week=? ORDER BY added_at, rowid", conn, params=(cur_season, cur_week))
slate_ids = list(slate_rows["event_id"])
slate_games = [games_by_id[eid] for eid in slate_ids if eid in games_by_id]

def add_to_pool(g):
    return conn.execute(
        "INSERT OR IGNORE INTO slate (season, week, event_id, matchup, added_at, league) "
        "VALUES (?,?,?,?,?,?)",
        (cur_season, cur_week, g["event_id"], g["name"],
         datetime.now().isoformat(timespec="seconds"), g.get("league", "CFB")))

_auto_graded = 0
for _eid, _r in picks_by_id.items():
    if _r["result"] is None:
        _res, _score = grade_pick(_r, games_by_id.get(_eid))
        if _res:
            conn.execute("UPDATE picks SET result=?, final_score=? "
                         "WHERE season=? AND week=? AND event_id=?",
                         (_res, _score, cur_season, cur_week, _eid))
            _auto_graded += 1
if _auto_graded:
    save(conn)
    pick_rows = pd.read_sql_query(
        "SELECT * FROM picks WHERE season=? AND week=?", conn,
        params=(cur_season, cur_week))
    picks_by_id = {r["event_id"]: r for _, r in pick_rows.iterrows()}

if st.session_state.get("sync_failed"):
    c1, c2 = st.columns([4, 1])
    _why = st.session_state.get("sync_error", "")
    c1.warning("⚠️ Some picks aren't backed up yet — they'd be lost if the app "
               "restarts." + (f" GitHub said: {_why}" if _why else ""))
    if c2.button("Retry"):
        if push_db_to_github():
            st.session_state["sync_failed"] = False
            st.rerun()
        else:
            st.error("Still can't reach GitHub. Check GITHUB_TOKEN in Secrets.")

# ─────────────────────────────────────────────
# HEADER — one line that says where the week stands
# ─────────────────────────────────────────────
n_picked = sum(1 for eid in slate_ids if eid in picks_by_id)
flips = [g for g in slate_games if worth_flipping(g)]
open_games = [g for g in slate_games if not is_locked(g["date"])]
next_lock = (lock_label(min(open_games,
                            key=lambda g: lock_time(g["date"]) or datetime.max.replace(tzinfo=timezone.utc)
                            )["date"]) if open_games else "all locked")

st.markdown(f"# Week {cur_week}")
if slate_games:
    bits = [f"**{n_picked} of {len(slate_games)}** picked"]
    if flips:
        bits.append(f"**{len(flips)}** worth a look")
    bits.append(next_lock)
    st.markdown(" · ".join(bits))

# ─────────────────────────────────────────────
# LOAD THIS WEEK'S GAMES
# ─────────────────────────────────────────────
with st.expander("➕ Load this week's games", expanded=not slate_games):
    st.caption("Send screenshots of the Splash board to Claude, then paste the "
               "list it gives back — one game per line.")
    with st.form("import_form"):
        paste = st.text_area("Game list", height=140, label_visibility="collapsed",
                             placeholder="Ohio State vs Texas\nPackers vs Vikings\n…")
        submitted = st.form_submit_button("Add these games")
    if submitted and paste.strip():
        matched, unmatched = match_paste_lines(paste, games)
        added = sum(add_to_pool(g).rowcount for _line, g in matched)
        if added:
            save(conn)
        st.success(f"Found {len(matched)} game(s), added {added}.")
        if unmatched:
            st.warning("Couldn't find these — add them under More → All games:\n\n- "
                       + "\n- ".join(unmatched))
        if added:
            st.rerun()

# ─────────────────────────────────────────────
# THE PICK LIST — the whole point of the app
# ─────────────────────────────────────────────
if not slate_games:
    st.info("Load this week's games above to get started.")
else:
    unpicked = [g for g in slate_games if g["event_id"] not in picks_by_id
                and not is_locked(g["date"]) and recommend(g)[0]]
    if unpicked:
        if st.button(f"✅ Pick all {len(unpicked)} games for me", type="primary",
                     width="stretch"):
            for g in unpicked:
                side, _p = recommend(g)
                opp = g["away"] if side is g["home"] else g["home"]
                upsert_pick(conn, cur_season, cur_week, g, side, opp, PICK_TYPE)
            save(conn)
            st.rerun()

    # Six "worth flipping" games is a list, not a decision — rank them and
    # name the two or three actually worth taking.
    flip_ranked = rank_flips([g for g in slate_games if worth_flipping(g)])
    take = recommended_flips(flip_ranked)
    take_ids = {g["event_id"] for _sc, g, _dog in take}
    if take:
        names = ", ".join(f"**{dog['name']}**" for _sc, _g, dog in take)
        lead = "Flip this one" if len(take) == 1 else f"Flip these {len(take)}"
        st.markdown(f"### 🔄 {lead}: {names}")
        st.caption("The closest games on your card. Taking the underdog here "
                   "costs almost nothing over a season but separates you from "
                   "everyone riding the chalk this week. Everything else: "
                   "leave it alone.")
    elif flip_ranked:
        st.caption("No flip worth making this week — every close game is still "
                   "leaning the favorite's way. Ride the chalk.")

    # Recommended flips first, then the rest of the close ones, then by kickoff.
    ordered = sorted(slate_games,
                     key=lambda g: (g["event_id"] not in take_ids,
                                    not worth_flipping(g), g["date"], g["name"]))
    for g in ordered:
        eid = g["event_id"]
        r = picks_by_id.get(eid)
        rec_side, rec_p = recommend(g)
        locked = is_locked(g["date"])
        flip = worth_flipping(g)

        if r is not None:
            pick_abbr = r["pick_abbr"]
            picked = g["home"] if pick_abbr == g["home"]["abbr"] else g["away"]
            other = g["away"] if picked is g["home"] else g["home"]
            headline = (f"<span class='pick-team'>{picked['name']}</span>"
                        f"<span class='pick-opp'> over {other['name']}</span>")
            p_for_pick = None
            hp, ap = fair_probs(g)
            if hp is not None:
                p_for_pick = hp if picked is g["home"] else ap
            if r["result"]:
                sub = {"W": "✅ Won", "L": "❌ Lost", "P": "Push"}.get(r["result"], "")
                if r["final_score"]:
                    sub += f" · {r['final_score']}"
            else:
                sub = confidence_word(p_for_pick)
                if show_numbers and p_for_pick is not None:
                    sub += f" · {p_for_pick:.0%}"
        else:
            picked = other = None
            headline = (f"<span class='pick-none'>No pick yet</span>"
                        f"<span class='pick-opp'> — {g['away']['name']} at {g['home']['name']}</span>")
            if g["completed"]:
                sub = "Missed — game already final"
            else:
                sub = confidence_word(rec_p)
                if rec_side:
                    sub = f"Suggested: {rec_side['name']} · {sub}"

        # The chip names the alternative — "worth flipping" alone doesn't
        # say flip to WHAT, which is the only thing you need to know here.
        chips = ""
        alt = other if r is not None else (favorite_side(g)[1] or g["away"])
        take_this = eid in take_ids
        if take_this and alt:
            chips += f"<span class='chip chip-flip'>🔄 FLIP TO {alt['name'].upper()}</span>"
        elif flip and alt:
            chips += "<span class='chip chip-close'>close game</span>"
        if flip and alt:
            # Two cached API calls per game — worth it for the handful of
            # close games, not for all 32 on every rerun.
            try:
                fpi_side, fpi_gap = market_vs_model(g)
            except Exception:
                fpi_side = fpi_gap = None
            if fpi_side is not None and fpi_gap and fpi_gap >= EDGE_MIN:
                chips += (f"<span class='chip chip-edge'>📈 FPI likes "
                          f"{fpi_side['name']}</span>")
        if r is not None and rec_side and pick_abbr != rec_side["abbr"] and not flip:
            chips += "<span class='chip chip-risk'>⚠️ risky change</span>"
        when = "Final" if g["completed"] else kickoff_local(g["date"])
        if locked and not g["completed"]:
            when += " · 🔒 locked"

        # A flip candidate should explain itself without being tapped.
        if flip and not g["completed"]:
            dp = dog_prob(g)
            if dp is not None and alt:
                sub += f" · {alt['name']} {dp:.0%} to win"

        st.markdown(f"""
<div class='pick-card'>
  <div class='pick-line'>{headline}{chips}</div>
  <div class='pick-sub'>{sub} · {when}</div>
</div>""", unsafe_allow_html=True)

        if g["completed"]:
            continue
        can_change = (not locked) or edit_locked

        def switch_button(container, key_suffix=""):
            """Change this pick. Visible on flip candidates; tucked inside
            Details everywhere else — the app already decided those."""
            if r is not None:
                if container.button(f"Switch to {other['name']}",
                                    key=f"sw_{eid}{key_suffix}",
                                    disabled=not can_change, width="stretch"):
                    upsert_pick(conn, cur_season, cur_week, g, other, picked, PICK_TYPE)
                    save(conn)
                    st.rerun()
            else:
                b1, b2 = container.columns(2)
                for col, side in ((b1, g["away"]), (b2, g["home"])):
                    if col.button(side["abbr"], key=f"pk_{eid}_{side['abbr']}{key_suffix}",
                                  disabled=not can_change, width="stretch"):
                        opp = g["home"] if side is g["away"] else g["away"]
                        upsert_pick(conn, cur_season, cur_week, g, side, opp, PICK_TYPE)
                        save(conn)
                        st.rerun()

        if take_this:
            switch_button(st.container())
        with st.expander("Details"):
            if not take_this:
                switch_button(st.container(), "_d")
            if flip:
                try:
                    summary = fetch_summary(eid, g.get("league", "CFB"))
                except requests.RequestException:
                    summary = None
                for ln in why_text(g, summary):
                    st.markdown(f"- {ln}")
            render_stats(g)

    # ── Copy into Splash ──
    st.divider()
    st.markdown("### Enter in Splash")
    picked_games = [g for g in slate_games if g["event_id"] in picks_by_id]
    unentered = sum(1 for eid in slate_ids
                    if eid in picks_by_id and not picks_by_id[eid].get("entered_in_splash"))
    if not picked_games:
        st.caption("Make your picks above and the list to copy shows up here.")
    else:
        tb_row = conn.execute("SELECT value FROM tiebreaker WHERE season=? AND week=?",
                              (cur_season, cur_week)).fetchone()
        tb_saved = tb_row[0] if tb_row else None
        lines = [f"{i:2d}. {picks_by_id[g['event_id']]['pick_name']} over "
                 f"{picks_by_id[g['event_id']]['opp_name']}"
                 for i, g in enumerate(picked_games, 1)]
        if tb_saved is not None:
            lines.append(f"Tiebreaker: {tb_saved}")
        st.code("\n".join(lines), language=None)

        tb_game = max((g for g in slate_games if g["over_under"]),
                      key=lambda g: g["date"], default=None)
        if tb_game:
            st.caption(f"💡 Vegas expects about **{tb_game['over_under']}** total points "
                       f"in {tb_game['name']} — a good tiebreaker guess.")
        t1, t2 = st.columns([2, 1])
        tb_default = (int(round(float(tb_game["over_under"]))) if tb_game and tb_saved is None
                      else int(tb_saved) if tb_saved is not None else 44)
        tb_new = t1.number_input("Tiebreaker (total points)", 0, 200, tb_default)
        if t2.button("Save", width="stretch"):
            conn.execute("INSERT INTO tiebreaker (season, week, value) VALUES (?,?,?) "
                         "ON CONFLICT(season, week) DO UPDATE SET value=excluded.value",
                         (cur_season, cur_week, int(tb_new)))
            save(conn)
            st.rerun()
        if unentered:
            st.warning(f"{unentered} pick(s) not marked as entered in Splash.")
            if st.button("✅ I entered them all in Splash", width="stretch"):
                conn.execute("UPDATE picks SET entered_in_splash=1 WHERE season=? AND week=?",
                             (cur_season, cur_week))
                save(conn)
                st.rerun()
        else:
            st.success("All picks entered in Splash.")

# ─────────────────────────────────────────────
# MORE — everything that isn't picking this week
# ─────────────────────────────────────────────
st.divider()
with st.expander("More — results, all games, stats"):
    t_res, t_all, t_season = st.tabs(["This week's results", "All games", "Season"])

    with t_res:
        if pick_rows.empty:
            st.caption("No picks yet this week.")
        else:
            if st.button("Update results"):
                changed = 0
                for _, row in pick_rows.iterrows():
                    res, score = grade_pick(row, games_by_id.get(row["event_id"]))
                    if res:
                        conn.execute("UPDATE picks SET result=?, final_score=? "
                                     "WHERE season=? AND week=? AND event_id=?",
                                     (res, score, cur_season, cur_week, row["event_id"]))
                        changed += 1
                if changed:
                    save(conn)
                st.rerun()
            graded = pick_rows[pick_rows["result"].notna()]
            if len(graded):
                w = (graded["result"] == "W").sum()
                l = (graded["result"] == "L").sum()
                st.markdown(f"### {w}–{l} this week")
            shown = pick_rows[["pick_name", "opp_name", "result", "final_score"]].copy()
            shown.columns = ["Pick", "Over", "W/L", "Final"]
            st.dataframe(shown, hide_index=True, width="stretch")
            rm = st.selectbox("Remove a pick", ["—"] + [f"{r['pick_name']} over {r['opp_name']}"
                                                        for _, r in pick_rows.iterrows()])
            if rm != "—" and st.button("Remove"):
                target = pick_rows[pick_rows.apply(
                    lambda r: f"{r['pick_name']} over {r['opp_name']}" == rm, axis=1)]
                for _, r in target.iterrows():
                    conn.execute("DELETE FROM picks WHERE season=? AND week=? AND event_id=?",
                                 (cur_season, cur_week, r["event_id"]))
                save(conn)
                st.rerun()

    with t_all:
        st.caption("Every game this week — add any the import missed.")
        q = st.text_input("Search team", placeholder="e.g. Michigan")
        shown = games
        if q.strip():
            ql = q.strip().lower()
            shown = [g for g in games
                     if ql in g["home"]["name"].lower() or ql in g["away"]["name"].lower()
                     or ql in g["home"]["abbr"].lower() or ql in g["away"]["abbr"].lower()]
        for g in sorted(shown, key=lambda g: g["date"])[:60]:
            in_slate = g["event_id"] in slate_ids
            c1, c2 = st.columns([4, 1])
            c1.markdown(f"**{g['away']['name']}** at **{g['home']['name']}** "
                        f"<span class='pick-sub'>{g['league']} · {kickoff_local(g['date'])}</span>",
                        unsafe_allow_html=True)
            if in_slate:
                if c2.button("Remove", key=f"rm_{g['event_id']}", width="stretch"):
                    conn.execute("DELETE FROM slate WHERE season=? AND week=? AND event_id=?",
                                 (cur_season, cur_week, g["event_id"]))
                    save(conn)
                    st.rerun()
            elif c2.button("Add", key=f"ad_{g['event_id']}", width="stretch"):
                add_to_pool(g)
                save(conn)
                st.rerun()

    with t_season:
        all_rows = pd.read_sql_query(
            "SELECT * FROM picks WHERE season=? ORDER BY week, kickoff", conn, params=(cur_season,))
        if all_rows.empty:
            st.caption("No picks recorded yet this season.")
        else:
            graded = all_rows[all_rows["result"].notna()]
            w = (graded["result"] == "W").sum()
            l = (graded["result"] == "L").sum()
            c1, c2 = st.columns(2)
            c1.metric("Season record", f"{w}–{l}")
            c2.metric("Win %", f"{w / (w + l):.0%}" if (w + l) else "—")
            by_week = (graded.groupby("week")["result"]
                       .apply(lambda s: f"{(s == 'W').sum()}–{(s == 'L').sum()}")
                       .rename("record").reset_index())
            if len(by_week):
                st.dataframe(by_week, hide_index=True, width="stretch")

conn.close()
