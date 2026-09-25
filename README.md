# 🏈 Gridiron Picks

Personal helper for a weekly college football pick 'em league that runs on
Splash Sports. Pulls live FBS games, lines, and analytics from ESPN's free
APIs (no key needed), tracks the manager's weekly pool, helps decide picks,
and grades the results.

Live app: https://shuggs-picks.streamlit.app

## Weekly routine

1. **Load the games** — screenshot the Splash board, send the images to
   Claude, paste the list it gives back into *Load this week's games*.
2. **Tap "Pick all N games for me"** — every game is picked for you using
   the devigged betting line (the best public predictor there is).
3. **Look at the 🔄 games** — these float to the top. They're the near
   coin flips where taking the underdog costs almost nothing on the season
   but separates you from the chalk crowd on the week. Tap **Why?** for the
   case in plain English: the line, ESPN's model, recent form, injuries.
   Flip 2–3 of them. A change anywhere else gets an ⚠️ risky change flag.
4. **Copy into Splash** — the numbered list at the bottom matches the order
   you pasted; the tiebreaker is pre-filled with the Vegas total of the last
   game. Hit *I entered them all* when done.
5. Picks **lock Saturday noon ET** (or kickoff if earlier). Results,
   season record and the full game list live under **More**.

## The numbers

**FPI** (ESPN's Football Power Index) is the app's second opinion: a
net-points rating — how many points a team beats an average opponent by on
a neutral field — that carries preseason priors, so it means something in
September when box-score stats are a two-game sample against nobody. The
app converts the FPI gap (plus home field: 2.6 pts college, 2.0 NFL) into a
win probability and compares it to the betting line. A gap of 6+ points of
win probability earns a **📈 FPI likes X** flag: a real reason to flip,
not a hunch.

**EPA** (expected points added per game, offense and defense) comes from
the same source and is the best single efficiency measure available here.

**Tap Stats on any game** for points/game, yards/game, yards per pass and
per rush attempt, third-down %, red-zone TD %, turnover margin and defensive
sacks. Every number is labeled with the season and games it's drawn from —
ESPN's current-season box scores aren't populated this early, so those fall
back to last season and say so. Turnover margin regresses hard; treat it as
luck, not skill.

**The betting line still decides the default pick** — it is the best single
predictor available. FPI, EPA and the box score are there to tell you when
it might be wrong.

## Importing the board

An iOS Shortcut copies the board out of Safari in one tap — see
**docs/ios-shortcut.md** — then you paste it into *Load this week's games*.
A raw dump of the whole page is exactly what it wants; it finds the games
itself, and it checks what it found against the game count the board
prints, so a short import says so instead of passing quietly.

## Automation (GitHub Actions)

- **keep-awake.yml** — visits the app every 2h so Streamlit Cloud never
  puts it to sleep.
- **pick-reminder.yml** — Saturday ~9 AM ET ntfy push if pool games are
  unpicked or not yet entered in Splash. Silent when everything's done.
- **results-recap.yml** — Saturday night + Sunday morning ntfy push with the
  week's record.

Notifications need an `NTFY_TOPIC` repo Actions secret (Settings → Secrets
and variables → Actions) matching the topic subscribed to in the
[ntfy](https://ntfy.sh) app.

## Persistence

`football_picks.db` (SQLite) is committed to this repo: the app pulls it on
server boot and pushes it back after every save, so picks survive Streamlit
Cloud's ephemeral filesystem. Configure in the Streamlit app's Secrets:

```toml
GITHUB_TOKEN = "github_pat_…"   # fine-grained PAT, Contents read/write on this repo
GITHUB_REPO  = "Shugg41/gridiron-picks"
```

Without secrets the app still works, local-only.

## Run locally

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```
