"""Conservative experimental hypotheses over cached technical analysis.

This module never reads market connections, sends orders or changes the original
analysis.  The same hypothesis is evaluated at 120, 300 and 600 seconds so the
horizons can be compared without changing rules after observing outcomes.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone


RULES_VERSION = "experimental-confluence-v1"
VALIDATION_STATUS = "EXPERIMENTAL"
OPERATIONAL_DECISION = "ESPERAR"
SUPPORTED_HORIZONS = (120, 300, 600)

BULLISH_TRIGGERS = (
    "hammer", "bullish engulfing", "morning star", "bullish doji",
    "macd bullish crossover",
)
BEARISH_TRIGGERS = (
    "shooting star", "bearish engulfing", "evening star", "bearish doji",
    "macd bearish crossover",
)


def _number(value):
    try:
        number = float(value)
        return number if number == number and abs(number) != float("inf") else None
    except (TypeError, ValueError):
        return None


def _matching(signals, names):
    return [signal for signal in signals
            if any(name in str(signal).lower() for name in names)]


def _context_trends(analysis):
    """Return usable 1h/1d trends only when explicitly marked sufficient."""
    context = analysis.get("context") or {}
    result = {}
    for timeframe in ("1h", "1d"):
        item = context.get(timeframe) or {}
        if item.get("status") in ("ready", "sufficient") and item.get("trend") in ("Alcista", "Bajista", "Neutral"):
            result[timeframe] = item["trend"]
    return result


def evaluate_hypothesis(analysis, horizons=SUPPORTED_HORIZONS):
    """Build an auditable hypothesis without mutating ``analysis``.

    RSI and Bollinger mean-reversion labels are context, never standalone
    direction triggers. A directional pattern/crossover must agree with the
    current MACD histogram. Available 1h/1d context may veto, but never create,
    a hypothesis. No confidence score or optimized threshold is invented.
    """
    source = deepcopy(analysis) if isinstance(analysis, dict) else {}
    selected = tuple(int(value) for value in horizons)
    if not selected or any(value not in SUPPORTED_HORIZONS for value in selected):
        raise ValueError("horizons must be selected from 120, 300 and 600 seconds")

    signals = [str(item) for item in source.get("signals", []) if str(item).strip()]
    values = deepcopy(source.get("values") or {})
    bullish = _matching(signals, BULLISH_TRIGGERS)
    bearish = _matching(signals, BEARISH_TRIGGERS)
    macd_hist = _number(values.get("macd_histogram"))
    rsi = _number(values.get("rsi_14"))
    contradictions = []
    context = _context_trends(source)
    hypothesis = "ESPERAR"

    ready = (source.get("status") == "ready" and source.get("stale") is False
             and source.get("last_candle_time") and source.get("symbol") == "NVDA")
    if bullish and bearish:
        contradictions.append("Existen disparadores alcistas y bajistas simultáneos.")
    if rsi is not None and rsi >= 70 and macd_hist is not None and macd_hist > 0:
        contradictions.append("RSI alto coincide con impulso MACD alcista; no implica BAJA automática.")
    if rsi is not None and rsi <= 30 and macd_hist is not None and macd_hist < 0:
        contradictions.append("RSI bajo coincide con impulso MACD bajista; no implica SUBE automática.")
    if bullish and macd_hist is not None and macd_hist < 0:
        contradictions.append("Disparador alcista contradicho por histograma MACD bajista.")
    if bearish and macd_hist is not None and macd_hist > 0:
        contradictions.append("Disparador bajista contradicho por histograma MACD alcista.")

    if ready and not contradictions and macd_hist is not None:
        if bullish and not bearish and macd_hist > 0:
            hypothesis = "SUBE"
        elif bearish and not bullish and macd_hist < 0:
            hypothesis = "BAJA"

    if hypothesis != "ESPERAR":
        opposing = "Bajista" if hypothesis == "SUBE" else "Alcista"
        conflicts = [f"{timeframe} {trend}" for timeframe, trend in context.items() if trend == opposing]
        if conflicts:
            contradictions.append("Contexto contrario disponible: " + ", ".join(conflicts) + ".")
            hypothesis = "ESPERAR"

    if not ready:
        justification = "Análisis oficial no listo, obsoleto o perteneciente a otro activo."
    elif contradictions:
        justification = " ".join(contradictions) + " Se exige confluencia; hipótesis ESPERAR."
    elif hypothesis == "SUBE":
        justification = "Disparador alcista confirmado por histograma MACD positivo."
    elif hypothesis == "BAJA":
        justification = "Disparador bajista confirmado por histograma MACD negativo."
    elif not bullish and not bearish:
        justification = "No existe disparador direccional confirmado; RSI/Bollinger aislados no generan entrada."
    else:
        justification = "Falta confirmación concordante del impulso MACD; hipótesis ESPERAR."

    detected = source.get("computed_at") or datetime.now(timezone.utc).isoformat()
    return {
        "activo": source.get("symbol") or "",
        "analizado_utc": detected,
        "vela_oficial_id": source.get("last_candle_time"),
        "valores_indicadores": values,
        "evidencia_alcista": bullish,
        "evidencia_bajista": bearish,
        "indicadores_contradictorios": contradictions,
        "contexto_tendencia": context,
        "sesgo_tecnico_original": source.get("bias") or "Datos insuficientes",
        "hipotesis_simulacion": hypothesis,
        "justificacion": justification,
        "version_reglas": RULES_VERSION,
        "estado_validacion": VALIDATION_STATUS,
        "decision_operativa_validada": OPERATIONAL_DECISION,
        "horizontes_segundos": list(selected),
        "fuente": "Alpaca IEX; no IQ Option",
    }
