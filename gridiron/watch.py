"""Noticing when a game changes after you have picked it.

Between entering picks and the deadline, a line moves or a quarterback
lands on the injury report, and the pick you made on Wednesday is not the
pick you would make on Saturday. Nothing was watching that gap.

This has to run inside the app rather than in a GitHub Action: ESPN
returns 403 to GitHub's runners on the summary endpoint where injuries
live, while the app is served both. Keep-awake already loads the app
every two hours, which is the polling loop — no new scheduler needed.

It only ever reports on games that are picked and not yet locked, since
an alert about a game you cannot change is just noise.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class Change:
    away: str = ""
    home: str = ""
    kind: str = ""               # "line" | "injury"
    detail: str = ""

    def __str__(self):
        return f"{self.away} @ {self.home}: {self.detail}"


def snapshot(event, summary=None):
    """What a game looked like at a point in time: the line, who is
    favored, and how many players are on the injury report."""
    if not event:
        return None
    hurt = None
    if summary is not None:
        hurt = 0
        for block in (summary.get("injuries") or []):
            hurt += len(block.get("injuries") or [])
    return {"line": event.get("line"), "fav": event.get("fav_abbr"),
            "injuries": hurt}


# A line has to move by more than the noise in a quoted price before it
# is worth a push notification at 7am.
LINE_STEP = 1.0


def compare(before, now, away, home):
    """What changed that a picker would actually want to know about."""
    out = []
    if not before or not now:
        return out

    old_line, new_line = before.get("line"), now.get("line")
    old_fav, new_fav = before.get("fav"), now.get("fav")
    if old_fav and new_fav and old_fav != new_fav:
        # The market changing its mind about who wins is the strongest
        # version of this, and worth saying differently.
        out.append(Change(away, home, "line",
                          f"the favorite flipped from {old_fav} to {new_fav}"))
    elif (old_line is not None and new_line is not None
            and abs(new_line - old_line) >= LINE_STEP):
        direction = "toward" if new_line > old_line else "away from"
        out.append(Change(away, home, "line",
                          f"the line moved {abs(new_line - old_line):g} "
                          f"{direction} {new_fav or old_fav} "
                          f"({old_line:g} to {new_line:g})"))

    old_hurt, new_hurt = before.get("injuries"), now.get("injuries")
    if (old_hurt is not None and new_hurt is not None
            and new_hurt > old_hurt):
        added = new_hurt - old_hurt
        out.append(Change(away, home, "injury",
                          f"{added} more player{'s' if added != 1 else ''} "
                          f"on the injury report"))
    return out


def record(conn, season, week, away, home, snap, when=None):
    if not snap:
        return
    from . import store
    store.upsert(conn, "watch",
                 {"season": season, "week": week,
                  "away_code": away, "home_code": home},
                 {"line": snap.get("line"), "fav": snap.get("fav"),
                  "injuries": snap.get("injuries"), "seen_at": when})


def previous(conn, season, week):
    return {(a, h): {"line": ln, "fav": f, "injuries": inj}
            for a, h, ln, f, inj in conn.execute(
                "SELECT away_code, home_code, line, fav, injuries FROM watch "
                "WHERE season=? AND week=?", (season, week))}
