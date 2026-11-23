"""Ajuste de altura de TraderAssistant; solo modifica ui/live.html.

No accede a Alpaca, ni a claves, ni a Internet. Compatible con v4 y
con la modificación opcional 'Solo Velas' si los marcadores se mantienen.
"""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import tempfile
from datetime import datetime

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "ui" / "live.html"
MARKER = "TA_VIEWPORT_FIT_20261118_V1"

# Insertar DESPUÉS del CSS existente, como capa de ajuste local:
# ningún estilo original se elimina y solo se aplica en ventanas de escritorio
# con suficiente espacio. En ventanas muy pequeñas sigue disponible el scroll.
CSS = r'''
/* BEGIN TA_VIEWPORT_FIT_20261118_V1
   Ajuste de altura de la VISTA, sin tocar los datos ni la lógica de mercado.
   Las secciones informativas no crecen al maximizar; el gráfico absorbe
   el espacio libre. A resoluciones pequeñas se conserva el desplazamiento.
*/
@media screen and (min-width: 1101px) and (min-height: 650px) {
  html, body {height:100%; overflow:hidden;}
  body {height:100vh; height:100dvh; display:flex; flex-direction:column;}
  header.top {flex:0 0 auto;}
  main.content {
    flex:1 1 auto; min-height:0; overflow:hidden;
    display:flex; flex-direction:column;
    padding:10px 14px 8px;
  }
  main.content > .marketStrip {
    flex:0 0 auto; margin-bottom:8px; padding:8px 12px;
  }
  main.content > .summary {flex:0 0 auto; margin-bottom:8px;}
  main.content > .summary .stat {min-height:0; padding:9px 12px;}
  main.content > .quoteStrip {
    flex:0 0 auto; margin-bottom:8px; padding:7px 12px;
  }
  main.content > .chartPanel {
    flex:1 1 0; min-height:0;
    display:flex; flex-direction:column;
  }
  main.content > .chartPanel > .chartHead {
    flex:0 0 auto; padding:8px 11px;
  }
  main.content > .chartPanel > #chart {
    flex:1 1 0; min-height:0 !important; height:auto !important;
  }
  main.content > .chartPanel > .progress,
  main.content > .chartPanel > .details {flex:0 0 auto;}
  main.content > .chartPanel > .details {
    padding:6px 10px; gap:6px 12px; font-size:11px;
  }
  main.content > .notice {
    flex:0 0 auto; margin:5px 2px 0; line-height:1.3; font-size:11px;
  }
}
/* END TA_VIEWPORT_FIT_20261118_V1 */
'''

INITIAL_OLD = "width:chartEl.clientWidth,height:Math.max(390,chartEl.clientHeight-1),"
INITIAL_NEW = "width:chartEl.clientWidth,height:Math.max(160,chartEl.clientHeight-1),"
RESIZE_OLD = "function resizeChart(){chart.resize(chartEl.clientWidth,Math.max(390,chartEl.clientHeight-1));}"
RESIZE_NEW = "function resizeChart(){chart.resize(chartEl.clientWidth,Math.max(160,chartEl.clientHeight-1));}"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def abort(reason: str) -> None:
    raise SystemExit("SIN CAMBIOS: " + reason)


def validate_base(txt: str) -> None:
    # Validar solo los anclajes necesarios. No imponer hashes de versiones
    # anteriores: así se preservan funciones añadidas más recientemente.
    required = (
        '<main class="content">',
        'class="marketStrip"',
        'class="summary"',
        'class="quoteStrip"',
        'class="chartPanel"',
        'id="chart"',
        'const chart = LightweightCharts.createChart(chartEl,',
        'const candle = chart.addCandlestickSeries(',
        'function resizeChart()',
        '</style>',
        '</script>',
    )
    missing = [v for v in required if v not in txt]
    if missing:
        abort("La versión de ui/live.html cambió y faltan marcadores esperados: " + ", ".join(missing))
    if txt.count('</style>') != 1:
        abort("Encontré más de un </style>; se requiere revisión manual.")


def make_payload(raw: bytes) -> bytes | None:
    has_bom = raw.startswith(b'\xef\xbb\xbf')
    try:
        source = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        abort("El archivo no está en UTF-8.")
    validate_base(source)
    if MARKER in source:
        if INITIAL_NEW in source and RESIZE_NEW in source and '/* END ' + MARKER + ' */' in source:
            return None
        abort("Hay una instalación parcial/desconocida del ajuste; no se sobrescribirá.")
    for old in (INITIAL_OLD, RESIZE_OLD):
        if source.count(old) != 1:
            abort("No coincide el control de tamaño del gráfico: " + old[:80])
    html = source.replace('</style>', CSS + '\n</style>', 1)
    html = html.replace(INITIAL_OLD, INITIAL_NEW, 1)
    html = html.replace(RESIZE_OLD, RESIZE_NEW, 1)
    # Verificaciones de integridad del cambio: todo el resto permanece intacto.
    assert MARKER in html and html.count(MARKER) == 2, "Marcadores incompletos"
    assert html.count(INITIAL_NEW) == 1 and html.count(RESIZE_NEW) == 1
    for token in ('id="quote-bid"', 'id="quote-ask"', 'id="chart"', 'candle.setData('):
        assert html.count(token) == source.count(token), "Cambió un elemento existente"
    for token in ('id="toggle-quote-line"', 'id="toggle-volume"'):
        assert html.count(token) == source.count(token), "Cambió un control existente"
    if b'\r\n' in raw:
        html = html.replace('\r\n','\n').replace('\n','\r\n')
    encoded = html.encode('utf-8')
    return (b'\xef\xbb\xbf' if has_bom else b'') + encoded


def main() -> None:
    parser = argparse.ArgumentParser(description="Ajuste seguro del tamaño de ventana de TraderAssistant.")
    parser.add_argument('--verificar', action='store_true', help='Solo comprobar, sin modificar nada.')
    args = parser.parse_args()

    if not (ROOT / 'main.py').is_file() or not (ROOT / 'app.py').is_file():
        abort("No estás en la carpeta raíz de TraderAssistant (faltan main.py o app.py).")
    if not TARGET.is_file():
        abort("No existe ui/live.html en esta carpeta.")
    original = TARGET.read_bytes()
    updated = make_payload(original)
    if updated is None:
        print("OK: el ajuste de pantalla ya está instalado. No se cambió ningún archivo.")
        return
    print("Archivo encontrado:", TARGET)
    print("SHA-256 original:", digest(original))
    print("Solo se modificará ui/live.html (CSS de altura y tamaño del gráfico).")
    if args.verificar:
        print("VERIFICACIÓN CORRECTA: compatible; no se modificó ningún archivo.")
        return

    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    backup = TARGET.with_name(f'live.html.bak_ajuste_pantalla_{stamp}')
    # No abrir el proyecto en paralelo mientras esté en uso.
    if TARGET.read_bytes() != original:
        abort("ui/live.html cambió mientras preparaba el parche.")
    shutil.copy2(TARGET, backup)
    if backup.read_bytes() != original:
        abort("El respaldo no se pudo verificar; el archivo principal sigue intacto.")

    tmpfile: str | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix='live.', suffix='.tmp', dir=TARGET.parent, delete=False) as tf:
            tmpfile = tf.name
            tf.write(updated)
            tf.flush()
            os.fsync(tf.fileno())
        if TARGET.read_bytes() != original:
            abort("ui/live.html fue modificado por otro proceso; no se reemplazará.")
        os.replace(tmpfile, TARGET)
        tmpfile = None
    finally:
        if tmpfile and os.path.exists(tmpfile):
            os.unlink(tmpfile)

    if TARGET.read_bytes() != updated:
        abort("Falló la verificación final; conserva el respaldo mostrado.")
    print('INSTALACIÓN COMPLETADA: al maximizar, el gráfico ocupa el espacio libre.')
    print('No se modificaron el backend Alpaca, las claves, las funciones ni los controles existentes.')
    print('Respaldo:', backup)
    print('Para restaurar, con TraderAssistant cerrado:')
    print(f'Copy-Item -LiteralPath "{backup}" -Destination "{TARGET}" -Force')
    print('Inicia normalmente con: .\\venv\\Scripts\\python.exe .\\main.py')


if __name__ == '__main__':
    main()
