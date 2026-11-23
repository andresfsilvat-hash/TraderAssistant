"""Pruebas OFFLINE sin API, sin acceso a secretos, sin modificar proyecto."""
from __future__ import annotations
import json
from pathlib import Path
import sys
import tempfile
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import unittest
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evaluar_nvda_2min_validacion import (
    FAMILIES, MIN_WARMUP_BARS, NY, bootstrap_days, candidate_directions,
    collect_events, compute_metrics, directional, named_signals,
    nonoverlap, numerical_features, run, validate_input, delayed_entry_sensitivity,
)
from screener.indicator_detector import detect_indicators
from screener.pattern_detector import detect_patterns


def sample(day=(2026,11,17), n=180):
    begin=datetime(*day,9,30,tzinfo=NY)
    rows=[]
    for i in range(n):
        price=100 + (i%50)*.015 + ((i%7)-3)*.005
        rows.append(dict(time=int((begin+timedelta(minutes=i)).timestamp()),
                         open=price, high=price+.1, low=price-.1,
                         close=price+.03 if i%2 else price-.02,
                         volume=1000, session_ny=begin.date().isoformat(),
                         minute_of_session=i))
    return pd.DataFrame(rows)

class OfflineTests(unittest.TestCase):
    def test_validate_regular_and_extended(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'test.csv'
            sample().drop(columns=['session_ny','minute_of_session']).to_csv(p,index=False)
            data,q=validate_input(p)
            self.assertEqual(len(data),180)
            self.assertEqual(q['minutos_faltantes_regular'],210)

    def test_validate_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'test.csv'
            d=sample().drop(columns=['session_ny','minute_of_session'])
            pd.concat([d,d.iloc[:1]]).to_csv(p,index=False)
            with self.assertRaises(ValueError):validate_input(p)

    def test_bars_outside_regular_filtered(self):
        d=sample().copy();d.loc[0,'time']-=3600
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'test.csv'
            d.drop(columns=['session_ny','minute_of_session']).sort_values('time').to_csv(p,index=False)
            out,q=validate_input(p)
            self.assertEqual(len(out),179)
            self.assertEqual(q['velas_fuera_sesion'],1)

    def test_patterns_reused_unmodified(self):
        d=sample();features=numerical_features(d)
        hist=pd.DataFrame({k.capitalize():d[k].to_numpy() for k in ('open','high','low','close','volume')},
                          index=pd.to_datetime(d.time,unit='s',utc=True))
        for pos in [59,60,89,120,178]:
            a,_=named_signals(hist,pos,features)
            b=detect_patterns(hist.iloc[:pos+1],'1m')
            self.assertEqual(a,b)

    def test_indicator_signals_match_original(self):
        d=sample();features=numerical_features(d)
        hist=pd.DataFrame({k.capitalize():d[k].to_numpy() for k in ('open','high','low','close','volume')},
                          index=pd.to_datetime(d.time,unit='s',utc=True))
        for pos in [59,65,88,100,123,160]:
            _, signals=named_signals(hist,pos,features)
            originals=detect_indicators(hist.iloc[:pos+1],'1m')
            def head(s):
                return s.split(' (')[0]
            self.assertEqual(sorted(head(s) for s in signals if 'MACD' in s or 'BB' in s or 'RSI' in s),
                             sorted(head(s) for s in originals))

    def test_no_future_leakage(self):
        a=sample();b=sample();b.loc[120:,'close']=b.loc[120:,'close']+.02
        f1=numerical_features(a);f2=numerical_features(b)
        for k in ['rsi','macd_hist','bb_pct_b']:
            self.assertEqual(float(f1.loc[100,k]),float(f2.loc[100,k]))

    def test_no_overlap(self):
        rows=[dict(session='a',entry=i*60,expiry=i*60+120, outcome=1,
                   rsi_extreme=1,baseline_last_candle=1) for i in range(10)]
        sampled=nonoverlap(rows,'rsi_extreme')
        self.assertEqual(len(sampled),5)
        self.assertTrue(all(b['entry'] >= a['expiry'] for a,b in zip(sampled,sampled[1:])))

    def test_no_overlap_per_family(self):
        rows=[dict(session='a',entry=i*60,expiry=i*60+120, rsi_extreme=1 if i%2 else 0,
                   macd_cross=-1 if i%2==0 else 0) for i in range(10)]
        self.assertEqual(len(nonoverlap(rows,'rsi_extreme')),5)
        self.assertEqual(len(nonoverlap(rows,'macd_cross')),5)

    def test_gapped_history_rejected_for_warmup(self):
        full=sample(n=160)
        gap=full[full.minute_of_session!=50].copy()
        rows,info=collect_events(gap)
        self.assertGreater(info['skipped_gaps'],0)
        self.assertTrue(all(r['signal_time'] >= int(gap[gap.minute_of_session>=110].iloc[0].time) for r in rows))

    def test_expected_proxy_expiry(self):
        rows,_=collect_events(sample(n=160))
        self.assertGreater(len(rows),0)
        self.assertTrue(all(r['expiry']-r['entry']==120 for r in rows))
        self.assertTrue(all(r['entry']-r['signal_time']==60 for r in rows))

    def test_no_signals_by_default(self):
        self.assertEqual(directional([]),0)
        self.assertEqual(directional(['Hammer (1m)','Shooting Star (1m)']),0)

    def test_comparable_baseline(self):
        fake=[dict(entry=60,expiry=180,session='a', rsi_extreme=-1,outcome=-1,baseline_last_candle=0),
              dict(entry=180,expiry=300,session='a',rsi_extreme=1,outcome=-1,baseline_last_candle=-1)]
        m=compute_metrics(fake,'rsi_extreme')
        self.assertEqual(m['accuracy'],50)
        self.assertEqual(m['compared_last_candle_n'],1)
        self.assertEqual(m['accuracy_matched_last_candle'],0)
        self.assertEqual(m['last_candle_accuracy_matched'],100)

    def test_bootstrap_reproducible(self):
        rows=[dict(session=str(i//4),entry=i*120,expiry=i*120+120, rsi_extreme=1,
                   outcome=1 if i%3 else -1) for i in range(40)]
        a=bootstrap_days(rows,'rsi_extreme');b=bootstrap_days(rows,'rsi_extreme')
        self.assertEqual(a,b)
        self.assertEqual(a['days'],10)

    def test_delayed_entry_does_not_change_horizon(self):
        d=sample(n=160)
        r=dict(session='2026-11-17',entry=int(d.iloc[100].time),
               expiry=int(d.iloc[102].time),baseline_last_candle=1,
               rsi_extreme=1,outcome=1)
        m=delayed_entry_sensitivity(d,[r],'rsi_extreme')
        self.assertEqual(m['n'],1)
        self.assertEqual(m['delay_minutes'],1)
        self.assertEqual(m['excluded_due_to_missing_or_close'],0)

    def test_selection_ignores_future_outcomes(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            dates=['2026-11-02','2026-11-03','2026-11-04']
            dummy=pd.DataFrame({'session_ny':dates,'time':[1,2,3],'open':[1,2,3]})
            def create_events(test_outcome):
                rows=[]
                for d, date in enumerate(dates):
                    for i in range(50):
                        entry=(d*100+i)*120
                        props=dict(session=date,signal_time=entry-60,entry=entry,
                                   expiry=entry+120,price_entry=100.,price_expiry=100.,
                                   outcome=1 if d<2 else test_outcome,baseline_last_candle=1,
                                   rsi=20.,macd_hist=0.1,bb_pct_b=.5,minute_ny=i,
                                   signals='RSI oversold (1m)')
                        props.update({family:(1 if family=='rsi_extreme' else -1 if family=='macd_cross' else 0)
                                      for family in FAMILIES})
                        rows.append(props)
                return rows,{}
            with patch('evaluar_nvda_2min_validacion.validate_input',
                       return_value=(dummy,dict(sha256='abc',velas_recibidas=3,velas_regular=3,dias=3,minutos_faltantes_regular=0))):
                with patch('evaluar_nvda_2min_validacion.collect_events',return_value=create_events(-1)):
                    first=run(root/'does-not-matter.csv',root/'out1',train_days=2)
                with patch('evaluar_nvda_2min_validacion.collect_events',return_value=create_events(1)):
                    second=run(root/'does-not-matter.csv',root/'out2',train_days=2)
            self.assertEqual(first['selected_only_from_training'],'rsi_extreme')
            self.assertEqual(first['selected_only_from_training'],second['selected_only_from_training'])
            self.assertNotEqual(first['test']['rsi_extreme']['accuracy'],second['test']['rsi_extreme']['accuracy'])

    def test_run_leaves_source_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'source.csv'
            all_days=[sample(day=(2026,11,2+i),n=95) for i in range(3)]
            # Keep all dates valid Mon-Fri in Nov 2026.
            all_days=[sample(day=(2026,11,2),n=95),sample(day=(2026,11,3),n=95),sample(day=(2026,11,4),n=95)]
            data=pd.concat(all_days).drop(columns=['session_ny','minute_of_session'])
            data.to_csv(p,index=False);before=p.read_bytes()
            result=run(p,root/'out',train_days=2)
            self.assertEqual(p.read_bytes(),before)
            self.assertTrue((root/'out'/'resumen_validacion_nvda.json').exists())
            self.assertTrue((root/'out'/'eventos_validacion_nvda.csv').exists())
            self.assertEqual(result['recommendation'].split(':')[0],'ESPERAR')
            self.assertEqual(result['split']['test_sessions'],1)

if __name__ == '__main__':unittest.main(verbosity=2)
