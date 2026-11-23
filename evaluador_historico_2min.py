"""Experimento OFFLINE de señales históricas a horizonte nominal de 120 segundos.

NO conecta Alpaca/IQ Option, NO usa credenciales, NO modifica cache, web ni
TraderAssistant. Evaluación exploratoria de detectores originales en barras IEX.
NO equivale a una recomendación de trading, backtest de ejecución ni cuota de éxito.

Ejemplo:
    .\\venv\\Scripts\\python.exe .\\evaluador_historico_2min.py --cache-dir .\\cache
"""
from __future__ import annotations

import sys
sys.dont_write_bytecode = True

import argparse
import csv
from datetime import datetime, time, timedelta, timezone
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from screener.indicator_detector import MIN_ROWS, detect_indicators
from screener.pattern_detector import detect_patterns
from screener.scorer import _classify

VERSION = "offline-2min-1.0"
NY = ZoneInfo("America/New_York")
EC = ZoneInfo("America/Guayaquil")
CANDLE_SECONDS = 60
HORIZON_SECONDS = 120
MAX_CONTEXT = 500
SYMBOLS = ("NVDA", "SPY", "QQQ", "MSFT", "AAPL", "AMD")
SESSION_MIN = time(9, 30)
SESSION_END = time(16, 0)
MIN_VALIDATION_SESSIONS = 5


def parse_timestamp(value):
    """Unix seconds or timezone-qualified ISO 8601; naive datetimes rejected."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(float(value)):
            raise ValueError("timestamp non-finite")
        return int(value)
    s = str(value).strip()
    if not s:
        raise ValueError("timestamp empty")
    if s.isdigit():
        return int(s)
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("ISO datetime requires explicit timezone")
    return int(dt.timestamp())


def validate_bars(records):
    """Normalize OHLCV, skip malformed/duplicate, last valid correction wins."""
    valid = {}
    meta = {"received": len(records), "invalid": 0, "duplicates": 0,
            "provisional": 0, "unaligned": 0}
    for b in records:
        if not isinstance(b, dict):
            meta["invalid"] += 1
            continue
        if b.get("provisional") is True or b.get("indicative") is True:
            meta["provisional"] += 1
            continue
        try:
            ts = parse_timestamp(b["time"])
            if ts <= 0 or ts % CANDLE_SECONDS != 0:
                meta["unaligned"] += 1
                continue
            vals = [float(b[k]) for k in ("open", "high", "low", "close")]
            vol = float(b.get("volume", 0))
            o, h, l, c = vals
            if any(not math.isfinite(x) for x in (*vals, vol)) or \
                    min(vals) <= 0 or vol < 0 or h < max(o, c) or \
                    l > min(o, c) or h < l:
                raise ValueError("invalid OHLCV")
        except (TypeError, ValueError, OverflowError, KeyError):
            meta["invalid"] += 1
            continue
        if ts in valid:
            meta["duplicates"] += 1
        valid[ts] = {"time": ts, "open": o, "high": h, "low": l,
                     "close": c, "volume": vol}
    return [valid[key] for key in sorted(valid)], meta


def load_cache(cache_dir, symbol):
    path = cache_dir / ("alpaca_iex_" + symbol.lower() + ".json")
    if not path.is_file():
        raise FileNotFoundError(str(path))
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if str(payload.get("symbol", "")).upper() != symbol or \
            str(payload.get("feed", "")).lower() != "iex":
        raise ValueError("cache file symbol/feed mismatch: " + path.name)
    if not isinstance(payload.get("candles"), list):
        raise ValueError("cache has no candles array: " + path.name)
    return validate_bars(payload["candles"]), {"path": str(path), "feed": "IEX",
                                                "saved_at": payload.get("saved_at")}


def load_csv(filename):
    with filename.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        required = {"time", "open", "high", "low", "close", "volume"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError("CSV columns required: " + ", ".join(sorted(required)))
        records = list(reader)
    return validate_bars(records), {"path": str(filename), "feed": "CSV (origen externo, no verificado)"}


def is_regular_minute(ts):
    local = datetime.fromtimestamp(ts, NY)
    return local.weekday() < 5 and SESSION_MIN <= local.time() < SESSION_END


def session_date(ts):
    return datetime.fromtimestamp(ts, NY).date().isoformat()


def utc_iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def ec_iso(ts):
    return datetime.fromtimestamp(ts, EC).isoformat()


def make_frame(bars):
    idx = pd.to_datetime([b["time"] for b in bars], unit="s", utc=True)
    df = pd.DataFrame({c: [b[c.lower()] for b in bars]
                       for c in ("Open", "High", "Low", "Close", "Volume")}, index=idx)
    df.index.name = "Timestamp"
    return df


def direction_from_signals(signals):
    directions = {_classify(s) for s in signals} - {0}
    if directions == {1}:
        return "SUBE"
    if directions == {-1}:
        return "BAJA"
    if directions == {1, -1}:
        return "CONTRADICTORIO"
    return "SIN_SENAL"


def classify_move(entry, exit_price):
    if exit_price > entry:
        return "SUBE"
    if exit_price < entry:
        return "BAJA"
    return "EMPATE"


def evaluate_symbol(symbol, bars, *, warmup=40):
    """Historical replay; t signal closed, next-bar open entry, +120s open exit.

    Exit is FIRST PRICE observed in minute bucket starting exactly at nominal
    expiry, not a trade executable at that second. Strict 1m continuity.
    """
    filtered = [b for b in bars if is_regular_minute(b["time"])]
    index_by_time = {b["time"]: i for i, b in enumerate(filtered)}
    df = make_frame(filtered)
    stats = {"bars_all": len(bars), "bars_regular": len(filtered),
             "analysis_points": 0, "no_signal": 0, "contradictory": 0,
             "skip_missing_exit": 0, "skip_cross_session": 0,
             "candidates_with_outcome": 0, "excluded_overlap": 0}
    events = []
    last_selected_exit = -1
    # min 40 rows consistent with existing detector. No speculative early signals.
    first_i = max(int(warmup), int(MIN_ROWS)) - 1
    for i in range(first_i, len(filtered)):
        current = filtered[i]
        t = current["time"]
        session_close = datetime.fromtimestamp(t, NY).replace(
            hour=16, minute=0, second=0, microsecond=0)
        signal_available = t + 60
        entry_time = signal_available
        exit_time = entry_time + HORIZON_SECONDS
        if exit_time > int(session_close.timestamp()):
            stats["skip_cross_session"] += 1
            continue
        stats["analysis_points"] += 1
        prefix = df.iloc[max(0, i + 1 - MAX_CONTEXT):i + 1]
        signals = detect_patterns(prefix, "1m") + detect_indicators(prefix, "1m")
        side = direction_from_signals(signals)
        if side == "SIN_SENAL":
            stats["no_signal"] += 1
            continue
        if side == "CONTRADICTORIO":
            stats["contradictory"] += 1
            continue
        # Require three consecutive MINUTE BUCKETS after signal bar:
        # entry at start of t+60, exit at start of t+180.
        expected = (t + 60, t + 120, t + 180)
        future_indices = [index_by_time.get(ts) for ts in expected]
        if any(k is None for k in future_indices) or any(
                session_date(ts) != session_date(t) for ts in expected):
            stats["skip_missing_exit"] += 1
            continue
        enter = float(filtered[future_indices[0]]["open"])
        leave = float(filtered[future_indices[2]]["open"])
        realized_side = classify_move(enter, leave)
        observed_baseline = "SUBE" if current["close"] > current["open"] else \
            "BAJA" if current["close"] < current["open"] else "EMPATE"
        selected = entry_time >= last_selected_exit
        if selected:
            last_selected_exit = exit_time
        else:
            stats["excluded_overlap"] += 1
        ret = (leave / enter - 1.0) * 100
        events.append({
            "symbol": symbol,
            "session_ny": session_date(t),
            "signal_bar_open_utc": utc_iso(t),
            "signal_available_ec": ec_iso(signal_available),
            "entry_nominal_ec": ec_iso(entry_time),
            "expiry_nominal_ec": ec_iso(exit_time),
            "entry_proxy_first_trade_1m": round(enter, 8),
            "expiry_proxy_first_trade_1m": round(leave, 8),
            "direction": side, "observed_direction": realized_side,
            "result": "ACIERTO" if side == realized_side else
                      "EMPATE" if realized_side == "EMPATE" else "FALLO",
            "return_underlying_pct": round(ret, 8),
            "baseline_last_candle": observed_baseline,
            "baseline_result": "ACIERTO" if observed_baseline == realized_side else
                               "EMPATE" if realized_side == "EMPATE" else "FALLO",
            "nonoverlap_selected": selected,
            "indicator_signals": " | ".join(signals),
            "signal_count": len(signals),
        })
        stats["candidates_with_outcome"] += 1
    return events, stats, sorted({session_date(b["time"]) for b in filtered})


def rate(wins, denom):
    return round(100.0 * wins / denom, 2) if denom else None


def summarize_events(events, sessions, *, payout=None):
    # Descriptive only; no fitting or hyperparameter optimization.
    chosen = [e for e in events if e["nonoverlap_selected"]]
    groups = {"total": chosen,
              "SUBE": [e for e in chosen if e["direction"] == "SUBE"],
              "BAJA": [e for e in chosen if e["direction"] == "BAJA"]}
    by_session = {}
    for sess in sessions:
        by_session[sess] = [e for e in chosen if e["session_ny"] == sess]

    def metrics(items):
        n = len(items)
        wins = sum(e["result"] == "ACIERTO" for e in items)
        ties = sum(e["result"] == "EMPATE" for e in items)
        baseline = sum(e["baseline_result"] == "ACIERTO" for e in items)
        result = {"evaluated": n, "wins": wins, "losses": n - wins - ties,
                  "ties": ties, "accuracy_pct_ties_as_not_wins": rate(wins, n),
                  "baseline_last_candle_accuracy_pct": rate(baseline, n)}
        if payout is not None:
            # Hypothetical all-or-nothing payout: ties counted as lost. NOT IQ pricing.
            result["hypothetical_net_units"] = round(wins * payout - (n - wins), 6)
            result["hypothetical_expectancy_units_per_case"] = round(
                (wins * payout - (n - wins)) / n, 6) if n else None
        return result

    min_sess = MIN_VALIDATION_SESSIONS
    return {"sessions": sessions, "session_count": len(sessions),
            "evidence_level": "INSUFICIENTE" if len(sessions) < min_sess else
                              "DESCRIPTIVO_NO_VALIDADO",
            "required_sessions_for_first_review": min_sess,
            "note": "No es validación fuera de muestra. No demuestra rentabilidad o capacidad predictiva.",
            "all_signal_events_including_overlap": len(events),
            "selected_nonoverlap_events": len(chosen),
            "metrics": {k: metrics(v) for k, v in groups.items()},
            "by_session": {k: metrics(v) for k, v in by_session.items()},
            "last_session_descriptive": metrics(by_session[sessions[-1]]) if sessions else None,
        }


def write_csv(filepath, records):
    fields = ["symbol", "session_ny", "signal_bar_open_utc", "signal_available_ec",
              "entry_nominal_ec", "expiry_nominal_ec", "entry_proxy_first_trade_1m",
              "expiry_proxy_first_trade_1m", "direction", "observed_direction", "result",
              "return_underlying_pct", "baseline_last_candle", "baseline_result",
              "nonoverlap_selected", "signal_count", "indicator_signals"]
    with filepath.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(records)


def markdown_report(report):
    lines = ["# Evaluación exploratoria OFFLINE — horizonte nominal 2 minutos",
             "", "**No apta para decisiones financieras reales.**", "",
             "Esta prueba usa operaciones IEX agregadas a **1 minuto** y evalúa las ",
             "funciones originales de TraderAssistant. No utiliza precios de NVIDIA Blitz.",
             "El archivo es descriptivo, no un modelo validado ni una recomendación SUBE/BAJA.",
             "", "## Contrato temporal de la evaluación", "",
             "- La señal se calcula al **cierre** de una vela de 1 minuto.",
             "- Entrada hipotética: **apertura de la siguiente vela de 1 minuto**.",
             "- Vencimiento nominal: **120 segundos después** de esa apertura.",
             "- Precio de salida aproximado: **apertura de la vela de 1 minuto que comienza al vencimiento**.",
             "- Las aperturas son las primeras operaciones registradas en el intervalo, **no necesariamente al segundo exacto**.",
             "- Se exige continuidad de los intervalos y permanencia dentro de sesión regular estadounidense.",
             "- Solo indicadores y patrones existentes, sin entrenar reglas ni usar futuros al calcular señales.",
             "- Para métricas principales, se seleccionan eventos sin solapamiento de 120 segundos.",
             "- Empates cuentan como no aciertos; no se presupone cómo liquida IQ Option.",
             "", "## Resumen por activo", "",
             "| Símbolo | Sesiones | Eventos no solapados | Aciertos | Errores | Empates | Acierto (%) | Referencia última vela (%) | Evidencia |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---|" ]
    for symbol, data in report["results"].items():
        sumry = data.get("summary")
        if not sumry:
            lines.append(f"| {symbol} | — | — | — | — | — | — | — | ERROR DE DATOS |")
            continue
        m = sumry["metrics"]["total"]
        lines.append("| {s} | {sess} | {n} | {wins} | {loss} | {ties} | {acc} | {baseline} | {level} |".format(
            s=symbol,sess=sumry["session_count"],n=m["evaluated"],wins=m["wins"],
            loss=m["losses"], ties=m["ties"],acc=m["accuracy_pct_ties_as_not_wins"],
            baseline=m["baseline_last_candle_accuracy_pct"],level=sumry["evidence_level"]))
    lines.extend(["", "## Limitaciones críticas", "",
        "1. Los cachés actuales representan aproximadamente **2–3 sesiones por activo**, insuficientes para validar una estrategia.",
        "2. IEX y NVIDIA Blitz **no comparten necesariamente** reglas de precio, liquidez, vencimiento ni liquidación.",
        "3. Señales original RSI/MACD/patrones se diseñaron para Daily/1h; aquí solo se examina su comportamiento exploratorio a 1m.",
        "4. El precio de entrada y el de salida son **proxies de aperturas de velas**, no ejecuciones ni cotizaciones exactas a 120s.",
        "5. No se estiman costos, spreads, retardo de clic, deslizamiento, comisiones ni horario de vencimiento en IQ Option.",
        "6. La evaluación no ajusta parámetros, no tiene validación fuera de muestra y **no justifica entradas reales**.",
        "", "## Archivo de trazabilidad", "",
        "`eventos_2min.csv` contiene horas de cálculo, entrada/vencimiento nominales, precios proxy, dirección, señales y resultado.",
        "El campo `nonoverlap_selected` identifica los eventos utilizados en la métrica principal.",
        "", "El evaluador no modifica el realtime, el motor de análisis en vivo ni las credenciales."])
    if report.get("payout_scenario") is not None:
        lines.extend(["", "## Escenario de pago puramente hipotético", "",
                      f"Pago por acierto: {report['payout_scenario']*100:.2f} % de la apuesta. ",
                      "Un fallo o empate se modela como pérdida total. No es una tarifa confirmada de IQ Option. ",
                      f"Umbral matemático de equilibrio (sin otros costos): {report['break_even_pct']:.2f} %."])
    return "\n".join(lines) + "\n"


def run(cache_dir, outdir, symbols, *, payout=None, csv_path=None):
    results = {}
    all_events = []
    for symbol in symbols:
        try:
            if csv_path is not None:
                (bars, validation), src = load_csv(csv_path)
            else:
                (bars, validation), src = load_cache(cache_dir, symbol)
            events, counts, sessions = evaluate_symbol(symbol, bars)
            summary = summarize_events(events, sessions, payout=payout)
            results[symbol] = {"source": src, "validation": validation,
                               "counts": counts, "summary": summary}
            all_events.extend(events)
        except (FileNotFoundError, ValueError, OSError, json.JSONDecodeError) as exc:
            results[symbol] = {"error": type(exc).__name__ + ": " + str(exc)}
    report = {"evaluator_version": VERSION,
              "generated_at_utc": datetime.now(timezone.utc).isoformat(),
              "horizon_nominal_seconds": HORIZON_SECONDS,
              "signal_source": "Original detect_patterns + detect_indicators + _classify",
              "real_trade_eligible": False,
              "payout_scenario": payout,
              "break_even_pct": round(100 / (1 + payout), 2) if payout is not None else None,
              "results": results}
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "resumen_2min.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (outdir / "informe_2min.md").write_text(markdown_report(report), encoding="utf-8")
    write_csv(outdir / "eventos_2min.csv", all_events)
    return report


def main():
    parser = argparse.ArgumentParser(description="Evaluación offline exploratoria de señales a dos minutos; sin trading.")
    parser.add_argument("--cache-dir", type=Path, default=Path(__file__).resolve().parent / "cache")
    parser.add_argument("--output-dir", type=Path,
                        default=Path(__file__).resolve().parent / "auditoria" / "evaluacion_2min")
    parser.add_argument("--symbol", choices=SYMBOLS, action="append", help="Filtrar símbolo; repetible.")
    parser.add_argument("--csv", dest="csv_path", type=Path,
                        help="CSV externo con columnas time,open,high,low,close,volume; un solo símbolo")
    parser.add_argument("--payout", type=float,
                        help="Solo escenario ilustrativo: ganancia neta como fracción de apuesta, ej. 0.86")
    args = parser.parse_args()
    if args.payout is not None and not 0 < args.payout <= 10:
        parser.error("--payout must be in (0,10]")
    symbols = args.symbol or list(SYMBOLS)
    if args.csv_path is not None and len(symbols) != 1:
        parser.error("--csv requires exactly one --symbol")
    report = run(args.cache_dir, args.output_dir, symbols,
                 payout=args.payout, csv_path=args.csv_path)
    for symbol, data in report["results"].items():
        if "error" in data:
            print(f"{symbol}: ERROR {data['error']}")
            continue
        summary = data["summary"]
        mt = summary["metrics"]["total"]
        print(f"{symbol}: {summary['session_count']} sesiones; {mt['evaluated']} casos no solapados; "
              f"{mt['wins']} aciertos, {mt['losses']} fallos, {mt['ties']} empates; "
              f"{mt['accuracy_pct_ties_as_not_wins']}% (NO VALIDADO)")
    print("Archivos:", str(args.output_dir.resolve()))
    print("ADVERTENCIA: datos IEX, no NVIDIA Blitz; no utilizar para realizar operaciones.")


if __name__ == "__main__":
    main()
