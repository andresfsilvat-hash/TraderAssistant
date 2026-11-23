import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from decision_engine_experimental import RULES_VERSION, evaluate_hypothesis
from simulation_results import SimulationResultsReader, register_simulation_results
from simulador_prospectivo_nvda_2min import (ProspectiveObserver, SimulatorInstanceLock,
                                             iso, parse_dt)

T = datetime(2026, 11, 19, 15, 0, tzinfo=timezone.utc)


def analysis(candle, *, signals=None, rsi=50, macd=0.1, **overrides):
    result = {
        "symbol": "NVDA", "status": "ready", "stale": False, "decision": "ESPERAR",
        "bias": "Alcista", "last_candle_time": iso(candle),
        "computed_at": iso(candle + timedelta(seconds=60)),
        "signals": list(signals or []), "values": {"rsi_14": rsi, "macd_histogram": macd},
    }
    result.update(overrides)
    return result


def market(timestamp=None, price=100):
    result = {"symbol": "NVDA"}
    if timestamp:
        result["last_trade"] = {"timestamp": iso(timestamp), "price": price}
    return result


class DecisionRulesTests(unittest.TestCase):
    def test_high_rsi_with_bullish_macd_is_not_automatic_baja(self):
        result = evaluate_hypothesis(analysis(T, signals=["RSI overbought >70 (1m)"], rsi=78, macd=.19))
        self.assertEqual(result["hipotesis_simulacion"], "ESPERAR")
        self.assertTrue(any("no implica BAJA" in item for item in result["indicadores_contradictorios"]))

    def test_low_rsi_with_bearish_macd_is_not_automatic_sube(self):
        result = evaluate_hypothesis(analysis(T, signals=["RSI oversold <30 (1m)"], rsi=22, macd=-.2))
        self.assertEqual(result["hipotesis_simulacion"], "ESPERAR")
        self.assertTrue(any("no implica SUBE" in item for item in result["indicadores_contradictorios"]))

    def test_confirmed_pattern_and_momentum(self):
        bullish = evaluate_hypothesis(analysis(T, signals=["Hammer (1m)"], macd=.01))
        bearish = evaluate_hypothesis(analysis(T, signals=["Shooting Star (1m)"], macd=-.01))
        self.assertEqual(bullish["hipotesis_simulacion"], "SUBE")
        self.assertEqual(bearish["hipotesis_simulacion"], "BAJA")
        self.assertEqual(bullish["horizontes_segundos"], [120, 300, 600])
        self.assertEqual(bullish["decision_operativa_validada"], "ESPERAR")

    def test_contradiction_and_missing_data_wait(self):
        mixed = evaluate_hypothesis(analysis(T, signals=["Hammer (1m)", "Shooting Star (1m)"], macd=.1))
        missing = evaluate_hypothesis({"symbol": "NVDA", "status": "insufficient", "stale": True})
        self.assertEqual(mixed["hipotesis_simulacion"], "ESPERAR")
        self.assertEqual(missing["hipotesis_simulacion"], "ESPERAR")

    def test_available_hourly_daily_context_can_veto_but_not_create(self):
        context = {"1h": {"status": "ready", "trend": "Bajista"},
                   "1d": {"status": "insufficient", "trend": "Alcista"}}
        result = evaluate_hypothesis(analysis(T, signals=["Hammer (1m)"], macd=.1, context=context))
        self.assertEqual(result["hipotesis_simulacion"], "ESPERAR")
        self.assertEqual(result["contexto_tendencia"], {"1h": "Bajista"})


class MultiHorizonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.observer = ProspectiveObserver(self.root, started=T)

    def _open_three(self):
        self.observer.process(analysis(T - timedelta(seconds=120), signals=["Hammer (1m)"]), market(), T)
        status = self.observer.process(
            analysis(T - timedelta(seconds=60), signals=["Hammer (1m)"], computed_at=iso(T + timedelta(seconds=1))),
            market(), T + timedelta(seconds=1))
        self.assertIn("[120, 300, 600]", status)
        return self.observer.pending

    def test_same_rule_creates_three_independent_horizons(self):
        records = self._open_three()
        self.assertEqual([item["horizonte_segundos"] for item in records], [120, 300, 600])
        self.assertEqual(len({item["grupo_id"] for item in records}), 1)
        self.assertTrue(all(item["version_reglas"] == RULES_VERSION for item in records))

    def test_entry_is_after_detection_and_expiries_use_real_entry(self):
        self._open_three()
        entry = T + timedelta(seconds=4)
        self.observer.process(analysis(T - timedelta(seconds=60), signals=["Hammer (1m)"]), market(entry, 100), entry)
        for record in self.observer.pending:
            detected = parse_dt(record["senal_detectada_utc"])
            entered = parse_dt(record["entrada_utc"])
            expiry = parse_dt(record["vencimiento_objetivo_utc"])
            self.assertGreater(entered, detected)
            self.assertEqual((expiry - entered).total_seconds(), record["horizonte_segundos"])

    def test_results_close_independently_per_horizon(self):
        self._open_three()
        entry = T + timedelta(seconds=4)
        self.observer.process(analysis(T - timedelta(seconds=60), signals=["Hammer (1m)"]), market(entry, 100), entry)
        for horizon, price in ((120, 101), (300, 99), (600, 102)):
            expiry = entry + timedelta(seconds=horizon)
            self.observer.process(analysis(T - timedelta(seconds=60), signals=["Hammer (1m)"]), market(expiry, price), expiry)
        with self.observer.csv_file.open(encoding="utf-8", newline="") as stream:
            rows = sorted(csv.DictReader(stream), key=lambda row: int(row["horizonte_segundos"]))
        self.assertEqual([row["resultado"] for row in rows], ["ACIERTO", "FALLO", "ACIERTO"])
        reader = SimulationResultsReader(ROOT, directories=[self.root])
        ref_120 = reader.snapshot(120)["statistics_by_rules_version"][RULES_VERSION]
        ref_300 = reader.snapshot(300)["statistics_by_rules_version"][RULES_VERSION]
        self.assertEqual(ref_120["reference_always_sube_wins"], 1)
        self.assertEqual(ref_300["reference_always_sube_wins"], 0)

    def test_partial_pending_file_recovers_as_warning(self):
        (self.root / "pendientes_multihorizonte.json").write_text('[{"id":', encoding="utf-8")
        recovered = ProspectiveObserver(self.root, started=T)
        self.assertEqual(recovered.pending, [])
        self.assertTrue(any(item.startswith("pending:") for item in recovered.load_warnings))

    def test_duplicate_pending_is_loaded_once(self):
        record = {"id": "same", "horizonte_segundos": 120}
        (self.root / "pendientes_multihorizonte.json").write_text(json.dumps([record, record]), encoding="utf-8")
        recovered = ProspectiveObserver(self.root, started=T)
        self.assertEqual(len(recovered.pending), 1)

    def test_instance_lock_rejects_duplicate_writer(self):
        first = SimulatorInstanceLock(self.root).acquire()
        self.addCleanup(first.release)
        with self.assertRaises(RuntimeError):
            SimulatorInstanceLock(self.root).acquire()


class ResultsEndpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_stopped_simulator_never_marks_old_pending_as_current(self):
        pending = [{"id": "old", "activo": "NVDA", "horizonte_segundos": 120,
                    "direccion_hipotetica": "SUBE", "senal_detectada_utc": iso(T)}]
        (self.root / "pendientes_multihorizonte.json").write_text(json.dumps(pending), encoding="utf-8")
        result = SimulationResultsReader(ROOT, directories=[self.root]).snapshot(120)
        self.assertEqual(result["simulator_status"], "SIMULADOR_DETENIDO")
        self.assertIsNone(result["latest"])
        self.assertEqual(result["active_simulation_status"], "SIN_SIMULACION_ACTIVA")

    def test_default_active_view_never_reads_legacy_directories(self):
        active = self.root / "auditoria" / "prospectivo_nvda_multihorizonte"
        legacy = self.root / "auditoria" / "prospectivo_nvda_2min_sesion_regular"
        active.mkdir(parents=True); legacy.mkdir(parents=True)
        now = datetime.now(timezone.utc)
        (active / "estado_simulador.json").write_text(json.dumps({
            "status": "running", "started_utc": iso(now - timedelta(minutes=2)),
            "heartbeat_utc": iso(now), "rules_version": RULES_VERSION,
        }), encoding="utf-8")
        (active / "pendientes_multihorizonte.json").write_text("[]", encoding="utf-8")
        (legacy / "pendientes.json").write_text(json.dumps([{
            "id": "legacy", "activo": "NVDA", "direccion_hipotetica": "SUBE",
            "senal_detectada_utc": iso(now - timedelta(hours=1)), "entrada_utc": iso(now - timedelta(hours=1)),
            "vencimiento_objetivo_utc": iso(now - timedelta(minutes=58)),
        }]), encoding="utf-8")
        result = SimulationResultsReader(self.root).snapshot(120)
        self.assertEqual(result["simulator_status"], "ACTIVO")
        self.assertIsNone(result["latest"])
        self.assertEqual(result["statistics_by_rules_version"], {})
        self.assertEqual(Path(result["active_directory"]), active.resolve())

    def test_heartbeat_freshness_is_recomputed_even_when_files_do_not_change(self):
        now = datetime.now(timezone.utc)
        (self.root / "estado_simulador.json").write_text(json.dumps({
            "status": "running", "started_utc": iso(now - timedelta(minutes=1)),
            "heartbeat_utc": iso(now), "rules_version": RULES_VERSION,
        }), encoding="utf-8")
        reader = SimulationResultsReader(ROOT, directories=[self.root])
        self.assertEqual(reader.snapshot(120)["simulator_status"], "ACTIVO")
        with patch("simulation_results.HEARTBEAT_MAX_AGE_SECONDS", -1):
            self.assertEqual(reader.snapshot(120)["simulator_status"], "SIMULADOR_DETENIDO")

    def test_expired_pending_is_never_presented_as_active(self):
        now = datetime.now(timezone.utc)
        (self.root / "estado_simulador.json").write_text(json.dumps({
            "status": "running", "started_utc": iso(now - timedelta(minutes=20)),
            "heartbeat_utc": iso(now), "rules_version": RULES_VERSION,
        }), encoding="utf-8")
        pending = [{"id": "expired", "activo": "NVDA", "horizonte_segundos": 120,
                    "direccion_hipotetica": "SUBE", "version_reglas": RULES_VERSION,
                    "senal_detectada_utc": iso(now - timedelta(minutes=10)),
                    "entrada_utc": iso(now - timedelta(minutes=9)),
                    "vencimiento_objetivo_utc": iso(now - timedelta(minutes=7))}]
        (self.root / "pendientes_multihorizonte.json").write_text(json.dumps(pending), encoding="utf-8")
        result = SimulationResultsReader(ROOT, directories=[self.root]).snapshot(120)
        self.assertEqual(result["simulator_status"], "ACTIVO")
        self.assertIsNone(result["latest"])
        self.assertEqual(result["stale_pending_count"], 1)
        self.assertEqual(result["statistics_by_rules_version"][RULES_VERSION]["active"], 0)

    def test_original_1023_record_is_not_active_for_process_started_at_1058(self):
        now = datetime.now(timezone.utc)
        process_start = datetime(2026, 11, 19, 15, 58, tzinfo=timezone.utc)  # 10:58 EC
        (self.root / "estado_simulador.json").write_text(json.dumps({
            "status": "running", "started_utc": iso(process_start),
            "heartbeat_utc": iso(now), "rules_version": RULES_VERSION,
        }), encoding="utf-8")
        old = [{"id": "sube-1023", "activo": "NVDA", "horizonte_segundos": 120,
                "direccion_hipotetica": "SUBE", "version_reglas": RULES_VERSION,
                "senal_detectada_utc": "2026-11-19T15:23:01+00:00",
                "entrada_utc": "2026-11-19T15:23:06+00:00",
                "vencimiento_objetivo_utc": "2026-11-19T15:25:06+00:00"}]
        (self.root / "pendientes_multihorizonte.json").write_text(json.dumps(old), encoding="utf-8")
        result = SimulationResultsReader(ROOT, directories=[self.root]).snapshot(120)
        self.assertEqual(result["simulator_status"], "ACTIVO")
        self.assertEqual(result["active_simulation_status"], "SIN_SIMULACION_ACTIVA")
        self.assertIsNone(result["latest"])
        self.assertEqual(result["stale_pending_count"], 1)

    def test_no_evaluable_is_preserved_and_scoped_to_selected_horizon(self):
        fields = ["id", "horizonte_segundos", "version_reglas", "resultado", "estatus"]
        with (self.root / "simulaciones_nvda_multihorizonte.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader()
            writer.writerow({"id": "two", "horizonte_segundos": 120, "version_reglas": RULES_VERSION,
                             "resultado": "NO_EVALUABLE", "estatus": "sin_salida"})
            writer.writerow({"id": "five", "horizonte_segundos": 300, "version_reglas": RULES_VERSION,
                             "resultado": "NO_EVALUABLE", "estatus": "sin_entrada"})
        reader = SimulationResultsReader(ROOT, directories=[self.root])
        two = reader.snapshot(120)["statistics_by_rules_version"][RULES_VERSION]
        five = reader.snapshot(300)["statistics_by_rules_version"][RULES_VERSION]
        ten = reader.snapshot(600)["statistics_by_rules_version"]
        self.assertEqual((two["generated"], two["not_evaluable"]), (1, 1))
        self.assertEqual((five["generated"], five["not_evaluable"]), (1, 1))
        self.assertEqual(ten, {})

    def test_endpoint_and_statistics_are_independent_by_horizon(self):
        observer = ProspectiveObserver(self.root, started=T)
        observer.process(analysis(T - timedelta(seconds=120), signals=["Hammer (1m)"]), market(), T)
        observer.process(analysis(T - timedelta(seconds=60), signals=["Hammer (1m)"], computed_at=iso(T + timedelta(seconds=1))), market(), T + timedelta(seconds=1))
        observer.heartbeat()
        app = Flask("phase6-test")
        register_simulation_results(app, directories=[self.root])
        client = app.test_client()
        for horizon in (120, 300, 600):
            response = client.get(f"/api/simulation/live?horizon={horizon}")
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["selected_horizon_seconds"], horizon)
            self.assertEqual(payload["statistics_by_rules_version"][RULES_VERSION]["generated"], 1)
        self.assertEqual(client.get("/api/simulation/live?horizon=42").status_code, 400)

    def test_cached_endpoint_is_lightweight(self):
        reader = SimulationResultsReader(ROOT, directories=[self.root])
        reader.snapshot(120)
        started = time.perf_counter()
        for _ in range(1000):
            reader.snapshot(120)
        self.assertLess((time.perf_counter() - started) / 1000, .005)

    def test_protected_realtime_and_original_analysis_hashes(self):
        expected = {
            "alpaca_live.py": "10BA6B883803C5E1DB04666B3855B70542C47C47F16E544D9B8D2D501EBB8127",
            "analysis_live.py": "D1FFBD23EC85FF2B41BAC7F5F5751F433A5BCB1D8031421E1B466829A486250A",
            "main.py": "67CD9EC723DAAB05E1B498FD765F46763FCA90E320C6D1AE99F7CC9AC08BE2DC",
        }
        for relative, digest in expected.items():
            self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest().upper(), digest)


if __name__ == "__main__":
    unittest.main(verbosity=2)
