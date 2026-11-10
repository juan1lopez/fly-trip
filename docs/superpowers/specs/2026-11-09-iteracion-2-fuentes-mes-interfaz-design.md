# fly-trip, iteration 2: more sources, search by month, new interface (design)

- **Date:** 2026-11-09
- **Status:** draft, pending approval
- **Base:** milestone 1, on `main` at 82751f0. Its spec, `2026-11-09-buscador-vuelos-baratos-design.md`, still applies to everything this document does not change.
- **Marks:** "(decisión mía)" marks decisions made by whoever designed this document. Everything else was chosen by the user in the conversation.

## 1. Intent

After trying milestone 1, the user asked for three things:
- more sites to search;
- searching by month instead of by specific dates;
- a new interface in the style of a Behance reference (Pilo Autonomous Taxi App).

**What the user chose:**
- **New sources:** add Skiplagged, and fix Google Flights by moving to the development version of `fli`.
- **Hidden-city fares:** exclude them always.
- **Month search:** choose one or more months plus nights, and see a per-day price calendar as well as the list of cheapest results.
- **Style:** option A, a dark two-column desktop panel, built from the screenshots the user provided.

## 2. Goals, non-goals and anti-goals

**Goals**
- Three working sources: Kiwi, Google Flights and Skiplagged.
- Month mode as the default search. Exact dates stay available as a secondary mode.
- A calendar of the cheapest price per departure day for the chosen months. Clicking a day searches that exact date.
- A complete web restyle (option A) that keeps every behavior from milestone 1.

**Non-goals**
- Price alerts, which remain milestone 2.
- Booking from the tool.
- "Any destination" search.
- Paid sources (SerpApi) and sources that need an account (Travelpayouts, Duffel).

**Anti-goals** (inherited from milestone 1, plus two new ones)
- Showing hidden-city fares.
- Presenting the calendar's indicative prices as if they were confirmed: they must be labeled as indicative.

## 3. Verified facts (live probes, 2026-11-09)

**Skiplagged**
- Official MCP server at `https://mcp.skiplagged.com/mcp`: Streamable HTTP, no authentication, stateless.
- `sk_flights_search` takes exact dates: `origin`, `destination`, `departureDate`, `returnDate`, `currency`, `adults`, `limit`, `sort`, `includeHiddenCity`, `includeVirtualInterlining`, `maxStops` and others.
- The response includes `structuredContent` with `searchUrl`, `flights`, `pagination` and `pricing`.
- Example: SCL→MAD, 19/03 to 04/04/2027, cheapest 713 USD (Iberia, with the return on LATAM via GIG), 300 results available.
- `sk_flex_departure_calendar` (`origin`, `destination`, `departureDate`, optional `returnDate`, `currency`) returns a price per departure day across roughly 6 weeks around the given date. Example: EZE→MAD gave 735–946 USD per day.

**Expedia MCP:** returns 403 because of its anti-bot system. Not usable.

**Google Flights via `fli`**
- Version 0.10.0 from GitHub main, commit `881aee5`, works from this machine.
- Example: EZE→MAD on 09/03/2027 gave 11 results, cheapest 735 USD (ITA and Air Europa).
- Version 0.9.0 from PyPI stays blocked.

## 4. Approaches considered

**4.1 Month calendar data** (decisión mía)

| Option | Verdict | Reason |
|---|---|---|
| **A. Skiplagged flex calendar** | Chosen | 1 call per origin and month covers every day. |
| B. Derive it from Kiwi and Google results | Rejected | Kiwi returns about 15 results per query, so most days stay empty. |
| C. Google's date calendar through `fli` | Rejected | It costs 1 download per day, about 90 per month: slow and abusive. |

**4.2 Interface** (user's choice: option A)
- A two-column desktop layout: search on the left; origin cards, calendar and results on the right.
- Option B (a single-column app style) was considered and not chosen.

## 5. How it works

### 5.1 Search by month

**Search form**
- Destination: IATA code or city.
- "Mes de salida": one to four consecutive months, chosen as pills. The default is the current month and the next two.
- Nights: minimum to maximum, or "solo ida".
- Origins, adults and "separate tickets" work as in milestone 1.
- An "Fechas exactas" link switches to the from/to mode of milestone 1.

**Mapping to the engine**
- The chosen months become a window that runs from the first day of the first month to the last day of the last month. If today falls inside that window, the window starts tomorrow.
- Everything downstream (Kiwi exploration, candidates, confirmation) is the same as in milestone 1.

**CLI:** `fly search MAD --mes 2027-03 [--hasta-mes 2027-05] --noches 14-21`. `--desde` and `--hasta` stay available.

### 5.2 Calendar

- In month mode, the engine also asks Skiplagged's flex calendar for each origin and month, with at most 4 months × 3 origins = 12 calls, and 3 at a time.
  - For round trips it sends `returnDate = salida + noches_mín`. For one-way searches it sends no return date.
- **Value per day:** the minimum over the origins of (calendar price + that origin's transfer), labeled with the origin that gives it.
- **UI:** one grid per month, Monday through Sunday.
  - The 10% cheapest days are highlighted in lime.
  - The cheapest day per month is marked.
  - Days with no data are shown empty.
  - The calendar header says "precio orientativo (Skiplagged)".
- **Click on a day:** runs an exact-date search for that day and the best origin, with nights from the minimum to the maximum.

### 5.3 Skiplagged source

- The adapter calls the MCP server over JSON-RPC, in the same style as Kiwi (decisión mía). It reuses the SSE parsing and sends `User-Agent: fly-trip/0.1 (uso personal)`.
- **Role:** like Google, it confirms the candidate date pairs. It receives the same pairs, with its own budget of at most 12 calls per search and 3 at a time (decisión mía).
- **Parameters:**
  - Always `includeHiddenCity=false`.
  - `includeVirtualInterlining` follows "permitir pasajes separados".
  - `currency=USD` and `adults`.
- **Normalization:**
  - Prices are in USD. The live probe must verify whether the price is the total for every passenger.
  - Segments use the local times the API returns, with the offset stripped.
  - Separate tickets are taken from the trip type when the API reports it, and stay unknown (`None`) when it doesn't.
  - The booking link is the result's link (`searchUrl` plus the trip hash).
- **Errors:** 429 → pause for 60 min. Any other error → visible "error" status. A response with no results for every pair → "posible bloqueo", the same rule as Google.
- **Contract:** it passes the common contract test, with recorded fixtures (a search and a calendar) and synthetic ones (an error and a malformed response).

### 5.4 Google Flights back in service

- Pin `flights` to the git commit `881aee5` (version 0.10.0) in `pyproject.toml` / `uv.lock`.
- Check that `_SingleAttemptClient` (one fetch, one request) still works in 0.10.0, and adjust it if not.
- Run the pending live verification:
  - (a) whether USD is respected;
  - (b) which tuple element holds the round-trip total;
  - (c) whether datetimes are naive and local;
  - (d) whether the price is the total for 2 adults.
- Re-record real fixtures.
- Update `docs/sources/google-flights.md`.

### 5.5 New interface (option A)

**Visual system**
- Background `#0d0d0d`, cards `#1c1c1c` / `#262626`, accent lime `#d4ff3a` on dark ink, text `#f5f5f2`, secondary `#9a9a96`.
- Warnings in amber `#ffb547`, errors in coral `#ff6b5e`.
- Typography:
  - Manjari for titles and large figures.
  - Inter for body text.
  - Both loaded from Google Fonts with system fonts as the fallback (decisión mía). This is CSS, not executable code.
- Card corners 20–24 px, buttons and tags as pills, and a lime CTA with an arrow in a circle.

**Layout**
- **Left column:** the search panel and the source status chips, where Kiwi, Skiplagged and Google each show OK, partial, paused or error.
- **Right column:**
  - The three origin cards; the best one is lime.
  - The transfers banner when they are not configured.
  - The calendar.
  - The results as cards, with a large price, route, chips (direct or stops, ⚠ separate tickets, ? unknown), dates, airlines, baggage, sources and a "Comprar ↗" button for each offer.
- The page becomes a single column below 900 px.

**Settings:** the same dark style.

**Everything from milestone 1 stays:**
- the data and copy (`status_label`, `price_breakdown`, `baggage_label`);
- `/buscar/validar` before the stream;
- "Actualizar" on cached results;
- `failed_origins`;
- the `.itinerary` and `.origin-card` classes the e2e test uses;
- the security rules (autoescape, `http(s)` links only, TrustedHost and Origin checks).

**Process:** the final mockup lives at `docs/design/mockup-a.html` as a visual reference for whoever builds it.

## 6. Acceptance scenarios

1. **Month search.** Madrid, March to May 2027, 14–21 nights, from the 3 origins. The three sources respond, the calendar shows March to May with the cheap days in lime, and a full search finishes in 30 s or less.
2. **Click on the cheapest day.** It runs the exact-date search, and the results show offers from at least two sources.
3. **Hidden city.** Skiplagged returns no hidden-city fares. A test checks the parameter and filters any hidden-city item that still arrives.
4. **Fallback when Skiplagged fails or is blocked.** The calendar shows "no disponible" and the rest still works.
5. **Google 0.10.0.** `fly doctor` shows all three sources OK. The live answers (a) to (d) are documented.
6. **Interface.** The e2e test runs through month search, the calendar and a click on a day with demo sources, using the new styles.

## 7. Left to whoever builds it

- Exact CSS and visual details, within §5.5 and the mockup.
- The calendar's tie rules and how the 10% highlight is computed.
- How to merge Skiplagged duplicates with Kiwi and Google, using the existing `itinerary_id`.
- The final rules for mapping Skiplagged's trip type to separate tickets, once the live fields are seen.
