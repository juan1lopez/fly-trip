# Google Flights (`fli`)

Fuente que usa la librería `flights` 0.10.0 (se importa como `fli`), fijada al commit `881aee5` de GitHub (`punitarani/fli`) en `pyproject.toml` y `uv.lock`. La 0.9.0 de PyPI devolvía vacío desde esta máquina; la 0.10.0 responde. Como es una referencia directa, `pyproject.toml` activa `tool.hatch.metadata.allow-direct-references`. Es sincrónica (curl_cffi), por eso la fuente la llama con `asyncio.to_thread`.

## Qué confirma

- Solo pares exactos: una fecha de ida y, si hay vuelta, una cantidad fija de noches. No acepta ventanas.
- Siempre pide `currency="USD"`, `language="es"`, `country="AR"` y `top_n=1`.
- El enlace de reserva es una búsqueda de Google Flights (`google_search_url`), porque `fli` no entrega un enlace por vuelo.
- No informa equipaje (`baggage=None`).

## Costo en descargas

- Solo ida: 1 descarga.
- Ida y vuelta: 1 + `top_n` = 2 descargas (`GOOGLE_RETURN_PAIR_COST`).
- Presupuesto por búsqueda: `GOOGLE_FETCH_BUDGET = 12`, con un máximo de `GOOGLE_MAX_CONCURRENCY = 3` consultas en paralelo.

## Una descarga es una solicitud HTTP

`fli` 0.10.0 pide la página de búsqueda con `Client.get` (ya no `post`). Tanto `Client.get` como `Client.post` siguen decorados con `tenacity` (`stop_after_attempt(3)`, `wait_exponential()`), y además `fetch_payload` repite hasta `PAGE_FETCH_ATTEMPTS = 3` veces una página que llega sin el bloque `ds:1` (páginas de consentimiento o de bloqueo). Sin tocarlo, una descarga fallida podía ser hasta 3 o 9 solicitudes. `RealFliClient` usa `_SingleAttemptClient`, que llama a los métodos sin decorar (`__wrapped__`: conserva el limitador de ritmo, el timeout y el mapeo de errores, pero no reintenta), y `google_flights.py` fija `fli.search._tfs.PAGE_FETCH_ATTEMPTS = 1`. Así, 1 descarga = 1 solicitud y el peor caso queda en 12. Dos tests con una sesión falsa fijan ese comportamiento (error de red y página sin `ds:1`). Si una versión futura de `fli` cambia el cliente, esos tests avisan.

## Qué pasa después de un 429

- La fuente guarda `_blocked_until = ahora + 60 min` al recibir un 429. Las consultas que ya estaban en la cola del semáforo (habían pasado el chequeo de pausa del motor) lo revisan antes de llamar a `fli` y levantan `SourceBlocked` sin hacer ninguna solicitud.
- El motor además pausa Google 60 minutos (`PauseRegistry`) y las búsquedas siguientes ni lo intentan.

## Verificación en vivo (2026-11-09, `fli` 0.10.0)

Se hicieron 3 búsquedas (4 descargas) con `record_google`, en serie y con pausa. Las tres devolvieron resultados.

| Pregunta | Respuesta | Evidencia |
|---|---|---|
| a) Precios en USD con `currency="USD"` | Sí. | Todos los resultados traen `currency == "USD"`; SCL-MAD ida y vuelta salió 715 USD (Skiplagged: 713). |
| b) Elemento de la tupla con el total de ida y vuelta | El último (`parts[-1]`). | En `madrid_scl_rt` el primer elemento (ida) trae el precio "desde" de esa ida (715 en las tres primeras) y el segundo trae el total del par elegido (715, 715 y 928). |
| c) `departure_datetime` en hora local y sin zona | Sí, ingenuo y local. | Sin `tzinfo`. SCL 00:50 (UTC-3) a MAD 17:30 (UTC+1) con `duration` 760 min: solo cuadra con horas locales. |
| d) Precio con 2 adultos es el total | Sí. | Mismo par, 1 adulto 715 y 2 adultos 1430 (exactamente el doble). `GOOGLE_PRICE_IS_TOTAL = True` queda confirmado. |

Un test offline (`test_recorded_fixtures_confirm_live_facts`) fija estos hechos sobre los fixtures grabados.

## Fixtures

`madrid_scl_rt`, `madrid_eze_oneway` y `madrid_scl_rt_2adults` son grabaciones reales (2026-11-09). Los demás (`synthetic_*`, `wrong_currency`) siguen siendo sintéticos, construidos con modelos `fli` y volcados con `model_dump(mode="json")`.

## Riesgos

- Google puede limitar o bloquear (429 pausa la fuente 60 minutos) o cambiar el formato (`SearchParseError`: "Google cambió el formato de la página").
- Respuesta vacía por rechazo silencioso: el §3 del spec cuenta también las páginas de captcha y de consentimiento como bloqueos, y `fli` las entrega como `None` o lista vacía. Si el motor hizo al menos una consulta a Google y TODAS devolvieron 0 itinerarios, lo trata como bloqueo: estado `error` con "Google no devolvió resultados para ninguna fecha (posible bloqueo)" y pausa de 60 minutos. Si solo algunas fechas vienen vacías, no es bloqueo.
- Sin proxies ni técnicas para esquivar bloqueos.

## Cómo regrabar

```
uv run python -c "from datetime import date; from pathlib import Path; from flytrip.devtools.record_google import record_google; record_google('madrid_scl_rt','SCL','MAD',date(2027,3,19),16,1,Path('tests/fixtures/google'))"
```

Escenarios: `madrid_scl_rt` (SCL-MAD, 2027-03-19, 16 noches), `madrid_eze_oneway` (EZE-MAD, 2027-03-07, solo ida), `madrid_scl_rt_2adults` (como el primero, con 2 adultos).
