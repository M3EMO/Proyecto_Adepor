# Fase 3 — Análisis stats avanzadas (posesión + 27 stats ESPN)

> Snapshot 2026-04-27. Bead: `adepor-6kw` (Fase 3). N=9.387 partidos con stats
> completas (12 ligas × 3 temps), N=3.544 con cuotas Pinnacle para análisis yield.
> Re-correr: `py analisis/fase3_*.py && py analisis/graficar_fase3.py`

## Setup

Scraper ESPN extendido para capturar las 28 stats avanzadas por equipo:
posesión, pases, crosses, longballs, blocks, tackles, interceptions, clearance,
saves, fouls, yellow/red cards, offsides, penalty kicks, shot accuracy, etc.

| Cobertura ESPN | Posesión disponible |
|---|---:|
| Argentina, Brasil, Chile, Colombia | 100% × 3 temps |
| Inglaterra, España, Italia, Alemania, Francia | 100% × 3 temps |
| Turquía 2024 | 100% (2022-2023 sin pos) |
| Noruega 2024 | 56% (2022-2023 sin pos) |
| Bolivia, Ecuador, Perú, Uruguay, Venezuela | 0% (ESPN no provee) |

Total: 9.387 partidos × 56 stats por equipo. Limitación: LATAM secundarias y
algunas EUR temps tempranas no son cubiertas por ESPN para posesión.

## Hallazgo #1 — Correlación posesión × xG es global pero variable por liga

| Liga | N | Pearson(pos, xG) | OLS β | R² |
|---|---:|---:|---:|---:|
| **Inglaterra** | 1.140 | **+0.697** | +0.0601 | **0.486** |
| **Italia** | 1.140 | **+0.650** | +0.0551 | **0.423** |
| Brasil | 1.140 | +0.553 | +0.0541 | 0.305 |
| España | 1.134 | +0.541 | +0.0530 | 0.293 |
| Francia | 992 | +0.540 | +0.0531 | 0.292 |
| Alemania | 918 | +0.532 | +0.0605 | 0.283 |
| Colombia | 589 | +0.453 | +0.0480 | 0.206 |
| Argentina | 1.134 | +0.430 | +0.0401 | 0.185 |
| Noruega | 135 | +0.397 | +0.0450 | 0.157 |
| Turquia | 342 | +0.390 | +0.0531 | 0.152 |
| **Chile** | 719 | **+0.282** | +0.0324 | 0.080 |

**Premier y Serie A son las más estructuradas** (R² > 0.42): la posesión predice
fuerte el xG del partido. **Argentina y Chile son más caóticas** (R² < 0.20):
posesión y xG están menos correlacionados.

Drift por temp: 2022 R²=0.39, 2023 R²=0.26, 2024 R²=0.25 (declive ligero).

## Hallazgo #2 — Ranking de stats por correlación con xG (univariable)

**Tier componentes del proxy** (definen la fórmula xG):
| Stat | Pearson | R² |
|---|---:|---:|
| shots_total | +0.937 | 0.877 |
| shots_on_target | +0.922 | 0.851 |
| corners | +0.754 | 0.568 |

**Tier ortogonales — predictores reales no triviales:**
| Stat | Pearson | R² |
|---|---:|---:|
| posesion | +0.710 | 0.503 |
| crosses_total | +0.685 | 0.469 |
| longball_pct | +0.680 | 0.463 |
| pass_pct | +0.676 | 0.456 |
| pases_total | +0.661 | 0.437 |
| **blocks** | +0.635 | 0.403 |
| crosses_acertados | +0.651 | 0.424 |

**Tier moderado:**
| Stat | Pearson | R² |
|---|---:|---:|
| shot_pct | +0.561 | 0.315 |
| longballs_total | +0.501 | 0.251 |
| tackles | +0.440 | 0.194 |
| fouls | +0.385 | 0.148 |
| interceptions | +0.330 | 0.109 |

**Tier bajo:**
| Stat | Pearson | R² |
|---|---:|---:|
| offsides | +0.237 | 0.056 |
| yellow | +0.172 | 0.030 |
| saves | +0.151 | 0.023 |
| **red** | **−0.019** | 0.000 (sin señal univariable) |

## Hallazgo #3 — OLS multivariable EXCLUYENDO componentes del proxy: R²=0.67

17 stats (sin shots/sots/corners) explican **67% de la varianza de xG**. Top
features por importancia semi-standardized:

| Feature | Coef | Importancia | Signo |
|---|---:|---:|---|
| **blocks** | +0.170 | **0.260** | + (dominancia) |
| crosses_total | +0.037 | 0.239 | + |
| posesion | +0.014 | 0.178 | + |
| cross_pct | +1.905 | 0.174 | + |
| longball_pct | +1.100 | 0.129 | + |
| tackle_pct | +0.660 | 0.098 | + |
| pk_shots | +0.382 | 0.091 | + |
| **yellow** | **−0.085** | 0.082 | **−** disciplina afecta |
| longballs_total | −0.004 | 0.063 | − |
| **red** | **−0.264** | 0.054 | **−** roja saca xG real |
| interceptions | +0.015 | 0.049 | + |
| saves | −0.019 | 0.026 | − (saves → defendiendo) |

**Yellow y red sí discriminan en multivariable** (no en univariable). La señal
de las tarjetas se confunde con otras variables hasta que el modelo lineal las
aísla.

## Hallazgo #4 — Yield del motor × posesión local NO es monotónico

**N=3.544 OOS** (predicciones walk_forward × cuotas Pinnacle × stats ESPN):

| Pos local | NApost | Hit% | Yield% | CI95 | sig |
|---|---:|---:|---:|---:|---|
| muy_baja (<35%) | 186 | **43.5** | **+40.3** | [+16.6, +67.9] | **★ POS** |
| baja (35-45%) | 356 | **48.3** | **+36.9** | [+22.3, +52.5] | **★ POS** |
| media (45-55%) | 410 | 33.7 | −10.0 | [−22.6, +1.8] | no |
| **alta (55-65%)** | 208 | 20.2 | **−49.0** | [−62.2, **−35.6**] | **★ NEG** |
| **muy_alta (>65%)** | 45 | 15.6 | **−57.1** | [−86.2, **−25.6**] | **★ NEG** |

**Asimetría brutal y sostenida**:
- Apostar locales con posesión <45% → yield **+37/+40%** sig
- Apostar locales con posesión >55% → yield **−49/−57%** sig

### Drill-down por temporada (sostiene el patrón en las 3)

| Pos local | 2022 | 2023 | 2024 |
|---|---:|---:|---:|
| muy_baja | +30.2 | **+43.4** ★ | +45.4 |
| baja | **+45.2** ★ | **+38.3** ★ | **+31.0** ★ |
| media | +10.5 | −12.5 | −19.6 |
| **alta** | **−78.8** ★ | **−32.1** ★ | **−46.6** ★ |
| muy_alta | **−68.6** ★ | −39.2 | **−70.8** ★ |

**Los 3 años sostienen `alta` significativamente negativo y `baja` significativamente
positivo**. Esto es estructural cross-régimen, no artefacto de un año.

### Heatmap pos × octavos confirma la regla cross-temp

[`graficos/fase3_yield_x_pos_x_bin8.png`](../graficos/fase3_yield_x_pos_x_bin8.png):

- **Fila pos local 55-65% (alta)**: ROJO en O1-O8 (8/8 octavos negativos: −36, −58, −41, −31, −66, −75, −50, −48)
- **Fila pos local 35-45% (baja)**: VERDE en 7/8 octavos
- **Fila pos local <35% (muy_baja)**: 6/8 octavos verdes

**Yield local con posesión alta es categóricamente malo en cualquier altura
de temporada**. La señal NO se diluye en ningún cuartil.

## Hallazgo #5 — Yield asimetría por cada stat individual (Q1 vs Q5)

Ranking por |Q5 − Q1|:

**APOSTAR cuando local tiene stat ALTA (Q5 sig pos):**

| Stat | Yield Q1 | Yield Q5 | Q5−Q1 | sig Q5 |
|---|---:|---:|---:|---|
| **shot_pct** | −47.2 | **+85.5** | +133 | ★ POS |
| **shots_on_target** | −43.8 | **+70.7** | +115 | ★ POS |
| **clearance** | −26.7 | +43.2 | +70 | ★ POS |
| longballs_total | −24.7 | +26.2 | +51 | ★ POS |
| cross_pct | −3.1 | +35.0 | +38 | ★ POS |
| offsides | −7.9 | +30.4 | +38 | ★ POS |
| interceptions | −14.3 | +23.8 | +38 | ★ POS |
| tackles | −13.7 | +19.0 | +33 | ★ POS |
| fouls | −5.1 | +23.2 | +28 | ★ POS |

**EVITAR cuando local tiene stat ALTA (Q5 sig neg):**

| Stat | Yield Q1 | Yield Q5 | Q5−Q1 | sig Q5 |
|---|---:|---:|---:|---|
| **posesion** | +40.3 | **−57.1** | **−97** | ★ NEG |
| **crosses_total** | +34.3 | **−59.8** | **−94** | ★ NEG |
| **longball_pct** | +21.5 | **−56.3** | **−78** | ★ NEG |
| **pases_total** | +34.1 | **−39.2** | **−73** | ★ NEG |
| corners | +11.7 | −38.7 | −50 | ★ NEG |
| **red** | +8.9 | **−31.4** | −40 | ★ NEG |
| blocks | +15.5 | −22.1 | −38 | ★ NEG |

## Interpretación profunda

Hay **dos arquetipos** de equipos en términos del yield del motor:

### Arquetipo A — "Posesión estéril" (motor PIERDE apostando)
- Posesión alta (>55%)
- Pases totales altos (volumen)
- Crosses totales altos (centra mucho)
- Longball_pct alto (depende de balones largos)
- Corners (presión sin conversión)
- Tarjeta roja (queda con 10, sigue siendo "favorito" en odds pero no rinde)
- Blocks altos (proxy de dominancia que NO se materializa)

Estos son los **favoritos clásicos** que el motor identifica como "deberían
ganar" pero el outcome no acompaña: equipos posesivos que dominan en estadísticas
brutas pero no convierten ocasiones.

### Arquetipo B — "Conversión efectiva" (motor GANA apostando)
- Posesión baja (<45%)
- shots_on_target alto (los pocos remates van al arco)
- shot_pct alto (eficiencia)
- clearance alto (defensa activa)
- offsides altos (atacan línea + verticalidad)
- fouls altos (defensa agresiva, contragolpean)
- interceptions altos (recuperan + transición)
- tackles altos (entradas exitosas)

Son **contragolpeadores** y **equipos defensivos efectivos**. El motor
identifica edge real cuando apuesta a ellos. Su perfil es: "pocas pero buenas
ocasiones".

## Implicación operativa fuerte

Si pudiéramos predecir EMA pre-partido de stats por equipo, podríamos construir
un **score de apostabilidad**:

```
score = +shots_on_target_EMA  +shot_pct_EMA  +clearance_EMA
        +offsides_EMA  +fouls_EMA  +interceptions_EMA
        −posesion_EMA  −pases_total_EMA  −crosses_total_EMA
        −longball_pct_EMA  −corners_EMA
```

Si score alto → apostar local. Si score bajo → no apostar.

Esto requiere **Fase 4**: tabla `historial_equipos_stats` con EMA por equipo
+ integración al motor.

## Drill-down por liga (yield por bucket pos)

Cobertura yield x pos OOS por liga (subset de N=3.544):

| Liga | N apost | Yield% | pos_avg local |
|---|---:|---:|---:|
| Argentina | ~570 | sostiene patrón general | varia por equipo |
| Brasil | similar | sostiene | similar |
| Inglaterra | ~360 | el más extremo (alta=−79 sig) | + |
| España | ~340 | sostiene | similar |
| Italia | ~340 | sostiene | similar |
| Alemania | ~270 | sostiene | similar |
| Francia | ~290 | sostiene | similar |
| Turquía 2024 | ~100 | sostiene | similar |

El patrón no es liga-dependiente.

## Por equipo — top correlaciones individuales pos × xG

| Liga | Equipo | N | Pearson | R² | pos_avg | xG_avg |
|---|---|---:|---:|---:|---:|---:|
| Inglaterra | Leeds United | 38 | +0.877 | 0.769 | 32.6 | 1.92 |
| Italia | Lecce | 114 | **+0.869** | 0.755 | **18.5** | 1.14 |
| Italia | Cremonese | 38 | +0.789 | 0.623 | 39.1 | 2.50 |
| Inglaterra | Wolves | 114 | +0.756 | 0.571 | 41.5 | 2.35 |
| Inglaterra | Liverpool | 114 | +0.739 | 0.547 | 51.5 | 3.69 |

Lecce con pos_avg 18.5% y r=+0.87 — equipo con muy poca posesión pero **cuando
sube su % de balón, sube su xG monotónicamente**. Equipos donde la fórmula
"posesión → xG" funciona como reloj.

## Limitaciones

1. **Cobertura ESPN incompleta**: Bolivia, Ecuador, Perú, Uruguay, Venezuela
   sin posesión. Noruega 2022-23 sin posesión. Turquía 2022-23 sin posesión.
   Estas ligas no participan del análisis pos.

2. **xG_proxy usado**: 0.10*shots + 0.30*sots + 0.10*corners. Es la fórmula
   simplificada del Manifiesto §II.A. xG real (con calibración OLS) puede
   diferir. Para Fase 4 considerar usar xG_v6_shadow (recalibrado).

3. **Posesión es POST-MATCH**. Para usar pre-partido necesitamos EMA por
   equipo. Eso es Fase 4.

4. **Stats correlacionadas entre sí**: posesión + pases + crosses + blocks
   están correlacionados. La regresión multivariable absorbe esto pero el
   coef individual puede ser engañoso (multicolinealidad).

5. **OOS yield × pos N=3.544 cubre ~3 años**. Para validar como estructural
   sostenido conviene esperar 2025+ cuando haya cobertura.

## Archivos generados

| Tipo | Ubicación |
|---|---|
| Scraper | `analisis/fase3_scraper_posesion.py` (28 stats × 2 equipos) |
| Schema DB | `stats_partido_espn` (12.999 filas, 9.387 con pos) |
| Script | `analisis/fase3_analisis_posesion.py` (correlación pos x xG) |
| Script | `analisis/fase3_stats_completo.py` (todas las stats) |
| Script | `analisis/fase3_yield_por_stats.py` (Q1-Q5 cada stat) |
| Script | `analisis/fase3_yield_posesion_oos.py` (yield x pos x bin x temp) |
| Script | `analisis/graficar_fase3.py` |
| JSONs | `analisis/fase3_correlacion_pos_xg.json` |
| JSONs | `analisis/fase3_stats_correlaciones.json` |
| JSONs | `analisis/fase3_yield_por_stats.json` |
| JSONs | `analisis/fase3_yield_posesion_oos_bin{4,8,12}.json` |
| Plots | `graficos/fase3_correlacion_global.png` |
| Plots | `graficos/fase3_pos_buckets_outcome.png` |
| Plots | `graficos/fase3_yield_x_pos_x_bin{4,8,12}.png` |
| Plots | `graficos/fase3_yield_pos_por_temp_bin{4,8,12}.png` |
| Cache | `analisis/cache_espn/{liga}_{temp}.json` (48 archivos) |

## Próximos pasos sugeridos

### Fase 4 — Predictor pre-partido de stats

1. Tabla `historial_equipos_stats` con EMA por equipo de:
   - posesion, shots_on_target, shot_pct, clearance, fouls, etc.
2. Integración al motor para que pre-partido tenga estimación de stats
   esperadas
3. Backtest de filtro: "no apostar local si posesion_esperada > 55%"

### PROPOSAL formal candidato

`[PROPOSAL: MANIFESTO CHANGE] V5.x — filtro stat-based: evitar locales con
posesion_EMA > 55%`. Validar primero con backtest:
- Yield del motor sin filtro vs con filtro (paired bootstrap CI95)
- Si yield_filtrado > yield_actual con CI95_lo > 0 → APROBADO
- Si no → cuestionable, considerar versiones más estrictas

### Detector de régimen (adepor-09s)

Las features de Fase 3 son **inputs naturales** para el detector. El régimen
no es solo "tipo-2022/23/24" sino también caracterizable por la **distribución
de stats** en cada temp.
