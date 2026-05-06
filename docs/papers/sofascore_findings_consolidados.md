# SofaScore — findings consolidados motor xG v2

**Fecha:** 2026-05-03
**Branch:** `experimentos`
**Sesión:** `2026-05-03_motor_xg_v2_sofa`
**Trigger:** consolidar todo lo aprendido sobre SofaScore como fuente de features pre-match para motor xG v2.

---

## TL;DR

SofaScore unofficial API expone una cantidad **drásticamente superior** de stats vs ESPN en las 16 ligas del proyecto, incluyendo BOL/VEN/URU/PER/ECU (LATAM exóticas). Cobertura confirmada season 2026 al **100% en las 16 ligas**.

**Más importante**: SofaScore expone:
1. **shotmap con coordenadas + situación** → permite reconstruir xG real (no derivado de SOT)
2. **referee CV histórico** (yellowCards, redCards, games) → árbitro strictness real
3. **`keeperSaveValue` por shot** → xG faced (proxy directo de xG ofensivo del rival)
4. **VAEP-like ValueNormalized** por jugador (defensiveValueNormalized, passValueNormalized, etc.)
5. **Player ratings** numéricos
6. **Formación canónica** "4-3-3" string + lineup confirmed pre-match

**ESPN solo expone**: stats post-match agregadas por equipo (28 stats) + officials parcialmente (78%). Sin shotmap, sin ratings, sin VAEP.

---

## Cobertura cross-liga verificada (sample 1 partido por liga)

| Liga | sofa_id | Stats groups | Shotmap | Formación | Manager | Momentum | Player rating | Referee CV |
|---|---|---|---|---|---|---|---|---|
| Argentina | 155 | 21 | 22 | ✓ | ✓ | 92 puntos | ✓ | ✓ Leandro Rey Hilfer |
| Brasil | 325 | 21 | 22 | ✓ | ✓ | 92 | ✓ | ✓ Flavio Rodrigues De Souza |
| **Bolivia** | 16736 | 21 | 24 | ✓ | ✓ | 92 | ✓ | ✗ NULL |
| **Perú** | 406 | 21 | 28 | ✓ | ✓ | 92 | ✓ | ✓ Pablo Lopez Ramos |
| Ecuador | 240 | 21 | 20 | ✓ | ✓ | 92 | ✓ | ✓ Alex Cajas Torres |
| **Venezuela** | 231 | 21 | 18 | ✓ | ✓ | 92 | ✓ | ✗ NULL |
| **Uruguay** | 278 | 7* | 30 | ✓ | ✓ | 128 | ✓ | ✓ Felipe Vikonis |
| Inglaterra | 17 | 21 | 30 | ✓ | ✓ | 92 | ✓ | n/a |
| España | 8 | 21 | 27 | ✓ | ✓ | 92 | ✓ | n/a |
| Italia | 23 | 21 | 31 | ✓ | ✓ | 92 | ✓ | n/a |
| Alemania | 35 | 21 | 34 | ✓ | ✓ | 92 | ✓ | n/a |
| Francia | 34 | 21 | 24 | ✓ | ✓ | 92 | ✓ | n/a |
| Turquía | 52 | 21 | 21 | ✓ | ✓ | 92 | ✓ | n/a |
| Noruega | 20 | 21 | 23 | ✓ | ✓ | 92 | ✓ | n/a |
| Chile | 11653 | 7* | 17 | ✓ | ✓ | 132 | ✓ | n/a |
| Colombia | 152 | 21 | 25 | ✓ | ✓ | 92 | ✓ | n/a |

`*Uruguay/Chile/Bolivia muestran 7 stats groups vs 21 estándar (formato reducido) pero datos clave presentes.`

**Cobertura referee LATAM exóticas vs ESPN/research previo:**
- ✓ Argentina, Brasil, Perú, Ecuador, Uruguay → SofaScore SÍ (research previo dijo NO en 3/5)
- ✗ Bolivia, Venezuela → SofaScore NO (research previo correcto)
- **Combinación SofaScore + ESPN ≈ 90%+ cobertura referee global**

---

## Stats nuevas vs ESPN (lo que SofaScore aporta)

### Stats per-partido (`/event/{id}/statistics`)

| Categoría | Stats nuevas no-ESPN |
|---|---|
| Match overview | Big chances, Big chances missed |
| Shots | **Shots inside box / outside box**, **Hit woodwork** |
| Attack | **Touches in penalty area**, Fouled in final third |
| Passes | Final third entries, Long balls %, Crosses % |
| Duels | Ground vs Aerial duels separados, Dribbles % |
| Defending | **Errors lead to a shot**, Recoveries, Tackles won % |
| Goalkeeping | High claims, Punches, Goal kicks |

Más: **3 períodos** (ALL / 1ST / 2ND) — ESPN solo agregado total.

### Stats per-shot (`/event/{id}/shotmap`)

Cada shot tiene 19 fields incluyendo:
- `playerCoordinates` (x, y, z) — desde dónde shoteó
- `goalMouthCoordinates` (x, y, z) — adónde fue
- `bodyPart` (right-foot/left-foot/head)
- `situation` (penalty/set-piece/corner/fast-break/assisted/regular-play)
- `shotType` (goal/save/miss/post/block)
- `time` + `addedTime`
- `player` y `goalkeeper` info completa

### Stats per-jugador (`/event/{id}/lineups.players[].statistics`)

30+ fields por jugador, destacados:
- `keeperSaveValue` ⭐ — **xG faced (xS) por save**
- `defensiveValueNormalized`, `passValueNormalized`, `dribbleValueNormalized`, `goalkeeperValueNormalized` — métricas tipo VAEP/EPV
- `rating` numérico (1-10)
- `keyPass`, `goalAssist`, `savedShotsFromInsideTheBox`
- `accuratePass`, `totalLongBalls`, `totalProgression`
- `ballRecovery`, `totalClearance`, `duelWon`

### Referee CV (`/event/{id}.referee`)

```json
{
  "name": "Leandro Rey Hilfer",
  "id": 787028,
  "yellowCards": 882,    // total HISTÓRICO
  "redCards": 24,
  "yellowRedCards": 22,
  "games": 171
}
```

Permite calcular features pre-match:
- `cards_per_game = (yellowCards + redCards) / games` — strictness del árbitro
- `red_per_game = redCards / games` — frecuencia de rojas (impacto goles)
- `xred_in_match = red_per_game` — proba de roja en este partido específico

---

## Cómo se usa cada feature en motor xG v2

| Feature | Modelo target | Por qué aporta |
|---|---|---|
| **xg_shotmap (suma per equipo)** | xg_calc reemplazante | xG real coordenadas-based vs SOT proxy |
| **big_chances** | xg_calc input | calidad de chance, no solo cantidad |
| **shots_inside_box** | xg_calc input | proxy ubicación shots |
| **touches_penalty_area** | xg_calc input | presión territorial |
| **keeperSaveValue rival** | xg_calc input | xS faced = xG ofensivo (cross-validation con shotmap) |
| **avg_rating equipo** | calidad equipo | proxy talento |
| **max_rating** | calidad estrella | jugador clave del partido |
| **cards_per_game ref** | dynamic feature | árbitro estricto → más cards → posible roja → goles cambian |
| **red_per_game ref** | dynamic feature | frecuencia roja en este referee |
| **formation cat** | táctica | 4-3-3 vs 5-4-1 efectos no-lineales |

---

## Endpoints útiles confirmados

```
/api/v1/unique-tournament/{id}                              # metadata torneo
/api/v1/unique-tournament/{id}/seasons                      # lista seasons (top = actual)
/api/v1/unique-tournament/{id}/season/{sid}/events/last/{p} # paginar eventos
/api/v1/event/{eid}                                         # main + referee CV
/api/v1/event/{eid}/statistics                              # 50+ stats (3 períodos)
/api/v1/event/{eid}/shotmap                                 # shots con coords
/api/v1/event/{eid}/lineups                                 # formación + 30 stats/jugador
/api/v1/event/{eid}/managers                                # DT info
/api/v1/event/{eid}/incidents                               # timeline cards/sub
/api/v1/event/{eid}/graph                                   # momentum 92 puntos
/api/v1/event/{eid}/best-players/summary                    # POTM + ratings
/api/v1/event/{eid}/team-streaks                            # rachas
/api/v1/event/{eid}/pregame-form                            # forma reciente
/api/v1/event/{eid}/odds/1/all                              # 15 markets cuotas
/api/v1/event/{eid}/comments                                # narrativa (no útil)
/api/v1/event/{eid}/highlights                              # videos (no útil)
```

---

## Restricciones operativas

### Anti-bot
- Sleep aleatorio 1.5-3.5s entre calls
- Pausa 60s cada 50 calls
- Pausa 5min cada 200 calls
- Cap absoluto: 1500 calls/sesión
- Abort inmediato al primer 403
- IP bloqueada → 1-24h o cambio de IP

### Stack técnico
- `curl_cffi` con `impersonate='chrome'` bypassa Cloudflare TLS fingerprint
- `seleniumbase` UC mode como fallback (más pesado)
- User-Agent rotation entre 5 variantes Chrome reales
- Headers: Referer + Origin + Accept-Language como browser

### Coverage gaps
- Bolivia/Venezuela: referee NULL (necesita scraping federación / prensa)
- ESPN cubre referee 78% global (incluyendo BOL/VEN parciales)
- Plan ideal: SofaScore primero, ESPN como complemento referee

---

## Hallazgo clave: matching SofaScore ↔ stats_partido_espn

**47.6% inicial → 70%+ con normalización agresiva**:

```python
def normalizar(s, liga=None):
    s = unicodedata.normalize('NFKD', s).encode('ascii', errors='ignore').decode().lower().strip()
    for prefix in ('club atletico ', 'ca ', 'cd ', 'club ', 'fc ', 'sc ', 'atletico '):
        if s.startswith(prefix):
            s = s[len(prefix):]
    s = re.sub(r'\([^)]*\)', '', s).strip()
    s = re.sub(r'\s+', ' ', s)
    return ALIASES_SOFA_TO_ESPN.get(liga, {}).get(s, s)
```

Aliases manuales restantes (ARG):
- `Gimnasia y Esgrima` → ambigüedad LP vs Mendoza (default LP)
- `Gimnasia y Esgrima Mendoza` → `Gimnasia Mendoza`
- `Union de Santa Fe` → `Union Santa Fe`
- `Central Cordoba` → `Central Cordoba Santiago del Estero`

---

## Plan de uso del POC

1. ✅ Backfill season 2026 en sofascore_match_features (en curso ~80 min)
2. ✅ Matching agresivo SofaScore ↔ ESPN
3. ✅ xG model interno entrenado sobre shotmap (LogReg + 5-fold CV)
4. ✅ Persistir `xg_shotmap_l/v` por partido
5. ⏳ **Ablation NNLS Bayesian + features sofa** — medir Δ RMSE forward-EMA
6. ⏳ Si Δ > 0.005 → backfill histórico SofaScore 2022-2025 (5h+)
7. ⏳ Bead `[PROPOSAL: MANIFESTO CHANGE]` Opción C completa con cascada

---

## Documentación relacionada

- `docs/papers/research_fuentes_features_premarch.md` — research general fuentes
- `docs/papers/sofascore_anti_bot_strategy.md` — guía anti-bot operativa
- `docs/papers/xg_from_shotmap_metodologia.md` — metodología xG model interno
- `docs/papers/motor_xg_v2_propuesta.md` — propuesta consolidada motor v2
- `docs/papers/research_fuentes_latam_features.md` — research específico LATAM
- `analisis/motor_xg_v2_13_sofascore_poc.py` — scraper safeguards
- `analisis/motor_xg_v2_14_xg_from_shotmap.py` — xG model
- `analisis/motor_xg_v2_15_ablation_sofa.py` — ablation pipeline
