# One-tap copy of the Splash board (iOS Shortcut)

Reads the board straight out of Safari — real page text, no screenshot and
no OCR — copies it, and opens the app. You paste. Two taps instead of one,
and **every game comes across**, which is the trade the one-tap version
could not make.

## Build it once

Shortcuts → **+** → **Edit** → add three actions:

1. **Run JavaScript on Web Page** — the whole script is one line:
   ```javascript
   completion(document.body.innerText);
   ```
   Requires Settings → Shortcuts → Advanced → **Allow Running Scripts**.
   Set the action's input to **Shortcut Input**.
2. **Copy to Clipboard** — feed it the JavaScript Result.
3. **Open URLs** — `https://shuggs-picks.streamlit.app`

Then ⓘ → **Show in Share Sheet** on. Name it *Load into Picks*.

## Use it

Splash board in Safari → Share → *Load into Picks* → the app opens → tap
the paste box under **Load this week's games**, paste, **Add these games**.

The same clipboard text can go into a Claude chat instead, if you'd rather
talk through the board than load it.

## Why it copies instead of just opening the app loaded

It used to put the board in the URL. A URL here carries almost nothing: the
whole page returned **414 Request-URI Too Large** from nginx, and even
filtered down it returned **502** — under nginx's cap but still too big for
Streamlit's own server. Shrinking the payload to team codes fit fine, but
codes alone lose games: Splash writes **JAC**, **WAS**, **LA** where ESPN
writes JAX, WSH and LAR, and it clips college codes the same way. A 25-game
board came in at 22.

The clipboard has no size limit, so the app gets the full page — codes
*and* the full team names printed lower down — and can find everything.

## How you know nothing is missing

The board states its own size in the day headers ("Saturday, Sep 19 **9
games**"). The app adds those up and reports against the total: *"Got all
31 games on the board"*, or a warning naming the codes it couldn't place.
A short import can't pass silently any more.

## If it ever breaks

Select the board in Safari by hand, copy, paste into the same box. That is
all the Shortcut is doing.
