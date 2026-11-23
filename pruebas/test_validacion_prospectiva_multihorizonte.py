import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from decision_engine_experimental import RULES_VERSION, SUPPORTED_HORIZONS
from validar_prospectivo_multihorizonte import (compare_iq, load_iq_prices, run,
                                                summarize)

T = datetime(2026, 11, 19, 15, 0, tzinfo=timezone.utc)


def row(identifier, horizon, result, entry=100, exit_price=101, direction="SUBE", day=0):
    entered = T + timedelta(days=day, minutes=int(identifier.strip("r") or 0))
    return {
        "id": identifier, "horizonte_segundos": str(horizon), "version_reglas": RULES_VERSION,
        "direccion_hipotetica": direction, "entrada_utc": entered.isoformat(),
        "vencimiento_objetivo_utc": (entered + timedelta(seconds=horizon)).isoformat(),
        "precio_entrada_iex": str(entry), "precio_salida_iex": str(exit_price),
        "resultado": result, "estatus": "evaluado" if result != "NO_EVALUABLE" else "sin_salida",
    }


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.simulations = self.root / "simulations.csv"
        self.pending = self.root / "pending.json"
        self.output = self.root / "output"

    def write_rows(self, rows):
        with self.simulations.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader(); writer.writerows(rows)
        self.pending.write_text("[]", encoding="utf-8")

    def test_four_horizons_are_supported_without_selecting_a_best(self):
        self.assertEqual(SUPPORTED_HORIZONS, (60, 120, 300, 600))
        rows = [row(f"r{i+1}", horizon, "ACIERTO")
                for i, horizon in enumerate(SUPPORTED_HORIZONS)]
        self.write_rows(rows)
        report = run(self.simulations, self.pending, self.output)
        self.assertIsNone(report["automatic_best_horizon"])
        self.assertEqual({item["horizon_seconds"] for item in report["statistics"].values()},
                         set(SUPPORTED_HORIZONS))
        self.assertEqual(report["iq_comparison"]["status"], "PENDIENTE_ARCHIVO_IQ_OPTION")

    def test_statistics_keep_no_evaluable_and_basic_references_separate(self):
        rows = [row("r1", 60, "ACIERTO", 100, 101),
                row("r2", 60, "FALLO", 100, 99),
                row("r3", 60, "NO_EVALUABLE", 100, "")]
        stats = summarize(rows, [], payout=None)[f"60:{RULES_VERSION}"]
        self.assertEqual((stats["wins"], stats["losses"], stats["not_evaluable"]), (1, 1, 1))
        self.assertEqual(stats["reference_always_up_evaluable"], 2)
        self.assertEqual(stats["reference_always_up_win_rate_percent"], 50.0)
        self.assertEqual(stats["verdict"], "PENDIENTE_MUESTRA_NUEVA")
        self.assertIsNone(stats["break_even_win_rate_percent"])

    def test_pending_counts_in_its_own_horizon(self):
        pending = [{"id": "p", "horizonte_segundos": 300, "version_reglas": RULES_VERSION}]
        stats = summarize([], pending)
        self.assertEqual(stats[f"300:{RULES_VERSION}"]["pending_records"], 1)
        self.assertNotIn(f"120:{RULES_VERSION}", stats)

    def test_iq_comparison_uses_first_price_at_or_after_targets(self):
        simulation = row("r1", 120, "ACIERTO", 100, 101)
        entered = datetime.fromisoformat(simulation["entrada_utc"])
        expiry = datetime.fromisoformat(simulation["vencimiento_objetivo_utc"])
        prices = [(entered - timedelta(seconds=1), 200, "NVIDIA Blitz"),
                  (entered + timedelta(seconds=2), 201, "NVIDIA Blitz"),
                  (expiry + timedelta(seconds=3), 202, "NVIDIA Blitz")]
        result = compare_iq([simulation], prices, tolerance_seconds=5)[0]
        self.assertEqual((result["iq_entry_price"], result["iq_exit_price"]), (201, 202))
        self.assertEqual(result["iq_result"], "ACIERTO")
        self.assertTrue(result["directional_agreement"])

    def test_missing_iq_price_is_not_evaluable_not_invented(self):
        simulation = row("r1", 120, "ACIERTO")
        result = compare_iq([simulation], [], tolerance_seconds=5)[0]
        self.assertEqual(result["iq_result"], "NO_EVALUABLE")
        self.assertEqual(result["iq_entry_price"], "")

    def test_iq_schema_and_end_to_end_output(self):
        rows = [row("r1", 120, "ACIERTO")]
        self.write_rows(rows)
        iq = self.root / "iq.csv"
        entered = datetime.fromisoformat(rows[0]["entrada_utc"])
        expiry = datetime.fromisoformat(rows[0]["vencimiento_objetivo_utc"])
        iq.write_text("timestamp_utc,price,product\n" +
                      f"{entered.isoformat()},200,NVIDIA Blitz\n" +
                      f"{expiry.isoformat()},201,NVIDIA Blitz\n", encoding="utf-8")
        before = hashlib.sha256(self.simulations.read_bytes()).hexdigest()
        report = run(self.simulations, self.pending, self.output, iq_prices=iq)
        self.assertEqual(report["iq_comparison"]["matched"], 1)
        self.assertEqual(report["iq_comparison"]["directional_agreement_percent"], 100.0)
        self.assertTrue((self.output / "comparacion_iex_iqoption.csv").exists())
        self.assertEqual(hashlib.sha256(self.simulations.read_bytes()).hexdigest(), before)

    def test_invalid_iq_schema_is_rejected(self):
        bad = self.root / "bad.csv"
        bad.write_text("time,value\n2026-11-19,1\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            load_iq_prices(bad)

    def test_wrong_instrument_or_naive_timestamp_is_rejected(self):
        wrong = self.root / "wrong.csv"
        wrong.write_text("timestamp_utc,price,product\n2026-11-19T15:00:00+00:00,1,NVDA stock\n",
                         encoding="utf-8")
        with self.assertRaises(ValueError):
            load_iq_prices(wrong)
        naive = self.root / "naive.csv"
        naive.write_text("timestamp_utc,price,product\n2026-11-19T15:00:00,1,NVIDIA Blitz\n",
                         encoding="utf-8")
        with self.assertRaises(ValueError):
            load_iq_prices(naive)


if __name__ == "__main__":
    unittest.main(verbosity=2)
