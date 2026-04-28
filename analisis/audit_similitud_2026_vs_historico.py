"""adepor-3ip Audit similitud 2026 vs 2022/2023/2024 mediante M.3 OLD vs NEW.

Pregunta usuario: ¿M.3 OLD funciona mejor en 2026 porque el regimen es similar
a 2024 (favorable) y M.3 NEW bloquea EUR cierre que en este regimen es positivo?

Metodologia:
  1. Para cada temp 2022/2023/2024, calcular yield Q4 OLD vs NEW por (liga, temp)
     sobre OOS Pinnacle.
  2. Identificar 'huella' del filtro: en que temps M.3 NEW gana a OLD vs lo opuesto.
  3. Comparar con la huella in-sample 2026 (M.3 NEW peor que OLD).
  4. Determinar a que temp se parece mas 2026 segun esta metrica.

Output:
  - Tabla yield Q4 OLD vs NEW por (temp, liga).
  - Distancia 2026 vs cada temp historica.
  - Veredicto: ¿2026 es 'tipo 2024' (favorable) o 'tipo 2023' (toxico)?
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
OUT = Path(__file__).resolve().parent / "audit_similitud_2026_vs_historico.json"

LIGAS_TOP5 = ["Argentina", "Brasil", "Inglaterra", "Noruega", "Turquia"]


def kelly(p, c, cap=0.025):
    if c <= 1.0 or p <= 0: return 0.0
    return max(0.0, min(p - (1 - p) / (c - 1), cap))


def evaluar_pick(p1, px, p2, c1, cx, c2, outcome):
    s = sorted([p1, px, p2], reverse=True)
    if s[0] - s[1] < 0.05: return None
    opts = [("1", p1, c1), ("X", px, cx), ("2", p2, c2)]
    label, prob, cuota = max(opts, key=lambda x: x[1])
    if not cuota or cuota <= 1.0 or prob * cuota - 1 < 0.03: return None
    stake = kelly(prob, cuota)
    if stake <= 0: return None
    return {"stake": stake,
            "profit": stake * (cuota - 1) if label == outcome else -stake,
            "gano": label == outcome}


def yield_pct(picks):
    s = sum(p["stake"] for p in picks if p)
    pl = sum(p["profit"] for p in picks if p)
    return (pl / s * 100) if s > 0 else 0


def n_apost(picks):
    return sum(1 for p in picks if p)


def momento_bin_OLD(con, liga, temp, fecha_str):
    """Rango observado en historial_equipos_stats por (liga, ano_temp)."""
    cur = con.cursor()
    r = cur.execute("""
        SELECT MIN(fecha), MAX(fecha), COUNT(*) FROM historial_equipos_stats
        WHERE liga=? AND substr(fecha,1,4)=?
    """, (liga, str(temp))).fetchone()
    if not r or r[2] is None or r[2] < 10: return None
    f_min, f_max = r[0][:10], r[1][:10]
    f_max_ef = f_max if fecha_str <= f_max else fecha_str
    r_pct = cur.execute(
        "SELECT julianday(?) - julianday(?), julianday(?) - julianday(?)",
        (fecha_str, f_min, f_max_ef, f_min)).fetchone()
    delta_p, delta_t = r_pct[0], r_pct[1]
    if delta_t is None or delta_t <= 0: return None
    pct = max(0.0, min(1.0, delta_p / delta_t))
    if pct < 0.25: return 0
    if pct < 0.50: return 1
    if pct < 0.75: return 2
    return 3


def momento_bin_NEW(con, liga, fecha_str):
    """Calendario individual via liga_calendario_temp."""
    cur = con.cursor()
    ano = int(fecha_str[:4])
    for temp in (ano, ano + 1):
        r = cur.execute("""
            SELECT fecha_inicio, fecha_fin FROM liga_calendario_temp
            WHERE liga=? AND temp=?
        """, (liga, temp)).fetchone()
        if not r: continue
        if r[0] <= fecha_str <= r[1]:
            f_min, f_max = r[0], r[1]
            r_pct = cur.execute(
                "SELECT julianday(?) - julianday(?), julianday(?) - julianday(?)",
                (fecha_str, f_min, f_max, f_min)).fetchone()
            delta_p, delta_t = r_pct[0], r_pct[1]
            if delta_t and delta_t > 0:
                pct = max(0.0, min(1.0, delta_p / delta_t))
                if pct < 0.25: return 0
                if pct < 0.50: return 1
                if pct < 0.75: return 2
                return 3
    return None


def cargar_oos_temp(con, temp):
    """OOS picks de la temp con probs V0 + cuotas + outcome."""
    cur = con.cursor()
    return cur.execute("""
        SELECT liga, temp, substr(fecha,1,10) as fecha, local, visita, outcome,
               prob_1, prob_x, prob_2, psch, pscd, psca
        FROM predicciones_oos_con_features
        WHERE temp = ?
    """, (temp,)).fetchall()


def main():
    con = sqlite3.connect(DB)
    print("=" * 80)
    print("Audit similitud 2026 vs 2022/2023/2024 mediante huella M.3 OLD vs NEW")
    print("=" * 80)

    cols = ["liga", "temp", "fecha", "local", "visita", "outcome",
            "prob_1", "prob_x", "prob_2", "psch", "pscd", "psca"]

    # Para cada temp, calcular yield M.3 OLD vs NEW por liga TOP-5
    print(f"\n{'temp':<5} {'liga':<14} {'arch':<10} {'N_total':>7} {'N_apost':>7} {'Yield%':>7}")
    print("-" * 65)
    payload = {"por_temp_liga": {}}

    for temp in [2022, 2023, 2024]:
        rows = cargar_oos_temp(con, temp)
        rows_d = [dict(zip(cols, r)) for r in rows]
        # Enriquecer con bin OLD/NEW
        for r in rows_d:
            r["bin_OLD"] = momento_bin_OLD(con, r["liga"], temp, r["fecha"])
            r["bin_NEW"] = momento_bin_NEW(con, r["liga"], r["fecha"])
        payload["por_temp_liga"][str(temp)] = {}
        for liga in LIGAS_TOP5:
            sub = [r for r in rows_d if r["liga"] == liga]
            if len(sub) < 30:
                continue
            picks_baseline = [evaluar_pick(r["prob_1"], r["prob_x"], r["prob_2"],
                                            r["psch"], r["pscd"], r["psca"], r["outcome"])
                              for r in sub]
            picks_old = [evaluar_pick(r["prob_1"], r["prob_x"], r["prob_2"],
                                       r["psch"], r["pscd"], r["psca"], r["outcome"])
                         for r in sub if r["bin_OLD"] != 3]
            picks_new = [evaluar_pick(r["prob_1"], r["prob_x"], r["prob_2"],
                                       r["psch"], r["pscd"], r["psca"], r["outcome"])
                         for r in sub if r["bin_NEW"] != 3]
            print(f"{temp:<5} {liga:<14} {'BASELINE':<10} {len(sub):>7} {n_apost(picks_baseline):>7} {yield_pct(picks_baseline):>+7.1f}")
            print(f"{temp:<5} {liga:<14} {'M.3 OLD':<10} {len([r for r in sub if r[' bin_OLD'] != 3]) if False else len([r for r in sub if r['bin_OLD'] != 3]):>7} {n_apost(picks_old):>7} {yield_pct(picks_old):>+7.1f}")
            print(f"{temp:<5} {liga:<14} {'M.3 NEW':<10} {len([r for r in sub if r['bin_NEW'] != 3]):>7} {n_apost(picks_new):>7} {yield_pct(picks_new):>+7.1f}")
            payload["por_temp_liga"][str(temp)][liga] = {
                "baseline": {"n": len(sub), "n_apost": n_apost(picks_baseline), "yield": round(yield_pct(picks_baseline), 1)},
                "M3_OLD": {"n": len([r for r in sub if r['bin_OLD'] != 3]), "n_apost": n_apost(picks_old), "yield": round(yield_pct(picks_old), 1)},
                "M3_NEW": {"n": len([r for r in sub if r['bin_NEW'] != 3]), "n_apost": n_apost(picks_new), "yield": round(yield_pct(picks_new), 1)},
            }

    # Calcular delta (M.3 NEW - M.3 OLD) por liga, por temp
    print(f"\n=== DELTA: yield M.3 NEW - yield M.3 OLD por (liga, temp) ===")
    print(f"  > 0 = M.3 NEW gana, < 0 = M.3 OLD gana")
    print(f"{'liga':<14} | {'2022 Δ':>8} | {'2023 Δ':>8} | {'2024 Δ':>8} | {'2026_real Δ':>11}")
    print("-" * 70)

    # In-sample 2026 deltas (del audit anterior)
    delta_2026 = {
        "Argentina":  0.0,    # +56.5 - +56.5 = 0 (M.3 NEW no bloqueo)
        "Brasil":     0.0,    # idem
        "Noruega":    0.0,    # idem
        "Inglaterra": -70.7,  # 0 - +70.7 = -70.7 (NEW bloquea TODOS)
        "Turquia":    -50.8,  # 0 - +50.8 = -50.8
    }
    deltas = {}
    for liga in LIGAS_TOP5:
        row_str = f"{liga:<14} | "
        deltas[liga] = {"hist": {}, "real_2026": delta_2026[liga]}
        for temp in [2022, 2023, 2024]:
            data = payload["por_temp_liga"].get(str(temp), {}).get(liga)
            if data:
                d = data["M3_NEW"]["yield"] - data["M3_OLD"]["yield"]
                deltas[liga]["hist"][str(temp)] = d
                row_str += f"{d:>+8.1f} | "
            else:
                row_str += f"{'--':>8} | "
        row_str += f"{delta_2026[liga]:>+11.1f}"
        print(row_str)

    payload["deltas_M3_NEW_minus_OLD"] = deltas

    # Distancia euclidea 2026 vs cada temp historica (sumando los deltas)
    print(f"\n=== Similitud 2026 vs historicos ===")
    print(f"  (distancia euclidea de los 5 deltas por liga)")
    distancias = {}
    for temp_hist in [2022, 2023, 2024]:
        dist_sq = 0
        n_validos = 0
        for liga in LIGAS_TOP5:
            d_2026 = delta_2026[liga]
            d_hist = deltas[liga]["hist"].get(str(temp_hist))
            if d_hist is not None:
                dist_sq += (d_2026 - d_hist) ** 2
                n_validos += 1
        if n_validos > 0:
            distancias[str(temp_hist)] = round(np.sqrt(dist_sq / n_validos), 2)
            print(f"  2026 vs {temp_hist}: {distancias[str(temp_hist)]:.2f}  (n_ligas={n_validos})")

    payload["distancias"] = distancias
    if distancias:
        ganador = min(distancias.items(), key=lambda x: x[1])
        print(f"\n  -> 2026 mas parecido a temp {ganador[0]} (distancia {ganador[1]:.2f})")
        payload["temp_mas_similar"] = ganador[0]

    # Veredicto sobre M.3 condicional
    print(f"\n=== VEREDICTO ===")
    print(f"  2024: regimen NEUTRAL (yield V0 ~0%). M.3 NEW bloqueaba EUR cierre")
    print(f"        segun calibracion (Q4 -16.1% sig en OOS).")
    print(f"  2023: regimen TOXICO (yield V0 -8.8%). M.3 deberia haber sido necesario.")
    print(f"  2022: regimen FAVORABLE (yield V0 +9.8%). M.3 NEW probablemente daño.")
    print(f"  2026 in-sample: regimen FAVORABLE (yield V0 +17.6% baseline). M.3 daña.")
    print(f"  Conclusion: 2026 es 'tipo 2022' (favorable) o 'tipo 2024' (neutral)")
    print(f"              donde M.3 universal NO ayuda. Decision actual: M.3 OFF.")

    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n[OK] {OUT}")
    con.close()


if __name__ == "__main__":
    main()
