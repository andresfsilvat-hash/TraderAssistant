# TraderAssistant — corrección del simulador prospectivo NVDA 2 minutos

Fecha: 19 de noviembre de 2026.

## Motivo

La primera versión podía registrar hipótesis antes de la apertura del mercado regular (por ejemplo a las 08:50 hora de Ecuador el 19 de noviembre). El estudio retrospectivo de 63 sesiones utilizó exclusivamente la sesión regular. Mezclar esos registros haría la comparación engañosa.

## Cambios

- Rechaza hipótesis con velas o detección fuera de 09:30 a 16:00 hora de Nueva York, lunes a viernes.
- Considera horario de verano e invierno de Estados Unidos mediante reglas del calendario, sin instalar `tzdata`.
- No permite abrir hipótesis cuyo vencimiento podría cruzar el cierre habitual del mercado.
- Descarta como `NO_EVALUABLE`, no como fallo, los registros premercado pendientes de la versión anterior si se reutiliza una carpeta de resultados.
- Conserva detección, precios reales IEX, vencimiento fijo de 120 segundos y pruebas de no solapamiento.
- No modifica `app.py`, `analysis_live.py`, `alpaca_live.py`, `ui/live.html` ni el gráfico.

**Limitación:** el filtro horario no conoce automáticamente festivos, suspensiones o cierres anticipados de la bolsa. En esas jornadas, se deberá incorporar un calendario oficial antes de considerar muestras válidas. Datos IEX no son liquidaciones IQ Option.

## Instalación protegida

1. Detener solo la terminal del simulador con Ctrl+C; mantener TraderAssistant abierto si se desea.
2. Desde `C:\Proyectos\TraderAssistant` ejecutar:

```powershell
New-Item -ItemType Directory -Force .\auditoria\respaldo_simulador_pre_horario | Out-Null
Copy-Item .\simulador_prospectivo_nvda_2min.py .\auditoria\respaldo_simulador_pre_horario\ -Force
Copy-Item .\pruebas\test_simulador_prospectivo_nvda_2min.py .\auditoria\respaldo_simulador_pre_horario\ -Force
Expand-Archive -LiteralPath "$env:USERPROFILE\Downloads\TraderAssistant_Simulador_NVDA_Correccion_Horario.zip" -DestinationPath "C:\Proyectos\TraderAssistant" -Force
.\venv\Scripts\python.exe -B .\pruebas\test_simulador_prospectivo_nvda_2min.py
```

3. Solo al aprobar las 19 pruebas:

```powershell
.\venv\Scripts\python.exe -B .\simulador_prospectivo_nvda_2min.py --output-dir .\auditoria\prospectivo_nvda_2min_sesion_regular
```

El directorio nuevo permite mantener separados los primeros registros anteriores al filtro.

## Recuperación

Detener el simulador (`Ctrl+C`) y restaurar los dos archivos desde `auditoria\respaldo_simulador_pre_horario`. No se deben eliminar los registros originales de auditoría.
