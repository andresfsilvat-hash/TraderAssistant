# TraderAssistant — Diagnóstico histórico NVDA, decisiones de 2 minutos

**Estado: EXPLORATORIO; no apto para orientar entradas reales en IQ Option.**

## Datos y trazabilidad
- Fuente: `nvda_iex_1min_20261118_213505_280555.csv`; SHA-256 `d2e79dae5d3d77543725c12fe8b14631369dc7345637f4308bf8e726a35d82bb`.
- Velas totales: **25,221**; dentro de sesión regular: **24,566**.
- Sesiones: **63**; minutos regulares faltantes: **4**.
- Desarrollo cronológico: **40 sesiones** (2026-08-21 a 2026-10-16).
- Prueba retrospectiva posterior: **23 sesiones** (2026-10-19 a 2026-11-18).
- RSI (14), MACD (12,26,9), Bollinger (20,2) con parámetros originales y ocho patrones del detector ya existente.
- Se descartan preapertura, postmercado, barras de la misma sesión con gaps y operaciones que cruzan 16:00 ET.
- Se exige calentamiento de 60 velas dentro de cada sesión para evitar mezclar indicadores con saltos nocturnos.

## Resultados — cada estrategia evaluada en sus propios eventos no solapados

| Familia predefinida | Desarrollo: casos | Desarrollo: acierto | Prueba posterior: casos | Prueba posterior: acierto | Siempre SUBE en los mismos casos |
|---|---:|---:|---:|---:|---:|
| Consenso original sin contradicciones | 3,834 | 48.38 % | 2,165 | 50.44 % | 48.78 % |
| RSI original (<30 / >70) | 639 | 50.23 % | 332 | 55.42 % | 49.40 % |
| Reversión Bollinger original | 807 | 46.96 % | 425 | 49.18 % | 49.18 % |
| Cruce MACD original | 957 | 47.75 % | 548 | 50.73 % | 46.53 % |
| Patrones japoneses originales | 2,707 | 48.54 % | 1,497 | 49.50 % | 49.63 % |
| RSI extremo + giro histograma MACD (experimental) | 260 | 51.92 % | 120 | 45.00 % | 46.67 % |

**Regla elegida exclusivamente por desempeño de desarrollo (mínimo 80 casos):** RSI extremo + giro histograma MACD (experimental)

La selección sirve para una prueba retrospectiva, NO para recomendar operaciones. 
La prueba posterior no fue realmente ciega porque el historial ya se revisó en la auditoría previa.

## Regla seleccionada: comparación justa en prueba posterior

- Casos no solapados: **120**. Aciertos **54**, errores **64**, empates **2**.
- Acierto: **45.00 %** (intervalo bootstrap por sesiones 95 %: 36.87–54.46 %).
- Comparador siempre SUBE, mismos casos: **46.67 %**.
- Diferencia frente a siempre SUBE, intervalo bootstrap de 95 %: **-11.43 a 7.19 puntos**.
- Comparación última vela solo cuando ambos tienen dirección: 117 casos; estrategia **44.44 %**, última vela **46.15 %**.
- Cobertura en prueba (entradas no solapadas sobre minutos elegibles): **1.62 %**.

**Sensibilidad al desplazamiento de la entrada 60 segundos adicionales:**
- Casos con proxy alternativo disponible: **119** de 120 (excluidos 1 por falta de datos o cierre).
- Acierto proxy entrada tardía: **50.42 %**; referencia siempre SUBE en esos mismos casos: **47.90 %**.
- Este desplazamiento NO representa la latencia real observada: ilustra sensibilidad temporal con velas de 1 minuto.

## Interpretación y límites
- No puede inferirse el porcentaje de acierto en NVIDIA Blitz a partir de velas IEX.
- La disponibilidad efectiva de cada vela puede ser posterior a su cierre; no se garantiza poder entrar al precio de apertura proxy.
- Cada comparación con la referencia usa exactamente los mismos casos para evitar ventajas por selección de muestras.
- Se reporta incertidumbre por sesión, no como si miles de velas del mismo día fueran independientes.
- Elegir una regla por el resultado de desarrollo y observarla en fechas posteriores reduce parte del sesgo, pero no corrige el conocimiento previo del conjunto de datos.
- Todavía faltan sesiones futuras, datos de precio de la plataforma destino y una prueba simulada sincronizada.

**Decisión para la aplicación: ESPERAR. No habilitar SUBE/BAJA.**

## Uso sin afectar el realtime
Ejecutar únicamente con TraderAssistant cerrado para minimizar cargas. El script lee CSV local y módulos originales; no abre conexiones.
```powershell
.\venv\Scripts\python.exe -B .\evaluar_nvda_2min_validacion.py --csv ".\auditoria\historico_nvda_iex\nvda_iex_1min_20261118_213505_280555.csv"
```
Produce un CSV por minuto con RSI, histograma MACD, %B y señales, además de JSON de métricas e informe. No cambia interfaz ni cachés.
