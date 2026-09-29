#!/usr/bin/env python3
"""Load a Splash page into the database from outside the app.

    python3 scripts/load.py 5 board.txt
    python3 scripts/load.py 4 matrix.txt standings.txt
    pbpaste | python3 scripts/load.py --push 5 -

The app is the normal way in, and it has to stay that way: nothing that
matters can wait on a session being open at noon on a Saturday. This is
the other way in — for a page the app will not parse, a week being
backfilled, a page that arrived as an image and had to be transcribed,
or simply because handing it over is easier. It runs gridiron.ingest,
the same function the paste bar calls, so the two cannot drift.

`-` reads the page from stdin. A season-long standings page is not
week-specific; pass any week and it is still stored against the season.

--push is the part that matters. This database lives in the repo
because Streamlit Cloud has no disk that survives a restart, so a load
that is not committed is lost when the container goes. --push pulls
whatever the app has written first, refusing to go on if the two have
diverged rather than picking a winner, then commits and pushes.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from gridiron import ingest, splash, store            # noqa: E402

SEASON = 2026
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DB = os.path.join(ROOT, "football_picks.db")


def git(*args, check=True):
    return subprocess.run(("git",) + args, cwd=ROOT, check=check,
                          capture_output=True, text=True).stdout.strip()


def catch_up():
    """Take on whatever the app has pushed since, or stop.

    The app writes this file too. Fast-forward only: if both have
    written, that is a real conflict in a binary file and guessing which
    one to keep is how the other writer's week disappears.
    """
    git("fetch", "origin", "main")
    behind, ahead = git("rev-list", "--left-right", "--count",
                        "origin/main...HEAD").split()
    if int(behind) and int(ahead):
        print(f"diverged from origin by {behind}/{ahead} commits — "
              f"sort that out before loading, or the app's writes are lost")
        return False
    if int(behind):
        git("merge", "--ff-only", "origin/main")
        print(f"pulled {behind} commit(s) the app had pushed")
    return True


def publish(summary):
    if not git("status", "--porcelain", "--", "football_picks.db"):
        print("nothing changed in the database — not committing")
        return 0
    git("add", "--", "football_picks.db")
    git("commit", "-m", f"Load {summary}")
    for attempt in range(4):
        try:
            git("push", "-u", "origin", "main")
            print("pushed")
            return 0
        except subprocess.CalledProcessError as exc:
            if attempt == 3:
                print(f"push failed: {exc.stderr.strip()}")
                return 1
            __import__("time").sleep(2 ** (attempt + 1))
    return 1


def main(argv):
    args = [a for a in argv[1:] if a != "--push"]
    push = "--push" in argv
    if len(args) < 2 or not args[0].isdigit():
        print(__doc__.strip())
        return 2
    week = int(args[0])
    if push and not catch_up():
        return 1

    conn = store.connect(DB)
    bad, loaded = 0, []
    for path in args[1:]:
        text = sys.stdin.read() if path == "-" else open(path).read()
        kind = splash.sniff(text)
        level, message = ingest.load(conn, SEASON, week, text)
        print(f"{'stdin' if path == '-' else os.path.basename(path)}: "
              f"[{kind}] {message}")
        bad += level != "ok"
        if level == "ok":
            loaded.append(kind or "page")
    # Last, and only for weeks Splash has not defined: the old tables
    # spell teams ESPN's way, so they duplicate rather than overwrite.
    g, pk = store.migrate_legacy(conn)
    if g or pk:
        print(f"legacy: {g} games, {pk} picks carried across")
    conn.commit()
    conn.close()

    if push and loaded:
        bad += publish(f"week {week}: " + ", ".join(loaded))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
