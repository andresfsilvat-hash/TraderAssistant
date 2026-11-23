# AUDITORÍA TÉCNICA DEL PROYECTO TRADERASSISTANT

**Fecha:** 17 de noviembre de 2026  
**Fuente auditada:** archivo `TraderAssistant.zip` aportado por el usuario en esta conversación  
**Modalidad:** revisión estática, comparación con Git y pruebas sintéticas sin conexión al broker  
**Estado:** informe de hallazgos; no se modificó el proyecto de origen ni se enviaron órdenes.

## 1. Resumen ejecutivo

**Conclusión:** el proyecto original de TraderAssistant sí está conservado y el complemento Alpaca está instalado; sin embargo, **la actualización v3 está almacenada como archivos de instalación y no está activa en el código principal incluido en el ZIP**. La versión que `main.py` abre es la vista **v2**, que consulta la API local cada segundo; no es la vista v3 con avisos SSE. El instalador de v3 presenta un defecto reproducible de comparación de hashes provocado por las diferencias entre saltos de línea Windows y Unix. Además, la construcción de velas provisionales a partir de operaciones sin comprobar sus condiciones puede producir OHLCV diferentes de los agregados oficiales. El motor de señales original sigue sin analizar directamente las cotizaciones de Alpaca.

**Prioridad:** corregir el estado de instalación y la integridad de las velas; luego instrumentar latencia y estabilidad; finalmente integrar indicadores y señales.

## 2. Inventario y alcance

- ZIP: ~66 MB comprimidos; **10.959 entradas** (9.872 archivos y 1.087 directorios); ~198 MB de tamaño total descomprimido.
- Archivos de proyecto, excluyendo `.git`, `venv` y cachés: **33 archivos**.
- Se encontraron `main.py`, `app.py`, `alpaca_live.py`, `ui/index.html`, `ui/live.html`, `ui/vendor/lightweight-charts.js`, `screener/*.py`, `requirements.txt`, `config.json`, documentación, instaladores y respaldos.
- El ZIP contiene el entorno virtual `venv` y metadatos `.git`: son útiles para documentar la instalación, pero no deben distribuirse como parte habitual del código fuente; un entorno virtual Windows no es portable de manera confiable.
- **No se encontró un archivo llamado `Alpaca_key.txt` dentro del ZIP.** Tampoco se detectaron patrones de claves Alpaca en los archivos de código y documentación examinados. Esto no equivale a una auditoría forense completa de todos los binarios o de los datos locales fuera del ZIP.
- Archivo ZIP SHA-256: `baccfca4c8e3bca36ccc0d883d4b0150ea3ac497be16eb5b9be960e9150670d8`.

## 3. ¿Qué versión se ejecuta?

**Punto de entrada:** `main.py:34-37` abre `http://127.0.0.1:5174/live`.

**Registro de rutas:** `app.py:20-24` registra `register_live(app)` desde el módulo raíz `alpaca_live.py`.

**Rutas actuales:** `/live`, `/api/alpaca/live`, `/` (analizador histórico) y las API de Yahoo Finance (`/api/scan`, `/api/chart/...`).

**Comprobación inequívoca de versión:**

| Ubicación | Contenido | ¿Está activa? |
|---|---|---|
| `alpaca_live.py` | versión v2, 10.975 bytes | Sí, importada desde `app.py` |
| `ui/live.html` | versión v2, 11.992 bytes | Sí, servida por `/live` |
| `integracion/alpaca_live.py` | versión v3, 14.045 bytes | No, solo archivo para el instalador |
| `integracion/ui/live.html` | versión v3, 15.022 bytes | No, solo archivo para el instalador |
| `instalar_realtime_v3.py` | instalador | No se ejecuta al iniciar `main.py` |

Pruebas: el HTML activo contiene `setInterval(refresh,1000)` y **no** contiene `EventSource`; la copia v3 dentro de `integracion/ui` sí contiene `EventSource` y un mecanismo SSE.

**Comparación con Git original:** commit `f3554c2`. Ignorando diferencias de saltos de línea, los cambios sustantivos en archivos rastreados se concentran en `app.py` (registro de Alpaca), `main.py` (apertura `/live`) y `ui/index.html` (enlace a la vista). El código original de los detectores, puntuación y descarga histórica se mantiene sin cambios sustantivos frente al commit original.

## 4. Hallazgos priorizados

### CRÍTICO PARA LA INSTALACIÓN — v3 no se aplica

`instalar_realtime_v3.py:12-16,31-42` exige hashes SHA-256 exactos de los archivos v2. Los archivos activos del ZIP tienen saltos de línea `CRLF`, mientras que el hash esperado corresponde al mismo contenido con `LF`. Una comparación literal falla y el instalador sale sin aplicar cambios.

**Prueba:** al convertir CRLF→LF, ambos hashes coinciden exactamente con las constantes del instalador; con los bytes tal como figuran en el ZIP, ninguno coincide. No se encontraron respaldos `.bak_realtime_v3` de una instalación aplicada.

**Acción:** corregir el instalador para validar el contenido normalizado o, preferiblemente, usar un parche versionado que compare contenido semántico y mantenga copias de seguridad. No sobrescribir v3 manualmente sin pruebas.

### ALTO — OHLCV provisional puede ser incorrecto

`alpaca_live.py:110-148` y `integracion/alpaca_live.py:151-199` incorporan cada operación (`T=t`) a las velas sin analizar `c` (condiciones de la operación). Las reglas de Alpaca excluyen o restringen determinados tipos de operación en la agregación oficial. Con operaciones sintéticas, una operación con condición `I` modificó indebidamente el máximo y el cierre de una vela.

El problema no se limita a v2: la función `insert_bar()` de v3, en una vela que considera actual, conserva el cierre provisional y el máximo/mínimo extremos aunque el agregado recibido sea distinto.

**Acción:** separar las operaciones (precio observado) de las velas oficiales (`bars`, `updatedBars`); aplicar las reglas correspondientes a cada operación si se pretende construir una vela provisional; definir una reconciliación determinista al cerrar cada minuto.

### ALTO — Las correcciones de velas anteriores pueden no dibujarse

En `ui/live.html` y `integracion/ui/live.html`, `paint()` usa una firma que solo considera el tamaño de la serie y la última vela. Si se corrige una vela anterior y la última permanece igual, `setData()` no se ejecuta y el gráfico puede mostrar un histórico incorrecto. Además, ambos backends manejan mensajes `T=u`, pero se suscriben solo a `trades` y `bars`, no a `updatedBars`, por lo que no solicitan explícitamente ese canal.

**Acción:** suscribir `updatedBars` según disponibilidad, implementar actualizaciones por índice/tiempo y aplicar reparaciones de barras anteriores de forma visible.

### ALTO — El análisis original aún no es tiempo real

`app.py:170-245` ejecuta `/api/scan` sobre `fetch_daily()` y `fetch_1h()` de Yahoo Finance. Los archivos de `screener` no consumen el `LiveFeed` Alpaca. Las señales LONG/SHORT no se recalculan por cada vela nueva de Alpaca.

**Acción:** introducir un proveedor de datos normalizado y un motor de análisis que procese velas cerradas de Alpaca; dejar Yahoo como fuente histórica auxiliar y evitar mezclar datos de distintas coberturas sin identificarlos.

### MEDIO — Carga histórica bloquea el inicio del flujo en vivo

`alpaca_live.py:175-185` y v3 `integracion/alpaca_live.py:228-239`: `run()` llama primero a `history()` con un timeout HTTP de 20 segundos, y solo después intenta conectar WebSocket. Si la petición histórica se demora, el inicio del tiempo real también se retrasa.

**Acción:** conectar WebSocket de inmediato y cargar historial en una tarea independiente; reconciliar las series al completarse.

### MEDIO — Falta medir la latencia que realmente ve el usuario

En v2, el navegador hace una consulta cada segundo. V3 incorpora notificaciones SSE, pero luego solicita un snapshot completo por HTTP y espera 200 ms antes de esa consulta. Se reporta un desfase entre hora de operación y recepción en Python, **no** entre recepción en Python y representación gráfica. Sin marcas de tiempo de extremo a extremo, no se puede comprobar la meta de menos de 500 ms para el 95 % de operaciones.

**Acción:** registrar al menos tiempo en bolsa, recepción en servidor, publicación al navegador y renderizado; informar p50/p95/p99 por intervalos, pérdidas, reconexiones y cola de eventos. Considerar envío incremental/deltas en lugar de arrays completos con cada evento.

### MEDIO — Riesgo de inyección HTML por símbolos

`app.py:78-93` acepta cadenas de ticker sin una validación restrictiva. En `ui/index.html:1182-1188` el ticker se introduce mediante `innerHTML` sin escape. Aunque la app escucha en `127.0.0.1`, conviene eliminar esta superficie de XSS. Las filas de resultados sí utilizan un helper de escape para el ticker.

**Acción:** construir el chip con `textContent` y elementos DOM; aplicar una validación de ticker en API y UI, compatible con los instrumentos previstos. No exponer el servidor local a redes externas antes de corregirlo.

### MEDIO — Dependencias no declaradas expresamente

`alpaca_live.py` importa `requests` y `websockets`, pero `requirements.txt` contiene solo pywebview, Flask, yfinance, ta y pandas. Ambas dependencias aparecen instaladas dentro del `venv` del ZIP, probablemente a través de otras dependencias; una instalación limpia futura podría no ser reproducible si esas relaciones cambian.

**Acción:** declarar las dependencias directas y sus rangos/versiones probadas, además de mantener un archivo de bloqueo o proceso equivalente. No se realizó una consulta en línea de vulnerabilidades de todos los binarios del entorno.

### BAJO/MEDIO — Volumen de distribución excesivo

El ZIP contiene 10.959 entradas, principalmente de `venv`, además de `.git`, `.pyc` y backups. Esto dificulta subirlo a Google Drive y auditar la versión vigente. Los respaldos son útiles, pero conviene gestionarlos fuera del directorio principal del código activo.

**Acción:** mantener un repositorio limpio, excluir `venv` y cachés en los entregables y almacenar un manifiesto explícito de versión y dependencias. **No eliminar estos elementos del ZIP recibido:** sería una tarea separada.

## 5. Pruebas ejecutadas y resultados

| Prueba | Resultado |
|---|---|
| Integridad del ZIP y listado de entradas | Correcto, sin necesidad de recuperar archivos de Drive |
| Compilación sintáctica Python (archivos de código del proyecto) | Correcta, con aviso no bloqueante por secuencia de escape en docstring de `instalar_realtime_v3.py` |
| Comprobación de sintaxis JavaScript (Node.js) en HTML original, v2 y v3 | Correcta |
| Comparación de cambios frente a Git original, ignorando CRLF/LF | Tres archivos rastreados con cambios sustantivos: `app.py`, `main.py`, `ui/index.html` |
| Simulación de operación con condición no elegible para cálculo de barra | Defecto reproducido en v2 y v3 |
| Simulación de barra oficial posterior | V2 reemplaza; v3 mantiene incorrectamente el extremo provisional si sigue siendo la vela actual |
| Análisis del instalador v3 | Defecto de hashes confirmado y reproducido |
| Prueba con cuenta Alpaca o velocidad de bolsa real | No ejecutada (el ZIP no contiene las credenciales y no se necesitaban para la auditoría) |
| Antivirus y auditoría de CVEs en todo `venv` | No ejecutada en esta auditoría; no se certifica ausencia de malware o CVEs |

## 6. Propuesta de criterios de aceptación

Antes de integrar señales automáticas, aceptar la **Fase 1** solo si:

1. Una comprobación de versión demuestra qué implementación está activa (`/api/version` o equivalente), con hash/commit y fecha.
2. Las operaciones llegan por WebSocket y se muestran automáticamente; ninguna señal de "congelación" se basa únicamente en ausencia de operaciones IEX.
3. La latencia interna servidor→renderizado tiene **p95 menor de 500 ms** durante una prueba de 30 minutos con tráfico, sin comprometer la integridad de precios. El retraso externo de Alpaca se mide por separado.
4. Las barras oficiales de 1 minuto concuerdan con Alpaca al cerrar; las diferencias provisionales se identifican como tales y las correcciones se aplican.
5. Se prueba reconexión tras cortar la red, continuidad del estado y recuperación de datos perdidos.
6. Se distinguen mercado abierto, mercado cerrado y conexión sin operaciones.
7. Se evitan XSS y credenciales en logs, interfaz o entregables.

## 7. Plan de corrección sin modificar el original

**Paso A — Estabilizar la instalación:** crear una rama/backup verificable; corregir el instalador de v3 y comprobar su aplicación mediante comparación de archivos y verificación funcional.  
**Paso B — Integridad:** separar trades, velas provisionales y agregados oficiales, incorporar condiciones de operaciones y `updatedBars`; añadir pruebas unitarias con eventos sintéticos.  
**Paso C — Rendimiento:** arrancar WebSocket antes de la descarga histórica, medir latencias end-to-end y corregir rutas de actualización del gráfico.  
**Paso D — Seguridad/reproducibilidad:** validación de ticker, declaración de dependencias, pruebas automáticas y empaquetado de código sin `venv`.  
**Paso E — Integración de análisis:** conectar `screener` a datos de Alpaca una vez superada la Fase 1; primero datos y gráficos fiables, después indicadores y señales.

## 8. Fuentes técnicas externas utilizadas para contraste

- Alpaca, Real-time Stock Pricing Data: https://docs.alpaca.markets/us/docs/real-time-stock-pricing-data
- Alpaca, Market Data FAQ (reglas de agregación y distinción IEX/SIP): https://docs.alpaca.markets/us/docs/market-data-faq

El código y los resultados expuestos proceden del ZIP proporcionado por el usuario; las reglas sobre los feeds y las condiciones de operaciones se contrastaron con documentación oficial de Alpaca.
