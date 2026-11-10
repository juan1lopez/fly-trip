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

1. Skiplagged entrega el calendario de cada origen. Una consulta cubre unos 48 días (del ancla menos 30 al ancla más 17): el motor consulta por origen, en secuencia (la primera con ancla a 30 días del inicio, las siguientes un día después del último día devuelto) y se detiene al cubrir la ventana o a las 3 consultas.
2. Kiwi explora la ventana y elige los candidatos; Google Flights y Skiplagged confirman las fechas de los mejores. El calendario solo se muestra: no elige candidatos.
3. Fusión, traslados y ranking son los mismos que en el modo fechas.

La web muestra el calendario con el rótulo "precio orientativo (Skiplagged)": Skiplagged los calcula por 1 adulto y el motor los multiplica por la cantidad de adultos; no están confirmados y sirven para elegir fechas, no para reservar.

## Mapa del spec a los módulos

Los specs son `docs/superpowers/specs/2026-11-09-buscador-vuelos-baratos-design.md` (hito 1) y `docs/superpowers/specs/2026-11-09-iteracion-2-fuentes-mes-interfaz-design.md` (iteración 2: Skiplagged, búsqueda por mes e interfaz nueva); lo que el segundo no cambia sigue el primero.

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
