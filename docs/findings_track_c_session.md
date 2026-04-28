# Findings — Sesión Track C (mejorar predicción) + V5.2 deployment

> Fecha: 2026-04-28 (sesión completa)
> Output: 17 scripts/audits + 3 docs nuevos + V5.2 motor deployment
> Bead meta: `adepor-4ic`

## Resumen ejecutivo

Sesión multi-track con dos vectores principales:

1. **V5.2 deployment** (Layer 3 H4 X-rescue per-liga): infraestructura aplicada al motor. JSON config vacío default — comportamiento V5.1.2 preservado hasta activación SQL explícita.

2. **Track C exploración mejora predicción**: 3 sub-líneas evaluadas en 1 sesión, **TODAS cerradas SIN promotion**. Negative findings son value real — confirman que el motor V0 + V12 Layer 2 + V5.2 Layer 3 está cerca del óptimo.

## Sub-líneas Track C exploradas

### Sub-1 Cold-start n_acum≤10 — CERRADO SIN ACCIÓN

**Hipótesis:** EMAs inmaduras al arranque temp generan picks con yield negativo.

**Resultado:** Hipótesis REFUTADA. Cold-start tiene yield positivo o tibio.

**Pero:** drilling cross-temp + cross-equipo reveló que **el yield positivo agregado +74.4% Argentina 0-4 era artefacto de:**
- Concentración en 5 equipos top (29% del stake genera 54% del profit)
- Un equipo recién promovido (Deportivo Riestra 2024) con +299% yield N=5
- Variación cada temp — cada año cold-starters distintos (Riestra 2024, Patronato/Arsenal/Instituto 2022)

**Implicación:** Aplicar Kelly boost a cold-start universal sería **curve-fitting peligroso** sobre selection bias retrospectivo no replicable.

**Hallazgo accidental:** bucket 31-59 OOS yield +2.7% AGREGADO enmascara heterogeneidad — 31-40 (−0.2%) + 41-50 (−4.0%) + 51-59 (+13.7%). M.2 actual sigue OK.

**Hallazgo accidental 2 (importante):** bucket ≥60 in-sample 2026 yield = +43.1% borderline. Brasil ≥60 in-sample +120% SIG sobre N=22. **El filtro M.2 actual (n_acum<60) puede estar drenando dinero en 2026.** → Bead `adepor-9uq` abierto.

**Output:** `analisis/audit_cold_start_n_acum.{py,json}` + `analisis/audit_argentina_cold_por_equipo.{py,json}`

---

### Sub-3 Calibración isotónica post-hoc — CERRADO SIN ACCIÓN

**Hipótesis:** V0 puede estar mal calibrado en algún bucket. Calibración isotónica per-liga corrige el mapeo prob_predicha → frecuencia_real.

**Metodología:** train fit sobre OOS 2022+2023, test sobre 2024 + in-sample 2026. `sklearn.IsotonicRegression` per outcome.

**Resultado:** **DESTRUYE yield universalmente.**

| Subset | ΔBrier (cal mejor) | ΔYield |
|---|---|---|
| Aggregate 2024 | −0.0069 ✓ | **−3.1pp** |
| Argentina 2024 | +0.002 | **−5.8pp** |
| Brasil 2024 | +0.003 | −5.0pp |
| Inglaterra 2024 | −0.001 | **−9.2pp** |
| Turquía 2024 | −0.026 ✓ | **−7.5pp** |
| Italia 2024 | −0.012 ✓ | −7.2pp |
| **España 2024** | +0.001 | **+12.6pp** ← única mejora |
| Alemania 2024 | +0.024 | **−14.8pp** |
| **In-sample Argentina 2026** | −0.012 | **−29.3pp** |
| In-sample Brasil 2026 | +0.019 | −27.5pp |
| In-sample Inglaterra 2026 | +0.045 | −28.7pp |
| In-sample Noruega 2026 | +0.032 | −22.9pp |
| In-sample Turquía 2026 | +0.035 | −19.3pp |

**Patrón cross-temp robustez:** 3/4 cross-temp empeoran. Solo `fit 2023 → eval 2024` mejora marginal +1.0pp.

**Lectura mecánica:** la **paradoja Brier↔Yield** se confirma brutalmente. Las probs V0 están desalineadas con la realidad observada — pero esa misalineación ES la fuente de value vs Pinnacle (que sí está bien calibrado). Calibrar el motor lo hace **más parecido al bookie** → desaparece el edge.

**Caveat:** España es la única liga donde calibración isotónica mejora yield. España no está en universo V5.1 LIVE (M.1 la filtra). Si en futuro entra, considerar calibración España-específica.

**Output:** `analisis/audit_isotonic_calibration_drill.{py,json}`

---

### Sub-4 Skellam V7 promoción — CERRADO SIN PROMOTION

**Hipótesis:** Skellam (P(diferencia goles)=0) modela empates mejor que Dixon-Coles tau correction.

**Metodología:**
- Audit preliminar SHADOW V7 (60 picks liquidados): V0 supera V7 (5/5 disagreements)
- Audit drill multidim sobre N=8,157 OOS 2022-2024 (V0 vs V7 con mismo xG, sin tau correction V7 vs con tau V0)

**Resultado:** **V7 NO supera V0 en ningún subset.**

| Dimensión | Hallazgo |
|---|---|
| Aggregate | V0=V7 hit 65.0%. Brier V0 (0.4697) MEJOR que V7 (0.4711). |
| Por temp 2022/2023/2024 | Deltas <0.5pp consistente. |
| Por liga (TOP-5 + EUR top + Brasil) | Deltas <1pp en todas. |
| Per equipo top | Max delta V7 mejor +2.94pp (Rosario Central N=34) — sin sig. |
| Per equipo top V0 mejor | Boca −6.25pp (N=32), Instituto −5pp (N=20). |

**Patrón débil observado:** V7 marginalmente mejor para MID/BOT con xG bajo (Rosario Central, Valladolid, Sociedad), V7 peor para TOP-3 con xG alto (Boca, Man United, Roma). Pero deltas <3pp con N<50 → ruido.

**Output:** `analisis/audit_v7_shadow_preliminar.{py,json}` + `analisis/audit_v7_skellam_drill.{py,json}`

---

## V5.2 Layer 3 H4 X-rescue (deployment)

### Audit Opción D (walk-forward por temp + multidim)

Sobre `adepor-edk` Layer 3 (H4 X-rescue threshold=0.35), audit ampliado:

**Walk-forward por temp (N grande):**

| Ventana | N | V0 yield | H4 yield | Δ |
|---|---|---|---|---|
| test_2022 | 1544 | +3.1% | +3.2% | +0.0pp |
| test_2023 | 2264 | −3.4% | −2.9% | +0.5pp |
| test_2024 | 2348 | −0.3% | +1.0% | +1.2pp |
| in_sample_2026 | 129 | +9.7% | +16.0% | +6.3pp |

4/4 ventanas con Δ ≥ 0. Threshold 0.35 fijo aguanta cross-temp.

**Caracterización población X-rescue (191 picks):**
- 60% Argentina, 14% Inglaterra, 12% Italia, 10% España, 4% Alemania, 4% Brasil
- Italia 2024: +13.51 estrella
- AMBOS ≤14d cansados: −1.407 SIG NEG (N=11) — filtro inverso requerido

**Drilling multidim (cruzando con findings):**

| Filtro | N | Hit% | Δ H4-V0 | CI95 | Sig |
|---|---|---|---|---|---|
| TODOS | 191 | 31.4% | +0.250 | [−0.07, +0.58] | NO |
| **NOT (local=TOP3) AND NOT (ambos≤14d)** | **160** | **35.0%** | **+0.426** | **[+0.07, +0.78]** | **★ POS SIG** |

**Findings críticos cross-equipo:**
- Hipótesis original "cansancio mid-week → empate" REFUTADA
- Pero filtro INVERSO útil: NOT ambos cansados ≤14d (sig pos)
- Pos local TOP3 destruye yield (−0.240) — excluir
- Pos local BOT da +1.021 (mejor bucket)

**Implementación V5.2:**

```python
# motor_calculadora.py post Layer 2 V12
if liga in h4_x_rescue_threshold and not _layer2_aplicado:
    if argmax_v12 == 'X' and P_v12(X) > thresh[liga]:
        if not local_es_top3 and not ambos_cansados:
            (p1, px, p2) = (p1_v12, px_v12, p2_v12)  # override
```

Helpers nuevos: `_get_pos_local_forward`, `_get_gap_dias_no_liga`.

Tabla nueva: `partidos_no_liga` (8,742 OOS via API-Football + 192 in-sample 2026 Wikipedia parcial).

View nueva: `v_partidos_unificado` (UNION liga + no-liga).

**Manifesto V5.1.2 → V5.2.** SHA: `471c1c00...4ab6c` locked.

**Activación recomendada (decisión usuario):**

```sql
UPDATE config_motor_valores
SET valor_texto = '{"Argentina": 0.35, "Italia": 0.35, "Inglaterra": 0.35, "Alemania": 0.35}'
WHERE clave = 'h4_x_rescue_threshold' AND scope = 'global';
```

**Output completo:** `docs/findings_layer3_walkforward.md`

---

## Otros findings de la sesión

### `adepor-a1v` — V13 captura calidad estructural (cerrado)

Audit `proxy_pos_backward_correlacion.py`: r promedio cross-(liga, temp) = **−0.622** (umbral cierre r<−0.3). V13 SHADOW ya captura señal estructural sin necesidad de feature explícito.

Caveat: Argentina V13 F1_off NNLS proxy débil (r=−0.019 vs −0.267 con ema_sots crudo) — intercept domina. Si V13 promueve a argmax en Argentina vía `adepor-6g5`, considerar primero F2_pos en vez de F1_off.

**Output:** `docs/findings_proxy_pos_backward.md`

---

### Audit hit rate copas (preliminar)

Sin cuotas históricas (API Pro requerido), solo hit rate puro:

| Universo | N | Hit Rate |
|---|---|---|
| Liga (referencia) | 4,564 | 50.02% |
| **Copa del Rey** | 39 | **61.5%** |
| **FA Cup** | 47 | 57.4% |
| **Coppa Italia** | 58 | 56.9% |
| EFL Cup | 49 | 51.0% |
| Champions League | 161 | 47.2% |
| Sudamericana | 65 | 40.0% |
| Libertadores | 90 | 35.6% |
| Copa do Brasil | 72 | 36.1% |
| Copa Argentina | 27 | 33.3% |
| **Europa League** | **59** | **28.8% (PEOR)** |

**Copas EUR domésticas SUPERAN liga.** Copas internacionales LATAM bajo 40%. Europa League below random.

Bloqueado yield validation por API-Football free tier no soporta `/odds`. Beads `adepor-4tb` y `adepor-8je` pending Pro upgrade.

**Output:** `analisis/audit_partidos_copa_hit_rate.{py,json}` + `analisis/audit_copas_internacionales_drill.{py,json}`

---

## Beads creados/cerrados en sesión

### Cerrados (5)

- `adepor-edk` — PROPOSAL madre Layer 1+2+3 (cumplió rol)
- `adepor-tyb` — Layer 3 H4 X-rescue per-liga (aplicado V5.2)
- `adepor-a1v` — V13 captura calidad estructural
- `adepor-0bb` — DECISION-LOG Fase 3/4 canceladas (archivo)
- `adepor-qea` — DECISION-LOG ENET descartado V13 (archivo)
- `adepor-5y0.1` — Schema partidos_no_liga + view + tests

### Abiertos nuevos (12)

**P2:**
- `adepor-hxd` — PROPOSAL M.3 condicional por liga
- `adepor-9hh` — INFRA Extender posiciones 3-formatos otras ligas
- `adepor-tyb` (closed) — sucesor `adepor-edk`
- `adepor-4tb` — EPIC Yield copas EUR domésticas (BLOCKED API)
- `adepor-8je` — Champions pred=1 (BLOCKED API)
- `adepor-4ic` — META mejorar predicción (no se cierra)
- `adepor-5y0` epic + 7 sub-beads (sub-1 cerrado)
- `adepor-9uq` — INVESTIGATION M.2 vs régimen 2026

**P3:**
- `adepor-6g5` — TRIGGER V13 promoción argmax (N≥200)

---

## Lecciones de la sesión

1. **Negative findings son value.** Track C cerró 3 sub-líneas que parecían prometedoras. Ahorra esfuerzo futuro.

2. **Drilling multidim es esencial.** El "Argentina cold-start +74.4% SIG" se desinfló al ver concentración por equipo + temp. El "5-10 SIG POS" agregado era artefacto 2024. Sin desagregación se aplicaba boost equivocado.

3. **Paradoja Brier↔Yield brutal.** Calibración isotónica mejora Brier pero destruye yield (−19 a −29pp in-sample). Confirmación canónica: yield es el único objetivo de optimización válido en betting.

4. **Filtros inversos > filtros directos.** Layer 3 H4 X-rescue funciona aplicando filtro INVERSO ("NOT ambos cansados"), no directo ("aplicar si cansado"). La intuición se invirtió.

5. **Régimen 2026 difiere del histórico.** Bucket ≥60 yield +43% in-sample vs −13.7% OOS. M.2 actual puede estar mal calibrado para 2026 — pendiente N≥200 para confirmar.

6. **API-Football free tier es limitante.** No incluye `/odds` ni seasons post-2024. Para validar yield copas o aplicar Champions pred=1, requiere upgrade Pro.
