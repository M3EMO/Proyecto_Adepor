# Dixon-Coles τ y MLE de ρ

**Define:** corrección Dixon-Coles a Poisson independiente para marcadores bajos + cálculo MLE de ρ per-liga.
**Referencia:** Dixon-Coles 1997 "Modelling Association Football Scores".
**Código:** `src/nucleo/motor_calculadora.py:944`, `scripts/calibrar_rho.py`.

---

## Función τ (corrector marcadores bajos)

Dado un partido con `λ_h` (xG local) y `λ_v` (xG visita):

```
τ(h, a, λ_h, λ_v, ρ) =
    1 − λ_h · λ_v · ρ           si h=0 ∧ a=0
    1 + λ_h · ρ                 si h=0 ∧ a=1
    1 + λ_v · ρ                 si h=1 ∧ a=0
    1 − ρ                       si h=1 ∧ a=1
    1                           otherwise
```

---

## Probabilidad de marcador (h, a)

```
P(home_goals = h, away_goals = a) =
    Poisson(h | λ_h) · Poisson(a | λ_v) · τ(h, a, λ_h, λ_v, ρ)
```

Donde `Poisson(k | λ) = e^(−λ) · λ^k / k!`.

---

## Probabilidades 1X2

Truncar a `MAX_GOALS = 8` (cobertura > 99.9% de marcadores reales).

```
P(L) = Σ_(h > a)  P(home=h, away=a)
P(E) = Σ_(h == a) P(home=h, away=a)
P(V) = Σ_(h < a)  P(home=h, away=a)
```

Normalizar: si `S = P(L) + P(E) + P(V) > 0`, dividir cada uno por S.

---

## MLE de ρ per-liga

Sobre histórico `{(λ_h_i, λ_v_i, hg_i, ag_i) : i = 1..N}` por liga:

```
LL(ρ) = Σ_i log P(home=hg_i, away=ag_i | λ_h_i, λ_v_i, ρ)
      = Σ_i [log Poisson(hg_i | λ_h_i) + log Poisson(ag_i | λ_v_i) + log τ(hg_i, ag_i, λ_h_i, λ_v_i, ρ)]
```

**Estimador:** `ρ_liga = argmax_ρ LL(ρ)` con ρ ∈ [-0.20, +0.20] grid step 0.005.

**Restricción:** N ≥ 50 partidos para calibrar (else fallback global ρ=−0.05).

---

## Pseudocódigo

```python
import math

MAX_GOALS = 8

def poisson_pmf(k, lam):
    if lam <= 0: lam = 0.01
    return math.exp(-lam) * (lam ** k) / math.factorial(k)

def dc_tau(h, a, lh, lv, rho):
    if h == 0 and a == 0: return 1 - lh * lv * rho
    if h == 0 and a == 1: return 1 + lh * rho
    if h == 1 and a == 0: return 1 + lv * rho
    if h == 1 and a == 1: return 1 - rho
    return 1.0

def prob_1x2(lh, lv, rho):
    pl = pe = pv = 0.0
    for h in range(MAX_GOALS + 1):
        for a in range(MAX_GOALS + 1):
            p = poisson_pmf(h, lh) * poisson_pmf(a, lv) * dc_tau(h, a, lh, lv, rho)
            p = max(0.0, p)
            if h > a:   pl += p
            elif h == a: pe += p
            else:        pv += p
    s = pl + pe + pv
    if s > 0: pl /= s; pe /= s; pv /= s
    return pl, pe, pv

def calibrar_rho(pairs):
    """pairs: list of (liga, lambda_h, lambda_v, hg, ag) por partido."""
    grid = [round(-0.2 + 0.005 * i, 3) for i in range(81)]
    by_liga = defaultdict(list)
    for liga, lh, lv, hg, ag in pairs:
        if lh > 0 and lv > 0:
            by_liga[liga].append((lh, lv, hg, ag))
    rhos = {}
    for liga, ps in by_liga.items():
        if len(ps) < 50:
            rhos[liga] = -0.05  # fallback
            continue
        best_rho, best_ll = -0.05, -math.inf
        for rho in grid:
            ll = 0.0
            for lh, lv, hg, ag in ps:
                p = poisson_pmf(hg, lh) * poisson_pmf(ag, lv) * dc_tau(hg, ag, lh, lv, rho)
                if p > 0: ll += math.log(p)
                else: ll = -math.inf; break
            if ll > best_ll:
                best_ll, best_rho = ll, rho
        rhos[liga] = best_rho
    return rhos
```

---

## Valores ρ típicos calibrados

Para liga competitiva top: ρ ∈ [-0.10, +0.05]. Valores observados:
- Brasil: -0.041
- Inglaterra: -0.041
- Bolivia: -0.031
- Alemania: -0.145 (más extremo, posible outlier sample chico)
- Default fallback: −0.05

---

## Almacenamiento

- `ligas_stats.rho_calculado` — ρ histórico calibrado por liga
- `config_motor_valores.RHO_FALLBACK` — fallback global cuando N < 50
