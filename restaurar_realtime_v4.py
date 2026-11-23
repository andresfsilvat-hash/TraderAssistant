"""Restaurar los dos archivos anteriores a v4, con protecciones.

No lee claves ni usa red. Ejecutar con la aplicacion cerrada.
"""
from datetime import datetime
from hashlib import sha256
import os
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent
TARGETS = ("alpaca_live.py", "ui/live.html")


def digest(data):
    return sha256(data.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")).hexdigest()


if __name__ == "__main__":
    common = None
    for relative in TARGETS:
        target = ROOT / relative
        stamps = {p.name.partition('.bak_pre_v4_')[2] for p in target.parent.glob(target.name+'.bak_pre_v4_*')}
        common = stamps if common is None else common & stamps
    if not common:
        raise SystemExit('No encuentro un par de respaldos pre-v4. No se modifico nada.')
    stamp = max(common)
    plans=[]
    for relative in TARGETS:
        target=ROOT/relative
        backup=target.with_name(target.name+'.bak_pre_v4_'+stamp)
        updated=ROOT/'realtime_v4'/relative
        if not (target.is_file() and backup.is_file() and updated.is_file()):
            raise SystemExit('No encuentro archivos de respaldo completos. No se modifico nada.')
        if digest(target.read_bytes())!=digest(updated.read_bytes()):
            raise SystemExit(f'{relative} ya fue modificado despues de instalar v4. No sobrescribire esos cambios.')
        plans.append((target, backup))
    for target, backup in plans:
        shutil.copy2(target,target.with_name(target.name+'.bak_v4_revert_'+stamp))
    for target, backup in plans:
        temp=target.with_name(target.name+'.restore_tmp')
        if temp.exists():
            raise SystemExit('Existe un archivo temporal de restauracion. No se modifico nada.')
        shutil.copy2(backup,temp)
        os.replace(temp,target)
        print('Restaurado:',target.relative_to(ROOT))
    print('Restauracion completa. Reinicia TraderAssistant normalmente.')
