"""Hook validate_task_completed: contrato de exit codes y metricas solo en campos de texto.
Tambien fija que .claude/settings.json llame a los hooks con python3."""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "scripts" / "hooks" / "validate_task_completed.py"


def _run(payload):
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run([sys.executable, str(HOOK)], input=raw,
                          capture_output=True, text=True, timeout=60)


METRICAS_OK = ("EV_total_horizonte: 12.1 -> 13.0; N=120; snapshot_db_sha256=abc; "
               "delta_brier=-0.01; delta_yield=+0.02")


def test_tarea_operativa_pasa():
    assert _run({'title': 'Arreglar typo en README', 'description': 'nada'}).returncode == 0


def test_optimizador_sin_metricas_bloquea_y_N_no_pasa_por_letra_suelta():
    r = _run({'title': 'Calibrar RHO Brasil', 'description': 'nada nuevo ni notable'})
    assert r.returncode == 2
    assert re.search(r'^  - N$', r.stderr, re.M), r.stderr


def test_metricas_completas_en_texto_pasan():
    r = _run({'title': 'Calibrar RHO', 'description': METRICAS_OK})
    assert r.returncode == 0, r.stderr


def test_metricas_en_evidence_dict_pasan():
    evidence = {'N': 120, 'EV_total_horizonte': 13.0, 'snapshot_db_sha256': 'abc',
                'delta_brier': -0.01, 'delta_yield': 0.02}
    r = _run({'task': {'title': 'Backtest kelly', 'evidence': evidence}})
    assert r.returncode == 0, r.stderr


def test_dataops_exige_sha256():
    r = _run({'title': 'Onboarding liga Chile', 'description': 'agregar liga'})
    assert r.returncode == 2
    assert re.search(r'^  - snapshot_db_sha256$', r.stderr, re.M), r.stderr


def test_json_invalido_deja_pasar():
    assert _run("esto no es json").returncode == 0


def test_settings_llama_hooks_con_python3():
    cfg = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    cmds = [h["command"] for evento in cfg["hooks"].values()
            for grupo in evento for h in grupo["hooks"]
            if "scripts/hooks/" in h["command"]]
    assert cmds
    assert all(c.startswith("python3 scripts/hooks/") for c in cmds), cmds


def test_payload_real_task_completed_con_task_description():
    """El payload de Claude Code trae task_subject/task_description planos."""
    import importlib.util, pathlib
    ruta = pathlib.Path(__file__).resolve().parent.parent / 'scripts/hooks/validate_task_completed.py'
    spec = importlib.util.spec_from_file_location('vtc', ruta)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    txt = m._texto_de_task({'task_subject': 'Calibrar rho', 'task_description': 'N=80 EV_total_horizonte'})
    assert 'N=80' in txt and 'Calibrar rho' in txt


def test_task_created_exige_label_en_el_bead(monkeypatch):
    import importlib.util, io, json, pathlib
    ruta = pathlib.Path(__file__).resolve().parent.parent / 'scripts/hooks/validate_task_created.py'
    spec = importlib.util.spec_from_file_location('vtcr', ruta)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    payload = json.dumps({'task_description': 'Cambiar FLOOR_PROB_MIN. MANIFESTO-CHANGE-APPROVED:bd-adepor-x1'})
    for aprobado, rc in ((False, 2), (True, 0), (None, 0)):
        monkeypatch.setattr(m, '_bead_aprobado', lambda _id, a=aprobado: a)
        monkeypatch.setattr('sys.stdin', io.StringIO(payload))
        assert m.main() == rc
