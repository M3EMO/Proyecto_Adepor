# MOCKUPS — Dashboard Operativo Adepor (V1)

> Autor: T2 disenador-ux | Fecha: 2026-04-16 (reorganizado 2026-04-17)
> Estado: V1 completo. **Solo mockups ASCII** — la spec completa (tokens, jerarquia, accesibilidad, shape de datos) vive en [SPEC_DASHBOARD_OPERATIVO.md](SPEC_DASHBOARD_OPERATIVO.md).
> Scope: PLAN.md Seccion 2 (correccion 2026-04-17) — `adepor_eval_review.html` queda FUERA. Este documento muestra como deberia verse el **dashboard operativo de apuestas** (artefacto futuro, sin implementacion en este ciclo).
> Convencion: ASCII boxes. `[CORCHETES]` = badge/chip exacto. `<placeholder>` = valor dinamico del backend.
>
> **Companion docs**:
> - [SPEC_DASHBOARD_OPERATIVO.md](SPEC_DASHBOARD_OPERATIVO.md) — spec completa: tokens, paleta, tipografia, interacciones, accesibilidad, responsive, shape de datos `OPERATIVO_DATA`, strings exactos del backend.
> - [AUDITORIA_VISOR_EVALS.md](AUDITORIA_VISOR_EVALS.md) — referencia visual heredable del visor existente (paleta, tipografia, patrones).

---

## 0. PROPOSITO Y NO-PROPOSITO

**Proposito**: presentar visualmente el output operativo del motor cuantitativo Adepor — apuestas activas, rechazos con razon, modo operativo, drawdown, ajustes de xG/stake, comparativos vs casa, y panel de constantes Reglas_IA al alcance.

**No-proposito**: NO recalcula nada, NO transforma datos numericos, NO altera strings comparados. Es solo presentacion de lo que el backend ya emite.

**Hard stops** (heredados de PLAN.md Seccion 1):
- Strings exactos: `"OPERAR LOCAL"`, `"PASAR"`, `"Liquidado"`, `"MODO NORMAL"`, `"MODO DEFENSIVO"`, claves de Cuatro Caminos (`"1"`, `"2"`, `"2B"`, `"3"`), razones de rechazo (`EV_BAJO`, `DIV_ALTA`, `FLOOR`, `CAMINO_2B_FUERA_RANGO`, `SHADOW_ONLY`) → bit-a-bit del backend.
- Numeros (EV, Kelly, xG, rho, EMA, factores tacticos, etc.) → solo formateo (decimales, separadores), NO recalculo.
- Matrices (`ALFA_EMA_POR_LIGA`, `DIVERGENCIA_MAX_POR_LIGA`, `FACTOR_CORR_XG_OU_POR_LIGA`, matriz tactica) → solo lectura, leidas desde JSON producido por T6.

---

## INDICE

- [0. Proposito y no-proposito](#0-proposito-y-no-proposito)
- [1. Layout general](#1-layout-general)
- [2. Header con modo operativo + equity (F5, F6)](#2-header-modo-equity)
- [3. Apuestas activas con clusters (F1)](#3-apuestas-activas-clusters)
- [4. Apuestas rechazadas con badges (F2)](#4-rechazos-badges)
- [5. Pipeline de ajustes xG colapsable (F3)](#5-pipeline-xg)
- [6. Stake desglose cascada (F4)](#6-stake-desglose)
- [7. Pill Shadow vs Op1 (F7)](#7-shadow-vs-op1)
- [8. Panel lateral Reglas_IA (F8)](#8-panel-reglas)
- [9. Brier score comparativo (F9)](#9-brier-score)
- [10. Divergencia con umbral (F10)](#10-divergencia-umbral)


> Para tokens, paleta, tipografia, accesibilidad y shape de datos ver [SPEC_DASHBOARD_OPERATIVO.md](SPEC_DASHBOARD_OPERATIVO.md).

---

## 1. LAYOUT GENERAL

### ANTES (no existe — el motor escupe a Excel y a logs)

```
[ Sin dashboard operativo. Usuario abre Backtest_Modelo.xlsx + lee logs Python. ]
[ Friccion: el contexto (cluster, modo, drawdown) hay que reconstruirlo a mano. ]
```

### DESPUES — Layout principal

```
+======================================================================+
|  [HEADER]  Adepor — Operativo  <fecha>           [Equity sparkline]  |
|  [MODO NORMAL 2.5%]   DD vivo: -1.2%   Banca: <banca>                |  <- F5, F6
+======================================================================+
|  Tabs: [ Resumen ] [ Apuestas ] [ Rechazos ] [ Reglas ] [ Backtest ] |
+======================================================================+
|                                                            +-------+ |
|  PANEL PRINCIPAL                                           | LADO  | |
|                                                            | F8    | |
|  +------------------------------------------------------+  | (drawer)
|  | Cluster: <Liga> · <Fecha>  N=<n>  factor 1/sqrt(N)   |  |       | |
|  +------------------------------------------------------+  | ALFA  | |
|  |  partido | EV% | Kelly_b | factor | dxG | stake_final|  | EMA   | |
|  |  ...                                                 |  | DIV   | |
|  +------------------------------------------------------+  | RHO   | |
|  | (pipeline xG colapsable + stake desglose colapsable) |  | TACT  | |
|  +------------------------------------------------------+  |       | |
|                                                            +-------+ |
+======================================================================+
```

---

## 2. HEADER MODO + EQUITY  (F5, F6)

### ANTES

```
[ Sin indicador. El modo se infiere leyendo motor_calculadora.py + DB. ]
```

### DESPUES — Modo NORMAL

```
+----------------------------------------------------------------------+
|  Adepor — Operativo                         [equity sparkline 30d]   |
|                                                  /\        /\        |
|  [MODO NORMAL <pct>%]                         __/  \______/  \___    |
|   ^^^^^^^^^^^^^^^^                            |                 |    |
|   chip verde, font-size 1.125rem              DD vivo: <dd>%         |
|   border-radius 9999, padding 0.5rem 1rem     Banca: <banca>         |
|                                               Liquidados: <n>        |
+----------------------------------------------------------------------+
```

### DESPUES — Modo DEFENSIVO (DD activo, banca por debajo del umbral)

```
+----------------------------------------------------------------------+
|  Adepor — Operativo                         [equity sparkline 30d]   |
|                                                  /\                  |
|  [MODO DEFENSIVO <pct>%]                      __/  \______           |
|   ^^^^^^^^^^^^^^^^^^^^                                    \___       |
|   chip ROJO, pulsing 2s ease infinite         DD vivo: <dd>% [!]     |
|   border 2px solid var(--red)                 Banca: <banca>         |
|                                               Liquidados: <n>        |
+----------------------------------------------------------------------+
```

**Strings exactos**: `"MODO NORMAL"` y `"MODO DEFENSIVO"` — no traducir, no abreviar.
**Sparkline**: SVG inline simple (path con 30 puntos diarios). Si banca cae bajo `umbral_dd`, color de la curva pasa a rojo.
**Equity y banca**: del backend (T6 produce JSON `equity_30d.json` con array de cierres diarios).

---

## 3. APUESTAS ACTIVAS + CLUSTERS  (F1)

### ANTES

```
+----------------------------------------------------------+
|  partido        | EV%   | Kelly  | stake  | estado       |
|  Boca-River     | 4.2   | 0.030  | 0.030  | PENDIENTE    |
|  Arsenal-Lyon   | 5.1   | 0.041  | 0.041  | PENDIENTE    |
|  Racing-Velez   | 3.8   | 0.025  | 0.025  | PENDIENTE    |
|  Ind-SanLor     | 4.5   | 0.032  | 0.032  | PENDIENTE    |
|  Newell-Estud   | 3.2   | 0.020  | 0.020  | PENDIENTE    |
|  ... (25 filas planas, sin contexto de cluster)          |
+----------------------------------------------------------+
```

Problema: 4 de esas son del mismo cluster (Argentina-2026-04-16) y deberian llevar penalizacion `1/sqrt(4) = 0.500`. Hoy invisible.

### DESPUES

```
+======================================================================+
|  Cluster: <Liga> · <Fecha>   N=<n>   factor 1/sqrt(N) = <factor>    |
|  border-left 4px var(--color-cluster-<liga>)                        |
|  ─────────────────────────────────────────────────────────────────── |
|  partido       | EV%   | Kelly_b | factor  | delta_xG | stake_final |
|  <p1>          | <ev>  | <k_b>   | <fact>  | <dxg>    | <stake>     |
|  <p2>          | ...   | ...     | ...     | ...      | ...         |
|                                              cluster total: <total>  |
+======================================================================+

+======================================================================+
|  Cluster: <Liga2> · <Fecha>      N=<n2>   factor 1/sqrt(N)=<factor2>|
|  ─────────────────────────────────────────────────────────────────── |
|  ...                                                                 |
+======================================================================+

+======================================================================+
|  Single bets (sin cluster)                                          |
|  ─────────────────────────────────────────────────────────────────── |
|  <p_single>    | ...   | ...     | x1.000  | ...      | ...         |
+======================================================================+
```

**Tratamiento visual**:
- Cada cluster es un `<details>` (HTML5 nativo) o una card colapsable.
- `border-left` 4px del color de la liga (Argentina, Brasil, Inglaterra, Turquia, Noruega).
- Columna `factor` muestra string formateado por backend (ej. `"x0.500"`). NO calcular en frontend.
- Footer `cluster total` = suma de stakes (formateo simple, no recomputo de logica).

**Agrupacion**: el backend ya debe emitir `cluster_id = <Liga>_<Fecha>`. El frontend solo agrupa por esa key.

---

## 4. APUESTAS RECHAZADAS + BADGES  (F2)

### ANTES

```
[ Hoy: motor descarta silenciosamente. Solo aparece en log si abrimos motor.py. ]
```

### DESPUES

```
+======================================================================+
|  Rechazos del dia (<n>)                                             |
|  Filtros: [TODOS] [EV_BAJO] [DIV_ALTA] [FLOOR] [CAMINO_2B_FUERA_...] |
|  ─────────────────────────────────────────────────────────────────── |
|  partido            | mercado | razon                  | detalle    |
|  <p1>               | 1X2     | [EV_BAJO]              | EV=<ev>    |
|  <p2>               | 1X2     | [DIV_ALTA]             | div=<d>    |
|  <p3>               | OU 2.5  | [FLOOR]                | p=<p>      |
|  <p4>               | 1X2     | [CAMINO_2B_FUERA_RANGO]| EV=<ev>    |
|  <p5>               | 1X2     | [SHADOW_ONLY]          | -          |
|  ...                                                                 |
+======================================================================+
```

**Strings exactos**: vienen del backend en campo `motivo_rechazo`. Lista observada hasta ahora:
- `EV_BAJO`
- `DIV_ALTA`
- `FLOOR`
- `CAMINO_2B_FUERA_RANGO`
- `SHADOW_ONLY`

[CONFIRMAR con T1/T6] si hay otros: `MIN_PARTIDOS_INSUFICIENTE`, `LIGA_NO_CALIBRADA`, `XG_FUERA_RANGO`, etc. **No inventar**. Si el badge llega y no esta mapeado a color, fallback gris.

**Visual badge**: chip pill, font-size 0.6875rem uppercase, color por categoria:
- `[EV_BAJO]` → ambar (es solo "no rentable hoy")
- `[DIV_ALTA]` → rojo (fuera de tolerancia matematica)
- `[FLOOR]` → gris (probabilidad insuficiente)
- `[CAMINO_2B_FUERA_RANGO]` → naranja (estrategia especial fuera de rango)
- `[SHADOW_ONLY]` → azul (control sin Fix #5/Hallazgo G/Hallazgo C)
- `[*otro*]` → gris (fallback)

---

## 5. PIPELINE DE AJUSTES xG  (F3)

### ANTES

```
[ El xG final aparece pero los ajustes intermedios estan ocultos en motor_calculadora.py. ]
[ Usuario debe leer 100+ lineas para entender por que xG paso de 1.42 a 1.58. ]
```

### DESPUES — Cascada visible (colapsable por partido)

```
+======================================================================+
|  <local> vs <visita>   xG_local: <base> → <final>                   |
|                        xG_visit: <base> → <final>                   |
|                                                                      |
|  [ v Ver pipeline de ajustes ]                                       |
|  ┌──────────────────────────────────────────────────────────────┐   |
|  │  LOCAL                                                        │   |
|  │  xG_base                          <xg_b>                      │   |
|  │  + fatiga (<f_fat>)      ─────►   <xg1>    (<motivo_fat>)     │   |
|  │  + altitud (<f_alt>)     ─────►   <xg2>    (<motivo_alt>)     │   |
|  │  + momentum (<f_mom>)    ─────►   <xg3>    (<motivo_mom>)     │   |
|  │  + ajuste_tactico (<f_t>) ────►   <xg4>    (<perfil_tact>)    │   |
|  │                                   ════                        │   |
|  │  xG_local FINAL                   <xg_f>                      │   |
|  │                                                               │   |
|  │  VISITA                                                       │   |
|  │  xG_base                          <xg_b_v>                    │   |
|  │  + fatiga (<f_fat_v>)    ─────►   <xg1_v>                     │   |
|  │  + altitud (<f_alt_v>)   ─────►   <xg2_v>                     │   |
|  │  + momentum (<f_mom_v>)  ─────►   <xg3_v>                     │   |
|  │  + ajuste_tactico (<f_t_v>) ──►   <xg4_v>                     │   |
|  │                                   ════                        │   |
|  │  xG_visit FINAL                   <xg_f_v>                    │   |
|  └──────────────────────────────────────────────────────────────┘   |
+======================================================================+
```

**Interaccion**: `<details>`/`<summary>` HTML5 nativo. Cerrado por defecto.
**Color del factor**: verde si `>1.0`, rojo si `<1.0`, gris si `=1.0`. (puramente CSS sobre el numero formateado por backend).
**Strings de etapa**: `"fatiga"`, `"altitud"`, `"momentum"`, `"ajuste_tactico"` — confirmar con T6 que el backend los emite con esos nombres exactos.

---

## 6. STAKE DESGLOSE  (F4)

### ANTES

```
stake_final: 0.0195   <- un solo numero opaco
```

### DESPUES — Cascada visible

```
+======================================================================+
|  <local>-<visita> — Stake desglose                                   |
|                                                                      |
|  Kelly_base                       <k_base>                           |
|     ↓ /sqrt(N=<n>) covarianza     <factor_cov>                       |
|  Kelly_ajustado_corr              <k_corr>                           |
|     ↓ delta_xG (<sign><dxg>)      <factor_dxg>                       |
|  Kelly_con_delta                  <k_dxg>                            |
|     ↓ cap por <modo>              min(<k_dxg>, <cap>)                |
|  ════════════════════════════                                        |
|  STAKE FINAL                      <stake_f>    (<pct>% banca)        |
+======================================================================+
```

**Tratamiento**: cascada con flechas, valor a la derecha, factor en el medio. Footer en bold. Mismo patron visual que pipeline xG (consistencia).

---

## 7. SHADOW vs OP1 PILL  (F7)

### ANTES

```
[ Hoy se confunden en la misma tabla. El revisor no sabe cual es "real" vs "control". ]
```

### DESPUES — Pill diferenciado

```
   [OP1]      <- chip naranja (--accent), fondo solido, color blanco
   [SHADOW]   <- chip azul (--color-shadow), fondo claro, border azul

+----------------------------------------------------------+
|  partido         | tipo      | EV%  | Kelly  | stake     |
|  <p>             | [OP1]     | <ev> | <k>    | <stake>   |
|  <p>             | [SHADOW]  | <ev> | <k>    | <stake_s> |
|  ^                                                       |
|  | misma fila pero shadow no aplica Fix #5 / Hallazgo G  |
+----------------------------------------------------------+
```

**Toggle global**: boton arriba `[ Solo OP1 | Solo SHADOW | Ambos ]` para filtrar.
**Strings**: `"OP1"` y `"SHADOW"` exactos del backend, no traducir.

---

## 8. PANEL LATERAL REGLAS_IA  (F8)

### ANTES

```
[ Usuario abre Reglas_IA.txt en otro programa. Friccion alta. ]
```

### DESPUES — Drawer lateral (sticky right en >=1280px, colapsable a icono en <1280px)

```
+----------------------------------------------------------+--------+
|  CONTENIDO PRINCIPAL                                     | REGLAS |
|                                                          | _____  |
|                                                          |        |
|                                                          | ALFA   |
|                                                          | EMA    |
|                                                          | ─────  |
|                                                          | BR <a> |
|                                                          | TR <a> |
|                                                          | NO <a> |
|                                                          | AR <a> |
|                                                          | EN <a> |
|                                                          | ─────  |
|                                                          |        |
|                                                          | DIV    |
|                                                          | MAX    |
|                                                          | ─────  |
|                                                          | <pais> |
|                                                          | <val>  |
|                                                          | ...    |
|                                                          | ─────  |
|                                                          |        |
|                                                          | RHO    |
|                                                          | ─────  |
|                                                          | AR <r> |
|                                                          | NO <r> |
|                                                          | EN <r> |
|                                                          | BR <r> |
|                                                          | TR <r> |
+----------------------------------------------------------+--------+
```

**SOLO LECTURA**, sin botones de editar.
**Origen del dato**: JSON `reglas_ia.json` producido por T6 leyendo `config_sistema.py` y la matriz tactica. NO duplicar valores en HTML — hardcodearlos rompe la fuente unica de verdad.
**Sticky**: `position: sticky; top: 0` para que siempre acompañe.

---

## 9. BRIER SCORE COMPARATIVO  (F9)

### ANTES

```
[ Solo aparece como log oculto. ]
```

### DESPUES — Bar de progreso comparativo

```
+======================================================================+
|  Brier Score (ultimo trimestre, N=<n>)                              |
|                                                                      |
|  Sistema   ████████████████████░░░░░░░░░░░░░░░░  <bs_sis> ← lower=mejor
|  Casa      ███████████████████████████░░░░░░░░░  <bs_casa>          |
|                                                                      |
|  Diff: <diff>  ←  <pct_mejora>% mejora  [verde si <0, rojo si >0]   |
|                                                                      |
|  N=<n> partidos liquidados desde <fecha_inicio>                      |
+======================================================================+
```

**Detalles visuales**:
- Bar horizontal escala 0-1 (Brier teorico maximo).
- Sistema en verde si `BS_sistema < BS_casa`, rojo si peor (lower=better).
- Numero a la derecha de la barra con 3 decimales (formateo en frontend OK).
- Diff explicito debajo, en porcentaje relativo.

**Origen del dato**: T6 produce `brier_trimestre.json` con `{bs_sistema, bs_casa, n_partidos, fecha_inicio}`.

---

## 10. DIVERGENCIA CON UMBRAL  (F10)

### ANTES

```
divergencia: 0.18   <- numero plano, usuario no sabe si es OK
```

### DESPUES — Con umbral por liga

```
+======================================================================+
|  <local>-<visita>   (<liga>)                                        |
|                                                                      |
|  Divergencia modelo:    <div_modelo>                                |
|  Umbral liga:           <div_umbral>                                |
|                                                                      |
|  ┌──────────────────────────────────────┐                           |
|  │  ░░░░░░░░░░░░░░│███████████████████  │  <div_modelo>             |
|  │                ↑                     │  ← fuera de rango         |
|  │            umbral <div_umbral>       │  [DIV_ALTA]               |
|  └──────────────────────────────────────┘                           |
|                                                                      |
|  Resultado: <RECHAZO|ACEPTACION> con razon [<razon>]                 |
+======================================================================+
```

**Color**: rojo si `div_modelo > div_umbral`, verde si dentro. Linea vertical de umbral siempre visible.
**Origen del umbral**: matriz `DIVERGENCIA_MAX_POR_LIGA` (incluida en `reglas_ia.json` del panel F8).

---

## SISTEMA DE DISENO

Tipografia, paleta extendida (modo, shadow, OP1, colores por cluster) y densidades estan documentadas en [SPEC_DASHBOARD_OPERATIVO.md Seccion 5](SPEC_DASHBOARD_OPERATIVO.md#5-sistema-de-diseno).

---

## SHAPE DE DATOS

El JSON completo `OPERATIVO_DATA` que el HTML consumiria (campos obligatorios, opcionales, ejemplo) esta documentado en [SPEC_DASHBOARD_OPERATIVO.md Seccion 10](SPEC_DASHBOARD_OPERATIVO.md#10-shape-de-datos).

Catalogo de strings exactos del backend que cada bloque renderiza literal: [SPEC_DASHBOARD_OPERATIVO.md Seccion 11](SPEC_DASHBOARD_OPERATIVO.md#11-strings-exactos).

---

## SIGUIENTE PASO

1. Esperar `docs/ux/REPORTE_FRICCIONES.md` completo de `analista-riesgos` para refinar strings exactos de razones de rechazo y etapas del pipeline.
2. Coordinar con `tech-lead` el destino del JSON `operativo_data.json` (Open Questions Q1-Q10 en SPEC_DASHBOARD_OPERATIVO.md).
3. Implementacion: artefacto futuro fuera de este ciclo (PLAN.md Seccion 2).
