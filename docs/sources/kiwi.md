# Fuente Kiwi

Servidor MCP oficial de Kiwi.com: `POST https://mcp.kiwi.com`, sin autenticación y sin estado (`tools/call` funciona sin `initialize`).

## Cómo se consulta

- Encabezados: `Content-Type: application/json`, `Accept: application/json, text/event-stream` y `User-Agent: fly-trip/0.1 (uso personal)`.
- Cuerpo: llamada JSON-RPC `tools/call` a la herramienta `search-flight`.
- La respuesta llega como SSE (`event: message` / `data: {json}`). Los datos útiles están en `result.structuredContent`; si falta, en `result.content[0].text`.

Parámetros que usamos: `flyFrom`, `flyTo`, `departureDate` y `departureDateTo` (formato `dd/mm/aaaa`), `adults`, `currency=USD`, `locale=es`, `sort=price`, `allow_self_transfer` y, si es ida y vuelta, `nights_in_dst_from` y `nights_in_dst_to`.

## Verificación en vivo (2026-11-09)

Todas las pruebas fueron MDZ/SCL → MAD, de 14 a 21 noches, en USD.

a) **Ventana de fechas.** `departureDate..departureDateTo` aceptó 92, 180 y 365 días sin error, y siempre devolvió 15 resultados. Como cada consulta trae solo unos 15 resultados, una ventana ancha da menos cobertura que varias chicas. Por eso `KIWI_MAX_WINDOW_DAYS = 92`: `KiwiSource` parte el rango en tramos de hasta 92 días, con una consulta por tramo y en secuencia.

b) **`allow_self_transfer`.** Omitirlo equivale a `true` (mismos resultados, desde USD 934 en MDZ→MAD). Con `false` los resultados suben (desde USD 980). Nosotros siempre lo enviamos de forma explícita.

c) **Precio con 2 adultos.** `price` es el **total** del grupo: SCL→MAD costó USD 763 con 1 adulto y USD 1530 con 2. Por eso `KIWI_PRICE_IS_TOTAL = True` y `normalize` no multiplica.

## Rarezas

- Devuelve unos 15 resultados por llamada y tarda entre 2 y 4 s.
- `structuredContent` trae `"error": null` cuando todo anda bien; se tolera. Un error real llega con `isError: true` o con `error` distinto de null y se informa como `Kiwi: <mensaje>`.
- Si la moneda no es USD, `normalize` falla con `moneda inesperada`.
- HTTP 429 pausa la fuente 60 minutos (`SourceBlocked`).
- Kiwi no informa si un itinerario es de pasajes separados: `separate_tickets` queda en `None`.
- Los horarios vienen en hora local del aeropuerto, y se guardan sin zona horaria.

## Regrabar los fixtures

Solo a mano, nunca desde los tests. Una consulta por fixture, en secuencia y con unos segundos de pausa:

```
D="--destino MAD --desde 2027-03-01 --hasta 2027-05-31 --noches 14-21"
uv run fly record kiwi madrid_scl_return --origen SCL $D
uv run fly record kiwi madrid_mdz_return_all --origen MDZ $D
uv run fly record kiwi madrid_mdz_return_protected --origen MDZ $D --sin-separados
uv run fly record kiwi madrid_eze_return --origen EZE $D
uv run fly record kiwi madrid_scl_return_2adults --origen SCL $D --adultos 2
```

Los fixtures `synthetic_*`, `tool_error`, `wrong_currency` y `empty` están escritos a mano. Todos los `.sse` van con saltos de línea LF.
