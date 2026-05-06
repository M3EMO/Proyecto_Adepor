# Match cuotas-stats — JOIN reglas

**Define:** cómo emparejar registros de `stats_partido_espn` (stats post-partido) con `cuotas_historicas_fdco` (cuotas 1X2 + O/U) para análisis de yield.
**Cobertura actual:** 8,892 / 13,430 (66.2%) post-fix mappings (2026-05-03).

---

## Tablas involucradas

### `stats_partido_espn` (stats post-partido ESPN)

| Col | Tipo | Notas |
|---|---|---|
| liga | TEXT | nombre canónico Adepor (Argentina, Brasil, ENG, ...) |
| fecha | TEXT | YYYY-MM-DD UTC (ESPN convención) |
| ht | TEXT | nombre local ESPN ("Manchester United") |
| at | TEXT | nombre visita ESPN |
| **ht_fdco_norm** | TEXT | NEW — normalizado para JOIN con fdco |
| **at_fdco_norm** | TEXT | NEW — normalizado para JOIN con fdco |
| **fecha_fdco** | TEXT | NEW — fecha resuelta para JOIN (timezone shift LATAM) |
| (otras stats) | INTEGER/REAL | hg, ag, hst, ast, hs, as_v, hc, ac, h_pos, ... |

### `cuotas_historicas_fdco` (cuotas football-data.co.uk)

| Col | Tipo | Notas |
|---|---|---|
| liga | TEXT | mismo schema canónico |
| fecha | TEXT | YYYY-MM-DD hora local (fdco convención) |
| equipo_local | TEXT | nombre local fdco ("Man United") |
| equipo_visita | TEXT | idem |
| equipo_local_norm | TEXT | normalizado lowercase + alphanum |
| equipo_visita_norm | TEXT | idem |
| cuota_1, cuota_x, cuota_2 | REAL | cuotas 1X2 cierre |
| cuota_o25, cuota_u25 | REAL | over/under 2.5 goles |

---

## Query JOIN canónico

**Use SIEMPRE este JOIN** (post-fix mappings + timezone):

```sql
SELECT s.liga, s.fecha, s.ht, s.at, ...,
       f.cuota_1, f.cuota_x, f.cuota_2
FROM stats_partido_espn s
JOIN cuotas_historicas_fdco f
  ON s.liga = f.liga
 AND s.fecha_fdco = f.fecha          -- USAR fecha_fdco (no fecha)
 AND s.ht_fdco_norm = f.equipo_local_norm
 AND s.at_fdco_norm = f.equipo_visita_norm
WHERE f.cuota_1 IS NOT NULL
  AND f.cuota_x IS NOT NULL
  AND f.cuota_2 IS NOT NULL
```

**Crítico:** usar `s.fecha_fdco`, NO `s.fecha`. La diferencia es timezone shift en ARG/BRA (UTC vs UTC-3) que desfasa partidos nocturnos ±1 día.

---

## Cobertura por liga (2026-05-03 post-fix)

| Liga | Stats N | Matched | % |
|---|---|---|---|
| Alemania | 927 | 927 | 100% |
| Argentina | 1217 | 1217 | 100% |
| Brasil | 1209 | 1209 | 100% |
| España | 1155 | 1155 | 100% |
| Francia | 1002 | 1002 | 100% |
| Inglaterra | 1169 | 1169 | 100% |
| Italia | 1148 | 1148 | 100% |
| Turquía | 1094 | 1065 | 97.3% (techo natural — Hatay 2023 terremoto) |
| **EUR/TUR/ARG/BRA** | **8,921** | **8,892** | **99.7%** |
| Bolivia | 572 | 0 | 0% (sin cobertura fdco) |
| Chile | 739 | 0 | 0% |
| Colombia | 616 | 0 | 0% |
| Ecuador | 386 | 0 | 0% |
| Noruega | 750 | 0 | 0% |
| Perú | 517 | 0 | 0% |
| Uruguay | 379 | 0 | 0% |
| Venezuela | 550 | 0 | 0% |
| **LATAM no-fdco** | **4,509** | **0** | **0%** (requiere theoddsapi) |

---

## Mappings ESPN → fdco (extracto)

`stats_partido_espn.ht_fdco_norm` se popula via mapping `ESPN_name → fdco_norm`. Cobertura completa per liga en `analisis/fix_match_todas_ligas.py`. Ejemplos:

```
Alemania:
  "Borussia Dortmund" → "dortmund"
  "Bayer Leverkusen"  → "leverkusen"
  "Borussia Mönchengladbach" → "m'gladbach"
  "Eintracht Frankfurt" → "einfrankfurt"
  ...

Inglaterra:
  "Manchester United" → "manunited"
  "Tottenham Hotspur" → "tottenham"
  "Wolverhampton Wanderers" → "wolves"
  "Nottingham Forest" → "nott'mforest"

Argentina:
  "Argentinos Juniors" → "argentinosjrs"
  "Atlético Tucumán" → "atl.tucuman"
  "Estudiantes de La Plata" → "estudiantesl.p."
  ...

Italia:
  "AC Milan" → "milan"
  "Internazionale" → "inter"
  "AS Roma" → "roma"
  "Hellas Verona" → "verona"
```

---

## Manejo timezone shift

Para LATAM (ARG/BRA), ESPN guarda fechas UTC, fdco guarda hora local (UTC-3). Partidos nocturnos cruzan medianoche → desfasan ±1 día.

**Solución:** col `fecha_fdco` resuelve la fecha canónica fdco:
- Para EUR/TUR (UTC vs UTC+1/+2 sin shift dramático): `fecha_fdco = fecha`.
- Para ARG/BRA: `fecha_fdco = fecha − 1 día` si hora del partido < 03:00 UTC, `fecha_fdco = fecha` else.

Implementado en `analisis/fix_match_todas_ligas.py`.

---

## Reglas para nuevo código

1. **NUNCA** usar `s.fecha = f.fecha` para JOIN (perderá ARG/BRA matches).
2. **SIEMPRE** filtrar `f.cuota_1 IS NOT NULL` (algunas filas tienen stats pero no cuotas — ej Hatayspor 2023 post-terremoto).
3. **NO contar LATAM** en cobertura de validación cuotas (universo efectivo = 8,892, no 13,430).

---

## Documentación relacionada

- `docs/papers/expansion_match_cuotas.md` — investigación expansion 21% → 66.2%
- `analisis/fix_match_todas_ligas.py` — código que populá `ht_fdco_norm`/`at_fdco_norm`/`fecha_fdco`
- `src/comun/gestor_nombres.py` — gestión de nombres canónicos Adepor (NO usar para fdco match — usar mapping específico)
