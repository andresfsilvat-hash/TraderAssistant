# Informe final — Corrección y estabilización REALTIME v4.0.0

**Fecha:** 2026-11-18  
**Proyecto:** `C:\Proyectos\TraderAssistant`  
**Estado de entrega:** parche preparado y probado; **no instalado en el proyecto activo**  
**Instalador:** `C:\Users\User\Downloads\Instalar_TraderAssistant_REALTIME_v4.ps1`  
**SHA-256 del instalador:** `3E98E0E896B7E3DB7904C04C517BACE117F64AC0041570D7E2D8A878ECBC492D`

## 1. Resultado ejecutivo

Se preparó un parche autocontenido para estabilizar REALTIME manteniendo la versión `4.0.0`. El parche corrige los defectos P0 reproducidos en la auditoría, incorpora las mejoras P1 verificables sin ampliar el proyecto hacia estrategias u órdenes, añade pruebas contra los archivos que realmente se instalarán en la raíz y proporciona respaldo y reversión automáticos.

El instalador fue ejecutado solamente sobre una copia temporal aislada. La instalación temporal, las 20 regresiones del backend, la prueba UI, la protección de archivos ajenos y la reversión pasaron correctamente. Los hashes originales fueron restaurados exactamente.

Los archivos activos del proyecto siguen sin cambios:

- `alpaca_live.py`: `10BA6B883803C5E1DB04666B3855B70542C47C47F16E544D9B8D2D501EBB8127`
- `ui/live.html`: `CB5A81D657FB0D8E6BC2AFE27CEA8BCFA798704E06966A304EE5C42A00D1C29A`

Por tanto, el proyecto actualmente instalado conserva el diagnóstico de **72 %** hasta que el usuario ejecute el instalador. La preparación corregida alcanza **89 % verificable** según la misma metodología; el porcentaje restante depende principalmente de validación prolongada durante sesión regular.

## 2. Errores corregidos

### Exactitud temporal y velas

- `open` y `close` provisionales se determinan por timestamp de mercado, no por orden de llegada.
- Trades desordenados dentro del minuto conservan correctamente apertura, cierre, máximo, mínimo y volumen.
- Los buckets tardíos de 5 segundos se insertan en orden dentro de una ventana acotada de 90 segundos.
- Trades recientes de un minuto ya oficial pueden completar una vela 5s sin modificar la barra oficial 1m.
- Eventos demasiado antiguos se descartan de la serie derivada y se contabilizan en `late_trade_drop_count`.
- La deduplicación exchange+trade-id evita sumar dos veces el volumen.
- Las barras oficiales continúan reemplazando la provisional sin mezclar volumen.
- La reconciliación REST puede corregir barras cerradas anteriores y actualiza `series_revision`.

### WebSocket y conexiones

- Exclusión interproceso mediante lock del sistema operativo. Dos instancias parcheadas no pueden abrir dos streams propios.
- El lock se libera automáticamente si el proceso termina abruptamente.
- Una segunda instancia de solo lectura ya no reescribe la caché al salir.
- La conexión solo declara `conectado` si Alpaca confirma `trades`, `quotes`, `bars` y `updatedBars` para el símbolo activo.
- Estado individual visible de los cuatro canales.
- Suscripción adicional confirmada a `corrections` y `cancelErrors`.
- Manejo controlado de 406, 407, 500, cierres de conexión y fallos de red.
- Backoff exponencial con jitter; el 406 usa pausa mínima más conservadora.
- Timeout explícito de autenticación y de confirmación de suscripciones.
- Reconexión registra causa, contador y último código.
- Correcciones/cancelaciones solicitan reconciliación REST sin alterar directamente una barra oficial desde un evento ambiguo.

### Historial, caché y símbolos

- Caché esquema 2 compatible con las cachés esquema 1 existentes.
- Origen por barra: `rest`, `websocket`, `cache`, `trades`, `live` o `mixed`.
- Estado de caché visible: recuperación, último guardado y error sanitizado.
- Escritura solamente cuando existen cambios de datos persistibles; evita sobrescribir caché con una segunda instancia pasiva.
- Cambio de símbolo reinicia canales, estado de caché, trades, quotes y series sin contaminar el activo nuevo.
- Respuestas históricas de un símbolo anterior continúan siendo descartadas.
- REST fallido conserva la última serie válida.

### Horarios y UI

- Fases `PREMARKET`, `REGULAR · ABIERTO`, `POSTMARKET`, `CERRADO` y `SIN VERIFICAR`.
- La fase utiliza el clock y calendario Alpaca del día, incluido `session_open/session_close`; no depende de la heurística semanal 08:00–17:00.
- Se muestran hora Ecuador, próxima apertura regular, próximo cierre regular y cuenta regresiva.
- Feriados y cierres tempranos se derivan del calendario devuelto por Alpaca.
- La ausencia de ticks se combina con la fase verificada y no aparenta movimiento.
- Se muestra spread bid/ask.
- Operación, quote y punto medio siguen separados; el punto medio se etiqueta como indicativo.
- Latencia servidor→pantalla se actualiza para trades o quotes, según el evento más reciente.
- Cada vela expone `quality` (`official`/`indicative`), `status` (`forming`/`closed`) y `origin`.
- Las velas 5s se identifican como derivadas de trades IEX, no oficiales.
- Las velas 5m muestran si el intervalo tiene menos de cinco barras 1m contribuyentes.
- La UI muestra canales, caché, fuente IEX y advertencia explícita de que IEX no es SIP.

## 3. Archivos entregados

### Instalados por el parche cuando sea autorizado

| Archivo | Propósito |
|---|---|
| `alpaca_live.py` | Motor REALTIME corregido: stream, OHLCV, locks, sesiones, caché y reconciliación. |
| `ui/live.html` | Estado de datos, spread, sesiones, fuentes, canales y velas. |
| `pruebas/probar_realtime_activo.py` | 20 regresiones que por defecto importan `C:\Proyectos\TraderAssistant\alpaca_live.py`. |
| `pruebas/probar_ui_realtime_activa.js` | Prueba la UI raíz `ui/live.html`. |

### No modificados

- `main.py`
- `app.py`
- `requirements.txt`
- `screener/`
- `config.json`
- LONG/SHORT, indicadores y estrategias
- credenciales Alpaca

No se añadieron dependencias.

### Artefactos de preparación

- Payload y pruebas: `auditoria/parche_realtime_v4_20261118/`
- Respaldo previo de preparación: `auditoria/respaldo_pre_estabilizacion_20261118_0905/`
- Instalador autocontenido dentro del proyecto: `auditoria/parche_realtime_v4_20261118/Instalar_TraderAssistant_REALTIME_v4.ps1`
- Copia lista para usar: `C:\Users\User\Downloads\Instalar_TraderAssistant_REALTIME_v4.ps1`

Después de instalar correctamente, puede borrarse la copia de Descargas sin afectar TraderAssistant.

## 4. Evidencia de pruebas

### PRUEBAS SIMULADAS

**Backend corregido:** 20/20 OK.

Cobertura incluida:

- trades ordenados/desordenados;
- `open/close` por timestamp;
- duplicados y volumen;
- buckets 5s tardíos y ventana máxima;
- barra oficial y correcciones;
- quotes atrasadas;
- ACK completo/parcial;
- errores 406, 407, 500 y fallo de red;
- reconexión y registro de causa;
- exclusión interproceso;
- caché/restauración y segunda instancia pasiva;
- fallo HTTP sin pérdida de caché;
- reconciliación REST;
- cambio de símbolo sin contaminación;
- PRE/REGULAR/POST, feriado y cierre temprano;
- solicitud de reconciliación ante corrección.

**UI corregida:** OK.

- carga del archivo que sería instalado;
- PREMARKET visible;
- spread;
- canales incompletos visibles;
- metadatos de calidad/origen;
- agregación OHLCV 5m, incluido volumen 150 desde cinco barras;
- redibujo por corrección SSE.

**Instalador:** OK sobre copia temporal.

- validación de baseline por SHA-256;
- respaldo automático;
- despliegue de cuatro archivos;
- sintaxis Python;
- 20 pruebas raíz;
- prueba UI raíz;
- verificación de `app.py`, `main.py`, `config.json` y `screener/` sin cambios;
- reversión;
- hashes originales restaurados.

### PRUEBA REAL CON ALPACA

Prueba de solo lectura realizada contra el payload corregido:

- Clock+calendar: `PREMARKET`, calendario verificado, mercado regular cerrado en ese instante.
- Autenticación WebSocket: exitosa.
- Símbolos: NVDA, SPY, QQQ, MSFT, AAPL y AMD.
- Para los seis símbolos Alpaca confirmó: `trades`, `quotes`, `bars`, `updatedBars`, `corrections`, `cancelErrors`.
- Errores Alpaca: 0.
- Durante una ventana de 2 segundos por símbolo se recibieron **52 quotes reales de QQQ**.
- No se recibieron trades, bars, updatedBars, corrections ni cancelErrors durante esas ventanas breves de premercado.
- La auditoría previa comprobó REST IEX HTTP 200, orden y OHLCV para los seis símbolos.

No se declara validada la recepción continua durante mercado regular porque esa condición no estuvo disponible durante la prueba.

## 5. Evidencia de que las pruebas apuntan al módulo activo

Los nuevos archivos no contienen referencias a `realtime_v4/alpaca_live.py` ni `realtime_v4/ui/live.html`.

- En una instalación normal, `probar_realtime_activo.py` calcula `ROOT = Path(__file__).resolve().parents[1]` y carga `ROOT / "alpaca_live.py"`.
- La prueba imprime la ruta exacta del backend probado.
- La prueba UI calcula la raíz desde su ubicación e inspecciona `ROOT/ui/live.html`.
- En el ensayo temporal, la salida confirmó rutas raíz dentro del proyecto temporal instalado, no el payload de desarrollo ni la copia antigua.

## 6. Porcentaje actualizado

Misma ponderación que la auditoría original:

| Área | Peso | Auditoría inicial | Parche preparado | Aporte actualizado |
|---|---:|---:|---:|---:|
| Alpaca IEX y conexión | 30 % | 72 % | 88 % | 26,40 % |
| Gráfico y velas | 25 % | 76 % | 90 % | 22,50 % |
| Horarios de mercado | 15 % | 58 % | 93 % | 13,95 % |
| Multiactivo | 15 % | 82 % | 90 % | 13,50 % |
| Rendimiento, recuperación y caché | 15 % | 69 % | 84 % | 12,60 % |
| **Total** | **100 %** | **72 %** |  | **89 %** |

**Interpretación:** 89 % es la preparación verificable del parche. El entorno activo continúa en 72 % hasta instalar. El 11 % restante no debe completarse con simulación: exige observación prolongada en sesión regular y pruebas de recuperación bajo condiciones reales.

## 7. Instalación — pendiente de autorización

No se ejecutó este procedimiento sobre el proyecto real.

1. Cerrar TraderAssistant y cualquier proceso que use el puerto 5174.
2. Abrir Windows PowerShell 5.1.
3. Ejecutar:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\Downloads\Instalar_TraderAssistant_REALTIME_v4.ps1"
```

El instalador:

- exige que los dos archivos activos conserven los hashes auditados;
- se detiene si detecta cambios desconocidos;
- crea un respaldo en `C:\Proyectos\TraderAssistant\auditoria\respaldo_instalacion_realtime_FECHA_HORA`;
- instala únicamente los cuatro archivos declarados;
- ejecuta sintaxis y regresiones;
- restaura automáticamente si algo falla;
- imprime la ubicación exacta del respaldo/reversor.

Para iniciar después de instalar:

```powershell
cd C:\Proyectos\TraderAssistant
.\venv\Scripts\python.exe .\main.py
```

## 8. Respaldo y reversión

Antes de desplegar, el instalador copia cada archivo original dentro del respaldo de instalación y genera:

```text
C:\Proyectos\TraderAssistant\auditoria\respaldo_instalacion_realtime_FECHA_HORA\Revertir_TraderAssistant_REALTIME_v4.ps1
```

Para revertir:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Proyectos\TraderAssistant\auditoria\respaldo_instalacion_realtime_FECHA_HORA\Revertir_TraderAssistant_REALTIME_v4.ps1"
```

El reversor comprueba que los archivos aún tengan los hashes instalados. Si detecta cambios posteriores, se detiene para no perderlos. La opción `-Force` existe únicamente para una reversión revisada conscientemente.

## 9. Limitaciones y validaciones pendientes

### Limitaciones permanentes de IEX

- IEX representa una sola bolsa y no el mercado consolidado SIP.
- Puede haber mercado regular activo sin trades recientes de IEX para un símbolo.
- Quotes IEX no equivalen al NBBO consolidado.
- Las velas 5s siguen siendo agregados derivados por TraderAssistant; no son barras oficiales Alpaca.
- REST 1m puede reconciliar barras oficiales, pero no reconstruye con exactitud una barra 5s afectada por una corrección/cancelación que no incluya suficiente detalle.

### Pendiente durante sesión regular

1. Soak test de una sesión completa.
2. Recepción continua de trades y quotes para los seis símbolos.
3. Al menos diez cierres `bars` y observación real de `updatedBars`.
4. Comparación automática WebSocket vs REST después del cierre.
5. Cambio repetido A→B→A bajo ticks reales.
6. Latencia p50/p95/p99 proveedor→servidor→pantalla.
7. CPU y RSS de backend y WebView durante 60 minutos o más.
8. Corte real de red y recuperación.
9. Reinicio durante sesión y backfill posterior.
10. Observación real de 406/407 si ocurre; no debe provocarse deliberadamente usando conexiones duplicadas.

## 10. Criterio de entrega

El parche está listo para revisión e instalación autorizada. No ejecuta órdenes, no modifica configuraciones personales, no cambia LONG/SHORT y no depende de Descargas después de instalarse. La etapa siguiente recomendada es instalarlo y realizar la matriz de validación durante sesión regular; solo entonces corresponde evaluar el avance final hacia 100 % verificable.
