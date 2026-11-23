#!/usr/bin/env python3
"""Evaluación cronológica offline del motor v2 sobre 63 sesiones NVDA IEX.

No abre red ni ejecuta órdenes. Las decisiones de cada fila usan únicamente
velas con marca temporal anterior o igual a la vela señal.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
import csv
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import random

import pandas as pd
import ta

from decision_engine_experimental import RULES_VERSION, SUPPORTED_HORIZONS, evaluate_hypothesis
from screener.pattern_detector import detect_patterns


NY_TZ = "America/New_York"
WARMUP = 50
TRAIN_SESSIONS = 42


def load_history(path):
    frame = pd.read_csv(path)
    required = {"time", "open", "high", "low", "close", "volume"}
    if not required.issubset(frame.columns):
        raise ValueError("CSV histórico sin columnas OHLCV requeridas")
    frame = frame[list(required)].copy()
    frame["timestamp"] = pd.to_datetime(frame["time"], unit="s", utc=True, errors="coerce")
    for name in ("open", "high", "low", "close", "volume"):
        frame[name] = pd.to_numeric(frame[name], errors="coerce")
    frame = frame.dropna().drop_duplicates("timestamp", keep="last").sort_values("timestamp")
    local = frame["timestamp"].dt.tz_convert(NY_TZ)
    minute = local.dt.hour * 60 + local.dt.minute
    frame = frame[(local.dt.weekday < 5) & (minute >= 570) & (minute < 960)].copy()
    frame["session"] = frame["timestamp"].dt.tz_convert(NY_TZ).dt.date.astype(str)
    return frame.reset_index(drop=True)


def add_features(frame):
    pieces = []
    for _, day in frame.groupby("session", sort=True):
        day = day.copy()
        close = day["close"]
        macd = ta.trend.MACD(close, window_slow=26, window_fast=12, window_sign=9)
        bb = ta.volatility.BollingerBands(close, window=20, window_dev=2)
        day["rsi"] = ta.momentum.RSIIndicator(close, window=14).rsi()
        day["macd"] = macd.macd(); day["macd_signal"] = macd.macd_signal()
        day["macd_hist"] = macd.macd_diff()
        day["bb_low"] = bb.bollinger_lband(); day["bb_mid"] = bb.bollinger_mavg()
        day["bb_high"] = bb.bollinger_hband(); day["bb_p"] = bb.bollinger_pband()
        day["sma20"] = close.rolling(20).mean(); day["sma50"] = close.rolling(50).mean()
        day["volume_sma20"] = day["volume"].rolling(20).mean()
        day["return3"] = (close / close.shift(3) - 1) * 100
        pieces.append(day)
    return pd.concat(pieces).sort_values("timestamp").reset_index(drop=True)


def _trend(closes):
    if len(closes) < 20:
        return None
    sma = closes.rolling(20).mean()
    current, average, previous = float(closes.iloc[-1]), float(sma.iloc[-1]), float(sma.iloc[-4])
    tolerance = current * .0002
    return "Alcista" if current > average + tolerance and average > previous else \
           "Bajista" if current < average - tolerance and average < previous else "Neutral"


def build_context_index(frame):
    hourly_rows, daily_rows = [], []
    for session, day in frame.groupby("session", sort=True):
        day = day.sort_values("timestamp").copy()
        local = day["timestamp"].dt.tz_convert(NY_TZ)
        day["bucket"] = ((local.dt.hour * 60 + local.dt.minute - 570) // 60).astype(int)
        for _, bucket in day.groupby("bucket"):
            if len(bucket) < 50:
                continue
            hourly_rows.append({"available": pd.Timestamp(bucket["timestamp"].iloc[-1]) + timedelta(minutes=1),
                                "close": bucket["close"].iloc[-1], "volume": bucket["volume"].sum()})
        daily_rows.append({"session": session,
                           "available": pd.Timestamp(day["timestamp"].iloc[-1]) + timedelta(minutes=1),
                           "close": day["close"].iloc[-1], "volume": day["volume"].sum()})
    return pd.DataFrame(hourly_rows), pd.DataFrame(daily_rows)


def context_at(available, hourly, daily):
    hour_position = int(hourly["available"].searchsorted(available, side="right"))
    day_position = int(daily["available"].searchsorted(available, side="right"))
    hours = hourly.iloc[:hour_position]
    days = daily.iloc[:day_position]
    if len(hours) >= 20:
        htrend = _trend(hours["close"].tail(24))
        hour = {"status": "sufficient", "trend": htrend, "rows": len(hours)}
    else:
        hour = {"status": "insufficient", "trend": None, "rows": len(hours)}
    if len(days) >= 50:
        dtrend = _trend(days["close"].tail(53))
        sma50 = float(days["close"].tail(50).mean())
        close = float(days["close"].iloc[-1])
        day = {"status": "sufficient", "trend": dtrend, "rows": len(days),
               "sma50": sma50,
               "sma50_position": "above" if close > sma50 else "below" if close < sma50 else "equal"}
    else:
        day = {"status": "insufficient", "trend": None, "rows": len(days)}
    return {"status": "sufficient" if hour["status"] == "sufficient" else "partial",
            "as_of": available.isoformat(), "future_rows_used": 0, "1h": hour, "1d": day}


def analysis_at(day, position, context):
    row = day.iloc[position]
    history = day.iloc[max(0, position - 10):position + 1]
    pattern_frame = pd.DataFrame({name.capitalize(): history[name].to_numpy()
                                  for name in ("open", "high", "low", "close", "volume")},
                                 index=history["timestamp"])
    patterns = detect_patterns(pattern_frame, "1m")
    signals = list(patterns)
    if position >= 2 and day.iloc[position - 2]["close"] < day.iloc[position - 2]["bb_low"] and row["close"] > row["bb_low"]:
        signals.append("Lower BB mean-reversion (1m)")
    if position >= 2 and day.iloc[position - 2]["close"] > day.iloc[position - 2]["bb_high"] and row["close"] < row["bb_high"]:
        signals.append("Upper BB mean-reversion (1m)")
    tolerance = float(row["close"]) * .0001
    trend = "Alcista" if row["close"] > row["sma20"] + tolerance and row["sma20"] > day.iloc[position - 3]["sma20"] else \
            "Bajista" if row["close"] < row["sma20"] - tolerance and row["sma20"] < day.iloc[position - 3]["sma20"] else "Neutral"
    available = pd.Timestamp(row["timestamp"]) + timedelta(minutes=1)
    values = {
        "rsi_14": float(row["rsi"]), "macd_12_26": float(row["macd"]),
        "macd_signal_9": float(row["macd_signal"]), "macd_histogram": float(row["macd_hist"]),
        "macd_histogram_previous": float(day.iloc[position - 1]["macd_hist"]),
        "bollinger_lower": float(row["bb_low"]), "bollinger_middle": float(row["bb_mid"]),
        "bollinger_upper": float(row["bb_high"]), "bollinger_percent_b": float(row["bb_p"]),
        "close": float(row["close"]), "sma20_1m": float(row["sma20"]),
        "sma50_1m": float(row["sma50"]), "trend_1m": trend,
        "return_3m_percent": float(row["return3"]), "volume": float(row["volume"]),
        "volume_sma20": float(row["volume_sma20"]),
        "volume_ratio": float(row["volume"] / row["volume_sma20"]) if row["volume_sma20"] > 0 else None,
    }
    return {"symbol": "NVDA", "status": "ready", "stale": False, "bias": "Neutral",
            "last_candle_time": row["timestamp"].isoformat(), "computed_at": available.isoformat(),
            "signals": signals, "patterns": patterns, "values": values, "context": context}


def collect_events(frame):
    frame = add_features(frame)
    hourly, daily = build_context_index(frame)
    events = []
    opportunities = {h: {} for h in SUPPORTED_HORIZONS}
    waits = {h: {} for h in SUPPORTED_HORIZONS}
    overlaps = {h: {} for h in SUPPORTED_HORIZONS}
    next_entry = {h: pd.Timestamp("1970-01-01", tz="UTC") for h in SUPPORTED_HORIZONS}
    for session, day in frame.groupby("session", sort=True):
        day = day.sort_values("timestamp").reset_index(drop=True)
        by_time = {stamp: pos for pos, stamp in enumerate(day["timestamp"])}
        for pos in range(WARMUP - 1, len(day)):
            signal_time = pd.Timestamp(day.iloc[pos]["timestamp"])
            available = signal_time + timedelta(minutes=1)
            if any(pd.isna(day.iloc[pos][name]) for name in ("rsi", "macd", "macd_signal", "macd_hist", "sma50")):
                continue
            context = context_at(available, hourly, daily)
            decision = evaluate_hypothesis(analysis_at(day, pos, context))
            for horizon in SUPPORTED_HORIZONS:
                entry_time = available
                expiry_time = entry_time + timedelta(seconds=horizon)
                entry_pos, expiry_pos = by_time.get(entry_time), by_time.get(expiry_time)
                if entry_pos is None or expiry_pos is None:
                    continue
                opportunities[horizon][session] = opportunities[horizon].get(session, 0) + 1
                evaluation = decision["evaluaciones"][str(horizon)]
                direction = evaluation["direccion"]
                if direction == "ESPERAR":
                    waits[horizon][session] = waits[horizon].get(session, 0) + 1
                    continue
                if entry_time < next_entry[horizon]:
                    overlaps[horizon][session] = overlaps[horizon].get(session, 0) + 1
                    continue
                entry_price = float(day.iloc[entry_pos]["open"])
                exit_price = float(day.iloc[expiry_pos]["open"])
                actual = "SUBE" if exit_price > entry_price else "BAJA" if exit_price < entry_price else "EMPATE"
                result = "EMPATE" if actual == "EMPATE" else "ACIERTO" if direction == actual else "FALLO"
                previous = day.iloc[pos]
                last_candle = "SUBE" if previous["close"] > previous["open"] else "BAJA" if previous["close"] < previous["open"] else "EMPATE"
                events.append({"session": session, "signal_time": signal_time.isoformat(),
                               "available_time": available.isoformat(), "entry_time": entry_time.isoformat(),
                               "expiry_time": expiry_time.isoformat(), "horizon_seconds": horizon,
                               "direction": direction, "entry_price": entry_price, "exit_price": exit_price,
                               "actual": actual, "result": result, "last_candle": last_candle,
                               "reason": evaluation["justificacion"], "rules_version": RULES_VERSION})
                next_entry[horizon] = expiry_time
    return events, opportunities, waits, overlaps


def metrics(events, opportunities, waits, overlaps, sessions, seed=20261121):
    output = {}
    for horizon in SUPPORTED_HORIZONS:
        rows = [item for item in events if item["horizon_seconds"] == horizon]
        rng = random.Random(seed + horizon)
        random_wins = 0
        paired = []
        for item in rows:
            random_side = "SUBE" if rng.random() < .5 else "BAJA"
            random_wins += item["actual"] != "EMPATE" and random_side == item["actual"]
            paired.append((item["session"], item["result"] == "ACIERTO",
                           item["actual"] == "SUBE", item["actual"] == "BAJA",
                           item["last_candle"] == item["actual"] and item["actual"] != "EMPATE",
                           random_side == item["actual"] and item["actual"] != "EMPATE"))
        def paired_ci(reference_position):
            by_session = {}
            for values in paired:
                counts = by_session.setdefault(values[0], [0, 0])
                counts[0] += 1
                counts[1] += int(values[1]) - int(values[reference_position])
            keys = sorted(by_session)
            if len(keys) < 2:
                return None
            bootstrap = random.Random(seed + horizon + reference_position)
            deltas = []
            for _ in range(3000):
                sampled = [by_session[bootstrap.choice(keys)] for _ in keys]
                deltas.append(100 * sum(item[1] for item in sampled) / sum(item[0] for item in sampled))
            deltas.sort()
            return [round(deltas[75], 3), round(deltas[2924], 3)]
        evaluable = sum(item["result"] in ("ACIERTO", "FALLO", "EMPATE") for item in rows)
        wins = sum(item["result"] == "ACIERTO" for item in rows)
        ties = sum(item["result"] == "EMPATE" for item in rows)
        output[str(horizon)] = {
            "sessions": len({item["session"] for item in rows}), "available_sessions": len(sessions),
            "eligible_minutes": opportunities[horizon], "signals_non_overlapping": len(rows),
            "abstentions_wait": waits[horizon], "skipped_overlap": overlaps[horizon], "wins": wins,
            "losses": sum(item["result"] == "FALLO" for item in rows), "ties": ties,
            "not_evaluable": 0, "coverage_percent": round(len(rows) / opportunities[horizon] * 100, 3) if opportunities[horizon] else 0,
            "win_rate_percent": round(wins / evaluable * 100, 3) if evaluable else None,
            "always_up_percent_same_events": round(sum(item["actual"] == "SUBE" for item in rows) / evaluable * 100, 3) if evaluable else None,
            "always_down_percent_same_events": round(sum(item["actual"] == "BAJA" for item in rows) / evaluable * 100, 3) if evaluable else None,
            "last_candle_percent_same_events": round(sum(item["last_candle"] == item["actual"] and item["actual"] != "EMPATE" for item in rows) / evaluable * 100, 3) if evaluable else None,
            "balanced_random_percent_same_events": round(random_wins / evaluable * 100, 3) if evaluable else None,
            "paired_delta_ci95_points": {"always_up": paired_ci(2), "always_down": paired_ci(3),
                                          "last_candle": paired_ci(4), "balanced_random": paired_ci(5)},
            "evidence_status": "SIN_VENTAJA_DEMOSTRADA",
            "latency": "NO_MEDIBLE_EN_CSV_1M",
        }
    return output


def run(csv_path, output_dir, train_sessions=TRAIN_SESSIONS):
    source_hash = hashlib.sha256(Path(csv_path).read_bytes()).hexdigest().upper()
    frame = load_history(csv_path)
    sessions = sorted(frame["session"].unique())
    if len(sessions) <= train_sessions:
        raise ValueError("No hay sesiones suficientes para separación cronológica")
    events, opportunities, waits, overlaps = collect_events(frame)
    train_set = set(sessions[:train_sessions])
    train_events = [item for item in events if item["session"] in train_set]
    test_events = [item for item in events if item["session"] not in train_set]
    train_opportunities = {h: sum(value for session, value in opportunities[h].items() if session in train_set)
                           for h in SUPPORTED_HORIZONS}
    test_opportunities = {h: sum(value for session, value in opportunities[h].items() if session not in train_set)
                          for h in SUPPORTED_HORIZONS}
    train_waits = {h: sum(value for session, value in waits[h].items() if session in train_set)
                   for h in SUPPORTED_HORIZONS}
    test_waits = {h: sum(value for session, value in waits[h].items() if session not in train_set)
                  for h in SUPPORTED_HORIZONS}
    train_overlaps = {h: sum(value for session, value in overlaps[h].items() if session in train_set)
                      for h in SUPPORTED_HORIZONS}
    test_overlaps = {h: sum(value for session, value in overlaps[h].items() if session not in train_set)
                     for h in SUPPORTED_HORIZONS}
    report = {
        "rules_version": RULES_VERSION, "source": str(Path(csv_path).resolve()),
        "source_sha256": source_hash, "feed": "Alpaca IEX 1m; no IQ Option",
        "causality": "Cada evaluación usa filas con timestamp <= vela señal; entrada y salida solo miden el resultado después.",
        "sessions_total": len(sessions),
        "split": {"development_sessions": train_sessions, "development_first": sessions[0],
                  "development_last": sessions[train_sessions - 1],
                  "retrospective_validation_sessions": len(sessions) - train_sessions,
                  "validation_first": sessions[train_sessions], "validation_last": sessions[-1]},
        "development": metrics(train_events, train_opportunities, train_waits, train_overlaps, sessions[:train_sessions]),
        "retrospective_validation": metrics(test_events, test_opportunities, test_waits, test_overlaps, sessions[train_sessions:]),
        "automatic_best_horizon": None,
        "limitations": ["La validación posterior es retrospectiva y no ciega.",
                        "Aperturas de velas IEX 1m son proxies, no precios NVIDIA Blitz.",
                        "Latencia, payout, spread y liquidación IQ Option no están disponibles.",
                        "Se requieren sesiones prospectivas nuevas antes de afirmar ventaja."],
    }
    output = Path(output_dir); output.mkdir(parents=True, exist_ok=True)
    (output / "resumen_motor_multihorizonte.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    with (output / "eventos_motor_multihorizonte.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(events[0]) if events else ["session"])
        writer.writeheader(); writer.writerows(events)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Evaluación offline causal NVDA 1/2/5/10 min")
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("auditoria") / "motor_multihorizonte_v2")
    args = parser.parse_args(argv)
    result = run(args.csv, args.output_dir)
    print(json.dumps({"sessions": result["sessions_total"], "output": str(args.output_dir.resolve()),
                      "best_horizon": None}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
