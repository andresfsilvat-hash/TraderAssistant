# Evaluación exploratoria OFFLINE — horizonte nominal 2 minutos

**No apta para decisiones financieras reales.**

Esta prueba usa operaciones IEX agregadas a **1 minuto** y evalúa las 
funciones originales de TraderAssistant. No utiliza precios de NVIDIA Blitz.
El archivo es descriptivo, no un modelo validado ni una recomendación SUBE/BAJA.

## Contrato temporal de la evaluación

- La señal se calcula al **cierre** de una vela de 1 minuto.
- Entrada hipotética: **apertura de la siguiente vela de 1 minuto**.
- Vencimiento nominal: **120 segundos después** de esa apertura.
- Precio de salida aproximado: **apertura de la vela de 1 minuto que comienza al vencimiento**.
- Las aperturas son las primeras operaciones registradas en el intervalo, **no necesariamente al segundo exacto**.
- Se exige continuidad de los intervalos y permanencia dentro de sesión regular estadounidense.
- Solo indicadores y patrones existentes, sin entrenar reglas ni usar futuros al calcular señales.
- Para métricas principales, se seleccionan eventos sin solapamiento de 120 segundos.
- Empates cuentan como no aciertos; no se presupone cómo liquida IQ Option.

## Resumen por activo

| Símbolo | Sesiones | Eventos no solapados | Aciertos | Errores | Empates | Acierto (%) | Referencia última vela (%) | Evidencia |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| NVDA | 63 | 7167 | 3530 | 3549 | 88 | 49.25 | 47.27 | DESCRIPTIVO_NO_VALIDADO |

## Limitaciones críticas

1. Los cachés actuales representan aproximadamente **2–3 sesiones por activo**, insuficientes para validar una estrategia.
2. IEX y NVIDIA Blitz **no comparten necesariamente** reglas de precio, liquidez, vencimiento ni liquidación.
3. Señales original RSI/MACD/patrones se diseñaron para Daily/1h; aquí solo se examina su comportamiento exploratorio a 1m.
4. El precio de entrada y el de salida son **proxies de aperturas de velas**, no ejecuciones ni cotizaciones exactas a 120s.
5. No se estiman costos, spreads, retardo de clic, deslizamiento, comisiones ni horario de vencimiento en IQ Option.
6. La evaluación no ajusta parámetros, no tiene validación fuera de muestra y **no justifica entradas reales**.

## Archivo de trazabilidad

`eventos_2min.csv` contiene horas de cálculo, entrada/vencimiento nominales, precios proxy, dirección, señales y resultado.
El campo `nonoverlap_selected` identifica los eventos utilizados en la métrica principal.

El evaluador no modifica el realtime, el motor de análisis en vivo ni las credenciales.
