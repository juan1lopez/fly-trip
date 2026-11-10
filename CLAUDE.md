# fly-trip

Buscador personal de vuelos baratos: una web local y una CLI que consultan Kiwi.com (MCP oficial),
Google Flights (`fli`) y Skiplagged (MCP oficial) desde Mendoza (MDZ), Santiago (SCL) y Ezeiza (EZE).
Specs vigentes: `docs/superpowers/specs/2026-11-09-buscador-vuelos-baratos-design.md` (hito 1) y `docs/superpowers/specs/2026-11-09-iteracion-2-fuentes-mes-interfaz-design.md` (iteración 2).

## Comandos

```bash
uv sync                  # instala dependencias
uv run fly check         # todos los chequeos (formato, lint, tipos, capas, tests)
uv run fly check --fast  # igual, sin tests e2e del navegador
uv run fly web           # levanta la web local
uv run fly search        # busca en la terminal (--mes/--hasta-mes: por mes)
uv run fly doctor        # revisa que las fuentes sigan respondiendo
uv run fly record        # graba fixtures nuevos desde las fuentes reales
```

Antes de dar una tarea por terminada, `uv run fly check` debe pasar completo.

## Capas y su regla

Se verifican con import-linter dentro de `fly check`:

- `core`: modelos, ranking, fusión y traslados. Lógica pura, no importa nada del proyecto.
- `sources`: Kiwi, Google Flights y Skiplagged. Solo importa `core`.
- `engine`: orquesta las fuentes. Importa `core` y `sources`.
- `web` importa `engine` y `core`, y nunca importa `cli`. `cli` importa `web`, `engine` y `core`.
- `devtools`: herramientas de desarrollo; la app no las importa.

## Reglas de tests

- Los tests nunca salen a internet: `tests/conftest.py` solo deja pasar localhost.
- Solo los tests con la marca `live` pueden usar la red, y no corren en `fly check`.
- Las respuestas de las fuentes viven en `tests/fixtures/`; se graban con `fly record`.
- Toda fuente cumple el mismo contrato común de tests.
- Los tests del navegador llevan la marca `e2e`.
- `FLYTRIP_TODAY` (fecha ISO) fija el "hoy" de las validaciones (`today_for_validation`). Es SOLO para tests: `tests/conftest.py` la define en 2026-11-09 para que las fechas fijas de 2027 no envejezcan, y los tests con subprocesos la pasan en su entorno.

## Lecciones reales

- El hook de edición corre `ruff check --fix` y borra los imports agregados antes de su primer uso: añadir el import junto con su uso.
- Nunca reformatear `docs/` con ruff (está excluido; reescribe los bloques Python de los Markdown).
- En Windows, ser explícito con UTF-8: leer `sys.stdin.buffer` y decodificar como UTF-8; usar `PYTHONUTF8=1` para subprocesos y salida de consola.
- `pytest` común excluye `live`; correr `-m live` solo a propósito, porque usa la red.
- Los worktrees de agentes arrancan desde origin/main: hacer `git reset --hard` a la rama de integración antes de empezar, solo en un worktree recién creado y sin cambios.
- Skiplagged: los pasajes hidden city (ciudad oculta) se excluyen siempre; nunca se piden ni se muestran.
- Google Flights usa `fli` 0.10.0 desde GitHub (commit `881aee5`); la 0.9.0 de PyPI devolvía vacío desde esta máquina. Ver `docs/sources/google-flights.md`.

## Cómo añadir una fuente

1. Escribir el test de contrato y grabar fixtures en `tests/fixtures/`.
2. Implementar el protocolo de `sources/base.py` en un módulo nuevo.
3. Convertir todo a los modelos de `core`; nada de formatos de la fuente fuera de `sources`.
4. Registrarla en `engine` con sus límites y timeouts.
5. Documentarla en `docs/sources/` y sumarla a `fly doctor`.

## Mapa de docs

- `docs/architecture.md`: capas, flujo de la búsqueda (modo fechas y mes) y qué módulo cumple cada parte del spec.
- `docs/setup.md`: puesta en marcha.
- `docs/sources/`: notas de cada fuente (límites, rarezas, formato).
- `docs/superpowers/`: specs y planes.

## Estilo

- Textos para la persona usuaria en español neutro latinoamericano ("pasajes", "valija", "celular").
- Código, identificadores y nombres de tests en inglés.
- Uso cortés de las fuentes: sin proxies, sin resolver captchas, sin esquivar bloqueos.
- Los secretos nunca van a git (`.env` está ignorado; el modelo es `.env.example`).

## Regla final

Cada error de un agente se convierte en una regla aquí o, mejor, en un chequeo.
