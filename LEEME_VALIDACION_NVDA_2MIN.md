# TraderAssistant — Evaluación cronológica NVDA, horizonte 2 minutos

**Solo investigación offline. No abre operaciones, no consulta Alpaca, no lee credenciales y no cambia el realtime.**

## Qué incluye

- `evaluar_nvda_2min_validacion.py`: lectura del CSV histórico IEX de 1 minuto, comprobaciones OHLCV, cálculo RSI/MACD/Bollinger con parámetros existentes y reutilización directa de `screener.pattern_detector` para patrones japoneses.
- `pruebas/test_evaluar_nvda_2min_validacion.py`: 16 pruebas automáticas (incluyendo coincidencia con detectores originales, ausencia de futuro en el cálculo, comparación justa y separación desarrollo/prueba).

La herramienta calcula seis familias **predefinidas**, separa **40 sesiones para desarrollar y seleccionar** una regla y **23 sesiones posteriores para evaluarla retrospectivamente**, sin cambiar la regla después de ver ese periodo. La división NO es una prueba ciega real porque este historial ya había sido inspeccionado. Las condiciones de ejecución son proxies de la primera transacción IEX por minuto; las velas oficiales pueden llegar con retardo y no son precios reales NVIDIA Blitz de IQ Option.

## Instalar

Descarga el ZIP y cierra TraderAssistant antes de ejecutar la evaluación para evitar competir por CPU:

```powershell
cd C:\Proyectos\TraderAssistant

# No sobrescribir archivos de una instalación anterior.
if ((Test-Path .\evaluar_nvda_2min_validacion.py) -or (Test-Path .\pruebas\test_evaluar_nvda_2min_validacion.py)) {
    throw 'El evaluador ya existe; no se sobrescribió.'
}

Expand-Archive -LiteralPath "$env:USERPROFILE\Downloads\TraderAssistant_Validacion_NVDA_2min_Offline.zip" -DestinationPath 'C:\Proyectos\TraderAssistant'

# Pruebas sin Internet ni claves.
.\venv\Scripts\python.exe -B .\pruebas\test_evaluar_nvda_2min_validacion.py

# Evaluación con el CSV que ya descargaste de Alpaca IEX.
.\venv\Scripts\python.exe -B .\evaluar_nvda_2min_validacion.py --csv '.\auditoria\historico_nvda_iex\nvda_iex_1min_20261118_213505_280555.csv'
```

Los archivos generados aparecerán en:

`C:\Proyectos\TraderAssistant\auditoria\validacion_nvda_2min\`

- `Informe_validacion_nvda_2min.md`: informe legible.
- `resumen_validacion_nvda.json`: métricas y fuente SHA-256.
- `eventos_validacion_nvda.csv`: cada minuto con sus indicadores, señales y resultados *hipotéticos*.

No altera los archivos originales de `screener`, `alpaca_live.py`, `analysis_live.py`, `app.py`, `main.py`, `ui/live.html` ni los cachés.

## Qué se considera un resultado positivo

Para siquiera empezar a pensar en un modo de avisos **simulados**, una estrategia elegida SIN mirar datos posteriores tendría que superar comparadores justos en días realmente nuevos, con muestras suficientes, sensibilidad razonable al retardo de entrada y precios comparables a los de liquidación de IQ Option. Este experimento **NO cumple esas condiciones**.

**Decisión operativa actual: ESPERAR.** Los porcentajes no justifican realizar operaciones reales.
