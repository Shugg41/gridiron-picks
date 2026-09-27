# 🏈 Gridiron Picks

Personal helper for the Cherry Football Pool — a weekly CFB/NFL pick 'em
run on Splash Sports, 38 entries, weekly prize plus season places.

Live app: https://shuggs-picks.streamlit.app

## How a week goes

1. **Paste the board.** Run the *Load into Picks* shortcut on the Splash
   page in Safari, paste into the app. Any of the four pages works — the
   board, your entry, Pick Distribution, or the standings — and it works
   out which is which.
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
streamlit_app.py   wiring only
```

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

## Notifications (ntfy, via GitHub Actions)

- **lock-watch** — every 3h, for games kicking before Saturday noon,
  which lock at kickoff. This is the one that catches a Thursday nighter.
- **pick-reminder** — Saturday morning, if no entry has been pasted or a
  game has no pick.
- **results-recap** — the week's record, from Splash's grading.
- **keep-awake** — every 2h so Streamlit Cloud never sleeps.

Needs an `NTFY_TOPIC` repo Actions secret matching the topic subscribed
to in the [ntfy](https://ntfy.sh) app.

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
