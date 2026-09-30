"""Pure rendering helpers: text and HTML in, no Streamlit, no state.

Keeping these out of the app file is what makes the screen testable
without driving a browser — the old version buried its formatting inside
1,500 lines of UI, so the only way to check a card was to render the
whole app and read the HTML back.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

CSS = """
<style>
:root {
  --bg:#0d0e10; --surface:#16181c; --surface2:#1c1f24; --border:#272b31;
  --text:#e9eaec; --muted:#8b9099; --accent:#e8b63a; --good:#3fa66a;
  --bad:#c9524a; --flip:#4a90d9;
}
.block-container { padding-top: 2.2rem; max-width: 46rem; }
.gp-head { font-size:1.35rem; font-weight:700; margin:0 0 .15rem; }
.gp-sub  { color:var(--muted); font-size:.85rem; margin:0 0 .1rem; }
.gp-mode { color:var(--accent); font-size:.85rem; font-weight:600;
           margin:.35rem 0 .9rem; }
.card { background:var(--surface); border:1px solid var(--border);
        border-left:3px solid transparent; border-radius:10px;
        padding:.55rem .75rem; margin:.3rem 0; }
.card.flip { border-left-color:var(--flip); }
.card.won  { border-left-color:var(--good); }
.card.lost { border-left-color:var(--bad); }
.card.none { border-left-color:var(--muted); }
.line { font-size:1.05rem; line-height:1.45; }
.num  { color:var(--muted); font-weight:700; font-variant-numeric:tabular-nums; }
.team { color:var(--accent); font-weight:700; }
.opp  { color:var(--text); opacity:.72; font-weight:400; }
.nopick { color:var(--bad); font-weight:700; }
.sub  { color:var(--muted); font-size:.8rem; margin-top:.1rem; }
.chip { display:inline-block; font-size:.66rem; font-weight:700;
        border-radius:999px; padding:.05rem .45rem; margin-left:.4rem;
        vertical-align:middle; }
.chip-flip { background:rgba(74,144,217,.16); color:#7db3e8; }
.chip-edge { background:rgba(232,182,58,.14); color:var(--accent); }
.chip-alone{ background:rgba(201,82,74,.14); color:#e08179; }
.standout { background:var(--surface2); border-left:3px solid var(--flip);
            border-radius:8px; padding:.4rem .7rem; margin:.25rem 0;
            font-size:1rem; }
</style>
"""


def kickoff_label(iso_or_text, now=None):
    """"Sat 3:30 PM" in Eastern, or whatever Splash printed if the kickoff
    never got an ESPN timestamp."""
    if not iso_or_text:
        return ""
    try:
        dt = datetime.fromisoformat(str(iso_or_text).replace("Z", "+00:00"))
    except ValueError:
        return str(iso_or_text)
    return dt.astimezone(ET).strftime("%a %-I:%M %p ET")


def lock_time(kickoff_iso):
    """Picks lock at noon ET on the slate's Saturday, or at kickoff for a
    game that starts before that. The week runs Tuesday to Monday, so
    Sunday and Monday games belong to the Saturday behind them."""
    try:
        kick = datetime.fromisoformat(str(kickoff_iso).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    et = kick.astimezone(ET)
    days_to_sat = -2 if et.weekday() == 0 else 5 - et.weekday()
    sat = (et + timedelta(days=days_to_sat)).date()
    noon = datetime(sat.year, sat.month, sat.day, 12, 0, tzinfo=ET)
    return min(kick, noon.astimezone(timezone.utc))


def locks_in(kickoff_iso, now=None):
    lt = lock_time(kickoff_iso)
    if not lt:
        return ""
    now = now or datetime.now(timezone.utc)
    if now >= lt:
        return "locked"
    left = lt - now
    hours = left.total_seconds() / 3600
    if hours >= 48:
        return f"locks in {int(hours // 24)}d"
    if hours >= 1:
        return f"locks in {int(hours)}h"
    return f"locks in {int(left.total_seconds() // 60)}m"


def card(n, pick, game, entry=None, edge=None, show_pct=False):
    """One game's row. `entry` is (team, result) once it is known."""
    entered, result = entry or (None, None)
    klass = "card"
    if result == "W":
        klass += " won"
    elif result == "L":
        klass += " lost"
    elif entered is None and entry is not None:
        klass += " none"
    elif pick.flipped:
        klass += " flip"

    shown = entered or pick.team
    if entry is not None and entered is None:
        head = (f"<span class='nopick'>No pick made</span>"
                f"<span class='opp'> — {pick.away} at {pick.home}</span>")
    elif shown:
        other = pick.home if shown == pick.away else pick.away
        head = (f"<span class='team'>{shown}</span>"
                f"<span class='opp'> over {other}</span>")
    else:
        head = (f"<span class='nopick'>No line</span>"
                f"<span class='opp'> — {pick.away} at {pick.home}</span>")

    chips = ""
    if pick.flipped and entered in (None, pick.team):
        chips += f"<span class='chip chip-flip'>FLIP TO {pick.team}</span>"
    if edge:
        chips += f"<span class='chip chip-edge'>{edge}</span>"
    if pick.field_on_team is not None and pick.field_on_team <= 0.2 and shown:
        chips += (f"<span class='chip chip-alone'>"
                  f"{pick.field_on_team:.0%} of the league</span>")

    bits = []
    if result:
        bits.append({"W": "Won", "L": "Lost"}.get(result, result))
        if game.get("away_score") is not None:
            bits.append(f"{pick.away} {int(game['away_score'])}"
                        f"–{int(game['home_score'])} {pick.home}")
    else:
        from .model import confidence
        bits.append(confidence(pick.prob))
        if show_pct and pick.prob is not None:
            bits.append(f"{pick.prob:.0%}")
        if pick.field_on_team is not None:
            bits.append(f"{pick.field_on_team:.0%} of the league")
        when = kickoff_label(game.get("kickoff"))
        if when:
            bits.append(when)
    return (f"<div class='{klass}'><div class='line'>"
            f"<span class='num'>{n}.</span> {head}{chips}</div>"
            f"<div class='sub'>{' · '.join(b for b in bits if b)}</div></div>")


def standout(n, pick):
    share = ""
    if pick.field_on_team is not None:
        share = f", only {pick.field_on_team:.0%} of the league on them"
    chance = f" — {pick.prob:.0%} to win" if pick.prob is not None else ""
    return (f"<div class='standout'><span class='num'>{n}.</span> "
            f"<span class='team'>{pick.team}</span>"
            f"<span class='opp'> over {pick.other}{chance}{share}</span></div>"
            + fpi_note(pick))


def fpi_note(pick):
    """Why this coin flip and not another one.

    Said in points of win probability and attributed to FPI, because
    the honest claim is narrow: an independent model prices this game
    differently from the book. It is not a claim that FPI is right —
    the market forecasts better than it does — only that among games
    already close enough to flip, this is the one where something
    other than the line has an opinion.
    """
    lean = getattr(pick, "fpi_lean", None)
    if lean is None or abs(lean) < 0.02:
        return ""
    pts = abs(lean)
    if lean > 0:
        body = (f"FPI rates {pick.team} {pts:.0%} more likely than the "
                f"line does — that disagreement is why this flip and "
                f"not another.")
    else:
        body = (f"FPI rates {pick.team} {pts:.0%} <em>less</em> likely "
                f"than the line does, so the second opinion is against "
                f"this one too.")
    return f"<div class='sub'>&#8990; {body}</div>"


def copy_list(numbered, tiebreak=None):
    """The list read off while typing into Splash."""
    lines = [f"{n:2d}. {pick.team} over {pick.other}" for n, pick in numbered
             if pick.team]
    if tiebreak is not None:
        lines.append(f"Tiebreaker: {tiebreak}")
    return "\n".join(lines)
