# TraderAssistant — puntuación completa original y evaluación de 2 minutos (OFFLINE)

Este complemento fue ejecutado sobre `NVDA_90_Dias_OHLCV.zip` del usuario. **No cambia el gráfico, las velas realtime, Alpaca, Flask, el panel ni las credenciales**. No instala paquetes, no conecta a Internet y no presenta señales operativas.

## Archivos incluidos

- `evaluar_scoring_completo_nvda_2min.py`: adapta el scorer ORIGINAL existente, conservando su lógica.
- `pruebas/test_scoring_completo_2min.py`: 14 pruebas automatizadas nuevas.
- `auditoria/scoring_completo_2min/resultados_scoring_completo.json`: resumen reproducible y especificación de las tres políticas.
- `auditoria/scoring_completo_2min/operaciones_no_solapadas.csv`: registro de las operaciones hipotéticas evaluadas, con puntuación, motivos, hora y datos de contexto.
- `auditoria/Informe_Scoring_Completo_NVDA_2min_2026-11-18.md`: interpretación de resultados y limitaciones.

El complemento requiere los archivos existentes en la instalación actual:
- `screener/scorer.py`, `screener/indicator_detector.py`, `screener/pattern_detector.py`.
- `evaluar_nvda_2min_validacion.py` (instalado en la fase anterior).
- Dependencias `pandas`, `numpy` y `ta` que ya utiliza TraderAssistant.

## Instalación sin sobrescribir archivos existentes

1. Cierra TraderAssistant para evitar consumir CPU mientras estudias el historial.
2. Descarga `TraderAssistant_Scoring_Completo_NVDA_2min.zip` en la carpeta Descargas.
3. PowerShell:

```powershell
cd C:\Proyectos\TraderAssistant
if ((Test-Path '.\evaluar_scoring_completo_nvda_2min.py') -or (Test-Path '.\pruebas\test_scoring_completo_2min.py')) {
    throw 'El complemento ya existe; no sobrescribas archivos sin compararlos.'
}
Expand-Archive -LiteralPath "$env:USERPROFILE\Downloads\TraderAssistant_Scoring_Completo_NVDA_2min.zip" -DestinationPath 'C:\Proyectos\TraderAssistant'
.\venv\Scripts\python.exe -B .\pruebas\test_scoring_completo_2min.py
.\venv\Scripts\python.exe -B .\evaluar_scoring_completo_nvda_2min.py --csv '.\auditoria\historico_nvda_iex\nvda_iex_1min_20261118_213505_280555.csv'
```

Si deseas mantener la carpeta de auditoría anterior intacta, añade `--output-dir '.\auditoria\scoring_completo_2min_prueba'` al último comando.

## ¿Qué se probó?

1. **Original diario + 1 hora**: usa `score_tickers()` exactamente con señales originales Daily y 1h, confirmación de volumen, coincidencia entre temporalidades, SMA50 y OLS. Genera un caso al cambiar la dirección neta de la puntuación.
2. **Completo adaptado a 1m**: usa `score_tickers()` con señales de la vela 1m recién cerrada **más** las de la última 1h y diaria totalmente cerradas. Requiere un disparador nuevo en 1m. Mantiene los mismos ajustes originales de volumen y SMA50.
3. **1m con filtros**: usa señales 1m, pero conserva el filtro diario SMA50 y la confirmación de volumen con velas 1h completas; como referencia de ablación, sin sumar señales de 1h y diario al puntaje base.

Los eventos se calculan solo desde velas que habían cerrado y se evalúan con **open de próxima vela 1m** y **open 120 segundos después**, con la salvedad de que esto NO equivale a una ejecución real ni a NVIDIA Blitz.

Se excluyen velas incompletas, intervalos faltantes y operaciones que cruzan el cierre. El tramo de 15:30 a 16:00 de Nueva York no se interpreta erróneamente como vela de una hora completa.

## Resultado y seguridad

El análisis retrospectivo **no encontró evidencia suficiente de ventaja estadística para habilitar SUBE/BAJA**. Conservar `ESPERAR` como decisión operativa del panel. El estudio sí deja registrado qué condiciones activó el sistema, qué puntuación calculó y los resultados históricos. Para validar el sistema completo desde el primer día, hace falta más historia para la SMA50 diaria; la mayor parte de la muestra no cumple esa condición.

El ZIP se puede instalar sobre el proyecto actual, pero **no actualiza automáticamente el panel ni añade análisis mientras opera la bolsa**. Todo se ejecuta bajo demanda y separado del realtime.
