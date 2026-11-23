"""Instalador seguro del panel visual, sin análisis ni cambios de backend.

Solo modifica ui/live.html si coincide EXACTAMENTE con la copia restaurada auditada.
Usar --verificar, --instalar o --restaurar. No requiere credenciales ni red.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from hashlib import sha256
import os
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / 'ui' / 'live.html'
PAYLOAD = ROOT / 'panel_visual_seguro' / 'ui_live_patch.html'
BASE_SHA = '7356f5882c936131b11a0920247f8ea2cfa69b5c31b3a227957581e8a99ce601'
PATCH_SHA = '07a54c5ccf203762030e64e3a4df46015432f36199d3dd4688f40d3005fa3de9'
BACKUP_ROOT = ROOT / 'auditoria'


def sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def atomic_write(path: Path, content: bytes) -> None:
    """En Windows, reemplazo atomico en el mismo directorio."""
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.panel-safe-', suffix='.tmp', delete=False) as f:
            temp_name = Path(f.name)
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_name, path)
        temp_name = None
    finally:
        if temp_name is not None:
            temp_name.unlink(missing_ok=True)


def ensure_payload() -> bytes:
    if not PAYLOAD.is_file():
        raise RuntimeError('No se encontro panel_visual_seguro/ui_live_patch.html: extrae el ZIP completo.')
    data = PAYLOAD.read_bytes()
    if sha(data) != PATCH_SHA:
        raise RuntimeError('El parche no coincide con su hash de seguridad. No se modifico nada.')
    return data


def current() -> bytes:
    if not TARGET.is_file():
        raise RuntimeError('No existe ui/live.html. No se modifico nada.')
    return TARGET.read_bytes()


def verify() -> None:
    ensure_payload()
    current_sha = sha(current())
    print('Archivo:', TARGET)
    if current_sha == BASE_SHA:
        print('COMPATIBLE: coincide con la copia restaurada auditada. Puede instalarse.')
    elif current_sha == PATCH_SHA:
        print('YA INSTALADO: el panel visual seguro esta activo. No haga nada mas.')
    else:
        raise RuntimeError('DETENIDO: ui/live.html tiene cambios distintos de la copia auditada. '
                           'No instalar para evitar perder modificaciones. SHA-256: '+current_sha)


def install() -> None:
    updated = ensure_payload()
    original = current()
    h = sha(original)
    if h == PATCH_SHA:
        print('El panel visual ya esta instalado; no se ha sobrescrito nada.')
        return
    if h != BASE_SHA:
        raise RuntimeError('DETENIDO: ui/live.html no coincide exactamente con la copia auditada. '
                           'No se ha sobrescrito nada. SHA-256: '+h)
    backup = BACKUP_ROOT / ('respaldo_panel_visual_seguro_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    backup.mkdir(parents=True, exist_ok=False)
    (backup/'live.html').write_bytes(original)
    if sha((backup/'live.html').read_bytes()) != BASE_SHA:
        raise RuntimeError('Respaldo no verificado. No se modifico ui/live.html.')
    try:
        atomic_write(TARGET, updated)
        if sha(current()) != PATCH_SHA:
            raise RuntimeError('No se pudo verificar la instalacion')
    except Exception:
        atomic_write(TARGET, original)
        raise
    print('INSTALACION CORRECTA. SOLO modificado: ui/live.html')
    print('RESPALDO:', backup/'live.html')
    print('Sin cambios en app.py, alpaca_live.py, main.py, screener ni las claves Alpaca.')


def restore() -> None:
    if sha(current()) != PATCH_SHA:
        raise RuntimeError('DETENIDO: ui/live.html no coincide con nuestro parche. No se restaura para no perder cambios propios.')
    dirs = sorted(BACKUP_ROOT.glob('respaldo_panel_visual_seguro_*'), reverse=True)
    for folder in dirs:
        source = folder/'live.html'
        if source.is_file() and sha(source.read_bytes()) == BASE_SHA:
            atomic_write(TARGET, source.read_bytes())
            if sha(current()) != BASE_SHA:
                raise RuntimeError('Error verificando la restauracion')
            print('RESTAURADO:', TARGET)
            print('Origen del respaldo:', source)
            return
    raise RuntimeError('No se encontro copia original valida. No se modifico nada.')


def main():
    parser = argparse.ArgumentParser(description='Panel visual TraderAssistant, sin modificar realtime')
    flags = parser.add_mutually_exclusive_group(required=True)
    flags.add_argument('--verificar', action='store_true')
    flags.add_argument('--instalar', action='store_true')
    flags.add_argument('--restaurar', action='store_true')
    opt = parser.parse_args()
    try:
        if opt.verificar:
            verify()
        elif opt.instalar:
            install()
        else:
            restore()
    except (OSError, RuntimeError, ValueError) as exc:
        parser.exit(1,'ERROR: '+str(exc)+'\n')


if __name__ == '__main__':
    main()
