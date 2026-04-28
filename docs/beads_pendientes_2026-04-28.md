# Beads pendientes — Snapshot 2026-04-28 (actualizado)

> Inventario humanamente legible de los 18 beads abiertos del proyecto.
> Cada bead explica QUÉ es, POR QUÉ existe, DÓNDE está parado, y qué EVENTO o
> ACCIÓN lo desbloquea.
>
> **Última actualización:** 2026-04-28 — agregados 5 beads nuevos al final del
> documento (`adepor-a1v`, `adepor-4f9`, `adepor-9ah`, `adepor-z0e`, `adepor-p4e`).

## Estado del proyecto al cierre del día

- **Manifesto:** V5.1.2 (commit `e433783` — M.3 OFF en config)
- **Filtros activos:** M.1 (TOP-5 ligas) + M.2 (n_acum<60). M.3 desactivado.
- **V13 SHADOW:** Argentina F1 NNLS, Francia F2 NNLS, Italia F2 RIDGE, Inglaterra F5 NNLS.
- **Posiciones:** tabla `posiciones_tabla_snapshot` viva, hook incremental al pipeline.
- **Calendario:** `liga_calendario_temp` poblada con 80 entradas por (liga, temp).

---

## Prioridad P1 — Decisiones grandes pendientes

### `adepor-edk` — PROPOSAL: Layer 1 (filtro liga) + Layer 3 (H4 X-rescue)

**Qué es.** PROPOSAL madre de la cual ya se aprobó y aplicó:
- ✅ **Layer 2** (V12 standalone Turquía): commit `37a30e1`, en producción.

Quedan pendientes los otros dos layers:
- **Layer 1**: filtro selectivo por liga `{Turquía, Italia, Francia, Inglaterra}`. Yield Drop_DE_ES H4 +5.7% sig.
- **Layer 3**: H4 X-rescue threshold=0.35 sobre subset filtrado. Yield +5.7% sig sobre OOS Pinnacle 2024.

**Por qué importa.** Es la única política con CI95 que excluye 0 sobre N=1.806 picks. El Layer 1 propone {TUR, ITA, FRA, ING}, distinto al filtro V5.1 actual {ARG, BRA, ING, NOR, TUR}.

**Estado.** Layer 2 ya aplicado. Layers 1+3 quedan en evaluación porque V5.1 (bead `adepor-ptk`, ya cerrado) usó otro filtro liga (basado en in-sample real). Hay que decidir si los layers 1/3 se descartan o se unifican con V5.1.

**Trigger.** Decisión humana. Posibles caminos:
- Cerrar como "obsoleto por V5.1" (filtro ptk gana en in-sample real).
- Reformular Layer 3 (H4 X-rescue) como bead separado si quiere validarse.

---

## Prioridad P2 — Investigaciones / propuestas activas

### `adepor-09s` — Detector de régimen 2022/2023/2024

**Qué es.** Investigación crítica sobre por qué V4.7 (desactivar HG+Fix5) cambia drásticamente entre años:
- 2022: Δyield V4.7 = +11.13pp [−6.4, +28.4] (favorable)
- 2023: Δyield V4.7 = **−15.69pp** [−24.9, −6.5] sig neg ★ (tóxico)
- 2024: Δyield V4.7 = −1.6pp (neutro)

**Por qué importa.** Cualquier cambio al motor (V4.7, M.3, V13) tiene efectos opuestos según el régimen. Sin un detector, no podemos aplicar políticas adaptativas.

**Estado.** Plan refinado en findings 2026-04-28:
- Fase 1 (caracterización 2022/2023/2024): **CERRADA** (`adepor-bix`). Hallazgo: features estructurales NO separan régimen 2023; solo yield_v0_unitario lo hace (p=0.034).
- Fase 2 (clasificador): pendiente.
- Plan refinado tras audit M.3 in-sample 2026: M.3 condicional por liga vía `yield_rolling(liga, 30d) < baseline−2σ` sostenido 14d → activar M.3 esa liga.

**Trigger.** N≥600 picks in-sample post-2026-03-16 (~3-4 semanas más, hoy ~358).

**Acción esperada.** Cuando se cumpla trigger, implementar Opción A (Brier/yield rolling) en `motor_adaptativo.py`.

---

### `adepor-6rv` — PROPOSAL: V4.7 desactivar HALLAZGO_G y Fix #5

**Qué es.** PROPOSAL para desactivar dos correcciones del motor (HG y Fix #5) que en algunos regímenes mejoran y en otros destruyen yield.

**Por qué importa.** Bead `adepor-09s` documenta que V4.7 es:
- Tóxico en 2023 (régimen sig neg)
- Favorable en 2022
- Neutro en 2024

**Estado.** Bloqueado por `adepor-09s` (necesita predictor de régimen para activación selectiva).

**Trigger.** Cuando `adepor-09s` Fase 2 cierre, evaluar V4.7 condicional por régimen. Si régimen "tóxico" detectado en una liga → desactivar HG+Fix5 esa liga.

**Acción esperada.** PROPOSAL: MANIFESTO CHANGE para V4.7 condicional. Snapshot DB + bump SHA.

---

### `adepor-d7h` — SHADOW V6+V7: xG recalibrado + Skellam

**Qué es.** Infraestructura SHADOW que loguea V6 (Poisson DC + xG OLS recalibrado) y V7 (Skellam + xG OLS) en cada corrida del motor productivo. NO afectan picks operativos.

**Por qué importa.** V6 y V7 son arquitecturas alternativas. Si en N≥80 picks SHADOW V6/V7 superan a V0 en yield + Brier, candidato a promoción.

**Estado.** Activo. Logging continuo en `picks_shadow_arquitecturas`. Conjunto V13 (bead `adepor-3ip` cerrado) también se loggea.

**Trigger.** N≥80 picks SHADOW liquidados.

**Acción esperada.** Audit V6/V7 vs V0 con N=80. Si yield V6 > V0 con CI95_lo > 0 → PROPOSAL para promover V6.

---

### `adepor-dex` — Cautela Argentina por regime shift

**Qué es.** Observabilidad alerta. Brier rolling Argentina last 50 = 0.206 (baseline 0.196, threshold 0.220). El motor está marginalmente peor calibrado en Argentina pero sin trigger para acción.

**Por qué importa.** Argentina es la única liga LIVE 1X2 hoy (TOP-5 V5.1). Si Brier sigue subiendo → considerar Kelly cap reducido per-liga.

**Estado.** Anotado con mitigación V5.1 §M.3 (ahora desactivada en V5.1.2). Re-evaluar cuando N≥30 picks adicionales.

**Trigger.** Brier rolling Argentina cruza 0.220 sostenido por >7 días.

**Acción esperada.** Si trigger: PROPOSAL Kelly cap 1.5% Argentina temporal scoped (no global).

---

### `adepor-1fd` — TRIGGER hit_rate cuando N≥30 con xg_*_corto

**Qué es.** Trigger automático: cuando se acumulen ≥30 picks reales con la columna `xg_local_corto`/`xg_visita_corto` calculada (xG con ventana corta ~5 partidos), recomputar `hit_rate_shadow_vs_actual` para evaluar si xG corto mejora prediction.

**Por qué importa.** xG corto vs xG largo (EMA estándar) es debate empírico abierto. Si N≥30 muestra xG_corto > xG_largo en hit, considerar promoción.

**Estado.** Esperando que se llenen los 30 picks con `xg_*_corto` poblado. Hoy N parcial (motor empezó a llenar la columna recientemente).

**Trigger.** N≥30 picks reales con `xg_*_corto IS NOT NULL`.

**Acción esperada.** Recomputar hit cross-cohorte (xg_corto vs xg_largo). Si Δhit > 5pp con CI95_lo > 0 → PROPOSAL.

---

### `adepor-hm9` — TRIGGER auditar CLV (Closing Line Value)

**Qué es.** Trigger: cuando se acumulen ≥30 picks con `clv_pct` calculado (diferencia entre cuota tomada y cuota de cierre Pinnacle), auditar si CLV positivo correlaciona con yield positivo.

**Por qué importa.** CLV positivo (tomar cuota antes de que el bookie la baje) es indicador clásico de "value betting". Si CLV correlaciona con yield → confirma que el motor identifica valor real.

**Estado.** `clv_pct` se calcula en `partidos_backtest`. Esperando acumular N=30.

**Trigger.** N≥30 picks con `clv_pct IS NOT NULL`.

**Acción esperada.** Análisis correlación CLV → yield. Si Pearson r > 0.20 sig → confirma value betting.

---

### `adepor-334` — Reevaluar rho in-sample cuando N>100 por liga

**Qué es.** Trigger: cuando cada liga TOP-5 acumule N>100 partidos liquidados in-sample 2026, recalibrar `rho_calculado` per-liga vía MLE Dixon-Coles sobre datos in-sample (no históricos).

**Por qué importa.** Los `rho_calculado` actuales se derivaron de OOS 2022-2024. Si el régimen 2026 tiene tau distinto (% empates cambiado), recalibrar mejora calibración.

**Estado.** Argentina tiene 83 liquidados, Brasil 71, Inglaterra 38 (no llega a 100). Esperar.

**Trigger.** N>100 partidos liquidados por cada liga TOP-5.

**Acción esperada.** Re-correr `py -m src.nucleo.calibrar_rho` con flag in-sample. Comparar rhos in-sample vs históricos. Si difieren significativamente → bead PROPOSAL para actualizar `ligas_stats.rho_calculado`.

---

### `adepor-tqm` — BACKLOG V5.0 follow-ups

**Qué es.** Lista de mejoras menores derivadas del análisis V5.0 Turquía V12: optimizar performance del lookup V12, validar V12 sobre temps recientes, monitorear drift V12.

**Por qué importa.** V5.0 está en producción (Turquía V12). Mantenimiento longitudinal.

**Estado.** BACKLOG, no urgente.

**Trigger.** Post-promoción de futuras ligas a V12 (cuando `adepor-d7h` o equivalente apruebe).

**Acción esperada.** Cleanup tareas: optimizar `_calcular_probs_v12_lr`, agregar audit V12 vs V0 mensual, etc.

---

## Prioridad P3 — Triggers / metodología

### `adepor-23w` — TRIGGER A/B altitud cuando equipos_altitud completo

**Qué es.** Trigger: re-evaluar piloto altitud (afecta yield ligas LATAM con estadios sobre 2.000 m.s.n.m.) cuando la tabla `equipos_altitud` esté completa Y se acumulen N≥30 picks con altitud aplicada.

**Por qué importa.** Bolivia (La Paz, Sucre) tiene estadios a >3.000m. Local con altitud puede tener ventaja estructural. Análisis A/B previo (`adepor-altitud-ab`) cerró con N insuficiente.

**Estado.** Esperando completar `equipos_altitud` (probablemente parcial).

**Trigger.** Tabla completa + N≥30 picks afectados.

**Acción esperada.** Re-correr piloto. Si efecto altitud sig pos → PROPOSAL Kelly boost local en altitud.

---

### `adepor-57p` — TRIGGER 6 arquitecturas SHADOW cuando N≥80

**Qué es.** Trigger gemelo de `adepor-d7h`: cuando N≥80 picks SHADOW se acumulen, evaluar las 6 arquitecturas paralelas (V0_actual, V1_no_fix5, V2_no_hg, V3_puro, V4_hg_sel, Skellam, V6, V7, V12, V13).

**Por qué importa.** Validación cruzada multi-arquitectura. Si alguna domina V0 con CI95_lo>0, candidato promoción.

**Estado.** Logging activo en `picks_shadow_arquitecturas`.

**Trigger.** N≥80 picks SHADOW liquidados.

**Acción esperada.** Audit comparativo. Promover ganador via PROPOSAL: MANIFESTO CHANGE.

---

### `adepor-j4e` — TRIGGER OOS-por-temp + in-sample mensual

**Qué es.** Trigger recurrente: cada cierre de mes, re-correr análisis OOS-por-temp + in-sample para detectar drifts emergentes (V4.7, M.3, filtros liga, V13).

**Por qué importa.** Sistema de monitoreo continuo. Sin esto, los drifts pueden acumularse silenciosamente.

**Estado.** Recurrente (no se cierra). Se ejecuta cada fin de mes.

**Trigger.** Cierre de mes calendario.

**Acción esperada.** Mensual: ejecutar suite de scripts (`yield_por_temp_v47_y_fix6.py`, `audit_M1_M2_M3_por_año_full.py`, etc.) y anotar resultados en este bead.

---

### `adepor-s7m` — METHODOLOGY: ventana móvil 2-temp en calibrar_rho

**Qué es.** Mejora metodológica de `calibrar_rho.py`: en lugar de usar todas las temps históricas con peso uniforme, aplicar ventana móvil de últimas 2 temps O decay exponencial (α=0.7 → temp más reciente pesa 0.7, temp anterior 0.3).

**Por qué importa.** Si el régimen cambia (ej. 2023 tóxico → 2024 neutro), las temps viejas contaminan el rho calibrado. Decay temporal hace que el rho reaccione más rápido a cambios.

**Estado.** No implementado, propuesto como mejora.

**Trigger.** No tiene trigger automático. Implementación manual cuando se decida.

**Acción esperada.** Modificar `calibrar_rho.py` con flag `--decay 0.7`. A/B sobre OOS 2024 con ventana móvil vs uniforme. Si Brier mejora con CI95_lo > 0 → adoptar.

---

---

## Beads nuevos creados 2026-04-28 (post-audit findings)

### `adepor-a1v` — Construir proxies de pos_backward (calidad estructural)

**Qué es.** Hallazgo del audit forward-vs-backward: pos_local FINAL de la temp
(backward) tiene MÁS poder predictivo que pos forward (runtime). Yields
significativos: TOP-3 backward 2024 +47.8% [+7.2, +87.4] ★, TOP-6 backward
2023 +40.6% [+9.2, +73.8] ★, |div|>5 +24.3% [+2.6, +46.8] ★.

**Por qué importa.** El motor V0 está captando calidad ESTRUCTURAL del equipo
que el bookie subestima. pos_backward NO es usable runtime (info post-partido)
pero sirve como AUDIT que confirma la señal.

**Estado.** Bead creado hoy. Script `analisis/proxy_pos_backward_correlacion.py`
preparado pero no ejecutado. Test: ¿xG_v13 ya correlaciona con pos_backward?
Si Pearson r < −0.3 cross-temp → V13 ya capta señal → bead cierra.

**Trigger.** Ejecutar script + interpretar correlación.

**Acción esperada.** Si V13 correlaciona → cerrar bead (ya tenemos el proxy).
Si NO → construir feature explícito 'calidad_estructural_proxy' y agregarlo
a V13 next iteration.

---

### `adepor-4f9` — Filtro M.4 candidato: bloquear partidos parejos en tabla

**Qué es.** Hallazgo audit posición OOS 2024 N=2,656: yield es **direccional
negativo** en partidos parejos en tabla (`|diff_pos| ≤ 3`):

| diff_pos | N_apost | Yield% | CI95 |
|---|---|---|---|
| L<<V (mismatch local mejor) | 144 | +18.9 | [−9.4, +48.2] |
| L~V (parejos) | 213 | **−14.0** | [−32.1, +4.9] casi sig |
| L>>V (mismatch local peor) | 19 | +23.2 | [−27.9, +75.2] |
| TOP-vs-TOP | 59 | **−25.5** | [−58.4, +9.4] |

**Por qué importa.** El motor V0 sufre cuando los equipos están en niveles
similares en tabla. Mejor performance con mismatch claro de calidad.

**Estado.** Direccional pero NO sig sobre N actual. Requiere validación
N≥200 picks operativos post-implementación.

**Trigger.** Acumular N≥200 picks operativos con feature `diff_pos_pre_partido`
poblada. Probable ETA 2-3 meses.

**Acción esperada.** A/B walk-forward por temp. Si M.4 mejora yield agregado
con CI95_lo > 0 → PROPOSAL: MANIFESTO CHANGE para activar M.4 (extender §M).

---

### `adepor-9ah` — TRIGGER M.3 selectivo Brasil Q4

**Qué es.** Brasil Q4 (cierre Brasileirão, oct-dic) es el **único (liga, bin)
con yield negativo CONSISTENTE en los 3 años OOS**:

| temp | N | Yield% | Sig |
|---|---|---|---|
| 2022 | 35 | −4.9 | no sig |
| 2023 | 42 | −17.9 | no sig |
| 2024 | 48 | **−35.7** | **★ SIG NEG** |

Otros (liga, bin) son inestables cross-año (Argentina Q3, Inglaterra Q4,
Turquía Q4 flipean entre años). Brasil Q4 es la excepción.

**Por qué importa.** Único candidato sólido para M.3 selectivo per-liga.
Cuando lleguen picks Brasil 2026 Q4, podemos confirmar y activar.

**Estado.** Brasil 2026 in-sample tiene SOLO Q1 (Brasileirão recién arrancando,
49 picks). Q4 llegará oct-dic 2026.

**Trigger.** N≥10 picks Brasil 2026 Q4 liquidados (~octubre 2026).

**Acción esperada.** Si yield Brasil 2026 Q4 < 0 → confirmar patrón y proponer
`filtro_picks_v51_m3_per_liga_bin = {"Brasil": [3]}` extensión M.3 selectivo.

**Caso alternativo:** si yield Brasil 2026 Q4 > 0 (régimen 2026 favorable
persiste), DESCARTAR. Confirmaría que el régimen 2026 es estructuralmente
distinto a OOS.

---

### `adepor-z0e` — BUG/DATA: Mojibake en historial_equipos_stats

**Qué es.** Equipos con encoding doble-convertido (mojibake) crean DUPLICADOS:

```
'Instituto (Cordoba)' (correcto?)
'Instituto (c�rdoba)' (mojibake con char reemplazo)
'Instituto (cordoba)' (sin acento)
```

**Por qué importa.**
- EMAs fragmentadas: `Instituto (Cordoba)` y `Instituto (c�rdoba)` calculados
  como equipos distintos.
- Posiciones tabla duplicadas: equipo aparece con N partidos dividido entre
  variantes.
- V13 lookup falla cuando partido tiene una variante y EMA está en otra.
- M.2 (n_acum<60) falsos negativos en equipos veteranos con encoding alterno.

**Estado.** No fix. Bead histórico `adepor-86` documentó mojibake en
`cache_espn/*.json` y aplicó fix a 27 archivos cache, pero `historial_equipos_stats`
acumuló las EMAs antes del fix → persiste.

**Trigger.** Manual cuando se priorice (no urgente, no rompe motor).

**Acción esperada.**
1. Detectar clusters via fuzzy match (Levenshtein < 2 + normalización).
2. Plan migración: nombre canónico por cluster, actualizar todas las tablas.
3. Snapshot DB obligatorio antes.
4. Verificar `gestor_nombres v5.0` para prevenir reincidencia.

---

### `adepor-p4e` — INVESTIGATION: ¿caída Q3 Argentina 2023 = copas internacionales?

**Qué es.** Hipótesis del usuario: el yield V0 cae brutal en Argentina Q3 2023
(−45.7% sig neg) puede explicarse por equipos jugando Libertadores/Sudamericana
en paralelo, llegando cansados a partidos liga local.

**Por qué importa.**
- Argentina Q3 2022: +37.8% sig POS
- Argentina Q3 2023: **−45.7% sig NEG** ★ caída cross-temp
- Argentina Q3 2024: +22.4%

Q3 = mid-temp (~50-75% del año). 2023 cayó en agosto-septiembre 2023.
**Libertadores 2023 fase final agosto-noviembre 2023** = conjunción temporal
consistente con la hipótesis.

10-12 equipos argentinos participaron en copas 2023 (≈50% de la liga).

**Estado.** Hipótesis no testada. Requiere data de copas internacionales
(scraping nuevo o lookup hardcoded por equipo×fecha).

**Trigger.** Cuando se obtenga calendario copas 2022/2023/2024.

**Acción esperada.**
1. Para cada partido Argentina LPF 2023: clasificar si el local jugó copa
   <=7 días antes.
2. Yield V0 con vs sin feature 'local cansado'.
3. Si confirma → feature `days_since_copa_local` a V13 next iteration o
   filtro M.5 candidato 'no apostar local cansado'.
4. Si refuta → otra explicación del 2023 tóxico.

---

## Resumen de prioridades operativas

### Esperando triggers (no acción inmediata)

| Bead | Trigger | ETA | Tipo |
|---|---|---|---|
| `adepor-edk` Layers 1/3 | Decisión usuario | inmediata | PROPOSAL |
| `adepor-09s` Fase 2 | N≥600 in-sample | ~3-4 sem | INFRA crítica |
| `adepor-d7h` / `adepor-57p` | N≥80 SHADOW | continuo | TRIGGER |
| `adepor-1fd` | N≥30 xg_corto | ~2-3 sem | TRIGGER |
| `adepor-hm9` | N≥30 CLV | ~2-3 sem | TRIGGER |
| `adepor-334` | N>100 por liga | ~2-3 meses | TRIGGER |
| `adepor-23w` | tabla altitud + N≥30 | varios meses | TRIGGER |
| `adepor-j4e` | fin de mes | mensual | TRIGGER recurrente |
| `adepor-6rv` | depende de `adepor-09s` | ~3-6 sem | PROPOSAL |
| `adepor-dex` | Brier rolling > 0.220 | observabilidad | OBS |
| `adepor-tqm` | post `adepor-edk` | indefinido | BACKLOG |
| `adepor-s7m` | manual | indefinido | METHODOLOGY |
| **`adepor-a1v`** | manual (script ya escrito) | inmediata | INFRA |
| **`adepor-4f9`** Filtro M.4 | N≥200 picks operativos con diff_pos | ~2-3 meses | INFRA |
| **`adepor-9ah`** Brasil Q4 | N≥10 picks Brasil 2026 Q4 | ~oct 2026 | TRIGGER |
| **`adepor-z0e`** Mojibake | manual cuando se priorice | indefinido | BUG |
| **`adepor-p4e`** Copas Q3 Arg | data copas 2022-2024 obtenida | indefinido | INVESTIGATION |

### Sin trigger inmediato accionable

Los 13 beads restantes esperan eventos (acumulación N, decisiones, fin de mes). **No hay work activo bloqueado** salvo el de Fase 2 que necesita más datos in-sample.

### Próxima ventana de acción esperada

**Mediados de mayo 2026** (~3 semanas):
- N in-sample alcanzará ~600 → `adepor-09s` Fase 2 ejecutable.
- N in-sample EUR top en cierre temporada (Premier 25-26 termina 24 may) → último bin Q4 EUR hasta agosto.
- Argentina cierre Apertura jun 22 → primer dato Q4 Argentina post fix-calendario.

**Agosto 2026:**
- Premier 26-27 arranque → primeros picks EUR Q1 2026-27.
- Re-test M.3 NEW en EUR top con sample diversificado.
