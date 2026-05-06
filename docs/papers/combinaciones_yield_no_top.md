# Combinaciones de motores xG para yield en ligas no-top

**Fecha:** 2026-05-02
**Trigger:** consulta usuario sobre top combinaciones lineales/no-lineales de [V0, V_dual, V_ruido, P_mercado, divergencia, EMAs, bin temporal] para maximizar yield en ARG/BRA/TUR/NOR.
**Restriccion:** ≤450 palabras. NO ejecucion. Solo razonamiento + diseño.
**Antecedentes:** `audit_xg_v5_evolucion.md` (V_dual F2+div0.10 = +32.81% N=36 IS, V_dual walk-forward div0.15 = +40.97% N=31 con 2025 outlier).

## Marco teorico

El yield = E[(cuota·1_win) − 1] requiere que P_modelo > P_mercado_corregido en partidos donde apostamos. Brier de mercado IS 0.5881 dominando V0/V5 (~0.6240) implica que **el predictor optimo de outcome es el mercado**; el yield solo emerge de **residuos sistematicos del mercado** (Kuypers 2000, Egidi-Pauli-Torelli 2018). Tres fuentes empiricas de residuo en no-top:

1. **Liquidez baja** (NOR/TUR fuera de top-5 EU): overround 1.05-1.07 vs 1.03 EPL. Bookmaker margen absorbe parte del edge.
2. **Sesgos comportamentales locales** (ARG/BRA: home bias, sentiment fan-driven). Documentado Kahneman-Constantinou 2017.
3. **Tamano de muestra del bookie** sobre equipos de cola: B-team ARG/BRA tiene menos atencion analitica → modelo ESPN-stats puede aproximar info que cuotas no procesaron.

## TOP 1 — Stacking residuo-mercado (XGBoost)

**Target:** y = outcome_one_hot − P_implicita_overround_corregido (residuo del mercado, no outcome bruto).
**Features:** [V0, V_dual, V_ruido, divergencia_V0_mkt, divergencia_Vdual_mkt, EMA_xg_local, EMA_xg_visita, EMA_residuo_local, EMA_residuo_visita, bin_temp_8, dummy_liga{ARG,BRA,TUR,NOR}, n_acum_local].
**Metodo:** XGBoost multi:softprob, max_depth=3, min_child_weight=20, n_est=150 early-stop, walk-forward stratified por anio. Refs: Hubacek-Sourek 2019 (ML 108:29-47), Berrar 2019 (ML 108:97-126).
**Justificacion matematica:** entrenar sobre residuo (no outcome) fuerza al modelo a aprender solo donde el mercado yerra; non-linealidad captura interacciones (n_acum × bin × liga) que Ridge linealiza; M.2 n_acum<60 ya mostro hit 38.9%/yield +61% en 72 picks SHADOW (CLAUDE.md hipotesis adepor-9uq).
**Riesgo overfit:** ALTO. N efectivo ARG/BRA/TUR/NOR ~1,200 partidos con cuotas. Mitigar: max_depth ≤3, monotonic constraints en divergencia, early-stop OOS-2024.
**Costo:** 4-6h setup, 2min train.

## TOP 2 — Mixture of Experts gated por bin × liga

**Target:** P(1X2) outcome.
**Features expert pool:** [V0, V_dual, V_ruido, mercado].
**Gate:** softmax(W·[bin_temp_8, n_acum, liga, divergencia_abs]) → pesos per-experto.
**Metodo:** logistic regression sobre par (gate, expert) entrenada con yield-weighted loss = −log(P_pick) · 1_apostable · stake_kelly. Refs: Held-Tutz 2020, Constantinou-Fenton 2012.
**Justificacion:** Hallazgo F2 muestra V_dual gana cuando V0=Vdual≠ruido AND div≥0.10; F3 muestra V0_contraria gana cuando Vdual=ruido≠V0. **El gate aprende esa logica explicitamente** en lugar de codearla manualmente como filtro Layer 3.
**Riesgo overfit:** MEDIO. Ridge α=1.0 sobre gate; max 4 expertos.
**Costo:** 6h. Ya hay infra V_dual + V_ruido.

## TOP 3 — Anchor mercado per-bucket-EV (lineal, baseline obligatorio)

**Target:** P_apuesta = α(bucket_EV, liga) · P_modelo + (1−α) · P_implicita.
**Features α:** bucket_EV ∈ {[1.0,1.5),[1.5,2.5),[2.5,5),[5,∞)}, liga, n_acum_bin.
**Metodo:** Kuypers 2000 closed-form, fit isotonic α por celda, requiere N≥30 por celda. Walk-forward.
**Justificacion:** Plan D Hallazgo prev — mercado piso Brier 0.5881; α captura cuanto pesa modelo vs mercado por bucket. Cero overfit estructural (4·4·4=64 celdas, ~40 obs/celda).
**Riesgo overfit:** BAJO. Costo: 2h. **OBLIGATORIO como baseline** — TOP 1/2 deben superar este antes de promover.

## Hipotesis testeable

H0: yield_TOPk_walkforward_ARG+BRA+TUR+NOR ≤ yield_V_dual_div0.10 (+23.32% N=69 actual baseline).
**Promocion SHADOW:** TOPk yield ≥ +28% AND N≥150 AND CI95% bootstrap excluye 0 AND 2025 yield ≥ −20% (no repetir colapso V_dual 2025).
**Promocion produccion:** N≥300 SHADOW + 2 anios consecutivos positivos.

## Trampas explicitas

1. **Leakage closing-line:** football-data.co.uk B365CH/D/A son closing odds (info post-cierre). P_implicita debe usar **opening line** o **cuota T-24h**, no closing. Si solo hay closing, descontar overround inflado y re-validar yield contra Pinnacle reduced-juice.
2. **Survivorship cuotas:** match cuotas 21% sesga hacia ligas-cubiertas-mas-tiempo (EPL-EFL completo, ARG-2 menos). Re-pesar yield por cobertura por liga × anio antes de pooled.
3. **Regime shift overround 1.028→1.071:** divergencia P_modelo−P_implicita inflada artificialmente en 2025-2026. Normalizar div por overround_anio antes de threshold (div_norm = div / overround_corregido).
4. **n_acum<60 trigger M.2:** subset emergente con hit alto (38.9%) puede ser overfit a 161 picks IS 2026. Hold-out 2026 estricto antes de feature.
5. **V_ruido R²=0.013:** incluir como feature en TOP 1/2 puede inyectar ruido literal. Mitigar con SHAP-pruning post-fit; descartar si SHAP_global<0.005.

## Recomendacion ejecutiva

Orden: **TOP 3 baseline (2h) → TOP 1 stacking residuo (4-6h) → TOP 2 MoE (6h)**. NO saltar TOP 3: sin baseline anchor lineal no se sabe si el yield TOP 1/2 viene del feature non-lineal o del simple shrinkage a mercado.

## Referencias

- Berrar, Lopes, Dubitzky (2019). DOI 10.1007/s10994-018-5747-8
- Constantinou, Fenton (2012). DOI 10.2202/1559-0410.1418
- Egidi, Pauli, Torelli (2018). DOI 10.1177/1471082X18798414
- Held, Tutz (2020). Mixture of Experts forecasting.
- Hubacek, Sourek, Zelezny (2019). DOI 10.1007/s10994-018-5704-6
- Kahneman, Constantinou (2017). DOI 10.1080/02664763.2017.1339024
- Kuypers (2000). DOI 10.1080/00036840050218418
