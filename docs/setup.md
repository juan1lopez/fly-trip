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
