# ANGULOS CREATIVOS — universo expandido N=8892 (apostable N=4339)
# Generado: agente investigador_xg | sesion 2026-05-02_team_filtros_oro
# JOIN: stats.fecha_fdco=fdco.fecha; EUR temp shift stats.temp+1=fdco.temp

import sqlite3, json, random, datetime as dt
from collections import defaultdict
from pathlib import Path

random.seed(42)
DB = "fondo_quant.db"
OUT_JSON = "analisis/angulos_creativos_universo_expandido.json"

c = sqlite3.connect(DB)
cur = c.cursor()

SQL_UNIVERSO = """
SELECT s.liga, s.temp, s.fecha AS f_iso, s.ht, s.at, s.hg, s.ag,
       f.cuota_1, f.cuota_x, f.cuota_2, f.cuota_o25, f.cuota_u25,
       p.prob_1, p.prob_x, p.prob_2, p.xg_l_pred, p.xg_v_pred, p.fecha_partido
FROM stats_partido_espn s
JOIN cuotas_historicas_fdco f
  ON s.liga=f.liga
  AND ((s.liga IN ('Argentina','Brasil') AND s.temp=f.temp)
       OR (s.liga NOT IN ('Argentina','Brasil') AND s.temp+1=f.temp))
  AND s.fecha_fdco=f.fecha
  AND s.ht_fdco_norm=f.equipo_local_norm
  AND s.at_fdco_norm=f.equipo_visita_norm
JOIN predicciones_walkforward p
  ON p.liga=s.liga AND p.temp=s.temp
  AND substr(p.fecha_partido,1,10)=substr(s.fecha,1,10)
  AND p.ht=s.ht AND p.at=s.at
WHERE p.fuente='walk_forward_sistema_real'
  AND s.hg IS NOT NULL AND s.ag IS NOT NULL
  AND f.cuota_1 IS NOT NULL AND f.cuota_2 IS NOT NULL AND f.cuota_x IS NOT NULL
  AND p.prob_1 IS NOT NULL
"""


# ============ PARSE ============
print("[query] running JOIN universo...")
rows = cur.execute(SQL_UNIVERSO).fetchall()
print(f"[universo] N JOIN = {len(rows)}")

KEYS = ['liga','temp','fecha','ht','at','hg','ag','c1','cx','c2','co','cu',
        'p1','px','p2','xg_l','xg_v','f_full']

records = []
for r in rows:
    d = dict(zip(KEYS, r))
    if d['hg'] > d['ag']:   d['out'] = '1'
    elif d['hg'] < d['ag']: d['out'] = '2'
    else:                   d['out'] = 'X'
    try:
        d['date'] = dt.date.fromisoformat(d['fecha'][:10])
    except Exception:
        continue
    d['year'] = d['date'].year
    d['month'] = d['date'].month
    d['dow'] = d['date'].weekday()
    probs = {'1':d['p1'],'X':d['px'],'2':d['p2']}
    d['argmax'] = max(probs, key=probs.get)
    d['p_argmax'] = probs[d['argmax']]
    d['cuota_argmax'] = {'1':d['c1'],'X':d['cx'],'2':d['c2']}[d['argmax']]
    inv_sum = (1.0/d['c1']) + (1.0/d['cx']) + (1.0/d['c2'])
    d['overround'] = inv_sum
    d['p_mkt_argmax'] = (1.0/d['cuota_argmax'])/inv_sum if inv_sum>0 else None
    full = d['f_full'] or ''
    d['hh'] = int(full[11:13]) if 'T' in full else None
    records.append(d)

N = len(records)
print(f"[universo] N records validos = {N}")
print(f"[universo] ligas: {sorted(set(r['liga'] for r in records))}")
print(f"[universo] anos: {sorted(set(r['year'] for r in records))}")


# ============ HELPERS ============
def yield_metric(picks, side_key="argmax"):
    if not picks: return None, 0, None
    pl = 0.0; n = 0
    for d in picks:
        if callable(side_key):    side = side_key(d)
        elif side_key in ("1","X","2"): side = side_key
        else:                     side = d[side_key]
        if side is None: continue
        cuota = {"1":d["c1"],"X":d["cx"],"2":d["c2"]}.get(side)
        if not cuota: continue
        pl += (cuota - 1) if d["out"]==side else -1.0
        n += 1
    if n == 0: return None, 0, None
    return pl/n, n, pl

def hit_rate(picks, side_key="argmax"):
    if not picks: return None
    h, n = 0, 0
    for d in picks:
        if callable(side_key):    side = side_key(d)
        elif side_key in ("1","X","2"): side = side_key
        else:                     side = d[side_key]
        if side is None: continue
        if d["out"]==side: h += 1
        n += 1
    return h/n if n else None

def bootstrap_ci(picks, side_key="argmax", B=1500):
    pls = []
    for d in picks:
        if callable(side_key):    side = side_key(d)
        elif side_key in ("1","X","2"): side = side_key
        else:                     side = d[side_key]
        if side is None: continue
        cuota = {"1":d["c1"],"X":d["cx"],"2":d["c2"]}.get(side)
        if not cuota: continue
        pl = (cuota-1) if d["out"]==side else -1.0
        pls.append(pl)
    if len(pls) < 5: return None, None
    n = len(pls); ys = []
    for _ in range(B):
        s = 0.0
        for _i in range(n): s += pls[random.randrange(n)]
        ys.append(s/n)
    ys.sort()
    return ys[int(0.025*B)], ys[int(0.975*B)]

def years_pos(picks, side_key="argmax"):
    yr = defaultdict(list)
    for d in picks: yr[d["year"]].append(d)
    pos = 0
    for y_, lst in yr.items():
        yval, _, _ = yield_metric(lst, side_key)
        if yval is not None and yval > 0: pos += 1
    return f"{pos}/{len(yr)}"

def fmt(x, w=8, pct=True):
    if x is None: return " "*w
    return f"{x*100:+{w-1}.2f}%" if pct else f"{x:{w}.4f}"

def build_diff_gap(records):
    team_last = {}
    sorted_r = sorted(records, key=lambda x: x["date"])
    for d in sorted_r:
        kl = (d["liga"], d["ht"]); kv = (d["liga"], d["at"])
        d["gap_l"] = (d["date"] - team_last[kl]).days if kl in team_last else None
        d["gap_v"] = (d["date"] - team_last[kv]).days if kv in team_last else None
        team_last[kl] = d["date"]; team_last[kv] = d["date"]
    return sorted_r

def build_olas(records, sorted_r):
    team_hist = defaultdict(list)
    def ola(seq, n):
        if len(seq) < n: return None
        last = seq[-n:]
        return last.count("W") - last.count("L")
    for d in sorted_r:
        kl, kv = (d["liga"],d["ht"]), (d["liga"],d["at"])
        d["ola3_l"] = ola(team_hist[kl],3)
        d["ola5_l"] = ola(team_hist[kl],5)
        d["ola3_v"] = ola(team_hist[kv],3)
        d["ola5_v"] = ola(team_hist[kv],5)
        if d["out"]=="1":
            team_hist[kl].append("W"); team_hist[kv].append("L")
        elif d["out"]=="2":
            team_hist[kl].append("L"); team_hist[kv].append("W")
        else:
            team_hist[kl].append("D"); team_hist[kv].append("D")

sorted_r = build_diff_gap(records)
build_olas(records, sorted_r)

results = {"universe": {}, "angulos": {}}
side1 = lambda x: "1"
side2 = lambda x: "2"
sideX = lambda x: "X"

# baseline
print()
print("="*70)
print("BASELINE V0_argmax")
print("="*70)
y, n, pl = yield_metric(records)
ci_lo, ci_hi = bootstrap_ci(records)
hr = hit_rate(records)
print(f"  N={n}  y={fmt(y)}  CI95=[{fmt(ci_lo)},{fmt(ci_hi)}]  hit={fmt(hr)}  yrs+={years_pos(records)}")
results["universe"] = {"N_total":N,"N_apostado":n,"baseline_yield":y,"baseline_hit":hr,
                       "ci95_baseline":[ci_lo,ci_hi],"years_pos":years_pos(records)}
BASELINE_Y = y


# ============ ANGULO 1: TEMPORALES ============
print()
print("="*70); print("ANGULO 1 — temporales (DOW, mes, gap_dias)"); print("="*70)
DOW = {0:"Lun",1:"Mar",2:"Mie",3:"Jue",4:"Vie",5:"Sab",6:"Dom"}

# 1A DOW
results["angulos"]["1A_dow"] = {}
for dnum in range(7):
    sub = [r for r in records if r["dow"]==dnum]
    if len(sub) < 80: continue
    yv,nv,_ = yield_metric(sub); cilo,cihi = bootstrap_ci(sub, B=800); yp = years_pos(sub)
    results["angulos"]["1A_dow"][DOW[dnum]] = {"N":nv,"yield":yv,"ci95":[cilo,cihi],"years_pos":yp}
    print(f"  {DOW[dnum]}: N={nv:5d} y={fmt(yv)} CI=[{fmt(cilo)},{fmt(cihi)}] yrs+:{yp}")

# 1B Mes
print("  --- Mes ---")
results["angulos"]["1B_mes"] = {}
for m in range(1,13):
    sub = [r for r in records if r["month"]==m]
    if len(sub) < 80: continue
    yv,nv,_ = yield_metric(sub); cilo,cihi = bootstrap_ci(sub, B=800); yp = years_pos(sub)
    results["angulos"]["1B_mes"][m] = {"N":nv,"yield":yv,"ci95":[cilo,cihi],"years_pos":yp}
    print(f"  Mes {m:2d}: N={nv:5d} y={fmt(yv)} CI=[{fmt(cilo)},{fmt(cihi)}] yrs+:{yp}")

# 1C gap_dias local
print("  --- gap_dias local ---")
gap_buckets = {"<=3":[],"4-5":[],"6-7":[],"8-13":[],">=14":[]}
for d in records:
    g = d.get("gap_l")
    if g is None: continue
    if g<=3: gap_buckets["<=3"].append(d)
    elif g<=5: gap_buckets["4-5"].append(d)
    elif g<=7: gap_buckets["6-7"].append(d)
    elif g<=13: gap_buckets["8-13"].append(d)
    else: gap_buckets[">=14"].append(d)
results["angulos"]["1C_gap_local"] = {}
for k_,sub in gap_buckets.items():
    if len(sub)<80: continue
    yv,nv,_ = yield_metric(sub); cilo,cihi = bootstrap_ci(sub, B=800); yp = years_pos(sub)
    results["angulos"]["1C_gap_local"][k_] = {"N":nv,"yield":yv,"ci95":[cilo,cihi],"years_pos":yp}
    print(f"  gap_l {k_:6s}: N={nv:5d} y={fmt(yv)} CI=[{fmt(cilo)},{fmt(cihi)}] yrs+:{yp}")

# 1D Diferencial gap
print("  --- diff_gap (local-visita) -> apostar local siempre ---")
diff_buckets = {"L+5":[],"L+2_4":[],"par":[],"V+2_4":[],"V+5":[]}
for d in records:
    if d.get("gap_l") is None or d.get("gap_v") is None: continue
    diff = d["gap_l"] - d["gap_v"]
    if diff>=5: diff_buckets["L+5"].append(d)
    elif diff>=2: diff_buckets["L+2_4"].append(d)
    elif diff>=-1: diff_buckets["par"].append(d)
    elif diff>=-4: diff_buckets["V+2_4"].append(d)
    else: diff_buckets["V+5"].append(d)
results["angulos"]["1D_diff_gap_apostar_1"] = {}
for k_,sub in diff_buckets.items():
    if len(sub)<80: continue
    yv,nv,_ = yield_metric(sub, side_key=side1); cilo,cihi = bootstrap_ci(sub, side_key=side1, B=800); yp = years_pos(sub, side_key=side1)
    results["angulos"]["1D_diff_gap_apostar_1"][k_] = {"N":nv,"yield":yv,"ci95":[cilo,cihi],"years_pos":yp}
    print(f"  diff {k_:7s}: N={nv:5d} y_loc={fmt(yv)} CI=[{fmt(cilo)},{fmt(cihi)}] yrs+:{yp}")


# ============ ANGULO 2: FORMA RECIENTE ============
print()
print("="*70); print("ANGULO 2 — forma reciente (ola_3, ola_5)"); print("="*70)

# 2A local racha (ola3>=2) + visita seq (ola3<=-2) -> 1
sub = [r for r in records if r.get("ola3_l") is not None and r.get("ola3_v") is not None
       and r["ola3_l"]>=2 and r["ola3_v"]<=-2]
yv,nv,_ = yield_metric(sub, side_key=side1); cilo,cihi = bootstrap_ci(sub, side_key=side1, B=1200); yp = years_pos(sub, side_key=side1)
print(f"  Local racha+visita seq -> 1: N={nv} y={fmt(yv)} CI=[{fmt(cilo)},{fmt(cihi)}] yrs+:{yp}")
results["angulos"]["2A_localracha_apostar_1"] = {"N":nv,"yield":yv,"ci95":[cilo,cihi],"years_pos":yp}

# 2B inverso
sub = [r for r in records if r.get("ola3_l") is not None and r.get("ola3_v") is not None
       and r["ola3_v"]>=2 and r["ola3_l"]<=-2]
yv,nv,_ = yield_metric(sub, side_key=side2); cilo,cihi = bootstrap_ci(sub, side_key=side2, B=1200); yp = years_pos(sub, side_key=side2)
print(f"  Visita racha+local seq -> 2: N={nv} y={fmt(yv)} CI=[{fmt(cilo)},{fmt(cihi)}] yrs+:{yp}")
results["angulos"]["2B_visitaracha_apostar_2"] = {"N":nv,"yield":yv,"ci95":[cilo,cihi],"years_pos":yp}

# 2C anti-hype local: ola5_l>=4 -> fade visita
sub = [r for r in records if r.get("ola5_l") is not None and r["ola5_l"]>=4]
yv,nv,_ = yield_metric(sub, side_key=side2); cilo,cihi = bootstrap_ci(sub, side_key=side2, B=1200); yp = years_pos(sub, side_key=side2)
print(f"  ANTI-hype local (ola5_l>=4) -> fade 2: N={nv} y={fmt(yv)} CI=[{fmt(cilo)},{fmt(cihi)}] yrs+:{yp}")
results["angulos"]["2C_anti_hype_local_fade_2"] = {"N":nv,"yield":yv,"ci95":[cilo,cihi],"years_pos":yp}

# 2D pro-hype local (continuar)
sub = [r for r in records if r.get("ola5_l") is not None and r["ola5_l"]>=4]
yv,nv,_ = yield_metric(sub, side_key=side1); cilo,cihi = bootstrap_ci(sub, side_key=side1, B=1200); yp = years_pos(sub, side_key=side1)
print(f"  PRO-hype local (ola5_l>=4) -> 1: N={nv} y={fmt(yv)} CI=[{fmt(cilo)},{fmt(cihi)}] yrs+:{yp}")
results["angulos"]["2D_pro_hype_local_apostar_1"] = {"N":nv,"yield":yv,"ci95":[cilo,cihi],"years_pos":yp}

# 2E anti-hype visita: ola5_v>=4 -> fade local
sub = [r for r in records if r.get("ola5_v") is not None and r["ola5_v"]>=4]
yv,nv,_ = yield_metric(sub, side_key=side1); cilo,cihi = bootstrap_ci(sub, side_key=side1, B=1200); yp = years_pos(sub, side_key=side1)
print(f"  ANTI-hype visita (ola5_v>=4) -> fade 1: N={nv} y={fmt(yv)} CI=[{fmt(cilo)},{fmt(cihi)}] yrs+:{yp}")
results["angulos"]["2E_anti_hype_visita_fade_1"] = {"N":nv,"yield":yv,"ci95":[cilo,cihi],"years_pos":yp}


# ============ ANGULO 3: MERCADO ============
print()
print("="*70); print("ANGULO 3 — mercado (overround, paridad, dogs)"); print("="*70)

# 3A overround buckets
or_buckets = {"<=1.04":[],"1.04-1.06":[],"1.06-1.08":[],">=1.08":[]}
for d in records:
    o = d["overround"]
    if o<=1.04: or_buckets["<=1.04"].append(d)
    elif o<=1.06: or_buckets["1.04-1.06"].append(d)
    elif o<=1.08: or_buckets["1.06-1.08"].append(d)
    else: or_buckets[">=1.08"].append(d)
results["angulos"]["3A_overround"] = {}
for k_,sub in or_buckets.items():
    if len(sub)<100: continue
    yv,nv,_ = yield_metric(sub); cilo,cihi = bootstrap_ci(sub, B=800); yp = years_pos(sub)
    results["angulos"]["3A_overround"][k_] = {"N":nv,"yield":yv,"ci95":[cilo,cihi],"years_pos":yp}
    print(f"  OR {k_:11s}: N={nv:5d} y={fmt(yv)} CI=[{fmt(cilo)},{fmt(cihi)}] yrs+:{yp}")

# 3B X paritarios
sub = [r for r in records if r["cx"] and 3.0<=r["cx"]<=3.6 and abs(r["c1"]-r["c2"])<=0.30]
if len(sub)>=80:
    yv,nv,_ = yield_metric(sub, side_key=sideX); cilo,cihi = bootstrap_ci(sub, side_key=sideX, B=1200); yp = years_pos(sub, side_key=sideX)
    print(f"  X paritarios cx[3.0,3.6] |c1-c2|<=0.3: N={nv} y={fmt(yv)} CI=[{fmt(cilo)},{fmt(cihi)}] yrs+:{yp}")
    results["angulos"]["3B_X_paritario"] = {"N":nv,"yield":yv,"ci95":[cilo,cihi],"years_pos":yp}

# 3C dog visita
sub = [r for r in records if r["c2"] and 4.0<=r["c2"]<=7.5]
yv,nv,_ = yield_metric(sub, side_key=side2); cilo,cihi = bootstrap_ci(sub, side_key=side2, B=1200); yp = years_pos(sub, side_key=side2)
print(f"  Dog visita c2[4,7.5]: N={nv} y={fmt(yv)} CI=[{fmt(cilo)},{fmt(cihi)}] yrs+:{yp}")
results["angulos"]["3C_dog_visita"] = {"N":nv,"yield":yv,"ci95":[cilo,cihi],"years_pos":yp}

# 3D heavy fav local
sub = [r for r in records if r["c1"] and r["c1"]<=1.35]
yv,nv,_ = yield_metric(sub, side_key=side1); cilo,cihi = bootstrap_ci(sub, side_key=side1, B=1200); yp = years_pos(sub, side_key=side1)
print(f"  Heavy fav local c1<=1.35 -> 1: N={nv} y={fmt(yv)} CI=[{fmt(cilo)},{fmt(cihi)}] yrs+:{yp}")
results["angulos"]["3D_heavy_fav_local_1"] = {"N":nv,"yield":yv,"ci95":[cilo,cihi],"years_pos":yp}

# 3E heavy fav visita
sub = [r for r in records if r["c2"] and r["c2"]<=1.55]
yv,nv,_ = yield_metric(sub, side_key=side2); cilo,cihi = bootstrap_ci(sub, side_key=side2, B=1200); yp = years_pos(sub, side_key=side2)
print(f"  Heavy fav visita c2<=1.55 -> 2: N={nv} y={fmt(yv)} CI=[{fmt(cilo)},{fmt(cihi)}] yrs+:{yp}")
results["angulos"]["3E_heavy_fav_visita_2"] = {"N":nv,"yield":yv,"ci95":[cilo,cihi],"years_pos":yp}

# 3F V0 over-confident vs mkt en argmax
sub = [r for r in records if r.get("p_mkt_argmax") is not None and r["p_argmax"]-r["p_mkt_argmax"]>=0.06]
yv,nv,_ = yield_metric(sub); cilo,cihi = bootstrap_ci(sub, B=1200); yp = years_pos(sub)
print(f"  V0-mkt>=+6pp: N={nv} y={fmt(yv)} CI=[{fmt(cilo)},{fmt(cihi)}] yrs+:{yp}")
results["angulos"]["3F_V0_overconfident"] = {"N":nv,"yield":yv,"ci95":[cilo,cihi],"years_pos":yp}

# 3G V0 alineado con mkt
sub = [r for r in records if r.get("p_mkt_argmax") is not None and abs(r["p_argmax"]-r["p_mkt_argmax"])<=0.02]
yv,nv,_ = yield_metric(sub); cilo,cihi = bootstrap_ci(sub, B=1200); yp = years_pos(sub)
print(f"  V0~mkt |delta|<=2pp: N={nv} y={fmt(yv)} CI=[{fmt(cilo)},{fmt(cihi)}] yrs+:{yp}")
results["angulos"]["3G_V0_aligned_mkt"] = {"N":nv,"yield":yv,"ci95":[cilo,cihi],"years_pos":yp}

# 3H V0 sub-confident vs mkt
sub = [r for r in records if r.get("p_mkt_argmax") is not None and r["p_argmax"]-r["p_mkt_argmax"]<=-0.06]
yv,nv,_ = yield_metric(sub); cilo,cihi = bootstrap_ci(sub, B=1200); yp = years_pos(sub)
print(f"  V0-mkt<=-6pp: N={nv} y={fmt(yv)} CI=[{fmt(cilo)},{fmt(cihi)}] yrs+:{yp}")
results["angulos"]["3H_V0_subconfident"] = {"N":nv,"yield":yv,"ci95":[cilo,cihi],"years_pos":yp}


# ============ ANGULO 4: HORA ============
print()
print("="*70); print("ANGULO 4 — hora del partido"); print("="*70)
hora_buckets = {"<14":[],"14-16":[],"17-19":[],"20-22":[],">=23":[]}
for d in records:
    h = d.get("hh")
    if h is None: continue
    if h<14: hora_buckets["<14"].append(d)
    elif h<17: hora_buckets["14-16"].append(d)
    elif h<20: hora_buckets["17-19"].append(d)
    elif h<23: hora_buckets["20-22"].append(d)
    else: hora_buckets[">=23"].append(d)
results["angulos"]["4A_hora"] = {}
for k_,sub in hora_buckets.items():
    if len(sub)<100: continue
    yv,nv,_ = yield_metric(sub); cilo,cihi = bootstrap_ci(sub, B=800); yp = years_pos(sub)
    results["angulos"]["4A_hora"][k_] = {"N":nv,"yield":yv,"ci95":[cilo,cihi],"years_pos":yp}
    print(f"  hora {k_:6s}: N={nv:5d} y={fmt(yv)} CI=[{fmt(cilo)},{fmt(cihi)}] yrs+:{yp}")

# 4B early sat
sub = [r for r in records if r["dow"]==5 and r.get("hh") is not None and r["hh"]<=13]
if len(sub)>=80:
    yv,nv,_ = yield_metric(sub); cilo,cihi = bootstrap_ci(sub, B=1200); yp = years_pos(sub)
    print(f"  Sab early (DOW=5, h<=13): N={nv} y={fmt(yv)} CI=[{fmt(cilo)},{fmt(cihi)}] yrs+:{yp}")
    results["angulos"]["4B_sat_early"] = {"N":nv,"yield":yv,"ci95":[cilo,cihi],"years_pos":yp}

# ============ ANGULO 5: COMBINACIONES ============
print()
print("="*70); print("ANGULO 5 — combinaciones (intersecciones)"); print("="*70)

# 5A V0>=0.55 + OR<=1.06 + DOW in {Jue,Sab,Dom}
sub = [r for r in records if r["p_argmax"]>=0.55 and r["overround"]<=1.06 and r["dow"] in (3,5,6)]
yv,nv,_ = yield_metric(sub); cilo,cihi = bootstrap_ci(sub, B=1200); yp = years_pos(sub)
print(f"  V0>=0.55+OR<=1.06+DOWin{{Jue,Sab,Dom}}: N={nv} y={fmt(yv)} CI=[{fmt(cilo)},{fmt(cihi)}] yrs+:{yp}")
results["angulos"]["5A_combo_premium"] = {"N":nv,"yield":yv,"ci95":[cilo,cihi],"years_pos":yp}

# 5B P>=0.50 + cuota[1.7,2.5] + ola3 alineada
def aligned(d):
    if d["argmax"]=="1" and d.get("ola3_l") is not None and d["ola3_l"]>=1: return True
    if d["argmax"]=="2" and d.get("ola3_v") is not None and d["ola3_v"]>=1: return True
    return False
sub = [r for r in records if r["p_argmax"]>=0.50 and 1.7<=r["cuota_argmax"]<=2.5 and aligned(r)]
yv,nv,_ = yield_metric(sub); cilo,cihi = bootstrap_ci(sub, B=1200); yp = years_pos(sub)
print(f"  P>=0.50+cuota[1.7,2.5]+ola3 align: N={nv} y={fmt(yv)} CI=[{fmt(cilo)},{fmt(cihi)}] yrs+:{yp}")
results["angulos"]["5B_aligned_streak"] = {"N":nv,"yield":yv,"ci95":[cilo,cihi],"years_pos":yp}

# 5C anti-empate: argmax!=X + px<0.27
sub = [r for r in records if r["argmax"]!="X" and r["px"]<0.27]
yv,nv,_ = yield_metric(sub); cilo,cihi = bootstrap_ci(sub, B=1200); yp = years_pos(sub)
print(f"  argmax!=X + px<0.27: N={nv} y={fmt(yv)} CI=[{fmt(cilo)},{fmt(cihi)}] yrs+:{yp}")
results["angulos"]["5C_anti_empate"] = {"N":nv,"yield":yv,"ci95":[cilo,cihi],"years_pos":yp}

# 5D heavy fav local + ola5_l>=2
sub = [r for r in records if r["c1"] and r["c1"]<=1.55 and r.get("ola5_l") is not None and r["ola5_l"]>=2]
yv,nv,_ = yield_metric(sub, side_key=side1); cilo,cihi = bootstrap_ci(sub, side_key=side1, B=1200); yp = years_pos(sub, side_key=side1)
print(f"  Fav local c1<=1.55+ola5>=2 -> 1: N={nv} y={fmt(yv)} CI=[{fmt(cilo)},{fmt(cihi)}] yrs+:{yp}")
results["angulos"]["5D_doble_conviccion_local"] = {"N":nv,"yield":yv,"ci95":[cilo,cihi],"years_pos":yp}

# 5E dog visita c2[4,7] + ola5_v>=2
sub = [r for r in records if r["c2"] and 4.0<=r["c2"]<=7.0 and r.get("ola5_v") is not None and r["ola5_v"]>=2]
yv,nv,_ = yield_metric(sub, side_key=side2); cilo,cihi = bootstrap_ci(sub, side_key=side2, B=1200); yp = years_pos(sub, side_key=side2)
print(f"  Dog visita c2[4,7]+ola5_v>=2 -> 2: N={nv} y={fmt(yv)} CI=[{fmt(cilo)},{fmt(cihi)}] yrs+:{yp}")
results["angulos"]["5E_dog_aligned"] = {"N":nv,"yield":yv,"ci95":[cilo,cihi],"years_pos":yp}

# 5F midweek con confianza
sub = [r for r in records if r.get("gap_l") is not None and r["gap_l"]<=4 and r["p_argmax"]>=0.55]
yv,nv,_ = yield_metric(sub); cilo,cihi = bootstrap_ci(sub, B=1200); yp = years_pos(sub)
print(f"  gap_l<=4+P>=0.55: N={nv} y={fmt(yv)} CI=[{fmt(cilo)},{fmt(cihi)}] yrs+:{yp}")
results["angulos"]["5F_midweek_confidence"] = {"N":nv,"yield":yv,"ci95":[cilo,cihi],"years_pos":yp}

# 5G dog visita aligned + V0 sub-confident vs mkt (mkt mas alto en argmax)
sub = [r for r in records if r["argmax"]=="1" and r.get("p_mkt_argmax") is not None
       and r["p_mkt_argmax"]-r["p_argmax"]>=0.06 and r["c2"] and 3.5<=r["c2"]<=6.0]
yv,nv,_ = yield_metric(sub, side_key=side2); cilo,cihi = bootstrap_ci(sub, side_key=side2, B=1200); yp = years_pos(sub, side_key=side2)
print(f"  V0 dice 1 pero mkt cree mas en local + dog visita: N={nv} y={fmt(yv)} CI=[{fmt(cilo)},{fmt(cihi)}] yrs+:{yp}")
results["angulos"]["5G_mkt_overconfident_local_apostar_dog"] = {"N":nv,"yield":yv,"ci95":[cilo,cihi],"years_pos":yp}


# ============ ANGULO 6: O/U CREATIVOS ============
print()
print("="*70); print("ANGULO 6 — O/U creativos"); print("="*70)

def settle_ou(d, side):
    tot = d["hg"]+d["ag"]
    cuota = d["co"] if side=="O" else d["cu"]
    if cuota is None: return None
    win = (tot>2.5) if side=="O" else (tot<=2.5)
    return (cuota-1) if win else -1.0

def yield_ou(picks, side):
    pls = [v for v in (settle_ou(d,side) for d in picks) if v is not None]
    return (sum(pls)/len(pls), len(pls)) if pls else (None,0)

def bootstrap_ou(picks, side, B=1200):
    pls = [v for v in (settle_ou(d,side) for d in picks) if v is not None]
    if len(pls)<5: return None,None
    n = len(pls); ys=[]
    for _ in range(B):
        s=0.0
        for _i in range(n): s += pls[random.randrange(n)]
        ys.append(s/n)
    ys.sort()
    return ys[int(0.025*B)], ys[int(0.975*B)]

def years_pos_ou(picks, side):
    yr = defaultdict(list)
    for d in picks: yr[d["year"]].append(d)
    pos = sum(1 for ys,lst in yr.items() if (yield_ou(lst,side)[0] or -1)>0)
    return f"{pos}/{len(yr)}"

# 6A U2.5 + paritarios + cu25 valor (>=1.85)
sub = [r for r in records if r["co"] and r["cu"] and 3.0<=r["cx"]<=3.6 and r["cu"]>=1.85]
if sub:
    yv,nv = yield_ou(sub,"U"); cilo,cihi = bootstrap_ou(sub,"U", B=1200); yp = years_pos_ou(sub,"U")
    print(f"  U25 paritarios cu25>=1.85: N={nv} y={fmt(yv)} CI=[{fmt(cilo)},{fmt(cihi)}] yrs+:{yp}")
    results["angulos"]["6A_U25_paritarios"] = {"N":nv,"yield":yv,"ci95":[cilo,cihi],"years_pos":yp}

# 6B O25 dos atacantes (c1<=2.0 y c2<=2.5)
sub = [r for r in records if r["co"] and r["c1"]<=2.0 and r["c2"]<=2.5]
if sub:
    yv,nv = yield_ou(sub,"O"); cilo,cihi = bootstrap_ou(sub,"O", B=1200); yp = years_pos_ou(sub,"O")
    print(f"  O25 dos atacantes (c1<=2,c2<=2.5): N={nv} y={fmt(yv)} CI=[{fmt(cilo)},{fmt(cihi)}] yrs+:{yp}")
    results["angulos"]["6B_O25_atacantes"] = {"N":nv,"yield":yv,"ci95":[cilo,cihi],"years_pos":yp}

# 6C U25 heavy fav (c1<=1.4)
sub = [r for r in records if r["cu"] and r["c1"]<=1.4]
if sub:
    yv,nv = yield_ou(sub,"U"); cilo,cihi = bootstrap_ou(sub,"U", B=1200); yp = years_pos_ou(sub,"U")
    print(f"  U25 heavy fav c1<=1.4: N={nv} y={fmt(yv)} CI=[{fmt(cilo)},{fmt(cihi)}] yrs+:{yp}")
    results["angulos"]["6C_U25_heavy_fav"] = {"N":nv,"yield":yv,"ci95":[cilo,cihi],"years_pos":yp}

# 6D O25 cuando V0 cree alto scoring (xg suma >= 3.0)
sub = [r for r in records if r["co"] and (r["xg_l"] or 0)+(r["xg_v"] or 0) >= 3.0]
if sub:
    yv,nv = yield_ou(sub,"O"); cilo,cihi = bootstrap_ou(sub,"O", B=1200); yp = years_pos_ou(sub,"O")
    print(f"  O25 V0 xg_total>=3.0: N={nv} y={fmt(yv)} CI=[{fmt(cilo)},{fmt(cihi)}] yrs+:{yp}")
    results["angulos"]["6D_O25_xg_alto"] = {"N":nv,"yield":yv,"ci95":[cilo,cihi],"years_pos":yp}


# ============ RANKING + OUTPUT ============
print()
print("="*70); print("RANKING TOP — yield + N>=80 + CI_lo>0 + sostenibilidad"); print("="*70)

ranking = []
def collect(prefix, dct):
    for k_, v in dct.items():
        if not isinstance(v, dict): continue
        if "yield" in v and "N" in v:
            yv = v.get("yield")
            nv = v.get("N",0)
            if yv is None or nv<80: continue
            ci = v.get("ci95",[None,None])
            ranking.append({
                "angulo": prefix+"."+str(k_),
                "N":nv, "yield":yv,
                "ci_lo":ci[0],"ci_hi":ci[1],
                "years_pos":v.get("years_pos","")
            })
        else:
            collect(prefix+"."+str(k_), v)

for k_top, v_top in results["angulos"].items():
    if not isinstance(v_top, dict): continue
    if "yield" in v_top and "N" in v_top:
        yv = v_top["yield"]; nv = v_top["N"]
        if yv is None or nv<80: continue
        ci = v_top.get("ci95",[None,None])
        ranking.append({
            "angulo":k_top,"N":nv,"yield":yv,
            "ci_lo":ci[0],"ci_hi":ci[1],
            "years_pos":v_top.get("years_pos","")
        })
    else:
        collect(k_top, v_top)

ranking.sort(key=lambda x: x["yield"] if x["yield"] is not None else -999, reverse=True)
print()
print(f"{'angulo':45s} {'N':>5s} {'yield':>9s} {'CI_lo':>9s} {'CI_hi':>9s} {'yrs+':>6s}")
print("-"*92)
for r in ranking[:20]:
    print(f"{r['angulo']:45s} {r['N']:5d} {fmt(r['yield']):>9s} {fmt(r['ci_lo']):>9s} {fmt(r['ci_hi']):>9s} {r['years_pos']:>6s}")

print("")
print(f"BASELINE V0_argmax: y={fmt(BASELINE_Y)}")
print("")
print("BOTTOM 5 (peor yield):")
for r in ranking[-5:]:
    print(f"{r['angulo']:45s} {r['N']:5d} {fmt(r['yield']):>9s} {fmt(r['ci_lo']):>9s} {fmt(r['ci_hi']):>9s} {r['years_pos']:>6s}")

# TOP angulos con CI_lo > 0 (estadisticamente positivos)
print()
print("TOP angulos con CI_lo > 0 (sig pos al 95%):")
sig_pos = [r for r in ranking if r["ci_lo"] is not None and r["ci_lo"]>0]
for r in sig_pos[:10]:
    print(f"  *** {r['angulo']:45s} N={r['N']:4d} y={fmt(r['yield'])} CI=[{fmt(r['ci_lo'])},{fmt(r['ci_hi'])}] yrs+:{r['years_pos']}")

results["ranking_top20"] = ranking[:20]
results["ranking_bottom5"] = ranking[-5:]
results["ranking_full"] = ranking
results["baseline_yield"] = BASELINE_Y
results["sig_positivos_ci_lo_gt_0"] = sig_pos

Path("analisis").mkdir(exist_ok=True)
with open(OUT_JSON,"w",encoding="utf-8") as f:
    json.dump(results, f, indent=2, default=str)
print()
print(f"[OUT] {OUT_JSON}")
