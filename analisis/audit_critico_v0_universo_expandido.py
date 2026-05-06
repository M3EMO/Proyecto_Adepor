"""
Audit critico V0 puro vs filtros sobre universo expandido.
Sesion 2026-05-02_team_filtros_oro - Critico.

Objetivo: con N expandido (post-fix mapping del agente 1), determinar si
existe alguna estrategia con CI95% Bonferroni > 0.

Universo audit:
- predicciones_walkforward.fuente='walk_forward_sistema_real' (probas V0 walk-forward,
  garantia anti-lookahead) JOIN stats_partido_espn (norm fix agente 1) JOIN
  cuotas_historicas_fdco (cuotas reales 1X2).
- Match: SUBSTR(fecha,1,10) + LOWER+strip(ht/at) entre wf y stats; stats.fecha_fdco +
  stats.ht_fdco_norm/at_fdco_norm <-> fdco.fecha + fdco.equipo_local_norm/visita_norm.

Output: yield + Brier + Sharpe + MaxDD + Bonferroni CI95% para 7 estrategias top.
"""
import math
import sqlite3
import json
from datetime import datetime
from pathlib import Path

DB = "fondo_quant.db"
SESION_ID = "2026-05-02_team_filtros_oro"
OUT_JSON = Path("analisis/audit_critico_v0_universo_expandido.json")
OUT_DOC = Path("docs/papers/audit_v0_crudo_n_expandido.md")

# ----------------------------------------------------------------------------
# 1) BUILD UNIVERSO
# ----------------------------------------------------------------------------
SQL_UNIVERSO = """
SELECT
  p.liga,
  SUBSTR(p.fecha_partido,1,10) AS fecha,
  p.ht, p.at, p.hg, p.ag, p.outcome,
  p.prob_1, p.prob_x, p.prob_2,
  f.cuota_1, f.cuota_x, f.cuota_2
FROM predicciones_walkforward p
INNER JOIN stats_partido_espn s
  ON p.liga=s.liga AND SUBSTR(p.fecha_partido,1,10)=SUBSTR(s.fecha,1,10)
 AND LOWER(REPLACE(REPLACE(p.ht,' ',''),'.',''))=LOWER(REPLACE(REPLACE(s.ht,' ',''),'.',''))
 AND LOWER(REPLACE(REPLACE(p.at,' ',''),'.',''))=LOWER(REPLACE(REPLACE(s.at,' ',''),'.',''))
INNER JOIN cuotas_historicas_fdco f
  ON s.liga=f.liga AND s.fecha_fdco=f.fecha
 AND s.ht_fdco_norm=f.equipo_local_norm
 AND s.at_fdco_norm=f.equipo_visita_norm
WHERE p.fuente='walk_forward_sistema_real'
  AND f.cuota_1>0 AND f.cuota_x>0 AND f.cuota_2>0
  AND p.prob_1>0 AND p.prob_x>0 AND p.prob_2>0
  AND p.outcome IN ('1','X','2')
"""


def fetch_universo():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    rows = cur.execute(SQL_UNIVERSO).fetchall()
    cols = ["liga", "fecha", "ht", "at", "hg", "ag", "outcome",
            "prob_1", "prob_x", "prob_2",
            "cuota_1", "cuota_x", "cuota_2"]
    data = [dict(zip(cols, r)) for r in rows]
    con.close()
    # Dedupe por (liga, fecha, ht, at) - take primer match
    seen = set()
    out = []
    for d in data:
        k = (d["liga"], d["fecha"], d["ht"], d["at"])
        if k in seen:
            continue
        seen.add(k)
        out.append(d)
    return out


# ----------------------------------------------------------------------------
# 2) METRICAS POR ESTRATEGIA
# ----------------------------------------------------------------------------

def pick_argmax(p1, px, p2):
    """Argmax 1X2 sobre las probabilidades del modelo."""
    if p1 >= px and p1 >= p2:
        return "1"
    if p2 >= px:
        return "2"
    return "X"


def pick_mercado(c1, cx, c2):
    """Pick = favorito de mercado (cuota minima)."""
    arr = [("1", c1), ("X", cx), ("2", c2)]
    arr.sort(key=lambda x: x[1])
    return arr[0][0]


def divergencia(probs_modelo, cuotas):
    """Divergencia maxima entre P_modelo y P_implied (sin overround)."""
    inv = [1.0 / c for c in cuotas]
    s = sum(inv)
    p_imp = [x / s for x in inv]
    div = [pm - pi for pm, pi in zip(probs_modelo, p_imp)]
    return div  # devuelve tres divergencias en orden 1, X, 2


def pl_from_pick(pick, outcome, cuota):
    """P/L unitario de stake=1."""
    if pick == outcome:
        return cuota - 1.0
    return -1.0


def stats_strategy(picks_log):
    """
    picks_log: list of dicts con keys pl (en unidades de stake=1).
    Devuelve N, hit, yield, Brier (parcial sobre la prob del pick), Sharpe, MaxDD.
    """
    n = len(picks_log)
    if n == 0:
        return dict(N=0, hit=None, yield_pct=None, brier=None,
                    sharpe=None, max_dd=None, ci_lo=None, ci_hi=None,
                    ci_lo_bonf=None, ci_hi_bonf=None)
    pls = [p["pl"] for p in picks_log]
    wins = [1 if p["pl"] > 0 else 0 for p in picks_log]
    hit = sum(wins) / n
    y = sum(pls) / n  # yield decimal
    mean = y
    var = sum((x - mean) ** 2 for x in pls) / max(n - 1, 1)
    std = math.sqrt(var)
    sharpe = mean / std * math.sqrt(n) if std > 0 else 0.0
    # MaxDD sobre curva acumulada
    eq = 0.0
    peak = 0.0
    max_dd = 0.0
    for x in pls:
        eq += x
        peak = max(peak, eq)
        max_dd = min(max_dd, eq - peak)
    # Brier (multi-clase 1X2): si hay prob/outcome en log
    if "brier_pt" in picks_log[0]:
        brier = sum(p["brier_pt"] for p in picks_log) / n
    else:
        brier = None
    # CI95% Wald sobre yield (no Wilson; pl puede ser negativo)
    se = std / math.sqrt(n) if n > 1 else 0.0
    ci_lo = y - 1.96 * se
    ci_hi = y + 1.96 * se
    return dict(N=n, hit=hit, yield_pct=y, brier=brier,
                sharpe=sharpe, max_dd=max_dd, std=std, se=se,
                ci_lo=ci_lo, ci_hi=ci_hi)


def bonferroni_ci(ci_lo_arr, ci_hi_arr, yields, ses, m_tests):
    """Devuelve CI95% Bonferroni-adjusted con alpha/m."""
    # alpha=0.05 -> per-test alpha = 0.05/m -> z=invnorm(1-alpha/(2m))
    # Aproximacion: z para 0.05/2=0.025 -> 1.96; para 0.05/14=0.0036 -> z~2.69
    # Usemos calculo directo
    from statistics import NormalDist
    alpha = 0.05
    z = NormalDist().inv_cdf(1 - alpha / (2 * m_tests))
    out = []
    for y, se in zip(yields, ses):
        out.append((y - z * se, y + z * se))
    return z, out


# ----------------------------------------------------------------------------
# 3) APLICAR ESTRATEGIAS
# ----------------------------------------------------------------------------

def brier_pick(prob_pick, outcome, pick):
    """Brier 1-class para el pick: (prob_pick - 1[pick==outcome])^2."""
    y = 1.0 if pick == outcome else 0.0
    return (prob_pick - y) ** 2


def estrategia_v0_puro(univ):
    """V0 argmax sobre todas las filas, sin filtro."""
    log = []
    for d in univ:
        pick = pick_argmax(d["prob_1"], d["prob_x"], d["prob_2"])
        cuota = {"1": d["cuota_1"], "X": d["cuota_x"], "2": d["cuota_2"]}[pick]
        prob_pick = {"1": d["prob_1"], "X": d["prob_x"], "2": d["prob_2"]}[pick]
        pl = pl_from_pick(pick, d["outcome"], cuota)
        log.append(dict(pl=pl, brier_pt=brier_pick(prob_pick, d["outcome"], pick)))
    return log


def estrategia_v0_ev(univ, ev_min=1.03):
    log = []
    for d in univ:
        pick = pick_argmax(d["prob_1"], d["prob_x"], d["prob_2"])
        cuota = {"1": d["cuota_1"], "X": d["cuota_x"], "2": d["cuota_2"]}[pick]
        prob_pick = {"1": d["prob_1"], "X": d["prob_x"], "2": d["prob_2"]}[pick]
        ev = prob_pick * cuota
        if ev < ev_min:
            continue
        pl = pl_from_pick(pick, d["outcome"], cuota)
        log.append(dict(pl=pl, brier_pt=brier_pick(prob_pick, d["outcome"], pick)))
    return log


def estrategia_v0_p_div(univ, p_min=0.55, div_min=0.05):
    log = []
    for d in univ:
        pick = pick_argmax(d["prob_1"], d["prob_x"], d["prob_2"])
        prob_pick = {"1": d["prob_1"], "X": d["prob_x"], "2": d["prob_2"]}[pick]
        if prob_pick < p_min:
            continue
        divs = divergencia([d["prob_1"], d["prob_x"], d["prob_2"]],
                           [d["cuota_1"], d["cuota_x"], d["cuota_2"]])
        idx = {"1": 0, "X": 1, "2": 2}[pick]
        if divs[idx] < div_min:
            continue
        cuota = {"1": d["cuota_1"], "X": d["cuota_x"], "2": d["cuota_2"]}[pick]
        pl = pl_from_pick(pick, d["outcome"], cuota)
        log.append(dict(pl=pl, brier_pt=brier_pick(prob_pick, d["outcome"], pick)))
    return log


def estrategia_v0_div_solo(univ, div_min=0.15):
    log = []
    for d in univ:
        pick = pick_argmax(d["prob_1"], d["prob_x"], d["prob_2"])
        prob_pick = {"1": d["prob_1"], "X": d["prob_x"], "2": d["prob_2"]}[pick]
        divs = divergencia([d["prob_1"], d["prob_x"], d["prob_2"]],
                           [d["cuota_1"], d["cuota_x"], d["cuota_2"]])
        idx = {"1": 0, "X": 1, "2": 2}[pick]
        if divs[idx] < div_min:
            continue
        cuota = {"1": d["cuota_1"], "X": d["cuota_x"], "2": d["cuota_2"]}[pick]
        pl = pl_from_pick(pick, d["outcome"], cuota)
        log.append(dict(pl=pl, brier_pt=brier_pick(prob_pick, d["outcome"], pick)))
    return log


def estrategia_v0_cuota_rango(univ, c_lo=1.5, c_hi=2.5):
    log = []
    for d in univ:
        pick = pick_argmax(d["prob_1"], d["prob_x"], d["prob_2"])
        cuota = {"1": d["cuota_1"], "X": d["cuota_x"], "2": d["cuota_2"]}[pick]
        if cuota < c_lo or cuota >= c_hi:
            continue
        prob_pick = {"1": d["prob_1"], "X": d["prob_x"], "2": d["prob_2"]}[pick]
        pl = pl_from_pick(pick, d["outcome"], cuota)
        log.append(dict(pl=pl, brier_pt=brier_pick(prob_pick, d["outcome"], pick)))
    return log


def estrategia_solo_local(univ):
    """Apostar siempre LOCAL sin importar argmax."""
    log = []
    for d in univ:
        pick = "1"
        cuota = d["cuota_1"]
        prob_pick = d["prob_1"]
        pl = pl_from_pick(pick, d["outcome"], cuota)
        log.append(dict(pl=pl, brier_pt=brier_pick(prob_pick, d["outcome"], pick)))
    return log


def estrategia_pick_mercado(univ):
    """Apostar al favorito de mercado (cuota minima). Baseline duro."""
    log = []
    for d in univ:
        pick = pick_mercado(d["cuota_1"], d["cuota_x"], d["cuota_2"])
        cuota = {"1": d["cuota_1"], "X": d["cuota_x"], "2": d["cuota_2"]}[pick]
        # Para Brier usamos prob de modelo del pick mercado
        prob_pick = {"1": d["prob_1"], "X": d["prob_x"], "2": d["prob_2"]}[pick]
        pl = pl_from_pick(pick, d["outcome"], cuota)
        log.append(dict(pl=pl, brier_pt=brier_pick(prob_pick, d["outcome"], pick)))
    return log


# ----------------------------------------------------------------------------
# 4) TEST RANDOM (apostar 1X2 al azar, equiponderado)
# ----------------------------------------------------------------------------

def estrategia_random_seed(univ, seed=42):
    """1/3 random pick. Reproducible."""
    import random
    rng = random.Random(seed)
    log = []
    for d in univ:
        pick = rng.choice(["1", "X", "2"])
        cuota = {"1": d["cuota_1"], "X": d["cuota_x"], "2": d["cuota_2"]}[pick]
        prob_pick = {"1": d["prob_1"], "X": d["prob_x"], "2": d["prob_2"]}[pick]
        pl = pl_from_pick(pick, d["outcome"], cuota)
        log.append(dict(pl=pl, brier_pt=brier_pick(prob_pick, d["outcome"], pick)))
    return log


# ----------------------------------------------------------------------------
# 5) MAIN
# ----------------------------------------------------------------------------

def main():
    print("=" * 70)
    print("AUDIT CRITICO V0 - UNIVERSO EXPANDIDO")
    print(f"Sesion: {SESION_ID}")
    print(f"Run: {datetime.now().isoformat(timespec='seconds')}")
    print("=" * 70)

    univ = fetch_universo()
    n_total = len(univ)
    print(f"\nUniverso final (wf walk_forward_sistema_real <-> stats <-> fdco): {n_total}")

    if n_total == 0:
        print("ERROR: universo vacio. Abortar.")
        return

    # Distribucion por liga
    from collections import Counter
    ligas = Counter(d["liga"] for d in univ)
    print("\nDistribucion por liga:")
    for liga, n in sorted(ligas.items(), key=lambda x: -x[1]):
        print(f"  {liga:<15s} {n:>5d}")

    # Distribucion por anio
    yrs = Counter(d["fecha"][:4] for d in univ)
    print("\nDistribucion por anio:")
    for y, n in sorted(yrs.items()):
        print(f"  {y} {n:>5d}")

    # Outcome real
    outc = Counter(d["outcome"] for d in univ)
    print("\nOutcome real:")
    for o in ["1", "X", "2"]:
        n = outc[o]
        print(f"  {o}: {n:>5d}  ({n/n_total*100:.1f}%)")

    # Aplicar estrategias
    estrategias = [
        ("V0_puro_argmax", estrategia_v0_puro(univ)),
        ("V0_EV_ge_1.03", estrategia_v0_ev(univ, 1.03)),
        ("V0_P_ge_0.55_DIV_ge_0.05", estrategia_v0_p_div(univ, 0.55, 0.05)),
        ("V0_P_ge_0.60_DIV_ge_0.05", estrategia_v0_p_div(univ, 0.60, 0.05)),
        ("V0_DIV_ge_0.15", estrategia_v0_div_solo(univ, 0.15)),
        ("V0_cuota_in_1.5_2.5", estrategia_v0_cuota_rango(univ, 1.5, 2.5)),
        ("solo_LOCAL", estrategia_solo_local(univ)),
        ("pick_MERCADO_favorito", estrategia_pick_mercado(univ)),
        ("RANDOM_1_3", estrategia_random_seed(univ, seed=42)),
    ]

    results = []
    for name, log in estrategias:
        st = stats_strategy(log)
        st["estrategia"] = name
        results.append(st)
        print(f"\n--- {name} ---")
        if st["N"] == 0:
            print("  N=0 (filtro deja universo vacio)")
            continue
        print(f"  N={st['N']:>5d}  hit={st['hit']:.4f}  yield={st['yield_pct']*100:+.2f}%")
        print(f"  Brier_pick={st['brier']:.4f}  Sharpe={st['sharpe']:+.3f}  MaxDD={st['max_dd']:+.2f}u")
        print(f"  CI95_Wald=[{st['ci_lo']*100:+.2f}%, {st['ci_hi']*100:+.2f}%]")

    # Bonferroni adjustment
    m = len([r for r in results if r["N"] > 0])
    yields = [r["yield_pct"] for r in results if r["N"] > 0]
    ses = [r["se"] for r in results if r["N"] > 0]
    z_bonf, ci_bonf = bonferroni_ci(None, None, yields, ses, m)
    print(f"\n=== BONFERRONI ADJUSTMENT (m={m} tests, alpha=0.05) ===")
    print(f"z_bonf = {z_bonf:.4f}")
    idx = 0
    for r in results:
        if r["N"] == 0:
            r["ci_lo_bonf"] = None
            r["ci_hi_bonf"] = None
            continue
        lo, hi = ci_bonf[idx]
        r["ci_lo_bonf"] = lo
        r["ci_hi_bonf"] = hi
        sig = "*** SIG POS" if lo > 0 else ("*** SIG NEG" if hi < 0 else "ns (cero dentro)")
        print(f"  {r['estrategia']:<30s} y={r['yield_pct']*100:+.2f}% "
              f"CI95_Bonf=[{lo*100:+.2f}%, {hi*100:+.2f}%]  {sig}")
        idx += 1

    # Test V0_puro vs RANDOM
    v0 = next(r for r in results if r["estrategia"] == "V0_puro_argmax")
    rnd = next(r for r in results if r["estrategia"] == "RANDOM_1_3")
    diff = v0["yield_pct"] - rnd["yield_pct"]
    se_diff = math.sqrt(v0["se"] ** 2 + rnd["se"] ** 2)
    z_diff = diff / se_diff if se_diff > 0 else 0
    print(f"\n=== V0_puro vs RANDOM_1_3 ===")
    print(f"  Delta yield = {diff*100:+.2f}%  SE_diff={se_diff*100:.4f}%  z={z_diff:+.3f}")
    print(f"  p_two_tailed ~ {2*(1-_norm_cdf(abs(z_diff))):.4f}")

    # Test V0_puro vs pick_MERCADO
    pm = next(r for r in results if r["estrategia"] == "pick_MERCADO_favorito")
    diff2 = v0["yield_pct"] - pm["yield_pct"]
    se_diff2 = math.sqrt(v0["se"] ** 2 + pm["se"] ** 2)
    z_diff2 = diff2 / se_diff2 if se_diff2 > 0 else 0
    print(f"\n=== V0_puro vs pick_MERCADO_favorito ===")
    print(f"  Delta yield = {diff2*100:+.2f}%  SE_diff={se_diff2*100:.4f}%  z={z_diff2:+.3f}")
    print(f"  p_two_tailed ~ {2*(1-_norm_cdf(abs(z_diff2))):.4f}")

    # ----- VEREDICTO -----
    sig_pos = [r for r in results if r["N"] > 0 and r["ci_lo_bonf"] is not None and r["ci_lo_bonf"] > 0]
    print("\n" + "=" * 70)
    print("VEREDICTO")
    print("=" * 70)
    if sig_pos:
        print(f"Estrategias con CI95_Bonferroni > 0: {len(sig_pos)}")
        for r in sig_pos:
            print(f"  - {r['estrategia']}: yield={r['yield_pct']*100:+.2f}% "
                  f"CI=[{r['ci_lo_bonf']*100:+.2f}%, {r['ci_hi_bonf']*100:+.2f}%]")
    else:
        print("NINGUNA estrategia con CI95_Bonferroni > 0.")
        print("=> NO HAY EDGE ESTADISTICAMENTE SIGNIFICATIVO sobre N expandido.")

    # Persist JSON
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    out = dict(
        sesion=SESION_ID,
        run_at=datetime.now().isoformat(timespec="seconds"),
        n_universo=n_total,
        ligas=dict(ligas),
        anos=dict(yrs),
        outcome=dict(outc),
        m_bonferroni=m,
        z_bonferroni=z_bonf,
        estrategias=results,
        v0_vs_random=dict(delta=diff, se=se_diff, z=z_diff),
        v0_vs_mercado=dict(delta=diff2, se=se_diff2, z=z_diff2),
        veredicto=("CON_EDGE" if sig_pos else "SIN_EDGE_BONFERRONI"),
        sig_pos=[r["estrategia"] for r in sig_pos],
    )
    OUT_JSON.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"\nJSON persistido: {OUT_JSON}")


def _norm_cdf(x):
    """Approximation Phi(x). Abramowitz-Stegun."""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


if __name__ == "__main__":
    main()
