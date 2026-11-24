"""Drives the built UI in a real browser: hover, pin, drag, play, and links between pages.

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
        [sys.executable, "-m", "uvicorn", "fwm.api:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
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
    assert page.locator(".readout a").get_attribute("href") == "#/instrument/F4_5"

    assert page.locator("g[aria-label^='Corporate equities:']").count() == 0
    page.click("button:has-text('Everything')")
    assert page.locator("g[aria-label^='Corporate equities:']").count() == 1


def test_play_advances_the_quarter_and_pause_stops_it(page):
    page.goto(page.base + "/")
    page.wait_for_selector(MAP)
    card = page.locator("section.card").first
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
    page.locator("table.moves a[href^='#/instrument/']").first.click()
    page.wait_for_selector(FLOW)

    page.locator("table.holders >> text=Rest of the world").last.click()
    detail = page.locator("section.card:has(h2:has-text('Rest of the world'))")
    assert detail.count() == 1

    detail.locator("a[href^='#/sector/']").first.click()
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
    page.goto(page.base + "/#/instrument/F3_2")
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
    page.goto(page.base + "/#/instrument/F3_2")
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
    page.goto(page.base + "/#/instrument/F4_1")
    page.wait_for_selector("select.picker")
    page.select_option("select.picker", "F521")
    page.wait_for_function("(document.querySelector('h1')?.innerText ?? '').includes('Money market fund shares')")


def test_no_console_errors(page):
    """Runs last: nothing in the session above logged an error."""
    assert page.errors == []
