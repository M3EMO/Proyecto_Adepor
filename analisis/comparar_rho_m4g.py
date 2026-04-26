"""Compara propuestas rho m4g vs rho_calculado actual en DB. Genera reporte + SQL."""
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"
JSON_IN = ROOT / "analisis" / "mle_externo_rho_adepor-m4g.json"
SQL_OUT = ROOT / "analisis" / "rho_update_adepor-m4g.sql"

con = sqlite3.connect(DB)
data = json.loads(JSON_IN.read_text(encoding="utf-8"))["resultados"]

print(f"{'Liga':<12} {'N_ext':>5} {'rho_MLE':>9} {'rho_prop':>9} {'rho_DB':>8}  {'delta':>7}  {'flag':<10}")
print("-" * 70)

sql_lines = ["-- UPDATE rho_calculado para 9 ligas (adepor-m4g, retry post-429)",
             "-- Generado automaticamente. Aplicar manual post-veredicto Critico.",
             ""]
n_propuestos = 0

for liga, r in data.items():
    rho_db_row = con.execute(
        "SELECT rho_calculado FROM ligas_stats WHERE liga = ?", (liga,)
    ).fetchone()
    rho_db = rho_db_row[0] if rho_db_row else None
    rho_prop = r.get("rho_propuesto_externo")
    n_ext = r.get("n_externo", 0)
    rho_mle = r.get("rho_mle")
    estado = r.get("estado", "N/A")

    if rho_prop is None or rho_db is None:
        print(f"{liga:<12} {n_ext:>5}  N/A  ({estado})")
        continue

    delta = rho_prop - rho_db
    # Flag si delta es trivial (< precision shrinkage_floor)
    if abs(delta) < 0.005:
        flag = "TRIVIAL"
    elif rho_mle == 0.0:
        flag = "MLE=0!"
    else:
        flag = "ACTUALIZAR"

    rho_mle_str = f"{rho_mle:+.4f}" if rho_mle is not None else "  N/A "
    print(f"{liga:<12} {n_ext:>5}  {rho_mle_str:>8}  {rho_prop:>+8.4f}  {rho_db:>+7.4f}  {delta:>+7.4f}  {flag:<10}")

    if flag == "ACTUALIZAR":
        sql_lines.append(
            f"UPDATE ligas_stats SET rho_calculado = {rho_prop} WHERE liga = '{liga}';  -- delta={delta:+.4f}, N_ext={n_ext}"
        )
        n_propuestos += 1
    elif flag == "MLE=0!":
        sql_lines.append(
            f"-- {liga}: rho_MLE=0 (post-COVID artifact?), shrinkage->floor={rho_prop:+.4f}. SUSPENDER hasta investigacion (similar a adepor-0yy Inglaterra)."
        )

SQL_OUT.write_text("\n".join(sql_lines) + "\n", encoding="utf-8")

print()
print(f"\n=== RESUMEN ===")
print(f"  Propuestos UPDATE: {n_propuestos}")
print(f"  Suspendidos (MLE=0): vease comentarios SQL")
print(f"  SQL: {SQL_OUT}")
con.close()
