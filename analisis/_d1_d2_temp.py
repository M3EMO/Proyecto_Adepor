import sqlite3, pandas as pd, numpy as np
con = sqlite3.connect('fondo_quant.db')

df = pd.read_sql("""
    SELECT liga, temp, fecha, equipo_local, equipo_visita, goles_l, goles_v,
           cuota_1, cuota_x, cuota_2
    FROM cuotas_historicas_fdco
    WHERE cuota_1 IS NOT NULL AND cuota_2 IS NOT NULL AND cuota_x IS NOT NULL
      AND goles_l IS NOT NULL AND goles_v IS NOT NULL
""", con)
print(f"N partidos historico con cuotas+resultado: {len(df)}")
print(f"Ligas: {sorted(df['liga'].unique())}")
print(f"Temporadas: {sorted(df['temp'].unique())}")
df['year'] = df['fecha'].str[:4]
print("\nAno distribucion:")
print(df['year'].value_counts().sort_index().to_string())

df['outcome'] = np.where(df['goles_l']>df['goles_v'], '1',
                np.where(df['goles_l']<df['goles_v'], '2', 'X'))
df['imp_1_raw'] = 1/df['cuota_1']
df['imp_x_raw'] = 1/df['cuota_x']
df['imp_2_raw'] = 1/df['cuota_2']
overround = df['imp_1_raw']+df['imp_x_raw']+df['imp_2_raw']
df['imp_1'] = df['imp_1_raw']/overround
df['imp_x'] = df['imp_x_raw']/overround
df['imp_2'] = df['imp_2_raw']/overround

def bucket_c1(c):
    if c < 1.5: return '0_<1.5'
    if c < 1.8: return '1_[1.5,1.8)'
    if c < 2.1: return '2_[1.8,2.1)'
    if c < 2.4: return '3_[2.1,2.4)'
    if c < 2.8: return '4_[2.4,2.8)'
    if c < 3.5: return '5_[2.8,3.5)'
    if c < 5.0: return '6_[3.5,5.0)'
    return '7_>=5.0'
df['bucket_c1'] = df['cuota_1'].apply(bucket_c1)

print("\n" + "="*90)
print("D.1.A - Calibracion mercado: hit LOCAL real vs implicito por bucket cuota_1")
print("="*90)
def calib(g):
    return pd.Series({
        'N': len(g),
        'hit_1_real': (g['outcome']=='1').mean(),
        'imp_1_med': g['imp_1'].mean(),
        'delta': (g['outcome']=='1').mean() - g['imp_1'].mean(),
        'cuota_1_med': g['cuota_1'].mean(),
    })
print(df.groupby('bucket_c1').apply(calib,include_groups=False).to_string(float_format=lambda x: f'{x:+.3f}'))

print("\n" + "="*90)
print("D.1.B - Calibracion por ANO (bucket [2.4,3.5) - rango donde motor 2026 aposto)")
print("="*90)
target = df[(df['cuota_1']>=2.4) & (df['cuota_1']<3.5)].copy()
def calib_year(g):
    return pd.Series({
        'N': len(g),
        'hit_1_real': (g['outcome']=='1').mean(),
        'hit_x_real': (g['outcome']=='X').mean(),
        'hit_2_real': (g['outcome']=='2').mean(),
        'imp_1': g['imp_1'].mean(),
        'imp_x': g['imp_x'].mean(),
        'imp_2': g['imp_2'].mean(),
        'delta_1': (g['outcome']=='1').mean() - g['imp_1'].mean(),
        'pnl_local_unif': np.where(g['outcome']=='1', g['cuota_1']-1, -1).mean(),
    })
print(target.groupby('year').apply(calib_year,include_groups=False).to_string(float_format=lambda x: f'{x:+.3f}'))

print("\n" + "="*90)
print("D.1.C - Por LIGA en bucket [2.4,3.5) - todos anos")
print("="*90)
print(target.groupby('liga').apply(calib_year,include_groups=False).sort_values('delta_1').to_string(float_format=lambda x: f'{x:+.3f}'))

# D.2 - n_acum_l + M.2
print("\n\n" + "="*90)
print("D.2 - M.2 invertido: yield apostando favorito local por bucket n_acum_l")
print("="*90)

df_sorted = df.sort_values(['liga','temp','fecha']).reset_index(drop=True)
partidos_por_equipo = []
for _,r in df_sorted.iterrows():
    partidos_por_equipo.append({'liga':r['liga'],'temp':r['temp'],'fecha':r['fecha'],'equipo':r['equipo_local']})
    partidos_por_equipo.append({'liga':r['liga'],'temp':r['temp'],'fecha':r['fecha'],'equipo':r['equipo_visita']})
log = pd.DataFrame(partidos_por_equipo).sort_values(['liga','equipo','fecha']).reset_index(drop=True)
log['n_acum'] = log.groupby(['liga','equipo']).cumcount()

n_map = log.set_index(['liga','equipo','fecha'])['n_acum']

def get_nacum(row):
    try:
        v = n_map.loc[(row['liga'], row['equipo_local'], row['fecha'])]
        if isinstance(v, pd.Series): return int(v.iloc[0])
        return int(v)
    except KeyError:
        return None

df_sorted['n_acum_l'] = df_sorted.apply(get_nacum, axis=1)
print(f"N con n_acum_l computado: {df_sorted['n_acum_l'].notna().sum()}/{len(df_sorted)}")

target_m2 = df_sorted[(df_sorted['cuota_1']>=2.2) & (df_sorted['cuota_1']<3.5) & df_sorted['n_acum_l'].notna()].copy()
target_m2['bucket_m2'] = np.where(target_m2['n_acum_l']>=60, '>=60_BLOQUEADO', '<60_PASA')
target_m2['won_local'] = (target_m2['outcome']=='1').astype(int)
target_m2['pnl_unit'] = np.where(target_m2['won_local']==1, target_m2['cuota_1']-1, -1)

def m2fmt(g):
    return pd.Series({'N':len(g),'hit':g['won_local'].mean(),
                      'cuota_med':g['cuota_1'].mean(),
                      'yield_unif':g['pnl_unit'].mean(),
                      'pnl_total':g['pnl_unit'].sum()})

print(f"\nTotal target (cuota_1 in [2.2, 3.5], todos anos): N={len(target_m2)}")
print("\nGLOBAL - bucket M.2:")
print(target_m2.groupby('bucket_m2').apply(m2fmt,include_groups=False).to_string(float_format=lambda x: f'{x:+.3f}'))

print("\nPor ANO - bucket M.2:")
print(target_m2.groupby(['year','bucket_m2']).apply(m2fmt,include_groups=False).to_string(float_format=lambda x: f'{x:+.3f}'))

print("\n" + "="*90)
print("D.2.B - Grid threshold M.2 sobre historico (cuota_1 in [2.2,3.5])")
print("="*90)
print(f"{'thr':>6s} {'N<':>6s} {'hit<':>7s} {'yld<':>7s}  {'N>=':>6s} {'hit>=':>7s} {'yld>=':>7s}  {'gap':>7s}")
for thr in [20, 30, 40, 50, 60, 70, 80, 90, 100, 120, 150]:
    lo = target_m2[target_m2['n_acum_l']<thr]
    hi = target_m2[target_m2['n_acum_l']>=thr]
    if len(lo)<20 or len(hi)<20: continue
    yl, yh = lo['pnl_unit'].mean(), hi['pnl_unit'].mean()
    print(f"  {thr:>3d}   {len(lo):>5d} {lo['won_local'].mean():>+.3f}  {yl:>+.3f}   {len(hi):>5d} {hi['won_local'].mean():>+.3f}  {yh:>+.3f}   {yh-yl:>+.3f}")

print("\n" + "="*90)
print("D.2.C - Por LIGA x bucket M.2 (cuota_1 in [2.2,3.5], todos anos)")
print("="*90)
print(target_m2.groupby(['liga','bucket_m2']).apply(m2fmt,include_groups=False).to_string(float_format=lambda x: f'{x:+.3f}'))

target_m2.to_csv('analisis/_d2_m2_historico.csv', index=False)
df.to_csv('analisis/_d1_bookmaker_calib.csv', index=False)
print("\nGuardado: analisis/_d2_m2_historico.csv, analisis/_d1_bookmaker_calib.csv")
