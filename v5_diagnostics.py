"""Endpoint de diagnóstico del motor V5; no altera el REALTIME ni el UI."""
from __future__ import annotations
from datetime import datetime, timezone

from engine.estado_v5 import construir_estado_v5


def register_v5_diagnostics(app):
    @app.route("/api/v5/estado", methods=["GET"])
    def v5_estado():
        from flask import jsonify
        from alpaca_live import _feed
        market = _feed.snapshot()
        analysis = app.extensions["live_analysis"].snapshot()
        value = construir_estado_v5(market, analysis, ahora_utc=datetime.now(timezone.utc))
        response = jsonify(value)
        response.headers["Cache-Control"] = "no-store"
        return response
