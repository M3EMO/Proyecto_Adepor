@AGENTS.md

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

## Adepor — Contexto del proyecto

**Tipo:** motor cuantitativo de apuestas deportivas en Python + SQLite (`fondo_quant.db`).
**Fuentes:** ESPN (fixtures, resultados, stats) y The Odds API (cuotas). SofaScore es opcional.
**Presentación:** Streamlit local (`./iniciar_dashboard.sh`). Es la única vista; el Excel se borró (D-023).
**Estado del modelo:** el v2 toma Pinnacle sin margen como verdad (D-019). El v1 se borró (D-022, D-023). El edge se mide con CLV.

### Lectura obligatoria antes de cambiar el motor

1. `docs/specs/00-contrato.md`: reglas que no se rompen y cambios que requieren aprobación.
2. `docs/decisiones/registro.md`: decisiones vigentes con su evidencia.
3. La spec del componente que vas a tocar, en `docs/specs/`.

### Gobierno de cambios

- Un cambio a la decisión, a las probabilidades o al riesgo requiere bead `[PROPOSAL: MANIFESTO CHANGE]`.
- El bead necesita el label `approved-by-lead`, que pone solo el usuario.
- La task que aplica el cambio lleva `MANIFESTO-CHANGE-APPROVED:bd-<id>`; el hook lo verifica.
- Todo cambio de modelo pasa primero por shadow (`aplicado_produccion = 0`).

### Comandos

```bash
.venv/bin/python -m pytest
```

```bash
.venv/bin/python ejecutar_proyecto.py --status
```

```bash
./ejecutar_robot.sh
```

```bash
./iniciar_dashboard.sh
```

```bash
.venv/bin/python adepor_guard.py snapshot
```

El runbook completo está en `docs/specs/06-operacion.md`.

### Filosofía de trabajo

- Nada se cambia sin evidencia walk-forward.
- La métrica de éxito se fija antes de mirar los resultados.
- El benchmark es Pinnacle: un modelo que no le gana fuera de muestra no apuesta.
- Antes de tocar la base se hace un backup.

### Documentación

- `docs/specs/`: qué hace cada componente, con referencias a código.
- `docs/decisiones/`: registro de decisiones y la auditoría 2026-10.
- `analisis/`: scripts de backtest con su `.json` reproducible.
- La investigación vive en el vault global (`research/betdeportivo-papers-2026`), no en el repo.

## Token efficiency

Instrumentacion de tokens via skill user-scope `token-efficiency`.
Log local: `data/logs/agent_tokens.jsonl`.
