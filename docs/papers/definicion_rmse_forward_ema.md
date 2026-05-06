# Definición precisa — RMSE forward-EMA goles

**Fecha:** 2026-05-03
**Propósito:** especificación matemática y operacional de la métrica usada para validar el motor xG. Para usar como referencia obligatoria en próximas sesiones (motor v2).

---

## Notación

Sea `P_t` el partido número `t` en orden cronológico estricto, con:
- `home_t`, `away_t` = equipos
- `hg_t`, `ag_t` = goles reales del local y visita
- `SOT_e_t`, `shots_off_e_t`, `corners_e_t` = stats post-partido del equipo `e ∈ {home_t, away_t}`

---

## Paso 1 — Computar `xg_final` del partido

Para cada equipo `e ∈ {home_t, away_t}`:

```
xg_calc_e_t  = β_sot(liga) · SOT_e_t
             + 0.010      · shots_off_e_t
             + coef_corner(liga) · corners_e_t

xg_final_e_t = θ · xg_calc_e_t + (1 − θ) · goles_reales_e_t
```

Parámetros:
- `θ` = parámetro híbrido (motor productivo: 0.70; óptimo empírico OOS validado: 0.15)
- `β_sot(liga)` ∈ `config_motor_valores.beta_sot` scope=liga (default global 0.352)
- `coef_corner(liga)` ∈ `ligas_stats.coef_corner_calculado` (default 0.03)
- `shots_off = max(0, total_shots − SOT)`

---

## Paso 2 — EMA forward por equipo (forward-strict)

Cada equipo `e` tiene un estado `EMA_e` evolucionando cronológicamente con ventana **FORWARD-STRICT**:

**Inicialización:** `EMA_e = None`, `n_e = 0`.

**Iteración:** para cada partido `P_t` ordenado por fecha ascendente:

```
# 1. CAPTURAR estado PRE-partido (este es la PREDICCIÓN para P_t)
prediccion_e_t = EMA_e        ← valor de EMA ANTES de incorporar P_t

# 2. UPDATE estado POST-partido (después de capturar)
si EMA_e is None:
    EMA_e = xg_final_e_t
sino:
    EMA_e = α(liga) · xg_final_e_t + (1 − α(liga)) · EMA_e

n_e += 1
```

Parámetro:
- `α(liga)` ∈ `config_motor_valores.alfa_ema` scope=liga (default 0.10)

**Crítico:** la predicción debe capturarse ANTES del update — el evento `P_t` NO está incluido en su propia predicción. Esto garantiza forward-strict (no leakage).

---

## Paso 3 — Cómputo del error por evento

Cada partido `P_t` contribuye **2 eventos** (uno por equipo):

```
evento_local:  predicción = prediccion_home_t,  target = hg_t
evento_visita: predicción = prediccion_away_t,  target = ag_t
```

**Filtro WARMUP:** descartar eventos donde `n_e < WARMUP = 5` (EMA fría, alta varianza).

**Error individual:**
```
error_evento = prediccion − target
```

---

## Paso 4 — RMSE pooled

Sobre el conjunto `S` de eventos válidos (post-warmup):

```
RMSE_S = sqrt( (1 / |S|) · Σ_(evento ∈ S) (error_evento)² )
```

---

## Paso 5 — Splits IS / OOS

Particionar `S` por año del partido:

```
S_2022 = {evento ∈ S : fecha_partido ∈ 2022}
S_2023, S_2024, S_2025, S_2026 idem

S_OOS_pool  = S_2022 ∪ S_2023 ∪ S_2024 ∪ S_2025
S_IS_2026   = S_2026
```

Reportar `RMSE(S_yt)` para cada año + `RMSE(S_OOS_pool)` y `RMSE(S_IS_2026)`.

---

## Interpretación de magnitudes

| RMSE | Interpretación |
|---|---|
| 0.00 | Predicción perfecta (imposible — varianza Poisson irreducible) |
| 1.00 | Objetivo práctico óptimo. Error cuadrático ≈ 1 gol promedio |
| 1.18 | Óptimo empírico actual (θ=0.15) — cerca de cota inferior teórica |
| 1.29 | Motor productivo θ=0.70 — sub-óptimo +9% sobre cota inferior |
| > 1.40 | Sub-calibración severa (xg_calc puro o θ extremo) |

**Cota inferior teórica:** dado λ_promedio ≈ 1.4 goles/equipo/partido, varianza Poisson pura = √λ ≈ 1.18. **Bajar de 1.18 requiere reducir varianza NO-Poisson** vía features adicionales (lineups, lesiones, contexto).

**Objetivo motor v2 (RMSE → 1.0):** implica romper la barrera Poisson via info que el modelo actual no captura.

---

## Pseudocódigo de referencia

```python
from collections import defaultdict
from math import sqrt

WARMUP = 5

def construir_eventos_cronologicos(partidos):
    """Cada partido genera 2 eventos (local + visita)."""
    eventos = []
    for p in sorted(partidos, key=lambda x: x.fecha):
        eventos.append({
            "fecha": p.fecha, "equipo": p.home, "rival": p.away,
            "sot": p.hst, "shots_off": max(0, p.hs - p.hst), "corners": p.hc,
            "goles": p.hg, "liga": p.liga,
        })
        eventos.append({
            "fecha": p.fecha, "equipo": p.away, "rival": p.home,
            "sot": p.ast, "shots_off": max(0, p.asv - p.ast), "corners": p.ac,
            "goles": p.ag, "liga": p.liga,
        })
    return sorted(eventos, key=lambda e: (e["equipo"], e["fecha"]))


def computar_rmse_forward_ema(partidos, theta, beta_sot, coef_corner, alfa_ema):
    """
    Devuelve dict {year: rmse, "OOS_pool": rmse, "IS_2026": rmse}.
    """
    eventos = construir_eventos_cronologicos(partidos)
    state = defaultdict(lambda: {"ema": None, "n": 0})
    errors_by_year = defaultdict(list)

    for ev in eventos:
        liga = ev["liga"]
        beta = beta_sot.get(liga, 0.352)
        coef_c = coef_corner.get(liga, 0.03)
        alfa = alfa_ema.get(liga, 0.10)

        # xg_final
        xg_calc = beta * ev["sot"] + 0.010 * ev["shots_off"] + coef_c * ev["corners"]
        xg_final = theta * xg_calc + (1 - theta) * ev["goles"]

        # CAPTURAR predicción ANTES de update
        s = state[ev["equipo"]]
        if s["ema"] is not None and s["n"] >= WARMUP:
            year = ev["fecha"][:4]
            errors_by_year[year].append(s["ema"] - ev["goles"])

        # UPDATE estado
        if s["ema"] is None:
            s["ema"] = xg_final
        else:
            s["ema"] = alfa * xg_final + (1 - alfa) * s["ema"]
        s["n"] += 1

    # Cómputo RMSE
    def rmse(errs):
        if not errs: return None
        return sqrt(sum(e**2 for e in errs) / len(errs))

    out = {y: rmse(errs) for y, errs in errors_by_year.items()}
    out["OOS_pool"] = rmse([e for y in ("2022", "2023", "2024", "2025")
                             for e in errors_by_year.get(y, [])])
    out["IS_2026"] = out.get("2026")
    return out
```

---

## Validación previa (resultado de referencia)

Sobre `stats_partido_espn` N=13,430 (todas ligas, eventos=26,860, post-warmup ≈ 24,800):

| θ | RMSE OOS pool | RMSE IS 2026 | RMSE 2022 | RMSE 2023 | RMSE 2024 | RMSE 2025 |
|---|---|---|---|---|---|---|
| 0.10 | 1.1885 | 1.1730 | 1.1934 | 1.2128 | 1.1812 | 1.1944 |
| **0.15** | **1.1868** | 1.1956 | 1.1935 | 1.2123 | 1.1798 | 1.1885 |
| **0.20** | 1.1880 | **1.1665** | 1.1968 | 1.2138 | 1.1816 | 1.1855 |
| 0.30 | 1.2128 | 1.2034 | 1.2238 | 1.2400 | 1.2069 | 1.2156 |
| 0.50 | 1.2479 | 1.2274 | 1.2641 | 1.2833 | 1.2462 | 1.2557 |
| **0.70 (motor productivo)** | **1.2890** | **1.2583** | 1.3076 | 1.3320 | 1.2885 | 1.3003 |
| 1.00 | 1.4143 | 1.3832 | 1.4368 | 1.4665 | 1.4198 | 1.4307 |

**Cota inferior demostrada:** RMSE 1.18 (θ=0.15-0.20). Motor productivo 1.29 está +9% por encima del óptimo simple.

---

## Para próxima sesión (motor v2)

1. Re-correr este pseudocódigo con motor v2.
2. Validar que RMSE OOS pool < 1.18 (mejor que cota empírica actual).
3. Si RMSE → 1.0, reportar: el modelo está rompiendo varianza Poisson irreducible.
4. Bonferroni si se prueban múltiples coeficientes (α=0.05/n_features).

**Script de referencia:** `analisis/theta_y_filtros_IS2026.py` (función `ema_with_theta` líneas 50-75 y validación líneas 153-188).
