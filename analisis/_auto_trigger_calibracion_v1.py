"""Auto-trigger calibracion P(LOCAL) — adepor-dh0.

Evalua thresholds sobre picks_shadow_prob_calibrada_1x2_log y, si se cumplen,
enciende flag prob_local_calibration_activa=TRUE en config_motor_valores.

Thresholds (todos requeridos):
  T1) N_apostable >= 80 (motor o calibrado apuesta + outcome conocido)
  T2) yield_calibrado >= yield_motor + 0.02 (diferencia >=2pp)
  T3) hit_calibrado >= hit_motor (calibrado no empeora hit rate)
  T4) Bootstrap CI95 yield_calibrado lower-bound > yield_motor

Si OK -> flag TRUE. Idempotente. Si flag ya TRUE, no-op.
Si flag actualmente TRUE pero thresholds dejan de cumplirse (safety),
emite WARNING pero NO desactiva automaticamente (revert manual).

Idea de integracion: ejecutar al final de cada `py ejecutar_proyecto.py`
(hook FASE 5) o como cron daily.
"""
import sqlite3
import sys
import json
from datetime import datetime
import numpy as np

DB = 'fondo_quant.db'

def evaluar_thresholds(con):
    """Lee SHADOW table + computa metrics. Returns dict con decision."""
    df_rows = con.execute("""
        SELECT cuota_1, cuota_x, cuota_2,
               pick_motor, side_motor, pick_calibrado, side_calibrado,
               outcome_real, hit_motor, hit_calibrado,
               pnl_motor_unit, pnl_calibrado_unit, cambio_decision
          FROM picks_shadow_prob_calibrada_1x2_log
         WHERE outcome_real IS NOT NULL
    """).fetchall()
    if not df_rows:
        return {'decision': 'NO_DATA', 'reason': 'tabla SHADOW vacia'}

    # Filtrar solo picks apostables (motor APOSTAR o calibrado APOSTAR)
    apost_motor = [(r[10],r[8]) for r in df_rows
                    if r[3] and r[3].startswith('[APOSTAR]') and r[10] is not None]
    apost_calib = [(r[11],r[9]) for r in df_rows
                    if r[5] and r[5].startswith('[APOSTAR]') and r[11] is not None]

    metrics = {
        'N_total': len(df_rows),
        'N_apost_motor': len(apost_motor),
        'N_apost_calib': len(apost_calib),
    }

    if len(apost_motor) > 0:
        pnl_m = np.array([p for p,h in apost_motor])
        hit_m = np.mean([h for p,h in apost_motor])
        metrics['yield_motor'] = float(pnl_m.mean())
        metrics['hit_motor'] = float(hit_m)
    else:
        metrics['yield_motor'] = None
        metrics['hit_motor'] = None

    if len(apost_calib) > 0:
        pnl_c = np.array([p for p,h in apost_calib])
        hit_c = np.mean([h for p,h in apost_calib])
        metrics['yield_calibrado'] = float(pnl_c.mean())
        metrics['hit_calibrado'] = float(hit_c)
    else:
        metrics['yield_calibrado'] = None
        metrics['hit_calibrado'] = None

    # Bootstrap CI95 para yield_calibrado (lower bound)
    if len(apost_calib) >= 30:
        pnls = np.array([p for p,h in apost_calib])
        boot = np.random.default_rng(42).choice(pnls, size=(1000, len(pnls)), replace=True)
        boot_means = boot.mean(axis=1)
        metrics['yield_calib_ci95_low'] = float(np.percentile(boot_means, 2.5))
        metrics['yield_calib_ci95_high'] = float(np.percentile(boot_means, 97.5))
    else:
        metrics['yield_calib_ci95_low'] = None
        metrics['yield_calib_ci95_high'] = None

    # Evaluar thresholds
    fails = []
    if metrics['N_apost_calib'] < 80:
        fails.append(f'T1: N_apost_calib={metrics["N_apost_calib"]} < 80')
    if metrics['yield_motor'] is not None and metrics['yield_calibrado'] is not None:
        if metrics['yield_calibrado'] < metrics['yield_motor'] + 0.02:
            fails.append(f'T2: yield_cal {metrics["yield_calibrado"]:+.3f} < yield_motor {metrics["yield_motor"]:+.3f} + 0.02')
    else:
        fails.append('T2: no hay yield motor o calibrado')
    if metrics['hit_motor'] is not None and metrics['hit_calibrado'] is not None:
        if metrics['hit_calibrado'] < metrics['hit_motor']:
            fails.append(f'T3: hit_cal {metrics["hit_calibrado"]:.3f} < hit_motor {metrics["hit_motor"]:.3f}')
    if metrics['yield_calib_ci95_low'] is not None and metrics['yield_motor'] is not None:
        if metrics['yield_calib_ci95_low'] < metrics['yield_motor']:
            fails.append(f'T4: CI95 low {metrics["yield_calib_ci95_low"]:+.3f} < yield_motor {metrics["yield_motor"]:+.3f}')

    return {
        'decision': 'PASS' if not fails else 'FAIL',
        'thresholds_failed': fails,
        'metrics': metrics,
    }


def main():
    con = sqlite3.connect(DB)
    try:
        # Estado actual del flag
        cur = con.cursor()
        row = cur.execute("""
            SELECT valor_texto FROM config_motor_valores
             WHERE clave='prob_local_calibration_activa' AND scope='global'
        """).fetchone()
        flag_actual = (str(row[0]).upper() == 'TRUE') if row else False
        print(f'[INFO] Flag actual prob_local_calibration_activa = {flag_actual}')

        # Evaluar
        result = evaluar_thresholds(con)
        print('\n[METRICS]')
        for k, v in result['metrics'].items():
            if isinstance(v, float):
                print(f'  {k}: {v:+.4f}' if v < 0 or v > 1 else f'  {k}: {v:.4f}')
            else:
                print(f'  {k}: {v}')

        print(f'\n[DECISION] {result["decision"]}')
        if result['decision'] == 'FAIL':
            print('Thresholds NO cumplidos:')
            for f in result['thresholds_failed']:
                print(f'  - {f}')
            if flag_actual:
                print('\n[WARNING] Flag YA en TRUE pero thresholds no cumplen. Considerar revert manual.')
            else:
                print('\n[NO_ACTION] Flag queda FALSE.')
            return 1
        else:
            print('Todos los thresholds OK.')
            if flag_actual:
                print('[NO_ACTION] Flag YA en TRUE. Idempotente.')
                return 0
            else:
                # Encender flag
                ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                fuente = 'MANIFESTO-CHANGE-APPROVED:bd-dh0 (auto-trigger)'
                cur.execute("""
                    INSERT OR REPLACE INTO config_motor_valores
                        (clave, scope, valor_texto, tipo, fuente, bloqueado, fecha_actualizacion)
                    VALUES ('prob_local_calibration_activa', 'global', 'TRUE', 'bool', ?, 0, ?)
                """, (fuente, ts))
                con.commit()
                print(f'\n[ACTIVATED] flag prob_local_calibration_activa=TRUE persistido.')
                print(f'Proxima corrida del motor aplicara calibracion P(LOCAL) sobre prob_1.')
                return 0
    finally:
        con.close()


if __name__ == '__main__':
    sys.exit(main())
