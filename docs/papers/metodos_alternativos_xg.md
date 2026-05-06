# Metodos alternativos xG - cerrar gap modelo vs mercado en Brier 1X2

**Fecha:** 2026-05-02
**Trigger:** hallazgo audit_xg_v5_evolucion.md - mercado Brier IS 0.5881 vs V0 0.6240, V5 0.6218, V_dual 0.6239. Gap ~5% descriptivo a recuperar SIN romper yield (V0 +13.15%, V_dual +40.97% div>=0.15).
**Restriccion:** ESPN summary post-match agregado (no event-level), N=2,689 partidos con cuotas, stack Python sklearn/numpy/xgboost.

## TOP 1 - XGBoost stacking + market anchor (TECNICA PRINCIPAL)

**Refs:** Hubacek-Sourek-Zelezny (2019, ML 108:29-47, DOI 10.1007/s10994-018-5704-6); Berrar-Lopes-Dubitzky (2019, ML 108:97-126, DOI 10.1007/s10994-018-5747-8) - XGBoost+rating features GANO 2017 Open Challenge: RPS 0.2054, acc 0.5194, superando Poisson/Dixon-Coles.

**Tecnica:** XGBoost multi:softprob sobre [SOT/shots/corners/pos/pass_pct/saves/blocks EMA, delta_xg_v5, delta_elo, P_implicita_mercado_overround_corregido]. Stacking out-of-fold: P_final = anchor*P_xgb + (1-anchor)*P_mercado, anchor calibrado por bucket EV (Kuypers 2000).

**Por que cierra el gap:** mercado as-feature garantiza piso Brier ~ 0.5881; non-linealidad captura interacciones (saves x SOT) que NNLS Ridge V5 linealiza; anchor activa cuando modelo no diverge significativamente, manteniendo yield V0 cuando si.

**Feasibility:** ALTA. pip install xgboost. 4-6h setup. max_depth=4, min_child_weight=10, n_estimators=200 early-stop. Walk-forward stratified por anio.

**Test:** Brier OOS y yield M.1+EV>=1.03+div_thr vs V0/V_dual. Promover SHADOW si Brier OOS<=0.6100 Y yield_div0.10>=+5%.

**Riesgo:** overfit con N=2,689; mitigable con regularizacion + early stopping.

## TOP 2 - Reemplazo metrica: Ignorance Score + ECE bucketed (AUDITORIA RAPIDA)

**Refs:** Wheatcroft (2021, JQAS 17(4):273-287, DOI 10.1515/jqas-2019-0089, arXiv:1908.08980) - Ignorance Score (-log2 P_real) supera Brier+RPS para identificar predictor optimo con menor N. Gneiting-Raftery (2007, JASA 102:359-378) - calibration+sharpness, no Brier global, predice yield.

**Tecnica:** auditar V0/V5/V_dual/mercado computando IS + ECE bucketed [0.30-0.40, ..., 0.70+] + sharpness en bucket P>=0.55 (zona apostable).

**Por que cierra el gap:** HIPOTESIS - el gap Brier 0.0022 V0-V5 puede ser ruido en zona NO apostable (P~0.33). Mercado domina Brier global, pero V0 podria GANAR ECE/sharpness en bucket P>=0.55 (eso explicaria el yield positivo). Cambio de metrica reordena el ranking. Si ganamos ECE en bucket apostable, gap es ilusorio.

**Feasibility:** MUY ALTA. 100% sklearn/numpy. ~2h. Cero modelo nuevo.

**Test:** computar IS+ECE+sharpness V0/V5/V_dual/mercado N=2,689. Si V0 gana ECE en bucket P>=0.55 vs mercado, mismatch Brier-yield queda explicado y gap real es < 0.005. Si pierde, confirma necesidad TOP 1.

**Riesgo:** ninguno - solo recalcula sobre data existente.

## TOP 3 - Bayesian hierarchical con market-prior (RECURSO PESADO)

**Refs:** Baio-Blangiardo (2010, JAS 37(2):253-264, DOI 10.1080/02664760802684177) - jerarquico att/def + mixture-prior. Egidi-Pauli-Torelli (2018, Stat Modelling 18:436-459, DOI 10.1177/1471082X18798414) - odds como prior empirico Bayesian, directamente atacable al gap. Macri Demartino (2025, arXiv:2508.05891) - state-space dinamico time-decay.

**Tecnica:** Lambda_h = exp(home + att_h - def_v + beta_xg*delta_xg + beta_market*P_implicita_h), priors att_i ~ N(mu_att, tau_att) jerarquicos, mixture-prior shrink hacia mercado cuando N_team < 30. PyMC v5 + numpyro.

**Por que cerraria el gap:** Bayesian shrinkage = solucion clasica al overconfidence (V12 sub-confident, documentado). Posterior ancla mercado cuando inferencia debil, separa cuando fuerte (N_team > 80). Mixture-prior Egidi resuelve gap sin colapsar yield.

**Feasibility:** MEDIA. PyMC funciona en stack. 12-16h setup, MCMC 30-60min batch (offline weekly). Coefs aplicados runtime.

**Test:** Brier+yield walk-forward 2023-2026. Validar shrinkage funciona empiricamente en N_team < 30 vs > 80.

**Riesgo:** prior empirico puede colapsar posterior hacia mercado (mismo problema V5: Brier+, yield-).

## Recomendacion ejecutiva

**Orden:** TOP 2 primero (2h, riesgo cero) - si confirma que gap se concentra en bucket P>=0.55, ejecutar TOP 1. TOP 3 ultimo recurso si TOP 1 no cierra.

**NO recomendar:** xT/EPV/VAEP raw (no event-level data; Frontiers 2025 mostro xG post-match RPS 0.148 supera EPV post-match 0.191 incluso CON tracking). Neural nets (N=2,689 insuficiente, overfit). Sequential BPL/Elo probabilistico (duplica senal de equipo_nivel_elo existente).

## Limitaciones

- No hubo acceso a `picks_shadow_arquitecturas` para confirmar que V12 ya fue probado contra benchmarks tipo Berrar.
- Wheatcroft IS requiere clipping P_min=0.001 (penaliza infinito P=0 en outcome real).
- Stacking depende de calibracion overround - usar Shin/Strumbelj (2014, IJF) no division simple.

## Referencias

- Baio, Blangiardo (2010). DOI 10.1080/02664760802684177
- Berrar, Lopes, Dubitzky (2019). DOI 10.1007/s10994-018-5747-8
- Egidi, Pauli, Torelli (2018). DOI 10.1177/1471082X18798414
- Gneiting, Raftery (2007). DOI 10.1198/016214506000001437
- Hubacek, Sourek, Zelezny (2019). DOI 10.1007/s10994-018-5704-6
- Kuypers (2000). DOI 10.1080/00036840050218418
- Macri Demartino et al. (2025). arXiv:2508.05891
- Wheatcroft (2021). DOI 10.1515/jqas-2019-0089. arXiv:1908.08980
