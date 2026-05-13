# Diagnóstico yield negativo 2026 (sesión 2026-05-13)

## Resumen ejecutivo

El bankroll perdió yield -12.5% sobre 52 apuestas reales (N=18 1x2 + N=34 ou) en
ventana 2026-04-23 a 2026-05-03. Análisis E+A+D revela 3 causas concurrentes:

1. **Bias LOCAL del motor (estructural, no drift 2026):** motor infla prob_1
   progresivamente con cuota. En bucket cuota_1 ∈ [2.4, 3.5) gap +8-15pp vs
   mercado, hit real 30pp por debajo de la predicción del motor.
2. **M.2 (n_acum_l<60) calibrado en 2024 (año atípico), invierte en 2026 y
   varias ligas** (Turquía, Argentina, Holanda con thr=20 darían yield positivo).
3. **Drift régimen 2026 (-4.7pp):** se suma a estructural pero NO es causa
   principal.

## Cadena de evidencia

### Etapa 1 — Análisis 2026 (partidos_backtest, N=281 liquidados)

- Stake uniforme=1: hit 51.2%, yield **+30.0%** → motor SÍ tiene edge.
- Stake real (bankroll): hit 42.3%, yield **-12.5%** → bankroll pierde.
- Tijera de 53pp entre lo que el motor "habría apostado" y lo efectivo.

Causa raíz inmediata: filtros operativos del bankroll seleccionan el subset PEOR
del universo del motor. En particular:

- **PRETEST MODE** (`apuestas_live` flag scoped per liga): si FALSE → motor
  calcula pero stake=0. Hoy TODAS las ligas en FALSE para 1x2.
- Las 18 apuestas 1x2 reales fueron en ventana donde Arg/Brasil/Noruega
  estaban TEMPORALMENTE TRUE. Fueron desactivadas post-mortem.
- **NO existía tabla histórica de config** → forensics ciegas (fixed por #4).

### Etapa 2 — M.2 invertido (picks_shadow_m2_log + histórico)

Sobre 107 picks 2026 decididos por motor:

| Bucket M.2 | N | Hit | Yield uniforme |
|---|---|---|---|
| `<60` (PASA) | 56 | 50.0% | +56.5% |
| `>=60` (BLOQUEADO) | 51 | 49.0% | **+83.6%** |

Costo M.2 con thr=60: ~27pp yield desperdiciados.

Sobre histórico 2012-2025 (N=23,568 cuotas_historicas_fdco):

- 2022, 2023, 2025: M.2 funciona (gap +11-15pp).
- 2024 (donde fue calibrada): gap **-13.8pp** (invertido).
- 2026: gap -8.9pp (mismo signo que 2024 → overfit a régimen atípico).

Per-liga heterogeneidad gigante (calibrado en analisis/_m2_per_liga_v1.json):

| Liga | thr óptimo | yield filtrado |
|---|---|---|
| Holanda | 20 | +8.1% |
| Turquía | 20 | +9.2% |
| España | 30 | -0.1% |
| Alemania | 50 | -0.2% |
| Italia | 70 | -6.1% |
| Inglaterra | 100 | +1.8% |
| Francia | DESACTIVAR | (todos thr empeoran) |
| Argentina/Brasil | 60 default | indiferente |

### Etapa 3 — Bias LOCAL motor (calibración partidos_backtest 2026)

Motor V0 sobre 823 partidos 2026 con prob predicha + outcome:

| Bucket cuota_1 | p_motor | hit_real | corr_factor | gap |
|---|---|---|---|---|
| <1.8 | 0.444 | 0.578 | +1.30 | -13.5pp (sub-predice) |
| [1.8, 2.4) | 0.452 | 0.497 | +1.10 | -4.6pp |
| [2.4, 2.8) | 0.435 | 0.354 | 0.81 | **+8.2pp** |
| [2.8, 3.5) | 0.412 | 0.294 | 0.71 | **+11.8pp** ← bucket apuestas |
| [3.5, 5.0) | 0.420 | 0.269 | 0.64 | +15.1pp |
| >=5.0 | 0.406 | 0.233 | 0.58 | +17.3pp |

Aplicando calibración sobre 150 partidos del bucket apuestas: prob_1 baja
0.425 → 0.325 alineada con hit real 0.327.

### Etapa 4 — D.1 mercado bookmaker bien calibrado (histórico 2012-2025)

Sobre 23,568 partidos con cuotas: delta hit vs implícito <±3pp en todos los
buckets. **El mercado NO está mispricing** — el bias 2026 viene del motor,
no de oportunidades de arbitraje vs bookies.

Apostar LOCAL ciegamente en bucket [2.4, 3.5):

| Year | hit_1 | delta vs implícito | yield uniforme |
|---|---|---|---|
| 2022 | 32.7% | -1.7pp | -7.9% |
| 2023 | 36.6% | +1.9pp | +2.5% |
| 2024 | 32.0% | -2.2pp | -9.7% |
| 2025 | 34.3% | -0.2pp | -5.0% |
| **2026** | **28.8%** | **-4.7pp** | **-19.7%** |

2026 está en extremo malo del rango histórico pero NO fuera de él. Apostar
LOCAL en este bucket nunca fue rentable (mediana yield -3%).

## Recomendaciones aplicadas / pendientes

| # | Acción | Estado | Bead |
|---|---|---|---|
| 1 | Calibración post-hoc P(LOCAL) por liga × bucket cuota_1 | **PROPOSAL** | adepor-vue |
| 2 | M.2 thresholds per-liga | **PROPOSAL** | adepor-to4 |
| 3 | Filtro hard gap motor/mercado | descartado (sin señal robusta, N=331) | - |
| 4 | Tabla `config_motor_valores_history` + triggers | **aplicado** | adepor-slu |
| 5 | V14 v3 audit (no resuelve liga regular, solo copas) | analizado | - |

## Artefactos

- `analisis/_d1_bookmaker_calib.csv` — universo histórico 2012-2025
- `analisis/_d2_m2_historico.csv` — picks LOCAL histórico bucket [2.2, 3.5)
- `analisis/_calibracion_local_v1.json` — calibración P(LOCAL) (Rec #1)
- `analisis/_m2_per_liga_v1.json` + `_m2_per_liga_patch.sql` — M.2 per-liga (Rec #2)
- `analisis/_filtro_gap_motor_mercado_v1.json` — filtro hard (descartado)
- `analisis/_config_history_setup.py` — infra history table (Rec #4 aplicado)

## Próximos pasos sugeridos

1. **Validar #1 SHADOW**: aplicar calibración como flag SHADOW en config, comparar
   yield motor-calibrado vs motor-actual sobre próximos 80+ picks.
2. **Validar #2 SHADOW**: aplicar M.2 thresholds per-liga como SHADOW, comparar.
3. **Re-correr backtest 2022-2025 con calibración aplicada** (D.3 acotado) para
   tener N suficiente para promoción.
4. **Investigar V15** para liga regular (bias LOCAL no se resuelve con V14 v2/v3
   que está scoped a copas).

## Referencias

- Bead `adepor-9uq` — M.2 régimen 2026 (track invertido)
- `docs/state/2026-05.md` — estado del proyecto
- `Reglas_IA.txt` §M (M.2 spec)
