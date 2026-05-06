# Audit Crítico V0 — Universo Expandido N=4,349

**Sesión:** `2026-05-02_team_filtros_oro`
**Agente:** crítico
**Fecha:** 2026-05-02
**Status:** completed
**Veto:** 1 (NO HAY EDGE ESTADISTICAMENTE SIGNIFICATIVO)

---

## TL;DR

Bajo Bonferroni-adjusted CI95% sobre el universo expandido, **NINGUNA estrategia
1X2 entre V0 puro y 7 variantes filtradas tiene yield positivo significativo**.

V0 puro:
- N=4,349 (8 ligas EUR + ARG/BRA, 2022-2025)
- Yield = **−3.73%** (CI95_Wald [−7.15%, −0.31%])
- CI95_Bonferroni m=7: **[−8.42%, +0.96%]** → cruza cero, no significativo
- Hit = 0.464 vs hit del favorito de mercado = 0.505

V0 puro **NO supera estadísticamente al pick mercado** (Δ yield = −1.01%, z = −0.43,
p = 0.66). Tampoco supera a un random 1/3 (Δ = +1.43%, z = +0.49, p = 0.63).

**El motor V0 no exhibe edge sobre 4,349 partidos walk-forward TRUE-OOS con cuotas
reales fdco.**

## Universo del audit

### Construcción

```sql
predicciones_walkforward p (fuente='walk_forward_sistema_real')
  INNER JOIN stats_partido_espn s  -- norm fix agente 1
  INNER JOIN cuotas_historicas_fdco f  -- cuotas reales 1X2
WHERE f.cuota_1>0 AND f.cuota_x>0 AND f.cuota_2>0
  AND p.outcome IN ('1','X','2')
```

JOIN keys: `SUBSTR(fecha,1,10)` + `LOWER+strip(ht/at)` (wf↔stats) y `fecha_fdco`+`*_fdco_norm` (stats↔fdco).

### Cobertura

| Liga | N |
|---|---|
| Brasil | 1,092 |
| Argentina | 1,080 |
| Italia | 686 |
| Turquía | 538 |
| Francia | 385 |
| España | 282 |
| Inglaterra | 225 |
| Alemania | 61 |
| **Total** | **4,349** |

| Año | N |
|---|---|
| 2022 | 946 |
| 2023 | 1,555 |
| 2024 | 1,472 |
| 2025 | 376 |

### Gap N=8,892 prometido vs N=4,349 efectivo

El agente 1 (`cazador_datos`) reportó N=8,892 sobre stats↔cuotas. Sólo 4,349 de esos
tienen probabilidades V0 walk-forward (`predicciones_walkforward.fuente='walk_forward_sistema_real'`).
La diferencia (4,543) son partidos con cuotas+stats pero **sin probabilidades V0
calculadas TRUE-OOS**. Para esos, no hay forma legítima de auditar V0 sin recomputar
walk-forward (fuera del alcance del audit).

EUR pierde mucho match porque el walk-forward usa nombres genéricos
("Celta", "Sociedad", "Ath Madrid") incompatibles con stats ("Celta Vigo", "Real Sociedad",
"Atlético Madrid"). Sólo aliases simples salvan ~2,000 EUR.

## Resultados por estrategia

| Estrategia | N | Hit | Yield | Brier | Sharpe | MaxDD (u) | CI95_Bonf m=7 |
|---|---|---|---|---|---|---|---|
| V0_puro_argmax | 4,349 | 0.4636 | **−3.73%** | 0.2454 | −2.14 | −167.10 | [−8.42%, +0.96%] ns |
| V0_EV≥1.03 | 1,822 | 0.3282 | −4.10% | 0.2334 | −1.22 | −96.86 | [−13.15%, +4.95%] ns |
| V0_P≥0.55_DIV≥0.05 | **0** | — | — | — | — | — | filtro vacía universo |
| V0_P≥0.60_DIV≥0.05 | **0** | — | — | — | — | — | filtro vacía universo |
| V0_DIV≥0.15 | 542 | 0.2362 | −8.57% | 0.2240 | −1.17 | −82.07 | [−28.27%, +11.13%] ns |
| V0_cuota∈[1.5,2.5) | 2,394 | 0.5013 | −3.77% | 0.2521 | −1.88 | −107.30 | [−9.15%, +1.62%] ns |
| solo_LOCAL | 4,349 | 0.4392 | −5.25% | 0.2393 | −2.85 | −250.40 | **[−10.19%, −0.30%] SIG NEG** |
| pick_MERCADO_favorito | 4,349 | 0.5047 | −2.72% | 0.2547 | −1.77 | −149.23 | [−6.85%, +1.40%] ns |
| RANDOM_1_3 | 4,349 | 0.3339 | −5.16% | 0.2103 | −2.19 | −247.74 | [−11.49%, +1.18%] ns |

**Únicas estrategias con CI95_Bonferroni significativo: solo_LOCAL = SIG NEG.**

### Hallazgo crítico: V0 sub-confidente en bins altos

Calibración V0 (prob_pick vs hit_real):

| Bin | N | avg_prob | hit_real | gap |
|---|---|---|---|---|
| [0.35, 0.40) | 957 | 0.3835 | 0.3971 | −0.0135 |
| [0.40, 0.45) | 854 | 0.4383 | 0.4239 | +0.0144 |
| [0.45, 0.50) | 1,881 | 0.4732 | 0.4636 | +0.0096 |
| [0.50, 0.55) | 632 | 0.5115 | **0.6076** | **−0.0961** |
| [0.55, 0.60) | 24 | 0.5689 | **0.7083** | **−0.1394** |
| [0.60, 1.00) | 1 | 0.6218 | 1.0000 | −0.3782 |

V0 está bien calibrado por debajo de 0.50 pero **sub-confidente arriba**. Los
0.55-0.60 ganan 70% del tiempo (no 57%). Sin embargo, solo hay 24+1 = 25 picks ahí
y el mercado les pone P_implied 0.70-0.93 → divergencia siempre NEGATIVA → filtros
de tipo "div positiva grande" SIEMPRE vacían el universo.

### Por qué los filtros previos parecían funcionar (universo viejo N=2,689)

El universo viejo tenía sesgo de selección hacia partidos con stats completas + cuotas
fdco MATCHED por el script anterior (que mapeaba sólo variantes con paréntesis).
Esto sobre-representaba ARG/BRA partidos de equipos GRANDES (River, Boca,
Flamengo, etc.) que tienden a tener match exitoso de nombres pero también yields
artificialmente altos por la temporada. Al expandir a 8,892 (cuotas) o 4,349 (con probs V0),
el sesgo de selección desaparece y el yield medio cae a la realidad.

**Esto es la firma estadística clásica del data snooping de los filtros previos.**

## Tests de hipótesis

### V0_puro_argmax vs RANDOM_1_3
- Δ yield = +1.43% [paper alpha]
- SE_diff = 2.93%
- z = +0.49, p_two_tailed ≈ 0.63 → **no significativo**

V0 NO supera al random.

### V0_puro_argmax vs pick_MERCADO_favorito
- Δ yield = −1.01%
- SE_diff = 2.32%
- z = −0.43, p_two_tailed ≈ 0.66 → **no significativo**

V0 NO supera al baseline trivial "apostar al favorito" — y de hecho está peor en
yield (−3.73% vs −2.72%) aunque la diferencia no es significativa. **El motor no
extrae información que el mercado no haya ya internalizado en las cuotas.**

## Veredicto

### VETADO: NO HAY EDGE REAL CON N=4,349

Bajo Bonferroni m=7, ninguna estrategia tiene CI95% > 0. Bajo Wald sin ajustar,
sólo V0_puro tiene CI levemente negativo no cruzando cero (−7.15%, −0.31%) y eso
es *peor* que cero, no mejor.

Los filtros que prometían edge en universo viejo (`P≥0.55 + div≥0.05` etc.) no
sólo NO mejoran V0, sino que **dejan el universo vacío** porque la divergencia
positiva del modelo respecto al mercado no existe sistemáticamente.

### Anti-overfitting check

| Criterio | Resultado |
|---|---|
| N de la muestra | 4,349 |
| Filtros testeados | 7 |
| Ratio datos/filtros | 621:1 (alto) |
| Bonferroni adj | aplicado, m=7 |
| Test contra random | no significativo (z=0.49) |
| Test contra mercado | no significativo (z=−0.43, signo contrario) |
| Calibración V0 | bias sub-confidente en bins altos N pequeño |

**El universo expandido CONFIRMA la sospecha del manifiesto: los yields previos
a N=2,689 fueron artefactos del sesgo de selección por mapping incompleto.**

## Recomendaciones (pivot dirección)

### Opción A — Recalibración con isotónica + temperature scaling

V0 está sub-confidente en bins ≥ 0.50. Aplicar Platt/isotónica per-liga sobre
walkforward podría mejorar Brier (0.2454 actual). PERO esto NO produce edge si
el mercado es más calibrado en esos mismos bins (lo está: P_imp llega a 0.70-0.93
y el evento ocurre 0.62-0.93 en muestra). Análisis previo en
`analisis/ab_calibracion_isotonica.py` debe re-correrse sobre N=4,349.

### Opción B — Cambiar mercado (1X2 → cuotas asiáticas / handicap)

El mercado 1X2 europeo tiene overround típico 5-7%. Cuotas asiáticas (handicap,
spread asiático, totals con líneas no-enteras) tienen overround 1-3%. Hipótesis:
en mercados más ajustados, los pequeños mispricings que el mercado no internaliza
se vuelven significativos. **Requiere fuente de cuotas asiáticas históricas
(Pinnacle archive vía OddsPortal scrape) — ~3-5 días de scraping.**

### Opción C — Side strategy con N alto y volume bajo riesgo

Apostar SISTEMÁTICAMENTE sólo a empate (X) cuando cuota_x > 4.0 y prob_modelo_x >
0.30, con stake fijo. La cola de la distribución de empates altos puede tener
mispricing. **Yield esperado modesto (+1-3%) pero con N>500 anuales, el sesgo
de varianza se controla.** Requiere validación retrospectiva específica.

### Opción D — Aceptar limitación y replantear el problema

Sin lineups (titulares antes del partido), lesiones late-breaking, ni clima/cancha,
no hay forma estructural de superar al mercado en 1X2 EUR/LATAM con cuotas de cierre.
Los modelos académicos que sí logran edge (Constantinou-Fenton, Hvattum-Arntzen)
usan probas pre-cierre y cuotas de apertura, NO cuotas de cierre como las de fdco.
**Toda la línea de "filtro de oro" sobre fdco está condenada al failure.**

### Opción E — ML supervisado con features post-stats

Aprovechar las ~67 features de stats_partido_espn (post-partido). Pero esto requiere
pipeline live de stats *pre-partido* (ej. running averages 5-match), que el proyecto
no tiene aún. Plan en `docs/papers/predicciones_por_liga.md` ya identificó esto:
EPV pre-match (Frontiers 2025), VAEP/VDEP defensivo (Premier League), no
generalizar EUR-LATAM. **Inversión 4-6 semanas.**

## Recomendación final del crítico

**VETAR** el plan "filtro de oro per-liga sobre N expandido". Los datos no
soportan edge.

Pivot recomendado: **Opción D + E paralelas**.
- Aceptar que 1X2 fdco NO es batible.
- Iniciar plan ML supervisado con stats pre-partido (Opción E) — investigación 4 sem.
- Mientras tanto, el motor V0 LIVE continúa con su filtro M.1 (5 ligas) + M.2 (n_acum)
  porque esos sí tienen evidencia OOS válida sobre `partidos_backtest` (en LIVE no
  fdco), pero **NO se le pide que mejore más vía filtros nuevos sobre fdco**.

## Reproducibilidad

- Script: `analisis/audit_critico_v0_universo_expandido.py`
- JSON: `analisis/audit_critico_v0_universo_expandido.json`
- DB consultada: `fondo_quant.db` (snapshot 2026-05-02 16:02 UTC)
- Manifesto SHA: `471c1c00b927baad59cd13688bd5db142550a1aadbc45980a2b6d76862c4ab6c`
