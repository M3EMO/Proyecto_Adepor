import sqlite3

conn = sqlite3.connect('fondo_quant.db')
c = conn.cursor()
c.execute("""
    SELECT id_partido, pais, local, visita,
           prob_1, prob_x, prob_2,
           cuota_1, cuota_x, cuota_2,
           goles_l, goles_v, apuesta_1x2, stake_1x2
    FROM partidos_backtest
    WHERE goles_l IS NOT NULL AND prob_1 IS NOT NULL
      AND cuota_1 IS NOT NULL AND cuota_1 > 1
    ORDER BY id_partido ASC
""")
rows = c.fetchall()
conn.close()

casos = []
for r in rows:
    id_p, pais, local, visita, p1, px, p2, c1, cx, c2, gl, gv, ap, stk = r
    if not all([p1, px, p2, c1, cx, c2]):
        continue
    if not all(v > 1 for v in [c1, cx, c2]):
        continue

    fav_mod = max([('LOCAL', p1, gl > gv), ('EMPATE', px, gl == gv), ('VISITA', p2, gl < gv)], key=lambda x: x[1])
    fav_mkt = min([('LOCAL', c1, gl > gv), ('EMPATE', cx, gl == gv), ('VISITA', c2, gl < gv)], key=lambda x: x[1])

    prob_mod  = {'LOCAL': p1, 'EMPATE': px, 'VISITA': p2}[fav_mod[0]]
    cuota_mod = {'LOCAL': c1, 'EMPATE': cx, 'VISITA': c2}[fav_mod[0]]
    prob_impl = 1.0 / cuota_mod
    div       = prob_mod - prob_impl
    ev        = (prob_mod * cuota_mod) - 1
    desacuerdo = fav_mod[0] != fav_mkt[0]

    casos.append({
        'id': id_p, 'pais': pais, 'local': local, 'visita': visita,
        'fav_mod': fav_mod[0], 'fav_mkt': fav_mkt[0],
        'prob_mod': prob_mod, 'cuota_mod': cuota_mod,
        'prob_impl': prob_impl, 'div': div, 'ev': ev,
        'hit': fav_mod[2], 'gl': gl, 'gv': gv,
        'desacuerdo': desacuerdo,
        'tipo': f"{fav_mkt[0]}->{fav_mod[0]}" if desacuerdo else "ACUERDO",
        'ap': ap, 'stk': stk
    })

desacos = [c for c in casos if c['desacuerdo']]
acuerdos = [c for c in casos if not c['desacuerdo']]

print("=" * 70)
print("A. TIPOS DE DESACUERDO por direccion")
print("=" * 70)
tipos = {}
for caso in casos:
    t = caso['tipo']
    if t not in tipos:
        tipos[t] = {'n': 0, 'hits': 0, 'evs': [], 'divs': [], 'cuotas': []}
    tipos[t]['n'] += 1
    tipos[t]['hits'] += int(caso['hit'])
    tipos[t]['evs'].append(caso['ev'])
    tipos[t]['divs'].append(caso['div'])
    tipos[t]['cuotas'].append(caso['cuota_mod'])

for t, v in sorted(tipos.items(), key=lambda x: -x[1]['n']):
    n = v['n']
    hit = v['hits'] / n
    avg_ev  = sum(v['evs']) / n
    avg_div = sum(v['divs']) / n
    avg_c   = sum(v['cuotas']) / n
    print(f"  {t:22s}: n={n:3d}  hit={hit:.1%}  cuota={avg_c:.2f}  div={avg_div:+.3f}  EV={avg_ev:.3f}")

print("\n" + "=" * 70)
print("B. DESACUERDO: hit por rango de prob del modelo")
print("=" * 70)
rangos = {'33-40%': {'d': [], 'a': []}, '40-50%': {'d': [], 'a': []},
          '50-65%': {'d': [], 'a': []}, '>65%':   {'d': [], 'a': []}}
for caso in casos:
    p = caso['prob_mod']
    rk = '33-40%' if p < 0.40 else ('40-50%' if p < 0.50 else ('50-65%' if p < 0.65 else '>65%'))
    key = 'd' if caso['desacuerdo'] else 'a'
    rangos[rk][key].append(int(caso['hit']))
for rk, v in rangos.items():
    d = v['d']; a = v['a']
    ds = f"hit={sum(d)/len(d):.1%} (n={len(d)})" if d else "n=0"
    ac = f"hit={sum(a)/len(a):.1%} (n={len(a)})" if a else "n=0"
    print(f"  prob {rk:8s}:  DESAC: {ds:22s}  |  ACUER: {ac}")

print("\n" + "=" * 70)
print("C. DESACUERDO: hit por rango de divergencia")
print("=" * 70)
div_rng = {'0-15%': {'d': [], 'a': []}, '15-25%': {'d': [], 'a': []},
           '25-35%': {'d': [], 'a': []}, '>35%':  {'d': [], 'a': []}}
for caso in casos:
    dv = caso['div']
    if dv < 0:    continue
    rk = '0-15%' if dv < 0.15 else ('15-25%' if dv < 0.25 else ('25-35%' if dv < 0.35 else '>35%'))
    key = 'd' if caso['desacuerdo'] else 'a'
    div_rng[rk][key].append(int(caso['hit']))
for rk, v in div_rng.items():
    d = v['d']; a = v['a']
    ds = f"hit={sum(d)/len(d):.1%} (n={len(d)})" if d else "n=0"
    ac = f"hit={sum(a)/len(a):.1%} (n={len(a)})" if a else "n=0"
    print(f"  div {rk:8s}:  DESAC: {ds:22s}  |  ACUER: {ac}")

print("\n" + "=" * 70)
print("D. DESACUERDO por liga")
print("=" * 70)
por_liga = {}
for caso in desacos:
    p = caso['pais']
    if p not in por_liga:
        por_liga[p] = {'n': 0, 'hits': 0, 'cuotas': []}
    por_liga[p]['n'] += 1
    por_liga[p]['hits'] += int(caso['hit'])
    por_liga[p]['cuotas'].append(caso['cuota_mod'])
for pais, v in sorted(por_liga.items(), key=lambda x: -x[1]['n']):
    hit = v['hits'] / v['n']
    avg_c = sum(v['cuotas']) / v['n']
    print(f"  {pais:12s}: n={v['n']:2d}  hit={hit:.1%}  cuota_promedio={avg_c:.2f}")

print("\n" + "=" * 70)
print("E. OPORTUNIDADES PERDIDAS: desacuerdos sin apuesta activa")
print("   Simulacion con DIVERGENCIA_MAX relajada a 0.30")
print("=" * 70)
FLOOR_PROB = 0.33
sin_apuesta = [c for c in desacos
               if not (c['ap'] and '[APOSTAR]' in str(c['ap']))
               and c['prob_mod'] >= FLOOR_PROB]
print(f"  Desacuerdos sin apuesta: {len(sin_apuesta)}")
print()
for ev_min, div_max in [(0.05, 0.30), (0.08, 0.30), (0.05, 0.25), (0.08, 0.25)]:
    liq = [c for c in sin_apuesta if c['div'] <= div_max and c['ev'] >= ev_min]
    if liq:
        g = sum(1 for c in liq if c['hit'])
        pl = sum((c['cuota_mod'] - 1) if c['hit'] else -1 for c in liq)
        print(f"  EV>={ev_min:.0%}  div<={div_max:.0%}: {len(liq):2d} apuestas  hit={g/len(liq):.1%}  P/L={pl:+.2f}u  yield={pl/len(liq):.1%}")

print()
print("  Detalle (EV>=5%, div<=30%):")
liq_det = [c for c in sin_apuesta if c['div'] <= 0.30 and c['ev'] >= 0.05]
for c in liq_det:
    res = f"{c['gl']}-{c['gv']}"
    ok = 'OK' if c['hit'] else 'FALLO'
    print(f"    {c['tipo']:14s}  {c['local']:20s} vs {c['visita']:20s} ({c['pais']:10s})"
          f"  prob={c['prob_mod']:.1%}  c={c['cuota_mod']:.2f}  div={c['div']:.3f}"
          f"  EV={c['ev']:.3f}  {res}  {ok}")

print("\n" + "=" * 70)
print("F. SWEET SPOT: div 15-30%, prob 40-65%, desacuerdo")
print("=" * 70)
sweet = [c for c in desacos if 0.15 <= c['div'] <= 0.35 and 0.40 <= c['prob_mod'] <= 0.65]
if sweet:
    g = sum(1 for c in sweet if c['hit'])
    print(f"  {len(sweet)} casos  hit={g/len(sweet):.1%}")
    for c in sweet:
        res = f"{c['gl']}-{c['gv']}"
        ok = 'OK' if c['hit'] else 'FALLO'
        print(f"    {c['tipo']:14s}  prob={c['prob_mod']:.1%}  c={c['cuota_mod']:.2f}"
              f"  div={c['div']:.3f}  EV={c['ev']:.3f}  {res}  {ok}  ({c['pais']})")
