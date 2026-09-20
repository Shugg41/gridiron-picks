#!/usr/bin/env python3
"""Read the live app's rendered state from CI.

The dev sandbox can't reach the app or ESPN; CI can drive a real browser.
This prints what the app actually shows — the week header, whether the
"picks are not backed up" banner is present, and the results/season
numbers behind More — so the app's real behaviour can be verified instead
of assumed.
"""
import re
import sys

from playwright.sync_api import sync_playwright

APP = "https://shuggs-picks.streamlit.app/"


def text_of(page):
    best = ""
    for f in page.frames:
        try:
            t = f.locator("body").inner_text()
            if len(t) > len(best):
                best = t
        except Exception:
            pass
    return " ".join(best.split())


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 420, "height": 1400})
    page.goto(APP, wait_until="domcontentloaded", timeout=90_000)
    page.wait_for_timeout(25_000)

    for frame in page.frames:
        wake = frame.get_by_text(re.compile("get this app back up", re.I))
        if wake.count():
            print("app was asleep — waking")
            try:
                wake.first.click(timeout=5_000)
            except Exception:
                pass
            page.wait_for_timeout(45_000)
            break

    main = text_of(page)
    print("=" * 70)
    print("MAIN SCREEN")
    print("=" * 70)
    print(main[:2500])

    print("\n" + "=" * 70)
    print("CHECKS")
    print("=" * 70)
    print("  backup banner present:", "not backed up" in main)
    print("  flip headline present:", "Flip th" in main)
    m = re.search(r"Week\s+(\d+)", main)
    print("  week shown:", m.group(0) if m else "?")
    m = re.search(r"(\d+) of (\d+) picked", main)
    print("  picked:", m.group(0) if m else "none yet")

    # open More -> results / season so the graded record is visible
    for frame in page.frames:
        more = frame.get_by_text(re.compile(r"More — results", re.I))
        if more.count():
            try:
                more.first.click(timeout=5_000)
                page.wait_for_timeout(6_000)
            except Exception as e:
                print("  couldn't open More:", type(e).__name__)
            break
    for label in ("Season", "This week's results"):
        for frame in page.frames:
            tab = frame.get_by_text(label, exact=True)
            if tab.count():
                try:
                    tab.first.click(timeout=5_000)
                    page.wait_for_timeout(5_000)
                except Exception:
                    pass
                break

    # Force a write: saving the tiebreaker at its existing value changes no
    # data but calls save() -> push, which is the only real test of the token.
    for frame in page.frames:
        save_btn = frame.get_by_role("button", name="Save", exact=True)
        if save_btn.count():
            print("\nclicking tiebreaker Save to force a GitHub push...")
            try:
                save_btn.first.click(timeout=8_000)
                page.wait_for_timeout(12_000)
            except Exception as e:
                print("  save click failed:", type(e).__name__)
            break
    else:
        print("\nno Save button found (no picks yet?) — push not exercised")

    after = text_of(page)
    print("\nafter save — sync warning present:",
          "aren't backed up" in after or "rejected the token" in after)
    for marker in ("GitHub said:", "rejected the token", "Picks saved to GitHub",
                   "not backed up"):
        if marker in after:
            i = after.index(marker)
            print(f"  [{marker}] ...{after[max(0, i - 80):i + 160]}...")
    print("\n" + "=" * 70)
    print("WITH 'MORE' OPEN (tail)")
    print("=" * 70)
    print(after[-2500:])
    browser.close()
print("\nPROBE COMPLETE")
