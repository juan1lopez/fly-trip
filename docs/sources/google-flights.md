# Google Flights (`fli`)

Fuente que usa la librería `flights==0.9.0` (se importa como `fli`). Es sincrónica (curl_cffi), por eso la fuente la llama con `asyncio.to_thread`.

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

`fli` 0.9.0 decora `Client.post` y `Client.get` con `tenacity` (`stop_after_attempt(3)`, `wait_exponential()`): una descarga que falla o recibe un 429 se repetía hasta 3 veces sin que lo viéramos, y el presupuesto de 12 descargas podía convertirse en 36 solicitudes. `RealFliClient` usa `_SingleAttemptClient`, que llama al método sin decorar (`__wrapped__`): conserva el limitador de ritmo, el timeout y el mapeo de errores, pero no reintenta. Así, 1 descarga = 1 solicitud y el peor caso queda en 12. Un test con una sesión falsa fija ese comportamiento. Si una versión futura de `fli` cambia el cliente, ese test avisa.

## Qué pasa después de un 429

- La fuente guarda `_blocked_until = ahora + 60 min` al recibir un 429. Las consultas que ya estaban en la cola del semáforo (habían pasado el chequeo de pausa del motor) lo revisan antes de llamar a `fli` y levantan `SourceBlocked` sin hacer ninguna solicitud.
- El motor además pausa Google 60 minutos (`PauseRegistry`) y las búsquedas siguientes ni lo intentan.

## Verificación en vivo (Step 1)

NO se pudo completar. El 2026-11-09, desde esta máquina, Google respondió 200 pero con un cuerpo de error
(`[["wrb.fr",null,null,null,null,[13]], ...]`) a todas las consultas, incluso a una simple JFK-LHR de solo ida
sin parámetros de moneda. `fli` interpreta eso como "sin resultados" y devuelve `None`. Pueden ser un bloqueo silencioso
o un cambio del lado de Google. Se hicieron 5 consultas y se paró.

| Pregunta | Estado |
|---|---|
| a) Precios en USD con `currency="USD"` | Sin verificar. Se defiende con `GoogleCurrencyError` si llega otra moneda. |
| b) Elemento de la tupla con el total de ida y vuelta | Sin verificar. Se asume el último (`parts[-1]`), como indica el diseño. |
| c) `departure_datetime` en hora local y sin zona | Sin verificar. El parser de `fli` genera `datetime` sin zona; se usan tal cual. |
| d) Precio con 2 adultos es el total | Sin verificar. `GOOGLE_PRICE_IS_TOTAL = True` es una suposición. |

Pendiente: repetir la verificación cuando Google vuelva a responder y ajustar `GOOGLE_PRICE_IS_TOTAL` y el elemento de precio si hace falta.

## Fixtures

Como no se pudo grabar, TODOS los fixtures de `tests/fixtures/google/` son sintéticos (construidos con modelos `fli` y volcados con `model_dump(mode="json")`), incluidos los que llevan nombre de escenario grabado (`madrid_*`). Reemplazarlos por grabaciones reales cuando se pueda.

## Riesgos

- Google puede limitar o bloquear (429 pausa la fuente 60 minutos) o cambiar el formato (`SearchParseError`: "Google cambió el formato de la página").
- Respuesta vacía por rechazo silencioso: el §3 del spec cuenta también las páginas de captcha y de consentimiento como bloqueos, y `fli` las entrega como `None` o lista vacía. Si el motor hizo al menos una consulta a Google y TODAS devolvieron 0 itinerarios, lo trata como bloqueo: estado `error` con "Google no devolvió resultados para ninguna fecha (posible bloqueo)" y pausa de 60 minutos. Si solo algunas fechas vienen vacías, no es bloqueo.
- Sin proxies ni técnicas para esquivar bloqueos.

## Cómo regrabar

```
uv run python -c "from datetime import date; from pathlib import Path; from flytrip.devtools.record_google import record_google; record_google('madrid_scl_rt','SCL','MAD',date(2027,3,19),16,1,Path('tests/fixtures/google'))"
```

Escenarios: `madrid_scl_rt` (SCL-MAD, 2027-03-19, 16 noches), `madrid_eze_oneway` (EZE-MAD, 2027-03-07), `madrid_scl_rt_2adults` (como el primero, con 2 adultos).

## Verificación en vivo de cierre del hito 1 (2026-11-09)

- `uv run fly doctor`: `Google Flights ✗ Rota: 0 itinerarios`. Sigue sin responder con `fli` 0.9.0 desde esta máquina.
- `uv run pytest -m live -q`: el test de 2 adultos se saltó (Google no devuelve nada).
- En la búsqueda real (escenario 1) la línea de estado fue `Google Flights: OK (0 en 0,6 s)`; desde entonces una respuesta vacía en todas las fechas se muestra como error y pausa la fuente (ver Riesgos). Los resultados de Kiwi se muestran igual.
- No insistir con consultas: ya se hicieron varias y no cambia nada. Reintentar solo con `fly doctor`, y de a poco.
