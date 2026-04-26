# Project Instructions for AI Agents

This file provides instructions and context for AI coding agents working on this project.

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

**Estado actual (2026-04-26):**
- **Versión:** V4.6 (post-corrección §IV.H que clarifica HG ACTIVO en Argentina+Brasil)
- **SHA-256:** `c1f3a1d2ce80dc82e9bd37c2c9cfc2aef2d6f60e8fbf949d07bf70779efd4f1f`
- **Locked:** `configuracion.manifesto_locked = 'true'`
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
| `config_motor_valores` | 142 | Parámetros operativos del motor (FLOOR_PROB, MARGEN, EV-min, Kelly cap, etc. — scope universal o por liga) |
| `predicciones_walkforward` | 23.268 | Predicciones walk-forward persistidas para calibración futura sin re-scraping |
| `partidos_historico_externo` | 14.489 | Stats crudas legacy (incluye faltas/tarjetas) — fuente para A/B de features alternativos |
| `xg_calibration_history` | 25 | Log iterativo de calibraciones xG (cada iter persiste OLS coef + R² + comentario) |
| `margen_optimo_per_liga` | 15 ligas | Thresholds de margen derivados por liga (display + análisis) |

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
| `picks_shadow_arquitecturas` | 73 | 6 arquitecturas V0–V5 (incluye Skellam) | bead `adepor-57p` — re-eval con N≥80 |
| `backfill_ema_shadow_log` | 6 | Backfill EMA dual-mode (estricto a prod / laxo a shadow) | observación longitudinal (sin trigger N) |

**Reglas del patrón:**
- Toda tabla shadow lleva `timestamp` para auditoría longitudinal
- Toda fila lleva `aplicado_produccion` (0/1) y `razon_no_aplicado` (cuando aplica)
- El motor de calculadora puede leer SHADOW pero **nunca** decide con esos datos hasta promoción explícita
- Promover de SHADOW a producción requiere bead `[PROPOSAL: MANIFESTO CHANGE]` o evidencia equivalente

### Documentación viva

Estos artefactos están checked-in y son la "memoria operativa" del proyecto. Lectura obligatoria antes de proponer cambios estructurales:

- `Reglas_IA.txt` — Manifiesto matemático/arquitectural (versión actual V4.6)
- `docs/pipeline_overview.md` — spec discoverable del pipeline (qué motor hace qué, en qué orden, con qué inputs/outputs)
- `docs/xg_calibration_history.md` — log iterativo de cómo se ha calibrado el xG histórico
- `docs/arquitectura/`, `docs/fase3/`, `docs/fase4/`, `docs/historico/`, `docs/ux/` — documentación por dominio
- `sintesis_body.md` — artefacto histórico-evolutivo del crítico-sintesis (research consolidado 2026-04-25 + anexos 2026-04-26)
- `analisis/` — backtests, A/B, ablations, walk-forwards (cada uno con su `.json` reproducible y `.py` que lo generó)
- `MEMORY.md` (`~/.claude/projects/<proj>/memory/`) — auto-memoria de Claude Code, separada de Beads
