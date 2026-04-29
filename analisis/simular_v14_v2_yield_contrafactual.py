"""
[adepor-141 V14 v2 SHADOW yield simulación] Backtest contrafactual sobre los
1,812 partidos copa test 2025 que V14 v2 cubre.

LIMITACIONES:
- Sin cuotas reales para copas 2025 (bead adepor-4tb BLOQUEADO API Pro).
- Cuotas implícitas con margen de mercado típico copa 6% (sweep alternativo 4-8%).
- Stake Kelly fractional con parámetros productivos del motor:
    fraccion_kelly = 0.5
    max_kelly_pct_normal = 0.025
    bankroll = 280,000 ARS
- Filtros V5.1 aplicados (floor_prob_min, margen_predictivo_1x2, umbral_ev_1x2).
- ESTO NO ES YIELD REAL — es una proyección de qué pasaría SI el mercado tuviera
  margen 6% y nuestras predicciones V14 v2 estuvieran bien calibradas.

NO promueve nada. Solo reporta.
"""
from __future__ import annotations
import sqlite3
import sys
import json
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
sys.path.insert(0, str(ROOT))

from scripts.calibrar_motor_copa_v14_v2 import build_features_no_xg, brier_multinomial


def fit_v14_v2(conn):
    X_train, y_train, _ = build_features_no_xg(conn, "2022-01-01", "2025-01-01", min_n=1)
    scaler = StandardScaler()
    Xtr = scaler.fit_transform(X_train)
    model = LogisticRegression(solver='lbfgs', C=1.0, max_iter=2000)
    model.fit(Xtr, y_train)
    return model, scaler


def _probs_elo_baseline(X):
    """Baseline mercado-débil: probabilidades 1X2 derivadas solo del delta_elo
    (idx 0 en X de V14 v2). Brier ~0.3542 (peor que V14 v2 0.2918). Asumimos
    mercado eficiente *al nivel de Elo* + margen — V14 v2 captura el alpha sobre Elo."""
    from scripts.calcular_elo_historico import expected_score, HOME_ADV
    out = np.zeros((len(X), 3))
    for i, row in enumerate(X):
        delta_elo = row[0]
        elo_l = 1500 + delta_elo / 2
        elo_v = 1500 - delta_elo / 2
        p_l = expected_score(elo_l, elo_v, home_adv=HOME_ADV)
        p_v = expected_score(elo_v, elo_l, home_adv=-HOME_ADV)
        p_x = max(0.0, 1.0 - p_l - p_v)
        s = p_l + p_v + p_x
        out[i] = (p_l/s, p_x/s, p_v/s) if s > 0 else (1/3, 1/3, 1/3)
    return out


def simular(conn, model, scaler, margen_mercado=0.06, bankroll=280000.0,
            modelo_mercado="elo", periodo="oos_2025"):
    """Simula yield + volumen con cuotas implícitas + margen.

    periodo:
      - 'oos_2025'  → test 2025 (out-of-sample, fechas '2025-01-01' a '2026-01-01')
      - 'in_sample' → train 2022-2024 (in-sample, sanity check)

    modelo_mercado:
      - 'elo'  → cuotas derivadas de Elo-solo + margen. V14 v2 captura alpha sobre Elo.
      - 'self' → cuotas derivadas de V14 v2 + margen (mercado eficiente, peor caso).
    """
    if periodo == "in_sample":
        X_test, y_test, meta = build_features_no_xg(conn, "2022-01-01", "2025-01-01", min_n=1)
    else:
        X_test, y_test, meta = build_features_no_xg(conn, "2025-01-01", "2026-01-01", min_n=1)
    Xte_s = scaler.transform(X_test)
    probs = model.predict_proba(Xte_s)  # (N, 3) — V14 v2

    if modelo_mercado == "elo":
        probs_mercado = _probs_elo_baseline(X_test)
    else:
        probs_mercado = probs.copy()

    # Filtros V5.1
    FLOOR_PROB = 0.40
    MARGEN_PRED = 0.05
    UMBRAL_EV = 0.03
    KELLY_FRAC = 0.5
    KELLY_CAP = 0.025

    classes = ["LOCAL", "DRAW", "VISITA"]
    picks = []  # (fecha, eq_l, eq_v, comp_tipo, pick_class, p_modelo, cuota, ev, stake, hit, pnl)

    for i in range(len(X_test)):
        fecha, eq_l, eq_v, comp_tipo, gl, gv = meta[i]
        outcome = int(y_test[i])
        for k in range(3):
            p_modelo = float(probs[i][k])
            p_mkt = float(probs_mercado[i][k])
            # Cuota mercado: prob mercado * (1 + margen) → mercado siempre paga menos
            # de lo "fair" para extraer margen. cuota = 1 / (p_mkt * (1 + margen)).
            cuota = 1.0 / (p_mkt * (1.0 + margen_mercado)) if p_mkt > 0 else 999.0
            p_implicita = 1.0 / cuota
            margen_pred = p_modelo - p_implicita
            ev = p_modelo * cuota - 1.0

            apostable = (
                p_modelo >= FLOOR_PROB
                and margen_pred >= MARGEN_PRED
                and ev >= UMBRAL_EV
            )
            if not apostable:
                continue

            # Kelly fractional
            b = cuota - 1.0
            p = p_modelo
            q = 1.0 - p
            kelly_full = (b * p - q) / b if b > 0 else 0.0
            kelly_pct = max(0.0, kelly_full * KELLY_FRAC)
            kelly_pct = min(kelly_pct, KELLY_CAP)
            stake = bankroll * kelly_pct

            hit = (outcome == k)
            pnl = stake * (cuota - 1.0) if hit else -stake
            picks.append({
                "fecha": fecha, "eq_l": eq_l, "eq_v": eq_v,
                "comp_tipo": comp_tipo, "pick_class": classes[k],
                "p_modelo": round(p_modelo, 4),
                "cuota": round(cuota, 3),
                "margen_pred": round(margen_pred, 4),
                "ev": round(ev, 4),
                "kelly_pct": round(kelly_pct, 4),
                "stake": round(stake, 2),
                "hit": hit,
                "pnl": round(pnl, 2),
            })

    # Agregados
    n_partidos = len(X_test)
    n_picks = len(picks)
    if n_picks == 0:
        return {
            "margen_mercado": margen_mercado,
            "n_partidos_test": n_partidos,
            "n_picks": 0,
            "nota": "0 picks — V14 v2 no genera EV+ sobre cuotas con margen igual al modelo.",
        }
    stake_total = sum(p["stake"] for p in picks)
    pnl_total = sum(p["pnl"] for p in picks)
    n_hits = sum(1 for p in picks if p["hit"])
    yield_bruto = pnl_total / stake_total if stake_total > 0 else 0.0
    hit_rate = n_hits / n_picks
    avg_stake = stake_total / n_picks

    # Por competición
    by_comp = {}
    for p in picks:
        c = p["comp_tipo"]
        by_comp.setdefault(c, {"n": 0, "stake": 0.0, "pnl": 0.0, "hits": 0})
        by_comp[c]["n"] += 1
        by_comp[c]["stake"] += p["stake"]
        by_comp[c]["pnl"] += p["pnl"]
        by_comp[c]["hits"] += int(p["hit"])
    for c, agg in by_comp.items():
        agg["yield"] = round(agg["pnl"] / agg["stake"], 4) if agg["stake"] > 0 else 0
        agg["hit_rate"] = round(agg["hits"] / agg["n"], 3) if agg["n"] > 0 else 0
        agg["pnl"] = round(agg["pnl"], 2)
        agg["stake"] = round(agg["stake"], 2)

    return {
        "margen_mercado": margen_mercado,
        "n_partidos_test": n_partidos,
        "n_picks": n_picks,
        "tasa_picks_pct": round(100.0 * n_picks / n_partidos, 2),
        "stake_total": round(stake_total, 2),
        "stake_promedio": round(avg_stake, 2),
        "stake_pct_bankroll": round(100.0 * avg_stake / bankroll, 3),
        "pnl_total": round(pnl_total, 2),
        "yield_bruto_pct": round(100.0 * yield_bruto, 2),
        "hit_rate_picks": round(hit_rate, 3),
        "n_hits": n_hits,
        "by_comp_tipo": by_comp,
    }


def main():
    conn = sqlite3.connect(DB); conn.text_factory = str
    print("=== Fit V14 v2 sobre train 2022-2024 ===")
    model, scaler = fit_v14_v2(conn)

    print("\n=== ESCENARIO 1: mercado = Elo-solo + margen (V14 v2 captura alpha sobre Elo) ===")
    print(f"{'margen':>7} | {'n_picks':>8} | {'%partidos':>9} | {'avg_stake':>10} | {'%bankroll':>9} | {'yield':>8} | {'hit_rate':>9} | {'pnl_total':>11}")
    print("-" * 100)
    sweep = []
    for margen in [0.04, 0.05, 0.06, 0.07, 0.08, 0.10]:
        r = simular(conn, model, scaler, margen_mercado=margen, modelo_mercado="elo")
        if r["n_picks"] == 0:
            print(f"{margen*100:>6.0f}% | 0 picks")
            sweep.append(r); continue
        print(f"{margen*100:>6.0f}% | {r['n_picks']:>8d} | {r['tasa_picks_pct']:>8.2f}% | "
              f"{r['stake_promedio']:>10.0f} | {r['stake_pct_bankroll']:>8.3f}% | "
              f"{r['yield_bruto_pct']:>+7.2f}% | {r['hit_rate_picks']:>9.3f} | {r['pnl_total']:>+11.0f}")
        sweep.append(r)

    print("\n=== ESCENARIO 2: mercado eficiente = V14 v2 + margen (peor caso, alpha=0) ===")
    print(f"{'margen':>7} | {'n_picks':>8}")
    for margen in [0.04, 0.06, 0.08, 0.10]:
        r2 = simular(conn, model, scaler, margen_mercado=margen, modelo_mercado="self")
        print(f"{margen*100:>6.0f}% | {r2['n_picks']:>8d}")

    print("\n=== Detalle por competition_tipo (Esc 1, margen 6% — base) ===")
    base = next(r for r in sweep if r["margen_mercado"] == 0.06)
    if base["n_picks"] > 0:
        for ct, agg in base["by_comp_tipo"].items():
            print(f"  {ct:25s} N={agg['n']:>4d} stake={agg['stake']:>10.0f} "
                  f"pnl={agg['pnl']:>+10.0f} yield={agg['yield']*100:>+6.2f}% hit={agg['hit_rate']:.3f}")

    # Proyección anual: 1,812 partidos test = ~1 año copas. Picks anuales ≈ n_picks.
    if base["n_picks"] > 0:
        print(f"\n=== Proyección anualizada (escenario base 6%) ===")
        print(f"  Volumen anual:    ~{base['n_picks']} picks")
        print(f"  Volumen mensual:  ~{base['n_picks']/12:.0f} picks/mes")
        print(f"  Stake anual:      ~{base['stake_total']:,.0f} ARS ({base['stake_total']/280000*100:.0f}% del bankroll, exposicion neta)")
        print(f"  PnL anual proy:   ~{base['pnl_total']:+,.0f} ARS ({base['pnl_total']/280000*100:+.1f}% del bankroll)")

    print("\n" + "=" * 100)
    print("=== ESCENARIO 1 IN-SAMPLE (train 2022-2024) — sanity check overfit ===")
    print("=" * 100)
    print(f"{'margen':>7} | {'n_picks':>8} | {'%partidos':>9} | {'yield':>8} | {'hit_rate':>9} | {'pnl_total':>11}")
    print("-" * 80)
    sweep_in = []
    for margen in [0.04, 0.06, 0.08, 0.10]:
        r = simular(conn, model, scaler, margen_mercado=margen, modelo_mercado="elo",
                    periodo="in_sample")
        if r["n_picks"] == 0:
            print(f"{margen*100:>6.0f}% | 0 picks")
            sweep_in.append(r); continue
        print(f"{margen*100:>6.0f}% | {r['n_picks']:>8d} | {r['tasa_picks_pct']:>8.2f}% | "
              f"{r['yield_bruto_pct']:>+7.2f}% | {r['hit_rate_picks']:>9.3f} | {r['pnl_total']:>+11.0f}")
        sweep_in.append(r)

    print("\n=== Comparativa OOS vs IN-SAMPLE (margen 6%) ===")
    oos_6 = next(r for r in sweep if r["margen_mercado"] == 0.06)
    in_6 = next(r for r in sweep_in if r["margen_mercado"] == 0.06)
    print(f"  OOS 2025:    yield={oos_6['yield_bruto_pct']:>+6.2f}%  hit={oos_6['hit_rate_picks']:.3f}  N={oos_6['n_picks']}")
    if in_6["n_picks"] > 0:
        print(f"  IN-SAMPLE:   yield={in_6['yield_bruto_pct']:>+6.2f}%  hit={in_6['hit_rate_picks']:.3f}  N={in_6['n_picks']}")
        delta = in_6['yield_bruto_pct'] - oos_6['yield_bruto_pct']
        print(f"  Delta IS-OOS yield: {delta:+.2f}pp ({'overfit' if abs(delta)>5 else 'consistente'})")

    out = ROOT / "analisis" / "simular_v14_v2_yield_contrafactual.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"sweep": sweep, "params": {
            "floor_prob_min": 0.40, "margen_predictivo_1x2": 0.05,
            "umbral_ev_1x2": 0.03, "fraccion_kelly": 0.5,
            "max_kelly_pct": 0.025, "bankroll": 280000.0,
        }}, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nReporte: {out}")
    conn.close()


if __name__ == "__main__":
    main()
