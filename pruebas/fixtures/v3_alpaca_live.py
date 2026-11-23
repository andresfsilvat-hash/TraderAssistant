"""Read-only Alpaca IEX market stream for TraderAssistant.

Only the market-data endpoints below are contacted. The paper trading Endpoint
in the text file is deliberately never used to place orders or access accounts.
Credentials remain in the local Documents folder and are never returned by Flask.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from flask import Response, jsonify, send_from_directory, stream_with_context
from websockets.sync.client import connect

SYMBOL = "NVDA"
FEED = "iex"
WEBSOCKET_URL = "wss://stream.data.alpaca.markets/v2/iex"
HISTORY_URL = "https://data.alpaca.markets/v2/stocks/NVDA/bars"
KEY_FILE = Path.home() / "Documents" / "Alpaca_key.txt"
MAX_BARS = 450
SHORT_SECONDS = 5  # velas de cinco segundos desde las operaciones IEX recibidas
MAX_SHORT_BARS = 1200


def _credentials():
    """Parse a three-label plaintext file; never print or return the secrets."""
    if not KEY_FILE.is_file():
        raise FileNotFoundError("No se encuentra Alpaca_key.txt en Documentos.")
    lines = [s.strip() for s in KEY_FILE.read_text(encoding="utf-8-sig").splitlines()]
    fields = {}
    for i in range(len(lines) - 1):
        label = lines[i].lower().rstrip(":")
        if label in ("endpoint", "key", "secret"):
            fields[label] = lines[i + 1]
    if not fields.get("key") or not fields.get("secret"):
        raise ValueError("El archivo debe incluir Key y Secret, cada uno en su propia linea.")
    # Do not trust a user-supplied URL as a network destination.
    return fields["key"], fields["secret"]


def _as_unix(value):
    # Alpaca timestamps may include up to 9 subsecond digits.
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())


def _bar(data):
    return {
        "time": _as_unix(data["t"]),
        "open": float(data["o"]),
        "high": float(data["h"]),
        "low": float(data["l"]),
        "close": float(data["c"]),
        "volume": int(data.get("v", 0)),
    }


class LiveFeed:
    def __init__(self):
        self.lock = threading.RLock()
        self.started = False
        self.status = "sin_iniciar"
        self.error = None
        self.history_error = None
        self.bars = []
        self.short_bars = []
        self.last_trade = None
        self.last_received_at = None
        self.last_feed_message_at = None
        self.trade_count = 0
        self.version = 0
        self.condition = threading.Condition(self.lock)

    def _notify(self):
        """Called with self.lock held; wake open SSE clients."""
        self.version += 1
        self.condition.notify_all()

    def wait_for_version(self, current_version, timeout=15):
        with self.condition:
            if self.version == current_version:
                self.condition.wait_for(lambda: self.version != current_version, timeout=timeout)
            return self.version

    def set_status(self, status, error=None):
        with self.lock:
            changed = (self.status != status or self.error != error)
            self.status, self.error = status, error
            if changed:
                self._notify()

    def start(self):
        with self.lock:
            if self.started:
                return
            self.started = True
            self.status = "iniciando"
            self._notify()
        threading.Thread(target=self.run, name="alpaca-market-data-iex", daemon=True).start()

    def snapshot(self):
        with self.lock:
            return {
                "symbol": SYMBOL,
                "feed": FEED,
                "status": self.status,
                "error": self.error,
                "history_error": self.history_error,
                "candles": [dict(b) for b in self.bars[-MAX_BARS:]],
                "short_candles": [dict(b) for b in self.short_bars[-MAX_SHORT_BARS:]],
                "last_trade": dict(self.last_trade) if self.last_trade else None,
                "last_received_at": self.last_received_at,
                "last_feed_message_at": self.last_feed_message_at,
                "trade_count": self.trade_count,
                "version": self.version,
                "server_time": datetime.now(timezone.utc).isoformat(),
            }

    def insert_bar(self, bar):
        """Apply exchange minute bars/corrections; avoid rolling back a live candle."""
        with self.lock:
            self.last_feed_message_at = datetime.now(timezone.utc).isoformat()
            existing = next((i for i, b in enumerate(self.bars) if b["time"] == bar["time"]), None)
            if existing is not None:
                previous = self.bars[existing]
                if self.last_trade is not None:
                    current_minute = (_as_unix(self.last_trade["timestamp"]) // 60) * 60
                else:
                    current_minute = -1
                if bar["time"] == current_minute:
                    # Keep the latest trade as close until minute ends; historical
                    # or corrected bars may arrive out of order.
                    self.bars[existing] = {
                        "time": bar["time"], "open": previous["open"],
                        "high": max(previous["high"], bar["high"]),
                        "low": min(previous["low"], bar["low"]),
                        "close": previous["close"],
                        "volume": max(previous["volume"], bar["volume"]),
                    }
                else:
                    self.bars[existing] = bar
            else:
                self.bars.append(bar)
                self.bars.sort(key=lambda b: b["time"])
                self.bars = self.bars[-MAX_BARS:]
            self._notify()

    def on_trade(self, obj):
        if obj.get("S") != SYMBOL:
            return
        try:
            price = float(obj["p"])
            size = int(obj.get("s", 0))
            trade_at = obj["t"]
            minute = (_as_unix(trade_at) // 60) * 60
        except (KeyError, ValueError, TypeError, OverflowError):
            return
        with self.lock:
            received = datetime.now(timezone.utc).isoformat()
            self.trade_count += 1
            self.last_feed_message_at = received
            if self.last_trade and _as_unix(trade_at) < _as_unix(self.last_trade["timestamp"]):
                # Ignore out-of-order trades for the price display, preserving
                # the last known chronological trade.
                self._notify()
                return
            self.last_trade = {"price": price, "timestamp": trade_at, "size": size}
            self.last_received_at = received
            if self.bars and minute < self.bars[-1]["time"]:
                self._notify()
                return
            if self.bars and minute == self.bars[-1]["time"]:
                b = self.bars[-1]
                b["high"] = max(b["high"], price)
                b["low"] = min(b["low"], price)
                b["close"] = price
                b["volume"] += max(0, size)
            else:
                self.bars.append({"time": minute, "open": price, "high": price,
                                  "low": price, "close": price, "volume": max(0, size)})
                self.bars = self.bars[-MAX_BARS:]

            # Velas de 5 s: se construyen solo con operaciones IEX que llegan
            # mientras el programa está conectado. No inventar velas sin trades.
            bucket = (_as_unix(trade_at) // SHORT_SECONDS) * SHORT_SECONDS
            if not self.short_bars or bucket > self.short_bars[-1]["time"]:
                self.short_bars.append({"time": bucket, "open": price, "high": price,
                                        "low": price, "close": price, "volume": max(0, size)})
                self.short_bars = self.short_bars[-MAX_SHORT_BARS:]
            elif bucket == self.short_bars[-1]["time"]:
                b5 = self.short_bars[-1]
                b5["high"] = max(b5["high"], price)
                b5["low"] = min(b5["low"], price)
                b5["close"] = price
                b5["volume"] += max(0, size)
            self._notify()

    def history(self, key, secret):
        # The IEX endpoint returns actual IEX bars, consistent with the live stream.
        start = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        try:
            response = requests.get(
                HISTORY_URL,
                headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
                params={"timeframe": "1Min", "feed": FEED, "start": start,
                        "limit": 1000, "adjustment": "raw"},
                timeout=20,
            )
            if not response.ok:
                raise RuntimeError(f"HTTP {response.status_code} en historial IEX")
            items = [_bar(d) for d in response.json().get("bars", [])]
            with self.lock:
                # Don't overwrite bars that were already populated by a websocket trade.
                existing = {b["time"]: b for b in self.bars}
                existing.update({b["time"]: b for b in items if b["time"] not in existing})
                self.bars = sorted(existing.values(), key=lambda b: b["time"])[-MAX_BARS:]
                self._notify()
        except (requests.RequestException, ValueError, RuntimeError) as err:
            # Never include a URL, headers, request object, or secrets in error text.
            with self.lock:
                self.history_error = (f"No se pudo cargar el historial IEX ({type(err).__name__}). "
                                      "El flujo en vivo puede seguir funcionando.")
                self._notify()

    def run(self):
        try:
            key, secret = _credentials()
        except (OSError, ValueError) as err:
            self.set_status("error", str(err))
            return
        self.history(key, secret)
        while True:
            try:
                self.set_status("conectando")
                with connect(WEBSOCKET_URL, open_timeout=12, ping_interval=20,
                             ping_timeout=20, max_size=1048576) as ws:
                    ws.send(json.dumps({"action": "auth", "key": key, "secret": secret}))
                    authenticated = False
                    for payload in ws:
                        try:
                            messages = json.loads(payload)
                        except (ValueError, TypeError):
                            continue
                        if not isinstance(messages, list):
                            continue
                        for obj in messages:
                            if not isinstance(obj, dict):
                                continue
                            kind = obj.get("T")
                            if kind == "success" and obj.get("msg") == "authenticated":
                                authenticated = True
                                ws.send(json.dumps({"action": "subscribe", "trades": [SYMBOL],
                                                    "bars": [SYMBOL]}))
                            elif kind == "subscription" and authenticated:
                                if SYMBOL in obj.get("trades", []):
                                    self.set_status("conectado")
                                else:
                                    self.set_status("error", "Suscripcion a NVDA no confirmada.")
                            elif kind == "error":
                                code = obj.get("code")
                                # Avoid reflecting arbitrary remote strings into the browser.
                                if code in (402, 409):
                                    self.set_status("error", "Alpaca rechazo autenticacion o acceso al feed IEX.")
                                    return
                                if code == 406:
                                    self.set_status("error", "Ya hay otra conexion al flujo de datos Alpaca.")
                                    return
                                self.set_status("error", f"Alpaca devolvio error {code}.")
                            elif kind == "t":
                                self.on_trade(obj)
                            elif kind in ("b", "u") and obj.get("S") == SYMBOL:
                                try:
                                    self.insert_bar(_bar(obj))
                                except (KeyError, ValueError, TypeError, OverflowError):
                                    continue
            except Exception:
                # Do not expose exception text, which can contain connection details.
                self.set_status("reconectando", "Conexion interrumpida; se intentara reconectar.")
            time.sleep(5)


_feed = LiveFeed()


def register_live(app):
    @app.route("/live")
    def alpaca_live_page():
        return send_from_directory(app.static_folder, "live.html")

    @app.route("/api/alpaca/live", methods=["GET"])
    def alpaca_live_state():
        _feed.start()
        response = jsonify(_feed.snapshot())
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.route("/api/alpaca/events", methods=["GET"])
    def alpaca_live_events():
        """Notify the local UI whenever market data changes; no secrets in events."""
        _feed.start()

        def updates():
            version = -1
            while True:
                updated = _feed.wait_for_version(version, timeout=15)
                if updated != version:
                    version = updated
                    yield f"event: update\ndata: {version}\n\n"
                else:
                    yield ": keepalive\n\n"

        return Response(
            stream_with_context(updates()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache, no-transform",
                     "X-Accel-Buffering": "no",
                     "Connection": "keep-alive"},
        )
