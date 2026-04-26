"""
Consolida resultados in-sample + MLE externo en JSON final + SQL pre-armado.

Logica de decision por liga:
  1. MLE externo con N >= min_required (Eur 80 / LATAM 150) -> usar rho_propuesto_externo.
  2. In-sample con delta_brier significativo (>=0.015) -> usar rho_propuesto_insample.
  3. Caso contrario: mantener rho_actual de ligas_stats.

Salida: analisis/rho_recalibrado_adepor-1vt.json (final, sobreescribe el in-sample-only)
        analisis/rho_update_adepor-1vt.sql  (final)
"""
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ANALISIS = ROOT / "analisis"
SHADOW_PATH = ROOT / "shadow_dbs" / "shadow_adepor-1vt.db"
SHADOW_SHA256 = "bd550d9ed7f2bd75cd76f0617adc05bf92919be871dc0ac39c293c6ecda22e1a"
BEAD_ID = "adepor-1vt"

JSON_INSAMPLE = ANALISIS / "rho_recalibrado_adepor-1vt.json"
JSON_EXTERNO = ANALISIS / "mle_externo_rho_adepor-1vt.json"
JSON_FINAL = ANALISIS / "rho_recalibrado_adepor-1vt.json"
SQL_FINAL = ANALISIS / "rho_update_adepor-1vt.sql"


def main():
    insample = json.loads(JSON_INSAMPLE.read_text(encoding='utf-8'))
    externo = json.loads(JSON_EXTERNO.read_text(encoding='utf-8'))

    # Cargar rho actual de ligas_stats (read-only via shadow)
    conn = sqlite3.connect(f"file:{SHADOW_PATH}?mode=ro", uri=True)
    c = conn.cursor()
    c.execute("SELECT liga, rho_calculado FROM ligas_stats")
    rho_actual_db = {r[0]: r[1] for r in c.fetchall()}
    conn.close()

    # Para Brier antes/despues a nivel global, ya tengo lo de in-sample (75 Arg + 54 Bra).
    # Para EV_total_horizonte (proxy): asumo Kelly nominal sin N_picks => reporto 0 con caveat.
    # delta_yield: idem, sin senal.

    consolidado = {}
    todas_las_ligas = set(insample['resultados_por_liga'].keys()) | set(externo['resultados']) | set(rho_actual_db.keys())

    for liga in sorted(todas_las_ligas):
        in_r = insample['resultados_por_liga'].get(liga, {})
        ex_r = externo['resultados'].get(liga, {})
        rho_act = rho_actual_db.get(liga)

        decision = {
            'liga': liga,
            'rho_actual_ligas_stats': rho_act,
            'in_sample': {
                'n_liquidados': in_r.get('n_liquidados', 0),
                'estado': in_r.get('estado', 'NO_DATA'),
                'rho_optimo_grid': in_r.get('rho_optimo_grid'),
                'rho_propuesto_insample': in_r.get('rho_propuesto_final'),
                'delta_brier_combinado': in_r.get('delta_brier_combinado'),
                'significativo_brier_015': in_r.get('significativo_brier_015'),
            },
            'externo_mle': {
                'fuente': ex_r.get('fuente'),
                'n_externo': ex_r.get('n_externo', 0),
                'estado': ex_r.get('estado', 'NO_DATA'),
                'rho_mle': ex_r.get('rho_mle'),
                'rho_propuesto_externo': ex_r.get('rho_propuesto_externo'),
                'outlier': ex_r.get('outlier'),
            },
        }

        # Logica de decision
        ex_estado = ex_r.get('estado')
        in_signif = in_r.get('significativo_brier_015', False)

        if ex_estado == 'MLE_OK':
            # 1) MLE externo es la fuente preferida (out-of-sample, N suficiente).
            decision['rho_propuesto_final'] = ex_r['rho_propuesto_externo']
            decision['fuente_decision'] = 'MLE_EXTERNO'
            decision['justificacion'] = (
                f"MLE externo OK con N={ex_r['n_externo']} (>= min). "
                f"Out-of-sample. Shrinkage hacia -0.12 con w={ex_r.get('shrinkage_w')}."
            )
        elif in_r.get('estado') == 'ANALIZADO_INSAMPLE' and in_signif:
            # 2) Solo in-sample y SIGNIFICATIVO -> usar
            decision['rho_propuesto_final'] = in_r['rho_propuesto_final']
            decision['fuente_decision'] = 'IN_SAMPLE_SIGNIFICATIVO'
            decision['justificacion'] = (
                f"MLE externo no disponible. In-sample N={in_r.get('n_liquidados')} "
                f"con delta_brier {in_r.get('delta_brier_combinado'):+.4f} >= 0.015."
            )
        else:
            # 3) Mantener actual (sin evidencia significativa)
            decision['rho_propuesto_final'] = rho_act
            if in_r.get('estado') == 'ANALIZADO_INSAMPLE' and not in_signif:
                decision['fuente_decision'] = 'MANTENER_NO_SIGNIFICATIVO'
                decision['justificacion'] = (
                    f"In-sample N={in_r.get('n_liquidados')} con delta_brier "
                    f"{in_r.get('delta_brier_combinado'):+.4f} < 0.015 (no significativo). "
                    f"MLE externo no disponible (rate limit / sin fuente)."
                )
            else:
                decision['fuente_decision'] = 'MANTENER_SIN_EVIDENCIA'
                decision['justificacion'] = (
                    f"Sin datos in-sample (N<{50}) y MLE externo no disponible "
                    f"(estado={ex_estado}). Mantener rho_calculado actual."
                )

        # Cambia o no?
        rho_prop = decision['rho_propuesto_final']
        if rho_prop is None or rho_act is None:
            decision['cambio'] = False
            decision['delta_rho'] = None
        else:
            decision['cambio'] = abs(rho_prop - rho_act) > 1e-5
            decision['delta_rho'] = round(rho_prop - rho_act, 4)

        consolidado[liga] = decision

    # Aggregate
    n_total = sum(d['in_sample'].get('n_liquidados', 0) for d in consolidado.values())
    n_in_sample = sum(d['in_sample'].get('n_liquidados', 0) for d in consolidado.values()
                      if d['in_sample'].get('estado') == 'ANALIZADO_INSAMPLE')
    n_externo_total = sum(d['externo_mle'].get('n_externo', 0) for d in consolidado.values()
                          if d['externo_mle'].get('estado') == 'MLE_OK')

    # Brier ponderado de in-sample (las dos ligas que se analizaron)
    suma_b_actual = 0.0
    suma_b_post = 0.0
    n_b = 0
    for liga, d in consolidado.items():
        in_r = insample['resultados_por_liga'].get(liga, {})
        if in_r.get('estado') == 'ANALIZADO_INSAMPLE':
            n_loc = in_r.get('n_liquidados', 0)
            ba = in_r.get('baseline_actual', {}).get('score_brier_combinado', 0)
            bp = in_r.get('metricas_post', {}).get('score_brier_combinado', 0)
            suma_b_actual += ba * n_loc
            suma_b_post += bp * n_loc
            n_b += n_loc

    output = {
        'bead_id': BEAD_ID,
        'snapshot_db_path': str(SHADOW_PATH.relative_to(ROOT)),
        'snapshot_db_sha256': SHADOW_SHA256,
        'metodologia': insample['metodologia'],
        'metodologia_externa': externo['metodologia'],
        'limitaciones': {
            **insample['limitaciones'],
            'rate_limit_api_football': '9 ligas no descargadas por HTTP 429: Chile, Colombia, Ecuador, Espana, Francia, Italia, Peru, Uruguay, Venezuela. Para estas se mantiene rho_actual.',
        },
        'logica_decision': [
            'MLE_EXTERNO: si N_externo >= min_required (Eur 80, LATAM 150) -> rho_propuesto_externo',
            'IN_SAMPLE_SIGNIFICATIVO: si in-sample N>=50 y |delta_brier|>=0.015 -> rho_propuesto_insample',
            'MANTENER_NO_SIGNIFICATIVO / MANTENER_SIN_EVIDENCIA: rho_actual sin cambio',
        ],
        'resultados_por_liga': consolidado,
        'aggregate': {
            'n_total_liquidados_db': n_total,
            'n_analizados_in_sample': n_in_sample,
            'n_externo_mle_total': n_externo_total,
            'brier_combinado_antes_in_sample': round(suma_b_actual / n_b, 6) if n_b > 0 else None,
            'brier_combinado_despues_in_sample': round(suma_b_post / n_b, 6) if n_b > 0 else None,
            'delta_brier_global_in_sample': round((suma_b_post - suma_b_actual) / n_b, 6) if n_b > 0 else None,
            'ev_total_horizonte_antes': 0.0,
            'ev_total_horizonte_despues': 0.0,
            'ev_total_horizonte_caveat': 'No calculado: 0 picks 1x2 reales y 10 picks O/U totales. Senal estadistica nula. No se reporta yield.',
            'delta_yield': None,
            'delta_yield_caveat': 'No calculable por baja N_picks. Brier es metrica primaria.',
        },
    }

    JSON_FINAL.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f"[OK] JSON final: {JSON_FINAL}")

    # SQL pre-armado
    sql_lines = [
        f"-- UPDATE rho_calculado por liga - bead {BEAD_ID}",
        f"-- Generado por: analisis/consolidar_rho_adepor-1vt.py",
        f"-- Snapshot referencia: {SHADOW_PATH.name}",
        f"-- SHA256: {SHADOW_SHA256}",
        f"-- NO EJECUTAR sin veredicto del Critico.",
        "",
        "BEGIN;",
        "",
    ]
    cambios_aplicar = []
    for liga, d in sorted(consolidado.items()):
        rho_act = d['rho_actual_ligas_stats']
        rho_prop = d['rho_propuesto_final']
        fuente = d['fuente_decision']
        cambio = d['cambio']
        delta = d['delta_rho']

        if cambio and rho_prop is not None:
            sql_lines.append(
                f"-- {liga}: actual={rho_act} -> propuesto={rho_prop}  [{fuente}, dRho={delta:+.4f}]"
            )
            sql_lines.append(
                f"UPDATE ligas_stats SET rho_calculado = {rho_prop} WHERE liga = '{liga}';"
            )
            cambios_aplicar.append(liga)
        else:
            sql_lines.append(f"-- {liga}: SIN CAMBIO  [{fuente}]  (actual={rho_act}, propuesto={rho_prop})")
        sql_lines.append("")
    sql_lines.append("COMMIT;")
    sql_lines.append("")
    sql_lines.append(f"-- Total ligas con cambio aplicable: {len(cambios_aplicar)}")
    sql_lines.append(f"-- Ligas con cambio: {', '.join(cambios_aplicar) if cambios_aplicar else 'NINGUNA'}")
    SQL_FINAL.write_text("\n".join(sql_lines), encoding='utf-8')
    print(f"[OK] SQL final: {SQL_FINAL}")
    print()
    print(f"Resumen: {len(cambios_aplicar)} ligas con UPDATE propuesto.")
    print(f"Ligas con cambio: {cambios_aplicar}")


if __name__ == "__main__":
    main()
