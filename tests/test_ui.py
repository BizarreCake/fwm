"""Drives the built UI in a real browser: hover, pin, drag, play, and links between pages.

The chat endpoint runs the real agent loop and tools against a scripted model (tests/scripted_app.py).

Skipped unless the data is ingested, the UI is built (`npm run build` in web/), and
Playwright can start a browser (installed Chrome, or `playwright install chromium`).
"""

import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

sync_api = pytest.importorskip("playwright.sync_api")


@pytest.fixture(scope="module")
def base_url():
    if not (ROOT / "data" / "fwm.duckdb").exists():
        pytest.skip("no ingested data; run `uv run fwm ingest`")
    if not (ROOT / "web" / "dist" / "index.html").exists():
        pytest.skip("UI not built; run `npm run build` in web/")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "--app-dir", str(ROOT / "tests"), "scripted_app:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=ROOT,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(f"{url}/api/overview", timeout=1)
                break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail("server did not start")
        yield url
    finally:
        server.terminate()
        server.wait(timeout=10)


@pytest.fixture(scope="module")
def page(base_url):
    with sync_api.sync_playwright() as playwright:
        browser = None
        for options in ({"channel": "chrome"}, {}):
            try:
                browser = playwright.chromium.launch(headless=True, **options)
                break
            except sync_api.Error:
                continue
        if browser is None:
            pytest.skip("no browser available to Playwright")
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        errors: list[str] = []
        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.base = base_url
        page.errors = errors
        yield page
        browser.close()


MAP = "svg[aria-label^='Amounts owed']"
FLOW = "svg[aria-label$='issuers and holders by sector group']"


def test_system_map_traces_and_pins(page):
    page.goto(page.base + "/")
    page.wait_for_selector(MAP)
    idle = page.inner_text(".readout")
    banks = "g[aria-label^='Banks & credit unions: owes']"
    page.hover(banks)
    assert "Banks" in page.inner_text(".readout") and page.inner_text(".readout") != idle

    page.click(banks)
    page.mouse.move(5, 5)
    assert "Banks" in page.inner_text(".readout"), "a clicked group stays highlighted"
    page.click(banks)
    page.mouse.move(5, 5)
    assert page.inner_text(".readout") == idle

    page.hover("g[aria-label^='Mortgages:']")
    assert page.locator(".readout a").get_attribute("href") == "#/us/instrument/F4_5"

    assert page.locator("g[aria-label^='Corporate equities:']").count() == 0
    page.click("button:has-text('Everything')")
    assert page.locator("g[aria-label^='Corporate equities:']").count() == 1


def test_play_advances_the_quarter_and_pause_stops_it(page):
    page.goto(page.base + "/")
    page.wait_for_selector(MAP)
    card = page.locator("section.card:has(button.play)").first
    slider = card.locator("input.slider")
    slider.fill(str(int(slider.get_attribute("max")) - 30))
    start = card.locator("output.period").inner_text()
    card.locator("button.play").click()
    page.wait_for_timeout(700)
    card.locator("button.play").click()
    paused = card.locator("output.period").inner_text()
    page.wait_for_timeout(400)
    assert paused != start
    assert card.locator("output.period").inner_text() == paused


def test_walk_from_a_flow_to_an_instrument_a_sector_and_back(page):
    page.goto(page.base + "/")
    page.wait_for_selector("table.moves")
    page.locator("table.moves a[href^='#/us/instrument/']").first.click()
    page.wait_for_selector(FLOW)

    page.locator("table.holders >> text=Rest of the world").last.click()
    detail = page.locator("section.card:has(h2:has-text('Rest of the world'))")
    assert detail.count() == 1

    detail.locator("a[href^='#/us/sector/']").first.click()
    page.wait_for_selector(".sheet")
    assert page.inner_text("h1") == "Rest of the world"

    rows = page.locator(".sheet-row").count()
    page.locator("button.chevron[aria-expanded='true']").first.click()
    assert page.locator(".sheet-row").count() < rows
    page.locator("button.chevron[aria-expanded='false']").first.click()
    assert page.locator(".sheet-row").count() == rows

    page.locator(".sheet-row >> text=Treasury securities").first.click()
    page.locator("a:has-text('Who holds and owes this')").click()
    page.wait_for_selector(FLOW)
    assert page.inner_text("h1") == "Treasury securities"

    page.locator("a.back").click()
    page.wait_for_selector(MAP)


def test_chart_hover_shows_a_tooltip_and_drag_changes_the_quarter(page):
    page.goto(page.base + "/#/us/instrument/F3_2")
    page.wait_for_selector(FLOW)
    chart = page.locator("svg[aria-label$='holders by sector group over time']")
    chart.scroll_into_view_if_needed()
    box = chart.bounding_box()
    y = box["y"] + box["height"] / 2
    page.mouse.move(box["x"] + box["width"] * 0.5, y)
    page.wait_for_selector(".tooltip")
    assert "Rest of the world" in page.inner_text(".tooltip")

    before = page.locator("output.period").inner_text()
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] * 0.3, y, steps=5)
    page.mouse.up()
    assert page.locator("output.period").inner_text() != before


def test_rates_events_and_share_of_gdp(page):
    page.goto(page.base + "/#/us/instrument/F3_2")
    page.wait_for_selector("svg[aria-label^='Interest rates over time']")
    assert page.locator(".event-mark").count() > 10

    # Q1 2020 has two announcements on the calendar; each links to its press release.
    slider = page.locator("input.slider")
    slider.fill(str(int(slider.get_attribute("max")) - 25))
    assert page.locator("output.period").inner_text() == "Q1 2020"
    links = page.locator(".events a")
    assert links.count() == 2
    assert links.first.get_attribute("href").startswith("https://www.federalreserve.gov/newsevents/pressreleases/monetary202003")

    chart = page.locator("svg[aria-label$='holders by sector group over time']")
    dollars = chart.locator("text.tick").all_text_contents()
    assert any(label.startswith("$") for label in dollars)
    page.click("button:has-text('% of GDP')")
    assert page.locator("button:has-text('% of GDP')").get_attribute("aria-pressed") == "true"
    labels = chart.locator("text.tick").all_text_contents()
    assert labels != dollars and any(label.endswith("%") for label in labels)
    assert not any(label.startswith("$") for label in labels)


def test_pickers_switch_pages(page):
    page.goto(page.base + "/#/us/instrument/F4_1")
    page.wait_for_selector("select.picker")
    page.select_option("select.picker", "F521")
    page.wait_for_function("(document.querySelector('h1')?.innerText ?? '').includes('Money market fund shares')")


def test_chat_answers_with_lookups_and_links_into_the_pages(page):
    page.goto(page.base + "/")
    page.wait_for_selector(MAP)
    page.click("button.chat-launch")
    assert page.inner_text(".chat-model").startswith("Claude Opus 5.5")
    page.fill(".chat textarea", "Who held the most Treasuries in early 2022?")
    page.keyboard.press("Enter")

    lookup = page.locator(".chat-tool a")
    lookup.wait_for()
    assert "Treasury securities" in lookup.inner_text() and "Q1 2022" in lookup.inner_text()
    page.wait_for_selector(".chat-assistant .markdown a")
    page.wait_for_selector(".chat-send:has-text('Ask')")
    answer = page.locator(".chat-assistant .markdown")
    assert "Answered by scripted" in page.inner_text(".chat-assistant")  # the model that actually replied
    assert "Answer 1:" in answer.inner_text() and answer.locator("strong").inner_text() == "Foreign investors"
    assert answer.locator("code").inner_text() == "LM263061105.Q"
    # Only links into the app or to https sites are rendered as links.
    assert answer.locator("a").count() == 1 and "a bad link" in answer.inner_text()

    # The link moves the page behind the panel to that instrument and quarter; the conversation stays.
    answer.locator("a").click()
    page.wait_for_selector(FLOW)
    assert page.inner_text("h1") == "Treasury securities"
    assert page.locator("main output.period").inner_text() == "Q1 2022"
    assert page.locator(".chat-user").count() == 1

    # A follow-up continues the same conversation.
    page.fill(".chat textarea", "And now?")
    page.keyboard.press("Enter")
    page.wait_for_selector(".chat-assistant >> text=Answer 2:")


def test_chat_shows_limits_of_the_data_and_can_start_over(page):
    page.fill(".chat textarea", "How many Treasuries does JPMorgan hold?")
    page.keyboard.press("Enter")
    page.wait_for_selector(".chat-gap")
    assert "individual banks" in page.inner_text(".chat-gap")
    page.wait_for_selector(".chat-assistant >> text=not single banks")

    page.wait_for_selector(".chat-send:has-text('Ask')")
    page.click("button:has-text('New conversation')")
    assert page.locator(".chat-user").count() == 0 and page.locator(".chat-suggestion").count() == 4
    page.click("button[aria-label='Close the assistant']")
    assert page.locator(".chat").count() == 0


def test_weekly_fed_page_is_newer_than_the_quarter_and_links_both_ways(page):
    page.goto(page.base + "/#/")
    page.wait_for_selector(".tiles")
    assert "Reserve balances of banks" in page.inner_text(".tiles")
    page.click("text=Weekly balance sheet →")
    page.wait_for_selector("svg[aria-label^='Federal Reserve liabilities']")
    latest = page.locator("output.period").inner_text()
    assert latest[-4:].isdigit() and "," in latest  # a date, not a quarter
    assert "Since " in page.locator("table.weekly thead").first.inner_text()

    # Pick a line on the asset side: the detail and the stacked chart follow it.
    page.click("table.weekly button:has-text('Mortgage-backed securities')")
    page.wait_for_selector("svg[aria-label^='Mortgage-backed securities: amount each week']")
    page.wait_for_selector("svg[aria-label^='Federal Reserve assets']")

    # Dragging back in time moves the tables, and before the quarter's end the comparison is a year.
    slider = page.locator("input.slider")
    slider.fill(str(int(slider.get_attribute("max")) - 60))
    assert page.locator("output.period").inner_text() != latest
    assert "Year" in page.locator("table.weekly thead").first.inner_text()

    # A deep link opens on the week containing the date.
    page.goto(page.base + "/#/us/weekly/fed?period=2020-03-17")
    page.wait_for_selector("table.weekly")
    assert page.locator("output.period").inner_text() == "Mar 18, 2020"

    page.click("text=Federal Reserve in the quarterly accounts →")
    page.wait_for_selector("text=Weekly balance sheet, more recent than the quarterly accounts →")


def test_foreign_holders_page_ranks_countries_and_is_linked_from_treasuries(page):
    page.goto(page.base + "/#/us/instrument/F3_2")
    page.wait_for_selector(FLOW)
    page.click("text=Which countries: foreign holders by country, monthly →")
    page.wait_for_selector("svg[aria-label^='Foreign holdings of Treasury securities by region']")
    rows = page.locator("table.foreign tbody tr")
    assert rows.count() == 20 and "1. Japan" in rows.first.inner_text()
    assert "custody" in page.inner_text("main")

    page.click("table.foreign button:has-text('China, Mainland')")
    page.wait_for_selector("svg[aria-label^='China, Mainland: holdings of Treasury securities each month']")
    page.click("text=/Show all \\d+ countries/")
    assert rows.count() > 50

    # Other kinds of security have their own page, without the bills column.
    assert "Of which bills" in page.inner_text("table.foreign thead")
    page.click("button:has-text('Equities')")
    page.wait_for_selector("svg[aria-label^='Foreign holdings of US equities by region']")
    assert "Of which bills" not in page.inner_text("table.foreign thead")
    assert "investment funds" in page.inner_text("main")

    # A deep link opens on that month, and purchases are marked as unavailable before 2023.
    page.goto(page.base + "/#/us/foreign/treasuries?period=2021-06")
    page.wait_for_selector("table.foreign")
    assert page.locator("output.period").inner_text() == "Jun 2021"
    assert "n/a" in page.locator("table.foreign tbody tr").first.inner_text()


def test_country_page_shows_both_directions_and_is_reachable_from_the_overview(page):
    page.goto(page.base + "/#/")
    page.wait_for_selector("table.countries")
    page.click("table.countries a:has-text('Japan')")
    page.wait_for_selector("table.bilateral")
    assert page.inner_text("h1") == "Japan and the United States"
    assert "not the country's own balance sheet" in page.inner_text(".callout")
    tables = page.locator("table.bilateral")
    assert "Treasury securities" in tables.nth(0).inner_text() and "Foreign equities" in tables.nth(1).inner_text()

    # Picking a line on the other side switches the charts to that direction.
    page.click("table.bilateral button:has-text('Foreign equities')")
    page.wait_for_selector("svg[aria-label^=\"Japan's securities held by US residents\"]")
    page.wait_for_selector("svg[aria-label^='Japan, Foreign equities: holdings each month']")

    # From a line to the ranking of all countries, and from a ranking row back to a country.
    page.click("table.bilateral button:has-text('Treasury securities')")
    page.click("text=All countries →")
    page.wait_for_selector("table.foreign")
    page.click("table.foreign a[aria-label^='United Kingdom']")
    page.wait_for_selector("table.bilateral")
    assert page.inner_text("h1") == "United Kingdom and the United States"


def test_links_made_before_pages_carried_an_economy_still_work(page):
    page.goto(page.base + "/#/sector/S121?period=2022:Q1")
    page.wait_for_url("**/#/us/sector/S121?period=2022:Q1")
    page.wait_for_selector("text=Weekly balance sheet, more recent than the quarterly accounts →")
    page.goto(page.base + "/#/foreign/equities")
    page.wait_for_url("**/#/us/foreign/equities")
    page.wait_for_selector("table.foreign")


def test_euro_area_pages_are_in_euro_and_keep_to_their_own_economy(page, base_url):
    page.goto(f"{base_url}/#/")
    page.wait_for_selector("h1")
    page.get_by_role("button", name="Euro area").click()
    page.wait_for_function("document.querySelector('h1')?.innerText.includes('Euro area financial system')")
    page.wait_for_selector("table.table")
    assert page.url.endswith("#/ea") and "Euro area financial system" in page.inner_text("h1")
    page.wait_for_selector("table.moves")
    page.wait_for_selector("svg[aria-label^='Amounts owed and held']")
    page.wait_for_selector("table.compare")
    page.wait_for_selector(".tiles")
    front = page.inner_text("main")
    # Dollars appear only in the side-by-side card, which converts on purpose.
    outside = "".join(card.inner_text() for card in page.locator("main > *").all() if "side by side" not in card.inner_text())
    assert "$" not in outside, [outside[max(0, k - 80):k + 30] for k in range(len(outside)) if outside[k] == "$"][:3]
    assert "€" in front and "Who owes, through what" in front and "of which:" in front
    # The two economies side by side, and the Eurosystem's weekly figures, are on the front page.
    assert "side by side" in front and "% of own GDP" in front and "Eurosystem total assets" in front
    assert "Held in custody" not in front and page.locator("svg[aria-label^='Amounts owed and held']").count() == 1
    page.get_by_role("link", name="Debt securities").first.click()
    page.wait_for_function("document.querySelector('h1')?.innerText.includes('Debt securities')")
    page.get_by_role("button", name="Euros").wait_for()
    assert "#/ea/instrument/F3" in page.url and "Euro area" in page.inner_text("h1")
    text = page.inner_text("main")
    assert "€" in text and "$" not in text and "of which:" in text and "Since 1999" in text
    assert page.get_by_role("button", name="Euros").count() == 1 and page.get_by_role("button", name="% of GDP").count() == 1
    assert "Interest rates and ECB announcements" in text and "Fed announcement" not in text
    # Who holds whose: the matrix opens on its largest cell, and a cell can be chosen.
    page.wait_for_selector("table.matrix")
    assert "holding paper of General government" in page.inner_text("h3.pair-title")
    page.locator("table.matrix tbody tr").nth(7).locator("button.cell-button").nth(1).click()
    assert "Households and non-profits holding paper of Banks" in page.inner_text("h3.pair-title")
    page.get_by_role("link", name="Central banks (Eurosystem) →").click()
    page.wait_for_function("document.querySelector('h1')?.innerText.includes('Central banks')")
    assert "#/ea/sector/S121" in page.url
    page.get_by_role("link", name="Weekly balance sheet, more recent than the quarterly accounts →").click()
    page.wait_for_function("document.querySelector('h1')?.innerText.includes('Eurosystem, weekly')")
    page.wait_for_selector("svg")
    weekly = page.inner_text("main")
    assert "#/ea/weekly/eurosystem" in page.url and "every Friday" in weekly and "Deposit facility" in weekly and "$" not in weekly
    page.get_by_role("link", name="← Overview").click()
    page.wait_for_function("document.querySelector('h1')?.innerText.includes('Euro area financial system')")
    assert page.url.endswith("#/ea")
    # Back in the US, amounts are in dollars again.
    page.get_by_role("button", name="United States").click()
    page.wait_for_function("document.querySelector('h1')?.innerText.includes('US financial system')")
    assert "US financial system" in page.inner_text("h1") and "€" not in page.inner_text("header")


def test_no_console_errors(page):
    """Runs last: nothing in the session above logged an error."""
    assert page.errors == []


def test_links_between_economies_page(page, base_url):
    page.goto(f"{base_url}/#/")
    page.get_by_role("link", name="What each holds of the other, and links with other economies →").click()
    page.wait_for_selector("table.matrix")
    assert page.url.endswith("#/links?pair=us-ea") and page.inner_text("h1") == "Links between economies"
    text = page.inner_text("main")
    for expected in ("United States and Euro area", "Equity & fund shares", "Bank liabilities", "Every pair", "Cayman Islands",
                     "dollar claims on residents outside the United States", "€" not in text and "$"):
        assert expected in text, expected
    assert page.locator("svg[aria-label*='both directions']").count() == 4
    # A cell of the matrix picks that pair; the bank tables have no rows for China.
    page.get_by_role("button", name="Bank claims").click()
    assert page.locator("table.matrix tbody tr").count() == 6 and "–" in page.locator("table.matrix tbody tr").nth(4).inner_text()
    page.locator("table.matrix tbody tr").nth(2).locator("button").first.click()
    page.wait_for_function("document.querySelector('h2')?.innerText.includes('Japan')")
    assert page.url.endswith("#/links?pair=jp-us") and "Japan and United States" in page.inner_text("main")
    assert page.locator("select").first.input_value() == "jp"
