# TraderAssistant — Fase 6: motor experimental multihorizonte

Fecha: 19 de noviembre de 2026  
Activo del experimento: NVDA  
Horizontes: 120, 300 y 600 segundos  
Estado operativo: **ESPERAR**  
Estado de las hipótesis: **EXPERIMENTAL / SOLO SIMULACIÓN**

## Resultado

Se integró un motor experimental separado del análisis técnico original y de REALTIME. Una misma evaluación genera, cuando hay confluencia, la misma hipótesis para 2, 5 y 10 minutos. Cada horizonte registra entrada, vencimiento, salida, resultado y estadísticas de manera independiente.

No se modificaron `alpaca_live.py`, `analysis_live.py`, `main.py`, los detectores originales ni `screener/scorer.py`. Tampoco se modificó ningún bloque del gráfico, sus series, construcción de velas, escalas, SSE, selección de timeframe, Línea o Volumen.

## Regla experimental congelada v1

Versión: `experimental-confluence-v1`.

1. El análisis debe corresponder a NVDA, una vela oficial cerrada, estado `ready` y no obsoleto.
2. RSI alto/bajo y reversión Bollinger aislados son contexto; nunca generan BAJA/SUBE por sí solos.
3. Se exige un disparador direccional del motor existente: patrón japonés direccional o crossover MACD.
4. SUBE requiere disparador alcista e histograma MACD positivo.
5. BAJA requiere disparador bajista e histograma MACD negativo.
6. Evidencia mixta, impulso contrario o contexto 1h/1d suficiente y opuesto producen ESPERAR.
7. El contexto 1h/1d puede vetar, pero nunca crear, una hipótesis.
8. No existe puntuación de confianza ni umbral optimizado retrospectivamente.

Esto corrige específicamente los casos observados: RSI >70 con MACD alcista ya no se convierte automáticamente en BAJA; RSI <30 con MACD bajista tampoco se convierte automáticamente en SUBE.

## Separación de responsabilidades

- `analysis_live.py`: conserva el análisis original cacheado de velas oficiales 1m.
- `decision_engine_experimental.py`: interpreta de forma conservadora una copia del resultado, sin mutarlo.
- `simulador_prospectivo_nvda_2min.py`: reutilizado y ampliado; observa endpoints locales y administra 120/300/600 s.
- `simulation_results.py`: lectura local cacheada y tolerante a archivos incompletos; no calcula indicadores.
- `app.py`: registra únicamente el endpoint de lectura `/api/simulation/live`.
- `ui/live.html`: añade campos compactos dentro del panel existente y consulta el endpoint cada dos segundos.

## Semántica temporal

- La detección se produce sólo después de una nueva vela oficial cerrada.
- La entrada requiere un trade IEX estrictamente posterior a la detección y dentro de 30 segundos.
- Sin trade válido se conserva `ENTRADA PENDIENTE` y finalmente `NO_EVALUABLE`.
- Los vencimientos se calculan desde la entrada real registrada: entrada +120, +300 o +600 s.
- La salida requiere un trade IEX entre el vencimiento y los ocho segundos posteriores.
- Sin salida válida el caso es `NO_EVALUABLE`, nunca un fallo inventado.
- No se abren hipótesis cerca del cierre si el horizonte más largo cruzaría la sesión regular.

## Archivos y compatibilidad

Los registros nuevos usan nombres distintos y no sobrescriben los históricos de 120 s:

- `simulaciones_nvda_multihorizonte.csv`
- `pendientes_multihorizonte.json`
- `observaciones_nvda_multihorizonte.jsonl`
- `estado_simulador.json`
- `simulador_multihorizonte.lock`

Los históricos anteriores siguen visibles con la versión `legacy-direct-bias-v0`, pero sus estadísticas no se mezclan con `experimental-confluence-v1`.

## Prevención de duplicados

Al iniciar la fase se detectaron dos instancias antiguas del simulador escribiendo en el mismo directorio. Ambas fueron detenidas después de persistir sus pendientes. La nueva versión usa un archivo de bloqueo exclusivo por directorio y rechaza una segunda instancia activa. También deduplica pendientes por ID y omite IDs ya finalizados.

No se inició automáticamente el nuevo simulador. El panel muestra `SIMULADOR DETENIDO` y no presenta un registro antiguo como activo.

## Estadística y referencias

Cada combinación horizonte + versión mantiene por separado:

- hipótesis generadas;
- entradas registradas;
- aciertos;
- fallos;
- empates;
- no evaluables;
- simulaciones activas;
- referencia básica “siempre SUBE” sobre casos con entrada y salida observables.

La lectura de los registros antiguos de 120 s encontró 17 casos generados, 14 con entrada, 6 aciertos, 5 fallos, 5 no evaluables y un pendiente antiguo. En los 11 casos evaluables, la referencia siempre SUBE acertó 4. Son datos de la regla anterior, basados en IEX, y no validan la regla nueva ni IQ Option.

No existen aún resultados prospectivos nuevos suficientes para 300/600 s. Por diseño, el panel no elige ni etiqueta automáticamente un horizonte como “mejor”. Esa comparación queda condicionada a sesiones nuevas y a una muestra suficiente por versión.

## Pruebas

| Grupo | Resultado |
|---|---:|
| Motor experimental + simulador multihorizonte | 34/34 |
| Evaluadores históricos y scoring existentes | 43/43 |
| Análisis técnico live | 12/12 |
| REALTIME v4 e instaladores | 12/12 |
| UI técnica + panel de simulación | OK |
| UI/streaming/correcciones/timeframes anterior | OK |
| Proceso real del analizador | OK |

Casos cubiertos: RSI alto/MACD alcista, RSI bajo/MACD bajista, contradicciones, datos insuficientes, confluencia alcista/bajista, contexto 1h/1d opuesto, entrada posterior, tres vencimientos, cierres independientes, falta de entrada/salida, recuperación, JSON parcial, duplicados, bloqueo de segunda instancia, otro activo, premercado, cierre, archivos históricos separados y preservación por SHA-256 de REALTIME.

`pruebas/v4_live.js` no es un ejecutable de prueba autónomo: es código que requiere DOM y falla si se invoca directamente con Node. Las pruebas DOM válidas son `probar_ui_node.js` y `probar_analysis_ui.js`, ambas aprobadas.

## Rendimiento

Línea base previa de `LiveFeed.snapshot()`: p95 1,1867 ms.  
Después de Fase 6, prueba aislada: mediana 0,4278 ms; p95 1,1820 ms.  
Lector cacheado de resultados, 1.000 llamadas directas: mediana 0,9853 ms; p95 2,2330 ms.

Prueba real temporal con mercado abierto:

- `/live`: HTTP 200.
- Alpaca: `conectado`, feed `iex`, símbolo NVDA.
- Muestra observada: 36 trades y 1.642 quotes.
- 499 velas oficiales disponibles.
- análisis: `ready`; decisión operativa: `ESPERAR`.
- rutas 120/300/600: HTTP correcto; simulador detenido.
- `/api/alpaca/live`: mediana 30,469 ms; p95 52,549 ms.
- `/api/simulation/live`: mediana 9,569 ms; p95 31,630 ms bajo servidor Flask de depuración.

El p95 de REALTIME fue menor que la medición activa previa de esta fase (71,357 ms). No se observó bloqueo del streaming mientras se consultó repetidamente el endpoint de simulación.

## Contexto 1h/1d

Los evaluadores históricos existentes mantienen la construcción sin anticipación de contexto 1h y diario cuando existen buckets completos. El motor experimental acepta ese contexto sólo si llega marcado como suficiente y lo usa exclusivamente como veto.

El payload live actual de `analysis_live.py` no contiene todavía contexto 1h/1d y sólo conserva hasta 500 velas 1m. Para proteger el analizador original y evitar llamadas pesadas a Yahoo dentro del flujo live, no se inventó ni forzó contexto insuficiente. En live, esta parte queda explícitamente pendiente de una fuente cacheada y validada.

## Limitaciones

1. IEX no es mercado consolidado y puede omitir actividad de otras bolsas.
2. Los trades IEX no son precios de entrada o liquidación de NVIDIA Blitz en IQ Option.
3. La ventana de ocho segundos puede producir no evaluables en minutos con poca actividad IEX.
4. No se validan feriados o cierres anticipados dentro del simulador; el panel principal conserva el reloj de Alpaca como autoridad de mercado.
5. No hay muestra prospectiva nueva suficiente para comparar consistencia de 2/5/10 minutos.
6. El simulador sigue siendo un proceso independiente. El bloqueo y heartbeat permiten administrarlo con un supervisor futuro, pero no se añadió inicio automático ni control de procesos desde la web.

## Inicio manual controlado

Con TraderAssistant abierto y verificando que no existe otra instancia:

```powershell
.\venv\Scripts\python.exe -B .\simulador_prospectivo_nvda_2min.py --horizons 120,300,600 --output-dir .\auditoria\prospectivo_nvda_multihorizonte
```

No ejecutar simultáneamente el comando antiguo que apunta a `prospectivo_nvda_2min_sesion_regular`.

## Restauración

Respaldo: `auditoria\respaldo_pre_fase6_multihorizonte_20261119_101906`.

Con TraderAssistant y simulador cerrados:

```powershell
powershell -ExecutionPolicy Bypass -File .\auditoria\restaurar_pre_fase6_multihorizonte_20261119.ps1
```

El restaurador valida hashes antes de actuar, restaura los archivos modificados, elimina sólo los tres archivos nuevos de código/prueba y conserva históricos e informes.

## Conclusión

El simulador y el panel funcionan con selección 2/5/10 minutos sin alterar el gráfico o REALTIME. La regla problemática basada en RSI aislado fue reemplazada por una confluencia explícita y conservadora. La implementación está preparada para recoger sesiones nuevas, pero todavía no existe evidencia para declarar superior ninguno de los tres horizontes ni para convertir una hipótesis en decisión operativa.
