#!/usr/bin/env python3
"""Simulador prospectivo NVDA multihorizonte, exclusivamente experimental.

Consume los endpoints locales existentes. No conecta con Alpaca, no modifica
REALTIME, no construye velas y jamás envía órdenes. Las mismas reglas quedan
congeladas para 120, 300 y 600 segundos; cada horizonte conserva sus resultados.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.error import URLError
from urllib.request import urlopen
from uuid import uuid4

from decision_engine_experimental import (RULES_VERSION, SUPPORTED_HORIZONS,
                                          evaluate_hypothesis)

LOCAL = "http://127.0.0.1:5174"
HORIZON_SECONDS = 120  # compatibilidad con importaciones anteriores
HORIZONS_SECONDS = SUPPORTED_HORIZONS
ENTRY_WINDOW_SECONDS = 30
EXIT_TOLERANCE_SECONDS = 8
FRESH_TRADE_SECONDS = 8
FIELDS = [
    "id", "grupo_id", "activo", "horizonte_segundos", "direccion_hipotetica",
    "sesgo", "velas_base_utc", "senal_detectada_utc", "entrada_utc",
    "precio_entrada_iex", "vencimiento_objetivo_utc", "salida_utc",
    "precio_salida_iex", "desfase_salida_segundos", "resultado", "indicadores",
    "evidencia_alcista", "evidencia_bajista", "contradicciones", "motivo",
    "version_reglas", "estado_validacion", "estatus", "nota",
]


def now_utc():
    return datetime.now(timezone.utc)


def parse_dt(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (TypeError, ValueError):
        return None


def iso(value):
    return value.astimezone(timezone.utc).isoformat() if value else ""


def _nth_sunday(year, month, number):
    first = datetime(year, month, 1, tzinfo=timezone.utc)
    return 1 + (6 - first.weekday()) % 7 + 7 * (number - 1)


def is_us_regular_session(when):
    """Lunes-viernes 09:30-16:00 ET, con horario de verano estadounidense."""
    if when is None or when.tzinfo is None:
        return False
    utc = when.astimezone(timezone.utc)
    start = datetime(utc.year, 3, _nth_sunday(utc.year, 3, 2), 7, tzinfo=timezone.utc)
    end = datetime(utc.year, 11, _nth_sunday(utc.year, 11, 1), 6, tzinfo=timezone.utc)
    eastern = utc + timedelta(hours=-4 if start <= utc < end else -5)
    minutes = eastern.hour * 60 + eastern.minute
    return eastern.weekday() < 5 and 570 <= minutes < 960


def valid_price(value):
    try:
        price = float(value)
        return price if price > 0 and math.isfinite(price) else None
    except (TypeError, ValueError):
        return None


def extract_trade(market, received_at):
    trade = market.get("last_trade") or {}
    timestamp = parse_dt(trade.get("timestamp"))
    price = valid_price(trade.get("price"))
    if timestamp is None or price is None or abs((received_at - timestamp).total_seconds()) > FRESH_TRADE_SECONDS:
        return None
    return {"time": timestamp, "price": price}


def fetch_json(path, timeout=2.5):
    with urlopen(LOCAL + path, timeout=timeout) as response:
        if getattr(response, "status", 200) != 200:
            raise RuntimeError("Respuesta HTTP local no válida")
        return json.load(response)


def atomic_write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def append_csv(path, event):
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists() or path.stat().st_size == 0
    with path.open("a", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, extrasaction="ignore")
        if new_file:
            writer.writeheader()
        writer.writerow(event)
        stream.flush()
        os.fsync(stream.fileno())


def append_jsonl(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        stream.flush()


class SimulatorInstanceLock:
    """Evita dos escritores multihorizonte en el mismo directorio."""
    def __init__(self, destination):
        self.path = Path(destination) / "simulador_multihorizonte.lock"
        self.token = uuid4().hex

    @staticmethod
    def _alive(pid):
        try:
            os.kill(int(pid), 0)
            return True
        except (OSError, TypeError, ValueError):
            return False

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    owner = json.loads(self.path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    owner = {}
                if self._alive(owner.get("pid")):
                    raise RuntimeError(f"Ya existe un simulador para este directorio (PID {owner.get('pid')}).")
                self.path.unlink(missing_ok=True)
                continue
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump({"pid": os.getpid(), "token": self.token,
                           "started_utc": iso(now_utc())}, stream)
            return self
        raise RuntimeError("No se pudo adquirir el bloqueo exclusivo del simulador.")

    def release(self):
        try:
            owner = json.loads(self.path.read_text(encoding="utf-8"))
            if owner.get("token") == self.token:
                self.path.unlink(missing_ok=True)
        except (OSError, json.JSONDecodeError):
            pass


class ProspectiveObserver:
    def __init__(self, destination: Path, started: datetime | None = None,
                 horizons=HORIZONS_SECONDS):
        self.destination = Path(destination)
        self.started = started or now_utc()
        self.horizons = tuple(sorted(set(int(value) for value in horizons)))
        if not self.horizons or any(value not in HORIZONS_SECONDS for value in self.horizons):
            raise ValueError("Horizontes permitidos: 60, 120, 300 y 600 segundos")
        self.last_seen_candle = None
        self.pending = []
        self.csv_file = self.destination / "simulaciones_nvda_multihorizonte.csv"
        self.pending_file = self.destination / "pendientes_multihorizonte.json"
        self.observations_file = self.destination / "observaciones_nvda_multihorizonte.jsonl"
        self.state_file = self.destination / "estado_simulador.json"
        self.completed_ids = set()
        self.load_warnings = []
        self._load_existing()
        self._persist()

    def _load_existing(self):
        if self.csv_file.exists():
            try:
                with self.csv_file.open(encoding="utf-8", newline="") as stream:
                    self.completed_ids = {row.get("id") for row in csv.DictReader(stream) if row.get("id")}
            except (OSError, csv.Error) as error:
                self.load_warnings.append("csv:" + type(error).__name__)
        if self.pending_file.exists():
            try:
                raw = json.loads(self.pending_file.read_text(encoding="utf-8"))
                if not isinstance(raw, list):
                    raise ValueError("pending root is not a list")
                seen = set()
                for record in raw:
                    identifier = record.get("id") if isinstance(record, dict) else None
                    if identifier and identifier not in self.completed_ids and identifier not in seen:
                        record["horizonte_segundos"] = int(record.get("horizonte_segundos") or HORIZON_SECONDS)
                        self.pending.append(record)
                        seen.add(identifier)
            except (OSError, ValueError, json.JSONDecodeError) as error:
                self.load_warnings.append("pending:" + type(error).__name__)

    def _persist(self):
        atomic_write_json(self.pending_file, self.pending)

    def heartbeat(self, status="running", message=""):
        atomic_write_json(self.state_file, {
            "status": status, "pid": os.getpid(), "started_utc": iso(self.started),
            "heartbeat_utc": iso(now_utc()), "symbol": "NVDA",
            "horizons_seconds": list(self.horizons), "rules_version": RULES_VERSION,
            "pending_count": len(self.pending), "load_warnings": self.load_warnings,
            "message": message, "orders_enabled": False,
        })

    def _close(self, item, status, note, trade=None):
        if item["id"] in self.completed_ids:
            return None
        closed = dict(item)
        if trade is not None:
            closed["salida_utc"] = iso(trade["time"])
            closed["precio_salida_iex"] = trade["price"]
            deadline = parse_dt(closed["vencimiento_objetivo_utc"])
            closed["desfase_salida_segundos"] = round((trade["time"] - deadline).total_seconds(), 3)
            movement = ((trade["price"] > float(closed["precio_entrada_iex"]))
                        - (trade["price"] < float(closed["precio_entrada_iex"])))
            closed["resultado"] = "EMPATE" if movement == 0 else (
                "ACIERTO" if (movement > 0) == (closed["direccion_hipotetica"] == "SUBE") else "FALLO")
        else:
            closed["resultado"] = "NO_EVALUABLE"
        closed["estatus"] = status
        closed["nota"] = note
        append_csv(self.csv_file, closed)
        self.completed_ids.add(closed["id"])
        return closed["resultado"]

    def _update_pending(self, market, current):
        trade = extract_trade(market, current) if market.get("symbol") == "NVDA" else None
        survivors = []
        for item in self.pending:
            if item["id"] in self.completed_ids:
                continue
            horizon = int(item.get("horizonte_segundos") or HORIZON_SECONDS)
            detected = parse_dt(item["senal_detectada_utc"])
            candle = parse_dt(item.get("velas_base_utc"))
            if not is_us_regular_session(detected) or not is_us_regular_session(candle):
                self._close(item, "fuera_sesion", "Hipótesis fuera de sesión regular; descartada")
                continue
            usable_trade = trade if trade and is_us_regular_session(trade["time"]) else None
            if not item.get("entrada_utc"):
                if (usable_trade and usable_trade["time"] > detected
                        and usable_trade["time"] <= detected + timedelta(seconds=ENTRY_WINDOW_SECONDS)
                        and is_us_regular_session(usable_trade["time"] + timedelta(seconds=horizon + EXIT_TOLERANCE_SECONDS))):
                    item["entrada_utc"] = iso(usable_trade["time"])
                    item["precio_entrada_iex"] = usable_trade["price"]
                    item["vencimiento_objetivo_utc"] = iso(usable_trade["time"] + timedelta(seconds=horizon))
                    print(f"SIMULACIÓN {horizon}s {item['direccion_hipotetica']} | entrada IEX {usable_trade['price']} (NO OPERAR)", flush=True)
                elif current > detected + timedelta(seconds=ENTRY_WINDOW_SECONDS):
                    self._close(item, "sin_entrada", "No hubo una operación IEX reciente dentro de 30 s")
                    continue
                survivors.append(item)
                continue
            deadline = parse_dt(item["vencimiento_objetivo_utc"])
            if usable_trade and deadline <= usable_trade["time"] <= deadline + timedelta(seconds=EXIT_TOLERANCE_SECONDS):
                result = self._close(item, "evaluado", "Precio de trade IEX, no liquidación de IQ Option", usable_trade)
                print(f"SIMULACIÓN CERRADA {horizon}s {item['direccion_hipotetica']}: {result}", flush=True)
                continue
            if current > deadline + timedelta(seconds=EXIT_TOLERANCE_SECONDS):
                self._close(item, "sin_salida", "Sin operación IEX válida en ventana de 8 s tras vencimiento")
                continue
            survivors.append(item)
        self.pending = survivors
        self._persist()

    def process(self, analysis, market, current=None):
        current = current or now_utc()
        self._update_pending(market, current)
        if market.get("symbol") != "NVDA" or analysis.get("symbol") != "NVDA":
            return "omitido: otro activo"
        candle = parse_dt(analysis.get("last_candle_time"))
        if candle is None:
            return "sin vela oficial analizada"
        marker = iso(candle)
        if self.last_seen_candle is None:
            self.last_seen_candle = marker
            return "observador iniciado: esperar siguiente vela nueva"
        if marker <= self.last_seen_candle:
            return "sin nueva vela"
        self.last_seen_candle = marker
        if candle + timedelta(seconds=60) > current:
            return "vela aún abierta"
        computed = parse_dt(analysis.get("computed_at"))
        if computed is None or computed < self.started or (current - computed).total_seconds() > 120:
            return "resultado de análisis anterior al inicio de la observación"
        if (current - (candle + timedelta(seconds=60))).total_seconds() > 60:
            return "resultado demasiado tardío"
        if not is_us_regular_session(candle) or not is_us_regular_session(current):
            return "fuera de sesión regular; no registrar hipótesis"
        if not is_us_regular_session(current + timedelta(seconds=ENTRY_WINDOW_SECONDS + max(self.horizons) + EXIT_TOLERANCE_SECONDS)):
            return "demasiado cerca del cierre regular"

        decision = evaluate_hypothesis(analysis, self.horizons)
        append_jsonl(self.observations_file, {
            "at": iso(current), "candle": marker, "source": "Alpaca IEX / API local", **decision,
        })
        direction = decision["hipotesis_simulacion"]
        if direction == "ESPERAR":
            return "observación registrada: ESPERAR"

        group = uuid4().hex
        created = []
        for horizon in self.horizons:
            if any(int(item.get("horizonte_segundos") or HORIZON_SECONDS) == horizon for item in self.pending):
                continue
            item = {key: "" for key in FIELDS}
            item.update({
                "id": uuid4().hex, "grupo_id": group, "activo": "NVDA",
                "horizonte_segundos": horizon, "direccion_hipotetica": direction,
                "sesgo": decision["sesgo_tecnico_original"], "velas_base_utc": marker,
                "senal_detectada_utc": iso(current),
                "indicadores": json.dumps(decision["valores_indicadores"], ensure_ascii=False),
                "evidencia_alcista": json.dumps(decision["evidencia_alcista"], ensure_ascii=False),
                "evidencia_bajista": json.dumps(decision["evidencia_bajista"], ensure_ascii=False),
                "contradicciones": json.dumps(decision["indicadores_contradictorios"], ensure_ascii=False),
                "motivo": decision["justificacion"], "version_reglas": RULES_VERSION,
                "estado_validacion": "EXPERIMENTAL", "estatus": "pendiente_entrada",
                "nota": "HIPÓTESIS EXPERIMENTAL; DECISIÓN OPERATIVA: ESPERAR",
            })
            self.pending.append(item)
            created.append(horizon)
        self._persist()
        if not created:
            return "observación registrada; horizontes ocupados por simulaciones no solapadas"
        return f"hipótesis {direction} registrada para {created} segundos (NO OPERAR)"


def _parse_horizons(value):
    try:
        result = tuple(int(part.strip()) for part in value.split(",") if part.strip())
    except ValueError as error:
        raise argparse.ArgumentTypeError("Use segundos separados por coma: 60,120,300,600") from error
    if not result or any(item not in HORIZONS_SECONDS for item in result):
        raise argparse.ArgumentTypeError("Horizontes permitidos: 60,120,300,600")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Simulador NVDA 60/120/300/600s; sólo estudio, jamás envía órdenes")
    parser.add_argument("--poll", type=float, default=5.0, help="Lectura de API local; mínimo 2 s")
    parser.add_argument("--output-dir", default=str(Path("auditoria") / "prospectivo_nvda_multihorizonte"))
    parser.add_argument("--horizons", type=_parse_horizons, default=HORIZONS_SECONDS,
                        help="Duraciones: 60,120,300,600 (predeterminado: las cuatro)")
    parser.add_argument("--diagnostico", action="store_true", help="Consultar una vez sin crear registros")
    args = parser.parse_args(argv)
    if args.poll < 2.0:
        parser.error("--poll debe ser de al menos 2 segundos")
    try:
        if args.diagnostico:
            analysis = fetch_json("/api/analysis/live")
            market = fetch_json("/api/alpaca/live")
            decision = evaluate_hypothesis(analysis, args.horizons)
            print("ANÁLISIS LOCAL:", analysis.get("symbol"), analysis.get("status"), analysis.get("last_candle_time"))
            print("HIPÓTESIS EXPERIMENTAL:", decision["hipotesis_simulacion"], decision["justificacion"])
            print("ALPACA LOCAL:", market.get("symbol"), market.get("status"))
            print("Sin registros nuevos, sin conexión directa a Alpaca y sin órdenes.")
            return 0

        lock = SimulatorInstanceLock(Path(args.output_dir)).acquire()
        observer = None
        try:
            observer = ProspectiveObserver(Path(args.output_dir), horizons=args.horizons)
            observer.heartbeat("running", "Simulador multihorizonte activo")
            print(f"INICIADO: SIMULACIÓN NVDA {args.horizons}s; NO OPERAR; CTRL+C para detener.", flush=True)
            failures = 0
            while True:
                try:
                    analysis = fetch_json("/api/analysis/live")
                    market = fetch_json("/api/alpaca/live")
                    status = observer.process(analysis, market)
                    observer.heartbeat("running", status)
                    if status.startswith("hipótesis"):
                        print(status, flush=True)
                    failures = 0
                except (URLError, TimeoutError, ConnectionError, OSError, json.JSONDecodeError) as error:
                    failures += 1
                    observer.heartbeat("degraded", type(error).__name__)
                    if failures in (1, 5, 20):
                        print("Sin acceso temporal al servidor local:", type(error).__name__, flush=True)
                time.sleep(args.poll)
        finally:
            if observer is not None:
                observer.heartbeat("stopped", "Proceso finalizado")
            lock.release()
    except KeyboardInterrupt:
        print("\nSimulador detenido; pendientes guardadas. REALTIME no modificado.")
        return 0
    except Exception as error:
        print("Error:", str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
