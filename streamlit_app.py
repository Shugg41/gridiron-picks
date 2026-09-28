"""Gridiron Picks — the screen.

Deliberately thin. Everything decidable without Streamlit is decided in
gridiron/, so this only fetches, arranges and renders. The old version
put all of it in one file and every fix reached something unrelated.

The shape of a week:

    paste the board    -> the games exist
    the app proposes   -> a list to type into Splash
    paste your entry   -> what you actually did, and the results
    paste the field    -> how the league picked, and what it cost

No per-game controls. Splash holds the picks, this holds the reasoning —
which is also what keeps the page quick, since thirty games of buttons is
thirty ways to trigger a rerun.
"""
import os

import streamlit as st

from gridiron import espn, model, simulate, splash, store, view

DB = os.path.join(os.path.dirname(__file__), "football_picks.db")
SEASON = 2026
WEEKS_IN_SEASON = 20

st.set_page_config(page_title="Gridiron Picks", page_icon="🏈",
                   layout="centered", initial_sidebar_state="collapsed")
st.markdown(view.CSS, unsafe_allow_html=True)


def secret(name):
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.environ.get(name)


@st.cache_resource
def _sync():
    return store.Sync(secret("GITHUB_REPO"), secret("GITHUB_TOKEN"), db_path=DB)


@st.cache_resource
def _conn():
    """Opened through the sync, so a write made outside the running app —
    by Claude, in a session — is picked up instead of ignored until the
    next restart."""
    conn = store.open_synced(DB, _sync())
    store.migrate_legacy(conn)
    return conn


sync, conn = _sync(), _conn()


def save():
    conn.commit()
    if sync.enabled and not sync.push(conn):
        st.session_state["sync_error"] = sync.reason
    else:
        st.session_state.pop("sync_error", None)


@st.cache_data(ttl=900, show_spinner=False)
def scoreboard():
    """Both leagues, and whatever went wrong, as a value.

    The failure is returned rather than stashed in session_state: a
    cached function only runs on a miss, so anything it writes to state
    is silently absent on every subsequent run — the error would show
    once and then vanish while still being true.
    """
    out, failed = [], []
    for league in ("CFB", "NFL"):
        try:
            out += espn.scoreboard(league)
        except Exception as exc:
            failed.append(f"{league}: {type(exc).__name__}")
    return out, ", ".join(failed)


# ── loading a week ──────────────────────────────────────────────────────
_, latest = store.latest_week(conn, SEASON)
all_weeks = [r[0] for r in conn.execute(
    "SELECT DISTINCT week FROM game WHERE season=? ORDER BY week DESC", (SEASON,))]
week = latest
if len(all_weeks) > 1:
    week = st.selectbox("Week", all_weeks, index=0, label_visibility="collapsed",
                        format_func=lambda w: f"Week {w}")

games = store.week_games(conn, SEASON, week) if week else []
entry = store.week_entry(conn, SEASON, week) if week else {}
field = store.week_field(conn, SEASON, week) if week else {}
standings = [splash.Standing(rank=r[2], name=r[0], entry=r[1], points=r[3],
                             wins=r[4], losses=r[5], tie_diff=r[6], me=bool(r[7]))
             for r in conn.execute(
                 "SELECT name, entry_name, rank, points, wins, losses, tie_diff, "
                 "me FROM standing WHERE season=?", (SEASON,))]
strat = model.strategy(standings, max(0, WEEKS_IN_SEASON - (week or 0)))


def enrich(games):
    """Attach an ESPN event to each game, remembering the link.

    A game that will not match keeps its place with no odds — the board
    decides what exists, and a missing line is cosmetic where a missing
    game is not.
    """
    if not games:
        return {}
    events = {e["event_id"]: e for e in scoreboard()[0]}
    found, unlinked = {}, []
    for g in games:
        key = (g["away_code"], g["home_code"])
        if g["espn_id"] and g["espn_id"] in events:
            found[key] = events[g["espn_id"]]
        else:
            unlinked.append(g)
    if unlinked and events:
        spare = [e for e in events.values() if e not in found.values()]
        pending = [splash.Game(away_code=g["away_code"], home_code=g["home_code"],
                               away=g["away"] or "", home=g["home"] or "")
                   for g in unlinked]
        for sg, evt in espn.link(pending, spare):
            if not evt:
                continue
            found[(sg.away_code, sg.home_code)] = evt
            conn.execute(
                "UPDATE game SET espn_id=?, kickoff=COALESCE(?, kickoff) "
                "WHERE season=? AND week=? AND away_code=? AND home_code=?",
                (evt["event_id"], evt.get("date"), SEASON, week,
                 sg.away_code, sg.home_code))
        conn.commit()
    return found


events = enrich(games)
linked = [(splash.Game(away_code=g["away_code"], home_code=g["home_code"],
                       away=g["away"] or "", home=g["home"] or ""),
           events.get((g["away_code"], g["home_code"]))) for g in games]
picks = model.propose(linked, field=field, strat=strat)
numbered = list(enumerate(picks, 1))
by_key = {(p.away, p.home): p for p in picks}

# ── header ──────────────────────────────────────────────────────────────
st.markdown(f"<div class='gp-head'>Week {week or '—'}</div>",
            unsafe_allow_html=True)
if games:
    nxt = min((g["kickoff"] for g in games if g["kickoff"]), default=None)
    unpicked = sum(1 for g in games
                   if entry.get((g["away_code"], g["home_code"]), (None,))[0] is None
                   and (g["away_code"], g["home_code"]) in entry)
    bits = [f"{len(games)} games"]
    if nxt:
        bits.append(view.locks_in(nxt))
    if entry:
        bits.append(f"{len(entry) - unpicked} of {len(games)} entered")
    st.markdown(f"<div class='gp-sub'>{' · '.join(bits)}</div>",
                unsafe_allow_html=True)
st.markdown(f"<div class='gp-mode'>{strat.why}</div>", unsafe_allow_html=True)

# A successful paste ends in st.rerun(), which wipes anything written
# before it — so the confirmation is stashed and rendered on the way back.
_note = st.session_state.pop("note", None)
if _note:
    {"ok": st.success, "warn": st.warning}[_note[0]](_note[1])

if st.session_state.get("sync_error"):
    st.warning(f"Not saved to GitHub: {st.session_state['sync_error']}")
_espn_error = scoreboard()[1]
if _espn_error:
    st.caption(f"No lines right now — ESPN unreachable ({_espn_error}). "
               f"The card is intact; the odds are not.")

def _match_pair(games, a, b):
    """Find the stored game these two codes belong to, either way round."""
    for g in games:
        if {a, b} == {g["away_code"], g["home_code"]}:
            return g["away_code"], g["home_code"]
    return None


# ── the paste bar ───────────────────────────────────────────────────────
with st.expander("Paste from Splash", expanded=not games):
    st.caption("Any of the four pages — the board, your entry, Pick "
               "Distribution, or the standings. It works out which is "
               "which. Text only: run the shortcut and paste.")
    with st.form("paste", clear_on_submit=True):
        text = st.text_area("Paste", height=150, label_visibility="collapsed")
        wk = st.number_input("Week", 1, WEEKS_IN_SEASON,
                             value=int(week or 1), step=1)
        go = st.form_submit_button("Load it", type="primary")
    if go and text.strip():
        kind = splash.sniff(text)
        wk = int(wk)
        if kind == "board" or kind == "entry":
            parsed = splash.parse_entry(text)
            store.save_games(conn, SEASON, wk, parsed.games)
            rows = [{"away_code": g.away_code, "home_code": g.home_code,
                     "team": g.picked,
                     "result": None if g.points is None else
                     ("W" if g.points else "L")} for g in parsed.games]
            if any(r["team"] for r in rows):
                store.save_entry(conn, SEASON, wk, rows)
            if parsed.tiebreaker is not None:
                conn.execute("INSERT INTO tiebreak (season, week, guess) "
                             "VALUES (?,?,?) ON CONFLICT(season, week) "
                             "DO UPDATE SET guess=excluded.guess",
                             (SEASON, wk, parsed.tiebreaker))
            save()
            st.session_state["note"] = (
                "ok", f"Week {wk}: {len(parsed.games)} games loaded.")
            st.rerun()

        elif kind == "picks_by_week":
            board_games, entries = splash.parse_picks_by_week(text)
            gobjs = [splash.Game(away_code=a, home_code=h) for a, h in board_games]
            store.save_games(conn, SEASON, wk, gobjs)
            mine = next((e for e in entries if e.me), None)
            if mine:
                rows = []
                for i, (a, h) in enumerate(board_games):
                    team, state = (mine.picks[i] if i < len(mine.picks)
                                   else (None, "open"))
                    rows.append({"away_code": a, "home_code": h, "team": team,
                                 "result": {"W": "W", "L": "L"}.get(state)})
                store.save_entry(conn, SEASON, wk, rows)
            store.save_field_cards(conn, SEASON, wk,
                                   simulate.rivals_from_matrix(board_games,
                                                               entries))
            dist = splash.distribution_from_matrix(board_games, entries)
            store.save_field(conn, SEASON, wk, [
                (board_games[i][0], board_games[i][1], side[0], side[1],
                 side[2], None)
                for i in range(len(board_games)) for side in dist[i]])
            save()
            missed = sum(1 for p in (mine.picks if mine else []) if p[0] is None)
            note = f"Week {wk}: {len(board_games)} games, {len(entries)} entries."
            if missed:
                note += f"  {missed} game(s) you never picked."
            st.session_state["note"] = ("ok", note)
            st.rerun()

        elif kind == "distribution":
            rows = splash.parse_distribution(text)
            saved = 0
            for (ca, na, pa), (cb, nb, pb) in rows:
                key = _match_pair(games, ca, cb)
                if not key:
                    continue
                store.save_field(conn, SEASON, wk,
                                 [(key[0], key[1], ca, na, pa, None),
                                  (key[0], key[1], cb, nb, pb, None)])
                saved += 1
            save()
            st.session_state["note"] = (
                "ok", f"Field loaded for {saved} of {len(rows)} games.")
            st.rerun()

        elif kind == "standings":
            rows, size = splash.parse_standings(text)
            store.save_standings(conn, SEASON, None, rows)
            save()
            me = next((r for r in rows if r.me), None)
            st.session_state["note"] = (
                "ok", f"Standings loaded — {len(rows)} of {size} entries"
                + (f", you are {me.rank} on {me.points}." if me else "."))
            st.rerun()
        else:
            st.session_state["note"] = (
                "warn", "Couldn't tell which page that is — paste the whole "
                        "page rather than a selection.")


# ── the week ────────────────────────────────────────────────────────────
if not games:
    st.info("Paste this week's board to get started.")
    st.stop()

flips = [(n, p) for n, p in numbered if p.flipped]
if flips and not entry:
    st.markdown(f"**Flip {'this one' if len(flips) == 1 else f'these {len(flips)}'}**")
    for n, p in flips:
        st.markdown(view.standout(n, p), unsafe_allow_html=True)
    st.caption("The closest games on the card. Taking the underdog costs "
               "almost nothing over a season and is the only thing that "
               "separates you from everyone riding the chalk.")

show_pct = st.toggle("Show percentages", value=False)
for n, p in numbered:
    g = games[n - 1]
    st.markdown(view.card(n, p, g, entry.get((p.away, p.home)) if entry else None,
                          show_pct=show_pct),
                unsafe_allow_html=True)

# ── how the week is likely to go ────────────────────────────────────────
with st.expander("Odds this week"):
    probs = simulate.probabilities(linked, picks)
    my_card = {(p.away, p.home): p.team for p in picks if p.team}
    if entry:                       # once entered, simulate what I really have
        my_card = {k: t for k, (t, _r) in entry.items() if t}
    rivals = store.week_field_cards(conn, SEASON, week)

    out = simulate.simulate(my_card, probs, rivals, trials=4000)
    st.markdown(
        f"**{out.mean:.1f}** correct is the middle of it — four weeks in "
        f"five you land between **{out.p10}** and **{out.p90}**.")

    if rivals:
        st.markdown(
            f"Against the **{len(rivals)}** other entries: "
            f"**{out.win:.0%}** to win outright"
            + (f", **{out.tie:.0%}** to tie at the top" if out.tie else "")
            + f", **{out.top3:.0%}** to finish top three.")
        flipped, chalk = simulate.what_flips_are_worth(picks, probs, rivals,
                                                       trials=4000)
        if flipped.mean != chalk.mean or flipped.any_win != chalk.any_win:
            st.caption(
                f"The flips cost {chalk.mean - flipped.mean:+.2f} in expected "
                f"score and move your chance of finishing first from "
                f"{chalk.any_win:.0%} to {flipped.any_win:.0%}. That trade is "
                f"the whole argument for making them — if it ever reads the "
                f"wrong way round, stop flipping.")
    else:
        st.caption("Paste the **Picks by Week** page once the deadline "
                   "passes and this turns into real odds of winning the "
                   "week. That page carries every entry's card, which is "
                   "what the simulation needs — percentages cannot say who "
                   "is on which side, and who is the question.")

# ── the list to type into Splash ────────────────────────────────────────
if not entry:
    st.divider()
    st.markdown("**Enter these in Splash**")
    last = events.get((picks[-1].away, picks[-1].home)) if picks else None
    tb = model.tiebreaker(last)
    st.code(view.copy_list(numbered, tb), language=None)
    if tb:
        st.caption(f"Tiebreaker {tb} is the Vegas total on the last game.")
    if st.button("Save these as this week's proposal", width="stretch"):
        store.save_proposals(conn, SEASON, week,
                             [(p.away, p.home, p.team, p.basis)
                              for p in picks if p.team])
        save()
        st.success("Saved. Paste your entry back once they're in Splash.")

# ── how it actually went ────────────────────────────────────────────────
with st.expander("How the week went"):
    if not entry:
        st.caption("Paste your entry once the picks are in Splash.")
    else:
        missing = [k for k, (t, _r) in entry.items() if t is None]
        if missing:
            st.error(f"{len(missing)} game(s) with no pick: "
                     + ", ".join(f"{a} @ {h}" for a, h in missing))
        if field:
            alone = [(k, t) for k, (t, r) in entry.items()
                     if t and (field.get(k) or {}).get(t, 1) <= 0.35]
            lost_alone = [k for k, t in alone if entry[k][1] == "L"]
            st.markdown(
                f"- **{len(alone)}** pick(s) against the crowd, "
                f"**{len(lost_alone)}** of them lost — those are the "
                f"expensive ones\n"
                f"- losses the crowd shared cost you nothing in the standings")
        props = {(a, h): (t, b) for a, h, t, b in conn.execute(
            "SELECT away_code, home_code, team, basis FROM proposal "
            "WHERE season=?", (SEASON,))}
        winners = {}
        for (a, h), (t, r) in store.week_entry(conn, SEASON, week).items():
            if t and r in ("W", "L"):
                winners[(a, h)] = t if r == "W" else (h if t == a else a)
        rep = model.advice_report(props, entry, winners)
        st.markdown(f"**{rep.verdict}**")
