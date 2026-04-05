"""
Audita cada filtro activo y simula el hit rate de lo que está bloqueando.
El objetivo es encontrar filtros demasiado restrictivos sin evidencia.
"""
import sqlite3, math

UMBRAL_EV_BASE = 0.03
TECHO_CUOTA_1X2 = 5.0
DIVERGENCIA_MAX_1X2 = 0.15
MARGEN_PREDICTIVO_1X2 = 0.05
FLOOR_PROB_MIN = 0.33
DESACUERDO_PROB_MIN = 0.40
DIVERGENCIA_DESACUERDO_MAX = 0.30
TECHO_CUOTA_ALTA_CONV = 8.0
CONVICCION_EV_MIN = 1.0
MARGEN_XG_OU = 0.4
DIVERGENCIA_MAX_OU = 0.05
MARGEN_PREDICTIVO_OU = 0.05

def min_ev_escalado(prob):
    if prob >= 0.50: return 0.03
    if prob >= 0.40: return 0.08
    if prob >= 0.33: return 0.12
    return 999.0

conn = sqlite3.connect('fondo_quant.db')
c = conn.cursor()
c.execute("""
    SELECT id_partido, pais, local, visita,
           prob_1, prob_x, prob_2, prob_o25, prob_u25,
           cuota_1, cuota_x, cuota_2, cuota_o25, cuota_u25,
           goles_l, goles_v, apuesta_1x2, apuesta_ou,
           xg_local, xg_visita
    FROM partidos_backtest
    WHERE goles_l IS NOT NULL AND prob_1 IS NOT NULL AND cuota_1 > 1
    ORDER BY id_partido ASC
""")
rows = c.fetchall()
conn.close()

print(f"Partidos liquidados: {len(rows)}\n")

# ============================================================
# Clasificar cada partido por el motivo real de bloqueo 1X2
# ============================================================

motivos = {
    'APOSTAR':            {'n': 0, 'hits': 0, 'evs': []},
    'Floor Prob (<33%)':  {'n': 0, 'hits': 0, 'evs': []},
    'EV Insuf Escalado':  {'n': 0, 'hits': 0, 'evs': []},
    'Margen Predictivo':  {'n': 0, 'hits': 0, 'evs': []},
    'Techo Cuota':        {'n': 0, 'hits': 0, 'evs': []},
    'Info Oculta (div)':  {'n': 0, 'hits': 0, 'evs': []},
    'Riesgo/Beneficio':   {'n': 0, 'hits': 0, 'evs': []},
    'Sin Valor':          {'n': 0, 'hits': 0, 'evs': []},
    'Sin Cuotas':         {'n': 0, 'hits': 0, 'evs': []},
    'Cubierto C2B/C3':    {'n': 0, 'hits': 0, 'evs': []},
}

for r in rows:
    id_p, pais, local, visita, p1, px, p2, po, pu, c1, cx, c2, co, cu, gl, gv, ap1, apou, xgl, xgv = r
    if not all([p1, px, p2, c1, cx, c2]) or not all(v > 1 for v in [c1, cx, c2]):
        motivos['Sin Cuotas']['n'] += 1
        continue

    # Excluir EMPATE como candidato (igual que V4.3)
    probs  = {'LOCAL': p1, 'VISITA': p2}
    cuotas = {'LOCAL': c1, 'VISITA': c2}

    probs_all = [p1, px, p2]
    probs_ord = sorted(probs_all)
    margen_pred_ok = (probs_ord[2] - probs_ord[1]) >= MARGEN_PREDICTIVO_1X2

    fav_key  = max(probs, key=probs.get)
    p_fav    = probs[fav_key]
    c_fav    = cuotas[fav_key]
    ev_fav   = (p_fav * c_fav) - 1
    div_fav  = p_fav - (1.0 / c_fav)
    umb_fav  = UMBRAL_EV_BASE * (0.5 / p_fav) if p_fav > 0 else 999

    fav_mkt  = min(cuotas, key=cuotas.get)
    desacuer = fav_key != fav_mkt

    outcome  = {'LOCAL': gl > gv, 'VISITA': gl < gv}[fav_key]

    # Determinar motivo real de bloqueo (en orden de prioridad de los caminos)
    if not margen_pred_ok:
        motivo = 'Margen Predictivo'
    elif p_fav < FLOOR_PROB_MIN:
        motivo = 'Floor Prob (<33%)'
    elif c_fav <= TECHO_CUOTA_1X2 and ev_fav >= umb_fav and div_fav <= DIVERGENCIA_MAX_1X2:
        motivo = 'APOSTAR'  # Camino 1
    elif desacuer and p_fav >= DESACUERDO_PROB_MIN and DIVERGENCIA_MAX_1X2 < div_fav <= DIVERGENCIA_DESACUERDO_MAX and ev_fav >= min_ev_escalado(p_fav) and c_fav <= TECHO_CUOTA_ALTA_CONV:
        motivo = 'APOSTAR'  # Camino 2B
    elif p_fav >= FLOOR_PROB_MIN and ev_fav >= CONVICCION_EV_MIN and c_fav <= TECHO_CUOTA_ALTA_CONV:
        motivo = 'APOSTAR'  # Camino 3
    elif ev_fav < min_ev_escalado(p_fav):
        motivo = 'EV Insuf Escalado'
    elif c_fav > TECHO_CUOTA_ALTA_CONV:
        motivo = 'Techo Cuota'
    elif div_fav > DIVERGENCIA_DESACUERDO_MAX:
        motivo = 'Info Oculta (div)'
    else:
        motivo = 'Sin Valor'

    motivos[motivo]['n'] += 1
    motivos[motivo]['hits'] += int(outcome)
    motivos[motivo]['evs'].append(ev_fav)

print("=" * 70)
print("1. MOTIVOS DE BLOQUEO 1X2 y hit rate real del favorito del modelo")
print("=" * 70)
print(f"  {'Motivo':<25} {'N':>4}  {'Hit Real':>9}  {'EV avg':>8}  {'Accion'}")
print(f"  {'-'*65}")
for motivo, v in sorted(motivos.items(), key=lambda x: -x[1]['n']):
    n = v['n']
    if n == 0: continue
    hit = v['hits'] / n
    avg_ev = sum(v['evs']) / len(v['evs']) if v['evs'] else 0
    # Señal de alerta: hit alto pero bloqueado
    alerta = ''
    if motivo != 'APOSTAR' and hit >= 0.55: alerta = '  <<< HIT ALTO'
    if motivo != 'APOSTAR' and hit >= 0.65: alerta = '  <<< OPORTUNIDAD'
    print(f"  {motivo:<25} {n:>4}  {hit:>9.1%}  {avg_ev:>8.3f}{alerta}")

# ============================================================
# 2. EV Insuf Escalado: desglose por rango de prob
# ============================================================
print("\n" + "=" * 70)
print("2. EV INSUF ESCALADO: desglose por rango de prob y umbral requerido")
print("=" * 70)

ev_insuf = []
for r in rows:
    id_p, pais, local, visita, p1, px, p2, po, pu, c1, cx, c2, co, cu, gl, gv, ap1, apou, xgl, xgv = r
    if not all([p1, px, p2, c1, cx, c2]) or not all(v > 1 for v in [c1, cx, c2]): continue
    probs  = {'LOCAL': p1, 'VISITA': p2}
    cuotas = {'LOCAL': c1, 'VISITA': c2}
    probs_all = sorted([p1, px, p2])
    if (probs_all[2] - probs_all[1]) < MARGEN_PREDICTIVO_1X2: continue
    fav_key = max(probs, key=probs.get)
    p_fav = probs[fav_key]; c_fav = cuotas[fav_key]
    ev_fav = (p_fav * c_fav) - 1
    div_fav = p_fav - (1.0 / c_fav)
    fav_mkt = min(cuotas, key=cuotas.get)
    desacuer = fav_key != fav_mkt

    if p_fav < FLOOR_PROB_MIN: continue
    if c_fav <= TECHO_CUOTA_1X2 and ev_fav >= (UMBRAL_EV_BASE*(0.5/p_fav)) and div_fav <= DIVERGENCIA_MAX_1X2: continue
    if desacuer and p_fav >= DESACUERDO_PROB_MIN and DIVERGENCIA_MAX_1X2 < div_fav <= DIVERGENCIA_DESACUERDO_MAX and ev_fav >= min_ev_escalado(p_fav) and c_fav <= TECHO_CUOTA_ALTA_CONV: continue
    if p_fav >= FLOOR_PROB_MIN and ev_fav >= CONVICCION_EV_MIN and c_fav <= TECHO_CUOTA_ALTA_CONV: continue

    ev_min = min_ev_escalado(p_fav)
    if ev_fav < ev_min:
        outcome = {'LOCAL': gl > gv, 'VISITA': gl < gv}[fav_key]
        ev_insuf.append({'pais': pais, 'prob': p_fav, 'cuota': c_fav, 'ev': ev_fav,
                         'ev_min': ev_min, 'div': div_fav, 'hit': outcome, 'desacuer': desacuer})

rangos_ev = {'33-40%': [], '40-50%': [], '50-65%': []}
for caso in ev_insuf:
    p = caso['prob']
    rk = '33-40%' if p < 0.40 else ('40-50%' if p < 0.50 else '50-65%')
    rangos_ev[rk].append(caso)

for rk, casos in rangos_ev.items():
    if not casos: continue
    hits = sum(1 for c in casos if c['hit'])
    avg_ev = sum(c['ev'] for c in casos) / len(casos)
    avg_ev_min = sum(c['ev_min'] for c in casos) / len(casos)
    avg_c = sum(c['cuota'] for c in casos) / len(casos)
    print(f"  prob {rk}: n={len(casos)}  hit={hits/len(casos):.1%}  avg_EV={avg_ev:.3f}  umbral_req={avg_ev_min:.3f}  cuota={avg_c:.2f}")

# ============================================================
# 3. Margen predictivo: ¿qué se bloquea?
# ============================================================
print("\n" + "=" * 70)
print("3. MARGEN PREDICTIVO: hit rate de lo que bloquea")
print("=" * 70)

margen_casos = []
for r in rows:
    id_p, pais, local, visita, p1, px, p2, po, pu, c1, cx, c2, co, cu, gl, gv, ap1, apou, xgl, xgv = r
    if not all([p1, px, p2]): continue
    probs_all = sorted([p1, px, p2])
    margen = probs_all[2] - probs_all[1]
    if margen >= MARGEN_PREDICTIVO_1X2: continue
    # Si no hubiera filtro, el modelo apostaría al favorito
    probs = {'LOCAL': p1, 'VISITA': p2}
    cuotas = {'LOCAL': c1, 'VISITA': c2} if c1 and c2 and c1>1 and c2>1 else None
    if not cuotas: continue
    fav_key = max(probs, key=probs.get)
    p_fav = probs[fav_key]; c_fav = cuotas[fav_key]
    ev = (p_fav * c_fav) - 1
    outcome = {'LOCAL': gl > gv, 'VISITA': gl < gv}[fav_key]
    margen_casos.append({'margen': margen, 'prob': p_fav, 'ev': ev, 'hit': outcome, 'pais': pais})

if margen_casos:
    hits = sum(1 for c in margen_casos if c['hit'])
    avg_margen = sum(c['margen'] for c in margen_casos) / len(margen_casos)
    avg_prob = sum(c['prob'] for c in margen_casos) / len(margen_casos)
    print(f"  Bloqueados por margen pred: {len(margen_casos)}  hit={hits/len(margen_casos):.1%}  avg_margen={avg_margen:.3f}  avg_prob={avg_prob:.1%}")
    # Por sub-rangos de margen
    for umbral in [0.01, 0.02, 0.03, 0.04, 0.05]:
        sub = [c for c in margen_casos if c['margen'] >= umbral]
        if sub:
            h = sum(1 for c in sub if c['hit'])
            print(f"    margen >= {umbral:.2f}: n={len(sub)}  hit={h/len(sub):.1%}")

# ============================================================
# 4. O/U: qué bloquea el filtro xG y el de divergencia
# ============================================================
print("\n" + "=" * 70)
print("4. O/U: filtros activos y hit rate de lo que bloquean")
print("=" * 70)

ou_motivos = {'APOSTAR': [], 'xG Margen': [], 'Margen Pred': [], 'Div Alta': [], 'Sin Valor': []}

for r in rows:
    id_p, pais, local, visita, p1, px, p2, po, pu, c1, cx, c2, co, cu, gl, gv, ap1, apou, xgl, xgv = r
    if not (po and pu and co and cu and co > 1 and cu > 1): continue
    es_over = (gl + gv) > 2
    fav_ou = 'OVER' if po > pu else 'UNDER'
    hit = (fav_ou == 'OVER' and es_over) or (fav_ou == 'UNDER' and not es_over)
    p_fav = max(po, pu); c_fav = co if po > pu else cu
    ev = (p_fav * c_fav) - 1
    div = p_fav - (1.0 / c_fav)
    xg_total = (xgl + xgv) if (xgl and xgv) else None

    if xg_total and abs(xg_total - 2.5) < MARGEN_XG_OU:
        ou_motivos['xG Margen'].append({'hit': hit, 'xgt': xg_total, 'ev': ev, 'pais': pais})
    elif abs(po - pu) < MARGEN_PREDICTIVO_OU:
        ou_motivos['Margen Pred'].append({'hit': hit, 'ev': ev, 'pais': pais})
    elif ev > (UMBRAL_EV_BASE * (0.5 / p_fav)) and c_fav <= 6.0 and div <= DIVERGENCIA_MAX_OU:
        ou_motivos['APOSTAR'].append({'hit': hit, 'ev': ev, 'pais': pais})
    elif div > DIVERGENCIA_MAX_OU:
        ou_motivos['Div Alta'].append({'hit': hit, 'div': div, 'ev': ev, 'pais': pais})
    else:
        ou_motivos['Sin Valor'].append({'hit': hit, 'ev': ev, 'pais': pais})

for motivo, casos in ou_motivos.items():
    if not casos: continue
    hits = sum(1 for c in casos if c['hit'])
    avg_ev = sum(c['ev'] for c in casos) / len(casos)
    alerta = '  <<< OPORTUNIDAD' if motivo != 'APOSTAR' and hits/len(casos) >= 0.60 else ''
    print(f"  {motivo:<15}: n={len(casos):3d}  hit={hits/len(casos):.1%}  avg_EV={avg_ev:.3f}{alerta}")

# Desglose del filtro xG por delta
xg_casos = ou_motivos['xG Margen']
if xg_casos:
    print(f"\n  Desglose xG Margen por delta al umbral 2.5:")
    for delta_min, delta_max in [(0.0, 0.1), (0.1, 0.2), (0.2, 0.3), (0.3, 0.4)]:
        sub = [c for c in xg_casos if 'xgt' in c and delta_min <= abs(c['xgt'] - 2.5) < delta_max]
        if sub:
            h = sum(1 for c in sub if c['hit'])
            print(f"    delta {delta_min:.1f}-{delta_max:.1f}: n={len(sub)}  hit={h/len(sub):.1%}")

# ============================================================
# 5. RESUMEN: cuantas apuestas adicionales habilitaria cada cambio
# ============================================================
print("\n" + "=" * 70)
print("5. RESUMEN: apuestas adicionales posibles y costo/beneficio")
print("=" * 70)

opciones = []

# EV escalado 40-50%: umbral 8% -> probar con 5%
sub = [c for c in ev_insuf if 0.40 <= c['prob'] < 0.50 and c['ev'] >= 0.05]
if sub:
    h = sum(1 for c in sub if c['hit'])
    opciones.append(('Bajar EV min 40-50% a 5%', len(sub), h/len(sub), 'Riesgo bajo'))

# EV escalado 33-40%: umbral 12% -> probar con 8%
sub2 = [c for c in ev_insuf if 0.33 <= c['prob'] < 0.40 and c['ev'] >= 0.08]
if sub2:
    h2 = sum(1 for c in sub2 if c['hit'])
    opciones.append(('Bajar EV min 33-40% a 8%', len(sub2), h2/len(sub2), 'Riesgo medio'))

# Margen predictivo: bajar de 5% a 2%
sub3 = [c for c in margen_casos if c['margen'] >= 0.02]
if sub3:
    h3 = sum(1 for c in sub3 if c['hit'])
    opciones.append(('Bajar margen pred a 2%', len(sub3), h3/len(sub3), 'Riesgo bajo'))

# xG OU: bajar margen de 0.4 a 0.25
sub4 = [c for c in ou_motivos['xG Margen'] if 'xgt' in c and abs(c['xgt'] - 2.5) >= 0.25]
if sub4:
    h4 = sum(1 for c in sub4 if c['hit'])
    opciones.append(('Bajar xG margen O/U a 0.25', len(sub4), h4/len(sub4), 'Riesgo bajo'))

# Div O/U alta: relajar a 0.10
sub5 = [c for c in ou_motivos['Div Alta'] if c.get('div', 999) <= 0.10]
if sub5:
    h5 = sum(1 for c in sub5 if c['hit'])
    opciones.append(('Relajar div O/U a 0.10', len(sub5), h5/len(sub5), 'Riesgo medio'))

print(f"  {'Opcion':<35} {'Bets+':>6}  {'Hit':>7}  {'Riesgo'}")
print(f"  {'-'*65}")
for nombre, n, hit, riesgo in sorted(opciones, key=lambda x: -x[2]):
    alerta = ' ***' if hit >= 0.60 else ''
    print(f"  {nombre:<35} {n:>6}  {hit:>7.1%}  {riesgo}{alerta}")
