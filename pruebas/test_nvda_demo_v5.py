"""Pruebas de demo NVIDIA V5: 10s, señal visible, fuente IEX, registro y resultados."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import re
import shutil
import subprocess
import unittest

from flask import Flask
from nvda_demo_v5 import (NVDADemoService, proponer_hipotesis,
                          register_nvda_demo_v5)

T = datetime(2026, 11, 24, 15, 0, 20, tzinfo=timezone.utc)
BAR = int((T-timedelta(seconds=80)).timestamp())


def market(now=T, *, price=151.2, quote_at=None, receipt_at=None, symbol="NVDA",
           is_open=True, source="alpaca", status="conectado"):
    quote_at = quote_at if quote_at is not None else now
    receipt_at = receipt_at if receipt_at is not None else now
    return {
        "symbol": symbol, "status": status,
        "market_clock": {"source": source, "is_open": is_open,
                         "checked_at": now.isoformat()},
        "candles": [{"time": BAR, "open": 150, "high": 152,
                     "low": 149, "close": 151.2, "volume": 3000,
                     "provisional": False}],
        "last_quote": {"bid": price - .01, "ask": price + .01,
                       "timestamp": quote_at.isoformat()},
        "last_quote_received_at": receipt_at.isoformat()}


def analysis():
    return {"symbol": "NVDA", "status": "ready", "stale": False,
            "last_candle_time": datetime.fromtimestamp(BAR, timezone.utc).isoformat(),
            "values": {"close": 151.2, "sma20_1m": 150.1,
                       "macd_histogram": .08, "return_3m_percent": .35,
                       "rsi_14": 60.0},
            "context": {"1h": {"status": "sufficient", "trend": "Alcista"}}}


class DemoNVDAEngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/"demo.json"
        self.demo = NVDADemoService(path=self.path)

    def test_propose_signal_even_when_conservative_waits(self):
        a = analysis()
        a["experimental_decision"] = {"evaluaciones": {"60": {"direccion": "ESPERAR"}}}
        out = proponer_hipotesis(market(), a, ahora_utc=T)
        self.assertTrue(out["disponible"])
        self.assertEqual(out["direccion"], "SUBE")
        self.assertGreaterEqual(out["puntaje_concordancia"], 50)
        self.assertEqual(out["duracion_segundos"], 600)
        self.assertNotIn("probabilidad", out)

    def test_10s_frozen_schedule_and_no_duplicate_from_poll(self):
        first = self.demo.tick(market(), analysis(), now=T)
        x = first["hipotesis_activa"]
        self.assertEqual(first["estado"], "CUENTA_REGRESIVA")
        self.assertEqual(first["segundos_para_entrada"], 10)
        self.assertEqual(x["direccion"], "SUBE")
        self.assertEqual(x["entrada_programada_utc"], (T+timedelta(seconds=10)).isoformat())
        self.assertFalse(first["operativa_autorizada"])
        for i in (1, 2, 5, 9):
            out = self.demo.tick(market(T+timedelta(seconds=i)), analysis(),
                                 now=T+timedelta(seconds=i))
            self.assertEqual(out["segundos_para_entrada"], 10-i)
            self.assertEqual(out["hipotesis_activa"]["id"], x["id"])
            self.assertEqual(out["estadisticas"]["total_hipotesis"], 1)
        self.assertTrue(self.path.is_file())

    def test_entry_exit_iex_and_observed_percentage(self):
        start = self.demo.tick(market(), analysis(), now=T)
        self.assertEqual(start["estadisticas"]["tasa_acierto_pct"], None)
        entry = T+timedelta(seconds=10)
        a = self.demo.tick(market(entry, price=151.2), analysis(), now=entry)
        self.assertEqual(a["estado"], "EN_SEGUIMIENTO")
        self.assertEqual(a["hipotesis_activa"]["precio_entrada"], 151.2)
        self.assertEqual(a["hipotesis_activa"]["fuente_entrada"], "IEX_MID_BID_ASK_PROXY")
        self.assertIsNone(a["hipotesis_activa"]["precio_salida"])
        due = entry+timedelta(seconds=a["hipotesis_activa"]["duracion_segundos"])
        final = self.demo.tick(market(due, price=151.5), analysis(), now=due)
        self.assertIsNone(final["hipotesis_activa"])
        self.assertEqual(final["ultima_hipotesis"]["resultado"], "ACIERTO")
        self.assertEqual(final["estadisticas"]["tasa_acierto_pct"], 100)
        self.assertEqual(final["estadisticas"]["aciertos"], 1)
        self.assertEqual(final["estadisticas_por_duracion"]["600"]["aciertos"], 1)
        self.assertEqual(final["estadisticas_por_duracion"]["600"]["tasa_acierto_pct"], 100)
        self.assertEqual(final["estadisticas_por_duracion"]["30"]["tasa_acierto_pct"], None)
        self.assertIn("bid_entrada", final["ultima_hipotesis"])
        self.assertIn("ask_salida", final["ultima_hipotesis"])
        self.assertIn("NO es operación IQ Option", final["ultima_hipotesis"]["motivo_resultado"])

    def test_fallo_baja_y_no_evaluable_when_missing_quote(self):
        with patch("nvda_demo_v5.proponer_hipotesis", return_value={
            "disponible": True, "vela_id": BAR, "direccion": "BAJA",
            "duracion_segundos": 60, "puntaje_concordancia": 55, "evidencias": [],
            "peso_favor": 5, "peso_contra": 4}):
            self.demo.tick(market(), analysis(), now=T)
            enter = T+timedelta(seconds=10)
            self.demo.tick(market(enter, price=150), analysis(), now=enter)
            due = enter+timedelta(seconds=60)
            result = self.demo.tick(market(due, price=151), analysis(), now=due)
        self.assertEqual(result["ultima_hipotesis"]["resultado"], "FALLO")
        self.assertEqual(result["estadisticas"]["tasa_acierto_pct"], 0)

        second = NVDADemoService(path=Path(self.tmp.name)/"second.json")
        with patch("nvda_demo_v5.proponer_hipotesis", return_value={
            "disponible": True, "vela_id": BAR, "direccion": "SUBE",
            "duracion_segundos": 60, "puntaje_concordancia": 55, "evidencias": [],
            "peso_favor": 5, "peso_contra": 4}):
            second.tick(market(), analysis(), now=T)
            late = T+timedelta(seconds=18)
            result = second.tick(market(late, quote_at=T), analysis(), now=late)
        self.assertEqual(result["ultima_hipotesis"]["resultado"], "NO_EVALUABLE")
        self.assertIsNone(result["estadisticas"]["tasa_acierto_pct"])

    def test_no_synthetic_market_or_historical_signal(self):
        self.assertFalse(proponer_hipotesis(market(is_open=False), analysis(),
                                            ahora_utc=T)["disponible"])
        self.assertFalse(proponer_hipotesis(market(status="reconectando"), analysis(),
                                            ahora_utc=T)["disponible"])
        self.assertFalse(proponer_hipotesis(market(symbol="SPY"), analysis(),
                                            ahora_utc=T)["disponible"])
        stale = market(quote_at=T-timedelta(seconds=20))
        self.assertFalse(proponer_hipotesis(stale, analysis(), ahora_utc=T)["disponible"])
        bad = analysis()
        bad["status"] = "insufficient"
        self.assertFalse(proponer_hipotesis(market(), bad, ahora_utc=T)["disponible"])
        bad = analysis()
        bad["last_candle_time"] = (T-timedelta(minutes=20)).isoformat()
        self.assertFalse(proponer_hipotesis(market(), bad, ahora_utc=T)["disponible"])

    def test_symbol_switch_cancels_even_after_entry(self):
        self.demo.tick(market(), analysis(), now=T)
        entry = T+timedelta(seconds=10)
        self.demo.tick(market(entry), analysis(), now=entry)
        changed = self.demo.tick(market(entry+timedelta(seconds=1), symbol="SPY"),
                                 analysis(), now=entry+timedelta(seconds=1))
        self.assertEqual(changed["ultima_hipotesis"]["resultado"], "NO_EVALUABLE")
        self.assertIsNone(changed["hipotesis_activa"])

    def test_reboot_never_fabricates_missed_outcome(self):
        self.demo.tick(market(), analysis(), now=T)
        reloaded = NVDADemoService(path=self.path)
        self.assertEqual(reloaded.entries[-1]["resultado"], "NO_EVALUABLE")
        next_poll = reloaded.tick(market(), analysis(), now=T)
        self.assertEqual(next_poll["estadisticas"]["total_hipotesis"], 1)
        self.assertIsNone(next_poll["hipotesis_activa"])

    def test_http_endpoint_no_orders_and_with_schema(self):
        class Mock:
            def __init__(self, value):
                self.value = value
            def snapshot(self):
                return self.value
        app = Flask(__name__)
        app.extensions["live_analysis"] = Mock(analysis())
        demo = NVDADemoService(path=Path(self.tmp.name)/"http.json", when=lambda: T)
        register_nvda_demo_v5(app, service=demo, feed=Mock(market()))
        response = app.test_client().get("/api/v5/demo")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.json["hipotesis_activa"]["direccion"], "SUBE")
        self.assertEqual(response.json["segundos_para_entrada"], 10)
        self.assertFalse(response.json["operativa_autorizada"])
        self.assertEqual(app.test_client().post("/api/v5/demo").status_code, 405)

    def test_ui_inline_javascript_parses(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js no instalado en este entorno.")
        html = (Path(__file__).resolve().parents[1]/"ui"/"live.html").read_text(encoding="utf-8")
        scripts = [body for body in re.findall(
            r"<script[^>]*>(.*?)</script>", html, flags=re.DOTALL) if body.strip()]
        self.assertEqual(len(scripts), 1)
        code_path = Path(self.tmp.name)/"v5_ui_check.js"
        code_path.write_text(scripts[0], encoding="utf-8")
        checked = subprocess.run([node, "--check", str(code_path)],
                                 capture_output=True, text=True, timeout=10)
        self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_ui_has_v5_countdown_voice_and_results(self):
        ui = (Path(__file__).resolve().parents[1]/"ui"/"live.html").read_text(encoding="utf-8")
        for text in ("v5demo-direction", "v5demo-countdown", "v5demo-accuracy",
                     "/api/v5/demo", "v5demo-voice", "ENTRADA SIMULADA AHORA"):
            self.assertIn(text, ui)
        self.assertEqual(ui.count("</script>"), 2)
        self.assertEqual(ui.count("setInterval(fetchSimulation,2000);"), 1)


if __name__ == "__main__":
    unittest.main()
