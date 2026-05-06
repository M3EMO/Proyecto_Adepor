# Research — Fuentes para features pre-match (árbitros, formaciones, lineups)

**Fecha:** 2026-05-03
**Sesión:** `2026-05-03_motor_xg_v2`
**Branch:** `experimentos`
**Trigger:** usuario solicita evaluar features pre-match no-derivables de stats post-game para bajar RMSE forward-EMA.

---

## TL;DR

**Top recomendación**: API-Football Pro $19/mes — cubre las 3 categorías (referee, formaciones, lineups) en un solo wrapper que **ya está integrado** en `src/ingesta/motor_cuotas_apifootball.py` y `scripts/scraper_copas_api_football.py`.

**Caveat de honestidad**: dado que el motor V0 ya está en techo informacional de stats post-match (tarjetas/fouls/offsides/possession/saves/blocks shrinkados a 0 por NNLS), **no hay garantía teórica de que referee/formation/lineup mejoren RMSE forward-EMA**. La literatura sugiere efectos de 2-3% (referee bias post-VAR) — magnitudes pequeñas. Hacer **POC con N=2024 (~3,500 partidos) primero** y validar Δ RMSE > 0.005 antes de scrapear todo.

**Eliminadas por TOS legal**: WhoScored, Sofascore (prohíben data mining explícitamente).

---

## Top-1 por categoría

| Categoría | Top-1 | Por qué |
|---|---|---|
| **Referee** | API-Football `/fixtures.referee` | 1,200+ ligas declaradas. Cubre las 19 del target. ESPN expone `gameInfo.officials` solo en top-5 EUR — falla en BOL/VEN |
| **Formaciones** | API-Football `/fixtures/lineups.formation` | Único feed con string canónico ("4-3-3"). FBref tiene pero scraping frágil (Cloudflare) |
| **Lineups + lesiones** | API-Football `/fixtures/lineups` + `/injuries` + `/sidelined` | Único endpoint con SLA pre-match real (20-40 min antes) |

---

## Tabla comparativa fuentes

| Fuente | Mensual USD | Cobertura referee | Cobertura formación | Cobertura lineups | TOS scraping |
|---|---|---|---|---|---|
| **API-Football Pro $19/mo (7,500 calls/d)** | **$19** | **82-93%** | **82-93%** | **82-93%** | ✅ API oficial paga |
| API-Football Free (100 calls/d) | $0 | igual | igual | igual | ✅ pero backfill 134 días |
| API-Football Ultra (75,000 calls/d) | $29 | igual | igual | igual | ✅ |
| ESPN site.api | $0 | 45-52% (solo top EUR + ARG/BRA) | 0% (solo `formationPlace` numérico) | 45-52% | gris (no documentado público) |
| FBref scrape (worldfootballR) | $0 | ~74% | ~74% | ~74% | ✅ con atribución, rate limit cloudflare |
| football-data.co.uk | $0 | 56% (solo CSV EUR + ARG/BRA) | 0% | 0% | ✅ CSVs públicos |
| SportMonks Pro | ~$272 | ~100% | ~100% | ~100% | ✅ comercial paga |
| Opta / StatsBomb | $5k+/año | ~100% | ~100% | ~100% | ✅ enterprise |
| WhoScored / Sofascore / FotMob | varía | varía | varía | varía | ❌ TOS prohíbe |

---

## Cantidad recuperable para 13,430 partidos (universo `stats_partido_espn`)

| Fuente | Referee | Formaciones | Lineups | Cobertura efectiva esperada |
|---|---|---|---|---|
| API-Football Pro $19/mo | ~13,000 | ~11,000-12,500 | ~11,000-12,500 | 82-93% (degradada en BOL/VEN/CHI/PER 2da div) |
| ESPN summary | ~6,000-7,000 | 0 | ~6,000-7,000 | 45-52% |
| FBref scrape | ~10,000 | ~10,000 | ~10,000 | 74% |
| football-data.co.uk | ~7,500 | 0 | 0 | 56% |
| SportMonks Pro | ~13,400 | ~13,400 | ~13,400 | ~100% |

---

## Caveats técnicos

1. **Verificación empírica obligatoria pre-implementación**: ping `/leagues?country=Bolivia&season=2024` con `coverage.fixtures.lineups`. API-Football declara cobertura pero `referee`/`formation` son fields opcionales que pueden venir `null`. Requiere muestra empírica N=50 por liga.

2. **ESPN cobertura asimétrica verificada empíricamente HOY (2026-05-03)**:
   - ✅ Premier League ENG: `gameInfo.officials[0].fullName = "Anthony Taylor"`
   - ❌ Bolivia (`bol.1`): `officials` ausente
   - ❌ Venezuela (`ven.1`): `officials` ausente
   - Pendiente: ARG, BRA, COL, CHI, ECU, PER, URU

3. **FotMob NO tiene API pública**: predicted lineups scrapeables pero endpoint cambia frecuentemente (Cloudflare + WebSocket). Frágil.

4. **TOS legal**: WhoScored y Sofascore prohíben explícitamente "data mining, robots or similar gathering" sin licencia. Aunque `soccerdata` los soporta técnicamente, integrar a un motor monetizado expone al proyecto a takedown/cease-and-desist. **Eliminadas**.

5. **Tracking del feature impact ANTES del scraping masivo**: literatura académica:
   - Referee bias: ~2-3% home advantage post-VAR (Wiley 2025)
   - Formación 4-2-3-1 outperforms 5-x-x en goal-scoring (Frontiers 2024) — solo subset
   - Days rest/fatigue: confirmado mejora xG models (PMC 11524524)

---

## Estrategia de implementación recomendada

### Etapa 0 — Verificación empírica gratis (1 hora, 0 USD)
Usar 100 calls/día gratuitas. Ping `/leagues?country=X` para las 19 ligas → confirmar `coverage.lineups=true` y `coverage.fixtures.referee=true`. Sample 50 fixtures por liga (de 2024) → verificar % real de fields poblados.

**Gate 1**: si <70% cobertura referee O <50% formaciones → NO pagar Pro, abandonar features pre-match.

### Etapa 1 — POC backfill solo temporada 2024 (2-3 días, 19 USD)
Solo si Etapa 0 valida. ~3,500 partidos 2024. Tabla nueva `fixture_premarch_features`. A/B Bayesian hierarchical CON vs SIN referee+formation+lineup.

**Gate 2**: si Δ RMSE OOS pool > 0.005 (significativo) → proceder a Etapa 2.

### Etapa 2 — Backfill completo (si pasa Gate 2)
13,430 partidos. Re-fit Bayesian hierarchical con set completo de features. Eval holdout 2026 final.

### Etapa 3 — Manifiesto change
Si pasa el holdout 2026: bead `[PROPOSAL: MANIFESTO CHANGE]` Opción C con cascada completa.

### Plan B — Múltiples API keys gratis
Si user consigue 5-10 keys API-Football gratis (100 calls/d c/u): 500-1000 calls/d → backfill 13,400 en 13-30 días. Lento pero $0.

---

## Persistencia recomendada

Tabla nueva `fixture_premarch_features`:
```sql
CREATE TABLE fixture_premarch_features (
  id_partido INTEGER PRIMARY KEY,
  fk_liga TEXT,
  referee_name TEXT,
  formacion_local TEXT,           -- "4-3-3"
  formacion_visita TEXT,
  lineup_local_json TEXT,          -- startXI [{name, pos, num}]
  lineup_visita_json TEXT,
  injuries_local_json TEXT,
  injuries_visita_json TEXT,
  fuente_premarch TEXT,            -- 'API-Football' | 'ESPN' | 'FBref'
  ingest_ts TEXT,
  FOREIGN KEY (id_partido) REFERENCES stats_partido_espn (evt_id)
);
```

Permite A/B con vs sin features pre-match sin tocar tabla principal.

---

## Sources

- [API-Football Documentation v3](https://www.api-football.com/documentation-v3)
- [API-Football Coverage list](https://www.api-football.com/coverage)
- [API-Football Pricing](https://www.api-football.com/pricing)
- [SportMonks Plans & Pricing](https://www.sportmonks.com/football-api/plans-pricing/)
- [football-data.org Coverage](https://www.football-data.org/coverage)
- [ESPN Hidden API Docs](https://gist.github.com/akeaswaran/b48b02f1c94f873c6655e7129910fc3b)
- [worldfootballR R package - FBref](https://jaseziv.github.io/worldfootballR/articles/extract-fbref-data.html)
- [WhoScored Terms of Use](https://www.whoscored.com/TermsOfUse) (TOS prohíbe scraping)
- [Sofascore Terms & Conditions](https://www.sofascore.com/terms-and-conditions) (TOS prohíbe scraping)
- [Referee bias and home advantage - Tandfonline 2007](https://www.tandfonline.com/doi/full/10.1080/02640410601038576)
- [VAR and Home Field Advantage - Wiley 2025](https://onlinelibrary.wiley.com/doi/10.1002/soej.12731)
- [Home advantage mediated by referee bias - Nature Sci Reports 2021](https://www.nature.com/articles/s41598-021-00784-8)
- [Formation impact on goals - Frontiers 2024](https://www.frontiersin.org/journals/sports-and-active-living/articles/10.3389/fspor.2024.1323930/full)
- [Improving xG models PMC 11524524](https://pmc.ncbi.nlm.nih.gov/articles/PMC11524524/)
- [VAR reduces referee bias - Sage 2025](https://journals.sagepub.com/doi/10.1177/17479541251391395)
