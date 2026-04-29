# V14 v2 SHADOW: filtro picks apostables copa_nacional (hit +21.6pp)

> **Fecha:** 2026-04-29
> **Pregunta:** Pool copa_nacional V14 v2 SHADOW tiene hit 47.8% (N=4,621). ¿Hay
> subset(s) con hit consistentemente >55% que justifique aplicar V14 v2 para
> selección de picks LIVE en F2-sub-15 fase 2?
> **Source:** `analisis/v14_v2_shadow_copa_nacional_drill.py` + `picks_shadow_v14_copa`.

---

## Hallazgos clave

### 1. Pattern p_max monotónico (calibración bayesiana de V14 v2)

| p_max bucket | N | hit% | Wilson lo |
|---|---|---|---|
| 0.40-0.45 | 1,743 | 41.5% | 39.2% |
| 0.45-0.50 | 1,716 | 48.0% | 45.6% |
| 0.50-0.55 | 525 | 50.1% | 45.8% |
| 0.55-0.60 | 228 | 53.5% | 47.0% |
| 0.60-0.65 | 133 | 59.4% | 50.9% |
| **0.65-0.70** | **96** | **67.7%** | **57.8%** |
| **0.70-1.00** | **175** | **76.0%** | **69.2%** |

**Lectura:** V14 v2 está bien calibrado en copa_nacional. p_max funciona como
score de confianza confiable. Todo pick con p_max ≥ 0.65 tiene hit > 67%.

### 2. Pattern delta_elo (favoritos extremos)

| |delta_elo_pre| | N | hit% | Wilson lo |
|---|---|---|---|
| 0-100 | 2,231 | 43.6% | 41.6% |
| 100-200 | 2,081 | 49.2% | 47.1% |
| **200-300** | **216** | **63.4%** | 56.8% |
| **300-400** | **70** | **78.6%** | 67.6% |

**Lectura:** Diferencia de Elo ≥200 puntos predice picks copa_nacional con
hit ≥63%. ≥300 puntos: 78.6%.

### 3. Pattern por edición × argmax (asimetría LOCAL/VISITA)

Buenos:
| Edición | Argmax | N | hit% | Wilson lo |
|---|---|---|---|---|
| **Copa del Rey** | 2 (visita) | 125 | **80.0%** | 72.1% |
| **Türkiye Kupası** | 1 (local) | 285 | **66.0%** | 60.3% |
| **Coppa Italia** | 1 (local) | 109 | **64.2%** | 54.9% |
| DFB Pokal | 1 | 103 | 53.4% | 43.8% |
| Copa do Brasil | 1 | 331 | 51.4% | 46.0% |
| FA Cup | 1 | 2,005 | 47.2% | 45.0% |

Malos (excluir):
| Edición | Argmax | N | hit% | Acción |
|---|---|---|---|---|
| **Coupe de France** | 1 | 304 | **33.9%** | EXCLUIR |
| **Copa del Rey** | 1 | 200 | **31.5%** | EXCLUIR |
| FA Cup | 2 | 253 | 37.2% | marginal |
| Copa Argentina | 1 | 155 | 42.6% | EXCLUIR |
| EFL Cup | 1 | 251 | 44.6% | marginal |

**Hallazgo crítico Copa del Rey:** los picks LOCAL (Real Sociedad local vs Real
Madrid visita) FALLAN 68% de las veces porque los GRANDES juegan visita y ganan.
**El argmax='2' (visita) en Copa del Rey acierta 80%** — Real/Barca/Atletico
visitando a equipos chicos y ganando.

### 4. Pattern HIGH-CONFIDENCE consolidado

LOCAL + p_max≥0.55 + delta_elo≥200:
| Edición | N | hit% | Wilson lo | Sig |
|---|---|---|---|---|
| **FA Cup** | 42 | **76.2%** | 61.5% | *** |
| **Copa do Brasil** | 52 | **73.1%** | 59.7% | *** |
| **Türkiye Kupası** | 22 | 68.2% | 47.3% | *** |
| **Coppa Italia** | 43 | 67.4% | 52.5% | *** |
| **EFL Cup** | 38 | 65.8% | 49.9% | *** |
| Copa Argentina | 23 | 60.9% | 40.8% | ** |
| Coupe de France | 31 | 54.8% | 37.8% | — |
| **TOTAL** | **276** | **68.1%** | **62.4%** | *** |

---

## Filtro propuesto (rules persistidas en `config_motor_valores.v14_v2_copa_nacional_filter_rules`)

### Reglas inclusión

- **R1**: `argmax='1' AND p_max>=0.55 AND delta_elo_pre>=200` (high-confidence LOCAL)
- **R2**: `competicion='Copa del Rey' AND argmax='2' AND p_max>=0.45` (favoritos visita)
- **R3**: `competicion='Türkiye Kupası' AND argmax='1' AND p_max>=0.45`
- **R4**: `competicion='Coppa Italia' AND argmax='1' AND p_max>=0.45`
- **R5**: `p_max_v14_v2>=0.65` (high-confidence cross-edición)

### Reglas exclusión (override sobre R1-R5)

- **X1**: `competicion='Coupe de France' AND argmax='1' AND p_max<0.55`
- **X2**: `competicion='Copa del Rey' AND argmax='1' AND p_max<0.65`
- **X3**: `competicion='Copa Argentina' AND argmax='1' AND p_max<0.55`

### Métricas subset apostable (sobre 9,164 partidos copa_nac SHADOW)

| Métrica | Valor |
|---|---|
| N apostable | 615 |
| Hits | 427 |
| **Hit rate** | **69.4%** |
| Wilson lo 95% | **65.7%** |
| Pool completo hit | 47.8% |
| **Mejora** | **+21.6 pp** |
| Volumen proyectado | ~12 picks/mes |

---

## Estabilidad temporal apostable

| Edición | 2022 | 2023 | 2024 | 2025 | 2026 IS | Lectura |
|---|---|---|---|---|---|---|
| Türkiye Kupası | 89% | 73% | 64% | 58% | — | Decrec moderada |
| Copa del Rey | — | 100% | 63% | 81% | — | Volatil alta |
| Coppa Italia | 80% | 54% | 67% | 68% | 50% | Estable medio |
| **Copa do Brasil** | — | 88% | 65% | 73% | 83% | **Alto sostenido** |
| **FA Cup** | — | 88% | 67% | 75% | 75% | **Alto sostenido** |
| EFL Cup | — | 50% | 82% | 64% | — | Volatil |
| Coupe de France | — | 60% | 67% | 62% | 62% | Estable medio |
| Copa Argentina | — | — | 62% | 62% | — | N chico |
| DFB Pokal | — | 60% | — | 80% | — | N chico |

**Más confiables: Copa do Brasil + FA Cup** (alto sostenido cross-año).
**Menos confiables: Türkiye Kupası decreciente** + EFL Cup volátil.

---

## Caveat: hit rate ≠ yield real

**Sin cuotas reales para copa_nacional histórico 2022-2026** (bead `adepor-4tb`
BLOQUEADO API Pro + football-data.co.uk no cubre copas).

Yield estimado con cuota promedio típica favoritos:
- Hit 0.694 × cuota 1.50 − 1 = +4.1%
- Hit 0.694 × cuota 1.70 − 1 = +18.0%
- Hit 0.694 × cuota 1.80 − 1 = +25.0%

**Confirmar yield real requiere obtener cuotas:**
1. Upgrade API-Football Pro (~$19/mes) — bead `adepor-4tb`
2. Scraper alternativo (oddsportal/footiqo) — high effort legal-grey
3. The-Odds-API (cobertura parcial: FA Cup soccer_fa_cup verified)

---

## Aplicación pendiente

Las rules están persistidas en `config_motor_valores.v14_v2_copa_nacional_filter_rules`
**pero NO se aplican aún en motor productivo**. F2-sub-15 fase 2 requiere:

1. `obtener_ema_cross_liga()` (resuelve EMA cross-liga para copas)
2. Hook bias factors + filter rules en `motor_calculadora.py`
3. Validación SHADOW N≥200 in-sample 2026 con outcomes reales antes de promover

**Trigger fase 2:** N≥200 picks SHADOW + cuotas reales disponibles.

---

## Sources

- `analisis/v14_v2_shadow_copa_nacional_drill.py` (script reproducible)
- `picks_shadow_v14_copa` (9,300 filas SHADOW backfill)
- `config_motor_valores.v14_v2_copa_nacional_filter_rules` (rules persistidas)
- Davis et al. 2024 ML journal (53 cits) — concept drift sports analytics

[REF: docs/papers/v14_v2_copa_nacional_filtro_apostable.md]
