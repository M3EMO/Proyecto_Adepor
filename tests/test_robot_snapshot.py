"""P7 (docs/specs/12-producto-deploy.md): ejecutar_robot.sh hace snapshot antes del pipeline."""
import os
import shutil
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def correr(tmp_path, falla_snapshot):
    shutil.copy(ROOT / 'ejecutar_robot.sh', tmp_path / 'ejecutar_robot.sh')
    fake = tmp_path / 'fakepy'
    fake.write_text('#!/usr/bin/env bash\n'
                    'echo "$@" >> "$(dirname "$0")/llamadas.txt"\n'
                    + ('[ "$1 $2" = "adepor_guard.py snapshot" ] && exit 1\n' if falla_snapshot else '')
                    + 'exit 0\n')
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    r = subprocess.run(['bash', str(tmp_path / 'ejecutar_robot.sh')], env={**os.environ, 'ADEPOR_PYTHON': str(fake)})
    llamadas = (tmp_path / 'llamadas.txt').read_text().splitlines()
    return r.returncode, llamadas


def test_snapshot_va_antes_del_pipeline(tmp_path):
    rc, llamadas = correr(tmp_path, falla_snapshot=False)
    assert rc == 0
    assert llamadas == ['adepor_guard.py snapshot', 'ejecutar_proyecto.py']


def test_si_el_snapshot_falla_no_corre_el_pipeline(tmp_path):
    rc, llamadas = correr(tmp_path, falla_snapshot=True)
    assert rc != 0
    assert llamadas == ['adepor_guard.py snapshot']
