"""
[adepor — audit profundo manual] Unificación whitelist de variantes display
en partidos_historico_externo + partidos_no_liga + equipo_nivel_elo.

A diferencia de fix_canonicalizacion_externos.py (heurística automática con falsos
positivos), este aplica SOLO mappings validados manualmente con conocimiento de fútbol.

Estrategia: para cada (variant_norm, variant_display) en la whitelist, UPDATE las
filas a (canon_norm, canon_display). Esto consolida ratings Elo dispersos.

[REF: docs/papers/entity_resolution_sports.md Q2 — heurísticas dominio fútbol]
"""
from __future__ import annotations
import sqlite3
import sys
import shutil
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
APPLY = "--apply" in sys.argv

# Whitelist unificación: (canon_norm, canon_display, [(variant_norm, variant_display), ...])
# Casos validados manualmente con alta confianza.
UNIFICATIONS = [
    # PSG: Paris Saint-Germain (oficial Wikipedia/ESPN cuenta UEFA)
    ("parissaintgermain", "Paris Saint-Germain", [
        ("parissg", "Paris SG"),
    ]),
    # Inter / Internazionale: dict tiene oficial='Inter' (Serie A oficial)
    ("inter", "Inter", [
        ("internazionale", "Internazionale"),
    ]),
    # Manchester City
    ("manchestercity", "Manchester City", [
        ("mancity", "Man City"),
    ]),
    # Atletico Madrid: dict tiene oficial='Atlético Madrid'
    ("atleticomadrid", "Atlético Madrid", [
        ("athmadrid", "Ath Madrid"),
    ]),
    # AFC Bournemouth: dict tiene oficial='AFC Bournemouth'
    ("afcbournemouth", "AFC Bournemouth", [
        ("bournemouth", "Bournemouth"),
        ("bournemouthfc", "Bournemouth FC"),
    ]),
    # FC St. Pauli (Alemania) - dict 'St. Pauli', pero unificar bajo dict
    ("stpauli", "St. Pauli", [
        ("fcstpauli", "FC St. Pauli"),
    ]),
    # Newell's Old Boys
    ("newellsoldboys", "Newell's Old Boys", [
        ("newells", "Newells"),
    ]),
    # Atletico-MG (Brasil) variantes
    ("atleticomg", "Atlético Mineiro", [
        ("atleticomineiro", "Atletico Mineiro"),
    ]),
    # Athletico Paranaense
    ("athleticoparanaense", "Athletico Paranaense", [
        ("athleticopr", "Athletico-PR"),
        ("atleticoparanaense", "Atletico Paranaense"),
    ]),
    # Cusco
    ("cuscofc", "Cusco FC", [
        ("cusco", "Cusco"),
    ]),
    # Carabobo
    ("carabobofc", "Carabobo FC", [
        ("carabobo", "Carabobo"),
    ]),
    # Deportivo Tachira
    ("deportivotachirafc", "Deportivo Táchira FC", [
        ("deportivotachira", "Deportivo Táchira"),
    ]),
]


def aplicar(conn, canon_norm, canon_disp, variants):
    cur = conn.cursor()
    n_phe_eq = n_pnl_eq = 0
    for var_norm, var_disp in variants:
        # phe (ht/at)
        for col_eq, col_norm in [("ht", "ht_norm"), ("at", "at_norm")]:
            cur.execute(f"""
                UPDATE partidos_historico_externo
                SET {col_eq}=?, {col_norm}=?
                WHERE {col_norm}=?
            """, (canon_disp, canon_norm, var_norm))
            n_phe_eq += cur.rowcount
        # pnl
        for col_eq, col_norm in [
            ("equipo_local", "equipo_local_norm"),
            ("equipo_visita", "equipo_visita_norm"),
        ]:
            cur.execute(f"""
                UPDATE partidos_no_liga
                SET {col_eq}=?, {col_norm}=?
                WHERE {col_norm}=?
            """, (canon_disp, canon_norm, var_norm))
            n_pnl_eq += cur.rowcount
        # equipo_nivel_elo (rebuild si APPLY tras esto)
    return n_phe_eq, n_pnl_eq


def main():
    if APPLY:
        ts = time.strftime("%Y%m%d_%H%M%S")
        snap = f"snapshots/fondo_quant_{ts}_pre_whitelist_unify.db"
        Path(snap).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(DB, snap)
        print(f"[SNAPSHOT] {snap}\n")

    conn = sqlite3.connect(DB); conn.text_factory = str

    print(f"{'APPLY' if APPLY else 'DRY-RUN'} unificación whitelist:")
    total_phe = total_pnl = 0
    for canon_norm, canon_disp, variants in UNIFICATIONS:
        if APPLY:
            n_phe, n_pnl = aplicar(conn, canon_norm, canon_disp, variants)
        else:
            cur = conn.cursor()
            n_phe = sum(
                cur.execute(f"SELECT COUNT(*) FROM partidos_historico_externo WHERE {col_norm}=?",
                              (var_norm,)).fetchone()[0]
                for var_norm, _ in variants for col_norm in ["ht_norm", "at_norm"]
            )
            n_pnl = sum(
                cur.execute(f"SELECT COUNT(*) FROM partidos_no_liga WHERE {col_norm}=?",
                              (var_norm,)).fetchone()[0]
                for var_norm, _ in variants
                for col_norm in ["equipo_local_norm", "equipo_visita_norm"]
            )
        var_str = ", ".join(f"'{vd}'" for _, vd in variants)
        print(f"  -> '{canon_disp}' (canon_norm={canon_norm})")
        print(f"     variantes [{var_str}]")
        print(f"     phe={n_phe}, pnl={n_pnl}")
        total_phe += n_phe
        total_pnl += n_pnl

    if APPLY:
        conn.commit()
    conn.close()
    print(f"\nTOTAL: phe={total_phe}, pnl={total_pnl}")


if __name__ == "__main__":
    main()
