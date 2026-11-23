"""Endpoint de diagnóstico del motor V5; no altera el REALTIME ni el UI."""
from __future__ import annotations
from datetime import datetime, timezone

from engine.estado_v5 import construir_estado_v5
from engine.planificacion_experimental import simular_reloj_de_hipotesis


def register_v5_diagnostics(app):
    @app.route("/api/v5/estado", methods=["GET"])
    def v5_estado():
        from flask import jsonify
        from alpaca_live import _feed
        market = _feed.snapshot()
        analysis = app.extensions["live_analysis"].snapshot()
        now = datetime.now(timezone.utc)
        value = construir_estado_v5(market, analysis, ahora_utc=now)
        value["reloj_experimental"] = simular_reloj_de_hipotesis(
            analysis, market, ahora_utc=now)
        response = jsonify(value)
        response.headers["Cache-Control"] = "no-store"
        return response
