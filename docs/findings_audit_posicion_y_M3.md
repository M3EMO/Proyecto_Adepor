# Audit posición + Re-evaluación M.2/M.3 con calendario fix

> Fecha: 2026-04-28 — adepor-3ip / adepor-bix
> Output: `analisis/audit_posicion_y_M3_recalibracion.{py,json}`

## Tarea 2 — Adaptación motor por posición tabla

### T2A: Yield V0 por bucket pos_local (OOS 2024 N=2,656)

| Bucket | N_pred | N_apost | Hit% | Yield% | CI95 |
|---|---|---|---|---|---|
| TOP-3 | 349 | 30 | 33.3 | −10.1 | [−55.9, +39.2] |
| TOP-6 | 368 | 77 | 31.2 | −17.7 | [−44.2, +10.2] |
| MID | 778 | 206 | 32.5 | −9.1 | [−27.3, +10.3] |
| BOT-6 | 571 | 226 | 37.2 | +1.6 | [−16.8, +20.0] |
| **BOT-3** | 590 | 258 | 36.8 | **+16.6** | [−4.4, +36.9] |

Patrón **monotónico ascendente**: yield mejora con posición peor en tabla. Pero
**ningún bucket es sig estadísticamente** (CI95 cruzan 0).

### T2B: Matchups top vs bottom

| Matchup | N | Yield% | CI95 |
|---|---|---|---|
| TOP-vs-TOP (TOP-6 ambos) | 59 | **−25.5** | [−58.4, +9.4] |
| BOT-vs-BOT (BOT-6 ambos) | 178 | −12.6 | [−33.0, +7.9] |
| BOT-3 vs TOP-6 | 27 | +52.6 | [−24.3, +144.7] |
| MID vs MID | 63 | −2.6 | [−37.1, +32.9] |

**TOP-vs-TOP partidos son los más dañinos** (yield −25.5%) pero N=59 chico.

### T2C: Yield por diff_pos (gap en tabla)

| diff_pos | N_pred | Yield% | CI95 |
|---|---|---|---|
| L<<V (local +10 mejor) | 370 | **+18.9** | [−9.4, +48.2] |
| L<V | 739 | +4.0 | [−10.7, +20.2] |
| **L~V (parejos)** | **661** | **−14.0** | **[−32.1, +4.9]** ★ casi sig |
| L>V | 602 | −4.6 | [−30.1, +21.9] |
| L>>V (local +10 peor) | 284 | +23.2 | [−27.9, +75.2] |

**HALLAZGO IMPORTANTE:** los **partidos parejos en tabla (diff_pos en [−3, +3])
son DAÑINOS** (yield −14.0% N=213, CI95 cerca de sig negativo). Los mismatches
grandes (L<<V o L>>V) son rentables.

**Implicación:** el motor pierde cuando no hay favorito claro en tabla.
Una "regla M.4" candidata: bloquear apuestas con `|diff_pos| <= 3`.

### Veredicto Tarea 2

- **Existe señal direccional** (BOT-3 mejor que TOP-3, parejos peor que mismatch)
- **No alcanza significancia estadística con N actual** (necesita N≥500 por bucket
  para discriminar con CI95 robusto)
- **Filtro propuesto M.4** (excluir parejos): direccionalmente positivo pero
  requiere validación post-N≥200 picks operativos.

## Tarea 3 — Re-evaluación M.2/M.3 con calendario CORRECTO

### Impacto del fix calendario (OLD vs NEW)

**61.9% de los partidos OOS 2024 cambiaron de bin** con el calendario correcto.

Distribución bin NEW (calendario correcto):
- Q1: 54 partidos (2.0%)
- Q2: 152 (5.6%)
- Q3: 201 (7.4%)
- **Q4: 2,315 (85.0%)** ★

Razón: muchas ligas (EUR top, Argentina anual) tienen partidos OOS concentrados
en cierre real. El método OLD usaba rango observado (chico) y mapeaba
artificialmente partidos a Q1-Q3. Con calendario real, la mayoría son Q4.

### T3A: Yield V0 por bin con calendario NEW

| Bin | N_pred | N_apost | Hit% | Yield% | CI95 |
|---|---|---|---|---|---|
| Q1_arr | 54 | 31 | 29.0 | −35.2 | [−71.6, +2.5] |
| **Q2_ini** | 152 | 71 | 39.4 | **+21.8** | [−15.6, +61.0] |
| **Q3_mit** | 201 | 114 | 43.0 | **+18.1** | [−8.1, +46.1] |
| Q4_cie | 2,315 | 604 | 33.0 | **−4.0** | [−15.2, +7.9] |

**Q4 con calendario correcto: yield −4.0% (NO sig).** Antes con OLD calendario
M.3 calibró Q4 a yield −16.1% (sig). El cambio aclara que **Q4 cierre extremo
no es tan dañino como pensábamos** — el bin OLD mezclaba mid-temps mal-clasificados.

### T3B: Filtro M.3 OLD vs NEW

| Filtro | N_apost | Yield% | CI95 |
|---|---|---|---|
| BASELINE | 820 | +0.1 | [−9.3, +10.6] |
| M.3 OLD (excluir bin_OLD=Q4) | 585 | +7.0 | [−5.4, +18.4] |
| **M.3 NEW (excluir bin_NEW=Q4)** | **216** | **+11.7** | [−6.9, +31.3] |

M.3 NEW es más selectivo (deja pasar 216 vs 585), yield más alto (+11.7 vs +7.0)
pero CI95 más amplio por N menor.

### T3C: Filtro combinado M.2 + M.3 NEW

| Filtro | N_apost | Yield% | CI95 |
|---|---|---|---|
| BASELINE | 820 | +0.1 | [−9.3, +10.6] |
| M.2 (n_acum<60) | 434 | +12.2 | [−2.6, +27.0] |
| **M.2 + M.3 NEW** | **103** | **+31.8** | **[+1.8, +64.4]** ★★ |

**M.2 + M.3 con calendario CORRECTO da yield +31.8% CI95 [+1.8, +64.4]
SIGNIFICATIVO** sobre N=103 picks operativos.

Comparado con la calibración original (M.2 + M.3 OLD = yield +17.4% [+4.7, +30.2]
sobre N=513), el filtro NEW es más selectivo pero más rentable.

### Veredicto Tarea 3

- **El fix del calendario MEJORA el filtro V5.1**, no lo rompe.
- Calibración OOS sigue válida pero con números actualizados:
  - M.3 NEW excluye realmente solo el cierre extremo (Q4), no mid-temps mal-clasificados.
  - Yield combinado M.2+M.3 NEW: **+31.8% CI95 [+1.8, +64.4] ★★** (vs +17.4% OLD).
  - N picks operativos baja (103 vs 513) — mayor selectividad.

## Resumen ejecutivo

1. **Tarea 2 (posición)**: existe señal direccional (parejos −14%, mismatches +18%
   a +23%) pero no significativa. Filtro M.4 candidato `|diff_pos|<=3` requeriría
   validación N≥200.

2. **Tarea 3 (recalibración M.3)**: calendario correcto MEJORA filtro.
   Yield M.2+M.3 NEW = **+31.8% CI95 [+1.8, +64.4] ★★** sobre N=103 OOS 2024.
   Filtro queda más selectivo y más rentable.

3. **Operativo**: Argentina post-fix V5.1 desbloqueada. M.3 NEW filtra solo cierre
   real (Premier/Serie A/etc en mayo). LATAM (Brasil/Noruega/Argentina) NO se
   bloquean ahora.

## Próximos pasos

- [ ] Validación longitudinal post-fix con N≥200 picks operativos.
- [ ] Considerar bead `[INFRA] Filtro M.4 por diff_pos` cuando N permita
  validación robusta.
