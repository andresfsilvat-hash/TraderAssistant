"""Protecciones causales para datos indicativos de 5 segundos."""
from datetime import datetime, timezone, timedelta
import unittest
from engine.micro_30s import analizar_micro_30s

T = datetime(2026, 11, 23, 15, 2, tzinfo=timezone.utc)


def velas(subida=True):
    start = int(T.timestamp()) - 120
    return [{"time": start + i*5, "close": 100 + (i * .01 if subida else -i * .01),
             "volume": 200 if i >= 18 else 100} for i in range(24)]


class MicroTests(unittest.TestCase):
    def test_subida_observada(self):
        r = analizar_micro_30s(velas(), ahora_utc=T)
        self.assertEqual(r["direccion_experimental"], "SUBE")
        self.assertFalse(r["operativa_autorizada"])

    def test_bajada_observada(self):
        r = analizar_micro_30s(velas(False), ahora_utc=T)
        self.assertEqual(r["direccion_experimental"], "BAJA")

    def test_hueco_temporal(self):
        bars = velas()
        bars[12]["time"] += 2
        self.assertEqual(analizar_micro_30s(bars, ahora_utc=T)["estado"], "ESPERAR")

    def test_sin_suficientes_barras(self):
        self.assertEqual(analizar_micro_30s(velas()[:8], ahora_utc=T)["estado"], "ESPERAR")

    def test_rechaza_caché(self):
        bars = velas()
        bars[0]["origin"] = "cache"
        self.assertEqual(analizar_micro_30s(bars, ahora_utc=T)["estado"], "ESPERAR")

    def test_rechaza_vela_abierta(self):
        self.assertEqual(analizar_micro_30s(velas(), ahora_utc=T-timedelta(seconds=1))["estado"], "ESPERAR")

    def test_rechaza_dato_antiguo(self):
        self.assertEqual(analizar_micro_30s(velas(), ahora_utc=T+timedelta(seconds=6))["estado"], "ESPERAR")

    def test_bloquea_bajo_volumen(self):
        bars = velas()
        for row in bars:
            row["volume"] = 100
        self.assertIsNone(analizar_micro_30s(bars, ahora_utc=T)["direccion_experimental"])

    def test_bloquea_sin_reloj(self):
        with self.assertRaises(ValueError):
            analizar_micro_30s(velas(), ahora_utc=datetime(2026, 11, 23))

    def test_bloquea_cero_volumen(self):
        bars = velas()
        bars[4]["volume"] = 0
        self.assertEqual(analizar_micro_30s(bars, ahora_utc=T)["estado"], "ESPERAR")


if __name__ == "__main__":
    unittest.main()
