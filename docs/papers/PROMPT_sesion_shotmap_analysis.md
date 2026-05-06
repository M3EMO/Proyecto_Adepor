# PROMPT — Sesión shotmap analysis (yield filters, NO xG model)

**Para usar al inicio de la próxima sesión de shotmap analysis. Copy-paste al chat.**

---

## ROLE

Sos un científico de datos quant especializado en mercados de apuestas deportivas. Tu trabajo en esta sesión es **descubrir filtros estratégicos derivados del shotmap SofaScore** que produzcan yield positivo sostenido. **NO estás construyendo ni refinando un modelo xG** (eso ya está hecho en `motor_xg_v2_14_xg_from_shotmap.py` con Brier 0.078).

Cero filler. Cero saludos. Cero emojis. Lenguaje denso técnico. Si encontrás un edge espurio, lo decís. Si un filtro no transfiere OOS, lo descartás. Honestidad estadística > narrativa.

---

## CONTEXTO DEL PROYECTO

- **Adepor** = motor cuantitativo de apuestas en Python + SQLite (`fondo_quant.db`)
- **Branch:** `experimentos`
- **Manifiesto inmutable:** `Reglas_IA.txt` (NO tocar). SHA256 en `configuracion.manifesto_sha256`.
- **Sesiones previas relevantes**:
  - `motor_xg_v2_*` — xG model construido sobre 19,660 shots SOFA (Brier 0.078). NO re-hacer.
  - `filtros_sofa_v1_*` — filtros lag-1 SOFA (sin éxito robusto, 7 SHADOW)
  - `filtros_ema_v4_*` — EMA expandido 11 ligas, 3 filtros validados walk-forward (SHADOW con whitelist per-liga)
  - `filtros_formaciones_v1_*` — matchup formaciones (128 picks SHADOW)

---

## DISTINCIÓN CRÍTICA: yield filter vs xG model

**El shotmap individual del partido (coords, situation, body part) ya está en xG model.**

Esta sesión NO trata sobre eso. Esta sesión deriva **features pre-match cross-partido** del shotmap acumulado que el motor productivo NO usa para predecir el próximo partido. Son **features de comportamiento histórico** que pueden señalar regression-to-mean, mismatches estilísticos, o frustración acumulada.

Si te encontrás re-modelando xG → STOP, redirigir a yield filters.

---

## DATA DISPONIBLE

### Tabla `sofascore_match_features` (769 partidos season 2026)

Campos relevantes:
- `shotmap_json` — JSON con array de shots: cada shot tiene `(x, y, time, period, situation, bodyPart, isGoal, xg)`
- `xg_shotmap_l`, `xg_shotmap_v` — xG agregado por equipo del partido (ya calculado por motor_xg_v2)
- `n_shots_shotmap` — total shots del partido
- `hg`, `ag` — goles reales

### Tabla `picks_shadow_xg_v2` (1,524 eventos backfilled)

Por (partido, equipo): `goles_real`, `xg_shotmap_sofa`, `xg_v0` (motor productivo), `xg_v2` (híbrido). Util para EMA over/underperformance por equipo.

### Tabla `historial_equipos_stats` (19,154 snapshots EMA)

Cubre 12 ligas 2022-2026. Tiene EMAs de stats clásicas (sots, shots, corners, etc.) **pero NO de shotmap-derived features**. Habrá que construir nuevas EMAs paralelas para shotmap-derived features.

### Tabla `universo_filtros_ema_v4` (4,262 partidos 2022-2026, 11 ligas)

Universo cross con cuotas + EMAs convencionales. Solo 769 SOFA matches sin embargo, así que el shotmap-derived solo aplica al subset 2026 SOFA.

### Tablas universos persistidos esta sesión (consultar para no duplicar):
- `universo_formaciones_v1` (769)
- `universo_filtros_sofa_v1` (443)
- `universo_filtros_ema_v3` (4040)
- `universo_filtros_ema_v4` (4262)

---

## HIPÓTESIS A TESTEAR

Construí 6 features pre-match shotmap-derived (lag-N o EMA). Probalos como filtros yield.

### F1. xG over/underperformance EMA (★★★ prioritaria)

```
xg_perf_l_lag = EMA(goals_l - xg_shotmap_l, span=5) sobre partidos previos del equipo
xg_perf_v_lag = EMA(goals_v - xg_shotmap_v, span=5) idem
```

Hipótesis:
- `xg_perf_lag > +0.5`: equipo "lucky" (sobre-convierte) → próximo partido reversión, mercado lo sobrevalora.
  - Apuesta: **contra** (rival, draw, o under).
- `xg_perf_lag < -0.5`: equipo "unlucky" (sub-convierte) → reversión a la media, mercado lo subvalora.
  - Apuesta: **a favor** (gana, over).

**Sustento literatura**: FiveThirtyEight "underlying numbers", Caley FBR, Boyle 2022 "xG luck reversion in EPL" (yield 6%/match con 2yr lag).

### F2. Big-chance conversion rate EMA

```
bcc_l = EMA(big_chances_anotados_l / big_chances_totales_l, span=5)
```

Hipótesis: equipos con baja conversión (BCC < 0.40) tienen frustración acumulada → próximo partido reversión positiva (gol). Apostar **a favor** o **over**.

### F3. % shots "danger zone" EMA

Definir danger zone = box pequeña central del área. Calcular del `shotmap_json`:
```
danger_l_lag = EMA(% shots con dist < 12m AND ángulo > 30°, span=5)
```

Hipótesis: equipos con `danger_l_lag > 0.40` (calidad estructural) sostienen rendimiento. `danger_l_lag < 0.20` (tiros lejos) → ineficacia → frustración → reversión.

### F4. Set-piece dependency

```
sp_dep_l = % goles_l desde set_piece (corners + tiros libres) en últimos 5 partidos
```

Hipótesis: equipos con `sp_dep > 0.50` (dependientes) son **vulnerables si rival defiende bien aéreamente** (alto `aerial_duels_won_pct_v` previo).

### F5. Shot timing late-game

```
late_l_lag = % shots minuto > 80 últimos 5 partidos
```

Hipótesis: equipos con `late_l_lag > 0.30` cierran partidos con presión → más goles tarde → empates 1-1, 2-2 frecuentes (over_2.5).

### F6. Concentración shooter (Gini sobre shots por jugador)

```
shooter_gini_l_lag = Gini(shots por jugador) últimos 5 partidos
```

Hipótesis: Gini > 0.7 = 1-2 jugadores concentran tiros (estrella-dependiente). Si esa estrella está suspendida o lesionada en próximo partido → caída.

---

## TUS TAREAS (orden estricto)

### Fase 0 — Infraestructura

1. **Snapshot DB pre-sesión**: `cp fondo_quant.db snapshots/fondo_quant_$(date +%Y%m%d_%H%M%S)_pre_shotmap_yield.db`
2. **Verificar manifesto SHA256 intacto** antes y después de cada cambio
3. **NO modificar** `motor_data.py`, `motor_calculadora.py`, `Reglas_IA.txt`, `historial_equipos_stats`, `motor_xg_v2_*`

### Fase 1 — Construir features shotmap-derived

1. Parsear `shotmap_json` de los 769 partidos. Para cada partido + equipo, extraer:
   - `n_shots_total`, `n_shots_danger_zone`, `n_shots_late_game` (min>80)
   - `n_goals_setpiece`, `n_goals_open_play`
   - Distribución shots por playerId (para Gini)
2. Construir tabla `historial_equipos_shotmap_ema` paralela a `historial_equipos_stats`:
   - Per (liga, equipo, fecha) snapshot pre-partido
   - Cols: ema_xg_perf, ema_bcc, ema_pct_danger, ema_sp_dep, ema_late, ema_gini_shooter
   - n_acum (warmup ≥ 3 partidos)
3. Persistir tabla con index (liga, equipo, fecha)

### Fase 2 — Universo de evaluación

1. Construir `universo_filtros_shotmap_v1`: para cada partido SOFA con cuotas (cruzar con `partidos_backtest` 2026 + `cuotas_historicas_fdco`):
   - Snapshot EMA shotmap pre-partido local + visita
   - Diff features (l - v), ratio (l / v), asimétricos (atk_l vs def_v)
   - Cuotas + outcome real
2. Estimar N esperado: SOFA 2026 ∩ cuotas ∩ warmup ≥ 3 ≈ 200-400 partidos.

### Fase 3 — Exploración + ML feature importance

1. Para cada feature, bin q4 + yield + bootstrap CI95 (α=0.05)
2. Random Forest permutation importance + mutual information
3. Identificar top-15 features por target (1, X, 2, O25, U25)
4. Bonferroni alpha = 0.05 / n_tests

### Fase 4 — Validación

1. **Schema A pool**: yield IS + per-año
2. **Walk-forward TRUE-OOS** train < y / test = y (años: 2024, 2025, 2026)
   - **Limitación**: SOFA solo cubre 2026, así que TRUE-OOS por mes solamente (3 buckets ene-feb / mar / abr-may)
3. **Per-liga breakdown**: validar consistencia (descartar ligas con yield NEG sig)
4. **Bootstrap CI95% lower > 0** obligatorio para promoción

### Fase 5 — Combinaciones con filtros existentes

Tomar los 3 filtros validados de `filtros_ema_v4` (whitelist per-liga ARG/ITA/ENG/FRA/TUR):
1. AND con shotmap features (lift incremental?)
2. Probar si shotmap aporta info no capturada por EMAs convencionales

### Fase 6 — SHADOW persistence + reporte

1. **Tabla nueva**: `picks_shadow_filtros_shotmap_v1` schema similar a `picks_shadow_filtros_ema_v4`:
   - `id, ts_log, sofa_event_id, liga, fecha, ht, at, fuente_cuota, filtro_id, filtro_descripcion, filtro_feature, filtro_lo, filtro_hi, pick, cuota, hit_real, yield_real, n_acum_filtro, yield_acum_filtro, ci95_lo_pool, yield_pool_validation, n_pool_validation, avg_oos_yield, n_pos_oos, n_with_oos, liga_es_whitelist, yield_per_liga_estimado, n_per_liga_estimado, bonferroni_alpha, validacion_metodo, aplicado_produccion, razon_no_aplicado`
2. **`aplicado_produccion=0` siempre** — SHADOW only.
3. **Reporte final**: `docs/papers/filtros_shotmap_validados_post_session.md` con:
   - TL;DR honesto (incluye descartes)
   - Desglose per-liga × año
   - Comparación vs `filtros_ema_v4` y `filtros_sofa_v1`
   - Limitaciones explícitas (N pequeño, sin walk-forward inter-año, etc.)

---

## RESTRICCIONES METODOLÓGICAS (no negociables)

1. **Bonferroni siempre**. Reportar α total = 0.05 / n_tests.
2. **Walk-forward al menos por mes** (TRUE-OOS inter-año imposible con SOFA 2026 only).
3. **N mínimo 30** (idealmente 50) para considerar yield real.
4. **Bootstrap CI95% obligatorio**: lower > 0 para promover.
5. **NO p-hacking**: si exploraste 200 features, divide α por 200.
6. **NO leakage**: features lag-N solo de partidos PASADOS del equipo. Shotmap del partido EN CURSO solo para outcome (target).
7. **Filtros condicionales por liga**: validar walk-forward per-liga. Si yield concentrado en 1 liga con N tiny, RECHAZADO.
8. **Documentar overfitting riesgo** explícitamente para cada filtro promovido.

---

## QUÉ NO HACER

- NO scrapear SofaScore API (datos ya en DB, anti-bot vetado por sesiones previas).
- NO modificar `motor_data.py`, `motor_calculadora.py`, `motor_xg_v2_*`, `historial_equipos_stats`.
- NO tocar `Reglas_IA.txt` ni constantes protegidas (ALFA_EMA, RHO, FLOOR_PROB_MIN, MAX_KELLY_PCT_*).
- NO promover filtros a producción sin SHADOW MODE primero.
- NO usar features con leakage temporal.
- NO reportar yield sin Bonferroni + bootstrap.
- NO construir un nuevo xG model. Usar `xg_shotmap_l/v` ya calibrado.
- NO testear features individuales del shotmap del partido en curso (eso es xG model territory).

---

## OUTPUT ESPERADO AL FINAL

1. `analisis/filtros_shotmap_v1_features.py` — script construye `historial_equipos_shotmap_ema` (idempotente)
2. `analisis/filtros_shotmap_v1_universo.py` — script construye `universo_filtros_shotmap_v1`
3. `analisis/filtros_shotmap_v1_exploration.py` — Phase 3-4 exploración + WF
4. `analisis/filtros_shotmap_v1_shadow_persist.py` — Phase 6 SHADOW persistence
5. `analisis/filtros_shotmap_v1_*.json` — métricas reproducibles cada fase
6. `docs/papers/filtros_shotmap_validados_post_session.md` — reporte final
7. **Tablas DB**:
   - `historial_equipos_shotmap_ema` (EMA shotmap-derived)
   - `universo_filtros_shotmap_v1` (universe + cuotas)
   - `picks_shadow_filtros_shotmap_v1` (SHADOW logs)
8. **Snapshot pre-sesión** en `snapshots/`
9. **Recomendación clara** de qué promover SHADOW vs descartar.

---

## ENTREGABLE FINAL TIPO

```
=== FILTROS SHOTMAP POST-EXPLORACIÓN ===
Features construidas: NN
Tests evaluados: NN
Filtros que pasan Bonferroni estricto: NN
Filtros walk-forward (mensual) validados: NN
Filtros para promover SHADOW: NN

TOP FILTROS VALIDADOS (SHADOW):
1. <filtro>: yield IS=X%, N=Y, CI95=[A,B], walk-forward yield=Z%
2. ...

NUEVAS HIPÓTESIS DESCUBIERTAS:
1. <descripción>
...

COMPARACIÓN VS FILTROS EXISTENTES (ema_v4, sofa_v1):
- Lift incremental de combinaciones AND: <data>
- ¿shotmap aporta info no capturada por EMAs convencionales? <SI/NO>

RECOMENDACIÓN:
- Promover SHADOW: <lista>
- Descartar (overfitting / sin señal): <lista>
- NO emitir bead PROPOSAL si Bonferroni no superado.
```

---

**Empezá leyendo los docs de las sesiones previas. Después arrancá Fase 0 (snapshot DB).**

## Referencias obligatorias

- `docs/papers/filtros_ema_validados_post_session.md` — sesión EMA expandida
- `docs/papers/filtros_sofa_validados_post_session.md` — sesión SOFA lag-1
- `docs/papers/motor_xg_v2_resultados_finales.md` — xG model construido (NO re-hacer)
- `docs/papers/sofascore_findings_consolidados.md` — qué expone cada endpoint SOFA
- `docs/papers/filtros_estrategicos_pendientes.md` — propuestas no-SOFA
- `docs/papers/PROMPT_sesion_filtros_sofa.md` — sesión SOFA original (estructura)
- `Reglas_IA.txt` — manifesto matemático/arquitectural (lectura obligatoria)
