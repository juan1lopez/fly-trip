# Puesta en marcha (Hito 1)

1. Instalar uv:

   ```bash
   python -m pip install uv
   ```

2. Instalar las dependencias del proyecto:

   ```bash
   uv sync
   ```

3. Instalar el navegador de pruebas, solo necesario para los tests e2e:

   ```bash
   uv run playwright install chromium
   ```

4. Hacer doble clic en `Buscar vuelos.cmd`.

## Comandos útiles

- `uv run fly doctor`: revisa que Kiwi, Google Flights y Skiplagged respondan (hace pocas consultas reales, no lo repitas seguido).
- `uv run fly search MAD --mes 2027-03 --hasta-mes 2027-05 --noches 14-21`: busca por mes (usa el calendario de Skiplagged). Los pasajes hidden city nunca se incluyen.
- `uv run fly web --demo`: abre la web con datos de ejemplo, sin red, para probar la interfaz.
- `uv run fly check --fast`: todos los chequeos menos los tests e2e del navegador (estos necesitan el paso 3).
- `uv run pytest -m live -q`: tests que sí usan la red. El `pytest` común los excluye; corrélos solo a propósito.
- En Windows, si la consola muestra mal los acentos, definir `PYTHONUTF8=1` antes de correr los comandos.
