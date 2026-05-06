# Filtros validados — para re-evaluar tras reconstruir motor xG

**Fecha de validación:** 2026-05-03
**Sesión:** `2026-05-02_team_filtros_oro` (universo expandido N=8,892, theta=0.15 óptimo)
**Trigger para re-evaluar:** después de reconstruir motor xG con RMSE → 1.0 (próxima sesión).

## Conceptos clave a probar tras nuevo motor xG

### Hipótesis arquitectural confirmada

1. **El edge contra cuotas NO viene de mejor descriptor xG global** — el mercado siempre será mejor predictor (Brier MKT 0.5881 vs V0 0.6240).
2. **El edge viene de DIVERGENCIA específica** entre P_modelo y P_implícita_mercado en zonas donde mercado yerra puntualmente.
3. **Per-liga es obligatorio** — generalizaciones cross-liga = ruido. Cada mercado tiene su propia eficiencia/régimen.
4. **Theta empírico óptimo = 0.15-0.20** (no 0.70). Validado IS 2026 + OOS pool 2022-2025. Motor productivo cambia: cascada (rho, gamma, factor_corr_xg_ou).

### Filtros validados (Schema A + Schema B con theta=0.15)

#### 🏴󠁧󠁢󠁥󠁮󠁧󠁿 Inglaterra — VALIDADO ★★

```
Regla: V0 pick=argmax(P), apostar SI:
  P_top >= 0.50
  AND divergencia(P_top - P_implícita_pick) >= 0.20
  AND cuota_pick >= 2.0
```

**Métricas validación (motor V0 actual con bug doble híbrido + theta=0.15):**
- Schema A (train all → eval per year): yield IS pool +42.82% N=45, 3/4 años positivos
- Schema B (LOYO): avg OOS +3.06%, 2/3 train years consistentes
- Por año: 2022 +55.81% N=16, 2023 +51.05% N=21, 2024 +9.40% N=5, 2025 -28.33% N=3 (tiny)

**Patrón:** alta convicción del modelo (P≥0.50) + asimetría fuerte vs mercado (div ≥ 0.20) + favorito moderado (cuota ≥ 2.0). Funciona porque la prima de cuota compensa la varianza.

**A re-evaluar tras motor v2:**
- ¿Sigue funcionando el threshold P≥0.50 si el motor mejora calibración?
- Si Brier modelo se acerca a mercado, ¿la divergencia ≥ 0.20 desaparece?
- Validar 2025-2026 con N≥30 (actual N=3 es tiny).

#### 🇪🇸 España — VALIDADO ★

```
Regla: V0 pick=argmax(P), apostar SI:
  P_top >= 0.45
  AND divergencia >= 0.15
  AND cuota_pick ∈ [2.0, 4.0]
```

**Métricas:**
- Schema A: yield IS pool +9.90% N=80, 3/4 años positivos
- Schema B: avg OOS +1.70%, 2/4 consistencia
- Por año: 2022 +49.08% N=12, 2023 +0.13% N=39, 2024 +30.32% N=19, 2025 -37.80% N=10

**Patrón:** mismo que Inglaterra pero con threshold P más bajo (0.45) + cuota acotada por arriba (≤4.0). 2025 colapsa fuerte → posible régimen shift España específico.

**A re-evaluar tras motor v2:**
- ¿Es 2025 outlier persistente o se corrige con mejor xG?
- Validar el cap superior de cuota (¿es necesario o ruido sample?).

### Filtros RECHAZADOS por LOYO (no transfieren OOS)

| Liga | A yield | B avg OOS | Razón |
|---|---|---|---|
| Argentina | +20.78% | -17.37% | one-shot histórico, no transfiere |
| Francia | +20.00% | -3.28% | inconsistencia cross-año |
| Italia | +12.33% | +0.47% | marginal pero no decisivo |
| Turquía | +12.72% | +0.90% | régimen volátil |
| Brasil | +1.32% | -22.88% | falla LOYO |
| Alemania | +0.38% | -25.70% | mercado muy eficiente |

**Re-evaluar todas tras motor v2** — el actual sub-calibrado puede estar enmascarando edge real.

### Filtros NEGATIVOS estructurales (anti-filtros, EXCLUIR del universo)

Confirmados por agente "ángulos creativos" sobre N=4,339:

| Excluir | N | Yield | CI95% |
|---|---|---|---|
| `gap_l ≥ 14 días` (post-FIFA) | 906 | -13.65% | [-20.4, -6.7] sig |
| `DOW = Lunes` | 376 | -14.60% | [-25.1, -2.9] sig |
| `Mes 10 / Mes 11` | 911 | -10 a -12% | sig NEG |
| `hora kickoff < 14` | 2,167 | -6.99% | [-11.4, -2.2] sig |

**Combinado anti-Lunes + anti-gap14:** lift +2.8pp sobre baseline V0 (-3.72% → -0.92%). NO es edge pero reduce drawdown. Probablemente robusto post-motor v2 también.

### Framework de validación a aplicar tras motor v2

1. **Schema A:** train con TODOS los años, evaluar yield IS pool + por año individual.
2. **Schema B (LOYO):** train con cada año individualmente, evaluar resto.
3. **Criterio promoción a SHADOW MODE:**
   - Schema A yield IS > +5%
   - Schema A años positivos ≥ 50%
   - Schema B avg OOS > 0
   - Schema B consistencia ≥ 50%
   - N >= 30 (mínimo)
4. **Bonferroni** α = 0.05/n_ligas si se prueba per-liga (8 ligas → α=0.00625).
5. **Bootstrap CI95%** con percentile 5 > 0 obligatorio.

### Datos a verificar tras motor v2

- ¿theta empírico cambia con motor reconstruído? Re-correr grid θ ∈ [0,1] con nuevo xg_calc.
- ¿Brier 1X2 modelo se acerca a mercado (0.5881)?
- ¿Hit rate global supera 1/3 random + 5%?
- ¿Yield IS pool sin filtros ≥ -2% (cerca del margen bookie)?

### Conceptos NO probados pendientes (si tiempo)

- ECE bucketed por liga (calibración zona apostable P≥0.50)
- xT / EPV / VAEP per-liga (requiere event-level data, no disponible aún)
- Anchor a mercado (Kuypers 2000) por bucket EV
- Ensemble V0 + V_dual + V_ruido por subset (consensus_v0_vr coef +0.42 LR)
- Mixture of experts gated por bin × liga
- Stats reales partido como features descriptivas: SOT diferencial favorito-rival, possession ratio
- Forma reciente (ola_3, streak local sin perder en casa)
- Equipos whitelist/blacklist específicos (Atlético Madrid +59% N=11, Newcastle +32% N=23 — si transfieren post-motor)
- Patrones contextuales: post-FIFA, post-derby, back-to-back

### Persistencia operacional

- Tabla DB: `agentes_findings` (sesion `2026-05-02_team_filtros_oro`, 16 filas)
- Bead epic: `adepor-mcj`
- Universo expandido: `stats_partido_espn` con cols `ht_fdco_norm`, `at_fdco_norm`, `fecha_fdco`
- Match-rate global: 8,892/13,430 (66.2%)
- LATAM 8 ligas sin cobertura fdco (4,538 partidos sin posibilidad match)
- TheOddsAPI: 6 keys, 378 credits, NED/POR/SCO/SWE/ARG/BRA/NOR/TUR confirmadas activas

### Documentos relacionados

- `docs/papers/audit_xg_v5_evolucion.md` — evolución completa
- `docs/papers/filtro_de_oro_findings_finales.md` — filtros pre-expansión
- `docs/papers/audit_v0_crudo_n_expandido.md` — veto crítico
- `docs/papers/walk_forward_true_oos_5_propuestas.md` — vetos walk-forward
- `docs/papers/filtros_oro_8_ligas.md` — filtros per-liga (overfit)
- `docs/papers/nichos_sostenibles.md` — nichos sin Bonferroni
- `docs/papers/angulos_creativos_resultados.md` — patrones contextuales
- `docs/papers/expansion_match_cuotas.md` — fix mappings
- `analisis/theta_y_filtros_IS2026.{py,json}` — validación theta + filtros
- `analisis/cv_filtros_y_validar_theta.py` — schema A+B initial
