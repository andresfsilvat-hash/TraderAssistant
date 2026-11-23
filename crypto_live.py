"""Lectura independiente de criptomonedas Alpaca 24/7 — sin órdenes.

WebSocket oficial v1beta3/crypto/us (trades, quotes, bars, updatedBars)
e historial REST autenticado. Se abre a demanda en /api/crypto/live.
Las velas cripto pueden incluir puntos medios bid/ask; NO son un precio de
liquidación IQ Option ni alimentan el motor predictivo NVDA.
"""
from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timedelta, timezone
import json
import math
import threading
import time

import requests
from flask import jsonify, request, send_from_directory
from websockets.sync.client import connect

from alpaca_live import _credentials

CRYPTO_SYMBOLS = {
    "BTC/USD": "Bitcoin", "ETH/USD": "Ethereum", "SOL/USD": "Solana"
}
WS_URL = "wss://stream.data.alpaca.markets/v1beta3/crypto/us"
REST_URL = "https://data.alpaca.markets/v1beta3/crypto/us/bars"
MAX_BARS = 450


def _now():
    return datetime.now(timezone.utc).isoformat()


def _timestamp(value):
    """Normaliza RFC3339 con nanosegundos; no admite marcas sin zona."""
    stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("timestamp sin zona")
    return stamp.astimezone(timezone.utc)


def _positive(value, *, zero=False):
    result = float(value)
    if not math.isfinite(result) or result < 0 or (not zero and result == 0):
        raise ValueError("precio o tamaño inválido")
    return result


def _parse_bar(obj):
    when = int(_timestamp(obj["t"]).timestamp())
    o, h, l, c = (_positive(obj[k]) for k in ("o", "h", "l", "c"))
    v = _positive(obj.get("v", 0), zero=True)
    if h < max(o, c) or l > min(o, c):
        raise ValueError("OHLC inconsistente")
    return {"time": when, "open": o, "high": h, "low": l,
            "close": c, "volume": v, "provisional": False}


def _safe_error(error):
    # Nunca exponer el objeto de excepción (puede contener headers o tokens).
    if isinstance(error, requests.HTTPError):
        status = error.response.status_code if error.response is not None else None
        return "HTTP " + str(status or "error")
    return type(error).__name__


class CryptoFeed:
    def __init__(self):
        self.lock = threading.RLock()
        self.started = False
        self.symbol = "BTC/USD"
        self.generation = 0
        self.bars = OrderedDict()
        self.last_trade = None
        self.last_quote = None
        self.last_received_at = None
        self.last_quote_received_at = None
        self.last_feed_message_at = None
        self.status = "sin_iniciar"
        self.error = None
        self.history_error = None
        self.history_source = "sin_datos"
        self.series_revision = 0
        self.trade_count = 0
        self.quote_count = 0

    def _reset(self):
        self.bars.clear()
        self.last_trade = None
        self.last_quote = None
        self.last_received_at = None
        self.last_quote_received_at = None
        self.last_feed_message_at = None
        self.error = None
        self.history_error = None
        self.history_source = "sin_datos"
        self.trade_count = 0
        self.quote_count = 0
        self.series_revision += 1

    def select_symbol(self, symbol):
        if not isinstance(symbol, str) or symbol not in CRYPTO_SYMBOLS:
            raise ValueError("Par cripto no permitido")
        with self.lock:
            if symbol == self.symbol:
                return
            self.symbol = symbol
            self.generation += 1
            self._reset()
            self.status = "cambiando_activo"
            generation = self.generation
        if self.started:
            self._start_history(symbol, generation)

    def _put_bar(self, obj):
        bar = _parse_bar(obj)
        old = self.bars.get(bar["time"])
        if old == bar:
            return
        self.bars[bar["time"]] = bar
        self.bars = OrderedDict(sorted(self.bars.items())[-MAX_BARS:])
        self.series_revision += 1

    def _start_history(self, symbol, generation):
        def worker():
            try:
                key, secret = _credentials()
                headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
                params = {"symbols": symbol, "timeframe": "1Min", "sort": "desc",
                          "limit": MAX_BARS,
                          "start": (datetime.now(timezone.utc)-timedelta(hours=24)).isoformat()}
                response = requests.get(REST_URL, headers=headers, params=params, timeout=12)
                response.raise_for_status()
                payload = response.json()
                items = (payload.get("bars") or {}).get(symbol) or []
                if not isinstance(items, list):
                    raise ValueError("Respuesta de barras inválida")
                parsed = []
                for item in items:
                    try:
                        parsed.append(_parse_bar(item))
                    except (KeyError, TypeError, ValueError, OverflowError):
                        continue
                with self.lock:
                    if generation != self.generation or symbol != self.symbol:
                        return
                    for bar in sorted(parsed, key=lambda b: b["time"]):
                        # Un dato REST no reemplaza una corrección recibida por WebSocket.
                        if bar["time"] not in self.bars:
                            self.bars[bar["time"]] = bar
                    self.bars = OrderedDict(sorted(self.bars.items())[-MAX_BARS:])
                    if parsed:
                        self.series_revision += 1
                    self.history_source = "Alpaca REST (criptomonedas)"
                    self.history_error = None if parsed else "Alpaca no devolvió velas recientes"
            except (OSError, requests.RequestException, ValueError, TypeError, KeyError) as exc:
                with self.lock:
                    if generation == self.generation:
                        self.history_error = "Historial cripto: " + _safe_error(exc)
        threading.Thread(target=worker, daemon=True, name="crypto-history").start()

    def start(self):
        with self.lock:
            if self.started:
                return
            self.started = True
            self.status = "conectando"
            symbol, generation = self.symbol, self.generation
        self._start_history(symbol, generation)
        threading.Thread(target=self.run, daemon=True, name="crypto-websocket").start()

    def _handle(self, obj, ws, authorized):
        if not isinstance(obj, dict):
            return authorized, False
        kind = obj.get("T")
        if kind == "success" and obj.get("msg") == "authenticated":
            # run() suscribe exactamente una vez, tras autenticar.
            return True, False
        if kind == "error":
            code = obj.get("code")
            with self.lock:
                self.status = "error"
                self.error = "Alpaca Crypto rechazó la suscripción (código " + str(code) + ")"
            return authorized, code in (401, 402, 403, 404, 405, 406, 409)
        with self.lock:
            symbol = self.symbol
            if kind == "subscription":
                accepted = symbol in (obj.get("bars") or []) or symbol in (obj.get("trades") or [])
                self.status = "conectado" if accepted else "suscribiendo"
                self.error = None if accepted else "Suscripción cripto todavía no confirmada"
                self.last_feed_message_at = _now()
                return authorized, False
            if obj.get("S") != symbol:
                return authorized, False
            if kind in ("b", "u"):
                try:
                    self._put_bar(obj)
                    self.last_feed_message_at = _now()
                except (KeyError, ValueError, TypeError, OverflowError):
                    pass
            elif kind == "t":
                try:
                    price, size = _positive(obj["p"]), _positive(obj.get("s", 0), zero=True)
                    stamp = _timestamp(obj["t"]).isoformat()
                    self.last_trade = {"price": price, "size": size, "timestamp": stamp}
                    self.last_received_at = _now()
                    self.last_feed_message_at = self.last_received_at
                    self.trade_count += 1
                except (KeyError, TypeError, ValueError, OverflowError):
                    pass
            elif kind == "q":
                try:
                    bid, ask = _positive(obj["bp"]), _positive(obj["ap"])
                    if bid > ask:
                        raise ValueError("spread negativo")
                    stamp = _timestamp(obj["t"]).isoformat()
                    self.last_quote = {"bid": bid, "ask": ask,
                                       "mid": (bid + ask) / 2, "timestamp": stamp}
                    self.last_quote_received_at = _now()
                    self.last_feed_message_at = self.last_quote_received_at
                    self.quote_count += 1
                except (KeyError, TypeError, ValueError, OverflowError):
                    pass
        return authorized, False

    def run(self):
        try:
            key, secret = _credentials()
        except (OSError, ValueError) as exc:
            with self.lock:
                self.status = "error"
                self.error = "No se pudo leer la clave local de Alpaca: " + _safe_error(exc)
                self.started = False
            return
        backoff = 2
        while True:
            try:
                with self.lock:
                    self.status = "conectando" if backoff == 2 else "reconectando"
                with connect(WS_URL, open_timeout=10, ping_interval=20,
                             ping_timeout=20, max_size=1048576) as ws:
                    ws.send(json.dumps({"action": "auth", "key": key, "secret": secret}))
                    authorized = False
                    subscribed = None
                    backoff = 2
                    while True:
                        try:
                            raw = ws.recv(timeout=1)
                        except TimeoutError:
                            raw = None
                        if raw is not None:
                            try:
                                messages = json.loads(raw)
                            except (TypeError, ValueError):
                                messages = []
                            if isinstance(messages, list):
                                for obj in messages:
                                    authorized, fatal = self._handle(obj, ws, authorized)
                                    if fatal:
                                        with self.lock:
                                            self.started = False
                                        return
                        with self.lock:
                            desired = self.symbol
                        if authorized and desired != subscribed:
                            if subscribed is not None:
                                ws.send(json.dumps({"action": "unsubscribe",
                                                    "trades": [subscribed],
                                                    "quotes": [subscribed],
                                                    "bars": [subscribed],
                                                    "updatedBars": [subscribed]}))
                            ws.send(json.dumps({"action": "subscribe",
                                                "trades": [desired], "quotes": [desired],
                                                "bars": [desired], "updatedBars": [desired]}))
                            subscribed = desired
            except Exception as exc:
                with self.lock:
                    self.status = "reconectando"
                    self.error = "WebSocket cripto: " + _safe_error(exc)
                time.sleep(backoff)
                backoff = min(backoff * 2, 30)

    def snapshot(self):
        with self.lock:
            return {
                "source": "alpaca_crypto", "feed": "crypto/us",
                "symbol": self.symbol, "symbol_name": CRYPTO_SYMBOLS[self.symbol],
                "available_symbols": dict(CRYPTO_SYMBOLS),
                "market_hours": "24/7", "market_open_schedule": "continuo",
                "status": self.status, "error": self.error,
                "history_error": self.history_error,
                "history_source": self.history_source,
                "candles": list(self.bars.values()), "series_revision": self.series_revision,
                "last_trade": dict(self.last_trade) if self.last_trade else None,
                "last_quote": dict(self.last_quote) if self.last_quote else None,
                "last_received_at": self.last_received_at,
                "last_quote_received_at": self.last_quote_received_at,
                "last_feed_message_at": self.last_feed_message_at,
                "trade_count": self.trade_count, "quote_count": self.quote_count,
                "operativa_autorizada": False,
                "aviso": "SOLO OBSERVACIÓN · NO OPERAR · NO ES IQ OPTION",
            }


_feed = CryptoFeed()


def register_crypto_live(app):
    @app.route("/crypto")
    def crypto_page():
        return send_from_directory(app.static_folder, "crypto.html")

    @app.route("/api/crypto/live", methods=["GET"])
    def crypto_live_state():
        _feed.start()
        response = jsonify(_feed.snapshot())
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.route("/api/crypto/symbol", methods=["POST"])
    def crypto_set_symbol():
        payload = request.get_json(silent=True)
        symbol = payload.get("symbol") if isinstance(payload, dict) else None
        if symbol not in CRYPTO_SYMBOLS:
            return jsonify({"error": "Par cripto no permitido"}), 400
        _feed.select_symbol(symbol)
        response = jsonify({"status": "ok", "symbol": _feed.snapshot()["symbol"]})
        response.headers["Cache-Control"] = "no-store"
        return response
