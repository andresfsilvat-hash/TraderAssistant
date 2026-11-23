# Auditoría independiente de TraderAssistant(2).zip — base para evaluar SUBE/BAJA a dos minutos

**Fecha:** 18 de noviembre de 2026  
**Alcance:** revisión de código, documentación, cachés locales y pruebas sin credenciales ni conexiones de mercado.  
**Integridad:** la copia subida no fue modificada. Las pruebas se ejecutaron sobre una extracción de trabajo independiente.

## 1. Estado comprobado

- **REALTIME:** `alpaca_live.py` contiene recepción por WebSocket de Alpaca IEX, soporte de operaciones/cotizaciones, velas, caché por símbolo y exposición de datos al panel web.
- **Analizador live:** `analysis_live.py` contiene una copia validada de velas oficiales cerradas de 1 minuto, `ProcessPoolExecutor(max_workers=1)`, detección de cambios y correcciones, y un endpoint de resultados cacheados `/api/analysis/live`.
- **Integración:** `app.py` registra tanto `register_live(app)` como `register_live_analysis(app)`.
- **Interfaz:** `ui/live.html` muestra sesgo, indicadores, patrones, hora de última vela y estado operativo **ESPERAR**. Conserva los controles de temporalidades, Línea y Volumen.
- **Indicadores originales reutilizados:** RSI(14), MACD(12,26,9), Bollinger(20,2), ocho patrones japoneses y clasificación textual de señales desde `screener/scorer.py`. El `score_tickers()` original diario/1h no se utiliza como regla de entrada en el módulo live.
- **Ausencias:** no se encontró una estrategia validada para vencimiento de dos minutos, una rutina de backtesting de señales SUBE/BAJA con liquidación al vencimiento, reglas de entrada, comparador histórico de secuencias ni fuente de precios históricos de NVIDIA Blitz de IQ Option.

## 2. Pruebas ejecutadas independientemente

- Compilación sintáctica Python de los módulos principales: **correcta**.
- `node pruebas/probar_analysis_ui.js`: **correcta** (2 consultas de análisis por 3 actualizaciones del gráfico en el escenario de prueba).
- `pruebas/probar_analysis_live.py`: **12 de 12 pruebas aprobadas**, con copias de bibliotecas Python presentes en el ZIP, cargadas en un directorio aislado.
- `compute_live_analysis()` ejecutado sobre el caché de seis activos: **6 resultados válidos**, con 500 velas por activo y tiempos de ejecución aproximados de 4 a 8 ms en el equipo de prueba.
- No se validaron WebSocket real, latencia extremo a extremo, arranque de Windows ni liquidaciones de IQ Option. Las pruebas de laboratorio no sustituyen la validación durante una sesión real.

## 3. Datos históricos realmente disponibles en el ZIP

| Activo | Velas 1m | Días calendario en ese caché | Pares de velas con separación exacta de 2m | Velas guardadas de 5s |
|---|---:|---:|---:|---:|
| NVDA | 500 | 2 | 471 | 1.200 |
| SPY | 500 | 3 | 485 | 0 |
| QQQ | 500 | 3 | 460 | 0 |
| MSFT | 500 | 2 | 489 | 0 |
| AAPL | 500 | 3 | 473 | 0 |
| AMD | 500 | 3 | 488 | 0 |

Los pares de dos minutos constituyen una **medida de cobertura temporal**, no operaciones probadas ni oportunidades ganadoras. Son observaciones intensamente solapadas, por lo que no deben tratarse como muestras estadísticamente independientes. Las 1.200 velas 5s de NVDA son indicativas de IEX y no equivalen a un historial oficial completo de NVIDIA Blitz.

## 4. Brechas para la meta de dos minutos

1. **Definir el producto:** diferenciar NVIDIA IEX (acción/mercado) de NVIDIA Blitz en IQ Option (precio de liquidación, horario, spread y reglas de vencimiento). Sin equivalencia de datos, el rendimiento estimado en IEX puede no replicarse en IQ Option.
2. **Definir señal antes de conocer el futuro:** condiciones calculadas exclusivamente con datos disponibles en la marca temporal de decisión; incorporar tiempo real hasta la visualización y tiempo de entrada realista.
3. **Historial suficiente:** recolectar sesiones completas en múltiples fechas, con origen de datos, correcciones, calidad y continuidad; mantener un dataset separado de las ventanas recientes de gráficos.
4. **Prueba de resultado a 120 segundos:** precio observado al disparar la señal frente al precio 120 segundos después según el producto usado, con reglas claras para empate/no cotización y horario permitido.
5. **Validación fuera de muestra:** separación temporal por sesiones, ventanas no solapadas para métricas principales y comparación contra un criterio simple; evitar reglas elegidas con conocimiento de datos futuros.
6. **Viabilidad económica:** medir porcentaje de aciertos, pérdidas, pagos reales, cobertura de señales y robustez por hora/mercado; mantener **ESPERAR** cuando la evidencia es insuficiente.
7. **Arquitectura sin regresiones:** motor experimental offline con datos congelados, separado de Alpaca WebSocket/SSE; no agregar tareas de backtesting dentro de los callbacks de cotizaciones.

## 5. Recomendación

**Siguiente etapa propuesta, sin instalar nada aún:** documentar el contrato del experimento para señales hipotéticas a 120 segundos; construir un evaluador histórico offline con los indicadores ya existentes, inicialmente sobre IEX, y registrar tanto resultados favorables como fallos. No conectar resultados al panel como SUBE/BAJA operativos hasta validar varias sesiones fuera de muestra y comprobar correspondencia con la liquidación de NVIDIA Blitz.

**Estado actual:** la infraestructura de visualización y análisis técnico existe. La capacidad de generar indicaciones de entrada y vencimiento rentables está **sin demostrar**. No existe base empírica suficiente para asignarle un porcentaje de acierto o proclamar precisión del análisis SUBE/BAJA.
