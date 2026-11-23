# Informe de limpieza de TraderAssistant — 2026-11-23

## Resumen ejecutivo

Se realizó una limpieza conservadora de `C:\Proyectos\TraderAssistant` sin modificar la lógica de programación, el realtime, Alpaca, WebSocket, SSE, las velas de 5 segundos, los gráficos, el motor de decisiones ni los datos históricos. Se conservaron íntegros `venv`, `.git`, `auditoria`, `cache`, las configuraciones activas y todos los módulos de ejecución, simulación, evaluación y pruebas.

La limpieza eliminó únicamente 17 archivos de bytecode Python regenerable contenidos en cuatro carpetas `__pycache__`, después de copiarlos a un respaldo externo y comprobar sus hashes SHA-256. Dos informes que estaban en la raíz se trasladaron a `auditoria` y se actualizaron sus referencias documentales.

## Métricas

| Métrica | Antes | Después de la limpieza, antes de generar este informe |
|---|---:|---:|
| Archivos | 39.119 | 39.102 |
| Tamaño total | 588.026.728 bytes (560,79 MiB) | 587.711.865 bytes (560,49 MiB) |
| Reducción neta medida |  | 314.863 bytes |
| Caché eliminada, en bruto |  | 315.085 bytes |

El tamaño final medido a las 11:47:18, incluido este informe, es **587.728.745** bytes (560,50 MiB). La diferencia entre la reducción bruta y la neta se debe a las reglas añadidas a `.gitignore`, las rutas documentales actualizadas, el propio informe y a la actividad concurrente de Google Drive en `.tmp.driveupload`.

Distribución principal antes de limpiar:

| Elemento | Archivos | Bytes |
|---|---:|---:|
| `.tmp.driveupload` | 19.447 | 294.013.364 |
| `venv` | 9.803 | 197.463.968 |
| `.git` | 9.641 | 81.650.158 |
| `auditoria` | 115 | 12.946.030 |
| `ui` | 8 | 412.308 |
| `cache` | 6 | 399.715 |

## Elementos eliminados

- `__pycache__`: 10 archivos `.pyc`, 217.219 bytes.
- `pruebas/__pycache__`: 1 archivo `.pyc`, 13.727 bytes.
- `realtime_v4/__pycache__`: 1 archivo `.pyc`, 26.339 bytes.
- `screener/__pycache__`: 5 archivos `.pyc`, 57.800 bytes.

Total: 17 archivos y 315.085 bytes. Las cuatro carpetas vacías `__pycache__` también se retiraron. Las pruebas se ejecutaron con `PYTHONDONTWRITEBYTECODE=1` y `python -B`; no se recrearon cachés.

## Respaldo verificable

- Ubicación: `C:\Users\User\AppData\Local\Temp\TraderAssistant_Cleanup_Backup_20261123_114404`
- Contenido: copia de los 17 archivos eliminados, conservando sus rutas relativas, y `manifest_sha256.csv`.
- SHA-256 del manifiesto: `9373031427B349319B1ABB12782DC9AC84467F49FC2FE7CF282A93C4233BDAF4`.
- Verificación: cada copia fue comparada con su origen mediante SHA-256 antes de eliminar el original; las 17 coincidieron.

El respaldo no está dentro del árbol limpiado. La eliminación es recuperable copiando nuevamente los archivos del respaldo, aunque no es necesario porque Python los regenera.

## Organización realizada

Se trasladaron, sin alterar su contenido:

- `Informe_Auditoria_TraderAssistant_Copia_Restaurada_2026-11-18.md` a `auditoria/`.
- `Informe_Scoring_Completo_NVDA_2min_2026-11-18.md` a `auditoria/`.

Se actualizaron las referencias correspondientes en `LEEME_PANEL_VISUAL_SEGURO.txt` y `LEEME_SCORING_COMPLETO_2MIN.md`.

Se añadieron a `.gitignore` reglas específicas para `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `*.tmp`, `.tmp.driveupload` y `.tmp.drivedownload`. No se desversionó ni eliminó ningún archivo mediante Git.

## Archivos y áreas importantes conservados

- `app.py`, `main.py`, `alpaca_live.py`, `analysis_live.py`.
- `decision_engine_experimental.py`, `multitimeframe_context.py`, `simulation_results.py`.
- Simulador, evaluadores y validadores de 1, 2, 5 y 10 minutos.
- `screener`, `ui`, `pruebas`, `realtime_v4`, `integracion` y scripts de instalación/restauración.
- `requirements.txt`, `config.json`, `config.example.json` y credenciales/configuraciones excluidas por Git.
- Los 117 archivos de `auditoria` existentes después de reubicar los dos informes, con 12.960.957 bytes, antes de añadir este informe.
- Los seis históricos/cachés de mercado en `cache`, los históricos de NVDA y todos los resultados de auditoría.
- `venv` y `.git` completos.
- Copias `.bak` e instaladores antiguos: se conservaron porque existen restauradores, documentación o pruebas que los referencian, o porque su dependencia no pudo descartarse con certeza.

## Elementos conservados por seguridad

### Carpetas temporales de Google Drive

`.tmp.driveupload` no se eliminó. Inicialmente contenía 19.447 archivos y 294.013.364 bytes; en la instantánea de cierre ya contenía 19.448 archivos y 294.021.908 bytes, con modificación a las 11:47:18. Había dos procesos `GoogleDriveFS.exe` activos. Sus archivos incluyen ejecutables, CSV históricos y otros fragmentos de una carga, por lo que no puede afirmarse que sean residuos inactivos ni que no estén abiertos por la sincronización.

`.tmp.drivedownload` estaba vacía, pero también fue modificada hoy y se conservó por la misma razón. Estas carpetas quedaron ignoradas por Git para evitar miles de entradas no versionadas. Deben revisarse de nuevo únicamente cuando Google Drive haya terminado o esté detenido de forma controlada, comprobando antes estabilidad, integridad de la sincronización y un respaldo completo.

### Estado previo de Git

Antes de la limpieza ya estaban modificados `app.py`, `main.py`, `requirements.txt` y `ui/index.html`; no se revirtieron ni sobrescribieron. El repositorio contiene además numerosos archivos no versionados que forman parte del sistema actual y de `auditoria`; se conservaron.

## Pruebas ejecutadas

| Prueba | Resultado |
|---|---|
| `python -B -m unittest discover -s pruebas -p 'test_*.py' -v` | 107 pruebas, todas correctas |
| `python -B pruebas/probar_analysis_live.py` | 12 pruebas, todas correctas |
| `python -B pruebas/probar_v4.py` | 12 pruebas, todas correctas |
| `node pruebas/probar_ui_node.js` | Correcta: inicio, streaming, corrección y temporalidad |
| `node pruebas/probar_analysis_ui.js` | Correcta: UI, análisis, simulación y velas |
| `python -B pruebas/probar_analysis_process.py` | Correcta: worker, `/live`, caché y endpoint |

Resultado acumulado de pruebas Python automatizadas: 131 correctas, 0 fallos. El smoke test confirmó `/live` con HTTP 200, estado de análisis `ready`, decisión segura y lectura de 500 filas. No se emitieron órdenes reales.

Las pruebas cubrieron el flujo Flask, SUBE/BAJA/ESPERAR, los cuatro horizontes 60/120/300/600 segundos, el simulador, resultados, históricos, causalidad, realtime v4, correcciones de velas, JavaScript y protección de hashes.

## Hashes SHA-256 del código protegido

Los siguientes valores fueron calculados antes y después. Todos coincidieron:

| Archivo | SHA-256 |
|---|---|
| `app.py` | `820FFBCC43B53C1AEAFBD1BA920BC1203B4D39BF4CB1A6D3AE855A50FD7ED51A` |
| `main.py` | `67CD9EC723DAAB05E1B498FD765F46763FCA90E320C6D1AE99F7CC9AC08BE2DC` |
| `alpaca_live.py` | `10BA6B883803C5E1DB04666B3855B70542C47C47F16E544D9B8D2D501EBB8127` |
| `analysis_live.py` | `FB7B281D79553AB3FD13D91371662A6AEF4BD60F772892784A3910043A80A80B` |
| `decision_engine_experimental.py` | `B5399285980AA8D320B0E1917277A2FF6A517CF2422A6A38E8D5F635F4759F81` |
| `multitimeframe_context.py` | `77E53DA993A96D4BC9E9C29807B48B92F41383658F9D8A6ED8246AE021377B10` |
| `simulation_results.py` | `CFB882C810852EDC2EF74045D405CC3D0DDDA60FA8ADFA972C44E22FD9720753` |
| `simulador_prospectivo_nvda_2min.py` | `D94BDF3BB24727B7A6560A3F0AEB62D752ECC41D563C53DFB3AA374218F7D063` |
| `evaluar_motor_multihorizonte.py` | `E2A4BE4718C8320611FA2B0DF537270C33231DC6C0DE764E8B582E13D4F48744` |
| `validar_prospectivo_multihorizonte.py` | `91662927B537F5CC112A3076C7B4B39115ECB947D35A9797A479142326DD5949` |
| `realtime_v4/alpaca_live.py` | `C294659BD37DBAC2B41B2080AC9E0997566552F7EBD216A7742A816E7A6AD4DB` |
| `ui/index.html` | `358E471642DD9D4E3301809AB35B77C193C708AA490A656079E4DF36F77D1357` |
| `ui/live.html` | `AE0EF301489C0F1089ADE2284D2454E9F10795183F224B32152768F2A0D87DDA` |

## Pendientes y conclusión

La limpieza segura está completa y las pruebas no detectaron regresiones. El único elemento de gran tamaño pendiente es `.tmp.driveupload` (~280,39 MiB), conservado deliberadamente porque Google Drive lo estaba modificando durante la operación. El proyecto quedó sin cachés Python prescindibles fuera de las áreas protegidas, con los informes centralizados y con reglas de Git adecuadas para los temporales observados.
