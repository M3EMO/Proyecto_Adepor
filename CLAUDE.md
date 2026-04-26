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

# Recalibración mensual
py scripts/calibrar_beta.py
py scripts/calibrar_piecewise.py
```

### Filosofía de trabajo (no-negociable)

- Nada se toca sin evidencia empírica (backtest, hold-out, test comparativo)
- "Yield no se rompe" — cambios al motor requieren validación de yield, no solo Brier
- "Brier no se rompe" — calibraciones que rompen Brier rompen todo
- Snapshots de seguridad antes de cambios de DB
- Display-only > motor: calibraciones que tocan display NO requieren cascada
