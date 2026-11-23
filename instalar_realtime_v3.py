"""Upgrade ONLY TraderAssistant's Alpaca market view, from the exact v2 build.

Does not start TraderAssistant, contact Alpaca, or read API keys.
Run from C:\Proyectos\TraderAssistant with its Python venv executable.
"""
from pathlib import Path
from hashlib import sha256
import shutil

root = Path(__file__).resolve().parent
source = root / "integracion"
files = [
    (root / "alpaca_live.py", source / "alpaca_live.py",
     "d4778f3d90b5225726d9b9616e3e9559814699e30ef033088a711c334ea1af72"),
    (root / "ui" / "live.html", source / "ui" / "live.html",
     "6cf80327d4ad43bd3d2fc9aff0756e6d866d8bc0c146a40948fae534837a34d8"),
]

def sha(data):
    return sha256(data).hexdigest()

if not (root / "app.py").is_file() or not (root / "main.py").is_file():
    raise SystemExit("Falta app.py o main.py. Debes extraer el ZIP dentro de la carpeta TraderAssistant.")

app_source = (root / "app.py").read_text(encoding="utf-8")
if "from alpaca_live import register_live" not in app_source:
    raise SystemExit("No encuentro la integración Alpaca v2 en app.py. No se modificó nada.")

# Validate *all* files before replacing any, so a modified local file is not clobbered.
updates = []
for target, payload, expected_v2 in files:
    if not target.is_file() or not payload.is_file():
        raise SystemExit(f"Falta un archivo: {target if not target.is_file() else payload}")
    original = target.read_bytes()
    new = payload.read_bytes()
    if sha(original) == sha(new):
        print(f"Ya estaba actualizado: {target.name}")
        continue
    if sha(original) != expected_v2:
        raise SystemExit(
            f"El archivo {target} no coincide con la v2 esperada; puede tener cambios propios. "
            "No se sobrescribió ningún archivo."
        )
    if target.suffix == ".py":
        compile(new.decode("utf-8"), str(target), "exec")
    updates.append((target, original, new))

# Backup and replace. No secret file is touched, no packages are installed.
for target, original, updated in updates:
    backup = target.with_name(target.name + ".bak_realtime_v3")
    if backup.exists() and backup.read_bytes() != original:
        raise SystemExit(f"Ya existe un respaldo diferente: {backup}. No se sobrescribió.")

for target, original, updated in updates:
    backup = target.with_name(target.name + ".bak_realtime_v3")
    if not backup.exists():
        shutil.copy2(target, backup)
    target.write_bytes(updated)
    print(f"Actualizado: {target}")

print("Listo: streaming SSE, diagnóstico de demora, horario Ecuador y zoom en las últimas velas.")
print("Inicia normalmente con: .\\venv\\Scripts\\python.exe .\\main.py")
