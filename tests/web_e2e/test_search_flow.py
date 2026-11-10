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
    hrefs = page.locator("a:has-text('Comprar')").evaluate_all("els => els.map(e => e.href)")
    assert hrefs and all(h.startswith("https://") for h in hrefs)


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
    assert cheapest.get_attribute("aria-label")
    cheapest.click()
    assert page.input_value("input[name=modo]") == "fechas"
    assert page.input_value("input[name=desde]") == day == page.input_value("input[name=hasta]")
    assert page.locator("input[name=origenes]:checked").evaluate_all(
        "els => els.map(e => e.value)"
    ) == [origin]
    page.wait_for_selector("text=Kiwi: OK")
    page.wait_for_selector("text=Skiplagged: OK")
    page.wait_for_selector(".itinerary")
    assert page.locator(".calendar").count() == 0  # exact dates: no calendar
    page.wait_for_selector("text=Google Flights: OK")
