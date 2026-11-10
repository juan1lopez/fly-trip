# Arquitectura

## Capas

```text
cli / web      interfaz: terminal y web local (FastAPI + Jinja2 + HTMX)
engine         orquestación, límites, timeouts y caché
sources        kiwi.py, google_flights.py (detrás de base.py)
core           modelos, ranking, fusión, traslados; lógica pura
devtools       chequeos y hooks de desarrollo; la app no los importa
```

Cada capa solo importa las de abajo. `core` no importa nada del proyecto. import-linter lo verifica
en `uv run fly check`.

## Flujo de una búsqueda

1. Kiwi explora: recorre ventanas de fechas (de hasta 92 días cada una) y devuelve candidatos baratos.
2. Los candidatos se reducen a los más prometedores.
3. Google Flights confirma el precio y los horarios de esos candidatos.
4. Fusión: se unen los resultados de ambas fuentes en un mismo modelo normalizado.
5. Traslados: se suma el costo y tiempo de llegar al aeropuerto de salida desde Mendoza.
6. Ranking: se ordena por costo total real.

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
