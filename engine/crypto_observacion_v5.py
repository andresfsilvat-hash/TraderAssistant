"""Análisis experimental de cripto (Alpaca), puro, causal y sin operaciones.

No reutiliza reglas ni resultados de NVIDIA. Las hipótesis SUBE/BAJA no están
calibradas ni verificadas contra precios de vencimiento de IQ Option. Se basan
solo en velas de 1 minuto CERRADAS, para registrar hipótesis a futuro.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import ceil, isfinite

HORIZONTES = (60, 120, 300, 600)
VERSION = "crypto-observacion-v5-1"
SIMBOLOS = ("BTC/USD", "ETH/USD", "SOL/USD")


def _utc(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Se requiere datetime consciente de zona horaria")
    return value.astimezone(timezone.utc)


def _date(value):
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return _utc(result)
    except (ValueError, TypeError, OverflowError):
        return None


def _ema(values, period):
    if len(values) < period:
        return None
    a = 2 / (period + 1)
    current = sum(values[:period]) / period
    for value in values[period:]:
        current = (value - current) * a + current
    return current


def _rsi(values, period=14):
    if len(values) < period + 1:
        return None
    changes = [values[i] - values[i-1] for i in range(1, len(values))]
    up = sum(max(0, x) for x in changes[:period]) / period
    down = sum(max(0, -x) for x in changes[:period]) / period
    for d in changes[period:]:
        up = (up * (period-1) + max(0, d)) / period
        down = (down * (period-1) + max(0, -d)) / period
    if down == 0:
        return 100.0 if up else 50.0
    return 100 - 100 / (1 + up / down)


def _parse_closed(candles, now):
    cleaned = {}
    for bar in candles if isinstance(candles, list) else []:
        if not isinstance(bar, dict) or bar.get("provisional") is True:
            continue
        try:
            stamp = int(bar["time"])
            o, h, l, c = (float(bar[k]) for k in ("open", "high", "low", "close"))
            volume = float(bar["volume"])
            if (stamp <= 0 or stamp % 60 != 0 or stamp + 60 > now.timestamp()
                    or any(not isfinite(v) for v in (o, h, l, c, volume))
                    or min(o, h, l, c) <= 0 or volume < 0
                    or h < max(o, c) or l > min(o, c)):
                continue
            cleaned[stamp] = {"time": stamp, "close": c, "volume": volume}
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    return [cleaned[k] for k in sorted(cleaned)]


def _base(symbol, now):
    return {"version": VERSION, "symbol": symbol, "ahora_utc": now.isoformat(),
            "estado": "ESPERAR", "motivo": "Sin datos evaluables",
            "mercado": "Alpaca Crypto US 24/7", "indicadores": {},
            "calidad": {"apta": False, "motivos": []}, "evaluaciones": {},
            "reloj_experimental": {"modo": "SIMULACION", "estado": "ESPERAR",
                "motivo": "Sin hipótesis verificable", "direccion_experimental": None,
                "duracion_segundos": None, "entrada_utc": None,
                "segundos_para_entrada": None, "operativa_autorizada": False},
            "operativa_autorizada": False,
            "probabilidad_acierto": None,
            "aviso": "HIPÓTESIS EXPERIMENTAL — NO OPERAR. "
                     "Alpaca Crypto no es IQ Option. Sin ventaja estadística demostrada."}


def _reloj(side, duration, last_bar, now, receipt):
    out = {"modo": "SIMULACION", "estado": "ESPERAR",
           "motivo": "Sin ventana temporal", "direccion_experimental": side,
           "duracion_segundos": duration, "entrada_utc": None,
           "segundos_para_entrada": None, "operativa_autorizada": False}
    # La entrada se ancla exclusivamente al cierre conocido de la vela:
    # no se reprograma al repreguntar la API.
    entry_ts = (last_bar["time"] + 120)
    target = datetime.fromtimestamp(entry_ts, timezone.utc)
    out["entrada_utc"] = target.isoformat()
    out["vencimiento_hipotetico_utc"] = (target + timedelta(seconds=duration)).isoformat()
    remaining = (target - now).total_seconds()
    if receipt is None or (now-receipt).total_seconds() > 15:
        out.update(estado="CANCELADA", motivo="Recepción del proveedor obsoleta")
    elif remaining < -1:
        out.update(estado="VENTANA_CERRADA", motivo="Entrada hipotética vencida")
    elif remaining <= 0:
        out.update(estado="ENTRAR", motivo="Instante hipotético, NO operar",
                   segundos_para_entrada=0)
    elif remaining <= 10:
        out.update(estado="CUENTA_REGRESIVA", motivo="Solo ensayo del reloj",
                   segundos_para_entrada=ceil(remaining))
    elif remaining <= 30:
        out.update(estado="PREPARARSE", motivo="Solo ensayo de preparación",
                   segundos_para_entrada=ceil(remaining))
    else:
        out.update(estado="ESPERAR", motivo="Hipótesis programada para simulación",
                   segundos_para_entrada=ceil(remaining))
    return out


def analizar_crypto(snapshot, *, ahora_utc):
    """Evalúa calidad, indicadores y escenarios sin órdenes ni predicción validada."""
    now = _utc(ahora_utc)
    market = snapshot if isinstance(snapshot, dict) else {}
    symbol = market.get("symbol")
    result = _base(symbol, now)
    issues = result["calidad"]["motivos"]
    if symbol not in SIMBOLOS or market.get("source") != "alpaca_crypto":
        issues.append("Fuente o par incompatible.")
    if market.get("status") != "conectado":
        issues.append("No existe una suscripción activa confirmada.")
    receipt = _date(market.get("last_feed_message_at"))
    if receipt is None or not -1 <= (now-receipt).total_seconds() <= 15:
        issues.append("Datos recibidos hace más de 15 s, sin recepción verificable o reloj desajustado.")
    bars = _parse_closed(market.get("candles"), now)
    if len(bars) < 80:
        issues.append("Se requieren al menos 80 velas de 1 minuto cerradas y válidas.")
    if bars and (now.timestamp()-(bars[-1]["time"]+60)) > 180:
        issues.append("Última vela cerrada tiene más de 180 s de atraso.")
    if len(bars) >= 80:
        tail = bars[-40:]
        if any(y["time"]-x["time"] != 60 for x,y in zip(tail,tail[1:])):
            issues.append("Hay huecos en las últimas 40 velas; no interpolar.")
        closes = [x["close"] for x in tail]
        if any(abs(b/a-1) > .12 for a,b in zip(closes,closes[1:])):
            issues.append("Salto de precio superior a 12% en una vela; revisar proveedor.")
        if sum(x["volume"] == 0 for x in tail[-20:]) > 8:
            issues.append("Más de 40% de últimas 20 velas sin volumen negociado.")
    result["calidad"].update(velas_cerradas=len(bars),
                            ultima_vela_utc=datetime.fromtimestamp(bars[-1]["time"], timezone.utc).isoformat()
                            if bars else None)
    if issues:
        result["motivo"] = " | ".join(issues)
        return result

    closes = [bar["close"] for bar in bars]
    volumes = [bar["volume"] for bar in bars]
    sma20 = sum(closes[-20:])/20
    sma50 = sum(closes[-50:])/50
    slope20 = sma20 - sum(closes[-24:-4])/20
    rsi = _rsi(closes)
    # Calcular serie MACD de modo causal para obtener la señal EMA9.
    macd_series = []
    for i in range(26, len(closes)+1):
        fast, slow = _ema(closes[:i], 12), _ema(closes[:i], 26)
        macd_series.append(fast-slow)
    macd = macd_series[-1]
    signal = _ema(macd_series, 9)
    macd_delta = macd - signal
    volume_mean = sum(volumes[-20:])/20
    vol_ratio = volumes[-1]/volume_mean if volume_mean else 0
    ret3 = closes[-1] / closes[-4] - 1
    result["indicadores"] = {
        "close": round(closes[-1], 7), "sma20": round(sma20, 7),
        "sma50": round(sma50, 7), "pendiente_sma20": round(slope20, 7),
        "rsi14": round(rsi, 4), "macd": round(macd, 7),
        "macd_signal": round(signal, 7), "macd_hist": round(macd_delta, 7),
        "retorno_3m_pct": round(ret3*100, 4),
        "volumen_ultimo": round(volumes[-1], 6),
        "ratio_volumen": round(vol_ratio, 4)}
    up = closes[-1] > sma20 and macd_delta > 0 and 52 <= rsi <= 72 and ret3 > 0
    down = closes[-1] < sma20 and macd_delta < 0 and 28 <= rsi <= 48 and ret3 < 0
    candidates = {}
    for horizon in HORIZONTES:
        side = "SUBE" if up else "BAJA" if down else "ESPERAR"
        missing = []
        if side == "ESPERAR":
            missing.append("Precio, MACD, RSI y retorno 3m no coinciden direccionalmente.")
        elif horizon >= 120 and not ((slope20 > 0 and side == "SUBE")
                                    or (slope20 < 0 and side == "BAJA")):
            missing.append("La pendiente SMA20 no confirma la dirección.")
        elif horizon >= 300 and not ((sma20 > sma50 and side == "SUBE")
                                    or (sma20 < sma50 and side == "BAJA")):
            missing.append("SMA20 y SMA50 no se encuentran alineadas.")
        elif horizon >= 600 and vol_ratio < 1.0:
            missing.append("Falta volumen relativo para la duración larga.")
        if missing:
            side = "ESPERAR"
        candidates[str(horizon)] = {
            "direccion": side, "horizonte_segundos": horizon,
            "justificacion": "Regla mecánica experimental, no calibrada" if not missing else " ".join(missing),
            "faltantes": missing}
    result["evaluaciones"] = candidates
    result["calidad"]["apta"] = True
    result["motivo"] = "Datos aceptados para observación, sin estrategia validada."
    # La selección es FIJA para el ensayo de reloj (2m); no anuncia
    # que ese horizonte es el mejor en términos de aciertos.
    slot = candidates["120"]
    if slot["direccion"] in ("SUBE", "BAJA"):
        result["reloj_experimental"] = _reloj(slot["direccion"], 120, bars[-1], now, receipt)
        result["estado"] = result["reloj_experimental"]["estado"]
    else:
        result["reloj_experimental"]["motivo"] = slot["justificacion"]
    return result
