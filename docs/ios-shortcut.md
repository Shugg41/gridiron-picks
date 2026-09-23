# One-tap import from Splash (iOS Shortcut)

Reads the Splash board straight out of Safari — real page text, no
screenshot and no OCR — and opens the app with the games loaded.

## Build it once

Shortcuts → **+** → **Edit** → add two actions:

1. **Run JavaScript on Web Page** — paste the script below.
   Requires Settings → Shortcuts → Advanced → **Allow Running Scripts**.
   Set the action's input to **Shortcut Input**.
2. **Open URLs** — feed it the JavaScript Result.

Then ⓘ → **Show in Share Sheet** on. Name it *Load into Picks*.

Use: Splash board in Safari → Share → *Load into Picks*.

## The script

```javascript
var seen = document.body.innerText.split('\n').map(function(s){return s.trim();});
var skip = /^(FINAL|LIVE|AM|PM|ET|CT|MT|PT|OT|TBD|VS|AT)$/;
var keep = seen.filter(function(s){
  return /^[A-Z][A-Z0-9&.()'-]{1,5}$/.test(s) && !skip.test(s);
});
completion('https://shuggs-picks.streamlit.app/?games=' + encodeURIComponent(keep.join('\n')));
```

It keeps **team codes only** — the all-caps 2–6 character lines (DET, BUF,
UNC, CLEM), minus scoreboard furniture. Everything else on the page goes:
records, win percentages, kickoff times, "Winner", "1 pick", day headers.
A full board comes out around 200 characters encoded.

### Why the payload has to be this small

Sending the whole page returned **414 Request-URI Too Large** — nginx caps
the request line near 8KB. Filtering to "lines that could be a team name"
cleared nginx but then returned **502 Bad Gateway**: the URL still passed
the front door and Streamlit's own server dropped it. Codes only is two
orders of magnitude under either limit, with room for a 40-game board.

Codes alone are enough because the app matches on abbreviations too, and
pairs the two teams of a game by how close their lines are.

## Note for whoever touches the matcher

Codes-only input is **dense** — two lines per game instead of ten. The old
"within 8 lines" rule then spans four games, which let the cross-league
code collisions re-pair (the Dolphins' `MIA` with a college `WAKE`, three
games down). `match_paste_lines()` now claims each line for exactly one
game, closest pairing first, so a real `MIA`/`SF` one line apart takes
`MIA` before any invention can. Scratchpad `abbrev_test.py` guards it.

## If it ever breaks

The app's **Load this week's games** box takes the same text: select the
board in Safari, copy, paste. No length ceiling, a few more taps.
