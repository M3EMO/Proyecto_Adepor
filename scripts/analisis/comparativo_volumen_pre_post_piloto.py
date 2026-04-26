"""Compara volumen de picks vivos ANTES vs DESPUES del piloto adepor-pilot.

ANTES: snapshot fondo_quant_20260425_211720_pre_backfill_auto.db
DESPUES: fondo_quant.db actual.

Objetivo: distinguir si la caida de volumen es por la recalibracion rho
(deberia concentrarse en Alemania/Argentina/Brasil/Noruega/Turquia) o
si es uniforme (otra causa).
"""
import sqlite3

DB_NOW = 'fondo_quant.db'
DB_PRE = 'snapshots/fondo_quant_20260425_211720_pre_backfill_auto.db'

LIGAS_RECALIB = {'Alemania', 'Argentina', 'Brasil', 'Noruega', 'Turquia'}


def picks_vivos_por_liga(db_path):
    con = sqlite3.connect(db_path)
    rows = con.execute("""
        SELECT pais,
               SUM(CASE WHEN stake_1x2>0 THEN 1 ELSE 0 END) AS vivas_1x2,
               SUM(CASE WHEN stake_ou>0 THEN 1 ELSE 0 END) AS vivas_ou,
               ROUND(COALESCE(SUM(stake_1x2 + stake_ou), 0), 0) AS stake_total,
               SUM(CASE WHEN apuesta_1x2 LIKE '[APOSTAR]%' THEN 1 ELSE 0 END) AS picks_1x2_total,
               SUM(CASE WHEN apuesta_ou LIKE '[APOSTAR]%' THEN 1 ELSE 0 END) AS picks_ou_total
        FROM partidos_backtest
        WHERE estado != 'Liquidado'
        GROUP BY pais
        HAVING vivas_1x2 + vivas_ou + picks_1x2_total + picks_ou_total > 0
    """).fetchall()
    con.close()
    return {r[0]: {'vivas_1x2': r[1], 'vivas_ou': r[2], 'stake': r[3],
                   'picks_1x2': r[4], 'picks_ou': r[5]} for r in rows}


def main():
    print("=" * 90)
    print("COMPARATIVO PICKS VIVOS — PRE vs POST piloto adepor-pilot")
    print("=" * 90)
    print()
    print(f"PRE:  {DB_PRE}")
    print(f"POST: {DB_NOW}")
    print()

    pre = picks_vivos_por_liga(DB_PRE)
    post = picks_vivos_por_liga(DB_NOW)

    todas_ligas = sorted(set(pre.keys()) | set(post.keys()))

    print(f"{'Liga':<14s} {'Recalib?':<10s} | {'Picks 1X2':<14s} | {'Picks O/U':<14s} | {'Vivas 1X2':<14s} | {'Vivas O/U':<14s} | {'Stake $':<22s}")
    print(f"{'':<14s} {'':<10s} | {'pre  -> post  d':<14s} | {'pre  -> post  d':<14s} | {'pre  -> post  d':<14s} | {'pre  -> post  d':<14s} | {'pre      -> post     d':<22s}")
    print("-" * 130)

    tot_pre = {'p1x2': 0, 'pou': 0, 'v1x2': 0, 'vou': 0, 'stake': 0}
    tot_post = {'p1x2': 0, 'pou': 0, 'v1x2': 0, 'vou': 0, 'stake': 0}

    recalib_pre = {'p1x2': 0, 'pou': 0, 'v1x2': 0, 'vou': 0, 'stake': 0}
    recalib_post = {'p1x2': 0, 'pou': 0, 'v1x2': 0, 'vou': 0, 'stake': 0}
    no_recalib_pre = {'p1x2': 0, 'pou': 0, 'v1x2': 0, 'vou': 0, 'stake': 0}
    no_recalib_post = {'p1x2': 0, 'pou': 0, 'v1x2': 0, 'vou': 0, 'stake': 0}

    for liga in todas_ligas:
        a = pre.get(liga, {'vivas_1x2': 0, 'vivas_ou': 0, 'stake': 0, 'picks_1x2': 0, 'picks_ou': 0})
        b = post.get(liga, {'vivas_1x2': 0, 'vivas_ou': 0, 'stake': 0, 'picks_1x2': 0, 'picks_ou': 0})
        d_p1x2 = b['picks_1x2'] - a['picks_1x2']
        d_pou = b['picks_ou'] - a['picks_ou']
        d_v1x2 = b['vivas_1x2'] - a['vivas_1x2']
        d_vou = b['vivas_ou'] - a['vivas_ou']
        d_st = b['stake'] - a['stake']

        recalib_marker = '* RECALIB' if liga in LIGAS_RECALIB else ''
        print(f"{liga:<14s} {recalib_marker:<10s} | "
              f"{a['picks_1x2']:>3d} -> {b['picks_1x2']:>3d}  {d_p1x2:+3d}  | "
              f"{a['picks_ou']:>3d} -> {b['picks_ou']:>3d}  {d_pou:+3d}  | "
              f"{a['vivas_1x2']:>3d} -> {b['vivas_1x2']:>3d}  {d_v1x2:+3d}  | "
              f"{a['vivas_ou']:>3d} -> {b['vivas_ou']:>3d}  {d_vou:+3d}  | "
              f"${a['stake']:>7,.0f} -> ${b['stake']:>7,.0f}  {d_st:+7,.0f}")

        for k_pre, k_post, val_pre, val_post in [
            ('p1x2', 'p1x2', a['picks_1x2'], b['picks_1x2']),
            ('pou', 'pou', a['picks_ou'], b['picks_ou']),
            ('v1x2', 'v1x2', a['vivas_1x2'], b['vivas_1x2']),
            ('vou', 'vou', a['vivas_ou'], b['vivas_ou']),
            ('stake', 'stake', a['stake'], b['stake']),
        ]:
            tot_pre[k_pre] += val_pre
            tot_post[k_post] += val_post
            if liga in LIGAS_RECALIB:
                recalib_pre[k_pre] += val_pre
                recalib_post[k_post] += val_post
            else:
                no_recalib_pre[k_pre] += val_pre
                no_recalib_post[k_post] += val_post

    print("-" * 130)
    print()
    print("=== TOTALES ===")
    print(f"GLOBAL:        picks 1X2: {tot_pre['p1x2']:>3} -> {tot_post['p1x2']:>3}   "
          f"picks O/U: {tot_pre['pou']:>3} -> {tot_post['pou']:>3}   "
          f"vivas 1X2: {tot_pre['v1x2']:>3} -> {tot_post['v1x2']:>3}   "
          f"vivas O/U: {tot_pre['vou']:>3} -> {tot_post['vou']:>3}   "
          f"stake: ${tot_pre['stake']:,.0f} -> ${tot_post['stake']:,.0f}")
    print()
    print(f"5 LIGAS RECALIBRADAS (Alemania, Argentina, Brasil, Noruega, Turquia):")
    print(f"   picks 1X2: {recalib_pre['p1x2']:>3} -> {recalib_post['p1x2']:>3}  "
          f"({recalib_post['p1x2'] - recalib_pre['p1x2']:+d})   "
          f"vivas 1X2: {recalib_pre['v1x2']:>3} -> {recalib_post['v1x2']:>3}  "
          f"({recalib_post['v1x2'] - recalib_pre['v1x2']:+d})   "
          f"stake: ${recalib_pre['stake']:,.0f} -> ${recalib_post['stake']:,.0f}  "
          f"({recalib_post['stake'] - recalib_pre['stake']:+,.0f})")
    print()
    print(f"11 LIGAS NO RECALIBRADAS (control):")
    print(f"   picks 1X2: {no_recalib_pre['p1x2']:>3} -> {no_recalib_post['p1x2']:>3}  "
          f"({no_recalib_post['p1x2'] - no_recalib_pre['p1x2']:+d})   "
          f"vivas 1X2: {no_recalib_pre['v1x2']:>3} -> {no_recalib_post['v1x2']:>3}  "
          f"({no_recalib_post['v1x2'] - no_recalib_pre['v1x2']:+d})   "
          f"stake: ${no_recalib_pre['stake']:,.0f} -> ${no_recalib_post['stake']:,.0f}  "
          f"({no_recalib_post['stake'] - no_recalib_pre['stake']:+,.0f})")


if __name__ == "__main__":
    main()
