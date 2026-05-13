"""M.2 thresholds per-liga — Recomendacion #2.

Objetivo: thresholds m2 optimos POR LIGA basados en histórico 2012-2025
(cuotas_historicas_fdco, N=23,568).

Output: JSON + SQL patch sugerido para `config_motor_valores` scope per-liga,
columna `m2_n_acum_max`. NO modifica nada en producción. Requiere PROPOSAL bead.
"""
import sqlite3, pandas as pd, numpy as np, json
con = sqlite3.connect('fondo_quant.db')

# Cargar histórico + computar n_acum_l (igual que D.2)
df = pd.read_sql("""
    SELECT liga, temp, fecha, equipo_local, equipo_visita, goles_l, goles_v, cuota_1
    FROM cuotas_historicas_fdco
    WHERE cuota_1 IS NOT NULL AND goles_l IS NOT NULL AND goles_v IS NOT NULL
""", con)
df['year'] = df['fecha'].str[:4]
df['outcome'] = np.where(df['goles_l']>df['goles_v'], '1',
                np.where(df['goles_l']<df['goles_v'], '2', 'X'))

# n_acum_l
df_s = df.sort_values(['liga','temp','fecha']).reset_index(drop=True)
log = []
for _,r in df_s.iterrows():
    log.append({'liga':r['liga'],'temp':r['temp'],'fecha':r['fecha'],'equipo':r['equipo_local']})
    log.append({'liga':r['liga'],'temp':r['temp'],'fecha':r['fecha'],'equipo':r['equipo_visita']})
log = pd.DataFrame(log).sort_values(['liga','equipo','fecha']).reset_index(drop=True)
log['n_acum'] = log.groupby(['liga','equipo']).cumcount()
n_map = log.set_index(['liga','equipo','fecha'])['n_acum']
def get_nacum(row):
    try:
        v = n_map.loc[(row['liga'], row['equipo_local'], row['fecha'])]
        if isinstance(v, pd.Series): return int(v.iloc[0])
        return int(v)
    except KeyError: return None
df_s['n_acum_l'] = df_s.apply(get_nacum, axis=1)

# Target: bucket cuota_1 [2.2, 3.5) donde motor 2026 apuesta
tg = df_s[(df_s['cuota_1']>=2.2) & (df_s['cuota_1']<3.5) & df_s['n_acum_l'].notna()].copy()
tg['won_1'] = (tg['outcome']=='1').astype(int)
tg['pnl_unit'] = np.where(tg['won_1']==1, tg['cuota_1']-1, -1)
print(f"N target (cuota_1 in [2.2,3.5)): {len(tg)}")

# Grid threshold per liga: buscar el thr que maximiza yield(>=thr) - yield(<thr)
# Si el yield(>=thr) > yield(<thr) significativamente → M.2 con ese thr funciona (bloquea perdedores)
# Si el yield(>=thr) < yield(<thr) → M.2 invierte (bloquea ganadores) → desactivar
THRESHOLDS = [20, 30, 40, 50, 60, 70, 80, 90, 100, 120, 150]

print("\n" + "="*110)
print("M.2 grid threshold POR LIGA (todos años, cuota_1 in [2.2,3.5))")
print("="*110)
print(f"{'liga':<13s} {'thr':>5s} {'N<':>5s} {'yld<':>7s} {'N>=':>5s} {'yld>=':>7s} {'gap':>7s} {'N_bloq_%':>10s}")

resultados = []
ligas = sorted(tg['liga'].unique())
for liga in ligas:
    sub = tg[tg['liga']==liga]
    best_thr = None
    best_gap = -999
    best_yld_filtrado = -999
    if len(sub) < 50: continue

    for thr in THRESHOLDS:
        lo = sub[sub['n_acum_l']<thr]
        hi = sub[sub['n_acum_l']>=thr]
        if len(lo)<10 or len(hi)<10: continue
        yl, yh = lo['pnl_unit'].mean(), hi['pnl_unit'].mean()
        # OBJETIVO: max yield(<thr) — los que apostamos. M.2 bloquea >=thr
        # Si yld_lo > yld_hi: filtro M.2 ayuda → buen thr
        # Si yld_lo < yld_hi: filtro M.2 daña → invertir o desactivar
        gap = yl - yh  # > 0 si M.2 ayuda con ese thr
        print(f"  {liga:<11s} {thr:>4d}  {len(lo):>4d} {yl:>+.3f}  {len(hi):>4d} {yh:>+.3f}  {gap:>+.3f}  {100*len(hi)/len(sub):>8.1f}%")
        if yl > best_yld_filtrado:
            best_thr = thr
            best_gap = gap
            best_yld_filtrado = yl

    # Sin filtro (baseline)
    yld_total = sub['pnl_unit'].mean()
    # Decision
    if best_thr is None:
        decision = "INSUFFICIENT_DATA"
    elif best_yld_filtrado > yld_total + 0.02 and best_gap > 0:
        decision = f"USAR thr={best_thr} (yld {yld_total:+.3f} -> {best_yld_filtrado:+.3f})"
    elif best_gap < -0.05:
        decision = f"DESACTIVAR M.2 (todos thr empeoran)"
    else:
        decision = f"INDIFERENTE (mantener thr=60 default)"

    resultados.append({
        'liga': liga, 'N_total': len(sub),
        'yield_sin_filtro': yld_total,
        'best_thr': best_thr,
        'best_yield_filtrado': best_yld_filtrado,
        'best_gap': best_gap,
        'decision': decision,
    })

print("\n" + "="*110)
print("DECISION M.2 POR LIGA")
print("="*110)
print(f"{'liga':<13s} {'N':>5s} {'yld_sin_filtro':>15s} {'best_thr':>10s} {'yld_filtrado':>14s} {'decision':<40s}")
for r in resultados:
    print(f"  {r['liga']:<11s} {r['N_total']:>5d} {r['yield_sin_filtro']:>+.4f}         {str(r['best_thr']):>5s}     {r['best_yield_filtrado']:>+.4f}      {r['decision']:<40s}")

# Generar SQL patch propuesto (NO ejecutar — solo proponer)
print("\n" + "="*110)
print("SQL PATCH SUGERIDO (NO EJECUTAR sin PROPOSAL bead aprobado)")
print("="*110)
sql_lines = ["-- M.2 thresholds per-liga calibrados sobre histórico 2012-2025"]
sql_lines.append("-- Aplicar con bead PROPOSAL aprobado (cambia comportamiento del motor)")
sql_lines.append("")
for r in resultados:
    liga = r['liga']
    if 'DESACTIVAR' in r['decision']:
        sql_lines.append(f"-- {liga}: desactivar M.2 (yld_sin_filtro {r['yield_sin_filtro']:+.3f}, best_gap negativo)")
        sql_lines.append(f"INSERT OR REPLACE INTO config_motor_valores (clave, scope, valor_real, tipo, fuente, bloqueado, fecha_actualizacion)")
        sql_lines.append(f"VALUES ('m2_n_acum_max', '{liga}', 9999, 'int', 'calibracion_m2_per_liga_2026-05-13', 0, datetime('now'));")
    elif 'USAR' in r['decision']:
        sql_lines.append(f"-- {liga}: thr={r['best_thr']} (yld {r['yield_sin_filtro']:+.3f} -> {r['best_yield_filtrado']:+.3f})")
        sql_lines.append(f"INSERT OR REPLACE INTO config_motor_valores (clave, scope, valor_real, tipo, fuente, bloqueado, fecha_actualizacion)")
        sql_lines.append(f"VALUES ('m2_n_acum_max', '{liga}', {r['best_thr']}, 'int', 'calibracion_m2_per_liga_2026-05-13', 0, datetime('now'));")
    sql_lines.append("")

sql_text = "\n".join(sql_lines)
with open('analisis/_m2_per_liga_patch.sql','w', encoding='utf-8') as f:
    f.write(sql_text)
print(f"\nPatch SQL guardado: analisis/_m2_per_liga_patch.sql")

# JSON estructurado
with open('analisis/_m2_per_liga_v1.json','w', encoding='utf-8') as f:
    json.dump({
        'meta':{
            'descripcion':'M.2 thresholds calibrados per-liga sobre histórico 2012-2025',
            'fuente':'cuotas_historicas_fdco',
            'rango_cuota_1':[2.2, 3.5],
            'metodologia':'grid search threshold maximizando yield del bucket <thr (apostable)',
            'estado':'PROPUESTA — no aplicado a producción',
        },
        'resultados': resultados,
    }, f, indent=2, ensure_ascii=False, default=float)
print(f"JSON guardado: analisis/_m2_per_liga_v1.json")
