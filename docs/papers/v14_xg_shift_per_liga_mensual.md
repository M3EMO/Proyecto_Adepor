# Papers: shift xG por liga, año, mes calendario + propuesta motor xG

> **Fecha:** 2026-04-29
> **Convención (decisión usuario 2026-04-29):** IN-SAMPLE = 2026 (año en curso);
> OOS = 2022-2025.
> **Pregunta de investigación:** ¿Hay shifts en xG/goles por (liga, año, mes
> calendario)? ¿El motor xG actual está sub-/sobre-calibrado per liga? ¿Cambios
> de formato calendario (anual → apertura/clausura) causan drift?
> **Sources:** análisis empírico `analisis/xg_shift_per_liga_per_year.py` +
> `analisis/xg_shift_per_mes_calendario.py` + OpenAlex 240M+ works.

---

## Motor xG actual (referencia)

Fórmula post-partido (calibrar_xg.py):
```
xG = β_sot · sot + β_shots_off · shots_off + β_corner · corners
    donde shots_off = max(0, shots − sot)
```

Coeficientes:
- `β_sot`: calibrado per liga, default 0.352, clamp [0.25, 0.45] (rango Opta)
- `β_shots_off`: 0.010 fijo (no calibrado)
- `β_corner`: 0.030 fijo (no calibrado)

Calibración actual usa **`partidos_backtest`** (612 filas liquidadas), NO usa
`partidos_historico_externo` (14,489 filas, mucho más data).

Calibrados per liga actualmente: Argentina (0.331), Brasil (0.331), Inglaterra (0.352
default), Noruega (0.351), Turquía (0.414). Resto fallback 0.352.

---

## Hallazgo 1: bias xG/goles ESTRUCTURAL por liga (problema sistemático)

| Liga | xG_estimado avg | goles_avg | bias xG/g | Comentario |
|---|---|---|---|---|
| Alemania | 3.79 | 3.12 | **1.21** | xG sobre-estima 21% |
| Argentina | 3.07 | 2.09 | **1.47** | sobre-estima **47%** ★ |
| Brasil | 3.48 | 2.44 | **1.43** | sobre-estima 43% ★ |
| Chile | 3.61 | 2.68 | 1.35 | sobre-estima 35% |
| Colombia | 3.30 | 2.21 | **1.49** | sobre-estima 49% ★ |
| España | 3.36 | 2.57 | 1.31 | sobre-estima 31% |
| Francia | 3.60 | 2.83 | 1.27 | sobre-estima 27% |
| Inglaterra | 3.71 | 2.97 | 1.25 | sobre-estima 25% |
| Italia | 3.40 | 2.65 | 1.28 | sobre-estima 28% |
| Turquía | 4.18 | 2.90 | **1.44** | sobre-estima 44% ★ |

**LECTURA:** xG estimado SISTEMÁTICAMENTE sobre-shoot goles reales en TODAS las ligas.
La fórmula motor está calibrada para Opta-style premier league (β_sot 0.352) que
asume conversión shots→goals balanceada. **LATAM y Turquía conversiones más bajas**
(menor calidad de remate, más bloqueos defensivos, peores keepers? — hipótesis
literatura `docs/papers/predicciones_por_liga.md`).

**Implicación motor:** el `gamma_1x2` (display correction post-fórmula) está
parcheando este bias para display, pero el xG que entra al **Poisson DC para
prob 1X2** sigue inflado. Esto sesga prob_local hacia arriba en LATAM/Turquía.

**Causa probable:**
- β_sot global 0.352 sobreestima en LATAM (deberían estar en 0.25-0.30)
- `β_shots_off=0.010` y `β_corner=0.030` aplicados igual en todas las ligas — pero
  conversion rate de shots-off-target y corners varía entre ligas

---

## Hallazgo 2: data 2025-2026 ligas NO existe en `partidos_historico_externo`

```
Distribución partidos_historico_externo por temp:
  2021: 2,206
  2022: 4,145
  2023: 4,308
  2024: 3,830
  (NO 2025, NO 2026)
```

**No se puede medir shift recent vs train en ligas hasta scraping nuevo (Opción C
adepor-d5u football-data.co.uk + ESPN scraper extension).**

---

## Hallazgo 3: PATRONES MENSUALES significativos por liga

Spread (max bias mes − min bias mes) cross-año:

| Liga | Mes pico | bias_max | Mes valle | bias_min | Spread |
|---|---|---|---|---|---|
| **Bolivia** | 4 (abr) | 1.174 | 7 (jul) | 0.769 | **40.5%** |
| **Francia** | 8 (ago) | 1.141 | 11 (nov) | 0.891 | 25.0% |
| **Italia** | 9 (sep) | 1.076 | **3 (mar)** | **0.836** | 24.0% |
| **Alemania** | 5 (may) | 1.136 | 2 (feb) | 0.916 | 22.0% |
| Turquía | 5 | 1.110 | 8 | 0.898 | 21.2% |
| Brasil | 10 | 1.115 | 8 | 0.922 | 19.3% |
| Ecuador | 6 | 1.151 | 5 | 0.959 | 19.3% |
| España | 9 | 1.090 | 1 | 0.905 | 18.5% |
| Argentina | 10 | 1.078 | 11 | 0.907 | 17.1% |
| Chile | 11 | 1.106 | 4 | 0.934 | 17.2% |
| Colombia | 5 | 1.040 | 2 | 0.904 | 13.5% |
| **Inglaterra** | 4 | 1.038 | 8 | 0.967 | **7.1%** ESTABLE |
| **Uruguay** | 2 | 1.034 | 5 | 0.986 | **4.8%** ESTABLE |

**LECTURA:**

1. **Inglaterra y Uruguay** son las ligas MÁS ESTABLES mensualmente (spread <8%).
   El motor xG default funciona bien sin corrección mensual.

2. **Bolivia spread 40%** — extremo. Motor sin corrección mensual pierde
   ~40pp en partidos abr vs jul. Probable: temporada fragmentada (descansos
   en jul-ago) cambia condiciones físicas.

3. **Italia spread 24% con valle marzo (0.836)** — congestión Coppa Italia +
   Champions League cuartos. **Carling et al. 2019 (PLoS ONE, 54 cits)** y
   **Sports Medicine 2022 (46 cits)**: fixture congestion → injury → performance
   decay. Marzo coincide con epicenter congestion italiana.

4. **Alemania pico mayo (1.136)** — fin temporada Bundesliga, do-or-die.
   Adicional: descenso en juego, equipos juegan abierto. Coincide con
   Goddard-Karavias 2017 PARX (`docs/papers/v14_train_coverage.md`).

5. **Francia valle noviembre, pico agosto** — pretemporada vs mid-season fatigue.

---

## Hallazgo 4: PATRONES MENSUALES en COPAS (más extremos)

| Edición | Pico | bias_max | Valle | bias_min | Spread |
|---|---|---|---|---|---|
| **DFB Pokal** | 7 (jul) | 1.14 | 12 (dic) | 0.82 | **14.5%** |
| **Libertadores** | 5 (may) | 1.14 | 8 (ago) | 0.78 | 11.8% |
| **Copa Argentina** | 3 (mar) | 1.16 | 8 (ago) | 0.80 | 11.2% |
| Türkiye Kupası | 12 (dic) | 1.19 | 9 (sep) | 0.89 | 9.7% |
| Copa del Rey | 10 (oct) | 1.10 | 12 (dic) | 0.86 | 8.8% |
| Copa do Brasil | 4 (abr) | 1.10 | 8 (ago) | 0.90 | 7.3% |

**Las copas con eliminatorias muestran picos en rounds early (más goleadas
favoritos vs underdogs) y valles en rounds finales (top vs top, partidos
cerrados).** DFB Pokal extremo: jul early rounds vs dic mid rounds (spread 14.5%).

---

## Hallazgo 5: 5 LIGAS CAMBIARON FORMATO CALENDARIO

| Liga | Formatos | Cambios |
|---|---|---|
| **Argentina** | feb-oct (2022) → ene-dic (2023-25) → ene-jun **2026 Apertura** | 4 formatos |
| **Brasil** | abr-nov → abr-dic → mar-dic | 3 formatos |
| **Noruega** | abr-nov → abr-dic → mar-nov | 3 formatos |
| Chile | feb-dic → ene-dic | 2 formatos |
| Perú | ene-nov → feb-nov | 2 formatos |

**Argentina cambió a Apertura/Clausura en 2026** — riesgo de drift estructural.
EMA xG basadas en histórico anual (2022-2025) NO reflejan dinámica
apertura/clausura (mini-torneo 6 meses).

**Hipótesis:** equipos en apertura tienen más variance early-season + rotación
mayor. Goles pueden variar significativamente del baseline anual.

---

## Investigación académica relevante

| Paper | Cits | Aplicación |
|---|---|---|
| **Carling et al. 2019 — Players' Physical Performance Decreased After Two-Thirds of the Season** (Int. J. Env. Res. Pub. Health) | 46 | Fundamenta valle marzo Italia + valle noviembre Francia (mid/late-season fatigue). |
| **Sports Medicine 2022 — Fixture Congestion + Injury Soccer** | 46 | Fixture congestion → injury → degraded performance. Aplicable a Italia (Coppa+CL+Liga simultáneos). |
| **Carling 2019 PLoS ONE — Six weeks congested match play** | 54 | Plasma volume + recovery markers durante congestion → menos calidad de remate. |
| **BMC Sports 2022 — Congested International Match Calendar (1055 players survey)** | 21 | Player views: international break compresses club season. |
| **European J Operational Research 2024 — Tournament design** | 25 | Apertura/clausura format design implications. |
| **Davis et al. 2024 ML journal — Sports analytics methodology** | 53 | Concept drift recommends rolling window retraining + per-context bias correction. |

Sources:
- https://doi.org/10.1371/journal.pone.0219519 (Carling 2019 PLoS)
- https://doi.org/10.1007/s40279-022-01691-2 (Sports Medicine 2022)
- https://doi.org/10.1186/s13102-022-00516-z (BMC Sports 2022)

**Conclusión literatura:** los hallazgos empíricos Adepor (spread mensual 7-40%
por liga, valles concentrados en jul / mar / nov) coinciden con la literatura
de **fixture congestion + late-season fatigue + pretemp recovery**.

---

## PROPUESTA cambios al motor xG (priorizada)

### CAMBIO 1 — Re-calibrar β_sot per liga sobre 14k filas (P0, alto impacto)

**Problema:** calibración actual usa solo `partidos_backtest` (612 filas
liquidadas). Sample chico → β_sot ruidoso, no llega a calibrar bien LATAM.

**Acción:**
- Modificar `scripts/calibrar_xg.py` para usar `partidos_historico_externo`
  (14,489 filas) como source primario.
- Re-calibrar β_sot per liga + agregar β_shots_off y β_corner per liga (no
  fijos).
- OLS multivariada en lugar de OLS univariada con residuos parciales.

**Impacto esperado:** reducir bias xG/goles de ~1.45 a ~1.10 en LATAM. Mejor
calibración prob 1X2 en LATAM.

[REF: docs/papers/v14_xg_shift_per_liga_mensual.md §1]

### CAMBIO 2 — Bias factor mensual per (liga, mes) (P1)

**Problema:** spread mensual 15-40% en mayoría ligas. Motor sin corrección
mensual sub-óptimo.

**Acción:**
- Persistir tabla `xg_bias_per_liga_mes` con factor multiplicativo per (liga, mes).
- Hook en `motor_calculadora.py` durante predict_xg:
  ```python
  bias_mes = xg_bias_liga_mes.get(f"{liga}|{mes:02d}", 1.0)
  xg_predicho_ajustado = xg_predicho * bias_mes
  ```
- Recalibrar mensualmente con `analisis/xg_shift_per_mes_calendario.py` cron.

**Impacto esperado:** reducir RMS error xG-vs-goles en ~10-15pp en ligas
spread alto (Bolivia, Francia, Italia, Alemania).

### CAMBIO 3 — Bias factor mensual per (copa edición, mes) (P1)

Análogo a CAMBIO 2 pero por edición:
- Champions League | mes
- Libertadores | mes
- DFB Pokal | mes
- Coppa Italia | mes
- ...

Persistir en `xg_bias_per_copa_mes`.

**Impacto:** crítico para F2-sub-15 cuando integremos copas al pipeline.

### CAMBIO 4 — Detectar cambio formato calendario → reset EMA (P2)

**Problema:** Argentina cambió a Apertura/Clausura en 2026. EMA basadas en 2022-2025
anual no reflejan dinámica del nuevo formato.

**Acción:**
- Hook en motor: cuando `liga_calendario_temp.formato` cambia entre temp t-1 y t,
  aplicar warmup_ema_factor=0.7 (EMA con menos peso histórico) durante primeros
  N partidos de la nueva temporada.
- Persistir flag en config `formato_change_detected[liga, temp]`.

**Impacto:** evita que el motor use EMA stales en transición de formato.

### CAMBIO 5 — Cron mensual recalibración (P1)

Script wrapper `scripts/recalibrar_xg_mensual.py`:
1. Corre `analisis/xg_shift_per_liga_per_year.py`
2. Corre `analisis/xg_shift_per_mes_calendario.py`
3. Actualiza tablas bias factor en `config_motor_valores`
4. Genera reporte diff vs mes anterior

Agregar a `ejecutar_proyecto.py` como FASE post-pipeline mensual.

---

## Checklist priorización

| Cambio | Prioridad | Esfuerzo | Impacto | Bloqueante de |
|---|---|---|---|---|
| 1 — Re-calibrar β_sot 14k filas | P0 | 2h | Alto en LATAM | F2-sub-15 |
| 2 — Bias mensual per liga | P1 | 4h | Alto Bolivia/Francia/Italia | — |
| 3 — Bias mensual per copa | P1 | 3h | Alto F2-sub-15 | F2-sub-15 |
| 4 — Detectar cambio formato | P2 | 6h | Alto Argentina 2026 | — |
| 5 — Cron mensual | P1 | 2h | Mantenibilidad | — |

**Recomendación de secuencia:**
1. CAMBIO 1 primero (β_sot re-calibrado) — corrige el problema más grande
2. CAMBIO 5 después (cron) — mantenibilidad continua
3. CAMBIOS 2-3 en paralelo
4. CAMBIO 4 último (Argentina 2026 puede esperar 1 mes con monitor)

---

## Sources

- `analisis/xg_shift_per_liga_per_year.py` + `.json`
- `analisis/xg_shift_per_mes_calendario.py` + `.json`
- `docs/papers/xg_seasonality_calendar.md` (papers OpenAlex)
- Carling et al. 2019 PLoS ONE — six weeks congested match play
- Sports Medicine 2022 — fixture congestion injury
- Davis et al. 2024 ML — concept drift sports analytics
- `Reglas_IA.txt` III.A.4 — fórmula xG actual

[REF: docs/papers/v14_xg_shift_per_liga_mensual.md]
