#!/usr/bin/env python3
"""Print the coming weekend's ratings as TSV.

A thin caller for gridiron.lookahead so the CI log and the app screen
cannot drift apart — the same collect-and-rate the page runs, with the
answer written out instead of drawn.

    python scripts/lookahead.py 20261107 20261108

With no dates, the next Thursday through Monday.
Run via .github/workflows/data-probe.yml.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from gridiron import lookahead                                # noqa: E402


def main():
    days = sys.argv[1:] or lookahead.weekend()
    print(f"# days: {', '.join(days)}", file=sys.stderr)
    rows = lookahead.rate(lookahead.collect(days))
    fmt = lambda v: "" if v is None else f"{v:.4f}"
    print("kickoff\tleague\taway\thome\tranked\tmarket_home\tfpi_home\t"
          "pick\tconf\tsources")
    for r in rows:
        rank = "/".join(f"{k}#{v}" for k, v in sorted(r["rank"].items()))
        print(f"{r['kickoff']}\t{r['league']}\t{r['away']}\t{r['home']}\t"
              f"{rank}\t{fmt(r['market'])}\t{fmt(r['fpi'])}\t{r['pick']}\t"
              f"{r['confidence']:.3f}\t{'+'.join(r['sources'])}")
    splits = [r for r in rows if r["split"]]
    priced = sum("market" in r["sources"] for r in rows)
    print(f"\n# {len(rows)} rated, {priced} with a line, "
          f"{len(splits)} where the line and FPI disagree", file=sys.stderr)
    for r in splits:
        print(f"#   {r['away']}@{r['home']}: market {r['market']:.0%} home, "
              f"fpi {r['fpi']:.0%} home", file=sys.stderr)


if __name__ == "__main__":
    main()
