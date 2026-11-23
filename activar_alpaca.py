"""One-time local patch: add read-only Alpaca live view to TraderAssistant.
Does not read credentials, access the Internet, or execute TraderAssistant.
"""
from pathlib import Path

root = Path(__file__).resolve().parent
app_path = root / 'app.py'
index_path = root / 'ui' / 'index.html'
if not all(p.exists() for p in (app_path, index_path, root / 'alpaca_live.py', root / 'ui' / 'live.html')):
    raise SystemExit('Error: descomprime todos los archivos dentro de C:\\Proyectos\\TraderAssistant')

app = app_path.read_text(encoding='utf-8')
code = 'from alpaca_live import register_live\nregister_live(app)\n'
anchor = 'app = Flask(__name__, static_folder="ui", static_url_path="")'
if code not in app:
    if app.count(anchor) != 1:
        raise SystemExit('No pude identificar el punto de insercion en app.py. No cambie nada.')
    app = app.replace(anchor, anchor + '\n\n# Read-only IEX market view; no order/trading routes\n' + code, 1)

html = index_path.read_text(encoding='utf-8')
if 'href="/live"' not in html:
    anchor_html = '<button id="btn-settings" onclick="openSettings()">'
    if html.count(anchor_html) != 1:
        raise SystemExit('No pude identificar el boton de ajustes en ui/index.html. No cambie nada.')
    html = html.replace(anchor_html, '<a href="/live" style="background:#166534;color:#fff;padding:8px 10px;border-radius:5px;text-decoration:none;font-size:12px">NVDA en vivo (IEX)</a>\n      ' + anchor_html, 1)

# Backups before changes. If something fails, the user's code is restorable.
if not (root / 'app.py.bak_alpaca').exists():
    (root / 'app.py.bak_alpaca').write_bytes(app_path.read_bytes())
if not (root / 'ui' / 'index.html.bak_alpaca').exists():
    (root / 'ui' / 'index.html.bak_alpaca').write_bytes(index_path.read_bytes())
app_path.write_text(app, encoding='utf-8')
index_path.write_text(html, encoding='utf-8')
print('Listo: ruta /live agregada; se guardaron copias .bak_alpaca.')
print('No se leyeron claves ni se abrio ninguna conexion de red.')
