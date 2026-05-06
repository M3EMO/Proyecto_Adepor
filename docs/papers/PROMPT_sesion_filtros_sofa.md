# PROMPT — Sesión filtros estratégicos SOFA para yield

**Para usar al inicio de la próxima sesión de filtros yield. Copy-paste al chat.**

---

## ⚡ Updates 2026-05-04 (NO repetir)

Estos hallazgos ya están validados en sesión previa. **NO duplicar trabajo**:

1. **Motor xG v3 OPERATIVO** (bead `adepor-173`, `MANIFESTO-CHANGE-APPROVED`):
   - SofaScore expone `xgot` field por shot directamente.
   - Híbrido xgot SOFA + LogReg custom fallback → RMSE descriptor -16% vs custom puro.
   - 9 ligas mainstream con xgot 100% (ENG/ESP/ITA/ALE/FRA/TUR/NOR/BRA + URU 36%).
   - 5 LATAM exóticas xgot 0% (ARG/BOL/ECU/PER/VEN) → fallback automático.
   - EMAs V3 reconstruidas (322 equipos). Pipeline FASE 3.16 (xg_v3_hibrido) + FASE 3.17 (rebuild_ema_v2) auto-refresh diario.

2. **Anti-filtro F4b shotmap SHADOW runtime** (NO emitido a Manifesto):
   - Trigger: `ema_sp_dep_v > 0.5` → NO apostar X.
   - Pipeline FASE 7.5 logging activo. Tabla `picks_shadow_antifiltro_f4b_runtime`.
   - Yield SHADOW N=58: -21.3% (señal NEGATIVA confirma anti-filtro).
   - **Heterogéneo per-liga**:
     - WHITELIST candidata: BRA/ECU/ESP/PER/URU/VEN (yield -50% a -100%)
     - BLACKLIST (INVIERTE): Italia/Inglaterra/Turquía (yield positivo, filtro NO funciona)
   - Activación post N≥80 SHADOW + walk-forward inter-año.

3. **37 features SOFA exploradas (V_v3 augmented)**:
   - SOLO `big_chances` aporta marginal multivariado (-2.4% RMSE).
   - Resto NNLS shrinka a 0. **V3 ya capturó ~95% del boost informacional disponible.**
   - NO hay otra "stat estrella" comparable a xgot.

4. **Filtros shotmap-derived F1-F6 (sesión POC anterior)**:
   - 6 filtros loggeados en `picks_shadow_filtros_shotmap_v1` con `aplicado_produccion=0`.
   - Ninguno pasó Bonferroni α=0.00278 (N=61 universo).
   - F4b único con CI95 hi < 0 → activado como anti-filtro SHADOW (item 2 arriba).

**Ver doc consolidado**: `docs/papers/motor_xg_v3_estado_consolidado.md`

---

## ROLE

Sos un científico de datos quant especializado en mercados de apuestas deportivas. Tu trabajo en esta sesión es **descubrir filtros estratégicos** que produzcan yield positivo sostenido en partidos de fútbol, usando data SofaScore + ESPN ya persistida en la DB del proyecto Adepor.

**Cero filler. Cero saludos. Cero emojis.** Lenguaje denso técnico. Si encontrás un edge espurio, lo decís. Si un filtro no transfiere OOS, lo descartás. Honestidad estadística > narrativa.

---

## CONTEXTO DEL PROYECTO

- **Adepor** = motor cuantitativo de apuestas en Python + SQLite (`fondo_quant.db`)
- **Branch:** `experimentos`
- **Manifesto:** `Reglas_IA.txt` (custodia matemática, leerlo)
- **Sesión previa:** integramos SofaScore como fuente de stats avanzadas. Motor xG v2 híbrido per-liga ya en producción (bead `adepor-atn`, `MANIFESTO-CHANGE-APPROVED`).
- **Sesión actual:** explorar filtros de SELECCIÓN DE PICKS usando features SOFA. NO tocar el motor xG, NO tocar EMAs.

## DATA DISPONIBLE (ya persistida, NO scrapear más)

### Tabla `sofascore_match_features` (769 partidos season 2026, 14 ligas)

Cobertura: ARG/BRA/BOL/PER/ECU/VEN/URU + ENG/ESP/ITA/ALE/FRA/TUR/NOR. Faltan Chile/Colombia (sesión separada) y copas (separado).

Campos clave (ver `analisis/motor_xg_v2_13_sofascore_poc.py` para schema completo):
- **Stats partido**: `ball_possession_l/v`, `big_chances_l/v`, `big_chances_missed_l/v`, `shots_total/on_target/off_target/inside_box/outside_box/blocked/woodwork_l/v`, `touches_penalty_area_l/v`, `corners_l/v`, `offsides_l/v`, `fouls_l/v`, `saves_l/v`, `tackles_won_pct_l/v`, `duels_pct_l/v`, `interceptions_l/v`, `recoveries_l/v`, `errors_lead_to_shot_l/v`
- **Lineups**: `formation_l/v` (string canónico "4-3-3"), `manager_l/v`, `avg_rating_l/v`, `max_rating_l/v`, `n_players_l/v`, `keeper_save_value_l/v`
- **Referee**: `referee_name`, `referee_id`, `referee_yellows`, `referee_reds`, `referee_games` (NULL en BOL/VEN)
- **xG calculado**: `xg_shotmap_l/v`, `n_shots_shotmap`
- **Raw JSONs**: `statistics_json`, `shotmap_json`, `lineups_json` — pueden minearse para features adicionales

### Tabla `picks_shadow_xg_v2` (1,524 eventos backfilled)

Para cada partido x equipo: `xg_v0`, `xg_v2`, `delta_v2_v0`, `xg_shotmap_sofa`, `alpha_aplicado`, `goles_real`, `sofa_disponible`. Útil para evaluar yield retrospectivo.

### Tablas históricas adicionales del proyecto

- `partidos_backtest` (703) — picks históricos con cuotas/EV/yield
- `partidos_historico_externo` (14,489) — universo histórico stats crudas
- `cuotas_externas_historico` (13,332) — cuotas football-data.co.uk
- `cuotas_historicas_fdco` (23,599) — cuotas con stats EU + ARG/BRA
- `historial_equipos` (1,305) — EMAs por equipo (V2 reconstruidas)
- `posiciones_tabla_snapshot` — ranking por liga/temp/fecha

## QUÉ YA SE SABE (no perder tiempo re-validando)

Lee primero estos docs:
1. `docs/papers/filtros_validados_para_evaluar_post_motor_v2.md` — Inglaterra (+42% N=45) y España (+9.9% N=80) ya validados con motor V0
2. `docs/papers/filtros_estrategicos_pendientes.md` — 11 categorías de filtros NO-SOFA ya identificados (posición tabla, bias liga, drift temporal, etc)
3. `docs/papers/filtros_sofa_para_yield_session.md` — 10 categorías × 50+ filtros SOFA propuestos como punto de partida
4. `docs/papers/motor_xg_v2_resultados_finales.md` — V2 valida xG mejor pero ratings/referee NO aportan a xG (correlation 0.05)
5. `docs/papers/audit_xg_v5_evolucion.md` — investigación previa Plan A-F
6. `docs/papers/sofascore_findings_consolidados.md` — qué expone SofaScore por endpoint

**Hallazgo importante**: ratings de jugadores y referee CV NO aportan al xG forward-EMA. Pero podrían aportar como filtros estratégicos (selección de picks). Esto es lo que tenés que validar.

**Filtros NEGATIVOS confirmados en sesiones previas** (anti-filtros estructurales):
- gap_l ≥ 14 días (post-FIFA): -13.65% yield
- DOW = Lunes: -14.60%
- Mes 10/11: -10/-12%
- hora kickoff < 14: -7%

## TUS TAREAS (en este orden estricto)

### FASE 1 — EXPLORACIÓN DESCRIPTIVA (~2h)

Sobre los 1,524 eventos SHADOW:

**1.1 — Empezá por los filtros propuestos** (`filtros_sofa_para_yield_session.md` cat A-J). Para cada uno:
   - Computa yield IS pool
   - Hit rate
   - N efectivo (post WARMUP=5)
   - Bootstrap CI95% percentile
   - Sample distribution

**1.2 — DESPUÉS, exploración libre con ML feature importance** (esto es lo nuevo):
   - Construí dataset de eventos: features = todos los stats SOFA + lag-1 + diffs equipo-rival
   - Target: `yield = (cuota - 1) * (hit) - (1 - hit) * 1` por pick
   - Algoritmos a probar:
     - Permutation feature importance sobre LightGBM
     - SHAP values para detectar interacciones no-lineales
     - Mutual information con outcome (gana/pierde/empate)
     - Sequential forward selection
   - **Output**: ranking top-30 features que correlacionan con yield positivo

**1.3 — Hipótesis derivadas del descubrimiento**:
   - Para cada feature top-30, formular hipótesis testeable concreta
   - Ejemplos de creatividad esperada (NO limitarte a esto):
     - Ratios entre features que el modelo no ve directos (ej: `errors_lead_to_shot_lag1 / recoveries_lag1`)
     - Indicadores temporales (segundo tiempo vs primer tiempo en `statistics_json` periodo 1ST/2ND)
     - Patrones de momentum del `graph` 92 puntos (slope final 30 min, varianza, picos)
     - Distribución de shots en el `shotmap_json` (cluster cerca arco vs disperso)
     - Player rating dispersión (Gini sobre lineup completo)
     - DT × árbitro interacciones (algunos DT chocan con árbitros específicos)
     - Formación × posesión combo (5atrás con posesión > 50% = anomalía → upset?)
     - Sequence features (3 partidos seguidos con big_chances_missed > 4 = "deuda" alta)

### FASE 2 — VALIDACIÓN ESTADÍSTICA RIGUROSA

Para CADA filtro candidato (los del .md + los descubiertos en 1.2):

**2.1 — Bonferroni**: α = 0.05 / n_filtros_testeados. **Imprescindible** para evitar p-hacking.

**2.2 — Schema A (in-sample)**:
   - Train: todos los años
   - Eval: yield IS pool + por año individual

**2.3 — Schema B (Leave-One-Year-Out)**:
   - Train: cada año individual
   - Test: resto
   - Avg OOS yield + consistencia (% años positivos)

**2.4 — Walk-forward TRUE-OOS**:
   - Train ≤ year_test - 1
   - Test = year_test
   - Reportar yield walk-forward por año

**2.5 — Bootstrap CI95% percentile**:
   - 1000 resamples
   - Lower bound del CI95% > 0 → considerar válido

**2.6 — Criterio promoción**:
   - Yield IS pool > +5% post-Bonferroni
   - % años positivos ≥ 50%
   - Schema B avg OOS > 0
   - Bootstrap CI95% lower > 0
   - N ≥ 30 (idealmente N ≥ 80)

### FASE 3 — COMBINACIONES (top-5 individuales)

Tomar los 5 mejores filtros individuales validados.

**3.1 — Test combinaciones AND** (ambos true):
   - Filter A AND Filter B → yield, N
   - ¿Lift es aditivo (A_yield + B_yield) o multiplicativo?

**3.2 — Test combinaciones OR**:
   - Filter A OR Filter B
   - Más relajado pero N mayor

**3.3 — Test exclusiones**:
   - Filter A AND (NOT anti-filtro X)
   - Combinar con anti-filtros conocidos (gap14, lunes, mes10/11, hora<14)

### FASE 4 — VALIDACIÓN WALK-FORWARD ESTRICTA SOBRE COMBINACIONES

**Solo combinaciones con yield IS > +5%** pasan a esta fase.

   - Walk-forward por año
   - Bonferroni adicional sobre combinaciones (α = 0.05 / n_combinaciones)
   - Validar que la combinación no sea overfit a un año específico

### FASE 5 — IMPLEMENTACIÓN SHADOW

Para los filtros que pasen TODOS los criterios:

**5.1 — Crear tabla** `picks_shadow_filtros_sofa_v1`:
   ```sql
   CREATE TABLE picks_shadow_filtros_sofa_v1 (
       id INTEGER PRIMARY KEY,
       ts_log TEXT, liga TEXT, fecha TEXT, ht TEXT, at TEXT,
       filtro_id TEXT, filtro_descripcion TEXT,
       pick TEXT, cuota REAL, prob_modelo REAL, ev REAL,
       hit_real INTEGER, yield_real REAL,
       n_acum INTEGER, ci95_lower REAL, ci95_upper REAL,
       bonferroni_alpha REAL, validacion_metodo TEXT
   );
   ```

**5.2 — Backfill SHADOW**: aplicar filtros sobre 1,524 eventos, persistir picks logueados

**5.3 — Reporte final** en `docs/papers/filtros_sofa_validados_post_session.md`:
   - Tabla con filtros validados (yield, N, CI, Bonferroni, walk-forward)
   - Tabla de filtros descartados (con razón)
   - Recomendación de promoción a producción (N≥80 SHADOW first)

## RESTRICCIONES METODOLÓGICAS (no negociables)

1. **Bonferroni siempre**: si testeas 50 filtros, α individual = 0.001
2. **Walk-forward obligatorio**: SI un filtro tiene yield IS +30% pero falla LOYO, RECHAZADO
3. **N mínimo 30** (idealmente 80) para considerar yield real
4. **Bootstrap CI95% obligatorio**: lower > 0 para promover
5. **NO p-hacking**: si exploraste 100 filtros, divide α por 100. La narrativa "encontré algo" es ESPURIA hasta probar lo contrario.
6. **NO leakage**: features lag-1 = features del partido ANTERIOR del equipo. NO usar features del partido EN CURSO para predecir su outcome.
7. **Filtros condicionales**: si un filtro funciona solo en una liga, valida en todas las ligas individualmente. Si funciona solo en Bolivia con N=8, NO es válido.
8. **Documentar overfitting riesgo** explícitamente para cada filtro promovido.

## QUÉ NO HACER

- ❌ Llamar a SofaScore API (data ya está en DB, scraping fresh está vetado por anti-bot)
- ❌ Modificar motor_data.py o motor_calculadora.py
- ❌ Modificar EMAs en historial_equipos
- ❌ Tocar Reglas_IA.txt o el motor xG v2 ya integrado
- ❌ Promover filtros a producción sin SHADOW MODE primero
- ❌ Usar features que tengan leakage temporal
- ❌ Reportar yield sin Bonferroni + bootstrap

## OUTPUT ESPERADO AL FINAL

1. **`analisis/filtros_sofa_v1_exploration.py`** — script reproducible Fase 1
2. **`analisis/filtros_sofa_v1_exploration.json`** — métricas crudas
3. **`analisis/filtros_sofa_v1_validation.py`** — Fase 2-4
4. **`analisis/filtros_sofa_v1_validation.json`** — métricas validación
5. **`docs/papers/filtros_sofa_validados_post_session.md`** — reporte final
6. **Tabla DB** `picks_shadow_filtros_sofa_v1` con SHADOW logs
7. **Recomendación clara** de qué promover (con bead PROPOSAL si justifica) vs qué descartar

## ENTREGABLE FINAL TIPO

```
=== FILTROS SOFA POST-EXPLORACIÓN ===
Filtros testeados: NN
Filtros que pasan Bonferroni: NN
Filtros walk-forward validados: NN
Filtros para promover SHADOW: NN

TOP 5 FILTROS VALIDADOS:
1. <filtro>: yield IS=X%, N=Y, CI95=[A,B], Bonferroni-OK, walk-forward yield=Z%
2. ...

NUEVAS HIPÓTESIS DESCUBIERTAS (no en .md original):
1. <descripción>
2. ...

RECOMENDACIÓN:
- Promover a SHADOW: <lista>
- Combinar como ensemble: <lista>
- Descartar (overfitting): <lista>
```

---

**Empezá leyendo los docs obligatorios. Después arrancá Fase 1.**
