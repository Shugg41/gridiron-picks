#!/usr/bin/env python3
"""Load a saved Splash page into the database from outside the app.

    python3 scripts/load.py 5 board.txt
    python3 scripts/load.py 4 matrix.txt standings.txt

The app is the normal way in. This exists for the cases it cannot cover:
a page that will not parse there, a week being backfilled after the
fact, or a page that arrived as an image and had to be transcribed by
hand. It runs gridiron.ingest — the same function the paste bar calls —
so there is no second implementation to keep in step.

A season-long standings page is not week-specific; pass any week and it
will still be stored against the season.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from gridiron import ingest, splash, store            # noqa: E402

SEASON = 2026
DB = os.path.join(os.path.dirname(__file__), "..", "football_picks.db")


def main(argv):
    if len(argv) < 3 or not argv[1].isdigit():
        print(__doc__.strip())
        return 2
    week = int(argv[1])
    conn = store.connect(DB)
    bad = 0
    for path in argv[2:]:
        text = open(path).read()
        level, message = ingest.load(conn, SEASON, week, text)
        print(f"{os.path.basename(path)}: [{splash.sniff(text)}] {message}")
        bad += level != "ok"
    # Last, and only for weeks Splash has not defined: the old tables
    # spell teams ESPN's way, so they duplicate rather than overwrite.
    g, pk = store.migrate_legacy(conn)
    if g or pk:
        print(f"legacy: {g} games, {pk} picks carried across")
    conn.commit()
    conn.close()
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
