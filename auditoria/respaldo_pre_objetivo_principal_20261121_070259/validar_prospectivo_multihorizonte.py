#!/usr/bin/env python3
"""Independent prospective validation for experimental NVDA hypotheses.

Reads frozen simulator outputs and, optionally, a user-supplied IQ Option price
export. It never connects to Alpaca/IQ Option, never sends orders and never
selects a "best" horizon automatically.
"""
from __future__ import annotations

import argparse
from bisect import bisect_left
import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import random
import statistics

from decision_engine_experimental import RULES_VERSION, SUPPORTED_HORIZONS


MIN_SESSIONS_FOR_CONCLUSION = 20
MIN_EVALUABLE_FOR_CONCLUSION = 100
DEFAULT_IQ_TOLERANCE_SECONDS = 8


def parse_time(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (TypeError, ValueError):
        return None


def finite_price(value):
    try:
        number = float(value)
        return number if number > 0 and math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def load_csv(path):
    if not Path(path).exists():
        return []
    with Path(path).open(encoding="utf-8", newline="") as stream:
        return [dict(row) for row in csv.DictReader(stream) if row.get("id")]


def load_pending(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        return [item for item in value if isinstance(item, dict) and item.get("id")] if isinstance(value, list) else []
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return []


def _outcome(entry, exit_price, direction):
    if entry is None or exit_price is None or direction not in ("SUBE", "BAJA"):
        return "NO_EVALUABLE"
    if exit_price == entry:
        return "EMPATE"
    correct = (exit_price > entry) == (direction == "SUBE")
    return "ACIERTO" if correct else "FALLO"


def _baseline_outcomes(entry, exit_price):
    if entry is None or exit_price is None:
        return None, None
    if exit_price == entry:
        return "EMPATE", "EMPATE"
    return ("ACIERTO" if exit_price > entry else "FALLO",
            "ACIERTO" if exit_price < entry else "FALLO")


def _paired_bootstrap(records, repetitions=3000, seed=20261119):
    by_session = {}
    for record in records:
        when = parse_time(record.get("entrada_utc"))
        if when is None:
            continue
        engine = 1 if record.get("resultado") == "ACIERTO" else 0
        entry = finite_price(record.get("precio_entrada_iex"))
        exit_price = finite_price(record.get("precio_salida_iex"))
        baseline, _ = _baseline_outcomes(entry, exit_price)
        if baseline is None:
            continue
        by_session.setdefault(when.date().isoformat(), []).append(engine - (1 if baseline == "ACIERTO" else 0))
    sessions = sorted(by_session)
    if len(sessions) < 2:
        return None
    rng = random.Random(seed)
    values = []
    for _ in range(repetitions):
        selected = [rng.choice(sessions) for _ in sessions]
        differences = [value for session in selected for value in by_session[session]]
        values.append(sum(differences) / len(differences))
    values.sort()
    return [round(values[int(.025 * repetitions)] * 100, 3),
            round(values[int(.975 * repetitions) - 1] * 100, 3)]


def summarize(rows, pending, payout=None):
    summaries = {}
    for horizon in SUPPORTED_HORIZONS:
        for version in sorted({item.get("version_reglas") or "unknown" for item in rows + pending} | {RULES_VERSION}):
            closed = [item for item in rows if int(item.get("horizonte_segundos") or 120) == horizon
                      and (item.get("version_reglas") or "unknown") == version]
            active = [item for item in pending if int(item.get("horizonte_segundos") or 120) == horizon
                      and (item.get("version_reglas") or "unknown") == version]
            if not closed and not active:
                continue
            counts = {name: sum(item.get("resultado") == name for item in closed)
                      for name in ("ACIERTO", "FALLO", "EMPATE", "NO_EVALUABLE")}
            evaluable = counts["ACIERTO"] + counts["FALLO"] + counts["EMPATE"]
            reference_up = reference_down = reference_evaluable = 0
            paired = []
            for item in closed:
                up, down = _baseline_outcomes(finite_price(item.get("precio_entrada_iex")),
                                              finite_price(item.get("precio_salida_iex")))
                if up is not None:
                    reference_evaluable += 1
                    reference_up += up == "ACIERTO"
                    reference_down += down == "ACIERTO"
                    paired.append(item)
            sessions = {parse_time(item.get("entrada_utc")).date().isoformat()
                        for item in paired if parse_time(item.get("entrada_utc"))}
            rate = counts["ACIERTO"] / evaluable if evaluable else None
            up_rate = reference_up / reference_evaluable if reference_evaluable else None
            interval = _paired_bootstrap(paired)
            enough = len(sessions) >= MIN_SESSIONS_FOR_CONCLUSION and evaluable >= MIN_EVALUABLE_FOR_CONCLUSION
            advantage = bool(enough and interval and interval[0] > 0)
            break_even = 1 / (1 + payout) if payout is not None else None
            economic = bool(advantage and break_even is not None and rate is not None and rate > break_even)
            verdict = ("PENDIENTE_MUESTRA_NUEVA" if not enough else
                       "SIN_VENTAJA_DEMOSTRADA" if not advantage else
                       "VENTAJA_IEX_PENDIENTE_VALIDACION_IQ" if not economic else
                       "VENTAJA_IEX_SUPERA_UMBRAL_HIPOTETICO")
            summaries[f"{horizon}:{version}"] = {
                "horizon_seconds": horizon, "rules_version": version,
                "generated": len(closed) + len(active), "closed": len(closed),
                "pending_records": len(active),
                "wins": counts["ACIERTO"], "losses": counts["FALLO"], "ties": counts["EMPATE"],
                "not_evaluable": counts["NO_EVALUABLE"], "evaluable": evaluable,
                "win_rate_percent": round(rate * 100, 3) if rate is not None else None,
                "sessions": len(sessions),
                "reference_always_up_evaluable": reference_evaluable,
                "reference_always_up_win_rate_percent": round(up_rate * 100, 3) if up_rate is not None else None,
                "reference_always_down_win_rate_percent": round(reference_down / reference_evaluable * 100, 3) if reference_evaluable else None,
                "paired_advantage_vs_always_up_ci95_points": interval,
                "minimum_sessions_required": MIN_SESSIONS_FOR_CONCLUSION,
                "minimum_evaluable_required": MIN_EVALUABLE_FOR_CONCLUSION,
                "payout_fraction": payout, "break_even_win_rate_percent": round(break_even * 100, 3) if break_even else None,
                "verdict": verdict,
            }
    return summaries


def load_iq_prices(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"timestamp_utc", "price"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("IQ CSV requires timestamp_utc and price columns")
        records = []
        for row in reader:
            timestamp, price = parse_time(row.get("timestamp_utc")), finite_price(row.get("price"))
            if timestamp and price:
                records.append((timestamp, price, row.get("product") or "NVIDIA Blitz"))
    return sorted(records, key=lambda item: item[0])


def compare_iq(rows, iq_prices, tolerance_seconds=DEFAULT_IQ_TOLERANCE_SECONDS):
    times = [item[0] for item in iq_prices]

    def at_or_after(target):
        if target is None:
            return None
        position = bisect_left(times, target)
        if position >= len(iq_prices):
            return None
        item = iq_prices[position]
        return item if (item[0] - target).total_seconds() <= tolerance_seconds else None

    comparison = []
    for row in rows:
        entry_target = parse_time(row.get("entrada_utc"))
        expiry_target = parse_time(row.get("vencimiento_objetivo_utc"))
        iq_entry, iq_exit = at_or_after(entry_target), at_or_after(expiry_target)
        iq_result = _outcome(iq_entry[1] if iq_entry else None, iq_exit[1] if iq_exit else None,
                             row.get("direccion_hipotetica"))
        comparison.append({
            "simulation_id": row.get("id"), "horizon_seconds": int(row.get("horizonte_segundos") or 120),
            "direction": row.get("direccion_hipotetica"), "iex_result": row.get("resultado") or "NO_EVALUABLE",
            "iq_entry_target_utc": row.get("entrada_utc"), "iq_entry_utc": iq_entry[0].isoformat() if iq_entry else "",
            "iq_entry_price": iq_entry[1] if iq_entry else "", "iq_expiry_target_utc": row.get("vencimiento_objetivo_utc"),
            "iq_exit_utc": iq_exit[0].isoformat() if iq_exit else "", "iq_exit_price": iq_exit[1] if iq_exit else "",
            "iq_result": iq_result, "directional_agreement": (row.get("resultado") == iq_result)
            if row.get("resultado") in ("ACIERTO", "FALLO", "EMPATE") and iq_result != "NO_EVALUABLE" else "",
            "source": iq_entry[2] if iq_entry else "",
        })
    return comparison


def write_csv(path, rows):
    if not rows:
        return
    with Path(path).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def run(simulations, pending, output, *, iq_prices=None, payout=None, tolerance_seconds=8):
    rows, active = load_csv(simulations), load_pending(pending)
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "prospective Alpaca IEX simulations; no real orders",
        "statistics": summarize(rows, active, payout=payout),
        "automatic_best_horizon": None,
        "validation_notice": "No horizon is approved without new sessions and comparable IQ Option outcomes.",
    }
    if iq_prices:
        comparison = compare_iq(rows, load_iq_prices(iq_prices), tolerance_seconds)
        write_csv(output / "comparacion_iex_iqoption.csv", comparison)
        matched = [item for item in comparison if item["iq_result"] != "NO_EVALUABLE"]
        agreements = [item for item in matched if item["directional_agreement"] != ""]
        report["iq_comparison"] = {
            "input": str(Path(iq_prices).resolve()), "rows": len(comparison), "matched": len(matched),
            "not_evaluable": len(comparison) - len(matched),
            "directional_agreement_percent": round(sum(bool(item["directional_agreement"]) for item in agreements) / len(agreements) * 100, 3) if agreements else None,
            "tolerance_seconds": tolerance_seconds,
        }
    else:
        report["iq_comparison"] = {"status": "PENDIENTE_ARCHIVO_IQ_OPTION"}
    (output / "resumen_validacion.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate frozen 1/2/5/10-minute prospective simulations")
    base = Path("auditoria") / "prospectivo_nvda_multihorizonte"
    parser.add_argument("--simulations", type=Path, default=base / "simulaciones_nvda_multihorizonte.csv")
    parser.add_argument("--pending", type=Path, default=base / "pendientes_multihorizonte.json")
    parser.add_argument("--output", type=Path, default=Path("auditoria") / "validacion_prospectiva_multihorizonte")
    parser.add_argument("--iq-prices", type=Path, help="CSV export with timestamp_utc,price[,product]")
    parser.add_argument("--iq-tolerance", type=int, default=DEFAULT_IQ_TOLERANCE_SECONDS)
    parser.add_argument("--payout", type=float, help="Hypothetical decimal payout, e.g. 0.80; never assumed")
    args = parser.parse_args(argv)
    if args.payout is not None and not 0 < args.payout <= 1:
        parser.error("--payout must be in (0,1]")
    report = run(args.simulations, args.pending, args.output, iq_prices=args.iq_prices,
                 payout=args.payout, tolerance_seconds=args.iq_tolerance)
    print(json.dumps({"output": str(args.output.resolve()), "groups": len(report["statistics"]),
                      "iq": report["iq_comparison"], "best_horizon": None}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
