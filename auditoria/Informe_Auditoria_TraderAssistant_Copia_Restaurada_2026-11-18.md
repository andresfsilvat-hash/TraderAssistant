# Auditoría de la copia restaurada de TraderAssistant y propuesta de integración visual segura

**Fecha:** 18 de noviembre de 2026  
**Fuente exclusiva:** `TraderAssistant(1).zip` enviado por el usuario en esta conversación.  
**Alcance:** auditoría estática de código, comprobación de archivos, pruebas de instalador e interfaz con respuestas simuladas. No se utilizaron claves de Alpaca, se enviaron órdenes ni se ejecutó el streaming real en el PC del usuario.

## 1. Estado real de la copia

- ZIP: ~67 MB comprimidos, **11.205 entradas**; incluye `venv`, `.git`, cachés y respaldos. Los archivos originales fueron inspeccionados en modo lectura; la intervención no modifica el ZIP.
- `main.py` inicia Flask + WebView en `127.0.0.1:5174`, abriendo `/live`.
- `app.py` registra la vista de Alpaca y mantiene el analizador histórico original.
- `alpaca_live.py` contiene `VERSION = "4.0.0"` y `BUILD = "mercado-multiactivo-20261118"`.
- `ui/live.html` tiene **32.442 bytes**, SHA-256 `7356f5882c936131b11a0920247f8ea2cfa69b5c31b3a227957581e8a99ce601`. Está presente el ajuste responsive `TA_VIEWPORT_FIT_20261118_V1`, así como los botones **Línea: OFF** y **Volumen: OFF**.
- No estaba instalado el panel de decisiones de la versión que el usuario rechazó. El módulo independiente `decision_panel.py` no figura entre los archivos principales de esta copia, y `app.py` no importa ese módulo.

## 2. Funciones existentes aplicables al objetivo

| Función existente | Archivos | Adecuación para SUBE/BAJA de segundos o minutos |
|---|---|---|
| Cotizaciones IEX, WebSocket, velas y caché | `alpaca_live.py`, `ui/live.html` | Base de observación en vivo, **no** decisión validada |
| Historial reciente IEX de 1 minuto | `alpaca_live.py`, `cache/*.json` | Útil como muestra preliminar; límite actual **500 barras por activo** |
| Velas indicativas de 5 segundos | `alpaca_live.py` | Para observación, no equivalentes a barras oficiales de Alpaca |
| Ocho patrones de velas | `screener/pattern_detector.py` | Reutilizables tras verificar comportamiento en 1m/5s |
| RSI, MACD, Bollinger, regresión OLS | `screener/indicator_detector.py` | Ya implementados, pero necesitan pruebas por horizonte y validación numérica |
| Filtro SMA50 y puntuación LONG/SHORT | `screener/scorer.py` | Construidos para diario + 1h; **no traducir directamente** a SUBE/BAJA 30s–5m |
| Indicador histórico sin `Run Fresh Scan` | Interfaz original `ui/index.html` | Todavía no es motor de señales sobre Alpaca |
| Comparación de formas con días anteriores | Ninguno en la copia inspeccionada | Pendiente |
| Validación de entrada, vencimiento y rentabilidad | Ninguno en la copia inspeccionada | Pendiente |

### Datos en caché incluidos

Los seis activos cuentan con hasta **500 velas de 1 minuto** en caché (NVDA, SPY, QQQ, MSFT, AAPL y AMD). NVDA incluye aproximadamente **1.044 velas de 5 segundos**; los demás no tienen ese historial fino en el ZIP. Estas cifras reflejan el contenido de la copia, **no una prueba de continuidad de cotizaciones en la sesión actual**.

El código selecciona **un activo a la vez** para el WebSocket, decisión razonable para conservar la conexión IEX y no saturar la interfaz. El histórico disponible no prueba una ventaja estadística para operaciones con vencimiento fijo.

## 3. Por qué NO volveremos a acoplar cálculos al realtime durante esta entrega

La integración anterior modificó `app.py` y `ui/live.html` y añadió cálculos periódicos; el usuario observó una degradación posterior. No existe evidencia aislada suficiente para atribuir causalidad exacta a una sola función, pero es imprescindible recuperar la separación entre recepción/renderizado y análisis.

**Medida para esta entrega:** insertar un panel puramente visual que **no añade rutas Flask, API, llamadas HTTP, temporizadores, hilos ni cálculos de indicadores**. Únicamente lee el objeto de velas que la interfaz ya recibe para describir **la última vela oficial cerrada de un minuto**. La decisión se mantiene en **ESPERAR** y el horario de entrada, duración y vencimiento permanecen sin completar hasta que exista una regla validada.

## 4. Archivos incluidos en el parche

- `instalar_panel_visual_seguro.py`: instalador verificable con opciones `--verificar`, `--instalar` y `--restaurar`; no lee secretos ni utiliza red.
- `panel_visual_seguro/ui_live_patch.html`: plantilla completa que reemplazará únicamente `ui/live.html` **si coincide su SHA-256** con la copia restaurada.
- `LEEME_PANEL_VISUAL_SEGURO.txt`: instalación y restauración.

**Archivos que el instalador NO modifica:** `alpaca_live.py`, `app.py`, `main.py`, `requirements.txt`, `screener/*`, `cache/*`, `config.json`, `Alpaca_key.txt` ni los respaldos anteriores.

**Garantía de compatibilidad limitada:** si la copia local se modificó desde que se generó este ZIP, el instalador se detendrá antes de escribir. No se recomienda sobrescribir manualmente el archivo ni forzar la instalación.

## 5. Pruebas ejecutadas en el entorno aislado

| Prueba | Resultado |
|---|---|
| Comprobación del SHA-256 base y del parche | Aprobada |
| Sintaxis Python del instalador | Aprobada |
| Sintaxis JavaScript del panel y de la página | Aprobada con `node --check` |
| Instalación sobre copia temporal exacta | Aprobada |
| Reinstalación idempotente (sin sobrescritura) | Aprobada |
| Respaldo y restauración del HTML original | Aprobada |
| Rechazo de HTML con modificaciones del usuario | Aprobada |
| Renderizado en Chromium con respuesta histórica simulada, sin servidor Alpaca | Aprobado |
| Ventanas 1366×768, 1649×900 y 1920×1080, sin desbordamiento vertical total | Aprobadas en navegador de prueba |
| Reloj Ecuador actualizado por el temporizador **ya existente** | Aprobado |
| Última vela oficial cerrada de 1m y etiqueta explícita «NO una señal SUBE/BAJA» | Aprobado |
| Regresión de conexiones reales WebSocket, latencia y ejecución en Windows del usuario | **No realizada** |

**Nota visual:** a 1366×768 el gráfico disponible queda en torno a 234 px de altura en la simulación. No hay desplazamiento vertical, pero introducir el panel necesariamente consume parte de la altura. En pantallas estrechas es correcto permitir desplazamiento para conservar legibilidad.

## 6. Qué sigue para el análisis que realmente quiere el usuario

1. **Establecer la referencia del instrumento de IQ Option:** activo, precio de liquidación y reglas de vencimiento; no son necesariamente iguales al precio de IEX.
2. **Definir horizontes de evaluación:** por ejemplo 30 s, 60 s y 300 s, todos medidos respecto de la hora de entrada real; no asumir que las condiciones de una vela de 1m sirven para el cierre a 30s.
3. **Preparar muestras suficientes:** almacenar OHLCV/ticks válidos con marcas de tiempo y estado de mercado, conservando también los registros donde no hubo operaciones. Se necesitan más datos que los últimos 500 minutos si se va a comparar con los mismos horarios de semanas anteriores.
4. **Evaluación offline desacoplada:** reutilizar las funciones de `screener` en un proceso o ejecución de pruebas independiente, leyendo copias de datos históricos; nunca introducir recomputaciones intensivas dentro del WebSocket, el SSE o los callbacks de renderizado.
5. **Estudiar dos familias de señales:** indicadores técnicos existentes y similitud de secuencias históricas; medirlas sobre periodos posteriores, evitando filtración de datos futuros y sobreajuste.
6. **Medir métricas:** número de oportunidades, aciertos por horizonte, frecuencia de «NO OPERAR», estabilidad por hora del día y resultados esperados considerando costos/pagos y diferencia entre proveedores.
7. **Solo si las reglas superan validación fuera de muestra**, incorporar al panel un adaptador de señales con límites de carga y un comportamiento seguro (por defecto ESPERAR ante datos insuficientes, retrasados o contradictorios).

**No se puede fijar todavía el segundo exacto de entrada ni la duración óptima basándonos en los indicadores existentes; es un resultado que habría que validar estadísticamente.**

## 7. Condición para aceptar el nuevo panel

Comprobar en la PC del usuario que los datos y las velas de 5s/1m siguen actualizándose con la misma fluidez que antes, sin errores de JavaScript. De ocurrir cualquier degradación, usar `--restaurar` con la app detenida para volver al HTML anterior; verificar los hashes de ambos estados. No tocar motores de Alpaca ni cuentas financieras.

## Dictamen

**La copia es adecuada como base del análisis que queremos, pero no incorpora aún un motor validado para decidir SUBE/BAJA y la expiración de operaciones cortas.** El único cambio aconsejable por ahora es un panel de lectura **sin carga adicional de análisis**. No autorizamos la creación de señales inferidas a partir de una única vela roja o verde.
