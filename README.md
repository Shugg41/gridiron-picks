# 🏈 Gridiron Picks

Personal helper for the Cherry Football Pool — a weekly CFB/NFL pick 'em
run on Splash Sports, 38 entries, weekly prize plus season places.

Live app: https://shuggs-picks.streamlit.app

## How a week goes

**Use the full page, not the in-game overlay.** The overlay (the one
starting "Close") keeps the tiebreaker in a form field, and `innerText`
cannot see a form field, so the total-score guess comes through blank.
The full page (starting "Back to entries") renders it as text. Both
parse; only one carries the tiebreaker.

**The week comes off the page, not the box.** Every page names its
week, so the number box is only a fallback for the pages that do not.

1. **Paste the board.** Run the *Load into Picks* shortcut on the Splash
   page in Safari, paste into the app. Any of the five pages works — the
   board, your entry, Pick Distribution, Picks by Week, or the standings
   — and it works out which is which. The board states its own game
   count, so a short paste is reported rather than accepted.
2. **Read the card.** Every game, in kickoff order, numbered to match
   Splash. The flips it would make are called out at the top.
3. **Type them into Splash**, off the numbered list at the bottom.
4. **Paste your entry back.** That is how the app learns what you
   actually did, and it brings Splash's own results with it.
5. **Paste Pick Distribution** once the deadline passes, to see where you
   stood against the field.

The app never holds your picks. Splash does. There is nothing to tick off
in two places.

## Why it is built this way

Splash defines the week; ESPN only decorates it. Earlier versions had
that backwards — ESPN decided which games existed and the pasted board
tried to match into it — which lost games whenever Splash spelled a team
differently (JAC for JAX, WAS for WSH, LA for LAR) and invented games
when codes collided across leagues. Now a game that cannot be matched to
ESPN keeps its place with no line, because a missing line is cosmetic and
a missing game is not.

```
gridiron/
  splash.py   the five Splash pages
  espn.py     odds, FPI, team stats — enrichment only
  model.py    probabilities, confidence, flips, the strategy dial
  store.py    schema, migration, GitHub sync
  view.py     cards and formatting
  ingest.py   a pasted page in, a database write out
streamlit_app.py   wiring only
```

## A game you never picked

Splash scores an unpicked game as a loss. It no longer autopicks the
favorite for you, which used to make a missed game a coin flip you
mostly won; now it is a certain nought. That raises the stakes on the
early-lock alert more than anything else here.

It also means two records are true at once, so both are shown: the
pick record over the games actually picked, and Splash's, which counts
the blanks as losses. Only the Picks by Week page states that a game
was never picked — the entry page prints it as "0 points", identical
to a game picked wrong — so a page that cannot make that distinction
is never allowed to overwrite one that has.

## The strategy dial

The weekly prize is winner-take-all; the season pays several places. So
the only question is whether a paying season finish is still reachable:
points behind the cutoff, divided by weeks left. Under a point a week is
noise in a thirty-game week, so the app plays chalk plus two or three
genuine coin flips. Beyond that, with the season gone, it hunts a weekly
win with five or six contrarian picks. The header always says which and
why.

Flips go to the closest games, and once the field is known, to the
closest games the crowd is most piled against — a coin flip nobody else
is fading buys no separation.

## What it works out for you

**Odds this week.** The card is played out four thousand times against
the other entries' actual cards, so you get a chance of winning the week
rather than an expected score. Everyone is scored against the same drawn
outcome each trial, because a pick 'em pool is thirty-one games where
nearly everyone takes the same favorites — treating entries as
independent would invent separation and overstate your chances badly.
Needs the Picks by Week page, which is the only one carrying every
entry's card.

**What the flips are worth.** The proposed card and pure chalk, played
against the same field and the same outcomes. Flipping gives up a little
expected score to buy a real chance of finishing alone at the top, and
the app prints that trade every week. If it ever reads the wrong way
round, stop flipping.

**Kickoff times without ESPN.** The board prints a day header and a
clock, and the lock line carries the year, so every game is dated from
the paste alone. That is what orders the card and what makes a Thursday
nighter lock at kickoff instead of at Saturday noon — none of it waits on
an ESPN match, because the game that fails to match is exactly the one
that would otherwise sort by the text "Mon 8:15pm" and never warn.

**A second opinion.** Every pick used to come from one number: the
betting line. ESPN's FPI is now fetched for the teams in any game
already close enough to flip, and its view of the game is compared
with the market's.

It is allowed to do one narrow thing: decide which coin flip to take.
FPI disagreeing with the line does not make FPI right — the market
forecasts better, and overriding it would cost points — but choosing
between two near-even games was previously arbitrary, and "the one an
independent model prices differently" beats list order. It never
changes which games are candidates and never touches the other
thirty. The ordering is lexicographic rather than weighted: blending
leverage and disagreement would need a number nobody has evidence
for.

Measured on a real slate: 28 games priced, median disagreement 2.7
points of win probability, 7 games at 5 or more. Mostly the two
agree, which is the expected and reassuring result.

**Line movement.** ESPN's core API carries the opening line as well as
the current one. The crowd piles onto favorites, so a favorite getting
cheaper since it opened is usually sharper money on the other side — a
flip where the line has come toward the dog gets a note saying the money
agrees, and one where it has gone the other way gets told to think
again. Shown rather than scored into the ranking: there is no evidence
yet on what it should be worth, and a made-up weight would only hide the
guess.

**Late changes.** Between picking and the deadline, a line moves or a
quarterback lands on the injury report. Each picked, unlocked game is
compared against how it last looked, and anything real gets a push. Half
a point is noise; a point or more, a flipped favorite, or players added
to the report are not. This runs inside the app because ESPN refuses
GitHub's runners on the injuries endpoint — keep-awake's two-hourly load
is the polling loop.

## Notifications (ntfy, via GitHub Actions)

- **lock-watch** — every 3h, for games kicking before Saturday noon,
  which lock at kickoff. This is the one that catches a Thursday nighter.
- **pick-reminder** — Saturday morning, if no entry has been pasted or a
  game has no pick.
- **results-recap** — the week's record, from Splash's grading.
- **keep-awake** — every 2h so Streamlit Cloud never sleeps.

Needs an `NTFY_TOPIC` repo Actions secret matching the topic subscribed
to in the [ntfy](https://ntfy.sh) app.

## Handing a page to Claude instead

```bash
python3 scripts/load.py 5 board.txt
python3 scripts/load.py --push 5 -          # page on stdin, committed
python3 scripts/load.py --push 4 matrix.txt standings.txt
```

Same function the paste bar calls (`gridiron/ingest.py`), so the two
cannot drift. Paste the page into a session and it gets loaded here —
including a page the app will not parse, a week backfilled after the
fact, or a page that arrived as an image, which a session can read and
the app cannot.

`--push` is the part that matters, because this database lives in the
repo and a load that is not committed dies with the container. It pulls
whatever the app has written first and refuses outright if both have
written since, rather than picking a winner — a binary file has no merge
and guessing is how a week disappears.

**The app still has to stand alone.** Nothing at noon on a Saturday can
wait on a session being open, so the paste bar, the card and all four
alerts work with nobody here.

Weeks 3-5 are already loaded. Week 3 came from the old ESPN-keyed
tables; weeks 4 and 5 came from Splash pages. Those two sources must
never be merged into one week — the old tables spell teams ESPN's way
(LAR, JAX, WSH, TA&M) where Splash says LA, JAC, WAS, TAMU, so merging
does not overwrite, it duplicates. `migrate_legacy` now skips any week
Splash has already defined.

## Tests

```bash
./tests/run.sh
```

No network. `tests/fixtures/` holds verbatim copies of real Splash pages,
because every parser bug this project has had came from writing against a
remembered shape rather than the real one.

## Persistence

`football_picks.db` lives in this repo: Streamlit Cloud has no disk that
survives a restart. Two writers are assumed — the app, and Claude in a
session — so the store re-pulls when the remote file has moved and
refuses a push that would overwrite the other's work. Configure in the
app's Secrets:

```toml
GITHUB_TOKEN = "github_pat_…"   # fine-grained PAT, Contents read/write
GITHUB_REPO  = "Shugg41/gridiron-picks"
```

Without them the app still runs, local only.

## Run locally

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```
