# Angulos Creativos NO Probados - Universo Expandido N=8892

**Fecha:** 2026-05-02
**Sesion:** 2026-05-02_team_filtros_oro
**Agente:** investigador_xg
**Status:** completed
**Universo apostable:** 4339 partidos (N=8892 INTERSECT predicciones_walkforward V0)
**Ligas:** Alemania, Argentina, Brasil, Espana, Francia, Inglaterra, Italia, Turquia
**Anos:** 2022-2025

## Mision

Explorar 6 grupos de angulos NO probados sobre universo expandido N=8892 cuotas matched.
Identificar 3-5 angulos con yield positivo sostenible cross-ano + bootstrap CI95.
Restriccion: SOLO features pre-bet (cuotas, calendario, racha derivada).

## Universo + JOIN clave



Convencion temp: stats.temp es ano-inicio, fdco.temp es ano-fin (shift +1) para EUR.
## BASELINE

Apostar V0_argmax (Poisson DC walk-forward) sobre 4339 partidos:

| Metrica | Valor |
|---|---|
| N | 4339 |
| yield | -3.72% |
| CI95 boot | [-7.18%, -0.21%] sig NEG |
| hit rate | 46.32% |
| anos pos | 0/4 |

**Diagnostico:** baseline V0_argmax sangra dinero contra cuotas reales.
CI superior < 0 (sig NEG). Confirma input mision.

## TOP 5 angulos por yield bruto (N>=80)

| # | Angulo | side | N | yield | CI95_lo | CI95_hi | yrs+ |
|---|---|---|---:|---:|---:|---:|---:|
| 1 | 2C anti-hype local fade (ola5_l>=4 -> apostar visita) | 2 | 210 | +18.16% | -17.78% | +56.71% | 3/4 |
| 2 | 5E dog aligned (c2[4,7] + ola5_v>=2 -> 2) | 2 | 201 | +8.98% | -20.49% | +38.13% | 4/4 |
| 3 | 1B mes 6 (Junio fin temp ARG/BRA) | argmax | 297 | +6.97% | -8.87% | +22.42% | 3/4 |
| 4 | 1B mes 2 (Febrero) | argmax | 294 | +6.80% | -5.53% | +21.55% | 2/3 |
| 5 | 1D diff_gap V+2_4 -> 1 | 1 | 362 | +5.89% | -5.62% | +18.46% | 2/4 |

**Importante:** ningun angulo tiene CI95_lo > 0. N pequeno (80-300) + alta varianza.
Necesita drill por liga.
## DRILL TOP 1: anti-hype local fade

| Liga | N | yield |
|---|---:|---:|
| Brasil | 49 | +14.57% |
| Turquia | 40 | -9.20% |
| Italia | 37 | +48.14% |
| Argentina | 33 | +56.88% |
| Espana | 25 | -26.40% |
| Francia | 19 | +11.53% |

Por ano: 2022 +75.6% / 2023 +22.4% / 2024 +1.3% / 2025 -33.2%.
**Veredicto:** alta varianza por celda. ARG 2023=-100% (9 obs), 2024=+136% (12 obs).
NO sostenible sin filtro de liga. Yield 2025 negativo sugiere decay del edge.

## DRILL TOP 2: dog visita aligned

| Liga | N | hit | yield |
|---|---:|---:|---:|
| Brasil | 71 | 25.4% | +30.28% |
| Argentina | 62 | 8.1% | -61.00% |
| Italia | 23 | 39.1% | +107.13% |
| Francia | 17 | 23.5% | +14.06% |
| Inglaterra | 10 | 10.0% | -36.80% |
| Turquia | 9 | 22.2% | +5.00% |
| Espana | 7 | 42.9% | +101.14% |

**Veredicto:** Argentina destruye yield (-61%, hit 8%). Restringido a Brasil+Italia+Francia,
queda N~111 con yield agregado positivo.
Hipotesis: torneo Apertura/Clausura ARG cambia regimen visitante (LATAM regresa rapido al promedio).
## FILTROS NEGATIVOS confirmados (sig NEG, excluir)

| Filtro NEG | N | yield | CI95 | yrs+ |
|---|---:|---:|---|---:|
| gap_l >= 14 (post-FIFA o reanudacion) | 906 | -13.65% | [-20.41%, -6.71%] *** | 0/4 |
| DOW = Lunes | 376 | -14.60% | [-25.13%, -2.91%] *** | 1/4 |
| Mes 10 (Octubre) | 529 | -10.58% | [-19.71%, -1.38%] *** | 0/4 |
| Mes 11 (Noviembre) | 382 | -12.49% | [-23.74%, -0.85%] *** | 1/3 |
| diff_gap L+2_4 (local +2/4 dias mas descanso) | 374 | -15.87% | [-27.08%, -2.94%] *** | 2/4 |
| hora < 14 (kickoffs tempranos) | 2167 | -6.99% | [-11.36%, -2.17%] *** | 0/4 |
| OR <= 1.04 (mercado eficiente) | 3820 | -4.24% | [-7.78%, -0.67%] *** | 0/4 |

Notacion *** = CI95_hi < 0 (significativamente negativo al 95%).

**Combinado anti-Lun + anti-gap_l>=14:**

| Subset | N | yield |
|---|---:|---:|
| KEEP (no Lun y no gap>=14) | 1672 | -0.92% |
| EXCLUYE (Lun OR gap>=14) | 2667 | -5.47% |
| Lift | - | +4.55pp |
| KEEP CI95 | - | [-6.48%, +4.75%] |

Yield KEEP NO distinguible de cero. Mejora baseline -3.72% -> -0.92%.
Genera break-even pero NO edge positivo significativo.
## TOP 5 propuestos para SHADOW (con regla)

Ningun angulo aprobaria criterio Adepor (yield+5%, CI_lo>0, yrs>=2/3).
Pero los 5 mejores candidatos drill-validados:

### A1. ARG_Mes6 - Junio fin Apertura/torneo (LATAM)



Universo apostable V0: N=101. yield +31.15%.
yrs+ 2/3: 2023 +44.09%, 2024 +59.00%, 2022 -17.50%.
Universo expandido sin V0 (mkt_argmax): N=143, yield +2.64% (edge requiere V0).

### A2. Dog_visita_aligned (Brasil + Italia + Francia, sin Argentina)



Universo apostable: N~111. yields BRA+30.3% / ITA+107.1% / FRA+14.1%.
CI95 amplio por N pequeno por celda. Acumular hasta N>=200 antes de promover.

### A3. NEG_excluir_Lun_y_gap14 (filtro NEGATIVO universal)



Universo post-filtro: N=1672. yield mejora -3.72% -> -0.92% (lift +2.8pp).
NO suficiente para apostar puro. Combinable con filtro positivo.

### A4. Heavy_fav_local_c1<=1.50_finde



Apostar todos los heavy favoritos finde es break-even (-1.09%).
Combinable con divergencia V0_alta vs mkt para edge potencial.

### A5. Mes_2 EUR (FRA + TUR + ESP)



Drill Mes 2 por liga: FRA +20.81% / TUR +26.10% / ESP +24.15%.
ITA -16.28% / ENG -8.64% (excluir). yrs+ 2/3.

## VEREDICTO FINAL

1. NINGUN angulo individual genera CI_lo > 0 sobre N=4339 universo apostable V0.
2. Los TOP 5 son hipotesis a validar en SHADOW con N>=200 antes de produccion.
3. Filtros NEGATIVOS son MAS robustos que positivos: lift +2.8pp confiable.
4. Heterogeneidad cross-liga es ENORME: angulos POSITIVOS en BRA/ITA destruyen en ARG/ENG.
   Generalizacion universal = ruido.
5. Recomendacion: regla disjuncta combinando A3 (filtro NEG universal) +
   A1 (ARG Mes6 V0) + A2 (dog visita aligned BRA/ITA/FRA).

## Limitaciones

- LATAM 8 ligas (Bolivia, Chile, Colombia, Ecuador, Noruega, Peru, Uruguay, Venezuela)
  sin cuotas fdco -> N=4538 partidos NO apostables, NO analizados.
- V_dual / V_ruido NO logueados como predicciones persistidas; solo V0 walkforward.
- Hora del partido limitada al subset con fecha ISO con T.
- Bootstrap supone independencia, no controla por liga/equipo (varianza inflada).

## Reproducibilidad

- Script: analisis/angulos_creativos_universo_expandido.py
- JSON: analisis/angulos_creativos_universo_expandido.json
- Universo: 4339 partidos (8892 fdco INTERSECT predicciones_walkforward V0)
- Bootstrap: B=1500-2000 con seed 42, percentil 2.5/97.5
- Re-ejecucion: py analisis/angulos_creativos_universo_expandido.py