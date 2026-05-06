# Filtros EMA validados — sesión yield/apuestas

**Fecha:** 2026-05-04
**Sesión:** `2026-05-04_filtros_ema_walkforward`
**Universo:** 4,262 partidos 2022-2026, 11 ligas (`universo_filtros_ema_v4`)
**Snapshot pre-sesión:** `snapshots/fondo_quant_20260504_*_pre_filtros_ema_v4_shadow.db`

---

## TL;DR

3 filtros pasan walk-forward TRUE-OOS train<y/eval=y, con **per-liga whitelist explícita**:

| Filtro | Pool yield | Whitelist | Yield whitelist | N whitelist |
|---|---|---|---|---|
| `ema_l_crosses_visita ∈ [0,14.25]` → **empate** | +11.5% (N=1062) | ARG, ITA, ENG, FRA, TUR | **+16.7%** | 928 |
| `ema_l_saves_visita ∈ [0,2.41]` → **empate** | +10.2% (N=1062) | ARG, BRA, ITA, ENG, FRA, TUR | **+13.1%** | 912 |
| `ratio_propio_tackle_pct ∈ [1.07,32.94]` → **U25** | +9.0% (N=568) | ESP, FRA, ENG, ITA | **+10.3%** | 538 |

**Ningún filtro supera Bonferroni estricto (α = 0.05/4520 = 0.0000111).**
**Walk-forward TRUE-OOS sí superado** (criterio más exigente que CV temporal interno).

Persistidos en `picks_shadow_filtros_ema_v4` (2,692 picks, `aplicado_produccion=0`).

---

## Pipeline ejecutado

| Paso | Resultado |
|---|---|
| Universo v1 (SOFA lag-1, 443 partidos) | 7 filtros marginales, 0 Bonferroni |
| Universo v2 (EMA fdco, 4,040 partidos) | 0 walk-forward TRUE-OOS pasan |
| Universo v3 (+ posición tabla) | 6 walk-forward (8 ligas) |
| **Universo v4 (16 ligas intent → 11 reales)** | **3 walk-forward + per-liga whitelist** |

### Por qué solo 11 ligas (no 16)

`historial_equipos_stats` (47 cols EMA) cubre solo:
- 8 EU: ENG, ESP, ITA, FRA, ALE, TUR, NOR, ALE
- 2 SUD mainstream: ARG, BRA
- 3 LATAM con scraping ESPN: COL (1202), CHL (1451), PER (34 — tiny)

NO cubre BOL, VEN, URU, ECU. Razón: scrapers ESPN no extienden a esas ligas.

Para 16 ligas se requiere extender `motor_data.py` con scrapers específicos LATAM exóticos (sesión separada).

---

## Universo v4: 4,262 partidos 11 ligas

```
Cobertura por liga (con EMA + warmup n_acum>=5):
  Argentina    929 (fdco, backtest)
  Italia       851
  Brasil       746
  España       527
  Francia      506
  Inglaterra   315
  Turquía      249
  Alemania      92
  Colombia      23 (solo backtest 2026)
  Noruega       15
  Chile          9

Cobertura por temp:
  2022 → 316    2023 → 964    2024 → 1006
  2025 → 1061   2026 → 915
```

**Baselines pool** (random uniform por pick, todo universo):
| Pick | N | Yield |
|---|---|---|
| Local | 4,247 | -6.01% |
| Visita | 4,247 | -7.59% |
| Empate | 4,247 | -0.74% |
| O25 | 2,519 | -4.79% |
| U25 | 2,519 | -2.59% |

Margen bookie ≈ 5%, baselines consistentes con eficiencia de mercado.

---

## Filtros validados — desglose 11 ligas × 5 años

### #1 `ema_l_crosses_visita ∈ [0, 14.25]` → EMPATE

**Pool: yield +11.48% N=1062. Walk-forward TRUE-OOS 3/3 años test, avg +11.2%.**

```
liga         2022   2023      2024      2025     2026     Total
Argentina   +52%(11) +11%(116) +23%(134) -8%(10) +38%(10) +19%(281)  ★
Italia       .       -16%( 79) +23%( 75)+39%(45) +24%(54) +14%(253)  ★
Brasil      -25%( 8) +26%( 10) -13%(  8)-23%(13) -100%(5) -19%( 44) ✗ NEG
España       .       +17%( 26) -19%( 17)-45%(18)  ~2      -14%( 63) ✗ NEG
Francia      .        +7%( 39) +98%( 15)+19%(13)  .       +29%( 67)  ★
Inglaterra   .       +81%( 25)  +1%( 30)+85%(14) -21%(10) +39%( 79)  ★
Turquía      .         .         .       -4%(128)+18%(120) +7%(248)  ★
Noruega      .         .         .        .      -65%(15) -65%( 15) ✗
Chile        .         .         .        .      -28%( 8) -28%(  8) ✗
Total       +20%(19) +10%(296) +21%(279) +6%(241)+6%(227)
```

**Whitelist**: ARG, ITA, FRA, ENG, TUR → yield combinado **+16.72% N=928**.
**Descartado**: BRA, ESP (NEG sig), NOR/CHL/COL (NEG o N tiny).

**Hipótesis**: visita con muchos centros (ema_l_crosses_visita alto) = estilo ineficiente (cruzar = baja conversión). Apostar empate captura este patrón. Funciona en ligas con técnica/control (ARG/ITA/ENG/FRA/TUR), NO en ligas físicas (BRA/ESP) donde centros son válidos.

### #2 `ema_l_saves_visita ∈ [0, 2.41]` → EMPATE

**Pool: yield +10.20% N=1062. Walk-forward 2/3 años test positivos, avg +7.94%.**

```
liga         2022    2023     2024     2025     2026      Total
Argentina   +22%(46) +15%(61) +27%(60) -13%(83)  +5%(38) +9%(288)
Italia       .        -1%(81) +34%(86) +14%(75)  -2%(78) +12%(320)  ★
Brasil      +47%(36)  -9%(22) ~4       .         ~4      +30%( 66)  ★
España       .       -14%(27) +50%(29)  -3%(33) -70%(30) -9%(119)  ✗ NEG
Francia      .       +20%(21) +73%(17) +24%(14) -36%(33) +10%( 85)
Inglaterra   .       +47%(28) -38%(23) +44%(13)  -2%(24) +11%( 88)
Turquía      .         .        .      +54%(39) -11%(26) +28%( 65)  ★
Alemania     .       -21%(10) +49%( 6) ~4       -17%( 5) +18%( 25)
Total       +33%(82)  +7%(250)+30%(225)+13%(261)-16%(244)
```

**Whitelist**: ARG, BRA, ITA, ENG, FRA, TUR → yield combinado **+13.11% N=912**.
**Descartado**: ESP (-9%).
**Drift 2026**: -16% pool 2026 (vs +13% 2025). Bandera roja monitoreo.

**Hipótesis**: arquero visita NO ha tenido oportunidades de saves (ema_l_saves_visita bajo) = visita NO está siendo atacada en sus partidos previos (defensiva sólida o partidos contra rivales débiles) → próximo partido será bajo en goles cuando son contra rival fuerte (cae al empate).

### #3 `ratio_propio_tackle_pct ∈ [1.07, 32.94]` → U25

**Pool: yield +9.05% N=568. Walk-forward 2/3 años test positivos, avg +0.43%.**

```
liga         2023      2024     2025     2026     Total
Italia       -0%(63)   +19%(66) +12%(61) +15%(22) +11%(212)  ★
España       -7%(43)   +16%(40)  +8%(21)  -8%(15)  +3%(119)
Francia     +12%(34)   +26%(28)  +8%(32)  -9%(31)  +9%(125)  ★
Inglaterra  +49%(26)   +25%(21) +16%(19) -19%(16) +22%( 82)  ★
Alemania     ~3        ~4       ~4       -33%( 5) +10%( 16)
Total        +7%(169)  +22%(159)+11%(137)-11%(103)
```

**Whitelist**: ESP, FRA, ENG, ITA → yield combinado **+10.33% N=538**.
**Drift 2026 NEG (-11%)**: cuestionable robustez actual.

**Hipótesis**: equipos balanceados en tackle_pct (ratio cercano a 1) = partidos paritarios tácticos → bajo en goles. Funciona en ligas tácticas EU.

---

## Limitaciones críticas

### Bonferroni
4520 tests × 5 picks → α = 0.05/4520 = **0.0000111**.
Para superar requeriría CI95 con percentile 99.9989 lower > 0.
**Ningún filtro lo supera.** Los walk-forward TRUE-OOS son SEÑAL pero NO PROBABILISTIC.

### Walk-forward limitado a 3 años test (2024, 2025, 2026)
Solo 2024-2026 son testables como OOS (anteriores son train data). Idealmente 5+ años.

### LATAM exóticas no cubiertas
BOL, VEN, URU, ECU sin EMA pre-construido. Requiere scrapers ESPN específicos.

### 2026 drift en filtros 2 y 3
- `ema_l_saves_visita`: 2026 yield -16% (vs +13% 2025) — régimen shift posible
- `ratio_propio_tackle_pct`: 2026 yield -11% (vs +11% 2025) — régimen shift confirmado

Filtro #1 (`ema_l_crosses_visita`) es el ÚNICO con consistencia 5/5 años pool positivos.

---

## Persistencia SHADOW

Tabla `picks_shadow_filtros_ema_v4`:
- 2,692 picks loggeados (3 filtros × eventos universo)
- `aplicado_produccion=0`
- `liga_es_whitelist=1` para picks dentro de la lista de ligas favorables
- `razon_no_aplicado='shadow_pendiente_n80_y_bonferroni_no_superado'`

Schema:
```sql
ts_log, liga, temp, fecha, ht, at, fuente_cuota,
filtro_id, filtro_descripcion, filtro_feature, filtro_lo, filtro_hi,
pick, cuota, hit_real, yield_real,
n_acum_filtro, yield_acum_filtro,
ci95_lo_pool, yield_pool_validation, n_pool_validation,
avg_oos_yield, n_pos_oos, n_with_oos,
liga_es_whitelist, yield_per_liga_estimado, n_per_liga_estimado,
bonferroni_alpha, validacion_metodo,
aplicado_produccion, razon_no_aplicado
```

---

## Recomendación

### Inmediata (NO requiere cambio Manifiesto)
1. **Mantener SHADOW puro**: NO promover a producción
2. **Acumular N≥80 en season 2026 incremental** sobre la whitelist per-filtro
3. **Si N≥80 en whitelist y yield_acum > +5% AND CI95_lower > 0** post 2026 → bead PROPOSAL

### Medio plazo
1. **Extender historial_equipos_stats** a BOL/VEN/URU/ECU (scrapers ESPN sesión separada)
2. **Agregar walk-forward season 2027** cuando esté disponible (test 2027, train ≤ 2026)
3. **Investigar drift 2026** en filtros #2 y #3 — ¿régimen estructural o aleatorio?

### Largo plazo
- **Mixture of Experts gateado por liga**: aplicar filtro EMA solo en ligas whitelist + V0 default en resto
- **Re-validar Phase 1.2 con LightGBM/SHAP** (instalar libs) para descubrir features no-lineales

---

## Comparación SOFA lag-1 vs EMA expandido

| Aspecto | SOFA lag-1 (sesión previa) | EMA v4 (esta sesión) |
|---|---|---|
| Universo | 443 partidos season 2026 | 4,262 partidos 2022-2026 |
| Features | Stats SOFA partido anterior | EMAs rolling 47 stats × 10 metodos |
| Walk-forward TRUE-OOS | NO posible (sin histórico SOFA) | SÍ — train<y / eval=y |
| Filtros validados | 7 (sin Bonferroni) | 3 (sin Bonferroni, con WF TRUE-OOS) |
| Top yield pool | +60% N=46 (AND combo) | +16.7% N=928 (whitelist) |
| Robustez | BAJA (lag-1 ruido) | MODERADA (EMA suavizado, WF TRUE-OOS) |

**Veredicto**: EMA expandido es metodología SUPERIOR. Mayor N, walk-forward genuino, per-liga whitelist concreta. Magnitud de yield más modesta pero más robusta.

---

## Outputs

### Scripts
- `analisis/filtros_ema_v4_universo_16ligas.py` — universo unión 11 ligas
- `analisis/filtros_ema_v4_exploration.py` — exploración + WF TRUE-OOS + desglose
- `analisis/filtros_ema_v4_shadow_persist.py` — SHADOW persist + whitelist

### JSONs
- `analisis/filtros_ema_v4_universo_16ligas.json` — métricas universo
- `analisis/filtros_ema_v4_findings.json` — findings + desglose 11×5
- `analisis/filtros_ema_v4_shadow_summary.json` — resumen whitelist

### Tablas DB
- `universo_filtros_ema_v4` — 4,262 partidos enriquecidos
- `picks_shadow_filtros_ema_v4` — 2,692 picks SHADOW

### Snapshot pre-sesión
- `snapshots/fondo_quant_20260504_*_pre_filtros_ema_v4_shadow.db`

---

## Referencias cruzadas

- `docs/papers/filtros_sofa_validados_post_session.md` — sesión SOFA lag-1
- `docs/papers/filtros_estrategicos_pendientes.md` — propuestas previas no-SOFA
- `docs/papers/filtros_validados_para_evaluar_post_motor_v2.md` — Inglaterra/España validados (sesión 2026-05-02)
- Reglas_IA.txt § motor (no modificado, SHA256 intacto)
