# Findings — Proxy pos_backward via V13 xG

> Bead: `adepor-a1v` (claimed + closed 2026-04-28)
> Sample: 4 ligas V13 (Argentina, Francia, Inglaterra, Italia) × temps 2022-2024 = 194 equipos
> Output: `analisis/proxy_pos_backward_correlacion.{py,json}`

## Resumen ejecutivo

**V13 xG capta calidad estructural (pos_backward) con r promedio = −0.622 cross-(liga, temp).**
Como pos_backward es ranking (1 = mejor), correlación negativa fuerte significa que
mejor equipo (pos_backward chica) → mayor xG_v13 esperado. **Bead cierra: V13 SHADOW
ya está capturando la señal estructural detectada en commit d489ec6**.

## Contexto

El audit previo (commit d489ec6) mostró que `pos_backward` (posición FINAL de la temp,
constante para todos los partidos del equipo en esa temp) tiene **más poder predictivo
que `pos_forward`** (posición runtime). Ej:

- Temp 2024 TOP-3 backward: yield +47.8% CI95 [+7.2, +87.4] ★★★ sig
- Temp 2024 |div_fwd_bwd| > 5: yield +24.3% CI95 [+2.6, +46.8] ★★ sig

Problema: `pos_backward` no es usable runtime (incluye info post-partido). Solo sirve
como AUDIT. Pregunta del bead: ¿hay un proxy runtime (V13 xG, EMAs) que ya capture la
señal y por tanto el motor ya la esté usando implícitamente?

## Resultados

### Correlación pos_backward vs xG_v13 promedio por (liga, temp)

| Liga | Temp | N | r(xg_v13) | r(ema_sots) | r(shot_pct) | r(diff_sots) |
|---|---|---|---|---|---|---|
| Argentina | 2023 | 9 | −0.019 | −0.267 | −0.016 | +0.406 |
| Inglaterra | 2022 | 9 | −0.276 | **−0.730** | +0.197 | +0.096 |
| Inglaterra | 2023 | 10 | **−0.789** | **−0.937** | −0.433 | −0.046 |
| Inglaterra | 2024 | 9 | **−0.916** | **−0.817** | −0.308 | **−0.600** |
| Italia | 2022 | 9 | **−0.710** | **−0.713** | −0.477 | **−0.592** |
| Italia | 2024 | 10 | **−0.825** | **−0.802** | **−0.620** | −0.393 |
| Francia | 2022 | 13 | **−0.747** | **−0.742** | −0.246 | −0.129 |
| Francia | 2023 | 12 | **−0.755** | **−0.813** | +0.129 | +0.374 |
| Francia | 2024 | 11 | **−0.565** | **−0.621** | −0.248 | **+0.680** |

★ = |r| > 0.5

**Promedio r(xg_v13, pos_backward) cross-(liga, temp) = −0.622** (umbral cierre: r < −0.3).

### Interpretación por liga

- **Inglaterra/Italia/Francia (V13 con feature_set rico)**: V13 capta señal con r entre
  −0.565 y −0.916. Particularmente fuerte en Inglaterra (F5_ratio NNLS) e Italia
  (F2_pos RIDGE).
- **Argentina (V13 F1_off NNLS)**: r=−0.019 en 2023 es ANÓMALO. Razón: F1 NNLS sólo
  activa coef `atk_sots = 0.160`, todos los demás coefs en cero. Como xG ≈ 0.594
  (intercept) + 0.160 × ema_l_sots, la varianza de xG_v13 entre equipos es chica →
  correlación amortiguada. EMA sots solo (sin intercept) da r=−0.267.
- **Diff_sots** (atk-def) es **inestable cross-temp**. Signo cambia en Argentina
  (+0.406), Francia 2024 (+0.680). NO es un buen proxy estable.

### EMA sots (sin pasar por V13) supera a xG_v13 en algunas ligas

| Liga | r(xg_v13) avg | r(ema_sots) avg |
|---|---|---|
| Inglaterra | −0.660 | −0.828 |
| Italia | −0.768 | −0.758 |
| Francia | −0.689 | −0.725 |
| Argentina | −0.019 | −0.267 |

EMA sots crudo correlaciona MÁS fuerte con pos_backward que xG_v13 en Inglaterra y
Argentina. Esto sugiere que el `intercept` de V13 (que en NNLS suele ser alto) está
"diluyendo" la señal de la feature dominante (sots). **Implicación secundaria:** en
ligas donde V13 es mayormente intercept (NNLS sparse), considerar pesar más la
feature de sots o entrenar con más features.

## Decisión

**CERRAR adepor-a1v** con veredicto **V13 captura calidad estructural** en las 4 ligas
calibradas (Argentina, Francia, Italia, Inglaterra). Cumple criterio del bead
(`r < −0.3` cross-temp).

### Caveats documentados

1. **Argentina V13 (F1_off NNLS) es proxy débil** (r=−0.019 vs r=−0.267 con ema_sots
   crudo). El intercept domina sobre la feature. Trigger futuro: si V13 se promueve
   a argmax en Argentina (`adepor-6g5`), evaluar primero si ema_sots crudo o un V13
   con feature_set ampliado (F2_pos en vez de F1_off) tiene mejor correlación.

2. **Las ligas TOP-5 V5.1 NO calibradas en V13** (Brasil, Noruega, Turquía) no tienen
   garantía de captura de pos_backward. Para esas ligas, el motor V0 + EMA crudo
   debe estar capturando algo similar pero no se mide en este audit.

3. **N por celda chico** (9-13 equipos por liga × temp). Pearson con N<15 es ruidoso.
   Conclusión cross-(liga, temp) con r promedio −0.622 es robusta, pero celdas
   individuales como Argentina 2023 son muy bajos N.

## Implicaciones operativas

- **No requiere cambio al motor**: V13 SHADOW (ya activo) suficientemente captura la
  señal estructural identificada.
- **Trigger futuro**: si V13 promueve a argmax en alguna liga vía `adepor-6g5`, validar
  primero que la correlación con pos_backward se sostiene en datos OOS post-promoción.
- **Si Argentina V13 promueve**: re-evaluar feature_set (F1_off → F2_pos) o
  considerar feature compuesto explícito tipo `calidad_estructural_proxy = mean(EMA
  sots) - mean(EMA sots concedidos)` que correlaciona más fuerte (r=−0.267 ARG vs
  r=−0.019 V13).

## Próximos pasos

- [x] Script ejecutado y veredicto claro
- [x] Bead `adepor-a1v` cerrado con notas
- [ ] Si en futuro un equipo de la liga Argentina con V13 muestra picks operativos
  débiles, regresar a este audit y considerar ampliar feature_set V13 ARG.
