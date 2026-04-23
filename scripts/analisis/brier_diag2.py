"""
Diagnostico 2: extender grid temperatura, descomponer calibracion vs refinamiento,
y testear si bias viene de gamma_1x2.
"""
import sqlite3, math
from collections import defaultdict
from datetime import datetime, timedelta

DB = 'C:/Users/map12/Desktop/Proyecto_Adepor/fondo_quant.db'
conn = sqlite3.connect(DB)
c = conn.cursor()

c.execute("""
    SELECT id_partido, fecha, pais, prob_1, prob_x, prob_2,
           cuota_1, cuota_x, cuota_2,
           goles_l, goles_v, xg_local, xg_visita,
           apuesta_1x2, stake_1x2
    FROM partidos_backtest
    WHERE estado='Liquidado' AND prob_1 > 0 AND goles_l IS NOT NULL
    ORDER BY fecha
""")
rows = c.fetchall()

def bs_row(p1,px,p2,gl,gv):
    y1,yx,y2 = (1.0 if gl>gv else 0.0),(1.0 if gl==gv else 0.0),(1.0 if gl<gv else 0.0)
    return (p1-y1)**2 + (px-yx)**2 + (p2-y2)**2

def temp_scale(p1, px, p2, T):
    p1,px,p2 = max(p1,1e-6),max(px,1e-6),max(p2,1e-6)
    l1,lx,l2 = math.log(p1)/T, math.log(px)/T, math.log(p2)/T
    m = max(l1,lx,l2)
    e1,ex,e2 = math.exp(l1-m),math.exp(lx-m),math.exp(l2-m)
    s = e1+ex+e2
    return e1/s, ex/s, e2/s

# --- Grid extendida (T<0.7 y fino) ---
print("--- Temperature grid extendida ---")
best_T, best_bs = 1.0, float('inf')
for T100 in range(30, 160):
    T = T100/100
    bs = sum(bs_row(*temp_scale(r[3],r[4],r[5],T), r[9], r[10]) for r in rows)/len(rows)
    if bs < best_bs:
        best_bs, best_T = bs, T
print(f"[GLOBAL] T* (minimo global) = {best_T:.2f}  BS={best_bs:.4f}  (T=1.0 daba {sum(bs_row(r[3],r[4],r[5],r[9],r[10]) for r in rows)/len(rows):.4f})")

# Muestreo de grid
print("Puntos del grid:")
for T100 in [40, 50, 60, 65, 70, 75, 80, 85, 90, 95, 100, 110, 120]:
    T = T100/100
    bs = sum(bs_row(*temp_scale(r[3],r[4],r[5],T), r[9], r[10]) for r in rows)/len(rows)
    print(f"  T={T:.2f}  BS={bs:.4f}")

# Misma busqueda sobre rolling-14d
rows_dt = [(datetime.strptime(r[1][:10], '%Y-%m-%d'), r) for r in rows if r[1]]
rows_dt.sort(key=lambda x: x[0])
max_dt = rows_dt[-1][0]
cutoff = max_dt - timedelta(days=14)
rec = [r for dt,r in rows_dt if dt >= cutoff]
print(f"\n--- Rolling-14d grid (N={len(rec)}) ---")
best_T, best_bs = 1.0, float('inf')
for T100 in range(30, 160):
    T = T100/100
    bs = sum(bs_row(*temp_scale(r[3],r[4],r[5],T), r[9], r[10]) for r in rec)/len(rec)
    if bs < best_bs: best_bs, best_T = bs, T
bs_ref = sum(bs_row(r[3],r[4],r[5],r[9],r[10]) for r in rec)/len(rec)
print(f"T*={best_T:.2f}  BS@T*={best_bs:.4f}  BS@T=1={bs_ref:.4f}  gain={bs_ref-best_bs:+.4f}")

# --- Test de holdout temporal: calibrar T en primera mitad, validar en segunda ---
print("\n--- Holdout temporal: T calibrado train -> evalua test ---")
n = len(rows_dt)
mid = n // 2
train = [r for _, r in rows_dt[:mid]]
test = [r for _, r in rows_dt[mid:]]
best_T, best_bs = 1.0, float('inf')
for T100 in range(30, 160):
    T = T100/100
    bs = sum(bs_row(*temp_scale(r[3],r[4],r[5],T), r[9], r[10]) for r in train)/len(train)
    if bs < best_bs: best_bs, best_T = bs, T
bs_test_T1 = sum(bs_row(r[3],r[4],r[5],r[9],r[10]) for r in test)/len(test)
bs_test_Topt = sum(bs_row(*temp_scale(r[3],r[4],r[5],best_T), r[9], r[10]) for r in test)/len(test)
print(f"Train (N={len(train)}): T*={best_T:.2f}  BS@T*={best_bs:.4f}")
print(f"Test  (N={len(test)}): BS@T=1.00={bs_test_T1:.4f}  BS@T*={bs_test_Topt:.4f}  gain={bs_test_T1-bs_test_Topt:+.4f}")

# --- Test sobre picks reales (no sobre toda la base): ¿yield cambia? ---
print("\n--- Impacto sobre picks reales (apuesta_1x2 != pendiente/None) ---")
# Simulamos: si el motor usara T* antes de decidir picks, ¿que picks cambiarian?
# Simplificado: solo medimos BS condicional a los picks actuales.
picks = [r for r in rows if r[13] and r[13] not in ('pendiente','No apostada', None) and r[14] and r[14]>0]
print(f"N picks: {len(picks)}")
if picks:
    bs_picks_T1 = sum(bs_row(r[3],r[4],r[5],r[9],r[10]) for r in picks)/len(picks)
    for T in [0.60, 0.70, 0.80, 0.90, 1.00, 1.10, 1.20]:
        bs_p = sum(bs_row(*temp_scale(r[3],r[4],r[5],T), r[9], r[10]) for r in picks)/len(picks)
        print(f"  T={T:.2f}  BS_picks={bs_p:.4f}")

# Gano/perdido real de los picks: si T* shiftea probs de 0.55 a 0.62, el EV sube
# y el filtro del motor habria mantenido el pick. No cambia el outcome, cambia calibracion.

# --- Brier descompuesto: confiabilidad + resolucion + uncertainty (Murphy 1973) ---
# BS = reliability - resolution + uncertainty
# Mayor reliability = peor. Mayor resolution = mejor.
def murphy_decomp(probs_list, outcomes_list, buckets):
    """
    probs_list: lista de probabilidades
    outcomes_list: lista de 0/1
    buckets: lista de (lo, hi)
    Retorna (reliability, resolution, uncertainty)
    """
    o_bar = sum(outcomes_list)/len(outcomes_list)
    unc = o_bar * (1 - o_bar)
    rel, res = 0.0, 0.0
    n = len(probs_list)
    for lo, hi in buckets:
        idxs = [i for i,p in enumerate(probs_list) if lo<=p<hi]
        if not idxs: continue
        nk = len(idxs)
        pk = sum(probs_list[i] for i in idxs)/nk
        ok = sum(outcomes_list[i] for i in idxs)/nk
        rel += (nk/n) * (pk - ok)**2
        res += (nk/n) * (ok - o_bar)**2
    return rel, res, unc

print("\n--- Murphy decomposition (P1 local) ---")
buckets = [(i/20, (i+1)/20) for i in range(20)]
p1_list = [r[3] for r in rows]
o1_list = [1.0 if r[9]>r[10] else 0.0 for r in rows]
rel, res, unc = murphy_decomp(p1_list, o1_list, buckets)
print(f"BS_P1 = rel - res + unc = {rel:.4f} - {res:.4f} + {unc:.4f} = {rel-res+unc:.4f}")
print(f"  reliability (peor si alto): {rel:.4f}   <- esto es lo que T-scaling ataca")
print(f"  resolution  (mejor si alto): {res:.4f}  <- lo que perderiamos si T->inf")

p2_list = [r[5] for r in rows]
o2_list = [1.0 if r[10]>r[9] else 0.0 for r in rows]
rel, res, unc = murphy_decomp(p2_list, o2_list, buckets)
print(f"\nBS_P2 = rel - res + unc = {rel:.4f} - {res:.4f} + {unc:.4f} = {rel-res+unc:.4f}")

px_list = [r[4] for r in rows]
ox_list = [1.0 if r[9]==r[10] else 0.0 for r in rows]
rel, res, unc = murphy_decomp(px_list, ox_list, buckets)
print(f"\nBS_PX = rel - res + unc = {rel:.4f} - {res:.4f} + {unc:.4f} = {rel-res+unc:.4f}")

conn.close()
