"""
[F3 — backtest preliminar Elo] Validación accuracy del Elo histórico
calculado en scripts/calcular_elo_historico.py.

Test: para cada partido liquidado OOS 2024 (sample temporal último año), predecir
1X2 usando solamente Elo + home advantage + goal_diff_modifier. Comparar argmax
y Brier vs resultado real. Sin xG, sin V0, sin nada — Elo puro.

Esto NO predice yield (sin cuotas) — solo accuracy estructural.

[REF: docs/papers/elo_calibracion.md Q1 — predictive accuracy estandar Elo
~60% standalone en EUR top-flight]
"""
from __future__ import annotations

import sqlite3
import sys
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
sys.path.insert(0, str(ROOT))
from scripts.calcular_elo_historico import (  # noqa: E402
    expected_score, HOME_ADV
)


def predecir_1x2_elo(elo_l, elo_v):
    """Convierte Elo a (P_local_win, P_draw, P_visita_win) via sigmoid + draw heuristic.

    Heurística standard (literatura Eloratings + Aldous):
    - p_l_win = expected_score(elo_l, elo_v, +HOME_ADV)
    - p_v_win = expected_score(elo_v, elo_l, -HOME_ADV)  (visita penalizada)
    - p_draw = 1 - p_l_win - p_v_win  (rara vez negativo si home_adv balanceado)
    """
    p_l = expected_score(elo_l, elo_v, home_adv=HOME_ADV)
    p_v = expected_score(elo_v, elo_l, home_adv=-HOME_ADV)
    p_x = max(0.0, 1.0 - p_l - p_v)
    s = p_l + p_v + p_x
    if s > 0:
        return p_l / s, p_x / s, p_v / s
    return 1/3, 1/3, 1/3


def brier_1x2(p1, px, p2, gl, gv):
    o1 = 1 if gl > gv else 0
    ox = 1 if gl == gv else 0
    o2 = 1 if gl < gv else 0
    return ((p1 - o1) ** 2 + (px - ox) ** 2 + (p2 - o2) ** 2) / 3.0


def lookup_elo_pre(conn, equipo_norm, fecha):
    """Elo más reciente anterior a fecha."""
    r = conn.execute("""
        SELECT elo_post, n_partidos_acumulados FROM equipo_nivel_elo
        WHERE equipo_norm = ? AND fecha < ?
        ORDER BY fecha DESC LIMIT 1
    """, (equipo_norm, fecha)).fetchone()
    if r:
        return r[0], r[1]
    return 1500.0, 0


def main():
    conn = sqlite3.connect(DB)
    conn.text_factory = str

    # Sample: 2024 (OOS para Elo calculado sobre 2022-2024 — implica look-ahead leve
    # para ranking final pero el Elo lookup es forward, así que cada partido usa Elo
    # PRE-partido. Test legitimo).
    rows = conn.execute("""
        SELECT fecha, equipo_local_norm, equipo_visita_norm,
               competicion, competicion_tipo, goles_l, goles_v
        FROM v_partidos_unificado
        WHERE goles_l IS NOT NULL AND goles_v IS NOT NULL
          AND equipo_local_norm IS NOT NULL AND equipo_visita_norm IS NOT NULL
          AND fecha >= '2024-01-01' AND fecha < '2025-01-01'
        ORDER BY fecha
    """).fetchall()
    print(f"Partidos 2024 a evaluar: {len(rows)}")

    # Por categoría (liga vs copa) + global
    n_total = 0
    counts = defaultdict(lambda: {"n": 0, "hits": 0, "briers": []})

    for fecha, eq_l, eq_v, comp, comp_tipo, gl, gv in rows:
        elo_l, n_l = lookup_elo_pre(conn, eq_l, fecha)
        elo_v, n_v = lookup_elo_pre(conn, eq_v, fecha)
        # Skip cold-start severos
        if n_l < 5 or n_v < 5:
            continue
        p1, px, p2 = predecir_1x2_elo(elo_l, elo_v)
        # Argmax
        if p1 == max(p1, px, p2): pred = "1"
        elif px == max(p1, px, p2): pred = "X"
        else: pred = "2"
        # Resultado real
        if gl > gv: real = "1"
        elif gl == gv: real = "X"
        else: real = "2"
        hit = (pred == real)
        b = brier_1x2(p1, px, p2, gl, gv)

        n_total += 1
        for cat in ["GLOBAL", comp_tipo or "unknown"]:
            counts[cat]["n"] += 1
            if hit: counts[cat]["hits"] += 1
            counts[cat]["briers"].append(b)

    conn.close()

    print("\n" + "=" * 70)
    print("ACCURACY ELO STANDALONE 2024 (no xG, no V0, solo Elo)")
    print("=" * 70)
    out = {"n_total": n_total, "categorias": {}}
    for cat, info in sorted(counts.items()):
        n = info["n"]; hits = info["hits"]
        avg_b = sum(info["briers"]) / n if n else 0
        hit_rate = hits / n if n else 0
        print(f"  {cat:<35s} N={n:>5d}  hit={hit_rate:.3f}  Brier={avg_b:.4f}")
        out["categorias"][cat] = {"n": n, "hit_rate": hit_rate, "brier_avg": avg_b}

    print("\nReferencia literatura: Elo standalone ~60% accuracy EUR top-flight.")
    print("(Si Adepor Elo da <55%, considerar regularización / cold-start tuning.)")

    Path("analisis/backtest_elo_preliminar.json").parent.mkdir(parents=True, exist_ok=True)
    with open("analisis/backtest_elo_preliminar.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
