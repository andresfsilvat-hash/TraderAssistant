"""Pruebas SIN cuenta Alpaca, SIN Internet y SIN operaciones bursatiles.

Uso: python pruebas/probar_v4.py desde la carpeta TraderAssistant.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / 'realtime_v4' / 'alpaca_live.py'

# Las pruebas de logica no necesitan importar Flask real.
if 'flask' not in sys.modules:
    fake = types.ModuleType('flask')
    fake.Response = object
    fake.jsonify = lambda obj: obj
    fake.send_from_directory = lambda *a: None
    fake.stream_with_context = lambda a: a
    sys.modules['flask'] = fake
spec = importlib.util.spec_from_file_location('test_v4_backend', BACKEND)
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)


def stamp(s):
    return datetime.fromtimestamp(s, tz=timezone.utc).isoformat().replace('+00:00','Z')


def trade(s, price, size=100, conditions=None, trade_id=None):
    return {'T':'t', 'S':'NVDA', 't':stamp(s), 'p':price, 's':size,
            'c':conditions if conditions is not None else ['@'], 'z':'C', 'x':'V',
            'i':trade_id if trade_id is not None else s}


class MarketTests(unittest.TestCase):
    def setUp(self):
        self.f = backend.LiveFeed()
        self.base = 1700000040  # minuto exacto

    def test_trades_create_provisional_without_authorizing_official(self):
        t=self.base
        self.f.on_trade(trade(t+1, 150, trade_id=1))
        self.f.on_trade(trade(t+2, 151, trade_id=2))
        s=self.f.snapshot()
        self.assertEqual(s['candles'][0]['high'],151)
        self.assertEqual(s['candles'][0]['volume'],200)
        self.assertTrue(s['candles'][0]['provisional'])
        self.assertEqual(len(self.f.official),0)

    def test_odd_lot_does_not_change_candle(self):
        t=self.base
        self.f.on_trade(trade(t+1, 150, trade_id=11))
        self.f.on_trade(trade(t+2, 300, size=5, conditions=['@','I'], trade_id=12))
        b=self.f.snapshot()['candles'][0]
        self.assertEqual(b['high'],150)
        self.assertEqual(b['close'],150)
        self.assertEqual(b['volume'],100)
        self.assertEqual(self.f.snapshot()['last_trade']['price'],300)
        self.assertEqual(self.f.snapshot()['excluded_count'],1)

    def test_official_bar_replaces_provisional_without_merge(self):
        t=self.base
        self.f.on_trade(trade(t+1, 150, trade_id=21))
        self.f.insert_bar({'time':t,'open':149,'high':150,'low':148,'close':148.5,'volume':900})
        b=self.f.snapshot()['candles'][0]
        self.assertEqual(b['close'],148.5)
        self.assertEqual(b['volume'],900)
        self.assertFalse(b['provisional'])
        self.assertIsNone(self.f.provisional)

    def test_late_official_correction_changes_revision(self):
        t=self.base
        bar={'time':t,'open':150,'high':152,'low':149,'close':151,'volume':1000}
        self.f.insert_bar(bar)
        self.f.insert_bar(dict(bar,close=150.5))
        self.assertEqual(self.f.snapshot()['candles'][0]['close'],150.5)
        self.assertGreaterEqual(self.f.series_revision,1)

    def test_older_correction_keeps_current_provisional(self):
        t=self.base
        self.f.insert_bar({'time':t,'open':150,'high':152,'low':149,'close':151,'volume':1000})
        self.f.on_trade(trade(t+61,153,trade_id=30))
        self.f.insert_bar({'time':t,'open':150,'high':152,'low':149,'close':150,'volume':1300})
        bars=self.f.snapshot()['candles']
        self.assertEqual(len(bars),2)
        self.assertFalse(bars[0]['provisional'])
        self.assertTrue(bars[1]['provisional'])
        self.assertEqual(bars[1]['close'],153)

    def test_dedup_trade_id(self):
        t=self.base
        event=trade(t+1,150,trade_id=40)
        self.f.on_trade(event);self.f.on_trade(event)
        self.assertEqual(self.f.trade_count,1)
        self.assertEqual(self.f.snapshot()['candles'][0]['volume'],100)

    def test_five_second_bars_only_on_trades(self):
        t=self.base
        self.f.on_trade(trade(t+1,150,trade_id=50))
        self.f.on_trade(trade(t+7,151,trade_id=51))
        self.assertEqual([b['time'] for b in self.f.snapshot()['short_candles']],[t,t+5])
        self.assertTrue(all(b['provisional'] for b in self.f.snapshot()['short_candles']))

    def test_unexpected_conditions_fail_closed(self):
        self.assertFalse(backend._price_eligible({'c':['@','???'],'z':'C'}))
        self.assertFalse(backend._price_eligible({'c':['@','Z'],'z':'C'}))
        self.assertTrue(backend._price_eligible({'c':['@','F'],'z':'C'}))

    def test_no_credentials_leaked_in_snapshot(self):
        obj=self.f.snapshot()
        for banned in ('key','secret','endpoint'):
            self.assertNotIn(banned,obj)

    def test_stream_does_not_wait_for_history(self):
        gate=threading.Event();connected=threading.Event()
        class FakeSocket:
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def send(self,payload):pass
            def __iter__(self):
                connected.set()
                yield '[{"T":"success","msg":"authenticated"}]'
                yield '[{"T":"subscription","trades":["NVDA"],"bars":["NVDA"],"updatedBars":["NVDA"]}]'
                yield '[{"T":"t","S":"NVDA","t":"2023-11-14T22:14:01Z","p":150,"s":100,"c":["@"],"z":"C","i":999,"x":"V"}]'
                yield '[{"T":"error","code":406}]'
        def slow_history(*a):gate.wait(1.5)
        with patch.object(backend,'_credentials',return_value=('FAKE','FAKE')),\
             patch.object(backend,'connect',return_value=FakeSocket()),\
             patch.object(self.f,'history',side_effect=slow_history):
            thread=threading.Thread(target=self.f.run)
            thread.start()
            self.assertTrue(connected.wait(1),'Conecta WebSocket sin esperar REST')
            thread.join(timeout=1)
            self.assertFalse(thread.is_alive())
            self.assertEqual(self.f.trade_count,1)
            gate.set()


class InstallerTests(unittest.TestCase):
    def _make_project(self,path,version):
        fixtures=ROOT/'pruebas'/'fixtures'
        # Archivos minimos ficticios para probar la validacion del instalador.
        (path/'ui'/'vendor').mkdir(parents=True,exist_ok=True)
        (path/'app.py').write_text('from alpaca_live import register_live\nregister_live(app)\n',encoding='utf-8')
        (path/'main.py').write_text('url=f"http://{HOST}:{PORT}/live"\n',encoding='utf-8')
        (path/'ui/vendor/lightweight-charts.js').write_text('/* prueba */',encoding='utf-8')
        backend_src=fixtures/(version+'_alpaca_live.py')
        html_src=fixtures/(version+'_live.html')
        for filename,source in [('alpaca_live.py',backend_src),('ui/live.html',html_src)]:
            dest=path/filename;dest.parent.mkdir(parents=True,exist_ok=True)
            s=source.read_text(encoding='utf-8').replace('\r\n','\n')
            dest.write_bytes(s.replace('\n','\r\n').encode('utf-8'))
        shutil.copy2(ROOT/'instalar_realtime_v4.py',path/'instalar_realtime_v4.py')
        shutil.copytree(ROOT/'realtime_v4',path/'realtime_v4')

    def test_install_from_v2_and_v3(self):
        for version in ('v2','v3'):
            with self.subTest(version=version):
                with tempfile.TemporaryDirectory() as directory:
                    path=Path(directory)
                    self._make_project(path,version)
                    p=subprocess.run([sys.executable,str(path/'instalar_realtime_v4.py')],capture_output=True,text=True)
                    self.assertEqual(p.returncode,0,p.stdout+'\n'+p.stderr)
                    self.assertIn('4.0.0',(path/'alpaca_live.py').read_text(encoding='utf-8'))
                    self.assertTrue(list(path.glob('alpaca_live.py.bak_pre_v4_*')))
                    self.assertTrue(list((path/'ui').glob('live.html.bak_pre_v4_*')))

    def test_unknown_source_aborts_without_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory);self._make_project(path,'v2')
            src=path/'alpaca_live.py';src.write_bytes(src.read_bytes()+b'\n# cambio local\n')
            before=(path/'ui/live.html').read_bytes()
            p=subprocess.run([sys.executable,str(path/'instalar_realtime_v4.py')],capture_output=True,text=True)
            self.assertNotEqual(p.returncode,0)
            self.assertEqual(before,(path/'ui/live.html').read_bytes())
            self.assertFalse(list(path.glob('*.bak_pre_v4_*')))


if __name__=='__main__':
    unittest.main(verbosity=2)
