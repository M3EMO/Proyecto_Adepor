# Nichos sostenibles cross-anio

Fecha: 2026-05-02
Sesion: 2026-05-02_team_filtros_oro
Agente: investigador_xg (filtro_oro: nichos)
Script: analisis/nichos_sostenibles_universo_expandido.py
JSON: analisis/nichos_sostenibles_universo_expandido.json

## Resumen ejecutivo

Investigacion de nichos sostenibles de yield positivo cross-anio sobre el universo
expandido post-fdco (8892 cuotas matched, 66.2 pct).
Predicciones V0 walk-forward emparejadas con cuotas:
  - 8277 matched (71.1 pct cobertura)
  - 2458 picks apostables (EV>=1.03 sobre argmax V0)

Definicion estricta de sostenibilidad:
  - yield IS pooled (2022+2023+2024) >= +10 pct sobre N>=15
  - AL MENOS 2 de 3 anios con N>=5 y yield > 0

Resultados:
  - 49 nichos pasan el filtro estricto.
  - 24 trampas one-shot detectadas.
  - NO hay datos 2026 en predicciones_walkforward: cubre 2022-2024.

## TOP 15 nichos sostenibles (priority = yield * sqrt(N))

Tabla columnas: # / Dimension / Descripcion / N_IS / yield_IS / hit / cuota_avg / AV / score

  1. LIGA_BANDA      Argentina cuota>=4.0          N=53  y=+95.4% hit=39.6% cuota=4.92  AV=3  score=6.94
  2. LIGA_PICK_BANDA Argentina pick=L cuota>=4.0   N=27  y=+110.9% hit=40.7% cuota=5.02  AV=2  score=5.77
  3. LIGA_MES        Inglaterra mes=12 (diciembre) N=42  y=+67.4% hit=50.0% cuota=3.74  AV=2  score=4.37
  4. LIGA_BIN4_PICK  Inglaterra bin4=4 pick=L      N=87  y=+44.0% hit=40.2% cuota=3.53  AV=3  score=4.11
  5. LIGA_PICK_BANDA Argentina pick=V cuota>=4.0   N=26  y=+79.2% hit=38.5% cuota=4.81  AV=2  score=4.04
  6. LIGA_MES        Argentina mes=6 (junio)        N=28  y=+72.9% hit=50.0% cuota=3.32  AV=3  score=3.86
  7. LIGA_BIN4       Inglaterra bin4=4 (oct-dic)    N=111 y=+30.2% hit=36.9% cuota=3.64  AV=2  score=3.18
  8. LIGA_BIN4_PICK  Brasil bin4=4 pick=V          N=24  y=+55.1% hit=41.7% cuota=3.49  AV=2  score=2.70
  9. LIGA_BIN4_PICK  Francia bin4=1 pick=V         N=37  y=+40.2% hit=40.5% cuota=3.59  AV=2  score=2.45
 10. EQUIPO_LOCAL   Inglaterra Wolves local        N=19  y=+56.0% hit=47.4% cuota=3.11  AV=2  score=2.44
 11. LIGA_BANDA     Inglaterra cuota 3.0-4.0       N=94  y=+25.1% hit=36.2% cuota=3.43  AV=2  score=2.43
 12. LIGA_MES       Francia mes=5 (mayo)           N=28  y=+45.5% hit=42.9% cuota=3.38  AV=2  score=2.41
 13. LIGA_BIN4      Argentina bin4=2 (abr-jun)     N=77  y=+24.1% hit=36.4% cuota=3.37  AV=3  score=2.12
 14. LIGA_MES       Alemania mes=11 (noviembre)    N=24  y=+42.1% hit=45.8% cuota=3.33  AV=2  score=2.06
 15. LIGA_BIN4      Francia bin4=2 (abr-jun)       N=67  y=+25.1% hit=37.3% cuota=3.40  AV=2  score=2.05

AV = anios validos en {2022,2023,2024}. Score = yield * sqrt(N).

## Nichos con AV=3 (los mas robustos)

Pasan el criterio en TODOS los anios 2022/2023/2024 con N>=5 y yield positivo:

  1. LIGA_BANDA Argentina cuota>=4.0       (N=53, y=+95.4%, score=6.94)
  2. LIGA_BIN4_PICK Inglaterra bin4=4 L    (N=87, y=+44.0%, score=4.11)
  3. LIGA_MES Argentina junio              (N=28, y=+72.9%, score=3.86)
  4. LIGA_BIN4 Argentina bin4=2            (N=77, y=+24.1%, score=2.12)
  5. EQUIPO_LOCAL Inglaterra Nott'm Forest local (N=24, y=+41.3%, score=2.02)
  6. LIGA_PICK_BANDA Inglaterra L 3.0-4.0   (N=64, y=+24.0%, score=1.92)
  7. LIGA_BIN4_PICK Francia bin4=2 V        (N=36, y=+22.3%, score=1.34)

Estos 7 son los candidatos de filtro_oro mas defensibles.

## Hipotesis de POR QUE

### Argentina banda 4.0+ (Nicho #1)
Cuota pick >= 4.0 implica que V0 detecta un underdog con probabilidad mayor que la
cuota implica. Drill por equipo:
  - Sarmiento Junin pick=L  N=6 yield+0.62
  - Barracas Central pick=V N=4 yield+1.73
  - Deportivo Riestra pick=L N=4 yield+2.88
Hipotesis: ineficiencias persistentes de las casas en equipos chicos del torneo
argentino. 2024 fue particularmente bueno (N=20 yield +131.2 pct).
ALERTA: Argentina actualmente bloqueada por filtro M.1 (regimen 2026 vs OOS).
Nicho deberia revisarse contra el regimen actual antes de promover.

### Inglaterra Q4 calendario (Nichos #4, #7, #11)
bin4=4 (oct-dic) en Inglaterra muestra patron consistente: Premier League en plena
fase intensiva, fixture congestion comienza, equipos top empiezan a cansarse.
V0 pick=L yield +44 pct (N=87) cuota_avg 3.53 -> picks de favoritos relativos.
Coherente con Reglas_IA.txt V5.1.2 que mantiene Q4 ENG y TUR.

### Argentina junio (mes=6, Nicho #6)
Junio es transicion campeonato Argentina (apertura/clausura corte). 28 picks 3 anios
con yield +72.9 pct hit 50 pct. Hipotesis: equipos eliminados pierden motivacion vs
peleadores por descenso/copa, V0 captura este score effect porque entreno con stats
que reflejan diferencia real, mientras casas mantienen lineas mecanicas.

### Wolves local (Nicho #10)
2022: N=9 y=+121.4 pct hit 67 pct. 2023: N=5 y+25.8 pct. 2024: N=5 y-31.4 pct.
AV=2/3, pero 2024 fue malo. Sospechoso: posible regression hacia la media en 2026.
Tratar con cautela.

### Argentina bin4=2 (abr-jun, Nicho #13)
Combinacion del fenomeno mes=6 + abril/mayo. 77 picks AV=3, yield +24.1 pct.
Util como filtro de subset apostable.

## Trampas one-shot a DESCARTAR (top 10)

  1. EQUIPO_LOCAL Bochum (Alemania)                  N=19 yield_aparente=+83.6 pct AV=1
  2. EQUIPO_LOCAL Bologna (Italia)                   N=15 yield_aparente=+54.8 pct AV=1
  3. LIGA_BANDA Argentina banda 2.0-2.5              N=15 yield_aparente=+41.9 pct AV=1
  4. LIGA_PICK_BANDA Argentina pick=L 2.0-2.5        N=15 yield_aparente=+41.9 pct AV=1
  5. EQUIPO_LOCAL Augsburg (Alemania)                N=18 yield_aparente=+36.4 pct AV=1
  6. LIGA_PICK_BANDA Turquia pick=V banda 2.5-3.0    N=19 yield_aparente=+35.5 pct AV=1
  7. LIGA_MES Italia diciembre                       N=20 yield_aparente=+34.4 pct AV=1
  8. EQUIPO_LOCAL Mallorca (Espana)                  N=21 yield_aparente=+31.2 pct AV=1
  9. LIGA_BIN4_PICK Argentina bin4=1 pick=V          N=17 yield_aparente=+29.1 pct AV=1
 10. LIGA_BIN4_PICK Argentina bin4=2 pick=L          N=61 yield_aparente=+26.7 pct AV=1

Lectura: estas combinaciones lucen rentables en el agregado pooled, pero al
desglosar por anio el yield positivo proviene exclusivamente de un anio (tipicamente
2022 o 2023 con muestra grande), mientras los otros anios son neutros o negativos.
Promover sin fundamento de causalidad probablemente colapse en el siguiente bloque.

## Caveats

  1. Sin validacion 2026: predicciones_walkforward solo cubre 2022-2024.
     Confirmar nichos requiere correr el motor sobre 2025-2026 con cuotas matched.
  2. V0 nunca elige X: distribucion picks revela que el motor productivo nunca
     selecciona empate (argmax probabilidad). Resultados sobre pick=X son inviables
     sin cambiar arquitectura (V12 Layer 2 Turquia, o futuro override empate).
  3. Argentina bloqueada por M.1: Argentina concentra muchos nichos top (#1, #2,
     #5, #6, #13) pero esta excluida del subset apostable actual.
  4. Cobertura naming Argentina/Brasil: la JOIN normalizada no cubre todas las
     variantes (Atl. Tucuman vs Atletico Tucuman). Universo real podria ser mayor.
  5. Multiple testing: ~8 dimensiones x ~20 ligas/equipos = ~160 tests.
     Algunos nichos pueden ser falsos positivos. Validar OOS antes de promover.

## Recomendaciones (sin cambios al motor)

Promovibles a SHADOW (subset apostable filtrado, observacion N>=80):
  - Inglaterra bin4=4 pick=L (Nicho #4, AV=3, score 4.11) - alineado con V5.1.2.
  - Inglaterra Q4 generico (Nicho #7, N=111, AV=2) - corrobora #4 a nivel agregado.

Investigar regimen actual antes de promover:
  - Argentina banda 4.0+ (Nicho #1) - excelente IS pero filtro M.1 lo bloquea.
  - Argentina junio + bin4=2 - posible ventana temporal sostenible.

Descartar:
  - Todos los nichos one-shot (24 trampas listadas).
  - Nichos con AV=2 dependientes de un solo equipo (Wolves: 2022 outlier).

## Test de validacion propuesto

Para cada nicho promovible:
  1. Reproducir el calculo en partidos_backtest (N=703 con cuotas reales 2025-2026).
  2. Si N_subset >= 5 y yield_subset > 0 -> SHADOW.
  3. Si N_subset < 5 -> esperar hasta acumular muestra antes de decidir.
  4. Trigger de promocion: N_shadow >= 80 con yield > 0.10 sostenido.

## Reproducibilidad

    cd C:/Users/map12/Desktop/Proyecto_Adepor
    python analisis/nichos_sostenibles_universo_expandido.py

Outputs:
  - stdout: tabla de nichos + tabla de trampas
  - JSON: analisis/nichos_sostenibles_universo_expandido.json
