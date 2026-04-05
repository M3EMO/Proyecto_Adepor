import sqlite3, math

conn = sqlite3.connect('fondo_quant.db')
c = conn.cursor()

c.execute("""
    SELECT id_partido, pais, local, visita,
           prob_1, prob_x, prob_2, prob_o25, prob_u25,
           cuota_1, cuota_x, cuota_2, cuota_o25, cuota_u25,
           goles_l, goles_v, apuesta_1x2, apuesta_ou,
           stake_1x2, stake_ou, incertidumbre, estado
    FROM partidos_backtest
    WHERE goles_l IS NOT NULL AND goles_v IS NOT NULL
    ORDER BY id_partido ASC
""")
rows = c.fetchall()
conn.close()

print(f"Partidos liquidados con resultado: {len(rows)}\n")

# ============================================================
# 1. CALIBRACION DEL MODELO
# ============================================================
print("=" * 65)
print("1. CALIBRACION: frecuencia real vs prob media del modelo")
print("=" * 65)

buckets_cal = {
    '0-20%':  {'total': 0, 'hits': 0, 'sum_prob': 0.0},
    '20-35%': {'total': 0, 'hits': 0, 'sum_prob': 0.0},
    '35-50%': {'total': 0, 'hits': 0, 'sum_prob': 0.0},
    '50-65%': {'total': 0, 'hits': 0, 'sum_prob': 0.0},
    '65-80%': {'total': 0, 'hits': 0, 'sum_prob': 0.0},
    '80%+':   {'total': 0, 'hits': 0, 'sum_prob': 0.0},
}

for r in rows:
    id_p, pais, local, visita, p1, px, p2, po, pu, c1, cx, c2, co, cu, gl, gv, ap1, apou, stk1, stkou, incert, estado = r
    for prob, outcome in [(p1, gl > gv), (px, gl == gv), (p2, gl < gv)]:
        if not prob:
            continue
        if   prob < 0.20: b = '0-20%'
        elif prob < 0.35: b = '20-35%'
        elif prob < 0.50: b = '35-50%'
        elif prob < 0.65: b = '50-65%'
        elif prob < 0.80: b = '65-80%'
        else:             b = '80%+'
        buckets_cal[b]['total'] += 1
        buckets_cal[b]['sum_prob'] += prob
        buckets_cal[b]['hits'] += int(outcome)

for b, v in buckets_cal.items():
    if v['total'] == 0:
        continue
    freq_real = v['hits'] / v['total']
    avg_pred  = v['sum_prob'] / v['total']
    sesgo = freq_real - avg_pred
    print(f"  {b:8s}: n={v['total']:4d}  pred_avg={avg_pred:.1%}  real={freq_real:.1%}  sesgo={sesgo:+.1%}")

# ============================================================
# 2. PATRON LOCAL vs VISITANTE
# ============================================================
print("\n" + "=" * 65)
print("2. PATRON LOCAL vs VISITANTE (favorito del modelo)")
print("=" * 65)

stats_lv = {
    'LOCAL':  {'n': 0, 'hits': 0},
    'VISITA': {'n': 0, 'hits': 0},
    'EMPATE': {'n': 0, 'hits': 0},
}

for r in rows:
    id_p, pais, local, visita, p1, px, p2, po, pu, c1, cx, c2, co, cu, gl, gv, ap1, apou, stk1, stkou, incert, estado = r
    if not (p1 and px and p2):
        continue
    fav_key = max([('LOCAL', p1, gl > gv), ('EMPATE', px, gl == gv), ('VISITA', p2, gl < gv)], key=lambda x: x[1])
    stats_lv[fav_key[0]]['n'] += 1
    stats_lv[fav_key[0]]['hits'] += int(fav_key[2])

for k, v in stats_lv.items():
    if v['n'] == 0:
        continue
    hit = v['hits'] / v['n']
    print(f"  {k:8s} es favorito: {v['n']:3d} veces  |  hit rate: {hit:.1%}")

# ============================================================
# 3. EMPATES: modelo vs mercado vs realidad
# ============================================================
print("\n" + "=" * 65)
print("3. EMPATES: modelo vs mercado implícito vs frecuencia real")
print("=" * 65)

total_x, empates_reales = 0, 0
sum_prob_mod, sum_prob_mkt = 0.0, 0.0

for r in rows:
    id_p, pais, local, visita, p1, px, p2, po, pu, c1, cx, c2, co, cu, gl, gv, ap1, apou, stk1, stkou, incert, estado = r
    if not (px and cx and cx > 1):
        continue
    total_x += 1
    if gl == gv:
        empates_reales += 1
    sum_prob_mod += px
    sum_prob_mkt += 1.0 / cx

avg_mod = sum_prob_mod / total_x if total_x else 0
avg_mkt = sum_prob_mkt / total_x if total_x else 0
freq_real = empates_reales / total_x if total_x else 0
print(f"  Frecuencia real empates:       {freq_real:.1%}  ({empates_reales}/{total_x})")
print(f"  Prob promedio MODELO (px):     {avg_mod:.1%}  (sesgo vs real: {avg_mod - freq_real:+.1%})")
print(f"  Prob promedio MERCADO (1/cx):  {avg_mkt:.1%}  (sesgo vs real: {avg_mkt - freq_real:+.1%})")

# ============================================================
# 4. RENDIMIENTO POR LIGA
# ============================================================
print("\n" + "=" * 65)
print("4. RENDIMIENTO DEL MODELO POR LIGA")
print("=" * 65)

ligas = {}
for r in rows:
    id_p, pais, local, visita, p1, px, p2, po, pu, c1, cx, c2, co, cu, gl, gv, ap1, apou, stk1, stkou, incert, estado = r
    if pais not in ligas:
        ligas[pais] = {'n': 0, 'fav_ok': 0, 'brier': [], 'over': 0, 'empates': 0}
    l = ligas[pais]
    l['n'] += 1
    if gl == gv:
        l['empates'] += 1
    if (gl + gv) > 2:
        l['over'] += 1
    if p1 and px and p2:
        fav = max([('L', p1, gl > gv), ('X', px, gl == gv), ('V', p2, gl < gv)], key=lambda x: x[1])
        if fav[2]:
            l['fav_ok'] += 1
        o1 = 1 if gl > gv else 0
        ox = 1 if gl == gv else 0
        o2 = 1 if gl < gv else 0
        bs = (p1 - o1) ** 2 + (px - ox) ** 2 + (p2 - o2) ** 2
        l['brier'].append(bs)

for pais, l in sorted(ligas.items(), key=lambda x: -x[1]['n']):
    n = l['n']
    hit = l['fav_ok'] / n
    avg_bs = sum(l['brier']) / len(l['brier']) if l['brier'] else 0
    rate_x = l['empates'] / n
    rate_ov = l['over'] / n
    print(f"  {pais:12s}: n={n:3d}  hit_fav={hit:.1%}  BS={avg_bs:.3f}  empates={rate_x:.1%}  over={rate_ov:.1%}")

# ============================================================
# 5. OVER/UNDER calibracion
# ============================================================
print("\n" + "=" * 65)
print("5. MERCADO O/U 2.5: modelo vs resultado real")
print("=" * 65)

over_real, under_real = 0, 0
n_ou = 0
sum_po, sum_pu = 0.0, 0.0
model_fav_ok = 0

for r in rows:
    id_p, pais, local, visita, p1, px, p2, po, pu, c1, cx, c2, co, cu, gl, gv, ap1, apou, stk1, stkou, incert, estado = r
    if not (po and pu):
        continue
    n_ou += 1
    es_over = (gl + gv) > 2
    if es_over:
        over_real += 1
    else:
        under_real += 1
    sum_po += po
    sum_pu += pu
    fav_ou = 'OVER' if po > pu else 'UNDER'
    if (fav_ou == 'OVER' and es_over) or (fav_ou == 'UNDER' and not es_over):
        model_fav_ok += 1

if n_ou:
    print(f"  Partidos con O/U probs: {n_ou}")
    print(f"  Over reales: {over_real} ({over_real/n_ou:.1%})  |  Under reales: {under_real} ({under_real/n_ou:.1%})")
    print(f"  Modelo avg prob OVER:  {sum_po/n_ou:.1%}  |  avg prob UNDER: {sum_pu/n_ou:.1%}")
    print(f"  Hit rate favorito O/U: {model_fav_ok/n_ou:.1%}")

# ============================================================
# 6. DIVERGENCIA MODELO-MERCADO vs ACIERTO REAL
# ============================================================
print("\n" + "=" * 65)
print("6. DIVERGENCIA MODELO-MERCADO vs ACIERTO REAL")
print("=" * 65)

div_buckets = {
    'negativa (<0)': [],
    '0-10%':         [],
    '10-20%':        [],
    '20-35%':        [],
    '>35%':          [],
}

for r in rows:
    id_p, pais, local, visita, p1, px, p2, po, pu, c1, cx, c2, co, cu, gl, gv, ap1, apou, stk1, stkou, incert, estado = r
    if not (p1 and px and p2 and c1 and cx and c2 and c1 > 1 and cx > 1 and c2 > 1):
        continue
    for prob, cuota, outcome in [(p1, c1, gl > gv), (px, cx, gl == gv), (p2, c2, gl < gv)]:
        div = prob - (1.0 / cuota)
        hit = int(outcome)
        if   div < 0:    div_buckets['negativa (<0)'].append(hit)
        elif div < 0.10: div_buckets['0-10%'].append(hit)
        elif div < 0.20: div_buckets['10-20%'].append(hit)
        elif div < 0.35: div_buckets['20-35%'].append(hit)
        else:            div_buckets['>35%'].append(hit)

print("  div = prob_modelo - prob_implicita_mercado")
for b, hits in div_buckets.items():
    if not hits:
        continue
    rate = sum(hits) / len(hits)
    print(f"  {b:15s}: {len(hits):4d} obs  |  hit real: {rate:.1%}")

# ============================================================
# 7. INCERTIDUMBRE DEL MODELO vs ACIERTO
# ============================================================
print("\n" + "=" * 65)
print("7. INCERTIDUMBRE DEL MODELO vs ACIERTO DEL FAVORITO")
print("=" * 65)

incert_buckets = {
    '<0.10':      [],
    '0.10-0.15':  [],
    '0.15-0.20':  [],
    '>0.20':      [],
}

for r in rows:
    id_p, pais, local, visita, p1, px, p2, po, pu, c1, cx, c2, co, cu, gl, gv, ap1, apou, stk1, stkou, incert, estado = r
    if incert is None or not (p1 and px and p2):
        continue
    fav = max([('L', p1, gl > gv), ('X', px, gl == gv), ('V', p2, gl < gv)], key=lambda x: x[1])
    hit = int(fav[2])
    if   incert < 0.10: incert_buckets['<0.10'].append(hit)
    elif incert < 0.15: incert_buckets['0.10-0.15'].append(hit)
    elif incert < 0.20: incert_buckets['0.15-0.20'].append(hit)
    else:               incert_buckets['>0.20'].append(hit)

for b, hits in incert_buckets.items():
    if not hits:
        continue
    rate = sum(hits) / len(hits)
    print(f"  incert {b:12s}: {len(hits):3d} obs  |  hit fav: {rate:.1%}")

# ============================================================
# 8. APUESTAS ACTIVAS POR RANGO DE PROBABILIDAD
# ============================================================
print("\n" + "=" * 65)
print("8. APUESTAS [APOSTAR]: rendimiento real por rango de prob")
print("=" * 65)

conn3 = sqlite3.connect('fondo_quant.db')
c3 = conn3.cursor()
c3.execute("""
    SELECT apuesta_1x2, stake_1x2, cuota_1, cuota_x, cuota_2,
           goles_l, goles_v, pais, prob_1, prob_x, prob_2
    FROM partidos_backtest
    WHERE goles_l IS NOT NULL AND apuesta_1x2 LIKE '%APOSTAR%'
    AND stake_1x2 > 0
""")
ap_rows = c3.fetchall()
conn3.close()

ranges = {
    '33-40%': {'n': 0, 'g': 0, 'pl': 0.0, 'vol': 0.0},
    '40-50%': {'n': 0, 'g': 0, 'pl': 0.0, 'vol': 0.0},
    '50-65%': {'n': 0, 'g': 0, 'pl': 0.0, 'vol': 0.0},
    '>65%':   {'n': 0, 'g': 0, 'pl': 0.0, 'vol': 0.0},
}
n_tot, g_tot, pl_tot, vol_tot = 0, 0, 0.0, 0.0

for ap, stk, c1v, cxv, c2v, gl, gv, pais, p1, px, p2 in ap_rows:
    if 'LOCAL' in ap:    cuota_ap = c1v; gano = gl > gv; prob_ap = p1
    elif 'EMPATE' in ap: cuota_ap = cxv; gano = gl == gv; prob_ap = px
    else:                cuota_ap = c2v; gano = gl < gv; prob_ap = p2
    n_tot += 1; vol_tot += stk
    if gano: g_tot += 1; pl_tot += stk * (cuota_ap - 1)
    else:    pl_tot -= stk
    if prob_ap:
        if   prob_ap < 0.40: pb = '33-40%'
        elif prob_ap < 0.50: pb = '40-50%'
        elif prob_ap < 0.65: pb = '50-65%'
        else:                pb = '>65%'
        ranges[pb]['n'] += 1; ranges[pb]['vol'] += stk
        if gano: ranges[pb]['g'] += 1; ranges[pb]['pl'] += stk * (cuota_ap - 1)
        else:    ranges[pb]['pl'] -= stk

if n_tot:
    print(f"  TOTAL: {n_tot} apuestas  |  hit={g_tot/n_tot:.1%}  yield={pl_tot/vol_tot:.1%}")
    for pb, s in ranges.items():
        if s['n']:
            yld = s['pl'] / s['vol'] if s['vol'] else 0
            print(f"  {pb:8s}: {s['n']:2d} bets  hit={s['g']/s['n']:.1%}  yield={yld:.1%}")

# ============================================================
# 9. PATRON: FAVORITO MERCADO vs FAVORITO MODELO (desacuerdo)
# ============================================================
print("\n" + "=" * 65)
print("9. DESACUERDO MODELO-MERCADO sobre el favorito")
print("=" * 65)

acuerdo_hits, desacuerdo_hits = [], []
desacuerdo_casos = []

for r in rows:
    id_p, pais, local, visita, p1, px, p2, po, pu, c1, cx, c2, co, cu, gl, gv, ap1, apou, stk1, stkou, incert, estado = r
    if not (p1 and px and p2 and c1 and cx and c2 and c1 > 1 and cx > 1 and c2 > 1):
        continue
    fav_modelo = max([('L', p1, gl > gv), ('X', px, gl == gv), ('V', p2, gl < gv)], key=lambda x: x[1])
    fav_mercado = min([('L', c1, gl > gv), ('X', cx, gl == gv), ('V', c2, gl < gv)], key=lambda x: x[1])
    hit = int(fav_modelo[2])
    if fav_modelo[0] == fav_mercado[0]:
        acuerdo_hits.append(hit)
    else:
        desacuerdo_hits.append(hit)
        desacuerdo_casos.append((local, visita, pais, fav_modelo[0], fav_mercado[0], hit))

print(f"  Modelo y mercado de ACUERDO:    {len(acuerdo_hits):3d} partidos  |  hit fav: {sum(acuerdo_hits)/len(acuerdo_hits):.1%}" if acuerdo_hits else "")
print(f"  Modelo y mercado en DESACUERDO: {len(desacuerdo_hits):3d} partidos  |  hit fav modelo: {sum(desacuerdo_hits)/len(desacuerdo_hits):.1%}" if desacuerdo_hits else "")
if desacuerdo_casos:
    print(f"\n  Casos de desacuerdo:")
    for local, visita, pais, fm, fmk, hit in desacuerdo_casos[:20]:
        print(f"    {local:20s} vs {visita:20s} ({pais})  modelo={fm}  mercado={fmk}  {'OK' if hit else 'FALLO'}")

# ============================================================
# 10. GOLES TOTALES PROMEDIO POR LIGA
# ============================================================
print("\n" + "=" * 65)
print("10. GOLES PROMEDIO POR LIGA (para calibrar O/U)")
print("=" * 65)

goles_liga = {}
for r in rows:
    id_p, pais, local, visita, p1, px, p2, po, pu, c1, cx, c2, co, cu, gl, gv, ap1, apou, stk1, stkou, incert, estado = r
    if pais not in goles_liga:
        goles_liga[pais] = {'goles': [], 'over25': 0, 'n': 0}
    goles_liga[pais]['goles'].append(gl + gv)
    goles_liga[pais]['n'] += 1
    if (gl + gv) > 2:
        goles_liga[pais]['over25'] += 1

for pais, v in sorted(goles_liga.items(), key=lambda x: -x[1]['n']):
    n = v['n']
    avg_g = sum(v['goles']) / n
    over_pct = v['over25'] / n
    print(f"  {pais:12s}: n={n:3d}  avg_goles={avg_g:.2f}  over25%={over_pct:.1%}")
