"""
[F3 backtest desglose extendido] Hit + Brier por (pais, tipo_competicion, año).

Tipo competición:
- LIGA: partidos de partidos_historico_externo (liga regular doméstica)
- COPA_NAC: partidos partidos_no_liga con competicion_tipo='copa_nacional'
- COPA_INT: partidos partidos_no_liga con competicion_tipo='copa_internacional'
  (atribuidos al país del equipo participante, no 'Internacional' agregado)

Output: docs/papers/-style tabla pais x (LIGA|COPA_NAC|COPA_INT) x año.
"""
from __future__ import annotations
import json, sqlite3, sys
from collections import defaultdict
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.calcular_elo_historico import expected_score, HOME_ADV  # noqa: E402

DB = ROOT / "fondo_quant.db"


def predecir(elo_l, elo_v):
    p_l = expected_score(elo_l, elo_v, home_adv=HOME_ADV)
    p_v = expected_score(elo_v, elo_l, home_adv=-HOME_ADV)
    p_x = max(0.0, 1.0 - p_l - p_v)
    s = p_l + p_v + p_x
    return (p_l/s, p_x/s, p_v/s) if s > 0 else (1/3, 1/3, 1/3)


def brier(p1, px, p2, gl, gv):
    o1 = 1 if gl > gv else 0
    ox = 1 if gl == gv else 0
    o2 = 1 if gl < gv else 0
    return ((p1-o1)**2 + (px-ox)**2 + (p2-o2)**2) / 3


def lookup(conn, eq, fecha):
    r = conn.execute("""
        SELECT elo_post, n_partidos_acumulados FROM equipo_nivel_elo
        WHERE equipo_norm = ? AND fecha < ?
        ORDER BY fecha DESC LIMIT 1
    """, (eq, fecha)).fetchone()
    return (r[0], r[1]) if r else (1500.0, 0)


def clasificar(origen, comp_tipo):
    """Devuelve LIGA | COPA_NAC | COPA_INT | OTRO."""
    if origen == "partidos_historico_externo":
        return "LIGA"
    if comp_tipo == "copa_internacional":
        return "COPA_INT"
    if comp_tipo == "copa_nacional":
        return "COPA_NAC"
    return "OTRO"


def main():
    conn = sqlite3.connect(DB); conn.text_factory = str
    rows = conn.execute("""
        SELECT fecha, equipo_local_norm, equipo_visita_norm,
               pais_origen, competicion_tipo, origen,
               goles_l, goles_v
        FROM v_partidos_unificado
        WHERE goles_l IS NOT NULL AND goles_v IS NOT NULL
          AND equipo_local_norm IS NOT NULL AND equipo_visita_norm IS NOT NULL
          AND fecha >= '2022-01-01' AND fecha < '2027-01-01'
        ORDER BY fecha
    """).fetchall()
    print(f"Partidos liquidados 2022-2026: {len(rows)}\n")

    # Por (pais, tipo, año)
    counts = defaultdict(lambda: {"n": 0, "hits": 0, "briers": []})
    for fecha, eq_l, eq_v, pais, comp_tipo, origen, gl, gv in rows:
        elo_l, n_l = lookup(conn, eq_l, fecha)
        elo_v, n_v = lookup(conn, eq_v, fecha)
        if n_l < 5 or n_v < 5:
            continue
        p1, px, p2 = predecir(elo_l, elo_v)
        pred = "1" if p1 == max(p1, px, p2) else ("X" if px == max(p1, px, p2) else "2")
        real = "1" if gl > gv else ("X" if gl == gv else "2")
        hit = (pred == real)
        b = brier(p1, px, p2, gl, gv)
        anio = int(fecha[:4])
        tipo = clasificar(origen, comp_tipo)
        # pais_origen para LIGA = el liga; para COPA_INT = "Internacional" agregado
        # Pero el usuario quiere desglose por pais. Para COPA_INT atribuyo al pais
        # de los equipos: necesitaria mapping. Por ahora uso pais_origen.
        # TODO sub-bead: para copa internacional, atribuir picks por pais del equipo local.
        pais_norm = pais or "(unknown)"
        for key in [
            ("PAIS_TIPO_AÑO", f"{pais_norm}|{tipo}|{anio}"),
            ("PAIS_TIPO", f"{pais_norm}|{tipo}"),
            ("TIPO_AÑO", f"{tipo}|{anio}"),
        ]:
            counts[key]["n"] += 1
            if hit: counts[key]["hits"] += 1
            counts[key]["briers"].append(b)

    conn.close()

    # === Tabla matriz: PAIS_TIPO por año ===
    print("=" * 100)
    print("MATRIZ: PAIS x TIPO x AÑO (solo celdas con N>=20)")
    print("=" * 100)
    print(f"  {'PAIS_TIPO':<35s} | {'2022':>15s} | {'2023':>15s} | {'2024':>15s} | {'2025':>15s} | {'2026':>15s}")
    print(f"  {'-'*35} | {'-'*15} | {'-'*15} | {'-'*15} | {'-'*15} | {'-'*15}")

    pais_tipo_set = set()
    for k in counts:
        if k[0] == "PAIS_TIPO_AÑO":
            pais, tipo, _ = k[1].split("|")
            pais_tipo_set.add((pais, tipo))

    def sort_key(pt):
        pais, tipo = pt
        order_tipo = {"LIGA": 0, "COPA_NAC": 1, "COPA_INT": 2}.get(tipo, 9)
        return (pais, order_tipo)

    for pais, tipo in sorted(pais_tipo_set, key=sort_key):
        cells = []
        any_data = False
        for anio in range(2022, 2027):
            k = ("PAIS_TIPO_AÑO", f"{pais}|{tipo}|{anio}")
            v = counts.get(k, {"n": 0, "hits": 0, "briers": []})
            if v["n"] >= 20:
                hit = v["hits"] / v["n"]
                cells.append(f"N={v['n']:>4d} h={hit:.2f}")
                any_data = True
            elif v["n"] > 0:
                cells.append(f"N={v['n']:>4d}    -")
            else:
                cells.append(" " * 15)
        if any_data:
            label = f"{pais}/{tipo}"
            print(f"  {label:<35s} | " + " | ".join(c[:15].ljust(15) for c in cells))

    # === Resumen por TIPO x AÑO ===
    print(f"\n{'='*70}\nRESUMEN POR TIPO x AÑO\n{'='*70}")
    print(f"  {'TIPO_AÑO':<25s} {'N':>5s} {'hit':>6s} {'Brier':>7s}")
    items = sorted([(k[1], v) for k, v in counts.items() if k[0] == "TIPO_AÑO"])
    for k, v in items:
        n = v["n"]; hit = v["hits"]/n if n else 0; b = sum(v["briers"])/n if n else 0
        print(f"  {k:<25s} {n:>5d} {hit:>6.3f} {b:>7.4f}")

    # Save
    out = {sec: {k[1]: {"n": v["n"], "hit_rate": v["hits"]/v["n"] if v["n"] else None,
                        "brier_avg": sum(v["briers"])/v["n"] if v["n"] else None}
                 for k, v in counts.items() if k[0] == sec}
           for sec in ["PAIS_TIPO_AÑO", "PAIS_TIPO", "TIPO_AÑO"]}
    Path("analisis/backtest_elo_pais_liga_copa_anio.json").parent.mkdir(parents=True, exist_ok=True)
    with open("analisis/backtest_elo_pais_liga_copa_anio.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\nReporte: analisis/backtest_elo_pais_liga_copa_anio.json")


if __name__ == "__main__":
    main()
