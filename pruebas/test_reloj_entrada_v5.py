"""Pruebas sin conexiones externas de la máquina de estados V5."""
from datetime import datetime, timedelta, timezone
import unittest
from engine.reloj_entrada import EstadoReloj, HipotesisEntrada, evaluar_reloj

T = datetime(2026, 11, 23, 15, 0, tzinfo=timezone.utc)


class RelojEntradaTests(unittest.TestCase):
    def plan(self, *, validada=True, duracion=120, direccion="SUBE"):
        return HipotesisEntrada(direccion, duracion, T + timedelta(seconds=45),
                               T, validada=validada)

    def estado(self, n, **kw):
        now = T + timedelta(seconds=n)
        return evaluar_reloj(self.plan(), ahora_utc=now, ultimo_dato_utc=now, **kw)

    def test_sin_hipotesis(self):
        r = evaluar_reloj(None, ahora_utc=T)
        self.assertEqual(r.estado, EstadoReloj.ESPERAR)
        self.assertIsNone(r.segundos_para_entrada)

    def test_no_validada_no_activar_reloj(self):
        r = evaluar_reloj(self.plan(validada=False), ahora_utc=T, ultimo_dato_utc=T)
        self.assertEqual(r.estado, EstadoReloj.ESPERAR)
        self.assertFalse(r.operativa_autorizada)

    def test_espera_temprana(self):
        r = self.estado(0)
        self.assertEqual((r.estado, r.segundos_para_entrada), (EstadoReloj.ESPERAR, 45))

    def test_prepararse(self):
        r = self.estado(15)
        self.assertEqual((r.estado, r.segundos_para_entrada), (EstadoReloj.PREPARARSE, 30))

    def test_regresiva_10_9_8(self):
        for advance, expected in [(35, 10), (36, 9), (37, 8), (44, 1)]:
            with self.subTest(advance=advance):
                r = self.estado(advance)
                self.assertEqual((r.estado, r.segundos_para_entrada),
                                 (EstadoReloj.CUENTA_REGRESIVA, expected))

    def test_entrar_instante_hipotetico(self):
        r = self.estado(45)
        self.assertEqual((r.estado, r.segundos_para_entrada), (EstadoReloj.ENTRAR, 0))
        self.assertFalse(r.operativa_autorizada)

    def test_ventana_cerrada(self):
        self.assertEqual(self.estado(47).estado, EstadoReloj.VENTANA_CERRADA)

    def test_cancelacion_por_dato_viejo(self):
        r = evaluar_reloj(self.plan(), ahora_utc=T + timedelta(seconds=40),
                          ultimo_dato_utc=T + timedelta(seconds=37))
        self.assertEqual(r.estado, EstadoReloj.CANCELADA)

    def test_cancelacion_por_falta_dato(self):
        self.assertEqual(evaluar_reloj(self.plan(), ahora_utc=T).estado,
                         EstadoReloj.CANCELADA)

    def test_cancelacion_por_reloj_futuro(self):
        r = evaluar_reloj(self.plan(), ahora_utc=T + timedelta(seconds=40),
                          ultimo_dato_utc=T + timedelta(seconds=42))
        self.assertEqual(r.estado, EstadoReloj.CANCELADA)

    def test_horizontes(self):
        for duration in (30, 60, 120, 300, 600):
            with self.subTest(duration=duration):
                self.assertEqual(self.plan(duracion=duration).duracion_segundos, duration)

    def test_horizonte_invalido(self):
        with self.assertRaises(ValueError):
            self.plan(duracion=15)

    def test_direccion_invalida(self):
        with self.assertRaises(ValueError):
            self.plan(direccion="COMPRAR")

    def test_sin_zona_horaria(self):
        with self.assertRaises(ValueError):
            HipotesisEntrada("SUBE", 60, datetime(2026, 1, 1), T)

    def test_configuracion_invalida(self):
        with self.assertRaises(ValueError):
            self.estado(0, preparacion_segundos=5, cuenta_regresiva_segundos=10)

    def test_lectura_conserva_direccion_y_duracion(self):
        r = self.estado(37)
        self.assertEqual((r.direccion, r.duracion_segundos), ("SUBE", 120))


if __name__ == "__main__":
    unittest.main()
