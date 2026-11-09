from typing import Annotated

import typer

from flytrip.devtools.check import build_check_steps, run_check_steps
from flytrip.devtools.record import record_app

app = typer.Typer(help="fly-trip: buscador personal de pasajes baratos.", no_args_is_help=True)

app.add_typer(record_app, name="record")


@app.callback()
def main() -> None:
    """Punto de entrada de los comandos de fly-trip."""


@app.command()
def check(
    fast: Annotated[bool, typer.Option("--fast", help="Omite los tests e2e y live.")] = False,
) -> None:
    """Corre formato, lint, tipos, arquitectura y tests."""
    failures = run_check_steps(build_check_steps(fast=fast))
    raise typer.Exit(code=1 if failures else 0)
