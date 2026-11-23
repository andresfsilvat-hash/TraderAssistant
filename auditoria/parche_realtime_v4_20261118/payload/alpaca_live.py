"""TraderAssistant v4 -- lectura de datos de mercado Alpaca IEX.

Solo lectura: no usa API de ordenes, ni expone credenciales por HTTP.
Velas 1m oficiales de Alpaca (REST y canales bars/updatedBars); la vela
actual y las de 5 s son INDICATIVAS a partir de operaciones elegibles.
"""
from __future__ import annotations

from collections import OrderedDict
import atexit
import os
import random
import tempfile
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import threading
import time
from zoneinfo import ZoneInfo

import requests
from flask import Response, jsonify, send_from_directory, stream_with_context
from websockets.sync.client import connect

VERSION = "4.0.0"
BUILD = "mercado-multiactivo-20261118"
SYMBOL = "NVDA"  # Activo por defecto; no modifica configuracion de usuario
SYMBOLS = {"NVDA": "NVIDIA", "SPY": "SPDR S&P 500 ETF", "QQQ": "Invesco Nasdaq-100 ETF",
           "MSFT": "Microsoft", "AAPL": "Apple", "AMD": "AMD"}
FEED = "iex"
WS_URL = "wss://stream.data.alpaca.markets/v2/iex"
HISTORY_URL = "https://data.alpaca.markets/v2/stocks/NVDA/bars"
KEY_FILE = Path.home() / "Documents" / "Alpaca_key.txt"
MAX_MINUTE_BARS = 500
HISTORY_LOOKBACK_DAYS = 10
HISTORY_MAX_PAGES = 20
CACHE_FILE = Path(__file__).resolve().parent / "cache" / "alpaca_iex_nvda.json"
MAX_5SEC_BARS = 1200
MAX_TRADE_IDS = 6000
MAX_QUOTE_POINTS = 600
SHORT_LATE_WINDOW_SECONDS = 90
AUTH_TIMEOUT_SECONDS = 10
SUBSCRIPTION_TIMEOUT_SECONDS = 12
NY_TZ = ZoneInfo("America/New_York")
REQUIRED_CHANNELS = ("trades", "quotes", "bars", "updatedBars")
OPTIONAL_CHANNELS = ("corrections", "cancelErrors")
STREAM_LOCK_FILE = Path(__file__).resolve().parent / "cache" / "alpaca_iex_stream.lock"

# Reglas conservadoras para la PREVISUALIZACION (no para velas oficiales).
# Basadas en la tabla de elegibilidad de trades por tape/condicion de Alpaca.
# Las operaciones con codigos desconocidos NO alteran precios provisionales.
# La fuente definitiva de OHLCV son barras 'b'/'u' emitidas por Alpaca.
PRICE_CONDITIONS = {
    "C": frozenset(("@", "A", "B", "D", "F", "K", "L", "O", "T", "X", "Y", "5", "6")),
    "A": frozenset((" ", "E", "F", "K", "L", "O", "T", "X", "5", "6")),
    "B": frozenset((" ", "E", "F", "K", "L", "O", "T", "X", "5", "6")),
    "O": frozenset(("@", "T")),
}


def _credentials():
    """Leer el TXT local, sin imprimir credenciales ni confiar en Endpoint."""
    if not KEY_FILE.is_file():
        raise FileNotFoundError("No se encuentra Alpaca_key.txt en la carpeta Documentos.")
    lines = [s.strip() for s in KEY_FILE.read_text(encoding="utf-8-sig").splitlines()]
    fields = {}
    for i, line in enumerate(lines[:-1]):
        label = line.lower().rstrip(":")
        if label in ("key", "secret", "endpoint"):
            fields[label] = lines[i + 1]
    if not fields.get("key") or not fields.get("secret"):
        raise ValueError("Alpaca_key.txt debe incluir Key y Secret en lineas separadas.")
    return fields["key"], fields["secret"]


def _unix(ts):
    """Convertir un timestamp ISO8601, incluso si Alpaca envía nanosegundos."""
    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Timestamp sin zona horaria")
    return dt.timestamp()


def _bar(obj):
    vals = [float(obj[k]) for k in ("o", "h", "l", "c")]
    if not all(math.isfinite(v) and v > 0 for v in vals):
        raise ValueError("Precios invalidos")
    if vals[1] < max(vals[0], vals[3]) or vals[2] > min(vals[0], vals[3]):
        raise ValueError("OHLC inconsistente")
    return {"time": int(_unix(obj["t"])) // 60 * 60,
            "open": vals[0], "high": vals[1], "low": vals[2],
            "close": vals[3], "volume": max(0, int(obj.get("v", 0)))}


def _price_eligible(trade):
    """Solo operaciones cuyo precio puede alterar O/H/L/C de una vela 1m.

    Reglas de seguridad conservadoras: las condiciones inesperadas se excluyen.
    Esto NO sustituye a las barras oficiales, especialmente para el volumen.
    """
    tape = trade.get("z") or "C"  # NVDA es una accion listada en Nasdaq
    allowed = PRICE_CONDITIONS.get(tape, frozenset())
    conditions = trade.get("c") or []
    if not isinstance(conditions, list):
        return False
    return all(isinstance(c, str) and c in allowed for c in conditions)




def _cached_candle(obj):
    """Read only market candles from local cache; reject malformed entries."""
    if not isinstance(obj, dict):
        raise ValueError("Invalid cached record")
    t = int(obj["time"])
    vals = [float(obj[k]) for k in ("open", "high", "low", "close")]
    if t < 0 or not all(math.isfinite(v) and v > 0 for v in vals):
        raise ValueError("Invalid cached prices")
    if vals[1] < max(vals[0], vals[3]) or vals[2] > min(vals[0], vals[3]):
        raise ValueError("Inconsistent cached candle")
    result = {"time": t, "open": vals[0], "high": vals[1], "low": vals[2],
              "close": vals[3], "volume": max(0, int(obj.get("volume", 0)))}
    origin = obj.get("origin")
    if origin in ("cache", "rest", "websocket", "live", "mixed"):
        result["origin"] = origin
    for name in ("first_trade_time", "last_trade_time"):
        value = obj.get(name)
        if isinstance(value, (int, float)) and math.isfinite(value):
            result[name] = float(value)
    return result


def _public_candle(bar, *, quality, status, origin, provisional):
    """Return browser-safe candle metadata without internal bookkeeping keys."""
    return {"time": bar["time"], "open": bar["open"], "high": bar["high"],
            "low": bar["low"], "close": bar["close"], "volume": bar["volume"],
            "quality": quality, "status": status, "origin": origin,
            "provisional": provisional}


class _RetryStream(Exception):
    """Server requested a controlled retry (e.g. Alpaca code 406)."""

    def __init__(self, code=None):
        super().__init__(str(code) if code is not None else "retry")
        self.code = code


class _ProcessStreamLock:
    """Non-blocking OS lock; the kernel releases it if the process dies."""

    def __init__(self, path):
        self.path = Path(path)
        self.handle = None

    def acquire(self):
        if self.handle is not None:
            return True
        handle = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            handle = open(self.path, "a+b")
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.handle = handle
            return True
        except (OSError, IOError):
            if handle is not None:
                handle.close()
            return False

    def release(self):
        handle, self.handle = self.handle, None
        if handle is None:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except (OSError, IOError):
            pass
        finally:
            handle.close()

def _utc_iso():
    return datetime.now(timezone.utc).isoformat()


class LiveFeed:
    def __init__(self):
        self.lock = threading.RLock()
        self.symbol = SYMBOL
        self.market_clock = {"source": "pendiente", "is_open": None, "next_open": None,
                             "next_close": None, "checked_at": None, "error": None,
                             "phase": "UNKNOWN", "session_open": None,
                             "session_close": None, "provider_time": None}
        self.condition = threading.Condition(self.lock)
        self.started = False
        self.status = "sin_iniciar"
        self.error = None
        self.history_error = None
        self.history_loaded = False
        self.official = {}  # timestamp -> candle, siempre autoridad final
        self.provisional = None  # vela 1m en progreso, indicativa
        self.short_bars = []  # velas 5s solo desde conexion, indicativas
        self.last_trade = None
        self.last_quote = None  # bid / ask IEX; no equivale a una operacion
        self.last_quote_received_at = None
        self.last_quote_lag_ms = None
        self.quote_count = 0
        self.quote_points = []  # precio medio indicativo, serie separada de las velas
        self.last_received_at = None
        self.last_feed_message_at = None
        self.trade_count = 0
        self.eligible_count = 0
        self.excluded_count = 0
        self.last_lag_ms = None
        self.version = 0
        self.series_revision = 0  # incrementa si hay correcciones antiguas o backfill
        self.reconnect_count = 0
        self.last_reconnect_reason = None
        self.last_error_code = None
        self.late_trade_drop_count = 0
        self.correction_count = 0
        self.channel_status = {name: False for name in REQUIRED_CHANNELS}
        self.optional_channel_status = {name: False for name in OPTIONAL_CHANNELS}
        self.cache_status = {"loaded_at": None, "saved_at": None, "error": None}
        self._seen_trade_ids = OrderedDict()
        self._history_busy = False
        self._history_requested_at = 0.0
        self._last_start_attempt = 0.0
        self.quotes_subscribed = False
        self._reconcile_requested = False
        self._process_lock = _ProcessStreamLock(STREAM_LOCK_FILE)
        self._maintenance_started = False
        self._history_completed_at = 0.0
        self.history_source = "sin_datos"
        self._cache_dirty = False
        self._restore_cache()

    def _cache_file(self):
        if self.symbol == SYMBOL:
            return CACHE_FILE  # compatibilidad con caché NVDA existente
        return CACHE_FILE.with_name("alpaca_iex_" + self.symbol.lower() + ".json")

    def _restore_cache(self):
        """Load market data only; cache never contains credentials."""
        try:
            path = self._cache_file()
            if not path.is_file() or path.stat().st_size > 2_000_000:
                return
            raw = json.loads(path.read_text(encoding="utf-8"))
            if raw.get("schema") not in (1, 2) or raw.get("symbol") != self.symbol or raw.get("feed") != FEED:
                return
            cutoff = time.time() - HISTORY_LOOKBACK_DAYS * 86400
            for item in raw.get("candles", [])[-MAX_MINUTE_BARS:]:
                try:
                    bar = _cached_candle(item)
                    if bar["time"] >= cutoff and bar["time"] < time.time() // 60 * 60:
                        bar["origin"] = "cache"
                        self.official[bar["time"]] = bar
                except (ValueError, TypeError, KeyError, OverflowError):
                    continue
            for item in raw.get("short_candles", [])[-MAX_5SEC_BARS:]:
                try:
                    bar = _cached_candle(item)
                    if bar["time"] >= cutoff:
                        bar["origin"] = "cache"
                        bar.setdefault("first_trade_time", float(bar["time"]))
                        bar.setdefault("last_trade_time", float(bar["time"]))
                        self.short_bars.append(bar)
                except (ValueError, TypeError, KeyError, OverflowError):
                    continue
            self.short_bars.sort(key=lambda x: x["time"])
            self._prune()
            if self.official:
                self.history_loaded = True
                self.history_source = "cache"
            self.cache_status = {"loaded_at": _utc_iso(), "saved_at": raw.get("saved_at"),
                                 "error": None}
        except (OSError, ValueError, TypeError):
            # Corrupted cache must never block startup or credentials.
            self.cache_status["error"] = "No se pudo restaurar la cache valida."
            return

    def _save_cache(self):
        with self.lock:
            if not self._cache_dirty:
                return
            path = self._cache_file()
            saved_version = self.version
            data = {"schema": 2, "symbol": self.symbol, "feed": FEED,
                    "saved_at": _utc_iso(),
                    "candles": [self.official[k] for k in sorted(self.official)][-MAX_MINUTE_BARS:],
                    "short_candles": self.short_bars[-MAX_5SEC_BARS:]}
        name = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                             prefix=".alpaca-", suffix=".tmp", delete=False) as file:
                name = file.name
                json.dump(data, file, separators=(",", ":"), allow_nan=False)
                file.flush()
                os.fsync(file.fileno())
            for attempt in range(4):
                try:
                    os.replace(name, path)
                    name = None
                    break
                except PermissionError:
                    if attempt == 3:
                        raise
                    time.sleep(0.1 * (attempt + 1))
            with self.lock:
                self.cache_status["saved_at"] = data["saved_at"]
                self.cache_status["error"] = None
                if path == self._cache_file() and self.version == saved_version:
                    self._cache_dirty = False
        except (OSError, TypeError, ValueError) as err:
            # Cache is a performance aid; it cannot interrupt the stream.
            with self.lock:
                self.cache_status["error"] = "Cache: " + type(err).__name__
        finally:
            if name:
                try:
                    os.unlink(name)
                except OSError:
                    pass

    def _cache_watchdog(self):
        last_version = -1
        while True:
            time.sleep(5)
            with self.lock:
                version = self.version
            if version != last_version:
                self._save_cache()
                last_version = version

    def _history_watchdog(self):
        # REST historical + market clock share a maintenance thread; never block WS.
        while True:
            try:
                key, secret = _credentials()
                self._refresh_market_clock(key, secret)
            except (OSError, ValueError):
                pass
            time.sleep(60)
            with self.lock:
                needed = (self.history_error or not self.history_loaded or
                          time.monotonic() - self._history_completed_at > 900)
            if not needed:
                continue
            try:
                key, secret = _credentials()
                self._start_history(key, secret, reconcile=True)
            except (OSError, ValueError):
                continue

    def _refresh_market_clock(self, key, secret):
        """Read Alpaca clock + calendar and derive the equity session phase."""
        headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
        for host in ("paper-api.alpaca.markets", "api.alpaca.markets"):
            try:
                response = requests.get("https://" + host + "/v2/clock", headers=headers, timeout=(3, 6))
                if not response.ok:
                    continue
                obj = response.json()
                if not isinstance(obj, dict) or not isinstance(obj.get("is_open"), bool):
                    continue
                opened, closed = obj.get("next_open"), obj.get("next_close")
                if not opened or not closed:
                    continue
                _unix(opened)
                _unix(closed)
                provider_time = obj.get("timestamp") or _utc_iso()
                provider_dt = datetime.fromtimestamp(_unix(provider_time), tz=timezone.utc)
                ny_now = provider_dt.astimezone(NY_TZ)
                day = ny_now.date().isoformat()
                calendar_response = requests.get("https://" + host + "/v2/calendar",
                    headers=headers, params={"start": day, "end": day}, timeout=(3, 6))
                calendar = calendar_response.json() if calendar_response.ok else []
                session = calendar[0] if isinstance(calendar, list) and calendar else None
                regular_open = regular_close = extended_open = extended_close = None
                if isinstance(session, dict):
                    def at(value):
                        text = str(value or "").replace(":", "")
                        if len(text) != 4 or not text.isdigit():
                            return None
                        return datetime(ny_now.year, ny_now.month, ny_now.day,
                                        int(text[:2]), int(text[2:]), tzinfo=NY_TZ)
                    regular_open = at(session.get("open"))
                    regular_close = at(session.get("close"))
                    extended_open = at(session.get("session_open"))
                    extended_close = at(session.get("session_close"))
                if obj["is_open"]:
                    phase = "REGULAR"
                elif regular_open and extended_open and extended_open <= ny_now < regular_open:
                    phase = "PREMARKET"
                elif regular_close and extended_close and regular_close <= ny_now < extended_close:
                    phase = "POSTMARKET"
                else:
                    phase = "CLOSED"
                with self.lock:
                    self.market_clock = {"source": "alpaca", "is_open": obj["is_open"],
                                         "next_open": opened, "next_close": closed,
                                         "checked_at": _utc_iso(), "error": None,
                                         "phase": phase, "provider_time": provider_time,
                                         "session_open": extended_open.astimezone(timezone.utc).isoformat() if extended_open else None,
                                         "session_close": extended_close.astimezone(timezone.utc).isoformat() if extended_close else None,
                                         "regular_open": regular_open.astimezone(timezone.utc).isoformat() if regular_open else None,
                                         "regular_close": regular_close.astimezone(timezone.utc).isoformat() if regular_close else None,
                                         "calendar_verified": session is not None}
                    self._notify()
                return
            except (requests.RequestException, ValueError, TypeError, KeyError, OverflowError):
                continue
        with self.lock:
            self.market_clock["error"] = "Horario de mercado no disponible; sin estimar apertura."
            self.market_clock["phase"] = "UNKNOWN"
            self._notify()

    def _market_clock_watchdog(self):
        while True:
            try:
                key, secret = _credentials()
                self._refresh_market_clock(key, secret)
            except (OSError, ValueError):
                with self.lock:
                    self.market_clock["error"] = "No se pudo consultar el reloj de Alpaca."
                    self._notify()
            time.sleep(60)

    def select_symbol(self, symbol):
        """Change active symbol on one WS; never open another Alpaca connection.

        The worker on the next WebSocket receive tick sends unsubscribe/subscribe.
        Previous symbol's cache is preserved before resetting the visual state.
        """
        if not isinstance(symbol, str) or symbol not in SYMBOLS:
            raise ValueError("Activo no permitido")
        with self.lock:
            if symbol == self.symbol:
                return
        self._save_cache()
        with self.lock:
            self.symbol = symbol
            self.official = {}
            self.provisional = None
            self.short_bars = []
            self.quote_points = []
            self.last_trade = None
            self.last_quote = None
            self.last_received_at = None
            self.last_feed_message_at = None
            self.last_quote_received_at = None
            self.last_quote_lag_ms = None
            self.last_lag_ms = None
            self.trade_count = 0
            self.quote_count = 0
            self.eligible_count = 0
            self.excluded_count = 0
            self._seen_trade_ids.clear()
            self.history_error = None
            self.history_loaded = False
            self.history_source = "sin_datos"
            self.cache_status = {"loaded_at": None, "saved_at": None, "error": None}
            self._cache_dirty = False
            self._history_busy = False
            self._history_requested_at = 0.0
            self._history_completed_at = 0.0
            self.quotes_subscribed = False
            self.channel_status = {name: False for name in REQUIRED_CHANNELS}
            self.optional_channel_status = {name: False for name in OPTIONAL_CHANNELS}
            self.status = "cambiando_activo"
            self.series_revision += 1
            self._restore_cache()
            self._notify()
        # No retrasa UI ni mantiene a Flask esperando REST.
        try:
            key, secret = _credentials()
            self._start_history(key, secret)
        except (OSError, ValueError):
            pass

    def _notify(self):
        # Siempre se llama con self.lock
        self.version += 1
        self.condition.notify_all()

    def set_status(self, status, error=None):
        with self.lock:
            if self.status != status or self.error != error:
                self.status, self.error = status, error
                self._notify()

    def start(self):
        with self.lock:
            now = time.monotonic()
            # Prevent a failed credential/auth attempt from spawning a thread
            # on every browser polling request.
            if self.started or now - self._last_start_attempt < 30:
                return
            self._last_start_attempt = now
            if not self._process_lock.acquire():
                self.status = "conexion_ocupada"
                self.error = ("Otra instancia local de TraderAssistant ya posee la conexion Alpaca IEX. "
                              "Cierre la otra instancia antes de reintentar.")
                self.last_error_code = "LOCAL_LOCK"
                self._notify()
                return
            self.started = True
            self.status = "iniciando"
            first = not self._maintenance_started
            self._maintenance_started = True
            self._notify()

        def guarded_run():
            try:
                self.run()
            finally:
                self._process_lock.release()
                with self.lock:
                    self.started = False
                    self._notify()

        threading.Thread(target=guarded_run, name="alpaca-iex-stream", daemon=True).start()
        if first:
            threading.Thread(target=self._history_watchdog, name="alpaca-historial-retry", daemon=True).start()
            threading.Thread(target=self._cache_watchdog, name="alpaca-cache", daemon=True).start()

    def wait_for_version(self, version, timeout=15.0):
        with self.condition:
            if self.version == version:
                self.condition.wait_for(lambda: self.version != version, timeout=timeout)
            return self.version

    def _prune(self):
        if len(self.official) > MAX_MINUTE_BARS:
            for key in sorted(self.official)[:-MAX_MINUTE_BARS]:
                self.official.pop(key, None)
        if len(self.short_bars) > MAX_5SEC_BARS:
            self.short_bars = self.short_bars[-MAX_5SEC_BARS:]

    def _snapshot_bars(self):
        candles = [_public_candle(self.official[k], quality="official", status="closed",
                                  origin=self.official[k].get("origin", "websocket"),
                                  provisional=False) for k in sorted(self.official)]
        p = self.provisional
        if p and (not candles or p["time"] > candles[-1]["time"]):
            status = "forming" if time.time() < p["time"] + 60 else "closed"
            candles.append(_public_candle(p, quality="indicative", status=status,
                                          origin="trades", provisional=True))
        return candles[-MAX_MINUTE_BARS:]

    def _snapshot_short_bars(self):
        now = time.time()
        return [_public_candle(b, quality="indicative",
                               status="forming" if now < b["time"] + 5 else "closed",
                               origin=b.get("origin", "live"), provisional=True)
                for b in self.short_bars[-MAX_5SEC_BARS:]]

    def snapshot(self):
        with self.lock:
            return {
                "version_info": VERSION, "build": BUILD,
                "symbol": self.symbol, "symbol_name": SYMBOLS[self.symbol],
                "available_symbols": SYMBOLS, "feed": FEED,
                "market_clock": dict(self.market_clock),
                "status": self.status, "error": self.error,
                "history_error": self.history_error,
                "history_loaded": self.history_loaded,
                "history_source": self.history_source,
                "candles": self._snapshot_bars(),
                "short_candles": self._snapshot_short_bars(),
                "last_trade": dict(self.last_trade) if self.last_trade else None,
                "last_quote": dict(self.last_quote) if self.last_quote else None,
                "last_quote_received_at": self.last_quote_received_at,
                "last_quote_lag_ms": self.last_quote_lag_ms,
                "quote_count": self.quote_count,
                "quote_points": [dict(q) for q in self.quote_points],
                "quotes_subscribed": getattr(self, "quotes_subscribed", False),
                "channel_status": dict(self.channel_status),
                "optional_channel_status": dict(self.optional_channel_status),
                "cache_status": dict(self.cache_status),
                "last_received_at": self.last_received_at,
                "last_feed_message_at": self.last_feed_message_at,
                "last_lag_ms": self.last_lag_ms,
                "trade_count": self.trade_count,
                "eligible_count": self.eligible_count,
                "excluded_count": self.excluded_count,
                "reconnect_count": self.reconnect_count,
                "last_reconnect_reason": self.last_reconnect_reason,
                "last_error_code": self.last_error_code,
                "late_trade_drop_count": self.late_trade_drop_count,
                "correction_count": self.correction_count,
                "series_revision": self.series_revision,
                "version": self.version,
                "server_time": _utc_iso(),
            }

    def insert_bar(self, bar):
        """Aplicar una barra oficial de Alpaca b/u sin mezclarla con provisional."""
        minute = bar["time"]
        bar = dict(bar)
        bar.setdefault("origin", "websocket")
        with self.lock:
            previous = self.official.get(minute)
            if previous == bar:
                return
            latest = max(self.official) if self.official else None
            self.official[minute] = dict(bar)
            self._cache_dirty = True
            if self.provisional and self.provisional["time"] <= minute:
                if self.provisional["time"] == minute:
                    self.provisional = None
                elif self.provisional["time"] < minute:
                    self.provisional = None
            if latest is not None and minute <= latest:
                self.series_revision += 1  # correccion o vela anterior
            self._prune()
            self.last_feed_message_at = _utc_iso()
            self._notify()

    def on_trade(self, trade):
        if trade.get("S") != self.symbol:
            return
        try:
            price = float(trade["p"])
            size = int(trade["s"])
            timestamp = trade["t"]
            trade_unix = _unix(timestamp)
            if not math.isfinite(price) or price <= 0 or size <= 0:
                return
        except (ValueError, TypeError, KeyError, OverflowError):
            return
        with self.lock:
            if trade.get("S") != self.symbol:
                return
            unique = (trade.get("x"), trade.get("i"))
            if unique[0] is not None and unique[1] is not None:
                if unique in self._seen_trade_ids:
                    return
                self._seen_trade_ids[unique] = True
                if len(self._seen_trade_ids) > MAX_TRADE_IDS:
                    self._seen_trade_ids.popitem(last=False)

            received = _utc_iso()
            self.trade_count += 1
            self.last_feed_message_at = received
            if self.last_trade is None or trade_unix >= _unix(self.last_trade["timestamp"]):
                self.last_trade = {"price": price, "timestamp": timestamp,
                                   "size": size, "conditions": list(trade.get("c") or [])}
                self.last_received_at = received
                # Incluye tiempo proveedor->servidor y diferencia de relojes.
                self.last_lag_ms = round((time.time() - trade_unix) * 1000)
            if not _price_eligible(trade):
                self.excluded_count += 1
                self._notify()
                return
            self.eligible_count += 1

            minute = int(trade_unix) // 60 * 60
            candle_changed = False
            official_closed = bool(self.official and minute <= max(self.official))
            older_than_provisional = bool(self.provisional and minute < self.provisional["time"])
            if not official_closed and not older_than_provisional:
                if not self.provisional or minute > self.provisional["time"]:
                    self.provisional = {"time": minute, "open": price, "high": price,
                                        "low": price, "close": price, "volume": size,
                                        "first_trade_time": trade_unix,
                                        "last_trade_time": trade_unix}
                else:
                    p = self.provisional
                    p["high"] = max(p["high"], price)
                    p["low"] = min(p["low"], price)
                    p["volume"] += size
                    if trade_unix < p.get("first_trade_time", trade_unix):
                        p["first_trade_time"] = trade_unix
                        p["open"] = price
                    if trade_unix >= p.get("last_trade_time", trade_unix):
                        p["last_trade_time"] = trade_unix
                        p["close"] = price
                candle_changed = True

            bucket = int(trade_unix) // 5 * 5
            latest_bucket = self.short_bars[-1]["time"] if self.short_bars else None
            last_trade_bucket = int(_unix(self.last_trade["timestamp"])) // 5 * 5 if self.last_trade else bucket
            reference_bucket = max(latest_bucket if latest_bucket is not None else bucket, last_trade_bucket)
            short_changed = False
            if bucket < reference_bucket - SHORT_LATE_WINDOW_SECONDS:
                self.late_trade_drop_count += 1
            else:
                target = None
                if latest_bucket == bucket:
                    target = self.short_bars[-1]
                elif latest_bucket is not None and bucket < latest_bucket:
                    for candidate in reversed(self.short_bars):
                        if candidate["time"] == bucket:
                            target = candidate
                            break
                        if candidate["time"] < bucket:
                            break
                if target is None:
                    target = {"time": bucket, "open": price, "high": price,
                              "low": price, "close": price, "volume": size,
                              "origin": "live", "first_trade_time": trade_unix,
                              "last_trade_time": trade_unix}
                    if latest_bucket is None or bucket > latest_bucket:
                        self.short_bars.append(target)
                    else:
                        index = len(self.short_bars)
                        while index and self.short_bars[index - 1]["time"] > bucket:
                            index -= 1
                        self.short_bars.insert(index, target)
                        self.series_revision += 1
                    short_changed = True
                else:
                    if target.get("origin") == "cache":
                        target["origin"] = "mixed"
                    target["high"] = max(target["high"], price)
                    target["low"] = min(target["low"], price)
                    target["volume"] += size
                    if trade_unix < target.get("first_trade_time", trade_unix):
                        target["first_trade_time"] = trade_unix
                        target["open"] = price
                    if trade_unix >= target.get("last_trade_time", trade_unix):
                        target["last_trade_time"] = trade_unix
                        target["close"] = price
                    if latest_bucket is not None and bucket < latest_bucket:
                        self.series_revision += 1
                    short_changed = True
            self._prune()
            if candle_changed or short_changed:
                self._cache_dirty = True
            self._notify()

    def on_quote(self, quote):
        """Registrar bid/ask IEX, sin alterar trades ni velas oficiales.

        Solo se usa el punto medio como referencia INDICATIVA de cotizacion,
        no como ultimo precio negociado ni como vela OHLCV de operaciones.
        """
        if quote.get("S") != self.symbol:
            return
        try:
            bid = float(quote["bp"])
            ask = float(quote["ap"])
            bid_size = max(0, int(quote.get("bs") or 0))
            ask_size = max(0, int(quote.get("as") or 0))
            ts = quote["t"]
            instant = _unix(ts)
            if (not math.isfinite(bid) or not math.isfinite(ask) or
                    bid <= 0 or ask <= 0 or ask < bid):
                return
        except (ValueError, TypeError, KeyError, OverflowError):
            return
        with self.lock:
            if quote.get("S") != self.symbol:
                return
            # Mensajes atrasados no sustituyen a una cotizacion mas nueva.
            if self.last_quote and instant < _unix(self.last_quote["timestamp"]):
                return
            mid = round((bid + ask) / 2.0, 6)
            self.last_quote = {"bid": bid, "ask": ask, "mid": mid,
                               "bid_size": bid_size, "ask_size": ask_size,
                               "timestamp": ts}
            now = _utc_iso()
            self.last_quote_received_at = now
            self.last_feed_message_at = now
            self.last_quote_lag_ms = round((time.time() - instant) * 1000)
            self.quote_count += 1
            bucket = int(instant) // 5 * 5
            if not self.quote_points or bucket > self.quote_points[-1]["time"]:
                self.quote_points.append({"time": bucket, "value": mid})
            elif bucket == self.quote_points[-1]["time"]:
                self.quote_points[-1]["value"] = mid
            if len(self.quote_points) > MAX_QUOTE_POINTS:
                self.quote_points = self.quote_points[-MAX_QUOTE_POINTS:]
            self._notify()

    def history(self, key, secret, symbol=None, reconcile=False):
        """Paginate 10 days and retain the most recent 500 official 1m candles.

        Network activity is strictly read-only and never blocks WebSocket.
        """
        with self.lock:
            symbol = symbol or self.symbol
        if symbol not in SYMBOLS:
            raise ValueError("Activo no permitido")
        history_url = "https://data.alpaca.markets/v2/stocks/" + symbol + "/bars"
        start = (datetime.now(timezone.utc) - timedelta(days=HISTORY_LOOKBACK_DAYS)).isoformat()
        gathered = {}
        token = None
        visited = set()
        last_http_status = None
        try:
            for page in range(HISTORY_MAX_PAGES):
                params = {"timeframe": "1Min", "feed": FEED, "start": start,
                          "limit": 1000, "adjustment": "raw"}
                if token:
                    params["page_token"] = token
                for attempt in range(3):
                    try:
                        response = requests.get(history_url,
                            headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
                            params=params, timeout=(4, 10))
                        last_http_status = response.status_code
                        if response.status_code in (429, 500, 502, 503, 504):
                            raise requests.HTTPError("Transient HTTP " + str(response.status_code))
                        if not response.ok:
                            raise RuntimeError("HTTP " + str(response.status_code))
                        result = response.json()
                        if not isinstance(result, dict) or not isinstance(result.get("bars", []), list):
                            raise ValueError("Unexpected REST payload")
                        break
                    except (requests.RequestException, ValueError) as err:
                        if attempt == 2:
                            raise
                        time.sleep(min(2 ** attempt, 4))
                for item in result.get("bars", []):
                    try:
                        bar = _bar(item)
                        bar["origin"] = "rest"
                        gathered[bar["time"]] = bar
                    except (ValueError, KeyError, TypeError, OverflowError):
                        continue
                next_token = result.get("next_page_token")
                if not next_token:
                    token = None
                    break
                if not isinstance(next_token, str) or next_token in visited:
                    raise ValueError("Repeated or malformed pagination token")
                visited.add(next_token)
                token = next_token
            if token:
                raise RuntimeError("Historical page limit reached; retained existing data")
            now_minute = int(time.time()) // 60 * 60
            with self.lock:
                if symbol != self.symbol:
                    return  # una respuesta antigua no debe contaminar el nuevo activo
                inserted = False
                for timestamp in sorted(gathered)[-MAX_MINUTE_BARS:]:
                    bar = gathered[timestamp]
                    # Never overwrite the ongoing minute. Reconciliation may replace
                    # an older stream/cache bar with the current REST authority.
                    if timestamp >= now_minute:
                        continue
                    previous = self.official.get(timestamp)
                    if previous is not None and not reconcile:
                        continue
                    comparable_previous = ({k: previous.get(k) for k in ("time", "open", "high", "low", "close", "volume")}
                                           if previous else None)
                    comparable_bar = {k: bar.get(k) for k in ("time", "open", "high", "low", "close", "volume")}
                    if comparable_previous != comparable_bar:
                        self.official[timestamp] = bar
                        inserted = True
                self.history_loaded = bool(self.official)
                self.history_source = ("alpaca" if gathered else self.history_source)
                self.history_error = None if gathered else "Alpaca no devolvio velas para este intervalo."
                self._history_completed_at = time.monotonic()
                if inserted:
                    self.series_revision += 1
                    self._prune()
                    self._cache_dirty = True
                self._notify()
        except (requests.RequestException, ValueError, RuntimeError, KeyError, TypeError) as err:
            # Report controlled diagnostic information only; never echo API URLs,
            # headers, tokens or arbitrary provider responses to the browser.
            diagnostic = ("HTTP " + str(last_http_status)) if last_http_status and last_http_status >= 400 \
                else type(err).__name__
            with self.lock:
                if symbol != self.symbol:
                    return
                self.history_error = "Historial REST: " + diagnostic + "; se conservan los datos existentes."
                self._notify()

    def _start_history(self, key, secret, *, reconcile=False, force=False):
        """Recupera huecos tras reconectar, sin lanzar solicitudes solapadas."""
        with self.lock:
            now = time.monotonic()
            if self._history_busy or (not force and now - self._history_requested_at < 30):
                return False
            self._history_busy = True
            self._history_requested_at = now
            symbol = self.symbol

        def worker():
            try:
                self.history(key, secret, symbol=symbol, reconcile=reconcile)
            finally:
                with self.lock:
                    if symbol == self.symbol:
                        self._history_busy = False

        threading.Thread(target=worker, name="alpaca-historial", daemon=True).start()
        return True

    @staticmethod
    def _subscription_payload(action, symbol):
        payload = {"action": action}
        for channel in REQUIRED_CHANNELS + OPTIONAL_CHANNELS:
            payload[channel] = [symbol]
        return payload

    def _subscriptions_complete(self):
        return all(self.channel_status.get(name, False) for name in REQUIRED_CHANNELS)

    def _feed_message(self, obj, ws, authenticated):
        if not isinstance(obj, dict):
            return authenticated, False
        kind = obj.get("T")
        if kind == "success" and obj.get("msg") == "authenticated":
            authenticated = True
            with self.lock:
                symbol = self.symbol
            ws.send(json.dumps(self._subscription_payload("subscribe", symbol)))
        elif kind == "subscription" and authenticated:
            with self.lock:
                symbol = self.symbol
                self.channel_status = {name: symbol in (obj.get(name) or [])
                                       for name in REQUIRED_CHANNELS}
                self.optional_channel_status = {name: symbol in (obj.get(name) or [])
                                                for name in OPTIONAL_CHANNELS}
                self.quotes_subscribed = self.channel_status["quotes"]
                complete = self._subscriptions_complete()
            if complete:
                self.set_status("conectado")
            else:
                missing = ", ".join(name for name in REQUIRED_CHANNELS
                                    if not self.channel_status.get(name))
                self.set_status("suscripcion_incompleta", "Canales pendientes: " + missing)
        elif kind == "error":
            code = obj.get("code")
            self.set_status("error", f"Error de Alpaca (codigo {code}).")
            # Evitar bucle de autenticacion/reconexion en errores de acceso.
            with self.lock:
                self.last_error_code = code
            return authenticated, code in (401, 402, 403, 404, 405, 406, 407, 409, 500)
        elif kind == "t":
            self.on_trade(obj)
        elif kind == "q":
            self.on_quote(obj)
        elif kind in ("b", "u") and obj.get("S") == self.symbol:
            try:
                self.insert_bar(_bar(obj))
            except (ValueError, KeyError, TypeError, OverflowError):
                pass
        elif kind in ("c", "x") and obj.get("S") == self.symbol:
            with self.lock:
                self.correction_count += 1
                self._reconcile_requested = True
                self.last_feed_message_at = _utc_iso()
                self._notify()
        return authenticated, False

    def run(self):
        try:
            key, secret = _credentials()
        except (OSError, ValueError) as err:
            # Errores locales controlados, sin imprimir el contenido del TXT.
            self.set_status("error", "No se pudo leer Alpaca_key.txt: " + type(err).__name__)
            return
        # Prioridad absoluta: conectar al flujo antes de descargar historicos.
        self._start_history(key, secret)
        backoff = 2
        while True:
            retry_code = None
            try:
                self.set_status("conectando" if backoff == 2 else "reconectando")
                with connect(WS_URL, open_timeout=10, ping_interval=20,
                             ping_timeout=20, max_size=1048576) as ws:
                    authenticated = False
                    connected_at = time.monotonic()
                    subscription_requested_at = None
                    reconciled_after_connect = False
                    ws.send(json.dumps({"action": "auth", "key": key, "secret": secret}))
                    subscribed_symbol = None
                    fallback_messages = iter(ws) if not hasattr(ws, "recv") else None
                    while True:
                        try:
                            payload = ws.recv(timeout=1.0) if fallback_messages is None else next(fallback_messages)
                        except TimeoutError:
                            payload = None
                        except StopIteration:
                            break
                        if payload is None:
                            messages = []
                        else:
                            try:
                                messages = json.loads(payload)
                            except (ValueError, TypeError):
                                messages = []
                        if isinstance(messages, list):
                            for obj in messages:
                                authenticated, fatal = self._feed_message(obj, ws, authenticated)
                                if (isinstance(obj, dict) and obj.get("T") == "success" and
                                        obj.get("msg") == "authenticated"):
                                    with self.lock:
                                        subscribed_symbol = self.symbol
                                    subscription_requested_at = time.monotonic()
                                if fatal:
                                    code = obj.get("code") if isinstance(obj, dict) else None
                                    if code in (406, 407, 500):
                                        raise _RetryStream(code)
                                    return
                        now = time.monotonic()
                        if not authenticated and now - connected_at > AUTH_TIMEOUT_SECONDS:
                            raise _RetryStream("AUTH_TIMEOUT")
                        if authenticated:
                            with self.lock:
                                desired_symbol = self.symbol
                                complete = self._subscriptions_complete()
                            if subscribed_symbol is not None and desired_symbol != subscribed_symbol:
                                old = subscribed_symbol
                                ws.send(json.dumps(self._subscription_payload("unsubscribe", old)))
                                ws.send(json.dumps(self._subscription_payload("subscribe", desired_symbol)))
                                subscribed_symbol = desired_symbol
                                subscription_requested_at = now
                                reconciled_after_connect = False
                            if (subscription_requested_at is not None and not complete and
                                    now - subscription_requested_at > SUBSCRIPTION_TIMEOUT_SECONDS):
                                raise _RetryStream("SUBSCRIPTION_TIMEOUT")
                            if self.status == "conectado":
                                backoff = 2
                                if self.reconnect_count and not reconciled_after_connect:
                                    self._start_history(key, secret, reconcile=True)
                                    reconciled_after_connect = True
                            with self.lock:
                                reconcile = self._reconcile_requested
                            if reconcile and self._start_history(key, secret, reconcile=True, force=True):
                                with self.lock:
                                    self._reconcile_requested = False
                    # Si cierra normalmente, tambien debemos reconectar.
                    self.set_status("reconectando", "Conexion terminada; reconectando.")
            except _RetryStream as err:
                retry_code = err.code
                if retry_code == 406:
                    backoff = max(backoff, 15)
                    message = "Alpaca rechazo una segunda conexion (406); reintento controlado."
                elif retry_code == 407:
                    message = "Alpaca desconecto al cliente lento (407); reduciendo carga y reconectando."
                elif retry_code == "AUTH_TIMEOUT":
                    message = "Alpaca no confirmo autenticacion a tiempo; reconectando."
                elif retry_code == "SUBSCRIPTION_TIMEOUT":
                    message = "Alpaca no confirmo todos los canales a tiempo; reconectando."
                else:
                    message = "Alpaca interrumpio el flujo; reconectando."
                self.set_status("reconectando", message)
            except Exception as err:
                # Nunca enviar excepciones potencialmente sensibles al navegador.
                retry_code = type(err).__name__
                self.set_status("reconectando", "Conexion interrumpida; reconectando.")
            with self.lock:
                self.reconnect_count += 1
                self.last_reconnect_reason = str(retry_code or "CONNECTION_CLOSED")
                self.last_error_code = retry_code
                self.channel_status = {name: False for name in REQUIRED_CHANNELS}
                self.optional_channel_status = {name: False for name in OPTIONAL_CHANNELS}
                self.quotes_subscribed = False
                self._notify()
            time.sleep(backoff + random.uniform(0, min(1.0, backoff * 0.2)))
            backoff = min(backoff * 2, 30)


_feed = LiveFeed()
atexit.register(_feed._save_cache)


def register_live(app):
    @app.route("/live")
    def alpaca_live_page():
        return send_from_directory(app.static_folder, "live.html")

    @app.route("/api/alpaca/live", methods=["GET"])
    def alpaca_live_state():
        _feed.start()
        result = jsonify(_feed.snapshot())
        result.headers["Cache-Control"] = "no-store"
        return result

    @app.route("/api/alpaca/symbol", methods=["POST"])
    def alpaca_live_select_symbol():
        from flask import request
        payload = request.get_json(silent=True)
        symbol = payload.get("symbol") if isinstance(payload, dict) else None
        if not isinstance(symbol, str) or symbol not in SYMBOLS:
            return jsonify({"error": "Activo no permitido"}), 400
        _feed.select_symbol(symbol)
        reply = jsonify({"symbol": _feed.snapshot()["symbol"], "status": "ok"})
        reply.headers["Cache-Control"] = "no-store"
        return reply

    @app.route("/api/alpaca/events", methods=["GET"])
    def alpaca_live_events():
        _feed.start()

        def events():
            version = -1
            while True:
                updated = _feed.wait_for_version(version, timeout=15)
                if updated != version:
                    version = updated
                    yield f"event: update\ndata: {version}\n\n"
                    # Batching de eventos para no saturar WebView ante miles de trades.
                    time.sleep(0.08)
                else:
                    yield ": keepalive\n\n"

        return Response(stream_with_context(events()), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache, no-transform",
                                 "X-Accel-Buffering": "no"})
