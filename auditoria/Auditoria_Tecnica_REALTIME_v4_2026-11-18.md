# Auditoría técnica exhaustiva — TraderAssistant v4.0.0 — REALTIME

**Fecha y hora de corte:** 2026-11-18 08:58 (America/Bogota/America/Guayaquil, UTC-5)  
**Proyecto auditado:** `C:\Proyectos\TraderAssistant`  
**Módulo activo:** `alpaca_live.py` + `ui/live.html`, registrados desde `app.py:20-24` y abiertos por `main.py:34-36`  
**Naturaleza de la auditoría:** solo lectura. No se ejecutaron órdenes bursátiles, no se alteraron LONG/SHORT, configuraciones, credenciales ni código. El único archivo creado es este informe.

## 1. Dictamen ejecutivo

El módulo REALTIME **no está al 80 % verificable**. La estimación técnica obtenida es **72 % de avance verificable**. Existe una base funcional considerable: autenticación real con Alpaca, una conexión WebSocket capaz de confirmar los cuatro canales requeridos para los seis símbolos, historial REST IEX válido, caché por símbolo, velas oficiales de un minuto, SSE hacia la pantalla, agregación visual de cinco minutos y cambio de activo sobre una conexión.

No se recomienda declarar el módulo estable o terminado todavía. Los principales motivos son:

1. Las operaciones que llegan desordenadas dentro del mismo minuto pueden dejar un `close` provisional incorrecto y pueden perderse por completo en las velas de 5 segundos (`alpaca_live.py:498-528`). El defecto fue reproducido contra el código activo.
2. La protección contra conexiones simultáneas es solo por proceso. No impide una segunda instancia de TraderAssistant u otra aplicación con las mismas credenciales; ante un 406 se reintenta indefinidamente, pero no se elimina la causa (`alpaca_live.py:370-386`, `723-797`, `800`).
3. El estado `conectado` se publica verificando solo `trades` y `bars`; puede aparecer como conectado aunque falten `quotes` o `updatedBars` (`alpaca_live.py:693-700`).
4. La interfaz no distingue explícitamente premercado, sesión regular y posmercado. Solo muestra abierto/cerrado regular y una ventana heurística 08:00–17:00 de Nueva York (`ui/live.html:101-121`, `346-352`).
5. Las pruebas incluidas en el repositorio no prueban los archivos activos: apuntan a la copia anterior `realtime_v4/` (`pruebas/probar_v4.py:21`, `pruebas/probar_ui_node.js:6`).
6. No se completó una prueba prolongada con ticks durante sesión regular. A las 08:55 UTC-5 Alpaca autenticó y confirmó todas las suscripciones, pero no emitió operaciones/cotizaciones en las ventanas de 3 segundos por símbolo. Esto es **pendiente de validación**, no un fallo demostrado.

## 2. Cálculo del porcentaje

Se usó una ponderación basada en los requisitos de esta auditoría. Un requisito solo recibe 100 % cuando fue comprobado contra el módulo activo; la presencia de código sin prueba se puntúa parcialmente y lo no comprobado en sesión activa no se considera verificado.

| Área | Peso | Cumplimiento del área | Aporte |
|---|---:|---:|---:|
| Alpaca IEX y conexión | 30 % | 72 % | 21,60 % |
| Gráfico y velas | 25 % | 76 % | 19,00 % |
| Horarios de mercado | 15 % | 58 % | 8,70 % |
| Multiactivo | 15 % | 82 % | 12,30 % |
| Rendimiento, recuperación y caché | 15 % | 69 % | 10,35 % |
| **Total redondeado** | **100 %** |  | **72 %** |

La diferencia respecto del 80 % anterior proviene principalmente de no otorgar crédito completo a funciones meramente implementadas, de la falta de prueba regular prolongada, del defecto reproducible con eventos desordenados, de la ausencia de control interproceso y de las pruebas automatizadas desalineadas con la versión activa.

## 3. Tabla de hallazgos

| Componente | Estado | Problema detectado | Archivo y línea | Corrección recomendada | Prioridad |
|---|---|---|---|---|---|
| Registro e integración del módulo | FUNCIONAL Y VERIFICADO | El módulo raíz es el realmente registrado; las copias `realtime_v4/` e `integracion/` no son la ejecución activa. | `app.py:20-24`; `main.py:34-36` | Documentar una única fuente canónica y excluir copias antiguas de las pruebas operativas. | Media |
| Sintaxis Python y JavaScript | FUNCIONAL Y VERIFICADO | Los tres Python activos compilan en memoria y el script de `ui/live.html` pasa `node --check`. | `alpaca_live.py`; `app.py`; `main.py`; `ui/live.html:89-445` | Mantener estas comprobaciones en CI sobre archivos activos. | Media |
| Lectura y autenticación Alpaca | FUNCIONAL Y VERIFICADO | Autenticación WebSocket real exitosa sin exponer claves. El parser depende de un TXT con etiquetas y líneas concretas. | `alpaca_live.py:32`, `53-65`, `723-741` | Añadir prueba automatizada del parser con credenciales ficticias y diagnóstico de formato, sin registrar secretos. | Media |
| Endpoint y feed IEX | FUNCIONAL Y VERIFICADO | Se usa correctamente `v2/iex`; es un feed de una sola bolsa. | `alpaca_live.py:29-31` | Mantener el feed visible en UI y añadir verificación de compatibilidad/deprecación de API. | Baja |
| Suscripción a trades | FUNCIONAL PARCIALMENTE | Alpaca confirmó la suscripción real para los seis símbolos, pero no se observaron trades en la ventana corta de premercado. | `alpaca_live.py:690-692`, `706-707` | Ejecutar prueba de 30–60 minutos en sesión regular y registrar conteo, huecos y edad máxima sin guardar precios sensibles. | Alta |
| Suscripción a quotes bid/ask | FUNCIONAL PARCIALMENTE | Confirmación real para los seis símbolos; no llegaron quotes durante la ventana corta. El procesamiento y rechazo de quotes atrasadas sí pasó simulación. | `alpaca_live.py:532-574`, `690-692`, `708-709` | Validar en sesión regular spread, orden temporal, frescura y latencia por cada símbolo. | Alta |
| Suscripción a bars | FUNCIONAL PARCIALMENTE | Canal confirmado y lógica de inserción probada por simulación; no se observó una barra WebSocket real durante la prueba corta. | `alpaca_live.py:440-458`, `690-692`, `710-714` | Observar al menos diez cierres de minuto y compararlos con REST IEX posterior. | Alta |
| Suscripción a updatedBars | FUNCIONAL PARCIALMENTE | Canal confirmado por Alpaca; no se recibió una corrección real. | `alpaca_live.py:690-692`, `710-714` | Forzar una observación prolongada y verificar que una `u` incrementa revisión y redibuja una vela anterior. | Alta |
| Validación del ACK de canales | CON ERRORES | Marca `conectado` si existen trades y bars, aunque falten quotes o updatedBars. Defecto reproducido con ACK parcial. | `alpaca_live.py:693-700` | Exigir los cuatro canales del símbolo antes de publicar `conectado`; exponer el estado de cada canal. | Alta |
| Reconexión automática | FUNCIONAL PARCIALMENTE | Hay ping, reconexión y backoff 2–30 s; no hay prueba prolongada real ni jitter, límite o estado terminal. | `alpaca_live.py:723-797` | Añadir jitter, métricas de causa/duración y pruebas de corte de red, cierre limpio, 407/500 y recuperación. | Alta |
| Prevención de conexiones simultáneas / 406 | CON ERRORES | `started` impide duplicados solo en el mismo proceso. Una segunda instancia o tercero puede causar 406; el programa solo reintenta. | `alpaca_live.py:370-386`, `765-797`, `800` | Implementar exclusión interproceso con lock/PID local, detección de instancia existente y política de 406 con pausa y mensaje accionable. | Crítica |
| Plazo de autenticación/suscripción | FUNCIONAL PARCIALMENTE | Se depende del error/timeout del servidor; no existe deadline local para llegar a autenticado y suscrito. | `alpaca_live.py:738-770` | Añadir deadline explícito y reconectar si no se completa el handshake lógico. | Media |
| Procesamiento de trades duplicados | FUNCIONAL Y VERIFICADO | La clave exchange+trade-id evita duplicar volumen; la estructura queda limitada a 6000 IDs. | `alpaca_live.py:475-481` | Mantener prueba sobre el archivo activo y medir colisiones/reutilización de ID por sesión. | Baja |
| Trades desordenados y vela provisional 1m | CON ERRORES | Un trade antiguo que llega después dentro del mismo minuto reemplaza indebidamente el `close`; el `open` también depende del orden de llegada. Reproducción: precios 108@+8 s y luego 102@+2 s dejaron `close=102`. | `alpaca_live.py:498-514` | Guardar primer/último timestamp por vela y actualizar open/close por tiempo de evento, no por orden de recepción. | Crítica |
| Velas de 5 segundos | CON ERRORES | Un trade tardío de un bucket anterior se ignora; no corrige OHLCV ni volumen. En la reproducción quedaron 1 en vez de 2 buckets útiles. Todas se etiquetan globalmente como provisionales. | `alpaca_live.py:516-530`, `420` | Mantener buckets indexados por timestamp, aceptar correcciones dentro de una ventana acotada, deduplicar y separar `indicative` de `forming/closed`. | Crítica |
| Velas oficiales de 1 minuto | FUNCIONAL Y VERIFICADO | Una barra oficial sustituye a la provisional sin mezclar volumen; correcciones incrementan revisión y la serie se ordena por timestamp. | `alpaca_live.py:401-406`, `440-458`, `710-714` | Añadir comparación automática WebSocket-vs-REST tras el cierre. | Media |
| Agregación de 5 minutos | FUNCIONAL PARCIALMENTE | OHLCV se agrega correctamente en código, pero una barra puede representar menos de cinco minutos sin indicador de completitud. La prueba UI fue simulada. | `ui/live.html:175-191` | Exponer número de minutos contribuyentes y marcar intervalos incompletos; agregar pruebas de límites de sesión y huecos. | Media |
| Orden cronológico y duplicados 1m | FUNCIONAL Y VERIFICADO | Las seis cachés tenían 500 barras, orden ascendente, cero duplicados y cero inconsistencias OHLCV. El diccionario oficial deduplica por minuto. | `alpaca_live.py:136`, `394-406`, `636-650` | Incorporar la misma validación al guardado/carga y a CI. | Baja |
| Historial REST por símbolo | FUNCIONAL Y VERIFICADO | REST real devolvió HTTP 200 y 10/10 barras válidas y ordenadas para cada uno de los seis símbolos auditados. | `alpaca_live.py:576-660` | Añadir comprobación de huecos, paginación completa, rate limits y comparación con la caché. | Media |
| Persistencia al reiniciar | FUNCIONAL Y VERIFICADO | Escritura atómica y restauración pasaron prueba aislada; existen seis cachés válidas. La persistencia está limitada a 500 barras 1m y 1200 barras 5s. | `alpaca_live.py:164-230`, `238-246`, `801` | Exponer `cache_saved_at`, error de guardado y política de retención. | Media |
| Errores de caché | FUNCIONAL PARCIALMENTE | La corrupción no bloquea el arranque, pero todos los fallos de escritura se silencian; la UI no sabe si la persistencia falló. | `alpaca_live.py:199-201`, `228-230` | Registrar error sanitizado y mostrar estado de salud de caché. | Media |
| Diferenciación vivo/histórico/caché | FUNCIONAL PARCIALMENTE | Hay `history_source`, `origin` en 5s y etiquetas UI; las barras oficiales individuales no conservan origen y el estado global puede simplificar una serie mixta. | `alpaca_live.py:161`, `188-198`, `418-420`; `ui/live.html:287-290` | Añadir origen por barra o metadatos por rango y timestamps de última actualización por fuente. | Media |
| Trades frente a cotizaciones | FUNCIONAL Y VERIFICADO | El punto medio bid/ask se mantiene separado y se etiqueta como no operación; no altera las velas. | `alpaca_live.py:532-574`; `ui/live.html:316-340` | Mantener separación y añadir validación de mercados cruzados/bid-ask anómalo. | Baja |
| Correcciones y cancelaciones de trades | CON ERRORES | Existen ramas para `c/x`, pero no se suscriben `corrections/cancelErrors`; además solo notifican y no disparan reconciliación inmediata. | `alpaca_live.py:690-692`, `715-720` | Suscribir canales compatibles, procesar identificadores y lanzar reconciliación REST controlada. | Alta |
| Actualización automática de pantalla | FUNCIONAL Y VERIFICADO | SSE notifica cambios, agrupa eventos y tiene sondeo de respaldo cada 3 s. La simulación del archivo activo verificó inicio, actualización, corrección y temporalidad. | `alpaca_live.py:828-846`; `ui/live.html:401-441` | Añadir prueba end-to-end con navegador y servidor reales durante una sesión. | Media |
| Sincronización servidor-pantalla | FUNCIONAL PARCIALMENTE | Hay versiones y `series_revision`; la latencia servidor→pantalla solo se recalcula con `last_received_at` de trades, no con quotes. | `alpaca_live.py:151-152`, `435-437`; `ui/live.html:401-415` | Incluir timestamp/sequence de cada snapshot y medir por tipo de evento. | Media |
| Vela cerrada frente a formación | FUNCIONAL PARCIALMENTE | 1m oficial/provisional está separado; 5s usa `provisional=true` para todas las velas y la UI infiere formación por reloj. No hay atributo explícito `closed`. | `alpaca_live.py:401-406`, `420`; `ui/live.html:382-392` | Exponer `status: forming/closed` y `quality: official/indicative` por separado. | Media |
| Reloj de mercado regular | FUNCIONAL Y VERIFICADO | Consulta real respondió cerrado con próxima apertura 09:30 y cierre 16:00 UTC-5. El reloj Alpaca aporta calendario regular. | `alpaca_live.py:268-298` | Conservar y añadir timestamp Alpaca para detectar desviación del reloj local. | Baja |
| Próxima apertura/cierre y cuenta regresiva | FUNCIONAL Y VERIFICADO | Se muestran y actualizan cada segundo sin inventar horarios cuando el reloj está ausente. | `ui/live.html:95-128`, `437-441` | Probar cambios de estado exactamente en apertura, cierre y cierre temprano. | Media |
| Zona horaria Ecuador | FUNCIONAL Y VERIFICADO | Se usa `America/Guayaquil`; las fechas remotas se convierten con `Intl`. | `ui/live.html:92`, `123-128` | Mantener zona IANA, no offsets manuales. | Baja |
| Premarket / regular / postmarket | CON ERRORES | No existe una fase de sesión; solo abierto/cerrado regular y heurística 08:00–17:00 NY. No se etiqueta PREMARKET ni POSTMARKET. | `ui/live.html:101-121`, `346-352` | Calcular fase con zona Nueva York y calendario Alpaca, o usar el clock multimarcas/fases disponible; mostrar `PRE`, `REGULAR`, `POST`, `CERRADO`. | Alta |
| Fines de semana, feriados, DST y cierres tempranos | FUNCIONAL PARCIALMENTE | `next_open/next_close` de Alpaca contempla calendario regular; la heurística local de ticks solo mira día laborable y hora, ignorando feriados/cierres tempranos. | `alpaca_live.py:268-298`; `ui/live.html:346-352` | Basar todos los mensajes de sesión en reloj/calendario Alpaca, no en la heurística semanal. | Alta |
| Mercado abierto sin ticks IEX | FUNCIONAL PARCIALMENTE | Hay aviso de ausencia de ticks, pero se decide por 08:00–17:00 NY y no por `market_clock.is_open`; puede dar mensajes incorrectos en feriados. | `ui/live.html:346-352`, `372-379` | Combinar estado regular real, edad del último trade, edad del último quote y estado de canales. | Alta |
| Cambio NVDA/SPY/QQQ/MSFT/AAPL/AMD | FUNCIONAL PARCIALMENTE | Alpaca confirmó unsubscribe/subscribe en una sola conexión para los seis activos y REST respondió para todos. Falta observar ticks continuos tras cada cambio en sesión regular. | `alpaca_live.py:311-357`, `773-781`; `ui/live.html:210-226` | Prueba end-to-end repetida A→B→A con ticks y comparación de símbolo en todos los eventos. | Alta |
| Aislamiento de datos por símbolo | FUNCIONAL Y VERIFICADO | Los handlers comprueban símbolo antes y dentro del lock; respuestas históricas antiguas se descartan. Las seis cachés declaran símbolo/feed correctos. | `alpaca_live.py:461-474`, `538-554`, `633-634`, `657-658` | Agregar prueba concurrente de cambios rápidos B→C con REST B todavía en vuelo. | Media |
| No alteración de otros módulos | FUNCIONAL Y VERIFICADO | REALTIME está registrado como rutas separadas; no se encontraron llamadas de órdenes ni modificaciones LONG/SHORT desde este módulo. | `app.py:20-24`; `alpaca_live.py:804-846` | Mantener límites de módulo y pruebas de rutas/configuración. | Baja |
| Latencia | PENDIENTE DE VALIDACIÓN | Se calculan métricas aproximadas, pero no hubo ticks reales en la ventana auditada y no existe percentil p50/p95/p99. | `alpaca_live.py:490-491`, `565`; `ui/live.html:359-367`, `409-412` | Medir timestamps de proveedor, servidor, snapshot y render durante 30–60 min; separar trades, quotes y bars. | Alta |
| CPU y memoria | FUNCIONAL PARCIALMENTE | Simulación de 50.000 trades: 5,83 s pared, 5,45 s CPU, ~8.576 eventos/s y 2,10 MiB pico de asignaciones medidas. No sustituye perfil en aplicación real. | `alpaca_live.py:124-574` | Perfilar proceso completo y WebView 60 min con SPY/QQQ; registrar CPU, RSS, GC y tamaño/frecuencia JSON. | Media |
| Límites de memoria | FUNCIONAL Y VERIFICADO | Barras, IDs y quotes tienen topes: 500, 1200, 6000 y 600 respectivamente. | `alpaca_live.py:33-39`, `394-399`, `480-481`, `572-573` | Añadir métricas del tamaño de snapshot y backpressure ante cliente lento/407. | Media |
| Estabilidad prolongada y recuperación tras reinicio | PENDIENTE DE VALIDACIÓN | La arquitectura y caché existen, pero no se hizo soak test ni reinicio controlado durante sesión activa. | `alpaca_live.py:238-267`, `723-801` | Ejecutar matriz de 8 h, corte de red, cierre/reapertura y comparación posterior con REST. | Alta |
| Cobertura automatizada activa | CON ERRORES | Las pruebas oficiales apuntan a artefactos distintos de los cargados por `app.py`; pueden pasar y dejar regresiones activas sin detectar. | `pruebas/probar_v4.py:21`; `pruebas/probar_ui_node.js:6` | Reorientar pruebas a los archivos raíz o eliminar duplicación mediante un único paquete importable. | Crítica |

## 4. Pruebas realizadas y resultados reproducibles

### 4.1 Inspección estática y sintaxis

- `git status --short`: usado solo para establecer el estado previo; el árbol ya contenía numerosos cambios y archivos no rastreados.
- Compilación Python en memoria mediante `compile(...)`: **OK** para `alpaca_live.py`, `app.py` y `main.py`; no se generaron `.pyc`.
- Extracción del bloque JavaScript de `ui/live.html` y `node --check -`: **OK**.
- Registro de rutas: `app.py` importa y registra el módulo raíz; `main.py` abre `/live`.

### 4.2 Validación real Alpaca, solo lectura

Realizada con una conexión y sin mostrar credenciales:

- Clock: HTTP 200, `is_open=false`, `next_open=2026-11-18 09:30 -05:00`, `next_close=2026-11-18 16:00 -05:00`.
- WebSocket `wss://stream.data.alpaca.markets/v2/iex`: autenticación **exitosa**.
- Suscripción secuencial sobre la misma conexión: ACK completo de `trades`, `quotes`, `bars`, `updatedBars` para **NVDA, SPY, QQQ, MSFT, AAPL y AMD**.
- Errores Alpaca durante la prueba: **0**.
- Eventos observados en 3 segundos por símbolo: 0 trades, 0 quotes, 0 bars, 0 updatedBars. La prueba fue en premercado y la ausencia de ticks en una ventana corta no demuestra fallo.
- REST IEX: HTTP 200 para los seis símbolos; 10 barras solicitadas por símbolo, todas ordenadas y con OHLCV válido.

Para reproducir con seguridad, debe usarse un script efímero que: lea las credenciales sin imprimirlas, abra una sola conexión, autentique, haga unsubscribe/subscribe secuencial y registre únicamente ACK, conteos y códigos de error. No debe iniciar `main.py` en paralelo, para evitar consumir una segunda conexión.

### 4.3 Cachés existentes

| Símbolo | Barras 1m | Duplicados | Orden no ascendente | OHLCV inválido | Barras 5s | Última 1m UTC observada |
|---|---:|---:|---:|---:|---:|---|
| NVDA | 500 | 0 | 0 | 0 | 2 | 2026-11-18 13:33 |
| SPY | 500 | 0 | 0 | 0 | 0 | 2026-11-18 13:35 |
| QQQ | 500 | 0 | 0 | 0 | 0 | 2026-11-18 13:36 |
| MSFT | 500 | 0 | 0 | 0 | 0 | 2026-11-17 20:59 |
| AAPL | 500 | 0 | 0 | 0 | 0 | 2026-11-18 13:36 |
| AMD | 500 | 0 | 0 | 0 | 0 | 2026-11-18 13:31 |

Las cachés demuestran historial previo y separación por símbolo, no continuidad futura del WebSocket. Que MSFT no tenga barra del premercado del 18 de noviembre puede ser ausencia real de prints IEX; debe compararse en una prueba regular.

### 4.4 Simulaciones sobre el código activo

Se cargó `alpaca_live.py` en memoria, anulando únicamente el registro `atexit` y redirigiendo la caché a un directorio temporal:

- Deduplicación y construcción 5s: **OK** para eventos ordenados.
- Barra oficial reemplaza provisional: **OK**.
- Quote midpoint y rechazo temporal: **OK**.
- Persistencia/restauración en temporal: **OK**.
- Mensaje de suscripción contiene los cuatro canales: **OK**.
- ACK parcial sin quotes/updatedBars marcado como conectado: **defecto reproducido**.
- Trades fuera de orden: `108 @ +8s`, luego `102 @ +2s` dejó `close=102` y solo un bucket 5s: **defecto reproducido**.
- Guardia `start()` llamada tres veces en un proceso: solicitó un solo hilo `alpaca-iex-stream`: **OK solo dentro del proceso**.

### 4.5 Simulación UI y rendimiento

- El harness Node existente se ejecutó en memoria redirigido al `ui/live.html` activo y con mock de la serie de quotes: inicio, evento SSE, corrección y cambio de temporalidad **OK**.
- Carga sintética de 50.000 trades elegibles: 5,83 s pared, 5,45 s CPU, 8.576 eventos/s y 2,10 MiB de pico en asignaciones trazadas; IDs retenidos=6000. Es una medición lógica con `tracemalloc`, no una medición de RSS ni de WebView.

## 5. Funciones realmente operativas

- Lectura segura de credenciales y autenticación real con Alpaca.
- Conexión al feed IEX y confirmación real de los cuatro canales requeridos.
- Cambio secuencial de suscripción para los seis símbolos sobre una sola conexión de prueba.
- Historial REST IEX real para NVDA, SPY, QQQ, MSFT, AAPL y AMD.
- Validación, orden y deduplicación de barras oficiales por minuto.
- Sustitución de vela provisional por barra oficial y manejo de `updatedBars` en la lógica.
- Recepción y separación lógica de trades y quotes.
- Caché atómica por símbolo y restauración tolerante a registros inválidos.
- Actualización UI mediante SSE con polling de respaldo.
- Agregación visual 5m, volumen y OHLC para entradas ordenadas.
- Zona horaria Ecuador y cuenta regresiva basada en clock Alpaca.
- Límites de memoria para series e IDs.

## 6. Funciones que requieren corrección o validación

### Corrección obligatoria

- Orden temporal correcto para open/close provisional y buckets 5s.
- Lock interproceso y tratamiento robusto del 406.
- Validación completa del ACK de los cuatro canales.
- Pruebas automatizadas contra archivos activos.
- Fases premarket/regular/postmarket y mensajes basados en calendario real.
- Manejo real de correcciones/cancelaciones o reconciliación inmediata.
- Estado de caché visible y no silencioso.

### Validación obligatoria en sesión regular

- Flujo continuo de trades y quotes por cada símbolo.
- Emisión de bars y updatedBars reales.
- Comparación exacta de barras cerradas contra REST IEX.
- Latencia p50/p95/p99 proveedor→servidor→pantalla.
- Cambio repetido de activo sin mezcla bajo carga.
- Reconexión por corte de red, cierre remoto, 407/500 y reinicio de aplicación.
- Soak test de al menos una sesión regular completa.

## 7. Limitaciones atribuibles a Alpaca IEX

Estas limitaciones no deben contabilizarse como defectos de TraderAssistant:

- IEX es una sola bolsa, mientras SIP consolida las bolsas estadounidenses. Alpaca documenta IEX como el feed en vivo gratuito y SIP como el consolidado: <https://docs.alpaca.markets/us/docs/market-data-faq>.
- La cobertura IEX representa aproximadamente 2,5 % del volumen del mercado; puede no haber prints recientes aunque el mercado general esté activo: <https://docs.alpaca.markets/in-giftcity/docs/historical-stock-data-1>.
- Alpaca normalmente limita a una conexión por endpoint en muchos planes; una segunda conexión produce error 406: <https://docs.alpaca.markets/us/docs/streaming-market-data>.
- `bars` se emite después del minuto y `updatedBars` puede aparecer alrededor del medio minuto posterior cuando llega un trade tardío: <https://docs.alpaca.markets/us/docs/real-time-stock-pricing-data>.
- Las barras pueden existir también en pre/posmercado, pero no se genera una barra si no hay operaciones elegibles. La ausencia de vela no significa automáticamente desconexión.
- El clock legacy informa la sesión regular y próxima apertura/cierre; no prueba que IEX vaya a producir ticks: <https://docs.alpaca.markets/us/v1.4.2/reference/getclock-1>.

Consecuencia: TraderAssistant debe presentar claramente “sin ticks IEX recientes” sin inventar precios y sin equiparar IEX a NBBO/SIP.

## 8. Plan priorizado para alcanzar el 100 % verificable

### P0 — Corrección de integridad y pruebas

1. Unificar la fuente activa y hacer que todas las pruebas importen exactamente el módulo usado por `app.py`.
2. Rehacer agregación provisional por timestamp de evento: índices por minuto/5s, primer y último timestamp, ventana acotada para tardíos y deduplicación.
3. Exigir ACK de trades, quotes, bars y updatedBars antes de `conectado`.
4. Añadir lock interproceso, detección de instancia y estrategia explícita para 406.
5. Crear pruebas de regresión para los tres defectos reproducidos antes de cualquier despliegue.

### P1 — Exactitud de sesión y recuperación

6. Modelar fases PRE/REGULAR/POST/CERRADO con reloj/calendario Alpaca y zona Nueva York; convertir solo la presentación a Ecuador.
7. Eliminar la heurística semanal 08:00–17:00 como autoridad del mercado.
8. Suscribir/procesar correcciones y cancelaciones cuando el feed lo permita, o reconciliar de inmediato con REST.
9. Exponer salud por canal, caché, última barra, última quote, última operación, reconexión y causa.
10. Añadir deadlines, jitter y pruebas de reconexión/corte/reinicio.

### P2 — Certificación operativa

11. Ejecutar prueba regular de 30–60 min por los seis activos, alternando símbolos y comparando cada barra cerrada con REST.
12. Ejecutar soak test de una sesión completa con CPU, RSS, frecuencia/tamaño de snapshots, p50/p95/p99 y pérdidas/huecos.
13. Probar fin de semana, feriado, cambio DST y cierre temprano usando respuestas controladas del clock/calendar.
14. Ejecutar reinicio durante sesión, confirmar restauración y backfill sin duplicados ni mezcla.
15. Solo después de superar esta matriz, reclasificar cada pendiente como `FUNCIONAL Y VERIFICADO` y recalcular el porcentaje.

## 9. Criterio de aceptación final

El 100 % verificable no significa cobertura SIP ni ticks permanentes. Significa que, dentro de las limitaciones IEX, el sistema:

- mantiene exactamente una conexión propia;
- confirma todos los canales;
- conserva orden y exactitud ante eventos tardíos;
- no mezcla símbolos;
- reconcilia barras oficiales;
- representa correctamente fase y frescura;
- se recupera de red y reinicio;
- demuestra estabilidad durante una sesión completa;
- y cuenta con pruebas automatizadas sobre los mismos archivos que ejecuta producción.

**Conclusión:** REALTIME v4.0.0 es **FUNCIONAL PARCIALMENTE**, con una base aprovechable y autenticación/suscripción reales confirmadas, pero con defectos críticos de exactitud temporal, exclusión de conexión y cobertura de pruebas que impiden aprobarlo todavía como estable, continuo y preciso.
