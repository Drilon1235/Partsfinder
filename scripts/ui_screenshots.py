"""Screenshots of every main screen of the app, with fixed test data (app/test/mock_partsfinder.js).

Use it after a UI change to see at a glance whether the screens still look the same and consistent
(375-1440 px), and for the demo pictures. Needs Playwright once:
    pip install playwright && python -m playwright install chromium
Run (from the project folder):
    python scripts/ui_screenshots.py            # pictures in data/ui-screens (outside git)
The script fails when a screen gives a JavaScript error or the window scrolls sideways.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

PROJECT = Path(__file__).resolve().parent.parent
PAGE = (PROJECT / "app" / "renderer" / "index.html").as_uri()
MOCK = PROJECT / "app" / "test" / "mock_partsfinder.js"
OUT = PROJECT / "data" / "ui-screens"
SIZES = [(1440, 960), (820, 1000), (390, 844)]


async def ask(page, text: str) -> None:
    await page.fill("#query", text)
    await page.keyboard.press("Enter")
    await page.wait_for_timeout(400)


async def screens(page, shot) -> None:
    await shot("01-empty")
    await ask(page, "M8x30 bolt 8.8")
    await shot("02-results")
    await page.click(".segmented button[data-mode=list]")
    await page.wait_for_timeout(200)
    await shot("02b-results-as-list")
    await page.click(".segmented button[data-mode=grid]")
    await ask(page, "nothing like a flux capacitor")
    await shot("03-not-found")
    await ask(page, "broken query")
    await shot("03b-error")
    await ask(page, "M8x30 bolt 8.8")
    await page.locator(".view .card-title").first.click()
    await page.wait_for_timeout(300)
    await shot("04-read-more")
    await page.get_by_role("button", name="Similar shapes").click()
    await page.wait_for_timeout(300)
    await page.evaluate("document.querySelector('#detail').scrollTop = 1e6")
    await shot("05-similar-shapes")
    await page.keyboard.press("Escape")
    cards = page.locator(".view .card")
    for i in range(2):
        await cards.nth(i).hover()
        await cards.nth(i).locator(".pick-chip").click()
    await page.click("#compare-open")
    await page.wait_for_timeout(300)
    await shot("06-compare")
    await page.keyboard.press("Escape")
    await ask(page, "make me a green bolt")              # no green bolt: said, and the thread is asked
    await shot("09a-no-green-bolt")
    await ask(page, "a bolt")                            # vague: the library asks for the thread
    await shot("09-vague-question")
    await page.locator(".need .chip", has_text="M8").last.click()
    await page.wait_for_timeout(400)
    await shot("10-after-choosing-m8")
    await ask(page, "give me 1 M8 bolt and 1 arduino")   # several parts: one section per requested part
    await shot("21-several-parts")
    # the one Filters button and its panel
    await page.click("#filter-btn")
    await page.wait_for_timeout(400)
    await shot("22-filters-panel")
    await page.click("#filters input[aria-label='Category']")
    await page.keyboard.type("bolts")
    await page.keyboard.press("Enter")
    await page.wait_for_timeout(300)                        # the panel follows the chosen category
    # the fields narrow while you type: "8.8" shows only the 8.8 materials
    await page.click("#filters input[aria-label='Material']")
    await page.keyboard.type("8.8")
    await page.wait_for_timeout(150)
    await shot("22a-filters-typing")
    await page.keyboard.press("Enter")
    await page.click("#filters input[aria-label='Standard']")
    await page.keyboard.type("4017")
    await page.keyboard.press("Enter")
    for side, v in (("length", "50"), ("width", "20"), ("height", "20")):
        await page.fill(f"#filters input[aria-label='Fits within: {side}']", v)
    await page.wait_for_timeout(150)
    await shot("22b-filters-panel-filled")
    await page.click("#filters button:has-text('Show parts')")
    await page.wait_for_timeout(500)
    await shot("23-filtered-results")
    sent = await page.evaluate("JSON.stringify((window.__lastSearch || {}).filters || {})")
    if '"category":"fasteners/bolts"' not in sent or '"material":"8.8"' not in sent or '"standards":["ISO 4017"]' not in sent or '"max_dims_mm":[50,20,20]' not in sent:
        raise AssertionError(f"filters not sent: {sent}")
    await page.locator(".filter-chips .chip-on", has_text="Material").click()   # remove one filter
    await page.wait_for_timeout(400)
    await page.fill("#query", "")
    await page.click(".filter-chips .filter-clear")                             # clear all: back to plain search
    await page.wait_for_timeout(400)
    # search with your own CAD file
    await page.set_input_files("#cad-file", files=[{"name": "bracket.step", "mimeType": "application/octet-stream",
                                                     "buffer": b"ISO-10303-21;"}])
    await page.wait_for_timeout(500)
    await shot("24-search-by-cad-file")
    await ask(page, "M8x30 bolt 8.8")
    await page.locator(".view .card-title").first.click()
    await page.wait_for_timeout(400)
    await page.evaluate("document.querySelector('#detail').scrollTop = 1e6")
    await shot("25-used-in")
    await page.keyboard.press("Escape")
    await page.click("#settings-btn")                      # your own AI key, and about
    await page.wait_for_timeout(300)
    await shot("26-settings")
    await page.evaluate("document.querySelector('#packs').scrollIntoView()")
    await shot("26b-data-packs")
    await page.evaluate("document.querySelector('#about').scrollIntoView()")
    await shot("27-about")
    await page.keyboard.press("Escape")


async def ask_ai(page, shot) -> None:
    await ask(page, "M8x30 bolt 8.8")                    # exact specs: settled in code, no AI
    await shot("07-checked-in-code")
    await ask(page, "something to hang a shelf on")      # plain language: the AI judges
    await page.wait_for_timeout(900)
    await shot("08-ai-judged-answer")


async def sign_in(page, shot) -> None:
    await shot("11-not-signed-in")
    await page.click("#settings-btn")                      # accounts exist: who the admin is, and the reset
    await page.wait_for_timeout(300)
    await page.evaluate("document.querySelector('#accounts').scrollIntoView()")
    await page.click("#accounts summary")
    await page.wait_for_timeout(150)
    await shot("11b-settings-accounts-exist")
    await page.keyboard.press("Escape")
    await page.click("#signin-btn")
    await page.fill("#signin-user", "anna")
    await page.fill("#signin-pass", "wrong")
    await page.click("#signin-go")
    await page.wait_for_timeout(200)
    await shot("12-sign-in-wrong-password")
    await page.fill("#signin-pass", "correct-horse")
    await page.click("#signin-go")
    await page.wait_for_timeout(400)
    await ask(page, "M8x30 bolt 8.8")
    await shot("13-signed-in-company")
    await page.click("#scope-btn")
    await page.wait_for_timeout(250)
    await shot("13b-choose-folders")
    await page.click(".scope-quick button:has-text('Only')")
    await page.keyboard.press("Escape")
    await page.click("#account")
    await page.wait_for_timeout(250)
    await shot("14-account-menu")
    await page.click(".menu-item:has-text('My library')")
    await page.wait_for_timeout(300)
    await shot("15-my-library")
    await page.evaluate("document.querySelector('#library').scrollTop = 1e6")
    await shot("15d-possible-duplicates")
    await page.evaluate("document.querySelector('#library').scrollTop = 0")
    await page.click("#library .access-btn[data-path='brackets']")
    await page.wait_for_timeout(250)
    await shot("15b-company-who-sees-a-folder")
    await page.click("#library .access-editor button:has-text('Cancel')")
    await page.click("#library button:has-text('Upload a folder')")
    await page.wait_for_timeout(250)
    await shot("15c-upload-who-sees-it")
    await page.click("#library .upload-choice input[value=nuclear]")
    await page.click("#library button:has-text('Choose the folder')")
    await page.wait_for_timeout(300)
    await shot("16-after-upload")
    await page.click("#library .detail-close")
    await page.click("#account")
    await page.click(".menu-item:has-text('Sign out')")
    await page.wait_for_timeout(300)
    await page.click("#signin-btn")
    await page.wait_for_timeout(200)
    await shot("16b-signed-out-clean")
    await page.fill("#signin-user", "drilon")
    await page.fill("#signin-pass", "correct-horse")
    await page.click("#signin-go")
    await page.wait_for_timeout(400)
    await page.click("#account")
    await page.click(".menu-item:has-text('Companies and people')")
    await page.wait_for_timeout(300)
    await shot("17-companies-and-people")
    await page.evaluate("document.querySelector('#people-table').scrollIntoView({block: 'center'})")
    await shot("17b-people-table")                          # every action of a row must be visible, never cut off
    cut = await page.evaluate("(() => { const w = document.querySelector('#people-table').closest('.table-wrap'); return w.scrollWidth - w.clientWidth; })()")
    if cut > 1 and (await page.evaluate("innerWidth")) >= 800:
        raise AssertionError(f"the people table is cut off by {cut}px")
    await page.evaluate("document.querySelector('#manage').scrollTop = 0")
    await page.click("#manage .add-user button[type=submit]")
    await page.wait_for_timeout(200)
    await shot("18-add-person-missing-fields")
    await page.click("#companies-table tr:has-text('Janssen') button:has-text('Library')")
    await page.wait_for_timeout(300)
    await shot("19-company-library-admin")
    await page.click("#library .access-btn[data-path='reactor']")
    await page.wait_for_timeout(250)
    await shot("20-who-sees-a-folder")
    await page.evaluate("document.querySelectorAll('dialog[open]').forEach((d) => d.close())")
    await page.wait_for_timeout(400)
    if not await page.evaluate("document.querySelector('#manage').open"):
        await page.click("#account")
        await page.click(".menu-item:has-text('Companies and people')")
        await page.wait_for_timeout(300)
    await page.click("#people-table tr:has-text('anna') button:has-text('Remove')")
    await page.wait_for_timeout(200)
    await shot("28-confirm-in-the-app")                   # no native confirm box
    await page.click("#confirm button:has-text('Cancel')")


async def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    problems = []
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        for w, h in SIZES:
            # the search, a question the AI judges, then a library that needs a key
            for run, signin in ((screens, False), (ask_ai, False), (sign_in, True)):
                page = await browser.new_page(viewport={"width": w, "height": h})
                page.on("pageerror", lambda e, w=w: problems.append(f"{w}px: JavaScript error: {e}"))
                await page.add_init_script(script=f"window.__signin = {str(signin).lower()};")
                await page.add_init_script(path=str(MOCK))
                await page.goto(PAGE)
                await page.wait_for_timeout(300)

                async def shot(name: str, page=page, w=w) -> None:
                    await page.screenshot(path=str(OUT / f"{w}-{name}.png"))
                    if await page.evaluate("document.documentElement.scrollWidth") > w:
                        problems.append(f"{w}px {name}: the window scrolls sideways")

                await run(page, shot)
        await browser.close()
    print(f"Screenshots in {OUT}")
    for line in problems:
        print("PROBLEM:", line)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
