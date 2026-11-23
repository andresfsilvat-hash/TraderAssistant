# Auditoría progresiva — TraderAssistant V5

## Objetivo acordado

Preservar V4 y todas sus funcionalidades. Prioridad absoluta: determinar, sobre evidencia comprobable, **cuándo preparar una entrada**, **SUBE/BAJA** y la **duración (30, 60, 120, 300 o 600 segundos)**. La presentación gráfica es secundaria. No hay órdenes automáticas.

## Ronda 1 — Núcleo temporal (implementada en `v5-development`)

Archivos añadidos:
- `engine/reloj_entrada.py`: reloj puro y determinista sin depender de Flask, Alpaca ni la UI.
- `pruebas/test_reloj_entrada_v5.py`: pruebas unitarias de transición, cinco duraciones, invalidación por datos antiguos/futuros, validación de UTC.
- `.github/workflows/v5-reloj-tests.yml`: ejecución automática de esas pruebas en cada cambio de la rama V5 y su PR.

Estados: ESPERAR → PREPARARSE (30 s antes) → CUENTA_REGRESIVA (10..1 s) → ENTRAR (instante hipotético) → VENTANA_CERRADA. CANCELADA ante datos obsoletos o relojes desincronizados. Los tiempos de 30 y 10 segundos son parámetros iniciales, no garantías de previsión.

**Límite esencial:** este reloj **NO** crea `HipotesisEntrada(validada=True)`. La palabra «validada» solo representa una condición que deberá determinar un proceso de validación posterior; no representa confianza operativa. `operativa_autorizada` siempre es `False`. Nunca usar esta primera versión para decidir operaciones reales.

Comando de prueba desde la raíz:
```bash
python -m unittest discover -s pruebas -p 'test_reloj_entrada_v5.py' -v
```

## Ronda 2 — Validador temporal fuera de muestra (implementado)

- `engine/validacion_temporal.py`: registros inmutables de entrada/vencimiento, dirección, precio, fuente y payout opcional.
- `pruebas/test_validacion_temporal_v5.py`: 12 casos para separación temporal, duplicados, fechas inválidas, payout ausente, resultados, intervalos Wilson y filtros por fuente.
- Separa entrenamiento (< corte) de pruebas (señal detectada >= corte); descarta eventos cruzados, evitando fuga temporal.
- Los resultados **no** demuestran precisión predictiva. Sin observaciones autorizadas del instrumento IQ Option y sin validación prospectiva, el campo `operativa_autorizada` es siempre falso.
- CI incluye todas las pruebas V5 mediante `python -m unittest discover -s pruebas -p \'test_*_v5.py\' -v`.

## Rondas 3 y 4 — Diagnóstico HTTP y entrada de datos auditados

- `engine/estado_v5.py`: agregador puro de estados de REALTIME y del analizador; expone las hipótesis experimentales por horizonte, comprueba símbolo, vigencia de datos y timestamps.
- `v5_diagnostics.py`: nuevo endpoint GET `/api/v5/estado` integrado en `app.py`, sin modificar gráficos ni realizar órdenes. Los resultados actuales permanecen en `ESPERAR` hasta que exista validación independiente y anticipación demostrada.
- `pruebas/test_estado_v5.py` y `pruebas/test_api_v5.py`: pruebas de estados y HTTP con Flask, incluidas peticiones de solo lectura y rechazo de POST.
- `engine/validacion_temporal.py` + `v5_validar_csv.py`: carga de observaciones reproducibles en CSV, duraciones exactas, atribución de fuente y cálculo de aciertos fuera de muestra. No sustituye a registros reales de IQ Option.
- `pruebas/test_csv_v5.py`: pruebas de formato, fechas, duraciones y acceso de solo lectura.

Para probar el endpoint, en Windows, desde `C:\\Proyectos\\TraderAssistant` tras descargar la rama de desarrollo:

```powershell
python -m unittest discover -s pruebas -p 'test_*v5.py' -v
python main.py
```

Con la aplicación abierta, consultar `http://127.0.0.1:5174/api/v5/estado` en el navegador. Es diagnóstico experimental; no debe usarse como señal de operación.

Para evaluar un CSV proporcionado por el usuario (nunca asumir que IEX liquida NVIDIA Blitz):

```powershell
python v5_validar_csv.py observaciones.csv --corte-utc 2026-11-23T15:00:00+00:00 --minimo 30 --fuente IQ_OPTION
```

Columnas CSV: `detectada_utc,entrada_utc,vencimiento_utc,duracion_segundos,direccion,precio_entrada,precio_salida,fuente,payout_neto`. Los timestamps requieren zona horaria y el precio de salida debe corresponder al vencimiento real.

**Bloqueador explícito:** siguen faltando muestras prospectivas verificables de NVIDIA Blitz, su calendario/reglas de expiración y la medición de latencia de interacción del usuario. No es responsable prometer una hora exacta de entrada ni una tasa de acierto mientras falte esa evidencia. La ejecución del módulo de diagnóstico sí es posible, pero el objetivo operativo aún no está validado.

## Hallazgos de la auditoría del proyecto actual

1. `decision_engine_experimental.py` admite horizontes 60/120/300/600, pero todavía no 30 segundos; su decisión operativa permanece **ESPERAR**.
2. `evaluar_motor_multihorizonte.py` usa velas 1m y compara apertura/cierre de intervalos, por lo que no debe extrapolarse a precisión de entrada de 30 segundos.
3. `alpaca_live.py` ya implementa WebSocket, SSE, datos provisionales 5s, seguimiento de lag y reconexión. No reemplazar sin una prueba de regresión.
4. `analysis_live.py` ya separa cálculo mediante `ProcessPoolExecutor`; no mover cálculos al hilo del stream.
5. Las cotizaciones de **Alpaca IEX** no equivalen al precio de liquidación de **NVIDIA Blitz en IQ Option**. No afirmar rentabilidad ni probabilidades calibradas sin datos independientes de ejecución/vencimiento.
6. La marca de tiempo del sistema es una aproximación si los relojes no están sincronizados; en fases siguientes se debe medir el desfase con la plataforma de destino.

## Siguientes rondas (pendientes, no validadas)

- **Ronda 2:** completar alimentación de la validación con observaciones reales y medir tasa de abstención; 30s solo con muestras suficientes de esa resolución.
- **Ronda 3:** planificador de oportunidades futuras a partir de evidencia causal, entrada programada, vencimiento, controles de calidad y registro inmutable.
- **Ronda 4:** integración aislada con módulos REALTIME y simulador actual; pruebas con mocks de reconexión/cancelación.
- **Ronda 5:** sincronización con IQ Option usando datos autorizados de la plataforma, evaluación de payout/latencia y pruebas supervisadas de extremo a extremo.
- **Ronda 6:** pruebas completas en Windows/VS Code y aceptación antes de fusionar a `main`; mejoras visuales después.

No se debe afirmar que V5 está lista para operar mientras los pasos pendientes no hayan sido probados.
