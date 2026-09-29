"""scripts/load.py — the other way into the database.

The parsing is already covered; what is not is the part that loses
work. This database lives in the repo and two writers push to it, so
the only failure that really costs anything is a load that overwrites
the app's week or never gets committed at all.

Runs entirely against a bare repo in a temp directory. No network.

    python tests/test_load.py
"""
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BOARD = os.path.join(HERE, "fixtures", "board_week5.txt")
WORK = tempfile.mkdtemp(prefix="gp_load_")


def git(cwd, *args, check=True):
    r = subprocess.run(("git",) + args, cwd=cwd, check=check,
                       capture_output=True, text=True)
    return r.stdout.strip()


def load(cwd, *args):
    """Run the script the way a session here would."""
    with open(BOARD) as fh:
        return subprocess.run(
            [sys.executable, "scripts/load.py", *args], cwd=cwd, stdin=fh,
            capture_output=True, text=True)


def meta(clone, key):
    db = sqlite3.connect(os.path.join(clone, "football_picks.db"))
    row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    db.close()
    return row and row[0]


def games(clone, week):
    db = sqlite3.connect(os.path.join(clone, "football_picks.db"))
    n = db.execute("SELECT COUNT(*) FROM game WHERE week=?", (week,)).fetchone()[0]
    db.close()
    return n


def write(clone, key):
    db = sqlite3.connect(os.path.join(clone, "football_picks.db"))
    db.execute("INSERT INTO meta (key, value) VALUES (?, ?)", (key, key))
    db.commit()
    db.close()


# ── a remote, and two clones that both write to it ─────────────────────
remote = os.path.join(WORK, "remote.git")
git(WORK, "init", "-q", "--bare", "-b", "main", remote)
mine, theirs = os.path.join(WORK, "mine"), os.path.join(WORK, "theirs")
git(WORK, "clone", "-q", remote, mine)
for name in ("gridiron", "scripts"):
    shutil.copytree(os.path.join(ROOT, name), os.path.join(mine, name))
shutil.copy(os.path.join(ROOT, "football_picks.db"), mine)
git(mine, "config", "user.email", "me@test")
git(mine, "config", "user.name", "Me")
git(mine, "add", "-A")
git(mine, "commit", "-qm", "init")
git(mine, "push", "-q", "-u", "origin", "main")
git(WORK, "clone", "-q", remote, theirs)
git(theirs, "config", "user.email", "app@test")
git(theirs, "config", "user.name", "App")

# ── loading without --push touches nothing outside the file ────────────
# Asked for week 6, handed week 5's board: the page wins, and says so.
r = load(mine, "6", "-")
assert r.returncode == 0, r.stderr
assert "36 games loaded" in r.stdout, r.stdout
assert "week 5, not 6" in r.stdout, r.stdout
assert games(mine, 5) == 36 and games(mine, 6) == 0
assert not git(mine, "log", "origin/main..HEAD", "--oneline"), \
    "a plain load must not commit anything"
git(mine, "checkout", "--", "football_picks.db")     # put it back
print("a plain load writes the file and nothing else OK")

# ── the app pushes; --push takes that on board before adding to it ─────
write(theirs, "app_wrote_this")
git(theirs, "commit", "-qam", "the app saved")
git(theirs, "push", "-q")

r = load(mine, "--push", "5", "-")
assert r.returncode == 0, r.stdout + r.stderr
assert "pulled 1 commit" in r.stdout, r.stdout
assert "pushed" in r.stdout, r.stdout

check = os.path.join(WORK, "check")
git(WORK, "clone", "-q", remote, check)
assert meta(check, "app_wrote_this") == "app_wrote_this", \
    "the app's write was flattened"
assert games(check, 5) == 36, "the load never reached the remote"
print("--push pulls the app's write, then adds to it OK")

# ── both wrote since: refuse, and change nothing ───────────────────────
git(theirs, "pull", "-q", "--ff-only")
write(theirs, "app_wrote_again")
git(theirs, "commit", "-qam", "the app saved again")
git(theirs, "push", "-q")
write(mine, "claude_wrote_here")
git(mine, "commit", "-qam", "loaded by hand")

r = load(mine, "--push", "5", "-")
assert r.returncode == 1, r.stdout
assert "diverged" in r.stdout, r.stdout
# it refuses before opening the database, so the file is untouched too
assert not git(mine, "status", "--porcelain", "--", "football_picks.db"), \
    "it loaded anyway after refusing"

after = os.path.join(WORK, "after")
git(WORK, "clone", "-q", remote, after)
assert meta(after, "app_wrote_again") == "app_wrote_again"
assert meta(after, "claude_wrote_here") is None, \
    "the local commit reached the remote after a refusal"
print("a diverged repo is refused, and nothing is loaded or lost OK")

# ── re-loading the same page changes nothing at all ────────────────────
git(mine, "reset", "-q", "--hard", "HEAD~1")
git(mine, "merge", "-q", "--ff-only", "origin/main", check=False)
git(mine, "fetch", "-q", "origin", "main")
git(mine, "merge", "-q", "--ff-only", "origin/main")
load(mine, "5", "-")
assert not git(mine, "status", "--porcelain", "--", "football_picks.db"), \
    "re-loading an identical page rewrote the database"
print("re-loading the same page is a no-op OK")

shutil.rmtree(WORK, ignore_errors=True)
print("\nALL LOAD TESTS PASS")
