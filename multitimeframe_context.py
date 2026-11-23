"""Contexto 1h/1d aislado y causal para el motor experimental.

El módulo solo lee históricos locales y combina las velas oficiales recibidas
por el analizador. No abre conexiones, no modifica REALTIME y nunca incorpora
filas posteriores a ``as_of``.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from datetime import timedelta

import pandas as pd


NY_TZ = "America/New_York"
DAILY_SMA_PERIOD = 50
TREND_SMA_PERIOD = 20


def _insufficient(reason, rows=0, required=0):
    return {"status": "insufficient", "trend": None, "reason": reason,
            "rows": int(rows), "required_rows": int(required)}


def _historical_candidates(project_root):
    root = Path(project_root or Path(__file__).resolve().parent)
    folder = root / "auditoria" / "historico_nvda_iex"
    return sorted(folder.glob("nvda_iex_1min_*.csv"),
                  key=lambda item: item.stat().st_mtime_ns if item.exists() else 0,
                  reverse=True)


@lru_cache(maxsize=4)
def _read_history_cached(path_text, modified_ns):
    del modified_ns
    path = Path(path_text)
    frame = pd.read_csv(path)
    required = {"time", "open", "high", "low", "close", "volume"}
    if not required.issubset(frame.columns):
        raise ValueError("historical CSV lacks OHLCV columns")
    frame = frame[list(required)].copy()
    frame["Timestamp"] = pd.to_datetime(frame["time"], unit="s", utc=True, errors="coerce")
    for name in ("open", "high", "low", "close", "volume"):
        frame[name] = pd.to_numeric(frame[name], errors="coerce")
    frame = frame.dropna().drop_duplicates("Timestamp", keep="last").sort_values("Timestamp")
    return frame.set_index("Timestamp").rename(columns={
        "open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"
    })[["Open", "High", "Low", "Close", "Volume"]]


def _local_history(project_root):
    candidates = _historical_candidates(project_root)
    if not candidates:
        return pd.DataFrame(), None
    path = candidates[0]
    return _read_history_cached(str(path.resolve()), path.stat().st_mtime_ns).copy(), path


def _regular_minutes(frame):
    if frame.empty:
        return frame
    local = frame.index.tz_convert(NY_TZ)
    minutes = local.hour * 60 + local.minute
    mask = (local.weekday < 5) & (minutes >= 570) & (minutes < 960)
    return frame.loc[mask]


def _trend_payload(frame, *, required, sma_period=TREND_SMA_PERIOD):
    if len(frame) < required:
        return _insufficient(f"Se requieren {required} velas cerradas.", len(frame), required)
    closes = frame["Close"].astype(float)
    sma = closes.rolling(sma_period).mean().iloc[-1]
    previous_sma = closes.rolling(sma_period).mean().iloc[-4]
    close = closes.iloc[-1]
    tolerance = max(abs(close) * 0.0002, 1e-9)
    if close > sma + tolerance and sma > previous_sma:
        trend = "Alcista"
    elif close < sma - tolerance and sma < previous_sma:
        trend = "Bajista"
    else:
        trend = "Neutral"
    volumes = frame["Volume"].astype(float)
    volume_average = volumes.tail(20).mean()
    return {
        "status": "sufficient", "trend": trend, "rows": int(len(frame)),
        "required_rows": int(required), "last_closed_at": frame.index[-1].isoformat(),
        "close": round(float(close), 6), "sma20": round(float(sma), 6),
        "volume": round(float(volumes.iloc[-1]), 3),
        "volume_sma20": round(float(volume_average), 3),
        "volume_ratio": round(float(volumes.iloc[-1] / volume_average), 4) if volume_average > 0 else None,
    }


def build_multitimeframe_context(live_frame, *, as_of=None, project_root=None):
    """Construir contexto usando exclusivamente información disponible en ``as_of``."""
    if live_frame is None or live_frame.empty:
        return {"status": "insufficient", "as_of": None,
                "1h": _insufficient("Sin velas oficiales."),
                "1d": _insufficient("Sin velas oficiales."),
                "source": "none"}
    cutoff = pd.Timestamp(as_of or live_frame.index[-1])
    cutoff = cutoff.tz_localize("UTC") if cutoff.tzinfo is None else cutoff.tz_convert("UTC")
    historical, source = _local_history(project_root)
    combined = pd.concat([historical, live_frame[["Open", "High", "Low", "Close", "Volume"]]])
    combined = combined[~combined.index.duplicated(keep="last")].sort_index()
    combined = combined.loc[combined.index <= cutoff]
    regular = _regular_minutes(combined)
    if regular.empty:
        return {"status": "insufficient", "as_of": cutoff.isoformat(),
                "1h": _insufficient("Sin minutos de sesión regular."),
                "1d": _insufficient("Sin minutos de sesión regular."),
                "source": str(source) if source else "live_only"}

    local = regular.index.tz_convert(NY_TZ)
    session = pd.Series(local.date, index=regular.index)
    session_minutes = local.hour * 60 + local.minute - 570
    hour_bucket = pd.Series((session_minutes // 60).astype(int), index=regular.index)
    grouped_hour = regular.assign(_session=session.values, _bucket=hour_bucket.values,
                                  _timestamp=regular.index).groupby(["_session", "_bucket"])
    hourly = grouped_hour.agg(Open=("Open", "first"), High=("High", "max"),
                              Low=("Low", "min"), Close=("Close", "last"),
                              Volume=("Volume", "sum"))
    hourly["_count"] = grouped_hour.size()
    hourly["_last"] = grouped_hour["_timestamp"].max()
    hourly["_last"] = pd.to_datetime(hourly["_last"], utc=True)
    hourly = hourly[(hourly["_count"] >= 50) & (hourly["_last"] + timedelta(minutes=1) <= cutoff)]
    hourly = hourly.set_index("_last")[["Open", "High", "Low", "Close", "Volume"]].sort_index()

    current_session = cutoff.tz_convert(NY_TZ).date()
    complete_daily_minutes = regular.loc[session.values != current_session]
    if complete_daily_minutes.empty:
        daily = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    else:
        daily_local = complete_daily_minutes.index.tz_convert(NY_TZ)
        daily_session = pd.Series(daily_local.date, index=complete_daily_minutes.index)
        grouped_day = complete_daily_minutes.assign(_session=daily_session.values).groupby("_session")
        daily = grouped_day.agg(Open=("Open", "first"), High=("High", "max"),
                                Low=("Low", "min"), Close=("Close", "last"),
                                Volume=("Volume", "sum"))
        daily.index = pd.to_datetime(daily.index, utc=True)

    hour_payload = _trend_payload(hourly, required=20)
    day_payload = _trend_payload(daily, required=DAILY_SMA_PERIOD, sma_period=DAILY_SMA_PERIOD)
    if day_payload["status"] == "sufficient":
        last_close = float(daily["Close"].iloc[-1])
        sma50 = float(daily["Close"].tail(DAILY_SMA_PERIOD).mean())
        day_payload["sma50"] = round(sma50, 6)
        day_payload["sma50_position"] = "above" if last_close > sma50 else "below" if last_close < sma50 else "equal"
    return {
        "status": "sufficient" if hour_payload["status"] == "sufficient" else "partial",
        "as_of": cutoff.isoformat(), "future_rows_used": 0,
        "source": str(source.resolve()) if source else "live_only",
        "historical_last_at": historical.index[-1].isoformat() if not historical.empty else None,
        "combined_rows": int(len(combined)), "regular_rows": int(len(regular)),
        "1h": hour_payload, "1d": day_payload,
    }
