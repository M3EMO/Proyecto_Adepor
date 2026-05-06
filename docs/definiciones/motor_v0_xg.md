# Motor V0 — xG productivo

**Define:** fórmula del motor xG productivo Adepor (V0).
**Código de referencia:** `src/ingesta/motor_data.py:119-157` (función `calcular_xg_hibrido`).

---

## Fórmula

Para un partido con stats post-partido `{SOT, total_shots, corners}` del equipo `e` y `goles_reales_e`:

```
shots_off_e = max(0, total_shots_e − SOT_e)

xg_calc_e   = β_sot(liga) · SOT_e
            + β_shots_off  · shots_off_e
            + coef_corner(liga) · corners_e

xg_final_e  = θ · xg_calc_e + (1 − θ) · goles_reales_e
```

**Edge case:** si `xg_calc_e == 0` y `goles_reales_e > 0` → retornar `goles_reales_e` directamente (skip híbrido).

---

## Parámetros

| Parámetro | Valor productivo | Scope | Tabla DB |
|---|---|---|---|
| `θ` (theta híbrido) | **0.70** | global hardcoded | `motor_data.py:156` |
| `β_sot` | 0.331-0.414 (per liga) / 0.352 (default) | per liga | `config_motor_valores.beta_sot` |
| `β_shots_off` | 0.010 | global | `config_motor_valores.beta_shots_off` |
| `coef_corner` | 0.02-0.03 (per liga) | per liga | `ligas_stats.coef_corner_calculado` |

---

## Hallazgo empírico (2026-05-03)

`θ = 0.70` está sub-óptimo. Óptimo OOS pool 2022-2025 es **θ = 0.15** (RMSE 1.187 vs motor 1.289, mejora −7.9%). Re-evaluar tras motor v2.

---

## Pseudocódigo

```python
def calcular_xg_hibrido(stats, goles_reales, liga):
    sot = stats.get("shotsOnTarget", 0)
    total_shots = stats.get("totalShots", 0)
    corners = stats.get("wonCorners", 0)
    shots_off = max(0, total_shots - sot)

    beta_sot = get_param("beta_sot", scope=liga, default=0.352)
    beta_shots_off = get_param("beta_shots_off", default=0.010)
    coef_corner = get_param("coef_corner_calculado", scope=liga, default=0.03)

    xg_calc = beta_sot * sot + beta_shots_off * shots_off + coef_corner * corners

    if xg_calc == 0 and goles_reales > 0:
        return goles_reales

    THETA = 0.70  # motor productivo — sub-óptimo según hallazgos 2026-05-03
    xg_final = THETA * xg_calc + (1 - THETA) * goles_reales
    return round(xg_final, 3)
```

---

## Cascada de recalibración (al cambiar θ o coefs)

Cualquier cambio a `xg_final` invalida y obliga recalibrar:
1. `ρ` Dixon-Coles per liga (`scripts/calibrar_rho.py`)
2. `gamma_1x2` display (scope=liga)
3. `factor_corr_xg_ou` per liga
4. EMA residuals (`motor_data.py`)

**Precedente:** Fix A del Manifiesto → yield −35.9pp por tocar `xg_visita` sin cascada.

---

## Outputs persistidos del motor V0

- `partidos_backtest.xg_local`, `xg_visita` (motor productivo aplicado a histórico)
- `historial_equipos.ema_xg_favor`, `ema_xg_contra` (EMA de `xg_final`)
- `predicciones_walkforward.fuente='walk_forward_sistema_real'` (probas 1X2 derivadas)

---

## Versiones SHADOW

- **V5_xg_calc** = Ridge(SOT, shots_off, corners, pos, saves_rival), positive=True, intercept libre. Fit empírico: `xg_calc ≈ 0.273 + 0.247·SOT` (los demás features shrink a 0 por NNLS).
- **V_dual** = Ridge sobre [EMA(xg_v5), EMA(residuo=goles−xg_v5)] como features paralelas para predict λ por equipo.
- **V_ruido** = Ridge sin SOT (solo shots_off, corners, possession, pass_pct, saves_rival, blocks_rival, longballs). R² ≈ 0.013, casi nulo predictor.

Ninguna promovida. Ver `docs/papers/audit_xg_v5_evolucion.md`.
