"""
Backtest in-sample de rho por liga sobre partidos_backtest.

Objetivo: barrer rho ∈ [-0.25, +0.05] step 0.005 (61 valores) por liga
elegible (N_liquidados >= 50), recomputar Brier 1x2/O/U y log-loss
con Poisson bivariado + tau Dixon-Coles, comparar contra rho actual de
ligas_stats y RHO_FALLBACK -0.09.

Salida: analisis/rho_recalibrado_adepor-1vt.json + analisis/rho_update_adepor-1vt.sql

NO escribe en fondo_quant.db (read-only). El UPDATE SQL queda
pre-armado para que el Critico lo valide antes de ejecutar.
"""
import json
import math
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DB_PATH = ROOT / "fondo_quant.db"
SHADOW_PATH = ROOT / "shadow_dbs" / "shadow_adepor-1vt.db"
SHADOW_SHA256 = "bd550d9ed7f2bd75cd76f0617adc05bf92919be871dc0ac39c293c6ecda22e1a"
JSON_OUT = ROOT / "analisis" / "rho_recalibrado_adepor-1vt.json"
SQL_OUT = ROOT / "analisis" / "rho_update_adepor-1vt.sql"

BEAD_ID = "adepor-1vt"

N_MIN_INSAMPLE = 50
RHO_GRID_MIN = -0.25
RHO_GRID_MAX = 0.05
RHO_GRID_STEP = 0.005
RHO_FLOOR = -0.03
RHO_FALLBACK = -0.09

RHO_RAZONABLE_MIN = -0.20
RHO_RAZONABLE_MAX = 0.05
RHO_SHRINKAGE_TARGET = -0.12
SHRINKAGE_PSEUDO_N = 200

RANGO_POISSON = 10


def poisson(k, lam):
    if lam <= 0 or k < 0:
        return 0.0
    try:
        return math.exp(k * math.log(lam) - lam - sum(math.log(i) for i in range(1, k + 1)))
    except (ValueError, OverflowError):
        return 0.0


def tau(i, j, lam, mu, rho):
    if i == 0 and j == 0:
        return max(1e-10, 1.0 - lam * mu * rho)
    elif i == 1 and j == 0:
        return max(1e-10, 1.0 + mu * rho)
    elif i == 0 and j == 1:
        return max(1e-10, 1.0 + lam * rho)
    elif i == 1 and j == 1:
        return max(1e-10, 1.0 - rho)
    return 1.0


def calcular_probs(xg_l, xg_v, rho):
    p1 = px = p2 = po = pu = 0.0
    for i in range(RANGO_POISSON):
        for j in range(RANGO_POISSON):
            pb = poisson(i, xg_l) * poisson(j, xg_v) * tau(i, j, xg_l, xg_v, rho)
            if i > j:
                p1 += pb
            elif i == j:
                px += pb
            else:
                p2 += pb
            if (i + j) > 2.5:
                po += pb
            else:
                pu += pb
    s1 = p1 + px + p2
    if s1 > 0:
        p1, px, p2 = p1 / s1, px / s1, p2 / s1
    so = po + pu
    if so > 0:
        po, pu = po / so, pu / so
    return p1, px, p2, po, pu


def brier_1x2(rows):
    if not rows:
        return None
    s = 0.0
    for p1, px, p2, y1, yx, y2 in rows:
        s += (p1 - y1) ** 2 + (px - yx) ** 2 + (p2 - y2) ** 2
    return s / (3 * len(rows))


def brier_ou(rows):
    if not rows:
        return None
    s = 0.0
    for po, pu, yo, yu in rows:
        s += (po - yo) ** 2 + (pu - yu) ** 2
    return s / (2 * len(rows))


def logloss_1x2(rows):
    if not rows:
        return None
    s = 0.0
    eps = 1e-9
    for p1, px, p2, y1, yx, y2 in rows:
        if y1 == 1:
            s -= math.log(max(p1, eps))
        elif yx == 1:
            s -= math.log(max(px, eps))
        else:
            s -= math.log(max(p2, eps))
    return s / len(rows)


def logloss_ou(rows):
    if not rows:
        return None
    s = 0.0
    eps = 1e-9
    for po, pu, yo, yu in rows:
        if yo == 1:
            s -= math.log(max(po, eps))
        else:
            s -= math.log(max(pu, eps))
    return s / len(rows)


def cargar_partidos_liquidados(conn):
    c = conn.cursor()
    c.execute("""
        SELECT pais, id_partido, xg_local, xg_visita,
               cuota_1, cuota_x, cuota_2, cuota_o25, cuota_u25,
               goles_l, goles_v
        FROM partidos_backtest
        WHERE estado = 'Liquidado'
          AND goles_l IS NOT NULL AND goles_v IS NOT NULL
          AND xg_local IS NOT NULL AND xg_visita IS NOT NULL
          AND cuota_1 IS NOT NULL AND cuota_x IS NOT NULL AND cuota_2 IS NOT NULL
        ORDER BY pais, fecha
    """)
    por_liga = {}
    for r in c.fetchall():
        liga = r[0]
        por_liga.setdefault(liga, []).append({
            'id': r[1], 'xg_l': r[2], 'xg_v': r[3],
            'c1': r[4], 'cx': r[5], 'c2': r[6], 'co': r[7], 'cu': r[8],
            'gl': r[9], 'gv': r[10]
        })
    return por_liga


def cargar_rho_actual(conn):
    c = conn.cursor()
    c.execute("SELECT liga, rho_calculado FROM ligas_stats")
    return {r[0]: r[1] for r in c.fetchall()}


def evaluar_rho(partidos, rho):
    out_1x2 = []
    out_ou = []
    for p in partidos:
        if p['gl'] > p['gv']:
            y1, yx, y2 = 1, 0, 0
        elif p['gl'] == p['gv']:
            y1, yx, y2 = 0, 1, 0
        else:
            y1, yx, y2 = 0, 0, 1
        if (p['gl'] + p['gv']) > 2.5:
            yo, yu = 1, 0
        else:
            yo, yu = 0, 1

        p1, px, p2, po, pu = calcular_probs(p['xg_l'], p['xg_v'], rho)
        out_1x2.append((p1, px, p2, y1, yx, y2))
        if p['co'] is not None and p['cu'] is not None:
            out_ou.append((po, pu, yo, yu))

    b_1x2 = brier_1x2(out_1x2)
    b_ou = brier_ou(out_ou)
    n1 = len(out_1x2)
    n2 = len(out_ou)
    if b_1x2 is not None and b_ou is not None and (n1 + n2) > 0:
        score = (b_1x2 * n1 + b_ou * n2) / (n1 + n2)
    elif b_1x2 is not None:
        score = b_1x2
    else:
        score = math.inf

    return {
        'brier_1x2': b_1x2,
        'brier_ou': b_ou,
        'logloss_1x2': logloss_1x2(out_1x2),
        'logloss_ou': logloss_ou(out_ou),
        'n_1x2': n1,
        'n_ou': n2,
        'score_brier_combinado': score,
    }


def grid_search(partidos):
    n_pasos = int(round((RHO_GRID_MAX - RHO_GRID_MIN) / RHO_GRID_STEP)) + 1
    res = {}
    for k in range(n_pasos):
        rho = round(RHO_GRID_MIN + k * RHO_GRID_STEP, 4)
        res[rho] = evaluar_rho(partidos, rho)
    return res


def aplicar_shrinkage(rho_mle, n, target=RHO_SHRINKAGE_TARGET, pseudo_n=SHRINKAGE_PSEUDO_N):
    w = n / (n + pseudo_n)
    return w * rho_mle + (1 - w) * target


def aplicar_floor(rho):
    return min(rho, RHO_FLOOR)


def main():
    print("=" * 70)
    print(f"BACKTEST RHO IN-SAMPLE - bead {BEAD_ID}")
    print("=" * 70)
    print(f"Snapshot: {SHADOW_PATH.name}")
    print(f"SHA256:   {SHADOW_SHA256}")
    print(f"Grid:     rho in [{RHO_GRID_MIN}, {RHO_GRID_MAX}] step {RHO_GRID_STEP}")
    print(f"Umbral:   N_liquidados >= {N_MIN_INSAMPLE}")
    print()

    conn = sqlite3.connect(f"file:{SHADOW_PATH}?mode=ro", uri=True)
    rho_actual_db = cargar_rho_actual(conn)
    por_liga = cargar_partidos_liquidados(conn)

    print("=== Inventario read-only del shadow ===")
    ligas_inventario = []
    for liga in sorted(por_liga.keys()):
        n = len(por_liga[liga])
        rho_db = rho_actual_db.get(liga, None)
        elegible = n >= N_MIN_INSAMPLE
        ligas_inventario.append({
            'liga': liga,
            'n_liquidados': n,
            'rho_actual_ligas_stats': rho_db,
            'elegible_in_sample': elegible,
        })
        flag = "ELEGIBLE" if elegible else "skip"
        print(f"  {liga:18s} N={n:3d}  rho_db={rho_db}  [{flag}]")
    print()

    resultados_por_liga = {}
    for entry in ligas_inventario:
        liga = entry['liga']
        if not entry['elegible_in_sample']:
            resultados_por_liga[liga] = {
                **entry,
                'estado': 'SKIP_N_INSUFICIENTE',
                'recomendacion': 'mantener rho_actual_ligas_stats (sin nueva evidencia)',
                'rho_propuesto_final': entry['rho_actual_ligas_stats'],
            }
            continue

        print(f"=== Liga: {liga} (N={entry['n_liquidados']}) ===")
        partidos = por_liga[liga]

        rho_db = entry['rho_actual_ligas_stats']
        baseline = evaluar_rho(partidos, rho_db) if rho_db is not None else None
        baseline_fallback = evaluar_rho(partidos, RHO_FALLBACK)

        grid_res = grid_search(partidos)
        rho_optimo, m_optimo = min(grid_res.items(), key=lambda kv: kv[1]['score_brier_combinado'])

        rho_post_shrinkage = aplicar_shrinkage(rho_optimo, entry['n_liquidados'])
        rho_post_floor = aplicar_floor(rho_post_shrinkage)

        if not (RHO_RAZONABLE_MIN <= rho_optimo <= RHO_RAZONABLE_MAX):
            outlier = True
            rho_post_outlier = aplicar_floor(RHO_SHRINKAGE_TARGET)
        else:
            outlier = False
            rho_post_outlier = rho_post_floor

        post = evaluar_rho(partidos, rho_post_outlier)

        delta_brier = (post['score_brier_combinado'] - baseline['score_brier_combinado']) if baseline else None
        significativo = (delta_brier is None) or (abs(delta_brier) >= 0.015)

        print(f"  rho_actual_db   = {rho_db}")
        print(f"  rho_optimo_grid = {rho_optimo}")
        print(f"  rho_post_shrink = {rho_post_shrinkage:.4f}  (w={entry['n_liquidados']/(entry['n_liquidados']+200):.3f})")
        print(f"  rho_propuesto   = {rho_post_outlier:.4f}  (outlier={outlier})")
        if baseline:
            print(f"  Brier_1x2: actual={baseline['brier_1x2']:.4f} | optimo_final={post['brier_1x2']:.4f} | dB={post['brier_1x2']-baseline['brier_1x2']:+.4f}")
            print(f"  Brier_OU:  actual={baseline['brier_ou']:.4f} | optimo_final={post['brier_ou']:.4f} | dB={post['brier_ou']-baseline['brier_ou']:+.4f}")
            print(f"  delta_brier_combinado = {delta_brier:+.4f}  [signif>=0.015={significativo}]")
        print(f"  Brier vs FALLBACK -0.09: B1x2={baseline_fallback['brier_1x2']:.4f}  BOU={baseline_fallback['brier_ou']:.4f}")
        # Tambien grilla minima/maxima Brier para diagnosticar
        sorted_grid = sorted(grid_res.items(), key=lambda kv: kv[1]['score_brier_combinado'])
        print(f"  Top 3 rhos por Brier combinado:")
        for rho_c, m_c in sorted_grid[:3]:
            print(f"     rho={rho_c:+.4f}  B_comb={m_c['score_brier_combinado']:.5f}  B1x2={m_c['brier_1x2']:.5f}  BOU={m_c['brier_ou']:.5f}")
        print(f"  Bottom 3 rhos:")
        for rho_c, m_c in sorted_grid[-3:]:
            print(f"     rho={rho_c:+.4f}  B_comb={m_c['score_brier_combinado']:.5f}")
        print()

        resultados_por_liga[liga] = {
            **entry,
            'estado': 'ANALIZADO_INSAMPLE',
            'rho_optimo_grid': rho_optimo,
            'rho_post_shrinkage': round(rho_post_shrinkage, 4),
            'rho_propuesto_final': round(rho_post_outlier, 4),
            'outlier_detectado': outlier,
            'shrinkage_w': round(entry['n_liquidados']/(entry['n_liquidados']+200), 4),
            'baseline_actual': baseline,
            'baseline_fallback_009': baseline_fallback,
            'metricas_post': post,
            'delta_brier_combinado': round(delta_brier, 6) if delta_brier is not None else None,
            'significativo_brier_015': significativo,
            'caveat_ev_horizonte': 'EV ruido N bajo: picks reales 1x2=0, picks O/U <=10 totales',
        }

    n_total = sum(r.get('n_liquidados', 0) for r in resultados_por_liga.values())
    delta_brier_pond = sum(
        (r.get('delta_brier_combinado') or 0) * r.get('n_liquidados', 0)
        for r in resultados_por_liga.values()
        if r.get('estado') == 'ANALIZADO_INSAMPLE'
    )
    n_analizados = sum(
        r.get('n_liquidados', 0)
        for r in resultados_por_liga.values()
        if r.get('estado') == 'ANALIZADO_INSAMPLE'
    )

    output = {
        'bead_id': BEAD_ID,
        'snapshot_db_path': str(SHADOW_PATH.relative_to(ROOT)),
        'snapshot_db_sha256': SHADOW_SHA256,
        'metodologia': {
            'grid': f'rho in [{RHO_GRID_MIN}, {RHO_GRID_MAX}] step {RHO_GRID_STEP}',
            'umbral_insample': N_MIN_INSAMPLE,
            'shrinkage_target': RHO_SHRINKAGE_TARGET,
            'shrinkage_pseudo_n': SHRINKAGE_PSEUDO_N,
            'outlier_range': [RHO_RAZONABLE_MIN, RHO_RAZONABLE_MAX],
            'floor': RHO_FLOOR,
            'fallback_actual_no_modificado': RHO_FALLBACK,
            'criterio_significancia': 'abs(delta_brier_combinado) >= 0.015',
        },
        'limitaciones': {
            'tipo_evaluacion': 'in-sample (sin holdout, N insuficiente para split)',
            'ev_horizonte_caveat': 'picks reales 1x2=0, picks O/U <=10 -> yield es ruido. Brier es metrica primaria.',
            'circularidad_data': 'partidos_backtest.prob_X fue calculado con rho_calculado actual; recomputo desde xg_local/xg_visita persistido.',
            'investigador_findings_bead': 'adepor-c2g',
            'investigador_resumen': 'literatura europea -0.10 a -0.15, LATAM extrapolado, recalibrar cada season, shrinkage hacia -0.12',
        },
        'resultados_por_liga': resultados_por_liga,
        'aggregate': {
            'n_total_liquidados': n_total,
            'n_analizados_in_sample': n_analizados,
            'delta_brier_global_ponderado': round(delta_brier_pond / n_analizados, 6) if n_analizados > 0 else None,
        },
    }

    JSON_OUT.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f"[OK] JSON: {JSON_OUT}")

    sql_lines = [
        f"-- UPDATE rho_calculado por liga - bead {BEAD_ID}",
        f"-- Generado por: analisis/backtest_rho_adepor-1vt.py",
        f"-- Snapshot referencia: {SHADOW_PATH.name}",
        f"-- SHA256: {SHADOW_SHA256}",
        f"-- NO EJECUTAR sin veredicto del Critico.",
        "",
        "BEGIN;",
        "",
    ]
    for liga, r in sorted(resultados_por_liga.items()):
        if r.get('estado') == 'ANALIZADO_INSAMPLE':
            rho_propuesto = r['rho_propuesto_final']
            rho_actual = r.get('rho_actual_ligas_stats')
            cambio = "MISMO" if rho_propuesto == rho_actual else "CAMBIO"
            sql_lines.append(
                f"-- {liga}: actual={rho_actual} -> propuesto={rho_propuesto}  [{cambio}, dB={r['delta_brier_combinado']:+.4f}, signif={r['significativo_brier_015']}]"
            )
            if rho_propuesto != rho_actual and r['significativo_brier_015']:
                sql_lines.append(
                    f"UPDATE ligas_stats SET rho_calculado = {rho_propuesto} WHERE liga = '{liga}';"
                )
            else:
                motivo = 'mismo valor' if rho_propuesto == rho_actual else 'no significativo (|dB|<0.015)'
                sql_lines.append(f"-- (no se ejecuta UPDATE: {motivo})")
            sql_lines.append("")
        else:
            sql_lines.append(f"-- {liga}: SKIP ({r.get('estado')}) - sin cambio")
    sql_lines.append("COMMIT;")
    SQL_OUT.write_text("\n".join(sql_lines), encoding='utf-8')
    print(f"[OK] SQL: {SQL_OUT}")

    conn.close()
    return output


if __name__ == "__main__":
    main()
