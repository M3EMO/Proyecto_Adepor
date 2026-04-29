# Beads pendientes — Snapshot 2026-04-28 NOCHE (cierre sesión 4)

> Inventario humanamente legible de los beads del proyecto al cierre del día
> 2026-04-28 (4 sesiones consecutivas: V5.2 + Track C + Layer 3 fix + audit profundo + V14 + ClubElo + copas pipeline).
>
> Cada bead explica QUÉ es, POR QUÉ existe, DÓNDE está parado, y qué EVENTO o
> ACCIÓN lo desbloquea.

## Estado del proyecto al cierre del día (NOCHE)

- **Manifesto:** **V5.2** (Layer 3 H4 X-rescue per-liga, **ACTIVO LIVE** desde 18:51)
- **SHA-256:** `471c1c00b927baad59cd13688bd5db142550a1aadbc45980a2b6d76862c4ab6c` (locked, sin cambios)
- **Filtros activos:** M.1 (TOP-5 ligas) + M.2 (n_acum<60). M.3 desactivado.
- **V13 SHADOW:** Argentina F1 NNLS, Francia F2 NNLS, Italia F2 RIDGE, Inglaterra F5 NNLS.
- **Layer 2 V12:** Turquía standalone (`arch_decision_per_liga = {"Turquia": "V12"}`)
- **Layer 3 H4 X-rescue ACTIVO:** `h4_x_rescue_threshold = {"Argentina": 0.35, "Italia": 0.35, "Inglaterra": 0.35, "Alemania": 0.35}`
- **Tabla Elo nueva:** `equipo_nivel_elo` (~40k filas, K-factor por competición)
- **Tabla ClubElo nueva:** `clubelo_ratings` (1,889 filas, 3 snapshots cross-validation)
- **Tabla shadow Layer 3:** `picks_shadow_layer3_log` (logging real-time decisiones Layer 3)
- **Tabla copas:** `partidos_no_liga` (~10k+ filas post-ESPN scraping; 1,251 nuevos partidos 2025 batch)
- **View:** `v_partidos_unificado` recreada con cols `_norm` (UNION liga + no-liga)
- **Coefs V14 persistidos:** `config_motor_valores.lr_v14_weights` (LogReg multinomial calibrado)

## Resumen sesiones 2026-04-28 (4 consecutivas)

### Sesión 1 (mañana) — V5.2 + Track C
- **V5.2 Layer 3 H4 X-rescue per-liga**: bead `adepor-tyb` aprobado tras audit Opción D.
  Δ +0.426 [+0.07, +0.78] *** sobre N=160 OOS. Helpers nuevos.
- Track C: 3 sub-líneas cerradas SIN promotion (cold-start n_acum, isotonic calib, Skellam V7).

### Sesión 2 (tarde) — Layer 3 ACTIVO + bug helpers + Mojibake
- **Layer 3 ACTIVADO LIVE 18:51 ARS** con thresh ARG/ITA/ING/ALE = 0.35.
- **Bug crítico Layer 3 helpers descubierto** (`adepor-0og` decision-log): query por `equipo` display
  pero parámetro `loc_norm` → 100% lookup fail → filtros NO bloqueaban.
- **Fix:** ALTER TABLE add `equipo_norm` cols + 5 indices + view recreada + helpers refactored.
- Mojibake fix `adepor-z0e` aplicado: 755 UPDATEs cleanup.

### Sesión 3 (noche temprana) — F1+F2+F3 estructurales
- **F1 INSERT consistency:** 4 scripts con `gestor_nombres` + popular `_norm`.
- **F2 schema partidos_no_liga:** 7 cols nuevas (liga_local, competicion_formato, series 2-leg, agregados).
- **F3 Motor copa research:** 18 fuentes peer-reviewed. Tabla `equipo_nivel_elo` (39k filas).
  Backtest standalone 49.5% global, copa internacional 53.0% (mejor año 2025: 54.1%).

### Sesión 4 (NOCHE) — Audit profundo + V14 + ClubElo + copas pipeline
- **Bug fuzzy gestor_nombres descubierto + corregido:** envenenamiento cross-country (Rangers→Angers, etc.).
  AUTO_LEARN_CUTOFF 0.92→0.95 + safety checks + 11 aliases envenenados eliminados.
- **Audit profundo:** docs/papers/entity_resolution_sports.md (Stoerts 2024 + 15 fuentes).
  Whitelist canonicalización: 788 filas unificadas. **Top-25 Elo coherente** (PSG 2004.6).
  COPA_INT 2025 hit 57.1%→58.9% (+1.8pp).
- **ClubElo CSV ingesta** (`adepor-04p` CLOSED): 1,889 filas. Cross-validation:
  corr GER 0.925, TUR 0.965, ESP 0.881, ITA 0.876, ENG 0.780. Bias -75 a -178 EUR.
- **Motor copa V14 calibrado** (`adepor-141`): LogReg multinomial. Test N=152, hit 54.6%, **Brier 0.2925** (mejor que Elo solo 0.3329 y xG solo 0.3588).
- **ESPN scraper bulk:** 16 copas, 439 partidos feb-abr 2026 + 1,251 partidos 2025.
- **Copas al pipeline LIVE (parcial):** `LIGAS_ESPN` += 14 copas. Pendiente integración full.
- **Investigación predicciones por liga (no generalizar):** docs/papers/predicciones_por_liga.md
  con 15 fuentes. Bundesliga EPV>xG, Italia tactical/Layer 3 relevante, Premier features defensivos
  rolling 3-match, LATAM estilos distintos (NO generalizar EUR).

### Track C (mejorar predicción) — 3 sub-líneas cerradas SIN promotion

- **Sub-1 cold-start n_acum≤10**: M.2 OK. Argentina 0-4 +74.4% agregado era artefacto Riestra 2024 + concentración en pocos equipos por temp. Drilling cross-temp + per-equipo refutó robustez.
- **Sub-3 calibración isotónica**: empeora yield consistentemente cross-liga + cross-temp + in-sample 2026 (todas TOP-5 V5.1 caen −19 a −29pp). Confirma paradoja Brier-Yield brutalmente.
- **Sub-4 Skellam V7**: V7 ≈ V0 en hit rate y Brier sobre N=8,157 OOS drilling cross-equipo. NO supera V0 en ningún subset.

### Beads cerrados

- `adepor-a1v` — V13 captura calidad estructural (r=−0.622 cross-liga). NO requiere feature explícito.
- `adepor-tyb` — Layer 3 H4 X-rescue per-liga aplicado.
- `adepor-edk` — PROPOSAL madre Layer 1+2+3 cerrada (Layer 2 aplicado, Layer 1 vetado, Layer 3 reformulado en `adepor-tyb`).
- `adepor-5y0.1` — Schema `partidos_no_liga` + view + indices + tests.
- `adepor-0bb`, `adepor-qea` — DECISION-LOGS archivados (Fase 3/4 canceladas; ENET descartado V13).

---

## Prioridad P1 — Decisiones grandes pendientes

(Ninguno hoy — `adepor-edk` cerrado tras aplicación V5.2)

---

## Prioridad P2 — Investigaciones / propuestas activas

### `adepor-5y0` — EPIC Calendario completo equipos (liga + copas nac. + int.)

**Qué es.** Epic para construir tabla `partidos_no_liga` con copas nacionales + internacionales (UEFA + Conmebol). Permite calcular `gap_dias_desde_ultimo_partido` por (equipo, fecha) considerando todas competiciones.

**Estado.** Sub-1 (schema) cerrado. Sub-2-7 abiertos:
- `adepor-5y0.2` — Poblar 2026 ARG (Libertadores + Sudamericana + Copa Argentina). Wikipedia parcial hecho (Libertadores + Sudamericana 192 partidos). Copa Argentina layout distinto, parser pending.
- `adepor-5y0.3` — Poblar 2026 ING (Champions + Europa + Conference + FA + EFL).
- `adepor-5y0.4` — Poblar OOS 2024 (cumplido vía API-Football, ~3,000 partidos).
- `adepor-5y0.5` — Poblar OOS 2022 + 2023 (cumplido vía API-Football, ~5,700 partidos).
- `adepor-5y0.6` — Cruzar X-rescue picks con calendario + análisis cansancio mid-week.
- `adepor-5y0.7` — Refinar `adepor-tyb` con feature `gap_dias_local`/`gap_dias_visita` (post sub-6).

**Trigger.** Manual — depende de scraping Wikipedia para Copa Argentina + Copa do Brasil 2026.

---

### `adepor-9uq` — INVESTIGATION M.2 universal vs régimen 2026

**Qué es.** Hallazgo accidental durante Track C Sub-1: bucket `n_acum_l ≥60` in-sample 2026 yield = +43.1% [-3.1, +91.6] borderline sobre N=64 picks. **Opuesto al OOS** (−13.7% sig neg).

Por liga in-sample 2026:
- Argentina ≥60: +6.6% (8/37) — neutral
- **Brasil ≥60: yield +120% [+23.0, +227.0] *** SIG POS** sobre N=22, hit_X 60%
- Inglaterra ≥60: +81.8% (11/33) borderline

**Por qué importa.** El filtro M.2 actual (`n_acum_max=60`) está BLOQUEANDO esos 64 picks. Si la inversión se mantiene, M.2 universal está drenando yield en 2026.

**Estado.** Esperando N≥200 picks ≥60 in-sample 2026 (~6-8 sem más).

**Trigger.** N≥200 + audit mensual (`adepor-j4e`) confirme yield_rolling sostenido CI95_lo > 0 sig por liga.

**Acción esperada.** PROPOSAL relajar M.2 a 80 universal O M.2 condicional por liga JSON (análogo Layer 3).

---

### `adepor-hxd` — PROPOSAL: M.3 condicional por liga vía yield_rolling 30d

**Qué es.** Aplicar M.3 (excluir momento_bin_4=Q4) selectivamente por liga: activar solo si `yield_rolling(liga, 30d) < baseline_liga - 2σ` sostenido 14d. Resuelve conflicto V5.1.2 (M.3 OFF) sin perder señal OOS 2024.

**Estado.** Bloqueado por `adepor-09s` Fase 2 (necesita detector régimen).

**Trigger.** N≥600 in-sample post-2026-03-16 (~3-4 semanas más).

---

### `adepor-9hh` — INFRA Extender `posiciones_tabla_snapshot` a 3-formatos

**Qué es.** Hoy solo Argentina tiene 3 formatos (anual + apertura + clausura). México, Brasil (estados), Colombia tienen formato apertura/clausura — replicar hook incremental.

**Estado.** Open. Long-running multi-session.

**Trigger.** Necesidad manual cuando V13 quiera aplicar pos_local en ligas no-anuales.

---

### `adepor-4tb` — EPIC Yield copas EUR domésticas (Copa Rey + FA + Coppa Italia)

**Qué es.** Audit hit rate sobre `partidos_no_liga` reveló copas EUR domésticas SUPERAN liga: Copa Rey 61.5%, FA 57.4%, Coppa 56.9%. Yield estimado +5-12pp.

**Estado.** **BLOQUEADO** — API-Football free tier NO soporta `/odds` (devuelve 0 sin error).

**Trigger.** Una de:
1. Upgrade API-Football Pro plan (~$19/mes)
2. Construir scraper oddsportal.com (high effort)
3. Datos cuotas históricas alternativos

---

### `adepor-8je` — INFRA Apostar Champions League pred=1 (favoritos locales)

**Qué es.** Audit reveló Champions League pred=1: hit 57.1% N=77, yield estimado +5.6%.

**Estado.** **BLOQUEADO** — mismo motivo `adepor-4tb` (API Pro requerido).

---

### `adepor-4ic` — META Mejorar predicción general (multi-line scoping)

**Qué es.** Bead meta para tracking de iniciativas que mejoran accuracy predictiva. NO se cierra — se actualiza cuando una sub-línea concreta se abre.

**Sub-líneas exploradas en sesión 2026-04-28:**
- Sub-1 cold-start n_acum≤10: cerrada SIN acción
- Sub-3 calibración isotónica: cerrada SIN acción (paradoja Brier-Yield confirmada)
- Sub-4 Skellam V7 promoción: cerrada SIN promotion

**Sub-líneas pendientes:**
- Sub-2 modelo separado para copa (3-5 sesiones, bloqueado yields)
- Sub-5 features V13 incrementales (2-3 sesiones)
- Sub-6 modelo isotónico per-liga selectivo (revisitar si España específicamente — única liga donde isotónica mejoró)

---

### `adepor-09s` — INFRA Detector régimen 2022/2023/2024

(sin cambio respecto inventario previo) Plan Fase 2 esperando N≥600 in-sample post-2026-03-16.

---

### `adepor-6rv` — PROPOSAL: V4.7 desactivar HG + Fix #5

(sin cambio) Bloqueado por `adepor-09s`.

---

### `adepor-d7h` — SHADOW V6+V7

**Sub-V7 cerrado direccionalmente** vía notes 2026-04-28 (audit_v7_skellam_drill: V7 ≈ V0 sobre N=8,157 OOS, ningún subset supera). V6 sigue como SHADOW input para V13.

**Trigger restante.** N≥80 picks SHADOW liquidados oficial (~3 sem más). Probable conclusión NO cambia.

---

### `adepor-1fd` — TRIGGER xg_corto N≥30

(sin cambio) Esperando.

---

### `adepor-hm9` — TRIGGER CLV N≥30

(sin cambio) Esperando.

---

### `adepor-334` — TRIGGER rho in-sample N>100/liga

(sin cambio) Esperando.

---

### `adepor-4f9` — INFRA Filtro M.4 candidato (parejos diff_pos≤3)

(sin cambio) Esperando N≥200 validación.

---

### `adepor-9ah` — TRIGGER M.3 selectivo Brasil Q4

(sin cambio) Esperando picks 2026 Q4.

---

### `adepor-p4e` — INVESTIGATION Caída Q3 Argentina 2023 copas internacionales

**Estado.** Bead todavía relevante. Hipótesis NO refutada por audit cansancio mid-week (Sub-X-rescue): hipótesis original (cansancio → empate) fue REFUTADA pero se identificó filtro INVERSO útil (NOT ambos cansados ≤14d) que ya está en V5.2 §N.

**Trigger restante.** Análisis específico Q3 ARG 2023 con tabla `partidos_no_liga` cuando esté completa para ARG (sub-bead `adepor-5y0.2`).

---

### `adepor-dex` — Cautela operativa Argentina

(sin cambio) Observabilidad.

---

### `adepor-tqm` — BACKLOG V5.0 follow-ups

(sin cambio) Bajo urgencia.

---

### `adepor-z0e` — BUG Mojibake `historial_equipos_stats`

(sin cambio) Pendiente debugging.

---

## Prioridad P3 — Triggers / metodología

### `adepor-23w` — TRIGGER A/B altitud
### `adepor-57p` — TRIGGER 6 arquitecturas SHADOW
### `adepor-6g5` — TRIGGER V13 promoción argmax por liga (N≥200 SHADOW)
### `adepor-j4e` — TRIGGER OOS-por-temp + in-sample mensual
### `adepor-s7m` — METHODOLOGY ventana móvil 2-temp en calibrar_rho

(sin cambios respecto inventario previo)

---

## Resumen de prioridades operativas

### Activación recomendada V5.2 (decisión usuario)

```sql
UPDATE config_motor_valores
SET valor_texto = '{"Argentina": 0.35, "Italia": 0.35, "Inglaterra": 0.35, "Alemania": 0.35}'
WHERE clave = 'h4_x_rescue_threshold' AND scope = 'global';
```

Operacionalmente solo Argentina + Inglaterra impactan picks LIVE V5.1 (M.1 filtra ITA/ALE).

### Esperando triggers (no acción inmediata)

| Bead | Trigger | ETA | Tipo |
|---|---|---|---|
| `adepor-09s` Fase 2 | N≥600 in-sample | ~3 sem | INFRA crítica |
| `adepor-9uq` M.2 vs 2026 | N≥200 picks ≥60 in-sample | ~6-8 sem | INVESTIGATION |
| `adepor-hxd` M.3 condicional | depende `adepor-09s` | ~3-6 sem | PROPOSAL |
| `adepor-d7h` / `adepor-57p` | N≥80 SHADOW | ~3 sem | TRIGGER (probable cierre direccional) |
| `adepor-1fd` | N≥30 xg_corto | ~2-3 sem | TRIGGER |
| `adepor-hm9` | N≥30 CLV | ~2-3 sem | TRIGGER |
| `adepor-334` | N>100/liga | ~2-3 meses | TRIGGER |
| `adepor-4f9` | N≥200 picks | ~6-8 sem | INFRA |
| `adepor-9ah` | picks 2026 Q4 | ~junio (post Apertura) | TRIGGER |
| `adepor-23w` | tabla altitud + N≥30 | varios meses | TRIGGER |
| `adepor-6g5` | N≥200 SHADOW V13 | ~3-6 meses | TRIGGER promoción |
| `adepor-j4e` | fin de mes | mensual | TRIGGER recurrente |
| `adepor-6rv` | depende `adepor-09s` | ~3-6 sem | PROPOSAL |
| `adepor-dex` | Brier rolling > 0.220 | observabilidad | OBS |
| `adepor-tqm` | post-V5.2 | indefinido | BACKLOG |
| `adepor-s7m` | manual | indefinido | METHODOLOGY |

### Bloqueados por API Pro

| Bead | Trigger desbloqueo |
|---|---|
| `adepor-4tb` | Upgrade API Pro O scraper alternativo |
| `adepor-8je` | Idem |

### Trabajo sub-bead activo (Epic `adepor-5y0`)

| Sub-bead | Estado | Próximo paso |
|---|---|---|
| 5y0.1 schema | ✓ closed | — |
| 5y0.2 ARG 2026 | open | Wikipedia Copa Argentina parser pending |
| 5y0.3 ING 2026 | open | Wikipedia + API hybrid |
| 5y0.4 OOS 2024 | open (data cumplida) | Cierre formal |
| 5y0.5 OOS 22/23 | open (data cumplida) | Cierre formal |
| 5y0.6 cruce X-rescue | open | Post-sub-2,3 |
| 5y0.7 refinar tyb | open | Post-sub-6 |

### Próxima ventana de acción esperada

**Mediados-fines de mayo 2026** (~3 semanas):
- N in-sample alcanzará ~600 → `adepor-09s` Fase 2 ejecutable
- N in-sample EUR top en cierre temporada (Premier 25-26 termina 24 may) → último bin Q4 EUR
- Argentina cierre Apertura jun 22 → primer dato Q4 Argentina post fix-calendario
- N≥200 picks ≥60 in-sample → `adepor-9uq` decidible

**Junio 2026:**
- Picks 2026 Q4 LATAM disponibles → `adepor-9ah` decidible
- Cierre Argentina Apertura → `adepor-p4e` analizable con calendario completo

**Agosto 2026:**
- Premier 26-27 arranque → primeros picks EUR Q1 2026-27
- Re-test M.3 NEW en EUR top con sample diversificado
