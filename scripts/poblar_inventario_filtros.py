"""Pobla motor_filtros_activos con inventario exhaustivo de filtros del motor.

Cada filtro:
  - nombre canonico
  - ubicacion (archivo:linea)
  - clave en config_motor_valores (si parametrizable)
  - descripcion clara
  - referencia al Manifesto

PROPOSITO: que cualquier agente futuro (Lead, optimizador, critico) pueda hacer
  SELECT * FROM motor_filtros_activos
y conocer los filtros existentes ANTES de proponer cambios.

Idempotente: borra y re-inserta.
"""
import sqlite3
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

DB = Path(__file__).resolve().parent.parent / "fondo_quant.db"

# Inventario manual exhaustivo (revisado contra motor_calculadora.py + Reglas_IA.txt)
FILTROS = [
    # === Filtros de DECISION (gates antes de [APOSTAR]) ===
    {
        "filtro": "FLOOR_PROB_MIN",
        "ubicacion": "motor_calculadora.py:158",
        "parametro_clave": "floor_prob_min",
        "default_global": 0.33,
        "descripcion": "Probabilidad minima del outcome elegido. Si prob < 0.33, [PASAR].",
        "referencia_manifesto": "II.E V4.1",
    },
    {
        "filtro": "MARGEN_PREDICTIVO_1X2",
        "ubicacion": "motor_calculadora.py:152, 615-617",
        "parametro_clave": "margen_predictivo_1x2",
        "default_global": 0.03,
        "descripcion": "Diferencia minima entre prob_top1 y prob_top2. Si margen < threshold, [PASAR] Margen Insuficiente. Scope por liga (config_motor_valores).",
        "referencia_manifesto": "II.E + IV.A V4.3",
    },
    {
        "filtro": "MARGEN_PREDICTIVO_OU",
        "ubicacion": "motor_calculadora.py:153",
        "parametro_clave": "margen_predictivo_ou",
        "default_global": 0.05,
        "descripcion": "Diferencia minima entre prob_OVER y prob_UNDER. Si menor, [PASAR].",
        "referencia_manifesto": "IV.D2",
    },
    {
        "filtro": "DIVERGENCIA_MAX_1X2",
        "ubicacion": "motor_calculadora.py:128, 604-605",
        "parametro_clave": "divergencia_max_1x2",
        "default_global": 0.10,
        "descripcion": "Max divergencia |prob_modelo - prob_implicita_mercado|. Si excede, considera Camino 2B (Desacuerdo). Scope por liga.",
        "referencia_manifesto": "II.E + Fix #4 V4.4",
    },
    {
        "filtro": "EV_MIN_ESCALADO",
        "ubicacion": "motor_calculadora.py (caminos)",
        "parametro_clave": "min_ev_escalado",
        "default_global": 0.03,
        "descripcion": "EV minimo por bucket prob. 3% bucket alto, 8% medio, 12% bajo (escalado).",
        "referencia_manifesto": "II.E + V4.4",
    },
    {
        "filtro": "APUESTA_EMPATE_PERMITIDA",
        "ubicacion": "motor_calculadora.py (Reglas_IA.txt)",
        "parametro_clave": "apuesta_empate_permitida",
        "default_global": 0.0,  # False
        "descripcion": "Si False, X no aparece como pick option. Cambiado a False en V4.3 por hit-rate bajo.",
        "referencia_manifesto": "II.E V4.3",
    },
    # === Calibraciones ===
    {
        "filtro": "FIX_5_BUCKET_40_50",
        "ubicacion": "motor_calculadora.py",
        "parametro_clave": "calibracion_bucket_min/max/correccion",
        "default_global": 0.042,
        "descripcion": "+0.042 a p1/p2 cuando prob_max en bucket [40%, 50%). Renormaliza despues.",
        "referencia_manifesto": "II.E Fix #5",
    },
    {
        "filtro": "HALLAZGO_G",
        "ubicacion": "motor_calculadora.py:851-873",
        "parametro_clave": "hallazgo_g_activo + n_min_hallazgo_g",
        "default_global": 50.0,
        "descripcion": "Boost local cuando freq_local_real_liga > 0.5 con N>=50. Activacion: HALLAZGO_G_ACTIVO=True.",
        "referencia_manifesto": "II.E + IV.H",
    },
    {
        "filtro": "HALLAZGO_C",
        "ubicacion": "motor_calculadora.py",
        "parametro_clave": "hallazgo_c (bucket)",
        "default_global": 1.15,
        "descripcion": "Multiplicador de stake por dominancia xG (1.15x o 1.30x).",
        "referencia_manifesto": "II.E + IV.G",
    },
    {
        "filtro": "GAMMA_DISPLAY",
        "ubicacion": "motor_calculadora.py:923",
        "parametro_clave": "gamma_1x2",
        "default_global": 0.59,
        "descripcion": "Comprime xG_display = xG_crudo × gamma. NO entra al Poisson, solo persistencia/UI. Scope por liga.",
        "referencia_manifesto": "II.A P5D fase3",
    },
    # === EMA / xG hibrido ===
    {
        "filtro": "ALFA_EMA",
        "ubicacion": "motor_data.py:296",
        "parametro_clave": "alfa_ema",
        "default_global": 0.18,
        "descripcion": "Smoothing EMA por liga. Mayor = mas peso a partidos recientes. Scope por liga.",
        "referencia_manifesto": "II.B Fix #3 V4.4",
    },
    {
        "filtro": "N0_ANCLA",
        "ubicacion": "motor_data.py",
        "parametro_clave": "n0_ancla",
        "default_global": 5.0,
        "descripcion": "Bayesian shrinkage hacia promedio_liga. w_liga = N0/(N0+N).",
        "referencia_manifesto": "II.B",
    },
    {
        "filtro": "BETA_SOT",
        "ubicacion": "motor_data.py:149",
        "parametro_clave": "beta_sot",
        "default_global": 0.352,
        "descripcion": "Coef shotsOnTarget en xg_hibrido. Scope por liga (P4 fase3 OLS calibrado).",
        "referencia_manifesto": "II.A P4 fase3",
    },
    {
        "filtro": "BETA_SHOTS_OFF",
        "ubicacion": "motor_data.py:150",
        "parametro_clave": "beta_shots_off",
        "default_global": 0.010,
        "descripcion": "Coef shots_off_target en xg_hibrido. Global. Discrepancia con OLS empirico (-0.027) — ver adepor-dx8 PARTE B.",
        "referencia_manifesto": "II.A P4 fase3",
    },
    {
        "filtro": "COEF_CORNER_LIGA",
        "ubicacion": "motor_data.py:152",
        "parametro_clave": "coef_corner_calculado (en ligas_stats)",
        "default_global": 0.020,
        "descripcion": "Coef corners en xg_hibrido. Scope por liga (calculado online via motor_data). Discrepancia OLS -0.055.",
        "referencia_manifesto": "II.A B2 fase3",
    },
    {
        "filtro": "RHO_DIXON_COLES",
        "ubicacion": "motor_calculadora.py:944, ligas_stats.rho_calculado",
        "parametro_clave": "rho_calculado (en ligas_stats) + RHO_FALLBACK",
        "default_global": -0.09,
        "descripcion": "Correlacion DC para marcadores bajos (0-0, 1-0, 0-1, 1-1). Scope por liga via MLE externo (calibrar_rho.py).",
        "referencia_manifesto": "II.A",
    },
    # === Stake (Kelly) ===
    {
        "filtro": "MAX_KELLY_PCT_NORMAL",
        "ubicacion": "motor_calculadora.py",
        "parametro_clave": "max_kelly_pct_normal",
        "default_global": 0.025,
        "descripcion": "Cap Kelly % normal (Camino 1, 2). 2.5% max per pick.",
        "referencia_manifesto": "II.I",
    },
    {
        "filtro": "MAX_KELLY_PCT_ALTO",
        "ubicacion": "motor_calculadora.py",
        "parametro_clave": "max_kelly_pct_alto",
        "default_global": 0.05,
        "descripcion": "Cap Kelly % alto (Camino 3 Alta Conviccion). 5% max.",
        "referencia_manifesto": "II.I",
    },
    {
        "filtro": "ALTITUD_NIVELES",
        "ubicacion": "motor_calculadora.py:402-408",
        "parametro_clave": None,
        "default_global": None,
        "descripcion": "[SHADOW] Multiplicadores xG por altitud local: Z.Muerte 1.35/0.75, Extremo 1.25/0.80, Alto 1.15/0.85, Medio 1.10/0.90. Solo aplica si equipo en equipos_altitud.",
        "referencia_manifesto": "II.G (en SHADOW por adepor-kc2 DIFERIDO)",
    },
]


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("DELETE FROM motor_filtros_activos")
    for f in FILTROS:
        cur.execute(
            """
            INSERT INTO motor_filtros_activos
            (filtro, ubicacion, parametro_clave, default_global, descripcion, referencia_manifesto)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (f["filtro"], f["ubicacion"], f.get("parametro_clave"),
             f.get("default_global"), f["descripcion"], f["referencia_manifesto"]),
        )
    con.commit()

    n = cur.execute("SELECT COUNT(*) FROM motor_filtros_activos").fetchone()[0]
    print(f"Inventario poblado: {n} filtros")
    print()
    print(f"{'Filtro':<28} {'Default':>9} {'Manifesto':<12} Ubicacion")
    print("-" * 100)
    for r in cur.execute("""
        SELECT filtro, default_global, referencia_manifesto, ubicacion, parametro_clave
        FROM motor_filtros_activos ORDER BY referencia_manifesto, filtro
    """):
        scope = "(global)" if r[4] is None else "(scope-liga)" if "(en " in (r[4] or "") else ""
        defv = f"{r[1]:.4f}" if r[1] is not None else "—"
        print(f"{r[0]:<28} {defv:>9} {r[2]:<12} {r[3]}")
    con.close()


if __name__ == "__main__":
    main()
