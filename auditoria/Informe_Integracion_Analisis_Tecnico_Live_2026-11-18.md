# Integración segura del análisis técnico en REALTIME

Fecha: 2026-11-18  
Proyecto: `C:\Proyectos\TraderAssistant`  
Estado: implementado; validación con sesión Alpaca activa pendiente

## Resultado ejecutivo

Se incorporó una capa de observación técnica de 1 minuto que consume exclusivamente una copia de las velas oficiales cerradas que ya mantiene REALTIME. No abre otra conexión WebSocket o REST, no modifica las velas, no escribe configuración y no contiene rutas de órdenes. La decisión operativa permanece forzada a **ESPERAR**; entrada, duración, salida y señal operativa siguen en `null`/“Pendiente de validación”.

El análisis reutiliza directamente `detect_patterns(df, "1m")` y `detect_indicators(df, "1m")`. Del `scorer` histórico sólo reutiliza `_classify()` para clasificar evidencia textual; no ejecuta `score_tickers()` sobre datos live porque ese algoritmo incorpora criterios diarios/1h, volumen 1h, SMA diaria y OLS diario que no son válidos como señal operativa de 1 minuto.

## Arquitectura implementada

1. REALTIME sigue siendo el único propietario de Alpaca, sus suscripciones y su caché.
2. Un monitor de baja frecuencia observa, bajo el bloqueo existente y durante una copia breve, símbolo, revisión y las últimas 500 velas oficiales.
3. Un SHA-256 del OHLCV evita cálculos repetidos. Sólo una nueva vela oficial o una corrección real del OHLCV genera trabajo.
4. RSI(14), MACD(12,26,9), Bollinger(20,2) y patrones se calculan en un `ProcessPoolExecutor` de un solo trabajador, fuera de Flask y del hilo WebSocket.
5. `/api/analysis/live` sólo devuelve una copia del último resultado en memoria; nunca calcula indicadores durante una petición.
6. Un resultado perteneciente a un símbolo anterior se descarta mediante símbolo + generación + digest.
7. La UI consulta el resultado únicamente cuando cambia la última vela oficial o `series_revision`; los ticks intermedios no disparan análisis.
8. La antigüedad se actualiza al leer el resultado, sin recalcular indicadores, para no mostrar como reciente una vela que dejó de actualizarse.

## Archivos

| Archivo | Cambio |
|---|---|
| `analysis_live.py` | Nuevo servicio aislado, conversión OHLCV, cálculo, caché, proceso trabajador y endpoint de sólo lectura. |
| `app.py` | Cinco líneas para registrar la extensión después de REALTIME. |
| `ui/live.html` | Extensión compacta del panel existente y consulta selectiva al endpoint. Se preservaron gráfico, 5s/1m/5m, Línea y Volumen. |
| `pruebas/probar_analysis_live.py` | Pruebas de datos, indicadores, patrones, aislamiento, deduplicación, correcciones, cambio de símbolo, errores y regresión histórica. |
| `pruebas/probar_analysis_ui.js` | Prueba DOM/JS sin red: panel, gráfico preservado y consultas sólo ante revisión oficial. |
| `pruebas/probar_analysis_process.py` | Prueba del proceso real, endpoint cacheado, página `/live` y latencia del snapshot. |
| `auditoria/restaurar_pre_analisis_live_20261118.ps1` | Restauración exacta con guardas SHA-256. |

No se modificaron `main.py`, `alpaca_live.py`, `requirements.txt`, `config.json`, credenciales ni los archivos del motor histórico bajo `screener/`.

## Interpretación mostrada

- Sesgo: Alcista, Bajista, Neutral, Contradictorio o Datos insuficientes.
- Evidencia: patrones e indicadores emitidos por los detectores originales.
- Valores numéricos: RSI, MACD, señal/histograma MACD y bandas de Bollinger.
- Trazabilidad: símbolo, timeframe 1m, hora UTC, hora Ecuador, fuente, cantidad de filas, revisión y antigüedad.
- Seguridad semántica: el texto aclara que es interpretación técnica y no señal de entrada.
- Decisión: siempre **ESPERAR**.

## Pruebas y resultados reproducibles

### Línea base anterior al cambio

| Prueba | Resultado |
|---|---:|
| Primera lectura de `/live` | HTTP 200; 30,672 ms |
| `/api/alpaca/live` en prueba aislada | HTTP 200; 11,475 ms |
| 1.000 llamadas a `LiveFeed.snapshot()` con 500 barras | mediana 0,6487 ms; p95 1,1867 ms; máximo 1,443 ms |

### Suite de integración ejecutada con las dependencias disponibles al inicio

| Comando | Resultado |
|---|---|
| `python pruebas\probar_analysis_live.py` | 10/10 pruebas OK; 0,889 s (antes de añadir la comprobación final del scorer y envejecimiento, ambas revisadas estáticamente). |
| `node pruebas\probar_analysis_ui.js` | OK; 2 consultas de análisis, 3 actualizaciones live, 61 velas; repetida al cierre con el mismo resultado. |
| `python pruebas\probar_analysis_process.py` | OK; proceso real; estado `ready`; 500 filas; cálculo 9,258 ms; endpoint mediana 0,2626 ms, p95 0,4585 ms; un solo cálculo. |
| Parseo AST Python | OK para `analysis_live.py`, `app.py` y pruebas Python. |
| Parseo del restaurador PowerShell | OK. |
| Hashes de archivos protegidos | OK, sin variación. |

La prueba unitaria incluye comparación de RSI y MACD con una implementación Pandas independiente, exclusión de provisional, orden/deduplicación, sustitución por corrección, ausencia de OLS en 1m, Hammer del detector original, datos insuficientes, fallo controlado del analizador, descarte entre símbolos y límite de un segundo con 500 velas.

### Condición del entorno al cierre

En la repetición final, `C:\Python313\python.exe` dejó de disponer de `Flask`, `ta` y `websockets`, aunque están declarados en `requirements.txt`. Los comandos fallan antes de cargar el código con `ModuleNotFoundError`. No se instalaron dependencias por la restricción expresa. Esta condición también impide ejecutar la suite histórica `pruebas/probar_v4.py` (`websockets` ausente) y arrancar la aplicación original; no es causada por la integración.

Por ello, la medición añadida de regresión final del p95 (límite 1,4240 ms, equivalente a +20 %) quedó preparada pero no pudo repetirse en el intérprete actual. La medición previa y el diseño muestran que el endpoint es cacheado, pero la aceptación definitiva de latencia se mantiene pendiente hasta restaurar el entorno ya previsto por `requirements.txt`.

## Estado de requisitos

| Requisito | Estado | Evidencia / observación |
|---|---|---|
| Sólo velas oficiales cerradas 1m | Verificado por simulación | Filtrado explícito de `provisional`; fuente `feed.official`. |
| Sin nueva conexión Alpaca | Verificado por código | El módulo recibe `_feed`; no contiene cliente HTTP/WebSocket. |
| Reutilizar motor existente | Verificado | Llamadas directas a detectores originales; hashes sin cambios. |
| No convertir scorer histórico en señal live | Verificado | Sólo `_classify`; decisión forzada a ESPERAR. |
| No bloquear Flask/WebSocket | Verificado por diseño y prueba previa | Proceso único; endpoint cacheado; copia breve bajo lock. |
| Recalcular sólo al cerrar/corregir vela | Verificado por simulación | Digest y marcador; prueba de no repetición y corrección. |
| Multiactivo sin mezcla | Verificado por simulación | Generación por símbolo y descarte de resultado anterior. |
| Tolerancia a fallo del analizador | Verificado por simulación | Error aislado; REALTIME no cambia; conserva último resultado válido. |
| Panel compacto sin perder controles | Verificado por prueba DOM | Gráfico, escalas, Línea y Volumen permanecen. |
| Sesión Alpaca activa real | **Pendiente de validación real** | No se abrieron conexiones ni se leyeron credenciales en esta fase. |
| Rendimiento final con entorno productivo | **Pendiente de validación real** | Repetir p95 al recuperar dependencias, con límite de +20 %. |

## Riesgos residuales

1. El proceso trabajador añade memoria equivalente a un intérprete Python con Pandas/TA. Debe medirse en el equipo productivo durante una sesión prolongada.
2. IEX puede tener minutos sin operaciones y no representa el mercado consolidado; el panel marca la vela desactualizada, pero no debe interpretarse esa ausencia como señal técnica.
3. Los detectores originales fueron diseñados para etiquetas configurables y funcionan con `1m`, pero su calidad estratégica no está validada. Por eso no se habilitó LONG/SHORT.
4. Si el entorno no contiene las dependencias de `requirements.txt`, falla también la aplicación preexistente. No se incorporó un fallback matemático distinto porque rompería la reutilización exacta solicitada.

## Validación real pendiente

Con el entorno de dependencias restaurado y durante mercado activo:

1. Abrir TraderAssistant normalmente y confirmar una sola conexión Alpaca.
2. Para NVDA, SPY, QQQ, MSFT, AAPL y AMD, esperar dos cierres oficiales consecutivos.
3. Confirmar que `last_candle_time`, símbolo y `feed_revision` del análisis coinciden con REALTIME.
4. Cambiar rápidamente de símbolo mientras el trabajador calcula y verificar que nunca aparece el resultado anterior.
5. Registrar durante 30–60 minutos latencia feed→gráfico, p95 de `snapshot`, CPU y memoria del proceso principal y trabajador.
6. Aceptar sólo si no hay 406 adicional, no hay segunda conexión, no hay pérdida de ticks y el p95 de `snapshot` no supera 1,4240 ms en condiciones comparables.

## Restauración

Respaldo verificado: `auditoria\respaldo_pre_analisis_live_20261118_144107`.

Con TraderAssistant cerrado, ejecutar desde PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\auditoria\restaurar_pre_analisis_live_20261118.ps1
```

El script verifica primero todos los hashes de la integración. Si algún archivo fue modificado posteriormente, aborta sin sobrescribirlo. Restaura `app.py` y `ui/live.html`, elimina únicamente los cuatro archivos nuevos de implementación/pruebas y conserva respaldo e informes.

## Conclusión

La capa técnica está integrada de manera no operativa, desacoplada y reversible. Las pruebas de lógica, UI y proceso ejecutadas inicialmente fueron satisfactorias y el motor REALTIME/histórico permanece intacto. La aprobación para uso observado debe quedar condicionada a recuperar las dependencias ya declaradas y completar la prueba de sesión real y rendimiento prolongado. No se recomienda habilitar LONG/SHORT a partir de estos resultados.
