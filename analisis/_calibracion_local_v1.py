"""Calibracion P(LOCAL) post-hoc — Recomendacion #1.

Objetivo: construir tabla de correccion por (liga, bucket_cuota_1) que ajuste
prob_1 del motor hacia la realidad observada en historico 2026.

Output: JSON con factor multiplicador por celda + persistencia SHADOW en config.
NO modifica motor productivo. Requiere PROPOSAL bead para promover.
"""
import sqlite3, pandas as pd, numpy as np, json
con = sqlite3.connect('fondo_quant.db')

# Historico motor: partidos_backtest 2026 (todos: liquidados Y calculados)
df = pd.read_sql("""
    SELECT pais, fecha, cuota_1, cuota_x, cuota_2,
           prob_1, prob_x, prob_2, goles_l, goles_v
    FROM partidos_backtest
    WHERE prob_1 IS NOT NULL AND cuota_1 IS NOT NULL
      AND goles_l IS NOT NULL AND goles_v IS NOT NULL
""", con)
print(f"N partidos 2026 con prob_motor + outcome: {len(df)}")

df['outcome'] = np.where(df['goles_l']>df['goles_v'], '1',
                np.where(df['goles_l']<df['goles_v'], '2', 'X'))
df['won_1'] = (df['outcome']=='1').astype(int)

# Implicit market (devig)
inv1, invx, inv2 = 1/df['cuota_1'], 1/df['cuota_x'], 1/df['cuota_2']
ov = inv1 + invx + inv2
df['imp_1'] = inv1/ov

# Buckets cuota_1
def bucket_c1(c):
    if c < 1.8: return '1_<1.8'
    if c < 2.4: return '2_[1.8,2.4)'
    if c < 2.8: return '3_[2.4,2.8)'
    if c < 3.5: return '4_[2.8,3.5)'
    if c < 5.0: return '5_[3.5,5.0)'
    return '6_>=5.0'
df['bucket'] = df['cuota_1'].apply(bucket_c1)

# Calibracion por (liga, bucket): comparar prob_1_motor vs hit_1_real
print("\n" + "="*100)
print("CALIBRACION P(LOCAL) por (liga, bucket cuota_1) — base motor 2026")
print("="*100)
print(f"{'liga':<13s} {'bucket':<14s} {'N':>4s} {'hit_real':>9s} {'p_motor':>9s} {'p_mercado':>10s} "
      f"{'gap_motor':>11s} {'gap_mercado':>13s} {'corr_factor':>12s}")
calib_table = []
for (liga, bucket), g in df.groupby(['pais','bucket']):
    if len(g) < 5: continue  # noisy
    hit = g['won_1'].mean()
    p_motor = g['prob_1'].mean()
    p_mkt = g['imp_1'].mean()
    gap_motor = p_motor - hit
    gap_mkt = p_mkt - hit
    corr = hit / p_motor if p_motor > 0 else 1.0
    print(f"  {liga:<11s} {bucket:<14s} {len(g):>4d} {hit:>+.3f}    {p_motor:>+.3f}    "
          f"{p_mkt:>+.3f}     {gap_motor:>+.3f}      {gap_mkt:>+.3f}        {corr:>+.3f}")
    calib_table.append({
        'liga': liga, 'bucket': bucket, 'N': len(g),
        'hit_real': hit, 'p_motor': p_motor, 'p_mercado': p_mkt,
        'gap_motor': gap_motor, 'gap_mercado': gap_mkt,
        'correction_factor': corr,
    })

print(f"\nTotal celdas calibracion (liga,bucket) con N>=5: {len(calib_table)}")

# AGREGAR a global (sin liga)
print("\n" + "="*100)
print("CALIBRACION GLOBAL por bucket cuota_1 (todas ligas)")
print("="*100)
print(f"{'bucket':<14s} {'N':>4s} {'hit_real':>9s} {'p_motor':>9s} {'p_mercado':>10s} {'gap_motor':>11s} {'corr_factor':>12s}")
calib_global = []
for bucket, g in df.groupby('bucket'):
    if len(g) < 10: continue
    hit = g['won_1'].mean()
    p_motor = g['prob_1'].mean()
    p_mkt = g['imp_1'].mean()
    corr = hit / p_motor if p_motor > 0 else 1.0
    print(f"  {bucket:<14s} {len(g):>4d} {hit:>+.3f}    {p_motor:>+.3f}    {p_mkt:>+.3f}     "
          f"{p_motor-hit:>+.3f}        {corr:>+.3f}")
    calib_global.append({
        'bucket': bucket, 'N': len(g),
        'hit_real': hit, 'p_motor': p_motor, 'p_mercado': p_mkt,
        'correction_factor': corr,
    })

# Guardar JSON
output = {
    'meta': {
        'descripcion': 'Calibracion post-hoc P(LOCAL) motor V0 2026',
        'fuente_datos': 'partidos_backtest 2026 (todos liquidados)',
        'N_total': len(df),
        'aplicacion': 'SHADOW — no afecta motor productivo',
        'metodologia': 'correction_factor = hit_realizado / prob_motor por (liga, bucket cuota_1)',
        'uso': 'prob_1_calibrada = prob_1_motor * correction_factor[(liga, bucket)]',
        'fallback': 'si (liga, bucket) no esta en tabla con N>=5, usar global bucket. Si tampoco, 1.0',
    },
    'calibracion_global': calib_global,
    'calibracion_por_liga': calib_table,
}
with open('analisis/_calibracion_local_v1.json', 'w', encoding='utf-8') as f:
    json.dump(output, f, indent=2, ensure_ascii=False, default=float)
print(f"\nGuardado: analisis/_calibracion_local_v1.json ({len(calib_table)} celdas liga, {len(calib_global)} celdas global)")

# Resumen impacto: en bucket donde apostó motor 2026 (3_[2.4,2.8) + 4_[2.8,3.5)
print("\n" + "="*100)
print("IMPACTO PROYECTADO: si aplicas correction_factor, cuanto baja prob_1 promedio en bucket de apuestas")
print("="*100)
target = df[df['bucket'].isin(['3_[2.4,2.8)','4_[2.8,3.5)'])].copy()
target['corr'] = 1.0
calib_lkp = {(c['liga'],c['bucket']):c['correction_factor'] for c in calib_table}
glob_lkp = {c['bucket']:c['correction_factor'] for c in calib_global}
for i,r in target.iterrows():
    key = (r['pais'], r['bucket'])
    if key in calib_lkp:
        target.at[i,'corr'] = calib_lkp[key]
    elif r['bucket'] in glob_lkp:
        target.at[i,'corr'] = glob_lkp[r['bucket']]
target['prob_1_calibrada'] = target['prob_1'] * target['corr']
print(f"\nN partidos en bucket apuestas: {len(target)}")
print(f"  prob_1 motor (sin corregir): media {target['prob_1'].mean():.3f}")
print(f"  prob_1 calibrada:            media {target['prob_1_calibrada'].mean():.3f}")
print(f"  hit_real:                    {target['won_1'].mean():.3f}")
print(f"  reduccion prob_1 promedio:   {target['prob_1'].mean()-target['prob_1_calibrada'].mean():+.3f}")
