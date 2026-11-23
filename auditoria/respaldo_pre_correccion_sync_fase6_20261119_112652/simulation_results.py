"""Read-only, cached view of prospective simulation files for the web panel."""
from __future__ import annotations

import csv
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import threading

from decision_engine_experimental import RULES_VERSION, SUPPORTED_HORIZONS


HEARTBEAT_MAX_AGE_SECONDS = 20


def _parse_time(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (TypeError, ValueError):
        return None


def _safe_json(path, default):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return deepcopy(default)


def _safe_csv(path):
    if not path.exists():
        return []
    try:
        with path.open(encoding="utf-8", newline="") as stream:
            return [dict(row) for row in csv.DictReader(stream) if row.get("id")]
    except (OSError, csv.Error, UnicodeDecodeError):
        return []


def _horizon(record):
    try:
        return int(record.get("horizonte_segundos") or 120)
    except (TypeError, ValueError):
        return 120


def _timestamp(record):
    for field in ("entrada_utc", "senal_detectada_utc", "salida_utc", "velas_base_utc"):
        parsed = _parse_time(record.get(field))
        if parsed:
            return parsed
    return datetime.min.replace(tzinfo=timezone.utc)


def _status(record):
    if record.get("resultado") == "NO_EVALUABLE" or record.get("estatus") in ("sin_entrada", "sin_salida", "fuera_sesion"):
        return "NO_EVALUABLE"
    if record.get("resultado"):
        return "CERRADA"
    if record.get("entrada_utc"):
        return "ACTIVA"
    return "ESPERANDO_PRECIO"


def _public_record(record, *, current):
    if not record:
        return None
    return {
        "id": record.get("id"),
        "group_id": record.get("grupo_id") or None,
        "symbol": record.get("activo") or "NVDA",
        "horizon_seconds": _horizon(record),
        "hypothesis": record.get("direccion_hipotetica") or "ESPERAR",
        "status": _status(record),
        "detected_at": record.get("senal_detectada_utc") or None,
        "entry_at": record.get("entrada_utc") or None,
        "entry_price_iex": record.get("precio_entrada_iex") or None,
        "expiry_at": record.get("vencimiento_objetivo_utc") or None,
        "exit_at": record.get("salida_utc") or None,
        "exit_price_iex": record.get("precio_salida_iex") or None,
        "result": record.get("resultado") or None,
        "reason": record.get("motivo") or "",
        "rules_version": record.get("version_reglas") or "legacy-direct-bias-v0",
        "validation_status": record.get("estado_validacion") or "EXPERIMENTAL",
        "note": record.get("nota") or "",
        "is_current": bool(current),
    }


class SimulationResultsReader:
    def __init__(self, project_root, directories=None):
        root = Path(project_root)
        self.directories = [Path(item) for item in (directories or (
            root / "auditoria" / "prospectivo_nvda_multihorizonte",
            root / "auditoria" / "prospectivo_nvda_2min_sesion_regular",
            root / "auditoria" / "prospectivo_nvda_2min",
        ))]
        self.lock = threading.RLock()
        self.fingerprint = None
        self.cache = None

    def _files(self):
        names = ("simulaciones_nvda_multihorizonte.csv", "pendientes_multihorizonte.json",
                 "observaciones_nvda_multihorizonte.jsonl", "estado_simulador.json",
                 "simulaciones_nvda_2min.csv", "pendientes.json")
        return [directory / name for directory in self.directories for name in names]

    def _fingerprint(self):
        values = []
        for path in self._files():
            try:
                stat = path.stat()
                values.append((str(path), stat.st_mtime_ns, stat.st_size))
            except OSError:
                values.append((str(path), 0, 0))
        return tuple(values)

    def _load(self):
        rows, pending, states = [], [], []
        seen_rows, seen_pending = set(), set()
        for directory in self.directories:
            for record in _safe_csv(directory / "simulaciones_nvda_multihorizonte.csv"):
                if record["id"] not in seen_rows:
                    rows.append(record); seen_rows.add(record["id"])
            multi_pending = _safe_json(directory / "pendientes_multihorizonte.json", [])
            if isinstance(multi_pending, list):
                for record in multi_pending:
                    if isinstance(record, dict) and record.get("id") and record["id"] not in seen_pending:
                        pending.append(record); seen_pending.add(record["id"])
            state = _safe_json(directory / "estado_simulador.json", {})
            if isinstance(state, dict) and state.get("heartbeat_utc"):
                states.append(state)

            # Historical 120-second records remain visible but keep a distinct
            # rules version and are never merged into newer-version statistics.
            for record in _safe_csv(directory / "simulaciones_nvda_2min.csv"):
                if record["id"] not in seen_rows:
                    record["horizonte_segundos"] = "120"
                    record["version_reglas"] = "legacy-direct-bias-v0"
                    rows.append(record); seen_rows.add(record["id"])
            legacy_pending = _safe_json(directory / "pendientes.json", [])
            if isinstance(legacy_pending, list):
                for record in legacy_pending:
                    if isinstance(record, dict) and record.get("id") and record["id"] not in seen_pending:
                        record["horizonte_segundos"] = 120
                        record["version_reglas"] = "legacy-direct-bias-v0"
                        pending.append(record); seen_pending.add(record["id"])

        state = max(states, key=lambda item: _parse_time(item.get("heartbeat_utc")) or datetime.min.replace(tzinfo=timezone.utc), default={})
        heartbeat = _parse_time(state.get("heartbeat_utc"))
        age = (datetime.now(timezone.utc) - heartbeat).total_seconds() if heartbeat else None
        running = bool(heartbeat and age <= HEARTBEAT_MAX_AGE_SECONDS and state.get("status") in ("running", "degraded"))
        return {"rows": rows, "pending": pending, "state": state,
                "running": running, "heartbeat_age_seconds": round(age, 3) if age is not None else None}

    def snapshot(self, horizon=120):
        horizon = int(horizon)
        if horizon not in SUPPORTED_HORIZONS:
            raise ValueError("horizon must be 120, 300 or 600")
        with self.lock:
            fingerprint = self._fingerprint()
            if fingerprint != self.fingerprint:
                self.cache = self._load()
                self.fingerprint = fingerprint
            data = deepcopy(self.cache)

        rows = [item for item in data["rows"] if _horizon(item) == horizon]
        pending = [item for item in data["pending"] if _horizon(item) == horizon]
        latest_pending = max(pending, key=_timestamp, default=None)
        latest_closed = max(rows, key=_timestamp, default=None)
        latest = latest_pending or latest_closed
        versions = {}
        for record in rows + pending:
            version = record.get("version_reglas") or "legacy-direct-bias-v0"
            stats = versions.setdefault(version, {"generated": 0, "entries": 0, "wins": 0,
                                                  "losses": 0, "ties": 0, "not_evaluable": 0,
                                                  "active": 0,
                                                  "reference_always_sube_evaluable": 0,
                                                  "reference_always_sube_wins": 0,
                                                  "reference_always_sube_ties": 0})
            stats["generated"] += 1
            if record.get("entrada_utc"): stats["entries"] += 1
            result = record.get("resultado")
            if result == "ACIERTO": stats["wins"] += 1
            elif result == "FALLO": stats["losses"] += 1
            elif result == "EMPATE": stats["ties"] += 1
            elif result == "NO_EVALUABLE": stats["not_evaluable"] += 1
            try:
                entry = float(record.get("precio_entrada_iex"))
                exit_price = float(record.get("precio_salida_iex"))
            except (TypeError, ValueError):
                entry = exit_price = None
            if entry is not None and exit_price is not None:
                stats["reference_always_sube_evaluable"] += 1
                if exit_price > entry: stats["reference_always_sube_wins"] += 1
                elif exit_price == entry: stats["reference_always_sube_ties"] += 1
            if record in pending: stats["active"] += 1

        return {
            "symbol": "NVDA", "selected_horizon_seconds": horizon,
            "supported_horizons_seconds": list(SUPPORTED_HORIZONS),
            "operational_decision": "ESPERAR", "validation_status": "EXPERIMENTAL",
            "simulator_status": "ACTIVO" if data["running"] else "SIMULADOR_DETENIDO",
            "heartbeat_age_seconds": data["heartbeat_age_seconds"],
            "active_rules_version": data["state"].get("rules_version") or RULES_VERSION,
            "latest": _public_record(latest, current=data["running"] and latest in pending),
            "statistics_by_rules_version": versions,
            "warning": "Resultados Alpaca IEX; no equivalen a liquidaciones de IQ Option. Ningún horizonte está validado como mejor.",
        }


def register_simulation_results(app, project_root=None, directories=None):
    root = Path(project_root or Path(__file__).resolve().parent)
    reader = SimulationResultsReader(root, directories=directories)
    app.extensions["simulation_results"] = reader

    @app.route("/api/simulation/live", methods=["GET"])
    def simulation_live_state():
        from flask import jsonify, request
        try:
            horizon = int(request.args.get("horizon", "120"))
            response = jsonify(reader.snapshot(horizon))
            response.headers["Cache-Control"] = "no-store"
            return response
        except (TypeError, ValueError):
            return jsonify({"error": "horizon must be 120, 300 or 600"}), 400

    return reader
