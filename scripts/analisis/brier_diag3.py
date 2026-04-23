"""
Diagnostico 3: ver si T-scaling rompe los picks actuales.
- Cuantos picks existen y como cambian con T<1
- Si el stake de Kelly cambia (EV se amplifica)
- Si picks nuevos aparecen (perdemos disciplina) o se pierden (perdemos volumen)
"""
import sqlite3, math
from collections import defaultdict

DB = 'C:/Users/map12/Desktop/Proyecto_Adepor/fondo_quant.db'
conn = sqlite3.connect(DB)
c = conn.cursor()

# Trae todos Liquidados con columnas de apuesta
c.execute("""
    SELECT id_partido, fecha, pais, prob_1, prob_x, prob_2,
           cuota_1, cuota_x, cuota_2,
           goles_l, goles_v,
           apuesta_1x2, stake_1x2,
           ev_local, ev_empate, ev_visita
    FROM partidos_backtest
    WHERE estado='Liquidado' AND prob_1 > 0 AND goles_l IS NOT NULL
""")
rows = c.fetchall()

def temp_scale(p1, px, p2, T):
    p1,px,p2 = max(p1,1e-6),max(px,1e-6),max(p2,1e-6)
    l1,lx,l2 = math.log(p1)/T, math.log(px)/T, math.log(p2)/T
    m = max(l1,lx,l2)
    e1,ex,e2 = math.exp(l1-m),math.exp(lx-m),math.exp(l2-m)
    s = e1+ex+e2
    return e1/s, ex/s, e2/s

# Cuantos picks hay?
picks = [r for r in rows if r[11] and r[11] not in ('pendiente','No apostada','No Apostada','') and r[12] and r[12]>0]
print(f"Total liquidados: {len(rows)}")
print(f"Picks reales:     {len(picks)}")

# Ver distribucion de apuesta_1x2
apuestas = defaultdict(int)
for r in rows:
    apuestas[str(r[11])] += 1
print(f"\nDistribucion apuesta_1x2:")
for k,v in sorted(apuestas.items(), key=lambda x: -x[1]):
    print(f"  '{k}' -> {v}")

# Si no hay 'picks reales' por nomenclatura, simulemos
# Picks = partidos donde EV>0.03 y prob>0.36 (C4 consenso)
picks_sim = []
for r in rows:
    p1, px, p2 = r[3], r[4], r[5]
    c1, cx, c2 = r[6] or 0, r[7] or 0, r[8] or 0
    if c1>1.12 and c1<=5.0 and p1>=0.36:
        ev = p1*c1 - 1
        if ev >= 0.03:
            picks_sim.append(('LOCAL', r, p1, c1, ev))
    if c2>1.12 and c2<=5.0 and p2>=0.36:
        ev = p2*c2 - 1
        if ev >= 0.03:
            picks_sim.append(('VISITA', r, p2, c2, ev))

print(f"\nPicks simulados (C4-style: cuota>1.12, prob>=0.36, EV>=0.03): {len(picks_sim)}")

def yield_of(picks_sim, T):
    pl = 0.0
    n = 0
    for side, r, p_old, cuota, ev_old in picks_sim:
        p1_new, px_new, p2_new = temp_scale(r[3], r[4], r[5], T)
        p_new = p1_new if side=='LOCAL' else p2_new
        # Con T distinto, el pick podria no cumplir umbrales
        if p_new < 0.36: continue
        ev_new = p_new*cuota - 1
        if ev_new < 0.03: continue
        # Kelly fraccional simplificado (fijo 0.5 unidad)
        gl, gv = r[9], r[10]
        ganaste = (side=='LOCAL' and gl>gv) or (side=='VISITA' and gv>gl)
        pl += (cuota - 1) if ganaste else -1.0
        n += 1
    yield_pct = 100*pl/n if n>0 else 0
    return n, pl, yield_pct

print(f"\n--- Yield simulado bajo T distintos (C4 picks) ---")
for T in [0.44, 0.60, 0.70, 0.80, 0.90, 0.95, 1.00, 1.05, 1.10]:
    n, pl, yp = yield_of(picks_sim, T)
    print(f"  T={T:.2f}  N_picks={n:>3}  PL={pl:+7.2f}u  yield={yp:+6.2f}%")

# Test: C1 style (favorito del modelo, div_max por liga)
# Aqui simplificamos: pick donde prob maxima cumple umbral y div <= 0.15
def pick_c1(r, T):
    p1, px, p2 = temp_scale(r[3], r[4], r[5], T)
    c1, cx, c2 = r[6] or 0, r[7] or 0, r[8] or 0
    # Prob modelo vs implied bookie
    if c1<=1 or cx<=1 or c2<=1: return None
    ip1, ipx, ip2 = 1/c1, 1/cx, 1/c2
    s = ip1+ipx+ip2
    imp1, imp2 = ip1/s, ip2/s
    # Favorito del modelo = mayor prob (excluye empate)
    if p1 > p2:
        div = abs(p1 - imp1)
        if div <= 0.15 and p1 >= 0.40 and c1>1.20:
            return ('LOCAL', p1, c1)
    else:
        div = abs(p2 - imp2)
        if div <= 0.15 and p2 >= 0.40 and c2>1.20:
            return ('VISITA', p2, c2)
    return None

print(f"\n--- Yield simulado C1-style (fav modelo, div<=0.15, prob>=0.40) ---")
for T in [0.44, 0.60, 0.70, 0.80, 0.90, 0.95, 1.00, 1.05, 1.10]:
    n, pl = 0, 0.0
    for r in rows:
        p = pick_c1(r, T)
        if p is None: continue
        side, prob, cuota = p
        gl, gv = r[9], r[10]
        ganaste = (side=='LOCAL' and gl>gv) or (side=='VISITA' and gv>gl)
        pl += (cuota - 1) if ganaste else -1.0
        n += 1
    yp = 100*pl/n if n>0 else 0
    print(f"  T={T:.2f}  N={n:>3}  PL={pl:+7.2f}u  yield={yp:+6.2f}%")

# Final: evaluar si la calibracion esta recomendando volver rho mas cercano a cero
print("\n--- Rho analisis por liga (diff con fallback -0.09) ---")
c.execute("SELECT liga, total_partidos, empates, rho_calculado FROM ligas_stats ORDER BY liga")
for liga, n, emp, rho in c.fetchall():
    freq_emp = emp/n if n>0 else 0
    print(f"  {liga:<14} N={n:>4} empates={emp:>3} freq={freq_emp:.3f}  rho={rho:+.4f}  dist_a_fallback={rho-(-0.09):+.4f}")

conn.close()
