# PLAN — Diseñador del Excel (`disenador-excel`)

**Team**: `adepor-fase2`
**Owner**: `disenador-excel`
**Lead/juez**: `team-lead`
**Fecha**: 2026-04-16
**Scope**: `Backtest_Modelo.xlsx` + sección Excel de `src/persistencia/motor_sincronizador.py` (LOC 1-1100, V9.2/V9.3).
**Estado**: PROPUESTA — sin ejecutar nada hasta validación humana (Fase 2.0 del PLAN.md).

---

## 1. INVENTARIO ACTUAL DEL EXCEL

Workbook `Backtest_Modelo.xlsx` contiene **4 hojas** (orden actual):

### 1.1. Hoja `Dashboard` (creada con `create_sheet(..., 0)` → primera al abrir)
- **Dimensiones**: A1:D34, layout vertical Métrica | Total | 1X2 | O/U.
- **Bloques**:
  1. Título + fecha + bankroll (filas 1-2, merge A:D).
  2. Header columnas (fila 3): `Metrica | Total | 1X2 | O/U`.
  3. **RESULTADOS FINANCIEROS**: Ganancia neta, Yield, Volumen apostado, N apuestas liquidadas.
  4. **TASA DE ACIERTO**: % Acierto P, % Acierto $, % Acierto all.
  5. **ESTADISTICA INFERENCIAL**: T-score, P-Value, Fracción Kelly.
  6. **CALIBRACION DEL MODELO**: BS Sistema, BS Casa, BS Global (Brier Score).
  7. Leyenda semáforo (1 línea italic).
  8. **ESTRATEGIA ACTIVA** (V4.3): 10 filas key/value de configuración.
- **Semáforos vigentes**:
  - Yield: `>=5%` verde, `>=0%` amarillo, `<0%` rojo.
  - Acierto: `>=55%` verde, `>=45%` amarillo, `<45%` rojo.
  - BS: `<=0.50` verde, `<=0.65` amarillo, `>0.65` rojo (menor mejor).
  - P-Value: `<=0.05` verde, `<=0.10` amarillo, `>0.10` rojo (menor mejor).
- **Nota observada**: el dashboard NO muestra distribución por liga, ni racha actual, ni drawdown, ni equity curve, ni cuántas apuestas hay activas/pendientes hoy.

### 1.2. Hoja `Backtest` (raw + fórmulas vivas)
- **Dimensiones reales**: A1:AC323 (29 columnas, 322 partidos).
- **Headers exactos** (consumidos por `motor_sincronizador.HEADERS`, también referenciados por scripts en `analisis/`):
  ```
   1 Fecha           11 Liga             21 Stake 1X2
   2 ID Partido      12 Prob 1           22 Stake O/U 2.5
   3 Partido         13 Prob X           23 Acierto
   4 Local           14 Prob 2           24 P/L Neto
   5 Visita          15 Prob +2.5        25 Equity Curve
   6 Cuota 1         16 Prob -2.5        26 BS Sistema
   7 Cuota X         17 Goles L          27 BS Casa
   8 Cuota 2         18 Goles V          28 Incertidumbre
   9 Cuota +2.5      19 Apuesta 1X2      29 Auditoria
  10 Cuota -2.5      20 Apuesta O/U 2.5
  ```
- **Fórmulas vivas** (NO se pre-evalúan; las recalcula Excel al abrir, `wb.calculation.fullCalcOnLoad = True`):
  - `Apuesta 1X2` (col S) y `Apuesta O/U 2.5` (col T): `=IF(...,"[GANADA] LOCAL",...)` — salida es string `[APOSTAR|GANADA|PERDIDA] LOCAL/EMPATE/VISITA/OVER 2.5/UNDER 2.5`.
  - `Acierto` (col W): `[ACIERTO]`, `[FALLO]`, `[PREDICCION] LOCAL/EMPATE/VISITA`, `[PASAR] Margen Insuf`.
  - `P/L Neto` (col X): suma 1X2 + O/U usando `SEARCH("[GANADA]", ...)` — depende del bracket.
  - `Equity Curve` (col Y): cumulativo `=Y(r-1) + X(r)`, fila 2 arranca desde bankroll.
  - `BS Sistema` (col Z) y `BS Casa` (col AA): Brier Score por partido.
- **Conditional Formatting actual**:
  - Filas A:R coloreadas por país: Argentina `#DEEAF1`, Brasil `#E2EFDA`, Noruega `#FFF2CC`, Turquia `#EAE0F0`, Inglaterra `#FCE4D6`. **Faltan**: Bolivia, Chile, Colombia, Ecuador, Peru, Uruguay, Venezuela (van sin color → fondo blanco).
  - Col S/T (apuestas): verde `[GANADA]`, rojo `[PERDIDA]`, amarillo `[PASAR]`, azul `[APOSTAR]`.
  - Col X (P/L): verde `>0`, rojo `<0`.
  - Col W (Acierto): verde `[ACIERTO]`, rojo `[FALLO]`, azul-prediccion `[PREDICCION]`, amarillo `[PASAR]`.
- **Auto-filter**: activado fila 1 columnas A:AC.
- **Freeze**: `A2`.
- **Distribución de picks observados (322 partidos actuales)**:
  - Activos 1X2: GANADA 22 (LOCAL 17 + VISITA 5), PERDIDA 28 (LOCAL 13 + VISITA 15), Pasar 218, vacío 51. Hit rate ≈44%.
  - Activos O/U: GANADA 2, PERDIDA 2, Pasar 309, vacío 9. Hit rate ≈50% (n muy bajo).

### 1.3. Hoja `Sombra` (auditoría comparativa Op1 vs Op4 shadow)
- **Dimensiones**: A1:N114.
- 14 columnas: Fecha | Partido | Liga | Apuesta Op1 | Stake Op1 | Resultado Op1 | P/L Op1 | Apuesta Op4 | Stake Op4 | Resultado Op4 | P/L Op4 | Dif P/L | Op1 Win | Op4 Win.
- 2 bloques: detalle por partido (filas 5-103) + resumen comparativo de KPI (filas 105-112).
- **Resultado** se escribe como string plano: `"GANADA"` / `"PERDIDA"` / `"PENDIENTE"` / `"-"` (sin brackets — ojo: distinto del Backtest que sí usa `[GANADA]`).
- **Mejor**: marcador `"Op1"` / `"Op4"` / `"="`.
- Leyenda: verde ganadora, rojo perdedora, amarillo pendiente.

### 1.4. Hoja `Resumen` (agregado por liga)
- **Dimensiones**: A1:H17.
- Headers: `Liga | Apuestas | Ganadas | Perdidas | % Acierto | P/L Neto | Yield | Volumen` + fila TOTAL al final.
- 12 ligas listadas (incluyendo las 7 sin actividad: Bolivia, Colombia, Ecuador, Peru, Uruguay, Venezuela, Chile).
- CF: Yield/PL/Acierto pintados con verde/amarillo/rojo según umbrales en `motor_sincronizador.py:1078-1085`.
- **NO usa SUMIF/COUNTIF**: los totales se calculan en Python y se escriben como literales. No hay fórmulas vivas en esta hoja.

### 1.5. Inventario de fórmulas Excel relevantes
- **NO existen fórmulas SUMIF/COUNTIF** en ninguna hoja del workbook actual. La compatibilidad con `'GANADA'`/`'PERDIDA'`/`'ANULADA'` la garantiza el bracket pattern `[GANADA]` que `SEARCH` usa en col X (P/L Neto). El string `'ANULADA'` **no aparece** en ningún lugar del workbook ni del código actual — está protegido por el PLAN como reserva.
- Lo que SÍ usa `SEARCH(...)` y por tanto bloquea cambios en strings:
  - Col X `P/L Neto`: busca `[GANADA]`, `[PERDIDA]`, `LOCAL`, `EMPATE`, `VISITA`, `OVER`, `UNDER`.
  - Col W `Acierto`: tokens `[ACIERTO]`, `[FALLO]`, `[PREDICCION]`, `[PASAR]`.
  - CF de cols S, T, W: `SEARCH("[GANADA]"...)`, etc.

---

## 2. HALLAZGOS DE UX (información clave NO visible o enterrada)

Ordenados por valor para el usuario operativo (que abre el Excel para decidir si apostar hoy):

### H1 — No hay filtro/sección "Apuestas activas hoy" (CRÍTICO)
El usuario debe scrollear 322 filas para encontrar las apuestas con `[APOSTAR]` que aún no se liquidaron. No hay vista filtrada ni KPI "stake en juego ahora".

### H2 — Equity curve no se grafica
Existe la columna `Equity Curve` con valores numéricos por fila pero **no hay chart** ni mini-sparkline en el Dashboard. El usuario ve $95,482 P/L neto pero no si ese número viene de subida lineal o de un drawdown enmascarado.

### H3 — Drawdown actual y racha de pérdidas no se muestran
Estrategia Sección IV.E del manifiesto activa modo defensivo tras 5 pérdidas consecutivas (`MAX_KELLY_PCT_DRAWDOWN=1.0%`). **El Dashboard no muestra**: cuántas pérdidas consecutivas llevamos, drawdown actual desde peak, ni si estamos en modo normal o defensivo.

### H4 — Performance por liga sólo en `Resumen`, NO en Dashboard
El usuario tiene que cambiar de pestaña para saber que Brasil rinde yield 117% (n=32) y Chile -100% (n=1). Heatmap por liga sería el primer dato a leer (decide si poner stake mañana en una liga concreta).

### H5 — Filas por liga sin colorear: 7 de 12 ligas (Bolivia, Chile, Colombia, Ecuador, Peru, Uruguay, Venezuela)
`PAISES_CF` solo contempla 5 de las 12 ligas activas en DB. Backtest tiene partidos de las 7 faltantes que se ven sin color → confusión visual.

### H6 — Col `Auditoria` muestra solo "NO" en 322/322 partidos
Información sin valor. O bien se elimina/oculta, o se reusa para algo útil (por ejemplo: marcar `'D2B'` cuando el pick vino del Camino 2B desacuerdo, `'C3'` cuando vino del Camino 3 alta convicción → permite analizar yield por estrategia).

### H7 — Col `Acierto` está vacía en 322/322 partidos (raw value)
La fórmula es `=IF(P12="","",...)` — vive como fórmula y depende de Excel evaluándola al abrir. En `data_only=True` openpyxl lee la última caché → vacío. **No es bug** pero confunde al inspeccionar. Acción: documentar o forzar `cached_value`.

### H8 — Brier Score sin contexto de comparación temporal
BS Sistema 0.61 vs BS Casa 0.62 → estamos 0.01 mejor. ¿Es eso bueno? El dashboard debería mostrar: "modelo gana al mercado en X de últimas Y apuestas" o tendencia (mejorando/empeorando últimos 30 partidos).

### H9 — Cuotas mostradas sin destacar la elegida
Cols 6/7/8 muestran C1/CX/C2 todas iguales en formato. Si el pick fue LOCAL, debería resaltarse `Cuota 1` con borde grueso o fondo distinto en esa fila — facilita verificar visualmente que el stake aplicó a la cuota correcta.

### H10 — Falta panel "Próximos partidos sin liquidar" (apuestas live)
Partidos con `estado='Calculado'` y `goles_l IS NULL` son los próximos con apuesta abierta. Hoy se mezclan con histórico ya liquidado en la misma vista cronológica.

### H11 — Stake en filas vacías muestra `0` (no `-`)
Cuando `[PASAR]`, las cols `Stake 1X2` / `Stake O/U` muestran `0` con formato `#,##0.00` → "0.00". Visualmente saturado. Mejor: vacío o guion.

### H12 — Hoja `Resumen` lista 7 ligas con todos ceros
Ocupan filas sin información. Filtrar para mostrar solo ligas con `apuestas > 0` (o agruparlas al final con texto "Sin actividad").

### H13 — Falta indicador de calibración por bucket de probabilidad
El dashboard agrega BS global pero no muestra si el bucket 33-40% acierta menos que el 50%+, que es exactamente lo que el manifiesto V4.5 (`corregir_calibracion`) intenta corregir. Tabla bucketizada pediría poco código y daría señal accionable.

### H14 — Sin timestamps de "última actualización por liga"
Si Argentina lleva 3 días sin actualizar fixtures pero Brasil sí, no hay forma de saberlo desde el Excel.

---

## 3. MOCKUPS TEXTUALES (ASCII) — bloques visuales propuestos

### M1 — Dashboard rediseñado (header KPI cards)

```
+================================================================================+
|                       DASHBOARD DE RENDIMIENTO — V9.4                          |
|     Generado: 16/04/2026 22:48   |   Bankroll: $100,000.00   |   Modo: NORMAL  |
+================================================================================+

+-- KPI CARDS (fila 3-5) --------------------------------------------------------+
| EQUITY ACTUAL  | P/L NETO     | YIELD GLOBAL  | DRAWDOWN ACTUAL | RACHA      |
|   $195,482.71  |  +$95,482.71 |    +71.31%    |     -2.4%       |   +3 W     |
|     [verde]    |    [verde]   |    [verde]    |    [amarillo]   |  [verde]   |
+--------------------------------------------------------------------------------+

+-- APUESTAS ACTIVAS HOY (fila 7-12) -------------------------------------------+
| Pendientes liquidar:  4 partidos   |   Stake en juego: $8,250.00              |
| - 17/04 Boca vs River      [APOSTAR] LOCAL  cuota 2.10  stake $2,500          |
| - 17/04 Flamengo vs Palmeiras [APOSTAR] OVER 2.5  cuota 1.85  stake $2,000    |
| ...                                                                            |
+--------------------------------------------------------------------------------+

+-- HEATMAP POR LIGA (fila 14-26) ----------------------------------------------+
|  Liga       | N  | Hit% | Yield  | P/L         | Sparkline equity            |
|  Brasil     | 32 | 47%  | +117%  | +$46,565    | ▁▂▄▆█ (verde)               |
|  Argentina  | 14 | 50%  |  +53%  | +$16,232    | ▂▄▅▆▇ (verde)               |
|  Noruega    | 10 | 60%  |  +76%  | +$15,366    | ▃▄▅▇█ (verde)               |
|  Inglaterra | 12 | 50%  |  +57%  | +$10,656    | ▂▃▄▅▆ (verde)               |
|  Turquia    | 12 | 42%  |  +41%  |  +$9,165    | ▁▂▃▅▆ (amarillo)            |
|  Chile      |  1 |  0%  | -100%  |  -$2,500    | ▇▁__  (rojo, n bajo)        |
|  ─ Sin actividad ─                                                            |
|  Bolivia, Colombia, Ecuador, Peru, Uruguay, Venezuela: 0 apuestas             |
+--------------------------------------------------------------------------------+

+-- TABLA EXISTENTE (Total | 1X2 | O/U) -------------- (fila 28+) ---------------+
[ Resto del dashboard original sin tocar: Yield, Volumen, T-score, P-Value, BS ]
```

### M2 — Hoja `Backtest` con highlights por estado

Agregar formato por filas usando estado de la apuesta (no solo país):

```
| Fecha     | Partido           | Liga       | Cuota 1 | ... | Apuesta 1X2          | P/L     |
| 16/03/26  | Instituto vs Indep| Argentina  |  1.65*  | ... | [GANADA] LOCAL  ✓    | +$1,575 |  ← borde grueso verde
| 17/03/26  | Caykur vs Samsuns | Turquia    |  2.10   | ... | [PERDIDA] LOCAL ✗    | -$2,500 |  ← borde grueso rojo
| 17/04/26  | Boca vs River     | Argentina  |  2.10*  | ... | [APOSTAR] LOCAL  ⏳   |   ---   |  ← borde grueso azul (live)
| 16/04/26  | River vs Indep    | Argentina  |  1.95   | ... | [PASAR] EV insuf      |   ---   |  ← gris claro semitransparente
```

`*` = cuota de la apuesta elegida (resaltada con bold + fondo `#FFE699`).
Símbolos UTF-8 son cosméticos; el string base se mantiene `[GANADA] LOCAL`.

### M3 — Mini panel de drawdown (en Dashboard)

```
+-- GESTIÓN DE RIESGO ACTUAL ---------------------------------------------------+
| Equity peak histórico: $198,210.45  (alcanzado: 14/04/2026)                   |
| Equity actual:          $195,482.71                                           |
| Drawdown desde peak:    -1.38%       [verde si < 5%]                          |
| Racha actual:           +3 ganadoras consecutivas                             |
| Pérdidas consecutivas:  0 (umbral defensivo: 5)                               |
| MAX_KELLY_PCT vigente:  2.5%   ← MODO NORMAL                                  |
+--------------------------------------------------------------------------------+
```

### M4 — Heatmap de calibración por bucket de probabilidad (Dashboard inferior)

```
+-- CALIBRACIÓN POR BUCKET -----------------------------------------------------+
| Bucket prob   | N apuestas | Predicho | Real    | Gap     | Status            |
| 33-40%        |    14      |  37.0%   | 28.6%   | -8.4pp  | rojo  (sobreestima)|
| 40-50%        |    23      |  45.2%   | 52.2%   | +7.0pp  | verde (corregido) |
| 50-60%        |    18      |  54.8%   | 55.6%   | +0.8pp  | verde             |
| 60-70%        |    12      |  64.1%   | 66.7%   | +2.6pp  | verde             |
| 70%+          |     6      |  73.3%   | 83.3%   | +10pp   | verde (con. alta) |
+--------------------------------------------------------------------------------+
```

Esta tabla es lectura directa de columna `Prob X/1/2` vs columna `Acierto`. Aporta señal accionable: si el bucket 33-40% sigue sobreestimando, hace falta extender Fix #5 (`corregir_calibracion`) a ese rango. **Solo lectura. No modifica fórmula matemática.**

### M5 — Color coding completo por liga (12 ligas, no 5)

```
PAISES_CF propuesto (paleta accesible WCAG AA, sin saturar):
  Argentina   #DEEAF1  (azul muy claro)        ← actual
  Brasil      #E2EFDA  (verde muy claro)       ← actual
  Noruega     #FFF2CC  (amarillo muy claro)    ← actual
  Turquia     #EAE0F0  (lavanda)               ← actual
  Inglaterra  #FCE4D6  (durazno)               ← actual
  Bolivia     #F2DCDB  (rosa pálido)           ← NUEVO
  Chile       #DDEBF7  (celeste lechoso)       ← NUEVO
  Colombia    #FFF4E5  (crema)                 ← NUEVO
  Ecuador     #E8F0E0  (oliva clara)           ← NUEVO
  Peru        #F8E1E1  (coral pálido)          ← NUEVO
  Uruguay     #E0E8F0  (gris-azul)             ← NUEVO
  Venezuela   #F0E0E8  (rosa-lavanda)          ← NUEVO
```

---

## 4. STRINGS QUE PRESERVO BIT-A-BIT

Lista exhaustiva — NO toco ninguno de estos strings (case-sensitive, espacios incluidos):

### 4.1. Estados de apuesta (PROTEGIDOS por PLAN.md §1A y §1D)
- `'GANADA'`
- `'PERDIDA'`
- `'ANULADA'`  *(reservado, no aparece en código actual pero protegido)*

### 4.2. Tokens con bracket usados por `SEARCH(...)` en fórmulas Excel
- `'[GANADA]'`
- `'[PERDIDA]'`
- `'[APOSTAR]'`
- `'[PASAR]'`
- `'[ACIERTO]'`
- `'[FALLO]'`
- `'[PREDICCION]'`

### 4.3. Picks 1X2 (literales en fórmulas y código Python)
- `'OPERAR LOCAL'` / `'OPERAR VISITA'` / `'OPERAR PASAR'` *(sintaxis del manifiesto, ojo: el Excel actual concatena `[APOSTAR] LOCAL` — preservar ambas formas)*
- `'LOCAL'`, `'EMPATE'`, `'VISITA'` (substrings buscados con `SEARCH`)
- `'[APOSTAR] LOCAL'`, `'[APOSTAR] EMPATE'`, `'[APOSTAR] VISITA'`
- `'[GANADA] LOCAL'`, `'[GANADA] EMPATE'`, `'[GANADA] VISITA'`
- `'[PERDIDA] LOCAL'`, `'[PERDIDA] EMPATE'`, `'[PERDIDA] VISITA'`

### 4.4. Picks O/U
- `'OVER 2.5'`, `'UNDER 2.5'`
- `'OVER'`, `'UNDER'` (substrings)
- `'[APOSTAR] OVER 2.5'`, `'[APOSTAR] UNDER 2.5'`
- `'[GANADA] OVER 2.5'`, `'[GANADA] UNDER 2.5'`
- `'[PERDIDA] OVER 2.5'`, `'[PERDIDA] UNDER 2.5'`

### 4.5. Estados de partido (compartidos con DB)
- `'Pendiente'`, `'Calculado'`, `'Liquidado'`, `'Finalizado'`

### 4.6. HEADERS de la hoja `Backtest` (29 columnas)
Preservo exactamente los textos del dict `HEADERS` (líneas 28-37 de motor_sincronizador.py). Los headers son referenciados por `analisis/analisis_filtros.py`, `analisis/analisis_desacuerdo.py` y `analisis/contraste.py` — verificar antes de cualquier rename.

### 4.7. Nombres de hojas
- `'Dashboard'`, `'Backtest'`, `'Sombra'`, `'Resumen'` (no agrego/renombro hojas en Fase 2.0; eventuales hojas nuevas en propuestas para Fase 2.2 con OK del usuario).

### 4.8. Strings `[PASAR] *` con razones (NO toco la lista de razones)
Razones observadas en el Excel actual: `Sin Cuotas`, `Sin Valor`, `Margen Predictivo Insuficiente (<5%)`, `Riesgo/Beneficio`, `EV Insuf (X<Y)`, `xG Margen Insuf (X, delta=...)`, `Floor Prob (X<33%)`, `Overlap`. Estos los genera `motor_calculadora.py` — NO es mi scope. Solo me aseguro de que el CF sigue identificando `[PASAR]` por el bracket inicial.

---

## 5. TAREAS PROPUESTAS (numeradas y priorizadas)

Orden = valor para el usuario operativo (decide qué apostar mañana) × esfuerzo de implementación. Estimaciones en horas-Claude.

### Prioridad CRÍTICA (impacto alto, esfuerzo bajo)

1. **T1 — Ampliar `PAISES_CF` a 12 ligas** (1h)
   Agregar 7 entradas nuevas a la tupla `PAISES_CF` con paleta del mockup M5. Cero cambios en strings, solo CF nuevo. **Riesgo: 0**.

2. **T2 — Filtrar hoja `Resumen` para excluir ligas con `apuestas == 0`** (1h)
   En el loop `for liga, s in sorted(stats_liga.items()):` añadir `if s['apuestas'] == 0: continue` (o moverlas a un bloque "Sin actividad" al pie). **Riesgo: 0** — solo afecta layout, no fórmulas.

3. **T3 — Reemplazar `0` por vacío en cols Stake cuando no hay apuesta** (0.5h)
   Cambiar `val if val and val > 0 else 0` por `val if val and val > 0 else None` en líneas 938-940. Verificar que `f_pl_neto` sigue tolerando celdas vacías (ya usa `IFERROR`). **Riesgo: bajo** — validar que `IFERROR` cubre.

### Prioridad ALTA (impacto alto, esfuerzo medio)

4. **T4 — Bloque KPI Cards en Dashboard** (mockup M1, header) (3h)
   Agregar filas 3-5 nuevas al Dashboard con: Equity actual, P/L Neto, Yield global, Drawdown actual, Racha actual. Calcular en `calcular_metricas_dashboard` reutilizando `bets_1x2 + bets_ou`. Solo lectura, no toca lógica de cálculo. **Riesgo: bajo**.

5. **T5 — Bloque "Apuestas activas hoy" en Dashboard** (mockup M1) (3h)
   Filtrar `[APOSTAR]` con `gl IS NULL`. Listar fecha, partido, pick, cuota, stake. Limitar a 10 entradas + "y N más...". **Riesgo: bajo**.

6. **T6 — Heatmap por liga en Dashboard** (mockup M1) (2h)
   Mover/copiar la tabla de `Resumen` al Dashboard (filas inferiores) con sparkline texto (solo bloque-Unicode, no chart). El usuario ve performance por liga sin cambiar de pestaña. **Riesgo: bajo**.

7. **T7 — Panel de Drawdown y Racha** (mockup M3) (2h)
   Calcular equity peak, drawdown actual, pérdidas consecutivas. Mostrar el `MAX_KELLY_PCT` vigente leyendo el flag `DRAWDOWN_THRESHOLD` desde `config_sistema.py`. **Riesgo: bajo** (read-only de constantes).

### Prioridad MEDIA (valor directo, esfuerzo medio-alto)

8. **T8 — Resaltar la cuota elegida en cols 6-10** (3h)
   Después de escribir cuotas, leer `ap1x2`/`apou` y aplicar bold + fondo amarillo claro a la celda C1/CX/C2 o CO/CU correspondiente. **Riesgo: bajo**.

9. **T9 — Heatmap de calibración por bucket** (mockup M4) (4h)
   Función nueva en `calcular_metricas_dashboard`: agrupar partidos por bucket de prob ganadora `[33-40, 40-50, 50-60, 60-70, 70+)` y comparar con tasa real de acierto. Renderizar tabla en Dashboard (no toca fórmulas matemáticas; solo agrega visualización). **Riesgo: 0** — requiere autorización si afecta `corregir_calibracion`. NO la toco.

10. **T10 — Equity Curve mini-chart** (4h)
    `openpyxl.chart.LineChart` simple sobre col Y. Embeber al pie del Dashboard. **Riesgo: bajo** (es un gráfico nativo Excel, no afecta fórmulas).

### Prioridad BAJA (mejoras cosméticas)

11. **T11 — Documentar columna `Auditoria`** (1h)
    Hoy 322/322 filas dicen `"NO"`. Confirmar con `tech-lead` si se planea poblarla con tags `D2B`/`C3`/`Shadow` (Camino 2B/3 + Shadow). Si no, agregar nota en Dashboard "col 29 reservada".

12. **T12 — Sparkline equity por liga en `Resumen`** (3h)
    Sparklines reales (no chars Unicode) con `openpyxl.worksheet.scenario` no soporta nativo — usaríamos imagen PNG generada con matplotlib. **Tiene fricción de dependencias** — proponer pero no priorizar.

### Tareas de DOCUMENTACIÓN (siempre antes de tocar código)

13. **T13 — Documentar contrato strings → SEARCH** en `docs/fase2/EXCEL_CONTRATO_STRINGS.md` (1h)
    Tabla exhaustiva: qué string busca cada fórmula, qué ocurre si se renombra. Sirve a futuros agentes para no romper el modelo.

14. **T14 — Documentar headers consumidos externamente** (1h)
    Auditar `analisis/*.py` y `adepor_eval_review.html` para confirmar qué columnas leen por nombre. Resultado a `docs/fase2/EXCEL_HEADERS_CONSUMIDORES.md`.

---

## 6. DEPENDENCIAS CON OTROS AGENTES

- **`tech-lead`**: si propongo cambiar el orden o número de columnas, debe aprobar (afecta consumers en `analisis/`).
- **`analista-datos`**: T11 (col `Auditoria`) requiere su input sobre qué metadata se planea persistir en DB.
- **`experto-apuestas`**: T9 (heatmap calibración) duplica/complementa lo que él vaya a analizar — coordinar para no repetir tabla en dos lugares.
- **`analista-sistemas`**: que valide que ningún data flow pisa los nuevos bloques del Dashboard.
- **NO hay dependencia con**: `experto-deportivo`, `junior-1`, `junior-2`.

---

## 7. RIESGOS IDENTIFICADOS

- **R1**: Si renombro un header de la hoja `Backtest`, los scripts en `analisis/` que lean por nombre se rompen. **Mitigación**: T14 audita primero.
- **R2**: Si modifico el bracket pattern (ej. `[GANADA]` → `[GANADA] ✓`), las fórmulas `SEARCH("[GANADA]",...)` siguen funcionando, pero `_resultado_1x2` en Python (`if "[GANADA]" in ap`) también — verificar con tests sintéticos antes de cualquier cambio.
- **R3**: Aumentar el número de hojas o de filas del Dashboard puede afectar `freeze_panes='A4'` y la leyenda inferior. Validar manualmente en cada cambio.
- **R4**: Color coding por liga con 12 colores corre riesgo de saturación visual y solapamiento con CF de cols S/T (que ya pinta verde/rojo/amarillo). **Mitigación**: usar pasteles muy claros (luminance > 90%) y dejar que el CF de columna gane (`stopIfTrue=True`).
- **R5**: Hoja `Sombra` usa string plano `"GANADA"` (sin bracket) y `Backtest` usa `"[GANADA]"`. Si unifico el formato puedo romper el pipeline aguas arriba que solo lee `Sombra`. **Mitigación**: NO unificar en Fase 2.0.
- **R6**: `wb.calculation.fullCalcOnLoad = True` requiere que Excel/LibreOffice recalcule al abrir. Si el usuario abre con un viewer que no recalcula, las celdas con fórmula se muestran vacías. **No es nuevo**, pero si agrego más fórmulas debo mantener compatibilidad.

---

## 8. RESUMEN EJECUTIVO (para Lead)

- **Inventariado**: 4 hojas (Dashboard 34 filas, Backtest 322 filas × 29 cols, Sombra 114 filas, Resumen 17 filas). NO hay SUMIF/COUNTIF; sí hay 5 fórmulas vivas (cols S, T, W, X, Y, Z, AA) que dependen de strings con bracket.
- **14 hallazgos UX** priorizados; los más críticos: falta panel "apuestas activas hoy", falta drawdown actual, 7 ligas sin color, equity sin gráfico.
- **14 tareas propuestas** con estimaciones (rango 0.5h-4h cada una). Total Fase 2.0 ≈ 3h (solo plan + documentación). Fase 2.2 ejecución ≈ 27h si se aprueban todas.
- **Cero riesgo a strings protegidos**: todos los `'GANADA'`/`'PERDIDA'`/`'ANULADA'` y picks `'LOCAL'`/`'VISITA'`/`'OVER'`/`'UNDER'` quedan bit-a-bit.
- **Bloqueo crítico antes de ejecutar**: T13 + T14 (auditar consumidores externos de headers) deben correr antes de cualquier cambio que toque la hoja `Backtest`.

**Estado**: PROPUESTA. Espero validación humana vía Lead antes de ejecutar tarea alguna (Fase 2.0 → 2.1 del PLAN.md).
