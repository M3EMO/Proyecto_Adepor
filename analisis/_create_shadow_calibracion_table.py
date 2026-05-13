"""Crear tabla SHADOW picks_shadow_prob_calibrada_1x2_log + run backtest.

Persistir comparacion (decision actual motor) vs (decision con prob calibrada)
sobre partidos_backtest 2026. Permite validacion N>=80 antes de activar
prob_local_calibration_activa=TRUE.

MANIFESTO-CHANGE-APPROVED:bd-vue (Fase 2 SHADOW logging).
"""
import sqlite3, json
import pandas as pd
import numpy as np
con = sqlite3.connect('fondo_quant.db')
c = con.cursor()

# === 1. Crear tabla SHADOW ===
print("=== Creando tabla picks_shadow_prob_calibrada_1x2_log ===")
c.execute("""
    CREATE TABLE IF NOT EXISTS picks_shadow_prob_calibrada_1x2_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha_log TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        liga TEXT,
        id_partido TEXT,
        fecha_partido TEXT,
        cuota_1 REAL,
        cuota_x REAL,
        cuota_2 REAL,
        p1_motor REAL,
        px_motor REAL,
        p2_motor REAL,
        p1_calibrada REAL,
        px_calibrada REAL,
        p2_calibrada REAL,
        bucket_cuota_1 TEXT,
        correction_factor REAL,
        pick_motor TEXT,
        side_motor TEXT,
        ev_motor REAL,
        pick_calibrado TEXT,
        side_calibrado TEXT,
        ev_calibrado REAL,
        cambio_decision INTEGER,  -- 1 si pick_motor != pick_calibrado
        outcome_real TEXT,         -- '1', 'X', '2' (NULL si pendiente)
        hit_motor INTEGER,         -- 1 si pick_motor gano
        hit_calibrado INTEGER,     -- 1 si pick_calibrado gano (None si fue PASAR)
        pnl_motor_unit REAL,       -- yield uniforme stake=1
        pnl_calibrado_unit REAL,
        aplicado_produccion INTEGER DEFAULT 0
    )
""")
c.execute("CREATE INDEX IF NOT EXISTS idx_shadow_calib_liga ON picks_shadow_prob_calibrada_1x2_log(liga)")
c.execute("CREATE INDEX IF NOT EXISTS idx_shadow_calib_fecha ON picks_shadow_prob_calibrada_1x2_log(fecha_partido)")
print("  [ok] tabla + indices creados")

# === 2. Cargar calibracion y buckets desde config ===
calib_raw = c.execute("SELECT valor_texto FROM config_motor_valores WHERE clave='prob_local_calibration_v1' AND scope='global'").fetchone()
buckets_raw = c.execute("SELECT valor_texto FROM config_motor_valores WHERE clave='prob_local_calibration_buckets' AND scope='global'").fetchone()
if not calib_raw or not buckets_raw:
    raise RuntimeError("Configs prob_local_calibration_* no encontradas. Aplicar adepor-vue primero.")

calibration = json.loads(calib_raw[0])
buckets_def = json.loads(buckets_raw[0])
print(f"\n  Calibracion cargada: {len(calibration)} scopes (incl _global)")
print(f"  Buckets cargados: {list(buckets_def.keys())}")

# === 3. Cargar partidos_backtest 2026 con prob_1 y outcome ===
df = pd.read_sql("""
    SELECT id_partido, pais as liga, fecha as fecha_partido,
           cuota_1, cuota_x, cuota_2,
           prob_1 as p1_motor, prob_x as px_motor, prob_2 as p2_motor,
           apuesta_1x2, stake_1x2,
           goles_l, goles_v
    FROM partidos_backtest
    WHERE prob_1 IS NOT NULL AND cuota_1 IS NOT NULL
""", con)
print(f"\n  N partidos_backtest con prob_motor: {len(df)}")

# === 4. Aplicar calibracion + simular decision con probs calibradas ===
def get_bucket(c1):
    for bname, brange in buckets_def.items():
        if brange['min'] <= c1 < brange['max']:
            return bname
    return None

def get_correction(liga, bucket):
    if bucket is None: return 1.0
    if liga and liga in calibration:
        f = calibration[liga].get(bucket)
        if f is not None: return f
    f = calibration.get('_global', {}).get(bucket)
    return f if f is not None else 1.0

def calibrar_probs(p1, px, p2, c1, liga):
    bucket = get_bucket(c1)
    factor = get_correction(liga, bucket)
    if factor == 1.0 or factor is None: return p1, px, p2, bucket, 1.0
    p1_new = max(0.0, min(1.0, p1 * factor))
    rest_old = px + p2
    rest_new = 1.0 - p1_new
    if rest_old > 0 and rest_new > 0:
        scale = rest_new / rest_old
        return p1_new, px * scale, p2 * scale, bucket, factor
    return p1_new, px, p2, bucket, factor

# === 5. Replica de la logica de pick_1x2 (simplificada, sin filtros M.1/M.2/M.3) ===
# Solo evalua FAVORITO del modelo, sin filtros V5.1. Esto es ESTRICTAMENTE para
# medir el impacto de la calibracion sobre la DECISION, no para reproducir el motor.
UMBRAL_EV_BASE = 0.080
TECHO_CUOTA_1X2 = 5.0
FLOOR_PROB_MIN = 0.40

def pick_simplificado(p1, px, p2, c1, cx, c2):
    """Solo evalua favorito del modelo + EV >= umbral + cuota <= TECHO."""
    if not all(isinstance(v, (int, float)) and v > 0 for v in [c1, cx, c2]):
        return "[PASAR] Sin Cuotas", None, -100
    probs = {"LOCAL": p1, "EMPATE": px, "VISITA": p2}
    cuotas = {"LOCAL": c1, "EMPATE": cx, "VISITA": c2}
    fav_key = max(probs, key=probs.get)
    p_fav = probs[fav_key]
    c_fav = cuotas[fav_key]
    if c_fav > TECHO_CUOTA_1X2:
        return f"[PASAR] Techo Cuota", fav_key, -100
    ev_fav = (p_fav * c_fav) - 1
    umb_fav = (UMBRAL_EV_BASE * (0.5 / p_fav)) if p_fav > 0 else 999
    if p_fav < FLOOR_PROB_MIN:
        return f"[PASAR] Floor Prob (<40%)", fav_key, ev_fav
    if ev_fav >= umb_fav:
        return f"[APOSTAR] {fav_key}", fav_key, ev_fav
    return f"[PASAR] EV Insuf", fav_key, ev_fav

# === 6. Para cada partido, comparar decision motor vs calibrada ===
print("\n=== Backfill SHADOW: comparando decisiones motor vs calibrado ===")
rows_inserted = 0
df['outcome_real'] = np.where(
    df['goles_l'] > df['goles_v'], '1',
    np.where(df['goles_l'] < df['goles_v'], '2', 'X')
)

for _, r in df.iterrows():
    p1, px, p2 = r['p1_motor'], r['px_motor'], r['p2_motor']
    c1, cx, c2 = r['cuota_1'], r['cuota_x'], r['cuota_2']
    liga = r['liga']

    # Pick MOTOR (con prob original)
    pick_m, side_m, ev_m = pick_simplificado(p1, px, p2, c1, cx, c2)

    # Pick CALIBRADO (con prob calibrada)
    p1c, pxc, p2c, bucket, factor = calibrar_probs(p1, px, p2, c1, liga)
    pick_c, side_c, ev_c = pick_simplificado(p1c, pxc, p2c, c1, cx, c2)

    cambio = int(pick_m != pick_c)

    # Yield uniforme stake=1 si APOSTAR
    pnl_m = None
    if side_m and pick_m.startswith('[APOSTAR]'):
        cuota_apostada_m = {'LOCAL': c1, 'EMPATE': cx, 'VISITA': c2}.get(side_m)
        gano_m = (r['outcome_real'] == {'LOCAL':'1','EMPATE':'X','VISITA':'2'}.get(side_m))
        pnl_m = (cuota_apostada_m - 1) if gano_m else -1

    pnl_c = None
    if side_c and pick_c.startswith('[APOSTAR]'):
        cuota_apostada_c = {'LOCAL': c1, 'EMPATE': cx, 'VISITA': c2}.get(side_c)
        gano_c = (r['outcome_real'] == {'LOCAL':'1','EMPATE':'X','VISITA':'2'}.get(side_c))
        pnl_c = (cuota_apostada_c - 1) if gano_c else -1

    hit_m = None
    if side_m and pick_m.startswith('[APOSTAR]'):
        hit_m = int(r['outcome_real'] == {'LOCAL':'1','EMPATE':'X','VISITA':'2'}.get(side_m))
    hit_c = None
    if side_c and pick_c.startswith('[APOSTAR]'):
        hit_c = int(r['outcome_real'] == {'LOCAL':'1','EMPATE':'X','VISITA':'2'}.get(side_c))

    c.execute("""
        INSERT INTO picks_shadow_prob_calibrada_1x2_log
            (liga, id_partido, fecha_partido, cuota_1, cuota_x, cuota_2,
             p1_motor, px_motor, p2_motor,
             p1_calibrada, px_calibrada, p2_calibrada,
             bucket_cuota_1, correction_factor,
             pick_motor, side_motor, ev_motor,
             pick_calibrado, side_calibrado, ev_calibrado,
             cambio_decision, outcome_real,
             hit_motor, hit_calibrado, pnl_motor_unit, pnl_calibrado_unit)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (liga, r['id_partido'], r['fecha_partido'], c1, cx, c2,
          p1, px, p2, p1c, pxc, p2c, bucket, factor,
          pick_m, side_m, ev_m, pick_c, side_c, ev_c,
          cambio, r['outcome_real'], hit_m, hit_c, pnl_m, pnl_c))
    rows_inserted += 1

con.commit()
print(f"  [ok] {rows_inserted} filas insertadas\n")

# === 7. Analisis del SHADOW ===
print("="*80)
print("ANALISIS SHADOW: motor vs calibrado")
print("="*80)
shadow_df = pd.read_sql("SELECT * FROM picks_shadow_prob_calibrada_1x2_log", con)
print(f"\nN total SHADOW: {len(shadow_df)}")
print(f"  Decisiones IDENTICAS: {(shadow_df['cambio_decision']==0).sum()}")
print(f"  Decisiones CAMBIAN:   {(shadow_df['cambio_decision']==1).sum()}")

# Picks que el motor decide APOSTAR (subset relevante)
apost_motor = shadow_df[shadow_df['pick_motor'].str.startswith('[APOSTAR]', na=False)]
apost_calib = shadow_df[shadow_df['pick_calibrado'].str.startswith('[APOSTAR]', na=False)]
print(f"\nMotor APOSTABLES: {len(apost_motor)}")
print(f"  hit_motor:      {apost_motor['hit_motor'].mean():.3f}")
print(f"  yield_unit:     {apost_motor['pnl_motor_unit'].mean():+.4f}")

print(f"\nCalibrado APOSTABLES: {len(apost_calib)}")
if len(apost_calib) > 0:
    print(f"  hit_calibrado:  {apost_calib['hit_calibrado'].mean():.3f}")
    print(f"  yield_unit:     {apost_calib['pnl_calibrado_unit'].mean():+.4f}")

# Por liga
print("\nPor LIGA (subset motor apostable):")
print(apost_motor.groupby('liga').agg(
    N=('hit_motor','count'),
    hit_motor=('hit_motor','mean'),
    yld_motor=('pnl_motor_unit','mean'),
).sort_values('yld_motor').to_string(float_format=lambda x: f'{x:+.3f}'))

con.close()
print("\n[done] Tabla SHADOW + backfill completados.")
print("Para activar calibracion en motor (FASE 3): bead nuevo + modificar motor_calculadora.py")
