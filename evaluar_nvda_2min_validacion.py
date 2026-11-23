"""Experimento exclusivamente OFFLINE de señales IEX NVDA / horizonte nominal de 120 s.

No modifica TraderAssistant, no conecta servicios, no lee credenciales ni opera.
Recupera las 8 reglas de velas del detector original y los parámetros RSI/MACD/BB
originales; usa 'ta' para valores calculados de forma vectorizada por sesión.
La división cronológica y la selección se fijan antes de evaluar el bloque final.

La apertura de cada minuto es un PROXY de precio, no precio ejecutable en IQ Option.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import ta
from screener import indicator_detector as ind
from screener.pattern_detector import detect_patterns
from screener.scorer import _classify

NY = ZoneInfo('America/New_York')
EC = ZoneInfo('America/Guayaquil')
HORIZON = 120
MIN_WARMUP_BARS = 60
TRAIN_DAYS = 40  # primera parte cronológica, sin ajustar después de ver evaluación
MIN_TRAIN_EVENTS = 80
VERSION = 'offline-robust-2min-1.0'

FAMILIES = [
    'original_consensus',
    'rsi_extreme',
    'bb_reversion',
    'macd_cross',
    'candlestick_patterns',
    'rsi_macd_turn',
]


def validate_input(path: Path):
    with path.open('rb') as f:
        checksum = hashlib.file_digest(f, 'sha256').hexdigest()
    frame = pd.read_csv(path, encoding='utf-8-sig')
    required = {'time','open','high','low','close','volume'}
    if not required.issubset(frame.columns):
        raise ValueError('Faltan columnas OHLCV requeridas')
    if frame.isnull().any().any():
        raise ValueError('Valores vacíos')
    if frame.time.duplicated().any() or (frame.time % 60 != 0).any():
        raise ValueError('Duplicados o velas sin inicio de minuto exacto')
    if not frame.time.is_monotonic_increasing:
        raise ValueError('Las velas deben estar ordenadas temporalmente')
    for col in ['open','high','low','close','volume']:
        frame[col] = pd.to_numeric(frame[col], errors='raise')
        if not np.isfinite(frame[col].to_numpy()).all():
            raise ValueError(f'Valores no finitos: {col}')
    if (frame[['open','high','low','close']] <= 0).any().any() or (frame.volume < 0).any():
        raise ValueError('OHLCV negativo o cero')
    if (frame.high < frame[['open','close','low']].max(axis=1)).any() or (frame.low > frame[['open','close','high']].min(axis=1)).any():
        raise ValueError('OHLCV inconsistente')
    idx = pd.to_datetime(frame.time, unit='s', utc=True).dt.tz_convert(NY)
    mins = idx.dt.hour * 60 + idx.dt.minute
    active = (idx.dt.dayofweek < 5) & (mins >= 570) & (mins < 960)
    regular = frame.loc[active].copy().reset_index(drop=True)
    idx_regular = idx.loc[active].reset_index(drop=True)
    regular['session_ny'] = idx_regular.dt.strftime('%Y-%m-%d')
    regular['minute_of_session'] = (idx_regular.dt.hour * 60 + idx_regular.dt.minute - 570).to_numpy()
    info = {'sha256': checksum, 'velas_recibidas': len(frame),
            'velas_regular': len(regular), 'velas_fuera_sesion': int((~active).sum()),
            'velas_duplicadas': 0, 'dias': int(regular.session_ny.nunique()),
            'dias_faltantes_parciales': int((regular.groupby('session_ny').size() < 390).sum()),
            'minutos_faltantes_regular': int(sum(390 - n for n in regular.groupby('session_ny').size()))}
    return regular, info


def directional(signals):
    directions = {_classify(s) for s in signals} - {0}
    return (1 if directions == {1} else -1 if directions == {-1} else 0)


def numerical_features(day: pd.DataFrame):
    close = day['close'].astype(float)
    macd = ta.trend.MACD(close, window_slow=ind.MACD_SLOW,
                         window_fast=ind.MACD_FAST, window_sign=ind.MACD_SIGNAL)
    rsi = ta.momentum.RSIIndicator(close, window=ind.RSI_PERIOD).rsi()
    bb = ta.volatility.BollingerBands(close, window=ind.BB_PERIOD, window_dev=ind.BB_STD)
    out = day[['time','open','high','low','close','volume','session_ny','minute_of_session']].copy()
    out['rsi'] = rsi
    out['macd'] = macd.macd()
    out['macd_signal'] = macd.macd_signal()
    out['macd_hist'] = out.macd - out.macd_signal
    out['bb_low'] = bb.bollinger_lband()
    out['bb_high'] = bb.bollinger_hband()
    out['bb_pct_b'] = bb.bollinger_pband()
    out['body_pct'] = (out.close - out.open) / out.open * 100
    return out


def named_signals(history, pos, features):
    """Replica reglas de RSI, MACD y BB originales, reutiliza patrones originales."""
    candle = history.iloc[:pos+1]
    patterns = detect_patterns(candle, '1m')
    signals = list(patterns)
    p = features.iloc[pos]
    prv = features.iloc[pos-1]
    if pd.notna(p['macd_hist']) and pd.notna(prv['macd_hist']):
        if prv.macd_hist <= 0 < p.macd_hist:
            signals.append('MACD bullish crossover (1m)')
        if prv.macd_hist >= 0 > p.macd_hist:
            signals.append('MACD bearish crossover (1m)')
    if pd.notna(p.bb_low) and pd.notna(p.bb_high):
        if any(features.iloc[k].close < features.iloc[k].bb_low for k in [pos-2,pos-1]) and p.close > p.bb_low:
            signals.append('Lower BB mean-reversion (1m)')
        if any(features.iloc[k].close > features.iloc[k].bb_high for k in [pos-2,pos-1]) and p.close < p.bb_high:
            signals.append('Upper BB mean-reversion (1m)')
    if pd.notna(p.rsi):
        if p.rsi < ind.RSI_OVERSOLD:
            signals.append(f'RSI oversold <{ind.RSI_OVERSOLD} (1m) [RSI={p.rsi:.1f}]')
        elif p.rsi > ind.RSI_OVERBOUGHT:
            signals.append(f'RSI overbought >{ind.RSI_OVERBOUGHT} (1m) [RSI={p.rsi:.1f}]')
    return patterns, signals


def candidate_directions(patterns, signals, features, i):
    siglower = [s.lower() for s in signals]
    rsi = float(features.iloc[i].rsi)
    hist = float(features.iloc[i].macd_hist)
    prior_hist = float(features.iloc[i-1].macd_hist)
    sides = {
        'original_consensus': directional(signals),
        'rsi_extreme': 1 if rsi < 30 else -1 if rsi > 70 else 0,
        'bb_reversion': directional([s for s in signals if 'bb mean-reversion' in s.lower()]),
        'macd_cross': directional([s for s in signals if 'macd ' in s.lower()]),
        'candlestick_patterns': directional(patterns),
        # Regla adicional PREDEFINIDA: RSI extremo + giro en histograma MACD.
        'rsi_macd_turn': 1 if rsi < 30 and hist > prior_hist else
                         -1 if rsi > 70 and hist < prior_hist else 0,
    }
    return sides


def collect_events(df: pd.DataFrame):
    """Sin futuro en señales; solo para medir resultados usa 3 aperturas futuras contiguas."""
    candidates = []
    eligible = 0
    skipped_missing = 0
    count_by_day = {}
    for sess, original in df.groupby('session_ny', sort=True):
        day = original.reset_index(drop=True)
        dts = day.time.to_numpy(dtype=np.int64)
        features = numerical_features(day)
        hist = pd.DataFrame({col.capitalize(): day[col].to_numpy() for col in ('open','high','low','close','volume')},
                            index=pd.to_datetime(day.time, unit='s', utc=True))
        bytime = {int(ts): i for i,ts in enumerate(dts)}
        count_by_day[sess] = 0
        for i in range(MIN_WARMUP_BARS-1, len(day)-3):
            # Entry at t+1 minute, expiry at t+3 minutes.
            current = int(dts[i]); entry = current+60; expiry = current+180
            if int(day.iloc[i].minute_of_session) > 386:
                continue
            # Un vacío previo invalidaría el calentamiento continuo de 60 barras.
            if int(dts[i]) - int(dts[i-(MIN_WARMUP_BARS-1)]) != 60*(MIN_WARMUP_BARS-1):
                skipped_missing += 1
                continue
            idx1 = bytime.get(entry); idx2 = bytime.get(current+120); idx3 = bytime.get(expiry)
            if any(j is None for j in [idx1,idx2,idx3]):
                skipped_missing += 1
                continue
            eligible += 1
            patterns, sigs = named_signals(hist, i, features)
            sides = candidate_directions(patterns, sigs, features, i)
            ep = float(day.iloc[idx1].open)
            xp = float(day.iloc[idx3].open)
            if xp > ep: target = 1
            elif xp < ep: target = -1
            else: target = 0
            feature = features.iloc[i]
            baseline = 1 if day.iloc[i].close > day.iloc[i].open else -1 if day.iloc[i].close < day.iloc[i].open else 0
            candidates.append(dict(session=sess, signal_time=int(dts[i]), entry=entry, expiry=expiry,
                                   price_entry=ep, price_expiry=xp, outcome=target,
                                   baseline_last_candle=baseline, rsi=float(feature.rsi),
                                   macd_hist=float(feature.macd_hist), bb_pct_b=float(feature.bb_pct_b),
                                   minute_ny=int(day.iloc[i].minute_of_session),
                                   signals=' | '.join(sigs), **sides))
            count_by_day[sess] += 1
    return candidates, {'eligible_minutes':eligible, 'skipped_gaps':skipped_missing,
                        'eligible_by_session': count_by_day}


def nonoverlap(rows, strategy):
    """Métrica principal: un evento cada >=120 segundos por estrategia."""
    selected = []
    expires_at = -1
    for r in rows:
        if r[strategy] == 0 or r['entry'] < expires_at:
            continue
        selected.append(r)
        expires_at = r['expiry']
    return selected


def compute_metrics(rows, strategy):
    selected = nonoverlap(rows, strategy)
    n = len(selected)
    wins = sum(r[strategy] == r['outcome'] for r in selected)
    ties = sum(r['outcome'] == 0 for r in selected)
    base_up = sum(r['outcome'] == 1 for r in selected)
    matched = [r for r in selected if r['baseline_last_candle'] != 0]
    base_candle = sum(r['baseline_last_candle'] == r['outcome'] for r in matched)
    matched_wins = sum(r[strategy] == r['outcome'] for r in matched)
    return dict(n=n, wins=wins, losses=n-wins-ties, ties=ties,
                accuracy=100*wins/n if n else None,
                always_up_accuracy_same_events=100*base_up/n if n else None,
                compared_last_candle_n=len(matched),
                accuracy_matched_last_candle=100*matched_wins/len(matched) if matched else None,
                last_candle_accuracy_matched=100*base_candle/len(matched) if matched else None,
                coverage_pct=100*n/len(rows) if rows else None)



def delayed_entry_sensitivity(data, events, strategy, *, delay_minutes=1):
    """Escenario alternativo: entrada un minuto después, mismo horizonte nominal.

    No modela latencia real; usa primeras operaciones de buckets posteriores.
    """
    sample = nonoverlap(events, strategy)
    by_ts = {int(t): float(p) for t,p in zip(data.time, data.open)}
    observed = []
    for r in sample:
        start = int(r['entry']) + 60*delay_minutes
        stop = int(r['expiry']) + 60*delay_minutes
        # Prohíbe cruzar sesión y requiere el minuto intermedio.
        if start not in by_ts or start+60 not in by_ts or stop not in by_ts:
            continue
        d0=datetime.fromtimestamp(start,NY)
        d1=datetime.fromtimestamp(stop,NY)
        if d0.date()!=d1.date() or d1.hour>=16:
            continue
        entry,exit_=by_ts[start],by_ts[stop]
        outcome = 1 if exit_>entry else -1 if exit_<entry else 0
        observed.append(dict(session=r['session'], entry=start, expiry=stop,
                             outcome=outcome, baseline_last_candle=r['baseline_last_candle'],
                             **{strategy:r[strategy]}))
    # La muestra proviene de entradas originales no solapadas: la separación sigue siendo >=120s.
    result=compute_metrics(observed,strategy)
    result['delay_minutes']=delay_minutes
    result['original_selected_count']=len(sample)
    result['excluded_due_to_missing_or_close']=len(sample)-len(observed)
    return result


def bootstrap_days(rows, strategy, *, seed=20261118, reps=3000):
    """Intervalos descriptivos de exactitud / ventaja sobre siempre SUBE, remuestreo POR DÍA."""
    chosen = nonoverlap(rows, strategy)
    if len(chosen) < 1: return None
    byday = {}
    for r in chosen:
        counts = byday.setdefault(r['session'], [0,0,0])
        counts[0] += 1
        counts[1] += (r[strategy] == r['outcome'])
        counts[2] += (r['outcome'] == 1)
    mat = np.asarray(list(byday.values()), dtype=float)
    rng = np.random.default_rng(seed)
    pos = rng.integers(0, len(mat), size=(reps,len(mat)))
    boots = mat[pos].sum(axis=1)
    accuracies = 100*boots[:,1]/boots[:,0]
    deltas = 100*(boots[:,1]-boots[:,2])/boots[:,0]
    return dict(days=len(mat), accuracy_ci_95=[round(float(x),2) for x in np.quantile(accuracies,[.025,.975])],
                delta_vs_always_up_ci_95=[round(float(x),2) for x in np.quantile(deltas,[.025,.975])])


def run(csv_file:Path, output:Path, train_days=TRAIN_DAYS):
    data, quality = validate_input(csv_file)
    quality = dict(quality)
    days = sorted(data.session_ny.unique())
    if len(days) <= train_days:
        raise ValueError('No hay días suficientes para desarrollo y prueba cronológica')
    candidates, build = collect_events(data)
    train, test = [], []
    train_set = set(days[:train_days])
    for event in candidates:
        (train if event['session'] in train_set else test).append(event)
    training = {s:compute_metrics(train,s) for s in FAMILIES}
    test_metrics = {s:compute_metrics(test,s) for s in FAMILIES}
    # Selección solo usando entrenamiento. No filtra en prueba por porcentajes.
    viable = [s for s in FAMILIES if training[s]['n'] >= MIN_TRAIN_EVENTS]
    winner = max(viable, key=lambda s:(training[s]['accuracy'] - training[s]['always_up_accuracy_same_events'], -FAMILIES.index(s))) if viable else None
    ci = {s:bootstrap_days(test,s) for s in FAMILIES}
    delayed = delayed_entry_sensitivity(data,test,winner) if winner else None
    result = {'version':VERSION,'source_file':csv_file.name,'source_sha256':quality.pop('sha256'),
              'data_quality':quality, 'contract':{
                  'feed':'Alpaca IEX, no IQ Option', 'horizon_nominal_s':120,
                  'signal':'last complete one-minute candle, 60 candle intraday warmup',
                  'entry_proxy':'first IEX trade price in next minute bucket',
                  'exit_proxy':'first IEX trade price in minute bucket 120s after entry',
                  'closed_1min_delay_unmeasured':True,
                  'nonoverlap':'120s strategy-specific', 'tie_as_failure':True,
                  'pattern_source':'screener.pattern_detector.detect_patterns',
                  'indicator_parameters':'screener.indicator_detector',
                  'train_days':train_days,'selection_min_train_events':MIN_TRAIN_EVENTS},
              'split': {'train_first':days[0], 'train_last':days[train_days-1],
                        'test_first':days[train_days], 'test_last':days[-1],
                        'train_sessions':train_days, 'test_sessions':len(days)-train_days,
                        'training_eligible_minutes':len(train),'test_eligible_minutes':len(test)},
              'training':training,'selected_only_from_training':winner,
              'test':test_metrics,'test_cluster_bootstrap':ci,
              'test_delayed_60sec_proxy_selected':delayed,
              'future_trial_required': True, 'recommendation':'ESPERAR: ninguna regla confirmada para IQ Option',
              'limitations':[
                  'División cronológica retrospectiva: partes del historial ya fueron inspeccionadas anteriormente. No es validación ciega.',
                  'Datos IEX agregados por minuto, precio de apertura aproximado no necesariamente obtenible a tiempo.',
                  'La publicación de barra cerrada, órdenes, spreads y liquidación de NVIDIA Blitz son desconocidos.',
                  'Los resultados no modelan costos, cierres IQ, pago real ni automatización.',
                  'Se examinan seis familias de señales; comparaciones múltiples elevan falsos hallazgos.',
                  'Sólo 63 sesiones de un activo, sin prueba en periodos futuros.'
              ]}
    output.mkdir(parents=True, exist_ok=True)
    (output/'resumen_validacion_nvda.json').write_text(json.dumps(result, ensure_ascii=False,indent=2),encoding='utf-8')
    with (output/'eventos_validacion_nvda.csv').open('w',newline='',encoding='utf-8-sig') as f:
        fields=['session','signal_time','entry','expiry','price_entry','price_expiry',
                'outcome','baseline_last_candle','rsi','macd_hist','bb_pct_b','minute_ny',
                *FAMILIES,'signals','period']
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for name,subset in [('DESARROLLO',train),('PRUEBA_RETROSPECTIVA',test)]:
            for r in subset:
                w.writerow({**r,'period':name})
    report = generate_report(result)
    (output/'Informe_validacion_nvda_2min.md').write_text(report,encoding='utf-8')
    return result


def fmt(v):
    return '—' if v is None else f'{v:.2f} %'


def generate_report(r):
    sp=r['split']; q=r['data_quality']; k=r['selected_only_from_training']
    titles={'original_consensus':'Consenso original sin contradicciones',
            'rsi_extreme':'RSI original (<30 / >70)',
            'bb_reversion':'Reversión Bollinger original',
            'macd_cross':'Cruce MACD original',
            'candlestick_patterns':'Patrones japoneses originales',
            'rsi_macd_turn':'RSI extremo + giro histograma MACD (experimental)'}
    lines=['# TraderAssistant — Diagnóstico histórico NVDA, decisiones de 2 minutos',
           '', '**Estado: EXPLORATORIO; no apto para orientar entradas reales en IQ Option.**',
           '', '## Datos y trazabilidad',
           f"- Fuente: `{r['source_file']}`; SHA-256 `{r['source_sha256']}`.",
           f"- Velas totales: **{q['velas_recibidas']:,}**; dentro de sesión regular: **{q['velas_regular']:,}**.",
           f"- Sesiones: **{q['dias']}**; minutos regulares faltantes: **{q['minutos_faltantes_regular']}**.",
           f"- Desarrollo cronológico: **{sp['train_sessions']} sesiones** ({sp['train_first']} a {sp['train_last']}).",
           f"- Prueba retrospectiva posterior: **{sp['test_sessions']} sesiones** ({sp['test_first']} a {sp['test_last']}).",
           '- RSI (14), MACD (12,26,9), Bollinger (20,2) con parámetros originales y ocho patrones del detector ya existente.',
           '- Se descartan preapertura, postmercado, barras de la misma sesión con gaps y operaciones que cruzan 16:00 ET.',
           '- Se exige calentamiento de 60 velas dentro de cada sesión para evitar mezclar indicadores con saltos nocturnos.',
           '', '## Resultados — cada estrategia evaluada en sus propios eventos no solapados',
           '', '| Familia predefinida | Desarrollo: casos | Desarrollo: acierto | Prueba posterior: casos | Prueba posterior: acierto | Siempre SUBE en los mismos casos |',
           '|---|---:|---:|---:|---:|---:|']
    for name in FAMILIES:
        tr=r['training'][name]; te=r['test'][name]
        lines.append(f"| {titles[name]} | {tr['n']:,} | {fmt(tr['accuracy'])} | {te['n']:,} | {fmt(te['accuracy'])} | {fmt(te['always_up_accuracy_same_events'])} |")
    lines += ['',f"**Regla elegida exclusivamente por desempeño de desarrollo (mínimo {MIN_TRAIN_EVENTS} casos):** " + (titles[k] if k else 'Ninguna'),
              '', 'La selección sirve para una prueba retrospectiva, NO para recomendar operaciones. ',
              'La prueba posterior no fue realmente ciega porque el historial ya se revisó en la auditoría previa.',
              '', '## Regla seleccionada: comparación justa en prueba posterior', '']
    if k:
        test=r['test'][k]; boot=r['test_cluster_bootstrap'][k]
        lines += [f"- Casos no solapados: **{test['n']:,}**. Aciertos **{test['wins']:,}**, errores **{test['losses']:,}**, empates **{test['ties']:,}**.",
                  f"- Acierto: **{fmt(test['accuracy'])}** (intervalo bootstrap por sesiones 95 %: {boot['accuracy_ci_95'][0]}–{boot['accuracy_ci_95'][1]} %).",
                  f"- Comparador siempre SUBE, mismos casos: **{fmt(test['always_up_accuracy_same_events'])}**.",
                  f"- Diferencia frente a siempre SUBE, intervalo bootstrap de 95 %: **{boot['delta_vs_always_up_ci_95'][0]} a {boot['delta_vs_always_up_ci_95'][1]} puntos**.",
                  f"- Comparación última vela solo cuando ambos tienen dirección: {test['compared_last_candle_n']:,} casos; estrategia **{fmt(test['accuracy_matched_last_candle'])}**, última vela **{fmt(test['last_candle_accuracy_matched'])}**.",
                  f"- Cobertura en prueba (entradas no solapadas sobre minutos elegibles): **{fmt(test['coverage_pct'])}**."]
        later=r['test_delayed_60sec_proxy_selected']
        lines += ['', '**Sensibilidad al desplazamiento de la entrada 60 segundos adicionales:**',
                  f"- Casos con proxy alternativo disponible: **{later['n']}** de {later['original_selected_count']} (excluidos {later['excluded_due_to_missing_or_close']} por falta de datos o cierre).",
                  f"- Acierto proxy entrada tardía: **{fmt(later['accuracy'])}**; referencia siempre SUBE en esos mismos casos: **{fmt(later['always_up_accuracy_same_events'])}**.",
                  '- Este desplazamiento NO representa la latencia real observada: ilustra sensibilidad temporal con velas de 1 minuto.']
    lines += ['', '## Interpretación y límites',
              '- No puede inferirse el porcentaje de acierto en NVIDIA Blitz a partir de velas IEX.',
              '- La disponibilidad efectiva de cada vela puede ser posterior a su cierre; no se garantiza poder entrar al precio de apertura proxy.',
              '- Cada comparación con la referencia usa exactamente los mismos casos para evitar ventajas por selección de muestras.',
              '- Se reporta incertidumbre por sesión, no como si miles de velas del mismo día fueran independientes.',
              '- Elegir una regla por el resultado de desarrollo y observarla en fechas posteriores reduce parte del sesgo, pero no corrige el conocimiento previo del conjunto de datos.',
              '- Todavía faltan sesiones futuras, datos de precio de la plataforma destino y una prueba simulada sincronizada.',
              '', '**Decisión para la aplicación: ESPERAR. No habilitar SUBE/BAJA.**',
              '', '## Uso sin afectar el realtime',
              'Ejecutar únicamente con TraderAssistant cerrado para minimizar cargas. El script lee CSV local y módulos originales; no abre conexiones.',
              '```powershell',
              '.\\venv\\Scripts\\python.exe -B .\\evaluar_nvda_2min_validacion.py --csv ".\\auditoria\\historico_nvda_iex\\nvda_iex_1min_20261118_213505_280555.csv"',
              '```',
              'Produce un CSV por minuto con RSI, histograma MACD, %B y señales, además de JSON de métricas e informe. No cambia interfaz ni cachés.']
    return '\n'.join(lines)+'\n'


def main():
    p=argparse.ArgumentParser(description='Prueba histórica retrospectiva NVDA (solo OFFLINE)')
    p.add_argument('--csv',type=Path,required=True)
    p.add_argument('--output-dir',type=Path,default=Path('auditoria')/'validacion_nvda_2min')
    args=p.parse_args()
    results=run(args.csv,args.output_dir)
    key=results['selected_only_from_training']
    if key:
        m=results['test'][key]
        print(f'NVDA: {results["split"]["train_sessions"]} días desarrollo / {results["split"]["test_sessions"]} días prueba retrospectiva')
        print(f'Regla seleccionada en desarrollo: {key}')
        print(f'Prueba: {m["n"]} casos; {m["wins"]} aciertos, {m["losses"]} fallos, {m["ties"]} empates; {m["accuracy"]:.2f}%')
        print(f'Siempre SUBE sobre los mismos casos: {m["always_up_accuracy_same_events"]:.2f}%')
    print('Informe y registros:',args.output_dir.resolve())
    print('NO VALIDADO PARA IQ OPTION. RECOMENDACIÓN OPERATIVA: ESPERAR.')

if __name__=='__main__': main()
