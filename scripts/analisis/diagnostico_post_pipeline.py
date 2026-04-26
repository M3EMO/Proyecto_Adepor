"""Diagnostico ad-hoc post-pipeline para verificar efecto del piloto adepor-pilot."""
import sqlite3
con = sqlite3.connect('fondo_quant.db')

print('=== LIQUIDACIONES RECIENTES (ultimas 24h por fecha_creacion) ===')
r = con.execute("""
    SELECT COUNT(*) FROM partidos_backtest
    WHERE estado='Liquidado' AND fecha_creacion >= datetime('now','-1 day')
""").fetchone()[0]
print(f'  Partidos creados en las ultimas 24h y ya Liquidados: {r}')

r = con.execute("""
    SELECT COUNT(*), SUM(stake_1x2 + stake_ou) FROM partidos_backtest
    WHERE estado='Liquidado' AND (stake_1x2>0 OR stake_ou>0)
""").fetchone()
print(f'  Apuestas con stake>0 ya Liquidadas (TODAS hist): {r[0]} con stake total ${r[1] or 0:,.0f}')

print()
print('=== PARTIDOS Calculados con [APOSTAR] (5 ligas recalibradas) ===')
r = con.execute("""
    SELECT pais, apuesta_1x2, apuesta_ou, prob_1, prob_x, prob_2, stake_1x2, stake_ou, fecha, local, visita
    FROM partidos_backtest
    WHERE estado='Calculado' AND (apuesta_1x2 LIKE '[APOSTAR]%' OR apuesta_ou LIKE '[APOSTAR]%')
      AND pais IN ('Alemania','Argentina','Brasil','Noruega','Turquia')
    ORDER BY pais, fecha
""").fetchall()
print(f'Total picks valid en 5 ligas recalibradas: {len(r)}')
for row in r:
    print(f'  [{row[0]:<10s}] {row[8]}  {row[9]} vs {row[10]}')
    print(f'    probs: 1={row[3]:.3f}  x={row[4]:.3f}  2={row[5]:.3f}')
    print(f'    pick 1X2: {row[1] or "—":<60s} stake={row[6] or 0}')
    print(f'    pick O/U: {row[2] or "—":<60s} stake={row[7] or 0}')

print()
print('=== PARTIDOS Calculados (5 ligas recalibradas) — distribucion de motivos PASAR ===')
r = con.execute("""
    SELECT pais, apuesta_1x2, COUNT(*) as n
    FROM partidos_backtest
    WHERE estado='Calculado' AND apuesta_1x2 IS NOT NULL
      AND pais IN ('Alemania','Argentina','Brasil','Noruega','Turquia')
    GROUP BY pais, apuesta_1x2
    ORDER BY pais, n DESC
""").fetchall()
for row in r:
    print(f'  [{row[0]:<10s}] {row[1]:<50s} N={row[2]}')

print()
print('=== Partidos Calculados sin cuotas (no entran a evaluacion) ===')
r = con.execute("""
    SELECT pais, COUNT(*)
    FROM partidos_backtest
    WHERE estado='Calculado' AND (cuota_1 IS NULL OR cuota_1 = 0)
      AND pais IN ('Alemania','Argentina','Brasil','Noruega','Turquia')
    GROUP BY pais
""").fetchall()
for row in r:
    print(f'  {row[0]:<10s} {row[1]} partidos sin cuotas 1X2')
