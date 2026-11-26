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
        self.assertEqual(x["espera_entrada_segundos"], 10)
        self.assertEqual(x["inicio_vencimiento_utc"], x["entrada_programada_utc"])
        self.assertEqual(x["tiempo_vencimiento_segundos"], x["duracion_segundos"])
        self.assertEqual(x["vencimiento_utc"],
                         (T+timedelta(seconds=10+x["duracion_segundos"])).isoformat())
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

    def test_vencimiento_30_45_180_empieza_despues_del_conteo(self):
        for expiry_seconds in (30, 45, 180):
            with self.subTest(expiry_seconds=expiry_seconds):
                instance = NVDADemoService(
                    path=Path(self.tmp.name)/f"test_{expiry_seconds}.json")
                candidate = {"disponible": True, "vela_id": BAR, "direccion": "SUBE",
                             "duracion_segundos": expiry_seconds, "puntaje_concordancia": 63,
                             "evidencias": [], "peso_favor": 4, "peso_contra": 3}
                with patch("nvda_demo_v5.proponer_hipotesis", return_value=candidate):
                    first = instance.tick(market(), analysis(), now=T)
                    x = first["hipotesis_activa"]
                    self.assertEqual(first["segundos_para_entrada"], 10)
                    self.assertEqual(x["entrada_programada_utc"],
                                     (T+timedelta(seconds=10)).isoformat())
                    self.assertEqual(x["inicio_vencimiento_utc"],
                                     x["entrada_programada_utc"])
                    end = T+timedelta(seconds=10+expiry_seconds)
                    self.assertEqual(x["vencimiento_utc"], end.isoformat())
                    entry_time = T+timedelta(seconds=10)
                    entered = instance.tick(
                        market(entry_time, price=151.2), analysis(), now=entry_time)
                    self.assertEqual(entered["estado"], "EN_SEGUIMIENTO")
                    almost_end = end-timedelta(seconds=1)
                    before = instance.tick(
                        market(almost_end, price=151.4), analysis(), now=almost_end)
                    self.assertEqual(before["estado"], "EN_SEGUIMIENTO")
                    self.assertIsNone(before["hipotesis_activa"]["precio_salida"])
                    after = instance.tick(market(end, price=151.5), analysis(), now=end)
                    self.assertEqual(after["ultima_hipotesis"]["resultado"], "ACIERTO")
                    self.assertEqual(
                        after["estadisticas_por_duracion"][str(expiry_seconds)]["aciertos"], 1)

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

    def test_no_repite_alerta_30s_mientras_sigue_vencimiento_2min(self):
        """Caso reportado: 2min SUBE, sin cotización de entrada, nueva 30s SUBE."""
        first_candidate = {"disponible": True, "vela_id": BAR, "direccion": "SUBE",
                           "duracion_segundos": 120, "puntaje_concordancia": 80,
                           "evidencias": [], "peso_favor": 8, "peso_contra": 2}
        second_candidate = {"disponible": True, "vela_id": BAR + 60, "direccion": "SUBE",
                            "duracion_segundos": 30, "puntaje_concordancia": 51,
                            "evidencias": [], "peso_favor": 5, "peso_contra": 5}
        with patch("nvda_demo_v5.proponer_hipotesis", return_value=first_candidate):
            first = self.demo.tick(market(), analysis(), now=T)
        self.assertEqual(first["segundos_para_entrada"], 10)
        self.assertEqual(first["hipotesis_activa"]["duracion_segundos"], 120)
        original_id = first["hipotesis_activa"]["id"]
        original_expiry = T + timedelta(seconds=130)

        # El feed falla después del clic hipotético. Antes, el motor marcaba
        # NO_EVALUABLE y permitía otro aviso sobre la siguiente vela de 1m.
        failed_quote = T + timedelta(seconds=18)
        with patch("nvda_demo_v5.proponer_hipotesis", return_value=second_candidate):
            interim = self.demo.tick(
                market(failed_quote, quote_at=T, receipt_at=T),
                analysis(), now=failed_quote)
        self.assertEqual(interim["ultima_hipotesis"]["resultado"], "NO_EVALUABLE")
        self.assertIsNone(interim["hipotesis_activa"])
        self.assertEqual(interim["estado"], "ESPERANDO_VENCIMIENTO")
        self.assertIsNone(interim["segundos_para_entrada"])
        self.assertEqual(interim["bloqueo_vencimiento"]["direccion"], "SUBE")
        self.assertEqual(interim["bloqueo_vencimiento"]["duracion_segundos"], 120)
        self.assertEqual(interim["bloqueo_vencimiento"]["hasta_utc"], original_expiry.isoformat())

        for seconds in (30, 60, 90, 119, 129, 130, 134):
            at = T + timedelta(seconds=seconds)
            with self.subTest(at=at), patch(
                    "nvda_demo_v5.proponer_hipotesis", return_value=second_candidate):
                current = self.demo.tick(market(at), analysis(), now=at)
                self.assertIsNone(current["hipotesis_activa"])
                self.assertIsNone(current["segundos_para_entrada"])
                self.assertEqual(current["estadisticas"]["total_hipotesis"], 1)
                self.assertEqual(current["ultima_hipotesis"]["id"], original_id)
                self.assertIsNotNone(current["bloqueo_vencimiento"])

        # Solo después de vencer y dejar 5 segundos de revisión puede abrirse
        # la segunda hipótesis, con nueva cuenta completa de 10 segundos.
        allowed = T + timedelta(seconds=135)
        with patch("nvda_demo_v5.proponer_hipotesis", return_value=second_candidate):
            next_signal = self.demo.tick(market(allowed), analysis(), now=allowed)
        self.assertEqual(next_signal["segundos_para_entrada"], 10)
        self.assertEqual(next_signal["hipotesis_activa"]["duracion_segundos"], 30)
        self.assertEqual(next_signal["estadisticas"]["total_hipotesis"], 2)
        self.assertNotEqual(next_signal["hipotesis_activa"]["id"], original_id)

    def test_reinicio_no_levanta_bloqueo_de_vencimiento_original(self):
        first_candidate = {"disponible": True, "vela_id": BAR, "direccion": "BAJA",
                           "duracion_segundos": 120, "puntaje_concordancia": 76,
                           "evidencias": [], "peso_favor": 7, "peso_contra": 3}
        second_candidate = dict(first_candidate, vela_id=BAR+60, duracion_segundos=30)
        with patch("nvda_demo_v5.proponer_hipotesis", return_value=first_candidate):
            self.demo.tick(market(), analysis(), now=T)
        resumed = NVDADemoService(path=self.path)
        t_plus_60 = T + timedelta(seconds=60)
        with patch("nvda_demo_v5.proponer_hipotesis", return_value=second_candidate):
            result = resumed.tick(market(t_plus_60), analysis(), now=t_plus_60)
        self.assertEqual(result["estado"], "ESPERANDO_VENCIMIENTO")
        self.assertEqual(result["estadisticas"]["total_hipotesis"], 1)
        self.assertIsNone(result["hipotesis_activa"])
        self.assertEqual(result["ultima_hipotesis"]["resultado"], "NO_EVALUABLE")
        self.assertEqual(result["bloqueo_vencimiento"]["duracion_segundos"], 120)
        self.assertFalse(result["operativa_autorizada"])

    def test_resultado_temprano_no_libera_antes_del_vencimiento(self):
        candidate = {"disponible": True, "vela_id": BAR, "direccion": "SUBE",
                     "duracion_segundos": 120, "puntaje_concordancia": 80,
                     "evidencias": [], "peso_favor": 8, "peso_contra": 2}
        new_candidate = dict(candidate, vela_id=BAR+60, duracion_segundos=30)
        with patch("nvda_demo_v5.proponer_hipotesis", return_value=candidate):
            self.demo.tick(market(), analysis(), now=T)
        entered = T + timedelta(seconds=10)
        self.demo.tick(market(entered), analysis(), now=entered)
        with patch("nvda_demo_v5.proponer_hipotesis", return_value=new_candidate):
            for seconds in (40, 80, 120):
                at = T + timedelta(seconds=seconds)
                result = self.demo.tick(market(at), analysis(), now=at)
                self.assertEqual(result["estado"], "EN_SEGUIMIENTO")
                self.assertEqual(result["hipotesis_activa"]["duracion_segundos"], 120)
                self.assertEqual(result["estadisticas"]["total_hipotesis"], 1)
        expired = T + timedelta(seconds=130)
        with patch("nvda_demo_v5.proponer_hipotesis", return_value=new_candidate):
            result = self.demo.tick(market(expired, price=151.8), analysis(), now=expired)
        self.assertEqual(result["ultima_hipotesis"]["resultado"], "ACIERTO")
        self.assertEqual(result["estado"], "REVISION_RESULTADO")
        self.assertIsNone(result["hipotesis_activa"])
        self.assertEqual(result["estadisticas"]["total_hipotesis"], 1)

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
                     "v5demo-expiry-countdown", "Vencimiento desde la entrada",
                     "Cuenta previa para entrar", "SIN NUEVA ENTRADA",
                     "bloqueo_vencimiento", "/api/v5/demo",
                     "v5demo-voice", "ENTRADA SIMULADA AHORA"):
            self.assertIn(text, ui)
        self.assertEqual(ui.count("</script>"), 2)
        self.assertEqual(ui.count("setInterval(fetchSimulation,2000);"), 1)


if __name__ == "__main__":
    unittest.main()
