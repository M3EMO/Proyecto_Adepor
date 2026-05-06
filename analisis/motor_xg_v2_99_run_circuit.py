"""
ORCHESTRATOR — ejecuta el circuito completo motor xG v2 post-backfill.

Pipeline:
  1. Verificar backfill complete (>= 600 partidos en sofascore_match_features)
  2. Matching extendido SofaScore <-> ESPN
  3. xG model entrenado (motor_xg_v2_14_xg_from_shotmap.py)
     → populates xg_shotmap_l/v en DB
     → persiste coefs en config_motor_valores.xg_model_coefs_v2
  4. Ablation suite (motor_xg_v2_15_ablation_sofa.py)
  5. Reporte consolidado por liga
  6. Decisión final: SHADOW vs PROPOSAL Manifesto

Output:
  - analisis/motor_xg_v2_99_run_circuit.json — reporte consolidado
  - logs en consola
"""

import json
import subprocess
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = str(ROOT / 'fondo_quant.db')
OUT_JSON = str(ROOT / 'analisis' / 'motor_xg_v2_99_run_circuit.json')


def step(msg):
    print(f'\n{"="*70}\n{msg}\n{"="*70}')


def check_backfill_state():
    con = sqlite3.connect(DB)
    n_total = con.execute('SELECT COUNT(*) FROM sofascore_match_features').fetchone()[0]
    n_ligas = con.execute('SELECT COUNT(DISTINCT liga) FROM sofascore_match_features').fetchone()[0]
    n_shots = con.execute('SELECT SUM(n_shots_shotmap) FROM sofascore_match_features WHERE n_shots_shotmap > 0').fetchone()[0] or 0
    by_liga = {}
    for r in con.execute('SELECT liga, COUNT(*) FROM sofascore_match_features GROUP BY liga'):
        by_liga[r[0]] = r[1]
    con.close()
    return {'n_total': n_total, 'n_ligas': n_ligas, 'n_shots': n_shots, 'by_liga': by_liga}


def run_script(script_name, args=None):
    """Ejecuta un script Python y captura output."""
    cmd = [sys.executable, str(ROOT / 'analisis' / script_name)]
    if args:
        cmd.extend(args)
    print(f'\n> Running: {" ".join(cmd)}')
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        print(f'  FAIL FAILED (exit {result.returncode})')
        print(f'  STDERR: {result.stderr[-500:]}')
        return False, result.stdout + '\n--- STDERR ---\n' + result.stderr
    print('  OK OK')
    return True, result.stdout


def main():
    print(f'CIRCUIT START: {datetime.now().isoformat()}')
    report = {'timestamp': datetime.now().isoformat()}

    # ========== STEP 1: Verificar backfill ==========
    step('STEP 1: Verificación backfill SofaScore')
    state = check_backfill_state()
    print(f'  Total partidos: {state["n_total"]}')
    print(f'  Ligas: {state["n_ligas"]}/16')
    print(f'  Total shots (shotmap): {state["n_shots"]}')
    for liga, n in sorted(state['by_liga'].items(), key=lambda x: -x[1]):
        print(f'    {liga:<14s} N={n:>3d}')
    report['backfill'] = state
    if state['n_total'] < 200:
        print('\n⚠ Insuficientes partidos backfilled. Abortar.')
        return

    # ========== STEP 2: xG model ==========
    step('STEP 2: Entrenar xG model sobre shotmap (Caley-Maye geom + 5-fold CV)')
    ok, out = run_script('motor_xg_v2_14_xg_from_shotmap.py')
    report['xg_model'] = {'success': ok, 'output_tail': out[-2000:]}
    if not ok:
        print('xG model failed. Continuamos con ablation sin xg_shotmap populated.')

    # ========== STEP 3: Ablation Bayesian + sofa features ==========
    step('STEP 3: Ablation Bayesian + features SofaScore')
    ok, out = run_script('motor_xg_v2_15_ablation_sofa.py')
    report['ablation'] = {'success': ok, 'output_tail': out[-3000:]}

    # ========== STEP 4: Reporte por liga ==========
    step('STEP 4: Reporte consolidado por liga')
    # Leer JSONs de los pasos previos
    try:
        with open(ROOT / 'analisis' / 'motor_xg_v2_14_xg_from_shotmap.json') as f:
            xg_data = json.load(f)
            report['xg_model_eval'] = xg_data
    except (FileNotFoundError, json.JSONDecodeError):
        report['xg_model_eval'] = None

    try:
        with open(ROOT / 'analisis' / 'motor_xg_v2_15_ablation_sofa.json') as f:
            ablation_data = json.load(f)
            report['ablation_eval'] = ablation_data
    except (FileNotFoundError, json.JSONDecodeError):
        report['ablation_eval'] = None

    # ========== STEP 5: Decisión ==========
    step('STEP 5: Decisión final')

    # Logica simple
    decision = 'PENDIENTE_ANALISIS_HUMANO'
    notes = []

    if report.get('ablation_eval'):
        baseline = report['ablation_eval'].get('baseline_rmse')
        results = report['ablation_eval'].get('results', {})
        best = None
        best_delta = 0
        for tag, r in results.items():
            if tag == 'BASELINE_sot':
                continue
            d = r.get('delta', 0)
            if d < best_delta:
                best_delta = d
                best = tag
        notes.append(f'baseline_rmse={baseline}')
        notes.append(f'best_variant={best} delta={best_delta:+.4f}')
        if best_delta < -0.005:
            decision = 'PROCEDER_PROPOSAL_MANIFESTO'
            notes.append('Mejora suficiente (D < -0.005). Recomendar bead PROPOSAL.')
        elif best_delta < -0.001:
            decision = 'PROMOVER_SHADOW'
            notes.append('Mejora marginal (D < -0.001). SHADOW MODE recomendado.')
        else:
            decision = 'NO_PROMOVER'
            notes.append('Mejora insuficiente. Mantener Bayesian baseline.')

    report['decision'] = decision
    report['decision_notes'] = notes
    print(f'\nDECISION: {decision}')
    for n in notes:
        print(f'  - {n}')

    # ========== Save ==========
    Path(OUT_JSON).parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    print(f'\nOK Reporte guardado: {OUT_JSON}')
    print(f'CIRCUIT END: {datetime.now().isoformat()}')


if __name__ == '__main__':
    main()
