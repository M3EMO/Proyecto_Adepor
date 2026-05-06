# Divergencia modelo vs mercado

**Define:** medida de desacuerdo entre la predicción del modelo y la cuota implícita del mercado, por outcome.
**Uso:** filtro pre-bet (umbral de divergencia mínima para apostar).

---

## Probabilidad implícita de mercado

Dada una cuota 1X2 `(c_1, c_x, c_2)` (formato decimal europeo):

```
overround = 1/c_1 + 1/c_x + 1/c_2

P_implícita(L) = (1/c_1) / overround
P_implícita(E) = (1/c_x) / overround
P_implícita(V) = (1/c_2) / overround
```

`overround > 1` siempre (margen del bookmaker). Típicamente 1.028-1.07.

---

## Divergencia del pick

Sea `pick = argmax(P_modelo)` con probabilidad modelo `P_modelo(pick)` y cuota correspondiente `c_pick`:

```
P_implícita(pick) = (1/c_pick) / overround
divergencia(pick) = P_modelo(pick) − P_implícita(pick)
```

**Interpretación:**
- `divergencia > 0`: modelo cree el outcome más probable que el mercado → potencial value bet.
- `divergencia < 0`: modelo cree menos probable que mercado → no apostar el pick.
- `divergencia = 0`: acuerdo total.

---

## Threshold típico de filtro

| Threshold | N relativo | Yield esperado | Interpretación |
|---|---|---|---|
| `div ≥ 0` | universo total argmax | margen bookie ~ -3 a -7% | sin filtro |
| `div ≥ 0.05` | ~80% del argmax | yield mejora 2-3pp | filtro suave |
| `div ≥ 0.10` | ~50% del argmax | yield ~ -1 a +5% | filtro estándar productivo |
| `div ≥ 0.15` | ~25% del argmax | yield ~ +0 a +13% | filtro estricto |
| `div ≥ 0.20` | ~10% del argmax | yield variable | filtro extremo, N chico |

**Threshold productivo Adepor:** `div ≥ 0.10` por defecto (filtro M.4 implícito).

---

## Validación EV

Adicionalmente al threshold de divergencia, exigir `EV_calc ≥ EV_MIN`:

```
EV_calc = P_modelo(pick) · c_pick
EV_MIN  = 1.03 (3% ventaja esperada mínima)
```

`EV_calc ≥ 1.0` significa break-even teórico. `EV_MIN = 1.03` añade 3% margen de seguridad.

---

## Pseudocódigo

```python
def evaluar_pick(P_modelo_lev, cuotas, div_thr=0.10, ev_min=1.03):
    """
    P_modelo_lev: tuple (P_L, P_E, P_V) del modelo
    cuotas: tuple (c_1, c_x, c_2) decimales
    """
    pl, pe, pv = P_modelo_lev
    c1, cx, c2 = cuotas

    overround = (1/c1) + (1/cx) + (1/c2)
    pi_l = (1/c1) / overround
    pi_e = (1/cx) / overround
    pi_v = (1/c2) / overround

    # Pick = argmax modelo
    opciones = [(pl, "L", c1, pi_l), (pe, "E", cx, pi_e), (pv, "V", c2, pi_v)]
    opciones.sort(key=lambda x: -x[0])
    p_top, pick, cuota_pick, pi_pick = opciones[0]

    divergencia = p_top - pi_pick
    ev = p_top * cuota_pick

    if divergencia < div_thr:
        return None  # filtrado
    if ev < ev_min:
        return None  # filtrado

    return {"pick": pick, "p_top": p_top, "cuota": cuota_pick,
            "divergencia": divergencia, "ev": ev}
```

---

## Documentación relacionada

- `docs/definiciones/dixon_coles_rho.md` — cómo se calcula `P_modelo`
- `docs/definiciones/match_cuotas_stats.md` — cómo se obtienen las cuotas
