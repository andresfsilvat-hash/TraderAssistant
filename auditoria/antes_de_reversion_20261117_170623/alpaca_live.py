"""TraderAssistant v4 -- lectura de datos de mercado Alpaca IEX.

Solo lectura: no usa API de ordenes, ni expone credenciales por HTTP.
Velas 1m oficiales de Alpaca (REST y canales bars/updatedBars); la vela
actual y las de 5 s son INDICATIVAS a partir de operaciones elegibles.
"""
from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timedelta, timezone
import json
import logging
import math
from pathlib import Path
import threading
import time
import tempfile
from zoneinfo import ZoneInfo

import requests
from flask import Response, jsonify, send_from_directory, stream_with_context
from websockets.sync.client import connect

VERSION = "4.0.0"
SYMBOL = "NVDA"
FEED = "iex"
WS_URL = "wss://stream.data.alpaca.markets/v2/iex"
HISTORY_URL = "https://data.alpaca.markets/v2/stocks/NVDA/bars"
KEY_FILE = Path.home() / "Documents" / "Alpaca_key.txt"
CACHE_DIR = Path(__file__).resolve().parent / "cache"
CACHE_FILE = CACHE_DIR / "alpaca_iex_nvda.json"
MAX_MINUTE_BARS = 500
MAX_5SEC_BARS = 1200
MAX_TRADE_IDS = 6000
HISTORY_DAYS = 10
HISTORY_PAGE_LIMIT = 1000
HISTORY_MAX_PAGES = 20
HISTORY_RETRIES = 3
HISTORY_RETRY_DELAYS = (1.0, 2.0, 4.0)
HISTORY_REFRESH_SECONDS = 300
HISTORY_FAILURE_RETRY_MAX = 60
CACHE_WRITE_INTERVAL = 1.0

logger = logging.getLogger(__name__)


class HistoryDownloadError(RuntimeError):
    def __init__(self, message, *, error_type="HistoryDownloadError", http_status=None):
        super().__init__(message)
        self.error_type = error_type
        self.http_status = http_status

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


def _utc_iso():
    return datetime.now(timezone.utc).isoformat()


def _regular_market_state(now=None):
    """Estado horario regular estimado; no afirma conocer festivos bursatiles."""
    current = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo("America/New_York"))
    minutes = current.hour * 60 + current.minute
    is_open = current.weekday() < 5 and 570 <= minutes < 960
    return {
        "regular_market": "open" if is_open else "closed",
        "regular_market_verified": False,
        "regular_market_note": "Estimado por horario NY; festivos no verificados.",
    }


class LiveFeed:
    def __init__(self):
        self.lock = threading.RLock()
        self.condition = threading.Condition(self.lock)
        self.started = False
        self.status = "sin_iniciar"
        self.error = None
        self.history_error = None
        self.history_error_type = None
        self.history_http_status = None
        self.history_loaded = False
        self.history_status = "idle"
        self.history_source = None
        self.history_cached_at = None
        self.history_last_attempt_at = None
        self.history_last_success_at = None
        self.official = {}  # timestamp -> candle, siempre autoridad final
        self.provisional = None  # vela 1m en progreso, indicativa
        self.short_bars = []  # velas 5s solo desde conexion, indicativas
        self.last_trade = None
        self.last_received_at = None
        self.last_feed_message_at = None
        self.trade_count = 0
        self.eligible_count = 0
        self.excluded_count = 0
        self.last_lag_ms = None
        self.version = 0
        self.series_revision = 0  # incrementa si hay correcciones antiguas o backfill
        self.reconnect_count = 0
        self._seen_trade_ids = OrderedDict()
        self._history_busy = False
        self._history_requested_at = 0.0
        self._history_manager_started = False
        self._history_wakeup = threading.Event()
        self._stream_running = False
        self._cache_save_busy = False
        self._cache_dirty = False
        self._last_cache_save = 0.0
        self._load_cache()

    def _notify(self):
        # Siempre se llama con self.lock
        self.version += 1
        self.condition.notify_all()

    def set_status(self, status, error=None):
        with self.lock:
            if self.status != status or self.error != error:
                self.status, self.error = status, error
                self._notify()

    @staticmethod
    def _cached_bar(item, seconds):
        if not isinstance(item, dict):
            raise ValueError("Vela cache invalida")
        timestamp = int(item["time"])
        vals = [float(item[k]) for k in ("open", "high", "low", "close")]
        volume = int(item.get("volume", 0))
        if timestamp % seconds or volume < 0 or not all(math.isfinite(v) and v > 0 for v in vals):
            raise ValueError("Vela cache invalida")
        if vals[1] < max(vals[0], vals[3]) or vals[2] > min(vals[0], vals[3]):
            raise ValueError("OHLC cache inconsistente")
        return {"time": timestamp, "open": vals[0], "high": vals[1], "low": vals[2],
                "close": vals[3], "volume": volume}

    def _load_cache(self):
        """Restaurar solo datos validados; una cache rota nunca impide arrancar."""
        if not CACHE_FILE.is_file():
            return
        try:
            if CACHE_FILE.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("Cache demasiado grande")
            payload = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            if payload.get("schema") != 1 or payload.get("symbol") != SYMBOL:
                raise ValueError("Esquema de cache incompatible")
            official = {}
            for item in payload.get("official", []):
                bar = self._cached_bar(item, 60)
                official[bar["time"]] = bar
            short = {}
            for item in payload.get("short_bars", []):
                bar = self._cached_bar(item, 5)
                bar["source"] = "cache"
                short[bar["time"]] = bar
            self.official = dict(sorted(official.items())[-MAX_MINUTE_BARS:])
            self.short_bars = [short[k] for k in sorted(short)][-MAX_5SEC_BARS:]
            self.history_cached_at = payload.get("saved_at")
            if self.official:
                self.history_loaded = True
                self.history_status = "cache"
                self.history_source = "cache"
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as err:
            logger.warning("Cache Alpaca ignorada: %s", type(err).__name__)

    def _cache_payload_locked(self):
        return {
            "schema": 1,
            "symbol": SYMBOL,
            "feed": FEED,
            "saved_at": _utc_iso(),
            "official": [dict(self.official[k]) for k in sorted(self.official)[-MAX_MINUTE_BARS:]],
            "short_bars": [dict(b) for b in self.short_bars[-MAX_5SEC_BARS:]],
        }

    @staticmethod
    def _write_cache_payload(payload):
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=CACHE_DIR,
                                             prefix="alpaca_", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
            temporary.replace(CACHE_FILE)
        finally:
            if temporary and temporary.exists():
                try:
                    temporary.unlink()
                except OSError:
                    pass

    def _schedule_cache_save(self):
        with self.lock:
            self._cache_dirty = True
            if self._cache_save_busy:
                return
            self._cache_save_busy = True

        def worker():
            while True:
                delay = max(0.0, CACHE_WRITE_INTERVAL - (time.monotonic() - self._last_cache_save))
                if delay:
                    time.sleep(delay)
                with self.lock:
                    if not self._cache_dirty:
                        self._cache_save_busy = False
                        return
                    self._cache_dirty = False
                    payload = self._cache_payload_locked()
                try:
                    self._write_cache_payload(payload)
                    self._last_cache_save = time.monotonic()
                    with self.lock:
                        self.history_cached_at = payload["saved_at"]
                except OSError as err:
                    logger.warning("No se pudo guardar cache Alpaca: %s", type(err).__name__)
                with self.lock:
                    if not self._cache_dirty:
                        self._cache_save_busy = False
                        return

        threading.Thread(target=worker, name="alpaca-cache", daemon=True).start()

    def start(self):
        with self.lock:
            if not self._history_manager_started:
                self._history_manager_started = True
                threading.Thread(target=self._history_loop, name="alpaca-historial", daemon=True).start()
            if self._stream_running:
                return
            self.started = True
            self._stream_running = True
            self.status = "iniciando"
            self._notify()
        threading.Thread(target=self.run, name="alpaca-iex-stream", daemon=True).start()

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
        candles = [dict(self.official[k], provisional=False) for k in sorted(self.official)]
        p = self.provisional
        if p and (not candles or p["time"] > candles[-1]["time"]):
            candles.append(dict(p, provisional=True))
        return candles[-MAX_MINUTE_BARS:]

    def snapshot(self):
        with self.lock:
            result = {
                "version_info": VERSION,
                "symbol": SYMBOL, "feed": FEED,
                "status": self.status, "error": self.error,
                "history_error": self.history_error,
                "history_error_type": self.history_error_type,
                "history_http_status": self.history_http_status,
                "history_loaded": self.history_loaded,
                "history_status": self.history_status,
                "history_source": self.history_source,
                "history_cached_at": self.history_cached_at,
                "history_last_attempt_at": self.history_last_attempt_at,
                "history_last_success_at": self.history_last_success_at,
                "candles": self._snapshot_bars(),
                "short_candles": [dict(b, provisional=True) for b in self.short_bars],
                "last_trade": dict(self.last_trade) if self.last_trade else None,
                "last_received_at": self.last_received_at,
                "last_feed_message_at": self.last_feed_message_at,
                "last_lag_ms": self.last_lag_ms,
                "trade_count": self.trade_count,
                "eligible_count": self.eligible_count,
                "excluded_count": self.excluded_count,
                "reconnect_count": self.reconnect_count,
                "series_revision": self.series_revision,
                "version": self.version,
                "server_time": _utc_iso(),
            }
            result.update(_regular_market_state())
            return result

    def insert_bar(self, bar):
        """Aplicar una barra oficial de Alpaca b/u sin mezclarla con provisional."""
        minute = bar["time"]
        with self.lock:
            previous = self.official.get(minute)
            if previous == bar:
                return
            latest = max(self.official) if self.official else None
            self.official[minute] = dict(bar)
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
            self._schedule_cache_save()

    def on_trade(self, trade):
        if trade.get("S") != SYMBOL:
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
            if self.official and minute <= max(self.official):
                # Una barra oficial JAMAS se recalcula desde un trade tardio.
                self._notify()
                return
            if self.provisional and minute < self.provisional["time"]:
                self._notify()
                return
            if not self.provisional or minute > self.provisional["time"]:
                self.provisional = {"time": minute, "open": price, "high": price,
                                    "low": price, "close": price, "volume": size}
            else:
                p = self.provisional
                p["high"] = max(p["high"], price)
                p["low"] = min(p["low"], price)
                p["close"] = price
                p["volume"] += size

            bucket = int(trade_unix) // 5 * 5
            if not self.short_bars or bucket > self.short_bars[-1]["time"]:
                self.short_bars.append({"time": bucket, "open": price, "high": price,
                                        "low": price, "close": price, "volume": size,
                                        "source": "live"})
            elif bucket == self.short_bars[-1]["time"]:
                b = self.short_bars[-1]
                b["high"] = max(b["high"], price)
                b["low"] = min(b["low"], price)
                b["close"] = price
                b["volume"] += size
            self._prune()
            self._notify()
            self._schedule_cache_save()

    def _history_page(self, key, secret, params):
        last_error = None
        last_status = None
        for attempt in range(HISTORY_RETRIES):
            try:
                response = requests.get(
                    HISTORY_URL,
                    headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
                    params=params,
                    timeout=(4, 10),
                )
                last_status = response.status_code
                if not response.ok:
                    raise HistoryDownloadError("Respuesta HTTP inesperada", http_status=last_status,
                                               error_type="HTTPError")
                payload = response.json()
                if not isinstance(payload, dict) or not isinstance(payload.get("bars", []), list):
                    raise HistoryDownloadError("Respuesta JSON inesperada", error_type="InvalidPayload")
                return payload
            except HistoryDownloadError as err:
                last_error = err
            except requests.RequestException as err:
                last_error = HistoryDownloadError("Fallo de red", error_type=type(err).__name__)
            except (ValueError, TypeError) as err:
                last_error = HistoryDownloadError("JSON invalido", error_type=type(err).__name__)
            if attempt + 1 < HISTORY_RETRIES:
                time.sleep(HISTORY_RETRY_DELAYS[min(attempt, len(HISTORY_RETRY_DELAYS) - 1)])
        if last_error is None:
            last_error = HistoryDownloadError("Fallo historico desconocido", http_status=last_status)
        raise last_error

    def history(self, key, secret):
        """Obtener hasta diez dias, paginar y conservar las ultimas 500 velas validas."""
        with self.lock:
            if self._history_busy:
                return False
            self._history_busy = True
            self._history_requested_at = time.monotonic()
            self.history_status = "loading"
            self.history_last_attempt_at = _utc_iso()
            self._notify()
        try:
            now = datetime.now(timezone.utc)
            params = {
                "timeframe": "1Min", "feed": FEED,
                "start": (now - timedelta(days=HISTORY_DAYS)).isoformat(),
                "end": now.isoformat(), "limit": HISTORY_PAGE_LIMIT,
                "adjustment": "raw", "sort": "asc",
            }
            unique = {}
            seen_tokens = set()
            invalid_count = 0
            for _ in range(HISTORY_MAX_PAGES):
                payload = self._history_page(key, secret, params)
                for item in payload.get("bars", []):
                    try:
                        bar = _bar(item)
                        unique[bar["time"]] = bar
                    except (ValueError, KeyError, TypeError, OverflowError):
                        invalid_count += 1
                token = payload.get("next_page_token")
                if not token:
                    break
                if not isinstance(token, str) or token in seen_tokens:
                    raise HistoryDownloadError("Token de paginacion invalido", error_type="PaginationError")
                seen_tokens.add(token)
                params["page_token"] = token
            else:
                raise HistoryDownloadError("Limite de paginas excedido", error_type="PaginationLimit")
            if invalid_count:
                logger.warning("Historial IEX omitio %d velas invalidas", invalid_count)
            now_minute = int(time.time()) // 60 * 60
            fetched = {t: unique[t] for t in sorted(unique) if t < now_minute}
            with self.lock:
                merged = dict(fetched)
                merged.update(self.official)  # las barras ya recibidas por stream prevalecen
                ordered = sorted(merged)[-MAX_MINUTE_BARS:]
                new_official = {t: merged[t] for t in ordered}
                if new_official != self.official:
                    self.official = new_official
                    self.series_revision += 1
                self.history_loaded = bool(self.official)
                self.history_status = "loaded" if fetched else ("cache" if self.official else "loaded")
                self.history_source = "alpaca" if fetched else ("cache" if self.official else None)
                self.history_error = None
                self.history_error_type = None
                self.history_http_status = None
                self.history_last_success_at = _utc_iso()
                self._prune()
                self._notify()
                self._schedule_cache_save()
            return True
        except HistoryDownloadError as err:
            logger.warning("Historial IEX fallo: tipo=%s http=%s", err.error_type,
                           err.http_status if err.http_status is not None else "n/a")
            with self.lock:
                self.history_status = "error"
                self.history_error_type = err.error_type
                self.history_http_status = err.http_status
                self.history_error = "No se pudo actualizar el historial IEX; se conserva la cache disponible."
                if self.official and self.history_source is None:
                    self.history_source = "cache"
                self.history_loaded = bool(self.official)
                self._notify()
            return False
        finally:
            with self.lock:
                self._history_busy = False

    def _history_loop(self):
        failure_delay = 5
        while True:
            try:
                key, secret = _credentials()
                success = self.history(key, secret)
            except (OSError, ValueError) as err:
                logger.warning("Historial IEX sin credenciales utilizables: %s", type(err).__name__)
                with self.lock:
                    self.history_status = "error"
                    self.history_error_type = type(err).__name__
                    self.history_error = "No se pudo leer Alpaca_key.txt para actualizar el historial."
                    self._notify()
                success = False
            wait_seconds = HISTORY_REFRESH_SECONDS if success else failure_delay
            failure_delay = 5 if success else min(failure_delay * 2, HISTORY_FAILURE_RETRY_MAX)
            self._history_wakeup.wait(wait_seconds)
            self._history_wakeup.clear()

    def _start_history(self, key=None, secret=None):
        """Solicitar una actualizacion al gestor unico, sin crear hilos solapados."""
        self._history_wakeup.set()

    def _feed_message(self, obj, ws, authenticated):
        if not isinstance(obj, dict):
            return authenticated, None
        kind = obj.get("T")
        if kind in ("success", "subscription", "error"):
            with self.lock:
                self.last_feed_message_at = _utc_iso()
                self._notify()
        if kind == "success" and obj.get("msg") == "authenticated":
            authenticated = True
            ws.send(json.dumps({"action": "subscribe", "trades": [SYMBOL],
                                "bars": [SYMBOL], "updatedBars": [SYMBOL]}))
        elif kind == "subscription" and authenticated:
            if (SYMBOL in obj.get("trades", []) and SYMBOL in obj.get("bars", [])
                    and SYMBOL in obj.get("updatedBars", [])):
                self.set_status("conectado")
            else:
                self.set_status("error", "Suscripcion al feed IEX no confirmada.")
                return authenticated, "stop"
        elif kind == "error":
            code = obj.get("code")
            if code == 406:
                self.set_status("reconectando", "Limite de conexion Alpaca (406); reintentando sin solapar conexiones.")
                return authenticated, "reconnect"
            self.set_status("error", f"Error de Alpaca (codigo {code}).")
            # Credenciales, protocolo o plan requieren intervencion; se permite reiniciar el hilo despues.
            return authenticated, "stop" if code in (401, 402, 403, 404, 405, 409) else "reconnect"
        elif kind == "t":
            self.on_trade(obj)
        elif kind in ("b", "u") and obj.get("S") == SYMBOL:
            try:
                self.insert_bar(_bar(obj))
            except (ValueError, KeyError, TypeError, OverflowError):
                pass
        elif kind in ("c", "x") and obj.get("S") == SYMBOL:
            # Se espera una barra actualizada u. Reconciliar historial en otra iteracion;
            # no cambiar retroactivamente OHLC desde eventos individuales ambiguos.
            with self.lock:
                self.last_feed_message_at = _utc_iso()
                self._notify()
        return authenticated, None

    def run(self):
        try:
            try:
                key, secret = _credentials()
            except (OSError, ValueError) as err:
                self.set_status("error", "No se pudo leer Alpaca_key.txt: " + type(err).__name__)
                return
            backoff = 2
            while True:
                try:
                    self.set_status("conectando" if self.reconnect_count == 0 else "reconectando")
                    with connect(WS_URL, open_timeout=10, ping_interval=20,
                                 ping_timeout=20, max_size=1048576) as ws:
                        authenticated = False
                        reconnect_requested = False
                        ws.send(json.dumps({"action": "auth", "key": key, "secret": secret}))
                        for payload in ws:
                            try:
                                messages = json.loads(payload)
                            except (ValueError, TypeError):
                                logger.warning("WebSocket IEX envio JSON invalido")
                                continue
                            if not isinstance(messages, list):
                                continue
                            for obj in messages:
                                authenticated, disposition = self._feed_message(obj, ws, authenticated)
                                if disposition == "stop":
                                    return
                                if disposition == "reconnect":
                                    reconnect_requested = True
                                    break
                            if reconnect_requested:
                                break
                            if authenticated and self.status == "conectado":
                                backoff = 2
                        if not reconnect_requested:
                            self.set_status("reconectando", "Conexion terminada; reconectando.")
                except Exception as err:
                    logger.warning("WebSocket IEX interrumpido: %s", type(err).__name__)
                    self.set_status("reconectando", "Conexion interrumpida; reconectando.")
                with self.lock:
                    self.reconnect_count += 1
                    self._notify()
                self._start_history()
                time.sleep(backoff)
                backoff = min(backoff * 2, 30)
        finally:
            with self.lock:
                self.started = False
                self._stream_running = False
                self._notify()


_feed = LiveFeed()


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
