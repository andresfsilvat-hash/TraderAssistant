"""Pruebas sin red ni credenciales, usando solo la biblioteca estándar."""
from __future__ import annotations
from datetime import datetime, timezone
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

P = Path(__file__).resolve().parents[1] / "descargar_historial_nvda_iex.py"
spec = importlib.util.spec_from_file_location("historia_nvda", P)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class Tests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 18, 20, 5, tzinfo=timezone.utc)

    def row(self, t="2026-11-17T14:30:00Z", **kwargs):
        x = {"t": t, "o": 150, "h": 151, "l": 149, "c": 150.5, "v": 42}
        x.update(kwargs)
        return x

    def test_range_excludes_current_minutes(self):
        start, end = m.build_range(30, now=self.now)
        self.assertEqual(end.isoformat(), "2026-11-18T20:03:00+00:00")
        self.assertEqual(int((end-start).total_seconds()), 30*86400)

    def test_invalid_days_rejected(self):
        for d in (0, 1, 6, 366, 900):
            with self.assertRaises(m.DownloadError): m.build_range(d, now=self.now)

    def test_validate_ohlcv(self):
        self.assertIsNotNone(m.normalize_bar(self.row()))
        self.assertIsNone(m.normalize_bar(self.row(h=149)))
        self.assertIsNone(m.normalize_bar(self.row(l=151)))
        self.assertIsNone(m.normalize_bar(self.row(c=0)))
        self.assertIsNone(m.normalize_bar(self.row(v=-1)))

    def test_nanosecond_timestamp(self):
        self.assertEqual(m._timestamp('2026-11-17T14:30:00.123456789Z'),
                         m._timestamp('2026-11-17T14:30:00Z'))

    def test_pagination_duplicate_and_sort(self):
        seen = []
        def fetch(params, k, s):
            seen.append(dict(params))
            if "page_token" not in params:
                return {"bars": [self.row("2026-11-17T14:31:00Z"),self.row()], "next_page_token": "next"}
            return {"bars": [self.row("2026-11-17T14:31:00Z",c=150.75)], "next_page_token": None}
        bars, meta = m.retrieve(30,"x","y",now=self.now,fetch=fetch)
        self.assertEqual([b['time'] for b in bars],sorted(b['time'] for b in bars))
        self.assertEqual(len(bars), 2)
        self.assertEqual(bars[-1]['close'],150.75)
        self.assertEqual(meta['duplicates_replaced'],1)
        self.assertEqual(seen[1]['page_token'], 'next')
        self.assertEqual(seen[0]['feed'], 'iex')

    def test_repeated_page_token_stops(self):
        def fetch(params, k, s):
            return {"bars":[],"next_page_token":"same"}
        with self.assertRaises(m.DownloadError): m.retrieve(30,"k","s",now=self.now,fetch=fetch)

    def test_no_secrets_in_output(self):
        with tempfile.TemporaryDirectory() as d:
            keypath=Path(d)/'secret.txt'
            keypath.write_text('Endpoint\nhttps://paper-api.alpaca.markets\nKey\nPKTEST0000\nSecret\nTESTSECRET99\n')
            self.assertEqual(m.read_credentials(keypath),('PKTEST0000','TESTSECRET99'))
            bars=[m.normalize_bar(self.row())]
            file,meta=m.save_output(bars,{'note':'read only'},Path(d)/'hist',timestamp='test')
            self.assertEqual(file.read_text(encoding='utf-8-sig').splitlines()[0],','.join(m.FIELDS))
            self.assertNotIn('TESTSECRET99',file.read_text()+meta.read_text())

    def test_dry_run_does_not_call_keys(self):
        with patch.object(m, 'read_credentials',side_effect=AssertionError('read keys')):
            rc=m.main(['--days','30','--dry-run'])
            self.assertEqual(rc,0)

    def test_401_no_response_echo(self):
        def opener(req,timeout=None):
            raise HTTPError('safe',401,'Unauthorized',{},io.BytesIO(b'{"secret":"LEAK"}'))
        with self.assertRaises(m.DownloadError) as cm:
            m._request_json({},'SECRET_KEY','SECRET2',opener=opener,sleeper=lambda x:None)
        self.assertNotIn('LEAK',str(cm.exception))
        self.assertNotIn('SECRET_KEY',str(cm.exception))

    def test_429_retries(self):
        counter={'n':0}
        class Res:
            def __enter__(self):return self
            def __exit__(self,*args):return None
            def read(self,limit=None):return b'{"bars":[],"next_page_token":null}'
        def opener(req, timeout=None):
            counter['n']+=1
            if counter['n']==1: raise HTTPError('safe',429,'Rate limit',{},None)
            return Res()
        x=m._request_json({},'KEY','SECRET',opener=opener,sleeper=lambda x:None)
        self.assertEqual(x['bars'],[])
        self.assertEqual(counter['n'],2)

    def test_no_original_file_mutation(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            cache=root/'cache'/'alpaca_iex_nvda.json';cache.parent.mkdir()
            cache.write_text('KEEP_ORIGINAL')
            new,meta=m.save_output([m.normalize_bar(self.row())],{'version':'test'},root/'auditoria'/'historico')
            self.assertEqual(cache.read_text(),'KEEP_ORIGINAL')
            self.assertTrue(new.exists() and meta.exists())


if __name__=='__main__':
    unittest.main(verbosity=2)
