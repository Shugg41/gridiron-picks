# 🏈 Gridiron Picks — weekly college football pick helper

A companion Streamlit app for a weekly pick 'em league. It pulls the full FBS
slate from ESPN's free scoreboard API (no API key needed) and helps you decide,
record, and grade your picks each week.

## Run it

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## What it does

**Game board** — every FBS game for the week with:
- AP rank, overall record, kickoff time (ET), TV network, neutral-site flag
- The Vegas line (favorite ★ and spread) and over/under from ESPN
- Implied win probability from the moneyline (the % next to each team)
- Sort by kickoff, biggest spread (easiest calls first), or closest spread
  (the true toss-ups); filter to Top-25 or search for a team

**Making picks** — tap a team's button under its game card. Picks are saved to
a local SQLite file (`football_picks.db`). The sidebar sets your league style:
- **Straight up** or **against the spread** (the line is snapshotted at the
  moment you pick, so later line moves don't change your grading)
- Optional **confidence points** if your league ranks picks

**Grading** — once games go final, hit *Grade completed games* on the My Picks
tab. ATS grading uses your snapshotted line and handles pushes.

**Season tab** — running record, win %, and week-by-week results.

## Notes

- Week/season auto-detect from ESPN's "current week"; toggle it off in the
  sidebar to browse any week (e.g. to look ahead or back-fill).
- Lines usually appear a few days before kickoff; early-week games may show
  "no line yet".
- `football_picks.db` lives next to the app. On Streamlit Community Cloud the
  filesystem is ephemeral — run locally (or back the file up) if you want your
  season history to survive restarts.
