"""Observación causal de velas IEX de 5 s (NO predicción validada de 30 s).

Las velas de 5 s son indicativas y no equivalen a vencimientos de IQ Option.
No emite órdenes ni fechas recomendadas de entrada.
"""
from __future__ import annotations
from datetime import datetime, timezone
import math


def analizar_micro_30s(short_candles, *, ahora_utc: datetime,
                       ventana=24, umbral_impulso=0.0005, volumen_minimo=1.2):
    if ahora_utc.tzinfo is None or ahora_utc.utcoffset() is None:
        raise ValueError("Se requiere reloj UTC con zona horaria")
    if ventana < 12 or ventana % 6:
        raise ValueError("La ventana debe ser múltiplo de 6 y >=12")
    if umbral_impulso <= 0 or volumen_minimo <= 0:
        raise ValueError("Umbrales inválidos")
    base = {"duracion_segundos": 30, "estado": "ESPERAR", "direccion_experimental": None,
            "operativa_autorizada": False, "fuente": "ALPACA_IEX_5S_INDICATIVA"}
    if not isinstance(short_candles, list) or len(short_candles) < ventana:
        return {**base, "motivo": "Historial de 5s insuficiente"}
    now = ahora_utc.astimezone(timezone.utc).timestamp()
    # Solo los últimos N registros, no rellena huecos con velas inventadas.
    rows = short_candles[-ventana:]
    times, closes, volumes = [], [], []
    for bar in rows:
        if not isinstance(bar, dict) or bar.get("origin") == "cache":
            return {**base, "motivo": "Vela de caché o formato inválido"}
        try:
            t = int(bar["time"])
            c = float(bar["close"])
            vol = float(bar["volume"])
        except (ValueError, TypeError, KeyError, OverflowError):
            return {**base, "motivo": "Vela de 5s incompleta"}
        if t % 5 or not math.isfinite(c) or c <= 0 or not math.isfinite(vol) or vol <= 0:
            return {**base, "motivo": "Tiempo, precio o volumen inválido"}
        if t + 5 > now:
            return {**base, "motivo": "Vela de 5s todavía abierta"}
        times.append(t)
        closes.append(c)
        volumes.append(vol)
    if any(b-a != 5 for a,b in zip(times, times[1:])):
        return {**base, "motivo": "Huecos u orden incorrecto entre velas de 5s"}
    if now - (times[-1] + 5) > 5:
        return {**base, "motivo": "Última vela de 5s atrasada"}
    first, last = closes[0], closes[-1]
    momentum = last / first - 1
    latest_volume = sum(volumes[-6:]) / 6
    previous_volume = sum(volumes[:-6]) / (ventana-6)
    volume_ratio = latest_volume / previous_volume if previous_volume else 0
    direction = ("SUBE" if momentum >= umbral_impulso else
                 "BAJA" if momentum <= -umbral_impulso else None)
    if volume_ratio < volumen_minimo:
        direction = None
    return {**base, "estado": "OBSERVACION_EXPERIMENTAL" if direction else "ESPERAR",
            "direccion_experimental": direction,
            "motivo": ("Impulso 5s observado, no pronóstico ni recomendación" if direction else
                       "Impulso o volumen insuficiente"),
            "impulso_observado": round(momentum, 8),
            "ratio_volumen": round(volume_ratio, 4),
            "ultima_vela_cerrada_utc": datetime.fromtimestamp(times[-1] + 5,
                                                              timezone.utc).isoformat()}
