# TraderAssistant — Historia IEX ampliada de NVIDIA, para estudio a 2 minutos

**Versión:** `hist-nvda-iex-1.0` · **Operación:** solo lectura de datos bursátiles históricos · **Activo:** NVDA

## ¿Por qué existe?

El evaluador de dos minutos ya funciona, pero las 500 velas guardadas normalmente abarcan apenas 2 sesiones. Este complemento consulta, por separado, hasta **90 días naturales de barras IEX de 1 minuto** para poder investigar más sesiones sin modificar el realtime.

**No genera una estrategia rentable, no ofrece señales de entrada y no pronostica el precio futuro.** Tampoco representa los vencimientos o las cotizaciones de NVIDIA Blitz en IQ Option.

## Protección del proyecto

- No modifica `main.py`, `app.py`, `alpaca_live.py`, `analysis_live.py`, `ui/live.html`, `screener/`, `requirements.txt` ni `config.json`.
- No modifica `cache/alpaca_iex_nvda.json` ni ningún otro caché en vivo.
- Solo lee la clave del TXT local cuando se realiza una descarga a `data.alpaca.markets` usando TLS. No imprime, guarda ni transmite claves a otros servidores.
- No abre WebSockets, ni envía órdenes, ni instala paquetes.
- Solo escribe un **CSV nuevo** y un **JSON de metadatos** dentro de `auditoria/historico_nvda_iex/`.
- Cada ejecución crea nombres distintos para evitar reemplazos.

## Preparación

Cierra TraderAssistant si quieres evitar cualquier carga concurrente, y en PowerShell:

```powershell
cd C:\Proyectos\TraderAssistant

# Primero comprobar que no hay versiones previas de estos archivos
Test-Path .\descargar_historial_nvda_iex.py
Test-Path .\pruebas\test_descargar_historial_nvda_iex.py

# Si ambos resultados son False, extraer el ZIP desde Descargas.
Expand-Archive -LiteralPath "$env:USERPROFILE\Downloads\TraderAssistant_Historial_Ampliado_NVDA.zip" -DestinationPath "C:\Proyectos\TraderAssistant"

# Comprobar sin red ni claves
.\venv\Scripts\python.exe -B .\descargar_historial_nvda_iex.py --days 90 --dry-run

# Ejecutar pruebas sin red
.\venv\Scripts\python.exe -B .\pruebas\test_descargar_historial_nvda_iex.py
```

## Descargar 90 días (una sola acción)

```powershell
.\venv\Scripts\python.exe -B .\descargar_historial_nvda_iex.py --days 90
```

El programa muestra páginas descargadas, total de barras y **la ruta completa del CSV** generado. Alpaca puede limitar la consulta según la cuenta, disponibilidad histórica y límites de API; en ese caso se muestra un error controlado.

## Evaluar offline a 2 minutos

**Copia la ruta del CSV real que el comando anterior te muestre.** Un ejemplo de sintaxis:

```powershell
.\venv\Scripts\python.exe -B .\evaluador_historico_2min.py --symbol NVDA --csv "C:\Proyectos\TraderAssistant\auditoria\historico_nvda_iex\nvda_iex_1min_AAAAmmdd_HHMMSS.csv" --output-dir ".\auditoria\evaluacion_2min_nvda_ampliada"
```

Reemplaza el nombre ficticio `AAAAmmdd_HHMMSS` con el nombre generado. **La evaluación se ejecuta aparte**; el descargador no toca el evaluador.

Los resultados de la evaluación aparecen en la carpeta indicada:
- `resumen_2min.json`
- `informe_2min.md`
- `eventos_2min.csv`

## Limitaciones de interpretación

- **90 días naturales** no son 90 sesiones bursátiles. Fines de semana y festivos no generan barras de sesión regular.
- Se recupera IEX, no SIP consolidado, ni cotizaciones de IQ Option.
- La última vela del rango se deja fuera para evitar datos en formación.
- La evaluación usa aperturas de 1 minuto como aproximación del momento de entrada y salida a 120 s: el precio real disponible al segundo exacto puede ser diferente.
- Con muchas más sesiones, `evaluador_historico_2min.py` recalcula indicadores por vela; ejecutarlo offline evita competir con el streaming pero no evita que el análisis tarde más.
- Un porcentaje histórico de aciertos no demuestra ventaja rentable; antes de usar señales en vivo hace falta validación fuera de muestra, comparación con una referencia y evaluación de costes y reglas de vencimiento.
