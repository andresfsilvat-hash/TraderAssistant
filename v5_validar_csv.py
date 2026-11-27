"""Evaluación V5 desde CSV de observaciones verificadas, sin red ni órdenes.

Ejemplo:
 python v5_validar_csv.py datos.csv --corte-utc 2026-11-23T15:00:00+00:00
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
import json
from pathlib import Path

from engine.validacion_temporal import Observacion, resumen_fuera_muestra

CAMPOS = ("detectada_utc", "entrada_utc", "vencimiento_utc",
          "duracion_segundos", "direccion", "precio_entrada",
          "precio_salida", "fuente", "payout_neto")


def leer_csv(path: str | Path) -> list[Observacion]:
    salida = []
    with Path(path).open("r", encoding="utf-8-sig", newline="") as archivo:
        reader = csv.DictReader(archivo)
        if not reader.fieldnames or any(field not in reader.fieldnames for field in CAMPOS):
            raise ValueError("CSV incompleto: se requieren " + ", ".join(CAMPOS))
        for index, row in enumerate(reader, start=2):
            try:
                payout = str(row["payout_neto"] or "").strip()
                salida.append(Observacion(
                    detectada_utc=datetime.fromisoformat(row["detectada_utc"].replace("Z", "+00:00")),
                    entrada_utc=datetime.fromisoformat(row["entrada_utc"].replace("Z", "+00:00")),
                    vencimiento_utc=datetime.fromisoformat(row["vencimiento_utc"].replace("Z", "+00:00")),
                    duracion_segundos=int(row["duracion_segundos"]),
                    direccion=row["direccion"].strip().upper(),
                    precio_entrada=float(row["precio_entrada"]),
                    precio_salida=float(row["precio_salida"]),
                    fuente=row["fuente"].strip(),
                    payout_neto=float(payout) if payout else None))
            except (TypeError, ValueError, AttributeError) as exc:
                raise ValueError(f"Registro inválido en fila {index}: {exc}") from exc
    return salida


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Auditar observaciones a tiempo fijo V5")
    parser.add_argument("archivo_csv", type=Path)
    parser.add_argument("--corte-utc", required=True, help="ISO 8601 con zona horaria")
    parser.add_argument("--minimo", type=int, default=30)
    parser.add_argument("--fuente", action="append", help="Filtrar por fuente; se puede repetir")
    args = parser.parse_args(argv)
    report = resumen_fuera_muestra(
        leer_csv(args.archivo_csv),
        corte_utc=datetime.fromisoformat(args.corte_utc.replace("Z", "+00:00")),
        minimo_prueba=args.minimo,
        incluir_fuentes=tuple(args.fuente) if args.fuente else None)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
