import asyncio
import socket
import sys
import webbrowser
from datetime import date
from typing import Annotated

import typer
import uvicorn
from fastapi import FastAPI
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from flytrip.core.models import Itinerary
from flytrip.core.query import SearchQuery, today_in_mendoza, validate_query
from flytrip.devtools.check import build_check_steps, run_check_steps
from flytrip.devtools.demo import build_demo_engine
from flytrip.devtools.record import record_app
from flytrip.engine.doctor import run_doctor
from flytrip.engine.factory import build_engine
from flytrip.engine.logs import configure_logging
from flytrip.engine.paths import data_dir, home_dir, logs_dir
from flytrip.engine.search import SearchEngine, SearchSnapshot, SnapshotEvent
from flytrip.engine.settings import SettingsStore
from flytrip.sources.base import PauseRegistry
from flytrip.sources.kiwi import utc_now
from flytrip.web.app import create_app
from flytrip.web.views import (
    SOURCE_NAMES,
    baggage_label,
    format_short_date,
    format_usd,
    price_breakdown,
    route_label,
    status_label,
)

app = typer.Typer(help="fly-trip: buscador personal de pasajes baratos.", no_args_is_help=True)

app.add_typer(record_app, name="record")

# Tests replace this to avoid touching the network.
engine_factory = build_engine


@app.callback()
def main() -> None:
    """Punto de entrada de los comandos de fly-trip."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


@app.command()
def check(
    fast: Annotated[bool, typer.Option("--fast", help="Omite los tests e2e y live.")] = False,
) -> None:
    """Corre formato, lint, tipos, arquitectura y tests."""
    failures = run_check_steps(build_check_steps(fast=fast))
    raise typer.Exit(code=1 if failures else 0)


def _parse_date(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        typer.echo(f"Fecha inválida: {text}. Usa el formato AAAA-MM-DD.", err=True)
        raise typer.Exit(code=2) from None


def _parse_nights(text: str) -> tuple[int, int]:
    low, sep, high = text.partition("-")
    try:
        return int(low), int(high if sep else low)
    except ValueError:
        typer.echo("Las noches se indican como MIN-MAX, por ejemplo 14-21.", err=True)
        raise typer.Exit(code=2) from None


def _itinerary_row(index: int, it: Itinerary) -> tuple[str, ...]:
    route = route_label(it.outbound) + (" ⚠" if it.separate_tickets else "")
    dates = format_short_date(it.outbound.segments[0].departure_local.date())
    stops = str(it.outbound.stops)
    if it.inbound is not None:
        dates += f" – {format_short_date(it.inbound.segments[0].departure_local.date())}"
        stops += f" / {it.inbound.stops}"
    legs = (it.outbound, it.inbound) if it.inbound is not None else (it.outbound,)
    airlines = dict.fromkeys(s.carrier_name for leg in legs for s in leg.segments)
    sources = ", ".join(dict.fromkeys(SOURCE_NAMES.get(o.source, o.source) for o in it.offers))
    return (
        str(index),
        format_usd(it.total_from_home_usd),
        price_breakdown(it),
        escape(route),
        dates,
        stops,
        escape(", ".join(airlines)),
        baggage_label(it.baggage),
        sources,
    )


def _render(snapshot: SearchSnapshot) -> None:
    console = Console() if sys.stdout.isatty() else Console(width=200, soft_wrap=False)
    table = Table(title=f"Pasajes a {escape(snapshot.query.destination)}")
    for column in (
        "#",
        "Total desde Mendoza",
        "Precio",
        "Ruta",
        "Fechas",
        "Escalas",
        "Aerolíneas",
        "Equipaje",
        "Fuentes",
    ):
        table.add_column(column, no_wrap=True)
    for index, it in enumerate(snapshot.itineraries, start=1):
        table.add_row(*_itinerary_row(index, it))
    console.print(table)
    if any(it.separate_tickets for it in snapshot.itineraries):
        console.print("⚠ = pasajes separados: si uno se demora, el otro no se protege.")
    for status in snapshot.statuses.values():
        console.print(escape(status_label(status)))
    if snapshot.from_cache:
        console.print(f"Resultado de la caché (hace {snapshot.cache_age_minutes} min).")


async def _final_snapshot(
    engine: SearchEngine, query: SearchQuery, use_cache: bool
) -> SearchSnapshot | None:
    last: SearchSnapshot | None = None
    async for event in engine.run(query, use_cache=use_cache):
        if isinstance(event, SnapshotEvent):
            last = event.snapshot
    if last is None:
        return None
    return last


@app.command()
def search(
    destination: Annotated[str, typer.Argument(help="Destino, por ejemplo MAD.")],
    desde: Annotated[str, typer.Option("--desde", help="Primera salida, AAAA-MM-DD.")],
    hasta: Annotated[str, typer.Option("--hasta", help="Última salida, AAAA-MM-DD.")],
    noches: Annotated[str | None, typer.Option("--noches", help="Noches MIN-MAX.")] = None,
    solo_ida: Annotated[bool, typer.Option("--solo-ida", help="Sin vuelta.")] = False,
    origenes: Annotated[
        str | None, typer.Option("--origenes", help="Orígenes separados por coma.")
    ] = None,
    adultos: Annotated[int | None, typer.Option("--adultos", help="Cantidad de adultos.")] = None,
    sin_separados: Annotated[
        bool, typer.Option("--sin-separados", help="Excluye pasajes separados.")
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Imprime el resultado en JSON.")] = False,
    sin_cache: Annotated[bool, typer.Option("--sin-cache", help="Ignora la caché.")] = False,
    demo: Annotated[bool, typer.Option("--demo", help="Usa datos grabados, sin red.")] = False,
) -> None:
    """Busca los pasajes más baratos desde Mendoza, Santiago y Ezeiza."""
    home = home_dir()
    configure_logging(logs_dir(home))
    engine = build_demo_engine(home) if demo else engine_factory(home)
    if solo_ida and noches is not None:
        typer.echo("Usa --noches o --solo-ida, no los dos.", err=True)
        raise typer.Exit(code=2)
    if not solo_ida and noches is None:
        typer.echo("Indica noches mínimas y máximas, o marca solo ida.", err=True)
        raise typer.Exit(code=2)
    nights = None if noches is None else _parse_nights(noches)
    settings = engine.settings
    query = SearchQuery(
        destination=destination.strip().upper(),
        origins=tuple(o.strip().upper() for o in origenes.split(","))
        if origenes
        else settings.default_origins,
        depart_from=_parse_date(desde),
        depart_to=_parse_date(hasta),
        nights_min=nights[0] if nights else None,
        nights_max=nights[1] if nights else None,
        adults=adultos if adultos is not None else settings.adults,
        allow_separate_tickets=settings.allow_separate_tickets and not sin_separados,
    )
    errors = validate_query(query, today_in_mendoza(utc_now()), engine.max_window_days)
    if errors:
        for message in errors:
            typer.echo(message, err=True)
        raise typer.Exit(code=2)
    snapshot = asyncio.run(_final_snapshot(engine, query, use_cache=not sin_cache))
    if snapshot is None:
        typer.echo("La búsqueda terminó sin resultados. Intenta de nuevo.", err=True)
        raise typer.Exit(code=1)
    if as_json:
        typer.echo(snapshot.model_dump_json(indent=2))
    else:
        _render(snapshot)


@app.command()
def doctor() -> None:
    """Comprueba que Kiwi y Google Flights responden con datos válidos."""
    home = home_dir()
    engine = engine_factory(home)
    health = asyncio.run(
        run_doctor(
            engine.kiwi,
            engine.google,
            today=today_in_mendoza(utc_now()),
            pauses=PauseRegistry(data_dir(home) / "pauses.json", utc_now),
            clock=utc_now,
        )
    )
    table = Table(title="Estado de las fuentes")
    table.add_column("Fuente")
    table.add_column("Estado")
    table.add_column("Detalle")
    for h in health:
        mark = "[green]✓[/green]" if h.ok else "[red]✗[/red]"
        table.add_row(SOURCE_NAMES.get(h.source, h.source), mark, escape(h.detail))
    Console().print(table)
    raise typer.Exit(code=0 if all(h.ok for h in health) else 1)


def find_free_port(start: int = 8765, attempts: int = 20) -> int:
    for port in range(start, start + attempts):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise OSError(f"No hay puertos libres entre {start} y {start + attempts - 1}.")


def make_web_app(engine: SearchEngine, store: SettingsStore) -> FastAPI:
    """One engine for the whole app lifetime: every request reuses it."""
    return create_app(engine_factory=lambda: engine, settings_store=store)


async def _serve(server: uvicorn.Server, engine: SearchEngine) -> None:
    try:
        await server.serve()
    finally:
        await engine.aclose()


@app.command()
def web(
    puerto: Annotated[int, typer.Option("--puerto", help="Puerto preferido.")] = 8765,
    demo: Annotated[bool, typer.Option("--demo", help="Usa datos grabados, sin red.")] = False,
    no_abrir: Annotated[bool, typer.Option("--no-abrir", help="No abre el navegador.")] = False,
) -> None:
    """Levanta la página de búsqueda en tu computadora."""
    home = home_dir()
    configure_logging(logs_dir(home))
    try:
        port = find_free_port(puerto)
    except OSError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None
    engine = build_demo_engine(home) if demo else engine_factory(home)
    store = SettingsStore(data_dir(home) / "settings.json")
    config = uvicorn.Config(
        make_web_app(engine, store), host="127.0.0.1", port=port, log_level="warning"
    )
    url = f"http://127.0.0.1:{port}"
    typer.echo(f"fly-trip está listo en {url} (Ctrl+C para cerrar)")
    if not no_abrir:
        webbrowser.open(url)
    asyncio.run(_serve(uvicorn.Server(config), engine))
