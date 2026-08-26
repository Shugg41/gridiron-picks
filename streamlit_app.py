import streamlit as st
import sqlite3
import pandas as pd
import requests
import re
from datetime import datetime, timezone

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
.rank-badge {
    color: var(--accent); font-size: 0.8rem; font-weight: 700;
    margin-right: 0.25rem;
}
.rec        { color: var(--muted); font-size: 0.8rem; font-weight: 400; }
.odds-line  { color: var(--field); font-size: 0.85rem; margin-top: 0.15rem; }
.picked     { color: var(--accent); font-weight: 700; }
.res-W      { color: var(--field);  font-weight: 700; }
.res-L      { color: var(--loss);  font-weight: 700; }
.res-P      { color: var(--push);  font-weight: 700; }

.stButton > button {
    background: var(--surface2) !important;
    color: var(--text) !important;
    border: 1px solid var(--border) !important;
    border-radius: 8px !important;
    padding: 0.25rem 0.6rem !important;
    font-size: 0.85rem !important;
}
.stButton > button:hover {
    border-color: var(--accent) !important;
    color: var(--accent) !important;
}
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────
DB_PATH = "football_picks.db"

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
    return conn

# ─────────────────────────────────────────────
# ESPN API
# ─────────────────────────────────────────────
SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"

@st.cache_data(ttl=300, show_spinner="Fetching games from ESPN…")
def fetch_scoreboard(year=None, week=None, seasontype=2):
    params = {"groups": "80", "limit": "400"}   # groups=80 → all of FBS
    if year and week:
        params.update({"dates": str(year), "seasontype": str(seasontype), "week": str(week)})
    r = requests.get(SCOREBOARD, params=params, timeout=15)
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

def parse_game(event):
    """Flatten one ESPN scoreboard event into a plain dict. Defensive: missing
    fields (odds don't exist for every game) come back as None."""
    comp = (event.get("competitions") or [{}])[0]
    g = {
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
            "rank": rank if rank and rank != 99 else None,
            "record": recs.get("total", ""),
            "home_record": recs.get("home", ""),
            "road_record": recs.get("road", ""),
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

def kickoff_local(iso_str):
    """ESPN dates are UTC like 2026-08-29T23:30Z → show as e.g. 'Sat 8/29 7:30 PM ET'."""
    try:
        dt = datetime.strptime(iso_str, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return iso_str
    try:
        from zoneinfo import ZoneInfo
        dt = dt.astimezone(ZoneInfo("America/New_York"))
        return dt.strftime("%a %-m/%-d %-I:%M %p ET")
    except Exception:
        return dt.strftime("%a %m/%d %H:%M UTC")

# ─────────────────────────────────────────────
# GRADING
# ─────────────────────────────────────────────
def grade_pick(row, game):
    """Return ('W'|'L'|'P', 'AWAY 24-21 HOME') for a completed game, else (None, None)."""
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
# SIDEBAR — league settings & week selection
# ─────────────────────────────────────────────
now = datetime.now()
default_season = now.year if now.month >= 8 else now.year - 1

with st.sidebar:
    st.markdown("## 🏈 Gridiron Picks")
    pick_type = st.radio("League pick style", ["SU", "ATS"], horizontal=True,
                         format_func=lambda x: "Straight up" if x == "SU" else "Against the spread")
    use_conf = st.toggle("Confidence points", value=False,
                         help="If your league ranks picks by confidence, turn this on.")
    st.divider()
    use_current = st.toggle("Current week (auto)", value=True)
    season = st.number_input("Season", 2020, 2030, default_season, disabled=use_current)
    week = st.selectbox("Week", list(range(1, 17)), disabled=use_current)
    if st.button("🔄 Refresh data"):
        fetch_scoreboard.clear()
        st.rerun()

# ─────────────────────────────────────────────
# FETCH & PARSE
# ─────────────────────────────────────────────
try:
    data = fetch_scoreboard() if use_current else fetch_scoreboard(int(season), int(week))
except requests.RequestException as e:
    st.error(f"Couldn't reach ESPN: {e}")
    st.stop()

api_week = (data.get("week") or {}).get("number")
api_season = ((data.get("season") or {}).get("year")) or ((data.get("leagues") or [{}])[0].get("season") or {}).get("year")
cur_season = int(api_season) if use_current and api_season else int(season)
cur_week = int(api_week) if use_current and api_week else int(week)

games = [parse_game(e) for e in data.get("events") or []]
games = [g for g in games if g["home"] and g["away"]]
games_by_id = {g["event_id"]: g for g in games}

conn = get_conn()
pick_rows = pd.read_sql_query(
    "SELECT * FROM picks WHERE season=? AND week=?", conn, params=(cur_season, cur_week))
picked_ids = set(pick_rows["event_id"])

st.markdown(f"# Week {cur_week} · {cur_season}")

tab_board, tab_picks, tab_season = st.tabs(["📋 Game board", f"✅ My picks ({len(picked_ids)})", "📈 Season"])

# ─────────────────────────────────────────────
# TAB 1 — GAME BOARD
# ─────────────────────────────────────────────
with tab_board:
    c1, c2, c3 = st.columns([2, 2, 3])
    with c1:
        sort_by = st.selectbox("Sort", ["Kickoff", "Biggest spread", "Closest spread"])
    with c2:
        only_ranked = st.toggle("Top-25 only")
    with c3:
        search = st.text_input("Find a team", placeholder="e.g. Michigan")

    shown = games
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

    st.caption(f"{len(shown)} games · lines from ESPN · tap a team to pick "
               f"({'straight up' if pick_type == 'SU' else 'against the spread'})")

    def team_html(side, is_fav, prob):
        rank = f"<span class='rank-badge'>#{side['rank']}</span>" if side["rank"] else ""
        rec = f"<span class='rec'> ({side['record']})</span>" if side["record"] else ""
        fav = " ★" if is_fav else ""
        pct = f" · {prob:.0%}" if prob else ""
        return f"{rank}{side['name']}{fav}{rec}<span class='rec'>{pct}</span>"

    for g in shown:
        home, away = g["home"], g["away"]
        fav_home = g["fav_abbr"] == home["abbr"]
        fav_away = g["fav_abbr"] == away["abbr"]
        odds_bits = []
        if g["fav_abbr"] and g["line"] is not None:
            odds_bits.append(f"{g['fav_abbr']} −{g['line']:g}")
        if g["over_under"]:
            odds_bits.append(f"O/U {g['over_under']}")
        odds_txt = " · ".join(odds_bits) if odds_bits else "no line yet"
        where = "· neutral site" if g["neutral_site"] else ""
        tv = f" · {g['broadcast']}" if g["broadcast"] else ""
        status = g["status_detail"] if g["completed"] else kickoff_local(g["date"])
        my = pick_rows[pick_rows["event_id"] == g["event_id"]]
        my_pick = my.iloc[0]["pick_abbr"] if len(my) else None

        with st.container():
            st.markdown(f"""
<div class='game-card'>
  <div class='game-meta'>{status}{tv} {where}</div>
  <div class='team-line'>{team_html(away, fav_away, g['away_ml_prob'])}</div>
  <div class='team-line'>at {team_html(home, fav_home, g['home_ml_prob'])}</div>
  <div class='odds-line'>{odds_txt}{f" &nbsp;·&nbsp; <span class='picked'>my pick: {my_pick}</span>" if my_pick else ""}</div>
</div>""", unsafe_allow_html=True)
            if not g["completed"]:
                b1, b2, _ = st.columns([1, 1, 3])
                for col, side, opp in ((b1, away, home), (b2, home, away)):
                    label = f"✔ {side['abbr']}" if my_pick == side["abbr"] else side["abbr"]
                    if col.button(label, key=f"pick_{g['event_id']}_{side['abbr']}"):
                        conn.execute("""
                            INSERT INTO picks (season, week, event_id, matchup, kickoff,
                                pick_abbr, pick_name, opp_abbr, opp_name, pick_type,
                                fav_abbr, line, created_at)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                            ON CONFLICT(season, week, event_id) DO UPDATE SET
                                pick_abbr=excluded.pick_abbr, pick_name=excluded.pick_name,
                                opp_abbr=excluded.opp_abbr, opp_name=excluded.opp_name,
                                pick_type=excluded.pick_type, fav_abbr=excluded.fav_abbr,
                                line=excluded.line, result=NULL, final_score=NULL
                        """, (cur_season, cur_week, g["event_id"], g["name"], g["date"],
                              side["abbr"], side["name"], opp["abbr"], opp["name"], pick_type,
                              g["fav_abbr"], g["line"], datetime.now().isoformat(timespec="seconds")))
                        conn.commit()
                        st.rerun()

# ─────────────────────────────────────────────
# TAB 2 — MY PICKS THIS WEEK
# ─────────────────────────────────────────────
with tab_picks:
    if pick_rows.empty:
        st.info("No picks yet this week — make them on the Game board tab.")
    else:
        if st.button("🏁 Grade completed games"):
            for _, row in pick_rows.iterrows():
                res, score = grade_pick(row, games_by_id.get(row["event_id"]))
                if res:
                    conn.execute("UPDATE picks SET result=?, final_score=? WHERE season=? AND week=? AND event_id=?",
                                 (res, score, cur_season, cur_week, row["event_id"]))
            conn.commit()
            st.rerun()

        for _, row in pick_rows.sort_values("kickoff").iterrows():
            line_txt = ""
            if row["pick_type"] == "ATS" and row["line"] is not None and row["fav_abbr"]:
                pts = -row["line"] if row["pick_abbr"] == row["fav_abbr"] else row["line"]
                line_txt = f" ({pts:+g})"
            res = row["result"]
            res_txt = f"<span class='res-{res}'>{ {'W':'WIN','L':'LOSS','P':'PUSH'}[res] }</span> · {row['final_score']}" if res else "pending"
            st.markdown(f"""
<div class='game-card'>
  <div class='team-line'><span class='picked'>{row['pick_name']}{line_txt}</span> <span class='rec'>over {row['opp_name']}</span></div>
  <div class='game-meta'>{row['matchup']} · {res_txt}</div>
</div>""", unsafe_allow_html=True)
            cols = st.columns([1, 1, 3])
            if use_conf:
                new_conf = cols[0].number_input("Conf.", 0, 50, int(row["confidence"] or 0),
                                                key=f"conf_{row['event_id']}", label_visibility="collapsed")
                if new_conf != (row["confidence"] or 0):
                    conn.execute("UPDATE picks SET confidence=? WHERE season=? AND week=? AND event_id=?",
                                 (new_conf, cur_season, cur_week, row["event_id"]))
                    conn.commit()
            if cols[1].button("Remove", key=f"del_{row['event_id']}"):
                conn.execute("DELETE FROM picks WHERE season=? AND week=? AND event_id=?",
                             (cur_season, cur_week, row["event_id"]))
                conn.commit()
                st.rerun()

        graded = pick_rows[pick_rows["result"].notna()]
        if len(graded):
            w = (graded["result"] == "W").sum()
            l = (graded["result"] == "L").sum()
            p = (graded["result"] == "P").sum()
            st.markdown(f"### Week {cur_week}: **{w}–{l}**" + (f"–{p}" if p else ""))

# ─────────────────────────────────────────────
# TAB 3 — SEASON RECORD
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

        show = all_rows[["week", "pick_name", "opp_name", "pick_type", "line", "result", "final_score"]].copy()
        show.columns = ["Wk", "Pick", "Over", "Type", "Line", "Result", "Final"]
        st.dataframe(show, hide_index=True, use_container_width=True)

conn.close()
