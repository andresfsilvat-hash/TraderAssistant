"""Pruebas HTTP reales del endpoint V5, con fuente Alpaca simulada."""
import sys
import types
import unittest
from unittest.mock import patch
from datetime import datetime, timezone

from flask import Flask

from v5_diagnostics import register_v5_diagnostics


class FakeFeed:
    def snapshot(self):
        return {"symbol": "NVDA", "feed": "iex", "last_received_at":
                datetime.now(timezone.utc).isoformat(), "last_lag_ms": 42}


class FakeAnalysis:
    def snapshot(self):
        return {"symbol": "NVDA", "status": "ready", "stale": False,
                "experimental_decision": {"evaluaciones": {
                    "120": {"direccion": "SUBE", "justificacion": "Hipótesis no validada"}}}}


class ApiV5Tests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.testing = True
        app.extensions["live_analysis"] = FakeAnalysis()
        module = types.ModuleType("alpaca_live")
        module._feed = FakeFeed()
        self.patch = patch.dict(sys.modules, {"alpaca_live": module})
        self.patch.start()
        self.addCleanup(self.patch.stop)
        register_v5_diagnostics(app)
        self.client = app.test_client()

    def test_http_json_sin_entradas_autorizadas(self):
        response = self.client.get("/api/v5/estado")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        info = response.get_json()
        self.assertEqual(info["estado"], "ESPERAR")
        self.assertFalse(info["operativa_autorizada"])
        self.assertIsNone(info["entrada_utc"])
        self.assertIn("reloj_experimental", info)
        self.assertFalse(info["reloj_experimental"]["operativa_autorizada"])
        self.assertEqual(info["hipotesis_experimentales"][0]["direccion_experimental"], "SUBE")

    def test_no_acepta_post(self):
        self.assertEqual(self.client.post("/api/v5/estado").status_code, 405)

    def test_sin_ordenes(self):
        data = self.client.get("/api/v5/estado").get_json()
        self.assertNotIn("orden", data)
        self.assertIsNone(data["segundos_para_entrada"])


if __name__ == "__main__":
    unittest.main()
