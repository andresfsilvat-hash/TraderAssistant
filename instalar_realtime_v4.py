"""Instalador local seguro de TraderAssistant Realtime v4.

NO instala paquetes, NO usa red, NO lee claves, NO inicia la aplicacion.
Reconoce la v1/v2/v3 originales (saltos LF o CRLF). Rechaza otros cambios.
"""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "realtime_v4"

KNOWN = {
    "alpaca_live.py": {
        "20ad296f64a6c12179e65a6b28b3010143071c2afeab90d8cf6c112427126c52",  # v1
        "d4778f3d90b5225726d9b9616e3e9559814699e30ef033088a711c334ea1af72",  # v2
        "b63ed58c5d47860aeb26ba68f9ab8648bf52237dead8bba1f8fe5436ec1b19ca",  # v3
    },
    "ui/live.html": {
        "82646c12027992ca9af33855deb0848cc71a440c216880213e14387800be12bd",  # v1
        "6cf80327d4ad43bd3d2fc9aff0756e6d866d8bc0c146a40948fae534837a34d8",  # v2
        "00cd7e15b522b031c99cc724507f768ceb4987fc88519d884965f01ef62eb07a",  # v3
    },
}


def normalized_hash(raw: bytes) -> str:
    text = raw.decode("utf-8-sig")
    return sha256(text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")).hexdigest()


def abort(message: str) -> None:
    raise SystemExit("INSTALACION CANCELADA: " + message)


def run() -> int:
    if not (ROOT / "app.py").is_file() or not (ROOT / "main.py").is_file():
        abort("Extrae este ZIP dentro de C:\\Proyectos\\TraderAssistant.")
    if not (ROOT / "ui" / "vendor" / "lightweight-charts.js").is_file():
        abort("No encontre la libreria local de graficos (ui/vendor/lightweight-charts.js).")
    app = (ROOT / "app.py").read_text(encoding="utf-8-sig")
    main = (ROOT / "main.py").read_text(encoding="utf-8-sig")
    if "from alpaca_live import register_live" not in app or "register_live(app)" not in app:
        abort("No se encontro el registro Alpaca en app.py. No se modifico nada.")
    if 'url=f"http://{HOST}:{PORT}/live"' not in main:
        abort("La ventana principal no apunta a /live. No se modifico nada.")

    plans = []
    for relative, known_hashes in KNOWN.items():
        dest = ROOT / relative
        src = SRC / relative
        if not dest.is_file() or not src.is_file():
            abort(f"Falta {relative} en el proyecto o en el ZIP. No se modifico nada.")
        raw_before = dest.read_bytes()
        raw_new = src.read_bytes()
        try:
            actual = normalized_hash(raw_before)
            expected_new = normalized_hash(raw_new)
        except UnicodeDecodeError:
            abort(f"{relative} no tiene codificacion compatible; no lo sobrescribo.")
        if relative.endswith(".py"):
            compile(raw_new.decode("utf-8"), str(src), "exec")
        else:
            page = raw_new.decode("utf-8")
            for token in ("/api/alpaca/live", "/api/alpaca/events", "/vendor/lightweight-charts.js"):
                if token not in page:
                    abort("La nueva vista esta incompleta.")
        if actual == expected_new:
            print(f"[OK] Ya actualizado: {relative}")
            continue
        if actual not in known_hashes:
            abort(f"{relative} tiene cambios diferentes a v1/v2/v3. "
                  "No se sobrescribio ningun archivo. Conserva tu copia y solicita revision.")
        plans.append((dest, raw_before, raw_new))

    if not plans:
        print("[OK] TraderAssistant Realtime v4 ya esta instalado. Nada que modificar.")
        return 0

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backups = []
    # Respaldar TODOS los archivos antes de tocar el primero.
    for target, old, _new in plans:
        backup = target.with_name(target.name + ".bak_pre_v4_" + stamp)
        if backup.exists():
            abort(f"Ya existe el respaldo {backup}. No se modifico nada.")
        shutil.copy2(target, backup)
        backups.append((target, backup))
        print("[RESPALDO]", backup)

    installed = []
    try:
        for target, _old, new in plans:
            temp = target.with_name(target.name + ".v4_install_tmp")
            if temp.exists():
                raise RuntimeError(f"Ya existe {temp.name}; no se sobrescribe.")
            try:
                with temp.open("xb") as handle:
                    handle.write(new)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp, target)
            finally:
                if temp.exists():
                    temp.unlink()
            installed.append(target)
            print("[ACTUALIZADO]", target.relative_to(ROOT))
    except Exception as err:
        for target, backup in backups:
            if target in installed:
                shutil.copy2(backup, target)
        abort("Error de escritura. Se restauraron los archivos modificados. " + type(err).__name__)

    print("\nINSTALACION COMPLETADA: TraderAssistant Realtime v4")
    print("Se conserva el proyecto original, el historial Yahoo y el TXT de Alpaca.")
    print("No necesitas instalar ni ejecutar v3.")
    print("Iniciar: .\\venv\\Scripts\\python.exe .\\main.py")
    return 0


if __name__ == "__main__":
    sys.exit(run())
