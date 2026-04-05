import sqlite3, math
from datetime import datetime

conn = sqlite3.connect('fondo_quant.db')
c = conn.cursor()

c.execute("""
    SELECT fecha, pais, local, visita,
           prob_1, prob_x, prob_2, prob_o25, prob_u25,
           cuota_1, cuota_x, cuota_2, cuota_o25, cuota_u25,
           goles_l, goles_v,
           xg_local, xg_visita, incertidumbre,
           apuesta_shadow_1x2, stake_shadow_1x2,
           cuota_am, cuota_no_am
    FROM partidos_backtest
    WHERE estado = 'Liquidado'
    ORDER BY fecha
""")
rows = c.fetchall()

def safe(v, default=0.0):
    try: return float(v) if v is not None else default
    except: return default

partidos = []
for r in rows:
    fecha, pais, loc, vis = r[0], r[1], r[2], r[3]
    p1,px,p2,po,pu = safe(r[4]),safe(r[5]),safe(r[6]),safe(r[7]),safe(r[8])
    c1,cx,c2,co,cu = safe(r[9]),safe(r[10]),safe(r[11]),safe(r[12]),safe(r[13])
    gl,gv = int(r[14]),int(r[15])
    xgl,xgv = safe(r[16]),safe(r[17])
    incert = safe(r[18])
    ap_sh, stk_sh = r[19], safe(r[20])
    cuota_am_v, cuota_no_am_v = safe(r[21]), safe(r[22])

    res = 'LOCAL' if gl > gv else ('VISITA' if gv > gl else 'EMPATE')
    fav_modelo  = 'LOCAL' if p1 >= p2 and p1 >= px else ('VISITA' if p2 >= p1 and p2 >= px else 'EMPATE')
    impl_1  = (1/c1) if c1 > 0 else 0
    impl_2  = (1/c2) if c2 > 0 else 0
    impl_x  = (1/cx) if cx > 0 else 0
    fav_mkt = 'LOCAL' if impl_1 >= impl_2 and impl_1 >= impl_x else ('VISITA' if impl_2 >= impl_1 and impl_2 >= impl_x else 'EMPATE')
    xg_total    = xgl + xgv
    goles_total = gl  + gv

    partidos.append({
        'fecha': fecha, 'pais': pais, 'local': loc, 'visita': vis,
        'p1': p1, 'px': px, 'p2': p2, 'po': po, 'pu': pu,
        'c1': c1, 'cx': cx, 'c2': c2, 'co': co, 'cu': cu,
        'gl': gl, 'gv': gv, 'res': res,
        'xgl': xgl, 'xgv': xgv, 'xg_total': xg_total,
        'goles_total': goles_total,
        'incert': incert,
        'fav_mod': fav_modelo, 'fav_mkt': fav_mkt,
        'ap_sh': ap_sh, 'stk_sh': stk_sh,
        'cuota_am': cuota_am_v, 'cuota_no_am': cuota_no_am_v,
    })

def hit_shadow(p):
    if not p['ap_sh'] or '[APOSTAR]' not in str(p['ap_sh']): return None
    if 'LOCAL'  in p['ap_sh']: return 1 if p['res'] == 'LOCAL'  else 0
    if 'VISITA' in p['ap_sh']: return 1 if p['res'] == 'VISITA' else 0
    if 'EMPATE' in p['ap_sh']: return 1 if p['res'] == 'EMPATE' else 0
    return None

print(f"Total partidos liquidados: {len(partidos)}")
print()

# =====================================================================
# A. CALIBRACION — prob del modelo vs frecuencia real
# =====================================================================
sep = "=" * 68
print(sep)
print("A. CALIBRACION COMPLETA — prob modelo vs frecuencia real")
print(sep)
buckets = [(0.30,0.35),(0.35,0.40),(0.40,0.45),(0.45,0.50),(0.50,0.55),(0.55,0.65),(0.65,1.0)]
for bmin, bmax in buckets:
    casos = []
    for p in partidos:
        for outcome, prob in [('LOCAL', p['p1']), ('EMPATE', p['px']), ('VISITA', p['p2'])]:
            if bmin <= prob < bmax:
                casos.append(1 if p['res'] == outcome else 0)
    n = len(casos)
    acc = sum(casos) / n if n else 0
    mid = (bmin + bmax) / 2
    sesgo = acc - mid
    flag = '  <<< SESGO ALTO' if abs(sesgo) > 0.08 else ''
    print(f"  [{bmin:.0%}-{bmax:.0%})  n={n:>3}  real={acc:.1%}  esperado={mid:.1%}  sesgo={sesgo:+.1%}{flag}")
print()

# =====================================================================
# B. PRECISION xG — error por liga
# =====================================================================
print(sep)
print("B. PRECISION xG — bias y MAE por liga")
print(sep)
for liga in ['Brasil', 'Argentina', 'Turquia', 'GLOBAL']:
    ps = [p for p in partidos if p['pais'] == liga] if liga != 'GLOBAL' else partidos
    if not ps: continue
    err_l = [p['xgl'] - p['gl'] for p in ps]
    err_v = [p['xgv'] - p['gv'] for p in ps]
    bias_l = sum(err_l) / len(err_l)
    bias_v = sum(err_v) / len(err_v)
    mae_l  = sum(abs(e) for e in err_l) / len(err_l)
    mae_v  = sum(abs(e) for e in err_v) / len(err_v)
    flag_l = '  <<< SOBREESTIMA LOCAL'  if bias_l >  0.25 else ('  <<< SUBESTIMA LOCAL'  if bias_l < -0.25 else '')
    flag_v = '  <<< SOBREESTIMA VISITA' if bias_v >  0.25 else ('  <<< SUBESTIMA VISITA' if bias_v < -0.25 else '')
    print(f"  {liga:<12} n={len(ps):>2}  LOCAL  bias={bias_l:+.3f} MAE={mae_l:.3f}{flag_l}")
    print(f"  {'':12}       VISITA bias={bias_v:+.3f} MAE={mae_v:.3f}{flag_v}")
print()

# =====================================================================
# C. xG vs GOLES TOTALES — sesgo O/U por rango de xG
# =====================================================================
print(sep)
print("C. SESGO OVER/UNDER — xG total del modelo vs goles reales")
print(sep)
rangos_xg = [(0, 1.8), (1.8, 2.2), (2.2, 2.5), (2.5, 2.8), (2.8, 3.5), (3.5, 99)]
for rmin, rmax in rangos_xg:
    grupo = [p for p in partidos if rmin <= p['xg_total'] < rmax]
    if not grupo: continue
    real_over  = sum(1 for p in grupo if p['goles_total'] > 2.5)
    real_under = sum(1 for p in grupo if p['goles_total'] < 2.5)
    real_exact = sum(1 for p in grupo if p['goles_total'] == 2)  # marcador tipico "empate del modelo"
    avg_xg = sum(p['xg_total'] for p in grupo) / len(grupo)
    avg_gl = sum(p['goles_total'] for p in grupo) / len(grupo)
    bias   = avg_xg - avg_gl
    print(f"  xG [{rmin:.1f}-{rmax:.1f})  n={len(grupo):>2}  xG_prom={avg_xg:.2f}  goles_prom={avg_gl:.2f}  bias={bias:+.2f}  over={real_over/len(grupo):.0%}  under={real_under/len(grupo):.0%}")
print()

# =====================================================================
# D. DESACUERDO MODELO-MERCADO — profundidad
# =====================================================================
print(sep)
print("D. DESACUERDO MODELO vs MERCADO — hit por tipo y divergencia")
print(sep)
acuerdo = [p for p in partidos if p['fav_mod'] == p['fav_mkt']]
desacuerdo = [p for p in partidos if p['fav_mod'] != p['fav_mkt']]
print(f"  Acuerdo    (mod=mkt)  n={len(acuerdo):>2}  hit_fav_mod={sum(1 for p in acuerdo if p['res']==p['fav_mod'])/len(acuerdo):.1%}" if acuerdo else "")
print(f"  Desacuerdo (mod≠mkt)  n={len(desacuerdo):>2}  hit_fav_mod={sum(1 for p in desacuerdo if p['res']==p['fav_mod'])/len(desacuerdo):.1%}" if desacuerdo else "")
print()

# Por dirección de desacuerdo
for mkt_fav, mod_fav in [('VISITA','LOCAL'),('LOCAL','VISITA'),('EMPATE','LOCAL'),('EMPATE','VISITA')]:
    sub = [p for p in partidos if p['fav_mkt'] == mkt_fav and p['fav_mod'] == mod_fav]
    if not sub: continue
    hits = sum(1 for p in sub if p['res'] == mod_fav)
    print(f"  Mkt={mkt_fav:<8} Mod={mod_fav:<8} n={len(sub):>2}  hit_modelo={hits/len(sub):.1%}")
    for p in sub:
        div = p['p1' if mod_fav=='LOCAL' else 'p2'] - (1/(p['c1' if mod_fav=='LOCAL' else 'c2']) if (p['c1' if mod_fav=='LOCAL' else 'c2'])>0 else 0)
        r = 'G' if p['res']==mod_fav else 'P'
        print(f"    {r} {p['pais']:<12} {p['local'][:16]:<16} vs {p['visita'][:16]:<16}  div={div:+.3f}")
print()

# =====================================================================
# E. INCERTIDUMBRE — hit rate por nivel
# =====================================================================
print(sep)
print("E. INCERTIDUMBRE vs HIT RATE y vs GOLES REALES")
print(sep)
buckets_i = [(0, 0.10),(0.10, 0.20),(0.20, 0.30),(0.30, 1.0)]
for bmin, bmax in buckets_i:
    ps_i = [p for p in partidos if bmin <= p['incert'] < bmax]
    if not ps_i: continue
    hs = [hit_shadow(p) for p in ps_i if hit_shadow(p) is not None]
    avg_goles = sum(p['goles_total'] for p in ps_i) / len(ps_i)
    avg_inc   = sum(p['incert'] for p in ps_i) / len(ps_i)
    hit_str   = f"{sum(hs)/len(hs):.1%} ({len(hs)} ap)" if hs else "sin apuestas"
    print(f"  incert [{bmin:.2f}-{bmax:.2f})  n={len(ps_i):>2}  hit_shadow={hit_str:<18}  goles_prom={avg_goles:.2f}  incert_med={avg_inc:.3f}")
print()

# =====================================================================
# F. PATRON DE GOLES — marcadores exactos
# =====================================================================
print(sep)
print("F. DISTRIBUCIÓN DE MARCADORES REALES vs xG esperado")
print(sep)
from collections import Counter
marcadores = Counter(f"{p['gl']}-{p['gv']}" for p in partidos)
print("  Marcadores más frecuentes:")
for marc, cnt in marcadores.most_common(10):
    gl_m, gv_m = int(marc.split('-')[0]), int(marc.split('-')[1])
    avg_xg_este = [p for p in partidos if p['gl']==gl_m and p['gv']==gv_m]
    avg_xg_str  = f"xG_prom={sum(p['xg_total'] for p in avg_xg_este)/len(avg_xg_este):.2f}" if avg_xg_este else ""
    print(f"    {marc}  x{cnt}  {avg_xg_str}")
print()

# =====================================================================
# G. SESGO LOCAL vs VISITANTE
# =====================================================================
print(sep)
print("G. SESGO LOCAL vs VISITANTE — modelo vs realidad")
print(sep)
n = len(partidos)
freq_loc = sum(1 for p in partidos if p['res']=='LOCAL') / n
freq_emp = sum(1 for p in partidos if p['res']=='EMPATE') / n
freq_vis = sum(1 for p in partidos if p['res']=='VISITA') / n
avg_p1 = sum(p['p1'] for p in partidos) / n
avg_px = sum(p['px'] for p in partidos) / n
avg_p2 = sum(p['p2'] for p in partidos) / n
print(f"  {'':8} {'Modelo (media)':>16} {'Real (freq)':>14} {'Sesgo':>8}")
for label, pm, fr in [('LOCAL', avg_p1, freq_loc),('EMPATE', avg_px, freq_emp),('VISITA', avg_p2, freq_vis)]:
    flag = '  <<< SESGO' if abs(pm-fr) > 0.05 else ''
    print(f"  {label:<8} {pm:>16.1%} {fr:>14.1%} {pm-fr:>+8.1%}{flag}")
print()

# =====================================================================
# H. CLV (Closing Line Value) proxy con cuota_am
# =====================================================================
print(sep)
print("H. CLV PROXY — cuota apertura vs cuota americanas (mercado)")
print(sep)
clv_data = []
for p in partidos:
    if not p['ap_sh'] or '[APOSTAR]' not in str(p['ap_sh']): continue
    if 'LOCAL' in p['ap_sh']:
        c_ap, c_mkt = p['c1'], p['cuota_am']
    elif 'VISITA' in p['ap_sh']:
        c_ap, c_mkt = p['c2'], p['cuota_no_am']
    else: continue
    if c_ap <= 0 or c_mkt <= 0: continue
    clv = c_ap / c_mkt - 1
    hit = hit_shadow(p)
    clv_data.append((clv, hit, p['pais'], p['local'], p['visita']))

if clv_data:
    clv_pos = [(c,h) for c,h,*_ in clv_data if c > 0]
    clv_neg = [(c,h) for c,h,*_ in clv_data if c <= 0]
    print(f"  CLV positivo (ap > mkt): n={len(clv_pos):>2}  hit={sum(h for _,h in clv_pos)/len(clv_pos):.1%}" if clv_pos else "  CLV positivo: ninguno")
    print(f"  CLV negativo (ap < mkt): n={len(clv_neg):>2}  hit={sum(h for _,h in clv_neg)/len(clv_neg):.1%}" if clv_neg else "  CLV negativo: ninguno")
    print()
    print(f"  Detalle:")
    for clv, hit, pais, loc, vis in sorted(clv_data, key=lambda x: x[0], reverse=True):
        r = 'G' if hit else 'P'
        print(f"    CLV={clv:+.3f} {r}  {pais:<12} {loc[:18]:<18} vs {vis[:18]}")
else:
    print("  Sin datos de cuota_am suficientes")
print()

# =====================================================================
# I. EQUIPOS MAS SOBRE/SUBESTIMADOS
# =====================================================================
print(sep)
print("I. SESGO xG POR EQUIPO (min 2 partidos)")
print(sep)
equipos = {}
for p in partidos:
    for nombre, xg, goles in [(p['local'], p['xgl'], p['gl']), (p['visita'], p['xgv'], p['gv'])]:
        if nombre not in equipos:
            equipos[nombre] = []
        equipos[nombre].append(xg - goles)

sesgos = [(n, len(d), sum(d)/len(d)) for n,d in equipos.items() if len(d) >= 2]
sesgos.sort(key=lambda x: abs(x[2]), reverse=True)
for nombre, n_eq, bias in sesgos[:15]:
    tipo = 'SOBREESTIMADO' if bias > 0.3 else ('SUBESTIMADO' if bias < -0.3 else 'ok')
    bar  = ('▲' * min(5, int(abs(bias)/0.25)) if bias > 0 else '▼' * min(5, int(abs(bias)/0.25)))
    print(f"  {nombre:<28} n={n_eq}  bias={bias:+.3f}  {bar} {tipo}")
print()

# =====================================================================
# J. DELTA xG (dominancia) vs RESULTADO
# =====================================================================
print(sep)
print("J. DOMINANCIA xG vs RESULTADO REAL")
print(sep)
rangos_delta = [(0,0.2,'equilibrio'),(0.2,0.5,'leve'),(0.5,0.9,'moderado'),(0.9,99,'alto')]
for dmin, dmax, label in rangos_delta:
    grupo = [p for p in partidos if dmin <= abs(p['xgl']-p['xgv']) < dmax]
    if not grupo: continue
    fav_gana = sum(1 for p in grupo if p['res'] == ('LOCAL' if p['xgl']>=p['xgv'] else 'VISITA'))
    empates  = sum(1 for p in grupo if p['res'] == 'EMPATE')
    sorpresa = sum(1 for p in grupo if p['res'] == ('VISITA' if p['xgl']>=p['xgv'] else 'LOCAL'))
    print(f"  delta [{dmin:.1f}-{dmax:.1f}) {label:<12} n={len(grupo):>2}  fav_gana={fav_gana/len(grupo):.0%}  empate={empates/len(grupo):.0%}  sorpresa={sorpresa/len(grupo):.0%}")
print()

# =====================================================================
# K. LIGA vs RESULTADO
# =====================================================================
print(sep)
print("K. RESULTADO REAL POR LIGA")
print(sep)
for liga in ['Brasil', 'Argentina', 'Turquia']:
    ps = [p for p in partidos if p['pais'] == liga]
    if not ps: continue
    loc = sum(1 for p in ps if p['res']=='LOCAL')
    emp = sum(1 for p in ps if p['res']=='EMPATE')
    vis = sum(1 for p in ps if p['res']=='VISITA')
    n_l = len(ps)
    avg_goles = sum(p['goles_total'] for p in ps) / n_l
    avg_xg    = sum(p['xg_total'] for p in ps) / n_l
    print(f"  {liga:<12} n={n_l:>2}  LOCAL={loc/n_l:.0%}  EMPATE={emp/n_l:.0%}  VISITA={vis/n_l:.0%}  goles_prom={avg_goles:.2f}  xG_prom={avg_xg:.2f}")

conn.close()
print()
print("=== FIN DEL ANALISIS ===")
