"""Auditoría V5 de consistencia del contexto diario y SMA20/SMA50."""
from datetime import timedelta
import tempfile
import unittest

import pandas as pd
from multitimeframe_context import build_multitimeframe_context


def synthetic_minutes(*, last_session_multiplier=1.0):
    """56 sesiones de 60 minutos, barras indicativas constantes por sesión."""
    days = pd.bdate_range("2026-08-03", periods=56)
    records = []
    for i, day in enumerate(days):
        local_start = pd.Timestamp(f"{day.date()} 09:30", tz="America/New_York")
        base = 100.0 + 0.30 * i
        if i == 55:
            base *= last_session_multiplier
        for minute in range(60):
            moment = (local_start + timedelta(minutes=minute)).tz_convert("UTC")
            close = base + 0.002 * minute
            records.append((moment, close))
    index = pd.DatetimeIndex([a for a, _ in records])
    return pd.DataFrame({
        "Open": [b for _, b in records],
        "High": [b+0.05 for _, b in records],
        "Low": [b-0.05 for _, b in records],
        "Close": [b for _, b in records],
        "Volume": [100 for _ in records]}, index=index)


class QualityDailyTests(unittest.TestCase):
    def check(self, frame):
        with tempfile.TemporaryDirectory() as root:
            return build_multitimeframe_context(frame, as_of=frame.index[-1], project_root=root)

    def test_sma20_diaria_es_distinta_de_sma50(self):
        result = self.check(synthetic_minutes())
        day = result["1d"]
        self.assertEqual(day["status"], "sufficient")
        self.assertNotEqual(day["sma20"], day["sma50"])
        self.assertEqual(day["trend"], "Alcista")
        self.assertEqual(result["future_rows_used"], 0)

    def test_desajuste_previo_al_precio_actual_bloquea_diario(self):
        result = self.check(synthetic_minutes(last_session_multiplier=1.5))
        day = result["1d"]
        self.assertEqual(day["status"], "insufficient")
        self.assertEqual(day["quality_flag"], "PRICE_SCALE_MISMATCH")
        self.assertGreater(day["desviacion_frente_ultimo_precio_pct"], 20)
        self.assertEqual(result["1h"]["status"], "sufficient")

    def test_no_descartar_contexto_diario_sano(self):
        result = self.check(synthetic_minutes(last_session_multiplier=1.01))
        self.assertEqual(result["1d"]["status"], "sufficient")


if __name__ == "__main__":
    unittest.main()
