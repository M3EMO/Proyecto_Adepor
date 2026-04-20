# PLAN — Experto Datos Deportivos (Fase 2.0)

> Auditor estadístico del proxy xG y backtester empírico contra realidad.
> Generado el 2026-04-16. READ-ONLY sobre código y DB.

---

## 0. SCOPE Y MÉTODO

- Universo de análisis: `partidos_backtest` con `goles_l IS NOT NULL AND xg_local IS NOT NULL` (N=201).
- Nota: en este snapshot de DB **no hay registros con `estado='Liquidado'`** — todos los 321 partidos están en `'Pendiente'`. Sin embargo, 201 ya tienen `goles_l/goles_v` cargados (consecuencia del flujo de ingesta), lo que permite tratarlos como liquidados de facto para auditar calibración. **Recomiendo al analista-datos verificar por qué `motor_liquidador` no marcó estos como `Liquidado`** — bug separado fuera de mi scope.
- Métricas: MAE entre xG predicho y goles reales por equipo, sesgo (xG−goles) en signo, Brier multiclase 1X2, log-loss multiclase, hit% real vs prob predicha agregada.

---

## 1. MÉTRICAS DE CALIBRACIÓN POR LIGA (calculadas con datos del repo, N=201)

```
liga          N   MAE_xL  MAE_xV   biasL   biasV  avgG  avgXG    BS    LL  real%H  pred%H  real%X  pred%X
Argentina    55   1.000   1.141  +0.509  +0.832  2.22   3.56  0.591  0.987  52.73%  40.89%  16.36%  22.72%
Bolivia       4   1.135   1.340  +1.135  +1.340  3.50   5.97  0.749  1.269  50.00%  47.85%  50.00%  16.15%
Brasil       52   1.115   1.397  +0.731  +1.341  2.50   4.57  0.610  1.026  55.77%  43.88%  23.08%  18.75%
Chile         3   1.378   2.238  +1.378  +2.238  1.00   4.62  0.467  0.796 100.00%  45.12%   0.00%  18.66%
Colombia      4   1.235   1.093  -0.134  +1.093  3.00   3.96  0.669  1.137  50.00%  45.73%  50.00%  20.83%
Ecuador       4   0.590   0.946  +0.590  +0.570  3.00   4.16  0.482  0.820  50.00%  38.93%   0.00%  20.05%
Inglaterra   19   1.208   1.261  +0.913  +1.170  2.79   4.87  0.665  1.106  42.11%  40.93%  26.32%  18.11%
Noruega      24   1.725   1.472  +1.210  +1.295  2.88   5.38  0.650  1.091  33.33%  42.59%  25.00%  17.31%
Peru          4   1.040   1.069  +0.735  +0.512  3.00   4.25  0.711  1.153  25.00%  46.21%  25.00%  19.64%
Turquia      25   1.288   1.283  +0.481  +0.954  3.04   4.47  0.618  1.044  48.00%  44.71%  28.00%  19.12%
Uruguay       4   1.050   0.535  +1.050  +0.513  2.50   4.06  0.648  1.079  25.00%  41.57%  25.00%  20.22%
Venezuela     3   1.478   0.409  +0.568  -0.116  4.00   4.45  0.413  0.731  33.33%  39.98%   0.00%  18.98%
TOTAL       201   1.186   1.267  +0.715  +1.070  2.61   4.40  0.615  1.032  48.76%  42.71%  22.39%  19.71%
```

### Hallazgos cuantitativos:

1. **Sesgo sistémico de sobreestimación de xG en TODAS las ligas con N suficiente** (Argentina, Brasil, Inglaterra, Noruega, Turquía).
   - Sesgo medio del visitante (+1.07) supera al del local (+0.72). El xG_visita está más inflado que el xG_local en la mayoría de ligas.
   - Inglaterra: pred xG_total = 4.87 vs goles_total real = 2.79 (sesgo +2.08 por partido, 75% sobreestima).
   - Brasil: pred 4.57 vs real 2.50 (sesgo +2.07).
   - Argentina: pred 3.56 vs real 2.22 (sesgo +1.34, **el menor sesgo de las ligas top-N**).
   - Esto confirma exactamente lo que dice Reglas_IA.txt §IV-D2 (Fix B y FACTOR_CORR_XG_OU_POR_LIGA): el xG está estructuralmente inflado y el motor_calculadora ya lo compensa para O/U con factores 0.524–0.648 por liga.

2. **Sesgo de empates ya identificado en Reglas_IA §IV.A se confirma**: pred%X (19.71%) vs real (22.39%) globalmente. NO hay sobreestimación sistémica aquí (de hecho infraestima ligeramente). El bloqueo `APUESTA_EMPATE_PERMITIDA = False` parece justificado por desbalance específico, no global.

3. **Sesgo de favorito local**: real%H = 48.76% vs pred%H = 42.71% — el modelo **infraestima la ventaja local en ~6pp** globalmente. Esto coincide con Reglas_IA §IV.H Hallazgo G ("Prior dinámico de ventaja local por liga"), aún pendiente de implementar.

4. **Brier scores** (0 = perfecto, 1 = pésimo en clasificación binaria; 2/3 baseline aleatorio multiclase):
   - Argentina (BS=0.591) es la **mejor calibrada de las top-N**.
   - Bolivia/Peru/Colombia/Inglaterra (BS≈0.66–0.75) son las peor calibradas, aunque Bolivia/Peru/Colombia/Uruguay tienen N≤4 (no concluyente).
   - Log-loss similar: Argentina mejor (0.987), Bolivia peor (1.269).

---

## 2. HIPÓTESIS SOBRE EL "SESGO ARGENTINA" (basada en evidencia empírica del repo)

**Conclusión: el sesgo Argentina detectado en fase 1 NO existe como bug del modelo. Es realidad empírica.**

Evidencia del repo:

- `ligas_stats` muestra que Argentina es la **liga de menor goleo** de las 12: 1.97 goles/partido vs Bolivia 3.66, Noruega 3.17, Inglaterra 2.75, Brasil 2.62. Esto es coherente con el conocimiento público del fútbol argentino (Liga Profesional cerrada y defensiva).
- `historial_equipos` para Argentina (28 equipos con ≥10 partidos) tiene avg fav_home=1.81 vs Inglaterra 2.40 — pero esa baja base es **CORRECTA** dado que la liga marca menos.
- En el backtest empírico: avg_goles_l real Argentina = 1.31 vs xL pred = 1.82 → el sesgo absoluto Argentina (+0.51) es **menor** que el de Inglaterra (+0.91), Brasil (+0.73), Noruega (+1.21). La calibración Argentina es **la mejor de las ligas con N≥19**.

Lo que **sí ocurre** y sí es un problema de modelado (no de captura):

- Como Argentina marca poco y el modelo infla +0.5 a +0.8 igual que en otras ligas, la asimetría delta_xG=|xL−xV| se aplasta mucho. En Argentina avg|xL−xV|≈0.13 vs Inglaterra ≈0.50. Resultado: probabilidades 1X2 casi planas (p1≈p2≈0.38), poca convicción.
- Esto es matemáticamente consistente, no un bug. El modelo refleja correctamente que la liga es competitiva y de bajo goleo. La consecuencia operativa (pocos picks de alta convicción en Argentina) es real, no un artifact.

**Recomendación**: NO modificar EMA Argentina. Lo que sí podría revisarse (con Tech Lead + Experto Apuestas) es si en ligas de bajo delta_xG hay que bajar `MARGEN_PREDICTIVO_1X2 = 0.03` a 0.02 o si simplemente se reportan menos apuestas (resultado correcto del filtro). Esto va a `PROPUESTAS_MATEMATICAS.md` sólo si se decide explorarlo.

---

## 3. DIAGNÓSTICO DEL BUG `total_corners=0` Y `shots=0`

### Evidencia

- `ligas_stats.total_corners = 0` en **las 12 ligas** (todas con `coef_corner_calculado = 0.02` default).
- `partidos_backtest`: de 54 registros con stats raw (`sot_l IS NOT NULL`), `corners_l=0`, `corners_v=0`, `shots_l=0`, `shots_v=0` en el **100% de los casos**. Solo `sot_l` y `sot_v` tienen valores reales (4–6 por partido, plausible).

### Causa raíz (verificada en código)

`src/ingesta/motor_data.py` busca los siguientes nombres en la lista `statistics` que devuelve la API ESPN scoreboard:
- línea 96, 98, 100: `'shotsOnTarget'`, `'cornerKicks'`, `'shots'`
- línea 397, 398: `'cornerKicks'`

El archivo `Ejemplo_Stats_ESPN.txt` (del repo, captura de la API ESPN) muestra que los nombres reales que devuelve la API son:
- `shotsOnTarget` (CORRECTO — único que match)
- `wonCorners` (NO `cornerKicks`)
- `totalShots` (NO `shots`)

**Resultado**: la lectura de córners y shots totales falla silenciosamente para TODOS los partidos. Los 0 se persisten en `partidos_backtest.corners_l/shots_l` y se acumulan como 0 en `estado_ligas[pais]["corners"]`. El cálculo `coef_corner_calculado = round(0.02 * ajuste, 4)` nunca se actualiza porque la condición `if total_corners > 0` siempre falla, y el coef queda en 0.02 default.

### Impacto en el xG híbrido (Reglas_IA §II.A)

Fórmula manifiesto: `(SoT*0.30) + (Shots_off_blocked*0.04) + (Corners*Coef_Liga)`.

- Componente Corners: 0 (siempre).
- Componente shots_off_or_blocked: `max(0, total_shots - sot)` → como `total_shots=0` y `sot>0`, queda 0. **Esto significa que TODOS los disparos fuera/bloqueados también valen 0 en el xG**. La fórmula se reduce de facto a `SoT*0.30`.
- Sólo el componente SoT contribuye al xG_calc. Esto explica parcialmente el sesgo: con un coeficiente único de 0.30 el rango de xG_calc para 4–6 SoT es 1.2–1.8, que multiplicado por 0.70 + 0.30*goles produce los xG observados.

### Caveat de captura

La API ESPN tiene **dos endpoints distintos**:
- Scoreboard (lo que usa motor_data.py): a veces devuelve estadísticas resumidas con nombres distintos al endpoint detalle.
- Summary/team-detail (el del Ejemplo_Stats_ESPN.txt): devuelve `wonCorners`, `totalShots`, etc.

**No puedo verificar 100% sin hacer un GET vivo a la API qué nombres devuelve hoy el scoreboard** — pero la evidencia indirecta (todos los corners=0 y todos los shots=0 en la DB para todas las ligas y todos los partidos) prueba que los nombres actuales `'cornerKicks'` y `'shots'` NO matchean lo que devuelve la API en este momento. **Es un bug de captura, no de escritura** (la escritura funciona, escribe el 0 que recibe).

---

## 4. PROPUESTAS DE TAREAS (numeradas, esfuerzo estimado)

> Toda modificación de fórmula matemática va a `PROPUESTAS_MATEMATICAS.md` (NO implementar sin OK del usuario, §1B del PLAN). Las que NO tocan fórmula sólo necesitan validación del Lead.

### A. Auditorías y backtests adicionales (no tocan fórmula)

1. **Auditoría de captura ESPN scoreboard** (esfuerzo: 1h).
   Pedir a `analista-sistemas` que haga un GET a una URL del endpoint scoreboard que usa motor_data.py y dump del raw `statistics` para confirmar los nombres reales actuales. Reportar a Tech Lead.

2. **Calibración por bucket de probabilidad** (esfuerzo: 2h).
   Reproducir la tabla "predicción 40–50% vs real" del Manifiesto §II.C Fix #5 con los 201 registros actuales. Confirmar si el `+0.042` sigue siendo el valor correcto o si requiere recalibración.

3. **Calibración por delta_xG bucket** (esfuerzo: 2h).
   Reproducir el backtest del Manifiesto §IV.G Hallazgo C (multiplicador stake) con los 201 registros. Verificar que los buckets `[0–0.2)/[0.2–0.3)/[0.3–0.5)/[0.5+)` y los hit% siguen siendo válidos.

4. **Ventaja local por liga (validar Hallazgo G §IV.H)** (esfuerzo: 1h).
   Para cada liga con N≥15: comparar real%H histórico vs p1 promedio del modelo. Tabla de propuesta de PRIOR_HOME_BONUS_POR_LIGA si la divergencia >5pp en alguna liga.

5. **Análisis de calibración por mercado O/U 2.5** (esfuerzo: 2h).
   No alcancé a auditar O/U en este ciclo. Calcular hit% real vs prob_o25 predicha por liga.

### B. Propuestas matemáticas (van a PROPUESTAS_MATEMATICAS.md, requieren OK)

6. **Recalibración de FACTOR_CORR_XG_OU_POR_LIGA** (esfuerzo: 1h).
   Con los sesgos medidos (Inglaterra +2.08, Brasil +2.07, Noruega +2.50, Argentina +1.34, Turquía +1.43): calcular factor empírico = goles_real/xG_pred por liga y comparar con los actuales (Noruega=0.524, Brasil=0.603, Argentina=0.642, Turquía=0.648).

7. **Re-derivar coeficientes de calcular_xg_hibrido** (esfuerzo: 4h, BLOQUEADO por bug #C1).
   Una vez arreglada la captura de corners y shots totales (bug #C1), correr OLS sobre `goles_real ~ sot + shots_off + corners` sobre 201 partidos. Las columnas `sot_l/shots_l/corners_l` ya existen en partidos_backtest precisamente para esto (son una migración explícita de motor_data.py líneas 187–194).

8. **Bloquear Argentina del modo Camino 2 (value hunting) hasta tener N>=50 con xG ajustado** (esfuerzo: trivial).
   En Argentina las probs son ~planas, el value hunting genera muchos falsos positivos. Sólo después de evidenciar empíricamente con `experto-apuestas`.

### C. Bug fixes (van a Tech Lead, NO tocan fórmula)

9. **Fix nombres ESPN en motor_data.py** (esfuerzo: 30min, ALTA PRIORIDAD).
   Cambiar `'cornerKicks'` → `'wonCorners'` y `'shots'` → `'totalShots'` en líneas 75, 77, 98, 100, 397, 398. Verificación previa: confirmar con un GET vivo (tarea #1). Después: re-ejecutar `motor_data.py --rebuild` para regenerar EMA con corners y shots totales correctos. Esto seguramente cambiará los xG predichos materialmente.

10. **Investigar por qué partidos con goles_l no están en estado='Liquidado'** (esfuerzo: ?, fuera de mi scope).
    Pasar a `analista-datos`. Es un bug separado.

---

## 5. DATOS QUE NECESITO Y NO TENGO EN EL REPO

> Estos son los CSVs/fuentes que el Lead debe pedir al usuario humano para profundizar la auditoría.

1. **Ground truth de xG por partido (StatsBomb / Understat / Opta)** para una muestra de las 5 ligas top (Argentina, Brasil, Inglaterra, Turquía, Noruega).
   - Por qué: nuestro xG es un proxy híbrido de stats agregados ESPN, no es xG real basado en posición de tiro/calidad de chance. Sin un ground truth de xG, no podemos saber si nuestro proxy se desvía por sesgo de cálculo o por sesgo de inputs.
   - Mínimo viable: 30 partidos por liga con xG_local_real, xG_visita_real, goles_l, goles_v. CSV con columnas: `liga, fecha, local, visita, xg_local_real, xg_visita_real, goles_l, goles_v`.

2. **Cuotas de cierre de bookmaker (closing odds) para los 201 liquidados** — para CLV.
   - El campo `cuota_cierre_1x2` existe en `partidos_backtest` pero no he validado si está poblado. Si está vacío, no podemos medir si nuestros picks tienen edge sobre el mercado eficiente o sólo sobre cuotas de apertura.
   - Pasar a `analista-datos` para confirmar el estado de poblado de `cuota_cierre_1x2` y `cuota_cierre_ou`.

3. **Confirmar respuesta cruda actual del endpoint ESPN scoreboard** (1 GET).
   - Sin esto no puedo confirmar al 100% que `wonCorners`/`totalShots` son los nombres correctos del scoreboard (mi evidencia es indirecta: el archivo `Ejemplo_Stats_ESPN.txt` es del endpoint summary, no scoreboard).
   - El usuario o `analista-sistemas` puede correr un curl simple a la URL.

4. **Histórico de goles por minuto (no agregados)** — para validar el ajuste de "score effects" §II.A de Reglas_IA.
   - Imposible sin datos minuto-a-minuto. Si no se puede obtener, descartar la auditoría de score effects.

---

## 6. RIESGOS

- **R1**: si el fix de nombres ESPN (#C9) regenera el EMA con nuevos componentes (corners + shots_off), los xG_pred cambiarán materialmente y todas las calibraciones documentadas en Reglas_IA.txt (FACTOR_CORR_XG_OU, divergencia, calibración Fix #5) podrían quedar invalidadas. El re-rebuild requiere re-derivar TODA la calibración matemática del manifiesto. Coordinación con Tech Lead obligatoria.
- **R2**: 8 de las 12 ligas tienen N<25 en el backtest; las métricas para Bolivia/Chile/Colombia/Ecuador/Peru/Uruguay/Venezuela (N=3–4) son **estadísticamente irrelevantes**. Sólo Argentina (55), Brasil (52), Turquía (25), Noruega (24), Inglaterra (19) tienen muestras mínimamente confiables.
- **R3**: el `motor_liquidador` no marca como `Liquidado` partidos que sí tienen `goles_l` cargado (321 'Pendiente' vs 0 'Liquidado'). Hay un fallo upstream que debe diagnosticar `analista-datos`. Si el liquidador está roto, métricas de hit% y yield del `experto-apuestas` están corruptas.

---

## 7. ENTREGABLE INMEDIATO

Este documento. Todas las métricas son derivadas directamente de `fondo_quant.db` con Python sqlite3 + cálculo en memoria — sin asumir, sin proyectar, sin inventar.

Próximo paso: esperar validación del Lead y del usuario para priorizar tareas A1–A5, B6–B8, C9–C10.
