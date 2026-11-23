"""Motor experimental, causal y auditable para hipótesis NVDA multihorizonte.

No abre conexiones, no envía órdenes y no modifica el análisis recibido. Las
familias correlacionadas se representan una sola vez (por ejemplo, línea MACD,
señal e histograma forman una familia de impulso).
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone


RULES_VERSION = "experimental-causal-groups-v2"
VALIDATION_STATUS = "EXPERIMENTAL_NO_VALIDADO"
OPERATIONAL_DECISION = "ESPERAR"
SUPPORTED_HORIZONS = (60, 120, 300, 600)

BULLISH_PATTERNS = ("hammer", "bullish engulfing", "morning star", "bullish doji")
BEARISH_PATTERNS = ("shooting star", "bearish engulfing", "evening star", "bearish doji")


def _number(value):
    try:
        number = float(value)
        return number if number == number and abs(number) != float("inf") else None
    except (TypeError, ValueError):
        return None


def _side_label(side):
    return "SUBE" if side > 0 else "BAJA" if side < 0 else "NEUTRAL"


def _exclusive_side(bullish, bearish):
    return 1 if bullish and not bearish else -1 if bearish and not bullish else 0


def _context_item(source, timeframe):
    item = (source.get("context") or {}).get(timeframe) or {}
    trend = item.get("trend")
    side = 1 if trend == "Alcista" else -1 if trend == "Bajista" else 0
    sufficient = item.get("status") in ("ready", "sufficient")
    return item, side if sufficient else None


def _evidence_groups(source):
    values = source.get("values") or {}
    signals = [str(item) for item in source.get("signals", []) if str(item).strip()]
    patterns = [str(item) for item in source.get("patterns", []) if str(item).strip()]
    lowered_patterns = [item.lower() for item in patterns]
    pattern_bull = [item for item, low in zip(patterns, lowered_patterns)
                    if any(name in low for name in BULLISH_PATTERNS)]
    pattern_bear = [item for item, low in zip(patterns, lowered_patterns)
                    if any(name in low for name in BEARISH_PATTERNS)]

    macd = _number(values.get("macd_12_26"))
    macd_signal = _number(values.get("macd_signal_9"))
    histogram = _number(values.get("macd_histogram"))
    previous_histogram = _number(values.get("macd_histogram_previous"))
    momentum = 0
    if None not in (macd, macd_signal, histogram):
        if macd > macd_signal and histogram > 0:
            momentum = 1
        elif macd < macd_signal and histogram < 0:
            momentum = -1

    trend_1m = values.get("trend_1m")
    price = 1 if trend_1m == "Alcista" else -1 if trend_1m == "Bajista" else 0
    rsi = _number(values.get("rsi_14"))
    percent_b = _number(values.get("bollinger_percent_b"))
    lower_signal = any("lower bb mean-reversion" in item.lower() for item in signals)
    upper_signal = any("upper bb mean-reversion" in item.lower() for item in signals)
    reversal_bull = lower_signal or (rsi is not None and percent_b is not None and rsi <= 30 and percent_b <= .15)
    reversal_bear = upper_signal or (rsi is not None and percent_b is not None and rsi >= 70 and percent_b >= .85)
    reversal = _exclusive_side(reversal_bull, reversal_bear)
    volume_ratio = _number(values.get("volume_ratio"))
    volume_confirmed = bool(volume_ratio is not None and volume_ratio >= 1.15)
    hour_item, hour = _context_item(source, "1h")
    day_item, day = _context_item(source, "1d")
    daily_sma = None
    if day is not None:
        position = day_item.get("sma50_position")
        daily_sma = 1 if position == "above" else -1 if position == "below" else 0

    acceleration = None
    if histogram is not None and previous_histogram is not None:
        acceleration = "aumenta" if histogram > previous_histogram else "disminuye" if histogram < previous_histogram else "estable"
    return {
        "patron": {"side": _exclusive_side(pattern_bull, pattern_bear),
                    "bullish": pattern_bull, "bearish": pattern_bear},
        "impulso_macd": {"side": momentum, "macd": macd, "signal": macd_signal,
                         "histogram": histogram, "histogram_change": acceleration},
        "tendencia_1m": {"side": price, "label": trend_1m or "No disponible"},
        "reversion_rsi_bollinger": {"side": reversal, "rsi": rsi, "percent_b": percent_b},
        "volumen": {"confirmed": volume_confirmed, "ratio": volume_ratio},
        "contexto_1h": {"side": hour, "status": hour_item.get("status", "insufficient"),
                        "trend": hour_item.get("trend")},
        "contexto_1d": {"side": day, "status": day_item.get("status", "insufficient"),
                        "trend": day_item.get("trend")},
        "sma50_diaria": {"side": daily_sma, "position": day_item.get("sma50_position")},
    }


def _describe(name, group):
    if name == "volumen":
        return f"volumen {'confirmado' if group['confirmed'] else 'sin confirmar'} (ratio {group.get('ratio')})"
    side = group.get("side")
    label = _side_label(side) if side is not None else "NO DISPONIBLE"
    return f"{name.replace('_', ' ')}: {label}"


def _evaluation(horizon, groups, ready_reason=None):
    missing, contradictions = [], []
    if ready_reason:
        return {"horizonte_segundos": horizon, "direccion": "ESPERAR",
                "estado": "DATOS_INSUFICIENTES", "evidencia_favor": [],
                "evidencia_contra": [], "faltante": [ready_reason],
                "justificacion": ready_reason, "aviso": "HIPÓTESIS EXPERIMENTAL — NO OPERAR"}

    pattern = groups["patron"]["side"]
    momentum = groups["impulso_macd"]["side"]
    price = groups["tendencia_1m"]["side"]
    reversal = groups["reversion_rsi_bollinger"]["side"]
    volume = groups["volumen"]["confirmed"]
    hour = groups["contexto_1h"]["side"]
    day = groups["contexto_1d"]["side"]
    daily_sma = groups["sma50_diaria"]["side"]
    direction = 0
    required_names = []

    if horizon == 60:
        required_names = ["impulso MACD", "patrón o reversión RSI/Bollinger"]
        trigger = pattern if pattern else reversal
        if momentum and trigger == momentum and price in (0, momentum):
            direction = momentum
        elif not momentum:
            missing.append("Falta impulso MACD direccional.")
        elif not trigger:
            missing.append("Falta patrón o reversión RSI/Bollinger confirmada.")
        elif trigger != momentum:
            contradictions.append("El disparador inmediato contradice al impulso MACD.")
        if direction and hour == -direction:
            contradictions.append("El contexto 1h se opone al movimiento de 1 minuto.")
            direction = 0
    elif horizon == 120:
        required_names = ["impulso MACD", "tendencia 1m", "confirmación adicional"]
        extra = pattern == momentum or reversal == momentum or volume
        if momentum and price == momentum and extra:
            direction = momentum
        else:
            if not momentum:
                missing.append("Falta impulso MACD direccional.")
            if not price:
                missing.append("La tendencia 1m es neutral.")
            if momentum and price and momentum != price:
                contradictions.append("Impulso MACD y tendencia 1m se contradicen.")
            if not extra:
                missing.append("Falta patrón, reversión o volumen confirmatorio independiente.")
        if direction and hour == -direction:
            contradictions.append("El contexto 1h es contrario.")
            direction = 0
    elif horizon == 300:
        required_names = ["impulso MACD", "tendencia 1m", "contexto 1h"]
        if hour is None:
            missing.append("Contexto 1h insuficiente.")
        elif momentum and price == momentum and hour == momentum:
            direction = momentum
        else:
            if not momentum:
                missing.append("Falta impulso MACD direccional.")
            if not price:
                missing.append("La tendencia 1m es neutral.")
            directional = [side for side in (momentum, price, hour) if side]
            if directional and len(set(directional)) > 1:
                contradictions.append("1m, impulso y 1h no están alineados.")
    else:
        required_names = ["tendencia 1m", "contexto 1h", "contexto 1d", "SMA50 diaria"]
        if hour is None:
            missing.append("Contexto 1h insuficiente.")
        if day is None:
            missing.append("Contexto 1d insuficiente.")
        if daily_sma is None:
            missing.append("SMA50 diaria no disponible.")
        if price and hour == price and day == price and daily_sma == price and momentum in (0, price):
            direction = price
        else:
            directional = [side for side in (price, hour, day, daily_sma, momentum) if side]
            if directional and len(set(directional)) > 1:
                contradictions.append("Las tendencias 1m/1h/1d o el impulso no están alineados.")

    if direction and pattern == -direction:
        contradictions.append("El patrón japonés se opone a la dirección candidata.")
    if direction and reversal == -direction:
        contradictions.append("La familia RSI/Bollinger se opone a la dirección candidata.")
    if contradictions:
        direction = 0
    favorable, opposing = [], []
    if direction:
        for name, group in groups.items():
            side = group.get("side")
            if side == direction or (name == "volumen" and group.get("confirmed")):
                favorable.append(_describe(name, group))
            elif side == -direction:
                opposing.append(_describe(name, group))
    chosen = _side_label(direction) if direction else "ESPERAR"
    if direction:
        reason = f"{chosen} para {horizon}s: " + "; ".join(favorable) + "."
    else:
        details = contradictions + missing
        reason = ("ESPERAR: " + " ".join(details)) if details else (
            "ESPERAR: no se completó la combinación exigida de " + ", ".join(required_names) + ".")
    return {"horizonte_segundos": horizon, "direccion": chosen,
            "estado": "HIPOTESIS_EXPERIMENTAL" if direction else "ESPERAR_JUSTIFICADO",
            "evidencia_favor": favorable, "evidencia_contra": opposing + contradictions,
            "faltante": missing, "justificacion": reason,
            "aviso": "HIPÓTESIS EXPERIMENTAL — NO OPERAR"}


def evaluate_hypothesis(analysis, horizons=SUPPORTED_HORIZONS):
    """Evaluar cada duración con reglas propias y datos disponibles en ese instante."""
    source = deepcopy(analysis) if isinstance(analysis, dict) else {}
    selected = tuple(int(value) for value in horizons)
    if not selected or any(value not in SUPPORTED_HORIZONS for value in selected):
        raise ValueError("horizons must be selected from 60, 120, 300 and 600 seconds")
    ready_reason = None
    if source.get("symbol") != "NVDA":
        ready_reason = "El activo analizado no es NVDA."
    elif source.get("status") != "ready":
        ready_reason = "El análisis oficial todavía no está listo."
    elif source.get("stale") is not False:
        ready_reason = "Los datos están obsoletos."
    elif not source.get("last_candle_time"):
        ready_reason = "No existe una vela oficial cerrada identificable."
    groups = _evidence_groups(source)
    evaluations = {str(horizon): _evaluation(horizon, groups, ready_reason) for horizon in selected}
    primary = evaluations.get("120") or evaluations[str(selected[0])]
    bullish = [_describe(name, group) for name, group in groups.items() if group.get("side") == 1]
    bearish = [_describe(name, group) for name, group in groups.items() if group.get("side") == -1]
    detected = source.get("computed_at") or datetime.now(timezone.utc).isoformat()
    return {
        "activo": source.get("symbol") or "", "analizado_utc": detected,
        "disponible_utc": detected, "vela_oficial_id": source.get("last_candle_time"),
        "valores_indicadores": deepcopy(source.get("values") or {}),
        "grupos_evidencia": groups, "evidencia_alcista": bullish,
        "evidencia_bajista": bearish,
        "indicadores_contradictorios": primary["evidencia_contra"],
        "contexto_tendencia": deepcopy(source.get("context") or {}),
        "sesgo_tecnico_original": source.get("bias") or "Datos insuficientes",
        "hipotesis_simulacion": primary["direccion"],
        "justificacion": primary["justificacion"], "evaluaciones": evaluations,
        "version_reglas": RULES_VERSION, "estado_validacion": VALIDATION_STATUS,
        "decision_operativa_validada": OPERATIONAL_DECISION,
        "horizontes_segundos": list(selected), "fuente": "Alpaca IEX; no IQ Option",
        "aviso": "HIPÓTESIS EXPERIMENTAL — NO OPERAR",
    }
