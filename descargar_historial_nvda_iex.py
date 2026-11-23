"""Descarga histórica SOLO NVDA/Alpaca IEX a CSV para el evaluador offline.

No altera TraderAssistant, no toca el caché de realtime, no envía órdenes,
no abre WebSockets y no crea logs de credenciales. Python estándar.

Uso: .\\venv\\Scripts\\python.exe -B .\\descargar_historial_nvda_iex.py --days 90
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

sys.dont_write_bytecode = True

VERSION = "hist-nvda-iex-1.0"
SYMBOL = "NVDA"
FEED = "iex"
URL = "https://data.alpaca.markets/v2/stocks/NVDA/bars"
MAX_PAGES = 150
TIMEOUT_SEC = 18
MAX_RETRIES = 3
KEY_FILE = Path.home() / "Documents" / "Alpaca_key.txt"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "auditoria" / "historico_nvda_iex"
FIELDS = ["time", "open", "high", "low", "close", "volume"]


class DownloadError(Exception):
    """Safe error, never include response contents or headers."""


def read_credentials(path: Path = KEY_FILE):
    if not path.is_file():
        raise DownloadError("No existe Alpaca_key.txt en Documentos. No se modificó nada.")
    # Preserve user's existing two-line label/value format, never echo values.
    lines = [s.strip() for s in path.read_text(encoding="utf-8-sig").splitlines()]
    data = {}
    for i in range(len(lines) - 1):
        label = lines[i].lower().rstrip(":")
        if label in {"key", "secret"}:
            data[label] = lines[i + 1]
    if not data.get("key") or not data.get("secret"):
        raise DownloadError("Archivo de claves incompleto: se necesitan Key y Secret.")
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,150}", data["key"]) or \
            not re.fullmatch(r"[A-Za-z0-9_-]{8,150}", data["secret"]):
        raise DownloadError("Formato de las claves no reconocido. No se efectuaron solicitudes.")
    return data["key"], data["secret"]


def _request_json(params, key, secret, *, opener=urlopen, sleeper=time.sleep):
    url = URL + "?" + urlencode(params)
    req = Request(url, headers={
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret,
        "Accept": "application/json",
        "User-Agent": "TraderAssistant-Offline-History/1.0",
    }, method="GET")
    for attempt in range(MAX_RETRIES + 1):
        try:
            with opener(req, timeout=TIMEOUT_SEC) as response:
                # 10,000 1m bars per page; bound decompressed response for safety.
                raw = response.read(12_000_001)
            if len(raw) > 12_000_000:
                raise DownloadError("Respuesta demasiado grande; se canceló la descarga.")
            obj = json.loads(raw)
            if not isinstance(obj, dict) or not isinstance(obj.get("bars"), list):
                raise DownloadError("Respuesta histórica inesperada de Alpaca.")
            return obj
        except HTTPError as exc:
            if exc.code in (401, 403):
                raise DownloadError(f"Alpaca HTTP {exc.code}: acceso a datos rechazado. Verifica los permisos de IEX.") from None
            if exc.code == 429 or 500 <= exc.code < 600:
                if attempt < MAX_RETRIES:
                    # Short capped pause, avoid hammering provider.
                    sleeper(min(2 ** attempt + 1, 10))
                    continue
            raise DownloadError(f"Alpaca respondió HTTP {exc.code}. No se modificó ningún archivo original.") from None
        except (URLError, TimeoutError, OSError) as exc:
            if attempt < MAX_RETRIES:
                sleeper(min(2 ** attempt + 1, 10))
                continue
            raise DownloadError(f"Error de red tras reintentos ({type(exc).__name__}).") from None
        except (UnicodeError, json.JSONDecodeError):
            raise DownloadError("Alpaca devolvió JSON no válido.") from None
    raise DownloadError("No fue posible recuperar la página.")


def _timestamp(v):
    if not isinstance(v, str):
        raise ValueError("bad timestamp")
    dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("no timezone")
    return int(dt.timestamp())


def normalize_bar(b):
    """Normalize API o/h/l/c/v/t into existing evaluator's CSV contract."""
    try:
        ts = _timestamp(b["t"])
        if ts <= 0 or ts % 60:
            return None
        o, h, l, c = (float(b[f]) for f in ("o", "h", "l", "c"))
        v = float(b.get("v", 0))
        if any(not math.isfinite(x) for x in (o, h, l, c, v)):
            return None
        if min(o, h, l, c) <= 0 or v < 0 or h < max(o, c) or l > min(o, c) or h < l:
            return None
        return {"time": ts, "open": o, "high": h, "low": l,
                "close": c, "volume": int(v) if v.is_integer() else v}
    except (TypeError, ValueError, KeyError, OverflowError, AttributeError):
        return None


def build_range(days, *, now=None):
    if not isinstance(days, int) or not 7 <= days <= 365:
        raise DownloadError("Los días deben estar entre 7 y 365.")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise DownloadError("El reloj debe tener zona horaria.")
    # Exclude the current provisional minute (and allow one additional minute).
    end = now.astimezone(timezone.utc).replace(second=0, microsecond=0) - timedelta(minutes=2)
    start = end - timedelta(days=days)
    return start, end


def retrieve(days, key, secret, *, now=None, fetch=_request_json, on_page=None):
    start, end = build_range(days, now=now)
    params = {"timeframe": "1Min", "start": start.isoformat().replace("+00:00", "Z"),
              "end": end.isoformat().replace("+00:00", "Z"),
              "feed": FEED, "adjustment": "raw", "limit": 10000, "sort": "asc"}
    all_bars = {}
    invalid = duplicates = pages = total_raw = 0
    seen_tokens = set()
    while True:
        pages += 1
        if pages > MAX_PAGES:
            raise DownloadError("Demasiadas páginas de Alpaca; se interrumpió de forma segura.")
        page = fetch(params, key, secret)
        total_raw += len(page["bars"])
        for b in page["bars"]:
            bar = normalize_bar(b)
            if not bar or not int(start.timestamp()) <= bar["time"] <= int(end.timestamp()):
                invalid += 1
                continue
            if bar["time"] in all_bars:
                duplicates += 1
            all_bars[bar["time"]] = bar
        if on_page:
            on_page(pages, len(all_bars))
        token = page.get("next_page_token")
        if not token:
            break
        if not isinstance(token, str) or token in seen_tokens:
            raise DownloadError("Token de paginación inválido o repetido; se canceló.")
        seen_tokens.add(token)
        params["page_token"] = token
    bars = [all_bars[t] for t in sorted(all_bars)]
    sessions = {datetime.fromtimestamp(b["time"], ZoneInfo("America/New_York")).date().isoformat()
                for b in bars if (9, 30) <= (
                    datetime.fromtimestamp(b["time"], ZoneInfo("America/New_York")).hour,
                    datetime.fromtimestamp(b["time"], ZoneInfo("America/New_York")).minute
                ) < (16, 0) and datetime.fromtimestamp(b["time"], ZoneInfo("America/New_York")).weekday() < 5}
    meta = {"tool": VERSION, "symbol": SYMBOL, "feed": FEED, "timeframe": "1Min",
            "adjustment": "raw", "start_utc": start.isoformat(), "end_utc": end.isoformat(),
            "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
            "pages": pages, "raw_records": total_raw, "valid_unique_bars": len(bars),
            "invalid_skipped": invalid, "duplicates_replaced": duplicates,
            "regular_session_days_with_data": len(sessions),
            "session_dates_ny": sorted(sessions),
            "source": "Alpaca historical stock bars REST, IEX; NO SIP; NO IQ Option",
            "usage": "Exploratory offline evaluation only; not a live trading signal"}
    return bars, meta


def save_output(bars, meta, outdir: Path, *, timestamp=None):
    # A separate audit directory; never overwrite cache/alpaca_iex_nvda.json.
    outdir.mkdir(parents=True, exist_ok=True)
    stamp = timestamp or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    base = f"nvda_iex_1min_{stamp}"
    csvfile = outdir / (base + ".csv")
    metafile = outdir / (base + ".meta.json")
    if csvfile.exists() or metafile.exists():
        raise DownloadError("Ya existe esta versión del archivo. No se sobrescribió nada.")
    if not bars:
        raise DownloadError("Alpaca devolvió cero velas históricas válidas; no se generaron archivos.")
    temps = []
    created_finals = []
    try:
        for final in (csvfile, metafile):
            fd, path = tempfile.mkstemp(prefix=".history_", dir=str(outdir), text=True)
            os.close(fd)
            temps.append(Path(path))
        with temps[0].open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(bars)
        with temps[1].open("w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        # Final files created only after download and both writes succeed.
        for source, target in zip(temps, (csvfile, metafile)):
            if target.exists():
                raise DownloadError("Salida ya existente; no se sobrescribió nada.")
            source.rename(target)
            created_finals.append(target)
        return csvfile, metafile
    except Exception:
        for p in created_finals:
            if p.exists():
                p.unlink()
        raise
    finally:
        for p in temps:
            if p.exists():
                p.unlink()


def main(argv=None):
    p = argparse.ArgumentParser(description="Descargar historia NVDA IEX, sin alterar realtime.")
    p.add_argument("--days", type=int, default=90, help="Días naturales hacia atrás (7 a 365). Por defecto 90.")
    p.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT,
                   help="Carpeta nueva de auditoría; no use cache/ del realtime.")
    p.add_argument("--dry-run", action="store_true", help="Muestra el rango; no accede a Alpaca ni lee claves.")
    args = p.parse_args(argv)
    try:
        start, end = build_range(args.days)
        if args.dry_run:
            print(f"PRUEBA SIN RED | {SYMBOL} | IEX | 1Min | {start.isoformat()} a {end.isoformat()}")
            print("No se leyeron credenciales ni se modificó ningún archivo.")
            return 0
        print(f"Descarga SOLO {SYMBOL} | IEX | 1Min | últimos {args.days} días naturales.")
        print("Solo se utilizará Alpaca Market Data REST; el realtime NO se toca.")
        key, secret = read_credentials()
        bars, meta = retrieve(args.days, key, secret,
                              on_page=lambda page, n: print(f"Página {page}: {n} velas únicas acumuladas"))
        csvfile, metafile = save_output(bars, meta, args.output_dir)
        print("DESCARGA COMPLETA")
        print(f"Días con velas en sesión regular: {meta['regular_session_days_with_data']}")
        print(f"Velas IEX de 1 minuto: {len(bars)}")
        print("CSV:", csvfile.resolve())
        print("Metadatos:", metafile.resolve())
        print("EVALUAR CON:")
        print(f'.\\venv\\Scripts\\python.exe -B .\\evaluador_historico_2min.py --symbol NVDA --csv "{csvfile}"')
        print("ATENCIÓN: los resultados son exploratorios; no equivalen a precios de NVIDIA Blitz.")
        return 0
    except DownloadError as exc:
        print("ERROR CONTROLADO:", str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
