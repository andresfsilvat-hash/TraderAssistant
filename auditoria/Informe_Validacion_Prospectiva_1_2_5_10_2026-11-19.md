# Informe de ampliación y validación prospectiva 1/2/5/10 minutos

Fecha: 2026-11-19 (Ecuador)  
Activo: NVDA  
Modo: exclusivamente simulación; órdenes deshabilitadas

## Resultado ejecutivo

Se incorporó el horizonte de 60 segundos al mismo motor experimental que ya evaluaba 120, 300 y 600 segundos. No se modificaron las reglas de decisión, el análisis técnico, Alpaca REALTIME, el WebSocket, las velas ni el gráfico. La interfaz permite seleccionar 1, 2, 5 o 10 minutos y mantiene 2 minutos como opción inicial.

También se agregó un validador prospectivo independiente que separa estadísticas por horizonte y versión de reglas, conserva `NO_EVALUABLE`, calcula referencias básicas y nunca declara automáticamente un horizonte ganador. La comparación con IQ Option queda pendiente hasta disponer de un archivo de precios exportado por el usuario; no se creó ninguna conexión ni automatización hacia IQ Option.

El simulador que ya estaba ejecutándose no fue detenido ni reiniciado. Por ello, su proceso actual continúa con 120/300/600 segundos y el horizonte de 60 segundos comenzará a generar observaciones únicamente en el próximo reinicio controlado. Esto evita alterar la sesión prospectiva en curso.

## Cambios aplicados

| Componente | Cambio | Ubicación principal | Estado |
|---|---|---|---|
| Motor experimental | Horizontes admitidos: 60, 120, 300 y 600 segundos | `decision_engine_experimental.py:16` | Implementado y probado |
| Simulador prospectivo | Predeterminado de cuatro horizontes y validación CLI | `simulador_prospectivo_nvda_2min.py:28`, `:351-362` | Implementado; 60 s pendiente del próximo reinicio controlado |
| Lector del panel | Expone los cuatro horizontes permitidos | `simulation_results.py:218` | Implementado y probado |
| Panel | Opción 1 minuto, sin cambios en la gráfica | `ui/live.html:172` | Implementado y probado |
| Validador independiente | Estadísticas, referencias, bootstrap por sesión, umbrales mínimos y comparación opcional IEX/IQ | `validar_prospectivo_multihorizonte.py:1-263` | Implementado y probado sin red |
| Pruebas de regresión | Cuatro horizontes, separación, NO_EVALUABLE, datos IQ ausentes y esquema inválido | `pruebas/test_validacion_prospectiva_multihorizonte.py:46-108` | 7 pruebas nuevas aprobadas |
| Prueba UI | Verifica la opción seleccionable de 1 minuto | `pruebas/probar_analysis_ui.js:6` | Aprobada |

## Criterio de validación

El validador agrupa por `horizonte_segundos` y `version_reglas`; no mezcla versiones ni duraciones. Para cada grupo informa:

- generadas, cerradas y registros pendientes;
- aciertos, fallos, empates y casos no evaluables;
- tasa de acierto solamente sobre casos evaluables;
- sesiones independientes;
- referencias “siempre SUBE” y “siempre BAJA” sobre los mismos precios IEX;
- intervalo bootstrap pareado por sesión frente a “siempre SUBE” cuando existen al menos dos sesiones;
- umbral de equilibrio únicamente si se proporciona explícitamente un payout;
- veredicto pendiente mientras no existan al menos 20 sesiones y 100 casos evaluables.

`automatic_best_horizon` permanece siempre en `null`. Cumplir el tamaño mínimo tampoco convierte automáticamente una duración en “la mejor”: aún exige ventaja estadística, información de payout y validación comparable con sesiones nuevas de IQ Option.

## Estado de la muestra actual

La ejecución reproducible quedó guardada en `auditoria/validacion_prospectiva_multihorizonte_20261119/resumen_validacion.json`.

| Horizonte | Cerradas | Evaluables | Aciertos | Fallos | NO_EVALUABLE | Sesiones | Veredicto |
|---:|---:|---:|---:|---:|---:|---:|---|
| 1 min | 0 | 0 | 0 | 0 | 0 | 0 | Aún no generado por el proceso activo |
| 2 min | 8 | 5 | 3 | 2 | 3 | 1 | PENDIENTE_MUESTRA_NUEVA |
| 5 min | 6 | 2 | 2 | 0 | 4 | 1 | PENDIENTE_MUESTRA_NUEVA |
| 10 min | 4 | 2 | 1 | 1 | 2 | 1 | PENDIENTE_MUESTRA_NUEVA |

Los porcentajes brutos de esta única sesión no constituyen evidencia de ventaja y no deben utilizarse para elegir duración ni operar. El archivo puede seguir cambiando mientras el simulador activo incorpora resultados; la tabla corresponde a la captura generada a las 17:53:10 UTC.

## Comparación con IQ Option

Se incluyó `auditoria/plantilla_precios_iq_option.csv` con columnas `timestamp_utc,price,product`. El validador busca el primer precio disponible en o después de la entrada y del vencimiento, dentro de una tolerancia predeterminada de 8 segundos. Si falta cualquiera de los dos precios, clasifica el caso como `NO_EVALUABLE`; nunca inventa ni interpola un resultado.

La comparación real está en estado `PENDIENTE_ARCHIVO_IQ_OPTION`. Los datos IEX y NVIDIA Blitz/IQ Option pueden diferir por fuente, producto, liquidez, latencia, spread y metodología de precio; por ello una coincidencia direccional en IEX no demuestra por sí sola un resultado equivalente en IQ Option.

## Pruebas reproducibles

Ejecutadas desde la raíz del proyecto con el entorno virtual existente, sin instalar dependencias:

```powershell
.\venv\Scripts\python.exe -B -m unittest discover -s pruebas -p 'test_*.py' -q
.\venv\Scripts\python.exe -B .\pruebas\probar_v4.py
.\venv\Scripts\python.exe -B .\pruebas\probar_analysis_live.py
node .\pruebas\probar_analysis_ui.js
node .\pruebas\probar_ui_node.js
.\venv\Scripts\python.exe -B .\validar_prospectivo_multihorizonte.py --output .\auditoria\validacion_prospectiva_multihorizonte_20261119
```

Resultados:

- 100 pruebas unitarias: `OK`.
- 12 pruebas del núcleo V4/REALTIME: `OK`.
- 12 pruebas del análisis: `OK`.
- Interfaz de análisis: `OK`, dos lecturas controladas del endpoint de simulación.
- Interfaz REALTIME: inicio, streaming, corrección y cambio de temporalidad `OK`.
- Validador: salida generada, tres grupos históricos actuales, IQ pendiente, horizonte ganador `null`.

## Integridad y límites de alcance

- `alpaca_live.py` conservó SHA-256 `10BA6B883803C5E1DB04666B3855B70542C47C47F16E544D9B8D2D501EBB8127`.
- `analysis_live.py` conservó SHA-256 `D1FFBD23EC85FF2B41BAC7F5F5751F433A5BCB1D8031421E1B466829A486250A`.
- No se modificaron WebSocket, autenticación, construcción/presentación de velas, gráfico, credenciales ni reglas experimentales.
- No se ejecutaron órdenes reales o simuladas en un broker.
- No se detuvo ni se creó otro simulador.
- El estado leído al cierre fue `running`, PID lógico 4652, `orders_enabled: false`, sin pendientes y con heartbeat 2026-11-19T18:08:48Z.

## Activación futura de 1 minuto

No debe iniciarse un segundo proceso en paralelo. En el próximo reinicio deliberado del simulador existente, la configuración predeterminada ya cargará 60/120/300/600. Antes de hacerlo debe comprobarse que el proceso anterior terminó y que no queda otro propietario del archivo de bloqueo. No se realizó ese reinicio en esta intervención para preservar la sesión activa.

## Respaldo y reversión

Respaldo previo exacto: `auditoria/respaldo_pre_validacion_1_2_5_10_20261119_124955`.  
Script de restauración: `auditoria/restaurar_pre_validacion_1_2_5_10_20261119.ps1`.

El script restaura únicamente los seis archivos existentes modificados, elimina los dos archivos de código/prueba creados por esta fase y conserva el informe, la plantilla, las salidas de auditoría y el respaldo.
