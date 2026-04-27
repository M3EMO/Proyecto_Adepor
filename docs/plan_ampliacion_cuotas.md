# Plan: Ampliar N de cuotas históricas para validación H4

## Estado actual

- **N=127 partidos_backtest** con cuotas + stats raw + resultado.
- Yield H4 = +0.246, hit 0.520. Pero **CI95 ~ ±10pp** — no estadísticamente concluyente.
- Para promover H4 a producción se necesita **N ≥ 500** OOS estricto.

## Fuentes disponibles para extender

### A. football-data.co.uk (cuotas batch CSVs)

**Cobertura efectiva F1 (post-correccion adepor-a0i)**:

Originalmente listamos 9 codigos. Auditoria detecto:
- **N1 = Eredivisie holandesa, NO Noruega** (bug `adepor-a0i`). Eredivisie no esta en
  Adepor → drop.
- **E1 = English Championship**: no esta en `partidos_historico_externo` → JOIN inutil
  para validacion H4 → drop.
- **P1 = Portugal Primeira**: idem, no en `partidos_historico_externo` → drop.

Net F1 scope (7 ligas):
- **6 ligas mmz4281** (formato per-temporada con opening+closing+8 bookies):
  E0 (Inglaterra), D1 (Alemania), I1 (Italia), SP1 (Espana), F1 (Francia), T1 (Turquia)
- **1 liga formato extra** (`/new/NOR.csv`, multi-temp, closing only):
  NOR (Noruega — Eliteserien). No tiene SoT/shots/corners → solo cuotas CLV; queda
  fuera de H4 V12 backtest pero util para V0 + CLV monitoring.

**Cuotas disponibles mmz4281** (per partido, schema rico):
- B365H/D/A (Bet365 opening), B365CH/CD/CA (Bet365 closing)
- BWH/D/A (Bwin), IWH/D/A (InterWetten)
- PSH/D/A (Pinnacle opening), PSCH/CD/CA (Pinnacle closing — ideal CLV)
- WHH/D/A (William Hill), VCH/D/A (VC Bet)
- MaxH/D/A (max), AvgH/D/A (avg)
- (closing variants tras 2019 con sufijo C)

**Cuotas formato extra (`/new/<COD>.csv`)** — schema reducido:
- HG, AG, Res (goles + resultado, **sin** SoT/shots/corners)
- PSCH, PSCD, PSCA (Pinnacle closing)
- MaxCH/CD/CA, AvgCH/CD/CA (max y avg closing)
- B365CH/CD/CA (Bet365 closing) — algunas filas vacias en temps mas viejas

**Implementacion**:
- Script `scripts/scraper_football_data_cuotas.py`:
  - Para cada (liga, temporada) mmz4281 en {2021, 2022, 2023, 2024}:
    - Descargar CSV `mmz4281/{tempY1Y2}/<COD>.csv`
    - Parse + INSERT en `cuotas_externas_historico` con `formato_csv='mmz4281'`
  - Para NOR (formato `/new/NOR.csv`): descarga unica + filtro `Season IN (2021..2024)`
    + INSERT con `formato_csv='new'`
- N esperado tras scraping:
  - mmz4281: 6 ligas × ~380 partidos/temp × 4 temps ≈ **9,100 filas**
  - NOR: ~240 partidos/temp × 4 temps ≈ **960 filas**
  - Total: **~10,000 filas con cuotas**

**Alineacion con partidos_historico_externo**:
- JOIN por (liga, fecha, ht, at) tras normalizacion con `limpiar_texto`.
- Match esperado ~95% (6 EUR mmz4281), 0% NOR (Noruega no esta en historico_externo →
  scraping NOR es paralelo, no se valida H4 con esa liga).

**Esfuerzo**: 1 sesion scraper + 1 sesion migracion + JOIN + audit.

### B. API-Football historical (alternativa)

**Cobertura**: 100+ ligas, datos detallados.

**Cuotas**: endpoint `/odds`, requiere SUSCRIPCIÓN PRO (~$15/mes para historical). Free plan limitado a 10 reqs/día.

**No aplica para 12,000 partidos sin pagar.**

### C. Sofascore / Whoscored (scraping web)

**Cuotas**: solo cierre, no históricas detalladas. Lentos (rate limit), riesgo de bloqueo.

**Recomendación**: NO usar como primario.

## Plan recomendado

### Fase 1: scraper football-data.co.uk (1 sesión) — EJECUTADA 2026-04-26

```bash
# 6 ligas mmz4281 (full schema con opening+closing+8 bookies)
py scripts/scraper_football_data_cuotas.py --temporadas 2021,2022,2023,2024 --ligas E0,D1,I1,SP1,F1,T1

# 3 ligas formato /new/ (closing only, multi-temp en un CSV)
# - NOR: Noruega (sin stats, solo CLV)
# - ARG: Argentina (Liga Profesional, full year — pero PHE solo cubre Clausura)
# - BRA: Brasil (Serie A, alineado con PHE 100%)
py scripts/scraper_football_data_cuotas.py --extra NOR,ARG,BRA --temporadas 2021,2022,2023,2024
```

Output final 2026-04-26: `cuotas_externas_historico` con **13,332 filas**:
- 8,600 mmz4281 (6 EUR)
- 967 NOR
- 3,765 ARG+BRA (con aliases CSV→ESPN para 30 nombres)

JOIN match con `partidos_historico_externo`:
- 6 EUR mmz4281: **100%** (8,600/8,600)
- ARG temp=2024: **90.5%** PHE (sólo Clausura cubierta por ESPN)
- BRA temp=2024: **87.4%** PHE
- NOR: 0% (Noruega no está en historico_externo, scraping paralelo solo para CLV)

LATAM secundarias (Chile/Col/Bol/Ecu/Per/Uru/Ven): **NO cubiertas por football-data**.
Validación H4 imposible bajo este protocolo. Statu quo V0 raw en producción.

### Fase 2: backfill yield walk-forward (1 sesión) — EJECUTADA 2026-04-26

Implementado en 3 scripts iterativos:
- `analisis/yield_v0_v12_backtest_extendido.py` (6 EUR, N=1.806)
- `analisis/audit_yield_F2_sweep_y_ci.py` (sweep H4 + CI95 por liga)
- `analisis/audit_yield_F2_filtro_liga.py` (politicas de filtro)
- `analisis/yield_v0_v12_F2_completo.py` (8 ligas + LATAM, N=2.348)

Hallazgos clave:
- H4 sin filtro: yield +0.011 (CI95 [-0.040, +0.060]) — NO valida la propuesta original.
- Heterogeneidad EUR: TUR/ITA/FRA/ENG ganan, DE/ES pierden, ARG marginal negativa, BRA break-even.
- Política dominante (Drop_negs): H4 +0.066 [+0.001, +0.130] — primer significativo CI95.

CI95 final ~ ±5pp por liga, ~±5pp agregado. Mejor que ±10pp con N=127, pero no ±2-3pp del plan
original. Razon: yield es noisy aún con N grande.

### Fase 3: decisión PROPOSAL — APROBADA Y APLICADA (2026-04-26)

Resultado F2 invalida adepor-617 H4-standalone. Sucesor: **adepor-edk** APROBADO con:

- **Layer 1 (filtro liga):** RECHAZADO por usuario ("mantener todas las ligas activas").
- **Layer 2 (V12 standalone Turquía):** **APLICADO en producción.** Manifesto V4.6 → V5.0
  con nueva §L. Override `arch_decision_per_liga = '{"Turquia": "V12"}'` en
  `config_motor_valores`. Implementación en `motor_calculadora.py:1397-1418` (fail-silent).
  Evidencia: walk-forward OOS Pinnacle 2024 N=271, V12 yield +0.116 CI95 [+0.003, +0.242] ★.
- **Layer 3 (H4 X-rescue):** queda en SHADOW. NO aplicado a producción (yield agregado
  +0.012 marginal, CI95 incluye 0).

Activos generados en aplicación V5.0:
- Snapshot pre-cambio: `snapshots/fondo_quant_20260426_224017_pre_v5_layer2_v12_tur.db`
- SHA-256 Manifesto: `c1f3a1d2...` → `6609ee91...`
- `bd adepor-edk` con label `approved-by-lead`
- Bug colateral resuelto: `config_motor.py::_coerce` no manejaba `tipo='json'` → cambiado
  el config flag a `tipo='text'` (motor parsea via `json.loads` localmente).

Validación end-to-end (corrida real 2026-04-26):
- 8 partidos turcos pendientes re-evaluados con V12 override.
- 3 partidos cambiaron argmax (Gaziantep FK 2→1, Samsunspor 1→2, Trabzonspor 1→2).
- Logs `[ARCH-V5.0:V12]` visibles en stdout durante corrida del motor.

Validación 2025+ pendiente (data no disponible aún) — re-evaluar en 6 meses para
confirmar yield V12 TUR sostenido o revertir override si degradación observada.

Evidencia uniforme (sin filtro liga, 8 ligas, N=2.348):
- V0 statu quo: yield -0.003 [-0.046, +0.043]
- L2 sólo (V12 TUR + V0 resto): yield -0.000 [-0.042, +0.046]
- L2+L3 propuesta original: yield +0.012 [-0.034, +0.057]

## Rollout estimado

| Fase | Esfuerzo | Resultado esperado |
|---|---|---|
| F1 scraper | 4-6 hs | tabla cuotas_externas_historico ~12k filas |
| F2 backfill yield | 2-3 hs | yield H4/V0/V12 OOS N≥3000 con CI95 reportado |
| F3 decisión | 1 hs | aprobar/rechazar adepor-617 con evidencia |

## Riesgos

| Riesgo | Mitigación |
|---|---|
| Cobertura ligas LATAM baja en football-data | Usar solo EUR para validación robusta. LATAM seguirá con V0 raw. |
| Noruega NOR.csv sin stats SoT/shots/corners | NOR queda fuera de H4 V12 backtest. Solo se usa para CLV monitoring sobre V0. |
| N1 era Eredivisie no Noruega (`adepor-a0i`) | Corregido: dropeado del scope F1. Re-scraping de Noruega via `/new/NOR.csv` correcto. |
| Bookmakers cambiaron entre 2021-2024 (margen evolución) | Usar Pinnacle (closing line) que es el estándar de mercado. |
| Match imperfecto entre nombres equipos (4 fuentes diferentes) | gestor_nombres.diccionario_equipos ya maneja variantes. |

## Próximo paso

Solo cuando tengamos F1+F2 listo, re-evaluar PROPOSAL `adepor-617`. Mientras tanto, H4 sigue como SHADOW.
