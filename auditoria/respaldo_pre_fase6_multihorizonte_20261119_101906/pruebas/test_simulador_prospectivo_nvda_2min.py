import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from simulador_prospectivo_nvda_2min import ProspectiveObserver, extract_trade, parse_dt, iso, HORIZON_SECONDS, is_us_regular_session

T = datetime(2026, 11, 19, 15, 0, tzinfo=timezone.utc)


def ana(candle, bias="Alcista", status="ready", **overrides):
    data = dict(symbol="NVDA", last_candle_time=iso(candle), status=status,
                stale=False, decision="ESPERAR", bias=bias, computed_at=iso(candle+timedelta(seconds=60)),
                values={"rsi_14": 32.1}, reason="Registro de prueba", signals=["Test"])
    data.update(overrides)
    return data


def mkmarket(trade_time=None, price=101, symbol="NVDA"):
    d = {"symbol": symbol}
    if trade_time:
        d["last_trade"] = {"price": price, "timestamp": iso(trade_time)}
    return d


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.obs = ProspectiveObserver(self.root, started=T)

    def base_signal(self):
        self.obs.process(ana(T-timedelta(seconds=120)), mkmarket(), T)
        result = self.obs.process(ana(T-timedelta(seconds=60), computed_at=iso(T+timedelta(seconds=1))), mkmarket(), T+timedelta(seconds=1))
        self.assertIn("hipotesis SUBE", result)
        return self.obs.pending[0]

    def read_rows(self):
        with (self.root/'simulaciones_nvda_2min.csv').open(encoding='utf-8', newline='') as f:
            return list(csv.DictReader(f))

    def test_no_history_retroactively_emitted(self):
        self.assertEqual(self.obs.process(ana(T-timedelta(seconds=60)), mkmarket(), T), "observador iniciado: esperar siguiente vela nueva")
        self.assertEqual(len(self.obs.pending), 0)

    def test_no_future_bar(self):
        self.obs.process(ana(T-timedelta(seconds=60)), mkmarket(), T)
        self.assertEqual(self.obs.process(ana(T, computed_at=iso(T+timedelta(seconds=1))), mkmarket(), T+timedelta(seconds=1)), "vela aún abierta")
        self.assertEqual(self.obs.pending, [])

    def test_exact_two_minutes_from_trade_entry(self):
        item = self.base_signal()
        first = T+timedelta(seconds=4)
        self.obs.process(ana(T-timedelta(seconds=60)), mkmarket(first, 101), first)
        self.assertEqual(parse_dt(self.obs.pending[0]['vencimiento_objetivo_utc'])-first, timedelta(seconds=HORIZON_SECONDS))

    def test_price_must_follow_detection(self):
        self.base_signal()
        self.obs.process(ana(T-timedelta(seconds=60)), mkmarket(T, 101), T+timedelta(seconds=2))
        self.assertFalse(self.obs.pending[0]['entrada_utc'])

    def test_close_with_valid_trade(self):
        self.base_signal()
        enter = T+timedelta(seconds=4)
        self.obs.process(ana(T-timedelta(seconds=60)), mkmarket(enter, 100), enter)
        exp = enter+timedelta(seconds=120)
        self.obs.process(ana(T-timedelta(seconds=60)), mkmarket(exp+timedelta(seconds=2), 101), exp+timedelta(seconds=2))
        self.assertEqual(self.read_rows()[0]['resultado'], 'ACIERTO')
        self.assertEqual(len(self.obs.pending), 0)

    def test_baja_win_and_tie(self):
        self.obs.process(ana(T-timedelta(seconds=120)), mkmarket(), T)
        self.obs.process(ana(T-timedelta(seconds=60), bias='Bajista', computed_at=iso(T+timedelta(seconds=1))), mkmarket(), T+timedelta(seconds=1))
        enter = T+timedelta(seconds=4)
        self.obs.process(ana(T-timedelta(seconds=60)), mkmarket(enter, 100), enter)
        exp = enter+timedelta(seconds=120)
        self.obs.process(ana(T-timedelta(seconds=60)), mkmarket(exp, 99), exp)
        self.assertEqual(self.read_rows()[0]['resultado'], 'ACIERTO')

    def test_missing_entry_is_not_evaluated(self):
        self.base_signal()
        after = T + timedelta(seconds=35)
        self.obs.process(ana(T-timedelta(seconds=60)), mkmarket(), after)
        self.assertEqual(self.read_rows()[0]['resultado'], 'NO_EVALUABLE')
        self.assertEqual(self.read_rows()[0]['estatus'], 'sin_entrada')

    def test_missing_exit_is_not_a_loss(self):
        self.base_signal()
        enter = T+timedelta(seconds=4)
        self.obs.process(ana(T-timedelta(seconds=60)), mkmarket(enter, 100), enter)
        after = enter+timedelta(seconds=135)
        self.obs.process(ana(T-timedelta(seconds=60)), mkmarket(), after)
        self.assertEqual(self.read_rows()[0]['resultado'], 'NO_EVALUABLE')
        self.assertEqual(self.read_rows()[0]['estatus'], 'sin_salida')

    def test_ignores_inactive_or_contradictory(self):
        self.obs.process(ana(T-timedelta(seconds=120)), mkmarket(), T)
        self.assertEqual(self.obs.process(ana(T-timedelta(seconds=60), bias='Contradictorio', computed_at=iso(T+timedelta(seconds=1))), mkmarket(), T+timedelta(seconds=1)), 'observacion registrada: ESPERAR')
        self.assertEqual(len(self.obs.pending), 0)

    def test_no_overlap(self):
        self.base_signal()
        enter = T + timedelta(seconds=4)
        self.obs.process(ana(T-timedelta(seconds=60)), mkmarket(enter, 100), enter)
        result = self.obs.process(ana(T, computed_at=iso(T+timedelta(seconds=61))), mkmarket(), T+timedelta(seconds=61))
        self.assertIn('no solapada', result)
        self.assertEqual(len(self.obs.pending), 1)

    def test_no_simulation_for_another_asset(self):
        self.obs.process(ana(T-timedelta(seconds=120)), mkmarket(), T)
        self.assertEqual(self.obs.process(ana(T-timedelta(seconds=60)), mkmarket(symbol='MSFT'), T+timedelta(seconds=1)), 'omitido: otro activo')

    def test_old_analysis_not_used(self):
        self.obs.process(ana(T-timedelta(seconds=120)), mkmarket(), T)
        self.assertIn('anterior', self.obs.process(ana(T-timedelta(seconds=60), computed_at=iso(T-timedelta(seconds=10))), mkmarket(), T+timedelta(seconds=1)))

    def test_trade_must_be_recent(self):
        self.assertIsNone(extract_trade(mkmarket(T, 100), T+timedelta(seconds=15)))

    def test_resume_pending_without_duplicate(self):
        self.base_signal()
        second = ProspectiveObserver(self.root, started=T+timedelta(seconds=5))
        self.assertEqual(len(second.pending), 1)
        enter = T+timedelta(seconds=7)
        second.process(ana(T-timedelta(seconds=60)), mkmarket(enter, 100), enter)
        exp = enter+timedelta(seconds=120)
        second.process(ana(T-timedelta(seconds=60)), mkmarket(exp, 101), exp)
        self.assertEqual(len(self.read_rows()), 1)
        third = ProspectiveObserver(self.root, started=exp+timedelta(seconds=3))
        self.assertEqual(len(third.pending), 0)

    def test_session_hours_winter_summer_and_weekend(self):
        self.assertFalse(is_us_regular_session(datetime(2026, 11, 19, 13, 50, tzinfo=timezone.utc)))
        self.assertTrue(is_us_regular_session(datetime(2026, 11, 19, 14, 30, tzinfo=timezone.utc)))
        self.assertFalse(is_us_regular_session(datetime(2026, 11, 19, 21, 0, tzinfo=timezone.utc)))
        self.assertTrue(is_us_regular_session(datetime(2026, 7, 2, 13, 30, tzinfo=timezone.utc)))
        self.assertFalse(is_us_regular_session(datetime(2026, 7, 2, 20, 0, tzinfo=timezone.utc)))
        self.assertFalse(is_us_regular_session(datetime(2026, 11, 21, 15, 0, tzinfo=timezone.utc)))

    def test_premarket_hypothesis_not_emitted(self):
        earlier = datetime(2026, 11, 19, 13, 50, tzinfo=timezone.utc)
        self.obs = ProspectiveObserver(self.root, started=earlier)
        self.obs.process(ana(earlier - timedelta(seconds=120)), mkmarket(), earlier)
        status = self.obs.process(ana(earlier - timedelta(seconds=60), computed_at=iso(earlier + timedelta(seconds=1))), mkmarket(), earlier + timedelta(seconds=1))
        self.assertIn('fuera de sesión', status)
        self.assertFalse(self.obs.pending)

    def test_close_to_end_of_day_has_no_new_hypothesis(self):
        near_close = datetime(2026, 11, 19, 20, 58, tzinfo=timezone.utc)
        self.obs.process(ana(near_close - timedelta(seconds=120)), mkmarket(), near_close)
        status = self.obs.process(ana(near_close - timedelta(seconds=60), computed_at=iso(near_close + timedelta(seconds=1))), mkmarket(), near_close + timedelta(seconds=1))
        self.assertIn('cierre', status)
        self.assertFalse(self.obs.pending)

    def test_old_premarket_pending_is_discarded(self):
        pending_time = datetime(2026, 11, 19, 13, 52, tzinfo=timezone.utc)
        item = {k: '' for k in __import__('simulador_prospectivo_nvda_2min').FIELDS}
        item.update(id='old-premarket', activo='NVDA', direccion_hipotetica='SUBE',
                    senal_detectada_utc=iso(pending_time), velas_base_utc=iso(pending_time - timedelta(minutes=1)))
        self.obs.pending = [item]
        self.obs._persist()
        self.obs.process({}, mkmarket(), pending_time + timedelta(minutes=1))
        self.assertFalse(self.obs.pending)
        self.assertEqual(self.read_rows()[0]['estatus'], 'fuera_sesion')
        self.assertEqual(self.read_rows()[0]['resultado'], 'NO_EVALUABLE')

    def test_no_valid_operational_signal(self):
        self.obs.process(ana(T-timedelta(seconds=120)), mkmarket(), T)
        self.obs.process(ana(T-timedelta(seconds=60), computed_at=iso(T+timedelta(seconds=1))), mkmarket(), T+timedelta(seconds=1))
        self.assertEqual(self.obs.pending[0]['nota'], 'HIPOTESIS EXPERIMENTAL, SIN VALIDEZ OPERATIVA')


if __name__ == '__main__':
    unittest.main(verbosity=2)
