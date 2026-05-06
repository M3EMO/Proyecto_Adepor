# Bonferroni & Bootstrap — anti-overfit estricto

**Define:** correcciones estadísticas obligatorias para validar cualquier filtro/estrategia antes de promover a SHADOW MODE o producción.

---

## Bonferroni — corrección por múltiples hipótesis

### Definición

Cuando se prueban `N` hipótesis simultáneamente con nivel de significancia individual `α`, la probabilidad de al menos un falso positivo crece con `N`. Bonferroni corrige:

```
α_individual_corregido = α_global / N
```

**Ejemplo:** probar 8 ligas con α global = 0.05 → α individual = 0.05/8 = **0.00625**.

### Cuándo aplicar

- Probar la misma estrategia sobre múltiples ligas/años/equipos.
- Grid search de thresholds (P_min × div_min × cuota → cientos de combinaciones).
- Comparativa de N modelos.

### Si se omite

Resultados con `p < 0.05` individual pueden ser ruido del multiple testing. Esperado: ~5% de N hipótesis dará falso positivo a α=0.05. Para 100 tests, **5 falsos positivos esperados**.

---

## Bootstrap percentile — CI95% del yield

### Definición

Dado un conjunto de bets `S = {pnl_1, pnl_2, ..., pnl_N}`, el bootstrap estima la distribución del yield estimador:

**Procedimiento:**
```
B = 5000 (o 10000 para más precisión)
for b in 1..B:
    sample_b = resample_with_replacement(S, size=N)
    yield_b  = mean(sample_b) * 100
sort(yield_1, ..., yield_B)

CI95%_lo = yield_{0.025*B}     # percentile 2.5
CI95%_hi = yield_{0.975*B}     # percentile 97.5
P(yield > 0) = #{b : yield_b > 0} / B
```

### Pseudocódigo

```python
import random

def bootstrap_yield_ci95(pnls, B=5000, seed=42):
    """
    pnls: list of pnl per bet (e.g. cuota-1 si gana, -1 si pierde, stake=1u flat).
    """
    random.seed(seed)
    n = len(pnls)
    if n == 0:
        return None
    boots = []
    for _ in range(B):
        sample = [random.choice(pnls) for _ in range(n)]
        boots.append(sum(sample) / n * 100)
    boots.sort()
    return {
        "yield_obs": sum(pnls) / n * 100,
        "ci95_lo": boots[int(0.025 * B)],
        "ci95_hi": boots[int(0.975 * B)],
        "prob_positive": sum(1 for y in boots if y > 0) / B * 100,
        "N": n,
    }
```

### Lectura

- `CI95%_lo > 0`: yield estadísticamente positivo. **Necesario para promoción.**
- `CI95%_lo < 0 < CI95%_hi`: yield no significativo (cruza cero).
- `prob_positive ≥ 95%`: equivalente a `CI95%_lo > 0` (Bayesian aprox).

---

## Reglas obligatorias para promoción a SHADOW

Toda estrategia/filtro candidato a SHADOW DEBE cumplir TODAS:

1. **N ≥ 100** picks (50 si imposible, marcar como tentativo).
2. **Yield IS pooled walk-forward ≥ +5%**.
3. **Bootstrap CI95% percentile 5 > 0** (LB positivo).
4. **≥ 50% años con yield > 0** (consistencia cross-año).
5. **Bonferroni-adjusted** si se prueban N hipótesis: usar `α = 0.05/N`.

---

## Reglas obligatorias para promoción a PRODUCCIÓN

Adicional a las de SHADOW:

6. **Holdout estrictamente OOS** confirma direccionalidad.
7. **Veto de critico** (`agentes_findings.veto_critico = 0`).
8. **Bead `[PROPOSAL: MANIFESTO CHANGE]`** si toca constantes protegidas.
9. **Cascada de recalibración documentada** si toca `xg_final` o filtros productivos.
10. **N SHADOW operativo ≥ 200** antes de bankroll real.

---

## DOF / N ratio — anti-overfit estructural

Para un filtro con `K` parámetros libres (thresholds, coefs, etc.) sobre `N` bets:

```
ratio = N / K
```

| Ratio | Riesgo |
|---|---|
| < 5:1 | Overfit casi garantizado. Rechazar. |
| 5:1 - 10:1 | Riesgo alto. Tentativo. |
| 10:1 - 25:1 | Aceptable con bootstrap. |
| ≥ 25:1 | Robusto. |

**Ejemplo:** filtro con `(P_min, div_min, c_min, c_max) = 4 thresholds` sobre N=100 bets → ratio 25:1, OK.

Filtro de 10 reglas (filtro de oro v2) sobre N=84 → ratio 8.4:1, riesgo alto. **Confirmado overfit en universo expandido.**

---

## Casos del proyecto (referencia histórica)

| Estrategia | N | DOF | ratio | Resultado |
|---|---|---|---|---|
| Filtro oro v2 score≥8 | 84 | 10 | 8.4:1 | OVERFIT (yield +12.96 → -6.66 al expandir N) |
| V0 P≥0.60 + div≥0.05 | 99 | 2 | 49.5:1 | ROBUSTO en metodología (pero -0.97% real) |
| ESP filtro P>=0.45+div>=0.15+cuota∈[2,4] | 80 | 4 | 20:1 | VALIDADO LOYO (B avg OOS +1.70%) |
| ENG filtro P>=0.50+div>=0.20+cuota>=2.0 | 45 | 3 | 15:1 | VALIDADO LOYO (B avg OOS +3.06%) |

---

## Documentación relacionada

- `docs/definiciones/walk_forward_paradigmas.md` — splits para validación
- `docs/papers/audit_v0_crudo_n_expandido.md` — uso de Bonferroni en audit crítico
- `docs/papers/walk_forward_true_oos_5_propuestas.md` — bootstrap percentile aplicado
