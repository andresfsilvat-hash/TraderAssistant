# Informe técnico: reutilización del scorER completo de TraderAssistant

**Fecha:** 18 de noviembre de 2026. **Fuente:** CSV de 25.221 barras Alpaca IEX del usuario, NO capturas del gráfico.

## Qué se ejecutó realmente

Se revisaron `README.md`, `devpost/prd.md`, `devpost/spec.md`, `screener/indicator_detector.py`, `screener/pattern_detector.py` y `screener/scorer.py` de la copia entregada.
El programa nuevo **importa `score_tickers()` directamente del `scorer.py` original**, no lo copia ni modifica. Conserva:
- +1 / −1 por indicadores y patrones, incluidas señales RSI, MACD, BB y patrones japoneses.
- Bono por confluencia del mismo tipo de señal en Daily y 1h.
- Confirmación o descuento por volumen de la última 1h COMPLETA frente a su promedio de 20 velas.
- Penalización de contratrend respecto de la SMA50 **diaria** (cuando ya existe historia).
- Detección OLS diaria y contexto de tendencia, donde el detector original lo permite.

Las velas diarias de la sesión presente se **excluyen** hasta su cierre de 16:00 NY. Las 1h se forman solo con los intervalos completos 09:30–10:30, ... 14:30–15:30 NY; el tramo final de 30m no se trata como una hora. Para disparos 1m se reutilizaron patrones originales y señales numéricas equivalentes a `detect_indicators()` (prueba comparativa automatizada).

## Calidad y muestra

- Velas IEX totales: 25,221. Dentro de horario regular: 24,566. Fuera de regular: 655.
- Sesiones: 63. Minutos regulares faltantes: 4. Sin registros duplicados.
- Daily completos: 59; 1h completas: 374.
- Desarrollo: 40 sesiones (2026-08-21–2026-10-16). Periodo posterior: 23 sesiones (2026-10-19–2026-11-18).
- La muestra posterior **ya se había examinado en experimentos anteriores** y por tanto NO es una prueba ciega.

## Resultados (casos independientes por política, sin solapamiento de vencimientos)

| Política | Desarrollo: casos / aciertos | Posterior: casos | Posterior: aciertos | Referencia siempre SUBE en los mismos casos |
|---|---:|---:|---:|---:|
| Screener original Daily + 1h | 55 / 50.91 % | 34 | 17 (50.00 %) | 50.00 % |
| Puntuación original + disparador 1m | 3,066 / 49.18 % | 1,573 | 772 (49.08 %) | 49.78 % |
| Señales 1m + volumen + SMA50 | 3,319 / 48.42 % | 1,557 | 765 (49.13 %) | 50.10 % |

**Intervalos descriptivos bootstrap por sesión en tramo posterior** (no corrigen selección previa del historial):

| Política | IC 95 % de acierto | IC 95 % de diferencia contra siempre SUBE (puntos) |
|---|---:|---:|
| Screener original Daily + 1h | 29.03 a 68.75 % | -19.30 a +16.22 |
| Puntuación original + disparador 1m | 47.77 a 50.61 % | -2.05 a +0.75 |
| Señales 1m + volumen + SMA50 | 46.33 a 51.75 % | -5.35 a +2.76 |

## Limitación especial: calentamiento de SMA50 diaria

Aunque el scorer es completo, los filtros Daily SMA50 y OLS tienen periodos de calentamiento. **Con 59 velas diarias completas, la SMA50 no está disponible durante las primeras 49 sesiones completas del historial.** En particular, *ningún* evento del tramo de desarrollo de 40 días cumple simultáneamente 50 Daily completas y 40 velas 1h completas. Por ello el experimento no valida una configuración totalmente calentada de forma comparable entre los dos periodos.

| Política | Casos con SMA50 y 1h suficientemente calentadas en tramo posterior | Acierto descriptivo | Sesiones |
|---|---:|---:|---:|
| Screener original Daily + 1h | 13 | 38.46 % | 9 |
| Puntuación original + disparador 1m | 702 | 49.43 % | 9 |
| Señales 1m + volumen + SMA50 | 552 | 47.64 % | 9 |

El subconjunto calentado ocupa unas 9 sesiones posteriores; **no es una validación suficiente** y no debe utilizarse para seleccionar reglas.

## Comparación e interpretación

- El scoring original Daily+1h acertó 17/34 en tramo posterior: **50,00 %**, igual al comparador siempre SUBE en esos mismos 34 casos. El intervalo de confianza es muy amplio por escasa muestra.
- La adaptación completa a 1m acertó 772/1.573 (**49,08 %**), por debajo de siempre SUBE (**49,78 %**) en los mismos casos.
- La variante 1m + filtros tampoco supera la referencia en el tramo posterior (**49,13 %** contra **50,10 %**).
- Los episodios temporales dentro de un mismo día no son ensayos independientes; se reportan intervalos por día, no por vela. Las políticas tienen distinta cobertura y no es válido compararlas como si fueran exactamente las mismas oportunidades.
- El criterio de entrada usa el primer precio reportado en el bucket siguiente, y no contempla latencia, spreads, comisiones, payout ni el feed de NVIDIA Blitz/IQ Option.

## Pruebas y efectos secundarios

- **14/14 pruebas nuevas** aprobadas, incluyendo score original, MTF, volumen alto/bajo, SMA50, equivalencia de disparadores 1m, no anticipación del contexto futuro, hourly completas, 120s y no solapamiento.
- **16/16 pruebas previas** del validador offline aprobadas.
- `scorer.py` original leído desde fuente, no reescrito ni reemplazado. SHA-256 de la copia fuente comprobada: `99ae7b48de29d6b5df0cc2ceb4e2710655983518f139ddf335a331d82d142190`.
- No se accedió a cuentas, claves, WebSocket ni a la interfaz; no se ejecutaron órdenes.

## Decisión

**NO ACTIVAR SUBE/BAJA** en el panel como señal de operación. Los resultados no muestran ventaja reproducible. Los indicadores sí están calculándose y el motor original ya se ha sometido a prueba real con datos IEX sin modificar la gráfica.

Para evaluar de verdad la SMA50 diaria se necesita un historial anterior adicional al disponible, y para validar operaciones deben añadirse **sesiones futuras no revisadas previamente**, precio/horario comparable a IQ Option y registro de señales en tiempo real con evaluación simulada.

## Reproducción

```powershell
cd C:\Proyectos\TraderAssistant
.\venv\Scripts\python.exe -B .\pruebas\test_scoring_completo_2min.py
.\venv\Scripts\python.exe -B .\evaluar_scoring_completo_nvda_2min.py --csv ".\auditoria\historico_nvda_iex\nvda_iex_1min_20261118_213505_280555.csv"
```
