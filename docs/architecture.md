# Arquitectura

## Capas

```text
cli / web      interfaz: terminal y web local (FastAPI + Jinja2 + HTMX)
engine         orquestación, límites, timeouts y caché
sources        kiwi.py, google_flights.py, skiplagged.py (detrás de base.py)
core           modelos, ranking, fusión, traslados; lógica pura
devtools       chequeos y hooks de desarrollo; la app no los importa
```

Cada capa solo importa las de abajo. `core` no importa nada del proyecto. import-linter lo verifica
en `uv run fly check`.

## Fuentes

- Kiwi (MCP oficial): explora rangos de fechas y devuelve candidatos baratos.
- Google Flights (`fli`): confirma precio y horarios de fechas exactas.
- Skiplagged (MCP oficial): confirma fechas exactas y además da un calendario de precios por mes. Los pasajes hidden city (ciudad oculta) se excluyen siempre.

Cada fuente tiene sus notas en `docs/sources/`.

## Flujo de una búsqueda (modo fechas)

1. Kiwi explora: recorre ventanas de fechas (de hasta 92 días cada una) y devuelve candidatos baratos.
2. Los candidatos se reducen a los más prometedores.
3. Google Flights confirma el precio y los horarios de esos candidatos.
4. Fusión: se unen los resultados de ambas fuentes en un mismo modelo normalizado.
5. Traslados: se suma el costo y tiempo de llegar al aeropuerto de salida desde Mendoza.
6. Ranking: se ordena por costo total real.

## Modo mes

`fly search --mes AAAA-MM [--hasta-mes AAAA-MM]` (o el selector de mes de la web) busca por meses en vez de un rango de fechas:

1. Skiplagged entrega el calendario de cada origen y mes (una consulta cubre todos los días).
2. Con esos precios se eligen los días más baratos, y las fuentes confirman los candidatos.
3. Fusión, traslados y ranking son los mismos que en el modo fechas.

La web muestra el calendario con el rótulo "precio orientativo (Skiplagged)": son precios por 1 adulto, sin confirmar, y sirven para elegir fechas, no para reservar.

## Mapa del spec a los módulos

El spec es `docs/superpowers/specs/2026-11-09-buscador-vuelos-baratos-design.md`.

| Sección del spec | Módulo |
| --- | --- |
| 5.1 Búsqueda | `engine`, `sources` |
| 5.2 Traslado desde Mendoza | `core` (traslados) |
| 5.3 Resultados | `core` (fusión, ranking), `web` |
| 5.4 Avisos | `alerts` (hito posterior) |
| 5.5 Ajustes y secretos | `.env.example`, `engine` (`settings.py`) |
| 5.6 Arranque y puesta en marcha | `Buscar vuelos.cmd`, `cli`, `docs/setup.md` |
| 6 Modelo de datos normalizado | `core` (modelos) |
| 7 Arquitectura propuesta | este documento, contratos de import-linter en `pyproject.toml` |
| 8 Arnés | `CLAUDE.md`, `.claude/settings.json`, `devtools`, `tests/conftest.py`, `.github/workflows/ci.yml` |
