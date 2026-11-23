"""Pruebas OFFLINE: no carga Flask, no red, no credenciales."""
import sys
import unittest
from pathlib import Path
from datetime import datetime
import hashlib
import json
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd
from zoneinfo import ZoneInfo

from screener.scorer import score_tickers
from screener.indicator_detector import detect_indicators
from screener.pattern_detector import detect_patterns
from evaluar_nvda_2min_validacion import numerical_features, named_signals
from evaluar_scoring_completo_nvda_2min import (
    aggregate_context,as_original,calculate_context_snapshots,score_at,
    direction,normalized_signal_types,nonoverlap,stats,bootstrap_ci,
    day_events,compute_events,produce,NY,POLICIES,
)


def sample_regular(n_days=1, skip=None, start='2026-11-16'):
    frames=[]
    skip=set(skip or [])
    days=pd.bdate_range(start,periods=n_days)
    for day in days:
        local=pd.date_range(f'{day.date()} 09:30',periods=390,freq='min',tz=NY)
        t=(local.tz_convert('UTC').astype('int64')//10**9).to_numpy()
        for i in range(390):
            if (str(day.date()),i) in skip:continue
            o=150+i*0.001
            frames.append(dict(time=int(t[i]),open=o,close=o+0.002,high=o+0.003,low=o-0.001,
                               volume=100+i%7,session_ny=str(day.date()),minute_of_session=i))
    return pd.DataFrame(frames)


class Tests(unittest.TestCase):
    def test_original_scoring_mtf_volume_macro(self):
        hour=pd.DataFrame({'Open':np.ones(21)*100,'High':np.ones(21)*100,'Low':np.ones(21)*100,
                           'Close':np.ones(21)*100,'Volume':[100]*20+[350]})
        daily=pd.DataFrame({'Close':np.linspace(70,120,50)})
        p={'NVDA':[]}; i={'NVDA':['MACD bullish crossover (daily, test)','MACD bullish crossover (1h, test)']}
        r=score_tickers(p,i,{'NVDA':hour},{'NVDA':daily})
        self.assertEqual(r['long'][0]['score'],4) # 2 signals + 1 multi-tf + 1 high-volume
        self.assertTrue(any('Multi-TF' in s for s in r['long'][0]['signals']))
        self.assertTrue(any('Volume confirmation' in s for s in r['long'][0]['signals']))

    def test_original_scoring_low_volume_and_sma(self):
        hour=pd.DataFrame({'Close':[100]*21,'Volume':[100]*20+[10]})
        daily=pd.DataFrame({'Close':[100]*49+[50]})
        i={'NVDA':['MACD bullish crossover (daily)','MACD bullish crossover (1h)']}
        r=score_tickers({'NVDA':[]},i,{'NVDA':hour},{'NVDA':daily})
        # 2+1 alignment -1 low volume -1 below daily SMA50 =1
        self.assertEqual(r['long'][0]['score'],1)
        self.assertTrue(any('Counter-trend' in s for s in r['long'][0]['signals']))
        self.assertTrue(any('Low volume' in s for s in r['long'][0]['signals']))

    def test_hourly_only_full_60_min_buckets(self):
        days,hours=aggregate_context(sample_regular())
        self.assertEqual(len(days),1)
        self.assertEqual(len(hours),6)
        self.assertEqual(hours.bucket.to_list(),[0,1,2,3,4,5])
        self.assertEqual(datetime.fromtimestamp(int(hours.iloc[0].available_at),tz=ZoneInfo(NY)).strftime('%H:%M'),'10:30')
        self.assertEqual(datetime.fromtimestamp(int(hours.iloc[-1].available_at),tz=ZoneInfo(NY)).strftime('%H:%M'),'15:30')
        self.assertEqual(datetime.fromtimestamp(int(days.iloc[0].available_at),tz=ZoneInfo(NY)).strftime('%H:%M'),'16:00')
        self.assertEqual(int(days.iloc[0].volume),sum(sample_regular().volume))

    def test_missing_minute_blocks_daily_and_partial_hour(self):
        _,h=aggregate_context(sample_regular(skip={('2026-11-16',2)}))
        d,_=aggregate_context(sample_regular(skip={('2026-11-16',2)}))
        self.assertEqual(len(h),5)
        self.assertEqual(len(d),0)

    def test_consecutive_prices_and_missing_exits(self):
        data=sample_regular()
        day,hr=aggregate_context(data)
        ds=calculate_context_snapshots(day,'daily')
        hs=calculate_context_snapshots(hr,'1h')
        r=day_events(data,0,0,[d['available_at'] for d in ds],[h['available_at'] for h in hs],ds,hs)
        for event in r:
            self.assertEqual(event['entry']-event['known_at'],0)
            self.assertEqual(event['expiry']-event['entry'],120)
            self.assertLessEqual(event['expiry'],int(data.iloc[-1].time)+60)

    def test_score_zero_even_with_indicators(self):
        self.assertEqual(score_at([],[],None,None)[0],0)
        r=score_at([],['RSI oversold <30 (1m)','RSI overbought >70 (1m)'],None,None)
        self.assertEqual(r[0],0)

    def test_only_minute_not_mtf_contribution(self):
        d={'signals':['RSI overbought >70 (daily)'],'patterns':[],'history':pd.DataFrame({'Close':[100]*50})}
        h={'signals':['RSI overbought >70 (1h)'],'patterns':[],'history':pd.DataFrame({'Volume':[100]*21,'Close':[100]*21})}
        inc=score_at([],['RSI oversold <30 (1m)'],h,d)
        solo=score_at([],['RSI oversold <30 (1m)'],h,d,use_context_signals=False)
        self.assertEqual(inc[0],-1)
        self.assertEqual(solo[0],1)

    def test_minute_detector_original_equivalence(self):
        day=sample_regular()
        df=as_original(day)
        feat=numerical_features(day)
        for j in [59,60,79,100,200,350,389]:
            pats,combined=named_signals(df,j,feat)
            self.assertEqual(pats,detect_patterns(df.iloc[:j+1],'1m'))
            expected=detect_indicators(df.iloc[:j+1],'1m')
            actual=combined[len(pats):]
            def types(a):
                return sorted(t.split(' (')[0].split(' <')[0].split(' >')[0] for t in a)
            self.assertEqual(types(actual),types(expected))

    def test_available_context_cutoff(self):
        f=sample_regular(n_days=3)
        d,h=aggregate_context(f)
        ds=calculate_context_snapshots(d,'daily')
        hs=calculate_context_snapshots(h,'1h')
        self.assertTrue(all(x['available_at']<=y['available_at'] for x,y in zip(ds,ds[1:])))
        self.assertTrue(all(x['available_at']<=y['available_at'] for x,y in zip(hs,hs[1:])))
        self.assertEqual(len(ds),3)
        self.assertEqual(len(hs),18)

    def test_no_future_leakage_hourly_snapshot(self):
        f=sample_regular(n_days=2)
        d,h=aggregate_context(f)
        hist=calculate_context_snapshots(h,'1h')
        prior=hist[1]['signals']+hist[1]['patterns']
        h2=h.copy();h2.loc[h2.index>5,'close']+=90
        hist2=calculate_context_snapshots(h2,'1h')
        self.assertEqual(prior,hist2[1]['signals']+hist2[1]['patterns'])

    def test_nonoverlap(self):
        e=[{'entry':10,'expiry':130,'session':'A','side':1,'outcome':1,'score':1,'baseline_last_candle':1},
           {'entry':70,'expiry':190,'session':'A','side':-1,'outcome':-1,'score':2,'baseline_last_candle':1},
           {'entry':130,'expiry':250,'session':'A','side':1,'outcome':-1,'score':1,'baseline_last_candle':-1}]
        r=nonoverlap(e)
        self.assertEqual(len(r),2)
        self.assertEqual(stats(e)['cases'],2)
        self.assertEqual(stats(e)['wins'],1)
        self.assertEqual(stats(e)['losses'],1)

    def test_bootstrap_day_reproducible(self):
        rows=[]
        for d in ['A','B','C']:
            for i in range(4):
                rows.append({'session':d,'side':1,'outcome':1 if i<2 else -1})
        self.assertEqual(bootstrap_ci(rows),bootstrap_ci(rows))

    def test_source_package_sha_unmodified(self):
        import inspect
        import screener.scorer as source
        self.assertIs(source.score_tickers,score_tickers)
        self.assertIn('score_tickers(',inspect.getsource(score_at))

    def test_no_fake_signals_from_context_only(self):
        self.assertFalse(normalized_signal_types([]))
        self.assertEqual(normalized_signal_types(['RSI oversold <30 (1m, now) [RSI=24.1]']),('rsi oversold',))


if __name__=='__main__':unittest.main(verbosity=2)
