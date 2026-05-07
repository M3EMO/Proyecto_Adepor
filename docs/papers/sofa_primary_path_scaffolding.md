# SOFA-primary path en motor_data — scaffolding

**Fecha:** 2026-05-07
**Trigger:** probe empírico SofaScore confirma que 7 ligas EU expansión (Holanda,
Portugal, Escocia, Dinamarca, Bélgica, Grecia, Suecia) tienen statistics +
shotmap completos vía API SOFA, contradiciendo doc previo `ligas_eu_expansion.md`
(2026-05-02) que las descartaba por falta de stats ESPN.

## Probe empírico (analisis/test_sofa_ligas_eu_expansion.py)

| Liga | uniqueTournament tid | Statistics | Shotmap | xg/shot | xgot/shot |
|---|---|---|---|---|---|
| Holanda Eredivisie | 37 | 113 items | 34 shots | 100% | 100% |
| Portugal Primeira | 238 | 125 items | 24 shots | 100% | 100% |
| Escocia Premiership | 36 | 127 items | 22 shots | 100% | 100% |
| Dinamarca Superliga | 39 | 126 items | 33 shots | 100% | **100%** ⭐ |
| Bélgica Pro League | 38 | 126 items | 27 shots | 100% | **100%** ⭐ |
| Grecia Super League | 185 | 127 items | 22 shots | 100% | **100%** ⭐ |
| Suecia Allsvenskan | 40 | 121 items | 22 shots | 0% | 0% (fallback custom) |

⭐ = ligas que `ligas_eu_expansion.md` descartaba por ESPN-only y resultan VIABLES vía SOFA.

## Cambios persistidos hoy (scaffolding INACTIVO)

1. **`src/comun/config_sistema.py`**: agregada constante `LIGAS_SOFA_PRIMARY`
   (set de 7 nombres internos). Las 7 ligas NO están en `LIGAS_ESPN` todavía,
   ergo `motor_data` no las itera. La constante solo activa el branch
   SOFA-primary cuando una liga aparece simultáneamente en `LIGAS_SOFA_PRIMARY`
   ∩ `LIGAS_ESPN`. Hoy intersección = ∅.

2. **`scripts/scrape_sofa_post_liquidacion.py`**: agregados 7 IDs
   `uniqueTournament` (NED 37, POR 238, SCO 36, DEN 39, BEL 38, GRE 185, SWE 40)
   al dict `SOFASCORE_LIGA_IDS`. Inactivos hasta que las ligas existan
   en `stats_partido_espn` (gated por `cargar_pendientes`).

3. **`src/ingesta/motor_data.py`**:
   - Helper `lookup_stats_sofa_primario(conn, liga, fecha, ht, at)`:
     busca `sofascore_match_features` con `norm_team_name` + ventana fecha ±2,
     devuelve dict (sot, shots, corners) por equipo o None. Solo opera si
     `liga in LIGAS_SOFA_PRIMARY`.
   - En el loop principal LIGAS_ESPN, después de extraer ESPN:
     ```
     stats_sofa = lookup_stats_sofa_primario(...)
     if stats_sofa is not None:
         override (sot_loc, shots_loc, corners_loc) y (sot_vis, shots_vis, corners_vis)
     ```
   - Guard: si liga no está en `LIGAS_SOFA_PRIMARY`, helper devuelve None
     antes de hacer cualquier query DB → cero overhead para las 16 ligas
     onboardeadas hoy.

## Limitación temporal documentada

`scrape_sofa_post_liquidacion.py` corre en FASE 3.1 (después de
`motor_data` en FASE 3). Ergo:

- **Día 1 fresh events** (DEN/BEL/GRE recién scrapeados ESPN): SOFA aún no
  cargó esa fecha → `lookup_stats_sofa_primario` MISS → fallback ESPN
  (statistics[] vacío → 0,0,0). `partidos_backtest` queda con
  (sot=0, shots=0, corners=0) ese día. xG sí se rellena vía
  FASE 3.15-3.17 (recompute xg_v3 desde shotmap_json). EMA absorve el ruido.

- **Día 2+** (mismos eventos ya liquidados, SOFA scrapeado): re-pass
  sobre `partidos_backtest` actualizaría stats si motor_data los
  re-procesara, pero el flujo actual NO re-procesa events ya marcados
  `procesados`. Stats quedan en (0,0,0).

**Trade-off aceptado para scaffolding:** el motor de calibración (β_sot,
OLS xG, rho DC) para las 7 ligas requerirá un step adicional al onboardear
(e.g. `scripts/backfill_partidos_backtest_stats_sofa.py`) que update
sot/shots/corners desde `sofascore_match_features` para `liga IN
LIGAS_SOFA_PRIMARY`. NO se implementa hoy — se dejará al bead epic
de onboarding cuando cada liga entre a producción.

## Test de inactividad (smoke)

```python
from src.comun.config_sistema import LIGAS_ESPN, LIGAS_SOFA_PRIMARY
assert LIGAS_SOFA_PRIMARY & set(LIGAS_ESPN.values()) == set()  # ∅
```

Ejecutado y validado 2026-05-07. Behavior change esperado para 16 ligas hoy
onboardeadas: NINGUNO.

## Activación futura (no en esta sesión)

Cada liga EU expansión activa el path SOFA-primary cuando:

1. Se agrega a `LIGAS_ESPN` (con código ESPN slug + nombre interno).
2. Se agrega a `MAPA_LIGAS_ODDS` (TheOddsAPI key o None).
3. Calibración inicial: β_sot per liga, rho DC, OLS xG (después del
   primer scrape SOFA backfill 2024-2026).
4. Onboarding completo via `onboarder_liga` agent + bead `[INFRA EPIC]`.

## Referencias

- `docs/papers/ligas_eu_expansion.md` (2026-05-02) — análisis ESPN-only previo,
  ahora parcialmente obsoleto (ver "Update 2026-05-07" agregado a esa fecha).
- `docs/papers/motor_xg_v3_estado_consolidado.md` — motor xG v3 OPERATIVO
  (cascada V3 > V_custom > V0 ESPN), aplicable a SOFA-primary.
- `analisis/test_sofa_ligas_eu_expansion.py` — script de probe reproducible.
- `analisis/test_sofa_search_ligas.py` — confirmó tids vía SofaScore search API.
