# Papers: shifts de goals/xG por EDICIÓN (no por país agregado)

> **Fecha:** 2026-04-29
> **Convención (decisión usuario 2026-04-29):** IN-SAMPLE = 2026 (año en curso);
> OOS = 2022-2025.
> **Pregunta de investigación:** ¿Hay shifts estadísticamente significativos en
> goals/partido por **edición específica** (Libertadores, UCL, FA Cup, Copa del
> Rey, etc.)? El análisis agregado por (país, comp_tipo) podría enmascarar
> tendencias opuestas dentro de una misma celda.
> **Sources:** análisis empírico `analisis/xg_shift_per_copa_per_year.py` +
> Davis et al. 2024 ML journal (concept drift sports).

---

## HALLAZGO CRÍTICO: el agregado enmascara tendencias opuestas

El análisis previo agregado mostraba **"copa_internacional Internacional ESTABLE"**
(1,632 partidos pooled, bias 0.996, no significativo).

Desagregado por edición específica revela:

| Edición | bias recent vs train | p-value | Sig | Dirección |
|---|---|---|---|---|
| **Champions League** | **1.133** | 0.0009 | *** | **ALCISTA fuerte** |
| Europa League | 0.983 | 0.665 | — | Estable |
| **Conference League** | **0.925** | 0.042 | * | **BAJISTA** |
| Libertadores | 0.923 | 0.117 | — | Bajista no-sig |
| **Sudamericana** | **0.882** | 0.015 | * | **BAJISTA** |
| FIFA Club World Cup | 1.000 | — | — | (N chico, 64 partidos solo 2025) |

**Las tendencias se cancelaban en el promedio "copa_internacional Internacional".**
UCL alcista compensa Conference + Sudamericana bajistas. Esto es lo que el
usuario quería ver al pedir desagregar por edición — la decisión fue acertada.

---

## Tabla completa goals/partido por edición

| Edición | Tipo | 2022 | 2023 | 2024 | 2025 | 2026 IS | Δ 26-22 |
|---|---|---|---|---|---|---|---|
| Conference League | copa_int | 2.559 | 2.947 | 2.785 | 2.544 | 2.655 | +0.096 |
| **Champions League** | copa_int | 2.951 | 2.939 | 3.053 | 3.300 | **3.675** | **+0.724** |
| Europa League | copa_int | 2.669 | 3.011 | 2.841 | 2.826 | 2.724 | +0.054 |
| **Libertadores** | copa_int | 2.465 | 2.490 | 2.387 | 2.381 | **2.045** | **−0.420** |
| **Sudamericana** | copa_int | 2.516 | 2.535 | 2.497 | 2.389 | **1.868** | **−0.648** |
| FIFA Club World Cup | copa_int | — | — | — | 3.094 | — | — |
| FA Cup | copa_nac | 3.248 | 3.458 | 3.151 | 3.026 | 2.867 | −0.382 |
| Coupe de France | copa_nac | 2.788 | 2.970 | 3.152 | 3.159 | — | +0.371 |
| Copa do Brasil | copa_nac | 2.303 | 2.492 | 2.189 | 2.402 | 2.118 | −0.185 |
| **Copa del Rey** | copa_nac | 2.774 | 2.897 | 2.968 | **3.342** | — | **+0.568** |
| Türkiye Kupası | copa_nac | 3.265 | 3.128 | 3.274 | 3.209 | — | −0.056 |
| EFL Cup | copa_nac | 2.631 | 2.887 | 3.258 | 2.774 | — | +0.143 |
| Copa Argentina | copa_nac | 2.484 | 2.365 | 2.254 | 2.317 | 2.500 | +0.016 |
| DFB Pokal | copa_nac | 3.958 | 3.972 | 3.381 | 3.369 | — | −0.589 |
| **Coppa Italia** | copa_nac | 3.786 | 2.898 | 3.163 | **2.326** | — | **−1.460** |

---

## Tabla bias factor recommendation por edición (recent vs train)

| Edición | g_train | g_recent | N_train | N_recent | bias | p | Sig |
|---|---|---|---|---|---|---|---|
| Conference League | 2.772 | 2.565 | 1,196 | 317 | 0.925 | 0.042 | * |
| **Champions League** | 2.984 | 3.381 | 626 | 360 | **1.133** | 0.0009 | *** |
| Europa League | 2.855 | 2.807 | 538 | 410 | 0.983 | 0.665 | — |
| Libertadores | 2.447 | 2.258 | 465 | 244 | 0.923 | 0.117 | — |
| **Sudamericana** | 2.516 | 2.219 | 471 | 233 | **0.882** | 0.015 | * |
| **FA Cup** | 3.286 | 3.000 | 2,574 | 184 | **0.913** | 0.031 | * |
| Coupe de France | 3.002 | 3.159 | 560 | 82 | 1.052 | 0.454 | — |
| Copa do Brasil | 2.328 | 2.267 | 366 | 232 | 0.974 | 0.633 | — |
| **Copa del Rey** | 2.890 | 3.342 | 345 | 158 | **1.156** | 0.0085 | ** |
| Türkiye Kupası | 3.222 | 3.209 | 445 | 43 | 0.996 | 0.963 | — |
| EFL Cup | 2.934 | 2.774 | 274 | 93 | 0.945 | 0.426 | — |
| Copa Argentina | 2.367 | 2.376 | 188 | 93 | 1.004 | 0.962 | — |
| DFB Pokal | 3.764 | 3.369 | 182 | 65 | 0.895 | 0.143 | — |
| **Coppa Italia** | 3.198 | 2.326 | 126 | 43 | **0.727** | 0.002 | ** |

**6 ediciones con shift significativo** (vs solo 3 cuando agregaba por país).

---

## Tabla bias por-año IS=2026 (drift en curso)

| Edición | OOS pooled (22-25) | IS 2026 | N 2026 | bias_2026 | Flag |
|---|---|---|---|---|---|
| Conference League | 2.731 | 2.655 | 58 | 0.972 | — |
| **Champions League** | 3.083 | **3.675** | 77 | **1.192** | **★ SHIFT FUERTE** |
| Europa League | 2.844 | 2.724 | 76 | 0.958 | — |
| **Libertadores** | 2.431 | **2.045** | 89 | **0.841** | **★ SHIFT FUERTE** |
| **Sudamericana** | 2.484 | **1.868** | 76 | **0.752** | **★ SHIFT FUERTE** |
| FA Cup | 3.272 | 2.867 | 30 | 0.876 | shift moderado |
| Copa do Brasil | 2.346 | 2.118 | 110 | 0.903 | shift moderado |
| Copa Argentina | 2.355 | 2.500 | 30 | 1.062 | — |

**3 SHIFTS FUERTES IS 2026** vs OOS 2022-2025:

1. **Champions League IS +19.2%**: tendencia alcista que viene desde 2024+, IS confirma. Estilo abierto + ataques top.

2. **Libertadores IS −15.9%**: shift bajista nuevo en 2026. N=89 confiable. Posible composición cohort: equipos menos dominantes.

3. **Sudamericana IS −24.8%**: shift bajista MUY fuerte. N=76 confiable.

---

## Causa probable por edición (hipótesis literatura)

| Edición | Tendencia | Hipótesis |
|---|---|---|
| Champions League | +19% IS | Reformat Swiss league phase 2024-25 (más matchups balanceados, menos blowouts pero más goles netos). Top teams mantienen producción |
| Sudamericana / Libertadores | −16-25% IS | Schedule congestion CONMEBOL 2026 (más fixturing simultáneo Brasileirão/Libertadores). Equipos rotan key players. Davis 2024 scheduling effects |
| Copa del Rey | +16% recent | VAR + tactical change Real Madrid era 2023+ (literatura tactical España) |
| Coppa Italia | −27% recent | Calcio defensivo 2024-25 (literatura tactical italiana) |
| FA Cup | −9% recent | Top teams rotan más en early rounds — matchups menos clearcut |
| Conference League | −7% recent | Mismo schedule effect que UEL/UCL |

---

## Bias factors PROPUESTOS para motor (PERSISTIR)

### Conservadores (sólo aplicar significativos p<0.05, fallback 1.0)

```json
{
  "edicion_xg_bias_factors": {
    "Champions League": 1.133,
    "Copa del Rey": 1.156,
    "Conference League": 0.925,
    "Sudamericana": 0.882,
    "FA Cup": 0.913,
    "Coppa Italia": 0.85,
    "_fallback": 1.0
  },
  "fuente": "analisis/xg_shift_per_copa_per_year.py 2026-04-29",
  "ventana_train": "2022-2024",
  "ventana_recent": "2025-2026",
  "p_threshold": 0.05,
  "italia_conservador": "0.727 medido pero con N=43 chico → conservar 0.85"
}
```

### Per-año (rolling, recalcular mensualmente)

`analisis/xg_shift_per_copa_per_year.py` cron mensual → actualizar tabla
`xg_bias_per_edicion_per_year` para detectar drifts emergentes (UCL +19%
2026 IS es señal a vigilar).

### Aplicación en motor (F2-sub-15)

```python
# motor_calculadora.py — hook nuevo en predict_xg_copa()
def predict_xg_copa(eq_l, eq_v, fecha, competicion):
    xg_l_raw, xg_v_raw = predict_xg_via_v6_or_proxy(eq_l, eq_v, fecha)

    # Bias correction por edición [REF: docs/papers/v14_xg_shift_per_copa.md]
    bias_per_ed = json.loads(get_config("edicion_xg_bias_factors"))
    bias = bias_per_ed.get(competicion, bias_per_ed.get("_fallback", 1.0))

    return xg_l_raw * bias, xg_v_raw * bias
```

**Nota:** V14 v2 NO usa xG, solo `delta_elo + dummies`. Bias factors NO afectan
SHADOW V14 v2. Sí afectan motor V0/V12 productivo cuando F2-sub-15 integre
copas al pipeline.

---

## Sources

- `analisis/xg_shift_per_copa_per_year.py` (script reproducible)
- `analisis/xg_shift_per_copa_per_year.json` (datos persistidos, 16 ediciones)
- Davis et al. 2024 ML journal (53 cits OpenAlex) — concept drift sports
- Cavus & Biecek 2022 (arXiv 2206.07212) — xG model + tactical features
- `docs/papers/predicciones_por_liga.md` — literatura por liga (15 fuentes)

[REF: docs/papers/v14_xg_shift_per_copa.md]
