# Filtros de Oro Estratificados por Liga (V_oro_liga)

**Fecha:** 2026-05-02
**Estado:** PROPUESTA — diseño hipotético, no ejecutado.
**Universo objetivo:** N=7,990 partidos con cuotas (post fix mappings ESPN→fdco).
**Match-rate por liga:** ALE/ESP/FRA/ENG/ITA 100%, TUR 97%, BRA 71%, ARG 55%.

---

## Antecedentes (filtro_de_oro_findings_finales.md)

- Filtro de oro v2 score>=8: yield +12.96% N=84 (universo viejo N=2,689).
- Sweet spot V0: P>=0.60 + div>=0.05 → yield +12.15% N=99, Sharpe 1.24, MaxDD 4.81%.
- Paradoja: consensus_3 NEGATIVO (-0.29 LR coef); consensus_v0_vr POSITIVO (+0.42).
- V_dual UNDERCONFIDENT en favoritos cuota<2.0 (gap +0.23).
- Brier MKT 0.5881 < V0 0.6240 → mercado mejor predictor agregado.

Hipótesis central: con N=7,990 estratificable por liga, el filtro óptimo es heterogéneo
(LATAM ineficiente vs EU eficiente). Aplicar un filtro global degrada Sharpe en ligas
donde la microestructura de mercado es distinta.

---

## 1. Filtros HIPOTÉTICOS para LIGAS NO_TOP

### Argentina (mercado ineficiente, alta varianza, match-rate 55%)

Sample selection bias: cuotas fdco solo cubren partidos "grandes". Filtros deben ser
robustos a este sesgo (no extrapolar a partidos sin cuota).

- **A1 — Anti-favorito local extremo:**
  `P_V0_top >= 0.55 AND div_v0_mkt >= 0.08 AND cuota_pick >= 1.85`
  Razonamiento: Hallazgo `adepor-09s` (régimen 2026) + `adepor-9uq` (n_acum>=60 yield
  +61.6%). Mercado paga sobre-redondeo en favoritos cortos; el modelo capta favoritos
  genuinos cuando cuota >= 1.85 (no aplastados por el book).

- **A2 — Visitante con momentum:**
  `P_V0_visita >= 0.42 AND ema_xg_visita / ema_xg_concedido_local >= 1.15 AND ola_visita_3 >= 1.0 pts/match`
  Razonamiento: home advantage decreciente en LATAM (ACM 2025); modelo V0 subestima
  visitantes con forma reciente porque EMA larga lo amortigua.

- **A3 — Empate calibrado:**
  `P_V0_X >= 0.32 AND div_X_mkt >= 0.06 AND consensus_v0_vr_X = True`
  V14 v2 SHADOW (sesion 2026-04-29) hit 69.4% subset apostable sugiere X infravalorado
  en LATAM. Manifiesto bloquea X universal pero §N Layer 3 lo permite condicional.

### Brasil (mercado intermedio, match-rate 71%)

- **B1:** Igual A1, cuota_pick >= 2.10 (mercado mas eficiente que ARG).
- **B2:** Floor `n_acum_local >= 40` (filtra primeras jornadas Serie A; ruido EMA).
- **B3:** Excluir copa nacional cuando `id_competicion != liga` (bias_per_edicion -15%).

### Turquía (V12 ya activo, match-rate 97%)

- **T1:** Mantener V12 argmax + agregar floor `cuota_pick >= 1.70` (drift bin9 -32%).
- **T2:** Extender §N Layer 3 X-rescue a 0.35 AND posicion_local NOT IN top3.
- **T3:** Anti-fixture saturado: skip si `gap_dias_no_liga <= 3`.

---

## 2. Filtros para LIGAS TOP_EU (ENG/ESP/ITA/FRA/ALE)

Mercado EU eficiente. NO competir en favoritos cortos. Buscar nichos donde V0 + V_dual
coinciden contra mercado en un rango acotado de divergencia.

- **EU1 — Doble conviccion + divergencia leve:**
  `P_V0_top >= 0.50 AND P_Vdual_top >= 0.48 AND argmax_V0 = argmax_Vdual AND div_v0_mkt en [0.05, 0.15]`
  Aprovecha consensus_v0_vr POSITIVO (+0.42 LR). Cap superior 0.15 evita trampa:
  divergencia >0.15 en EU implica info publica (lesion, alineacion) que el modelo no ve.

- **EU2 — Anchor a market en favoritos cortos:**
  Si `cuota_pick < 2.00` → exigir `P_V0_top >= MKT_implicita + 0.03` (no menos).
  Corrige V_dual UNDERCONFIDENT gap +0.23 detectado en findings finales.

- **EU3 — Italia low-scoring + Layer 3 X:**
  Italia: `P_X >= 0.30 AND posicion_local NOT IN top4` → activar X-rescue.
  Justificacion: Frontiers 2025 tactical/low-scoring + V14 v3 bin3 -26%.

---

## 3. Variables NO Probadas (priorizadas por expected lift)

| # | Variable | Definicion | Hipotesis | Liga objetivo | Prioridad |
|---|---|---|---|---|---|
| 1 | `kelly_proxy` | `P_top * (cuota_pick - 1)` | Filtro nativo de EV; rama Kelly criterion | Universal | ALTA |
| 2 | `delta_n_acum` | `n_acum_l - n_acum_v` | Asimetria de madurez EMA → ruido direccional | NO_TOP | ALTA |
| 3 | `ola_3` | `pts(ultimos 3) / 9` | Forma reciente vs EMA larga | NO_TOP | ALTA |
| 4 | `ratio_xg_mismatch` | `ema_xg_l / ema_xg_concedido_v` | Mismatch ofensivo puro | Todas | ALTA |
| 5 | `std_outcomes_l_10` | Std outcomes ult 10 | Volatilidad alta → X mas probable | ITA, ARG | MEDIA |
| 6 | `pass_pct_diff` | `pass_pct_l_ema - pass_pct_v_ema` | Control de juego != xG | EU | MEDIA |
| 7 | `h2h_balance_5` | Balance ult 5 enfrentamientos | Match-up dominance | Copas, derbis | MEDIA |
| 8 | `cuota_imp_X_relativa` | `cuota_imp_X / max(cuota_imp_L, cuota_imp_V)` | Mercado dudando → X infravalorado | LATAM | MEDIA |
| 9 | `vol_ema` | std movil sobre xG ult 10 | Equipos volatiles → cuota mal precificada | NO_TOP | BAJA |
| 10 | `pos_local - pos_visita` | Diferencia posicion tabla | Probado parcialmente; revisar interaccion con n_acum | Todas | BAJA |

---

## 4. Estrategia de Validacion Anti-Overfitting

Riesgo: con N=200-1000 por liga y K filtros candidatos, el FWER (family-wise error rate)
explota. Protocolo obligatorio:

### 4.1 Walk-forward temporal por liga
- Train: <=2024.
- Valid: 2025.
- Holdout congelado: 2026 (no se mira hasta freeze final).
- NO random split (leakage temporal).

### 4.2 Correccion por multiple testing
- Si se prueban K=12 filtros, alpha efectivo Bonferroni = 0.05/12 = 0.00417.
- Reportar IC95 ajustado por Bonferroni. Filtro pasa solo si p-ajustado < 0.05.
- Alternativa menos conservadora: Benjamini-Hochberg FDR <= 0.10.

### 4.3 N minimo por liga
- Floor universal: N=80 partidos apostables.
- ARG/BRA con match-rate parcial: N=120 (compensar sample selection bias).
- N<80 → marcar EXPLORATORIO, no promover.

### 4.4 Bootstrap estabilidad
- 1,000 resamples del yield por liga.
- Reportar percentiles 5/50/95.
- Filtro estable si percentil 5 > 0% (yield positivo en >95% de remuestras).

### 4.5 SHADOW obligatorio pre-produccion
- Logging a `picks_shadow_filtros_oro_liga` con flag `aplicado_produccion=0`.
- N>=200 picks SHADOW antes de PROPOSAL MANIFESTO CHANGE.
- Trigger de promocion: yield IC95% inf > 0 AND Brier no peor que V0 baseline.

### 4.6 Penalizacion complejidad
- AIC/BIC sobre LR de seleccion de features.
- Si AIC del filtro complejo no mejora 2+ unidades vs baseline, rechazar.

### 4.7 Hold-out temporal estricto
- Ultimas 8 semanas (~Marzo-Mayo 2026) congeladas hasta freeze final.
- Tocar holdout antes del freeze invalida el experimento (registrar en decisions log).

### 4.8 Auditoria del Critico
- Toda PROPOSAL filtro_oro_liga debe incluir:
  - N por liga, hit%, yield%, Sharpe, MaxDD.
  - IC95 ajustado por Bonferroni o BH.
  - Bootstrap percentiles.
  - Snapshot DB pre/post.
  - Comparacion vs V0 raw + filtro_oro v2 actual.

---

## 5. Roadmap Sugerido (no comprometido)

1. **Fase 0 — Auditoria descriptiva por liga (1 sesion):** distribucion P_V0_top, div,
   cuota, hit, yield baseline por liga. Output: tabla N=15 ligas.
2. **Fase 1 — Generar features no probadas (1 sesion):** kelly_proxy, delta_n_acum,
   ola_3, ratio_xg_mismatch en `partidos_backtest`.
3. **Fase 2 — Grid search por liga (2 sesiones):** filtros A1-A3, B1-B3, T1-T3, EU1-EU3.
   Walk-forward train<=2024 / valid 2025.
4. **Fase 3 — SHADOW logging (LIVE):** infraestructura `picks_shadow_filtros_oro_liga`.
5. **Fase 4 — N>=200 + PROPOSAL:** beads `[PROPOSAL: MANIFESTO CHANGE]` por liga.

---

## 6. Riesgos Identificados

- **Sample selection bias ARG/BRA:** match-rate 55-71% → filtros calibrados sobre subset
  no extrapolables al universo total. Documentar en cada PROPOSAL.
- **Regime shift:** V14 v3 bins temporales detectan shifts IS 2026 hasta -32%. Filtros
  calibrados <=2024 pueden no transferir (ya pasado con M.3).
- **Multiple testing:** sin Bonferroni/BH la probabilidad de filtro espureo es alta.
- **Overlap con Hallazgo G y Fix #5:** verificar que filtros no canibalicen calibraciones
  existentes (re-correr A/B "puro" vs "sistema" como exige protocolo SHADOW).
- **Liquidez de cuotas:** filtro que selecciona cuota_pick >= 1.85 en ARG puede no tener
  liquidez real en books accesibles → yield teorico no realizable.

---

## 7. Referencias Cruzadas

- `docs/papers/filtro_de_oro_findings_finales.md` — baseline N=2,689.
- `docs/findings_n_acum_drift.md` — M.2 calibracion.
- `docs/papers/v14_v3_analisis_exhaustivo_propuestas.md` — bins temporales.
- `docs/regime_profiles_2022_2023_2024.md` — caracterizacion de regimenes.
- `Reglas_IA.txt` §L (Layer 2) §M (filtro_picks_v51) §N (Layer 3) — interaccion con
  filtros existentes.
- Bead `adepor-9uq` — n_acum>=60 yield SHADOW.
- Bead `adepor-617` — H4 V0+X-rescue PROPOSAL.

---

**Autor:** optimizador_modelo
**Revisar antes de implementar:** lead-adepor + critico
**N minimo PROPOSAL:** 200 picks SHADOW por liga
