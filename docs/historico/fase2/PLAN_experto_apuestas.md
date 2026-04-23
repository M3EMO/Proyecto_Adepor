# PLAN — Experto en Apuestas (Fase 2.0)

**Autor**: experto-apuestas | **Fecha**: 2026-04-16
**Modo**: READ-ONLY sobre código y DB. Propuestas para validación humana antes de ejecutar.

---

## 0. ESTADO DE LA DB ANALIZADA

- 321 partidos totales en `partidos_backtest`. **Estado pegado en `'Pendiente'`** (debería migrar a `'Liquidado'` el liquidador, pero el campo `estado` no se actualiza — lo único que cambia es `apuesta_1x2` de `[APOSTAR]` a `[GANADA]`/`[PERDIDA]`).
- 201 partidos con `goles_l` y `goles_v` no nulos = **liquidables**.
- De los 201 liquidados: **73 apuestas Op1 1X2** + **60 apuestas Shadow 1X2** + **8 apuestas O/U**.
- 23 picks `[APOSTAR]` con goles ya cargados que el liquidador NO marcó como `[GANADA]`/`[PERDIDA]` (bug del liquidador, no del modelo). Para este análisis los normalicé yo en código.
- **Hallazgo G: INACTIVO** en todas las ligas (todas tienen N < 50 liquidados por liga).
- **Shadow ≠ Op1**: 22 picks "Op1 solo" (45% hit) vs 9 "Shadow solo" (33% hit). El shadow filtra mejor lo malo pero también pierde lo bueno; Op1 sigue mejor.

---

## 1. MÉTRICAS BASE — TODO EL PERÍODO LIQUIDADO

| Mercado / Source | n | Hit % | Yield | Profit |
|---|---|---|---|---|
| **1X2 Op1 (activa)** | 73 | **49.3%** | **+81.2%** | +$97,722 |
| **1X2 Shadow (control)** | 60 | 46.7% | +77.0% | +$115,500 |
| **O/U 2.5** | 8 | 37.5% | -16.5% | -$2,239 |

> **Lectura**: Op1 supera a Shadow en hit (+2.6pp) y en yield (+4.2pp). Los tres fixes (Hallazgo G, Fix #5 calibración, Hallazgo C delta-stake) **agregan valor real** medible. Mantener.
> **Hit < 55%** total. Pero: el yield positivo proviene de cuotas medias (3.0+) — el sistema gana plata aunque pierda más de la mitad. La métrica relevante es **yield ponderado por stake**, no hit raw.

---

## 2. TABLA YIELD + HIT% POR LIGA × MERCADO × SHADOW/OP1

| Liga | 1X2 Op1 (n) | Hit | Yield | OU (n) | Hit | Yield | Shadow (n) | Hit | Yield |
|---|---|---|---|---|---|---|---|---|---|
| **Argentina** | 14 | 50% | +53.5% | 0 | – | – | 12 | 50% | +67.0% |
| **Brasil** | 31 | 48% | **+124.3%** | 1 | 0% | -100% | 21 | 57% | **+150.1%** |
| **Inglaterra** | 7 | 57% | +104.0% | 5 | 40% | -4.3% | 4 | 50% | +66.2% |
| **Noruega** | 9 | **67%** | +100.9% | 1 | 0% | -100% | 10 | 50% | +67.0% |
| **Turquia** | 11 | 36% | +35.4% | 1 | 100% | +105% | 12 | 25% | -14.2% |
| **Chile** | 1 | 0% | -100% | 0 | – | – | 1 | 0% | -100% |

> Brasil es el motor de yield; Turquia e Inglaterra-OU son los lastres.

---

## 3. TABLA POR CAMINO DE APUESTA

| Camino | n | Hit | Yield | Veredicto |
|---|---|---|---|---|
| **C1 Normal (favorito modelo)** | 33 | **54.5%** | +67.4% | OK — backbone del sistema |
| **C2 Value Hunting (underdog max EV)** | 24 | **29.2%** | **+10.0%** | **DESTRUCTOR** — hit muy bajo |
| **C2B Desacuerdo (modelo vs mercado)** | 15 | **66.7%** | **+200.9%** | **Joya** — sostener y proteger |
| **C3 Alta Convicción (EV ≥ 1.0)** | 1 | 100% | +483% | n insuf, mantener |

> El **Camino 2 está rompiendo el sistema**. Todos los picks Brasil-VISITA-prob<40% (10 casos, 10% hit, -29% yield) son C2: el modelo dice "el visitante tiene 35-38% de prob, la cuota paga 4.0+, hay value matemático" — pero la realidad es que el local gana 9 de 10 veces. El "value" es el bias estructural xG_visita inflado del que advierte Reglas_IA.txt §II.C.

---

## 4. TABLA POR CAMINO × LIGA (subconjuntos relevantes)

| Camino | Liga | n | Hit | Yield |
|---|---|---|---|---|
| C1 | Argentina | 7 | 71% | +99.8% |
| C1 | Brasil | 13 | 54% | +73.5% |
| C1 | Noruega | 5 | 60% | +75.9% |
| C1 | Turquia | 7 | 43% | +33.3% |
| **C2B** | **Brasil** | 7 | **86%** | **+393.5%** |
| C2B | Inglaterra | 3 | 67% | +141.2% |
| C2B | Argentina | 3 | 33% | +36.7% |
| C2B | Turquia | 2 | 50% | +153.6% |
| **C2** | **Brasil** | **10** | **10%** | **-29.4%** |
| C2 | Argentina | 4 | 25% | -13.9% |
| C2 | Turquia | 2 | 0% | -100% |
| C2 | Inglaterra | 3 | 67% | +118% |
| C2 | Noruega | 4 | 75% | +132% |

---

## 5. TOP 5 BUCKETS GANADORES (alta convicción real)

1. **Brasil C2B (Desacuerdo)**: n=7, hit 86%, yield **+393%**. Patrón: modelo ve LOCAL favorito con prob 40-50% y mercado pone VISITA favorito (cuota local 2.5-4.0). Acertó 6 de 7.
2. **Cuota ≥ 5.0**: n=7, hit 86%, yield **+390%**. Apuestas-bombazo cuando el modelo discrepa fuerte. Casi todos C2B/C3.
3. **Brasil 1X2 LOCAL**: n=17, hit 65%, yield **+221%**. La eficiencia local en Brasil supera 50% real; el modelo lo captura.
4. **Prob 45-50%**: n=21, hit **81%**, yield **+215%**. Sweet spot del modelo — ahí Fix #5 (calibración +0.042) está actuando bien.
5. **Delta xG 0.2-0.3**: n=11, hit **82%**, yield **+171%**. Hallazgo C funcionando: dominancia clara de xG predice ganador con altísima fiabilidad. Multiplicador x1.15 actual está conservador.

## 6. TOP 5 BUCKETS PERDEDORES (deberíamos no entrar)

1. **Brasil C2 (Value hunting underdog)**: n=10, hit **10%**, yield **-29%**, profit -$3,943. **EL DESTRUCTOR**. Casi todos VISITA con p=33-38%.
2. **Turquia C2 (Value hunting)**: n=2, hit 0%, yield -100%, -$3,536.
3. **Turquia VISITA todos**: n=3, hit 0%, yield -100%. Patrón empate (3 partidos terminaron empate, pick visita perdió).
4. **OU Inglaterra OVER cuando xG alto pero falso**: n=5, hit 40%, yield -4%. Modelo predice OVER por xG hinchado (avg xG=4.87, ratio real 0.57 — la calibración 0.627 que usa es muy optimista para PL).
5. **Prob 33-40% global (todos los caminos)**: n=21, hit **29%**, yield +7%. Casi break-even. La mayoría son C2 Brasil. Bucket "ruido" — el FLOOR_PROB_MIN de 33% es muy permisivo en este rango cuando se combina con C2.

---

## 7. SIMULACIONES CONTRAFÁCTICAS (qué pasa si...)

| Cambio | n bets | Hit | Yield | Δ vs base |
|---|---|---|---|---|
| **BASE actual** | 73 | 49.3% | +81.2% | — |
| Bloquear C2 (value hunting underdog) GLOBAL | 49 | **59.2%** | **+116.1%** | **+34.9pp yield, +9.9pp hit** |
| Bloquear sólo Brasil-Camino2 | 63 | 55.6% | +95.1% | +13.9pp |
| Bloquear sólo Brasil-VISITA con p<40% | 64 | 54.7% | +93.4% | +12.2pp |
| Subir FLOOR a 0.40 sólo Brasil/Arg/Tur/Chi | 55 | **61.8%** | **+120.9%** | **+39.7pp** |
| Subir FLOOR a 0.40 GLOBAL | 48 | 60.4% | +120% | +38.8pp |

> El `FLOOR_PROB_MIN = 0.33` es demasiado bajo en ligas sudamericanas/turca: el rango 33-40% concentra la mayor pérdida.
> El cambio más limpio es **subir FLOOR a 0.40** (o equivalentemente: deshabilitar el Camino 2 underdog en p<0.40). Conserva C1, C2B y C3 (los tres con yield > +60%).

---

## 8. PROPUESTAS DE CONFIGURACIÓN PRIORIZADAS

> **Importante**: ninguna de estas modifica fórmulas (II.A-K). Sólo constantes de la sección IV (filtros / decisión). Cualquier cambio sigue el workflow §1B del PLAN — pasa por `PROPUESTAS_MATEMATICAS.md` y espera OK del usuario.

### P1 — Subir FLOOR_PROB_MIN de 0.33 a 0.40 (ALTA PRIORIDAD)
- **Evidencia**: bucket prob 33-40% tiene 29% hit y +7% yield (n=21). Subiendo el floor: n cae a 48-55, yield sube a +120%, hit a 60%.
- **Riesgo**: pierde el C3 alta-convicción que funciona con prob ≥ 0.33 (1 caso, +483%). Se podría diferenciar: floor 0.33 SOLO para C3 (EV ≥ 1.0), floor 0.40 para C1/C2/C2B.
- **Implementación sugerida**: dos constantes — `FLOOR_PROB_NORMAL=0.40`, `FLOOR_PROB_ALTA_CONV=0.33`.

### P2 — Restringir o eliminar Camino 2 (Value Hunting underdog) (ALTA PRIORIDAD)
- **Evidencia**: C2 global = 24 bets, 29% hit, +10% yield. Bloquearlo sube yield base de +81% a +116%, hit de 49% a 59%. C2B sigue activo (es el que sí funciona en desacuerdo).
- **Causa raíz probable**: C2 explota "value matemático" en underdog VISITA, pero el bias estructural xG_visita inflado (Reglas_IA.txt §II.C, +0.49 promedio) infla artificialmente p2 → genera EV positivo falso → C2 abre apuestas que pierden 90% del tiempo.
- **Opciones** (de menos a más invasiva):
   1. Subir prob_min de C2 a 0.40 (matar C2 en bucket 33-40%).
   2. Bloquear C2 cuando `pk == VISITA` y `liga ∈ {Brasil, Argentina, Turquia, Chile}` mientras N_liquidados_por_liga < 30 (datos insuficientes para confiar en el "value" del visitante).
   3. Eliminar C2 completamente y dejar sólo C1/C2B/C3.

### P3 — Recalibrar `FACTOR_CORR_XG_OU_POR_LIGA` con datos propios actuales (MEDIA PRIORIDAD)
- **Evidencia (mi cálculo)**:
  - Argentina: ratio observado **0.623** (config actual: 0.642) — ligero ajuste a la baja.
  - Brasil: ratio **0.547** (config: 0.603) — **bajar a 0.55**.
  - Inglaterra: ratio **0.573** (config: 0.627) — **bajar a 0.57**.
  - Noruega: ratio **0.534** (config: 0.524) — OK, sin cambio.
  - Turquia: ratio **0.679** (config: 0.648) — **subir a 0.68**.
- **Impacto**: con xG_total más bajo, más partidos caen en zona UNDER (xG_cal < 2.25), donde el modelo ahora dice PASAR. Posiblemente abre más UNDER reales y bloquea más OVER falsos.

### P4 — Subir `MARGEN_XG_OU_OVER` de 0.30 a 0.40 (MEDIA PRIORIDAD)
- **Evidencia**: 6 de 8 OU son OVER, 3 GANADAS / 5 PERDIDAS = 37.5% hit, yield -16.5%. Mirando los detalles: en 4 de las 5 perdedoras los goles reales fueron 0-2 (UNDER) con xG_total > 4.5 (sobreestimación cruda). El margen 0.30 actual no protege suficiente contra el bias OVER.
- **Riesgo**: bloquear más OVER reduce volumen pero el yield negativo justifica el corte.
- **Alternativa**: dejar `APUESTA_OU_ACTIVA=False` hasta acumular n≥30 OU liquidados.

### P5 — Aumentar `DELTA_STAKE_MULT_MED` de 1.15 a 1.25 (BAJA PRIORIDAD)
- **Evidencia**: bucket delta_xG 0.2-0.3 tiene **82% hit** y +171% yield (n=11). Subir multiplicador a 1.25 captura más de esa señal.
- **Riesgo**: cap MAX_KELLY_PCT actúa después, no se descontrola el riesgo.

### P6 — Excluir Turquia VISITA hasta acumular más data (BAJA PRIORIDAD)
- **Evidencia**: 3 picks VISITA, 0 GANADAS, yield -100%. Patrón inquietante: 3 empates y picks visita perdiendo. n bajo (3) — no es estadísticamente concluyente, pero pega fuerte por tamaño de stake.
- **Acción**: monitorear; si en próximos 10 picks Turquia-VISITA el hit sigue < 30%, bloquear.

### P7 — Diferenciar `MARGEN_PREDICTIVO_1X2` por liga (BAJA PRIORIDAD)
- Actualmente fijo 0.03 global. La rotura del C2 sugiere que en ligas con alta divergencia mercado-modelo (Brasil, Turquia) el margen 3% es muy permisivo. Subirlo a 0.05 en ligas problemáticas reduciría picks borderline.

---

## 9. NECESITO DATOS EXTRAS

Para análisis más profundo (no bloqueante para P1-P7):

1. **Cuotas históricas de cierre (CLV)**: la columna `cuota_cierre_1x2` está casi siempre NULL. Sin CLV no puedo medir si el modelo "vence al mercado" en sentido estricto (sólo mido yield post-resultado).
2. **Resultados ML completos para validar Hallazgo G**: necesitamos N≥50 liquidados por liga. Hoy: Argentina 55, Brasil 52, Noruega 24, Inglaterra 19, Turquia 25, Chile <5. Brasil y Argentina ya están listas para activar Hallazgo G — proponer al `tech-lead` validar la activación natural.
3. **Líneas O/U distintas a 2.5** (Asian handicap, O/U 1.5, 3.5): ampliaría espacio de apuestas O/U sin pelear contra la zona-trampa 2.25-2.80.
4. **Backtest de Camino 2 con muchos más partidos** (target: n≥80 C2 antes de eliminar definitivamente). Hoy n=24, suficiente para sospechar pero no para sentencia. Entre tanto, restringir vía P2 opción 1 o 2.
5. **Datos de árbitro (`arbitros_stats`)**: explorar si ciertos árbitros sesgan resultados (ya existe `arbitro` en partidos_backtest pero no se usa en la decisión).

---

## 10. RIESGOS IDENTIFICADOS

- **R1**: Cualquier cambio de constante reduce N de apuestas. Con 73 bets actuales el ruido estadístico es alto. Recomiendo activar cambios uno por uno y monitorear 30+ partidos antes de la siguiente iteración.
- **R2**: Bug de `liquidador.py` no actualiza `estado='Liquidado'` ni picks shadow. Esto invalida la query `WHERE estado = 'Liquidado'` que usa `aplicar_hallazgo_g` en motor_calculadora. **El Hallazgo G NUNCA SE ACTIVARÁ** mientras este bug exista. Es un bug de `analista-datos`/`tech-lead`, no mío, pero lo flageo aquí.
- **R3**: El experimento Op1 vs Shadow se rompe porque el liquidador tampoco resuelve `apuesta_shadow_1x2`. Hoy nadie ve qué bandos ganan más. Mismo bug que R2.
- **R4**: El sesgo xG_visita estructural (Reglas_IA §II.C) es la causa raíz del C2 destructivo. Cualquier corrección en motor_data.py podría hacer que el C2 vuelva a tener sentido — re-evaluar tras Fix.

---

## 11. RESUMEN EJECUTIVO PARA LEAD

- Yield Op1 actual **+81.2%** con hit **49.3%** sobre n=73. Buen sistema, pero con un bucket destructor identificado.
- **Cortar Camino 2 (value hunting underdog) sube yield a +116% y hit a 59%**. Cambio máximo impacto / mínimo costo.
- **Subir FLOOR de 0.33 a 0.40** logra efecto similar (+120% yield, hit 60%) — preferible si queremos preservar la estructura "Cuatro Caminos" intacta.
- Brasil es la liga rey: C2B Desacuerdo da **+393% yield** con 86% hit. **Proteger ese bucket a toda costa**.
- O/U está en negativo (yield -16.5%, n=8): recalibrar `FACTOR_CORR_XG_OU_POR_LIGA` con datos actuales o desactivar `APUESTA_OU_ACTIVA` hasta n≥30.
- Bug heredado: `liquidador.py` no marca estado='Liquidado' ni resuelve apuestas shadow. **Bloquea activación natural del Hallazgo G** y rompe métrica de validación Op1 vs Shadow. Flag al `analista-datos`/`tech-lead`.

**Próximo paso**: esperar OK del usuario sobre P1+P2 (los dos cambios de mayor impacto) y registrar en `PROPUESTAS_MATEMATICAS.md` antes de implementar.
