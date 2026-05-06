# Audit critico — Filtro de oro v2 score>=8

**Fecha:** 2026-05-02
**Auditor:** Critico (poder de veto)
**Propuesta auditada:** promover Filtro_oro_v2 score>=8 a produccion (yield +12.96% N=84 IS pooled walk-forward)
**Artefactos revisados:** `docs/papers/filtro_de_oro_findings_finales.md`, `docs/papers/audit_xg_v5_evolucion.md`, `analisis/filtro_de_oro_v2_logistic.json`, `analisis/filtro_de_oro_v3.json`, `analisis/filtro_de_oro_v2_logistic.py`, `analisis/filtro_de_oro_v3_universo_expandido.py`

---

## VEREDICTO: VETADO

**Razon en una oracion:** el universo expandido (N=7990 post fix match) DESPLOMA score>=8 de +12.96% (N=84) a **-6.66% (N=149)**. La edge que se queria promover era artefacto de selection bias del subset matched-cuotas viejo, no senal real.

---

## VERIFICACION INDEPENDIENTE DE CLAIMS

| Claim reportado | Verificacion DB | Status |
|---|---|---|
| Score>=8 yield +12.96% N=84 (universo viejo 2689) | OK — confirmado en `filtro_de_oro_v2_logistic.json` score_grid_v2["8"]=[84, 58.33, 12.96, 10.89, 1.92] | VERIFICADO |
| Bootstrap CI95% [-9.5%, +28.6%], P(>0)=83% | El IS pooled walk-forward (LR thr=0.55) reporta CI95 [-10.79%, +53.82%] P(>0)=90.3%. El CI95 propuesto del filtro hard-coded score>=8 NO esta calculado en el JSON (script v2 NO bootstraps el filtro de reglas). El usuario reporta CI95% [-9.5%, +28.6%] pero NO encuentro ese numero en los artefactos. **Reclamo NO VERIFICADO.** | NO RASTREABLE |
| Universo expandido N=7990 cuotas | OK — `filtro_de_oro_v3.json` confirma 7,990 records con cuotas (post fix ALE/ESP/FRA/ITA/ENG) | VERIFICADO |
| 10 reglas en scoring | OK — confirmado en codigo (lineas 537-553 de v2 + 291-300 de v3) | VERIFICADO |

---

## CONTRA-EVIDENCIA DECISIVA

Comparacion lado a lado universo viejo (filtro_de_oro_v2) vs universo expandido fixed (filtro_de_oro_v3):

| score | N_viejo | hit_viejo | yield_viejo | N_nuevo | hit_nuevo | yield_nuevo | delta_yield |
|---|---|---|---|---|---|---|---|
| 6 | 225 | 48.44% | +0.06% | 567 | 49.03% | -2.08% | -2.14pp |
| 7 | 145 | 51.03% | -0.08% | 338 | 50.30% | -3.33% | -3.25pp |
| **8** | **84** | **58.33%** | **+12.96%** | **149** | **48.99%** | **-6.66%** | **-19.62pp** |

El score=8 sweet-spot DESAPARECE al expandir el universo. **Hit rate cae de 58.33% a 48.99% (-9.3pp).** El subset de 84 picks era selection bias del bookmaker matching incompleto pre-fix.

Esto es exactamente el patron del Hallazgo "2025 fail" del propio findings doc: cuando el match es bajo cobertura, el subset matched es no-representativo. Aqui pasa lo mismo con el universo entero, no solo 2025.

---

## HALLAZGOS CRITICOS

### 1. Hindsight bias confirmado (regla "NO Turquia" -3)

El score asigna -3 puntos cuando `is_turquia==1`. **Esto NO es una regla; es una correccion ex-post derivada de observar que Turquia fue OOS-negativa en sample previo.** En el contexto del expanded universe el coef LR estandarizado de `is_turquia` es solo -0.078 (rango medio del coef-set, no top discriminator). Asignar -3 es 38x el coef LR. Es ajuste manual contra el dato.

Si Turquia da -3, ¿por que no Italia, Francia, Alemania mas conservativo? Decision arbitraria.

### 2. Data snooping en thresholds

5 thresholds continuos elegidos post-hoc (P_top>=0.55, >=0.60; div>=0.05, >=0.10; delta_v0_vd>0.05; cuota in [1.5, 2.5)). Cada threshold es un grado de libertad ajustado para que el resultado salga bonito. Total ~10-12 DOF efectivos.

**Ratio dato/parametro: 84/10 = 8.4:1 — DEBAJO del minimo aceptable 10:1** (Reglas_IA.txt principio anti-overfit + literatura ML estandar).

### 3. Bootstrap CI toca CERO

CI95% [-9.5%, +28.6%] cruza cero. Esto significa **NO se rechaza H0: yield=0** al alpha=0.05 two-sided. P(>0)=83% no es un p-value frecuentista — equivale a one-sided p~0.17. **Insuficiente para promocion.**

### 4. Walk-forward OOS pero scoring es in-sample

Las predicciones V_dual / V0 son OOS (refit por year_test). PERO las **10 reglas del filtro fueron derivadas con el dataset completo presente**. Esto es contaminacion de calibracion: las reglas (que son el meta-modelo) tuvieron acceso a 2025-2026.

Si las reglas se hubieran elegido SOLO con datos pre-2025, no veriamos `is_turquia=-3` (Turquia 2025 dio -89% en algunos audits, hindsight). Ni `is_top_liga=-0.10` (NO_TOP es mejor) — eso es V_dual NO_TOP +20.96% del experimento masivo, conocido recien en esta sesion.

### 5. Selection bias multiplicador 2025 NO mitigado en N=7990

El findings doc dice "2025 fail RESUELTO via selection bias". PERO el mismo selection bias afectaba TODO el universo viejo, no solo 2025. La caida de yield al expandir confirma que el problema era estructural — no especifico de 2025.

---

## ANALISIS DE OVERFITTING

| Dimension | Valor |
|---|---|
| N efectivo (score>=8 universo viejo) | 84 |
| Grados de libertad reglas | ~10-12 |
| Ratio dato/parametro | 8.4:1 (FALLA criterio 10:1) |
| Test out-of-sample independiente | NO — reglas usaron data 2026 |
| CI95% del bootstrap | toca cero (no significativo) |
| Replicacion en universo expandido | **FALLA — yield colapsa a -6.66%** |

**Conclusion: overfitting confirmado por replicacion fallida.**

---

## RIESGOS PARA PRODUCCION

1. **Regimen mercado**: 2025 fail muestra que un solo regimen distinto destruye el yield. No hay defensa.
2. **Recalibracion bookmaker**: las divergencias V0 vs mercado dependen de que el bookmaker no cierre el gap. Cualquier mejora del bookie = edge cero.
3. **Sensibility a 1-2 partidos**: cuota_avg 1.92, 84 picks, 49 wins, 35 losses — un solo upset extra mueve yield ~1pp.
4. **Cobertura asimetrica residual**: aun en N=7990, Bolivia/Chile/Col/Ecu/Nor/Peru/Uruguay/Venezuela con 0% match. Decisiones tomadas solo sobre EU+ARG+BRA+TUR no extrapolan.

---

## CONDICIONES PARA RE-EVALUACION

El filtro oro v2 score>=8 NO es production-ready. Para re-evaluar se requiere:

1. **Re-derivar reglas SOLO con datos pre-2025** (excluir 2025-2026 del descubrimiento de reglas).
2. **Validar en hold-out 2025-2026 sin tocar reglas** — esto seria true OOS.
3. **N>=200 picks en hold-out estricto** (no 84).
4. **Bootstrap CI95% que NO toque cero** en hold-out.
5. **Eliminar regla `is_turquia=-3`** (hindsight). Reemplazar por mecanismo principled (ej: entrenamiento per-liga con cross-validation).
6. **Replicacion en universo expandido N=7990** debe dar yield consistentemente positivo en cada subgrupo (year, liga, bin).

---

## ALTERNATIVAS RECOMENDADAS

Del mismo findings doc se observan candidatos mas robustos:

1. **V0 P>=0.60 + div>=0.05**: yield +12.15% N=99, Sharpe 1.24, MaxDD 4.81%. **2 reglas vs 10.** DOF=2, ratio dato/parametro 99/2=49:1. Esto SI pasa criterio overfit.
2. **F2 V_dual + div=0.10 (NO_TOP)**: yield +20.96% N=55, en universo experimentos masivos. Necesita N adicional pero la estructura es mas defendible (filtro liga + filtro modelo, sin reglas magicas).

Cualquiera de estas dos alternativas pasaria una auditoria mas facil que el filtro oro v2.

---

## RECOMENDACION FINAL

**VETADO promover filtro oro v2 score>=8 a produccion.**

El descubrimiento empirico decisivo es que el universo expandido (N=7990) destruye la edge. Antes de cualquier intento futuro:

1. Aceptar que el +12.96% IS era artefacto del subset matched.
2. Investigar **POR QUE** 84 picks score>=8 en universo viejo daban edge — ¿que partidos especificos? ¿que ligas? Probablemente concentrados en Italia (63% match) o Turquia (52.8%) — un sample no aleatorio.
3. Iterar sobre alternativas con menos DOF (V0 P>=0.60 + div>=0.05) primero, donde la evidencia es mas robusta.

El filtro oro v2 score>=8 es un caso-libro de overfitting con post-hoc rule engineering. Persistir esto en produccion seria cobrar al bankroll por un fantasma estadistico.
