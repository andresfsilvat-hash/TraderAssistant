"""Asynchronous technical observation for closed Alpaca IEX 1-minute bars.

This module is deliberately read-only with respect to REALTIME.  It does not
open market-data connections and never runs calculations in a Flask request or
inside the WebSocket thread.  The operational decision remains ESPERAR.
"""
from __future__ import annotations

import atexit
from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import multiprocessing
import threading
import time
from zoneinfo import ZoneInfo

import pandas as pd
import ta

from screener.indicator_detector import (
    BB_PERIOD, BB_STD, MACD_FAST, MACD_SIGNAL, MACD_SLOW, MIN_ROWS,
    RSI_PERIOD, detect_indicators,
)
from screener.pattern_detector import detect_patterns
from screener.scorer import _classify


ANALYSIS_VERSION = "live-1m-v1"
TIMEFRAME_LABEL = "1m"
MAX_ANALYSIS_BARS = 500
STALE_AFTER_SECONDS = 180
ECUADOR_TZ = ZoneInfo("America/Guayaquil")


def _finite(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non-finite numeric value")
    return number


def official_candles_to_dataframe(candles):
    """Validate, deduplicate and sort closed official candles.

    Provisional records are excluded.  For duplicate timestamps the last valid
    record wins, matching a later official correction without summing volume.
    Returns (DataFrame, metadata).
    """
    if not isinstance(candles, (list, tuple)):
        raise ValueError("candles must be a list")
    valid = {}
    rejected = 0
    provisional_excluded = 0
    duplicate_count = 0
    for item in candles:
        if not isinstance(item, dict):
            rejected += 1
            continue
        if item.get("provisional") is True:
            provisional_excluded += 1
            continue
        try:
            timestamp = int(item["time"])
            opened, high, low, closed = (_finite(item[name]) for name in
                                         ("open", "high", "low", "close"))
            volume = _finite(item.get("volume", 0))
            if timestamp <= 0 or min(opened, high, low, closed) <= 0 or volume < 0:
                raise ValueError("invalid OHLCV")
            if high < max(opened, closed) or low > min(opened, closed) or high < low:
                raise ValueError("inconsistent OHLC")
        except (KeyError, TypeError, ValueError, OverflowError):
            rejected += 1
            continue
        if timestamp in valid:
            duplicate_count += 1
        valid[timestamp] = {"Open": opened, "High": high, "Low": low,
                            "Close": closed, "Volume": volume}
    ordered = sorted(valid.items())[-MAX_ANALYSIS_BARS:]
    index = pd.to_datetime([item[0] for item in ordered], unit="s", utc=True)
    frame = pd.DataFrame([item[1] for item in ordered], index=index,
                         columns=["Open", "High", "Low", "Close", "Volume"])
    frame.index.name = "Timestamp"
    return frame, {"received": len(candles), "valid": len(frame),
                   "rejected": rejected, "provisional_excluded": provisional_excluded,
                   "duplicates_replaced": duplicate_count}


def _value_or_none(series):
    if series is None or series.empty:
        return None
    value = float(series.iloc[-1])
    return round(value, 6) if math.isfinite(value) else None


def _numeric_values(frame):
    close = frame["Close"]
    rsi = ta.momentum.RSIIndicator(close=close, window=RSI_PERIOD).rsi()
    macd_obj = ta.trend.MACD(close=close, window_slow=MACD_SLOW,
                             window_fast=MACD_FAST, window_sign=MACD_SIGNAL)
    bb_obj = ta.volatility.BollingerBands(close=close, window=BB_PERIOD,
                                           window_dev=BB_STD)
    return {
        "rsi_14": _value_or_none(rsi),
        "macd_12_26": _value_or_none(macd_obj.macd()),
        "macd_signal_9": _value_or_none(macd_obj.macd_signal()),
        "macd_histogram": _value_or_none(macd_obj.macd_diff()),
        "bollinger_upper": _value_or_none(bb_obj.bollinger_hband()),
        "bollinger_middle": _value_or_none(bb_obj.bollinger_mavg()),
        "bollinger_lower": _value_or_none(bb_obj.bollinger_lband()),
        "close": round(float(close.iloc[-1]), 6),
    }


def _bias_and_reason(signals):
    bullish = [signal for signal in signals if _classify(signal) > 0]
    bearish = [signal for signal in signals if _classify(signal) < 0]
    if bullish and bearish:
        bias = "Contradictorio"
    elif bullish:
        bias = "Alcista"
    elif bearish:
        bias = "Bajista"
    else:
        bias = "Neutral"
    if bullish or bearish:
        parts = []
        if bullish:
            parts.append("Evidencia alcista: " + "; ".join(bullish))
        if bearish:
            parts.append("Evidencia bajista: " + "; ".join(bearish))
        reason = ". ".join(parts) + ". Interpretación técnica; no es señal de entrada."
    else:
        reason = ("Ningún patrón o condición extrema/crossover del motor original se activó "
                  "en la última vela oficial. Sesgo neutral; no es señal de entrada.")
    return bias, bullish, bearish, reason


def _base_result(symbol, status, message, row_count=0):
    return {
        "analysis_version": ANALYSIS_VERSION,
        "symbol": symbol,
        "timeframe": TIMEFRAME_LABEL,
        "decision": "ESPERAR",
        "operational_signal": None,
        "entry_time": None,
        "duration": None,
        "exit_time": None,
        "status": status,
        "bias": "Datos insuficientes" if status == "insufficient" else "Pendiente",
        "reason": message,
        "signals": [], "patterns": [], "indicator_signals": [],
        "bullish_evidence": [], "bearish_evidence": [], "values": {},
        "row_count": row_count, "required_rows": MIN_ROWS,
        "last_candle_time": None, "last_candle_ecuador": None,
        "stale": True, "age_seconds": None,
    }


def compute_live_analysis(payload):
    """CPU worker entry point.  Input and output are pickle-safe dictionaries."""
    started = time.perf_counter()
    symbol = str(payload.get("symbol") or "")
    frame, validation = official_candles_to_dataframe(payload.get("candles") or [])
    if len(frame) < MIN_ROWS:
        result = _base_result(
            symbol, "insufficient",
            f"Datos insuficientes: {len(frame)} de {MIN_ROWS} velas oficiales cerradas requeridas.",
            len(frame),
        )
        result["validation"] = validation
        result["source"] = payload.get("source") or "sin_datos"
        result["feed_revision"] = payload.get("feed_revision")
        result["calculation_ms"] = round((time.perf_counter() - started) * 1000, 3)
        result["computed_at"] = datetime.now(timezone.utc).isoformat()
        return result

    patterns = detect_patterns(frame, TIMEFRAME_LABEL)
    indicator_signals = detect_indicators(frame, TIMEFRAME_LABEL)
    signals = patterns + indicator_signals
    values = _numeric_values(frame)
    bias, bullish, bearish, reason = _bias_and_reason(signals)
    last_timestamp = frame.index[-1].to_pydatetime()
    now = datetime.now(timezone.utc)
    age_seconds = max(0, int((now - last_timestamp).total_seconds()) - 60)
    last = frame.iloc[-1]
    direction = "Alcista" if last["Close"] > last["Open"] else \
        "Bajista" if last["Close"] < last["Open"] else "Sin cambio"
    result = {
        "analysis_version": ANALYSIS_VERSION,
        "symbol": symbol,
        "timeframe": TIMEFRAME_LABEL,
        "decision": "ESPERAR",
        "operational_signal": None,
        "entry_time": None, "duration": None, "exit_time": None,
        "status": "ready",
        "bias": bias,
        "direction_observed": direction,
        "reason": reason,
        "signals": signals,
        "patterns": patterns,
        "indicator_signals": indicator_signals,
        "bullish_evidence": bullish,
        "bearish_evidence": bearish,
        "values": values,
        "row_count": len(frame),
        "required_rows": MIN_ROWS,
        "last_candle_time": last_timestamp.astimezone(timezone.utc).isoformat(),
        "last_candle_ecuador": last_timestamp.astimezone(ECUADOR_TZ).isoformat(),
        "stale": age_seconds > STALE_AFTER_SECONDS,
        "age_seconds": age_seconds,
        "source": payload.get("source") or "alpaca",
        "feed_revision": payload.get("feed_revision"),
        "validation": validation,
        "computed_at": now.isoformat(),
        "calculation_ms": round((time.perf_counter() - started) * 1000, 3),
    }
    return result


def _candles_digest(candles):
    compact = [[int(item["time"]), float(item["open"]), float(item["high"]),
                float(item["low"]), float(item["close"]), float(item.get("volume", 0))]
               for item in candles]
    raw = json.dumps(compact, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class LiveAnalysisService:
    def __init__(self, feed, *, executor_factory=None, analyzer=compute_live_analysis,
                 poll_interval=0.25):
        self.feed = feed
        self.executor_factory = executor_factory or (lambda: ProcessPoolExecutor(max_workers=1))
        self.analyzer = analyzer
        self.poll_interval = poll_interval
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread = None
        self.executor = None
        self.future = None
        self.future_token = None
        self.queued = None
        self.current_symbol = None
        self.generation = 0
        self.last_marker = None
        self.completed_digest = None
        self.calculation_count = 0
        self.duplicate_skip_count = 0
        self.discarded_result_count = 0
        self.last_valid_by_symbol = {}
        self.state = _base_result("", "waiting", "Esperando velas oficiales cerradas.")

    def start(self):
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            self.executor = self.executor_factory()
            self.stop_event.clear()
            self.thread = threading.Thread(target=self._run, name="analysis-live-monitor", daemon=True)
            self.thread.start()

    def stop(self):
        self.stop_event.set()
        thread = self.thread
        if thread and thread.is_alive():
            thread.join(timeout=2)
        executor, self.executor = self.executor, None
        if executor is not None:
            try:
                executor.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                executor.shutdown(wait=False)

    def _observe(self):
        with self.feed.lock:
            symbol = self.feed.symbol
            official = self.feed.official
            latest = max(official) if official else None
            marker = (symbol, latest, len(official), self.feed.series_revision)
            source = self.feed.history_source
            if marker == self.last_marker:
                return symbol, marker, None
            candles = []
            for timestamp in sorted(official)[-MAX_ANALYSIS_BARS:]:
                bar = official[timestamp]
                candles.append({"time": timestamp, "open": bar["open"], "high": bar["high"],
                                "low": bar["low"], "close": bar["close"],
                                "volume": bar.get("volume", 0), "provisional": False})
        return symbol, marker, {"symbol": symbol, "source": source, "candles": candles,
                                "feed_revision": marker[3]}

    def _accept_completed(self):
        future = self.future
        if future is None or not future.done():
            return
        token = self.future_token
        self.future = None
        self.future_token = None
        try:
            result = future.result()
        except Exception as err:
            with self.lock:
                if token and token[0] == self.current_symbol and token[1] == self.generation:
                    previous = self.last_valid_by_symbol.get(token[0])
                    if previous:
                        self.state = deepcopy(previous)
                        self.state["status"] = "stale_error"
                        self.state["analyzer_error"] = type(err).__name__
                        self.state["reason"] += " El último cálculo falló; se conserva este resultado previo."
                    else:
                        self.state = _base_result(token[0], "error", "El analizador falló; REALTIME continúa sin cambios.")
                        self.state["analyzer_error"] = type(err).__name__
            return
        with self.lock:
            if not token or token[0] != self.current_symbol or token[1] != self.generation:
                self.discarded_result_count += 1
                return
            self.state = result
            self.completed_digest = token[2]
            self.calculation_count += 1
            if result.get("status") == "ready":
                self.last_valid_by_symbol[token[0]] = deepcopy(result)

    def _submit_queued(self):
        if self.future is not None or self.queued is None or self.executor is None:
            return
        payload, token = self.queued
        self.queued = None
        self.future_token = token
        self.future = self.executor.submit(self.analyzer, payload)

    def _run(self):
        while not self.stop_event.is_set():
            self._accept_completed()
            symbol, marker, payload = self._observe()
            with self.lock:
                if symbol != self.current_symbol:
                    self.current_symbol = symbol
                    self.generation += 1
                    self.completed_digest = None
                    self.queued = None
                    self.state = _base_result(symbol, "waiting", "Esperando análisis de velas oficiales cerradas.")
                if payload is not None:
                    self.last_marker = marker
                    if not payload["candles"]:
                        self.state = _base_result(symbol, "insufficient", "Sin velas oficiales cerradas.")
                    else:
                        digest = _candles_digest(payload["candles"])
                        pending_digest = self.future_token[2] if self.future_token else None
                        queued_digest = self.queued[1][2] if self.queued else None
                        if digest in (self.completed_digest, pending_digest, queued_digest):
                            self.duplicate_skip_count += 1
                            if digest == self.completed_digest and self.state.get("symbol") == symbol:
                                self.state["feed_revision"] = marker[3]
                        else:
                            token = (symbol, self.generation, digest)
                            self.queued = (payload, token)
                            if self.future is None:
                                self.state = _base_result(symbol, "calculating", "Calculando indicadores fuera del proceso REALTIME.")
                self._submit_queued()
            self.stop_event.wait(self.poll_interval)
        self._accept_completed()

    def snapshot(self):
        with self.feed.lock:
            symbol = self.feed.symbol
        with self.lock:
            if self.state.get("symbol") != symbol:
                result = _base_result(symbol, "waiting", "Esperando resultado del activo seleccionado.")
            else:
                result = deepcopy(self.state)
            # Freshness must continue aging even when there is no new candle;
            # this updates metadata only and never reruns technical analysis.
            last_candle = result.get("last_candle_time")
            if last_candle:
                try:
                    timestamp = datetime.fromisoformat(last_candle.replace("Z", "+00:00"))
                    age_seconds = max(0, int((datetime.now(timezone.utc) - timestamp).total_seconds()) - 60)
                    result["age_seconds"] = age_seconds
                    result["stale"] = age_seconds > STALE_AFTER_SECONDS
                except (TypeError, ValueError):
                    result["stale"] = True
            result["service"] = {
                "calculation_count": self.calculation_count,
                "duplicate_skip_count": self.duplicate_skip_count,
                "discarded_result_count": self.discarded_result_count,
                "worker_busy": self.future is not None,
                "queued": self.queued is not None,
            }
            return result


def register_live_analysis(app, feed=None, *, start=True, executor_factory=None):
    if feed is None:
        from alpaca_live import _feed as feed
    service = LiveAnalysisService(feed, executor_factory=executor_factory)
    app.extensions["live_analysis"] = service
    if start and multiprocessing.current_process().name == "MainProcess":
        service.start()
        atexit.register(service.stop)

    @app.route("/api/analysis/live", methods=["GET"])
    def live_analysis_state():
        from flask import jsonify
        response = jsonify(service.snapshot())
        response.headers["Cache-Control"] = "no-store"
        return response

    return service
