"""Verifica el estado de los triggers D (hm9, 1fd, 23w)."""
import sqlite3
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

DB = Path(__file__).resolve().parent.parent / "fondo_quant.db"
con = sqlite3.connect(DB)
cur = con.cursor()

# adepor-hm9: CLV
n_clv = cur.execute("""
    SELECT COUNT(*) FROM partidos_backtest
    WHERE clv_pct_1x2 IS NOT NULL OR clv_pct_ou IS NOT NULL
""").fetchone()[0]

# adepor-1fd: xg_corto
n_corto = cur.execute("""
    SELECT COUNT(*) FROM partidos_backtest
    WHERE estado='Liquidado' AND xg_local_corto IS NOT NULL AND xg_visita_corto IS NOT NULL
""").fetchone()[0]

# adepor-23w: altitud aplicada (post-backfill om4 = 46)
n_alt = cur.execute("""
    SELECT COUNT(*) FROM partidos_backtest
    WHERE estado='Liquidado' AND pais IN ('Bolivia','Peru','Ecuador','Colombia')
      AND COALESCE(shadow_xg_local,0)/NULLIF(xg_local,0) > 1.85
""").fetchone()[0]

print(f"adepor-hm9 (CLV ops):       N picks con clv = {n_clv:>3}  (trigger >=30)  {'DISPARA' if n_clv>=30 else 'gating'}")
print(f"adepor-1fd (EMA shadow):    N Liq con xg_corto = {n_corto:>3}  (trigger >=30)  {'DISPARA' if n_corto>=30 else 'gating'}")
print(f"adepor-23w (altitud A/B):   N Liq altitud aplicada = {n_alt:>3}  (trigger >=30)  {'DISPARA' if n_alt>=30 else 'gating'}")

con.close()
