"""Pruebas de seguridad, causalidad y reloj experimental cripto V5 (sin red)."""
from datetime import datetime, timedelta, timezone
import math
import unittest
from unittest.mock import patch

from flask import Flask
import crypto_live
from engine.crypto_observacion_v5 import analizar_crypto, _reloj

T = datetime(2026, 11, 24, 16, 0, 0, tzinfo=timezone.utc)


def sample_market(*, now=T, symbol="BTC/USD"):
    bars = []
    for i in range(110):
        start = int((T-timedelta(minutes=110-i)).timestamp())
        price = 100 + .02*i + .3*math.sin(i*.6)
        bars.append({"time": start, "open": price-.02, "high": price+.05,
                     "low": price-.05, "close": price, "volume": 10,
                     "provisional": False})
    return {"source": "alpaca_crypto", "status": "conectado", "feed": "crypto/us",
            "symbol": symbol, "candles": bars,
            "last_feed_message_at": (now-timedelta(seconds=1)).isoformat()}


class CryptoObservacionV5Tests(unittest.TestCase):
    def test_hipotesis_siempre_no_autorizada(self):
        out = analizar_crypto(sample_market(), ahora_utc=T)
        self.assertTrue(out["calidad"]["apta"])
        self.assertFalse(out["operativa_autorizada"])
        self.assertIsNone(out["probabilidad_acierto"])
        self.assertEqual(set(out["evaluaciones"]), {"60", "120", "300", "600"})
        self.assertEqual(out["evaluaciones"]["120"]["direccion"], "SUBE")
        self.assertEqual(out["reloj_experimental"]["entrada_utc"],
                         (T+timedelta(minutes=1)).isoformat())
        self.assertEqual(out["reloj_experimental"]["duracion_segundos"], 120)
        self.assertFalse(out["reloj_experimental"]["operativa_autorizada"])

    def test_reloj_estable_y_cuenta_atras(self):
        data = sample_market()
        start = analizar_crypto(data, ahora_utc=T)
        soon = analizar_crypto(sample_market(now=T+timedelta(seconds=35)),
                               ahora_utc=T+timedelta(seconds=35))
        count = analizar_crypto(sample_market(now=T+timedelta(seconds=52)),
                                ahora_utc=T+timedelta(seconds=52))
        self.assertEqual(start["reloj_experimental"]["entrada_utc"],
                         count["reloj_experimental"]["entrada_utc"])
        self.assertEqual(soon["estado"], "PREPARARSE")
        self.assertEqual(count["estado"], "CUENTA_REGRESIVA")
        self.assertEqual(count["reloj_experimental"]["segundos_para_entrada"], 8)

    def test_bloquea_feed_obsoleto(self):
        data = sample_market()
        data["last_feed_message_at"] = (T-timedelta(seconds=20)).isoformat()
        x = analizar_crypto(data, ahora_utc=T)
        self.assertFalse(x["calidad"]["apta"])
        self.assertEqual(x["estado"], "ESPERAR")
        self.assertEqual(x["evaluaciones"], {})

    def test_no_utiliza_velas_futuras(self):
        data = sample_market()
        extra = dict(data["candles"][-1])
        extra["time"] = int((T+timedelta(minutes=1)).timestamp())
        extra["close"] = 999999
        extra["high"] = 999999
        data["candles"].append(extra)
        x = analizar_crypto(data, ahora_utc=T)
        self.assertTrue(x["calidad"]["apta"])
        self.assertLess(x["indicadores"]["close"], 1000)

    def test_rechaza_huecos_del_historial(self):
        data = sample_market()
        del data["candles"][-12]
        x = analizar_crypto(data, ahora_utc=T)
        self.assertFalse(x["calidad"]["apta"])
        self.assertIn("huecos", x["motivo"])

    def test_cero_volumen_no_confirma_precio_negociado(self):
        data = sample_market()
        for bar in data["candles"][-12:]:
            bar["volume"] = 0
        x = analizar_crypto(data, ahora_utc=T)
        self.assertFalse(x["calidad"]["apta"])
        self.assertIn("volumen", x["motivo"])
        self.assertEqual(x["evaluaciones"], {})

    def test_nunca_producir_senal_con_origen_incorrecto(self):
        data = sample_market()
        data["source"] = "iex"
        x = analizar_crypto(data, ahora_utc=T)
        self.assertFalse(x["calidad"]["apta"])
        self.assertEqual(x["reloj_experimental"]["estado"], "ESPERAR")

    def test_senal_solo_con_velas_cerradas(self):
        data = sample_market()
        data["candles"][-1]["provisional"] = True
        x = analizar_crypto(data, ahora_utc=T)
        self.assertFalse(x["calidad"]["apta"])  # gap en últimos 40
        self.assertIn("huecos", x["motivo"])

    def test_bloquea_saltos_de_precio_anomalos(self):
        data = sample_market()
        bad = data["candles"][-1]
        bad["open"] *= 1.5
        bad["high"] *= 1.5
        bad["low"] *= 1.5
        bad["close"] *= 1.5
        x = analizar_crypto(data, ahora_utc=T)
        self.assertFalse(x["calidad"]["apta"])
        self.assertIn("12%", x["motivo"])

    def test_sin_zona_horaria_se_rechaza(self):
        with self.assertRaises(ValueError):
            analizar_crypto(sample_market(), ahora_utc=datetime(2026, 11, 24, 16, 0))

    def test_endpoint_http_sin_arrancar_ordenes(self):
        app = Flask(__name__)
        app.testing = True
        crypto_live.register_crypto_live(app)
        with patch.object(crypto_live._feed, "start"), \
             patch.object(crypto_live._feed, "snapshot", return_value=sample_market()):
            response = app.test_client().get("/api/crypto/analisis")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertFalse(response.json["operativa_autorizada"])
        self.assertNotIn("orden", response.json)
        self.assertIsNone(response.json["probabilidad_acierto"])
        self.assertEqual(app.test_client().post("/api/crypto/analisis").status_code, 405)


if __name__ == "__main__":
    unittest.main()
