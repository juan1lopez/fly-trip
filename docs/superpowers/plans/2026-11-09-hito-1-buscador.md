# Hito 1: buscador (motor, fuentes, web y arnés). Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** construir una web local que busca vuelos con fechas abiertas desde MDZ, SCL y EZE, en Kiwi y en Google Flights, y muestra lo más barato desde Mendoza. Se construye con un arnés que permite a agentes construirla y mantenerla.

**Architecture:** el código vive en el paquete `flytrip`, organizado en capas `core → sources → engine → web → cli` que import-linter verifica.
- Kiwi explora el rango completo de fechas a través de su MCP (JSON-RPC por HTTP).
- Google Flights, mediante `fli`, confirma pares de fechas dentro de un presupuesto.
- El motor emite eventos. La web los muestra por SSE a medida que llegan, y la CLI usa el mismo motor.

**Tech Stack:**
- Aplicación: Python 3.12 con uv, Typer + rich, FastAPI + Jinja2 + HTMX 2 (extensión SSE, en copia local), httpx, `flights==0.9.0` (se importa como `fli`), pydantic v2, SQLite y tzdata.
- Tests: pytest, pytest-asyncio, respx, pytest-socket y pytest-playwright.
- Chequeos: ruff, mypy e import-linter.

**Spec:** `docs/superpowers/specs/2026-11-09-buscador-vuelos-baratos-design.md`. Cubre las secciones 1 a 9 y el escenario 8; los avisos (5.4) quedan para el Hito 2.

## Global Constraints

**Entorno y dependencias**
- Python `>=3.12,<3.13`.
- Dependencias gestionadas con `uv`; `uv.lock` se versiona.
- `flights` fijado en `==0.9.0`.
- `tzdata` es obligatorio, porque Windows no trae la base de zonas horarias.
- Si `uv` no está en el PATH, se usa `python -m uv` en todos los comandos de este plan.

**Idioma**
- En español neutro latinoamericano ("pasajes", "valija", "celular"): la interfaz, los mensajes de error, la salida de la CLI y las docs.
- En inglés: el código, los identificadores y los nombres de tests.

**Moneda y fechas**
- Todas las fuentes se consultan en USD. Un resultado en otra moneda es un error de esa fuente: nunca se mezclan monedas.
- "Hoy" se calcula en `America/Argentina/Mendoza`.
- Las horas de los vuelos son las locales de cada aeropuerto, sin zona horaria (naive).

**Kiwi**
- Dirección: `https://mcp.kiwi.com`.
- Como máximo 6 consultas por tramo de fechas, con un máximo de 4 tramos.
- Timeout de 20 s por consulta.
- Envía el User-Agent `fly-trip/0.1 (uso personal)`.

**Google Flights**
- Como máximo 12 descargas por búsqueda y 3 a la vez.
- Un par de ida y vuelta cuesta 2 descargas (`top_n=1`).
- Timeout total de 40 s.

**Tiempos, caché y bloqueos**
- La búsqueda se corta a los 60 s.
- Las búsquedas idénticas se sirven desde una caché de 30 min.
- Ante un bloqueo (HTTP 429, captcha o página de consentimiento), la fuente queda en pausa 60 min.
- Nunca se usan proxies, ni se resuelven captchas, ni se aplican técnicas para esquivar bloqueos.

**Web**
- Escucha solo en `127.0.0.1`.
- Puerto preferido: 8765. Si está ocupado, usa el siguiente libre.

**Valores por defecto**
- Orígenes: `MDZ`, `SCL` y `EZE`.
- Adultos: 1, en un rango de 1 a 9.
- Valor del tiempo: 10 USD por hora.
- Pasajes separados permitidos.
- Rango máximo de fechas: `min(365, 4 × KIWI_MAX_WINDOW_DAYS)` días.

**Tests**
- Los tests no salen a internet: solo pueden conectar con `127.0.0.1`, `localhost` y `::1`.
- Los tests que sí necesitan internet llevan la marca `live` y nunca se ejecutan dentro de `fly check`.

**Archivos excluidos de git**
- Datos locales en `.flytrip/`, logs en `logs/` y secretos en `.env`. Los tres van en `.gitignore`.

**Fin de línea**
- `.gitattributes` fija `* text=auto eol=lf`, salvo `*.cmd`, que usa `eol=crlf`.

## Review Focus

1. **Consola de Windows en cp1252.** `fly search` imprime "→", "⚠" y acentos. Se espera una salida legible y el código de salida 0, nunca un `UnicodeEncodeError`. Lo prueba la Tarea 10 (`test_search_output_survives_cp1252`).
2. **Google ignora `curr=USD` y devuelve otra moneda.** Esa fuente queda en error con un mensaje que menciona "moneda inesperada", y ningún precio suyo llega a los resultados. Lo prueba la Tarea 7 (`test_wrong_currency_is_error`).
3. **Un origen sin resultados.** Su tarjeta muestra "Sin resultados para este origen" en vez de desaparecer. Lo prueba la Tarea 11 (`test_empty_origin_card_shows_message`).
4. **El puerto 8765 está ocupado.** `fly web` usa el siguiente puerto libre y abre esa URL. Lo prueba la Tarea 12 (`test_find_free_port_skips_busy`).
5. **Dos o más adultos.** El precio es siempre el total para todos los pasajeros, en las dos fuentes. Lo prueban las Tareas 6 y 7 (`test_two_adults_price_is_total`).

---

### Task 1: Esqueleto del proyecto y `fly check`

**Files:**
- Create: `pyproject.toml`, `.python-version` (`3.12`), `.gitignore`, `.gitattributes`, `.env.example` (vacío con un comentario; los secretos llegan en el Hito 2)
- Create: `src/flytrip/__init__.py`, `src/flytrip/__main__.py`, `src/flytrip/cli.py`, `src/flytrip/{core,sources,engine,web,devtools}/__init__.py`, `src/flytrip/devtools/check.py`
- Test: `tests/__init__.py`, `tests/devtools/test_check.py`

**Interfaces:**
- Produces:
  - `flytrip.cli.app`, una app de Typer que se instala como el script `fly = "flytrip.cli:app"`. `python -m flytrip` ejecuta `app()`.
  - `flytrip.devtools.check.CheckStep`, una dataclass frozen con los campos `name: str` y `argv: list[str]`.
  - `build_check_steps(fast: bool) -> list[CheckStep]`.
  - `run_check_steps(steps: list[CheckStep], runner: Callable[[list[str]], int] = subprocess_runner) -> int`. Ejecuta **todos** los pasos, imprime `✓ name` o `✗ name` por cada uno y devuelve cuántos fallaron.
  - El comando `fly check [--fast]` termina con 0 si no falló ningún paso y con 1 si falló alguno.

- [ ] **Step 1: Instalar uv**

Run: `python -m pip install uv`, y después `python -m uv --version`.
Expected: muestra una versión.

- [ ] **Step 2: Escribir `pyproject.toml`**

Valores fijos:
- `[project]`:
  - `name = "flytrip"`, `requires-python = ">=3.12,<3.13"`.
  - Dependencias: `fastapi`, `uvicorn[standard]`, `jinja2`, `httpx`, `pydantic>=2`, `typer`, `rich`, `flights==0.9.0`, `tzdata`.
- `[dependency-groups].dev`: `pytest`, `pytest-asyncio`, `respx`, `pytest-socket`, `pytest-playwright`, `ruff`, `mypy`, `import-linter`.
- Build backend: hatchling, con el paquete en `src/flytrip`.
- `[tool.pytest.ini_options]`:
  - `asyncio_mode = "auto"` y `testpaths = ["tests"]`.
  - `markers`: `live` (sale a internet) y `e2e` (navegador).
- `[tool.ruff]`: `line-length = 100`, `target-version = "py312"`, `lint.select = ["E","F","I","UP","B","SIM","ASYNC"]`.
- `[tool.mypy]`: `files = ["src"]`, `plugins = ["pydantic.mypy"]`. `strict = true` en los overrides de `flytrip.core.*` y `flytrip.engine.*`.
- `[tool.importlinter]`, con `root_package = "flytrip"` y dos contratos:
  - De tipo `layers`, con el orden `flytrip.cli` > `flytrip.web` > `flytrip.engine` > `flytrip.sources` > `flytrip.core`.
  - De tipo `forbidden`: `flytrip.core`, `flytrip.sources`, `flytrip.engine` y `flytrip.web` no pueden importar `flytrip.devtools`.
- Para `.gitignore` y `.gitattributes`, ver Global Constraints.

- [ ] **Step 3: Escribir los tests que fallan**

```python
from flytrip.devtools.check import CheckStep, build_check_steps, run_check_steps


def test_fast_steps_skip_e2e_and_live():
    steps = build_check_steps(fast=True)
    assert [s.name for s in steps] == [
        "ruff format",
        "ruff lint",
        "mypy",
        "import-linter",
        "pytest",
    ]
    assert steps[0].argv == ["uv", "run", "ruff", "format", "--check", "."]
    assert steps[1].argv == ["uv", "run", "ruff", "check", "."]
    assert steps[2].argv == ["uv", "run", "mypy"]
    assert steps[3].argv == ["uv", "run", "lint-imports"]
    assert steps[4].argv == ["uv", "run", "pytest", "-q", "-m", "not live and not e2e"]


def test_full_steps_include_e2e():
    assert build_check_steps(fast=False)[-1].argv == ["uv", "run", "pytest", "-q", "-m", "not live"]


def test_run_counts_failures_and_runs_all_steps():
    codes, seen = iter([0, 1, 0]), []
    steps = [CheckStep("a", ["a"]), CheckStep("b", ["b"]), CheckStep("c", ["c"])]
    assert run_check_steps(steps, runner=lambda argv: seen.append(argv) or next(codes)) == 1
    assert seen == [["a"], ["b"], ["c"]]
```

- [ ] **Step 4: Comprobar que fallan**

Run: `uv sync && uv run pytest tests/devtools/test_check.py -q`
Expected: FAIL porque no existe `flytrip.devtools.check`.

- [ ] **Step 5: Implementar `check.py` y el comando `check` de `cli.py`**

- [ ] **Step 6: Comprobar que todo pasa**

Run: `uv run fly check --fast`
Expected: los 5 pasos muestran `✓` y el código de salida es 0.

- [ ] **Step 7: Commit**

`git add -A && git commit -m "chore: project skeleton with fly check"`

---

### Task 2: Guías y sensores del arnés

**Files:**
- Create: `CLAUDE.md`, `AGENTS.md`, `docs/architecture.md`, `docs/setup.md`, `.claude/settings.json`, `.github/workflows/ci.yml`
- Create: `src/flytrip/devtools/hooks.py`, `tests/conftest.py` (bloqueo de red)
- Test: `tests/devtools/test_hooks.py`, `tests/harness/test_network_guard.py`, `tests/harness/test_docs.py`

**Interfaces:**
- Consumes: el comando `fly check --fast` de la Tarea 1.
- Produces:
  - `flytrip.devtools.hooks.post_edit_commands(payload: dict[str, Any]) -> list[list[str]]`.
  - `should_run_stop_check(payload: dict[str, Any]) -> bool`.
  - `summarize_failure(output: str, max_lines: int = 40) -> str`.
  - Un punto de entrada de módulo, `python -m flytrip.devtools.hooks {post-edit|stop}`, que lee el JSON del hook por stdin:
    - `post-edit` ejecuta los comandos. Si `ruff check` sigue reportando errores, los escribe en stderr y sale con 2.
    - `stop` ejecuta `uv run fly check --fast` cuando `should_run_stop_check` lo indica. Si falla, escribe `summarize_failure(...)` en stderr y sale con 2.

- [ ] **Step 1: Escribir los tests que fallan**

```python
from flytrip.devtools.hooks import post_edit_commands, should_run_stop_check, summarize_failure


def test_post_edit_formats_python_files():
    payload = {"tool_name": "Edit", "tool_input": {"file_path": "src/flytrip/core/models.py"}}
    assert post_edit_commands(payload) == [
        ["uv", "run", "ruff", "format", "src/flytrip/core/models.py"],
        ["uv", "run", "ruff", "check", "--fix", "src/flytrip/core/models.py"],
    ]


def test_post_edit_ignores_other_files():
    assert (
        post_edit_commands({"tool_name": "Write", "tool_input": {"file_path": "docs/setup.md"}})
        == []
    )


def test_stop_check_skips_when_hook_already_active():
    assert should_run_stop_check({"stop_hook_active": True}) is False
    assert should_run_stop_check({"stop_hook_active": False}) is True


def test_summarize_keeps_last_lines():
    out = "\n".join(f"line {i}" for i in range(100))
    assert summarize_failure(out, max_lines=40).splitlines() == [
        f"line {i}" for i in range(60, 100)
    ]
```

```python
# tests/harness/test_network_guard.py
import socket, pytest
from pytest_socket import SocketConnectBlockedError


def test_internet_is_blocked():
    with pytest.raises(SocketConnectBlockedError):
        socket.create_connection(("1.1.1.1", 443), timeout=1)


def test_localhost_is_allowed():
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    with socket.create_connection(server.getsockname(), timeout=1):
        pass
    server.close()
```

```python
# tests/harness/test_docs.py
ROOT = Path(__file__).resolve().parents[2]


def test_claude_md_is_a_short_map():
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert len(text.splitlines()) <= 100
    for needle in ["uv run fly check", "docs/architecture.md", "docs/sources/", "tests/fixtures/"]:
        assert needle in text


def test_agents_md_points_to_claude_md():
    assert "CLAUDE.md" in (ROOT / "AGENTS.md").read_text(encoding="utf-8")
```

- [ ] **Step 2: Comprobar que fallan**

Run: `uv run pytest tests/devtools/test_hooks.py tests/harness -q`
Expected: FAIL.

- [ ] **Step 3: Implementar `hooks.py`, el bloqueo de red y las guías**

- **Bloqueo de red:** un fixture `autouse` en `tests/conftest.py` limita las conexiones a `127.0.0.1`, `localhost` y `::1` con pytest-socket, salvo en los tests con la marca `live`. No se usa `--disable-socket`, porque el event loop de asyncio en Windows necesita sockets locales.
- **`CLAUDE.md`** (como máximo 100 líneas, en español). Secciones:
  - Qué es el proyecto.
  - Comandos: `uv run fly check`, `--fast`, `fly web`, `fly search`, `fly doctor` y `fly record`.
  - Capas y su regla.
  - Reglas de tests: sin red, fixtures en `tests/fixtures/`, contrato común para fuentes.
  - Lista de pasos para añadir una fuente.
  - Mapa de docs: `docs/architecture.md`, `docs/sources/`, `docs/superpowers/`.
  - Regla final: "cada error de un agente se convierte en una regla aquí o, mejor, en un chequeo".
- **`AGENTS.md`:** una sola línea que apunta a `CLAUDE.md`.
- **`docs/architecture.md`:**
  - Las capas y el flujo: Kiwi explora → candidatos → Google confirma → fusión → traslados → ranking.
  - Un mapa que relaciona cada sección del spec con su módulo.
- **`docs/setup.md`**, la parte del Hito 1:
  1. `python -m pip install uv`.
  2. `uv sync`.
  3. `uv run playwright install chromium`, solo para los tests e2e.
  4. Doble clic en `Buscar vuelos.cmd`.
- **`.claude/settings.json`:**
  - `PostToolUse` con `matcher` `"Edit|Write|MultiEdit"` → `uv run python -m flytrip.devtools.hooks post-edit`.
  - `Stop` → `uv run python -m flytrip.devtools.hooks stop`, con `timeout` de 180.
- **`.github/workflows/ci.yml`**, que se ejecuta en push y en pull_request sobre `ubuntu-latest`:
  1. checkout.
  2. `astral-sh/setup-uv`, en la versión mayor vigente.
  3. `uv sync --frozen`.
  4. `uv run playwright install --with-deps chromium`.
  5. `uv run fly check`.

- [ ] **Step 4: Comprobar que todo pasa**

Run: `uv run fly check --fast`
Expected: todos los pasos muestran `✓`.

Nota: Claude Code carga los hooks al iniciar la sesión, así que estos se activan en la siguiente. Se puede confirmar con `/hooks`.

- [ ] **Step 5: Commit**

`git add -A && git commit -m "chore: agent harness guides, hooks, CI and network guard"`

---

### Task 3: Modelos del núcleo, tramos y consulta

**Files:**
- Create: `src/flytrip/core/models.py`, `src/flytrip/core/legs.py`, `src/flytrip/core/query.py`, `tests/factories.py`
- Test: `tests/core/test_legs.py`, `tests/core/test_models.py`, `tests/core/test_query.py`

**Interfaces:**
- Produces, en `models.py` (pydantic v2, `frozen=True`, dinero en `Decimal`):
  - `Segment(carrier_code: str, carrier_name: str, flight_number: str, from_airport: str, to_airport: str, departure_local: datetime, arrival_local: datetime)`
  - `Layover(airport: str, minutes: int, overnight: bool, airport_change: bool)`
  - `Leg(segments: tuple[Segment, ...], stops: int, layovers: tuple[Layover, ...], duration_minutes: int)`
  - `Baggage(personal_item: int | None, cabin_bag: int | None, checked_bag: int | None)`
  - `Offer(source: Literal["kiwi", "google"], price_usd: Decimal, booking_url: str, fetched_at: datetime)`
  - `TransferCost(cost_usd_roundtrip: Decimal, hours_one_way: Decimal)`, con los dos campos `>= 0`.
  - `Itinerary(id: str, origin: str, destination: str, trip_type: Literal["oneway", "return"], outbound: Leg, inbound: Leg | None, offers: tuple[Offer, ...], baggage: Baggage | None, separate_tickets: bool | None, transfer: TransferCost | None = None)`. Propiedades:
    - `best_offer -> Offer`: la oferta de menor precio.
    - `price_usd -> Decimal`.
    - `total_from_home_usd -> Decimal`: el precio, más el costo del traslado si lo hay.
    - `travel_hours -> Decimal`: la suma de los tramos en horas, más `hours_one_way × (2 si es ida y vuelta, 1 si es solo ida)`.
- Produces, en `legs.py`:
  - `normalize_flight_number(carrier_code: str, raw: str) -> str`: quita el prefijo de la aerolínea, los espacios y los ceros a la izquierda.
  - `build_leg(segments: Sequence[Segment], duration_minutes: int) -> Leg`. La duración la da la fuente, porque las horas son locales y no se pueden restar entre zonas horarias. Para cada escala:
    - `airport` es el aeropuerto de llegada del segmento anterior.
    - `minutes` es la diferencia entre la salida siguiente y esa llegada.
    - `overnight` es verdadero si las dos fechas son distintas.
    - `airport_change` es verdadero si el aeropuerto de salida siguiente es distinto del de llegada.
  - `itinerary_id(outbound: Leg, inbound: Leg | None) -> str`: los primeros 16 caracteres hexadecimales del sha1 de `"|".join(f"{s.carrier_code}{s.flight_number}@{s.departure_local:%Y-%m-%dT%H:%M}")`, recorriendo todos los segmentos en orden.
- Produces, en `query.py`:
  - `MENDOZA_TZ`.
  - `today_in_mendoza(now_utc: datetime) -> date`.
  - `SearchQuery(destination: str, origins: tuple[str, ...], depart_from: date, depart_to: date, nights_min: int | None, nights_max: int | None, adults: int = 1, allow_separate_tickets: bool = True)`. No impone restricciones de rango: valida solo `validate_query`. Tiene la propiedad `trip_type` y el método `cache_key() -> str` (sha256 del JSON canónico).
  - `validate_query(query: SearchQuery, today: date, max_window_days: int = 365) -> list[str]`, con los mensajes exactos de los tests.
- Produces, en `tests/factories.py`:
  - `seg(carrier, number, frm, to, dep_iso, arr_iso) -> Segment`.
  - `T(cost: str, hours: str) -> TransferCost`.
  - `make_itinerary(id="X", origin="SCL", destination="MAD", price="758", out_minutes=780, in_minutes=780, transfer=None, offers=None, separate_tickets=None, trip_type="return") -> Itinerary`. `offers` es `list[tuple[source, precio_str, url]]`; si se omite, se genera una oferta de Kiwi con `price`.
  - `make_query(**kw) -> SearchQuery`. Por defecto usa MAD, `("MDZ", "SCL", "EZE")`, del 2027-03-01 al 2027-05-31 y de 14 a 21 noches; `kw` sobrescribe esos valores.
  - `fixed_clock(iso: str) -> Callable[[], datetime]`.
  - Las constantes `FETCHED = datetime(2026, 11, 9, 15, 0, tzinfo=timezone.utc)` y `CLOCK = fixed_clock("2026-11-09T15:00:00+00:00")`.
  - `fixture(source: str, name: str) -> str`, que lee `tests/fixtures/<source>/<name>` en UTF-8.

- [ ] **Step 1: Escribir los tests que fallan**

```python
def test_normalize_flight_number():
    assert normalize_flight_number("IB", "IB6830") == "6830"
    assert normalize_flight_number("IB", "06830") == "6830"
    assert normalize_flight_number("H2", "H2 123") == "123"
    assert normalize_flight_number("JA", "7104") == "7104"


def test_build_leg_computes_layovers():
    leg = build_leg(
        [
            seg("JA", "7104", "MDZ", "SCL", "2027-03-10T06:00", "2027-03-10T07:00"),
            seg("IB", "6830", "SCL", "MAD", "2027-03-10T23:50", "2027-03-11T16:40"),
        ],
        1830,
    )
    assert leg.stops == 1 and leg.duration_minutes == 1830
    assert leg.layovers[0] == Layover(
        airport="SCL", minutes=1010, overnight=False, airport_change=False
    )


def test_overnight_and_airport_change():
    leg = build_leg(
        [
            seg("AR", "1405", "MDZ", "AEP", "2027-03-10T20:00", "2027-03-10T22:00"),
            seg("AR", "1132", "EZE", "MAD", "2027-03-11T08:00", "2027-03-12T01:00"),
        ],
        1740,
    )
    assert leg.layovers[0] == Layover(
        airport="AEP", minutes=600, overnight=True, airport_change=True
    )


def test_itinerary_id_is_stable_and_order_sensitive():
    a = build_leg([seg("IB", "6830", "SCL", "MAD", "2027-03-19T00:50", "2027-03-19T17:30")], 760)
    b = build_leg([seg("IB", "6831", "MAD", "SCL", "2027-04-04T23:55", "2027-04-05T08:45")], 750)
    assert itinerary_id(a, b) == itinerary_id(a, b) != itinerary_id(b, a)
    assert len(itinerary_id(a, None)) == 16


def test_total_and_travel_hours_with_transfer():
    it = make_itinerary(
        origin="SCL", price="758", out_minutes=780, in_minutes=780, transfer=T("80", "7")
    )
    assert it.total_from_home_usd == Decimal("838")
    assert it.travel_hours == Decimal("40")


def test_today_in_mendoza_is_utc_minus_3():
    assert today_in_mendoza(datetime(2026, 11, 10, 2, 30, tzinfo=timezone.utc)) == date(2026, 11, 9)


TODAY = date(2026, 11, 9)
q = make_query  # MAD, ("MDZ", "SCL", "EZE"), 2027-03-01..2027-05-31, 14–21 noches; kw sobrescribe


def test_valid_query_has_no_errors():
    assert validate_query(q(), TODAY) == []


@pytest.mark.parametrize(
    "kw,message",
    [
        ({"destination": "  "}, "Indica un destino."),
        ({"origins": ()}, "Elige al menos un origen."),
        ({"origins": ("MDZ", "X1")}, "Origen inválido: X1."),
        ({"depart_from": TODAY}, "La fecha 'desde' tiene que ser posterior a hoy."),
        ({"depart_to": date(2027, 2, 1)}, "La fecha 'hasta' no puede ser anterior a 'desde'."),
        ({"depart_to": date(2028, 3, 2)}, "El rango de fechas no puede superar 365 días."),
        ({"nights_max": None}, "Indica noches mínimas y máximas, o marca solo ida."),
        ({"nights_min": 0}, "Las noches tienen que estar entre 1 y 60."),
        ({"nights_min": 22}, "Las noches mínimas no pueden superar las máximas."),
        ({"adults": 10}, "Adultos: entre 1 y 9."),
    ],
)
def test_validation_messages(kw, message):
    assert message in validate_query(q(**kw), TODAY)


def test_cache_key_changes_with_query():
    assert q().cache_key() == q().cache_key() != q(adults=2).cache_key()
```

- [ ] **Step 2: Comprobar que fallan**

Run: `uv run pytest tests/core -q`
Expected: FAIL por import.

- [ ] **Step 3: Implementar `models.py`, `legs.py`, `query.py` y `tests/factories.py`**

Con las firmas de Interfaces.

- [ ] **Step 4: Comprobar que todo pasa**

Run: `uv run fly check --fast`
Expected: todo `✓`. mypy en modo strict sobre `core` también pasa.

- [ ] **Step 5: Commit**

`git add -A && git commit -m "feat(core): itinerary models, legs and search query validation"`

---

### Task 4: Ranking, fusión y pasajes separados

**Files:**
- Create: `src/flytrip/core/ranking.py`
- Test: `tests/core/test_ranking.py`

**Interfaces:**
- Consumes: `Itinerary`, `TransferCost` y las factorías de la Tarea 3.
- Produces:
  - `merge_duplicates(itineraries: Iterable[Itinerary]) -> list[Itinerary]`. Agrupa los itinerarios con el mismo `id`:
    - `offers`: la unión, sin repetir `(source, booking_url)`, ordenada por precio.
    - `baggage`: el primero que no sea `None`.
    - `separate_tickets`: `True` si alguno es `True`; si no, `False` si alguno es `False`; si no, `None`.
  - `mark_separate_tickets(all_mode: Sequence[Itinerary], protected_mode: Sequence[Itinerary]) -> list[Itinerary]`. Los `id` presentes en `protected_mode` quedan en `False` y los que solo están en `all_mode`, en `True`.
  - `apply_transfers(itineraries: Iterable[Itinerary], transfers: Mapping[str, TransferCost | None]) -> list[Itinerary]`. Asigna el traslado según `origin`. Un origen ausente o con valor `None` queda sin traslado.
  - `sort_by_total(itineraries: Iterable[Itinerary]) -> list[Itinerary]`, con la clave `(total_from_home_usd, travel_hours, id)`.
  - `best_per_origin(itineraries: Sequence[Itinerary], origins: Sequence[str]) -> dict[str, Itinerary | None]`. Las claves salen en el orden de `origins`.
  - `best_balance(itineraries: Sequence[Itinerary], usd_per_hour: Decimal) -> Itinerary | None`. Elige el mínimo de `total_from_home_usd + usd_per_hour × travel_hours`; un empate se resuelve por total y después por `id`.

- [ ] **Step 1: Escribir los tests que fallan**

```python
def test_sort_best_per_origin_and_balance():
    a = make_itinerary(
        id="A", origin="SCL", price="758", out_minutes=780, in_minutes=780, transfer=T("80", "7")
    )
    b = make_itinerary(id="B", origin="MDZ", price="934", out_minutes=900, in_minutes=960)
    c = make_itinerary(
        id="C", origin="EZE", price="1021", out_minutes=750, in_minutes=780, transfer=T("200", "2")
    )
    ranked = sort_by_total([c, b, a])
    assert [i.id for i in ranked] == ["A", "B", "C"]
    assert best_per_origin(ranked, ["MDZ", "SCL", "EZE", "AEP"]) == {
        "MDZ": b,
        "SCL": a,
        "EZE": c,
        "AEP": None,
    }
    assert best_balance(ranked, Decimal("10")).id == "A"  # 838+400=1238 < 934+310=1244
    assert best_balance(ranked, Decimal("20")).id == "B"  # 934+620=1554 < 838+800=1638


def test_merge_keeps_both_links_cheapest_first():
    k = make_itinerary(id="X", offers=[("kiwi", "763", "https://kiwi.com/u/1")])
    g = make_itinerary(
        id="X",
        offers=[("google", "770", "https://www.google.com/travel/flights?q=x")],
        separate_tickets=False,
    )
    [m] = merge_duplicates([g, k])
    assert [o.source for o in m.offers] == ["kiwi", "google"]
    assert m.price_usd == Decimal("763") and m.separate_tickets is False


def test_mark_separate_tickets_from_two_modes():
    x, y = make_itinerary(id="X"), make_itinerary(id="Y")
    marked = {
        i.id: i.separate_tickets for i in mark_separate_tickets(all_mode=[x, y], protected_mode=[y])
    }
    assert marked == {"X": True, "Y": False}


def test_apply_transfers_by_origin():
    [scl] = apply_transfers(
        [make_itinerary(origin="SCL", price="758")], {"SCL": T("80", "7"), "EZE": None}
    )
    [mdz] = apply_transfers([make_itinerary(origin="MDZ", price="934")], {"SCL": T("80", "7")})
    assert scl.total_from_home_usd == Decimal("838")
    assert mdz.transfer is None and mdz.total_from_home_usd == Decimal("934")
```

- [ ] **Step 2: Comprobar que fallan**

Run: `uv run pytest tests/core/test_ranking.py -q`
Expected: FAIL.

- [ ] **Step 3: Implementar `ranking.py`**

Funciones puras, sin red ni disco.

- [ ] **Step 4: Comprobar que todo pasa**

Run: `uv run fly check --fast`
Expected: todo `✓`.

- [ ] **Step 5: Commit**

`git add -A && git commit -m "feat(core): ranking, duplicate merge and separate-ticket marking"`

---

### Task 5: Protocolo de fuentes, pausas, ejecución segura y contrato

**Files:**
- Create: `src/flytrip/sources/base.py`, `tests/fakes.py`, `tests/contract/cases.py`
- Test: `tests/sources/test_base.py`, `tests/contract/test_source_contract.py`

**Interfaces:**
- Consumes: `Itinerary` (Tarea 3) y `MENDOZA_TZ`.
- Produces:
  - `SourceRequest(origin: str, destination: str, depart_from: date, depart_to: date, nights_min: int | None, nights_max: int | None, adults: int, allow_separate_tickets: bool)`, frozen.
  - `SourceResult(source: str, status: Literal["ok", "paused", "error", "timeout"], itineraries: tuple[Itinerary, ...] = (), detail: str = "", latency_ms: int = 0, fetches: int = 0)`, frozen.
  - `class Source(Protocol)`, con el atributo `name: str` y el método `async def search(self, request: SourceRequest) -> SourceResult`.
  - `class SourceBlocked(Exception)`, cuyo constructor es `__init__(self, reason: str)`.
  - `class PauseRegistry`, persistido como JSON en `path`:
    - `__init__(self, path: Path, clock: Callable[[], datetime])`.
    - `pause(self, source: str, minutes: int, reason: str) -> None`.
    - `active_pause(self, source: str) -> tuple[datetime, str] | None`, que ignora las pausas vencidas.
  - `async def run_safely(source: Source, request: SourceRequest, *, timeout_s: float, pauses: PauseRegistry, clock: Callable[[], datetime]) -> SourceResult`. **Nunca lanza.** Siempre rellena `latency_ms`, y devuelve estos `detail` exactos:
    - Fuente en pausa → `"En pausa hasta las HH:MM: {motivo}"`, con la hora en Mendoza.
    - `SourceBlocked` → pausa la fuente 60 min y devuelve el mismo formato.
    - Timeout → `"No respondió en {timeout_s:.0f} s"`.
    - Cualquier otra excepción → `"Error inesperado ({NombreDeLaExcepción})"`.
  - En `tests/fakes.py`:
    - `FakeSource(name, results: Callable[[SourceRequest], SourceResult | Exception], delay_s=0.0)`, que guarda `calls: list[SourceRequest]`. Si `results` devuelve una excepción, `search` la lanza.
  - En `tests/contract/cases.py`:
    - `ContractCase(id, source, request, expected_status)`.
    - `CONTRACT_CASES: list[ContractCase]`.

- [ ] **Step 1: Escribir los tests que fallan**

```python
REQ = SourceRequest(
    origin="SCL",
    destination="MAD",
    depart_from=date(2027, 3, 1),
    depart_to=date(2027, 5, 31),
    nights_min=14,
    nights_max=21,
    adults=1,
    allow_separate_tickets=True,
)


async def test_unexpected_exception_becomes_error(tmp_path):
    src = FakeSource("fake", lambda r: ValueError("x"))
    r = await run_safely(
        src, REQ, timeout_s=1, pauses=PauseRegistry(tmp_path / "p.json", CLOCK), clock=CLOCK
    )
    assert (r.status, r.detail) == ("error", "Error inesperado (ValueError)")


async def test_timeout(tmp_path):
    src = FakeSource("slow", lambda r: SourceResult(source="slow", status="ok"), delay_s=5)
    r = await run_safely(
        src, REQ, timeout_s=1, pauses=PauseRegistry(tmp_path / "p.json", CLOCK), clock=CLOCK
    )
    assert (r.status, r.detail) == ("timeout", "No respondió en 1 s")


async def test_blocked_pauses_for_60_minutes_and_persists(tmp_path):
    pauses = PauseRegistry(tmp_path / "p.json", CLOCK)
    r = await run_safely(
        FakeSource("g", lambda r: SourceBlocked("429")),
        REQ,
        timeout_s=1,
        pauses=pauses,
        clock=CLOCK,
    )
    assert (r.status, r.detail) == ("paused", "En pausa hasta las 13:00: 429")
    assert PauseRegistry(tmp_path / "p.json", CLOCK).active_pause("g") is not None
    later = fixed_clock("2026-11-09T16:01:00+00:00")
    assert PauseRegistry(tmp_path / "p.json", later).active_pause("g") is None
```

```python
@pytest.mark.parametrize("case", CONTRACT_CASES, ids=lambda c: c.id)
async def test_source_contract(case, tmp_path):
    result = await run_safely(
        case.source,
        case.request,
        timeout_s=2,
        pauses=PauseRegistry(tmp_path / "p.json", CLOCK),
        clock=CLOCK,
    )
    assert result.status == case.expected_status
    for it in result.itineraries:
        assert it.offers and all(o.source == case.source.name for o in it.offers)
        assert all(o.price_usd > 0 and o.booking_url.startswith("https://") for o in it.offers)
        for leg in filter(None, (it.outbound, it.inbound)):
            assert all(len(s.from_airport) == 3 and s.from_airport.isupper() for s in leg.segments)
```

Para empezar, `CONTRACT_CASES` contiene cuatro fuentes falsas: ok, excepción, bloqueada y lenta. Las Tareas 6 y 7 le añaden casos.

- [ ] **Step 2: Comprobar que fallan**

Run: `uv run pytest tests/sources tests/contract -q`
Expected: FAIL.

- [ ] **Step 3: Implementar `base.py` y los dobles de prueba**

- [ ] **Step 4: Comprobar que todo pasa**

Run: `uv run fly check --fast`
Expected: todo `✓`.

- [ ] **Step 5: Commit**

`git add -A && git commit -m "feat(sources): source protocol, pause registry and safe runner with contract suite"`

---

### Task 6: Fuente Kiwi

**Files:**
- Create: `src/flytrip/sources/kiwi.py`, `src/flytrip/devtools/record.py` (subcomando `record kiwi`), `docs/sources/kiwi.md`
- Create: fixtures en `tests/fixtures/kiwi/`:
  - Grabados: `madrid_scl_return.sse`, `madrid_mdz_return_all.sse`, `madrid_mdz_return_protected.sse`, `madrid_eze_return.sse`, `madrid_scl_return_2adults.sse`.
  - Escritos a mano: `synthetic_two_segments.sse`, `synthetic_text_only.sse`, `tool_error.sse`, `wrong_currency.sse`, `empty.sse`.
- Modify: `src/flytrip/cli.py`, para añadir `fly record`.
- Modify: `tests/contract/cases.py`, para añadir los casos de Kiwi.
- Test: `tests/sources/test_kiwi.py`

**Interfaces:**
- Consumes: `SourceRequest`, `SourceResult`, `SourceBlocked` (Tarea 5), además de `build_leg`, `itinerary_id` y `normalize_flight_number` (Tarea 3).
- Produces:
  - Las constantes `KIWI_URL = "https://mcp.kiwi.com"`, `KIWI_MAX_WINDOW_DAYS: int` y `KIWI_PRICE_IS_TOTAL: bool`. Las dos últimas se fijan en el Step 1.
  - `split_window(start: date, end: date, max_days: int) -> list[tuple[date, date]]`.
  - `build_arguments(request: SourceRequest) -> dict[str, object]`.
  - `build_rpc_body(arguments: dict[str, object], request_id: int = 1) -> dict[str, object]`, que arma una llamada `tools/call` a `search-flight`.
  - `parse_sse(text: str) -> dict[str, Any]`. Toma el último `data:` que contenga `result` o `error`; si el cuerpo es JSON plano, lo acepta tal cual.
  - `normalize(rpc: dict[str, Any], *, origin: str, adults: int, fetched_at: datetime) -> list[Itinerary]`. Lee `structuredContent` o, si no está, `content[0].text`. Se tolera un campo `"error": null`, pero:
    - `isError` o un error que no sea null lanzan `KiwiToolError`.
    - Si la moneda no es `USD`, lanza `KiwiProtocolError("moneda inesperada: …")`.
  - `class KiwiSource`:
    - `name = "kiwi"`.
    - `__init__(self, client: httpx.AsyncClient, url: str = KIWI_URL, clock=utc_now)`.
    - `async search(self, request) -> SourceResult`. Hace una consulta por cada tramo de `split_window` y devuelve `fetches` igual al número de tramos. Las respuestas se tratan así:
      - HTTP 429 → `SourceBlocked("Kiwi limitó las consultas (429)")`.
      - Otro error HTTP → `status="error"` con `detail` `"Kiwi respondió {código}"`.
      - `KiwiToolError` → `"Kiwi: {mensaje}"`.
      - `KiwiProtocolError` → `"Kiwi: {mensaje}"`.
  - El comando `fly record kiwi <escenario> --origen SCL --destino MAD --desde 2027-03-01 --hasta 2027-05-31 [--noches 14-21] [--adultos N] [--sin-separados]` guarda el SSE crudo en `tests/fixtures/kiwi/<escenario>.sse`.

- [ ] **Step 1: Verificación en vivo, que no es un test**

Consultar Kiwi con un script desechable o con `fly record` y anotar tres respuestas en `docs/sources/kiwi.md`:
- a) El rango más amplio que acepta `departureDate..departureDateTo`. Probar 92, 180 y 365 días. El resultado fija `KIWI_MAX_WINDOW_DAYS`.
- b) El comportamiento cuando se omite `allow_self_transfer`, comparado con `true` y con `false`, para MDZ→MAD.
- c) Si `price` con `adults=2` es el total o el precio por persona. El resultado fija `KIWI_PRICE_IS_TOTAL`. Si es por persona, `normalize` multiplica por `adults`.

- [ ] **Step 2: Grabar los fixtures**

Grabar con `fly record kiwi`, siempre con destino MAD, salida entre el 1/3 y el 31/5/2027 y de 14 a 21 noches:
- `madrid_scl_return`: desde SCL.
- `madrid_mdz_return_all`: desde MDZ, con pasajes separados.
- `madrid_mdz_return_protected`: desde MDZ, con `--sin-separados`.
- `madrid_eze_return`: desde EZE.
- `madrid_scl_return_2adults`: desde SCL, con `--adultos 2`.

Escribir a mano los sintéticos, con el formato SSE real de Kiwi:
- `synthetic_two_segments.sse` usa `structuredContent` con un solo itinerario:
  - Precio 934.0 USD, `bookingUrl` `https://kiwi.com/u/abc123`, equipaje `1/1/0`.
  - Ida: MDZ→SCL con JA 7104 (2027-03-10, de 06:00 a 07:00, 3600 s) y SCL→MAD con IB 6830 (de 2027-03-10T23:50 a 2027-03-11T16:40, 45600 s). `durationSeconds` del tramo: 109800.
  - Vuelta: MAD→SCL con IB 6831 (de 2027-03-25T23:55 a 2027-03-26T08:45, 45000 s) y SCL→MDZ con H2 1430 (2027-03-26, de 14:00 a 15:00, 3600 s). `durationSeconds` del tramo: 67500.
- `synthetic_text_only.sse`: el mismo itinerario, pero solo en `content[0].text`.
- `tool_error.sse`: `isError: true` con el texto `"Invalid date"`.
- `wrong_currency.sse`: `currency: "EUR"`.
- `empty.sse`: `itineraries: []` y `resultsCount: 0`.

- [ ] **Step 3: Escribir los tests que fallan**

```python
REQ = SourceRequest(
    origin="SCL",
    destination="MAD",
    depart_from=date(2027, 3, 1),
    depart_to=date(2027, 5, 31),
    nights_min=14,
    nights_max=21,
    adults=1,
    allow_separate_tickets=False,
)


def test_build_arguments_return_trip():
    assert build_arguments(REQ) == {
        "flyFrom": "SCL",
        "flyTo": "MAD",
        "departureDate": "01/03/2027",
        "departureDateTo": "31/05/2027",
        "adults": 1,
        "currency": "USD",
        "locale": "es",
        "sort": "price",
        "allow_self_transfer": False,
        "nights_in_dst_from": 14,
        "nights_in_dst_to": 21,
    }


def test_build_arguments_oneway_has_no_nights():
    assert "nights_in_dst_from" not in build_arguments(
        REQ.model_copy(update={"nights_min": None, "nights_max": None})
    )


def test_split_window_92_days():
    assert split_window(date(2027, 1, 1), date(2027, 12, 31), 92) == [
        (date(2027, 1, 1), date(2027, 4, 2)),
        (date(2027, 4, 3), date(2027, 7, 3)),
        (date(2027, 7, 4), date(2027, 10, 3)),
        (date(2027, 10, 4), date(2027, 12, 31)),
    ]


@pytest.mark.parametrize("name", ["synthetic_two_segments.sse", "synthetic_text_only.sse"])
def test_normalize_synthetic(name):
    [it] = normalize(parse_sse(fixture("kiwi", name)), origin="MDZ", adults=1, fetched_at=FETCHED)
    assert it.price_usd == Decimal("934") and it.trip_type == "return" and it.destination == "MAD"
    assert [(s.carrier_code, s.flight_number) for s in it.outbound.segments] == [
        ("JA", "7104"),
        ("IB", "6830"),
    ]
    assert it.outbound.layovers[0].minutes == 1010 and it.outbound.duration_minutes == 1830
    assert it.inbound.layovers[0].minutes == 315 and it.inbound.duration_minutes == 1125
    assert it.baggage == Baggage(personal_item=1, cabin_bag=1, checked_bag=0)
    assert it.offers[0].booking_url == "https://kiwi.com/u/abc123" and it.separate_tickets is None


RECORDED_KIWI_FIXTURES = [
    ("madrid_scl_return.sse", "SCL"),
    ("madrid_mdz_return_all.sse", "MDZ"),
    ("madrid_mdz_return_protected.sse", "MDZ"),
    ("madrid_eze_return.sse", "EZE"),
]


@pytest.mark.parametrize("name,origin", RECORDED_KIWI_FIXTURES)
def test_recorded_fixtures_normalize(name, origin):
    rpc = parse_sse(fixture("kiwi", name))
    data = rpc["result"]["structuredContent"]
    itins = normalize(rpc, origin=origin, adults=1, fetched_at=FETCHED)
    assert len(itins) == data["resultsCount"] and all(i.price_usd > 0 for i in itins)


def test_two_adults_price_is_total():
    rpc = parse_sse(fixture("kiwi", "madrid_scl_return_2adults.sse"))
    raw = Decimal(str(rpc["result"]["structuredContent"]["itineraries"][0]["price"]))
    [first, *_] = normalize(rpc, origin="SCL", adults=2, fetched_at=FETCHED)
    assert first.price_usd == (raw if KIWI_PRICE_IS_TOTAL else raw * 2)


@respx.mock
async def test_tool_error_and_wrong_currency_are_errors():
    respx.post(KIWI_URL).mock(
        side_effect=[
            httpx.Response(200, text=fixture("kiwi", "tool_error.sse")),
            httpx.Response(200, text=fixture("kiwi", "wrong_currency.sse")),
        ]
    )
    async with httpx.AsyncClient() as c:
        src = KiwiSource(c, clock=CLOCK)
        assert (await src.search(REQ)).detail == "Kiwi: Invalid date"
        assert "moneda inesperada" in (await src.search(REQ)).detail


@respx.mock
async def test_429_pauses_kiwi(tmp_path):
    respx.post(KIWI_URL).mock(return_value=httpx.Response(429))
    pauses = PauseRegistry(tmp_path / "p.json", CLOCK)
    async with httpx.AsyncClient() as c:
        r = await run_safely(
            KiwiSource(c, clock=CLOCK), REQ, timeout_s=5, pauses=pauses, clock=CLOCK
        )
    assert r.status == "paused" and pauses.active_pause("kiwi") is not None
```

Añadir a `CONTRACT_CASES` un caso por cada fixture grabado (con `expected_status="ok"`) y un caso para `empty.sse` (también `"ok"`, sin itinerarios). Esos casos usan `KiwiSource` con un `httpx.AsyncClient` simulado por respx.

- [ ] **Step 4: Comprobar que fallan**

Run: `uv run pytest tests/sources/test_kiwi.py tests/contract -q`
Expected: FAIL.

- [ ] **Step 5: Implementar `kiwi.py` y `record kiwi`**

Además, escribir `docs/sources/kiwi.md`: los parámetros que se usan, los resultados del Step 1, los límites, las rarezas (`"error": null`, que devuelve unos 15 resultados) y cómo regrabar los fixtures.

- [ ] **Step 6: Comprobar que todo pasa**

Run: `uv run fly check --fast`
Expected: todo `✓`.

- [ ] **Step 7: Commit**

`git add -A && git commit -m "feat(sources): Kiwi MCP source with recorded fixtures"`

---

### Task 7: Fuente Google Flights (`fli`)

**Files:**
- Create: `src/flytrip/sources/google_flights.py`, `docs/sources/google-flights.md`
- Create: fixtures en `tests/fixtures/google/`:
  - Grabados: `madrid_scl_rt.json`, `madrid_eze_oneway.json`, `madrid_scl_rt_2adults.json`.
  - Sintéticos: `synthetic_oneway.json`, `synthetic_rt.json`, `wrong_currency.json`.
- Modify: `src/flytrip/devtools/record.py` (subcomando `record google`) y `tests/contract/cases.py`
- Modify: `tests/fakes.py`, para añadir:
  - `FakeFli(results=None, raises=None)`, que cumple `FliClient`.
  - `load_fli(name) -> list[FlightResult | tuple[FlightResult, ...]]`, que valida el JSON de `tests/fixtures/google/` con `FlightResult.model_validate`.
- Test: `tests/sources/test_google_flights.py`

**Interfaces:**
- Consumes: lo mismo que la Tarea 6, además de `fli.models` (`FlightSearchFilters`, `FlightSegment`, `PassengerInfo`, `SeatType`, `MaxStops`, `SortBy`, `TripType`, `Airport` y `FlightResult`) y `fli.search` (`SearchFlights`, `SearchClientError`, `SearchTimeoutError`, `SearchConnectionError` y `SearchHTTPError`, este último con `status_code`). `SearchParseError` se importa desde `fli.search.flights`.
- Produces:
  - Las constantes `GOOGLE_FETCH_BUDGET = 12`, `GOOGLE_MAX_CONCURRENCY = 3` y `GOOGLE_RETURN_PAIR_COST = 2`.
  - `class FliClient(Protocol)`, con `def search(self, filters: FlightSearchFilters, *, top_n: int, currency: str, language: str, country: str) -> list[FlightResult | tuple[FlightResult, ...]] | None`. La implementación real envuelve `SearchFlights().search`; en los tests, un doble carga los fixtures con `FlightResult.model_validate`.
  - `build_filters(request: SourceRequest) -> FlightSearchFilters`. Exige que `depart_from == depart_to`, y que `nights_min == nights_max` o que ambos sean `None`; si no, lanza `ValueError("Google solo confirma fechas exactas")`. Si el destino no está en `Airport`, lanza `ValueError("El destino no es un aeropuerto: …")`. Configuración:
    - Tipo de viaje: `ROUND_TRIP` si hay noches, `ONE_WAY` si no.
    - Clase `ECONOMY`, escalas `MaxStops.ANY` y orden `SortBy.CHEAPEST`.
    - `PassengerInfo(adults=request.adults)`.
  - `google_search_url(origin: str, destination: str, depart: date, return_date: date | None) -> str`.
  - `normalize_results(raw, *, origin: str, destination: str, adults: int, fetched_at: datetime) -> list[Itinerary]`. Reglas:
    - El precio de ida y vuelta se lee del elemento de la tupla que indique el Step 1.
    - Un resultado con `price is None` se descarta.
    - Si `currency` no es `None` ni `"USD"`, lanza `GoogleCurrencyError`.
    - `self_transfer` pasa a `separate_tickets`.
    - `baggage` queda en `None`.
    - Cada segmento sale de un `FlightLeg`: `carrier_code = leg.airline.name`, `carrier_name = leg.airline.value` y aeropuertos `.name`.
  - `class GoogleFlightsSource`:
    - `name = "google"`.
    - `__init__(self, client: FliClient, clock=utc_now, max_concurrency: int = GOOGLE_MAX_CONCURRENCY)`.
    - `async search(self, request) -> SourceResult` confirma un par por cada `request`. Llama a `fli`, que es síncrono, con `asyncio.to_thread`, bajo un semáforo compartido. Devuelve `fetches` igual a 1 en solo ida y a 2 en ida y vuelta.
    - Las excepciones se convierten así:
      - `SearchHTTPError` con código 429 → `SourceBlocked("Google Flights limitó las consultas (429)")`.
      - Otro `SearchHTTPError` → error con `"Google respondió {código}"`.
      - `SearchTimeoutError` → `status="timeout"`.
      - `SearchConnectionError` → error con `"Sin conexión con Google Flights"`.
      - `SearchParseError` → error con `"Google cambió el formato de la página"`.
      - `GoogleCurrencyError` → error con `"Google devolvió precios en {moneda} (moneda inesperada)"`.
    - Siempre llama con `currency="USD"`, `language="es"`, `country="AR"` y `top_n=1`.

- [ ] **Step 1: Verificación en vivo, que no es un test**

Grabar con `fly record google` y anotar en `docs/sources/google-flights.md`:
- a) Si los precios llegan en USD con `currency="USD"`.
- b) Qué elemento de la tupla de ida y vuelta trae el precio total; se espera el último.
- c) Si `departure_datetime` viene en hora local y sin zona horaria.
- d) Si el precio con `adults=2` es el total. Fijar la constante `GOOGLE_PRICE_IS_TOTAL`.

- [ ] **Step 2: Grabar los fixtures**

Los grabados se vuelcan con `model_dump(mode="json")`:
- `madrid_scl_rt`: SCL→MAD, salida 2027-03-19, 16 noches.
- `madrid_eze_oneway`: EZE→MAD, 2027-03-07.
- `madrid_scl_rt_2adults`: como `madrid_scl_rt`, con 2 adultos.

Los sintéticos se generan construyendo `FlightResult` en Python y volcándolos de la misma manera. **No se escriben a mano**, porque los enums de `fli` se serializan por su nombre largo:
- `synthetic_oneway`: EZE→MAD con AR 1132, de 2027-03-19T13:35 a 2027-03-20T06:05, 750 min, 650.0 USD y `self_transfer=False`.
- `synthetic_rt`: una ida con precio 600 y una vuelta con precio 980.
- `wrong_currency`: con `currency="EUR"`.

- [ ] **Step 3: Escribir los tests que fallan**

```python
PAIR = SourceRequest(
    origin="SCL",
    destination="MAD",
    depart_from=date(2027, 3, 19),
    depart_to=date(2027, 3, 19),
    nights_min=16,
    nights_max=16,
    adults=1,
    allow_separate_tickets=True,
)


def test_build_filters_round_trip():
    f = build_filters(PAIR)
    assert f.trip_type == TripType.ROUND_TRIP and f.sort_by == SortBy.CHEAPEST
    assert [s.travel_date for s in f.flight_segments] == ["2027-03-19", "2027-04-04"]
    assert f.passenger_info.adults == 1


def test_build_filters_rejects_windows_and_non_airports():
    with pytest.raises(ValueError, match="fechas exactas"):
        build_filters(PAIR.model_copy(update={"depart_to": date(2027, 3, 20)}))
    with pytest.raises(ValueError, match="no es un aeropuerto"):
        build_filters(PAIR.model_copy(update={"destination": "Madrid"}))


def test_google_search_url():
    assert google_search_url("SCL", "MAD", date(2027, 3, 19), date(2027, 4, 4)) == (
        "https://www.google.com/travel/flights?q=Flights%20to%20MAD%20from%20SCL%20on%202027-03-19"
        "%20through%202027-04-04&curr=USD&hl=es"
    )
    assert google_search_url("EZE", "MAD", date(2027, 3, 7), None).endswith(
        "on%202027-03-07&curr=USD&hl=es"
    )


def test_normalize_synthetic_oneway():
    [it] = normalize_results(
        load_fli("synthetic_oneway.json"),
        origin="EZE",
        destination="MAD",
        adults=1,
        fetched_at=FETCHED,
    )
    assert (
        it.price_usd == Decimal("650") and it.trip_type == "oneway" and it.separate_tickets is False
    )
    assert [(s.carrier_code, s.flight_number) for s in it.outbound.segments] == [("AR", "1132")]
    assert it.offers[0].source == "google" and it.baggage is None


def test_round_trip_price_comes_from_verified_element():
    [it] = normalize_results(
        load_fli("synthetic_rt.json"), origin="SCL", destination="MAD", adults=1, fetched_at=FETCHED
    )
    assert it.price_usd == Decimal("980")  # ajustar al elemento verificado en el Step 1


async def test_wrong_currency_is_error():
    r = await GoogleFlightsSource(FakeFli(load_fli("wrong_currency.json")), clock=CLOCK).search(
        PAIR
    )
    assert r.status == "error" and "moneda inesperada" in r.detail and r.itineraries == ()


async def test_429_pauses_google(tmp_path):
    pauses = PauseRegistry(tmp_path / "p.json", CLOCK)
    src = GoogleFlightsSource(FakeFli(raises=SearchHTTPError("x", status_code=429)), clock=CLOCK)
    assert (await run_safely(src, PAIR, timeout_s=5, pauses=pauses, clock=CLOCK)).status == "paused"


async def test_parse_error_says_format_changed():
    src = GoogleFlightsSource(FakeFli(raises=SearchParseError("bad")), clock=CLOCK)
    assert (await src.search(PAIR)).detail == "Google cambió el formato de la página"


def test_two_adults_price_is_total():
    raw = load_fli("madrid_scl_rt_2adults.json")
    [first, *_] = normalize_results(
        raw, origin="SCL", destination="MAD", adults=2, fetched_at=FETCHED
    )
    expected = verified_total_price(raw[0])  # helper del test: lee el elemento verificado
    assert first.price_usd == (expected if GOOGLE_PRICE_IS_TOTAL else expected * 2)
```

Añadir a `CONTRACT_CASES` los fixtures grabados (`"ok"`), `wrong_currency` (`"error"`) y el 429 (`"paused"`).

- [ ] **Step 4: Comprobar que fallan**

Run: `uv run pytest tests/sources/test_google_flights.py tests/contract -q`
Expected: FAIL.

- [ ] **Step 5: Implementar `google_flights.py` y `record google`**

Además, escribir `docs/sources/google-flights.md`, con los resultados del Step 1, el costo en descargas, los riesgos y cómo regrabar.

- [ ] **Step 6: Comprobar que todo pasa**

Run: `uv run fly check --fast`
Expected: todo `✓`.

- [ ] **Step 7: Commit**

`git add -A && git commit -m "feat(sources): Google Flights source via fli with currency and block handling"`

---

### Task 8: Ajustes locales y rutas de datos

**Files:**
- Create: `src/flytrip/engine/paths.py`, `src/flytrip/engine/settings.py`
- Test: `tests/engine/test_settings.py`

**Interfaces:**
- Consumes: `TransferCost` (Tarea 3).
- Produces:
  - `home_dir() -> Path`: la variable de entorno `FLYTRIP_HOME` o, si no está, `Path.cwd()`.
  - `data_dir(home: Path) -> Path`: `home/.flytrip`, creado si no existe.
  - `logs_dir(home: Path) -> Path`: `home/logs`, creado si no existe.
  - `Settings` (pydantic) con estos defaults:
    - `default_origins = ("MDZ", "SCL", "EZE")` y `home_city = "Mendoza"`.
    - `transfers: dict[str, TransferCost | None] = {"SCL": None, "EZE": None}`.
    - `adults = 1`, `usd_per_hour = Decimal("10")` y `allow_separate_tickets = True`.
  - `SettingsStore(path: Path)`:
    - `load() -> Settings`: devuelve los defaults si el archivo no existe o es inválido, y en ese caso escribe un warning en el log.
    - `save(settings: Settings) -> None`: escritura atómica (archivo temporal más `replace`).

- [ ] **Step 1: Escribir los tests que fallan**

```python
def test_defaults_when_missing(tmp_path):
    s = SettingsStore(tmp_path / "settings.json").load()
    assert s.default_origins == ("MDZ", "SCL", "EZE") and s.usd_per_hour == Decimal("10")
    assert s.transfers == {"SCL": None, "EZE": None} and s.adults == 1


def test_roundtrip(tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    store.save(Settings(transfers={"SCL": T("80", "7"), "EZE": None}))
    assert store.load().transfers["SCL"] == T("80", "7")


def test_invalid_file_falls_back_to_defaults(tmp_path):
    (tmp_path / "settings.json").write_text("{nope", encoding="utf-8")
    assert SettingsStore(tmp_path / "settings.json").load() == Settings()


def test_negative_transfer_is_rejected():
    with pytest.raises(ValidationError):
        TransferCost(cost_usd_roundtrip=Decimal("-1"), hours_one_way=Decimal("1"))
```

- [ ] **Step 2: Comprobar que fallan**

Run: `uv run pytest tests/engine/test_settings.py -q`
Expected: FAIL.

- [ ] **Step 3: Implementar `paths.py` y `settings.py`**

- [ ] **Step 4: Comprobar que todo pasa**

Run: `uv run fly check --fast`
Expected: todo `✓`.

- [ ] **Step 5: Commit**

`git add -A && git commit -m "feat(engine): local settings store and data paths"`

---

### Task 9: Motor de búsqueda (candidatos, caché y eventos)

**Files:**
- Create: `src/flytrip/core/candidates.py`, `src/flytrip/engine/cache.py`, `src/flytrip/engine/search.py`
- Create: `tests/engine/conftest.py`, con los fixtures `engine`, `slow_engine`, `engine_without_eze_results`, `pauses` y `clock` (adelantable con `clock.advance(minutes=…)`), además de `async def collect(aiter) -> list`
- Modify: `tests/factories.py`, para añadir `itin_on(origin: str, depart_iso: str, return_iso: str, price: int) -> Itinerary`, un itinerario de un segmento por tramo hasta MAD
- Test: `tests/core/test_candidates.py`, `tests/engine/test_cache.py`, `tests/engine/test_search.py`

**Interfaces:**
- Consumes: todo lo de las Tareas 3, 4, 5 y 8, más `KIWI_MAX_WINDOW_DAYS` (Tarea 6) y `GOOGLE_FETCH_BUDGET` (Tarea 7).
- Produces:
  - `DatePair(origin: str, destination_airport: str, depart: date, return_date: date | None)`, una dataclass frozen, con la propiedad `cost -> int` (2 en ida y vuelta, 1 en solo ida).
  - `select_google_candidates(kiwi_itineraries: Sequence[Itinerary], query: SearchQuery, fetch_budget: int = 12) -> list[DatePair]`. Reglas:
    - Para cada origen, en el orden de `query.origins`, se toman los `(destino real, salida, regreso)` distintos, ordenados por precio. Si dos tienen el mismo precio, se respeta el orden en que llegaron (orden estable). El destino real es `outbound.segments[-1].to_airport`.
    - Los orígenes se recorren por turnos. La selección se detiene cuando el siguiente par no cabe en el presupuesto.
    - Si un origen no tiene itinerarios de Kiwi y `query.destination` son 3 letras, se usan 4 salidas de respaldo: `depart_from + round(k × días_del_rango / 5)` para k de 1 a 4, con regreso en `salida + nights_min`.
  - `SearchCache(path: Path, clock, ttl_minutes: int = 30)`:
    - `get(key: str) -> tuple[str, int] | None` devuelve el JSON y su antigüedad en minutos.
    - `put(key: str, payload_json: str) -> None`.
    - Guarda en SQLite, en la tabla `searches(key TEXT PRIMARY KEY, stored_at TEXT, payload TEXT)`.
  - `SourceStatus(source: str, state: Literal["pending", "running", "ok", "paused", "error", "timeout", "skipped"], detail: str = "", latency_ms: int | None = None, count: int = 0)`.
  - `SearchSnapshot(query: SearchQuery, itineraries: tuple[Itinerary, ...], best_per_origin: dict[str, Itinerary | None], best_balance: Itinerary | None, statuses: dict[str, SourceStatus], completed_at: datetime, from_cache: bool = False, cache_age_minutes: int | None = None)`.
  - Los eventos `StatusEvent(status: SourceStatus)` y `SnapshotEvent(snapshot: SearchSnapshot, final: bool)`.
  - `class SearchEngine`:
    - `__init__(self, *, kiwi: Source, google: Source, settings: Settings, cache: SearchCache, pauses: PauseRegistry, clock, kiwi_timeout_s: float = 20, google_timeout_s: float = 40, hard_timeout_s: float = 60)`.
    - `max_window_days -> int`: `min(365, 4 × KIWI_MAX_WINDOW_DAYS)`.
    - Expone las fuentes como `self.kiwi` y `self.google`, y los ajustes como `self.settings`.
    - `async def run(self, query: SearchQuery, *, use_cache: bool = True) -> AsyncIterator[StatusEvent | SnapshotEvent]`.
- Flujo de `run`, siguiendo la sección 5.1 del spec:
  1. Si hay caché, emite un único `SnapshotEvent(final=True)` con `from_cache=True` y termina.
  2. Emite el estado "running" de Kiwi y "pending" de Google.
  3. Por cada origen consulta Kiwi en el modo protegido y, si `allow_separate_tickets` es verdadero, también en el modo "todos".
  4. Aplica `mark_separate_tickets`, después los traslados de los ajustes y después el orden. Emite el estado de Kiwi y un `SnapshotEvent(final=False)`.
  5. Si Google está en pausa, emite "paused". Si no hay candidatos, emite "skipped" con el detalle "Sin fechas para confirmar". Si los hay, confirma los pares (como máximo 3 a la vez, con el tiempo total de `google_timeout_s`), aplica `merge_duplicates` y, si no se permiten pasajes separados, descarta los itinerarios con `separate_tickets=True`.
  6. Emite el estado de Google y el `SnapshotEvent(final=True)`. Guarda en caché solo si alguna fuente terminó en "ok".
  7. Si se supera `hard_timeout_s`, cancela lo pendiente, marca esas fuentes como "timeout" y emite el snapshot final.
  8. Escribe un log `logging.getLogger("flytrip.search").info("source_done", extra={...})` por cada fuente, con los campos `source`, `state`, `latency_ms`, `count` y `query_key`.

- [ ] **Step 1: Escribir los tests que fallan**

```python
def test_round_robin_respects_budget_for_return_trips():
    kiwi = [
        itin_on("SCL", "2027-03-19", "2027-04-04", 758),
        itin_on("SCL", "2027-03-11", "2027-03-31", 763),
        itin_on("MDZ", "2027-03-10", "2027-03-25", 934),
        itin_on("MDZ", "2027-03-09", "2027-03-24", 949),
        itin_on("EZE", "2027-03-07", "2027-03-26", 1021),
        itin_on("EZE", "2027-04-18", "2027-05-05", 1038),
        itin_on("SCL", "2027-03-08", "2027-03-24", 763),
    ]
    pairs = select_google_candidates(kiwi, q(), fetch_budget=12)
    assert [(p.origin, p.depart.isoformat()) for p in pairs] == [
        ("MDZ", "2027-03-10"),
        ("SCL", "2027-03-19"),
        ("EZE", "2027-03-07"),
        ("MDZ", "2027-03-09"),
        ("SCL", "2027-03-11"),
        ("EZE", "2027-04-18"),
    ]


def test_fallback_dates_when_origin_has_no_kiwi_results():
    pairs = select_google_candidates([], q(origins=("EZE",)), fetch_budget=12)
    assert [p.depart.isoformat() for p in pairs] == [
        "2027-03-19",
        "2027-04-06",
        "2027-04-25",
        "2027-05-13",
    ]
    assert all(p.return_date == p.depart + timedelta(days=14) for p in pairs)


def test_no_fallback_for_city_names():
    assert select_google_candidates([], q(destination="Madrid"), fetch_budget=12) == []
```

```python
async def test_kiwi_snapshot_arrives_before_google_finishes(engine):  # google fake con delay 0.3 s
    events = [e async for e in engine.run(q())]
    first_partial = next(
        i for i, e in enumerate(events) if isinstance(e, SnapshotEvent) and not e.final
    )
    google_done = next(
        i
        for i, e in enumerate(events)
        if isinstance(e, StatusEvent)
        and e.status.source == "google"
        and e.status.state not in {"pending", "running"}
    )
    assert (
        first_partial < google_done and isinstance(events[-1], SnapshotEvent) and events[-1].final
    )


async def test_separate_tickets_from_two_kiwi_modes(engine):
    final = (await collect(engine.run(q())))[-1].snapshot
    assert {i.id: i.separate_tickets for i in final.itineraries if i.id in {"SELF", "PROT"}} == {
        "SELF": True,
        "PROT": False,
    }


async def test_disallowing_separate_tickets(engine):
    final = (await collect(engine.run(q(allow_separate_tickets=False))))[-1].snapshot
    assert (
        all(r.allow_separate_tickets is False for r in engine.kiwi.calls)
        and len(engine.kiwi.calls) == 3
    )
    assert all(i.separate_tickets is not True for i in final.itineraries)


async def test_google_calls_stay_within_budget(engine):
    await collect(engine.run(q()))
    assert sum(2 if r.nights_min else 1 for r in engine.google.calls) <= 12


async def test_paused_google_is_not_called(engine, pauses):
    pauses.pause("google", 60, "429")
    final = (await collect(engine.run(q())))[-1].snapshot
    assert engine.google.calls == [] and final.statuses["google"].state == "paused"


async def test_hard_timeout_marks_pending_sources(
    slow_engine,
):  # hard_timeout_s=0.2, kiwi con delay 5 s
    final = (await collect(slow_engine.run(q())))[-1].snapshot
    assert final.statuses["kiwi"].state == "timeout"


async def test_cache_hit_and_expiry(engine, clock):
    await collect(engine.run(q()))
    calls = len(engine.kiwi.calls)
    clock.advance(minutes=10)
    [only] = await collect(engine.run(q()))
    assert (
        only.snapshot.from_cache
        and only.snapshot.cache_age_minutes == 10
        and len(engine.kiwi.calls) == calls
    )
    clock.advance(minutes=21)
    await collect(engine.run(q()))
    assert len(engine.kiwi.calls) > calls


async def test_transfers_and_empty_origin(engine_without_eze_results):
    final = (await collect(engine_without_eze_results.run(q())))[-1].snapshot
    assert final.best_per_origin["EZE"] is None
    assert final.best_per_origin["SCL"].total_from_home_usd == Decimal(
        "838"
    )  # ajustes: SCL = T("80", "7")


async def test_logs_one_record_per_source(engine, caplog):
    caplog.set_level("INFO", logger="flytrip.search")
    await collect(engine.run(q()))
    assert sorted(r.source for r in caplog.records if r.msg == "source_done") == ["google", "kiwi"]
```

Comportamiento de las fuentes falsas en `tests/engine/conftest.py`:
- **Kiwi**:
  - MDZ en modo "todos" devuelve `[SELF (934), PROT (949)]`, y en modo protegido, `[PROT]`.
  - SCL devuelve `[A (758)]` y EZE, `[C (1021)]`.
  - `engine_without_eze_results` devuelve `[]` para EZE.
- **Google**: tarda 0,3 s y devuelve un itinerario propio de 999 USD por cada par, con un `id` distinto.
- **Ajustes**: los traslados son `{"SCL": T("80", "7"), "EZE": T("200", "2")}`.
- **`slow_engine`**: usa `hard_timeout_s=0.2`, y su Kiwi tarda 5 s.

- [ ] **Step 2: Comprobar que fallan**

Run: `uv run pytest tests/core/test_candidates.py tests/engine -q`
Expected: FAIL.

- [ ] **Step 3: Implementar `candidates.py`, `cache.py` y `search.py`**

- [ ] **Step 4: Comprobar que todo pasa**

Run: `uv run fly check --fast`
Expected: todo `✓`.

- [ ] **Step 5: Commit**

`git add -A && git commit -m "feat(engine): search orchestration with Google candidates, cache and events"`

---

### Task 10: `fly search`, modo demo y logs a archivo

**Files:**
- Create: `src/flytrip/engine/factory.py`, `src/flytrip/engine/logs.py`, `src/flytrip/devtools/demo.py`, `src/flytrip/web/views.py`
- Modify: `src/flytrip/cli.py` y `tests/fakes.py` (para añadir `StaticEngine` y `SNAPSHOT_A_B_C`)
- Test: `tests/cli/test_search_cli.py`, `tests/web/test_views.py`

**Interfaces:**
- Consumes: `SearchEngine` (Tarea 9) y las fuentes reales (Tareas 6 y 7).
- Produces:
  - `build_engine(home: Path) -> SearchEngine`. Arma `KiwiSource` con un `httpx.AsyncClient` y `GoogleFlightsSource` con el cliente real de `fli`, y usa la caché, las pausas y los ajustes de `data_dir(home)`.
  - `configure_logging(logs_dir: Path) -> None`. Escribe JSON por líneas en `logs/flytrip.jsonl`.
  - `flytrip.devtools.demo.build_demo_engine(home: Path) -> SearchEngine`. Usa fuentes que reproducen los fixtures grabados (Kiwi elige por origen y modo; Google tarda 1,5 s). Sirve para probar la app y hacer demos sin red.
  - El comando `fly search DESTINO --desde AAAA-MM-DD --hasta AAAA-MM-DD [--noches MIN-MAX | --solo-ida] [--origenes MDZ,SCL,EZE] [--adultos N] [--sin-separados] [--json] [--sin-cache] [--demo]`. Muestra:
    - Una tabla rich con las columnas `#`, `Total desde Mendoza`, `Precio`, `Ruta`, `Fechas`, `Escalas`, `Aerolíneas`, `Equipaje`, `Fuentes` y la marca `⚠` en los pasajes separados.
    - Debajo de la tabla, una línea por fuente, como `Kiwi: OK (15 en 2,3 s)`.
    - Con `--json`, imprime el `SearchSnapshot`.
    - Si la consulta no valida, imprime los mensajes en stderr y termina con el código 2.
  - La CLI reconfigura `stdout` y `stderr` a UTF-8 con `errors="replace"` al arrancar.
  - El atributo de módulo `flytrip.cli.engine_factory` vale `build_engine` y los tests lo pueden reemplazar. La CLI valida con `validate_query(query, today_in_mendoza(now), engine.max_window_days)`.
  - En `flytrip/web/views.py`, que comparten la CLI y la web:
    - `format_number(value: Decimal) -> str`: redondea a entero y usa el punto como separador de miles, por ejemplo `"1.021"`.
    - `format_usd(value: Decimal) -> str`: `format_number` seguido de `" USD"`.
    - `format_duration(minutes: int) -> str`: por ejemplo `"13 h 20 min"` o `"45 min"`.
    - `format_short_date(d: date) -> str`: por ejemplo `"19/03"`.
    - `route_label(leg: Leg) -> str`: por ejemplo `"MDZ → SCL → MAD"`.
    - `price_breakdown(it: Itinerary, home_airport: str = "MDZ") -> str`. Devuelve:
      - `"758 + 80 traslado"` si hay traslado.
      - `"934"` si el origen es `home_airport`.
      - `"1.021 + traslado (sin configurar)"` en cualquier otro caso.
    - `status_label(status: SourceStatus) -> str`. Los nombres son "Kiwi" y "Google Flights", y los textos son:
      - `"Kiwi: OK (15 en 2,3 s)"`.
      - `"{nombre}: en pausa — {detail}"`.
      - `"{nombre}: error — {detail}"`.
      - `"{nombre}: sin respuesta — {detail}"`, para un timeout.
      - `"{nombre}: omitida — {detail}"`, para una fuente omitida.
      - `"{nombre}: esperando"`, si está pendiente.
      - `"{nombre}: buscando…"`, mientras busca.
    - `ORIGIN_LABELS = {"MDZ": "Mendoza (todo en avión)", "SCL": "Vía Santiago", "EZE": "Vía Ezeiza"}`. Cualquier otro origen se muestra como `"Desde {código}"`.
  - En `tests/fakes.py`:
    - `StaticEngine(snapshot)`. Su `run` emite un solo `SnapshotEvent(final=True)` y tiene `max_window_days = 365`.
    - `SNAPSHOT_A_B_C`. Contiene los itinerarios A, B y C de la Tarea 4, ordenados por total, con B marcado como pasajes separados y las dos fuentes en "ok".

- [ ] **Step 1: Escribir los tests que fallan**

```python
def test_search_table_shows_totals_and_warning(monkeypatch):
    monkeypatch.setattr(
        cli, "engine_factory", lambda home: StaticEngine(SNAPSHOT_A_B_C)
    )  # snapshot de la Tarea 4
    result = CliRunner().invoke(
        cli.app,
        ["search", "MAD", "--desde", "2027-03-01", "--hasta", "2027-05-31", "--noches", "14-21"],
    )
    assert result.exit_code == 0
    assert "838 USD" in result.output and "758 + 80 traslado" in result.output
    assert "SCL → MAD" in result.output and "⚠" in result.output


def test_search_json_is_a_snapshot(monkeypatch):
    monkeypatch.setattr(cli, "engine_factory", lambda home: StaticEngine(SNAPSHOT_A_B_C))
    out = (
        CliRunner()
        .invoke(
            cli.app,
            [
                "search",
                "MAD",
                "--desde",
                "2027-03-01",
                "--hasta",
                "2027-05-31",
                "--noches",
                "14-21",
                "--json",
            ],
        )
        .output
    )
    assert SearchSnapshot.model_validate_json(out).itineraries[0].id == "A"


def test_invalid_query_exits_2_in_spanish():
    r = CliRunner().invoke(
        cli.app, ["search", "MAD", "--desde", "2027-05-31", "--hasta", "2027-03-01", "--solo-ida"]
    )
    assert r.exit_code == 2 and "La fecha 'hasta' no puede ser anterior a 'desde'." in r.output


def test_search_output_survives_cp1252(tmp_path):
    env = {**os.environ, "PYTHONIOENCODING": "cp1252", "FLYTRIP_HOME": str(tmp_path)}
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "flytrip",
            "search",
            "MAD",
            "--desde",
            "2027-03-01",
            "--hasta",
            "2027-05-31",
            "--noches",
            "14-21",
            "--demo",
        ],
        env=env,
        capture_output=True,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    assert b"UnicodeEncodeError" not in proc.stderr
```

```python
# tests/web/test_views.py
def test_views_formatting():
    assert format_usd(Decimal("1021")) == "1.021 USD" and format_usd(Decimal("757.6")) == "758 USD"
    assert format_duration(800) == "13 h 20 min" and format_duration(45) == "45 min"
    assert format_short_date(date(2027, 3, 19)) == "19/03"


def test_price_breakdown():
    assert (
        price_breakdown(make_itinerary(origin="SCL", price="758", transfer=T("80", "7")))
        == "758 + 80 traslado"
    )
    assert price_breakdown(make_itinerary(origin="MDZ", price="934")) == "934"
    assert (
        price_breakdown(make_itinerary(origin="EZE", price="1021"))
        == "1.021 + traslado (sin configurar)"
    )


def test_status_label():
    assert (
        status_label(SourceStatus(source="kiwi", state="ok", latency_ms=2300, count=15))
        == "Kiwi: OK (15 en 2,3 s)"
    )
    assert (
        status_label(SourceStatus(source="google", state="paused", detail="429"))
        == "Google Flights: en pausa — 429"
    )
```

- [ ] **Step 2: Comprobar que fallan**

Run: `uv run pytest tests/cli/test_search_cli.py tests/web/test_views.py -q`
Expected: FAIL.

- [ ] **Step 3: Implementar `factory.py`, `logs.py`, `demo.py` y el comando `search`**

- [ ] **Step 4: Comprobar que todo pasa**

Run: `uv run fly check --fast`, y después `uv run fly search MAD --desde 2027-03-01 --hasta 2027-05-31 --noches 14-21 --demo`.
Expected: todo `✓`, y la segunda orden imprime la tabla.

- [ ] **Step 5: Commit**

`git add -A && git commit -m "feat(cli): fly search with demo mode and JSONL logs"`

---

### Task 11: Web: búsqueda con resultados en vivo y ajustes

**Files:**
- Create: `src/flytrip/web/app.py`, `tests/web/conftest.py` (con los fixtures `client`, `client_without_eze` y `settings_store`, además del helper `sse_events(client, url) -> list[tuple[str, str]]`, que une las líneas `data:` de cada evento)
- Create: las plantillas `src/flytrip/web/templates/{base,index,_status,_results,settings}.html`
- Create: los archivos estáticos `src/flytrip/web/static/{htmx.min.js,sse.js,app.css}`. HTMX 2.x y su extensión SSE se descargan una vez desde unpkg y se guardan con la versión anotada en un comentario.
- Test: `tests/web/test_app.py`

**Interfaces:**
- Consumes:
  - `SearchEngine`, `SearchSnapshot` y `StatusEvent` (Tarea 9).
  - `SettingsStore` (Tarea 8) y `validate_query` (Tarea 3).
  - Todos los helpers de `flytrip/web/views.py`, `StaticEngine` y `SNAPSHOT_A_B_C` (Tarea 10).
- Produces:
  - `create_app(*, engine_factory: Callable[[], SearchEngine], settings_store: SettingsStore) -> FastAPI`.
  - Las rutas:
    - `GET /`: el formulario, con los valores por defecto de los ajustes.
    - `GET /buscar/stream`: los mismos parámetros que el formulario, respondidos como `text/event-stream`. Por cada `StatusEvent` emite un evento `status` (fragmento `_status.html`). Por cada `SnapshotEvent` emite `status`, con los estados del snapshot, y después `results` (fragmento `_results.html`). Al final emite `done`. Si la consulta no valida, responde 422 con un fragmento HTML que lista los mensajes de `validate_query`.
    - `GET /ajustes` y `POST /ajustes`. Si los datos no validan, se vuelve a mostrar la página con errores en español.
  - Los nombres de los campos del formulario de búsqueda son `destino`, `desde`, `hasta`, `noches_min`, `noches_max`, `solo_ida`, `origenes` (que puede repetirse), `adultos` y `separados`.
  - Los nombres de los campos del formulario de ajustes son `origenes`, `adultos`, `separados`, `usd_por_hora`, `traslado_SCL_costo`, `traslado_SCL_horas`, `traslado_EZE_costo` y `traslado_EZE_horas`. Un traslado con los dos campos vacíos significa "sin configurar".
  - La web valida con `engine.max_window_days`.
  - El botón "Crear aviso con esta búsqueda" no está en este hito: llega con los avisos en el Hito 2.
- Contenido de los resultados, según la sección 5.3 del spec:
  - Una barra de estado por fuente.
  - Las tarjetas "Lo mejor por origen". Una tarjeta sin resultados dice "Sin resultados para este origen".
  - El bloque "Mejor equilibrio".
  - La lista completa, con una fila por itinerario que incluye:
    - El total y su desglose, por ejemplo "758 + 80 traslado". Sin traslado configurado se muestra "+ traslado (sin configurar)".
    - Las fechas y la ruta.
    - Cada escala con su duración y las marcas "pasa la noche" y "cambia de aeropuerto".
    - La duración, las aerolíneas y el equipaje: "mochila", "cabina", "valija" o "desconocido".
    - En los pasajes separados, el aviso "⚠ Pasajes separados: si pierdes la conexión, nadie te recoloca".
    - Un botón "Comprar en Kiwi" o "Comprar en Google Flights" por oferta.
    - La antigüedad del precio, por ejemplo "hace 3 min".

- [ ] **Step 1: Escribir los tests que fallan**

```python
QS = (
    "destino=MAD&desde=2027-03-01&hasta=2027-05-31&noches_min=14&noches_max=21"
    "&origenes=MDZ&origenes=SCL&origenes=EZE&adultos=1&separados=1"
)


def test_index_prefills_defaults(client):
    html = client.get("/").text
    for code in ("MDZ", "SCL", "EZE"):
        assert f'value="{code}" checked' in html
    assert 'name="adultos" value="1"' in html


def test_stream_emits_status_then_results_then_done(client):
    events = sse_events(client, "/buscar/stream?" + QS)  # helper: [(event, data)]
    names = [e for e, _ in events]
    assert names[0] == "status" and "results" in names and names[-1] == "done"


def test_results_show_breakdown_and_separate_warning(client):
    html = "".join(d for e, d in sse_events(client, "/buscar/stream?" + QS) if e == "results")
    assert "758 + 80 traslado" in html and "Pasajes separados" in html and "Comprar en Kiwi" in html


def test_empty_origin_card_shows_message(client_without_eze):
    html = "".join(
        d for e, d in sse_events(client_without_eze, "/buscar/stream?" + QS) if e == "results"
    )
    assert "Vía Ezeiza" in html and "Sin resultados para este origen" in html


def test_validation_error_is_spanish_422(client):
    r = client.get("/buscar/stream?" + QS.replace("desde=2027-03-01", "desde=2020-01-01"))
    assert r.status_code == 422 and "La fecha 'desde' tiene que ser posterior a hoy." in r.text


def test_settings_post_persists_transfers(client, settings_store):
    client.post(
        "/ajustes",
        data={"traslado_SCL_costo": "80", "traslado_SCL_horas": "7", "usd_por_hora": "10"},
    )
    assert settings_store.load().transfers["SCL"] == T("80", "7")
```

Los fixtures de pytest:
- `client` crea la app con `StaticEngine(SNAPSHOT_A_B_C)`.
- `client_without_eze` usa un snapshot sin itinerarios de EZE, con `best_per_origin["EZE"] = None`.
- Los dos usan `SettingsStore(tmp_path / "settings.json")`, que también expone el fixture `settings_store`.

- [ ] **Step 2: Comprobar que fallan**

Run: `uv run pytest tests/web -q`
Expected: FAIL.

- [ ] **Step 3: Implementar `app.py`, las plantillas y los estáticos**

Diseño visual simple y legible, en español. No hace falta que se adapte al celular.

- [ ] **Step 4: Comprobar que todo pasa**

Run: `uv run fly check --fast`
Expected: todo `✓`.

- [ ] **Step 5: Commit**

`git add -A && git commit -m "feat(web): live search page with streaming results and settings"`

---

### Task 12: `fly web`, lanzador con doble clic y E2E

**Files:**
- Modify: `src/flytrip/cli.py` (comando `web`)
- Create: `Buscar vuelos.cmd`
- Test: `tests/cli/test_web_cli.py`, `tests/web_e2e/test_search_flow.py` (marca `e2e`)

**Interfaces:**
- Consumes: `create_app` (Tarea 11), además de `build_engine` y `build_demo_engine` (Tarea 10).
- Produces:
  - `find_free_port(start: int = 8765, attempts: int = 20) -> int`, en `flytrip.cli`.
  - El comando `fly web [--puerto 8765] [--demo] [--no-abrir]`. Levanta uvicorn en `127.0.0.1:{puerto libre}`, abre el navegador en esa URL salvo que se use `--no-abrir`, e imprime la URL.
  - El archivo `Buscar vuelos.cmd`, con fin de línea CRLF y este contenido exacto:

    ```
    @echo off
    cd /d "%~dp0"
    uv run fly web
    if errorlevel 1 pause
    ```

- [ ] **Step 1: Escribir los tests que fallan**

```python
def test_find_free_port_skips_busy():
    busy = socket.socket()
    busy.bind(("127.0.0.1", 0))
    port = busy.getsockname()[1]
    busy.listen(1)
    assert find_free_port(port) > port
    busy.close()


def test_launcher_runs_fly_web():
    text = (ROOT / "Buscar vuelos.cmd").read_text(encoding="utf-8")
    assert 'cd /d "%~dp0"' in text and "uv run fly web" in text
```

```python
@pytest.mark.e2e
def test_search_flow(
    page, demo_server
):  # demo_server: `fly web --demo --no-abrir --puerto <libre>` en un subproceso
    page.goto(demo_server)
    page.fill("input[name=destino]", "MAD")
    page.fill("input[name=desde]", "2027-03-01")
    page.fill("input[name=hasta]", "2027-05-31")
    page.fill("input[name=noches_min]", "14")
    page.fill("input[name=noches_max]", "21")
    page.click("text=Buscar")
    page.wait_for_selector("text=Kiwi: OK")
    assert page.locator(".itinerary").count() >= 1
    assert not page.locator("text=Google Flights: OK").is_visible()  # Google demo tarda 1,5 s
    page.wait_for_selector("text=Google Flights: OK")
    assert page.locator("text=Vía Santiago").is_visible()
    hrefs = page.locator("a:has-text('Comprar')").evaluate_all("els => els.map(e => e.href)")
    assert hrefs and all(h.startswith("https://") for h in hrefs)
```

- [ ] **Step 2: Comprobar que fallan**

Run: `uv run playwright install chromium && uv run pytest tests/cli/test_web_cli.py tests/web_e2e -q`
Expected: FAIL.

- [ ] **Step 3: Implementar el comando `web`, `find_free_port` y `Buscar vuelos.cmd`**

- [ ] **Step 4: Comprobar que todo pasa**

Run: `uv run fly check`, completo y con e2e.
Expected: todo `✓`.

Verificación manual: hacer doble clic en `Buscar vuelos.cmd`. Debe abrirse el navegador en `http://127.0.0.1:8765`.

- [ ] **Step 5: Commit**

`git add -A && git commit -m "feat: fly web launcher, double-click start and e2e search flow"`

---

### Task 13: `fly doctor` y cierre del hito

**Files:**
- Create: `src/flytrip/engine/doctor.py`
- Modify: `src/flytrip/cli.py` (comando `doctor`), `CLAUDE.md`, `docs/setup.md`
- Test: `tests/engine/test_doctor.py`, `tests/live/test_live_sources.py` (marca `live`)

**Interfaces:**
- Consumes: `run_safely`, las fuentes reales y `build_engine` (Tareas 5 a 10).
- Produces:
  - `SourceHealth(source: str, ok: bool, detail: str, latency_ms: int)`, una dataclass frozen.
  - `check_result_shape(result: SourceResult) -> SourceHealth`. La fuente está sana si `status == "ok"`, si devolvió al menos 1 itinerario y si todos tienen precio mayor que 0, al menos un segmento por tramo y una URL https. El `detail` es uno de estos:
    - `"OK: {n} itinerarios en {s:.1f} s"`, con coma decimal.
    - `"Rota: 0 itinerarios"`.
    - `"Rota: {detalle de la fuente}"`.
  - `async def run_doctor(kiwi: Source, google: Source, *, today: date, pauses, clock) -> list[SourceHealth]`:
    - Kiwi: SCL→MAD, salida entre `today+30` y `today+44`, 14 noches.
    - Google: SCL→MAD, salida en `today+30`, 14 noches.
  - El comando `fly doctor` imprime una tabla y termina con 1 si alguna fuente no está sana.

- [ ] **Step 1: Escribir los tests que fallan**

```python
def test_shape_ok():
    h = check_result_shape(
        SourceResult(source="kiwi", status="ok", itineraries=(make_itinerary(),), latency_ms=2300)
    )
    assert h.ok and h.detail == "OK: 1 itinerarios en 2,3 s"


def test_shape_empty_is_broken():
    assert (
        check_result_shape(SourceResult(source="kiwi", status="ok")).detail == "Rota: 0 itinerarios"
    )


def test_shape_passes_source_detail():
    r = SourceResult(
        source="google", status="error", detail="Google cambió el formato de la página"
    )
    assert check_result_shape(r) == SourceHealth(
        "google", False, "Rota: Google cambió el formato de la página", 0
    )
```

```python
@pytest.mark.live
async def test_live_sources_are_healthy(tmp_path):
    engine = build_engine(tmp_path)
    health = await run_doctor(
        engine.kiwi,
        engine.google,
        today=today_in_mendoza(datetime.now(timezone.utc)),
        pauses=PauseRegistry(tmp_path / "p.json", utc_now),
        clock=utc_now,
    )
    assert {h.source: h.ok for h in health}["kiwi"] is True
```

- [ ] **Step 2: Comprobar que fallan**

Run: `uv run pytest tests/engine/test_doctor.py -q`
Expected: FAIL.

- [ ] **Step 3: Implementar `doctor.py` y el comando `doctor`**

- [ ] **Step 4: Comprobar que todo pasa**

Run: `uv run fly check`
Expected: todo `✓`.

- [ ] **Step 5: Verificación en vivo del hito**

1. `uv run fly doctor`. Kiwi tiene que dar OK. Si Google sale rota o bloqueada, anotar el motivo en `docs/sources/google-flights.md` y seguir.
2. `uv run pytest -m live -q`. Pasa.
3. Escenario 1 del spec: `uv run fly search MAD --desde 2027-03-01 --hasta 2027-05-31 --noches 14-21`. Tiene que mostrar resultados de los tres orígenes en 30 s o menos.
4. Repetir la misma búsqueda. Debe salir al instante desde la caché e indicar su antigüedad (escenario 8).
5. Abrir la web con doble clic y repetir la búsqueda.

- [ ] **Step 6: Actualizar las guías**

- `CLAUDE.md`: añadir solo los errores reales que aparecieron durante el hito.
- `docs/setup.md`: añadir lo que haya hecho falta en la práctica.

- [ ] **Step 7: Commit**

`git add -A && git commit -m "feat: fly doctor live source checks and milestone wrap-up"`
