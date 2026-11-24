## Ronda 10 — Observación técnica cripto, hipótesis y reloj de prueba (2026-11-24)

Después de que el usuario confirmó en su PC WebSocket suscrito, operaciones y cotizaciones recientes de BTC/USD, se agregó `engine/crypto_observacion_v5.py` y `GET /api/crypto/analisis`, totalmente separados del análisis NVDA. Acepta únicamente BTC/USD, ETH/USD y SOL/USD desde `Alpaca Crypto US`; no comparte estadísticas, precio, supuestas ventajas ni habilitación de trading con IQ Option.

Calidad de entrada: exige suscripción confirmada; último mensaje recibido con menos de 15 s y reloj coherente; mínimo 80 velas OHLCV **cerradas**; última vela cerrada con menos de 180 s; 40 velas sin huecos; rechazo de salto mayor a 12% de una vela a otra; rechazo si más del 40% de 20 velas carecen de volumen transado. Esos umbrales son **filtros de ingeniería, no predictores validados**. Los valores con volumen cero pueden provenir de punto medio de cotizaciones según Alpaca (https://docs.alpaca.markets/us/docs/market-data-faq).

Observa RSI14, MACD y señal, SMA20/SMA50, variación de 3m y volumen. Tiene combinaciones experimentales distintas para 1/2/5/10 minutos y devuelve `SUBE/BAJA/ESPERAR` por horizonte, siempre con **HIPÓTESIS EXPERIMENTAL — NO OPERAR**, `probabilidad_acierto=null`, `operativa_autorizada=false`. Los cálculos se hacen solo con datos disponibles hasta la vela cerrada, no con precios futuros. **No se ha validado su rentabilidad ni ninguna tasa de acierto.**

Reloj de SIMULACIÓN: usa solo la hipótesis de 2 min como ensayo fijo, no como duración óptima. La entrada hipotética está anclada a la vela (inicio + 120 s), sin mover el objetivo por refresco de HTTP. Estados ESPERAR/PREPARARSE/CUENTA_REGRESIVA/ENTRAR/VENTANA_CERRADA y cancelación ante datos no frescos; nunca crea orden. No se afirma que esa frontera sea el momento más rentable ni que equivalga al vencimiento de IQ Option. La página `/crypto` muestra diagnóstico, motivos, indicadores, reloj con cuenta regresiva estimada por reloj del PC y advertencia de hipótesis no validada.

Pruebas sintéticas de señales, cancelación por feed viejo, huecos, cero volumen, salto, rechazo de futuro/provisional, aislamiento y GET sin ejecución real en `pruebas/test_crypto_observacion_v5.py`. **Próxima fase:** registrar hipótesis en tiempo real de forma prospectiva e identificar el precio exacto y condiciones de un eventual instrumento de destino antes de calcular probabilidad y payout. No es una estrategia lista para dinero real.

## Ronda 9 — Conexión independiente de criptomonedas 24/7 (2026-11-23)

El usuario solicitó disponer de datos de mercado tras el cierre de acciones de EE. UU. Se implementó una **fuente cripto separada de IEX** y de las hipótesis NVDA, en `crypto_live.py`. Su URL WebSocket oficial es `wss://stream.data.alpaca.markets/v1beta3/crypto/us`; se autentica con `Alpaca_key.txt` del equipo sin publicar credenciales; recibe `trades`, `quotes`, `bars` y `updatedBars`, y carga barras con REST `/v1beta3/crypto/us/bars`. Al iniciar, solo abre un WebSocket cripto en segundo plano tras abrir `/api/crypto/live`. No altera la conexión IEX, abre cuentas ni envía órdenes.

Pares seleccionables: BTC/USD, ETH/USD, SOL/USD. Rutas locales:
- `/crypto`: pantalla nueva enlazada desde el panel REALTIME `/live`.
- `GET /api/crypto/live`: solo lectura, estado de conexión, cotización, operaciones, velas, timestamps y `operativa_autorizada=false`.
- `POST /api/crypto/symbol`: valida par y resuscribe el único feed cripto sin mezclar datos previos.

La página dibuja velas de 1m, precio de la última operación, bid/ask, recencia y fallos de autenticación o de suscripción. Los precios de las velas cripto **pueden incorporar puntos medios bid/ask**, por documentación de Alpaca, incluso cuando no hay trades: no deben presentarse como última transacción ni como precio de liquidación IQ Option. La arquitectura no conecta el motor predictivo NVDA con BTC/USD. Las alertas/subidas/bajadas de un instrumento no son extrapolables a otro. Cobertura 24/7 se refiere al horario de mercado, no a garantía de actividad continua del proveedor.

**Limitación de validación real:** las pruebas automáticas usan mensajes y REST simulados; el entorno GitHub Actions no dispone de la clave privada del usuario. No se declara conexión efectiva ni latencia real sin comprobar en su PC el estado `conectado` y marcas de tiempo actuales en /api/crypto/live. Fuentes oficiales de contrato: https://docs.alpaca.markets/us/docs/real-time-crypto-pricing-data y https://docs.alpaca.markets/us/reference/cryptobars-1.

## Ronda 8 — Catálogo multiactivo REALTIME (2026-11-23)

Solicitud: ampliar el selector de activos que antes mostraba seis opciones; el escáner histórico mantiene su capacidad independiente de hasta 200 símbolos. El backend REALTIME ahora ofrece 24 acciones/ETF estadounidenses; la interfaz carga la lista desde `available_symbols`, sin duplicar un catálogo fijo en HTML.

**Invariantes:** solo un símbolo en la suscripción activa Alpaca IEX; selección mediante endpoint validado; caché separado por símbolo; sin ampliar conexiones, automatizar órdenes ni validar la señal en otros activos. `evaluate_hypothesis` sigue restringido a NVDA en el motor experimental V5; la disponibilidad de un activo en el selector no equivale a una predicción ni a soporte de IQ Option.

**Horario:** los 24 instrumentos comparten sesión de mercado estadounidense. Esta mejora permite elegir más activos durante la sesión y consultar históricos fuera de ella, **no** elimina el cierre simultáneo. Para horarios 24/7 es necesario integrar por separado un feed de criptomonedas o equivalente, con sus propios datos y controles de calidad, antes de ofrecer una opción funcional.

Se actualizó el hash de protección `alpaca_live.py` únicamente por la modificación autorizada del catálogo; quedaron protegidas las demás funciones del feed. Se agregaron pruebas de catálogo, cambios de símbolo, ausencia de conexiones adicionales, UI dinámica y abstención por activos ajenos a NVDA.

# Auditoría progresiva — TraderAssistant V5

## Objetivo acordado

Preservar V4 y todas sus funcionalidades. Prioridad absoluta: determinar, sobre evidencia comprobable, **cuándo preparar una entrada**, **SUBE/BAJA** y la **duración (30, 60, 120, 300 o 600 segundos)**. La presentación gráfica es secundaria. No hay órdenes automáticas.

## Ronda 1 — Núcleo temporal (implementada en `v5-development`)

Archivos añadidos:
- `engine/reloj_entrada.py`: reloj puro y determinista sin depender de Flask, Alpaca ni la UI.
- `pruebas/test_reloj_entrada_v5.py`: pruebas unitarias de transición, cinco duraciones, invalidación por datos antiguos/futuros, validación de UTC.
- `.github/workflows/v5-reloj-tests.yml`: ejecución automática de esas pruebas en cada cambio de la rama V5 y su PR.

Estados: ESPERAR → PREPARARSE (30 s antes) → CUENTA_REGRESIVA (10..1 s) → ENTRAR (instante hipotético) → VENTANA_CERRADA. CANCELADA ante datos obsoletos o relojes desincronizados. Los tiempos de 30 y 10 segundos son parámetros iniciales, no garantías de previsión.

**Límite esencial:** este reloj **NO** crea `HipotesisEntrada(validada=True)`. La palabra «validada» solo representa una condición que deberá determinar un proceso de validación posterior; no representa confianza operativa. `operativa_autorizada` siempre es `False`. Nunca usar esta primera versión para decidir operaciones reales.

Comando de prueba desde la raíz:
```bash
python -m unittest discover -s pruebas -p 'test_reloj_entrada_v5.py' -v
```

## Ronda 2 — Validador temporal fuera de muestra (implementado)

- `engine/validacion_temporal.py`: registros inmutables de entrada/vencimiento, dirección, precio, fuente y payout opcional.
- `pruebas/test_validacion_temporal_v5.py`: 12 casos para separación temporal, duplicados, fechas inválidas, payout ausente, resultados, intervalos Wilson y filtros por fuente.
- Separa entrenamiento (< corte) de pruebas (señal detectada >= corte); descarta eventos cruzados, evitando fuga temporal.
- Los resultados **no** demuestran precisión predictiva. Sin observaciones autorizadas del instrumento IQ Option y sin validación prospectiva, el campo `operativa_autorizada` es siempre falso.
- CI incluye todas las pruebas V5 mediante `python -m unittest discover -s pruebas -p \'test_*_v5.py\' -v`.

## Rondas 3 y 4 — Diagnóstico HTTP y entrada de datos auditados

- `engine/estado_v5.py`: agregador puro de estados de REALTIME y del analizador; expone las hipótesis experimentales por horizonte, comprueba símbolo, vigencia de datos y timestamps.
- `v5_diagnostics.py`: nuevo endpoint GET `/api/v5/estado` integrado en `app.py`, sin modificar gráficos ni realizar órdenes. Los resultados actuales permanecen en `ESPERAR` hasta que exista validación independiente y anticipación demostrada.
- `pruebas/test_estado_v5.py` y `pruebas/test_api_v5.py`: pruebas de estados y HTTP con Flask, incluidas peticiones de solo lectura y rechazo de POST.
- `engine/validacion_temporal.py` + `v5_validar_csv.py`: carga de observaciones reproducibles en CSV, duraciones exactas, atribución de fuente y cálculo de aciertos fuera de muestra. No sustituye a registros reales de IQ Option.
- `pruebas/test_csv_v5.py`: pruebas de formato, fechas, duraciones y acceso de solo lectura.

Para probar el endpoint, en Windows, desde `C:\\Proyectos\\TraderAssistant` tras descargar la rama de desarrollo:

```powershell
python -m unittest discover -s pruebas -p 'test_*v5.py' -v
python main.py
```

Con la aplicación abierta, consultar `http://127.0.0.1:5174/api/v5/estado` en el navegador. Es diagnóstico experimental; no debe usarse como señal de operación.

Para evaluar un CSV proporcionado por el usuario (nunca asumir que IEX liquida NVIDIA Blitz):

```powershell
python v5_validar_csv.py observaciones.csv --corte-utc 2026-11-23T15:00:00+00:00 --minimo 30 --fuente IQ_OPTION
```

Columnas CSV: `detectada_utc,entrada_utc,vencimiento_utc,duracion_segundos,direccion,precio_entrada,precio_salida,fuente,payout_neto`. Los timestamps requieren zona horaria y el precio de salida debe corresponder al vencimiento real.

**Bloqueador explícito:** siguen faltando muestras prospectivas verificables de NVIDIA Blitz, su calendario/reglas de expiración y la medición de latencia de interacción del usuario. No es responsable prometer una hora exacta de entrada ni una tasa de acierto mientras falte esa evidencia. La ejecución del módulo de diagnóstico sí es posible, pero el objetivo operativo aún no está validado.

## Ronda 5 — Horizonte exploratorio de 30 segundos y regresión completa

- `engine/micro_30s.py`: prueba causal de impulso y volumen en 24 velas indicativas consecutivas de 5 segundos; rechaza huecos, barras en formación, cache de días previos, retrasos y precios/volúmenes inválidos.
- `pruebas/test_micro_30s_v5.py`: casos positivos y negativos de calidad de datos. **Es observación experimental, no predicción calibrada ni señal de entrada.**
- Regresión GitHub Actions del commit `856413f97e212a2ef82fc4f0863ba69ffbdac2b5`: **161 pruebas aprobadas** en Ubuntu, además de los jobs específicos V5 en Ubuntu y Windows. Enlace: https://github.com/andresfsilvat-hash/TraderAssistant/actions/runs/45259872318
- Se detectó y corrigió en la rama de desarrollo un test de hash `main.py` con firma anterior a la versión original publicada. El blob de `main.py` (`55ad1bfa2c3a5627e792092653322fb7c30632e2`) coincide exactamente entre `main` y `v5-development`; no se modificó el archivo principal V4.

## Criterios pendientes antes de considerar listo el objetivo operativo

1. Datos temporales de NVIDIA Blitz en IQ Option, con vencimientos exactos, payouts y fuentes verificadas.
2. Validación *prospectiva* de anticipación: medir qué porcentaje de eventos permite preparar 10 s antes, sin sesgo temporal y sin alterar falsamente los resultados.
3. Métricas predictivas separadas por patrón, dirección y horizonte, incluyendo tasa de abstención y costos; prueba fuera de muestra y monitoreo de cambios de régimen.
4. Motor de planificación temporal conectado únicamente a modelos calibrados, con bloqueo por latencia y revocación de señales obsoletas; verificación de ejecución simulada end-to-end.
5. Pruebas locales del proyecto completo en Windows con Alpaca IEX conectado, medición de red y comparación independiente con los precios/vencimientos del instrumento de destino.

La API `/api/v5/estado` funciona como diagnóstico; **permanece en ESPERAR por diseño** hasta superar los criterios. No se han habilitado órdenes automáticas ni cambios visuales.

## Ronda 6 — Preparación y cuenta regresiva en simulación

- `engine/planificacion_experimental.py` crea una **hora hipotética de entrada estable** a partir del timestamp del análisis experimental existente, no a partir de la hora de cada solicitud HTTP; evita desplazar el contador con cada actualización.
- `pruebas/test_planificacion_v5.py` verifica la transición PREPARARSE → CUENTA_REGRESIVA 10..1 → ENTRAR en simulación y la cancelación por falta de datos recientes.
- `/api/v5/estado` incluye un objeto independiente `reloj_experimental` que muestra duración, instante hipotético y contador. La respuesta principal sigue en ESPERAR; `operativa_autorizada=false`. No conecta con órdenes ni precios de liquidación de IQ Option.
- Horizonte 30s: análisis exploratorio de 5s separado, sin planificador habilitado hasta calibración.
- La hora hipotética usa una frontera de minuto posterior al análisis para pruebas temporales; **no existe evidencia de que sea el mejor momento para operar**.

## Ronda 7 — Corrección diaria y diagnóstico de ESPERAR (2026-11-23)

Hallazgo en una respuesta real del usuario: contexto 1d con cierre 125,65 y `sma20 == sma50 == 208,4575`, frente a precio 1m de 164,60; 1h Alcista y 1m/1d Bajista. No se presume que el histórico esté corrupto: hay que verificar datos ajustados, continuidad y origen.

Cambios:
- `multitimeframe_context.py`: ahora la tendencia y campo `sma20` del contexto diario usan realmente 20 sesiones; la `sma50` se calcula por separado. La implementación anterior usaba 50 como parámetro de ambas, lo que además podía producir pendiente incompleta con 50-52 sesiones.
- Se añade control conservador de divergencia >20% entre último cierre diario y último precio regular disponible, con bandera `PRICE_SCALE_MISMATCH` y bloqueo **solo** del contexto diario; no reescribe ni ajusta precios, no elimina el análisis 1m/1h. Este umbral es una alerta inicial configurable en código, no un detector probado de splits; requiere revisión de fuentes ante una alerta.
- `engine/estado_v5.py`: `diagnostico_por_duracion` para 30/60/120/300/600, con faltantes/contradicciones, y `alertas_calidad` con causa y desviación.
- `pruebas/test_calidad_contexto_v5.py` y `pruebas/test_estado_v5.py`: tests de SMA20 vs SMA50, diferencias de escala, funcionamiento normal y exposición de los motivos. Se conserva `operativa_autorizada=false` en todo momento.

No se alteran las reglas de las hipótesis de dirección para forzar señales. El motor sigue experimental; mejora la integridad y explicación del resultado, no demuestra subida de tasa de aciertos.

## Hallazgos de la auditoría del proyecto actual

1. `decision_engine_experimental.py` admite horizontes 60/120/300/600, pero todavía no 30 segundos; su decisión operativa permanece **ESPERAR**.
2. `evaluar_motor_multihorizonte.py` usa velas 1m y compara apertura/cierre de intervalos, por lo que no debe extrapolarse a precisión de entrada de 30 segundos.
3. `alpaca_live.py` ya implementa WebSocket, SSE, datos provisionales 5s, seguimiento de lag y reconexión. No reemplazar sin una prueba de regresión.
4. `analysis_live.py` ya separa cálculo mediante `ProcessPoolExecutor`; no mover cálculos al hilo del stream.
5. Las cotizaciones de **Alpaca IEX** no equivalen al precio de liquidación de **NVIDIA Blitz en IQ Option**. No afirmar rentabilidad ni probabilidades calibradas sin datos independientes de ejecución/vencimiento.
6. La marca de tiempo del sistema es una aproximación si los relojes no están sincronizados; en fases siguientes se debe medir el desfase con la plataforma de destino.

## Siguientes rondas (pendientes, no validadas)

- **Ronda 2:** completar alimentación de la validación con observaciones reales y medir tasa de abstención; 30s solo con muestras suficientes de esa resolución.
- **Ronda 3:** planificador de oportunidades futuras a partir de evidencia causal, entrada programada, vencimiento, controles de calidad y registro inmutable.
- **Ronda 4:** integración aislada con módulos REALTIME y simulador actual; pruebas con mocks de reconexión/cancelación.
- **Ronda 5:** sincronización con IQ Option usando datos autorizados de la plataforma, evaluación de payout/latencia y pruebas supervisadas de extremo a extremo.
- **Ronda 6:** pruebas completas en Windows/VS Code y aceptación antes de fusionar a `main`; mejoras visuales después.

No se debe afirmar que V5 está lista para operar mientras los pasos pendientes no hayan sido probados.
