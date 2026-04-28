# Prompt próxima sesión — 2026-04-27 cierre

> Sesión de hoy: cerrada Fase 3 + corrida Fase 4 (D entregado, C falló,
> C.bis borderline). Branch `main`. Pendiente: commit + push.

## Estado al cierre

### Cerrado en esta sesión

- **Fase 3 stats avanzadas**: graficos/fase3/ por liga/año/equipo
  (umbral 12 partidos), análisis cuartiles, fix mojibake en
  `cache_espn/*.json` y `stats_partido_espn`. Findings en
  `docs/fase3_findings.md`.
- **Fase 4 D — Timelines EMA**: 124 timelines individuales + 30
  comparativos top-5 por liga + arquetipos global.
  Output: `graficos/fase4/`.
- **Fase 4 backbone**: `historial_equipos_stats` (19.154 snapshots
  × 328 equipos × 12 ligas), API `predecir_stats_pre_partido()`.
- **Fase 4 C — Score apostable lineal**: implementado, **falló**.
  Q5−Q1 yield = +3.0pp (sin discriminación). Pesos derivados
  delta_g_pct de Fase 3 NO se traducen pre-partido.
- **Fase 4 C.bis — Filtro asimétrico ratio**: paired bootstrap
  N=2000. Δyield +1.01pp, CI95 [-0.28, +2.30], P(Δ>0)=0.932.
  **NO significativo.** Direccionalmente positivo pero insuficiente
  (N bloqueadas=42 muy bajo).

### Hallazgos colaterales empíricos

1. **`n_acum` (madurez EMA) discrimina yield**:
   - `n_acum<10`: yield **+33.3%**
   - `n_acum>=60`: yield **−13.7%**
   - Delta: −47pp. Merece investigación propia.
2. **Asimetría posesión rinde, valor absoluto no**:
   - `pos_l − pos_v > +15`: yield −29.5%
   - `ratio_pos_l > 0.55`: yield −18.2% (sobre apostadas a local)
3. **Mojibake doble-encoding fixed**: causa raíz de Brasil 2026
   matching 1/70. Aplicado a 27 archivos cache + DB.

### Pendiente (re-evaluar antes de tocar)

- **Fase 4 B — Integración al motor**: NO ejecutar todavía. Sin
  evidencia (C falló, C.bis no sig). Si se retoma, hook
  `motor_data.py` + pre-fase en `ejecutar_proyecto.py`.
- **Fase 4 A — PROPOSAL filtro pos_EMA**: **descartar versión
  absoluta** (Fase 3 era post-match, no pre-partido). Versión
  asimétrica requiere N adicional o cambio a feature multivariable.

## Tareas concretas próxima sesión (priorizadas)

### Prioridad 1 — Cleanup + commit

```bash
cd C:/Users/map12/Desktop/Proyecto_Adepor
git status                           # ver el universo de cambios
# Decidir qué entra al commit Fase 3+4:
#   analisis/fase4_*.py
#   analisis/fase4_*.json
#   analisis/fix_cache_mojibake.py
#   analisis/graficar_fase3_*.py
#   analisis/cache_espn/*.json (mojibake fix)
#   docs/fase3_findings.md
#   docs/fase4_findings.md
#   docs/fase4/PROMPT_PROXIMA_SESION_2026-04-27.md
#   graficos/fase3/*  graficos/fase4/*
#   scripts/scrape_post_liquidacion.py
git add <bloques>
git commit -m "feat(fase3-4): EMA stats por equipo + visualizaciones + findings"
```

### Prioridad 2 — Investigar `n_acum` madurez EMA (NUEVO bead)

El hallazgo "yield −47pp entre EMA inmadura vs madura" es la mejor
señal empírica que sacamos de Fase 4. Crear bead:

```
bd create --type=task --priority=2 \
  --title="[INFRA] Investigar caida yield con n_acum EMA alto (drift fin-temp?)" \
  --description="..."
```

Tests sugeridos:
1. Cruzar `n_acum_l` con `momento_temp` (% trayecto liga-temp).
   ¿Es `n_acum` un proxy de "estamos en cierre de temp"?
2. Si SÍ es proxy: el drift es fin-de-temp, no EMA-madurez.
3. Si NO es proxy: hay algo en EMA madura per se que rompe yield
   (¿overfitting de Pinnacle a comportamientos conocidos?).

### Prioridad 3 — V13 SHADOW (xG + EMA features) — DEFERRED

Sólo retomar si #2 muestra que `n_acum` aporta señal independiente.
Plan: añadir EMA stats al modelo xG OLS como features adicionales,
loggear como nueva arquitectura SHADOW.

## Comandos útiles para arrancar

```bash
# Recordar manifesto actual
py -c "import sqlite3; con=sqlite3.connect('fondo_quant.db'); print('SHA:', con.execute(\"SELECT valor FROM configuracion WHERE clave='manifesto_sha256'\").fetchone()[0]); print('Locked:', con.execute(\"SELECT valor FROM configuracion WHERE clave='manifesto_locked'\").fetchone()[0])"

# Ver tabla EMA stats (sanity check)
py -c "import sqlite3; con=sqlite3.connect('fondo_quant.db'); print('Snapshots:', con.execute('SELECT COUNT(*) FROM historial_equipos_stats').fetchone()[0]); print('Equipos:', con.execute('SELECT COUNT(DISTINCT equipo) FROM historial_equipos_stats').fetchone()[0])"

# Ver beads abiertos
bd list --status=open
bd show adepor-6kw    # epic Fase 3+4
```

## Archivos modificados sin commitar (al cierre de hoy)

- 27× `analisis/cache_espn/*.json` (mojibake fix)
- `analisis/scraper_espn_historico.py`
- `docs/xg_calibration_history.md`
- `.beads/issues.jsonl`

## Archivos nuevos sin trackear

- `analisis/fase4_ema_stats.py`
- `analisis/fase4_score_apostable.py`
- `analisis/fase4_score_validation.json`
- `analisis/fase4_graficar_timelines.py`
- `analisis/fase4_filtro_asimetrico_bootstrap.py`
- `analisis/fase4_filtro_asimetrico_bootstrap.json`
- `analisis/fix_cache_mojibake.py`
- `analisis/graficar_fase3_*.py` (varios)
- `analisis/si_hubiera_*.json/py` (varios)
- `analisis/v47_yield_*.json/py`
- `analisis/yield_por_*.json/py`
- `docs/fase2_findings.md`
- `docs/fase3_findings.md`
- `docs/fase4_findings.md`
- `docs/yield_curva_operativa.md`
- `graficos/fase3/`, `graficos/fase4/`
- `scripts/scrape_post_liquidacion.py`
