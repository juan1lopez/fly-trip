"""FastAPI app: search form, live results over SSE, and settings."""

import logging
from collections.abc import AsyncIterator, Callable
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape

from flytrip.core.models import TransferCost
from flytrip.core.query import SearchQuery, today_for_validation, validate_query
from flytrip.engine.search import SearchEngine, SnapshotEvent, SourceStatus, StatusEvent
from flytrip.engine.settings import Settings, SettingsStore
from flytrip.web import views

WEB_DIR = Path(__file__).parent
TRANSFER_AIRPORTS = ("SCL", "EZE")
ALL_ORIGINS = ("MDZ", "SCL", "EZE")
SEARCH_FAILED = "La búsqueda falló por un error inesperado. Intenta de nuevo."
log = logging.getLogger("flytrip.web")


def _environment() -> Environment:
    env = Environment(
        loader=FileSystemLoader(WEB_DIR / "templates"),
        autoescape=select_autoescape(["html"]),
    )
    env.globals.update(
        origin_label=views.origin_label,
        format_usd=views.format_usd,
        format_duration=views.format_duration,
        format_short_date=views.format_short_date,
        route_label=views.route_label,
        price_breakdown=views.price_breakdown,
        status_label=views.status_label,
        baggage_label=views.baggage_label,
        age_label=views.age_label,
        source_names=views.SOURCE_NAMES,
        unknown_separate=views.UNKNOWN_SEPARATE,
    )
    return env


def _sse(event: str, html: str) -> str:
    lines = html.splitlines() or [""]
    return f"event: {event}\n" + "".join(f"data: {line}\n" for line in lines) + "\n"


class _Form:
    """Minimal `.get` / `.getlist` view over a parsed urlencoded body."""

    def __init__(self, data: dict[str, list[str]]) -> None:
        self._data = data

    def get(self, name: str, default: str = "") -> str:
        values = self._data.get(name)
        return values[0] if values else default

    def getlist(self, name: str) -> list[str]:
        return self._data.get(name, [])


def _parse_query(params: Any) -> tuple[SearchQuery | None, list[str]]:
    """Build a SearchQuery from form parameters; the list holds parsing errors."""
    errors: list[str] = []

    def to_date(name: str, label: str) -> date:
        try:
            return date.fromisoformat(params.get(name, ""))
        except ValueError:
            errors.append(f"La fecha '{label}' no es válida.")
            return date.min

    def to_int(name: str, label: str) -> int | None:
        raw = params.get(name, "").strip()
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError:
            errors.append(f"{label}: tiene que ser un número entero.")
            return None

    depart_from = to_date("desde", "desde")
    depart_to = to_date("hasta", "hasta")
    one_way = bool(params.get("solo_ida"))
    nights_min = None if one_way else to_int("noches_min", "Noches mínimas")
    nights_max = None if one_way else to_int("noches_max", "Noches máximas")
    adults = to_int("adultos", "Adultos") or 1
    if errors:
        return None, errors
    query = SearchQuery(
        destination=params.get("destino", "").strip().upper(),
        origins=tuple(params.getlist("origenes")),
        depart_from=depart_from,
        depart_to=depart_to,
        nights_min=nights_min,
        nights_max=nights_max,
        adults=adults,
        allow_separate_tickets=bool(params.get("separados")),
    )
    return query, []


def _parse_settings(form: Any, current: Settings) -> tuple[Settings | None, list[str]]:
    errors: list[str] = []

    def to_decimal(name: str, label: str) -> Decimal | None:
        raw = form.get(name, "").strip().replace(",", ".")
        if not raw:
            return None
        try:
            value = Decimal(raw)
        except InvalidOperation:
            errors.append(f"{label}: valor inválido.")
            return None
        if not value.is_finite() or value < 0:
            errors.append(f"{label}: valor inválido.")
            return None
        return value

    transfers: dict[str, TransferCost | None] = {}
    for code in TRANSFER_AIRPORTS:
        cost = to_decimal(f"traslado_{code}_costo", f"Traslado {code}, costo")
        hours = to_decimal(f"traslado_{code}_horas", f"Traslado {code}, horas")
        if cost is None and hours is None:
            transfers[code] = None
        elif cost is None or hours is None:
            errors.append(f"Traslado {code}: completa el costo y las horas, o deja ambos vacíos.")
            transfers[code] = None
        else:
            transfers[code] = TransferCost(cost_usd_roundtrip=cost, hours_one_way=hours)
    per_hour = to_decimal("usd_por_hora", "USD por hora")
    if per_hour is None and not errors:
        errors.append("USD por hora: valor inválido.")
    try:
        adults = int(form.get("adultos") or current.adults)
    except ValueError:
        adults = 0
    if not 1 <= adults <= 9:
        errors.append("Adultos: entre 1 y 9.")
    # An unchecked group is indistinguishable from an absent one: keep the stored origins.
    origins = tuple(code for code in form.getlist("origenes") if code in ALL_ORIGINS)
    origins = origins or current.default_origins
    if errors or per_hour is None:
        return None, errors
    return (
        Settings(
            default_origins=origins,
            transfers=transfers,
            adults=adults,
            usd_per_hour=per_hour,
            allow_separate_tickets=bool(form.get("separados")),
        ),
        [],
    )


def create_app(
    *, engine_factory: Callable[[], SearchEngine], settings_store: SettingsStore
) -> FastAPI:
    app = FastAPI(title="fly-trip")
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
    env = _environment()

    def render(name: str, **context: Any) -> str:
        return env.get_template(name).render(**context)

    def settings_page(settings: Settings, errors: list[str], saved: bool = False) -> str:
        return render(
            "settings.html", settings=settings, errors=errors, saved=saved, all_origins=ALL_ORIGINS
        )

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        settings = settings_store.load()
        return render("index.html", settings=settings, all_origins=ALL_ORIGINS)

    def check(
        request: Request,
    ) -> tuple[SearchEngine, SearchQuery | None, list[str]]:
        engine = engine_factory()
        query, errors = _parse_query(request.query_params)
        if query is not None:
            today = today_for_validation(datetime.now(UTC))
            errors = validate_query(query, today, engine.max_window_days)
        return engine, query, errors

    @app.get("/buscar/validar", response_model=None)
    async def search_validate(request: Request) -> Response:
        _, _, errors = check(request)
        if errors:
            return HTMLResponse(render("_errors.html", errors=errors), status_code=422)
        return Response(status_code=204)

    @app.get("/buscar/stream", response_model=None)
    async def search_stream(request: Request) -> StreamingResponse | HTMLResponse:
        engine, query, errors = check(request)
        if query is None or errors:
            return HTMLResponse(render("_errors.html", errors=errors), status_code=422)
        use_cache = not request.query_params.get("refrescar")

        async def events() -> AsyncIterator[str]:
            statuses: dict[str, SourceStatus] = {}
            try:
                async for event in engine.run(query, use_cache=use_cache):
                    if isinstance(event, StatusEvent):
                        statuses[event.status.source] = event.status
                        yield _sse("status", render("_status.html", statuses=statuses.values()))
                    elif isinstance(event, SnapshotEvent):
                        snapshot = event.snapshot
                        statuses.update(snapshot.statuses)
                        yield _sse("status", render("_status.html", statuses=statuses.values()))
                        yield _sse(
                            "results",
                            render("_results.html", snapshot=snapshot, now=datetime.now(UTC)),
                        )
            except Exception:
                log.exception("La búsqueda falló")
                yield _sse("error", render("_errors.html", errors=[SEARCH_FAILED]))
            finally:
                yield _sse("done", "")

        return StreamingResponse(events(), media_type="text/event-stream")

    @app.get("/ajustes", response_class=HTMLResponse)
    async def settings_get() -> str:
        return settings_page(settings_store.load(), [])

    @app.post("/ajustes", response_class=HTMLResponse)
    async def settings_post(request: Request) -> HTMLResponse:
        current = settings_store.load()
        # Plain urlencoded parsing: avoids the python-multipart dependency.
        body = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)
        settings, errors = _parse_settings(_Form(body), current)
        if settings is None:
            return HTMLResponse(settings_page(current, errors), status_code=422)
        settings_store.save(settings)
        return HTMLResponse(settings_page(settings, [], saved=True))

    return app
