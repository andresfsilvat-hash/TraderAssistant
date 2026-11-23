#!/usr/bin/env python3
"""Observador prospectivo SOLO SIMULACION, sin órdenes ni API de Alpaca.

Lee exclusivamente los endpoints locales YA existentes de TraderAssistant.
No modifica el streaming, el panel, los archivos de caché ni credenciales.

Una clasificación alcista/bajista de analysis_live es una HIPOTESIS a probar,
NO una entrada validada ni una recomendación para IQ Option. Registra únicamente
operaciones hipotéticas usando precios de operaciones IEX recibidas DESPUES de
la detección y DESPUES del vencimiento.
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

LOCAL = "http://127.0.0.1:5174"
HORIZON_SECONDS = 120
ENTRY_WINDOW_SECONDS = 30
EXIT_TOLERANCE_SECONDS = 8
FRESH_TRADE_SECONDS = 8
FIELDS = ["id", "activo", "direccion_hipotetica", "sesgo", "velas_base_utc",
          "senal_detectada_utc", "entrada_utc", "precio_entrada_iex", "vencimiento_objetivo_utc",
          "salida_utc", "precio_salida_iex", "desfase_salida_segundos", "resultado",
          "indicadores", "motivo", "estatus", "nota"]


def now_utc():
    return datetime.now(timezone.utc)


def parse_dt(s):
    if not isinstance(s, str):
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except (TypeError, ValueError):
        return None


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat() if dt else ""


def _nth_sunday(year, month, n):
    """Calendario del horario de verano de EE. UU., sin dependencias externas."""
    first = datetime(year, month, 1, tzinfo=timezone.utc)
    first_sunday = 1 + (6 - first.weekday()) % 7
    return first_sunday + 7 * (n - 1)


def is_us_regular_session(when):
    """Solo lunes-viernes, 09:30-16:00 America/New_York; no valida feriados.

    Usa las reglas actuales de horario de verano de EE. UU. para evitar
    depender de tzdata en Windows. Si la bolsa cierra antes por un feriado,
    una validacion de calendario de mercado seria necesaria.
    """
    if when is None or when.tzinfo is None:
        return False
    utc = when.astimezone(timezone.utc)
    year = utc.year
    dst_start = datetime(year, 3, _nth_sunday(year, 3, 2), 7, tzinfo=timezone.utc)
    dst_end = datetime(year, 11, _nth_sunday(year, 11, 1), 6, tzinfo=timezone.utc)
    offset = -4 if dst_start <= utc < dst_end else -5
    eastern = utc + timedelta(hours=offset)
    if eastern.weekday() >= 5:
        return False
    minutes = eastern.hour * 60 + eastern.minute
    return 9 * 60 + 30 <= minutes < 16 * 60


def valid_price(value):
    try:
        p = float(value)
        return p if p > 0 and math.isfinite(p) else None
    except (TypeError, ValueError):
        return None


def extract_trade(market, received_at):
    """Referencia IEX observable: trade validado, reciente, con timestamp real."""
    trade = market.get("last_trade") or {}
    ts = parse_dt(trade.get("timestamp"))
    price = valid_price(trade.get("price"))
    if ts is None or price is None or abs((received_at - ts).total_seconds()) > FRESH_TRADE_SECONDS:
        return None
    return {"time": ts, "price": price}


def fetch_json(path, timeout=2.5):
    # Puerto fijo local: no abre conexiones a Alpaca ni acepta direcciones externas.
    with urlopen(LOCAL + path, timeout=timeout) as resp:
        if getattr(resp, "status", 200) != 200:
            raise RuntimeError("Respuesta HTTP local no válida")
        return json.load(resp)


def atomic_write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def append_csv(path, event):
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists() or path.stat().st_size == 0
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        if new_file:
            writer.writeheader()
        writer.writerow(event)
        f.flush()


def append_jsonl(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


class ProspectiveObserver:
    def __init__(self, destination: Path, started: datetime | None = None):
        self.destination = Path(destination)
        self.started = started or now_utc()
        self.last_seen_candle = None
        self.pending = []
        self.csv_file = self.destination / "simulaciones_nvda_2min.csv"
        self.pending_file = self.destination / "pendientes.json"
        self.observations_file = self.destination / "observaciones_nvda.jsonl"
        self.completed_ids = set()
        if self.csv_file.exists():
            with self.csv_file.open(encoding="utf-8", newline="") as f:
                self.completed_ids = {r.get("id") for r in csv.DictReader(f)}
        if self.pending_file.exists():
            raw = json.loads(self.pending_file.read_text(encoding="utf-8"))
            self.pending = [r for r in raw if r.get("id") not in self.completed_ids]
        self._persist()

    def _persist(self):
        atomic_write_json(self.pending_file, self.pending)

    def _close(self, item, status, note, trade=None):
        if item["id"] in self.completed_ids:
            return
        item = dict(item)
        if trade is not None:
            item["salida_utc"] = iso(trade["time"])
            item["precio_salida_iex"] = trade["price"]
            deadline = parse_dt(item["vencimiento_objetivo_utc"])
            item["desfase_salida_segundos"] = round((trade["time"] - deadline).total_seconds(), 3)
            comparison = (trade["price"] > float(item["precio_entrada_iex"])) - (trade["price"] < float(item["precio_entrada_iex"]))
            item["resultado"] = "EMPATE" if comparison == 0 else (
                "ACIERTO" if (comparison > 0) == (item["direccion_hipotetica"] == "SUBE") else "FALLO"
            )
        else:
            item["resultado"] = "NO_EVALUABLE"
        item["estatus"] = status
        item["nota"] = note
        append_csv(self.csv_file, item)
        self.completed_ids.add(item["id"])
        return item["resultado"]

    def _update_pending(self, market, current):
        # Procesa las pendientes incluso si el analizador está caído o cambió el activo.
        trade = extract_trade(market, current) if market.get("symbol") == "NVDA" else None
        survivors = []
        for item in self.pending:
            if item["id"] in self.completed_ids:
                continue
            start = parse_dt(item["senal_detectada_utc"])
            bar = parse_dt(item.get("velas_base_utc"))
            # No mezclar registros anteriores de pre/posmercado con la muestra regular.
            if not is_us_regular_session(start) or not is_us_regular_session(bar):
                self._close(item, "fuera_sesion", "Hipótesis fuera de sesión regular; descartada")
                continue
            if trade and not is_us_regular_session(trade["time"]):
                trade = None
            if not item.get("entrada_utc"):
                if (trade and trade["time"] > start
                        and trade["time"] <= start + timedelta(seconds=ENTRY_WINDOW_SECONDS)
                        and is_us_regular_session(trade["time"] + timedelta(seconds=HORIZON_SECONDS + EXIT_TOLERANCE_SECONDS))):
                    item["entrada_utc"] = iso(trade["time"])
                    item["precio_entrada_iex"] = trade["price"]
                    item["vencimiento_objetivo_utc"] = iso(trade["time"] + timedelta(seconds=HORIZON_SECONDS))
                    print(f"REGISTRO DE PRUEBA {item['direccion_hipotetica']} | entrada IEX {trade['price']} | vence en 120 s (NO OPERAR)", flush=True)
                elif current > start + timedelta(seconds=ENTRY_WINDOW_SECONDS):
                    self._close(item, "sin_entrada", "No hubo una operación IEX reciente dentro de 30 s")
                    continue
                survivors.append(item)
                continue
            deadline = parse_dt(item["vencimiento_objetivo_utc"])
            if trade and deadline <= trade["time"] <= deadline + timedelta(seconds=EXIT_TOLERANCE_SECONDS):
                result = self._close(item, "evaluado", "Precio de trade IEX, no liquidación de IQ Option", trade)
                print(f"PRUEBA CERRADA {item['direccion_hipotetica']}: {result} (solo estudio)", flush=True)
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
        # Al arrancar, registrar la vela existente como referencia, pero NUNCA disparar una señal retrospectiva.
        if self.last_seen_candle is None:
            self.last_seen_candle = marker
            return "observador iniciado: esperar siguiente vela nueva"
        if marker <= self.last_seen_candle:
            return "sin nueva vela"
        self.last_seen_candle = marker
        # El resultado se generó necesariamente despues de que cerró la vela.
        if candle + timedelta(seconds=60) > current:
            return "vela aún abierta"
        if analysis.get("status") != "ready" or analysis.get("stale") or analysis.get("decision") != "ESPERAR":
            return "analisis no listo / obsoleto"
        compute_time = parse_dt(analysis.get("computed_at"))
        if compute_time is None or compute_time < self.started or (current-compute_time).total_seconds() > 120:
            return "resultado de análisis anterior al inicio de la observación"
        if (current - (candle + timedelta(seconds=60))).total_seconds() > 60:
            return "resultado demasiado tardío"
        if not is_us_regular_session(candle) or not is_us_regular_session(current):
            return "fuera de sesión regular; no registrar hipótesis"
        # No abrir una simulación si incluso el último vencimiento posible
        # cruza el cierre de la sesión.
        if not is_us_regular_session(current + timedelta(seconds=ENTRY_WINDOW_SECONDS + HORIZON_SECONDS + EXIT_TOLERANCE_SECONDS)):
            return "demasiado cerca del cierre regular"
        bias = analysis.get("bias")
        direction = {"Alcista": "SUBE", "Bajista": "BAJA"}.get(bias)
        obs = {"at": iso(current), "candle": marker, "bias": bias,
               "signals": analysis.get("signals", []), "values": analysis.get("values", {}),
               "status": analysis.get("status"), "source": "Alpaca IEX / API local"}
        append_jsonl(self.observations_file, obs)
        if not direction:
            return "observacion registrada: ESPERAR"
        if any(item.get("entrada_utc") or item.get("senal_detectada_utc") for item in self.pending):
            return "observación registrada; simulación no solapada"
        item = {key: "" for key in FIELDS}
        item.update({"id": uuid4().hex, "activo": "NVDA", "direccion_hipotetica": direction,
                     "sesgo": bias, "velas_base_utc": marker, "senal_detectada_utc": iso(current),
                     "indicadores": json.dumps(analysis.get("values", {}), ensure_ascii=False),
                     "motivo": str(analysis.get("reason", "")), "estatus": "pendiente_entrada",
                     "nota": "HIPOTESIS EXPERIMENTAL, SIN VALIDEZ OPERATIVA"})
        self.pending.append(item)
        self._persist()
        return f"hipotesis {direction} registrada, a la espera de un trade FUTURO (NO OPERAR)"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Simulador prospectivo NVDA 120s, SOLO observación, jamás envía órdenes")
    parser.add_argument("--poll", type=float, default=5.0, help="Intervalo lectura APIs locales (min 2 segundos)")
    parser.add_argument("--output-dir", default=str(Path("auditoria") / "prospectivo_nvda_2min"))
    parser.add_argument("--diagnostico", action="store_true", help="Consultar endpoints locales una vez, sin generar datos")
    args = parser.parse_args(argv)
    if args.poll < 2.0:
        parser.error("--poll debe ser de al menos 2 segundos")
    try:
        if args.diagnostico:
            a = fetch_json("/api/analysis/live")
            m = fetch_json("/api/alpaca/live")
            print("ANALISIS LOCAL:", a.get("symbol"), a.get("status"), a.get("bias"), "ultima vela", a.get("last_candle_time"))
            print("ALPACA LOCAL:", m.get("symbol"), m.get("status"), "ultimo trade", (m.get("last_trade") or {}).get("timestamp"))
            print("No se creó ningún registro ni se accedió a Alpaca directamente.")
            return 0
        observer = ProspectiveObserver(Path(args.output_dir))
        print("INICIADO: SIMULACION NVDA 2 MIN; NO OPERAR; CTRL+C para detener. Ningun cambio al realtime.", flush=True)
        print("Archivos de salida:", observer.destination.resolve(), flush=True)
        failures = 0
        while True:
            try:
                a = fetch_json("/api/analysis/live")
                m = fetch_json("/api/alpaca/live")
                status = observer.process(a, m)
                if status.startswith("hipotesis"):
                    print(status, flush=True)
                failures = 0
            except (URLError, TimeoutError, ConnectionError, OSError, json.JSONDecodeError) as exc:
                failures += 1
                if failures in (1, 5, 20):
                    print("Sin acceso temporal al servidor local; TraderAssistant debe estar abierto:", type(exc).__name__, flush=True)
            time.sleep(args.poll)
    except KeyboardInterrupt:
        print("\nSimulador detenido; pendientes guardadas. Real-time no modificado.")
        return 0
    except Exception as exc:
        print("Error:", str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
