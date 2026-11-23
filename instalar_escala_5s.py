"""Ajusta SOLO la escala vertical del gráfico de 5 s; no cambia datos de Alpaca.

Instala de forma reversible un HTML conocido y validado por SHA-256.
No hace conexión a red, ni lee credenciales, ni toca scripts de backend.
"""
from __future__ import annotations
import argparse
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / 'ui' / 'live.html'
PAYLOADS = ROOT / 'ajuste_escala_5s'
AUDIT = ROOT / 'auditoria'
VERSIONS = {
    # ui/live.html de la copia restaurada con ajuste de pantalla y controles
    '7356f5882c936131b11a0920247f8ea2cfa69b5c31b3a227957581e8a99ce601':
        ('ui_base.html', 'dad55ffaf3cae9c9cc4c390d91053f85a289a9620e3969c1709285b3563b5b8c'),
    # ui/live.html tras instalar Panel Visual Seguro (solo observación)
    '07a54c5ccf203762030e64e3a4df46015432f36199d3dd4688f40d3005fa3de9':
        ('ui_con_panel.html', '5ec5b7b11a8275d4cbcaf173b6bfa31eef2dad2784962271f895aea63eeccd04'),
}

def sha(buf: bytes) -> str:
    return sha256(buf).hexdigest()

def atomic_write(path: Path, payload: bytes):
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.5sscale-', suffix='.tmp', delete=False) as f:
            tmp = Path(f.name)
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        tmp = None
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)

def checked_payload(name, expected_hash):
    p = PAYLOADS / name
    if not p.is_file():
        raise RuntimeError('Falta archivo del ZIP: ' + str(p))
    b = p.read_bytes()
    if sha(b) != expected_hash:
        raise RuntimeError('Archivo de actualización alterado; instalación detenida.')
    if b'TA_5S_STABLE_SCALE_20261118_V1' not in b:
        raise RuntimeError('No se encontró la marca de la corrección.')
    return b

def state():
    if not TARGET.is_file():
        raise RuntimeError('No se encontró ui/live.html en TraderAssistant.')
    current = TARGET.read_bytes()
    current_hash = sha(current)
    if current_hash in VERSIONS:
        name, new_hash = VERSIONS[current_hash]
        new_bytes = checked_payload(name, new_hash)
        return 'compatible', current_hash, new_bytes
    if any(current_hash == new_hash for _, new_hash in VERSIONS.values()):
        return 'installed', current_hash, None
    raise RuntimeError('La versión local de ui/live.html es distinta a las dos auditadas. '
                       'No se sobrescribió nada. SHA-256: ' + current_hash)

def verify():
    status, h, _ = state()
    print('VERSION:', status)
    print('SHA-256:', h)
    print('ARCHIVO:', TARGET)
    print('Solo cambia la escala visual 5 s; no corrige precios de proveedores diferentes.')

def install():
    status, h, content = state()
    if status == 'installed':
        print('YA INSTALADO: ningún archivo modificado.')
        return
    original = TARGET.read_bytes()
    folder = AUDIT / ('respaldo_escala_5s_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    folder.mkdir(parents=True, exist_ok=False)
    backup = folder / 'live.html'
    backup.write_bytes(original)
    if sha(backup.read_bytes()) != h:
        raise RuntimeError('Falló respaldo: ninguna modificación realizada.')
    metadata = {'old_sha':h, 'new_sha':sha(content)}
    (folder / 'manifest.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    try:
        atomic_write(TARGET, content)
        if sha(TARGET.read_bytes()) != metadata['new_sha']:
            raise RuntimeError('Fallo de verificación después de instalar')
    except Exception:
        atomic_write(TARGET, original)
        raise
    print('INSTALADO. SOLO ui/live.html ha cambiado.')
    print('Respaldo:', backup)
    print('El motor, las velas OHLC, los datos y las credenciales no se han modificado.')

def restore():
    if not TARGET.is_file():
        raise RuntimeError('No existe ui/live.html')
    current_hash = sha(TARGET.read_bytes())
    for folder in sorted(AUDIT.glob('respaldo_escala_5s_*'),reverse=True):
        backup = folder / 'live.html'
        manifest = folder / 'manifest.json'
        if not backup.is_file() or not manifest.is_file():
            continue
        data = json.loads(manifest.read_text(encoding='utf-8'))
        if current_hash != data.get('new_sha') or sha(backup.read_bytes()) != data.get('old_sha'):
            continue
        atomic_write(TARGET, backup.read_bytes())
        assert sha(TARGET.read_bytes()) == data['old_sha']
        print('RESTAURADO a la versión anterior al ajuste 5 s:', TARGET)
        return
    raise RuntimeError('La versión actual no coincide con un respaldo seguro. Nada modificado.')

def main():
    parser=argparse.ArgumentParser(description='Ajuste visual y reversible de la escala 5 s')
    g=parser.add_mutually_exclusive_group(required=True)
    g.add_argument('--verificar',action='store_true')
    g.add_argument('--instalar',action='store_true')
    g.add_argument('--restaurar',action='store_true')
    a=parser.parse_args()
    try:
        if a.verificar:verify()
        elif a.instalar:install()
        else:restore()
    except (OSError,ValueError,RuntimeError) as e:
        parser.exit(1,'DETENIDO: '+str(e)+'\n')
if __name__ == '__main__':main()
