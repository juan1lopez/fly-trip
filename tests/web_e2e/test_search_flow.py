import re

import pytest


@pytest.mark.e2e
def test_search_flow(page, demo_server):
    page.goto(demo_server)
    page.click("#toggle-mode")
    page.fill("input[name=destino]", "MAD")
    page.fill("input[name=desde]", "2027-03-01")
    page.fill("input[name=hasta]", "2027-05-31")
    page.fill("input[name=noches_min]", "14")
    page.fill("input[name=noches_max]", "21")
    page.click("button.cta")
    page.wait_for_selector("text=Kiwi: OK")
    page.wait_for_selector(".itinerary")
    assert page.locator(".itinerary").count() >= 1
    assert not page.locator("text=Google Flights: OK").is_visible()  # Google demo tarda 1,5 s
    page.wait_for_selector("text=Google Flights: OK")
    assert page.locator(".origin-cards >> text=Vía Santiago").is_visible()
    # Every card's route leaves from its own origin (the demo replays never cross fixtures).
    mdz_card = page.locator(".origin-card", has_text="Mendoza")
    assert mdz_card.get_by_text(re.compile(r"· MDZ →")).count() == 1
    assert page.locator("#results").get_attribute("aria-busy") == "false"
    hrefs = page.locator("a:has-text('Comprar')").evaluate_all("els => els.map(e => e.href)")
    assert hrefs and all(h.startswith("https://") for h in hrefs)


@pytest.mark.e2e
def test_mode_toggle_reports_expanded_state(page, demo_server):
    page.goto(demo_server)
    toggle = page.locator("#toggle-mode")
    assert toggle.get_attribute("aria-expanded") == "false"
    toggle.click()
    assert toggle.get_attribute("aria-expanded") == "true"
    toggle.click()
    assert toggle.get_attribute("aria-expanded") == "false"


@pytest.mark.e2e
def test_cached_results_can_be_refreshed(page, demo_server):
    page.goto(demo_server)
    page.click("#toggle-mode")
    page.fill("input[name=destino]", "MAD")
    page.fill("input[name=desde]", "2027-03-01")
    page.fill("input[name=hasta]", "2027-05-31")
    page.click("button.cta")
    page.wait_for_selector("text=Google Flights: OK")
    page.click("button.cta")
    page.wait_for_selector("text=Resultados guardados")
    page.click("#refresh")
    page.wait_for_selector("text=Resultados guardados", state="detached")
    page.wait_for_selector("text=Google Flights: OK")
    assert page.locator(".itinerary").count() >= 1
    assert page.locator("#refresh").count() == 0


@pytest.mark.e2e
def test_month_search_shows_calendar_and_a_day_click_searches_exact_dates(page, demo_server):
    page.goto(demo_server)
    page.fill("input[name=destino]", "MAD")
    # Default pills are Nov 2026 to Jan 2027; narrow to Jan and extend up to Mar 2027.
    page.click("[data-month='2026-11']")
    page.click("[data-month='2026-12']")
    page.click("[data-month='2027-03']")
    assert page.input_value("input[name=mes]") == "2027-01"
    assert page.input_value("input[name=hasta_mes]") == "2027-03"
    page.click("button.cta")
    page.wait_for_selector("text=Kiwi: OK")
    page.wait_for_selector(".calendar button[data-day]")
    assert page.locator(".calendar .day.cheap").count() >= 1
    assert page.locator(".calendar >> text=precio orientativo (Skiplagged)").count() >= 1
    assert page.locator(".origin-card.best").count() == 1
    cheapest = page.locator(".calendar button.cheapest").first
    day, origin = cheapest.get_attribute("data-day"), cheapest.get_attribute("data-origin")
    label = cheapest.get_attribute("aria-label")
    assert "orientativo" in label and "el más barato del mes" in label
    form_origins = page.locator("input[name=origenes]:checked").evaluate_all(
        "els => els.map(e => e.value)"
    )
    with page.expect_request(lambda r: "/buscar/stream" in r.url and f"desde={day}" in r.url):
        cheapest.click()
    # The click searches from the last search's parameters; the form is left as it was.
    assert page.input_value("input[name=modo]") == "mes"
    assert (
        page.locator("input[name=origenes]:checked").evaluate_all("els => els.map(e => e.value)")
        == form_origins
    )
    page.wait_for_selector("text=Kiwi: OK")
    page.wait_for_selector("text=Skiplagged: OK")
    page.wait_for_selector(".itinerary")
    assert page.locator(".calendar").count() == 0  # exact dates: no calendar
    routes = page.locator(".origin-card .breakdown").all_inner_texts()
    assert any(f"· {origin} →" in text for text in routes)
    page.wait_for_selector("text=Google Flights: OK")
