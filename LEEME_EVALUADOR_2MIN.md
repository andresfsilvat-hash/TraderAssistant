# TraderAssistant — Evaluador histórico exploratorio de 2 minutos

**Versión:** `offline-2min-1.0`  
**Alcance:** investigación OFFLINE, sin órdenes ni API ni credenciales. No es un sistema de entradas verificadas.

## Qué hace

Reutiliza `screener/indicator_detector.py`, `screener/pattern_detector.py` y la clasificación `_classify` de `screener/scorer.py`. No altera ninguna de esas funciones ni modifica `alpaca_live.py`, `analysis_live.py`, `main.py`, `app.py` o `ui/live.html`.

Para cada vela de 1 minuto de una sesión bursátil regular:

1. Calcula los detectores usando solo el historial **hasta esa vela ya cerrada**.
2. Si los detectores dan evidencia alcista sin bajista, marca una **hipótesis histórica SUBE**; si ocurre lo inverso, una **hipótesis histórica BAJA**. Si se contradicen o no hay señal, no crea operación hipotética.
3. Supone una entrada a la **apertura de la siguiente vela** de un minuto.
4. Considera un vencimiento nominal 120 segundos después, utilizando como **precio proxy de salida** la apertura de la vela que empieza entonces.
5. Exige que existan todos los intervalos consecutivos necesarios y que la operación no cruce el cierre regular de la bolsa estadounidense.
6. Calcula aciertos, errores, empates y una referencia simple (dirección de la última vela) para los mismos instantes. Excluye eventos solapados de la métrica principal.

**Precaución:** las aperturas son los primeros precios de operaciones registrados dentro de cada minuto, **no se sabe si se negociaron al segundo exacto**. Además, el caché puede contener barras corregidas retrospectivamente y no conserva qué versión se conocía en cada instante. Esto limita la validez histórica, incluso aunque el algoritmo no lea barras futuras para generar su señal.

## Instalar sin dañar TraderAssistant

**1.** Cerrar TraderAssistant antes de ejecutar el evaluador, para utilizar una foto estable de los cachés. No es necesario reinstalar v1/v2/v3/v4.

**2.** Descomprimir el ZIP en `C:\Proyectos\TraderAssistant`. Solo añade:

- `evaluador_historico_2min.py`
- `pruebas/test_evaluador_historico_2min.py`
- `LEEME_EVALUADOR_2MIN.md`

**3.** Desde PowerShell:

```powershell
cd C:\Proyectos\TraderAssistant

# Comprueba el evaluador con datos sintéticos, sin conectarse a Internet
.\venv\Scripts\python.exe -B .\pruebas\test_evaluador_historico_2min.py

# Experimento offline sobre los seis cachés existentes
.\venv\Scripts\python.exe -B .\evaluador_historico_2min.py

# Solo NVIDIA
.\venv\Scripts\python.exe -B .\evaluador_historico_2min.py --symbol NVDA
```

Los resultados se crean en:

`C:\Proyectos\TraderAssistant\auditoria\evaluacion_2min\`

Contienen `informe_2min.md`, `resumen_2min.json` y `eventos_2min.csv` (CSV compatible con Excel).

Para un conjunto externo en CSV previamente descargado con permiso de uso, con encabezados `time,open,high,low,close,volume`:

```powershell
.\venv\Scripts\python.exe -B .\evaluador_historico_2min.py --symbol NVDA --csv "C:\ruta\mis_velas.csv" --output-dir ".\auditoria\evaluacion_nvda_ampliada"
```

El `time` debe contener segundos UNIX o ISO 8601 **con zona horaria**. Las velas deben tener intervalos UTC alineados a 60 segundos. Es responsabilidad del usuario verificar que el CSV sea de un proveedor autorizado y representativo.

## Opciones y limitaciones

- `--payout 0.86` añade **solo un escenario matemático hipotético** (+0,86 unidades por acierto y −1 por fallo o empate), no el pago ni el resultado real de IQ Option.
- El número mínimo de cinco sesiones en el reporte es **un indicador de insuficiencia**, **no** un criterio para dar una estrategia como validada. Aun con cinco sesiones, la evaluación sigue siendo descriptiva.
- El análisis original fue pensado para 1 hora y diario. Su desempeño a 1 minuto no está validado.
- Precio negociado en IEX **no es** necesariamente el precio del producto NVIDIA Blitz ni el de liquidación de IQ Option.
- No incluye spread, deslizamiento, latencia de clic, comisiones, ejecución, horario propio del producto ni empates de IQ Option.
- No busca automáticamente reglas óptimas, no aprende ni predice. No emite señales operativas al panel.

## Criterios de seguridad

No abre conexiones; no lee `Alpaca_key.txt`; no toca `venv`, Git, GUI, WebSocket, SSE, los detectores originales ni los cachés fuente. Los únicos archivos que escribe son los **resultados** en la carpeta de salida especificada.

Si la carpeta de salida contiene trabajos previos que quieras conservar, usa un `--output-dir` nuevo. Para retirar el módulo, elimina **solo los tres archivos nuevos** y, opcionalmente, la carpeta de resultados generada por esta herramienta.
