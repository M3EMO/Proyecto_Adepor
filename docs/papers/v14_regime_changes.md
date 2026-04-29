# Papers: V14 v2 — cambios de régimen año a año

> **Fecha:** 2026-04-29
> **Convención (decisión usuario 2026-04-29):** IN-SAMPLE = 2026 (año en curso);
> OOS = 2022-2025. NO confundir con convención train/test interna del modelo
> (V14 v2 usa train 2022-2024 + test 2025-2026 internamente; pero para juicio
> de producción el AÑO EN CURSO es lo que importa).
> **Pregunta de investigación:** El backtest contrafactual V14 v2 muestra
> heterogeneidad por año (hit 0.43-0.44 sobre 2022-2024 OOS-pasado, hit 0.578
> 2025 OOS-pasado, hit 0.44 2026 IS). ¿La literatura académica documenta
> cambios de régimen en predicción de fútbol? ¿Qué causas y cómo se manejan?
> **Sources:** OpenAlex 240M+ works, WebSearch COVID home advantage, análisis
> empírico goals/copa/año (`docs/papers/v14_xg_shift_per_copa.md`).

---

## Hallazgos clave

### 1. COVID-19 empty stadiums (2020-2021): régimen documentado más fuerte

> Sources:
> - https://www.frontiersin.org/journals/sports-and-active-living/articles/10.3389/fspor.2021.695922/full
> - https://pmc.ncbi.nlm.nih.gov/articles/PMC8670806/
> - https://www.sciencedirect.com/science/article/pii/S1469029223001164

Hallazgos consensuados (10+ ligas europeas + 2 rugby):

- **Home advantage REDUCIDO a la mitad** durante 2020-21 sin público.
  - Pre-COVID: home teams +0.29 goals/partido vs visitor.
  - COVID empty: home teams +0.15 goals/partido (−48%).
  - Premier Rugby + Celtic League: home advantage ANULADO completamente.
- Causa principal: **deterioro performance de los equipos locales** (no bias
  arbitral), por ausencia de stimuli del público.
- Effect documentado en Premier League, La Liga, Serie A, Bundesliga, Ligue 1,
  Belgium Pro League, Eredivisie, Greece, Portugal, Turkey, Premiership Rugby,
  Celtic League.

**Aplicabilidad Adepor:** régimen 2020-21 fue REAL y MEDIBLE. Cualquier modelo
que no haya sido recalibrado en 2020-21 vio degradación severa de calibración.
Adepor no opera en ese período (data 2022+), entonces blindado.

### 2. Davis et al. 2024 — "Methodology and evaluation in sports analytics" (53 cits, ML journal)

> https://doi.org/10.1007/s10994-024-06585-0

Discute **concept drift en sports analytics**:

- "Statistical patterns in sports data are NON-STATIONARY" — tactical evolutions,
  rule changes (VAR, offside rules), squad rotations, new managers.
- Recomienda: **walk-forward validation** (NO random k-fold) + **rolling window
  retraining** + **regime detection cuándo Brier rolling > baseline + 2σ**.

**Aplicabilidad Adepor:** este enfoque es exactamente lo que `adepor-09s` Detector
régimen + el motor adaptativo (drift detector ventana 30d) están construyendo.
V14 v2 SHADOW logging permite validación empírica de drift.

### 3. Thaler 1988 — "Anomalies: The Winner's Curse" (539 cits)

> https://doi.org/10.1257/jep.2.1.191

No específico a sports pero clave conceptualmente: en mercados con incertidumbre,
los "winners" sistemáticamente over-bid. **Aplicación a betting markets:** picks
con yield extremo (45%+) son sospechosos por winner's curse — captura ineficiencias
del modelo, no del mercado real.

### 4. Otros papers OpenAlex (background)

| Year | Cits | Title | Relevancia |
|---|---|---|---|
| 2000 | 525 | The Sports Business as a Labor Market Laboratory (J. Econ. Persp.) | Marco general |
| 2014 | 87 | Gambling advertising: A critical research review | Marco general |
| 2013 | 82 | Financial Fair Play in European Club Football | Marco general |

Ningún paper OpenAlex específico sobre **regime detection in football betting
models** (gap en literatura). Lo más cercano: Davis 2024 (sports analytics
methodology) + Frontiers 2025 Bayesian football (Fontana) que ya citamos en v14.

---

## Análisis empírico Adepor V14 v2 año por año

Backtest contrafactual con `mercado = Elo solo + 6% margen`:

| Año | Status | N partidos | N picks | Hit picks | Yield | Avg cuota | Breakeven hit |
|---|---|---|---|---|---|---|---|
| 2022 | IN-SAMPLE | 1,560 | 89 | 0.427 | +32.57% | 3.141 | 0.318 |
| 2023 | IN-SAMPLE | 2,556 | 287 | 0.432 | +28.91% | 3.068 | 0.326 |
| 2024 | IN-SAMPLE | 2,727 | 372 | 0.444 | +28.85% | 2.978 | 0.336 |
| **2025** | **OOS** | **1,812** | **199** | **0.578** | **+45.79%** | **2.628** | 0.380 |
| **2026** | **OOS YTD** | **547** | **41** | **0.439** | **+13.42%** | **2.764** | 0.362 |

**Lectura:**

1. **2022-2024 IS son MUY estables**: hit ~0.43-0.44 (alpha hit ~0.10), yield
   ~28-32%, cuota ~3.0. Modelo capturando consistente pequeña ineficiencia sobre
   Elo solo.

2. **2025 OOS es OUTLIER POSITIVO**: hit 0.578 (+0.14 sobre IS-avg), cuota
   menor 2.63. **Modelo seleccionó favoritos más confiables ese año.**

3. **2026 OOS YTD vuelve al baseline**: hit 0.439 (en línea con IS), yield
   +13.4% (más bajo que IS — N=41 chico, alta varianza).

**Hipótesis sobre 2025:**

- Dataset enriquecido: scraper ESPN aportó 1,251 partidos Libertadores +
  Sudamericana 2025 completas — perfiles más predecibles (favoritos consolidados).
- Composición no representativa: 2025 dominado por copa internacional sudamericana
  donde los teams establecidos (Flamengo, Palmeiras, River, Boca) dominan
  consistentemente.
- N=199 OOS pequeño: CI95(yield) ≈ ±15pp asintótico → +45% es +30-60% real
  con 95% confianza. Sigue siendo positivo pero rango amplio.

**Conclusión empírica:** **2025 NO es régimen estructural — es composición de
dataset.** 2022, 2023, 2024 IS y 2026 OOS YTD muestran régimen consistente con
yield ~25-30% asumiendo mercado = Elo solo. El 45% de 2025 se explica por
composición del scraping reciente (Libertadores/Sudamericana favorables).

---

## Explicación analítica diff hit-yield

**Fórmula aproximada:** `yield ≈ hit × cuota_avg − 1` (asumiendo Kelly stake
relativamente uniforme).

| Año | Hit | Cuota avg | hit × cuota | yield esperado | yield real | Match |
|---|---|---|---|---|---|---|
| 2022 IS | 0.427 | 3.141 | 1.341 | +34.1% | +32.6% | ✓ |
| 2023 IS | 0.432 | 3.068 | 1.325 | +32.5% | +28.9% | ✓ |
| 2024 IS | 0.444 | 2.978 | 1.322 | +32.2% | +28.9% | ✓ |
| **2025** | 0.578 | 2.628 | 1.519 | **+51.9%** | +45.8% | ✓ |
| 2026 OOS | 0.439 | 2.764 | 1.213 | +21.3% | +13.4% | ✓ aprox |

**Por qué hit alto + cuota baja da yield mayor que hit moderado + cuota alta:**

- Hit 0.44 con cuota 3.0: ganador paga 3.0× stake, perdedor pierde stake → +0.32
- Hit 0.58 con cuota 2.6: ganador paga 2.6× stake, perdedor pierde stake → +0.51

El multiplicador `(cuota − 1)` amplifica el alpha hit sobre breakeven. Cuanto
más alto sea el alpha (hit − 1/cuota), mayor el yield.

**Definición exacta:**
```
yield = sum(stake_i × (cuota_i − 1) si hit_i, sino −stake_i) / sum(stake_i)
      ≈ hit_avg × cuota_avg − 1     (cuando stake es uniforme)
```

Con Kelly stake variable, el modelo asigna más stake a picks con mayor margen.
Esto **amplifica el yield** vs la fórmula simple cuando los hits coinciden con
los stakes mayores. No es nuestro caso (Kelly cap 2.5% activo en 100% picks),
así que la fórmula simple aplica.

---

## Decisión derivada

1. **2025 OOS no debe usarse aislado para validación** — composición sesgada.
   Usar 2022-2024 IS + 2026 OOS YTD para juicio de yield realista (~20-30% sobre
   mercado = Elo solo).

2. **Régimen "estructural" detectable**: literatura confirma concept drift en
   sports models (Davis 2024). Plan `adepor-09s` + drift detector motor adaptativo
   son la respuesta correcta.

3. **Régimen 2025 vs 2026 ≠ régimen real**: probablemente artefacto de muestra,
   no shift estructural. Validar con scraper football-data.co.uk para cuotas
   reales (Opción C).

[REF: docs/papers/v14_regime_changes.md]

---

## Sources externos citados

- Frontiers SAL 2021 — COVID-19 home/away victories: https://www.frontiersin.org/journals/sports-and-active-living/articles/10.3389/fspor.2021.695922/full
- ScienceDirect 2023 — COVID home advantage high/low stakes: https://www.sciencedirect.com/science/article/pii/S1469029223001164
- PMC 2021 — Empty stadiums + home advantage: https://pmc.ncbi.nlm.nih.gov/articles/PMC8670806/
- Davis et al. 2024 — Sports analytics methodology: https://doi.org/10.1007/s10994-024-06585-0
- Thaler 1988 — Anomalies Winner's Curse: https://doi.org/10.1257/jep.2.1.191

[REF: docs/papers/v14_regime_changes.md]
