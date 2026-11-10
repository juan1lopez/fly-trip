## Qué es
Buscador personal de vuelos baratos con fechas abiertas, desde Mendoza (MDZ), Santiago (SCL) y Ezeiza (EZE). Ordena los resultados por el **total real desde Mendoza**, sumando el traslado a Santiago o Ezeiza que configures en Ajustes.

## Cómo se usa
- `Buscar vuelos.cmd` (doble clic) abre la web en `127.0.0.1`.
- `uv run fly search MAD --desde 2027-03-01 --hasta 2027-05-31 --noches 14-21`
- `uv run fly web --demo` prueba la app sin conexión.
- `uv run fly doctor` comprueba si las fuentes funcionan.

## Qué incluye
- **Fuentes:** Kiwi.com, a través de su MCP oficial, y Google Flights, a través de `fli`. Kiwi recorre todo el rango de fechas y Google confirma las mejores.
- **Resultados:**
  - Lo mejor por origen y el mejor equilibrio precio/duración.
  - Los pasajes separados marcados.
  - El equipaje incluido.
  - La antigüedad del precio en caché, con botón "Actualizar".
- **Fallos visibles:** cuando una fuente o un origen falla, se muestra; nunca aparece como "OK". Google pasa a pausa ante un bloqueo y no reintenta.
- **Arnés para agentes:**
  - `CLAUDE.md`.
  - Tests sin red con respuestas grabadas y un contrato común para las fuentes.
  - import-linter y mypy estricto.
  - Hooks de Claude Code, CI y `fly doctor`.

## Verificación
- `uv run fly check`: 216 tests en verde, incluido el test con navegador real (Playwright).
- **En vivo:**
  - Kiwi OK: 56 resultados de los tres orígenes en 6,1 s; la búsqueda repetida sale de la caché en 1,5 s.
  - Google Flights está bloqueado desde esta máquina con `fli` 0.9.0. Se muestra como error.

## Pendiente
- Los avisos de precio por Telegram son el hito 2.
- Google Flights: hay que probar otra versión de `fli`.
- Hay unos 40 detalles menores diferidos, registrados durante la revisión.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
