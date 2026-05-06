# Patrones identificados — para re-evaluar tras reconstruir motor xG

**Fecha:** 2026-05-03
**Trigger re-evaluación:** después de motor xG v2 con RMSE → 1.0.

Este doc cataloga TODOS los patrones encontrados durante la sesión `2026-05-02_team_filtros_oro` (universo expandido N=8,892 cuotas matched). Algunos son robustos, otros tentativos. Re-validar con motor v2.

---

## I. Patrones de calibración del motor

### I.1 Theta híbrido óptimo es 0.15-0.20, NO 0.70

| θ | RMSE OOS pool 2022-25 | RMSE IS 2026 | Veredicto |
|---|---|---|---|
| 0.10 | 1.1885 | 1.1730 | óptimo histórico |
| **0.15** | **1.1868** | 1.1956 | óptimo OOS pool |
| **0.20** | 1.1880 | **1.1665** | óptimo IS 2026 |
| 0.50 | 1.2479 | 1.2274 | sub-óptimo |
| 0.70 (motor) | 1.2890 | 1.2583 | mal calibrado |
| 1.00 | 1.4143 | 1.3832 | xg_calc puro = peor |

**Theta óptimo por año:**
- 2022: 0.15
- 2023: 0.10
- 2024: 0.15
- 2025: 0.25
- 2026: 0.20

**Estable 0.10-0.25 cross-año.** Re-validar tras motor v2.

### I.2 V_dual underconfident sistemáticamente en favoritos

Gap por banda cuota_pick (cuanto mayor, más underconfident):
- cuota [1.0, 1.5): predice 50%, hits **73%** → gap **+0.235** ★★★
- cuota [1.5, 2.0): predice 44%, hits 57% → gap +0.130
- cuota [2.0, 2.5): predice 41%, hits 40% → gap -0.012 (calibrado)
- cuota [2.5, 3.5): predice 40%, hits 34% → gap -0.053
- cuota ≥ 5.0: predice 39%, hits 19% → gap -0.199

**Mecanismo:** V_dual = Ridge(SOT, residuo) está miscalibrado. Yield viene de underestimación de favoritos. **Frágil — recalibración elimina el edge.**

**Re-evaluar tras motor v2:** ¿la nueva calibración cierra este gap? ¿Hay nuevo gap explotable?

### I.3 Brier MKT < V0 motor

| Modelo | Brier IS | Hit% |
|---|---|---|
| V0 motor (θ=0.70) | 0.6240 | 47.85% |
| V_dual | 0.6218 | 48.18% |
| **MERCADO P_implícita** | **0.5881** | **51.92%** |

Mercado siempre será mejor predictor por info exclusiva (lineups, lesiones, sharp money). **Edge solo en divergencias específicas.**

### I.4 Bug doble híbrido en backtests previos

Códigos previos aplicaban:
```
xg_final = 0.70·xg_calc + 0.30·goles  (motor productivo OK)
xg_p = θ·xg_final + (1-θ)·goles        (BUG: segundo híbrido)
```
Con θ=0.30: efectivamente 21% xg_calc + 79% goles. NO es V0 productivo.

Impacto medido: yield IS pool V0 REAL -6.33% vs V0 BUG -5.03% (Δ -1.3pp). Hallazgos previos cualitativamente OK pero thresholds distintos.

---

## II. Patrones temporales

### II.1 Filtros NEGATIVOS robustos (anti-filtros)

| Excluir | N | Yield | CI95% | Hipótesis |
|---|---|---|---|---|
| `gap_l ≥ 14 días` (post-FIFA) | 906 | -13.65% | [-20.4, -6.7] sig | cansancio internacionales |
| `DOW = Lunes` | 376 | -14.60% | [-25.1, -2.9] sig | partidos atrasados, pizarra desfasada |
| Mes 10 / Mes 11 | 911 | -10/-12% | sig NEG | otoño-EU régimen específico |
| Hora kickoff < 14 | 2167 | -6.99% | [-11.4, -2.2] sig | morning games asiáticos? |

**Combinado anti-Lunes + anti-gap14:** lift +2.8pp baseline (-3.72 → -0.92). Implementable robusto.

### II.2 Bin temporal — heterogeneidad por liga

V_dual gana Brier en 21/24 bins (4+8+12). Edge mayor en mid-temporada (Q2):
- Bin 4 del bin12: Δ -0.0064 IS
- Bin 6 del bin12: Δ -0.0069 IS
- Bin 11 (final): Δ +0.0017 (V0 mejor)

**Inglaterra bin4=4 pick=L cross-año:** N=87, yield +44.0%, score 4.11 (3/3 años pos). Alineado con V5.1.2 ENG Q4 ya en motor.

### II.3 Argentina Q1+Q2 zona de oro

| Bin | N | Yield V0 | Hipótesis |
|---|---|---|---|
| Q1 (inicio Apertura) | 8-16 | +46 a +118% | mercado caliente al inicio, errores grandes |
| Q2 (mid Apertura) | 8-9 | +104 a +130% | momentum acumulado mal-priced |
| Q3 | 10-14 | -76 a -100% | régimen distinto (calor, vacaciones?) |
| Q4 | 7-10 | -10 a -64% | cierre semestre, motivación variable |

**Patrón LATAM exclusivo** — torneo Apertura/Clausura tiene dinámica distinta a EU.

### II.4 Régimen 2025 — selection bias confirmado

Hipótesis previa: mercado más eficiente 2025+. **REFUTADA.**

| Liga | 2023 ov | 2024 ov | 2025 ov |
|---|---|---|---|
| Italia | 1.029 | 1.036 | 1.035 |
| España | 1.029 | 1.036 | 1.036 |
| Francia | 1.029 | 1.035 | 1.037 |

Overround 2025 ≈ 2024. **2025 fail era selection bias** del subset matched al 21% (composición sesgada Italia + Francia).

Post-fix mappings (66.2% match), 2025 sigue siendo problemático en algunas ligas (España -37.80% en filtro óptimo). Investigar individualmente.

---

## III. Patrones de equipos específicos

### III.1 TOP equipos LOCALES (cross-año, sostenibles)

| Liga | Equipo | N | hit% | Yield | Estado |
|---|---|---|---|---|---|
| Argentina | Arsenal Sarandí | 6 | 50% | +129% | tiny |
| **España** | **Atlético Madrid** | 11 | **82%** | **+59%** | candidato whitelist |
| **Inglaterra** | **Aston Villa** | 19 | 58% | **+53%** | candidato whitelist |
| Argentina | Argentinos Juniors | 7 | 57% | +54% | tiny |
| Alemania | Bayer Leverkusen | 6 | 67% | +60% | tiny |
| Brasil | Grêmio | 13 | 54% | +44% | candidato |
| Italia | Como | 9 | 56% | +42% | tiny |
| Inglaterra | Newcastle United | 23 | 57% | +32% | candidato whitelist |
| España | Real Madrid | 6 | 83% | +31% | tiny |

### III.2 BOTTOM equipos locales (NO apostar)

| Liga | Equipo | N | hit% | Yield |
|---|---|---|---|---|
| Alemania | SC Freiburg | 14 | **0%** | **-100%** ✗ |
| Inglaterra | Luton Town | 5 | 0% | -100% |
| España | Cádiz | 5 | 0% | -100% |
| Francia | Montpellier | 23 | 9% | -75% |
| Italia | Udinese | 9 | 11% | -74% |
| España | Almería | 15 | 13% | -64% |

**Re-evaluar tras motor v2:** ¿estos patrones son por el equipo o por que el motor los miscalifica?

### III.3 Walk-forward TRUE-OOS RECHAZÓ whitelist/blacklist

Test agente 10: P4 whitelist top + P5 blacklist bottom → ambas RECHAZADAS por one-shot. Selection retrospectivo sin transferencia OOS.

**Conclusion:** equipos top yield 2022-2024 no garantizan 2025-2026. Re-validar con N grande post-motor v2.

---

## IV. Patrones cross-liga

### IV.1 Heterogeneidad ENORME (refuta filtros universales)

Misma regla "dog aligned" (cuota_v ∈ [4,7] + ola5_v ≥ 2 → V):
- Brasil: +30%
- Italia: **+107%**
- Francia: +14%
- **Argentina: -61%** (hit 8%)

**Reglas universales = ruido garantizado.** Filtros DEBEN ser per-liga.

### IV.2 Stats ganadores vs perdedores — patrón consistente cross-liga

En TODAS las 8 ligas (post EV>=1.03):
- `sot_l_w > sot_l_l` (Δ +0.10 a +0.97)
- `sot_v_w < sot_v_l` (Δ -0.18 a -0.77)
- `res_h_w > res_h_l` (residuo histórico local más positivo)

**3 patrones structurales sólidos.** Confirma intuición: ataque local + defensa local + momentum local = WIN.

### IV.3 Mercado más eficiente en TOP_EU vs NO_TOP

V_anc05 (anchor 0.5 a mercado) en TOP_EU yield +25.76%, en NO_TOP -14.61%.
V_dual en NO_TOP yield +20.96%, en TOP_EU -18.31%.

**Estrategia diferenciada por categoría liga obligatoria.**

---

## V. Patrones del ensemble (multi-motor)

### V.1 Consensus V0+V_ruido POSITIVO

LR coef +0.419 (mayor predictivo de WON). Cuando V0 y V_ruido coinciden, hay edge.

### V.2 Consensus 3 (V0+V_dual+V_ruido) NEGATIVO

LR coef -0.289. Cuando los 3 coinciden, ES MÁS PROBABLE PERDER.

**Hipótesis:** partidos donde todos coinciden = obvios = mercado los pricea bien = sin edge. Edge está en disensos parciales.

### V.3 Subset F3 (V_dual=ruido≠V0)

Cuando descriptores (V_dual + V_ruido) coinciden y V0 difiere, **apostar V0 contraria gana +94% N=12** (sample tiny). 

**Hipótesis:** V0 captura "ruido informativo" (clutch, score effects) que descriptores ortodoxos eliminan. Re-validar con motor v2 sobre N grande.

---

## VI. Patrones derivados de ECE bucketed

### VI.1 V_dual UNDERCONFIDENT en bucket apostable (P≥0.50)

| Modelo | ECE bucket P≥0.50 |
|---|---|
| V0 | 0.0137 (calibrado) |
| **V_dual** | **0.1383** (descalibrado fuerte) |
| MKT | 0.0106 (mejor) |

V_dual predice 53.86%, hits 67.69% → gap +13.83pp.

### VI.2 Yield V_dual NO viene de mejor descripción

Viene de **descalibración beneficiosa**: el modelo es overly conservative en favoritos extremos, generando divergencia con mercado que SÍ acierta.

Re-evaluar tras motor v2: si nuevo motor está bien calibrado, ¿hay otro modelo descalibrado intencional para extraer edge?

---

## VII. Patrones de mercado (cuotas)

### VII.1 Margen bookie creciente

| Año | Overround promedio |
|---|---|
| 2022 | 1.0282 |
| 2023 | 1.0303 |
| 2024 | 1.0378 |
| 2025 | 1.0406 |
| 2026 | 1.0705 |

**Hallazgo previo refutado** (afirmaba mercado más eficiente con tiempo). Solo overround crece, pero distribución outcomes estable.

### VII.2 Cuota_pick en banda [2.0, 4.0] es el sweet spot

España e Inglaterra ambas validadas con cuota ≥ 2.0. Hipótesis:
- Cuota < 2.0: favoritos extremos, mercado los pricea bien.
- Cuota > 4.0: underdogs, mercado underestimates upset frequency menos que modelo.
- [2.0, 4.0]: zona "favorito moderado" donde mercado tiene más varianza.

---

## VIII. Patrones rechazados (no transfieren OOS)

### VIII.1 Argentina cuota ≥ 4.0 (anti-favorito)

IS yield +95% N=53, 3/3 años pos. **PERO LOYO:** OOS -17.37%, 0/3 consistencia. **One-shot histórico.**

### VIII.2 Whitelist/Blacklist equipos

Validados IS pero RECHAZADOS por walk-forward TRUE-OOS. Selection retrospectivo.

### VIII.3 Filtro oro v2 score≥8

Selection bias del subset 21% match. Sobre N=8,892 colapsa a yield -6.66%.

---

## IX. Lista de hipótesis NO probadas (pendientes post-motor v2)

1. **xT / EPV / VAEP per-liga** — requiere event-level (no disponible).
2. **Anchor mercado per-bucket EV** — Kuypers 2000.
3. **Mixture of experts gated por (liga, bin)** — Constantinou-Fenton 2012.
4. **Bayesian hierarchical con market-prior** — Baio-Blangiardo 2010.
5. **XGBoost stacking + market anchor** — Hubacek-Berrar 2019 (winner 2017 Open Challenge RPS 0.205).
6. **Closing line value (CLV)** — opening vs cierre cuota.
7. **Bonferroni-adjusted exhaustive grid search** sobre 8 ligas × 5 bandas cuota × 4 thresholds P × 4 div.
8. **Forma reciente** — ola_3, racha local sin perder en casa, momentum cluster.
9. **Patrones de árbitro** (si data disponible).
10. **Liquidez real cuotas en books accesibles** — yield teórico ≠ realizable.

---

## X. Persistencia & rastreo

- Tabla DB: `agentes_findings` (sesion `2026-05-02_team_filtros_oro`, 16 filas)
- Bead epic: `adepor-mcj`
- Universo expandido: `stats_partido_espn` cols `ht_fdco_norm`, `at_fdco_norm`, `fecha_fdco`
- Match-rate global: 8,892/13,430 (66.2%)
- Documentos relacionados:
  - `docs/papers/audit_xg_v5_evolucion.md` (master)
  - `docs/papers/filtros_validados_para_evaluar_post_motor_v2.md` (filtros)
  - `docs/papers/audit_v0_crudo_n_expandido.md` (veto)
  - `docs/papers/walk_forward_true_oos_5_propuestas.md` (vetos)
  - `docs/papers/nichos_sostenibles.md` (sin Bonferroni)
  - `docs/papers/angulos_creativos_resultados.md`
  - `docs/papers/expansion_match_cuotas.md`
  - `docs/papers/metodos_alternativos_xg.md` (TOP 3 técnicas modernas)
- Scripts clave:
  - `analisis/theta_y_filtros_IS2026.py` — validación final
  - `analisis/cv_filtros_y_validar_theta.py` — schema A+B
  - `analisis/v0_real_repaso_IS_filtro_suave.py` — fix bug doble híbrido
