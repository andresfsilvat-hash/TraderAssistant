"""Ensayos de la preparación y la cuenta atrás derivadas de datos causales."""
from datetime import datetime, timedelta, timezone
import unittest

from engine.planificacion_experimental import simular_reloj_de_hipotesis

T = datetime(2026, 11, 23, 15, 0, tzinfo=timezone.utc)
DETECTED = T - timedelta(seconds=40)


def analysis():
    return {"symbol": "NVDA", "status": "ready", "stale": False,
            "computed_at": DETECTED.isoformat(),
            "experimental_decision": {"evaluaciones": {
                "120": {"direccion": "SUBE"},
                "60": {"direccion": "ESPERAR"}}}}


def market(now):
    return {"symbol": "NVDA", "last_received_at": now.isoformat()}


def read(offset, **kwargs):
    now = T + timedelta(seconds=offset)
    return simular_reloj_de_hipotesis(
        analysis(), market(now), ahora_utc=now, **kwargs)


class PlanTests(unittest.TestCase):
    def test_programa_entrada_fija(self):
        for offset in (-30, -20, -10, -9):
            r = read(offset)
            self.assertEqual(r["entrada_utc"], T.isoformat())
            self.assertFalse(r["operativa_autorizada"])

    def test_es_prepararse(self):
        r = read(-20)
        self.assertEqual((r["estado"], r["segundos_para_entrada"]),
                         ("PREPARARSE", 20))

    def test_regresiva(self):
        for off, number in [(-10, 10), (-9, 9), (-1, 1)]:
            with self.subTest(off=off):
                r = read(off)
                self.assertEqual((r["estado"], r["segundos_para_entrada"]),
                                 ("CUENTA_REGRESIVA", number))

    def test_instante_de_entrada_solo_simulacion(self):
        r = read(0)
        self.assertEqual(r["estado"], "ENTRAR")
        self.assertFalse(r["operativa_autorizada"])
        self.assertEqual(r["vencimiento_hipotetico_utc"],
                         (T + timedelta(seconds=120)).isoformat())

    def test_fuera_de_ventana(self):
        self.assertEqual(read(2)["estado"], "VENTANA_CERRADA")

    def test_rechaza_dato_atrasado(self):
        now = T - timedelta(seconds=10)
        r = simular_reloj_de_hipotesis(
            analysis(), market(now - timedelta(seconds=4)), ahora_utc=now)
        self.assertEqual(r["estado"], "CANCELADA")

    def test_espera_si_no_hay_senal(self):
        self.assertEqual(read(-20, horizonte=60)["estado"], "ESPERAR")

    def test_30s_no_suficientes(self):
        self.assertEqual(read(-20, horizonte=30)["estado"], "ESPERAR")

    def test_no_extrapola_analisis_antiguo(self):
        r = read(100)
        self.assertEqual(r["estado"], "ESPERAR")

    def test_no_acepta_activo_incompatible(self):
        now = T - timedelta(seconds=10)
        m = market(now)
        m["symbol"] = "SPY"
        self.assertEqual(simular_reloj_de_hipotesis(analysis(), m,
                                                    ahora_utc=now)["estado"], "ESPERAR")


if __name__ == "__main__":
    unittest.main()
