# Filtros estratégicos pendientes — para sesión de yield/apuestas (no motor xG)

## ⚡ Update 2026-05-04: Anti-filtro F4b SHADOW runtime activo + motor xG v3

**Anti-filtro F4b (shotmap-derived)** activado en pipeline FASE 7.5:
- Trigger: `ema_sp_dep_v > 0.5` (visita set-piece dependent) → NO apostar X
- Modo SHADOW: loggea sin afectar producción. Tabla `picks_shadow_antifiltro_f4b_runtime`.
- Validación N=58: yield -21.3% (NEGATIVO confirma señal), hit empate 24.1% vs ~28-30% baseline.
- **Heterogéneo per-liga**:
  - WHITELIST sugerida: BRA/ECU/ESP/PER/URU/VEN (yield -50% a -100%)
  - BLACKLIST: Italia, Inglaterra, Turquía (filtro INVIERTE, yield positivo)
- Activación futura: tras N≥80 SHADOW + walk-forward inter-año post backfill SOFA histórico.

**Motor xG v3 OPERATIVO** (bead `adepor-173`):
- xgot SOFA + LogReg custom fallback. RMSE descriptor -16% vs V_custom puro.
- 9 ligas mainstream con xgot 100%. 5 LATAM exóticas xgot 0% → fallback custom.
- EMAs V3 reconstruidas (322 equipos), pipeline auto-rebuild diario.

Ver `docs/papers/motor_xg_v3_estado_consolidado.md` para detalle.

---


**Fecha:** 2026-05-03
**Sesión origen:** `2026-05-03_motor_xg_v2`
**Trigger:** durante reconstrucción motor xG v2, varios hallazgos NO mejoran RMSE pero SÍ podrían ser **filtros estratégicos** (capa de selección de picks). Persistir para evaluar en sesión separada de yield.

**Importante:** todos estos hallazgos requieren validación walk-forward + Bonferroni antes de promoción a producción. Lista provisional, no decisiones.

---

## A) Patrones de POSICIÓN DE TABLA (Fase 9 motor xG v2)

Datos: `posiciones_tabla_snapshot` (32,394 snapshots, 16 ligas).

### Hallazgo central

| bin posición | es_local | avg goles | avg SOT | n |
|---|---|---|---|---|
| **top 20%** local | 1 | **1.81** | 3.96 | 979 |
| top 20% visita | 0 | 1.29 | 2.85 | 879 |
| mid (40-60%) local | 1 | 1.45 | 3.09 | 1,815 |
| mid visita | 0 | 1.09 | 2.43 | 1,791 |
| bot 20% local | 1 | 1.28 | 2.85 | 2,533 |
| **bot 20% visita** | 0 | **0.97** | 2.29 | 2,659 |

**Diferencias:**
- top20% local vs bot20% local: **+0.53 goles** (1.81 vs 1.28)
- top20% visita vs bot20% visita: +0.32 goles (1.29 vs 0.97)

### Ideas de filtros estratégicos

1. **Filtro "top home dominante"**: apostar over_2.5 cuando local está top 20% AND visita está bot 50%
2. **Filtro "anti-bot away"**: NO apostar over en partidos donde visita es bot 20% (mete <1 gol promedio)
3. **Filtro "mismatch posicional"**: cuando dif_pos > 8 (rango), value en favorito local
4. **Anti-filtro "mid vs mid"**: descartar picks donde ambos equipos están mid 40-60% (varianza alta, mercado eficiente)

### Por qué NO sirvió en motor xG
- Modelo SOT EMA forward-strict YA captura calidad del equipo implícitamente.
- Multicolinealidad: NNLS shrinka pos_propia a 0 cuando hay SOT.
- Posición tabla y EMA xG están correlacionadas.

### Por qué SÍ podría servir en yield
- El **mercado** puede miscalificar la magnitud del mismatch posicional, especialmente en LATAM o cuando equipo top tiene racha mala reciente.
- Filtro categorial discreto (top/mid/bot) es interpretable y robusto a outliers.

---

## B) Bias estructural por liga (Audit Fase 8)

Ligas donde el modelo **subestima** sistemáticamente goles:

| Liga | mean residuo | Hipótesis |
|---|---|---|
| Bolivia | +0.225 | Defensas débiles + porteros amateurs → conversión SOT→gol mayor |
| Noruega | +0.222 | Eliteserien con xG inflated por Bodø/Glimt + Molde |
| Perú | +0.213 | Stats incompletas + ofensivas más permisivas |
| Venezuela | +0.206 | Liga marginal, cuotas posiblemente desfasadas |
| Ecuador | +0.202 | Idem |
| Turquía | +0.182 | Régimen volátil documentado en Layer 3 X-rescue |
| Uruguay | +0.150 | Liga corta, varianza alta |

### Filtros estratégicos derivados

1. **Filtro over_2.5 LATAM no-mainstream**: en Bolivia/Perú/Venezuela/Ecuador/Uruguay, P(over_2.5) modelo está subestimado → mercado puede dar value sistemático
2. **Filtro divergencia liga-específico**: en estas ligas, divergencia P_modelo vs P_implícita_mercado puede tener sesgo → value en pick=visita cuando modelo dice empate (por bias subestima)
3. **Hipótesis a testear**: ¿el bookie también subestima en LATAM exóticas (cuotas no eficientes)? Entonces value puede compounding.

---

## C) Equipos con bias persistente (Audit Fase 8)

### Sub-estimados (modelo predice MENOS goles de los que meten)

| Equipo | Liga | n | bias |
|---|---|---|---|
| Defensor Sporting | Uruguay | 41 | +0.518 |
| Alianza Lima | Perú | 50 | +0.496 |
| Sporting Cristal | Perú | 50 | +0.489 |
| **Bodø/Glimt** | Noruega | 85 | **+0.478** |
| Melgar | Perú | 50 | +0.451 |
| **Molde** | Noruega | 88 | **+0.393** |
| Nacional | Uruguay | 42 | +0.392 |
| Universidad Católica (Quito) | Ecuador | 43 | +0.391 |
| **Galatasaray** | Turquía | 109 | **+0.389** |
| Peñarol | Uruguay | 43 | +0.379 |
| Independiente del Valle | Ecuador | 44 | +0.359 |
| Nacional Potosí | Bolivia | 63 | +0.348 |
| Bolívar | Bolivia | 66 | +0.325 |

### Sobre-estimados (modelo predice MÁS goles)

| Equipo | Liga | n | bias |
|---|---|---|---|
| Montpellier | Francia | 101 | -0.232 |
| Troyes | Francia | 33 | -0.258 |
| FC Cologne | Alemania | 64 | -0.293 |

### Filtros estratégicos derivados

1. **Whitelist sub-estimados (over)**: posibles value picks en over_2.5 cuando juega Bodø/Glimt, Galatasaray, Independiente del Valle, Bolívar. **Caveat**: en walk-forward, la corrección equipo-específica falla (planteles cambian) — el bias es **aprendizaje histórico**, no garantía futura.
2. **Blacklist sobre-estimados (under)**: Montpellier, Troyes, FC Cologne podrían dar value en under_2.5.
3. **Combinar con filtro Inglaterra/España validados**: estos equipos no aparecen en filtros yield validados — son hallazgos nuevos.

### Caveat
- Test walk-forward: corrección equipo-específica entrenada con 2022-2025 NO transfiere a 2026 (RMSE +0.0077).
- Esto significa que el bias por equipo **drift-a** con el tiempo — los planteles cambian.
- Solución: re-validar con N reciente (último año 2025-2026), ventana móvil 30 partidos.

---

## D) Cuotas pre-match como predictor (Fase 7B)

- Correlación P_implícita vs goles: **+0.367** (más alto que SOT 0.30)
- Modelo PURE p_diff (solo cuotas, sin SOT) → RMSE OOS pool 1.1758 sobre subset N=8,892

### Filtros estratégicos derivados

1. **Anchor a mercado per-bucket EV** (Kuypers 2000): `P_pick = α·P_modelo + (1-α)·P_implícita_mercado` con α calibrado por bucket EV. Usar cuando modelo y mercado divergen, anchor reduce overconfidence.
2. **Detector "modelo vs mercado contradice"**: cuando P_modelo y P_implícita disagree fuerte (div > 0.20), bandera para review manual o filtro de exclusión.

---

## E) Drift temporal cross-año (Audit Fase 8)

Patrones detectados:

```
Turquía:  2022:+0.331 → 2023:+0.244 → 2024:+0.168 → 2025:+0.049 → 2026:-0.073
Noruega:  2022:+0.365 → 2023:+0.231 → 2024:+0.105
Francia:  2022:-0.182 → 2023:-0.092 → 2024:+0.077 → 2025:+0.060
Inglaterra:2022:+0.110 → 2023:+0.109 → 2024:+0.043 → 2025:-0.016 → 2026:-0.081
```

### Filtros estratégicos

1. **Filtro temporal "régimen volátil"**: en ligas con drift > 0.20 año a año, filtrar picks fuera de bin estable (mid temporada).
2. **Detector cambio de régimen**: cuando bias pasa de positivo a negativo o viceversa → señal de cambio estructural (ej. Inglaterra 2024→2025 cambio +0.04 → -0.02).

---

## F) Filtros NEGATIVOS estructurales (ya conocidos)

Confirmados en sesiones previas (`audit_xg_v5_evolucion.md`):

| Excluir | N | Yield | CI95% |
|---|---|---|---|
| `gap_l ≥ 14 días` (post-FIFA) | 906 | -13.65% | sig NEG |
| `DOW = Lunes` | 376 | -14.60% | sig NEG |
| `Mes 10 / Mes 11` | 911 | -10 a -12% | sig NEG |
| `hora kickoff < 14` | 2,167 | -6.99% | sig NEG |

Combinado anti-Lunes + anti-gap14 → lift +2.8pp sobre baseline V0.

---

## G) Patrones temporales LATAM Apertura/Clausura

(Ya conocidos, persistir junto):

| Liga | Bin | N | Yield V0 | Hipótesis |
|---|---|---|---|---|
| Argentina | Q1 (inicio Apertura) | 8-16 | +46% a +118% | Mercado caliente al inicio |
| Argentina | Q2 (mid Apertura) | 8-9 | +104% a +130% | Momentum acumulado mal-priced |
| Argentina | Q3 | 10-14 | -76% a -100% | Régimen distinto (calor, vacaciones?) |
| Argentina | Q4 | 7-10 | -10% a -64% | Cierre semestre |

---

## H) Equipos top yield (sostenibles cross-año)

(Ya conocidos):

| Liga | Equipo | n | Yield |
|---|---|---|---|
| **España** | **Atlético Madrid** | 11 | **+59%** |
| **Inglaterra** | **Aston Villa** | 19 | **+53%** |
| **Inglaterra** | **Newcastle United** | 23 | **+32%** |
| Brasil | Grêmio | 13 | +44% |
| Italia | Como | 9 | +42% |
| España | Real Madrid | 6 | +31% |

**Caveat**: walk-forward TRUE-OOS RECHAZÓ whitelist universal (one-shot retrospectivo). Usar como hipótesis a re-validar con N grande.

### Bottom (NO apostar):

| Liga | Equipo | n | hit% | Yield |
|---|---|---|---|---|
| Alemania | SC Freiburg | 14 | 0% | -100% |
| Inglaterra | Luton Town | 5 | 0% | -100% |
| España | Cádiz | 5 | 0% | -100% |
| Francia | Montpellier | 23 | 9% | -75% |
| Italia | Udinese | 9 | 11% | -74% |

---

## I) Stats ganadores vs perdedores (cross-liga consistente)

En TODAS las 8 ligas (post EV>=1.03):
- `sot_l_w > sot_l_l` (Δ +0.10 a +0.97) → ataque local marca
- `sot_v_w < sot_v_l` (Δ -0.18 a -0.77) → defensa visita marca
- `res_h_w > res_h_l` → residuo histórico positivo del local

3 patrones structurales consistentes. Confirma intuición. **Filtro candidato**: pick = local cuando `sot_l_lag3 > sot_v_lag3 + threshold`.

---

## J) Estrategia diferenciada TOP vs NO_TOP (Plan F.1)

| Cat | Modelo top yield | Yield IS |
|---|---|---|
| TOP_EU (ENG/ESP/ITA/FRA/ALE) | V_anc05 (anchor mercado 0.5) | +25.76% N=40 |
| NO_TOP (TUR/NOR/ARG/BRA/Chile/etc) | V_dual (descalibrado) | +20.96% N=55 |

**Filtro estratégico**: aplicar V_anc05 solo en TOP_EU, V_dual solo en NO_TOP. Mixture of Experts gateado por liga.

---

## K) Filtros validados sólidos (sesión 2026-05-02 team)

(Ya en `filtros_validados_para_evaluar_post_motor_v2.md`):

### Inglaterra ★★ — VALIDADO Schema A + B
```
P_top >= 0.50 AND divergencia >= 0.20 AND cuota_pick >= 2.0
→ Schema A yield IS pool +42.82% N=45
```

### España ★ — VALIDADO Schema A + B
```
P_top >= 0.45 AND divergencia >= 0.15 AND cuota_pick ∈ [2.0, 4.0]
→ Schema A yield IS pool +9.90% N=80
```

---

## Plan para próxima sesión yield/filtros

1. **Re-correr filtros validados (ENG/ESP) con motor xG v2** (Bayesian hierarchical). ¿Mantienen yield?
2. **Probar filtros derivados de A) posición tabla**:
   - Top home dominante vs bot away (bin × bin)
   - Mismatch posicional dif_pos > 8
3. **Test whitelist equipos sub-estimados (B+C)** sobre 2025-2026 con re-validación walk-forward.
4. **Anchor a mercado per-bucket EV** (D) con calibración por bucket.
5. **Mixture of Experts (J)**: V_anc05 TOP_EU + V_dual NO_TOP en producción SHADOW.
6. **Re-validar filtros NEGATIVOS (F)** post-motor xG v2.
7. **Bonferroni α = 0.05/n_filtros** obligatorio si se prueban múltiples.
8. **N≥30 por filtro mínimo + bootstrap CI95% percentile 5 > 0**.

---

## Referencias

- `docs/papers/audit_xg_v5_evolucion.md` — investigación previa (Plan A-F)
- `docs/papers/filtros_validados_para_evaluar_post_motor_v2.md` — filtros validados ENG/ESP
- `docs/papers/patrones_validados_para_evaluar_post_motor_v2.md` — 10 patrones identificados
- `docs/papers/audit_bias_xg_v2.md` — audit bias goles vs xG (sesión actual)
- `docs/papers/research_fuentes_features_premarch.md` — research fuentes (sesión actual)
- `analisis/motor_xg_v2_10_posicion_tabla.{py,json}` — descriptivo posición tabla
- `analisis/motor_xg_v2_08_audit_bias.{py,json}` — audit bias completo
- `analisis/motor_xg_v2_09_correccion_bias_liga.{py,json}` — test corrección walk-forward
- `analisis/motor_xg_v2_07_cuotas_premarket.{py,json}` — cuotas pre-match feature
