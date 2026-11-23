# TraderAssistant — Observador prospectivo NVIDIA de 2 minutos (experimental)

**Versión:** 2026-11-19. **Propósito:** registrar hipótesis técnicas en nuevas sesiones, sin operar.

## Qué hace
- Es **un programa externo al servidor**: solo consulta `http://127.0.0.1:5174/api/analysis/live` y `.../api/alpaca/live`, rutas ya presentes en `TraderAssistant(2).zip`.
- **No modifica** el gráfico, `alpaca_live.py`, `analysis_live.py`, `app.py`, WebSocket, SSE, SQLite, caché o credenciales.
- No instala paquetes ni accede directamente a Alpaca o IQ Option. No genera ni ejecuta órdenes.
- Solo toma **NVIDIA** como activo; solo procesa **velas oficiales cerradas nuevas, publicadas después de arrancar**.
- Utiliza `bias=Alcista/Bajista` del análisis existente como hipótesis **no validada**. `Neutral`, `Contradictorio`, datos obsoletos o insuficientes quedan en observación sin operación hipotética.
- Espera un **trade IEX posterior** a la detección (hasta 30 segundos); toma ese precio como aproximación observada. Si no aparece, marca NO_EVALUABLE.
- Fija el vencimiento teórico **120 segundos después de ese primer trade observado**; para cerrar acepta únicamente un trade nuevo entre el instante previsto y los siguientes 8 segundos, conservando el desfase exacto. Si no llega, registra NO_EVALUABLE. No inventa precios.
- Nunca solapa dos pruebas hipotéticas. Si se cierra la terminal, puede recuperar pruebas pendientes del archivo local.

### Limitaciones técnicas fundamentales
- Los precios son **operaciones IEX** vistas mediante sondeo cada 5 segundos; no son precios ejecutables en IQ Option ni liquidaciones NVIDIA Blitz.
- No hay garantía de observar una transacción al segundo exacto de entrada/salida: las ventanas de aceptación se documentan.
- Una dirección alcista o bajista del motor existente **no ha demostrado ventaja fuera de muestra**. Esto solo registra sus resultados prospectivamente. No demuestra rentabilidad, probabilidad de acierto ni debe convertirse en consejo de entrada.
- Un sondeo extra al servidor local puede generar carga marginal; el impacto en la instalación del usuario durante mercado abierto **no ha sido medido**. Si ve algún problema, detenga únicamente el simulador con Ctrl+C.
- Las pruebas automatizadas usan datos sintéticos y no validan el feed durante mercado abierto.

## Instalación (con TraderAssistant cerrado)

Descargue `TraderAssistant_Simulador_Prospectivo_NVDA_2min.zip` en `C:\Users\User\Downloads`:

```powershell
cd C:\Proyectos\TraderAssistant
if (Test-Path .\simulador_prospectivo_nvda_2min.py) { throw "El complemento ya está instalado; no sobrescribir" }
Expand-Archive -LiteralPath "$env:USERPROFILE\Downloads\TraderAssistant_Simulador_Prospectivo_NVDA_2min.zip" -DestinationPath "C:\Proyectos\TraderAssistant"
.\venv\Scripts\python.exe -B .\pruebas\test_simulador_prospectivo_nvda_2min.py
```

## Primer uso en una sesión de mercado abierto

1. Abra TraderAssistant como acostumbra y seleccione **NVDA**.
2. En otra terminal PowerShell:

```powershell
cd C:\Proyectos\TraderAssistant
.\venv\Scripts\python.exe -B .\simulador_prospectivo_nvda_2min.py --diagnostico
```

3. Cuando muestre ambos estados locales, inicie la prueba:

```powershell
.\venv\Scripts\python.exe -B .\simulador_prospectivo_nvda_2min.py
```

4. Deje esa terminal abierta durante las observaciones. **No pulse SUBE/BAJA en IQ Option basándose en esas líneas de simulación.**
5. Detenga únicamente la consola del simulador con `Ctrl+C`, antes de cerrar TraderAssistant.

## Archivos de salida

`C:\Proyectos\TraderAssistant\auditoria\prospectivo_nvda_2min\`

- `observaciones_nvda.jsonl`: cada nueva vela analizada y los indicadores disponibles.
- `pendientes.json`: simulaciones aún no resueltas.
- `simulaciones_nvda_2min.csv`: casos terminados, resultados, empates y NO_EVALUABLE.

Las columnas incluyen instante de señal, instante de transacción de entrada observada, vencimiento objetivo 120s después, instante de última transacción usada como salida, desfase, resultado e indicadores. No contienen datos de autenticación.

Para auditoría, comparta el `simulaciones_nvda_2min.csv` tras varias sesiones nuevas; no hace falta compartir contraseñas ni toda la carpeta del proyecto.

## Para desinstalar

Con el observador cerrado, elimine solo estos dos nuevos archivos:
- `simulador_prospectivo_nvda_2min.py`
- `pruebas\test_simulador_prospectivo_nvda_2min.py`

Los registros se conservan en la carpeta de auditoría hasta que decida borrarlos.
