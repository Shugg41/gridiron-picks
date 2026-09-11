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

.game-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 0.7rem 0.9rem;
    margin-bottom: 0.35rem;
}
.game-meta  { color: var(--muted); font-size: 0.78rem; }
.team-line  { font-size: 1.02rem; font-weight: 600; }
.rank-badge { color: var(--accent); font-size: 0.8rem; font-weight: 700; margin-right: 0.25rem; }
.rec        { color: var(--muted); font-size: 0.8rem; font-weight: 400; }
.odds-line  { color: var(--field); font-size: 0.85rem; margin-top: 0.15rem; }
.picked     { color: var(--accent); font-weight: 700; }
.res-W      { color: var(--field); font-weight: 700; }
.res-L      { color: var(--loss); font-weight: 700; }
.res-P      { color: var(--push); font-weight: 700; }
.tag {
    display: inline-block; font-size: 0.72rem; font-weight: 700;
    border-radius: 6px; padding: 0.05rem 0.4rem; margin-left: 0.35rem;
    border: 1px solid var(--border); color: var(--muted);
}
.tag-safe   { color: var(--field); border-color: var(--field); }
.tag-toss   { color: var(--accent); border-color: var(--accent); }
.tag-road   { color: var(--push); border-color: var(--push); }
.tag-dog    { color: var(--loss); border-color: var(--loss); }
.tag-lock   { color: var(--muted); }

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

def push_db_to_github():
    if not sync_enabled():
        return True  # local-only mode: a local commit is all there is
    try:
        url = f"https://api.github.com/repos/{gh_repo()}/contents/{DB_PATH}"
        r = requests.get(url, headers=gh_headers(), timeout=15)
        sha = r.json().get("sha") if r.status_code == 200 else None
        with open(DB_PATH, "rb") as f:
            payload = {"message": f"Update picks db {datetime.now(ET):%Y-%m-%d %H:%M}",
                       "content": base64.b64encode(f.read()).decode()}
        if sha:
            payload["sha"] = sha
        r = requests.put(url, headers=gh_headers(), json=payload, timeout=20)
        return r.status_code in (200, 201)
    except Exception:
        return False

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
# SHARED CARD RENDERING
# ─────────────────────────────────────────────
def team_html(side, is_fav, prob):
    rank = f"<span class='rank-badge'>#{side['rank']}</span>" if side["rank"] else ""
    rec = f"<span class='rec'> ({side['record']})</span>" if side["record"] else ""
    fav = " ★" if is_fav else ""
    pct = f" · {prob:.0%}" if prob else ""
    return f"{rank}{side['name']}{fav}{rec}<span class='rec'>{pct}</span>"

LEVERAGE_DOG_P = 0.45   # dog win prob at which a contrarian flip is "cheap"

def dog_prob(g):
    """The underdog's fair win probability, or None."""
    hp, ap = fair_probs(g)
    return min(hp, ap) if hp is not None else None

def game_tags(g, my_pick_abbr):
    tags = []
    fav, dog = favorite_side(g)
    fav_prob = None
    if fav:
        fav_prob = g["home_ml_prob"] if fav is g["home"] else g["away_ml_prob"]
    if fav_prob is not None:
        if fav_prob >= 0.78:
            tags.append("<span class='tag tag-safe'>🔒 safe</span>")
        elif fav_prob < 0.60:
            tags.append("<span class='tag tag-toss'>⚠️ toss-up</span>")
    dp = dog_prob(g)
    if dp is not None and dp >= LEVERAGE_DOG_P and not g["completed"]:
        tags.append("<span class='tag tag-toss'>💎 leverage</span>")
    if fav and fav is g["away"] and not g["neutral_site"]:
        tags.append("<span class='tag tag-road'>🛣 road fav</span>")
    if my_pick_abbr and dog and my_pick_abbr == dog["abbr"]:
        tags.append("<span class='tag tag-dog'>🎲 on the dog</span>")
    return "".join(tags)

def render_breakdown(g):
    """On-demand analytics from ESPN's game summary endpoint."""
    try:
        s = fetch_summary(g["event_id"], g.get("league", "CFB"))
    except requests.RequestException as e:
        st.caption(f"Couldn't load breakdown: {e}")
        return
    pred = s.get("predictor") or {}
    hp = (pred.get("homeTeam") or {}).get("gameProjection")
    ap = (pred.get("awayTeam") or {}).get("gameProjection")
    if hp or ap:
        try:
            st.markdown(f"**ESPN matchup predictor:** {g['away']['name']} "
                        f"{float(ap):.0f}% · {g['home']['name']} {float(hp):.0f}%")
        except (TypeError, ValueError):
            pass
    for team_block in s.get("lastFiveGames") or []:
        t = (team_block.get("team") or {})
        tname = t.get("shortDisplayName") or t.get("displayName", "?")
        results = []
        for ev in (team_block.get("events") or [])[:5]:
            res = ev.get("gameResult", "?")
            opp = ((ev.get("opponent") or {}).get("abbreviation")
                   or (ev.get("opponent") or {}).get("shortDisplayName") or "")
            results.append(f"{res} {ev.get('atVs', '')} {opp}".strip())
        if results:
            wl = "".join(r[0] for r in results)
            st.markdown(f"**{tname} last {len(results)}:** `{wl}` — " + ", ".join(results))
    inj_bits = []
    for team_block in s.get("injuries") or []:
        t = (team_block.get("team") or {})
        n = len(team_block.get("injuries") or [])
        if n:
            inj_bits.append(f"{t.get('shortDisplayName', '?')}: {n} listed")
    if inj_bits:
        st.markdown("**Injuries:** " + " · ".join(inj_bits))
    if not (hp or ap) and not s.get("lastFiveGames"):
        st.caption("No extra data from ESPN for this game yet.")

# ─────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────
now = datetime.now()
default_season = now.year if now.month >= 8 else now.year - 1

with st.sidebar:
    st.markdown("## 🏈 Gridiron Picks")
    pick_type = st.radio("League pick style", ["SU", "ATS"], horizontal=True,
                         format_func=lambda x: "Straight up" if x == "SU" else "Against the spread")
    edit_locked = st.toggle("Edit locked picks", value=False,
                            help="Lets you change picks after the Saturday-noon lock (for corrections).")
    st.divider()
    use_current = st.toggle("Current week (auto)", value=True)
    season = st.number_input("Season", 2020, 2030, default_season, disabled=use_current)
    week = st.selectbox("Week", list(range(1, 17)), disabled=use_current)
    if st.button("🔄 Refresh data"):
        fetch_scoreboard.clear()
        fetch_summary.clear()
        st.rerun()
    st.divider()
    if sync_enabled():
        st.caption("☁️ Picks back up to GitHub on every save.")
    else:
        st.caption("⚠️ Local-only mode — add GITHUB_TOKEN and GITHUB_REPO "
                   "to the app's Secrets so picks survive restarts.")

# ─────────────────────────────────────────────
# FETCH & PARSE
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
# current week; when browsing history, fetch by the CFB week's date span
# (padded through Monday night) instead of guessing a week offset.
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
games_by_id = {g["event_id"]: g for g in games}

conn = get_conn()
pick_rows = pd.read_sql_query(
    "SELECT * FROM picks WHERE season=? AND week=?", conn, params=(cur_season, cur_week))
picks_by_id = {r["event_id"]: r for _, r in pick_rows.iterrows()}
slate_rows = pd.read_sql_query(
    "SELECT * FROM slate WHERE season=? AND week=? ORDER BY added_at", conn, params=(cur_season, cur_week))
slate_ids = list(slate_rows["event_id"])

if st.session_state.get("sync_failed"):
    c1, c2 = st.columns([4, 1])
    c1.warning("⚠️ Some changes aren't backed up to GitHub yet — they'll be lost if the app restarts.")
    if c2.button("Retry sync"):
        if push_db_to_github():
            st.session_state["sync_failed"] = False
            st.rerun()
        else:
            st.error("Still can't reach GitHub. Check GITHUB_TOKEN in the app's Secrets.")

st.markdown(f"# Week {cur_week} · {cur_season}")

n_picked = sum(1 for eid in slate_ids if eid in picks_by_id)
tab_pool, tab_board, tab_picks, tab_season = st.tabs(
    [f"🎯 My Pool ({n_picked}/{len(slate_ids)})" if slate_ids else "🎯 My Pool",
     "📋 Game board", "✅ My Picks", "📈 Season"])

def render_card(g, key_prefix, in_pool):
    home, away = g["home"], g["away"]
    fav, _dog = favorite_side(g)
    my = picks_by_id.get(g["event_id"])
    my_pick = my["pick_abbr"] if my is not None else None
    locked = is_locked(g["date"])

    odds_bits = []
    if g["fav_abbr"] and g["line"] is not None:
        odds_bits.append(f"{g['fav_abbr']} −{g['line']:g}")
    if g["over_under"]:
        odds_bits.append(f"O/U {g['over_under']}")
    if in_pool and not g["completed"]:
        rec_side, rec_p = recommend(g)
        if rec_side and rec_p is not None:
            odds_bits.append(f"model: {rec_side['abbr']} {rec_p:.0%}")
    odds_txt = " · ".join(odds_bits) if odds_bits else "no line yet"
    tv = f" · {g['broadcast']}" if g["broadcast"] else ""
    where = " · neutral site" if g["neutral_site"] else ""
    status = g["status_detail"] if g["completed"] else kickoff_local(g["date"])
    lock_txt = "" if g["completed"] else f" · <span class='tag tag-lock'>{lock_label(g['date'])}</span>"
    pick_txt = f" &nbsp;·&nbsp; <span class='picked'>my pick: {my_pick}</span>" if my_pick else ""

    st.markdown(f"""
<div class='game-card'>
  <div class='game-meta'>{g['league']} · {status}{tv}{where}{lock_txt}</div>
  <div class='team-line'>{team_html(away, fav is away, g['away_ml_prob'])}</div>
  <div class='team-line'>at {team_html(home, fav is home, g['home_ml_prob'])}{game_tags(g, my_pick)}</div>
  <div class='odds-line'>{odds_txt}{pick_txt}</div>
</div>""", unsafe_allow_html=True)

    if not g["completed"]:
        pickable = (not locked) or edit_locked
        cols = st.columns([1, 1, 1, 2])
        for col, side, opp in ((cols[0], away, home), (cols[1], home, away)):
            label = f"✔ {side['abbr']}" if my_pick == side["abbr"] else side["abbr"]
            if col.button(label, key=f"{key_prefix}_pick_{g['event_id']}_{side['abbr']}",
                          disabled=not pickable):
                upsert_pick(conn, cur_season, cur_week, g, side, opp, pick_type)
                save(conn)
                st.rerun()
        with cols[2]:
            if in_pool:
                if st.button("➖ Pool", key=f"{key_prefix}_unpool_{g['event_id']}"):
                    conn.execute("DELETE FROM slate WHERE season=? AND week=? AND event_id=?",
                                 (cur_season, cur_week, g["event_id"]))
                    save(conn)
                    st.rerun()
            else:
                in_slate = g["event_id"] in slate_ids
                if st.button("✔ In pool" if in_slate else "➕ Pool",
                             key=f"{key_prefix}_pool_{g['event_id']}", disabled=in_slate):
                    conn.execute("INSERT OR IGNORE INTO slate (season, week, event_id, matchup, added_at, league) VALUES (?,?,?,?,?,?)",
                                 (cur_season, cur_week, g["event_id"], g["name"],
                                  datetime.now().isoformat(timespec="seconds"), g.get("league", "CFB")))
                    save(conn)
                    st.rerun()
    if in_pool and not g["completed"]:
        with st.expander("📊 Breakdown"):
            if st.toggle("Load stats", key=f"{key_prefix}_bd_{g['event_id']}"):
                render_breakdown(g)

# ─────────────────────────────────────────────
# TAB 1 — MY POOL
# ─────────────────────────────────────────────
with tab_pool:
    with st.expander("📥 Import this week's games", expanded=not slate_ids):
        st.caption("Paste one matchup per line (e.g. `Ohio State vs Texas`). "
                   "Tip: send screenshots of your Splash board to Claude and "
                   "paste the list it gives back.")
        with st.form("import_form"):
            paste = st.text_area("Game list", height=160, label_visibility="collapsed",
                                 placeholder="Ohio State vs Texas\nAlabama vs Wisconsin\n…")
            submitted = st.form_submit_button("Match & add to pool")
        if submitted and paste.strip():
            matched, unmatched = match_paste_lines(paste, games)
            added = 0
            for _line, g in matched:
                cur = conn.execute(
                    "INSERT OR IGNORE INTO slate (season, week, event_id, matchup, added_at, league) VALUES (?,?,?,?,?,?)",
                    (cur_season, cur_week, g["event_id"], g["name"],
                     datetime.now().isoformat(timespec="seconds"), g.get("league", "CFB")))
                added += cur.rowcount
            if added:
                save(conn)
            st.success(f"Matched {len(matched)} game(s), added {added} new to the pool.")
            if unmatched:
                st.warning("Couldn't match these lines — add them from the Game board tab:\n\n- "
                           + "\n- ".join(unmatched))
            if added:
                st.rerun()

    slate_games = [games_by_id[eid] for eid in slate_ids if eid in games_by_id]
    missing = [eid for eid in slate_ids if eid not in games_by_id]
    if missing:
        st.caption(f"{len(missing)} pool game(s) aren't in this week's ESPN slate "
                   "(wrong week selected, or the game moved).")

    if not slate_games:
        st.info("No pool games yet — import the manager's list above, or add games "
                "from the Game board tab.")
    else:
        unpicked = [g for g in slate_games if g["event_id"] not in picks_by_id]
        n_done = len(slate_games) - len(unpicked)
        unentered = sum(1 for eid in slate_ids
                        if eid in picks_by_id and not picks_by_id[eid].get("entered_in_splash"))
        open_games = [g for g in slate_games if not is_locked(g["date"])]

        # Expected wins: sum of each picked side's fair win probability.
        exp_mine = exp_chalk = 0.0
        n_prob = 0
        for g in slate_games:
            hp, ap = fair_probs(g)
            if hp is None:
                continue
            n_prob += 1
            exp_chalk += max(hp, ap)
            r = picks_by_id.get(g["event_id"])
            if r is not None:
                exp_mine += hp if r["pick_abbr"] == g["home"]["abbr"] else ap

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Picked", f"{n_done}/{len(slate_games)}")
        c2.metric("In Splash", f"{n_done - unentered}/{n_done}" if n_done else "—")
        c3.metric("Expected wins", f"{exp_mine:.1f}" if n_done and n_prob else "—",
                  help="Sum of each pick's win probability. 'Best possible' "
                       f"(picking every model favorite) is {exp_chalk:.1f}.")
        c4.metric("Next lock", lock_label(min(
            open_games, key=lambda g: lock_time(g["date"]) or datetime.max.replace(tzinfo=timezone.utc)
        )["date"]) if open_games else "all locked")

        fillable = [g for g in unpicked if not is_locked(g["date"]) and recommend(g)[0]]
        if fillable and st.button(f"🎯 Fill {len(fillable)} open pick(s) with model favorites"):
            for g in fillable:
                side, _p = recommend(g)
                opp = g["away"] if side is g["home"] else g["home"]
                upsert_pick(conn, cur_season, cur_week, g, side, opp, pick_type)
            save(conn)
            st.rerun()

        # ── Edge board: every pool game ranked from gimme to coin flip ──
        with st.expander("🧠 Edge board — where this week is won"):
            st.caption("Sorted from safest to true coin flips. **Season prize:** "
                       "take the model side everywhere. **Weekly prize:** flip "
                       "2–3 💎 games to the dog — near-free separation from the "
                       "chalk crowd. Never flip a game that isn't 💎: a 🚨 pick "
                       "burns real expected wins.")
            rows = []
            for g in slate_games:
                side, p = recommend(g)
                if side is None:
                    continue
                r = picks_by_id.get(g["event_id"])
                mine = r["pick_abbr"] if r is not None else "—"
                dp = dog_prob(g)
                leverage = dp is not None and dp >= LEVERAGE_DOG_P
                flags = []
                if leverage:
                    flags.append("💎 leverage")
                elif p is not None and p < 0.60:
                    flags.append("⚠️ toss-up")
                if r is not None and mine != side["abbr"]:
                    flags.insert(0, "🎲 dog taken" if leverage or dp is None else "🚨 costly")
                rows.append({"Game": g["name"], "Model pick": side["abbr"],
                             "Win %": f"{p:.0%}" if p is not None else "?",
                             "My pick": mine, "": " ".join(flags),
                             "_p": p if p is not None else 0.5})
            if rows:
                edge_df = pd.DataFrame(rows).sort_values("_p", ascending=False).drop(columns="_p")
                st.dataframe(edge_df, hide_index=True, use_container_width=True)

        picked_games = [g for g in slate_games if g["event_id"] in picks_by_id]
        if picked_games:
            tb_row = conn.execute("SELECT value FROM tiebreaker WHERE season=? AND week=?",
                                  (cur_season, cur_week)).fetchone()
            tb_saved = tb_row[0] if tb_row else None
            with st.expander("📋 Splash entry list"):
                lines = []
                for i, g in enumerate(picked_games, 1):
                    r = picks_by_id[g["event_id"]]
                    mark = "" if r.get("entered_in_splash") else "   ← not entered"
                    lines.append(f"{i:2d}. {r['pick_name']} over {r['opp_name']}{mark}")
                if tb_saved is not None:
                    lines.append(f"Tiebreaker (combined total score): {tb_saved}")
                st.code("\n".join(lines), language=None)
                tb_game = max((g for g in slate_games if g["over_under"]),
                              key=lambda g: g["date"], default=None)
                if tb_game:
                    st.caption(f"💡 Vegas total for {tb_game['name']} (the last game): "
                               f"**{tb_game['over_under']}** — the sharpest tiebreaker guess.")
                tc1, tc2 = st.columns([2, 1])
                tb_default = (int(round(float(tb_game["over_under"]))) if tb_game and tb_saved is None
                              else int(tb_saved) if tb_saved is not None else 44)
                tb_new = tc1.number_input("Tiebreaker: combined total score", 0, 200, tb_default)
                if tc2.button("Save tiebreaker"):
                    conn.execute("INSERT INTO tiebreaker (season, week, value) VALUES (?,?,?) "
                                 "ON CONFLICT(season, week) DO UPDATE SET value=excluded.value",
                                 (cur_season, cur_week, int(tb_new)))
                    save(conn)
                    st.rerun()
                if unentered and st.button("✅ Mark all as entered in Splash"):
                    conn.execute("UPDATE picks SET entered_in_splash=1 WHERE season=? AND week=?",
                                 (cur_season, cur_week))
                    save(conn)
                    st.rerun()
        if unentered:
            st.warning(f"⚠️ {unentered} pick(s) not entered in Splash yet.")

        st.divider()
        pool_sort = st.radio("Order", ["Kickoff", "Toss-ups first", "Safest first"],
                             horizontal=True, label_visibility="collapsed")
        def _conf(g):
            _s, p = recommend(g)
            return p if p is not None else 0.5
        if pool_sort == "Toss-ups first":
            ordered = sorted(slate_games, key=_conf)
        elif pool_sort == "Safest first":
            ordered = sorted(slate_games, key=_conf, reverse=True)
        else:
            ordered = sorted(slate_games, key=lambda g: (g["date"], g["name"]))
        for g in ordered:
            render_card(g, "pool", in_pool=True)

# ─────────────────────────────────────────────
# TAB 2 — GAME BOARD (full FBS slate)
# ─────────────────────────────────────────────
with tab_board:
    c0, c1, c2, c3 = st.columns([1.2, 2, 2, 3])
    with c0:
        league_filter = st.selectbox("League", ["All", "CFB", "NFL"])
    with c1:
        sort_by = st.selectbox("Sort", ["Kickoff", "Biggest spread", "Closest spread"])
    with c2:
        only_ranked = st.toggle("Top-25 only")
    with c3:
        search = st.text_input("Find a team", placeholder="e.g. Michigan")

    shown = games
    if league_filter != "All":
        shown = [g for g in shown if g["league"] == league_filter]
    if only_ranked:
        shown = [g for g in shown if g["home"]["rank"] or g["away"]["rank"]]
    if search.strip():
        q = search.strip().lower()
        shown = [g for g in shown if q in g["home"]["name"].lower() or q in g["away"]["name"].lower()
                 or q in g["home"]["abbr"].lower() or q in g["away"]["abbr"].lower()]
    if sort_by == "Biggest spread":
        shown = sorted(shown, key=lambda g: -(g["line"] or -1))
    elif sort_by == "Closest spread":
        shown = sorted(shown, key=lambda g: (g["line"] is None, g["line"] or 0))
    else:
        shown = sorted(shown, key=lambda g: g["date"])

    st.caption(f"{len(shown)} games · lines from ESPN · ➕ adds a game to your pool")
    for g in shown:
        render_card(g, "board", in_pool=False)

# ─────────────────────────────────────────────
# TAB 3 — MY PICKS THIS WEEK
# ─────────────────────────────────────────────
with tab_picks:
    if pick_rows.empty:
        st.info("No picks yet this week — make them on the My Pool tab.")
    else:
        if st.button("🏁 Grade completed games"):
            changed = 0
            for _, row in pick_rows.iterrows():
                res, score = grade_pick(row, games_by_id.get(row["event_id"]))
                if res:
                    conn.execute("UPDATE picks SET result=?, final_score=? WHERE season=? AND week=? AND event_id=?",
                                 (res, score, cur_season, cur_week, row["event_id"]))
                    changed += 1
            if changed:
                save(conn)
            st.rerun()

        for _, row in pick_rows.sort_values("kickoff").iterrows():
            res = row["result"]
            res_txt = (f"<span class='res-{res}'>{ {'W': 'WIN', 'L': 'LOSS', 'P': 'PUSH'}[res] }</span>"
                       f" · {row['final_score']}") if res else "pending"
            splash = "" if row.get("entered_in_splash") else " <span class='tag tag-dog'>not in Splash</span>"
            st.markdown(f"""
<div class='game-card'>
  <div class='team-line'><span class='picked'>{row['pick_name']}</span> <span class='rec'>over {row['opp_name']}</span>{splash}</div>
  <div class='game-meta'>{row['matchup']} · {res_txt}</div>
</div>""", unsafe_allow_html=True)
            cols = st.columns([1, 1, 3])
            if not row.get("entered_in_splash"):
                if cols[0].button("✔ Entered", key=f"ent_{row['event_id']}"):
                    conn.execute("UPDATE picks SET entered_in_splash=1 WHERE season=? AND week=? AND event_id=?",
                                 (cur_season, cur_week, row["event_id"]))
                    save(conn)
                    st.rerun()
            if cols[1].button("Remove", key=f"del_{row['event_id']}"):
                conn.execute("DELETE FROM picks WHERE season=? AND week=? AND event_id=?",
                             (cur_season, cur_week, row["event_id"]))
                save(conn)
                st.rerun()

        graded = pick_rows[pick_rows["result"].notna()]
        if len(graded):
            w = (graded["result"] == "W").sum()
            l = (graded["result"] == "L").sum()
            p = (graded["result"] == "P").sum()
            st.markdown(f"### Week {cur_week}: **{w}–{l}**" + (f"–{p}" if p else ""))

# ─────────────────────────────────────────────
# TAB 4 — SEASON RECORD
# ─────────────────────────────────────────────
with tab_season:
    all_rows = pd.read_sql_query("SELECT * FROM picks WHERE season=? ORDER BY week, kickoff", conn, params=(cur_season,))
    if all_rows.empty:
        st.info("No picks recorded yet this season.")
    else:
        graded = all_rows[all_rows["result"].notna()]
        w = (graded["result"] == "W").sum()
        l = (graded["result"] == "L").sum()
        p = (graded["result"] == "P").sum()
        pct = w / (w + l) if (w + l) else 0
        c1, c2, c3 = st.columns(3)
        c1.metric("Season record", f"{w}–{l}" + (f"–{p}" if p else ""))
        c2.metric("Win %", f"{pct:.0%}" if (w + l) else "—")
        c3.metric("Picks made", len(all_rows))

        by_week = (graded.groupby("week")["result"]
                   .apply(lambda s: f"{(s == 'W').sum()}–{(s == 'L').sum()}" +
                                    (f"–{(s == 'P').sum()}" if (s == 'P').sum() else ""))
                   .rename("record").reset_index())
        if len(by_week):
            st.dataframe(by_week, hide_index=True, use_container_width=True)

        show = all_rows[["week", "pick_name", "opp_name", "result", "final_score"]].copy()
        show.columns = ["Wk", "Pick", "Over", "Result", "Final"]
        st.dataframe(show, hide_index=True, use_container_width=True)

conn.close()
