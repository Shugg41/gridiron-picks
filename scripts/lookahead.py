#!/usr/bin/env python3
"""Print the coming weekend's ratings as TSV.

A thin caller for gridiron.lookahead so the CI log and the app screen
cannot drift apart — the same collect-and-rate the page runs, with the
answer written out instead of drawn.

    python scripts/lookahead.py 20261107 20261108
    python scripts/lookahead.py --ranked

With no dates, the next Thursday through Monday. This prints the WHOLE
slate — every game with a sportsbook line — because it exists for
scouting, and the games worth scouting are not only the ranked ones.
--ranked gives the short list the app's page shows.
Run via .github/workflows/data-probe.yml.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from gridiron import lookahead                                # noqa: E402


def main():
    args = sys.argv[1:]
    ranked = "--ranked" in args
    days = [a for a in args if not a.startswith("--")] or lookahead.weekend()
    print(f"# days: {', '.join(days)}", file=sys.stderr)
    rows = lookahead.rate(lookahead.collect(days, everything=not ranked))
    if not ranked:
        # The full listing includes lower-division games nobody prices.
        # A game with no line is not going on the card.
        rows = [r for r in rows if r["market"] is not None]
    fmt = lambda v: "" if v is None else f"{v:.4f}"
    print("kickoff\tleague\taway\thome\tranked\tmarket_home\tfpi_home\t"
          "pick\tconf\ttotal\tmoved\tsources")
    for r in rows:
        rank = "/".join(f"{k}#{v}" for k, v in sorted(r["rank"].items()))
        total = "" if r["total"] is None else f"{r['total']:g}"
        moved = ("" if r["moved"] is None
                 else f"{r['moved']:g} to {r['toward']}")
        print(f"{r['kickoff']}\t{r['league']}\t{r['away']}\t{r['home']}\t"
              f"{rank}\t{fmt(r['market'])}\t{fmt(r['fpi'])}\t{r['pick']}\t"
              f"{r['confidence']:.3f}\t{total}\t{moved}\t"
              f"{'+'.join(r['sources'])}")
    splits = [r for r in rows if r["split"]]
    priced = sum("market" in r["sources"] for r in rows)
    print(f"\n# {len(rows)} rated, {priced} with a line, "
          f"{len(splits)} where the line and FPI disagree", file=sys.stderr)
    for r in splits:
        print(f"#   {r['away']}@{r['home']}: market {r['market']:.0%} home, "
              f"fpi {r['fpi']:.0%} home", file=sys.stderr)


if __name__ == "__main__":
    main()
