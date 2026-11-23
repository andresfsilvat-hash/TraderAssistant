"""Planificador reproducible de entrada para SIMULACIÓN, no para operar.

Deriva la ventana desde la marca de análisis. No reprograma cada polling.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import ceil

from engine.reloj_entrada import HipotesisEntrada, evaluar_reloj

HORIZONTES_EVALUADOS_V4 = (60, 120, 300, 600)


def _fecha(value):
    if not isinstance(value, str):
        return None
    try:
        t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, OverflowError):
        return None
    return t.astimezone(timezone.utc) if t.tzinfo is not None and t.utcoffset() is not None else None


def simular_reloj_de_hipotesis(analysis, market, *, ahora_utc, horizonte=120,
                               preparacion_segundos=30):
    """Reproduce la cuenta atrás desde una hipótesis causal.

    No calcula la probabilidad, no conoce el vencimiento IQ Option y nunca
    convierte una hipótesis en autorización de entrada.
    """
    result = {"modo": "SIMULACION", "estado": "ESPERAR",
              "direccion_experimental": None, "duracion_segundos": None,
              "segundos_para_entrada": None, "entrada_utc": None,
              "operativa_autorizada": False,
              "motivo": "Sin hipótesis temporal elegible"}
    if ahora_utc.tzinfo is None or ahora_utc.utcoffset() is None:
        raise ValueError("Hora actual sin zona horaria")
    now = ahora_utc.astimezone(timezone.utc)
    if horizonte not in HORIZONTES_EVALUADOS_V4:
        return {**result, "motivo": "Horizonte todavía no calibrado para simulación"}
    if not isinstance(analysis, dict) or not isinstance(market, dict):
        return result
    if (analysis.get("status") != "ready" or analysis.get("stale") is not False
            or analysis.get("symbol") != "NVDA" or market.get("symbol") != "NVDA"):
        return {**result, "motivo": "Análisis no disponible o activo incompatible"}
    decision = (analysis.get("experimental_decision") or {}).get("evaluaciones") or {}
    slot = decision.get(str(horizonte)) or {}
    side = slot.get("direccion")
    if side not in ("SUBE", "BAJA"):
        return {**result, "motivo": "El motor experimental indica ESPERAR"}
    detected = _fecha(analysis.get("computed_at"))
    feed_time = _fecha(market.get("last_received_at"))
    if detected is None or feed_time is None or (now-detected).total_seconds() < 0:
        return {**result, "motivo": "Marcas temporales insuficientes o futuras"}
    # Se requiere una hipótesis reciente. Datos de un minuto anterior no sirven
    # para construir una nueva oportunidad futura por simple extrapolación.
    if (now-detected).total_seconds() > 90:
        return {**result, "motivo": "Análisis demasiado antiguo"}
    # Próxima frontera de minuto con al menos 30 segundos desde la detección.
    stamp = ceil((detected.timestamp() + preparacion_segundos) / 60) * 60
    target = datetime.fromtimestamp(stamp, timezone.utc)
    if target <= detected:
        target += timedelta(minutes=1)
    hypo = HipotesisEntrada(side, horizonte, target, detected, validada=True)
    reading = evaluar_reloj(hypo, ahora_utc=now, ultimo_dato_utc=feed_time,
                            preparacion_segundos=preparacion_segundos)
    return {**result, "estado": reading.estado.value,
            "direccion_experimental": side, "duracion_segundos": horizonte,
            "segundos_para_entrada": reading.segundos_para_entrada,
            "entrada_utc": target.isoformat(), "motivo": reading.motivo,
            "vencimiento_hipotetico_utc": (target+timedelta(seconds=horizonte)).isoformat(),
            "aviso": "SIMULACIÓN EXPERIMENTAL — NO OPERAR"}
