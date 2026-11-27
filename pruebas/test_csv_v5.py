"""Pruebas de CSV real, fechas y esquema requerido."""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import tempfile
import unittest

from v5_validar_csv import leer_csv, main

BASE = datetime(2026, 11, 23, 15, 0, tzinfo=timezone.utc)
HEADER = ("detectada_utc,entrada_utc,vencimiento_utc,duracion_segundos,"
          "direccion,precio_entrada,precio_salida,fuente,payout_neto\n")


def fila():
    return (f"{(BASE-timedelta(seconds=10)).isoformat()},"
            f"{BASE.isoformat()},"
            f"{(BASE+timedelta(seconds=30)).isoformat()},30,SUBE,100,101,IQ_OPTION,0.80\n")


class CsvTests(unittest.TestCase):
    def crear(self, contenido):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "registros.csv"
        path.write_text(contenido, encoding="utf-8")
        return path

    def test_csv_valido(self):
        data = leer_csv(self.crear(HEADER + fila()))
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0].fuente, "IQ_OPTION")
        self.assertEqual(data[0].duracion_segundos, 30)

    def test_columnas_faltantes(self):
        with self.assertRaises(ValueError):
            leer_csv(self.crear("entrada_utc,precio_entrada\nx,1\n"))

    def test_fila_invalida(self):
        with self.assertRaisesRegex(ValueError, "fila 2"):
            leer_csv(self.crear(HEADER + fila().replace(",30,SUBE", ",13,SUBE")))

    def test_cli_no_autoriza_operar(self):
        from unittest.mock import patch
        from io import StringIO
        output = StringIO()
        path = self.crear(HEADER + fila())
        with patch("sys.stdout", output):
            self.assertEqual(main([str(path), "--corte-utc",
                                   (BASE-timedelta(seconds=10)).isoformat()]), 0)
        self.assertIn('"operativa_autorizada": false', output.getvalue())


if __name__ == "__main__":
    unittest.main()
