# Findings — n_acum drift y unificación de filtros operativos

> Bead: `adepor-0ac` (claimed 2026-04-27, autor Mateo Peralta)
> Triangulación: OOS Pinnacle 2022-24 (N=4.584) + in-sample real 2026-03/04 (N=266)
> Output: `analisis/n_acum_drift_investigacion.json` + `analisis/n_acum_triangulacion_real.json`

## Resumen ejecutivo

El hallazgo Fase 4 "yield decae −47pp con EMA madura" es **REAL**, **INDEPENDIENTE
del momento de temporada**, y **REPLICA en datos in-sample reales** (con menor
magnitud). Combinado con el filtro liga `adepor-ptk` (TOP-5), produce la mejor
política de filtrado observada hasta hoy: **yield real +68.0% CI95 [+23.3, +100.5]**
sobre N=44 picks vs +15.0% baseline.

## Hipótesis evaluadas

| Hipótesis | Veredicto |
|---|---|
| H1: n_acum es proxy de momento_temp | **PARCIAL**. Pearson r=+0.207, Spearman ρ=+0.210 (p≈0). Correlación significativa pero baja. No es proxy. |
| H2: n_acum es proxy de overfit Pinnacle a equipos conocidos | **PLAUSIBLE**. El efecto se mantiene en todos los momentos del año (T1 fila ≥60). Patrón también en visita (T7). |
| H3: Combinación de efectos independientes | **CONFIRMADA**. Ambos efectos coexisten y son aditivos. |

## Evidencia clave

### T1 — Matriz n_acum × momento (OOS Pinnacle, yield% por celda)

| n_acum_l | Q1_arr | Q2_ini | Q3_mit | Q4_cie |
|---|---|---|---|---|
| <10 | −50.0 (N=17) | +61.6 (N=50) | — | — |
| 10-29 | −15.6 (N=27) | +5.4 (N=73) | +16.9 (N=149) | +3.3 (N=95) |
| 30-59 | +6.9 (N=120) | +16.0 (N=134) | +18.1 (N=91) | −20.3 (N=135) |
| **≥60** | **−31.9 (N=59)** | **−6.0 (N=88)** | **+3.8 (N=124)** | **−22.3 (N=207)** |

Bucket ≥60 daña en 3 de 4 momentos → efecto NO depende solo de Q4.
Q4 daña en buckets 30-59 (−20.3%) y ≥60 (−22.3%) → efecto NO depende solo de n_acum.

### T2 — Heterogeneidad por liga (yield ≥60 vs <30, OOS)

| Liga | <30 | ≥60 | Δ |
|---|---|---|---|
| Argentina | +47% / +8% | −1.6% | leve |
| Brasil | +12% / +9% | −15.5% | −24pp |
| España | +25% | −44.7% | −70pp ★ |
| Italia | +60% / −11% | −20.1% | −40pp |
| Inglaterra | −40% | −11.8% | bandeja |
| Turquía | +148% / +37% | sin dato | — |

España e Italia colapsan en EMA madura. Argentina aguanta. Esto refuerza la
necesidad del filtro liga TOP-5 (`adepor-ptk`).

### TR3 — Filtros sobre picks reales 2026-03/04 (N=266 enriquecidos, stake real $)

| Filtro | N | Hit% | Stake$ | P/L $ | Yield% | CI95 |
|---|---|---|---|---|---|---|
| BASELINE | 166 | 49.4 | $9.67M | +$1.45M | +15.0 | [−7.7, +40.1] |
| Excluir n_acum≥60 | 74 | 55.4 | $4.09M | +$1.46M | +35.8 | [+0.7, +71.9] ★ |
| Excluir Q4 | 101 | 53.5 | $4.15M | +$1.21M | +29.1 | [−2.4, +60.1] |
| Excluir (n_acum≥60 OR Q4) | 45 | 62.2 | $1.76M | +$1.03M | +58.8 | [+11.1, +100.5] ★★ |
| TOP-5 solo | 119 | 54.6 | $5.46M | +$2.22M | +40.6 | [+10.2, +71.5] ★ |
| **TOP-5 + filtro doble** | **44** | **63.6** | **$1.66M** | **+$1.13M** | **+68.0** | **[+23.3, +100.5]** ★★★ |

## Convergencia OOS vs in-sample real

El patrón monotónico se sostiene **direccionalmente** en ambos samples:

| Métrica | OOS Pinnacle 2022-24 | Real 2026-03/04 |
|---|---|---|
| Yield baseline | +0.3% | +15.0% |
| Yield filtro doble | +14.1% ★ | +58.8% ★★ |
| Yield TOP-5 + doble | +17.4% ★★ | +68.0% ★★★ |
| Δ baseline → unificado | +17.1pp | +53pp |

Magnitud diferente: in-sample real es 6 semanas con cuotas internas (Pinnacle
no necesariamente), OOS es 3 temporadas Pinnacle closing. Pero el **signo
y la jerarquía de filtros es idéntica**.

## Limitaciones

1. **Cobertura `historial_equipos_stats`**: 12 ligas. Bolivia/Ecuador/Uruguay/
   Paraguay no scrapeadas. 92/358 picks reales no triangulables. Dado que esas
   ligas no están en TOP-5, no afecta la propuesta de filtro unificado pero
   sí limita su universalidad.

2. **N <10 OOS Q1/Q2**: solo 67 picks apostados. Muestra chica para conclusión
   firme sobre EMA muy joven (<10 partidos).

3. **Riesgo data-snooping**: el filtro doble se eligió retrospectivamente sobre
   los datos. Validación definitiva requiere out-of-sample futuro (>=N=200
   picks post-aprobación).

4. **N=44 in-sample triangulable + TOP-5 + filtro doble**: bajo. CI95 amplio
   [+23.3, +100.5]. Sostener este yield requiere monitoreo continuo.

## Implicación operativa

Las dos PROPOSALs en cola (`adepor-edk` Layer 1 OOS-only, `adepor-ptk`
in-sample-only) deben **unificarse** en una sola política con tres capas:

1. **Filtro liga**: `liga ∈ {Argentina, Brasil, Inglaterra, Noruega, Turquía}`
2. **Filtro madurez EMA**: `n_acum_l < 60`
3. **Filtro momento temporada**: `momento_bin_4 != 3` (excluir Q4 cierre)

Implementación: nueva clave config `filtro_picks_v51 = '{liga: top5, n_acum_max: 60, excluir_q4: true}'`.
Modificación en `motor_calculadora.py::evaluar_pick`.

## Próximos pasos

- [x] Triangulación OOS + real
- [x] Documentar findings (este archivo)
- [ ] Anotar adepor-0ac con findings + cerrar
- [ ] Anotar adepor-ptk con extensión filtros n_acum + momento (PROPOSAL super-conjunta)
- [ ] Esperar autorización Lead/usuario para unificación
- [ ] Si aprobada: implementar filtro triple en motor_calculadora.py + bump V5.0 → V5.1
- [ ] Calibración mensual de los 3 filtros (`adepor-j4e`)
