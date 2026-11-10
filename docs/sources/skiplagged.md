# Fuente Skiplagged

Servidor MCP oficial de Skiplagged: `POST https://mcp.skiplagged.com/mcp`, sin autenticación y sin sesión (`tools/call` funciona sin `initialize`).

## Cómo se consulta

- Encabezados: `Content-Type: application/json`, `Accept: application/json, text/event-stream` y `User-Agent: fly-trip/0.1 (uso personal)`.
- Cuerpo: llamada JSON-RPC `tools/call`. La respuesta llega como SSE (`data: {json}`) y se lee con el mismo `parse_sse` de Kiwi.
- Herramientas que usamos:
  - `sk_flights_search`: `origin`, `destination`, `departureDate`, `returnDate` (solo ida y vuelta), `currency=USD`, `adults`, `sort=price`, `limit=20`, `includeHiddenCity=false` e `includeVirtualInterlining` (sigue a "permitir pasajes separados").
  - `sk_flex_departure_calendar`: `origin`, `destination`, `departureDate` (ancla), `returnDate` opcional y `currency=USD`.
- Solo confirma fechas exactas (una salida y, si hay vuelta, una cantidad exacta de noches).
- Cada búsqueda es una consulta (`fetches=1`). Se permiten 3 a la vez (`SKIPLAGGED_MAX_CONCURRENCY`).

## Verificación en vivo (2026-11-09, 4 consultas)

a) **Forma de `sk_flights_search`.** `result.structuredContent` trae `searchUrl`, `flights`, `pagination` y `pricing` (`currency`, `rate`, `approximate`). Cada elemento de `flights` es un `FlightCard` con: `id`, `airlines` (texto), `departure`/`arrival` (`airport` y `dateTime` con offset, como `2027-03-19T00:50:00-03:00`), `duration` (texto), `layovers`, `price` (`amount`, `currency`, `usdAmount`), `deepLink`, `attributes` y `returnFlight` (con los mismos campos y sus propios `attributes`).

b) **El detalle de tramos NO está en `structuredContent`.** Ahí solo hay origen, destino, salida y llegada de cada sentido. Las escalas con aeropuerto y horario salen del texto Markdown (`result.content[0].text`): una fila de tabla por vuelo, con líneas `AAA → BBB (inicio → fin)` por tramo, `Layover in XXX` entre tramos, un bloque `Outbound:<br/>` y otro `Return:<br/>`. Los números de vuelo salen del hash del `deepLink`: `#trip=IB114,IB269-LA777` (sentidos separados por coma, tramos por guion; el código de aerolínea son los 2 primeros caracteres). `normalize_search` une cada tarjeta con su fila por el `deepLink` y exige que la cantidad de tramos coincida con la de vuelos; si no coincide, falla con "los tramos no coinciden con los vuelos" (señal de que cambió el formato). El nombre de la aerolínea por tramo no se informa: `carrier_name` repite el código.

c) **Tipo de pasaje.** `attributes[0]` es `standard` o `virtual-interline` (ejemplo SCL→MAD con `includeVirtualInterlining=true`: 8 de 100 resultados eran `virtual-interline`, con cambio de aeropuerto GRU→VCP incluido). El resto es la cantidad de escalas (`nonstop`, `one-stop`, `multi-stop`). La columna "Type" del texto dice `Virtual interline` o `—`. Mapeo: `virtual-interline` en cualquier sentido es `separate_tickets=True`; todos los sentidos `standard` es `False`; cualquier otro valor es `None`.

d) **Hidden city.** Con `includeHiddenCity=true` en 100 resultados SCL→MAD no apareció ninguno marcado, así que el nombre exacto de su atributo no se pudo ver. Se envía siempre `includeHiddenCity=false` y, por seguridad, `normalize_search` además descarta cualquier tarjeta cuyo `attributes` (de cualquier sentido) contenga "hidden" o cuya fila de texto diga "Hidden city". Ese descarte está probado con un fixture sintético (`hidden_city.sse`), no con uno grabado.

e) **Precio con 2 adultos.** `price.amount` es el **total** del grupo: el vuelo Iberia SCL→MAD costó 715 con 1 adulto y 1430 con 2. Por eso `SKIPLAGGED_PRICE_IS_TOTAL = True` y no se multiplica. Los precios no traen separador de miles en `structuredContent` (el texto sí: `$1,430`).

f) **Calendario.** `structuredContent.chart.points` es una lista de `{departure, return, price, usdPrice}` por día de salida (con `chart.currency`). Con ancla 2027-03-15 devolvió de 2027-02-13 a unos 6 semanas después. El calendario no recibe `adults`: los precios son por 1 adulto (orientativos). Se queda con el mínimo por día si hubiera repetidos.

g) **Cantidad.** Una búsqueda trae hasta `limit` resultados (el total disponible va en `pagination.totalAvailable`, 41 con `includeHiddenCity=false` y 300 con `true` para el mismo viaje).

## Rarezas

- La búsqueda con `limit=100` pesa unos 146 KB; con `limit=20` unos 30 KB.
- Los horarios llevan offset; se guardan como hora local de cada aeropuerto, sin zona. La duración de cada sentido se calcula con los horarios completos (con offset), no con el texto.
- Una moneda distinta de USD en `pricing.currency` hace fallar `normalize_search` con "moneda inesperada".
- HTTP 429 pausa la fuente 60 minutos (`SourceBlocked`); las llamadas que estaban en cola detrás de un 429 no salen. El calendario nunca lanza: devuelve `CalendarResult` con estado `paused`, `error` o `timeout`.
- Un error de la herramienta llega con `isError: true` y se informa como `Skiplagged: <mensaje>`.
- Solo se aceptan enlaces `https://`.

## Grabar fixtures

```bash
uv run fly record skiplagged madrid_scl_rt --origen SCL --destino MAD --salida 2027-03-19 --noches 16
uv run fly record skiplagged calendar_eze_mad --origen EZE --destino MAD --salida 2027-03-15 --noches 14 --calendario
```
