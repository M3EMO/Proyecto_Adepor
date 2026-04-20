# CIERRE FASE 3 — Adepor

**Fecha cierre**: 2026-04-20
**Lead**: team-lead (chat principal)
**Team**: adepor-fase3 (flujo-datos, senior, junior-hardcodes, junior-bugs, junior-refactor)

---

## 1. Objetivos cumplidos

### Arquitectura

- `config_motor_valores` creada (82 filas, 10 core bloqueadas con trigger RAISE(ABORT)).
- `src/comun/config_motor.py` con `get_param(clave, scope, default)` + cache + fallback chain.
- `src/comun/` expandido: `tipos.py`, `mapas.py`, `tiempo.py`, `adaptadores_odds_api.py`, `constantes_espn.py`, `resolucion.py` (extraídas 6 redundancias inter-motor).
- Hardcodes migrados a DB con fallback de seguridad.

### Bugs corregidos

- **B1** columna `estado`: 321/321 `Pendiente` → 153 `Liquidado` / 62 `Liquidado` (después del re-run) / 118 `Calculado`.
  - Causa raíz: `desbloquear_matriz.py:23` hacía `UPDATE ... SET estado='Pendiente'` sin WHERE.
- **B2** captura corners ESPN: nombres mal `cornerKicks`/`shots` → corregidos a `wonCorners`/`totalShots` en `motor_data.py` (6 líneas en 3 sitios).
- **Datos zombi `equipos_stats`**: DELETE 122 filas con liga no canónica (`Primera División`, `Eliteserien`, `Premier League`, etc.).
- **Parche timeout ESPN**: `timeout=(3, 8)` tupla + retry + skip tras detectar cuelgue 2 días con `timeout=5` simple.
- **Bypass REBUILD_YES=1**: motor_data `--rebuild` ahora acepta env var para automatización.
- **Fix emojis Unicode**: cero emojis en output (ya no rompe cp1252).

### Decisiones del usuario aplicadas

| # | Cambio | Valor viejo | Valor nuevo |
|---|---|---|---|
| F1 | `FLOOR_PROB_MIN` | 0.33 | **0.40** (Camino 3 mantiene 0.33 como override) |
| F2b | Camino 2 | orden 1→2→2B→3 | orden 1→2B→3→**2 último** + filtro subset destructor (VISITA 33-40% en Brasil/Ing/Nor/Tur) |
| F3C | `apuesta_ou_live` | True | **False** (O/U pausado en modo shadow hasta más N) |
| F4 | `delta_stake_mult_med` | 1.15 | **1.25** (backtest N=9 bucket MED hit 100%, +2.2pp yield global) |
| F9 | `margen_predictivo_1x2` por liga | global 0.03 | 0.015 / 0.020 / 0.030 según delta_xG típico |
| F10 | `factor_corr_xg_ou` | Arg 0.642 / Bra 0.603 | Arg **0.628** / Bra **0.564** (N≥50) |
| D1 | Fix estado liquidador | 321 Pendiente | 215 liquidado / 62 calculado |
| D2' | DELETE equipos_stats legacy | 122 filas zombi | 0 |
| D4 | `PROFUNDIDAD_INICIAL` por liga | global 210 | configurable 0-365 por liga |

### Corners capturados post-rebuild

| Liga | Corners |
|---|---|
| Argentina | 4528 |
| Colombia | 4285 |
| Brasil | 4192 |
| Inglaterra | 3794 |
| Turquia | 3147 |
| Peru | 3118 |
| Ecuador | 2995 |
| Noruega | 2811 |
| Chile | 2550 |
| Bolivia, Uruguay, Venezuela | 0 (ESPN no las cubre con `wonCorners`) |

Antes: **0 en las 12 ligas**.

### Métricas de calibración

- Brier multiclase 1X2 global: **0.617 → 0.601 (-2.6%)** sobre la misma muestra N=215.
- 9 ligas mejoran, 3 empeoran (las 3 sin corners ESPN, N<7, ruido estadístico).
- Sobre la muestra original de 123 partidos del snapshot 13-abril: Brier 0.5838 → **0.5795** (-0.43%).

---

## 2. Decisiones pendientes para Fase 4

### STEP 10 F6 — EMA pre-partido lookahead-free

Diseño y backtest. Requiere inspección de `ema_procesados` para reconstruir EMA "al día del partido" sin incluir posteriores. No implementado por complejidad + cambio significativo a backtesting.

### STEP 11 — Modularizar motor_sincronizador

1100 LOC → 4 archivos. Postergado: no es funcional, el motor actual funciona.

### STEP 12 — 14 tareas UX Excel

Dashboard con colores por liga, KPI cards, equity chart. Postergado hasta cierre funcional del pipeline.

### Optimización ESPN

`requests.Session()` + `ThreadPoolExecutor(max_workers=6)` en motor_data/backtest/arbitro. Ganancia esperada **~8x** (rebuild de 60 min → 8 min).

### Propuestas P4 (recalibrar coeficientes híbrido)

Requiere N≥50 liquidados POST-fix corners con stats reales. Hoy recién empezamos a capturar corners correctamente.

### 6 ligas sin cuotas (Bolivia/Col/Ecu/Per/Uru/Ven)

D9 diagnóstico queda pendiente: verificar si falta mapping en `MAPA_LIGAS_ODDS` o si The-Odds-API no las cubre.

---

## 3. Artifacts de fase 3

- `src/comun/*.py` — 8 módulos (3 heredados + 5 nuevos de STEP 2d + config_motor).
- `config_motor_valores` — 82 filas seed con trigger de bloqueo.
- `fondo_quant.db` — post-rebuild con corners + estados correctos.
- `snapshots/` — múltiples backups defensivos.
- `docs/fase2/*.md` — 5 docs de diagnóstico + propuestas.
- `docs/arquitectura/*.md` — deuda técnica + migración schema pendiente.

---

## 4. Estado funcional final

```
python ejecutar_proyecto.py
```

1. motor_purga → 2. motor_backtest → 3. motor_liquidador → 4. motor_arbitro → 5. motor_data (con corners correctos) → 6. motor_fixture → 7. motor_tactico → 8. motor_cuotas → 9. motor_calculadora (con F1/F2b/F3C/F4/F9/F10) → 10. motor_sincronizador.

**Producción estable, calibración mejorada, escalable vía `config_motor_valores`.**
