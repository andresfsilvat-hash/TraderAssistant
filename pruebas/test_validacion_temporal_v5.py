"""Pruebas auditables de resultados por vencimiento fijo."""
from datetime import datetime, timedelta, timezone
import unittest

from engine.validacion_temporal import Observacion, resumen_fuera_muestra

BASE = datetime(2026, 11, 23, 15, 0, tzinfo=timezone.utc)


def obs(n, *, horizon=30, direction="SUBE", entry=100.0, exit=101.0,
        payout=0.8, source="IEX"):
    start = BASE + timedelta(minutes=n)
    return Observacion(start, start,
                       start + timedelta(seconds=horizon), horizon,
                       direction, entry, exit, source, payout)


class ValidacionTests(unittest.TestCase):
    def test_acierto_fallo_empate(self):
        values = [obs(0), obs(1, exit=99), obs(2, exit=100)]
        result = resumen_fuera_muestra(values, corte_utc=BASE)
        h = result["horizontes"]["30"]
        self.assertEqual((h["aciertos"], h["fallos"], h["empates"]), (1, 1, 1))
        self.assertEqual(h["tasa_acierto"], .5)
        self.assertAlmostEqual(h["utilidad_neta_unidades"], -.2)
        self.assertFalse(result["operativa_autorizada"])

    def test_corte_sin_filtracion_futura(self):
        values = [obs(-2), obs(-1), obs(0), obs(1)]
        result = resumen_fuera_muestra(values, corte_utc=BASE)
        h = result["horizontes"]["30"]
        self.assertEqual(h["entrenamiento"], 2)
        self.assertEqual(h["prueba"], 2)

    def test_fraccion_cruza_corte_no_contamina(self):
        start = BASE - timedelta(seconds=10)
        item = Observacion(start - timedelta(seconds=1), start,
                           start + timedelta(seconds=30), 30,
                           "SUBE", 100, 101, "IEX")
        h = resumen_fuera_muestra([item], corte_utc=BASE)["horizontes"]["30"]
        self.assertEqual(h["excluidos_frontera"], 1)

    def test_rechazo_duracion_inexacta(self):
        with self.assertRaises(ValueError):
            Observacion(BASE, BASE, BASE + timedelta(seconds=60), 30,
                        "SUBE", 100, 101, "IEX")

    def test_no_inventar_payout(self):
        h = resumen_fuera_muestra([obs(0, payout=None)], corte_utc=BASE)["horizontes"]["30"]
        self.assertIsNone(h["utilidad_neta_unidades"])

    def test_duplicados_bloqueados(self):
        with self.assertRaises(ValueError):
            resumen_fuera_muestra([obs(0), obs(0)], corte_utc=BASE)

    def test_pocos_datos_no_validan(self):
        h = resumen_fuera_muestra([obs(0)], corte_utc=BASE)["horizontes"]["30"]
        self.assertFalse(h["evidencia_suficiente"])

    def test_rechazo_precio_invalido(self):
        with self.assertRaises(ValueError):
            obs(0, entry=-1)

    def test_rechazo_entrada_anterior_a_senal(self):
        with self.assertRaises(ValueError):
            Observacion(BASE + timedelta(seconds=1), BASE,
                        BASE + timedelta(seconds=30), 30, "BAJA", 100, 99, "IEX")

    def test_direccion_baja(self):
        h = resumen_fuera_muestra([obs(0, direction="BAJA", exit=99)],
                                  corte_utc=BASE)["horizontes"]["30"]
        self.assertEqual(h["aciertos"], 1)

    def test_wilson_menor_que_tasa(self):
        h = resumen_fuera_muestra([obs(i) for i in range(30)],
                                  corte_utc=BASE)["horizontes"]["30"]
        self.assertEqual(h["tasa_acierto"], 1.0)
        self.assertLess(h["limite_inferior_wilson_95"], 1.0)
        self.assertTrue(h["evidencia_suficiente"])

    def test_filtro_por_fuente(self):
        h = resumen_fuera_muestra([obs(0), obs(1, source="IQ_OPTION")],
                                  corte_utc=BASE,
                                  incluir_fuentes=("IQ_OPTION",))["horizontes"]["30"]
        self.assertEqual(h["prueba"], 1)


if __name__ == "__main__":
    unittest.main()
