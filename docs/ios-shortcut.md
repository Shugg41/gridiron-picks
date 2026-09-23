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

The filtering matters. Sending the whole page returns **414 Request-URI
Too Large** from nginx, which caps the request line around 8KB; a full
board with live scores runs well past that. Keeping only lines that could
be a team name cuts roughly 90% and lands near 1–2KB.

```javascript
var lines = document.body.innerText.split('\n').map(function(s){return s.trim();});
var keep = lines.filter(function(s){
  if (!s || s.length > 28) return false;      // prose, not a team name
  if (!/[A-Za-z]/.test(s)) return false;      // bare numbers
  if (/%$/.test(s)) return false;             // 46.7%
  if (/^\d+[-–]\d+$/.test(s)) return false;   // 1-0 records
  if (/(AM|PM)$/i.test(s)) return false;      // kickoff times
  if (/^(Winner|FINAL|LIVE|No picks|Rules|Make picks)$/i.test(s)) return false;
  return true;
});
completion('https://shuggs-picks.streamlit.app/?games=' + encodeURIComponent(keep.join('\n')));
```

## If it ever breaks

The app's **Load this week's games** box takes the same text: select the
board in Safari, copy, paste. No length ceiling, a few more taps.
