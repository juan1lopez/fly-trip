# fly-trip: buscador personal de vuelos baratos (diseño)

- **Fecha:** 2026-11-09
- **Estado:** borrador, pendiente de aprobación
- **Proceso:** brainstorming de superpowers (v7.0.2) y harness engineering
- **Marcas:** "(decisión mía)" señala lo que decidió quien diseñó, no la persona usuaria. Todo lo demás lo eligió ella en la conversación.

---

## 1. Intención y por qué

Es una herramienta personal, con una sola persona usuaria. Sirve para encontrar **rápido** el vuelo más barato, directo o con escalas, sin revisar varias webs. Los viajes empiezan en **Mendoza (Argentina)** y pueden salir de tres aeropuertos: Mendoza (MDZ), Santiago de Chile (SCL) o Buenos Aires-Ezeiza (EZE). Son sobre todo de **largo radio** y casi nunca tienen fechas fijas. Además, la herramienta debe **avisar por Telegram** cuando un viaje vigilado baje de un precio objetivo, aunque la PC esté apagada.

Este dato real muestra por qué conviene buscar desde los tres aeropuertos. Es una consulta a Kiwi del 2026-11-09: Madrid, ida y vuelta, salida entre marzo y mayo de 2027, de 14 a 21 noches.

| Origen | Más barato | Cómo |
|---|---|---|
| SCL | 758 USD | Iberia directo |
| MDZ | 934 USD | JetSMART/Sky hasta SCL + Iberia |
| EZE | 1021 USD | Air Europa directo |

**Éxito significa:**
1. Una búsqueda con fechas abiertas desde los tres orígenes muestra en segundos el más barato de cada origen y el total real desde Mendoza, con un enlace para comprar.
2. Cuando un aviso baja del objetivo, llega **un** mensaje de Telegram (sin spam), también con la PC apagada.
3. Cuando una fuente se rompe, la persona usuaria se entera. Un agente puede detectarlo, arreglarlo y demostrar con tests que quedó arreglado.

## 2. Objetivos, no-objetivos y anti-objetivos

**Objetivos (v1)**
- Búsqueda con fechas abiertas: un rango de salida y un rango de noches, o "solo ida".
- Orígenes por defecto MDZ, SCL y EZE, modificables en cada búsqueda.
- Fuentes: Kiwi.com (servidor MCP oficial) y Google Flights (librería `fli`).
- Resultados ordenados por el total desde Mendoza. Cada uno muestra el equipaje incluido, las escalas, una ⚠ si son pasajes separados y un enlace de compra.
- Avisos de precio por Telegram, revisados cada 6 horas en la nube.
- Un arnés para que agentes construyan y mantengan el proyecto (sección 8).

**No-objetivos (fuera de v1; el diseño no debe impedirlos)**
- Comprar desde la herramienta: solo se ofrecen enlaces.
- "Cualquier destino", multi-ciudad, y volver desde otra ciudad (open-jaw).
- Sumar al precio las valijas extra. Solo se muestra lo que incluye cada tarifa.
- Niños y bebés (v1 solo admite adultos, de 1 a 9), y clases superiores a turista.
- Varias personas usuarias, cuentas, acceso desde fuera de la PC o desde la red local, y app de celular.
- Historial de precios con gráficos.
- Más fuentes (Travelpayouts, SerpApi de pago, webs de aerolíneas). Debe poder añadirse una sin tocar el núcleo.

**Anti-objetivos (sería un fracaso aunque "funcione")**
- Presentar resultados incompletos como completos. Si una fuente falla o está en pausa, se tiene que ver.
- Ocultar que una combinación usa pasajes separados.
- Mostrar un precio de caché como si fuera actual. Siempre se indica su antigüedad.
- Enviar el mismo aviso de Telegram cada 6 horas.
- Provocar que bloqueen la IP de casa con consultas agresivas, o usar proxies, resolver captchas o técnicas para esquivar bloqueos.
- Subir secretos al repositorio (token de Telegram, token de GitHub).
- Búsquedas que tarden minutos.

## 3. Restricciones

- **Máquina:** Windows 11, con Python 3.12.7, Git 2.54, Node 26 y Docker 29. Node y Docker no son necesarios. `uv` no está instalado; se instala al montar el proyecto.
- **Fuentes descartadas:**
  - Ninguna API de pago.
  - Amadeus Self-Service cerró el 2026-07-17.
  - Skyscanner y Kayak no tienen API abierta y bloquean el scraping.
  - Ryanair no opera en la región.
- **Kiwi MCP:**
  - Dirección: `https://mcp.kiwi.com`. Transporte Streamable HTTP, sin autenticación y sin sesión: acepta `tools/call` sin `initialize`, y las respuestas llegan con el formato SSE `event: message` / `data: {...}`.
  - Herramienta `search-flight`. Parámetros útiles: `flyFrom`, que acepta varios códigos separados por coma (probado con `"MDZ,SCL,EZE"`); `departureDate` y `departureDateTo` en formato `dd/mm/yyyy`; `nights_in_dst_from` y `nights_in_dst_to`; `allow_self_transfer`; `max_sector_stopovers`; `adults`; `currency`; y `sort`, que admite `price`, `duration`, `quality`, `date` y `popularity`.
  - Devuelve unos 15 itinerarios por consulta, cada uno con `price`, `baggage`, `bookingUrl` y segmentos que incluyen la aerolínea y el número de vuelo. El JSON de la respuesta trae un campo `"error": null` que no indica error. Tarda entre 2 y 4 segundos.
- **Google Flights**, mediante el paquete de PyPI `flights` (se importa como `fli`):
  - No es oficial. Desde 2026-08 lee la página pública de búsqueda de Google.
  - Cada fecha consultada cuesta una descarga de página, con un máximo de 93 fechas por llamada.
  - Devuelve entre 20 y 45 itinerarios por búsqueda y admite elegir la moneda. La versión 0.9.0, la última en PyPI, no da enlaces de compra por vuelo.
  - En ida y vuelta, cada búsqueda cuesta 1 descarga más por cada ida que se expande para ver sus vueltas.
  - Aproximadamente 1 de cada 60 consultas sale vacía y reintenta sola.
  - Puede romperse en cualquier momento y puede ser bloqueado desde servidores en la nube.
- **Uso moderado (decisión mía):**
  - Límites por búsqueda: Kiwi, como máximo 6 consultas por tramo de fechas, con hasta 4 tramos (ver 5.1); Google, como máximo 12 descargas y 3 a la vez.
  - Si una fuente responde 429, captcha o página de consentimiento, se pausa 1 hora. **Nunca** se intenta esquivar el bloqueo.
- **Avisos:** corren en GitHub Actions, en un repositorio privado, sin pasar de los minutos gratuitos. El uso estimado es de unos 250 min/mes; hay que verificar el cupo vigente al montarlo.
- **Moneda:** USD. Lo que acabe cobrando la tarjeta (impuestos o percepciones por compras en moneda extranjera) no se calcula; se muestra el precio de la fuente.
- **Idioma:**
  - La interfaz, los mensajes y las docs van en español neutro latinoamericano ("pasajes", "valija", "celular").
  - El código y los identificadores van en inglés.
- **Zona horaria:** "hoy" se calcula en `America/Argentina/Mendoza`. Las horas de los vuelos son las locales de cada aeropuerto.
- **Red:** la web escucha solo en `127.0.0.1`.

## 4. Enfoques considerados

### 4.1 Dónde se busca: elegido por la persona usuaria, **web en la PC**

| Opción | A favor | En contra |
|---|---|---|
| **Web local (elegida)** | Cómoda para comparar muchas fechas y tres orígenes. Google funciona mejor desde la IP de casa. No hay servidor que mantener. | Solo se busca desde la PC; los avisos sí llegan al celular. |
| Todo por Telegram | Se puede buscar desde cualquier lado. | Necesita un servidor en la nube, con cuenta y a veces tarjeta. Si estaba dormido, tarda hasta un minuto en arrancar. Desde la nube, probablemente solo funcione Kiwi. |
| Terminal | Lo más rápido de construir y lo más robusto. | No es visual y hay que escribir comandos. |

Descartados: una app de celular (demasiado trabajo para un uso personal) y pedírselo a Claude en cada búsqueda (es lento y gasta tokens).

### 4.2 Dónde corren los avisos y por qué canal llegan

- **Dónde corren:** la persona usuaria contestó que la PC solo está encendida cuando la usa, así que corren en **GitHub Actions cada 6 horas** (decisión mía basada en esa respuesta). El Programador de tareas de Windows se descartó porque no revisa nada con la PC apagada.
- **Canal:** **Telegram**, elegido por la persona usuaria. Se descartaron WhatsApp (no tiene una vía oficial simple y gratuita), el email (menos inmediato) y ntfy.

### 4.3 Cómo combinar las fuentes con fechas abiertas (decisión mía)

- **A. Barrer el calendario en Google Flights.** Costaría una descarga por fecha: con 3 orígenes y unos 90 días, y más todavía con ida y vuelta, serían cientos de descargas por búsqueda. Es lento y abusivo. Descartado.
- **B. Solo Kiwi.** Es rápido, porque una consulta cubre todo el rango. Pero solo ve lo que vende Kiwi y devuelve unos 15 resultados. No basta por sí solo.
- **C. Kiwi explora y Google confirma (elegido).** Kiwi recorre el rango completo. De sus mejores fechas por origen salen los pares (salida, regreso) que quepan en el límite de 12 descargas de Google, y Google Flights se consulta solo para esas fechas exactas. Al final se fusionan los resultados de ambas fuentes.

## 5. Cómo funciona

### 5.1 Búsqueda

**Datos que se piden:**
- Destino: código IATA o ciudad.
- Salida: entre [desde] y [hasta].
- Duración: de [mín] a [máx] noches, o "solo ida".
- Orígenes: casillas, marcadas por defecto MDZ, SCL y EZE.
- Adultos: 1 por defecto.
- "Permitir pasajes separados": activado por defecto.

**Validación:**
- Las fechas cumplen `hoy < desde ≤ hasta`, y las noches cumplen `mín ≤ máx`.
- El rango máximo depende del límite real de Kiwi, que hay que verificar. Si el rango pedido lo supera, se parte en tramos, hasta 4. No se acepta un rango que necesite más tramos, ni uno de más de 365 días.

**Flujo:**
1. **Kiwi, por origen, en dos modos:** uno con `allow_self_transfer` activado y otro desactivado. Son como máximo 6 consultas por tramo de fechas y van en paralelo. Un itinerario que solo aparece en el modo con pasajes separados permitidos se marca **⚠ pasajes separados**. Hay que verificar cuál es el valor por defecto de `allow_self_transfer`.
2. **Elegir las fechas que se confirman en Google** (decisión mía):
   - Por origen, se toman los pares (salida, regreso) distintos más baratos que devolvió Kiwi. Se reparten por turnos entre los orígenes hasta agotar el límite de 12 descargas de Google.
   - Un par de ida y vuelta cuesta 2 descargas (la ida, más las vueltas de la ida más barata), así que caben 6. En solo ida, cada fecha cuesta 1 descarga y caben 12.
   - Si Kiwi no devolvió nada para un origen, se toman 4 fechas de salida repartidas a lo largo del rango, con las noches mínimas. Esto solo es posible si el destino es un código de aeropuerto; si es un nombre de ciudad, ese origen se queda sin confirmación de Google.
   - Si todos los pares posibles caben en el límite, se consultan todos.
3. **Google Flights** se consulta para esos pares, con 3 consultas a la vez como máximo.
4. **Normalizar y fusionar:**
   - Todo se convierte al modelo común de la sección 6.
   - Si dos fuentes traen el mismo itinerario (mismos vuelos y fechas), queda una sola fila con el precio menor y los enlaces de ambas.
   - El precio es siempre el **total para todos los pasajeros**. Hay que verificar si cada fuente da el precio por persona o el total.
5. **Total desde Mendoza:** precio más el traslado del origen (5.2).
6. **Mostrar resultados a medida que llegan:** primero Kiwi, después lo que confirme Google.

**Velocidad (decisión mía):**
- Los primeros resultados aparecen en 5 segundos o menos, en un caso típico.
- La búsqueda completa tarda 30 segundos o menos, en un caso típico. Hay un corte a los 60 segundos que muestra lo que haya.
- Una búsqueda idéntica en los últimos 30 minutos sale de la caché local al instante, con su antigüedad visible y un botón "Actualizar".

### 5.2 Traslado desde Mendoza

- Los resultados con origen MDZ ya incluyen vuelos reales hasta SCL o EZE, como en el ejemplo de JetSMART/Sky con Iberia.
- Para SCL y EZE, la persona usuaria indica una sola vez en Ajustes el costo de ida y vuelta (USD) y las horas del traslado desde Mendoza, sea en bus, en auto o en avión.
- Mientras el traslado no esté configurado, aparece "+ traslado (sin configurar)", el total no lo incluye y se muestra una advertencia.
- El orden de los resultados y los avisos se basan en el **total desde Mendoza**.

### 5.3 Resultados

- **Arriba:** el estado de cada fuente, que puede ser OK (con el tiempo que tardó), en pausa (con el motivo y hasta cuándo) o error (con el motivo).
- **"Lo mejor por origen":** tres tarjetas: Mendoza (todo en avión), vía Santiago (+ traslado) y vía Ezeiza (+ traslado).
- **"Mejor equilibrio" (decisión mía):** el itinerario que minimiza `total + valor_del_tiempo × horas_totales`. Las horas incluyen la ida, la vuelta y el traslado. El valor por defecto es 10 USD por hora y se puede ajustar.
- **Lista completa:** ordenada por total.
- **Cada itinerario muestra:**
  - El total y su desglose (precio + traslado).
  - Las fechas de ida y vuelta.
  - La ruta, con cada escala y su duración. Se marcan las escalas que pasan la noche y las que cambian de aeropuerto.
  - La duración total y las aerolíneas.
  - El equipaje incluido: artículo personal, cabina y despachada, o "desconocido".
  - La marca ⚠ pasajes separados, con la explicación "si pierdes la conexión, nadie te recoloca".
  - La fuente o fuentes, con un botón **Comprar** por cada una. En Kiwi es su `bookingUrl`. En Google es un enlace a la búsqueda de Google Flights con esa ruta y esas fechas, porque la versión 0.9.0 de `fli` no da enlaces por vuelo.
  - La antigüedad del precio.
- **Botón "Crear aviso con esta búsqueda":** propone como objetivo el mejor total actual.

### 5.4 Avisos

- **Qué es un aviso:** una búsqueda guardada (destino, rango, noches, orígenes, adultos y si se permiten pasajes separados) junto con un **precio objetivo**, que es el total desde Mendoza en USD. Su estado puede ser activo, pausado o vencido.
- **Gestión desde la web:** se crean, pausan y borran ahí. La lista muestra la última revisión, el mejor precio visto y si ya se notificó. Si no hay conexión, se muestra la última lista conocida.
- **Dónde se guardan (decisión mía):**
  - En el repositorio privado de GitHub, en una rama `data`:
    - `alerts.json`: los avisos.
    - `settings.json`: los ajustes no secretos que necesita el proceso de revisión, como los traslados y el valor del tiempo.
    - `state.json`: el estado de cada aviso.
    - `doctor.json`: el último resultado del chequeo diario de cada fuente.
  - La web local escribe `alerts.json` y `settings.json` a través de la API de GitHub. Usa un token personal con permisos mínimos y solo sobre este repositorio: contents de lectura y escritura, y actions de lectura.
  - El proceso de revisión escribe `state.json`, y solo cuando algo cambia.
- **Proceso de revisión:**
  - Es un workflow programado cada 6 horas.
  - Para cada aviso activo, repite la búsqueda solo con Kiwi. Google se suma únicamente si el chequeo diario (8.2) confirma que funciona desde Actions.
  - Calcula el total desde Mendoza y se queda con el mejor.
- **Cuándo notifica (decisión mía):**
  - Envía un mensaje cuando el mejor total queda en el objetivo o por debajo, y además se cumple una de estas condiciones: todavía no se notificó en este ciclo, o el precio bajó al menos un 3 % respecto al último notificado.
  - Si el precio vuelve a superar el objetivo, el ciclo se reinicia.
- **Vencimiento:**
  - El rango efectivo es `[max(desde, mañana), hasta]`.
  - Si `hasta` ya pasó, el aviso queda vencido y se notifica una sola vez.
- **Mensaje de Telegram:** en español. Incluye el destino, el mejor total con su desglose, las fechas, la ruta, la ⚠ si son pasajes separados y el enlace Comprar, más las 3 mejores opciones.
- **Límite:** 10 avisos activos.
- **Fallos:**
  - Si el proceso no puede revisar los avisos, envía **un** mensaje por incidencia, no uno por ejecución.
  - La web avisa si la última ejecución tiene más de 12 horas, porque GitHub puede atrasar o desactivar los workflows programados. La hora de la última ejecución la obtiene de la API de GitHub Actions.

### 5.5 Ajustes y secretos

- **Ajustes en la web:**
  - Orígenes por defecto.
  - Traslados a SCL y EZE (USD de ida y vuelta, y horas).
  - Adultos por defecto.
  - Valor del tiempo.
  - Si se permiten pasajes separados por defecto.
  - Telegram, con un botón "Enviar mensaje de prueba".
  - GitHub: estado de la conexión y última ejecución del proceso de revisión.
- **Dónde se guardan los ajustes:** en la PC. Si GitHub está configurado, la web copia a `settings.json`, en la rama `data`, lo que necesita el proceso de revisión.
- **Secretos locales:** van en `.env`, que está excluido de git: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `GITHUB_TOKEN` y `GITHUB_REPO`.
- **Secretos en Actions:** `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID`.

### 5.6 Arranque y puesta en marcha

- **Arranque:** se hace doble clic en `Buscar vuelos.cmd`, en la raíz del proyecto; puede tener además un acceso directo en el escritorio. Arranca el servidor en `127.0.0.1` y abre el navegador. Al cerrar la ventana, se detiene.
- **Guía:** `docs/setup.md` explica paso a paso:
  1. Instalar `uv`.
  2. Crear el bot con BotFather y obtener el `chat_id`.
  3. Crear el repositorio privado y subir el código.
  4. Cargar los secretos.
  5. Crear el token personal de GitHub.

## 6. Modelo de datos normalizado

Esto es una orientación. Quien construya puede cambiar los nombres, pero no el contenido.

- `Itinerary`:
  - Identidad y ruta: `id` (estable: hash de los segmentos y las fechas), `origin`, `destination` y `trip_type` (`oneway` o `return`).
  - Tramos: `outbound: Leg` e `inbound: Leg | None`.
  - Ofertas: `offers: list[Offer]`.
  - Equipaje y pasajes: `baggage: Baggage | None` y `separate_tickets: bool | None`, donde `None` significa desconocido.
  - Totales: `total_duration`, `transfer: TransferCost | None`, `best_price_usd` y `total_from_home_usd`.
- `Leg`: `segments: list[Segment]`, `stops` y `layovers: list[Layover]`.
- `Segment`: `carrier_code`, `carrier_name`, `flight_number`, `from_airport`, `to_airport`, `departure_local` y `arrival_local`.
- `Layover`: `airport`, `duration`, `overnight` y `airport_change`.
- `Offer`: `source`, `price_usd`, `booking_url` y `fetched_at`.
- Una fuente cumple un protocolo común: `search(query) -> SourceResult(itineraries, status, latency, error)`. Declara su límite de consultas y de paralelismo, y **nunca** lanza excepciones al motor: cualquier error se convierte en un `status`.

## 7. Arquitectura propuesta

```
src/flytrip/
  core/      modelos, ranking, fusión, detección de pasajes separados, traslados,
             reglas de aviso. Lógica pura: sin red ni disco.
  sources/   base.py (protocolo y límites), kiwi.py, google_flights.py
  engine.py  orquestación: reparte la búsqueda entre fuentes, aplica límites,
             timeouts y caché (SQLite local), y emite resultados a medida que llegan
  web/       FastAPI, plantillas y HTMX (copia local, sin CDN)
  alerts/    almacén (API de GitHub), proceso de revisión, notificador de Telegram
  cli.py     fly web | search | doctor | record | alerts run | check
tests/       unit/ contract/ engine/ alerts/ web_e2e/ fixtures/
.github/workflows/  ci.yml (en cada push), alerts.yml (cada 6 h), doctor.yml (diario)
docs/        architecture.md, sources/kiwi.md, sources/google-flights.md, setup.md, superpowers/
Buscar vuelos.cmd
```

**Reglas de dependencia, verificadas automáticamente:**
- `core` no importa nada del proyecto.
- `sources` solo importa `core`.
- `engine` importa `core` y `sources`.
- `web` y `alerts` importan `engine` y `core`, pero no se importan entre sí.

**Stack (decisión mía):**
- Python 3.12 con `uv`, FastAPI, Jinja2 y HTMX, `httpx` y `flights` (`fli`).
- pydantic para los modelos y SQLite (de la librería estándar) para la caché.
- pytest para los tests y Playwright para los tests de la web.
- ruff, mypy e import-linter para los chequeos.

## 8. Arnés (harness engineering)

El objetivo es que un agente (Claude Code u otro) pueda construir, cambiar y reparar el proyecto con confianza, y que los fallos se detecten solos.

### 8.1 Guías (antes de actuar)

- **`CLAUDE.md`:** un mapa corto, de 100 líneas como máximo. Explica qué es el proyecto, los comandos, las reglas de arquitectura y de tests, dónde está cada doc y la lista de pasos para añadir una fuente. `AGENTS.md` solo apunta a `CLAUDE.md`. Se escribe a mano y crece **a partir de errores reales**: cada error de un agente se convierte en una regla o, mejor, en un chequeo automático.
- **`docs/sources/<fuente>.md`:** cómo funciona cada fuente, sus parámetros, límites y rarezas, y cómo volver a grabar sus fixtures.
- **Proceso de trabajo:** diseño, después plan y después tareas con TDD (superpowers).

### 8.2 Sensores (después de actuar)

- **`fly check`:** un solo comando que tarda menos de 60 segundos. Ejecuta:
  - ruff (formato y lint).
  - mypy estricto en `core` y `engine`.
  - import-linter, para las reglas de dependencia.
  - pytest **sin red**.
- **Tests sin red:**
  - Cada fuente se prueba con **respuestas reales grabadas** (fixtures saneados).
  - Hay un **test de contrato común** que toda fuente debe pasar. Comprueba que normaliza bien, que nunca lanza excepciones al motor, que respeta sus límites y que maneja respuestas vacías, timeouts y respuestas malformadas.
  - Si un test intenta salir a la red, falla.
- **`fly record <fuente> <escenario>`:** graba fixtures nuevos desde la fuente real, para cuando cambie el formato.
- **`fly doctor`:**
  - Hace una consulta real mínima a cada fuente y valida la forma de la respuesta.
  - Corre a diario en Actions, donde guarda su resultado en `doctor.json` (rama `data`), y, cuando se quiera, en local.
  - Avisa por Telegram **solo cuando una fuente cambia de estado**, de OK a rota o de rota a OK.
- **Tests de la web con Playwright:** usan fuentes falsas. Recorren la búsqueda, los resultados que llegan de a poco, los estados de las fuentes y la creación de un aviso (con un GitHub falso).
- **Hooks de Claude Code** (`.claude/settings.json`):
  - Después de editar un `.py`, se formatea y se revisa con ruff ese archivo.
  - Al terminar un turno se ejecuta `fly check --fast` (todo `fly check` menos los tests de Playwright), y los fallos vuelven al agente.
- **CI:** `fly check` completo en cada push a GitHub.
- **Registro:** cada búsqueda escribe en `logs/` un log estructurado con la fuente, la latencia, el estado y el número de resultados, para que un agente pueda diagnosticar problemas.

## 9. Escenarios de aceptación

1. **Búsqueda completa.** Madrid, salida entre el 1/3 y el 31/5/2027, de 14 a 21 noches, desde MDZ, SCL y EZE.
   - Lo de Kiwi se ve en 5 segundos o menos, y todo en 30 segundos o menos.
   - Aparecen las tres tarjetas por origen, con totales desde Mendoza.
   - Los enlaces abren Kiwi con ese vuelo, o Google Flights con esa ruta y esas fechas.
2. **Google bloquea o falla.** Los resultados de Kiwi se ven igual, el estado indica "Google Flights en pausa" con el motivo y no aparece ningún error en pantalla.
3. **Pasajes separados.** Un itinerario MDZ→SCL→MAD con JetSMART e Iberia que solo aparece con pasajes separados permitidos se muestra con la ⚠ y su explicación.
4. **Mismo vuelo en las dos fuentes.** Queda una sola fila, con el precio menor y dos enlaces.
5. **Aviso que salta.**
   - Se crea un aviso con objetivo 800 USD y aparece en `alerts.json` de la rama `data`.
   - Si en la siguiente revisión el total es de 800 USD o menos, llega 1 mensaje de Telegram.
   - Si en la revisión siguiente el precio es el mismo, no llega ningún mensaje.
   - Si baja al menos un 3 % más, llega otro.
6. **Aviso vencido.** Un aviso cuyo rango ya pasó queda vencido y se notifica una sola vez.
7. **Fuente rota.** Con un fixture de "formato cambiado", `fly doctor` marca la fuente como rota, y en Actions llega un único mensaje de Telegram.
8. **Caché.** La misma búsqueda repetida a los 10 minutos sale al instante desde la caché y muestra su antigüedad.

## 10. Orden de construcción (decisión mía)

1. **Hito 1:** arnés base, motor, fuentes y web de búsqueda. Ya se puede usar por sí solo.
2. **Hito 2:** avisos, que incluyen el almacén en GitHub, el proceso de revisión, Telegram y el chequeo diario.

Habrá un plan por hito.

## 11. A criterio de quien construya

- El diseño visual exacto de la web: tiene que ser simple, legible y en español. No hace falta que se adapte al celular.
- HTMX o JS mínimo, y SSE o consultas periódicas para mostrar los resultados a medida que llegan.
- El cliente MCP: el SDK oficial `mcp` o JSON-RPC plano por HTTP.
- Cómo convertir ciudades en códigos IATA, por ejemplo con una tabla local de OurAirports o con lo que resuelva Kiwi, incluidas las ciudades con varios aeropuertos.
- El formato de los fixtures y la herramienta para grabarlos.
- Los detalles de la API de GitHub y del formato JSON de la rama `data`.
- El ajuste fino de límites, timeouts y tiempo de caché, siempre dentro de los valores de este documento.
- Las verificaciones pendientes:
  - El rango máximo de fechas de Kiwi.
  - El valor por defecto de `allow_self_transfer`.
  - Si cada fuente da el precio por persona o el total.

## 12. Riesgos conocidos

- `fli` y Google Flights pueden romperse en cualquier momento; de hecho, el transporte ya cambió en 2026-08. Por eso hay chequeo diario, fixtures y una fuente aislada.
- Kiwi MCP puede cambiar su esquema o empezar a pedir autenticación. El chequeo diario lo detecta.
- GitHub puede atrasar o desactivar los workflows programados. La web muestra cuánto hace de la última revisión.
- Kiwi devuelve unos 15 itinerarios por consulta y puede no ver tarifas que solo vende la aerolínea. Google mitiga una parte, y en el futuro se pueden añadir más fuentes.
