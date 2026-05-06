# Descalibración V_dual + estrategias maxN apostable

**Fecha:** 2026-05-02
**Trigger:** entender por qué V_dual genera yield siendo descalibrado + maximizar N en zona apostable.
**Script:** `analisis/descalibracion_vdual_y_maxN.py`
**Universo:** 7,045 records OOS walk-forward, 1,767 con cuotas.

## PARTE A — Descalibración V_dual desglosada

### A.1 — Por pick × bucket P_top

V_dual underestima sistemáticamente cuando pick es LOCAL o VISITA con P_top alto:

| Pick | Bucket P | N | P_avg | hit_obs | gap |
|---|---|---|---|---|---|
| L | [0.30, 0.40) | 1541 | 0.380 | 0.404 | +0.024 |
| L | [0.40, 0.50) | 2966 | 0.442 | 0.506 | +0.065 |
| **L** | **[0.50, 0.60)** | **684** | **0.534** | **0.670** | **+0.136** ★ |
| L | [0.60, 0.70) | 38 | 0.625 | 0.711 | +0.086 |
| V | [0.30, 0.40) | 890 | 0.377 | 0.370 | -0.007 (calibrado) |
| V | [0.40, 0.50) | 824 | 0.434 | 0.506 | +0.072 |
| **V** | **[0.50, 0.60)** | **85** | **0.531** | **0.718** | **+0.186** ★★ |

**V_dual está muy underconfident en zona apostable (P_top ≥ 0.50)** — predice 53%, gana 67-72%.

### A.2 — Por liga (P >= 0.50)

| Liga | N | P_avg | hit_obs | gap |
|---|---|---|---|---|
| **España** | 155 | 0.542 | 0.742 | **+0.200** ★★ |
| **Francia** | 71 | 0.537 | 0.732 | **+0.195** ★★ |
| Brasil | 35 | 0.519 | 0.686 | +0.167 |
| Italia | 133 | 0.534 | 0.692 | +0.158 |
| Inglaterra | 172 | 0.538 | 0.692 | +0.154 |
| Alemania | 131 | 0.543 | 0.657 | +0.114 |
| Argentina | 18 | 0.538 | 0.556 | +0.018 (calibrado) |
| Turquía | 60 | 0.547 | 0.583 | +0.036 (calibrado) |
| **Colombia** | 13 | 0.520 | 0.385 | -0.135 (overconfident) |
| **Noruega** | 10 | 0.575 | 0.200 | -0.375 (muy overconfident) ✗ |

**V_dual underconfident en TOP EU (ESP/FRA/ITA/ENG/ALE) y BRA**. **Overconfident en Noruega/Colombia** (samples chicos).

### A.3 — Por banda de cuota_pick (HALLAZGO DECISIVO)

| Banda cuota | N | P_avg | hit_obs | gap |
|---|---|---|---|---|
| **[1.0, 1.5) favoritos extremos** | 274 | 0.499 | 0.734 | **+0.235** ★★★ |
| [1.5, 2.0) | 567 | 0.442 | 0.571 | +0.130 |
| [2.0, 2.5) | 415 | 0.414 | 0.402 | -0.012 (calibrado) |
| [2.5, 3.5) | 350 | 0.396 | 0.343 | -0.053 |
| [3.5, 5.0) | 135 | 0.388 | 0.207 | **-0.181** |
| [5.0+) underdogs | 26 | 0.391 | 0.192 | -0.199 |

## EXPLICACIÓN DEFINITIVA del yield V_dual

**V_dual está sistemáticamente:**
- **UNDERCONFIDENT en favoritos** (cuota < 2.0): predice 44-50% pero gana 57-73%.
- **OVERCONFIDENT en underdogs** (cuota > 3.5): predice 39% pero gana 19-21%.

Cuando V_dual dice "favorito a 1.40 con P=50%" pero el favorito gana 73%:
- Divergencia con mercado (que predice 70%): gap negativo en P pero pick coincide.
- En realidad, el outcome se cumple → win.

El **yield viene de UNDERESTIMACIÓN sistemática de favoritos**. No es magia descriptiva — es un sesgo del modelo que el filtro EV captura porque la cuota baja (1.40) × hit alto (73%) = +2pp sobre 1.0.

**Esto es FRÁGIL.** Cualquier recalibración (Platt scaling, isotonic regression) que arregle la descalibración eliminaría el yield.

**Lección:** V_dual NO es mejor predictor que V0/MKT. V_dual ES un descriptor sub-óptimo cuyo error sistemático coincide con la inversión asimétrica del mercado en favoritos.

## PARTE B — Estrategias maxN con yield > 0

### TOP yield N ≥ 200 (production-ready N)

| Strategy | N | hit% | Yield IS |
|---|---|---|---|
| V0+Vdual CONSENSUS div>=0.10 | 287 | 31.71 | **+2.34%** |
| V0+Vdual+Vruido AVG div>=0.10 | 211 | 27.01 | +1.91% |
| V0+Vruido CONSENSUS div>=0.05 | 230 | 33.48 | +1.88% |
| V0+Vdual AVG div>=0.10 | 309 | 30.74 | +1.84% |
| V0+Vruido AVG div>=0.10 | 230 | 27.39 | +0.92% |

### TOP yield N ≥ 100

| Strategy | N | hit% | Yield IS |
|---|---|---|---|
| V0+Vruido CONSENSUS div>=0.10 | 118 | 30.51 | **+8.45%** |
| **V0 P>=0.55 div>=0.05** | 164 | 51.83 | **+4.76%** ★ |
| V0 P>=0.6 div>=0.05 | 99 | 59.60 | **+12.15%** ★★ |
| V0+Vdual CONSENSUS div>=0.10 | 287 | 31.71 | +2.34% |

### TOP yield N ≥ 30

| Strategy | N | hit% | Yield IS |
|---|---|---|---|
| V0 anchor=0.5 div>=0.10 | 55 | 45.45 | **+16.82%** ★★ |
| V0 P>=0.6 div>=0.05 | 99 | 59.60 | +12.15% |
| V0 anchor=0.3 div>=0.05 | 68 | 47.06 | +9.97% |
| V0+Vruido CONSENSUS div>=0.10 | 118 | 30.51 | +8.45% |

### Hallazgos críticos

**1. V_dual SOLO puede agregar valor en consensus/avg con V0.** Single-model V_dual NO da yield. La dilución con V0 evita el overconfidence en underdogs de V_dual.

**2. **V0 puro con FLOOR_P alto + div>=0.05 es la estrategia más limpia:**
- V0 P>=0.55 div>=0.05: N=164 yield +4.76%
- V0 P>=0.60 div>=0.05: N=99 yield +12.15% (sweet spot)
- V0 anchor=0.5 div>=0.10: N=55 yield +16.82%

**Esto valida el motor productivo SIN tocar V_dual.** Filtros simples (FLOOR_P + divergencia) sobre V0 alcanzan +12% yield N=99.

**3. Ensembles V0+Vdual:** mejor volumen (N=287) pero yield modesto (+2.34%). Útil si queremos N alto a costa de yield.

**4. V_ruido contribuye marginalmente.** V0+V_ruido CONSENSUS gana +8.45% N=118 — útil como filtro de "ruido informativo" adicional.

## Recomendación operativa actualizada

### Configuración para producción:

```python
# Configuración 1 — máxima yield, N moderada
si V0.predict pick = X with P >= 0.55 AND divergencia(V0, mercado) >= 0.05:
    apostar  # esperado: +4.76% yield, N=164/4años (≈40/año)

# Configuración 2 — sweet spot
si V0.predict pick = X with P >= 0.60 AND divergencia(V0, mercado) >= 0.05:
    apostar  # esperado: +12.15% yield, N=99/4años (≈25/año)

# Configuración 3 — ensemble para más volumen
si V0.pick == Vdual.pick AND divergencia(consensus, mercado) >= 0.10:
    apostar el pick  # esperado: +2.34% yield, N=287/4años (≈70/año)
```

### Comparativa final con V0 motor original

| | V0 original | V0 + filtros maxN | V0+Vdual CONSENSUS |
|---|---|---|---|
| Estrategia | div>=0.15 fija | P>=0.60 + div>=0.05 | consensus + div>=0.10 |
| N IS | 104 | 99 | 287 |
| Yield IS | +13.15% | +12.15% | +2.34% |

V0 original es mejor que V0+filtros en yield% pero con MISMO N. El motor productivo ya está bien tuned. **Las configuraciones nuevas no superan dramáticamente.**

## Conclusión

1. **V_dual yield viene de descalibración sistemática en favoritos** — no es generalizable.
2. **El motor productivo V0 con filtros simples (FLOOR_P + div) ya extrae el yield disponible.**
3. **Ensembles aportan volumen pero diluyen yield** — útil solo si la prioridad es N alto.
4. **Espacio de mejora limitado** dado el régimen mercado eficiente y los datos disponibles.
