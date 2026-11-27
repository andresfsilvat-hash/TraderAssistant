"""Estado funcional V5 derivado de REALTIME y del analizador existente.

Solo lectura. No convierte hipótesis de Alpaca IEX en instrucciones IQ Option.
"""
from __future__ import annotations
from datetime import datetime, timezone
from math import isfinite

HORIZONTES = (30, 60, 120, 300, 600)


def _parse(timestamp):
    if not isinstance(timestamp, str):
        return None
    try:
        result = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if result.tzinfo is None:
            return None
        return result.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def construir_estado_v5(market, analysis, *, ahora_utc):
    """Diagnostica disponibilidad y conserva la abstención operativa."""
    if ahora_utc.tzinfo is None or ahora_utc.utcoffset() is None:
        raise ValueError("La hora actual requiere zona horaria")
    now = ahora_utc.astimezone(timezone.utc)
    market = market if isinstance(market, dict) else {}
    analysis = analysis if isinstance(analysis, dict) else {}
    symbol = market.get("symbol")
    direct = analysis.get("experimental_decision") or {}
    evaluations = direct.get("evaluaciones") or {}
    age = market.get("last_lag_ms")
    age_valid = isinstance(age, (int, float)) and not isinstance(age, bool) and isfinite(age)
    last_at = _parse(market.get("last_received_at"))
    fresh = bool(last_at and -0.5 <= (now-last_at).total_seconds() <= 2)
    same_symbol = (symbol == "NVDA" and analysis.get("symbol") == symbol)
    ready = same_symbol and analysis.get("status") == "ready" and analysis.get("stale") is False

    candidates = []
    for horizon in HORIZONTES:
        payload = evaluations.get(str(horizon))
        if not isinstance(payload, dict):
            continue
        side = payload.get("direccion")
        if side in ("SUBE", "BAJA"):
            candidates.append({"duracion_segundos": horizon,
                               "direccion_experimental": side,
                               "justificacion": str(payload.get("justificacion") or ""),
                               "operativa_autorizada": False})

    # El diagnóstico muestra por horizonte qué está impidiendo la señal,
    # sin modificar los criterios experimentales ni forzar entradas.
    rechazos = {}
    for horizon in HORIZONTES:
        item = evaluations.get(str(horizon))
        if isinstance(item, dict):
            rechazos[str(horizon)] = {
                "direccion": item.get("direccion") if item.get("direccion") in
                             ("SUBE", "BAJA") else "ESPERAR",
                "justificacion": str(item.get("justificacion") or "Sin justificación"),
                "contradicciones": list(item.get("evidencia_contra") or []),
                "faltantes": list(item.get("faltante") or []),
            }
        else:
            rechazos[str(horizon)] = {"direccion": "ESPERAR",
                                      "justificacion": "Horizonte no evaluado",
                                      "contradicciones": [], "faltantes": []}
    context = analysis.get("context") or {}
    daily = context.get("1d") or {}
    quality_alerts = []
    if daily.get("quality_flag") == "PRICE_SCALE_MISMATCH":
        quality_alerts.append({
            "codigo": "PRICE_SCALE_MISMATCH",
            "detalle": str(daily.get("reason") or ""),
            "desviacion_pct": daily.get("desviacion_frente_ultimo_precio_pct"),
        })

    reasons = []
    if not same_symbol:
        reasons.append("Sin análisis NVDA consistente con el activo REALTIME")
    if not ready:
        reasons.append("El análisis oficial no está listo o está obsoleto")
    if not fresh:
        reasons.append("No hay datos de mercado frescos")
    if not age_valid:
        reasons.append("No se puede comprobar el retardo de la última operación")
    if quality_alerts:
        reasons.append("Inconsistencia detectada en el histórico diario; contexto diario bloqueado")
    reasons.append("Falta validar el instrumento, la predicción anticipada y el vencimiento en IQ Option")
    return {
        "version": "v5-diagnostico-1",
        "estado": "ESPERAR",
        "operativa_autorizada": False,
        "direccion": None,
        "duracion_segundos": None,
        "entrada_utc": None,
        "segundos_para_entrada": None,
        "activo": symbol if isinstance(symbol, str) else None,
        "fuente": market.get("feed") if isinstance(market.get("feed"), str) else None,
        "mercado_fresco": fresh,
        "analisis_listo": bool(ready),
        "retardo_ultimo_trade_ms": age if age_valid else None,
        "hipotesis_experimentales": candidates,
        "diagnostico_por_duracion": rechazos,
        "alertas_calidad": quality_alerts,
        "motivos_espera": reasons,
        "ahora_utc": now.isoformat(),
    }
