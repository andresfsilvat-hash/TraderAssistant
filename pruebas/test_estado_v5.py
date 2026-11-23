"""Pruebas de abstención segura para el estado agregado V5."""
from datetime import datetime, timedelta, timezone
import unittest

from engine.estado_v5 import construir_estado_v5

T = datetime(2026, 11, 23, 15, 0, tzinfo=timezone.utc)


def market(when=T):
    return {"symbol": "NVDA", "feed": "iex", "last_received_at": when.isoformat(),
            "last_lag_ms": 120}


def analysis():
    return {"symbol": "NVDA", "status": "ready", "stale": False,
            "experimental_decision": {"evaluaciones": {
                "60": {"direccion": "ESPERAR"},
                "120": {"direccion": "SUBE", "justificacion": "Simulación"},
                "300": {"direccion": "BAJA", "justificacion": "Simulación"}}}}


class EstadoV5Tests(unittest.TestCase):
    def test_hypotheses_never_authorize_trading(self):
        x = construir_estado_v5(market(), analysis(), ahora_utc=T)
        self.assertEqual(x["estado"], "ESPERAR")
        self.assertFalse(x["operativa_autorizada"])
        self.assertIsNone(x["entrada_utc"])
        self.assertEqual([(a["duracion_segundos"], a["direccion_experimental"])
                          for a in x["hipotesis_experimentales"]], [(120, "SUBE"), (300, "BAJA")])

    def test_market_stale_blocks_freshness(self):
        x = construir_estado_v5(market(T-timedelta(seconds=5)), analysis(), ahora_utc=T)
        self.assertFalse(x["mercado_fresco"])

    def test_analysis_stale_blocks(self):
        a = analysis()
        a["stale"] = True
        x = construir_estado_v5(market(), a, ahora_utc=T)
        self.assertFalse(x["analisis_listo"])

    def test_symbol_mismatch_blocks(self):
        m = market()
        m["symbol"] = "SPY"
        x = construir_estado_v5(m, analysis(), ahora_utc=T)
        self.assertFalse(x["analisis_listo"])
        self.assertEqual(x["estado"], "ESPERAR")

    def test_unknown_inputs_safe(self):
        x = construir_estado_v5(None, None, ahora_utc=T)
        self.assertEqual(x["hipotesis_experimentales"], [])
        self.assertFalse(x["mercado_fresco"])

    def test_future_clock_blocks_freshness(self):
        x = construir_estado_v5(market(T+timedelta(seconds=3)), analysis(), ahora_utc=T)
        self.assertFalse(x["mercado_fresco"])

    def test_timestamp_without_tz_blocks(self):
        m = market()
        m["last_received_at"] = "2026-11-23T15:00:00"
        x = construir_estado_v5(m, analysis(), ahora_utc=T)
        self.assertFalse(x["mercado_fresco"])

    def test_lag_not_numeric(self):
        m = market()
        m["last_lag_ms"] = "120"
        x = construir_estado_v5(m, analysis(), ahora_utc=T)
        self.assertIsNone(x["retardo_ultimo_trade_ms"])

    def test_utc_required(self):
        with self.assertRaises(ValueError):
            construir_estado_v5(market(), analysis(), ahora_utc=datetime(2026, 11, 23))


if __name__ == "__main__":
    unittest.main()
