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

## Hallazgos de la auditoría del proyecto actual

1. `decision_engine_experimental.py` admite horizontes 60/120/300/600, pero todavía no 30 segundos; su decisión operativa permanece **ESPERAR**.
2. `evaluar_motor_multihorizonte.py` usa velas 1m y compara apertura/cierre de intervalos, por lo que no debe extrapolarse a precisión de entrada de 30 segundos.
3. `alpaca_live.py` ya implementa WebSocket, SSE, datos provisionales 5s, seguimiento de lag y reconexión. No reemplazar sin una prueba de regresión.
4. `analysis_live.py` ya separa cálculo mediante `ProcessPoolExecutor`; no mover cálculos al hilo del stream.
5. Las cotizaciones de **Alpaca IEX** no equivalen al precio de liquidación de **NVIDIA Blitz en IQ Option**. No afirmar rentabilidad ni probabilidades calibradas sin datos independientes de ejecución/vencimiento.
6. La marca de tiempo del sistema es una aproximación si los relojes no están sincronizados; en fases siguientes se debe medir el desfase con la plataforma de destino.

## Siguientes rondas (pendientes, no validadas)

- **Ronda 2:** pruebas comparativas histórica vs prospectiva con separación temporal, datos de calidad y tasa de abstención; soportar 30s solo con muestras suficientes de esa resolución.
- **Ronda 3:** planificador de oportunidades futuras a partir de evidencia causal, entrada programada, vencimiento, controles de calidad y registro inmutable.
- **Ronda 4:** integración aislada con módulos REALTIME y simulador actual; pruebas con mocks de reconexión/cancelación.
- **Ronda 5:** sincronización con IQ Option usando datos autorizados de la plataforma, evaluación de payout/latencia y pruebas supervisadas de extremo a extremo.
- **Ronda 6:** pruebas completas en Windows/VS Code y aceptación antes de fusionar a `main`; mejoras visuales después.

No se debe afirmar que V5 está lista para operar mientras los pasos pendientes no hayan sido probados.
