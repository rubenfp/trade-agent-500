# Trade Agent 500 — MVP de simulación

Aplicación web local con Streamlit para escanear activos, ejecutar un backtest diario y mantener una cartera virtual persistente de 500 €. **No envía órdenes reales y no necesita claves API.**

## Requisitos
- Python 3.10–3.12 recomendado.
- Conexión a internet para descargar datos históricos públicos de Yahoo Finance.
- Los datos gratuitos pueden tener retrasos, límites, errores o cambios de cobertura; no se garantiza disponibilidad.

## Instalación en Windows
1. Instala Python desde https://www.python.org/downloads/ y activa la opción de añadir Python al PATH.
2. Descomprime la carpeta `trade-agent`.
3. Abre PowerShell en esa carpeta.
4. Ejecuta:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
streamlit run app.py
```

Si PowerShell bloquea la activación, ejecuta en esa misma terminal `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` y vuelve a activar el entorno.

La aplicación se abrirá en el navegador, normalmente en `http://localhost:8501`.

## Instalación en macOS/Linux
```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
streamlit run app.py
```

## Uso
1. En la barra lateral, deja capital inicial 500 €, riesgo por operación 1 %, máximo 4 posiciones y puntuación mínima 70.
2. En **Escáner**, pulsa **Analizar mercados ahora**.
3. Revisa candidatos y fechas de los datos.
4. Pulsa **Ejecutar ciclo de trading virtual** para registrar entradas/salidas virtuales. El estado se guarda en `paper_trading.sqlite3`.
5. En **Backtesting**, selecciona un símbolo y periodo y ejecuta la prueba. Descarga el CSV de operaciones si lo necesitas.
6. En **Cartera virtual**, revisa y, si lo deseas, cierra una posición de forma virtual.

## Estrategia inicial
- EMA 20 > EMA 50.
- Cierre por encima de EMA 50.
- Cierre supera el máximo de las 20 sesiones anteriores (calculado sin incluir la sesión actual).
- RSI(14) entre 50 y 70.
- Stop inicial de 2 ATR y objetivo teórico de 3R.
- Riesgo objetivo del 1 % de la cuenta por operación; tamaño limitado al 30 % de patrimonio y al efectivo disponible.
- Costes simulados por defecto: comisión 0,10 % y deslizamiento 0,10 % por lado.

## Limitaciones importantes
- Este es un MVP educativo, no una estrategia validada ni asesoramiento financiero.
- El backtest es por activo y no representa un backtest completo de cartera multi-activo. No corrige automáticamente todos los sesgos de supervivencia, impuestos, dividendos, spreads reales ni diferencias de ejecución.
- El ciclo de cartera virtual usa datos descargados y es una aproximación; no equivale a un simulador tick a tick.
- El universo incluido cotiza en USD y el adaptador intenta convertir OHLC a EUR usando EURUSD=X alineado por fecha. Si no se puede obtener el cambio, ese símbolo se omite. Es una conversión diaria aproximada, no una simulación FX intradía.
- Los datos de Yahoo Finance son de terceros y pueden ser retrasados o discontinuados. Comprueba sus términos y disponibilidad.
- No hay apalancamiento, cortos ni órdenes reales. No añadas claves privadas ni conectes una cuenta financiada a este proyecto.

## Tests
```bash
pytest -q
```
