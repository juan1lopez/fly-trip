from datetime import date
from pathlib import Path
from typing import Annotated

import httpx
import typer

from flytrip.devtools.record_google import record_google
from flytrip.sources.base import SourceRequest
from flytrip.sources.kiwi import KIWI_HEADERS, KIWI_URL, build_arguments, build_rpc_body

record_app = typer.Typer(help="Graba respuestas reales de las fuentes como fixtures de tests.")

KIWI_FIXTURES = Path("tests/fixtures/kiwi")
GOOGLE_FIXTURES = Path("tests/fixtures/google")


def _parse_nights(value: str) -> tuple[int, int]:
    low, _, high = value.partition("-")
    try:
        return int(low), int(high or low)
    except ValueError as exc:
        raise typer.BadParameter("Usa el formato 14-21.") from exc


@record_app.command()
def kiwi(
    scenario: Annotated[str, typer.Argument(help="Nombre del fixture, sin extensión.")],
    origen: Annotated[str, typer.Option("--origen")],
    destino: Annotated[str, typer.Option("--destino")],
    desde: Annotated[str, typer.Option("--desde", help="AAAA-MM-DD")],
    hasta: Annotated[str, typer.Option("--hasta", help="AAAA-MM-DD")],
    noches: Annotated[str | None, typer.Option("--noches", help="Por ejemplo 14-21.")] = None,
    adultos: Annotated[int, typer.Option("--adultos")] = 1,
    sin_separados: Annotated[bool, typer.Option("--sin-separados")] = False,
) -> None:
    """Hace UNA consulta a Kiwi y guarda el SSE crudo en tests/fixtures/kiwi/."""
    nights = _parse_nights(noches) if noches else (None, None)
    request = SourceRequest(
        origin=origen,
        destination=destino,
        depart_from=date.fromisoformat(desde),
        depart_to=date.fromisoformat(hasta),
        nights_min=nights[0],
        nights_max=nights[1],
        adults=adultos,
        allow_separate_tickets=not sin_separados,
    )
    response = httpx.post(
        KIWI_URL,
        json=build_rpc_body(build_arguments(request)),
        headers=KIWI_HEADERS,
        timeout=90,
    )
    response.raise_for_status()
    KIWI_FIXTURES.mkdir(parents=True, exist_ok=True)
    target = KIWI_FIXTURES / f"{scenario}.sse"
    target.write_bytes(response.text.replace("\r\n", "\n").encode("utf-8"))
    typer.echo(f"Guardado {target}")


@record_app.command()
def google(
    scenario: Annotated[str, typer.Argument(help="Nombre del fixture, sin extensión.")],
    origen: Annotated[str, typer.Option("--origen")],
    destino: Annotated[str, typer.Option("--destino")],
    salida: Annotated[str, typer.Option("--salida", help="AAAA-MM-DD")],
    noches: Annotated[int | None, typer.Option("--noches")] = None,
    adultos: Annotated[int, typer.Option("--adultos")] = 1,
) -> None:
    """Hace UNA búsqueda en Google Flights y guarda el resultado en tests/fixtures/google/."""
    target = record_google(
        scenario, origen, destino, date.fromisoformat(salida), noches, adultos, GOOGLE_FIXTURES
    )
    typer.echo(f"Guardado {target}")
