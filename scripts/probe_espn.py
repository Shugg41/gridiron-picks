#!/usr/bin/env python3
"""Probe what ESPN will and won't serve, and confirm the live app is healthy.

The dev sandbox has no egress to ESPN, and a first CI probe showed ESPN
returns 403 to plain urllib from GitHub's runners. So this tries, in order:
  1. urllib with full browser-ish headers
  2. a real Chromium (Playwright) fetch from the same runner
  3. the live Streamlit app, whose rendered text says whether IT can reach ESPN
Whichever works becomes the way the stats layer gets its data.
"""
import json
import sys
import urllib.error
import urllib.request

SITE = "https://site.api.espn.com/apis/site/v2/sports/football"
CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues"
APP = "https://shuggs-picks.streamlit.app/"

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.espn.com/",
    "Origin": "https://www.espn.com",
}

URLS = {
    "cfb_scoreboard": f"{SITE}/college-football/scoreboard?limit=5&groups=80",
    "nfl_scoreboard": f"{SITE}/nfl/scoreboard?limit=5",
    "core_cfb_teams": f"{CORE}/college-football/seasons/2026/types/2/teams/99/statistics",
}


def banner(t):
    print("\n" + "=" * 70 + f"\n{t}\n" + "=" * 70)


banner("1. urllib with browser headers")
urllib_ok = {}
for name, url in URLS.items():
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=25) as r:
            payload = json.load(r)
            urllib_ok[name] = True
            print(f"  OK   {name}: {len(json.dumps(payload))} bytes, "
                  f"top keys = {list(payload)[:8]}")
    except urllib.error.HTTPError as e:
        urllib_ok[name] = False
        print(f"  FAIL {name}: HTTP {e.code}")
    except Exception as e:
        urllib_ok[name] = False
        print(f"  FAIL {name}: {type(e).__name__}: {e}")

banner("2. real browser (Playwright) from this same runner")
browser_ok = False
try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.goto("https://www.espn.com/", wait_until="domcontentloaded", timeout=60_000)
        for name, url in URLS.items():
            got = pg.evaluate(
                """async (u) => {
                     try {
                       const r = await fetch(u);
                       const t = await r.text();
                       return {status: r.status, len: t.length, head: t.slice(0, 120)};
                     } catch (e) { return {error: String(e)}; }
                   }""", url)
            print(f"  {name}: {got}")
            if got.get("status") == 200:
                browser_ok = True
        b.close()
except Exception as e:
    print(f"  Playwright unavailable/failed: {type(e).__name__}: {e}")

banner("3. is the LIVE APP reaching ESPN?")
try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.goto(APP, wait_until="domcontentloaded", timeout=90_000)
        pg.wait_for_timeout(20_000)
        text = ""
        for f in pg.frames:
            try:
                t = f.locator("body").inner_text()
                if len(t) > len(text):
                    text = t
            except Exception:
                pass
        flat = " ".join(text.split())
        print(f"  rendered text ({len(flat)} chars):")
        print("  " + flat[:1200])
        print("\n  VERDICT:",
              "ESPN UNREACHABLE FROM APP" if "Couldn't reach ESPN" in flat
              else "app is loading games OK" if "Week" in flat else "unclear")
        b.close()
except Exception as e:
    print(f"  app check failed: {type(e).__name__}: {e}")

banner("SUMMARY")
print(f"  urllib from CI: {urllib_ok}")
print(f"  browser from CI: {browser_ok}")
print("PROBE COMPLETE")
