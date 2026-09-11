# 🏈 Gridiron Picks

Personal helper for a weekly college football pick 'em league that runs on
Splash Sports. Pulls live FBS games, lines, and analytics from ESPN's free
APIs (no key needed), tracks the manager's weekly pool, helps decide picks,
and grades the results.

Live app: https://shuggs-picks.streamlit.app

## Weekly routine

1. **Import the pool** — screenshot the Splash board, send the images to
   Claude, paste the game list it returns into *My Pool → Import*. (Or type
   matchups yourself, one per line, or tap ➕ on the Game board tab.)
2. **⭐ Fill with favorites** — one tap picks the Vegas favorite everywhere.
3. **Adjust on vibes** — flip individual games. Badges help: 🔒 safe,
   ⚠️ toss-up, 🛣 road favorite, 🎲 you're on the dog. Each pool game has a
   📊 Breakdown with ESPN's matchup predictor, recent form, and injuries.
4. **Enter in Splash** — copy the numbered *Splash entry list*, enter the
   picks in Splash, hit *Mark all as entered*.
5. Picks **lock Saturday noon ET** (or kickoff if earlier); after games go
   final, *Grade completed games* scores the week and the Season tab keeps
   the running record.

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
