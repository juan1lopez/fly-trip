import pytest


@pytest.mark.e2e
def test_search_flow(page, demo_server):
    page.goto(demo_server)
    page.fill("input[name=destino]", "MAD")
    page.fill("input[name=desde]", "2027-03-01")
    page.fill("input[name=hasta]", "2027-05-31")
    page.fill("input[name=noches_min]", "14")
    page.fill("input[name=noches_max]", "21")
    page.click("button:has-text('Buscar')")
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
    page.fill("input[name=destino]", "MAD")
    page.fill("input[name=desde]", "2027-03-01")
    page.fill("input[name=hasta]", "2027-05-31")
    page.click("button:has-text('Buscar')")
    page.wait_for_selector("text=Google Flights: OK")
    page.click("button:has-text('Buscar')")
    page.wait_for_selector("text=Resultados guardados")
    page.click("#refresh")
    page.wait_for_selector("text=Resultados guardados", state="detached")
    page.wait_for_selector("text=Google Flights: OK")
    assert page.locator(".itinerary").count() >= 1
    assert page.locator("#refresh").count() == 0
