"""
[F3 — backtest Elo desglosado] Hit rate + Brier por (año, país) sobre todos
los partidos liquidados 2022-2026.

Categorías:
- 2022, 2023, 2024 = OOS (Elo se calibró con esos partidos pero predicción es
  forward — usa Elo PRE-partido, sin leakage temporal).
- 2026 = in-sample (datos recientes — el histórico Elo cubre menos del 2026).

Por país: filtra por pais_origen del partido. Para liga regular esto coincide
con la liga; para copas es el origen del torneo (ej Libertadores -> Internacional).

[REF: docs/papers/elo_calibracion.md Q3 — performance esperada varia por liga
debido a cobertura desigual del histórico].
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
sys.path.insert(0, str(ROOT))
from scripts.calcular_elo_historico import expected_score, HOME_ADV  # noqa: E402


def predecir_1x2_elo(elo_l, elo_v):
    p_l = expected_score(elo_l, elo_v, home_adv=HOME_ADV)
    p_v = expected_score(elo_v, elo_l, home_adv=-HOME_ADV)
    p_x = max(0.0, 1.0 - p_l - p_v)
    s = p_l + p_v + p_x
    return (p_l/s, p_x/s, p_v/s) if s > 0 else (1/3, 1/3, 1/3)


def brier_1x2(p1, px, p2, gl, gv):
    o1 = 1 if gl > gv else 0
    ox = 1 if gl == gv else 0
    o2 = 1 if gl < gv else 0
    return ((p1 - o1) ** 2 + (px - ox) ** 2 + (p2 - o2) ** 2) / 3.0


def lookup_elo_pre(conn, equipo_norm, fecha):
    r = conn.execute("""
        SELECT elo_post, n_partidos_acumulados FROM equipo_nivel_elo
        WHERE equipo_norm = ? AND fecha < ?
        ORDER BY fecha DESC LIMIT 1
    """, (equipo_norm, fecha)).fetchone()
    return (r[0], r[1]) if r else (1500.0, 0)


def main():
    conn = sqlite3.connect(DB)
    conn.text_factory = str

    # Cargar TODOS los liquidados 2022-2026
    rows = conn.execute("""
        SELECT fecha, equipo_local_norm, equipo_visita_norm,
               pais_origen, competicion_tipo, goles_l, goles_v
        FROM v_partidos_unificado
        WHERE goles_l IS NOT NULL AND goles_v IS NOT NULL
          AND equipo_local_norm IS NOT NULL AND equipo_visita_norm IS NOT NULL
          AND fecha >= '2022-01-01' AND fecha < '2027-01-01'
        ORDER BY fecha
    """).fetchall()
    print(f"Partidos 2022-2026 liquidados: {len(rows)}\n")

    # Agrupar por (año, pais_origen, oos_o_in_sample)
    counts = defaultdict(lambda: {"n": 0, "hits": 0, "briers": []})

    for fecha, eq_l, eq_v, pais, comp_tipo, gl, gv in rows:
        elo_l, n_l = lookup_elo_pre(conn, eq_l, fecha)
        elo_v, n_v = lookup_elo_pre(conn, eq_v, fecha)
        if n_l < 5 or n_v < 5:
            continue  # cold-start severo
        p1, px, p2 = predecir_1x2_elo(elo_l, elo_v)
        pred = "1" if p1 == max(p1, px, p2) else ("X" if px == max(p1, px, p2) else "2")
        real = "1" if gl > gv else ("X" if gl == gv else "2")
        hit = (pred == real)
        b = brier_1x2(p1, px, p2, gl, gv)

        anio = int(fecha[:4])
        regimen = "in_sample" if anio == 2026 else "OOS"
        # Pais "Internacional" si copas, sino el pais
        pais_norm = pais if pais else "(unknown)"

        for key in [
            ("AÑO", str(anio)),
            ("PAIS", pais_norm),
            ("REGIMEN", regimen),
            ("AÑO_x_PAIS", f"{anio}_{pais_norm}"),
            ("AÑO_x_REGIMEN", f"{anio}_{regimen}"),
            ("PAIS_x_REGIMEN", f"{pais_norm}_{regimen}"),
            ("TIPO", comp_tipo or "unknown"),
        ]:
            counts[key]["n"] += 1
            if hit: counts[key]["hits"] += 1
            counts[key]["briers"].append(b)

    conn.close()

    def _fmt_section(seccion, ordenar_por="key"):
        items = [(k[1], v) for k, v in counts.items() if k[0] == seccion]
        if not items:
            return
        if ordenar_por == "n":
            items.sort(key=lambda x: -x[1]["n"])
        else:
            items.sort(key=lambda x: x[0])
        print(f"\n{'='*70}\n{seccion}\n{'='*70}")
        print(f"  {'categoria':<25s}  {'N':>6s}  {'hit':>6s}  {'Brier':>7s}")
        for k, v in items:
            n = v["n"]
            hit = v["hits"] / n if n else 0
            br = sum(v["briers"]) / n if n else 0
            print(f"  {k:<25s}  {n:>6d}  {hit:>6.3f}  {br:>7.4f}")

    _fmt_section("AÑO")
    _fmt_section("REGIMEN")
    _fmt_section("PAIS", ordenar_por="n")
    _fmt_section("TIPO")
    _fmt_section("AÑO_x_REGIMEN")
    _fmt_section("PAIS_x_REGIMEN", ordenar_por="n")

    # Tabla detallada año x país (top 12 países por N)
    paises_top = sorted(
        [(k[1], v["n"]) for k, v in counts.items() if k[0] == "PAIS"],
        key=lambda x: -x[1]
    )[:15]
    pais_top_set = {p for p, _ in paises_top}
    print(f"\n{'='*70}\nAÑO x PAIS (top 15 paises por N)\n{'='*70}")
    print(f"  {'categoria':<35s}  {'N':>6s}  {'hit':>6s}  {'Brier':>7s}")
    items_yp = sorted(
        [(k[1], v) for k, v in counts.items() if k[0] == "AÑO_x_PAIS"],
        key=lambda x: x[0]
    )
    for k, v in items_yp:
        # k formato "2024_Argentina"
        parts = k.split("_", 1)
        if len(parts) != 2:
            continue
        anio, pais = parts
        if pais not in pais_top_set:
            continue
        n = v["n"]
        if n < 10: continue
        hit = v["hits"] / n
        br = sum(v["briers"]) / n
        print(f"  {k:<35s}  {n:>6d}  {hit:>6.3f}  {br:>7.4f}")

    # Save
    out = {
        seccion: {
            k[1]: {
                "n": v["n"],
                "hit_rate": v["hits"] / v["n"] if v["n"] else None,
                "brier_avg": sum(v["briers"]) / v["n"] if v["n"] else None,
            }
            for k, v in counts.items() if k[0] == seccion
        }
        for seccion in ["AÑO", "REGIMEN", "PAIS", "TIPO", "AÑO_x_PAIS", "AÑO_x_REGIMEN", "PAIS_x_REGIMEN"]
    }
    Path("analisis/backtest_elo_desglose.json").parent.mkdir(parents=True, exist_ok=True)
    with open("analisis/backtest_elo_desglose.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\nReporte: analisis/backtest_elo_desglose.json")


if __name__ == "__main__":
    main()
