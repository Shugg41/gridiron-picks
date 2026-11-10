# Gridiron Picks — standing rules

One entry in a 38-entry straight-up pick'em (Cherry Football Pool on
Splash). Weekly prize is winner-take-all, so the aim is to win a week,
not to finish respectably. Picks lock Saturday noon ET, or at kickoff
for anything earlier. The app deploys from `main`.

## What the weekly job is

Scout for underdogs that might do something unexpected, each with a
specific football reason. He chooses which to take. Do not try to prove
an edge, do not build expected-value tables, and do not choose for him.

- **Research first.** `gh workflow run research.yml --ref main` writes
  `data/research_week<N>.md`: every game read from ESPN's own records
  (quarterback changes from box scores, the NFL injury list, form,
  rest, look-ahead and letdown spots, totals, turnovers, line moves,
  FPI) and the underdogs whose reasons outweigh the reasons against.
  With the board loaded it reads the board's games in Splash's codes;
  before that, the whole slate. It also runs on a schedule and the app
  shows the newest page. It is the reading list: web search is for
  confirming what it infers, above all who is playing quarterback.
- **Monday**: scout from that page. The board is not posted until
  Tuesday morning.
- **Wednesday**: the card, then three to six chaos candidates. Record
  each one in the ledger and text the list.
- **Saturday morning**: report what changed. News only — see below.

## Rules learned the hard way

1. **Our own data beats a search summary.** On a number — a spread, a
   record, a score — the ESPN feed and the database win. Search
   summaries were wrong three times in two weeks (a spread with the
   wrong team favoured, a year-old concussion report, a two-week-old
   stat line) and the feed was right each time.
2. **A news item needs a dated source.** If the article's date cannot
   be established, it is not news. Check the year.
3. **Read last week's scores from the database before searching.**
4. **The Saturday check reports, it does not rule.** Say what changed
   and which reason it touches. Never say "don't flip" or "flip": one
   reason going away is not the pick going away. Penn State was talked
   off the list on a healthy-quarterback report and won.
5. **Every candidate goes in the ledger** (`scripts/chaos.py add`),
   with the market price, before it is mentioned to him. A candidate
   that is not recorded cannot be graded.
6. **The list goes to his phone** (`gh workflow run text.yml`). A long
   post in the chat was not read before week 10's card was filled in,
   and four winning underdogs went unused.
7. **Short.** He reads on a phone. Lead with the answer; a routine's
   reply should fit on one screen.
8. No field, crowd or rival analysis unless he asks. No "honestly".

## Mechanics

- Tests: `set -o pipefail && ./tests/run.sh`. Without pipefail a pipe
  through `tail` reports tail's status and a red suite reads green.
- This container cannot reach ESPN. Anything that needs it runs in
  Actions: `gh workflow run data-probe.yml -f scope=lookahead` (or
  `opinions`, which also records `data/opinions.tsv`).
- The database is committed. Pull before writing it, and never let two
  writers race: text files (`data/announced.txt`, `data/chaos.tsv`) are
  where CI writes, so a collision is a one-line merge.
- ESPN and Splash spell three NFL teams differently: LAR/LA, JAX/JAC,
  WSH/WAS. Grade by side (home or away), never by abbreviation.
- The results watch settles the ledger as games finish. Every other
  scheduled workflow also calls it, because GitHub's scheduler drops
  runs.
- `python scripts/chaos.py report` is the record: flagged, hit, and
  what the prices said to expect.
- College has no usable injury list on ESPN (three teams, entries from
  2020). A college quarterback change is inferred: the top passer in
  the last game against the season's leading passer.
- An "opening" line can be a summer look-ahead number. The research
  ignores a move of more than seven points for that reason.
