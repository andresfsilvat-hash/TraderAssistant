# Auditoría independiente de resultados — TraderAssistant NVDA, 2 minutos
**Fecha:** 18 de noviembre de 2026
**Fuente exclusiva:** `Resultados_NVDA_63_Sesiones.zip` proporcionado por el usuario (`eventos_2min.csv`, `resumen_2min.json`, `informe_2min.md`), más lectura del evaluador previamente compartido para aclarar su metodología.
**SHA-256 de `eventos_2min.csv`:** `cb07e3e8239a36895cda467020e7222c8f6499474ba14d2734a65b1ac7c755eb`
**Alcance:** diagnóstico retrospectivo. No es entrenamiento de un modelo, simulación de ejecución ni validación de operaciones reales.

## Resumen ejecutivo

| Métrica | Valor |
|---|---:|
| Sesiones bursátiles | 63 |
| Eventos candidatos con resultado | 10,784 |
| Eventos no solapados (métrica principal) | 7,167 |
| Aciertos del evaluador | 3,530 |
| Fallos del evaluador | 3,549 |
| Empates del evaluador | 88 |
| Tasa de acierto global, empates no acertados | 49.25 % |
| Acierto del comparador «última vela», sin filtrar | 47.27 % |
| Eventos con última vela sin dirección (doji exacto) | 307 |
| Casos con ambos métodos direccionales | 6,860 |
| Evaluador en casos comparables | 49.27 % |
| Última vela en casos comparables | 49.33 % |
| Referencia «siempre SUBE» sobre los casos seleccionados | 49.95 % |

**Hallazgo metodológico principal:** la aparente ventaja de 49,25 % frente al 47,27 % de la última vela no resiste una comparación equilibrada. En 307 eventos seleccionados la última vela era un empate, de modo que no proponía SUBE ni BAJA. Al excluir esos eventos de **ambos** métodos, se obtiene 49,27 % para el evaluador frente a 49,33 % para el comparador. No hay una mejora observable en condiciones comparables.

Como medida orientativa de incertidumbre, al remuestrear 10.000 veces las **63 sesiones completas** (no los eventos como observaciones independientes), la tasa del evaluador en casos comparables quedó en 48.02–50.50 % y la diferencia frente a la última vela en -1.21–+1.12 puntos porcentuales. Son intervalos descriptivos por bootstrap, no garantía predictiva.

## Desglose de indicadores únicos

Solo se muestran eventos no solapados con **una señal** para aislar cada detector; el resto combina indicadores, por lo que sus resultados no son atribuibles a una sola señal. Las tasas son observadas en esta misma muestra; no se han probado independientemente.

| Señal original | Casos | Aciertos | Acierto | Primeras 44 sesiones | Últimas 19 sesiones |
|---|---:|---:|---:|---:|---:|
| Hammer | 744 | 365 | 49.06 % | 49.91 % (541) | 46.80 % (203) |
| Shooting Star | 707 | 340 | 48.09 % | 47.84 % (510) | 48.73 % (197) |
| Bullish Engulfing | 697 | 336 | 48.21 % | 46.80 % (438) | 50.58 % (259) |
| Bearish Engulfing | 663 | 320 | 48.27 % | 48.48 % (460) | 47.78 % (203) |
| MACD bearish crossover | 522 | 269 | 51.53 % | 50.99 % (353) | 52.66 % (169) |
| MACD bullish crossover | 515 | 254 | 49.32 % | 51.16 % (344) | 45.61 % (171) |
| RSI oversold <30 | 505 | 266 | 52.67 % | 51.19 % (336) | 55.62 % (169) |
| Lower BB mean-reversion | 454 | 237 | 52.20 % | 52.30 % (304) | 52.00 % (150) |
| Upper BB mean-reversion | 420 | 193 | 45.95 % | 44.98 % (309) | 48.65 % (111) |
| RSI overbought >70 | 386 | 189 | 48.96 % | 45.67 % (289) | 58.76 % (97) |
| Bullish Doji | 221 | 108 | 48.87 % | 47.74 % (155) | 51.52 % (66) |
| Bearish Doji | 213 | 110 | 51.64 % | 54.90 % (153) | 43.33 % (60) |
| Morning Star | 150 | 74 | 49.33 % | 45.63 % (103) | 57.45 % (47) |
| Evening Star | 139 | 68 | 48.92 % | 43.88 % (98) | 60.98 % (41) |

Los mejores porcentajes puntuales entre señales únicas con muestras de varios cientos de casos aparecen, por ejemplo, en RSI oversold y Lower BB; ninguno constituye por sí solo una señal validada. Examinar múltiples indicadores y escoger el que más acertó en estos datos introduciría sesgo de selección.

## Confluencia (cantidad de señales)

| Señales simultáneas | Casos seleccionados | Aciertos | Porcentaje |
|---|---:|---:|---:|
| 1 | 6,336 | 3,129 | 49.38 % |
| 2 | 767 | 365 | 47.59 % |
| 3 | 63 | 36 | 57.14 % |
| 4 | 1 | 0 | 0.00 % |

Con esta lógica, dos señales simultáneas no proporcionaron una mejor tasa de aciertos que una. El grupo de tres señales tiene muy pocos casos para considerar estable su porcentaje.

## Desglose por hora relativa a apertura de NY (9:30 ET)

Se utiliza la hora **relativa a la apertura de Nueva York** y no la hora fija de Ecuador, porque el cambio estacional de horario en EE. UU. desplaza la apertura una hora vista desde Ecuador.

| Tramo NY | Casos | Aciertos | Porcentaje |
|---|---:|---:|---:|
| Minutos 000–060 desde apertura | 1,104 | 555 | 50.27 % |
| Minutos 060–120 desde apertura | 1,101 | 541 | 49.14 % |
| Minutos 120–180 desde apertura | 1,094 | 545 | 49.82 % |
| Minutos 180–240 desde apertura | 1,096 | 560 | 51.09 % |
| Minutos 240–300 desde apertura | 1,102 | 511 | 46.37 % |
| Minutos 300–360 desde apertura | 1,106 | 561 | 50.72 % |
| Minutos 360–390 desde apertura | 564 | 257 | 45.57 % |

Los últimos 30 minutos (minutos 360–390) presentan un porcentaje menor en este historial, pero usar esa observación para modificar la estrategia requeriría validación en sesiones posteriores.

## Periodos cronológicos (solo diagnóstico, NO prueba fuera de muestra)

| Periodo | Sesiones | Eventos | Aciertos | Tasa |
|---|---:|---:|---:|---:|
| Primeras 44 sesiones | 44 | 4,979 | 2,433 | 48.87 % |
| Últimas 19 sesiones | 19 | 2,188 | 1,097 | 50.14 % |

Esta división se hizo para describir estabilidad histórica. **No constituye validación fuera de muestra**: no se fijó ni entrenó previamente una regla sobre las primeras sesiones para después probarla a ciegas en las siguientes.

## Auditoría de trazabilidad y obstáculos para señales de entrada reales

1. **Proxies de ejecución:** el evaluador toma la apertura de la vela siguiente como entrada y la apertura de la vela +120 s como salida. El precio de apertura de un bucket puede corresponder a una operación posterior al segundo exacto; el cierre oficial de una vela puede publicarse después del inicio de la siguiente. No está demostrada la posibilidad de capturar esos precios después de recibir la señal.
2. **Mercados distintos:** se mide NVIDIA mediante agregados IEX, no NVIDIA Blitz ni los precios con los que IQ Option liquidaría SUBE/BAJA. No se puede transferir este porcentaje de acierto a la plataforma de destino.
3. **Campo «stale» histórico:** el texto de muchas señales contiene `⚠ stale`; el detector original compara la fecha de cada vela retrospectiva contra la fecha actual al generar la etiqueta. Es una advertencia de presentación que aparece naturalmente al reproducir históricos; no demuestra por sí misma que la señal sea inválida. En este archivo, aproximadamente el 98 % de eventos seleccionados incluyen dicha etiqueta.
4. **Sin valores completos:** el CSV guarda los nombres de señales y, en algunos casos, el RSI redondeado; no guarda las series completas y los valores continuos de MACD, Bandas de Bollinger, ATR o contexto de volumen. Con este ZIP sí se puede desglosar rendimiento por familia de señal, pero no comprobar filtros numéricos finos ni reconstruir todas las trayectorias históricas.
5. **Múltiples comparaciones:** elegir después de ver los datos el mejor indicador, horario o combinación inflaría las expectativas. La siguiente estrategia debe definir reglas en una muestra de desarrollo y evaluarlas **sin ajustes** en sesiones futuras y, posteriormente, en simulación con precios comparables a IQ Option.
6. **Riesgo y pagos:** sin payout real, reglas de empate, comisiones, límites de entrada y precio liquidable, no se puede convertir la tasa de acierto en rendimiento financiero real.

## Recomendación para la siguiente fase (sin tocar realtime)

**No conectar todavía el evaluador al panel como avisador de entradas.** Primero corregir la evaluación de la referencia (abstención en dojis), registrar latencia real de disponibilidad de velas y obtener el CSV histórico OHLCV original de 25.221 barras para disponer de indicadores numéricos y reproducir pruebas temporales con entradas ejecutables. Mantener la fase siguiente completamente **offline**, con separación cronológica de desarrollo y validación por día, un conjunto pequeño de reglas predefinidas, control de comparaciones múltiples y medición explícita del porcentaje de abstenciones. Una estrategia que no supere referencias comparables y condiciones económicas debe seguir mostrando ESPERAR.

## Integridad y cambios

El análisis únicamente leyó los archivos del ZIP recibido y el código del evaluador disponible en la conversación. No modificó los archivos instalados en `C:\Proyectos\TraderAssistant`, no abrió conexiones con Alpaca, no consultó credenciales ni alteró el WebSocket, el panel o el gráfico.
