"""Actualiza TraderAssistant para abrir la pantalla IEX en vivo de forma predeterminada.

Conserva el analizador historico. No lee secretos, no usa red y no ejecuta la app.
"""
from pathlib import Path
import shutil

root = Path(__file__).resolve().parent
integracion = root / "integracion"
app_path = root / "app.py"
main_path = root / "main.py"
index_path = root / "ui" / "index.html"
backend_path = root / "alpaca_live.py"
page_path = root / "ui" / "live.html"

needed = [app_path, main_path, index_path, integracion / "alpaca_live.py", integracion / "ui" / "live.html"]
missing = [str(p) for p in needed if not p.is_file()]
if missing:
    raise SystemExit("Error: no se encontraron los archivos para instalar. Extraiga el ZIP en C:\\Proyectos\\TraderAssistant.")

app = app_path.read_text(encoding="utf-8")
main = main_path.read_text(encoding="utf-8")
index = index_path.read_text(encoding="utf-8")

registration = "from alpaca_live import register_live\nregister_live(app)\n"
if registration not in app:
    anchor = 'app = Flask(__name__, static_folder="ui", static_url_path="")'
    if app.count(anchor) != 1:
        raise SystemExit("No identifique el punto de instalacion en app.py. No se modifico ningun archivo.")
    app = app.replace(anchor, anchor + "\n\n# Market data IEX (solo lectura, sin ordenes)\n" + registration, 1)

old_url = 'url=f"http://{HOST}:{PORT}/",'
new_url = 'url=f"http://{HOST}:{PORT}/live",'
if new_url not in main:
    if main.count(old_url) != 1:
        raise SystemExit("No identifique la URL de inicio en main.py. No se modifico ningun archivo.")
    main = main.replace(old_url, new_url, 1)

if 'href="/live"' not in index:
    anchor = '<button id="btn-settings" onclick="openSettings()">'
    if index.count(anchor) != 1:
        raise SystemExit("No encontre el menu para regresar al vivo en ui/index.html. No se modifico ningun archivo.")
    button = '<a href="/live" style="background:#166534;color:white;padding:8px 10px;border-radius:5px;text-decoration:none;font-size:12px">Mercado en vivo (IEX)</a>\n      '
    index = index.replace(anchor, button + anchor, 1)

# Comprobar la sintaxis del modulo antes de escribirlo.
source = (integracion / "alpaca_live.py").read_text(encoding="utf-8")
compile(source, str(integracion / "alpaca_live.py"), "exec")
compile(app, "app.py", "exec")
compile(main, "main.py", "exec")

changes = [(app_path, app), (main_path, main), (index_path, index),
           (backend_path, source), (page_path, (integracion / "ui" / "live.html").read_text(encoding="utf-8"))]
for dest, content in changes:
    if dest.is_file() and dest.read_text(encoding="utf-8") == content:
        continue
    backup = dest.with_name(dest.name + ".bak_live_v2")
    if dest.is_file() and not backup.exists():
        shutil.copy2(dest, backup)
    dest.write_text(content, encoding="utf-8")

print("INSTALACION CORRECTA: TraderAssistant ahora inicia directamente en /live.")
print("El analizador historico sigue disponible desde la vista en vivo.")
print("Se conservaron copias .bak_live_v2 de los archivos reemplazados.")
print("Las claves se mantienen en su archivo TXT; nunca fueron leidas por este instalador.")
