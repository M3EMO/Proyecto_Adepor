# Ligas EU expansión Adepor — cobertura ESPN + fdco

**Fecha:** 2026-05-02
**Trigger:** investigación de qué ligas EU NO integradas hoy tienen cobertura completa para validación.

## Tabla resumen

| Liga | ESPN slug | Stats ESPN 2024 | fdco mainline | Profundidad | Recomendación |
|---|---|---|---|---|---|
| **Países Bajos** Eredivisie | `ned.1` | **YES** (27 stats) | N1.csv (full + odds 1X2 + O/U) | 1993-2026 vivo | **HIGH** |
| **Portugal** Primeira Liga | `por.1` | **YES** (27 stats) | P1.csv (full + odds) | vivo 2024-25 | **HIGH** |
| **Escocia** Premiership | `sco.1` | **YES** (28 stats) | SC0.csv (full + odds) | vivo 2024-25 | **HIGH** |
| **Suecia** Allsvenskan | `swe.1` | **YES** (27 stats) | SWE.csv (solo cuotas) | 2012-2026 vivo | HIGH (sin stats fdco) |
| Bélgica Pro League | `bel.1` | NO (boxscore vacío) | B1.csv (full + odds) | vivo | MED |
| Grecia Super League | `gre.1` | NO | G1.csv (full + odds) | vivo | MED |
| Suiza Super League | `sui.1` | NO | DEPRECATED 2012-16 | dead | LOW |
| Austria Bundesliga | `aut.1` | NO | DEPRECATED 2012-16 | dead | LOW |
| Dinamarca Superliga | `den.1` | NO | DEPRECATED 2012-16 | dead | LOW |
| Polonia Ekstraklasa | `pol.1` | HTTP 400 | DEPRECATED 2012-15 | dead | DESCARTAR |
| República Checa Fortuna | `cze.1` | events vacío | NO | dead | DESCARTAR |

## Top 3 priorizado

### 1. Países Bajos (Eredivisie) — HIGH
- ESPN summary devuelve 27 stats (idéntico schema 16 ligas actuales).
- fdco `N1.csv` mainline vivo con stats SoT/shots/corners/cards/fouls + cuotas 1X2 + O/U 2.5.
- Estilo ofensivo-posicional (3.0+ goles/partido) — diversifica del set actual.
- Mercado líquido en Pinnacle/B365.

### 2. Portugal (Primeira Liga) — HIGH
- ESPN stats YES verificado event 680288 (2024-03-10).
- fdco P1.csv vivo con full stats + cuotas.
- Estilo defensivo-pragmático (Sporting/Porto/Benfica).
- UEFA coef-3 → flujo cruzado con UCL/UEL ya scrapeados.

### 3. Escocia (Premiership) — HIGH
- ESPN summary 28 stats (más rico que NED/POR).
- fdco SC0.csv vivo con full stats + 110+ cols de cuotas.
- Liga compacta 12 equipos, alta varianza Old Firm vs cola.
- Útil para validar Layer 3 X-rescue (estilo físico-defensivo).

### Bonus: Suecia (Allsvenskan)
- ESPN stats YES (event 691679 verificado 2024-08-10).
- fdco SWE.csv solo cuotas (sin stats — usar ESPN como fuente única).
- Calendario inverso mar-nov → cubre valle junio-julio del calendario EU principal.

## Hallazgos negativos críticos

- **BEL/SUI/AUT/GRE/DEN ESPN summary** devuelve boxscore sin `statistics[]` array. ESPN solo trackea stats live para ligas top-tier.
- **fdco extra files** (AUT, POL, SUI, DNK) están deprecated en 2012-2016, inservibles para validación 2024-2026.
- Polonia, Rep. Checa imposibles vía ESPN en estado actual.

## Acción recomendada

**Integrar en orden NED → POR → SCO → SWE** (4 ligas, todas con match ESPN-stats + cuotas-mainline).

**Bélgica/Grecia van a MED** — solo cuotas, requeriría:
- Complementar con SofaScore (otro scraper).
- O relegar a modelo solo-cuotas tipo V12 LR sin features stats.

**Austria, Suiza, Dinamarca, Polonia, Rep. Checa: DESCARTAR.**

## Evidencia (event IDs verificados)

- NED: event=741259, 675538 (stats YES)
- POR: event=750525, 680288 (stats YES)
- SCO: event=709935 (stats YES, 28 stats)
- SWE: event=691679 (stats YES)
- BEL: event=674611, 674618 (stats NO)
- SUI: event=692562, 692554 (stats NO)
- AUT: event=675279, 675283 (stats NO)
- GRE: event=682671, 699782 (stats NO)
- DEN: event=670987, 670995 (stats NO)
