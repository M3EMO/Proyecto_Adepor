# Cobertura The Odds API para ligas no-top — Reporte Cazador

**Fecha:** 2026-05-02
**Contexto:** evaluación de cobertura para extender cuotas históricas más allá de fdco (que solo cubre bien ARG/BRA y limitado TUR/NOR).

## 1. Cobertura por liga (sport_keys exactos)

| Liga | sport_key | Disponible |
|---|---|---|
| Argentina Primera | `soccer_argentina_primera_division` | SI |
| Brasil Serie A | `soccer_brazil_campeonato` | SI |
| Brasil Serie B | `soccer_brazil_serie_b` | SI |
| Turquía Süper Lig | `soccer_turkey_super_league` | SI |
| Noruega Eliteserien | `soccer_norway_eliteserien` | SI |
| Chile Primera | `soccer_chile_campeonato` | SI |
| Colombia / Perú / Ecuador / Uruguay / Bolivia / Venezuela | — | **NO listadas** |
| EPL/LaLiga/SerieA/Ligue1/Bundesliga + 2das divs + copas | múltiples | SI (control) |

**Gap crítico:** LATAM no-top (COL/PER/ECU/URU/BOL/VEN) NO cubierta por theoddsapi. Para esas ligas sigue siendo BetExplorer scraping o nada.

## 2. Profundidad histórica

- Earliest: **2020-06-06** (10-min snapshots)
- Desde **2022-09**: snapshots cada 5 min
- Cubre el rango 2022-2026 requerido por el proyecto. Ligas no-top probablemente agregadas más tarde — verificar via `/historical/sports?date=2022-01-01` antes de comprar plan.

## 3. Mercados disponibles

- `h2h` (1X2) — SI
- `totals` (O/U 2.5 y otros) — SI
- `spreads` (handicap europeo) — SI
- `btts` — SI (mencionado explícitamente)
- `draw_no_bet`, `double_chance` — SI
- **Asian handicap: NO mencionado** en docs (riesgo: no disponible para soccer)
- Player props soccer: **solo bookmakers US** (irrelevante para ligas no-US)

## 4. Costo y rate limit

| Plan | USD/mes | Credits/mes |
|---|---|---|
| Free | $0 | 500 |
| 20K | $30 | 20.000 |
| 100K | $59 | 100.000 |
| 5M | $119 | **5.000.000** |
| 15M | $249 | 15.000.000 |

**Costo histórico:** 10 × markets × regions credits/request.

### Estimación backfill ARG+BRA+TUR+NOR 2022-2026

- Partidos/año: ARG 280 + BRA 380 + TUR 306 + NOR 240 = **~1.206/año**
- 5 años: **~6.030 partidos**
- 1 snapshot/partido (cierre, suficiente para CLV) × 2 mercados (h2h+totals) × 1 región (eu) = **20 credits/partido**
- Total: **~120.600 credits one-shot**

| Plan | Viabilidad backfill 5 años |
|---|---|
| Free 500 | imposible |
| 20K $30 | requiere 6 meses acumulados |
| 100K $59 | NO single-shot (120k > 100k); 2 meses |
| **5M $119** | **single-shot con holgura x40 — RECOMENDADO** |

Para CLV completo (apertura + cierre × 2 snapshots/partido) → 240k credits, sigue cabiendo cómodo en 5M.

Mantenimiento ongoing post-backfill: ~1.200 partidos/año × 20 credits = 24k/año → plan 100K $59/mes alcanza sobrado.

## 5. Bookmakers (regiones)

Documentación no enumera bookmakers exactos por liga; práctica conocida:
- `eu`: Pinnacle, bet365, Marathon, William Hill, 1xBet, Unibet
- `uk`: bet365, Bet Victor, Coral, Ladbrokes
- `us`: DraftKings, FanDuel (irrelevante non-US)
- `au`: TAB, Sportsbet (limitado para LATAM/TUR/NOR)

Para ARG/BRA/TUR/NOR el bookmaker pivote sigue siendo **Pinnacle** (sharpest), región `eu`.

## 6. Comparativa vs football-data.co.uk (cuotas_historicas_fdco N=23.599)

| Liga | fdco actual | theoddsapi añade |
|---|---|---|
| ARG 2012-2026 | cuotas SI, stats NO | snapshots intra-day → CLV calculable; redundante para 1X2 cierre |
| BRA 2012-2026 | cuotas SI, stats NO | idem ARG |
| TUR | parcial / ausente | **valor real**: cobertura completa 2022-2026 |
| NOR | parcial / ausente | **valor real**: cobertura completa 2022-2026 |
| EU top 5 | cuotas+stats SI | redundante (ya cubierto) |

## Veredicto

**SI vale la pena para TUR + NOR.** Para ARG/BRA fdco ya da cuotas de cierre — theoddsapi solo aporta CLV (apertura→cierre) que es marginal para validación de yield estadístico.

**Decisión recomendada:**
1. Suscribir plan **5M $119** un solo mes para backfill ARG+BRA+TUR+NOR 2022-2026 (~240k credits con apertura+cierre)
2. Downgrade a **20K $30/mes** post-backfill para mantener picks live ongoing (6.030 partidos/año / 12 meses × 20 credits = 10k/mes alcanza)
3. **Costo total año 1: $119 + 11×$30 = $449 USD**
4. **NO cubre LATAM no-top (COL/PER/ECU/URU/BOL/VEN)** — para esas ligas seguir BetExplorer

## Riesgos

- Asian handicap NO confirmado para soccer (verificar antes de migrar mercado AH)
- Ligas no-top pueden tener cobertura histórica parcial (theoddsapi agrega ligas progresivamente — TUR/NOR pueden no tener 2022 completo)
- **Test obligatorio antes de pagar**: usar 500 credits free para `/historical/odds?sport=soccer_turkey_super_league&date=2022-08-15` y validar que retorna data
