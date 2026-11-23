"""TraderAssistant v4 -- lectura de datos de mercado Alpaca IEX.

Solo lectura: no usa API de ordenes, ni expone credenciales por HTTP.
Velas 1m oficiales de Alpaca (REST y canales bars/updatedBars); la vela
actual y las de 5 s son INDICATIVAS a partir de operaciones elegibles.
"""
from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import threading
import time

import requests
from flask import Response, jsonify, send_from_directory, stream_with_context
from websockets.sync.client import connect

VERSION = "4.0.0"
SYMBOL = "NVDA"
FEED = "iex"
WS_URL = "wss://stream.data.alpaca.markets/v2/iex"
HISTORY_URL = "https://data.alpaca.markets/v2/stocks/NVDA/bars"
KEY_FILE = Path.home() / "Documents" / "Alpaca_key.txt"
MAX_MINUTE_BARS = 650
MAX_5SEC_BARS = 1200
MAX_TRADE_IDS = 6000

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


class LiveFeed:
    def __init__(self):
        self.lock = threading.RLock()
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
            if self.started:
                return
            self.started = True
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
            return {
                "version_info": VERSION,
                "symbol": SYMBOL, "feed": FEED,
                "status": self.status, "error": self.error,
                "history_error": self.history_error,
                "history_loaded": self.history_loaded,
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
                                        "low": price, "close": price, "volume": size})
            elif bucket == self.short_bars[-1]["time"]:
                b = self.short_bars[-1]
                b["high"] = max(b["high"], price)
                b["low"] = min(b["low"], price)
                b["close"] = price
                b["volume"] += size
            self._prune()
            self._notify()

    def history(self, key, secret):
        """Cargar historial en OTRO hilo, sin bloquear el websocket en vivo."""
        start = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        try:
            result = requests.get(
                HISTORY_URL,
                headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
                params={"timeframe": "1Min", "feed": FEED, "start": start,
                        "limit": 1000, "adjustment": "raw"},
                timeout=(4, 10),
            )
            if not result.ok:
                raise RuntimeError("Respuesta HTTP inesperada")
            items = [_bar(item) for item in result.json().get("bars", [])]
            now_minute = int(time.time()) // 60 * 60
            with self.lock:
                inserted = False
                for bar in items:
                    # No contaminar vela en formacion ni reemplazar barras del stream.
                    if bar["time"] >= now_minute or bar["time"] in self.official:
                        continue
                    self.official[bar["time"]] = bar
                    inserted = True
                self.history_loaded = True
                self.history_error = None
                if inserted:
                    self.series_revision += 1
                    self._prune()
                self._notify()
        except (requests.RequestException, ValueError, RuntimeError, KeyError, TypeError):
            with self.lock:
                self.history_error = "No se pudo recuperar el historial IEX; el flujo puede seguir activo."
                self._notify()

    def _start_history(self, key, secret):
        """Recupera huecos tras reconectar, sin lanzar solicitudes solapadas."""
        with self.lock:
            now = time.monotonic()
            if self._history_busy or now - self._history_requested_at < 30:
                return
            self._history_busy = True
            self._history_requested_at = now

        def worker():
            try:
                self.history(key, secret)
            finally:
                with self.lock:
                    self._history_busy = False

        threading.Thread(target=worker, name="alpaca-historial", daemon=True).start()

    def _feed_message(self, obj, ws, authenticated):
        if not isinstance(obj, dict):
            return authenticated, False
        kind = obj.get("T")
        if kind == "success" and obj.get("msg") == "authenticated":
            authenticated = True
            ws.send(json.dumps({"action": "subscribe", "trades": [SYMBOL],
                                "bars": [SYMBOL], "updatedBars": [SYMBOL]}))
        elif kind == "subscription" and authenticated:
            if SYMBOL in obj.get("trades", []) and SYMBOL in obj.get("bars", []):
                self.set_status("conectado")
            else:
                self.set_status("error", "Suscripcion al feed IEX no confirmada.")
                return authenticated, True
        elif kind == "error":
            code = obj.get("code")
            self.set_status("error", f"Error de Alpaca (codigo {code}).")
            # Evitar bucle de autenticacion/reconexion en errores de acceso.
            return authenticated, code in (401, 402, 403, 404, 405, 406, 409)
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
            try:
                self.set_status("conectando" if backoff == 2 else "reconectando")
                with connect(WS_URL, open_timeout=10, ping_interval=20,
                             ping_timeout=20, max_size=1048576) as ws:
                    authenticated = False
                    ws.send(json.dumps({"action": "auth", "key": key, "secret": secret}))
                    for payload in ws:
                        try:
                            messages = json.loads(payload)
                        except (ValueError, TypeError):
                            continue
                        if not isinstance(messages, list):
                            continue
                        for obj in messages:
                            authenticated, fatal = self._feed_message(obj, ws, authenticated)
                            if fatal:
                                return
                        if authenticated and self.status == "conectado":
                            backoff = 2
                            if self.reconnect_count:
                                self._start_history(key, secret)
                    # Si cierra normalmente, tambien debemos reconectar.
                    self.set_status("reconectando", "Conexion terminada; reconectando.")
            except Exception:
                # Nunca enviar excepciones potencialmente sensibles al navegador.
                self.set_status("reconectando", "Conexion interrumpida; reconectando.")
            with self.lock:
                self.reconnect_count += 1
                self._notify()
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)


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
