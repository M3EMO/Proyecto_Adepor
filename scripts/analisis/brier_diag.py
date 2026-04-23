"""
Diagnostico empirico: Brier por liga, gamma coverage, reliability.
No modifica nada — solo lee partidos_backtest.
"""
import sqlite3
import math
from collections import defaultdict

DB = 'C:/Users/map12/Desktop/Proyecto_Adepor/fondo_quant.db'

conn = sqlite3.connect(DB)
c = conn.cursor()

c.execute("""
    SELECT id_partido, fecha, pais, prob_1, prob_x, prob_2,
           cuota_1, cuota_x, cuota_2,
           goles_l, goles_v,
           xg_local, xg_visita
    FROM partidos_backtest
    WHERE estado='Liquidado' AND prob_1 > 0 AND goles_l IS NOT NULL
    ORDER BY fecha
""")
rows = c.fetchall()

def safe_f(x):
    try: return float(x) if x is not None else 0.0
    except Exception: return 0.0

def bs_row(p1, px, p2, gl, gv):
    y1 = 1.0 if gl > gv else 0.0
    yx = 1.0 if gl == gv else 0.0
    y2 = 1.0 if gl < gv else 0.0
    return (p1-y1)**2 + (px-yx)**2 + (p2-y2)**2

def bs_bookie(c1, cx, c2, gl, gv):
    c1, cx, c2 = safe_f(c1), safe_f(cx), safe_f(c2)
    if c1<=1 or cx<=1 or c2<=1:
        return None
    ip1, ipx, ip2 = 1/c1, 1/cx, 1/c2
    s = ip1+ipx+ip2
    if s<=0: return None
    p1, px, p2 = ip1/s, ipx/s, ip2/s
    y1 = 1.0 if gl > gv else 0.0
    yx = 1.0 if gl == gv else 0.0
    y2 = 1.0 if gl < gv else 0.0
    return (p1-y1)**2 + (px-yx)**2 + (p2-y2)**2

# --- Por liga: BS sistema vs BS bookie ---
print(f"[TOTAL] N liquidados con prob: {len(rows)}\n")
por_liga = defaultdict(lambda: {'n':0, 'bs_sys':0.0, 'bs_book':0.0, 'n_book':0,
                                'goles_l':0, 'goles_v':0, 'empates':0, 'wins_l':0,
                                'p1_sum':0.0, 'px_sum':0.0, 'p2_sum':0.0})
for row in rows:
    _, fecha, pais, p1, px, p2, c1, cx, c2, gl, gv, xgl, xgv = row
    d = por_liga[pais]
    d['n'] += 1
    d['bs_sys'] += bs_row(p1, px, p2, gl, gv)
    bs_b = bs_bookie(c1, cx, c2, gl, gv)
    if bs_b is not None:
        d['bs_book'] += bs_b
        d['n_book'] += 1
    d['goles_l'] += gl
    d['goles_v'] += gv
    d['empates'] += (1 if gl==gv else 0)
    d['wins_l']  += (1 if gl>gv else 0)
    d['p1_sum']  += p1
    d['px_sum']  += px
    d['p2_sum']  += p2

print(f"{'LIGA':<14} {'N':>4} {'BS_sys':>8} {'BS_bk':>8} {'Delta':>8} {'p1_avg':>7} {'freqL':>7} {'px_avg':>7} {'freqX':>7}")
for liga in sorted(por_liga.keys()):
    d = por_liga[liga]
    bs_sys = d['bs_sys']/d['n']
    if d['n_book']>0:
        bs_book = d['bs_book']/d['n_book']
        delta = bs_sys - bs_book
        bk_str = f"{bs_book:>8.4f} {delta:>+8.4f}"
    else:
        bk_str = f"{'--':>8} {'--':>8}"
    p1_avg = d['p1_sum']/d['n']
    px_avg = d['px_sum']/d['n']
    freq_l = d['wins_l']/d['n']
    freq_x = d['empates']/d['n']
    print(f"{liga:<14} {d['n']:>4} {bs_sys:>8.4f} {bk_str} {p1_avg:>7.3f} {freq_l:>7.3f} {px_avg:>7.3f} {freq_x:>7.3f}")

# Total
tot_sys = sum(d['bs_sys'] for d in por_liga.values())
tot_book = sum(d['bs_book'] for d in por_liga.values())
tot_n = sum(d['n'] for d in por_liga.values())
tot_nb = sum(d['n_book'] for d in por_liga.values())
print(f"\n[TOTAL]  N={tot_n}  BS_sys={tot_sys/tot_n:.4f}  BS_book={tot_book/max(1,tot_nb):.4f}  Delta={tot_sys/tot_n - tot_book/max(1,tot_nb):+.4f}")

# --- Reliability diagram por bucket (agregado total) ---
print("\n--- Reliability diagram (P1 local) ---")
print(f"{'bucket':<14} {'N':>4} {'pred_avg':>9} {'freq':>7} {'bias':>7}")
buckets = [(0,0.10),(0.10,0.20),(0.20,0.30),(0.30,0.40),(0.40,0.50),(0.50,0.60),(0.60,0.70),(0.70,0.80),(0.80,0.90),(0.90,1.01)]
for lo,hi in buckets:
    items = [(r[3], 1.0 if r[9]>r[10] else 0.0) for r in rows if lo<=r[3]<hi]
    if not items: continue
    n = len(items)
    pa = sum(x[0] for x in items)/n
    fr = sum(x[1] for x in items)/n
    print(f"[{lo:.2f},{hi:.2f}) {n:>4} {pa:>9.3f} {fr:>7.3f} {fr-pa:>+7.3f}")

print("\n--- Reliability diagram (PX empate) ---")
print(f"{'bucket':<14} {'N':>4} {'pred_avg':>9} {'freq':>7} {'bias':>7}")
for lo,hi in buckets:
    items = [(r[4], 1.0 if r[9]==r[10] else 0.0) for r in rows if lo<=r[4]<hi]
    if not items: continue
    n = len(items)
    pa = sum(x[0] for x in items)/n
    fr = sum(x[1] for x in items)/n
    print(f"[{lo:.2f},{hi:.2f}) {n:>4} {pa:>9.3f} {fr:>7.3f} {fr-pa:>+7.3f}")

print("\n--- Reliability diagram (P2 visitante) ---")
print(f"{'bucket':<14} {'N':>4} {'pred_avg':>9} {'freq':>7} {'bias':>7}")
for lo,hi in buckets:
    items = [(r[5], 1.0 if r[10]>r[9] else 0.0) for r in rows if lo<=r[5]<hi]
    if not items: continue
    n = len(items)
    pa = sum(x[0] for x in items)/n
    fr = sum(x[1] for x in items)/n
    print(f"[{lo:.2f},{hi:.2f}) {n:>4} {pa:>9.3f} {fr:>7.3f} {fr-pa:>+7.3f}")

# --- Brier ROLLING 14d ---
from datetime import datetime, timedelta
rows_dt = [(datetime.strptime(r[1][:10], '%Y-%m-%d'), r) for r in rows if r[1]]
rows_dt.sort(key=lambda x: x[0])
max_dt = rows_dt[-1][0]
cutoff = max_dt - timedelta(days=14)
reciente = [r for dt, r in rows_dt if dt >= cutoff]
bs_rec = sum(bs_row(r[3], r[4], r[5], r[9], r[10]) for r in reciente) / max(1, len(reciente))
print(f"\n[ROLLING-14d] N={len(reciente)}  BS_sys={bs_rec:.4f}  (desde {cutoff.date()} hasta {max_dt.date()})")

# --- Temperature scaling search ---
print("\n--- Temperature scaling grid (aplicado a log-odds globales) ---")
def temp_scale(p1, px, p2, T):
    p1, px, p2 = max(p1,1e-6), max(px,1e-6), max(p2,1e-6)
    l1, lx, l2 = math.log(p1)/T, math.log(px)/T, math.log(p2)/T
    m = max(l1,lx,l2)
    e1, ex, e2 = math.exp(l1-m), math.exp(lx-m), math.exp(l2-m)
    s = e1+ex+e2
    return e1/s, ex/s, e2/s

for T in [0.80, 0.85, 0.90, 0.95, 1.00, 1.05, 1.10, 1.15, 1.20, 1.25, 1.30, 1.40, 1.50]:
    total = 0.0
    for r in rows:
        q1, qx, q2 = temp_scale(r[3], r[4], r[5], T)
        total += bs_row(q1, qx, q2, r[9], r[10])
    print(f"  T={T:.2f}  BS_sys={total/len(rows):.4f}")

# Per-liga temperature grid (para top ligas)
print("\n--- Temperature optimal por liga (N>=15) ---")
for liga in sorted(por_liga.keys()):
    lrows = [r for r in rows if r[2]==liga]
    if len(lrows) < 15: continue
    best_T = 1.0
    best_bs = float('inf')
    for T100 in range(70, 160):
        T = T100/100
        bs = sum(bs_row(*temp_scale(r[3],r[4],r[5],T), r[9], r[10]) for r in lrows)/len(lrows)
        if bs < best_bs:
            best_bs = bs
            best_T = T
    bs_actual = sum(bs_row(r[3],r[4],r[5],r[9],r[10]) for r in lrows)/len(lrows)
    print(f"  {liga:<14} N={len(lrows):>3}  T*={best_T:.2f}  BS@T*={best_bs:.4f}  BS@T=1={bs_actual:.4f}  gain={bs_actual-best_bs:+.4f}")

# --- Rolling-14d temperature test ---
print("\n--- Temperature optimal en rolling-14d ---")
best_T, best_bs = 1.0, float('inf')
for T100 in range(70, 160):
    T = T100/100
    bs = sum(bs_row(*temp_scale(r[3],r[4],r[5],T), r[9], r[10]) for r in reciente)/len(reciente)
    if bs < best_bs:
        best_bs = bs; best_T = T
print(f"  rolling-14d N={len(reciente)} T*={best_T:.2f} BS@T*={best_bs:.4f} BS@T=1={bs_rec:.4f} gain={bs_rec-best_bs:+.4f}")

conn.close()
