"""Filtro hard "gap motor vs mercado" - Recomendacion #3 rev2.

Insight: apostar LOCAL ciegamente NO tiene edge en ningun bucket de cuota
(yield -0.6% a -24% segun bucket).

Hipotesis nueva: si motor predice prob_1 MUY POR ENCIMA del mercado en ese
partido, eso es senal de overfit / sobreestimacion - NO apostar.

Filtro: bloquear pick LOCAL si (prob_1_motor - prob_1_implicito_mercado) > UMBRAL.

Calibracion sobre partidos_backtest 2026 (donde tenemos prob_1 motor + outcome).
"""
import sqlite3, pandas as pd, numpy as np, json
con = sqlite3.connect('fondo_quant.db')

df = pd.read_sql("""
    SELECT pais, fecha, cuota_1, cuota_x, cuota_2, prob_1, prob_x, prob_2,
           apuesta_1x2, stake_1x2, goles_l, goles_v
    FROM partidos_backtest
    WHERE prob_1 IS NOT NULL AND cuota_1 IS NOT NULL
      AND goles_l IS NOT NULL AND goles_v IS NOT NULL
""", con)
print(f"N partidos 2026 con prob_motor + outcome: {len(df)}")

# Implicit mercado (devig)
inv1, invx, inv2 = 1/df['cuota_1'], 1/df['cuota_x'], 1/df['cuota_2']
ov = inv1 + invx + inv2
df['imp_1'] = inv1/ov

df['gap_motor_mkt_1'] = df['prob_1'] - df['imp_1']
df['won_1'] = (df['goles_l']>df['goles_v']).astype(int)
df['pnl_local'] = np.where(df['won_1']==1, df['cuota_1']-1, -1)

# Filtrar a los partidos donde motor habria apostado LOCAL (cuota[2.2, 4.0])
# o donde el motor decidio (cualquier rango)
target = df[(df['cuota_1']>=2.0) & (df['cuota_1']<4.5)].copy()
print(f"N target (cuota_1 in [2.0, 4.5)): {len(target)}")

# Distribucion gap_motor_mkt_1
print("\n=== Distribucion gap_motor_mkt_1 (prob_1_motor - prob_1_mercado) ===")
print(target['gap_motor_mkt_1'].describe().to_string())

# Buckets de gap
def gap_bucket(g):
    if g < -0.05: return '1_<-5pp_(motor_sub_predice)'
    if g < 0.05: return '2_[-5pp,+5pp]_(alineado)'
    if g < 0.10: return '3_(+5pp,+10pp]'
    if g < 0.15: return '4_(+10pp,+15pp]'
    if g < 0.20: return '5_(+15pp,+20pp]'
    return '6_>+20pp_(motor_muy_optimista)'

target['gap_bucket'] = target['gap_motor_mkt_1'].apply(gap_bucket)

print("\n=== Yield apostar LOCAL por gap_bucket ===")
res = target.groupby('gap_bucket').agg(
    N=('won_1','count'),
    hit=('won_1','mean'),
    p_motor_med=('prob_1','mean'),
    imp_med=('imp_1','mean'),
    cuota_med=('cuota_1','mean'),
    yield_unif=('pnl_local','mean'),
).sort_index()
print(res.to_string(float_format=lambda x: f'{x:.3f}'))

# Grid umbral
print("\n=== Grid umbral gap_motor_mercado: yield_si_apostamos vs yield_si_bloqueamos ===")
print(f"{'umbral':>8s}  {'N_apost':>9s} {'yld_apost':>10s}  {'N_bloq':>8s} {'yld_bloq':>10s}  {'gap':>7s}")
for u in [0.00, 0.025, 0.05, 0.075, 0.10, 0.125, 0.15, 0.175, 0.20]:
    apost = target[target['gap_motor_mkt_1'] <= u]
    bloq = target[target['gap_motor_mkt_1'] > u]
    if len(apost) < 20 or len(bloq) < 20: continue
    ya, yb = apost['pnl_local'].mean(), bloq['pnl_local'].mean()
    print(f"  >{u:>+.3f}  {len(apost):>8d} {ya:>+.4f}    {len(bloq):>7d} {yb:>+.4f}    {ya-yb:>+.4f}")

# Decision: encontrar umbral con yield_apost positivo + N>=100
print("\n=== Mejor umbral (yield apostable maximo con N>=100) ===")
best = None
for u in [0.00, 0.025, 0.05, 0.075, 0.10, 0.125, 0.15, 0.175, 0.20]:
    apost = target[target['gap_motor_mkt_1'] <= u]
    if len(apost) < 100: continue
    y = apost['pnl_local'].mean()
    if best is None or y > best[1]:
        best = (u, y, len(apost))
if best:
    print(f"  Umbral: gap_motor_mkt_1 <= {best[0]:+.3f}")
    print(f"  N apostables: {best[2]}")
    print(f"  Yield apostables: {best[1]:+.4f}")

# Output
output = {
    'meta':{
        'descripcion':'Filtro hard gap motor vs mercado para LOCAL — Rec #3 rev2',
        'fuente':'partidos_backtest 2026 (N motor + outcome disponible)',
        'rango_cuota':[2.0, 4.5],
        'metodologia':'bloquear pick LOCAL si prob_1_motor - prob_1_mercado_devig > umbral',
        'estado':'PROPUESTA — requiere PROPOSAL bead para aplicar',
    },
    'yield_por_gap_bucket': res.reset_index().to_dict('records'),
    'umbral_recomendado': {
        'umbral': float(best[0]) if best else None,
        'N_apostables': int(best[2]) if best else None,
        'yield_apostables': float(best[1]) if best else None,
    } if best else None,
}
with open('analisis/_filtro_gap_motor_mercado_v1.json','w', encoding='utf-8') as f:
    json.dump(output, f, indent=2, ensure_ascii=False, default=float)
print(f"\nGuardado: analisis/_filtro_gap_motor_mercado_v1.json")
