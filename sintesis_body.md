# SINTESIS RESEARCH ADEPOR-RESEARCH CONSOLIDADA

**Fecha**: 2026-04-25
**Sintesis por**: critico-sintesis (auditor jefe)
**Inputs recibidos**: 4/4
- inv-apuestas -> yield+Brier+Kelly (bead adepor-mcn, 15 papers, 7 comments)
- inv-stats-ligas -> stats 16 ligas (bead adepor-zbc, 5 comments)
- inv-form -> form/rachas Boca + EMA improvements (bead adepor-d4r, 4 comments v2)
- inv-xg -> research xG (NO RECIBIDO DIRECTAMENTE EN MI INBOX - bead_id no provisto, referenciado por scope)

**Caveat de auditoria**: el input de inv-xg no llego como SendMessage al critico-sintesis. Lead confirmo que el equipo esta idle. Hallazgos potencialmente cubiertos por inv-xg quedan marcados como [NO VERIFICADO POR CRITICO]. La sintesis es defensiva - no asumo hallazgos no transmitidos.

---

> ## ANEXO DE ACTUALIZACION 2026-04-26
>
> Este documento se preserva con el veredicto original del 2026-04-25 como evidencia
> auditable. Los items que fueron ejecutados o cuyos hechos cambiaron tras la sintesis
> se anotan inline con bloques `[ANEXO 2026-04-26]` debajo del veredicto original.
>
> **Sintesis de cambios entre 2026-04-25 y 2026-04-26:**
> - 1.1 equipos_altitud Bolivia: EJECUTADO en modo SHADOW A/B (commit `359605f`).
> - 1.2 rho EPL 5 temporadas: EJECUTADO + extendido a 5 ligas EUR (commit `f9d32ce`).
> - 1.4 CLV en backtest: EJECUTADO (commit `e9af2b9`).
> - 2.2 HG threshold: corrigida afirmacion factual — Argentina y Brasil YA estaban
>   activos al momento de la sintesis. Manifesto V4.6 §IV.H formaliza la lectura.
>   Veto conceptual del critico (no bajar threshold) sigue VIGENTE.
> - 4.1.A / 5.A2 EMA dual SHADOW: EJECUTADO (commit `e9c4b76`, 333 equipos).
> - Gap inv-xg: parcialmente cerrado por trabajo posterior (commits `dd25dec`,
>   `3840acb`, `8ddb07c`, `f88a70b` — bead `adepor-bgt`, walk-forward LATAM).
>
> Items NO modificados: 1.3, 1.5, 2.1, 2.3, 2.4, 3.x, 4.2.x, 4.3, Veredicto Boca.

---

## SECCION 1 - APLICABLES YA (sin PROPOSAL)

Cambios a parametros NO protegidos por el Manifiesto, mejoras a scripts auxiliares, fuentes de datos.

### 1.1 [APROBADO] Verificar uso activo de tabla equipos_altitud para Bolivia
- **Origen**: inv-stats-ligas (adepor-zbc)
- **Claim**: Chumacero (paper externo) cuantifica +1.48 gol/partido en Bolivia por altitud. La Seccion II.G del Manifiesto YA tiene multiplicadores (Visita x0.75 zona muerte / Local x1.35), aplicados desde tabla estatica equipos_altitud.
- **Verificacion necesaria**: confirmar (a) que equipos_altitud esta poblada para todos los equipos bolivianos, (b) que motor_calculadora consulta efectivamente esa tabla en cada calculo. Si esta dormido, es la mejora mas rentable inmediata.
- **N**: paper Chumacero (literatura externa, solido) + Manifiesto ya implementado.
- **Costo**: 30min (query DB + verificar log motor_calculadora).
- **Riesgo**: BAJO (es verificacion, no cambio de logica).
- **Veredicto**: **APROBADO** - ejecutar como primera accion.

> **[ANEXO 2026-04-26 - ESTADO: DONE en SHADOW]**
> - Verificacion: tabla `equipos_altitud` esta poblada y motor_calculadora la consulta.
> - Ademas se monto A/B SHADOW Bolivia+Peru via `scripts/analisis/altitud_ab.py` y
>   `scripts/backfill_shadow_xg_altitud.py`. Commit principal: `359605f`.
> - Resultados parciales N=6 partidos: DIFERIDO con bead `adepor-23w` esperando N>=30.
> - 3 snapshots A/B persistidos en `analisis/altitud_ab_*.json` (2026-04-26).

### 1.2 [APROBADO] Recalibrar rho EPL con ventana 5 temporadas pooled
- **Origen**: inv-stats-ligas (adepor-zbc)
- **Claim**: rho_MLE=0 piloto EPL es probable artifact de temporada 24-25 (4 peor en %draws historica, Opta lo califica de "noise").
- **Accion**: extender ventana de calibrar_rho.py a 5 temporadas historicas EPL, no solo 24-25. Esto NO toca el Manifiesto (RHO_FALLBACK=-0.09 sigue siendo el fallback global protegido); solo mejora el script de calibracion.
- **N**: 5 temporadas EPL ~= 1900 partidos, robusto.
- **Costo**: 2-4h (modificar calibrar_rho.py, descargar football-data.co.uk multi-season).
- **Riesgo**: BAJO (script auxiliar, output va a tabla rho_por_liga, reversible).
- **Veredicto**: **APROBADO**.

> **[ANEXO 2026-04-26 - ESTADO: DONE + EXTENDIDO]**
> - EPL: recalibrado via MLE externo con multi-temporada (commit `f9d32ce`,
>   bead `adepor-1vt`).
> - Alcance ampliado mas alla del plan original a 5 ligas EUR: EPL, La Liga,
>   Bundesliga, Serie A, Ligue 1. Outputs en `analisis/rho_recalibrado_adepor-1vt.json`
>   y aplicados via `analisis/rho_update_adepor-1vt.sql`.
> - Bootstrap CI 95%: `analisis/bootstrap_rho_epl_adepor-wxv.json`.
> - Documentacion deep-dive: `analisis/diagnostico_rho_inglaterra_espana.py`.
> - Bead seguimiento: `adepor-cae` (BUG grid) + `adepor-s7m` (METHODOLOGY ventana movil).

### 1.3 [RECLASIFICADO] Pooled prior LATAM secundarias hasta N>=50
- **Origen**: inv-stats-ligas (adepor-zbc)
- **Claim**: Bolivia/Chile/Col/Ecu/Per/Uru/Ven con small-sample bias confirmado (%empate, %loc, gol_avg internos divergen >5pp del externo).
- **Accion**: en motor_calculadora, cuando una liga tiene N<50 liquidados, usar promedio_liga POOLED LATAM en vez de promedio_liga propia para la regresion Bayesiana N0_ANCLA.
- **Riesgo identificado por critico**: tocar la formulacion Bayesiana es modificacion al Manifiesto Seccion II.B. ESTO NO ES "APLICABLE YA" sino que requiere PROPOSAL. **Reclasificado a Seccion 2.3**.
- **Veredicto critico**: **MOVIDO A SECCION 2** - clasificacion original del investigador era incorrecta.

### 1.4 [APROBADO] Integrar CLV (Closing Line Value) como metrica complementaria
- **Origen**: inv-apuestas (adepor-mcn)
- **Claim**: Estudios industria - bettors con CLV+ consistente tienen ROI 2-3x mayor. Adepor podria detectar degradacion del modelo con N=50 via CLV antes de drawdown realizado.
- **Accion**: agregar columna cuota_cierre a partidos_backtest y metrica derivada CLV en motor_backtest. Solo agrega instrumentacion, no toca logica de decision.
- **N**: literatura industria (no academico anclaje unico - caveat de inv-apuestas).
- **Costo**: 4-6h (agregar scrape de cierre + calculo + dashboard).
- **Riesgo**: BAJO (metrica observacional, no cambia decisiones).
- **Veredicto**: **APROBADO**.

> **[ANEXO 2026-04-26 - ESTADO: DONE]**
> - Captura `cuota_cierre` agregada a `partidos_backtest`. CLV calculado separado
>   por mercado (1x2 / O/U). Commit: `e9af2b9`.
> - Migracion historica: `scripts/migrate_clv_pct.py`.
> - Pendiente operativo: dashboard de CLV agregado por liga (no parte de esta entrega).

### 1.5 [DIFERIDO] EV-min 5% como sweet spot para mercados ineficientes
- **Origen**: inv-apuestas (adepor-mcn)
- **Claim**: industria sugiere 3% high liquidity, 5% low liquidity.
- **Estado actual Adepor**: EV escalado por confianza (3%/8%/12% por bucket de prob). El 5% lineal NO es claramente superior al esquema escalado actual.
- **Veredicto**: **DIFERIDO** - el esquema actual esta calibrado por backtest interno. Cambiar requiere re-backtest. No hay claim cuantitativa de mejora, solo de estar dentro de rango.

---

## SECCION 2 - REQUIEREN PROPOSAL MANIFIESTO

Cambios que tocan constantes protegidas o logica de motor_calculadora/motor_data.

### 2.1 [DIFERIDO con sospecha overfit] Penalizacion multi-stake correlacionado
- **Origen**: inv-apuestas (adepor-mcn)
- **Claim**: 1X2 + O/U mismo partido tienen correlacion 0.30-0.50 (Gaussian copula). Adepor asume independencia -> sobreestima edge cuando ambas se ejecutan.
- **Manifiesto Seccion II.I** ya tiene "Ajuste de Covarianza" para apuestas en mismo (Liga, Dia) con factor 1/sqrt(N). NO cubre 1X2+O/U mismo partido especificamente.
- **Riesgo**: aplicar (1-rho^2) introduce un parametro nuevo (rho 1X2-O/U) que requiere calibracion. Riesgo de overfit alto si se calibra sobre el mismo backtest interno.
- **Solucion segura**: o restringir 1 apuesta/partido (regla dura, sin parametro), o calibrar rho con N>=200 partidos donde ambas se ejecutaron simultaneamente.
- **N actual**: NO TENGO DATO - verificar cuantos partidos en partidos_backtest tienen ambas apuestas activas.
- **Veredicto**: **DIFERIDO** - valido teoricamente pero requiere medir cuantos casos con doble apuesta hay antes de proponer.

### 2.2 [VETADO] Activar Hallazgo G antes de N>=50 por liga
- **Origen**: NO recibido en research, pero detectado por critico al revisar Manifiesto Seccion IV.H.
- **Estado**: HALLAZGO_G_ACTIVO=True, pero N_MIN_HALLAZGO_G=50 no se alcanza en ninguna liga aun.
- **Cualquier propuesta de bajar N_MIN**: **VETADO automaticamente** por mi parte. El threshold 50 es defensa anti-overfit.

> **[ANEXO 2026-04-26 - CORRECCION FACTUAL]**
> - El estado del 2026-04-25 ("no se alcanza en ninguna liga aun") era INCORRECTO al
>   momento de escribirlo. Argentina (N=79, freq_real_local=0.494) y Brasil (N=65,
>   freq_real_local=0.539) YA superaban el threshold N=50 en esa fecha.
> - El Manifesto fue corregido en V4.6 §IV.H para reflejar la lectura real:
>   "ACTIVO en Argentina y Brasil; INACTIVO en el resto hasta alcanzar N>=50".
> - El **veto conceptual del critico SIGUE VIGENTE**: no proponemos bajar el threshold
>   N=50, solo se documenta correctamente que ese threshold ya se cruzo en 2 ligas.
> - El SHADOW de 6 arquitecturas (commit `10d0279`, bead `adepor-57p`) re-evalua
>   el efecto neto de HG y Fix #5 con N>=80 antes de cualquier cambio de estado.

### 2.3 [DIFERIDO] Pooled prior LATAM (movido desde 1.3)
- **Origen**: inv-stats-ligas (adepor-zbc)
- **Razon de PROPOSAL**: cambio en como se calcula el promedio_liga input al esquema Bayesiano (Seccion II.B Manifiesto). Es modificacion de formula, aunque no de constante.
- **Riesgo**: si un equipo de liga LATAM con N<50 se mueve a "pool LATAM", su comportamiento depende de que el pool sea representativo. Si el pool oculta heterogeneidad real (Chile vs Ecuador vs Bolivia tienen sport effects distintos), introduce sesgo.
- **N**: el propio investigador reconoce divergencia >5pp interno vs externo. Esto sugiere que SI hay un problema. Pero el fix correcto puede ser "usar baseline externo soccerstats" (no pooling) en vez de "pooled LATAM" (mezcla heterogenea).
- **Veredicto**: **DIFERIDO** - propuesta valida pero el mecanismo elegido (pooling vs external baseline) requiere debate. El investigador no separo las dos opciones.

### 2.4 [DIFERIDO] EMA dual / DEMA / Kalman / form_factor (ver Seccion 4 dedicada)

---

## SECCION 3 - DESCARTADOS

### 3.1 [DESCARTADO] "Racha 14 invicto Boca" como justificacion de fix
- **Origen**: caso planteado por usuario, contradicho por inv-form
- **Razon**: inv-form confirma honestamente que la DB solo trackea liga; los 5 partidos de liga muestran EMA reflejando correctamente el xG crudo (~1.12-1.17/partido). La "racha 14" incluye Copa Libertadores que NO esta en partidos_backtest.
- **Veredicto**: el fix NO debe disenarse para optimizar contra la "racha 14". Debe disenarse para el problema real (divergencia goles vs xG, ver Seccion 4 y Veredicto Boca).

### 3.2 [DESCARTADO] Ajuste post-COVID a goal inflation / home advantage
- **Origen**: inv-stats-ligas (adepor-zbc)
- **Razon**: home advantage ya restaurado (literatura unanime); goal inflation NO se transfiere a LATAM (Argentina/Ecuador siguen 2.0).
- **Veredicto**: **DESCARTADO** - no hacer nada.

### 3.3 [DESCARTADO con caveat] Bajar Kelly de 0.025 a 0.05 (o viceversa)
- **Origen**: inv-apuestas (adepor-mcn)
- **Razon**: ambos valores son defensibles. Sun&Boyd 2018 + Uhrin 2021 validan adaptive fractional Kelly. NO hay paper anclaje numerico que diga "0.025 vs 0.05" textualmente. Es juicio practico del autor del motor.
- **Veredicto**: **DESCARTADO** - sin evidencia robusta para mover, mantener MAX_KELLY_PCT_NORMAL=2.5%.

### 3.4 [DESCARTADO] Opcion B xG / NNLS multivariable redux
- **Origen**: ningun investigador propuso re-evaluar.
- **Razon**: ya VETADO en project_opcion_B_xg_veto.md por 3 agentes en abril 2026. Ningun hallazgo de este research lo revive.
- **Veredicto**: **DESCARTADO** - sigue VETADO.

### 3.5 [DESCARTADO] Brier vs EV como criterio unico
- **Origen**: inv-apuestas (adepor-mcn) - confirma que NO es uno-o-el-otro
- **Razon**: literatura distingue 3 niveles (estructural / calibracion / decision). Aplicar EV<5% VETO a parametros estructurales es error categorico.
- **Veredicto**: **DESCARTADO** - pero esto NO es para no hacer nada, es para asegurar que las propuestas estructurales se evaluen con log-loss/Brier descompuesto, no con EV. Ver Seccion 5 accion #2.

---

## SECCION 4 - EMA IMPROVEMENTS (seccion dedicada)

Ranking consolidado de inv-form (update v2, bead adepor-d4r) mas auditoria critica.

### 4.1 APLICABLES SIN PROPOSAL - AGREGADOS PARALELOS

Ningun hallazgo de EMA improvements puede ir a produccion sin tocar la logica del Manifiesto Seccion II.B, porque cualquier cambio al calculo del xG_efectivo final es modificacion de formula. PERO se pueden agregar como columnas nuevas en historial_equipos para analisis SHADOW sin tocar produccion.

#### 4.1.A [APROBADO en SHADOW] Agregar columnas xg_ema_corto con alfa=0.40
- **Origen**: inv-form (recomendacion #1)
- **Accion**: en motor_data.py, calcular EMA corto en paralelo al actual y guardar en historial_equipos. NO usar en motor_calculadora (queda en SHADOW).
- **Razon critico**: esto es OBSERVACION, no cambio de logica. Se puede ejecutar 30 dias sin riesgo.
- **N requerido**: 30 dias o N>=15 equipos con divergencia ratio>1.3 (criterio de inv-form).
- **Costo**: 4-8h (modificacion motor_data + migracion tabla).
- **Riesgo**: BAJO (campo nuevo, no usado en decision).
- **Veredicto**: **APROBADO en modo SHADOW**.

> **[ANEXO 2026-04-26 - ESTADO: DONE]**
> - EMA dual SHADOW implementado en `motor_data.py` (alfa_corto + alfa_largo).
> - `historial_equipos` extendida con columnas paralelas. Backfill historico
>   completado para 333 equipos. Commit: `e9c4b76`.
> - Baseline persistido en `analisis/ema_dual_baseline_20260425_232235.json`.
> - Comparativos: `scripts/analisis/comparativo_ema_dual.py`.
> - Trigger de re-evaluacion: 30 dias / N>=15 equipos con ratio>1.3 (criterio
>   original de inv-form preservado).

### 4.2 REQUIEREN PROPOSAL FORMAL

#### 4.2.A [DIFERIDO con auditoria] EMA dual en produccion (recomendacion #1 inv-form)
- **Claim de inv-form**: para Boca con alfa_corto=0.40, capturaria upturn en 2-3 partidos vs ~7 actuales.
- **Auditoria critico**:
  - **VENTAJA**: self-correcting cuando los EMAs convergen. NO toca alfa_largo.
  - **RIESGO 1 (overfit por liga)**: alfa_corto requiere calibracion por liga via MLE. Ligas LATAM con N<50 no van a tener calibracion robusta - se cae en mismo problema que ya conocemos.
  - **RIESGO 2 (funcion de combinacion)**: w = f(divergencia entre EMAs) NO esta especificada. Es lineal? Logistica? Threshold? Cada eleccion agrega un grado de libertad. Inv-form no detallo.
  - **RIESGO 3 (caso Boca especifico)**: el problema de Boca NO es EMA - el propio inv-form lo dice ("EMA refleja correctamente"). Es ratio goles/xG = 1.60. EMA dual con alfa_corto=0.40 NO resuelve esto: capturaria rachas de xG real, pero el problema es luck overperformance que el EMA no puede ver porque no esta en el xG crudo.
- **Veredicto critico**: **DIFERIDO** - propuesta interesante pero el caveat #3 es decisivo. Si Boca gano 4 de 5 con xG crudo de 1.12-1.17 (Boca) vs 1.10 (rivales), el EMA dual hubiera predicho lo mismo. El EMA dual es bueno para detectar mejora REAL de xG, no luck.

#### 4.2.B [VETADO con condicion] form_factor multiplicador clamp [0.7, 1.3]
- **Claim de inv-form**: ratio(goles_reales / xG_modelo) ultimos 5P, aplicado como multiplicador post-Bayesiano.
- **Auditoria critico**:
  - Este es exactamente el patch que SI habria afectado a Boca (1.60 -> clamp 1.30 -> xG 1.15->1.50).
  - PERO: la literatura citada por inv-form (Miller-Sanjurjo 2018) dice "ratio 1.60 sobre 5P es comun por luck, pero >50P si distingue skill". Aplicarlo con N=5 es exactamente el escenario donde la literatura advierte que NO se puede separar skill de luck.
  - CONCLUSION: implementar form_factor con N=5 seria overfit a corto plazo. Backtest historico podria dar bien por suerte.
- **Veredicto**: **VETADO sobre N=5**. Si se quiere implementar, requiere N>=20 ultimos partidos como ventana minima. Pero a N=20, el efecto se diluye.

#### 4.2.C [DIFERIDO] STES (Taylor 2004)
- **Riesgo**: cambio fundamental al motor de EMA. PROPOSAL formal requerido.
- **Veredicto**: DIFERIDO - sin evidencia interna, basarse solo en literatura es insuficiente para tocar Seccion II.B.

### 4.3 DESCARTADOS

- **DEMA/TEMA paralelo**: inv-form lo descarta - sin ganancia clara vs EMA dual.
- **Kalman state-space**: >2 semanas dev. inv-form lo descarta para Adepor ahora.
- **N0_ANCLA dinamico**: tocaria constante protegida del Manifiesto. Sin evidencia, **VETADO** por critico.
- **Alfa adaptativo por desviacion (Bayesian Weighted Dynamic, arxiv 2508.05891)**: literatura interesante pero introduce parametros adaptativos por equipo. Riesgo overfit alto. **DIFERIDO**.

---

## SECCION 5 - RECOMENDACION PRIORIZADA

### Accion #1 - Verificar equipos_altitud Bolivia (1 hora)
- **Beneficio esperado**: si esta dormido, +1.48 gol/partido es la correccion mas grande disponible.
- **Riesgo**: BAJO (verificacion, no cambio).
- **Trabajo**: 30min query + 30min revisar logs motor_calculadora.

### Accion #2 - Implementar EMA dual SHADOW (4-8 horas)
- **Beneficio esperado**: 30 dias de data SHADOW para evaluar si captura form real distinto del EMA actual.
- **Riesgo**: BAJO (columna nueva, no usada en decision).
- **Trabajo**: modificar motor_data.py + migrar tabla historial_equipos.
- **Metrica de exito**: hit rate en equipos con divergencia ratio>1.3 mejora >2pp en SHADOW.
- **Importante**: NO mover a produccion hasta tener evidencia con N adecuado, y entender que EMA dual NO resuelve el caso Boca.

> **[ANEXO 2026-04-26 - ESTADO: DONE]** Ver §4.1.A. Commit `e9c4b76`. SHADOW activa,
> trigger de re-evaluacion a 30 dias / N>=15 equipos.

### Accion #3 - Recalibrar rho EPL con 5 temporadas + integrar CLV en backtest (8 horas combinado)
- **Beneficio esperado (rho)**: corregir artifact de temporada 24-25.
- **Beneficio esperado (CLV)**: detectar degradacion del modelo con N=50 antes de drawdown realizado. Metrica complementaria a Brier.
- **Riesgo**: BAJO (rho actualiza tabla; CLV es metrica observacional).
- **Trabajo**: 4h cada uno.

> **[ANEXO 2026-04-26 - ESTADO: DONE ambos]**
> - rho: ver §1.2. Commit `f9d32ce`. Alcance ampliado de EPL a 5 ligas EUR.
> - CLV: ver §1.4. Commit `e9af2b9`. Operativo en `motor_backtest`.

### Acciones NO en top-3 pero a vigilar
- Pooled prior LATAM o baseline externo (Seccion 2.3) - requiere debate sobre mecanismo.
- Penalizacion multi-stake 1X2+O/U (Seccion 2.1) - requiere medir N de partidos con doble apuesta primero.
- Argentina LIVE %empate sub-estimada / Noruega LIVE %loc sub-estimada (alertas operativas inv-stats-ligas).

---

## ALERTAS DE CONTRADICCION ENTRE INVESTIGADORES

### Contradiccion #1: inv-form sobre el caso Boca
- inv-form (parte A) dice "el problema NO es EMA, es ratio goles/xG"
- inv-form (parte B EMA improvements) dice "EMA dual hubiera capturado upturn en 2-3 partidos"
- **Resolucion del critico**: ambas son verdaderas pero apuntan a problemas distintos. EMA dual ayuda con rachas de xG REAL (mejora sostenida en produccion de chances). El caso Boca es diferente: produccion xG estable, conversion por encima de la media (luck o skill no-medible). EMA dual NO resuelve Boca.

### Contradiccion #2: pooled LATAM
- inv-stats-ligas dice "POOLED LATAM hasta N>=50"
- Critico observa: pooling vs baseline externo (soccerstats) son dos opciones distintas. inv-stats-ligas no las separo.
- **Resolucion**: requiere clarificacion antes de proceder. PROPOSAL pendiente.

### Gap: inv-xg no transmitido directamente
- **Riesgo**: hallazgos sobre xG modernos (calibracion Murphy, log-loss, Brier descompuesto a nivel xG) podrian existir pero no fueron auditados por critico.
- **Accion recomendada al Lead**: solicitar bead_id de inv-xg y re-auditar si hay claims relevantes a Manifiesto Seccion II.A.

> **[ANEXO 2026-04-26 - ESTADO: PARCIALMENTE CERRADO]**
> - Bead `adepor-bgt` consolido walk-forward "maquina del tiempo" para xG en multiples
>   iteraciones:
>   - iter1 (commit `dd25dec`): 6 ligas EUR baseline.
>   - iter2 (commit `3840acb`): 9 ligas LATAM goals-only via API-Football.
>   - iter3 (commit `8ddb07c`): 9 LATAM full stats via ESPN scraping.
>   - persistencia (commit `f88a70b`): 11.634 predicciones walk-forward + cache ESPN
>     12 paises x 3 temporadas para reproducibilidad.
> - A/B OLS xG con datos extendidos (`analisis/walk_forward_ab_xg_ols.json`,
>   `analisis/calibracion_xg_ols_por_liga.json`).
> - OLS multivariable con faltas: NO significativo (Δ R² +0.003), faltas descartadas
>   como proxy de posesion. Resultado en `analisis/ols_xg_extendido_faltas.json`.
> - Reliability diagram del motor: `analisis/reliability_diagram_motor.json` revela
>   compresion (over-estimacion 30-40%, sub-estimacion 45-55%).
> - **Subpendiente**: Murphy decomposition formal (Reliability + Resolution +
>   Uncertainty) sigue sin documentar como artifact propio.

---

## VEREDICTO BOCA (respuesta directa al usuario)

**Pregunta usuario**: Por que el modelo recomendo apostar contra Boca cuando estaba en racha de 14 invicto?

**Respuesta consolidada**:
1. La "racha 14" mezcla liga + Copa. La DB solo trackea liga. Sobre liga (5 partidos), Boca tiene xG crudo ~1.12-1.17/partido - modelo lo refleja correctamente.
2. El modelo NO fallo en xG. Fallo en predecir conversion: Boca anoto 9 goles con 5.61 xG (ratio 1.60x sobreperformance) y recibio 1 gol con 5.52 xG (ratio 0.18x defensa).
3. Esto es **luck overperformance** (Miller-Sanjurjo 2018: a N=5 no se distingue de skill). Es lo que el modelo Dixon-Coles correctamente NO deberia seguir, porque a largo plazo el ratio regresa a 1.0.
4. **Fix recomendado**: NO ajustar el motor para "perseguir" Boca. Seria overfit. Lo correcto es:
   - Aceptar que en 5 de 5 vs prediccion Boca-LOCAL, hubo 4 LOSS para el modelo (esperable estadisticamente).
   - Evaluar si en N>=20 partidos proximos el ratio regresa a 1.0 (prediccion del modelo).
   - **NO implementar form_factor con N=5** (VETADO).
   - Si se quiere instrumentacion, implementar EMA dual SHADOW (Accion #2) para tener data - pero entender que NO resuelve este caso especifico.
5. **Si en N=20 partidos proximos Boca sigue con ratio>1.5**: entonces es senal real (skill estructural, posible cambio de DT, plantel, etc.), y hay caso para PROPOSAL formal con evidencia.

---

## REFERENCIAS BEADS DE ORIGEN

- **adepor-zbc** (inv-stats-ligas): stats 16 ligas + veredicto pooling
- **adepor-d4r** (inv-form): form/rachas Boca + EMA improvements v2
- **adepor-mcn** (inv-apuestas): yield+Brier+Kelly, 15 papers
- **inv-xg**: bead_id no transmitido al critico-sintesis. Lead notificado.


---

# ANEXO 2026-04-26 (PARTE 2) — Cierre experimento V6-V12 SHADOW + Motor adaptativo

## Contexto

Sesion extendida 2026-04-26 (post-anexo PARTE 1): el usuario pidio auditar el calculo de xG.
Esto disparo un experimento de 7 arquitecturas SHADOW (V6-V12) con multiple analisis OOS.
Resultado final: V0 raw sigue siendo el mejor argmax-default, pero se identificaron parches
toxicos en producci on y un hibrido prometedor (H4) con evidencia preliminar.

## Hallazgos principales

### 1. xG OLS recalibrado (V6) — diagnostico

Audit OLS sobre N=24,164 obs (10 ligas) detecto 3 errores estructurales en Reglas_IA.txt §II.A:

- beta_shots_off positivo (+0.010 codigo) vs OLS empirico (-0.027)  → SIGNO INVERTIDO
- coef_corner positivo (+0.02 codigo) vs OLS empirico (-0.055)  → SIGNO INVERTIDO
- intercept ausente (asume 0) vs OLS estima +0.46 goles baseline  → MISSING

Bias xG_total V0 legacy = +1.93 goles/partido (sobreestima). gamma_display=0.59 era parche.
Bias xG_total V6 OLS = +0.08 goles. Pero NO se traduce en mejor 1X2 OOS.

### 2. Resultado OOS estricto (test 2024 N=2,768)

Walk-forward EMA cutoff 2023-12-31, sin leak comparativo:

| Modelo | hit | Brier |
|---|---:|---:|
| V0 raw | **0.488** | **0.6182** |
| V6 OLS+DC | 0.482 | 0.6222 |
| V7 Skellam | 0.482 | 0.6223 |
| V12 LR multinomial | 0.473 | 0.6219 |

**V0 raw GANA OOS**. La superioridad in-sample de V12 (5pp) era 100% leak.

### 3. Audit parches V0 OOS

| Parche | Δhit | Veredicto |
|---|---:|---|
| Hallazgo G | **−1.2pp** | TOXICO |
| Fix #5 | =0 | Inocuo |
| Hallazgo G + Fix #5 | −1.2pp | Mismo |

HALLAZGO_G_ACTIVO=True (default producci on) **degrada el motor 1.2pp OOS**.

### 4. H4 V0+X-rescue (sobre cuotas reales N=127)

H4 = V0 default + override 'X' si V12 dice argmax=X y P(X) > 0.30.

| | hit | yield_A | yield_B (EV>5%) |
|---|---:|---:|---:|
| V0 baseline | 0.488 | +0.157 | +0.255 |
| **H4** | **0.520** | **+0.246** | +0.317 |

Threshold sweep [0.25, 0.50] confirma robustez en [0.25, 0.35]. Elegido: 0.30.
**Caveat**: N=127 chico (CI95 ±10pp). PROPOSAL adepor-617 BLOQUEADO pending N≥500.

### 5. Empate cuasi-aleatorio dado xG

Cohen's d uniformemente <0.13 para todas las features (xg, delta, h2h_fx, var, etc.) en
discriminar X vs no-X. Buckets bivariate: freq_X siempre 0.21-0.30. Sin patron explotable.

V12 sub-detecta empates (3.2% picks vs 25.9% real) con precision 33% (cerca de base).
Para activar empates con edge real se necesitan **features pre-partido NO presentes hoy**:
alineaciones, lesiones jugadores top, posicion tabla, motivacional. Scrapeable pero costoso.

## Motor adaptativo permanente (NUEVO)

Implementado `motor_adaptativo.py` integrado en `ejecutar_proyecto.py` FASE 3.5 (entre
motor_data y motor_fixture). Cada corrida del pipeline:

1. Identifica partidos liquidados nuevos (idempotente via `motor_adaptativo_last_run`)
2. SGD step sobre `lr_v12_weights[liga]` + `[global]` paralelo (warmup 100, lr=0.005,
   ridge=0.1, anchor regularization=0.05)
3. Auto-audit ultimos 200 SGD steps: WEIGHT_NORM>50 / GRAD_NORM>5 / BRIER>baseline×1.10
   → AUTO-REVERT al anchor batch (cooldown 7d)
4. Drift detector ventana 30d sobre Brier rolling vs baseline+2σ
5. Persiste last_run timestamp

Smoke test 2026-04-26: 373 partidos backtest reales procesados, 102 SGD steps efectivos
(271 warmup), 0 reverts, Brier_avg=0.5296 (mejor que baseline batch 0.587), weight_norm=0.61
estable. Tablas: `online_sgd_log`, `drift_alerts`.

## Estado final beads

| Bead | Estado | Rol |
|---|---|---|
| adepor-d7h | OPEN | Infra SHADOW V6/V7/V12/V12b + motor_adaptativo |
| adepor-617 | OPEN P1 | PROPOSAL H4 V0+X-rescue + desactivar HG. BLOQUEADO pending N>=500 |
| adepor-2yo | CLOSED | PROPOSAL V12 viejo descartado tras OOS |

## Conclusion estrategica

1. **El motor V0 actual SIN parches toxicos seria mas fuerte** (+1.2pp hit OOS).
2. **xG recalibrado V6 NO mejora 1X2** aunque corrige bias goles. Aceptamos status quo en xG.
3. **Empate es ruido estructural** dado el feature space xG. Sin scraping de alineaciones/
   lesiones, ningun modelo va a mover la aguja en X.
4. **H4 hibrido prometedor** pero requiere N>=500 con cuotas reales antes de promover.
5. **ML adaptativo activo**: V12 SHADOW se actualiza online cada corrida con auto-reverts
   protegidos. NO afecta motor productivo. Drift detector alertara si Brier degrada.

## Archivos generados sesion 2026-04-26

| Tipo | Archivo |
|---|---|
| Script | `analisis/calibrar_xg_por_liga_ols.py`, `calibrar_v12.py`, `calibrar_v12b.py` |
| Script | `analisis/comparativo_v6_v7.py`, `walk_forward_v12_oos.py`, `walk_forward_v12b_skellam.py`, `walk_forward_v12_clean.py` |
| Script | `analisis/audit_parches_v0_oos.py`, `audit_parches_extendido.py`, `v12_vs_v0_subset_x.py` |
| Script | `analisis/yield_v0_v12_backtest.py`, `yield_hibridos_backtest.py`, `sweep_threshold_h4.py` |
| Motor | `motor_adaptativo.py`, `scripts/online_sgd_v12.py`, `scripts/drift_detector.py` |
| Backfill | `scripts/persistir_coefs_xg_v6.py`, `backfill_xg_v6_shadow.py` |
| Doc | `docs/ml_adaptativo_plan.md`, `docs/plan_ampliacion_cuotas.md` |
| DB | snapshot `snapshots/fondo_quant_20260426_181820_pre_xg_v6_shadow.db` |
| Tabla nueva | `historial_equipos_v6_shadow`, `online_sgd_log`, `drift_alerts` |

---

# ANEXO 2026-04-26 (PARTE 3) — Plan ampliacion cuotas EJECUTADO + V5.0 APROBADO

## Contexto

Sesion 2026-04-26 PARTE 3: ejecutar plan_ampliacion_cuotas.md para validar PROPOSAL adepor-617
(H4 V0+X-rescue) con N grande contra cuotas Pinnacle closing reales 2024.

## Hallazgos principales

### F1 — Scraper football-data.co.uk

Tabla nueva `cuotas_externas_historico` (13.332 filas):
- 8.600 mmz4281 (6 EUR full schema): E0/D1/I1/SP1/F1/T1, JOIN 100% match con partidos_historico_externo.
- 967 NOR via /new/NOR.csv (Noruega Eliteserien — fix bug `adepor-a0i` que confundia N1=Eredivisie con Noruega).
- 3.765 ARG/BRA via /new/{ARG,BRA}.csv. JOIN 87-90% post-aliases (30 mappings CSV→ESPN).

Drop del scope original: E1 (English Championship) y P1 (Portugal) NO estan en
partidos_historico_externo → JOIN inutil.

### F2 — Walk-forward OOS estricto

Test 2024 EUR + ARG + BRA, warmup EMA 2021-2023, N=2.348 partidos. Bootstrap CI95 B=1.000.

| Estrategia (8 ligas, sin filtro) | Yield | CI95 | Sig 95% |
|---|---|---|---|
| V0 statu quo | -0.003 | [-0.046, +0.043] | . |
| V12 uniforme | +0.007 | [-0.039, +0.053] | . |
| H4 thresh=0.35 uniforme | +0.010 | [-0.036, +0.054] | . |
| L2 (V12 TUR + V0 resto) | -0.000 | [-0.042, +0.046] | . |
| L2+L3 (V12 TUR + H4 resto) | +0.012 | [-0.034, +0.057] | . |

**Por liga:** SOLO Turquia es estadisticamente significativa al 95%. V12 TUR yield +0.116
[+0.003, +0.242] ★ con N=271. Resto de ligas tienen yields apuntando en direccion
esperada (positivo en TUR/ITA/FRA/ENG, negativo en DE/ES, marginal LATAM) pero CI95 amplios.

Coincidencia con `xg_calibration_history.md` tier verde (TUR/ITA/FRA/ENG +7-11pp edge real)
descarta data-snooping puro: hay senal estructural pre-existente.

### F3 — PROPOSAL adepor-617 invalidado

H4 con N=127 daba yield +0.246. Con N=1.806 sobre Pinnacle cae a +0.011 (CI95 incluye 0).
Reconciliacion con N=127 ORIGINAL: imposible. partidos_backtest fecha 2026 mixto
LATAM+EUR, cuotas_externas 2021-2024 EUR Pinnacle. Match: 0/418 (poblaciones disjuntas).

Sucesor `adepor-edk` con 3 layers:
- Layer 1 (filtro liga apostar/no): **RECHAZADO** por usuario ("mantener todas las ligas").
- Layer 2 (V12 standalone Turquia): **APROBADO Y APLICADO**.
- Layer 3 (H4 X-rescue thresh=0.35): **SHADOW, no aplicado**.

## V5.0 APLICADO en producción

Manifesto bump V4.6 → V5.0:
- Reglas_IA.txt nueva §L "Arquitectura de Decisión por Liga"
- SHA-256: `c1f3a1d2...` → `6609ee91...`
- `configuracion.manifesto_sha256` actualizado

motor_calculadora.py:1397-1418 — bloque LAYER 2 fail-silent. Si arch_target=='V12':
1. _get_xg_v6_para_partido(loc_norm, vis_norm) → xG_v6
2. _calcular_probs_v12_lr(xg_v6, ...) → V12 probs
3. Override p1, px, p2 antes de evaluar_mercado_1x2

config_motor_valores: `arch_decision_per_liga = '{"Turquia": "V12"}'` (tipo=text).

Bug colateral encontrado y resuelto: `config_motor.py::_coerce` no manejaba `tipo='json'` →
retornaba `valor_real` (NULL). Cambiado a `tipo='text'`, motor parsea localmente con json.loads.

## Validación end-to-end (corrida real 2026-04-26)

8 partidos turcos pendientes re-evaluados con V12 override. Logs `[ARCH-V5.0:V12]` visibles:

| Partido | V0 pick | V12 pick | Cambio |
|---|---|---|---|
| Alanyaspor vs Samsunspor | 1 | 1 | + confianza |
| Besiktas vs Fatih Karagumruk | 1 | 1 | + confianza |
| Konyaspor vs Trabzonspor | 1 | 1 | — |
| Caykur Rizespor vs Konyaspor | 1 | 1 | + confianza |
| Gaziantep FK vs Besiktas | 2 (0.357) | **1 (0.412)** | **flip 2→1** |
| Fenerbahce vs Istanbul Basaksehir | 1 | 1 | + confianza |
| Samsunspor vs Galatasaray | 1 (0.458) | **2 (0.471)** | **flip 1→2** |
| Trabzonspor vs Goztepe | 1 (0.440) | **2 (0.383)** | **flip 1→2** |

3 de 8 partidos cambiaron pick. Stakes y EV recalculados con probs V12.

## Estado final beads

| Bead | Estado | Rol |
|---|---|---|
| adepor-617 | OPEN obsoleto | Sucedido por adepor-edk (H4 standalone no valida con N grande) |
| adepor-edk | OPEN approved-by-lead | V5.0 aplicada parcialmente (Layer 2 prod, Layer 3 shadow) |
| adepor-a0i | OPEN | Bug N1=Eredivisie fixed para scraper cuotas; calibrar_rho.py pendiente |

## Archivos generados sesion 2026-04-26 PARTE 3

| Tipo | Archivo |
|---|---|
| Script | `scripts/scraper_football_data_cuotas.py` (mmz4281 + /new/, ALIASES_NEW_FORMAT) |
| Script | `analisis/yield_v0_v12_backtest_extendido.py`, `yield_v0_v12_F2_completo.py`, `yield_v0_v12_F2_sin_filtro.py` |
| Script | `analisis/audit_yield_F2.py`, `audit_yield_F2_sweep_y_ci.py`, `audit_yield_F2_filtro_liga.py` |
| Motor | `src/nucleo/motor_calculadora.py:1397-1418` (Layer 2 V12 override) |
| Manifesto | `Reglas_IA.txt` §L (V5.0) |
| Config | `config_motor_valores.arch_decision_per_liga = '{"Turquia": "V12"}'` |
| DB | snapshot `snapshots/fondo_quant_20260426_215241_pre_cuotas_externas_F1.db` (10.96 MB, pre-F1) |
| DB | snapshot `snapshots/fondo_quant_20260426_224017_pre_v5_layer2_v12_tur.db` (18.31 MB, pre-V5.0) |
| DB | tabla `cuotas_externas_historico` (13.332 filas, 9 ligas) |
| Doc | `docs/plan_ampliacion_cuotas.md` (F1+F2+F3 marcados ejecutados) |
| Doc | `docs/pipeline_overview.md` (motor 7 documenta override V5.0) |
| Doc | `docs/xg_calibration_history.md` (Anexo PARTE 3) |
| JSON | 4 outputs persistidos en `analisis/*.json` con bootstrap CI95 |
