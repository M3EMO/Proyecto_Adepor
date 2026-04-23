"""
Diagnostico 4: donde vive el bias del bucket 50-60% P1?
Cual liga contribuye mas?
Y - alternativa al T-scaling: Platt-style por banda (piecewise).
"""
import sqlite3, math
from collections import defaultdict

DB = 'C:/Users/map12/Desktop/Proyecto_Adepor/fondo_quant.db'
conn = sqlite3.connect(DB)
c = conn.cursor()

c.execute("""
    SELECT pais, prob_1, prob_x, prob_2, goles_l, goles_v
    FROM partidos_backtest
    WHERE estado='Liquidado' AND prob_1 > 0 AND goles_l IS NOT NULL
""")
rows = c.fetchall()

def bs_row(p1,px,p2,gl,gv):
    y1,yx,y2 = (1.0 if gl>gv else 0.0),(1.0 if gl==gv else 0.0),(1.0 if gl<gv else 0.0)
    return (p1-y1)**2 + (px-yx)**2 + (p2-y2)**2

# Bucket 50-60 P1 por liga
print("--- Bucket P1 [0.50, 0.60) por liga ---")
bl = defaultdict(lambda: {'n':0, 'wins_l':0, 'pred':0.0})
for r in rows:
    pais, p1, px, p2, gl, gv = r
    if 0.50 <= p1 < 0.60:
        bl[pais]['n'] += 1
        bl[pais]['wins_l'] += (1 if gl>gv else 0)
        bl[pais]['pred'] += p1
for liga, d in sorted(bl.items(), key=lambda x: -x[1]['n']):
    if d['n']==0: continue
    print(f"  {liga:<14}  N={d['n']:>3}  freq_local={d['wins_l']/d['n']:.3f}  p1_avg={d['pred']/d['n']:.3f}")

# Bucket P2 40-50 por liga
print("\n--- Bucket P2 [0.40, 0.50) por liga (sobreestimamos visita) ---")
bl = defaultdict(lambda: {'n':0, 'wins_v':0, 'pred':0.0})
for r in rows:
    pais, p1, px, p2, gl, gv = r
    if 0.40 <= p2 < 0.50:
        bl[pais]['n'] += 1
        bl[pais]['wins_v'] += (1 if gv>gl else 0)
        bl[pais]['pred'] += p2
for liga, d in sorted(bl.items(), key=lambda x: -x[1]['n']):
    if d['n']==0: continue
    print(f"  {liga:<14}  N={d['n']:>3}  freq_visita={d['wins_v']/d['n']:.3f}  p2_avg={d['pred']/d['n']:.3f}")

# Piecewise calibration: mapeo lineal por bucket
# Construye mapeo P1 -> freq_real usando TRAIN y aplica en TEST
print("\n--- Piecewise calibration (bucket 5pp) holdout ---")
from datetime import datetime
c.execute("""
    SELECT fecha, pais, prob_1, prob_x, prob_2, goles_l, goles_v
    FROM partidos_backtest
    WHERE estado='Liquidado' AND prob_1 > 0 AND goles_l IS NOT NULL
    ORDER BY fecha
""")
rows2 = c.fetchall()
rows2 = [(datetime.strptime(r[0][:10], '%Y-%m-%d'), r[1:]) for r in rows2]
rows2.sort(key=lambda x: x[0])
mid = len(rows2)//2
train = [r for _,r in rows2[:mid]]
test  = [r for _,r in rows2[mid:]]

# Mapeo P1: bucket -> freq (train)
def build_map(train_rows, idx_p, idx_y):
    # idx_p: index de la prob; idx_y: funcion que devuelve 0/1
    m = {}
    for lo in [i/20 for i in range(20)]:
        hi = lo + 0.05
        items = [(r[idx_p], idx_y(r)) for r in train_rows if lo<=r[idx_p]<hi]
        if len(items) >= 5:
            freq = sum(x[1] for x in items)/len(items)
            m[(lo,hi)] = freq
    return m

y1 = lambda r: 1.0 if r[4]>r[5] else 0.0
yx = lambda r: 1.0 if r[4]==r[5] else 0.0
y2 = lambda r: 1.0 if r[5]>r[4] else 0.0

m1 = build_map(train, 1, y1)
mx = build_map(train, 2, yx)
m2 = build_map(train, 3, y2)

print("Map P1 (train):")
for k,v in sorted(m1.items()):
    print(f"  {k[0]:.2f}-{k[1]:.2f} -> {v:.3f}")

def apply_map(p, m):
    for (lo,hi), v in m.items():
        if lo<=p<hi: return v
    return p

# BS test
bs_test_raw = sum(bs_row(r[1],r[2],r[3],r[4],r[5]) for r in test)/len(test)
bs_test_cal = 0.0
for r in test:
    p1,px,p2 = r[1],r[2],r[3]
    q1 = apply_map(p1, m1)
    qx = apply_map(px, mx)
    q2 = apply_map(p2, m2)
    # renormalizar
    s = q1+qx+q2
    if s>0: q1,qx,q2 = q1/s, qx/s, q2/s
    bs_test_cal += bs_row(q1,qx,q2,r[4],r[5])
bs_test_cal /= len(test)
print(f"\nTest set N={len(test)}")
print(f"  BS crudo     = {bs_test_raw:.4f}")
print(f"  BS piecewise = {bs_test_cal:.4f}")
print(f"  gain         = {bs_test_raw - bs_test_cal:+.4f}")

# Beta scaling: p' = a*p + b (lineal, 2 parametros)
print("\n--- Beta-scaling lineal (p' = a*p + b) por salida ---")
def fit_beta_grid(train_rows, idx_p, fy):
    best = (1.0, 0.0, float('inf'))
    for a10 in range(50, 151):
        a = a10/100
        for b100 in range(-20, 21):
            b = b100/100
            bs = 0.0
            for r in train_rows:
                p = max(0, min(1, a*r[idx_p] + b))
                y = fy(r)
                bs += (p-y)**2
            bs /= len(train_rows)
            if bs < best[2]:
                best = (a, b, bs)
    return best

a1,b1,bs1 = fit_beta_grid(train, 1, y1)
ax,bx,bsx = fit_beta_grid(train, 2, yx)
a2,b2,bs2 = fit_beta_grid(train, 3, y2)
print(f"  P1: a={a1:.2f} b={b1:+.2f}  (train BS_p1={bs1:.4f})")
print(f"  PX: a={ax:.2f} b={bx:+.2f}  (train BS_px={bsx:.4f})")
print(f"  P2: a={a2:.2f} b={b2:+.2f}  (train BS_p2={bs2:.4f})")

bs_cal_test = 0.0
for r in test:
    p1_new = max(0, min(1, a1*r[1]+b1))
    px_new = max(0, min(1, ax*r[2]+bx))
    p2_new = max(0, min(1, a2*r[3]+b2))
    s = p1_new+px_new+p2_new
    if s>0: p1_new,px_new,p2_new = p1_new/s, px_new/s, p2_new/s
    bs_cal_test += bs_row(p1_new,px_new,p2_new,r[4],r[5])
bs_cal_test /= len(test)
print(f"\nTest N={len(test)}")
print(f"  BS raw        = {bs_test_raw:.4f}")
print(f"  BS beta-scale = {bs_cal_test:.4f}")
print(f"  gain          = {bs_test_raw - bs_cal_test:+.4f}")

conn.close()
