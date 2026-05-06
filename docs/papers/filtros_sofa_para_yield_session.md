# Filtros estratégicos SOFA para sesión yield futura

**Fecha:** 2026-05-04
**Trigger:** durante POC motor xG v2, identificamos features SOFA que NO aportan al xG forward-EMA pero SÍ podrían aportar como filtros de selección de picks (yield).
**Data ya disponible:** `sofascore_match_features` (769 partidos season 2026, 19,660 shots) + `picks_shadow_xg_v2` (1,524 eventos backfilled).

---

## A. ÁRBITROS (`referee_name`, `referee_yellows`, `referee_reds`, `referee_games`)

| ID | Filtro | Hipótesis | Métrica validación |
|---|---|---|---|
| A1 | árbitro_strict (cards/game ≥ 6.0) | Más cards → mayor varianza → más empates | yield empate, over_2.5 cards |
| A2 | árbitro_red_freq (red/game ≥ 0.30) | Más rojas → favorito con jugadores- → upset | yield favorito (NEGATIVO esperado) |
| A3 | árbitro_lax (cards/game ≤ 4.0) | Menos cards → menos roja → favorito gana | yield favorito (POSITIVO esperado) |
| A4 | árbitro_first_match (games < 30) | Árbitro novel → más errores → varianza alta | filtro NEGATIVO universal |
| A5 | árbitro × liga blacklist | Algunos árbitros tienen yield NEGATIVO consistente | yield <-10% N≥10 |
| A6 | árbitro_home_bias (home_win_rate por ref) | Algunos favorecen local | yield local cuando ratio > 0.55 |

**Cobertura**: 14/16 ligas tienen referee_name populated (BOL/VEN NULL en SOFA).

## B. FORMACIONES (`formation_l`, `formation_v`)

| ID | Filtro | Hipótesis | Métrica |
|---|---|---|---|
| B1 | 3atrás vs 5atrás mismatch | Ataque vs defensa = over | over_2.5 yield |
| B2 | 4-2-3-1 vs 5-4-1 | Frontiers 2024: 4-2-3-1 outperforms 5-x en goals | yield over + goals_l |
| B3 | mismatch tactical (abs diff formation_score) | Diff táctica grande → unpredictable | yield NEGATIVO/over |
| B4 | 3-4-2-1 high press | Configuración high press → BTTS | yield BTTS |
| B5 | 5atrás home (defensiva) | Local con 5atrás → empate/derrota → NO apostar local | filtro NEGATIVO |
| B6 | DT cambio formación vs partido anterior | DT improvisa → cohesión↓ → upset | yield underdog |

**Cobertura**: 16/16 ligas, formación canónica string disponible.

## C. MANAGERS (`manager_l`, `manager_v`)

| ID | Filtro | Hipótesis | Métrica |
|---|---|---|---|
| C1 | DT debutante | Primer partido → varianza alta | filtro NEGATIVO |
| C2 | DT streak > 5W | Momentum mantenido | yield favorito |
| C3 | DT × liga whitelist | Algunos DT con yield + en liga específica | yield > +10% N≥10 |
| C4 | h2h DT vs DT | Si DT_l venció a DT_v 4/5 veces → favorito | yield h2h DT |

## D. STATS PARTIDO (lag-1, predicen siguiente)

| ID | Filtro | Hipótesis | Métrica |
|---|---|---|---|
| D1 | big_chances_missed_lag1 ≥ 3 | "Deuda" → mete más next | yield over equipo en N+1 |
| D2 | errors_lead_to_shot_lag1 ≥ 2 | Defensa colapsa → sigue errando | yield contra |
| D3 | touches_penalty_area_lag1 > 25 | Presión territorial sostenida | yield sobre ese equipo |
| D4 | shots_outside_box_ratio > 0.50 | Frustración tirando lejos → bajo xG | yield contra |
| D5 | recoveries_lag1 < 50 | Posesión perdida fácil → rival ataca | yield rival |
| D6 | aerial_duels_won < 30% | Débil en alto → corners rival peligroso | yield over corners |

## E. PLAYER RATINGS (`avg_rating`, `max_rating`)

| ID | Filtro | Hipótesis | Métrica |
|---|---|---|---|
| E1 | max_rating_lag1 ≥ 8.5 | Star en forma | yield favorito ese equipo |
| E2 | avg_rating_lag1 < 6.5 | Rotación masiva → rendimiento bajo | yield contra |
| E3 | rating_std alto (varianza) | Pocos clave + muchos suplentes → frágil | filtro NEGATIVO favorito |

## F. KEEPER (`keeper_save_value`)

| ID | Filtro | Hipótesis | Métrica |
|---|---|---|---|
| F1 | keeper_save_value_lag1 > 1.5 | "Salvó" partido pasado → buena forma | yield contra (no marcar) |
| F2 | keeper_save_value_lag1 < 0.3 | Arquero malo → over | yield over vs ese equipo |

## G. MOMENTUM (`graph` 92 puntos)

| ID | Filtro | Hipótesis | Métrica |
|---|---|---|---|
| G1 | momentum_reversion_lag1 | Dominó sin ganar → "frustración" → next exit | yield equipo N+1 |
| G2 | momentum_late_game > 70% | Dominio final game → forma | continuidad N+1 |

## H. PREGAME FORM + STREAKS

| ID | Filtro | Hipótesis | Métrica |
|---|---|---|---|
| H1 | 5W streak | Racha fuerte → continuidad | yield favorito |
| H2 | 3L streak después de 3W | Reversión post-racha | yield underdog |
| H3 | h2h favorable (3 últimos vs rival) | Dominio histórico | yield favorito h2h |
| H4 | forma reciente discordante (W-L-W-L) | Inconsistencia | filtro NEGATIVO |

## I. COMBINACIONES (top-3 individuales × combinaciones)

| ID | Filtro | Hipótesis |
|---|---|---|
| I1 | árbitro_strict + 3-atrás vs 5-atrás | many cards + tactical mismatch | over_2.5 cards + goals |
| I2 | DT cambio + visitante | DT nuevo afuera = chaos | NEGATIVO local underdog |
| I3 | keeper_low + errors_lead | Defensa + arquero cracked | yield rival over |
| I4 | avg_rating_alto + posesión > 60% | Top dominante | yield favorito home |
| I5 | árbitro_strict + cuota alta favorito | Cards en partido cerrado → empate | yield empate |

## J. DERIVADOS (computables sobre DB existente)

| ID | Feature | Idea |
|---|---|---|
| J1 | referee_strictness × home_factor liga | algunos árbitros sesgo home en liga específica |
| J2 | formation_diversity_team (entropy formaciones lag-5) | DT improvisa = inconsistente |
| J3 | player_rating_distribution (Gini lineup) | Star vs balanceado |
| J4 | xg_shotmap_concentration (% shots inside_box) | Calidad vs cantidad |
| J5 | rating_volatility_player_top (std max_rating) | Star inestable → upset |

---

## Plan ejecución sesión futura

### Fase 1 — Exploración descriptiva (1-2h)
- Para cada filtro A-J, computar:
  - Yield IS sobre 1,524 eventos SHADOW
  - Hit rate
  - N efectivo
  - Bootstrap CI95% percentile
- Bonferroni α = 0.05/n_filtros (~0.001 si 50 filtros)

### Fase 2 — Validación walk-forward
- Schema A: train all years → eval per year
- Schema B (LOYO): train cada año → test resto
- Criterio promoción:
  - Yield IS pool > +5%
  - % años positivos ≥ 50%
  - OOS avg > 0
  - Bootstrap CI95% lower > 0

### Fase 3 — Combinaciones top
- Tomar 3-5 mejores individuales
- Probar combinaciones (AND, OR)
- Lift aditivo vs multiplicativo

### Fase 4 — Implementación SHADOW
- Tabla nueva: `picks_shadow_filtros_sofa_v1`
- Loggear picks aplicando filtros
- N≥80 → decisión promoción

---

## Documentos relacionados

- `docs/papers/motor_xg_v2_resultados_finales.md` — POC xG v2
- `docs/papers/sofascore_findings_consolidados.md` — features SOFA disponibles
- `docs/papers/filtros_estrategicos_pendientes.md` — filtros sin SOFA (sesión previa)
- Tabla DB: `sofascore_match_features` (769 partidos)
- Tabla DB: `picks_shadow_xg_v2` (1,524 eventos)
