"""The database, and keeping it in one piece across two writers.

Streamlit Community Cloud has no disk that survives a restart, so the
SQLite file lives in the GitHub repo: pulled when the app boots, pushed
after every write. That worked while the app was the only writer. It no
longer is — Claude writes to it too, on the user's behalf, when a page
will not parse or arrives as a screenshot.

Two things follow, and both are here rather than in the app:

* **Notice an outside write.** The app used to pull only at boot, so a
  commit made while it was running stayed invisible until it restarted.
  `sync()` compares the remote file's sha against the one last seen and
  re-pulls when it has moved.
* **Never clobber.** Before pushing, the sha is checked again. If the
  remote moved underneath us the push is refused and reported, rather
  than overwriting whatever the other writer just saved.

A game's identity is its two team codes within a week, not its position:
the board is fixed once posted, but keying on position would turn any
re-paste into a pile of duplicates.

No streamlit import, so this runs in the app, in tests, and in a script.
"""
import base64
import os
import sqlite3
import time

try:
    import requests
except ImportError:          # the notifier runs on a bare GitHub runner
    requests = None          # with no pip install, and sync is optional there

API = "https://api.github.com"

SCHEMA = """
CREATE TABLE IF NOT EXISTS game (
    season INTEGER NOT NULL, week INTEGER NOT NULL,
    away_code TEXT NOT NULL, home_code TEXT NOT NULL,
    away TEXT, home TEXT, seq INTEGER,
    day TEXT, kickoff TEXT, espn_id TEXT,
    status TEXT, away_score INTEGER, home_score INTEGER,
    PRIMARY KEY (season, week, away_code, home_code)
);
CREATE TABLE IF NOT EXISTS proposal (
    season INTEGER NOT NULL, week INTEGER NOT NULL,
    away_code TEXT NOT NULL, home_code TEXT NOT NULL,
    team TEXT, basis TEXT, created_at TEXT,
    PRIMARY KEY (season, week, away_code, home_code)
);
CREATE TABLE IF NOT EXISTS entry (
    season INTEGER NOT NULL, week INTEGER NOT NULL,
    away_code TEXT NOT NULL, home_code TEXT NOT NULL,
    team TEXT, result TEXT,
    PRIMARY KEY (season, week, away_code, home_code)
);
CREATE TABLE IF NOT EXISTS field (
    season INTEGER NOT NULL, week INTEGER NOT NULL,
    away_code TEXT NOT NULL, home_code TEXT NOT NULL,
    team TEXT NOT NULL, picks INTEGER, pct REAL, mkt_prob REAL,
    PRIMARY KEY (season, week, away_code, home_code, team)
);
CREATE TABLE IF NOT EXISTS field_card (
    season INTEGER NOT NULL, week INTEGER NOT NULL,
    entrant TEXT NOT NULL,
    away_code TEXT NOT NULL, home_code TEXT NOT NULL, team TEXT,
    PRIMARY KEY (season, week, entrant, away_code, home_code)
);
CREATE TABLE IF NOT EXISTS standing (
    season INTEGER NOT NULL, week INTEGER,
    name TEXT NOT NULL, entry_name TEXT NOT NULL,
    rank TEXT, points INTEGER, wins INTEGER, losses INTEGER,
    tie_diff INTEGER, me INTEGER DEFAULT 0,
    PRIMARY KEY (season, week, name, entry_name)
);
CREATE TABLE IF NOT EXISTS tiebreak (
    season INTEGER NOT NULL, week INTEGER NOT NULL,
    guess INTEGER, actual INTEGER,
    PRIMARY KEY (season, week)
);
CREATE TABLE IF NOT EXISTS watch (
    season INTEGER NOT NULL, week INTEGER NOT NULL,
    away_code TEXT NOT NULL, home_code TEXT NOT NULL,
    line REAL, fav TEXT, injuries INTEGER, seen_at TEXT,
    PRIMARY KEY (season, week, away_code, home_code)
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def connect(path):
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def meta_get(conn, key, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def upsert(conn, table, keys, values, keep=()):
    """Write a row whether or not it is already there, without UPSERT.

    SQLite's ON CONFLICT ... DO UPDATE needs 3.24 and a conflict target
    that lines up exactly with a constraint. Both held locally and
    something about them did not hold on Streamlit Cloud, where the real
    message is redacted — so rather than guess which of seven upserts
    broke, none of them use it. An UPDATE followed by an INSERT works
    everywhere and reads better anyway.

    The WHERE uses `IS` rather than `=` because it has to match NULLs:
    season-long standings are stored with no week, and `week = NULL` is
    never true. With `=` the UPDATE always missed, the INSERT always ran,
    and since NULLs do not collide in a primary key the rows quietly
    piled up on every paste.

    keys   : {column: value} identifying the row
    values : {column: value} to write
    keep   : columns where an existing value survives a new NULL
    """
    sets, params = [], []
    for col, val in values.items():
        sets.append(f"{col}=COALESCE(?, {col})" if col in keep else f"{col}=?")
        params.append(val)
    where = " AND ".join(f"{k} IS ?" for k in keys)
    cur = conn.execute(f"UPDATE {table} SET {', '.join(sets)} WHERE {where}",
                       params + list(keys.values()))
    if cur.rowcount:
        return 0
    cols = list(keys) + list(values)
    conn.execute(f"INSERT INTO {table} ({', '.join(cols)}) "
                 f"VALUES ({', '.join('?' * len(cols))})",
                 list(keys.values()) + list(values.values()))
    return 1


def meta_set(conn, key, value):
    upsert(conn, "meta", {"key": key}, {"value": str(value)})


# ── writing a week ──────────────────────────────────────────────────────
def save_games(conn, season, week, games, links=None):
    """Record the board. `links` is the ESPN event per game, or None.

    Re-pasting the same board updates in place — including filling in an
    ESPN id that was missing the first time — rather than duplicating,
    because identity is the two codes and not the row's position.
    """
    n = 0
    for i, g in enumerate(games, 1):
        ev = (links or {}).get(i - 1)
        upsert(conn, "game",
               {"season": season, "week": week,
                "away_code": g.away_code, "home_code": g.home_code},
               {"away": g.away or None, "home": g.home or None, "seq": i,
                "day": g.day or None,
                "kickoff": (ev or {}).get("date") or g.kickoff or None,
                "espn_id": (ev or {}).get("event_id"),
                "status": g.status or None,
                "away_score": g.away_score, "home_score": g.home_score},
               keep=("kickoff", "espn_id", "status", "away_score",
                     "home_score"))
        n += 1
    return n


def save_entry(conn, season, week, games):
    """Record what was actually picked, from the Splash entry or matrix.

    A game the user did not pick is stored with team NULL rather than
    left out. That distinction is the whole point: the entry page omits
    missing picks, which is how one went unnoticed for a week.
    """
    for g in games:
        upsert(conn, "entry",
               {"season": season, "week": week,
                "away_code": g["away_code"], "home_code": g["home_code"]},
               {"team": g.get("team"), "result": g.get("result")},
               keep=("result",))


def save_proposals(conn, season, week, picks):
    """What the app recommended, kept apart from what was entered — which
    is the only way to answer whether the advice is any good."""
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    for away, home, team, basis in picks:
        upsert(conn, "proposal",
               {"season": season, "week": week,
                "away_code": away, "home_code": home},
               {"team": team, "basis": basis, "created_at": now})


def save_field(conn, season, week, rows):
    """rows: [(away, home, team, picks, pct, mkt_prob)]"""
    for away, home, team, picks, pct, mkt in rows:
        upsert(conn, "field",
               {"season": season, "week": week, "away_code": away,
                "home_code": home, "team": team},
               {"picks": picks, "pct": pct, "mkt_prob": mkt},
               keep=("mkt_prob",))


def save_field_cards(conn, season, week, cards):
    """Every rival's whole card, not just the per-side totals.

    Percentages say how many took a side; they cannot say WHO, and who is
    the question when a weekly prize goes to one entry. Simulating the
    week needs each rival's card so that all of them can be scored
    against the same drawn outcome — entries in a pick 'em pool move
    together, and losing that correlation would invent separation that
    does not exist.

    cards: {entrant: {(away, home): team}}
    """
    for entrant, card in cards.items():
        for (away, home), team in card.items():
            upsert(conn, "field_card",
                   {"season": season, "week": week, "entrant": entrant,
                    "away_code": away, "home_code": home},
                   {"team": team})


def week_field_cards(conn, season, week):
    """{entrant: {(away, home): team}} for everyone but me."""
    out = {}
    for entrant, away, home, team in conn.execute(
            "SELECT entrant, away_code, home_code, team FROM field_card "
            "WHERE season=? AND week=?", (season, week)):
        if team:
            out.setdefault(entrant, {})[(away, home)] = team
    return out


def save_standings(conn, season, week, rows):
    """Season-long standings are stored with week NULL, which is why the
    upsert helper matches keys with IS rather than =."""
    for r in rows:
        upsert(conn, "standing",
               {"season": season, "week": week, "name": r.name,
                "entry_name": r.entry},
               {"rank": str(r.rank), "points": r.points, "wins": r.wins,
                "losses": r.losses, "tie_diff": r.tie_diff,
                "me": 1 if r.me else 0})


# ── reading a week ──────────────────────────────────────────────────────
def week_games(conn, season, week):
    """The board in kickoff order, which is the order Splash lists it."""
    rows = conn.execute(
        "SELECT away_code, home_code, away, home, seq, day, kickoff, espn_id, "
        "status, away_score, home_score FROM game WHERE season=? AND week=? "
        "ORDER BY COALESCE(kickoff, '9999'), seq",
        (season, week)).fetchall()
    cols = ["away_code", "home_code", "away", "home", "seq", "day", "kickoff",
            "espn_id", "status", "away_score", "home_score"]
    return [dict(zip(cols, r)) for r in rows]


def week_entry(conn, season, week):
    return {(a, h): (t, res) for a, h, t, res in conn.execute(
        "SELECT away_code, home_code, team, result FROM entry "
        "WHERE season=? AND week=?", (season, week))}


def week_field(conn, season, week):
    out = {}
    for a, h, t, pct in conn.execute(
            "SELECT away_code, home_code, team, pct FROM field "
            "WHERE season=? AND week=?", (season, week)):
        out.setdefault((a, h), {})[t] = pct
    return out


def latest_week(conn, season=None):
    row = conn.execute(
        "SELECT season, week FROM game " +
        ("WHERE season=? " if season else "") +
        "ORDER BY season DESC, week DESC LIMIT 1",
        (season,) if season else ()).fetchone()
    return (row[0], row[1]) if row else (None, None)


# ── GitHub sync ─────────────────────────────────────────────────────────
class Sync:
    """Keeps the SQLite file in the repo, with two writers in mind."""

    def __init__(self, repo, token, path="football_picks.db", db_path=None):
        self.repo, self.token = repo, token
        self.path, self.db_path = path, db_path
        self.reason = None

    @property
    def enabled(self):
        return bool(self.repo and self.token and requests)

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json"}

    def _url(self):
        return f"{API}/repos/{self.repo}/contents/{self.path}"

    def remote(self):
        """(sha, content_bytes) for the stored file, or (None, None)."""
        try:
            r = requests.get(self._url(), headers=self._headers(), timeout=20)
        except requests.RequestException as exc:
            self.reason = f"network: {type(exc).__name__}"
            return None, None
        if r.status_code == 404:
            self.reason = None
            return None, None
        if r.status_code != 200:
            self.reason = self._why(r)
            return None, None
        body = r.json()
        return body.get("sha"), base64.b64decode(body.get("content", ""))

    def pull_if_changed(self, last_sha):
        """Replace the local file when the remote has moved, returning the
        new sha or None.

        Takes a sha rather than a connection on purpose: this swaps the
        file out wholesale, and any handle open across the call would be
        left reading a database that no longer exists. Use open_synced()
        rather than calling this with a connection in hand.
        """
        if not self.enabled:
            return None
        sha, blob = self.remote()
        if sha is None or not blob or sha == last_sha:
            return None
        with open(self.db_path, "wb") as fh:
            fh.write(blob)
        return sha

    def push(self, conn, message=None):
        """Write the file back, refusing if the remote moved underneath.

        A refusal is not a failure to paper over: it means the other
        writer saved something, and overwriting it would silently destroy
        their work. The caller re-pulls and re-applies.
        """
        if not self.enabled:
            return False
        seen = meta_get(conn, "remote_sha")
        sha, _blob = self.remote()
        if seen and sha and sha != seen:
            self.reason = "remote changed since last read — pull first"
            return False
        conn.commit()
        with open(self.db_path, "rb") as fh:
            content = base64.b64encode(fh.read()).decode()
        payload = {"message": message or f"Update picks {time.strftime('%F %H:%M')}",
                   "content": content}
        if sha:
            payload["sha"] = sha
        try:
            r = requests.put(self._url(), headers=self._headers(),
                             json=payload, timeout=30)
        except requests.RequestException as exc:
            self.reason = f"network: {type(exc).__name__}"
            return False
        if r.status_code in (200, 201):
            new_sha = ((r.json().get("content") or {}).get("sha"))
            if new_sha:
                meta_set(conn, "remote_sha", new_sha)
                conn.commit()
            self.reason = None
            return True
        self.reason = self._why(r)
        return False

    @staticmethod
    def _why(r):
        """GitHub's own words, so a bad token says so instead of hiding
        behind a generic failure — this app has already lost a week to a
        silently rejected credential."""
        try:
            msg = r.json().get("message", "")
        except ValueError:
            msg = (r.text or "")[:120]
        return f"{r.status_code} {msg}".strip()


def open_synced(db_path, sync):
    """Open the database, first taking any newer copy from the repo.

    The connection is opened, closed, and reopened around the pull
    because the pull replaces the file — which is exactly what makes a
    write from outside the running app visible to it.
    """
    conn = connect(db_path)
    last = meta_get(conn, "remote_sha")
    conn.close()
    fresh_sha = sync.pull_if_changed(last) if sync and sync.enabled else None
    conn = connect(db_path)
    if fresh_sha:
        meta_set(conn, "remote_sha", fresh_sha)
        conn.commit()
    return conn


def sync_from_env(db_path, env=None):
    env = env or os.environ
    return Sync(env.get("GITHUB_REPO"), env.get("GITHUB_TOKEN"),
                db_path=db_path)


# ── bringing the old tables across ──────────────────────────────────────
def migrate_legacy(conn):
    """Carry weeks already recorded under the old schema into the new one.

    The old `slate`/`picks` tables keyed on ESPN event ids and stored a
    pick as an abbreviation; the new tables key on the two codes. Only
    rows that can be mapped confidently come across, and nothing is
    deleted — the old tables stay until the new ones have been checked
    against the live app.
    """
    have = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if "slate" not in have or "picks" not in have:
        return 0, 0

    games = picks = 0
    for season, week, matchup, eid in conn.execute(
            "SELECT season, week, matchup, event_id FROM slate"):
        codes = _codes(matchup)
        if not codes:
            continue
        away, home = codes
        conn.execute(
            "INSERT OR IGNORE INTO game (season, week, away_code, home_code, "
            "espn_id) VALUES (?,?,?,?,?)", (season, week, away, home, eid))
        games += 1

    for season, week, matchup, pick, result in conn.execute(
            "SELECT season, week, matchup, pick_abbr, result FROM picks"):
        codes = _codes(matchup)
        if not codes:
            continue
        away, home = codes
        conn.execute(
            "INSERT OR IGNORE INTO entry (season, week, away_code, home_code, "
            "team, result) VALUES (?,?,?,?,?,?)",
            (season, week, away, home, pick, result))
        picks += 1
    conn.commit()
    return games, picks


def _codes(matchup):
    """"ATL @ GB" or "BAL VS DAL" -> ("ATL", "GB")."""
    if not matchup:
        return None
    for sep in (" @ ", " VS ", " vs "):
        if sep in matchup:
            a, h = matchup.split(sep, 1)
            a, h = a.strip(), h.strip()
            if a and h:
                return a, h
    return None
