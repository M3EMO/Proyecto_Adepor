"""[adepor-d7h F2] Motor adaptativo permanente — corre cada pipeline diario.

Pipeline:
  1. Identifica partidos liquidados desde ultima corrida (idempotente).
  2. Para cada partido: SGD step sobre V12 weights + log.
  3. Auto-audit: revisa weight_norm growth, gradient norm, brier rolling.
     Si detecta divergencia: revierte W al anchor batch.
  4. Drift detector: alerta si Brier rolling > baseline + 2sigma.
  5. Persiste timestamp de la ultima corrida en config_motor_valores.

Position en pipeline (ejecutar_proyecto.py):
  Despues de FASE 1 (motor_backtest + motor_liquidador + motor_data).
  Antes de FASE 3 (motor_calculadora).

Idempotente: si no hay partidos nuevos, hace nada.
NO afecta motor productivo: solo actualiza V12 SHADOW weights.
"""
import json
import math
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.comun.gestor_nombres import limpiar_texto
from scripts.online_sgd_v12 import sgd_step_partido, init_log_table, WARMUP_N, LR_BASE
from scripts.drift_detector import detect_drift, init_drift_table

DB = ROOT / "fondo_quant.db"
ALFA = 0.15
OLS_GLOBAL = {'beta_sot': 0.3138, 'beta_off': -0.0272, 'coef_corner': -0.0549, 'intercept': 0.4648}

# Auto-audit thresholds
WEIGHT_NORM_MAX = 50.0      # ||W|| no debe exceder este valor (sanity)
GRAD_NORM_AVG_MAX = 5.0     # avg grad sobre ultimos N steps
BRIER_DEGRADATION_PCT = 0.10  # +10% Brier = revert
REVERT_COOLDOWN_DAYS = 7    # min dias entre reverts auto


def log(msg, nivel="INFO"):
    color = {'INFO': '\033[94m', 'EXITO': '\033[92m', 'ALERTA': '\033[93m',
             'ERROR': '\033[91m', 'END': '\033[0m'}.get(nivel, '\033[0m')
    end = '\033[0m'
    hora = datetime.now().strftime("%H:%M:%S")
    print(f"{color}[{hora}] {nivel} - {msg}{end}")


def get_last_run(conn):
    row = conn.execute("""
        SELECT valor_texto FROM config_motor_valores
        WHERE clave='motor_adaptativo_last_run' AND scope='global'
    """).fetchone()
    return row[0] if row and row[0] else "1970-01-01 00:00:00"


def set_last_run(conn, ts):
    conn.execute("""
        INSERT OR REPLACE INTO config_motor_valores
            (clave, scope, valor_real, valor_texto, tipo, fuente, bloqueado)
        VALUES ('motor_adaptativo_last_run', 'global', NULL, ?, 'text', 'motor_adaptativo', 0)
    """, (ts,))


def calc_xg_v6(sot, shots, corners, goles, liga, ols):
    sot = sot or 0; shots = shots or 0; corners = corners or 0; goles = goles or 0
    shots_off = max(0, shots - sot)
    c = ols.get(liga, OLS_GLOBAL)
    xg_calc = max(0.0, sot*c['beta_sot'] + shots_off*c['beta_off'] + corners*c['coef_corner'] + c['intercept'])
    if xg_calc == 0 and goles > 0:
        return goles
    return xg_calc * 0.70 + goles * 0.30


def ajustar_xg(xg, gf, gc):
    diff = (gf or 0) - (gc or 0)
    if diff > 0:
        return xg * min(1.0 + 0.08 * math.log(1 + diff), 1.20)
    if diff < 0:
        return xg * max(1.0 - 0.05 * math.log(1 + abs(diff)), 0.80)
    return xg


def features_v12_para_partido(conn, liga, ht_norm, vt_norm, fecha):
    """Construye features V12 desde EMA shadow + var legacy + H2H DB."""
    cur = conn.cursor()

    # EMA V6 shadow
    el = cur.execute("""
        SELECT ema_xg_v6_favor_home, ema_xg_v6_contra_home,
               ema_xg_v6_favor_away, ema_xg_v6_contra_away
        FROM historial_equipos_v6_shadow WHERE equipo_norm=?
    """, (ht_norm,)).fetchone()
    ev = cur.execute("""
        SELECT ema_xg_v6_favor_home, ema_xg_v6_contra_home,
               ema_xg_v6_favor_away, ema_xg_v6_contra_away
        FROM historial_equipos_v6_shadow WHERE equipo_norm=?
    """, (vt_norm,)).fetchone()
    if not el or not ev or el[0] is None or ev[2] is None:
        return None
    xg_l = max(0.10, (el[0] + ev[3]) / 2.0)  # fav_home_l + ca_v
    xg_v = max(0.10, (ev[2] + el[1]) / 2.0)  # fav_away_v + ch_l

    # Varianza legacy
    var_l_row = cur.execute("""
        SELECT ema_var_favor_home, ema_var_contra_away FROM historial_equipos WHERE equipo_norm=?
    """, (ht_norm,)).fetchone()
    var_v_row = cur.execute("""
        SELECT ema_var_favor_away, ema_var_contra_home FROM historial_equipos WHERE equipo_norm=?
    """, (vt_norm,)).fetchone()
    var_l = ((var_l_row[0] if var_l_row and var_l_row[0] else 0.5) +
             (var_v_row[1] if var_v_row and var_v_row[1] else 0.5)) / 2.0
    var_v = ((var_v_row[0] if var_v_row and var_v_row[0] else 0.5) +
             (var_l_row[1] if var_l_row and var_l_row[1] else 0.5)) / 2.0

    # H2H sobre histórico
    rows = cur.execute("""
        SELECT ht, hg, ag, fecha FROM partidos_historico_externo
        WHERE has_full_stats=1 AND liga=? AND fecha < ?
          AND ((LOWER(REPLACE(REPLACE(ht,' ',''),'-','')) LIKE ?
                AND LOWER(REPLACE(REPLACE(at,' ',''),'-','')) LIKE ?)
            OR (LOWER(REPLACE(REPLACE(ht,' ',''),'-','')) LIKE ?
                AND LOWER(REPLACE(REPLACE(at,' ',''),'-','')) LIKE ?))
    """, (liga, fecha, f'%{ht_norm[:6]}%', f'%{vt_norm[:6]}%',
          f'%{vt_norm[:6]}%', f'%{ht_norm[:6]}%')).fetchall()
    if rows:
        prev = []
        for ht_r, hg, ag, _ in rows:
            ht_n_r = limpiar_texto(ht_r)
            if ht_n_r in (ht_norm, vt_norm):
                prev.append({'home': ht_n_r, 'hg': hg, 'ag': ag})
        if prev:
            avg_g = sum(p['hg']+p['ag'] for p in prev)/len(prev)
            n_l = sum(1 for p in prev if (p['home']==ht_norm and p['hg']>p['ag']) or
                                          (p['home']!=ht_norm and p['ag']>p['hg']))
            n_x = sum(1 for p in prev if p['hg']==p['ag'])
            f_loc = n_l/len(prev); f_x = n_x/len(prev)
        else:
            avg_g, f_loc, f_x = 2.7, 0.45, 0.26
    else:
        avg_g, f_loc, f_x = 2.7, 0.45, 0.26

    mes = int(fecha[5:7]) if len(fecha) >= 7 else 6

    return [1.0, xg_l, xg_v, xg_l-xg_v, abs(xg_l-xg_v), (xg_l+xg_v)/2.0, xg_l*xg_v,
            avg_g, f_loc, f_x, var_l, var_v, float(mes)]


def auto_audit(conn):
    """Audit que dispara revert si detecta divergencia."""
    cur = conn.cursor()
    issues = []

    # 1. Weight norm sobre ultimos 50 SGD steps
    rows = cur.execute("""
        SELECT arch, AVG(weight_norm), MAX(weight_norm), AVG(grad_norm), COUNT(*)
        FROM online_sgd_log
        WHERE id IN (SELECT id FROM online_sgd_log ORDER BY id DESC LIMIT 200)
        GROUP BY arch
    """).fetchall()
    for arch, avg_w, max_w, avg_g, n in rows:
        if max_w and max_w > WEIGHT_NORM_MAX:
            issues.append((arch, 'WEIGHT_NORM_EXCEDIDA', f"max={max_w:.2f} > {WEIGHT_NORM_MAX}"))
        if avg_g and avg_g > GRAD_NORM_AVG_MAX:
            issues.append((arch, 'GRAD_NORM_ALTA', f"avg={avg_g:.2f} > {GRAD_NORM_AVG_MAX}"))

    # 2. Brier rolling vs baseline (sobre online log)
    rows = cur.execute("""
        SELECT arch, AVG(brier_pre)
        FROM online_sgd_log
        WHERE id IN (SELECT id FROM online_sgd_log ORDER BY id DESC LIMIT 100)
          AND reverted = 0
        GROUP BY arch
    """).fetchall()
    for arch, avg_brier in rows:
        # Comparar contra baseline batch (V12 in-sample = 0.587)
        if avg_brier and avg_brier > 0.587 * (1 + BRIER_DEGRADATION_PCT):
            issues.append((arch, 'BRIER_DEGRADADO',
                            f"avg={avg_brier:.4f} > 0.587 * (1+{BRIER_DEGRADATION_PCT})"))

    # 3. Si hay issues criticos, revertir a anchor
    revertidos = 0
    for arch, code, detail in issues:
        # Cooldown: solo 1 revert cada REVERT_COOLDOWN_DAYS
        last_revert = cur.execute("""
            SELECT MAX(fecha_log) FROM online_sgd_log WHERE arch=? AND notes LIKE 'AUTO_REVERT%'
        """, (arch,)).fetchone()
        if last_revert and last_revert[0]:
            try:
                last_dt = datetime.fromisoformat(last_revert[0])
                if (datetime.now() - last_dt).days < REVERT_COOLDOWN_DAYS:
                    log(f"AUDIT issue {arch} {code} pero cooldown activo, skip", "ALERTA")
                    continue
            except Exception:
                pass

        # Restaurar weights desde anchor
        scope_liga = arch.replace('v12_', '') if arch.startswith('v12_') else 'global'
        anchor_row = cur.execute("""
            SELECT valor_texto FROM config_motor_valores
            WHERE clave='lr_v12_weights_batch_anchor' AND scope=?
        """, (scope_liga,)).fetchone()
        if anchor_row and anchor_row[0]:
            anchor = json.loads(anchor_row[0])
            current_row = cur.execute("""
                SELECT valor_texto FROM config_motor_valores
                WHERE clave='lr_v12_weights' AND scope=?
            """, (scope_liga,)).fetchone()
            if current_row:
                current = json.loads(current_row[0])
                current['W'] = anchor['W']  # solo restauro W; mean/std stay
                cur.execute("""
                    UPDATE config_motor_valores SET valor_texto=?, fecha_actualizacion=CURRENT_TIMESTAMP
                    WHERE clave='lr_v12_weights' AND scope=?
                """, (json.dumps(current), scope_liga))
                cur.execute("""
                    INSERT INTO online_sgd_log
                        (fecha_log, bead_id, arch, n_partidos_acum, grad_norm, weight_norm,
                         brier_pre, loss_pre, loss_post, delta_weight, reverted, notes)
                    VALUES (?, 'auto_audit', ?, 0, NULL, NULL, NULL, NULL, NULL, NULL, 1, ?)
                """, (datetime.now().isoformat(), arch, f"AUTO_REVERT por {code}: {detail}"))
                conn.commit()
                revertidos += 1
                log(f"AUTO-REVERT {arch} (causa: {code} {detail})", "ALERTA")

    return issues, revertidos


def main():
    print("=" * 70)
    print("[*] MOTOR ADAPTATIVO PERMANENTE — V12 SHADOW")
    print("=" * 70)

    init_log_table()
    init_drift_table()

    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    last_run = get_last_run(conn)
    log(f"Ultima corrida: {last_run}", "INFO")

    # 1. Identificar partidos liquidados desde ultima corrida
    rows = cur.execute("""
        SELECT id_partido, pais, local, visita, fecha,
               sot_l, shots_l, corners_l, sot_v, shots_v, corners_v,
               goles_l, goles_v
        FROM partidos_backtest
        WHERE sot_l IS NOT NULL AND shots_l IS NOT NULL AND corners_l IS NOT NULL
          AND goles_l IS NOT NULL AND goles_v IS NOT NULL
          AND fecha > ?
          AND LOWER(estado) IN ('liquidado', 'finalizado')
        ORDER BY fecha ASC
    """, (last_run,)).fetchall()

    log(f"Partidos liquidados nuevos: {len(rows)}", "INFO")

    # 2. Procesar cada partido: SGD step
    n_sgd = 0; n_warm = 0; n_skip = 0
    last_fecha = last_run
    for row in rows:
        id_partido, pais, local, visita, fecha, sot_l, shots_l, corners_l, sot_v, shots_v, corners_v, hg, ag = row
        ht_n = limpiar_texto(local); at_n = limpiar_texto(visita)
        if not ht_n or not at_n: n_skip += 1; continue

        feats = features_v12_para_partido(conn, pais, ht_n, at_n, fecha)
        if feats is None:
            n_skip += 1
            continue

        real = "1" if hg > ag else ("2" if hg < ag else "X")
        # Update weights por liga
        ok_l, msg_l = sgd_step_partido(conn, pais, feats, real, bead_id="motor_adaptativo")
        # Update tambien pool global (paralelo)
        ok_g, msg_g = sgd_step_partido(conn, 'global', feats, real, bead_id="motor_adaptativo")

        if 'warmup' in msg_l or 'warmup' in msg_g: n_warm += 1
        elif 'step_done' in msg_l or 'step_done' in msg_g: n_sgd += 1

        last_fecha = fecha

    log(f"SGD: {n_sgd} steps  warmup: {n_warm}  skip: {n_skip}", "EXITO" if n_sgd > 0 else "INFO")

    # 3. Auto-audit
    log("Auto-audit pesos...", "INFO")
    issues, revertidos = auto_audit(conn)
    if issues:
        log(f"Issues detectados: {len(issues)}, revertidos: {revertidos}", "ALERTA")
        for arch, code, detail in issues[:5]:
            log(f"  [{code}] {arch}: {detail}", "ALERTA")
    else:
        log("Auto-audit OK — sin divergencia", "EXITO")

    # 4. Drift detector
    log("Drift detector (ventana 30d)...", "INFO")
    try:
        alertas = detect_drift(window_days=30, dry_run=False)
        if alertas:
            log(f"Drift alertas: {len(alertas)}", "ALERTA")
        else:
            log("Drift OK — sin alertas", "EXITO")
    except Exception as e:
        log(f"Drift detector fallo: {e}", "ERROR")

    # 5. Persist last_run
    set_last_run(conn, last_fecha)
    conn.commit()
    conn.close()

    print("=" * 70)
    log(f"[*] MOTOR ADAPTATIVO COMPLETADO  last_run={last_fecha}", "EXITO")
    print("=" * 70)


if __name__ == "__main__":
    main()
