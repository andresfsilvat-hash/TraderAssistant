# TraderAssistant — Informe final de integración del objetivo principal

Fecha de cierre técnico: 2026-11-22 (Ecuador)  
Activo del motor experimental: NVIDIA / NVDA  
Instrumento de destino pendiente de validación: NVIDIA Blitz de IQ Option  
Reglas: `experimental-causal-groups-v2`  
Modo: simulación y observación; ninguna orden habilitada

## Resultado ejecutivo

Se completó el flujo técnico verificable:

`vela oficial cerrada → análisis 1m → contexto causal 1h/1d → evaluación independiente 1/2/5/10 min → publicación en panel → entrada IEX posterior → vencimiento → resultado`.

TraderAssistant puede producir `SUBE`, `BAJA` o `ESPERAR` para cada horizonte, explicar la evidencia presente, las contradicciones y lo que falta, y registrar una entrada únicamente después de que la evaluación estuvo disponible. Toda dirección aparece como **HIPÓTESIS EXPERIMENTAL — NO OPERAR**.

La integración técnica está terminada, pero la estrategia no está validada para operar: la prueba histórica posterior no demuestra ventaja consistente frente a referencias simples y todavía no existen sesiones prospectivas nuevas con las reglas v2 ni precios autorizados de liquidación de NVIDIA Blitz.

## Componentes terminados

| Componente | Implementación | Estado comprobado |
|---|---|---|
| Análisis en vivo | RSI, MACD/señal/histograma, Bollinger, patrones existentes, SMA20/SMA50 1m, tendencia, retorno, volumen y ratio de volumen | FUNCIONAL EN PRUEBAS CONTROLADAS |
| Contexto multitemporal | Adaptador local aislado; agrega 1h y 1d, volumen, SMA50 diaria y recorta en el instante analizado | FUNCIONAL; sin uso de datos futuros |
| Evidencia independiente | MACD completo cuenta como una familia; patrón, tendencia, RSI/Bollinger, volumen y contexto son grupos separados | FUNCIONAL Y AUDITABLE |
| Motor multihorizonte | Reglas distintas para 60/120/300/600 segundos; contradicciones pueden vetar | SUBE/BAJA/ESPERAR PROBADOS EN LOS CUATRO HORIZONTES |
| Simulador existente | Reutilizado; archivos v2 separados, bloqueo de instancia, entrada posterior y vencimiento desde la entrada | FUNCIONAL EN SIMULACIONES CONTROLADAS |
| Cobertura de precios | Trade exacto prioritario; respaldo con cierre de vela IEX 5s derivada solo de trades, marcado como proxy | FUNCIONAL; nunca usa bid/ask como trade |
| Panel | Evaluación, duración, detección, entrada, vencimiento, motivo, reglas, resultado y aviso NO OPERAR | FUNCIONAL EN PRUEBA JAVASCRIPT |
| Lector de resultados | Lee v2 como estado actual y conserva históricos v1 separados por versión | FUNCIONAL; no presenta vencidas como activas |
| Validador IQ Option | Exige producto NVIDIA Blitz, UTC con zona, precio válido y distingue IEX/IQ | FUNCIONAL CON CSV; datos reales pendientes |
| Evaluador histórico | 63 sesiones, corte 42/21, sin selección automática, cuatro referencias y bootstrap por sesión | EJECUTADO |

## Reglas v2 por horizonte

- **60 s:** requiere impulso MACD y patrón o reversión RSI/Bollinger concordante; tendencia 1m y contexto 1h pueden vetar.
- **120 s:** requiere impulso MACD, tendencia 1m y una confirmación adicional independiente: patrón, reversión o volumen.
- **300 s:** requiere alineación de impulso MACD, tendencia 1m y contexto 1h.
- **600 s:** requiere tendencia 1m, contexto 1h, contexto 1d y posición respecto de SMA50 diaria; el impulso no puede oponerse.

RSI o Bollinger aislados no crean dirección. Línea MACD, señal e histograma son una sola familia correlacionada. Una contradicción relevante fuerza `ESPERAR` y la justificación identifica el conflicto o dato insuficiente.

## Causalidad y tiempos

Cada análisis conserva:

- vela oficial que lo originó;
- instante de cálculo/disponibilidad;
- instante en que el aviso quedó publicado para el panel;
- dirección y duración específicas;
- entrada IEX estrictamente posterior a la detección;
- fuente de entrada y salida (`IEX_TRADE_EXACTO` o `IEX_VELA_5S_TRADE_CLOSE_PROXY`);
- vencimiento calculado desde la entrada observada;
- resultado y causa de `NO_EVALUABLE`.

`aviso_pantalla_utc` representa el instante servidor en que el aviso quedó disponible para el panel. No es una confirmación enviada de regreso por el navegador; la demora de pintura se sigue midiendo visualmente en la interfaz REALTIME.

Las simulaciones v2 se guardan separadas en:

- `simulaciones_nvda_multihorizonte_v2.csv`
- `pendientes_multihorizonte_v2.json`
- `observaciones_nvda_multihorizonte_v2.jsonl`

Los archivos anteriores no fueron eliminados ni mezclados con la nueva versión.

## Resultado histórico — 21 sesiones posteriores

Fuente completa: 63 sesiones IEX, 25.221 velas.  
Desarrollo cronológico: 42 sesiones, 2026-08-21 a 2026-10-20.  
Prueba retrospectiva posterior: 21 sesiones, 2026-10-21 a 2026-11-18.

| Duración | Señales no solapadas | ESPERAR | Omitidas por solape | Aciertos / fallos / empates | Acierto bruto | Siempre SUBE | Siempre BAJA | Última vela | Aleatoria |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 min | 406 | 6.710 | 0 | 209 / 189 / 8 | 51,478 % | 45,320 % | 52,709 % | 51,232 % | 50,000 % |
| 2 min | 575 | 6.348 | 172 | 302 / 267 / 6 | 52,522 % | 43,826 % | 55,130 % | 51,130 % | 51,130 % |
| 5 min | 440 | 5.680 | 912 | 236 / 200 / 4 | 53,636 % | 46,136 % | 52,955 % | 50,909 % | 45,909 % |
| 10 min | 185 | 6.049 | 693 | 94 / 90 / 1 | 50,811 % | 48,649 % | 50,811 % | 44,324 % | 49,189 % |

Interpretación:

- 1 minuto quedó por debajo de “siempre BAJA”.
- 2 minutos quedó por debajo de “siempre BAJA”; su intervalo de ventaja frente a esa referencia fue `[-6,425; 0,861]` puntos.
- 5 minutos mostró el mayor porcentaje bruto, pero solo 0,681 puntos sobre “siempre BAJA”; su intervalo fue `[-2,174; 4,515]` y cruza cero.
- 10 minutos igualó exactamente “siempre BAJA” en esta muestra y solo tuvo señales en 13 de las 21 sesiones por la exigencia de 50 sesiones diarias previas.
- Ningún horizonte supera concluyentemente todas las referencias.
- `automatic_best_horizon` permanece `null`.

Conclusión estadística: **SIN VENTAJA DEMOSTRADA**. Estos resultados no justifican considerar fiable una dirección ni escoger automáticamente 5 minutos.

Archivos reproducibles:

- `auditoria/motor_multihorizonte_v2_20261121/resumen_motor_multihorizonte.json`
- `auditoria/motor_multihorizonte_v2_20261121/eventos_motor_multihorizonte.csv`

## Validación prospectiva e IQ Option

La validación prospectiva v2 contiene cero grupos porque todavía no se han recopilado sesiones nuevas con estas reglas. Esto es intencional: los registros v1 permanecen históricos y no se reutilizan como si validaran v2.

Estado actual:

- `automatic_best_horizon: null`;
- IQ Option: `PENDIENTE_ARCHIVO_IQ_OPTION`;
- sesiones prospectivas v2: 0;
- estrategia: no validada.

La importación CSV exige `timestamp_utc`, `price` y `product`; rechaza timestamps sin zona, precios inválidos e instrumentos que no identifiquen explícitamente NVIDIA Blitz. También registra diferencias de precio IEX/IQ. La condición exacta de liquidación continúa `NO_VERIFICADA_EN_EXPORTACION` mientras no exista un registro autorizado que la documente.

En la revisión de documentación oficial del 2026-11-22 no se localizó una API pública documentada para descargar ticks o liquidaciones de NVIDIA Blitz. Esto es una inferencia por ausencia de documentación pública, no una afirmación de que IQ Option no posea interfaces privadas. La política oficial indica que los precios negociables son los mostrados en su plataforma y dependen de sus proveedores; además, su documentación OTC advierte que esos precios no están vinculados al dato bursátil en tiempo real y pueden diferir de otras plataformas. Por esa razón se conserva la importación CSV autorizada y no se implementó scraping ni una conexión no oficial. Fuentes: [política oficial de ejecución](https://files.iqoption.com/storage/public/5a/c3/aadc8c5ff/order_execution_policy.pdf), [guía oficial OTC](https://blog.iqoption.com/en/otc-trading-on-iq-option-how-to-trade-securities-over-the-counter/).

## Rendimiento y estabilidad

Medición directa sobre el caché NVDA existente, cinco cálculos completos:

- primer cálculo en frío: 616,99 ms;
- siguientes cálculos: 174,39–184,62 ms;
- mediana: 181,99 ms;
- límite automatizado para 500 velas: menor a 1 segundo, aprobado;
- endpoint `/api/analysis/live`: devuelve resultado en caché y no recalcula por petición;
- cálculo: ejecutado en trabajador separado, no en WebSocket ni en petición Flask;
- corrección de vela histórica: un solo recálculo;
- cambio de símbolo: descarta resultado anterior;
- fallo del analizador: REALTIME continúa y conserva estado seguro.

La latencia bursátil real de señal a pantalla no pudo medirse en una sesión activa durante este cierre, realizado en fin de semana. Las cifras anteriores son pruebas locales reproducibles, no validación de mercado activa.

## Pruebas finales

- **107 pruebas unitarias:** OK.
- **12 pruebas del núcleo REALTIME:** OK.
- **12 pruebas del análisis:** OK.
- **Interfaz de análisis:** OK.
- **Interfaz REALTIME y gráfica:** inicio, streaming, corrección y temporalidades OK.
- Flujo vela → análisis → decisión → entrada → vencimiento → resultado: OK en simulación controlada.
- SUBE, BAJA y ESPERAR en 60/120/300/600: OK.
- Entrada posterior a detección: OK.
- Recuperación de pendientes v2 sin duplicados: OK.
- Hipótesis vieja o vencida como activa: rechazada.
- `NO_EVALUABLE`: preservado con causa.
- Importación IQ con instrumento/timestamp inválido: rechazada.

Comandos principales:

```powershell
.\venv\Scripts\python.exe -B -m unittest discover -s pruebas -p 'test_*.py' -q
.\venv\Scripts\python.exe -B .\pruebas\probar_v4.py
.\venv\Scripts\python.exe -B .\pruebas\probar_analysis_live.py
node .\pruebas\probar_analysis_ui.js
node .\pruebas\probar_ui_node.js
.\venv\Scripts\python.exe -B .\evaluar_motor_multihorizonte.py --csv .\auditoria\historico_nvda_iex\nvda_iex_1min_20261118_213505_280555.csv --output-dir .\auditoria\motor_multihorizonte_v2_20261121
```

## Protección de REALTIME

Los hashes protegidos permanecen:

- `alpaca_live.py`: `10BA6B883803C5E1DB04666B3855B70542C47C47F16E544D9B8D2D501EBB8127`
- `main.py`: `67CD9EC723DAAB05E1B498FD765F46763FCA90E320C6D1AE99F7CC9AC08BE2DC`
- `screener/indicator_detector.py`: `5CCBB66A3E5CFF85B08941C5E241CC0B6717990042F4A09B299694706C3CC7E0`
- `screener/pattern_detector.py`: `B10B67AB5DFEEDADD0DF1F73F19235182C7AFFD546D1981234895868FD894546`
- `screener/scorer.py`: `99AE7B48DE29D6B5DF0CC2CEB4E2710655983518F139DDF335A331D82D142190`

No se modificaron autenticación, WebSocket, trades, quotes, SSE, construcción de velas, velas de cinco segundos, escalas, controles Línea/Volumen, configuración ni credenciales. Las pruebas originales de barras 5s y correcciones oficiales continúan aprobadas.

## Pendientes reales

1. Recopilar sesiones prospectivas nuevas v2; hoy la muestra es cero.
2. Obtener exportación autorizada y sincronizada de precios/condiciones de liquidación NVIDIA Blitz.
3. Medir latencia de recepción, evaluación y pintura durante sesiones activas.
4. Confirmar o rechazar la ventaja con sesiones nuevas; los datos actuales no la demuestran.

Estos pendientes son validación externa y evidencia futura, no funciones técnicas simuladas como terminadas.

## Respaldo y restauración

- Respaldo previo: `auditoria/respaldo_pre_objetivo_principal_20261121_070259`
- Restaurador: `auditoria/restaurar_pre_objetivo_principal_20261122.ps1`

El restaurador recupera los archivos previos, verifica sus hashes, elimina únicamente los tres archivos de código/prueba creados por esta integración y conserva todos los informes y resultados de auditoría.
