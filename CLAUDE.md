# Project Instructions for AI Agents

This file provides instructions and context for AI coding agents working on this project.

## Protocolo de Comunicación con el Usuario

**Rol primario:** Científico analítico, gestor de riesgos y auditor lógico.

### Reglas Universales
- Cero texto de relleno. Cero saludos. Cero emojis.
- Identifica fallas en la lógica matemática o argumentativa del usuario.
- Pregunta antes de asumir variables faltantes o información incompleta.
- Prioriza documentos internos. Notifica obligatoriamente el uso de fuentes externas.

### Condición A — Ejecución de Herramientas y Extracción de Datos
- Ejecuta la herramienta primero.
- Muestra el resultado. Detén la generación.
- Sintaxis estricta: frases de 3 a 6 palabras.
- Omite artículos ("Calculo varianza" no "Calculo la varianza").

### Condición B — Debate, Explicación de Fórmulas y Análisis Crítico
- Suspende la restricción de longitud para garantizar rigor técnico.
- Desmenuza las premisas del usuario. Fomenta debate crítico.
- Justifica refutaciones con lógica pura y fuentes empíricas.
- Si usas fórmulas, explícalas paso a paso e integra al usuario al desarrollo.
- Si se requieren bases de datos, solicita autorización para crear y actualizar hojas de cálculo.

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:ca08a54f -->
## Beads Issue Tracker

This project uses **bd (beads)** for **persistent cross-session issue tracking**. Run `bd prime` for full command reference.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work atomically
bd close <id>         # Complete work
```

### Adepor Hybrid Rules (NOT the default Beads rules)

This project deliberately runs a **two-plane coordination model**. Read carefully — this OVERRIDES the default Beads rules:

- **Beads (`bd`) is for PERSISTENT items only**:
  - `[PROPOSAL: MANIFESTO CHANGE]` (Reglas_IA.txt mutation requests)
  - `[PROPOSAL: SCHEMA CHANGE]` (DB schema modifications)
  - Decisions log (audited record of approvals/vetoes)
  - Archive of completed experiments / backtests evidence
  - Long-running multi-session work
- **Native task list (`TodoWrite` + agent team `TaskCreated`/`TaskCompleted` hooks) is for OPERATIVE items**:
  - Day-to-day work units claimed by teammates
  - Things that complete and disappear within one team session
- **MEMORY.md (auto-memory at `~/.claude/projects/<proj>/memory/`) STAYS** — it is auto-managed by Claude Code, separate from Beads. Do not move project facts there into `bd remember`.
- **No "MANDATORY git push"** — this is a private project, the user pushes when they decide. Do NOT auto-push.

### When to use which

| Item | Where |
|---|---|
| "Calibrar RHO Brasil con N=80" (1 sesión) | TodoWrite / native task list |
| "Auditar consistencia DB post-PK-compuesta" (1 sesión) | TodoWrite / native task list |
| "PROPOSAL: bajar FLOOR_PROB_MIN a 0.35" | `bd create --label proposal-manifesto` |
| "Onboardear Italia + cascada de calibraciones" (multi-día) | `bd create` epic + sub-issues |
| Decision log "approved RHO recalibration on 2026-04-25" | `bd create --label decision-log --close` |
<!-- END BEADS INTEGRATION -->


## Adepor — Project Context

**Tipo:** motor cuantitativo de apuestas deportivas en Python + SQLite (`fondo_quant.db`).
**Pipeline orquestador:** `py ejecutar_proyecto.py` (V8.0 con subcomandos `--status`, `--summary`, `--analisis`).
**Branch estable:** `main`. **Branch experimental:** `experimentos` (donde vive la arquitectura multi-agent).

### Manifiesto inmutable

`Reglas_IA.txt` es el contrato matemático/arquitectural del proyecto. Su SHA-256 está
registrado en `configuracion.manifesto_sha256`. **Antes de cualquier modificación a
`Reglas_IA.txt`, `motor_calculadora.py`, o constantes protegidas (ALFA_EMA, RHO_FALLBACK,
FLOOR_PROB_MIN, MAX_KELLY_PCT_*, etc.)** se debe:

1. Crear bead `[PROPOSAL: MANIFESTO CHANGE]` con evidencia (N≥50, backtest, Brier, EV)
2. Esperar autorización humana explícita (label `approved-by-lead`)
3. Incluir tag `MANIFESTO-CHANGE-APPROVED:bd-<id>` en la task que aplica el cambio

El hook `scripts/hooks/validate_task_created.py` enforca esto a nivel `TaskCreated`.

**Estado actual (2026-04-28 post-sesión 2):**
- **Versión:** V5.2 (Layer 3 H4 X-rescue per-liga, **ACTIVO**) + bug-fix helpers (decision-log adepor-0og)
- **SHA-256:** `471c1c00b927baad59cd13688bd5db142550a1aadbc45980a2b6d76862c4ab6c` (sin cambios — fix interno no toca manifesto)
- **Locked:** `configuracion.manifesto_locked = 'true'`
- **Layers vigentes:**
  - V5.0 §L Layer 2: `arch_decision_per_liga = {"Turquia": "V12"}`. V12 standalone activo
    para argmax 1X2 SOLO en Turquía. Otras 15 ligas → V0.
  - V5.1 §M filtro de picks apostables triple:
    - **M.1** `apostar_solo_si_liga_in {Argentina, Brasil, Inglaterra, Noruega, Turquía}` ✓ ACTIVO
    - **M.2** `apostar_solo_si n_acum_l < 60` ✓ ACTIVO (calibrado en 2024 sig)
    - **M.3** `apostar_solo_si momento_bin_4 != 3` ✗ DESACTIVADO en V5.1.2
  - **V5.2 §N Layer 3 H4 X-rescue per-liga**: `h4_x_rescue_threshold = '{"Argentina":0.35,"Italia":0.35,"Inglaterra":0.35,"Alemania":0.35}'`
    ✓ **ACTIVO LIVE 2026-04-28 18:51 ARS**. Operativamente solo ARG+ING impactan picks LIVE
    (M.1 filtra ITA/ALE — listadas para activación futura). Validación OOS 2022-2024
    N=160 con filtro doble: Δ +0.426 [+0.07, +0.78] *** SIG POS. Backtest contrafáctico
    in-sample 2026 N=6: V0 yield +1.175 vs X yield -0.525, Δ -1.700 (CI95 amplio, no
    concluyente, pero alineado con `adepor-9uq` régimen 2026 vs OOS).
    Auditoría longitudinal vía `picks_shadow_layer3_log` + `analisis/audit_layer3_monthly.py`.
- **V5.1.2 cambio (2026-04-28):** `filtro_picks_v51.excluir_q4=false` en config. Audit in-sample
  reveló que M.3 NEW (calendario fix) bloquea Inglaterra Q4 +70.7% y Turquía Q4 +50.8% que
  hoy están dando dinero. Calibración OOS 2024 (Q4 −16.1% sig) NO transfiere a régimen 2026.
  M.3 condicional por régimen pendiente (`adepor-09s` Fase 2).
- **V5.2 cambio (2026-04-28):** Bump V5.1.2 → V5.2 con nueva sección §N (Layer 3 H4 X-rescue).
  Bead `adepor-tyb` aprobado tras audit Opción D extendido (walk-forward por temp + multidim).
  Infraestructura ready, JSON empty. Activación liga-por-liga vía SQL post-merge.
  Doc: `docs/findings_layer3_walkforward.md`. Audit: `analisis/audit_yield_F2_walkforward_por_temp.{py,json}`,
  `analisis/audit_yield_F2_x_rescue_population.{py,json}`, `analisis/audit_x_rescue_multidim.{py,json}`.
  Helpers nuevos: `_get_pos_local_forward`, `_get_gap_dias_no_liga` en motor_calculadora.py.
  Tabla nueva: `partidos_no_liga` (8,742 OOS 2022-2024 via API-Football + 192 in-sample 2026
  via Wikipedia parcial), view `v_partidos_unificado` (UNION liga + no-liga).
- **V5.2 sesión 2 (2026-04-28 PM):** Layer 3 ACTIVO live. Bug fix Layer 3 helpers
  (decision-log `adepor-0og`): los helpers usaban `WHERE equipo=?` con `loc_norm` (lower+sin
  acentos) pero las tablas almacenaban display name → lookup retornaba None 100% → filtros
  inversos no funcionaban. Fix: ALTER TABLE ADD `equipo_norm` a `posiciones_tabla_snapshot`,
  `ht_norm`/`at_norm` a `partidos_historico_externo`, `equipo_local_norm`/`equipo_visita_norm`
  a `partidos_no_liga`; backfill 32k+14k+8k filas; 5 índices nuevos; `v_partidos_unificado`
  recreada con cols norm. Sanity post-fix: 7 APLICA + 6 SKIP_TOP3 + 2 SKIP_CANSADOS sobre
  184 partidos. Logging activo en `picks_shadow_layer3_log` (PK `id_partido`+`fecha_evaluacion`).
  Mojibake fix `adepor-z0e` aplicado (regla B-corregida: acento+uppercase canónicos): 755 UPDATEs,
  0 DELETEs, 0 clusters residuales. Follow-up `adepor-qqb`: popular `_norm` en INSERT path
  scrapers (sin esto, datos nuevos no son lookable). Scripts nuevos: `analisis/sanity_layer3.py`,
  `analisis/fixture_layer3_upcoming.py`, `analisis/audit_layer3_monthly.py`,
  `analisis/backtest_layer3_contrafactual.py`, `analisis/diagnostic_mojibake_equipos.py`,
  `analisis/fix_mojibake_equipos.py`.
- **V5.2 sesión 3 (2026-04-28 PM, 3 fases consecutivas):**
  - **F1 Consistencia INSERT:** 4 scripts modificados para wrappear `gestor_nombres.obtener_nombre_estandar()`
    + popular `_norm` (cierra `adepor-qqb`). Backfill idempotente `scripts/backfill_norm_columns.py`.
  - **F2 Schema enriquecido `partidos_no_liga`:** agregadas 7 cols (liga_local, liga_visita,
    competicion_formato, id_serie_eliminatoria, numero_partido_serie, agregado_local_pre/visita_pre).
    Backfill: 21% liga_home resuelta (limitado por diccionario incompleto — `adepor-g4s`).
    125 series 2-legs detectadas con agregados pre-poblados. 539 partidos cross-liga.
  - **F3 Motor copa research + Elo:** documentado en `docs/papers/copa_modelado.md` + `docs/papers/elo_calibracion.md`
    (18 fuentes peer-reviewed: Cattelan 2013 RSS, Olesker-Taylor 2024 NeurIPS, Tandfonline 2025 sparse,
    Aldous Berkeley, World Football Elo, Eloratings.net). Workflow `scripts/research/buscar_papers.py`
    (Semantic Scholar + arXiv API fallback). Tabla nueva `equipo_nivel_elo` (39,164 filas Elo dinámico
    cross-competition con K-factor diferenciado: liga 20, copa nacional 30, copa internacional 40,
    knockout 50, final 60). Cold-start regularization K*0.5 cuando n<30 (Tandfonline 2025).
    Backtest desglosado: hit standalone 49.5% global, copa internacional 53.0% (mejor), Turquía 53.3%,
    Argentina 43.2% (peor de los grandes — coherente con `adepor-09s` régimen). 2025 OOS 54.1% (mejor año).
  - **Process gate fundamentación académica (decisión usuario 2026-04-28):** toda decisión técnica
    nueva debe estar fundamentada en investigación (Semantic Scholar / arXiv / WebSearch) + persistida
    en `docs/papers/<topic>.md` + referenciada en código con `[REF: docs/papers/...]`.
- **V13 SHADOW puro:** Argentina F1_off NNLS, Francia F2_pos NNLS, Italia F2_pos RIDGE,
  Inglaterra F5_ratio NNLS. NO afecta picks. Validación N≥200 SHADOW para promoción.
- **Calendario individual:** tabla `liga_calendario_temp` (80 filas) con fechas reales
  inicio/fin por (liga, temp). Reemplaza método "rango observado" para `momento_bin_4`.
- **Posiciones snapshots:** `posiciones_tabla_snapshot` con 3 formatos paralelos para
  Argentina (anual, apertura, clausura). Hook incremental al pipeline.
- **Beads pendientes:** ver `docs/beads_pendientes_2026-04-28.md` (13 abiertos).
- **Validación rápida:** `py -c "import sqlite3; print(sqlite3.connect('fondo_quant.db').execute(\"SELECT valor FROM configuracion WHERE clave='manifesto_sha256'\").fetchone()[0])"`

### Multi-Agent Team (experimental)

Activado vía `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` (user-level settings). Equipo:

- **Lead** (`.claude/agents/lead-adepor.md`) — coordinador, custodio del Manifiesto
- **Investigador** (`cazador_datos` / `investigador_xg`) — research + literatura
- **Optimizador** (`optimizador_modelo`) — backtests sobre `shadow_dbs/`, plan-approval requerido
- **DataOps** (`onboarder_liga` / `fixture_supervisor`) — único con escritura a producción, plan-approval
- **Crítico** (`critico`) — auditor con poder de veto, valida métricas (EV_total_horizonte, N, snapshot_id)

### Build & Test

```bash
# Status snapshot del sistema
py ejecutar_proyecto.py --status

# Pipeline diario completo
py ejecutar_proyecto.py

# Sniper Telegram (post-pipeline)
py motor_live.py --once

# Recalibración mensual / on-demand
py scripts/calibrar_beta.py        # display-only: factor de calibración Beta
py scripts/calibrar_piecewise.py   # display-only: piecewise por bucket
py scripts/calibrar_xg.py          # OLS xG histórico → coeficientes por liga
py -m src.nucleo.calibrar_rho      # MLE rho por liga (Dixon-Coles)

# Backfill EMA scoped (auto: estricto a prod + laxo a shadow)
py scripts/backfill_ema_scoped.py --auto --dry-run   # preview
py scripts/backfill_ema_scoped.py --auto             # aplica + loggea

# Snapshot DB pre-cambio (obligatorio antes de tocar tablas)
cp fondo_quant.db "snapshots/fondo_quant_$(date +%Y%m%d_%H%M%S)_pre_<motivo>.db"
```

### Filosofía de trabajo (no-negociable)

- Nada se toca sin evidencia empírica (backtest, hold-out, test comparativo)
- "Yield no se rompe" — cambios al motor requieren validación de yield, no solo Brier
- "Brier no se rompe" — calibraciones que rompen Brier rompen todo
- Snapshots de seguridad antes de cambios de DB
- Display-only > motor: calibraciones que tocan display NO requieren cascada

### Tablas clave para descubrimiento (introspección rápida)

Antes de leer código para entender qué hace el motor, consultar estas meta-tablas
en `fondo_quant.db`. Existen explícitamente para que un agente nuevo no re-descubra
filtros/motores/históricos por inspección de archivos.

| Tabla | Filas (snapshot) | Para qué sirve |
|---|---|---|
| `motor_filtros_activos` | 19 | Inventario de los 19 filtros activos del motor (origen, parámetro, estado). Único punto de verdad |
| `pipeline_motores` | 14 | Documentación de los 14 motores del pipeline (nombre, frecuencia, responsabilidad, dependencias) |
| `config_motor_valores` | 200+ | Parámetros operativos del motor (FLOOR_PROB, MARGEN, EV-min, Kelly cap, filtro_picks_v51, OLS V6, LR V12, V12b1/b2/b3, anchor batch — scope universal o por liga) |
| `predicciones_walkforward` | 23.268 | Predicciones walk-forward persistidas para calibración futura sin re-scraping |
| `partidos_historico_externo` | 14.489 | Stats crudas legacy (incluye faltas/tarjetas) — fuente para A/B de features alternativos |
| `xg_calibration_history` | 25 | Log iterativo de calibraciones xG (cada iter persiste OLS coef + R² + comentario) |
| `margen_optimo_per_liga` | 15 ligas | Thresholds de margen derivados por liga (display + análisis) |
| `historial_equipos_v6_shadow` | 402 equipos | EMA xG OLS recalibrado por equipo (V6 SHADOW input para V7/V12) |
| `historial_equipos_stats` | 19.154 snapshots | EMA stats avanzadas por (liga, equipo, fecha) — sots, shot_pct, pos, pass_pct, corners, yellow, red, fouls, tackles, blocks. Input para V13 SHADOW + filtro M.2 (n_acum) |
| `liga_calendario_temp` | 80 | Calendario individual por (liga, temp): fecha_inicio + fecha_fin del torneo. Reemplaza método "rango observado" para `momento_bin_4` |
| `posiciones_tabla_snapshot` | crece | Ranking acumulado por (liga, temp, formato, fecha, equipo) sin look-ahead. Argentina con 3 formatos paralelos (anual + apertura + clausura). Hook incremental al pipeline |
| `v13_coef_por_liga` | 8+ | Coeficientes V13 SHADOW (NNLS/RIDGE) calibrados por (liga, target). Argentina F1_off NNLS, Francia F2_pos NNLS, Italia F2_pos RIDGE, Inglaterra F5_ratio NNLS |
| `online_sgd_log` | crece | Log diagnóstico de cada SGD step del motor adaptativo (grad, weight, brier, dW, reverted) |
| `drift_alerts` | crece | Alertas de drift Brier rolling 30d vs baseline+2σ (motor adaptativo) |

Comando de exploración rápida (lista todas las tablas con conteo real de filas):
```bash
py -c "import sqlite3; c=sqlite3.connect('fondo_quant.db').cursor(); \
tablas=[r[0] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='table' ORDER BY name\")]; \
[print(f'{t:<40s} {c.execute(f\"SELECT COUNT(*) FROM {t}\").fetchone()[0]:>10d}') for t in tablas]"
```

### Patrón SHADOW MODE

**Convención unificadora**: cualquier cambio al motor que afecte decisiones (filtros,
fórmulas, arquitectura de probabilidad) NO va directo a producción. Se loggea primero
a una tabla `*_shadow_*` con flag `aplicado_produccion ∈ {0,1}` y se observa N≥80
partidos liquidados antes de promover. Esto resuelve el dilema "yield vs Brier" sin
pagar el costo de revertir cambios mal calibrados.

| Tabla SHADOW | Filas | Origen | Trigger de promoción |
|---|---|---|---|
| `picks_shadow_margen_log` | 21 | V4.5 SHADOW (margen_predictivo) | bead `adepor-dx8` (FLOOR universal aprobado) |
| `picks_shadow_arquitecturas` | 73+ | Arquitecturas V0–V12 (V6 OLS+DC, V7 Skellam, V12 LR multinomial). V8/V9/V10/V11 cerradas 2026-04-26 (no validaron OOS). | bead `adepor-617` (PROPOSAL H4 V0+X-rescue) — pending N≥500 |
| `backfill_ema_shadow_log` | 6 | Backfill EMA dual-mode (estricto a prod / laxo a shadow) | observación longitudinal (sin trigger N) |
| `historial_equipos_v6_shadow` | 402 equipos | EMA paralelo xG OLS recalibrado (input V6/V7/V12) | bead `adepor-d7h` (infra SHADOW) |
| `online_sgd_log` | crece | SGD steps del motor adaptativo permanente (V12 weights) | NO se promueve — es runtime adaptativo |
| `drift_alerts` | crece | Alertas Brier rolling > baseline+2σ | trigger automático bead PROPOSAL re-train batch |

**Arquitecturas SHADOW vivas (loggeadas en cada corrida del motor)**:
- **V0** = Poisson DC + xG legacy (motor producción actual)
- **V6** = Poisson DC + xG OLS recalibrado
- **V7** = Skellam + xG OLS (sin tau DC)
- **V12** = LR multinomial (xG + H2H + varianza + mes), per-liga + global pool. Activo en argmax SOLO en Turquía (V5.0 §L Layer 2).
- **V12b1/b2/b3** = LR pool global ridge=0.1 con/sin H2H + class_weights (persistidas en config como referencia, no logueadas rutinariamente)
- **V13** = Poisson DC + xG ridge regularizado (5-7 features) por liga. BEST por liga: Argentina F1_off NNLS, Francia F2_pos NNLS, Italia F2_pos RIDGE, Inglaterra F5_ratio NNLS. SHADOW puro hasta N≥200 picks.

**Hallazgos OOS 2026-04-26** (test 2024 N=2,768):
- V0 raw GANA hit (0.488) y Brier (0.6182) en OOS estricto
- Hallazgo G EMPEORA V0/V6/V7 −1.2pp hit, +0.0044 Brier
- Fix #5 inocuo (cero impacto OOS)
- V12 sub-confidente en local: solo gana con HG (+0.6pp), única arquitectura beneficiada
- H4 V0+X-rescue (V0 default + override X si V12 dice X y P(X)>0.30): hit 0.520, yield +0.246 sobre N=127 partidos_backtest con cuotas reales — PROPOSAL `adepor-617` BLOQUEADO pending N≥500

**Reglas del patrón:**
- Toda tabla shadow lleva `timestamp` para auditoría longitudinal
- Toda fila lleva `aplicado_produccion` (0/1) y `razon_no_aplicado` (cuando aplica)
- El motor de calculadora puede leer SHADOW pero **nunca** decide con esos datos hasta promoción explícita
- Promover de SHADOW a producción requiere bead `[PROPOSAL: MANIFESTO CHANGE]` o evidencia equivalente

### Motor adaptativo (FASE 1.5 del pipeline)

`motor_adaptativo.py` corre permanentemente cada `py ejecutar_proyecto.py`:
1. Identifica partidos liquidados desde `motor_adaptativo_last_run` (idempotente)
2. Aplica SGD step sobre `lr_v12_weights[liga]` + `[global]` paralelo (warmup 100, lr=0.005, ridge=0.1, anchor=0.05)
3. Auto-audit sobre últimos 200 SGD steps: revierte a anchor batch si detecta WEIGHT_NORM > 50, GRAD_NORM > 5, o BRIER > baseline×1.10. Cooldown 7 días.
4. Drift detector ventana 30d sobre Brier rolling
5. Persiste `last_run` timestamp

NO afecta motor productivo (V0 sigue decidiendo argmax). Solo actualiza V12 SHADOW. Plan completo en `docs/ml_adaptativo_plan.md`.

### Documentación viva

Estos artefactos están checked-in y son la "memoria operativa" del proyecto. Lectura obligatoria antes de proponer cambios estructurales:

- `Reglas_IA.txt` — Manifiesto matemático/arquitectural (versión actual V5.2; §N Layer 3 H4 X-rescue infraestructura ON, JSON empty)
- `docs/beads_pendientes_2026-04-28.md` — inventario humano de los 13 beads abiertos con explicación de cada uno
- `docs/findings_n_acum_drift.md` — investigación M.2 (n_acum) drift, validación dual OOS+real
- `docs/findings_v13_grid_search.md` — grid search V13 (4 reg × 6 feat × 8 ligas), BEST por liga
- `docs/findings_audit_posicion_y_M3.md` — audit posición tabla + recalibración M.3 con calendario fix
- `docs/regime_profiles_2022_2023_2024.md` — caracterización Fase 1 predictor de régimen
- `docs/pipeline_overview.md` — spec discoverable del pipeline (qué motor hace qué, en qué orden, con qué inputs/outputs)
- `docs/xg_calibration_history.md` — log iterativo de cómo se ha calibrado el xG histórico
- `docs/ml_adaptativo_plan.md` — plan 3 capas (L1 EMA+rho, L2 online SGD V12, L3 drift detector). Estado: F1+F2+F3 implementados.
- `docs/plan_ampliacion_cuotas.md` — plan scraper football-data.co.uk para llevar N=127 → N≥3000 de validación H4
- `docs/arquitectura/`, `docs/fase3/`, `docs/fase4/`, `docs/historico/`, `docs/ux/` — documentación por dominio
- `sintesis_body.md` — artefacto histórico-evolutivo del crítico-sintesis (research consolidado 2026-04-25 + anexos 2026-04-26)
- `analisis/` — backtests, A/B, ablations, walk-forwards (cada uno con su `.json` reproducible y `.py` que lo generó)
- `MEMORY.md` (`~/.claude/projects/<proj>/memory/`) — auto-memoria de Claude Code, separada de Beads
