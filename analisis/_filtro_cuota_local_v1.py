"""Filtro hard cuota_1 LOCAL — Recomendacion #3 (rev2).

Insight clave: apostar LOCAL ciegamente en CUALQUIER bucket es no rentable.
El filtro hard debe ser sobre EV motor calibrado, no sobre cuota cruda.

Nueva regla propuesta: bloquear apuestas LOCAL donde gap_motor_vs_mercado
(prob_1_motor - prob_1_implicito_mercado) > UMBRAL.
"""
import sqlite3, pandas as pd, numpy as np, json
con = sqlite3.connect('fondo_quant.db')

df = pd.read_sql("""
    SELECT liga, fecha, cuota_1, goles_l, goles_v
    FROM cuotas_historicas_fdco
    WHERE cuota_1 IS NOT NULL AND goles_l IS NOT NULL AND goles_v IS NOT NULL
""", con)
df['year'] = df['fecha'].str[:4]
df['won_1'] = (df['goles_l']>df['goles_v']).astype(int)
df['pnl_local_unif'] = np.where(df['won_1']==1, df['cuota_1']-1, -1)

# Buckets más finos
def bucket(c):
    if c < 1.5: return '<1.5'
    if c < 1.8: return '1.5-1.8'
    if c < 2.1: return '1.8-2.1'
    if c < 2.4: return '2.1-2.4'
    if c < 2.7: return '2.4-2.7'
    if c < 3.0: return '2.7-3.0'
    if c < 3.5: return '3.0-3.5'
    if c < 5.0: return '3.5-5.0'
    return '>=5.0'
df['bucket'] = df['cuota_1'].apply(bucket)

print("=== Yield apostar LOCAL ciegamente por bucket × año (2022+) ===")
recent = df[df['year'].isin(['2022','2023','2024','2025','2026'])]
piv = recent.pivot_table(values='pnl_local_unif',index='bucket',columns='year',aggfunc='mean')
piv_n = recent.pivot_table(values='pnl_local_unif',index='bucket',columns='year',aggfunc='count')
print(piv.to_string(float_format=lambda x: f'{x:+.3f}'))
print("\nN por celda:")
print(piv_n.fillna(0).astype(int).to_string())

print("\n=== Yield GLOBAL apostar LOCAL ciegamente por bucket (2022+) ===")
global_recent = recent.groupby('bucket').agg(
    N=('pnl_local_unif','count'),
    hit=('won_1','mean'),
    yield_unif=('pnl_local_unif','mean'),
).sort_index()
print(global_recent.to_string(float_format=lambda x: f'{x:.3f}'))

# Buckets PROHIBIDOS para apostar LOCAL: yield <-3% consistente
print("\n=== Reglas propuestas ===")
reglas = []
for bucket_name, row in global_recent.iterrows():
    if row['yield_unif'] < -0.03 and row['N'] >= 100:
        # bucket prohibido
        # Estimar impacto
        reglas.append({
            'bucket': bucket_name,
            'yield_historico': row['yield_unif'],
            'hit': row['hit'],
            'N_historico': row['N'],
            'regla': 'PROHIBIR_APOSTAR_LOCAL',
        })
        print(f"  Bucket {bucket_name}: yield {row['yield_unif']:+.3f} (hit {row['hit']:.3f}) → PROHIBIR_APOSTAR_LOCAL")
    else:
        print(f"  Bucket {bucket_name}: yield {row['yield_unif']:+.3f} → permitir (rentable o break-even)")

# Estimar impacto sobre 2026
print("\n=== Impacto proyectado: cuántos picks 2026 LOCAL se hubieran bloqueado ===")
buckets_prohibidos = [r['bucket'] for r in reglas]
print(f"Buckets prohibidos: {buckets_prohibidos}")

# Verificar sobre partidos_backtest 2026 (donde el motor apostó LOCAL)
pb = pd.read_sql("""
    SELECT pais, fecha, cuota_1, apuesta_1x2, stake_1x2,
           goles_l, goles_v, prob_1
    FROM partidos_backtest
    WHERE apuesta_1x2 LIKE '%LOCAL%'
      AND (apuesta_1x2 LIKE '[GANADA]%' OR apuesta_1x2 LIKE '[PERDIDA]%' OR apuesta_1x2 LIKE '[APOSTAR]%')
      AND cuota_1 IS NOT NULL
""", con)
pb['bucket'] = pb['cuota_1'].apply(bucket)
pb['won'] = pb['apuesta_1x2'].str.startswith('[GANADA]').astype(int)
pb['pnl'] = np.where(pb['won']==1, pb['cuota_1']-1, -1)

picks_total = len(pb)
picks_bloqueados = len(pb[pb['bucket'].isin(buckets_prohibidos)])
picks_permitidos = len(pb[~pb['bucket'].isin(buckets_prohibidos)])
yld_bloqueados = pb[pb['bucket'].isin(buckets_prohibidos)]['pnl'].mean() if picks_bloqueados>0 else np.nan
yld_permitidos = pb[~pb['bucket'].isin(buckets_prohibidos)]['pnl'].mean() if picks_permitidos>0 else np.nan

print(f"\nPicks LOCAL 2026 totales: {picks_total}")
print(f"  Bucket prohibido (regla los bloquea): {picks_bloqueados} | yield UNIF: {yld_bloqueados:+.3f}")
print(f"  Bucket permitido (regla los deja):    {picks_permitidos} | yield UNIF: {yld_permitidos:+.3f}")
if not np.isnan(yld_bloqueados) and not np.isnan(yld_permitidos):
    print(f"\nDelta yield aplicando regla: {(yld_permitidos - yld_bloqueados):+.3f} unidades por pick salvado")
    print(f"PnL salvado si todos los bucket_prohibidos hubieran sido stake=1: {-pb[pb['bucket'].isin(buckets_prohibidos)]['pnl'].sum():+.2f} unidades")

# Output
output = {
    'meta': {
        'descripcion': 'Filtro hard cuota_1 LOCAL — bloquear apuestas LOCAL en buckets sin edge histórico',
        'fuente': 'cuotas_historicas_fdco 2022-2026 (N grande)',
        'umbral_yield': -0.03,
        'estado': 'PROPUESTA — requiere PROPOSAL bead',
    },
    'buckets_prohibidos': reglas,
    'yield_por_bucket_global': global_recent.reset_index().to_dict('records'),
    'impacto_2026': {
        'picks_local_totales': picks_total,
        'bloqueados': picks_bloqueados,
        'permitidos': picks_permitidos,
        'yield_bloqueados': float(yld_bloqueados) if not np.isnan(yld_bloqueados) else None,
        'yield_permitidos': float(yld_permitidos) if not np.isnan(yld_permitidos) else None,
    }
}
with open('analisis/_filtro_cuota_local_v1.json','w', encoding='utf-8') as f:
    json.dump(output, f, indent=2, ensure_ascii=False, default=float)
print(f"\nGuardado: analisis/_filtro_cuota_local_v1.json")
