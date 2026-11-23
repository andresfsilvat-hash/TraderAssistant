"""Experimento OFFLINE, solo lectura: scorer ORIGINAL Daily/1h y adaptación a 1m.

No genera órdenes ni señales operativas en vivo. La apertura de la vela siguiente
es un proxy retrospectivo, no un precio garantizado de ejecución/IQ Option.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import Counter
from datetime import datetime
from pathlib import Path
import csv
import hashlib
import json
import math
import sys

import numpy as np
import pandas as pd
import ta

from screener.indicator_detector import detect_indicators, MACD_FAST, MACD_SLOW, MACD_SIGNAL, RSI_PERIOD, RSI_OVERSOLD, RSI_OVERBOUGHT, BB_PERIOD, BB_STD
from screener.pattern_detector import detect_patterns
from screener.scorer import score_tickers
from evaluar_nvda_2min_validacion import validate_input, numerical_features, named_signals, bootstrap_days

NY = 'America/New_York'
VERSION = '1.0.0'
TRAIN_DAYS = 40
MIN_WARMUP = 60
POLICIES = ('original_daily_1h_cambio', 'completo_1m_disparador', 'solo_1m_con_filtros')
TICKER = 'NVDA'


def as_original(df):
    """Copia OHLCV con esquema del screener, index UTC para detectores."""
    result = df.rename(columns={'open':'Open','high':'High','low':'Low','close':'Close','volume':'Volume'})
    result = result[['Open','High','Low','Close','Volume']].copy()
    result.index = pd.to_datetime(df['time'].to_numpy(dtype='int64'), unit='s', utc=True)
    return result


def aggregate_context(regular):
    """Genera velas DIARIAS/1H usando solo buckets completamente cerrados.

    Las velas daily se vuelven visibles a las 16:00 NY del día; las 1h en
    10:30,11:30,...15:30 NY. El bloque final de 30m NO es 1h.
    """
    day_raw, hour_raw = [], []
    for day, frame in regular.groupby('session_ny', sort=True):
        frame = frame.sort_values('time')
        minute = frame['minute_of_session'].astype(int)
        def aggregate(chunk):
            first, last = chunk.iloc[0], chunk.iloc[-1]
            return {'time':int(first.time),'open':float(first.open),'high':float(chunk.high.max()),
                    'low':float(chunk.low.min()),'close':float(last.close),'volume':float(chunk.volume.sum()),
                    'session_ny':day}
        # Full regular session only (no partial Daily candle)
        if len(frame) == 390 and np.array_equal(minute.to_numpy(),np.arange(390)):
            d = aggregate(frame)
            d['available_at'] = int(frame.iloc[-1].time) + 60
            day_raw.append(d)
        for bucket in range(6):
            start=bucket*60; end=start+60
            part=frame[(minute >= start)&(minute<end)]
            if len(part)==end-start and np.array_equal(part['minute_of_session'].to_numpy(dtype=int),np.arange(start,end)):
                h=aggregate(part)
                h['available_at']=int(part.iloc[-1].time)+60
                h['bucket']=bucket
                hour_raw.append(h)
    return pd.DataFrame(day_raw),pd.DataFrame(hour_raw)


def calculate_context_snapshots(frame, timeframe):
    """Un llamado real a detect_indicators/detect_patterns por vela cerrada."""
    if len(frame)==0: return []
    all_df=as_original(frame)
    out=[]
    for j in range(len(frame)):
        hist=all_df.iloc[:j+1]
        # Solo se procesa al cerrar cada vela del timeframe respectivo.
        signals=detect_indicators(hist,timeframe)
        patterns=detect_patterns(hist,timeframe)
        out.append({'available_at':int(frame.iloc[j].available_at),
                    'signals':signals, 'patterns':patterns,'history':hist,
                    'count':j+1, 'time':int(frame.iloc[j].time)})
    return out


def normalized_signal_types(signals):
    """Evita confundir fecha/RSI numérico con cambio real de tipo de señal."""
    return tuple(sorted(s.split(' (')[0].split(' <')[0].split(' >')[0].lower().strip() for s in signals))


def direction(ranked):
    if ranked['long']: return 1, int(ranked['long'][0]['score']),ranked['long'][0]
    if ranked['short']: return -1,int(ranked['short'][0]['score']),ranked['short'][0]
    return 0, 0,None


def score_at(min_patterns,min_indicators,hour_snapshot,day_snapshot, *, use_context_signals=True):
    p=list(min_patterns); inds=list(min_indicators)
    if use_context_signals:
        if hour_snapshot:
            p += hour_snapshot['patterns']; inds += hour_snapshot['signals']
        if day_snapshot:
            p += day_snapshot['patterns']; inds += day_snapshot['signals']
    hd={TICKER:hour_snapshot['history']} if hour_snapshot else {}
    dd={TICKER:day_snapshot['history']} if day_snapshot else {}
    ranked=score_tickers({TICKER:p}, {TICKER:inds}, hd, dd)
    return direction(ranked)


def day_events(day, day_snapshot_idx, hour_snapshot_idx, day_starts, hour_starts, day_snapshots, hour_snapshots):
    times=day.time.to_numpy(dtype=np.int64)
    idx_by_t={int(t):i for i,t in enumerate(times)}
    f=numerical_features(day)
    raw=as_original(day)
    candidates=[]
    previous_minute_types=()
    previous_orig_dir=0
    for i in range(len(day)):
        minute_start=int(times[i]); close_at=minute_start+60
        # Contexto exterior solo si está CERRADO antes de que la señal exista
        dpos=bisect_right(day_starts,close_at)-1
        hpos=bisect_right(hour_starts,close_at)-1
        daily=day_snapshots[dpos] if dpos>=0 else None
        hourly=hour_snapshots[hpos] if hpos>=0 else None
        is_warm=(i>=MIN_WARMUP-1 and int(times[i])-int(times[i-(MIN_WARMUP-1)]) == (MIN_WARMUP-1)*60)
        if not is_warm:
            previous_minute_types=()
            previous_orig_dir=0
            continue
        patterns,signals=named_signals(raw,i,f)
        # named_signals incluye patrones en la lista; scorer requiere separarlos
        indicators=signals[len(patterns):]
        sig_types=normalized_signal_types(signals)
        fresh=bool(sig_types and sig_types!=previous_minute_types)
        previous_minute_types=sig_types
        # Tres políticas predefinidas. scorer.py NO se modifica.
        orig_dir,orig_score,orig_result=score_at([],[],hourly,daily)
        orig_new=bool(orig_dir and orig_dir != previous_orig_dir)
        previous_orig_dir=orig_dir
        full_dir=full_score=only_dir=only_score=0
        full_result=only_result=None
        if fresh:
            full_dir,full_score,full_result=score_at(patterns,indicators,hourly,daily)
            only_dir,only_score,only_result=score_at(patterns,indicators,hourly,daily,use_context_signals=False)
        # La vela señal de 1m inicia en minute_start y CIERRA en close_at.
        # Proxy de entrada es open de vela siguiente en close_at.
        # Vencimiento 2 minutos después, open de bucket minute_start+180.
        if (not fresh and not orig_new): continue
        j=idx_by_t.get(close_at)
        k=idx_by_t.get(close_at+60)
        l=idx_by_t.get(close_at+120)
        if None in (j,k,l): continue
        if int(day.iloc[i].minute_of_session)>386: continue
        price_entry=float(day.iloc[j].open)
        price_exit=float(day.iloc[l].open)
        outcome=int(np.sign(price_exit-price_entry))
        candle=int(np.sign(float(day.iloc[i].close)-float(day.iloc[i].open)))
        policies={
            POLICIES[0]:(orig_dir if orig_new else 0,orig_score,orig_result),
            POLICIES[1]:(full_dir if fresh else 0,full_score,full_result),
            POLICIES[2]:(only_dir if fresh else 0,only_score,only_result),
        }
        # Un evento por política, todos comparten el mismo precio y horizonte
        for key,(side,score,result) in policies.items():
            if side==0: continue
            pieces=(result or {}).get('signals',[])
            candidates.append({
                'session':str(day.iloc[i].session_ny),'strategy':key,'signal_time':minute_start,
                'known_at':close_at,'entry':close_at,'expiry':close_at+120,
                'entry_price':price_entry,'expiry_price':price_exit,'outcome':outcome,
                'side':int(side),'score':int(score),'baseline_last_candle':candle,
                'daily_context_time':int(daily['available_at']) if daily else None,
                'hourly_context_time':int(hourly['available_at']) if hourly else None,
                'min_signals':' | '.join(signals),'score_reasons':' | '.join(pieces),
                'rsi':round(float(f.iloc[i].rsi),4),
                'macd_hist':round(float(f.iloc[i].macd_hist),7),
                'bb_pct_b':round(float(f.iloc[i].bb_pct_b),5),
                'minute_ny':int(day.iloc[i].minute_of_session),
                'daily_bars_available':int(daily['count']) if daily else 0,
                'hourly_bars_available':int(hourly['count']) if hourly else 0,
                'fully_warmed_macro':bool(daily and daily['count']>=50 and hourly and hourly['count']>=40),
            })
    return candidates


def compute_events(regular):
    days,hours=aggregate_context(regular)
    ds=calculate_context_snapshots(days,'daily')
    hs=calculate_context_snapshots(hours,'1h')
    dts=[d['available_at'] for d in ds]; hts=[h['available_at'] for h in hs]
    rows=[]
    for ix,(name,day) in enumerate(regular.groupby('session_ny',sort=True)):
        rows.extend(day_events(day.reset_index(drop=True),ix,ix,dts,hts,ds,hs))
    rows.sort(key=lambda r:(r['entry'],r['strategy']))
    return rows,{'daily_complete_bars':len(days),'hourly_complete_bars':len(hours),
                 'daily_signal_snapshots':len(ds),'hourly_signal_snapshots':len(hs)}


def nonoverlap(rows):
    selected=[]; last_expiry=-1
    for r in sorted(rows,key=lambda x:x['entry']):
        if r['entry']<last_expiry: continue
        selected.append(r);last_expiry=r['expiry']
    return selected


def stats(rows):
    chosen=nonoverlap(rows)
    n=len(chosen)
    wins=sum(r['side']==r['outcome'] for r in chosen)
    ties=sum(r['outcome']==0 for r in chosen)
    up=sum(r['outcome']==1 for r in chosen)
    last_valid=[r for r in chosen if r['baseline_last_candle']]
    b_wins=sum(r['baseline_last_candle']==r['outcome'] for r in last_valid)
    paired_wins=sum(r['side']==r['outcome'] for r in last_valid)
    return {'cases':n,'wins':wins,'losses':n-wins-ties,'ties':ties,
            'accuracy_pct':round(100*wins/n,2) if n else None,
            'always_sube_same_cases_pct':round(100*up/n,2) if n else None,
            'paired_last_candle_n':len(last_valid),
            'paired_scorer_accuracy_pct':round(100*paired_wins/len(last_valid),2) if last_valid else None,
            'paired_last_candle_accuracy_pct':round(100*b_wins/len(last_valid),2) if last_valid else None,
            'unique_sessions':len(set(r['session'] for r in chosen)),
            'score_distribution':dict(sorted(Counter(abs(r['score']) for r in chosen).items())),
            'directions':{'sube':sum(r['side']>0 for r in chosen),'baja':sum(r['side']<0 for r in chosen)}}


def bootstrap_ci(chosen, reps=1500, seed=20261118):
    if not chosen: return None
    byday=[]
    for _,g in pd.DataFrame(chosen).groupby('session'):
        n=len(g); wins=int((g.side==g.outcome).sum()); up=int((g.outcome==1).sum());
        byday.append([n,wins,up])
    v=np.asarray(byday,dtype=float)
    rng=np.random.default_rng(seed)
    b=v[rng.integers(0,len(v),size=(reps,len(v)))].sum(axis=1)
    return {'accuracy_ci_95_pct':[round(float(x),2) for x in np.quantile(100*b[:,1]/b[:,0],[.025,.975])],
            'delta_vs_sube_ci_95_pp':[round(float(x),2) for x in np.quantile(100*(b[:,1]-b[:,2])/b[:,0],[.025,.975])]}


def produce(csv_path,outdir):
    regular,quality=validate_input(Path(csv_path))
    rows,ctx=compute_events(regular)
    days=sorted(regular.session_ny.unique()); train=set(days[:TRAIN_DAYS]); test=set(days[TRAIN_DAYS:])
    report={'version':VERSION,'input_file':Path(csv_path).name,'sha256':quality.pop('sha256'),
            'quality':quality,'context':ctx,'split':{'train_days':len(train),'test_days':len(test),
            'train_first':min(train),'train_last':max(train), 'test_first':min(test),'test_last':max(test)},
            'contract':{
              'source':'Alpaca IEX 1m; NO IQ Option','horizon_seconds':120,
              'entry_proxy':'open próxima vela 1m al cierre de señal, ejecución perfecta NO garantizada',
              'exit_proxy':'open vela en t+120 segundos','indicator_timeframes':'1m RTH, 1h RTH cerrada, daily RTH COMPLETA de sesiones anteriores',
              'original_scorer':'score_tickers importado SIN MODIFICAR',
              'policy_original':'scorer Daily+1h, entra solo cuando cambia de 0 o de lado; evita mantener señal cada minuto',
              'policy_full':'scorer Daily+1h+1m; requiere nueva señal 1m y resultado distinto de 0',
              'policy_minute':'scorer 1m, conservando confirmación volumen 1h y filtro SMA50 diario',
              'hour_definition':'solo bloques COMPLETOS de 60min desde 9:30 NY; el tramo 15:30-16:00 no se usa como 1h',
              'note':'resultados retrospectivos, último periodo ya estudiado antes, no validación ciega'},
            'strategies':{}}
    detailed=[]
    for key in POLICIES:
        st={}
        for period,allow in [('development',train),('later',test)]:
            relevant=[r for r in rows if r['strategy']==key and r['session'] in allow]
            sample=nonoverlap(relevant)
            st[period]=stats(relevant)
            st[period]['bootstrap_by_day']=bootstrap_ci(sample)
            st[period]['full_macro_context_only']=stats([r for r in relevant if r['fully_warmed_macro']])
            for r in sample:
                rr=dict(r);rr['period']=period; rr['correct']=int(rr['side']==rr['outcome']); detailed.append(rr)
        report['strategies'][key]=st
    outdir=Path(outdir);outdir.mkdir(parents=True,exist_ok=True)
    (outdir/'resultados_scoring_completo.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    with (outdir/'operaciones_no_solapadas.csv').open('w',newline='',encoding='utf-8-sig') as f:
        if detailed:
            writer=csv.DictWriter(f,fieldnames=list(detailed[0]));writer.writeheader();writer.writerows(detailed)
    return report, detailed


def main():
    p=argparse.ArgumentParser(description='Prueba OFFLINE del scoring original y adaptación 1m, horizonte 120s')
    p.add_argument('--csv',type=Path,required=True)
    p.add_argument('--output-dir',type=Path,default=Path('auditoria/scoring_completo_2min'))
    args=p.parse_args()
    report,_=produce(args.csv,args.output_dir)
    print('NVDA - scorer.py ORIGINAL reutilizado:')
    print('Daily completos:',report['context']['daily_complete_bars'],'1h completos:',report['context']['hourly_complete_bars'])
    for k,v in report['strategies'].items():
        a=v['development']; b=v['later']
        print(f"{k}: desarrollo {a['cases']} casos / {a['accuracy_pct']}%; posterior {b['cases']} casos / {b['accuracy_pct']}%; siempre SUBE mismos casos {b['always_sube_same_cases_pct']}%")
    print('Guardado en',args.output_dir.resolve())
    print('SOLO ESTUDIO RETROSPECTIVO IEX. NO VALIDADO PARA IQ OPTION. NO EMITE ENTRADAS OPERATIVAS.')

if __name__=='__main__':main()
