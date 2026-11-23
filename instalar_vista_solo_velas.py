"""Añade dos controles de visualización a TraderAssistant.

Seguridad:
- Solo modifica ui/live.html de forma local.
- No toca claves, API, backend, indicadores ni fuentes de datos.
- Requiere patrones exactos conocidos; ante divergencias, aborta.
- Hace respaldo y reemplaza el HTML de manera atómica.
- Idempotente: si ya está instalado, no realiza cambios.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from hashlib import sha256
import os
import shutil
import tempfile

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "ui" / "live.html"

CSS_OLD = ".chartHead .name{font-size:14px;font-weight:650}.time{display:flex;gap:6px;align-items:center}"
CSS_NEW = ".chartHead .name{font-size:14px;font-weight:650}.time{display:flex;gap:6px;align-items:center;flex-wrap:wrap}"

HTML_OLD = '<button id="follow" type="button" class="active" title="Regresar a las últimas velas">Seguir precio</button>'
HTML_NEW = (
    HTML_OLD
    + '<button id="toggle-quote-line" type="button" aria-pressed="false" '
    'title="Mostrar u ocultar la línea indicativa del punto medio bid/ask">Línea: OFF</button>'
    + '<button id="toggle-volume" type="button" aria-pressed="false" '
    'title="Mostrar u ocultar las barras de volumen">Volumen: OFF</button>'
)

JS_OLD = "chart.priceScale('volume').applyOptions({scaleMargins:{top:.82,bottom:0}});"
JS_NEW = JS_OLD + """

// VISTA SOLO VELAS: alterna únicamente la visibilidad; no elimina las series ni sus datos.
// Los dos controles son independientes y comienzan apagados en una instalación nueva.
const OVERLAY_PREF_KEY = 'traderassistant-v4-overlay-visibility';
function readOverlayPreferences(){
  try {
    const saved = JSON.parse(localStorage.getItem(OVERLAY_PREF_KEY) || '{}');
    return {line: saved.line === true, volume: saved.volume === true};
  } catch (_) { return {line:false, volume:false}; }
}
let overlayPreferences = readOverlayPreferences();
function applyOverlayPreferences(){
  quoteLine.applyOptions({visible:overlayPreferences.line});
  volume.applyOptions({visible:overlayPreferences.volume});
  const lineButton = $('toggle-quote-line');
  const volumeButton = $('toggle-volume');
  lineButton.textContent = 'Línea: ' + (overlayPreferences.line ? 'ON' : 'OFF');
  volumeButton.textContent = 'Volumen: ' + (overlayPreferences.volume ? 'ON' : 'OFF');
  lineButton.classList.toggle('active', overlayPreferences.line);
  volumeButton.classList.toggle('active', overlayPreferences.volume);
  lineButton.setAttribute('aria-pressed', String(overlayPreferences.line));
  volumeButton.setAttribute('aria-pressed', String(overlayPreferences.volume));
}
function saveOverlayPreferences(){
  try { localStorage.setItem(OVERLAY_PREF_KEY, JSON.stringify(overlayPreferences)); }
  catch (_) { /* localStorage puede estar deshabilitado en algunos WebView */ }
}
$('toggle-quote-line').addEventListener('click',()=>{
  overlayPreferences.line = !overlayPreferences.line;
  applyOverlayPreferences();
  saveOverlayPreferences();
});
$('toggle-volume').addEventListener('click',()=>{
  overlayPreferences.volume = !overlayPreferences.volume;
  applyOverlayPreferences();
  saveOverlayPreferences();
});
applyOverlayPreferences();
"""


def stop(message: str) -> None:
    raise SystemExit("SIN CAMBIOS: " + message)


def main() -> None:
    if not TARGET.is_file():
        stop("No existe ui/live.html. Extrae el ZIP en la raíz de TraderAssistant.")

    raw = TARGET.read_bytes()
    try:
        content = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        stop("ui/live.html no es UTF-8; no se modificará.")

    # La identificación es deliberadamente conservadora.
    if 'id="toggle-quote-line"' in content or 'id="toggle-volume"' in content:
        if all(token in content for token in ('id="toggle-quote-line"', 'id="toggle-volume"',
                                               'function applyOverlayPreferences()',
                                               'OVERLAY_PREF_KEY')):
            print("YA INSTALADO: los botones Línea y Volumen existen. No se modificó ningún archivo.")
            return
        stop("Hay un control de visualización preexistente diferente. Revisión manual necesaria.")

    patterns = [(CSS_OLD, CSS_NEW), (HTML_OLD, HTML_NEW), (JS_OLD, JS_NEW)]
    for original, _ in patterns:
        if content.count(original) != 1:
            stop(f"No se reconoció un punto de instalación: {original[:65]!r}. "
                 "Codex puede haber modificado la pantalla: no se sobrescribirá.")
    required = ("const quoteLine = chart.addLineSeries(",
                "const volume = chart.addHistogramSeries(",
                "candle.setData(", "volume.setData(", "quoteLine.setData(")
    if not all(x in content for x in required):
        stop("Las series del gráfico no coinciden con las auditadas. No se modificará.")

    edited = content
    for old, new in patterns:
        edited = edited.replace(old, new, 1)

    if edited.count('id="toggle-quote-line"') != 1 or edited.count('id="toggle-volume"') != 1:
        stop("La verificación de controles falló.")
    if "candle.setData(" not in edited:
        stop("Error de integridad del gráfico principal.")

    newline = '\r\n' if b'\r\n' in raw else '\n'
    if newline == '\r\n':
        # Conservar estilo original sin alterar otros contenidos.
        edited = edited.replace('\r\n', '\n').replace('\n', '\r\n')
    payload = edited.encode('utf-8-sig' if raw.startswith(b'\xef\xbb\xbf') else 'utf-8')
    if payload == raw:
        stop("No había cambios que aplicar.")

    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup = TARGET.with_name(f'live.html.bak_solo_velas_{stamp}')
    if backup.exists():
        stop('Ya existe el respaldo con el mismo nombre. Ejecuta el instalador un segundo después.')

    # Copia con el contenido exacto preexistente.
    shutil.copy2(TARGET, backup)
    if sha256(backup.read_bytes()).digest() != sha256(raw).digest():
        stop("No se pudo comprobar el respaldo; no se modifica nada.")

    fd, temp_name = tempfile.mkstemp(prefix='live.html.', suffix='.tmp', dir=TARGET.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_name, TARGET)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)

    print("OK: Vista Solo Velas añadida a TraderAssistant.")
    print("Botones iniciales: Línea OFF y Volumen OFF.")
    print("El estado se guarda en el navegador si localStorage está disponible.")
    print(f"Respaldo intacto: {backup}")
    print("Único archivo modificado: ui/live.html")
    print("Para restaurar, con la aplicación cerrada, copia el respaldo sobre ui/live.html.")


if __name__ == '__main__':
    main()
