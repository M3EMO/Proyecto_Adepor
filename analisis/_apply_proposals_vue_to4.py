"""Aplicar PROPOSALs adepor-vue (calibracion P(LOCAL)) + adepor-to4 (M.2 per-liga).

Approved-by-lead 2026-05-13.
Snapshot pre-cambio: snapshots/fondo_quant_20260513_171414_pre_apply_proposals_vue_to4.db

Esta script persiste configs en config_motor_valores. El motor productivo
todavia NO las lee — modificacion motor_calculadora.py es FASE 2 (bead nuevo).
"""
import sqlite3, json
from datetime import datetime
con = sqlite3.connect('fondo_quant.db')
c = con.cursor()

ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
fuente_vue = 'MANIFESTO-CHANGE-APPROVED:bd-vue'
fuente_to4 = 'MANIFESTO-CHANGE-APPROVED:bd-to4'

# ============ Bead to4 — M.2 thresholds per-liga ============
print("="*80)
print("Aplicando adepor-to4: M.2 thresholds per-liga")
print("="*80)

m2_thresholds = {
    'Holanda':    20,
    'Turquia':    20,
    'Espana':     30,
    'Alemania':   50,
    'Italia':     70,
    'Inglaterra': 100,
    'Argentina':  60,    # indiferente — explicito default
    'Brasil':     60,    # indiferente — explicito default
    'Francia':    9999,  # DESACTIVAR (no bloquea nunca)
}

for liga, thr in m2_thresholds.items():
    c.execute("""
        INSERT OR REPLACE INTO config_motor_valores
            (clave, scope, valor_real, tipo, fuente, bloqueado, fecha_actualizacion)
        VALUES ('m2_n_acum_max', ?, ?, 'int', ?, 0, ?)
    """, (liga, thr, fuente_to4, ts))
    print(f"  m2_n_acum_max scope={liga:<12s} = {thr}")

# Default global (fallback si liga no en lista)
c.execute("""
    INSERT OR REPLACE INTO config_motor_valores
        (clave, scope, valor_real, tipo, fuente, bloqueado, fecha_actualizacion)
    VALUES ('m2_n_acum_max', 'global', 60, 'int', ?, 0, ?)
""", (fuente_to4, ts))
print(f"  m2_n_acum_max scope=global       = 60 (default fallback)")

# ============ Bead vue — Calibracion P(LOCAL) ============
print("\n" + "="*80)
print("Aplicando adepor-vue: calibracion P(LOCAL) post-hoc")
print("="*80)

with open('analisis/_calibracion_local_v1.json','r',encoding='utf-8') as f:
    calib = json.load(f)

# Persistir tabla calibracion como JSON en config (valor_texto)
# Schema del JSON persistido: dict { (liga|"_global"): { bucket: correction_factor } }
calib_lookup = {'_global': {}}
for c_row in calib['calibracion_global']:
    calib_lookup['_global'][c_row['bucket']] = c_row['correction_factor']
for c_row in calib['calibracion_por_liga']:
    liga = c_row['liga']
    if liga not in calib_lookup:
        calib_lookup[liga] = {}
    calib_lookup[liga][c_row['bucket']] = c_row['correction_factor']

calib_json = json.dumps(calib_lookup, ensure_ascii=False)
c.execute("""
    INSERT OR REPLACE INTO config_motor_valores
        (clave, scope, valor_texto, tipo, fuente, bloqueado, fecha_actualizacion)
    VALUES ('prob_local_calibration_v1', 'global', ?, 'json', ?, 0, ?)
""", (calib_json, fuente_vue, ts))
print(f"  prob_local_calibration_v1 (json): {len(calib_lookup)-1} ligas + 1 global, "
      f"{sum(len(v) for v in calib_lookup.values())} celdas totales")

# Activacion flag (default FALSE — motor NO la lee hasta que se modifique código)
c.execute("""
    INSERT OR REPLACE INTO config_motor_valores
        (clave, scope, valor_texto, tipo, fuente, bloqueado, fecha_actualizacion)
    VALUES ('prob_local_calibration_activa', 'global', 'FALSE', 'bool', ?, 0, ?)
""", (fuente_vue, ts))
print(f"  prob_local_calibration_activa = FALSE (flag para activacion futura)")

# Buckets definicion (para que el motor sepa cómo bucketizar cuota_1)
buckets_def = {
    '1_<1.8':       {'min': 0.0, 'max': 1.8},
    '2_[1.8,2.4)':  {'min': 1.8, 'max': 2.4},
    '3_[2.4,2.8)':  {'min': 2.4, 'max': 2.8},
    '4_[2.8,3.5)':  {'min': 2.8, 'max': 3.5},
    '5_[3.5,5.0)':  {'min': 3.5, 'max': 5.0},
    '6_>=5.0':      {'min': 5.0, 'max': 999.0},
}
c.execute("""
    INSERT OR REPLACE INTO config_motor_valores
        (clave, scope, valor_texto, tipo, fuente, bloqueado, fecha_actualizacion)
    VALUES ('prob_local_calibration_buckets', 'global', ?, 'json', ?, 0, ?)
""", (json.dumps(buckets_def), fuente_vue, ts))
print(f"  prob_local_calibration_buckets (json): {len(buckets_def)} buckets cuota_1")

# Activacion flag M.2 per-liga (default FALSE)
c.execute("""
    INSERT OR REPLACE INTO config_motor_valores
        (clave, scope, valor_texto, tipo, fuente, bloqueado, fecha_actualizacion)
    VALUES ('m2_per_liga_activo', 'global', 'FALSE', 'bool', ?, 0, ?)
""", (fuente_to4, ts))
print(f"  m2_per_liga_activo = FALSE (flag para activacion futura)")

con.commit()

# ============ Sanity check ============
print("\n" + "="*80)
print("SANITY: verificar persistencia + auditoria")
print("="*80)
rows = c.execute("""
    SELECT clave, scope, COALESCE(valor_texto, CAST(valor_real AS TEXT)), fuente
    FROM config_motor_valores
    WHERE clave LIKE 'm2_%' OR clave LIKE 'prob_local_calib%'
    ORDER BY clave, scope
""").fetchall()
print(f"\n{len(rows)} filas nuevas/actualizadas:")
for r in rows:
    val_short = str(r[2])[:60] if r[2] else 'NULL'
    print(f"  {r[0]:<35s} scope={r[1]!s:<12s} val={val_short:<60s} fuente={r[3]}")

# Verificar que history table capturo los cambios
n_hist_new = c.execute("""
    SELECT COUNT(*) FROM config_motor_valores_history
    WHERE accion IN ('INSERT','UPDATE') AND fuente_new LIKE 'MANIFESTO-CHANGE-APPROVED:%'
""").fetchone()[0]
print(f"\nFilas capturadas por triggers en config_motor_valores_history: {n_hist_new}")
print("(deberia matchear cantidad de configs aplicadas)")

con.close()
print("\n[done] Configs persistidas. NO se modifico motor_calculadora.py.")
print("FASE 2: bead nuevo para modificar motor para leer estas configs.")
