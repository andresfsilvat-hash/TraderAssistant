# Corrección de sincronización — Fase 6

Fecha: 19 de noviembre de 2026  
Proyecto: `C:\Proyectos\TraderAssistant`  
Alcance: lectura y presentación del simulador multihorizonte

## Resultado

Se corrigió exclusivamente la sincronización entre los archivos del simulador Fase 6 y el panel. No se modificaron REALTIME, Alpaca, WebSocket/SSE, velas, gráfico, análisis técnico, reglas experimentales ni el proceso del simulador.

La vista activa ahora lee únicamente:

`auditoria\prospectivo_nvda_multihorizonte`

Los directorios siguientes permanecen intactos y ya no participan en el endpoint activo:

- `auditoria\prospectivo_nvda_2min_sesion_regular`
- `auditoria\prospectivo_nvda_2min`

## Causa exacta

`SimulationResultsReader` cargaba simultáneamente los tres directorios. Después:

1. combinaba sus CSV y pendientes;
2. seleccionaba como `latest` cualquier pendiente antiguo;
3. seleccionaba por separado el heartbeat más reciente;
4. marcaba `is_current=True` si existía un heartbeat activo y el registro pertenecía a la lista combinada de pendientes.

Por ello, el heartbeat del proceso iniciado a las 10:58 EC podía otorgar vigencia a la hipótesis SUBE antigua de las 10:23 EC. La UI confiaba correctamente en `is_current`, pero ese indicador estaba mal construido por el backend.

Había además dos defectos relacionados:

- `running` se calculaba sólo al recargar archivos y quedaba cacheado; si el heartbeat dejaba de cambiar, podía permanecer verdadero indefinidamente.
- No se comparaba la hora actual con `vencimiento_objetivo_utc`, por lo que una operación vencida podía seguir con estado ACTIVA mientras permaneciera en `pendientes.json`.

## Corrección aplicada

### Fuente activa

El lector admite exactamente un directorio activo. El valor predeterminado es exclusivamente `prospectivo_nvda_multihorizonte`. Los nombres legacy (`simulaciones_nvda_2min.csv` y `pendientes.json`) dejaron de formar parte de `_files()` y `_load()`.

### Heartbeat

Los datos de archivo siguen cacheados por tamaño/mtime, pero edad y estado del heartbeat se recalculan en cada `snapshot()`. Un proceso sin heartbeat reciente pasa a `SIMULADOR_DETENIDO` aunque ningún archivo haya cambiado.

### Vigencia de simulaciones

Un pendiente sólo es vigente cuando cumple todo lo siguiente:

- heartbeat reciente y proceso `running` o `degraded`;
- símbolo NVDA;
- detección igual o posterior a `started_utc` del proceso vigente;
- versión compatible con la del heartbeat;
- sin entrada: dentro de los 30 segundos posteriores a la detección;
- con entrada: antes de vencimiento + tolerancia de ocho segundos.

Un pendiente vencido queda contabilizado como obsoleto (`stale_pending_count`) y nunca se devuelve en `latest`. El lector no modifica registros; el simulador conserva la responsabilidad de cerrarlos como NO EVALUABLE cuando recupere acceso a sus fuentes.

### Respuesta del endpoint

- `latest`: únicamente simulación vigente del horizonte seleccionado, o `null`.
- `latest_completed`: último registro cerrado, separado y nunca marcado vigente.
- `active_simulation_status`: `ACTIVA`, `ESPERANDO_PRECIO` o `SIN_SIMULACION_ACTIVA`.
- `stale_pending_count`: pendientes rechazados por vigencia.
- `active_directory`: trazabilidad de la fuente exclusiva.
- `statistics_by_rules_version`: sólo registros del directorio activo y del horizonte solicitado.

Se deduplican IDs del CSV y del archivo de pendientes; un ID ya cerrado no vuelve a considerarse pendiente.

### Panel

Cuando `latest` es `null`, el panel muestra:

- hipótesis: `ESPERAR`;
- estado: `SIN SIMULACIÓN ACTIVA` si el heartbeat está vigente;
- entrada y vencimiento: `—`;
- resultado: `SIN SIMULACIÓN ACTIVA`.

El cambio de 2/5/10 minutos conserva un token de petición y muestra únicamente las estadísticas recibidas para el horizonte seleccionado.

## Reproducción exacta corregida

Prueba automatizada:

- operación anterior: detección 10:23:01 EC, entrada 10:23:06 EC y vencimiento 10:25:06 EC;
- inicio del proceso vigente: 10:58 EC;
- heartbeat vigente;
- resultado esperado y obtenido: `latest=null`, `SIN_SIMULACION_ACTIVA`, un pendiente obsoleto y cero activos.

La prueba se denomina `test_original_1023_record_is_not_active_for_process_started_at_1058`.

## Verificación contra el simulador en ejecución

El proceso no fue iniciado ni detenido. Los PID 10908 y 4652 forman una relación padre-hijo con la misma línea de comando; se trataron como una sola ejecución lógica, no como dos simuladores independientes.

Durante la comprobación, el lector corregido obtuvo exclusivamente del directorio activo:

| Horizonte | Estado mostrado | Vigencia |
|---|---|---|
| 120 s | SIN SIMULACIÓN ACTIVA | pendiente ya vencido rechazado |
| 300 s | SIN SIMULACIÓN ACTIVA después del vencimiento | pendiente vencido rechazado |
| 600 s | ACTIVA mientras no había alcanzado su vencimiento | registro actual aceptado |

El heartbeat seguía actualizándose. Posteriormente indicó `degraded / URLError` porque el servidor local no estaba accesible, pero el proceso del simulador continuaba vivo. No se intervino sobre él.

## Estadísticas

La consulta directa mostró conjuntos separados por horizonte. En la muestra observada cada horizonte tenía dos registros generados; 120 y 300 ya no tenían activos, mientras 600 conservaba uno hasta su vencimiento. Los NO EVALUABLE existentes permanecieron contabilizados.

No se mezcló ningún resultado `legacy-direct-bias-v0` con `experimental-confluence-v1`.

## Pruebas

| Prueba | Resultado |
|---|---:|
| Fase 6 + simulador prospectivo | 39/39 OK |
| Históricas/scoring | 43/43 OK |
| REALTIME v4 | 12/12 OK |
| UI análisis + sincronización | OK; 2 consultas de simulación |
| UI streaming/correcciones/timeframes | OK |
| Proceso aislado del analizador | OK |

El proceso aislado midió:

- endpoint de análisis p95: 0,7682 ms;
- `LiveFeed.snapshot()` p95: 1,1526 ms;
- cálculo de 500 barras: 27,984 ms fuera del hilo REALTIME.

El lector corregido, en 1.000 snapshots directos, obtuvo mediana 0,6333 ms y p95 1,1915 ms.

La consulta HTTP a la aplicación instalada no fue posible porque el puerto 5174 no estaba escuchando durante la comprobación final. La ruta se validó con Flask `test_client`, y el lector se verificó directamente contra los archivos que el simulador activo estaba actualizando. No se inició otra aplicación ni otro simulador.

## Integridad

Hashes protegidos sin cambios:

| Archivo | SHA-256 |
|---|---|
| `alpaca_live.py` | `10BA6B883803C5E1DB04666B3855B70542C47C47F16E544D9B8D2D501EBB8127` |
| `analysis_live.py` | `D1FFBD23EC85FF2B41BAC7F5F5751F433A5BCB1D8031421E1B466829A486250A` |
| `decision_engine_experimental.py` | `D6407B056BA78A5967CF56C2DE67635BCD87987E4208EE21E71C637AE61B6B74` |
| `simulador_prospectivo_nvda_2min.py` | `D018F1B07F24B654DEAC356996BD60725F393B9F7105991A9799FD194E1AC4C3` |

## Archivos modificados

- `simulation_results.py`
- `ui/live.html` — sólo textos/consumo del estado de simulación dentro del panel
- `pruebas/test_fase6_multihorizonte.py`
- `pruebas/probar_analysis_ui.js`

`app.py` fue inspeccionado y no requirió cambios.

## Respaldo y restauración

Respaldo verificable:

`auditoria\respaldo_pre_correccion_sync_fase6_20261119_112652`

Con TraderAssistant cerrado:

```powershell
powershell -ExecutionPolicy Bypass -File .\auditoria\restaurar_pre_correccion_sync_fase6_20261119.ps1
```

El script valida los hashes de los cuatro archivos corregidos antes de restaurarlos. No elimina ni modifica simulaciones actuales o históricas.

## Conclusión

La hipótesis antigua ya no puede heredar el heartbeat de otro directorio o proceso. La vigencia se decide por fuente, inicio de proceso, heartbeat, versión, ventana de entrada y vencimiento. Sin una simulación actual del horizonte elegido, el panel presenta ESPERAR / SIN SIMULACIÓN ACTIVA.
