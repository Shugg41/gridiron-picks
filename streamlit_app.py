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
import sqlite3
from datetime import datetime as _dt, timezone as _tz

import streamlit as st

from gridiron import espn, model, simulate, splash, store, view, watch

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


def load_paste(text, wk):
    """Route a pasted page to its parser and store what came back.

    Returns (level, message) rather than drawing anything, so the caller
    can catch a failure and SHOW it. Streamlit redacts the message of an
    uncaught exception — from a phone that reads as "an error occurred,
    see the logs", which is no use at all an hour before a deadline.
    """
    kind = splash.sniff(text)

    if kind in ("board", "entry"):
        parsed = splash.parse_entry(text)
        store.save_games(conn, SEASON, wk, parsed.games)
        rows = [{"away_code": g.away_code, "home_code": g.home_code,
                 "team": g.picked,
                 "result": None if g.points is None else
                 ("W" if g.points else "L")} for g in parsed.games]
        if any(r["team"] for r in rows):
            store.save_entry(conn, SEASON, wk, rows)
        if parsed.tiebreaker is not None:
            store.upsert(conn, "tiebreak", {"season": SEASON, "week": wk},
                         {"guess": parsed.tiebreaker})
        return "ok", f"Week {wk}: {len(parsed.games)} games loaded."

    if kind == "picks_by_week":
        board_games, entries = splash.parse_picks_by_week(text)
        store.save_games(conn, SEASON, wk,
                         [splash.Game(away_code=a, home_code=h)
                          for a, h in board_games])
        mine = next((e for e in entries if e.me), None)
        if mine:
            store.save_entry(conn, SEASON, wk, [
                {"away_code": a, "home_code": h,
                 "team": (mine.picks[i] if i < len(mine.picks) else (None,))[0],
                 "result": {"W": "W", "L": "L"}.get(
                     mine.picks[i][1] if i < len(mine.picks) else "")}
                for i, (a, h) in enumerate(board_games)])
        store.save_field_cards(conn, SEASON, wk,
                               simulate.rivals_from_matrix(board_games, entries))
        dist = splash.distribution_from_matrix(board_games, entries)
        store.save_field(conn, SEASON, wk, [
            (board_games[i][0], board_games[i][1], side[0], side[1], side[2],
             None)
            for i in range(len(board_games)) for side in dist[i]])
        missed = sum(1 for p in (mine.picks if mine else []) if p[0] is None)
        note = f"Week {wk}: {len(board_games)} games, {len(entries)} entries."
        if missed:
            note += f"  {missed} game(s) you never picked."
        return "ok", note

    if kind == "distribution":
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
        return "ok", f"Field loaded for {saved} of {len(rows)} games."

    if kind == "standings":
        rows, size = splash.parse_standings(text)
        store.save_standings(conn, SEASON, None, rows)
        me = next((r for r in rows if r.me), None)
        return "ok", (f"Standings loaded — {len(rows)} of {size} entries"
                      + (f", you are {me.rank} on {me.points}." if me else "."))

    return "warn", ("Couldn't tell which page that is — paste the whole page "
                    "rather than a selection.")


# ── the paste bar ───────────────────────────────────────────────────────
with st.expander("Paste from Splash", expanded=not games):
    st.caption("Any of the pages — the board, your entry, Picks by Week, "
               "Pick Distribution, or the standings. It works out which is "
               "which. Text only: run the shortcut and paste.")
    with st.form("paste", clear_on_submit=True):
        text = st.text_area("Paste", height=150, label_visibility="collapsed")
        wk = st.number_input("Week", 1, WEEKS_IN_SEASON,
                             value=int(week or 1), step=1)
        go = st.form_submit_button("Load it", type="primary")
    if go and text.strip():
        try:
            level, message = load_paste(text, int(wk))
            if level == "ok":
                save()
            st.session_state["note"] = (level, message)
            st.rerun()
        except Exception as exc:
            # Show it. A redacted "see the logs" is useless on a phone,
            # and the paste is the one place a new Splash layout will
            # surface — the message is the whole diagnosis.
            conn.rollback()
            st.error(f"**{type(exc).__name__}**: {exc}")
            st.caption(f"sqlite {sqlite3.sqlite_version} · page read as "
                       f"{splash.sniff(text)!r} · {len(text)} characters. "
                       f"Send me this and I can fix it.")


# ── the week ────────────────────────────────────────────────────────────
if not games:
    st.info("Paste this week's board to get started.")
    st.stop()

@st.cache_data(ttl=3600, show_spinner=False)
def movement_for(event_id, league, home, away):
    """Only the core API carries an opening line, and it is one request
    per game — so this is asked only for the handful of games where the
    answer could change a decision, and cached for an hour."""
    try:
        return espn.movement(espn.odds_history(event_id, league), home, away)
    except Exception:
        return None, None


flips = [(n, p) for n, p in numbered if p.flipped]
if flips and not entry:
    st.markdown(f"**Flip {'this one' if len(flips) == 1 else f'these {len(flips)}'}**")
    for n, p in flips:
        st.markdown(view.standout(n, p), unsafe_allow_html=True)
        ev = events.get((p.away, p.home))
        if not ev:
            continue
        pts, toward = movement_for(ev["event_id"], ev["league"], p.home, p.away)
        if not pts:
            continue
        # Which way the money went is the part worth saying out loud: the
        # crowd piles onto favorites, so a favorite getting cheaper is
        # usually sharper money taking the side you are considering.
        if toward == p.team:
            st.caption(f"    ↳ the line has moved **{pts:g} points toward "
                       f"{toward}** since it opened — money agreeing with "
                       f"this flip.")
        else:
            st.caption(f"    ↳ the line has moved **{pts:g} points toward "
                       f"{toward}** since it opened — money going the other "
                       f"way. Worth a second thought.")
    st.caption("The closest games on the card. Taking the underdog costs "
               "almost nothing over a season and is the only thing that "
               "separates you from everyone riding the chalk.")

show_pct = st.toggle("Show percentages", value=False)
for n, p in numbered:
    g = games[n - 1]
    st.markdown(view.card(n, p, g, entry.get((p.away, p.home)) if entry else None,
                          show_pct=show_pct),
                unsafe_allow_html=True)

# ── has anything moved on a game already picked ────────────────────────
def check_for_changes():
    """Compare each picked, unlocked game against how it looked last time.

    This runs in the app rather than a GitHub Action because ESPN refuses
    the runners on the summary endpoint where injuries live, while the
    app is served both. Keep-awake loads the page every two hours, so
    that is the polling loop — no scheduler of its own.

    Only picked games that can still be changed are considered: an alert
    about a game you cannot do anything about is noise, and noise is how
    a useful alert gets ignored.
    """
    if not entry:
        return []
    seen = watch.previous(conn, SEASON, week)
    changes, touched = [], False
    for g in games:
        key = (g["away_code"], g["home_code"])
        if not (entry.get(key) or (None,))[0]:
            continue
        if view.locks_in(g["kickoff"]) == "locked":
            continue
        event = events.get(key)
        if not event:
            continue
        try:
            summary = espn.summary(event["event_id"], event["league"])
        except Exception:
            summary = None
        now = watch.snapshot(event, summary)
        if not now:
            continue
        changes += watch.compare(seen.get(key), now, *key)
        watch.record(conn, SEASON, week, key[0], key[1], now,
                     when=str(_dt.now(_tz.utc)))
        touched = True
    if touched:
        conn.commit()
    return changes


moves = check_for_changes()
if moves:
    st.warning("**Since you picked:**\n\n"
               + "\n".join(f"- {c}" for c in moves))
    topic = secret("NTFY_TOPIC")
    pushed_key = f"pushed:{week}:" + "|".join(str(c) for c in moves)
    if topic and st.session_state.get("last_push") != pushed_key:
        try:
            import urllib.request
            req = urllib.request.Request(
                f"https://ntfy.sh/{topic}",
                data=("\n".join(str(c) for c in moves)).encode(),
                headers={"Title": "Something moved on a game you picked",
                         "Tags": "warning,football"})
            urllib.request.urlopen(req, timeout=10)
            st.session_state["last_push"] = pushed_key
        except Exception:
            pass                      # a failed push must never break the page

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
