# Auditoría previa — integración segura del análisis técnico LIVE

Fecha: 2026-11-18 14:41 UTC-5  
Proyecto: `C:\Proyectos\TraderAssistant`

## Estado observado

- El árbol de trabajo ya contiene modificaciones y numerosos archivos no rastreados; no se realizará reset, limpieza ni commit.
- El UI activo (`ui/live.html`, SHA-256 `5EC5B7B11A8275D4CBCAF173B6BFA31EEF2DAD2784962271F895AEA63EECCD04`) contiene el panel visual seguro, botones Línea/Volumen y el ajuste visual de escala 5s. Deben preservarse.
- El backend REALTIME activo es `alpaca_live.py` SHA-256 `10BA6B883803C5E1DB04666B3855B70542C47C47F16E544D9B8D2D501EBB8127`.
- Línea base aislada: `/live` HTTP 200 (30,672 ms en primera lectura), `/api/alpaca/live` HTTP 200 (11,475 ms), `LiveFeed.snapshot()` con 500 velas: mediana 0,6487 ms, p95 1,1867 ms, máximo 1,443 ms en 1000 iteraciones.

## Inventario reutilizable

### `screener.indicator_detector`

- `detect_indicators(df, timeframe_label)`: reutilizable con `timeframe_label="1m"` y velas oficiales cerradas.
- MACD: 12/26/9; Bollinger: 20, 2 desviaciones; RSI: 14, umbrales 30/70.
- Requiere 40 filas para su API pública (`MIN_ROWS`).
- `_ols_trend_reversal` se excluye automáticamente si la etiqueta no contiene `daily`; por tanto OLS no se trasladará a 1m.
- Los valores numéricos RSI/MACD/Bollinger se pueden calcular con `ta` usando exactamente las constantes del módulo, sin duplicar reglas de señal.

### `screener.pattern_detector`

- `detect_patterns(df, "1m")`: reutilizable directamente.
- Ocho patrones existentes: Hammer, Shooting Star, Bullish/Bearish Engulfing, Morning/Evening Star y Bullish/Bearish Doji.
- La API opera sobre la última vela completa y acepta cualquier etiqueta intradía.

### `screener.scorer`

- `score_tickers()` completo **no se reutilizará** para 1m: incorpora alineación diaria/1h, volumen 1h, SMA50 diaria y contexto OLS diario.
- Solo `_classify(signal)` es reutilizable como clasificador de polaridad de los nombres emitidos por los detectores. No se expondrá score LONG/SHORT.

### `screener.data_fetcher`

- No es necesario para LIVE: usa Yahoo Finance y marcos diario/1h. El adaptador consumirá únicamente las barras oficiales ya presentes en memoria en Alpaca.

## Arquitectura aprobada

- Nuevo `analysis_live.py`, sin nuevas conexiones Alpaca.
- Lectura breve y consistente de una copia de `_feed.official` bajo el lock existente; nunca modifica esos objetos.
- Monitor ligero detecta únicamente nueva vela oficial/corrección mediante símbolo, último timestamp y `series_revision`.
- Cálculo en `ProcessPoolExecutor(max_workers=1)`; el proceso worker no inicia otro coordinador.
- Resultado cacheado; `/api/analysis/live` solo devuelve el último estado, sin calcular indicadores.
- Resultado de símbolo anterior se descarta mediante generación/token.
- `app.py` requiere un registro mínimo del nuevo módulo. No se modifican rutas históricas.
- `ui/live.html` consulta el resultado cacheado y actualiza únicamente el panel; no toca SSE, WebSocket, gráfico, overlays ni selección de activos.

## Archivos previstos

- Nuevo: `analysis_live.py`.
- Nuevo: `pruebas/probar_analysis_live.py`.
- Nuevo: `pruebas/probar_analysis_ui.js`.
- Modificación mínima: `app.py` (registro de ruta/servicio).
- Modificación localizada: `ui/live.html` (contenido del panel y consulta del endpoint).
- Sin cambios: `alpaca_live.py`, `main.py`, `requirements.txt`, `screener/`, configuración y credenciales.

## Respaldo

`auditoria/respaldo_pre_analisis_live_20261118_144107/`

