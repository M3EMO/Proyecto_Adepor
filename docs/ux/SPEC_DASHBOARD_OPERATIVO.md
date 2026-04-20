# SPEC — dashboard_operativo.html (artefacto futuro)

> Autor: T2 disenador-ux | Fecha: 2026-04-17
> Estado: V1 spec completa. **NO se implementa en este ciclo** — la implementacion HTML es un proyecto futuro fuera de este team (PLAN.md Seccion 2, correccion 2026-04-17).
> Companion docs:
> - [MOCKUPS.md](MOCKUPS.md) — mockups ASCII bloque por bloque.
> - [AUDITORIA_VISOR_EVALS.md](AUDITORIA_VISOR_EVALS.md) — patrones visuales heredables del visor existente.

---

## INDICE

- [1. Proposito y no-proposito](#1-proposito-y-no-proposito)
- [2. Hard stops](#2-hard-stops)
- [3. Inventario de bloques visuales](#3-inventario-de-bloques)
- [4. Jerarquia visual y layout](#4-jerarquia-y-layout)
- [5. Sistema de diseno (tokens, paleta, tipografia)](#5-sistema-de-diseno)
- [6. Interacciones y estados](#6-interacciones)
- [7. Accesibilidad](#7-accesibilidad)
- [8. Responsive breakpoints](#8-responsive)
- [9. Performance budget](#9-performance)
- [10. Shape de datos OPERATIVO_DATA (contrato con T6)](#10-shape-de-datos)
- [11. Strings exactos del backend (catalogo no exhaustivo)](#11-strings-exactos)
- [12. Open questions / pendientes para T6](#12-open-questions)

---

## 1. PROPOSITO Y NO-PROPOSITO

**Proposito**: presentar el output operativo del motor cuantitativo Adepor en una sola pagina HTML estatica (analoga al visor de evals): apuestas activas agrupadas por cluster de correlacion, rechazos con razon explicita, modo operativo con drawdown, ajustes de xG y stake en cascada visible, comparativos vs casa, y panel de constantes Reglas_IA al alcance.

**No-proposito**:
- NO recalcula nada (el backend ya emite todos los numeros y strings finales).
- NO transforma datos numericos mas alla de formateo de presentacion (decimales, miles).
- NO altera strings comparados aguas arriba.
- NO escribe a la DB ni a Excel.
- NO incluye logica de negocio.

**Modelo mental**: el HTML es un consumidor *read-only* de un JSON `operativo_data.json` producido por T6 (analogo a `EMBEDDED_DATA` en el visor de evals).

---

## 2. HARD STOPS

Heredados de PLAN.md Seccion 1 y Reglas_IA:

| # | Restriccion | Por que |
|---|---|---|
| H1 | Strings de modo (`"MODO NORMAL"`, `"MODO DEFENSIVO"`) — bit a bit | Comparados aguas arriba en motor_calculadora.py |
| H2 | Strings de status (`"Liquidado"`, `"PENDIENTE"`, `"Calculado"`, `"Finalizado"`) — bit a bit | Comparados en motor_liquidador.py / motor_backtest.py |
| H3 | Claves de Cuatro Caminos (`"1"`, `"2"`, `"2B"`, `"3"`) — bit a bit | Mapean a Estrategia V4.3/V4.4 Seccion IV |
| H4 | Razones de rechazo (`EV_BAJO`, `DIV_ALTA`, `FLOOR`, `CAMINO_2B_FUERA_RANGO`, `SHADOW_ONLY`, etc.) — bit a bit | Vienen del backend, no inventar |
| H5 | Strings de pais/liga (`"Argentina"`, `"Brasil"`, `"Inglaterra"`, `"Turquia"`, `"Noruega"`) — bit a bit | Keys de matrices `ALFA_EMA_POR_LIGA`, `RHO_POR_LIGA`, etc. |
| H6 | Strings de mercado (`"1X2"`, `"OU 2.5"`) y seleccion (`"1"`, `"X"`, `"2"`, `"OVER"`, `"UNDER"`) — bit a bit | Comparados en evaluar_mercado_*() |
| H7 | Numeros (EV, Kelly, xG, rho, EMA, factores) | Solo formateo, NO recalculo |
| H8 | Matrices Reglas_IA (ALFA_EMA, DIV_MAX, RHO, FACTOR_CORR, matriz tactica) | Solo lectura desde JSON producido por T6 — fuente unica de verdad en `config_sistema.py` |

**Si llega un string desconocido al frontend**: render literal, fallback gris para badges, NUNCA traducir/normalizar.

---

## 3. INVENTARIO DE BLOQUES

10 bloques visuales mapeados a las 10 fricciones de T1:

| Bloque | Origen friccion T1 | Componente principal | Densidad | Colapsable |
|---|---|---|---|---|
| B1 Header modo + banca + DD vivo | F5 | chip grande + sparkline | baja | no |
| B2 Equity sparkline 30d | F6 | SVG inline path | baja | no |
| B3 Cluster card (apuestas activas) | F1 | card con border-left + tabla densa | alta | si (por cluster) |
| B4 Rechazos con badges | F2 | tabla + chip pill por razon | media | no (filtrable) |
| B5 Pipeline xG cascada | F3 | `<details>` + lista de etapas | alta | si (por partido) |
| B6 Stake desglose cascada | F4 | `<details>` + cascada vertical | media | si (por partido) |
| B7 Pill Shadow vs OP1 | F7 | chip + toggle global | baja | no |
| B8 Panel Reglas_IA lateral | F8 | drawer sticky right | media | si (en <1280px) |
| B9 Brier score comparativo | F9 | bar chart horizontal + labels | baja | no |
| B10 Divergencia con umbral | F10 | bar con linea de umbral | baja | si (por partido) |

---

## 4. JERARQUIA Y LAYOUT

```
+======================================================================+
| B1 HEADER (sticky top)                                              |
| [MODO ...] DD ... Banca ...                B2 [equity sparkline]    |
+======================================================================+
| TABS: [ Resumen ] [ Apuestas ] [ Rechazos ] [ Reglas ] [ Backtest ] |
+======================================================================+
|                                                            +--------+
|  CONTENIDO TAB ACTIVO                                      | B8     |
|                                                            | REGLAS |
|  Tab "Resumen"   -> KPIs (B9 Brier) + cluster summary      | sticky |
|  Tab "Apuestas"  -> B3 cluster cards con B5/B6/B10 dentro  |        |
|  Tab "Rechazos"  -> B4 tabla con filtros                   |        |
|  Tab "Reglas"    -> matrices completas read-only           |        |
|  Tab "Backtest"  -> equity historica + Brier + drawdowns   |        |
|                                                            +--------+
+======================================================================+
```

### Orden de lectura priorizado (top-to-bottom, left-to-right)

1. **Modo operativo** (B1) — golpe visual en 0.5s. ¿Estoy en NORMAL o DEFENSIVO?
2. **Drawdown vivo + banca** (B1 derecha) — ¿cuanto perdimos hoy?
3. **Equity sparkline** (B2) — tendencia ultimos 30d.
4. **Tab activo por defecto** = Apuestas (lo mas accionable).
5. Dentro de Apuestas: clusters ordenados por stake_total desc.
6. Dentro de cluster: filas ordenadas por EV desc.
7. Pipeline xG y stake desglose: cerrados por defecto, abren on demand.
8. Panel Reglas_IA (B8): siempre visible en pantallas grandes (referencia constante).

---

## 5. SISTEMA DE DISENO

### Tokens (heredados del visor + extension)

```css
:root {
  /* Heredados del visor de evals */
  --bg: #faf9f5;
  --surface: #ffffff;
  --border: #e8e6dc;
  --text: #141413;
  --text-muted: #b0aea5;
  --accent: #d97757;        /* OP1 */
  --accent-hover: #c4613f;
  --green: #788c5d;         /* MODO NORMAL, deltas positivos */
  --green-bg: #eef2e8;
  --red: #c44;              /* MODO DEFENSIVO, DIV_ALTA */
  --red-bg: #fceaea;
  --header-bg: #141413;
  --header-text: #faf9f5;
  --radius: 6px;

  /* Nuevos para dashboard operativo */
  --shadow-blue: #1976d2;       /* pill SHADOW */
  --shadow-blue-bg: rgba(33, 150, 243, 0.12);
  --amber: #f57f17;             /* EV_BAJO, badges secundarios */
  --amber-bg: rgba(255, 193, 7, 0.15);

  /* Cluster border-left por liga (paleta categorica accesible) */
  --cluster-arg: #6BAED6;
  --cluster-bra: #FDD835;
  --cluster-eng: #C44;
  --cluster-tur: #8B4513;
  --cluster-nor: #1565C0;

  /* Tipografia */
  --font-display: 'Poppins', sans-serif;
  --font-body: 'Lora', Georgia, serif;
  --font-mono: 'SF Mono', SFMono-Regular, Consolas, 'Liberation Mono', Menlo, monospace;
}
```

### Tipografia (escala explicita)

| Clase | Font | Tamano | Peso | Uso |
|---|---|---|---|---|
| `.t-modo-grande` | display | 1.125rem | 600 | chip MODO NORMAL/DEFENSIVO |
| `.t-section-h` | display | 1rem | 600 | titulos de tab/seccion |
| `.t-cluster-h` | display | 0.875rem | 600 | titulos de cluster card |
| `.t-label` | display | 0.75rem | 500 uppercase | labels uppercase (REGLAS, BANCA, etc.) |
| `.t-cell` | mono | 0.8125rem | 400 | numeros en tablas |
| `.t-cell-strong` | mono | 0.8125rem | 600 | stake_final, totales |
| `.t-body` | body | 0.9375rem | 400 | texto general |
| `.t-muted` | body | 0.75rem | 400 | metadatos, evidencia |

### Reglas de uso de color

- **Verde** (`--green`) = mejor que baseline / dentro de tolerancia / aceptado.
- **Rojo** (`--red`) = peor que baseline / fuera de tolerancia / rechazado por DIV_ALTA o modo defensivo.
- **Ambar** (`--amber`) = warning soft (EV_BAJO, factor neutro).
- **Azul** (`--shadow-blue`) = SHADOW (control sin Fix #5/Hallazgo G/Hallazgo C).
- **Naranja accent** (`--accent`) = OP1 (apuestas reales del fondo).
- **Gris muted** (`--text-muted`) = neutro, sin opinion.

### Densidades

- Cards de cluster: `padding: 1rem`, `gap: 0.75rem` interno.
- Chips/badges: `padding: 0.2rem 0.625rem`, `border-radius: 9999px`, `font-size: 0.6875rem uppercase`.
- Tablas densas: `padding: 0.5rem 0.75rem` por celda, `font-size: 0.8125rem`.
- Spacing entre bloques de tab: `gap: 1.25rem`.

---

## 6. INTERACCIONES

### Estados y triggers

| Componente | Estado por defecto | Trigger | Estado nuevo |
|---|---|---|---|
| Tabs | `Apuestas` activo | click tab | switch panel, scroll top |
| Cluster card | abierta | click summary | colapsada (mantiene header) |
| Pipeline xG `<details>` | cerrado | click summary | abierto |
| Stake desglose `<details>` | cerrado | click summary | abierto |
| Filtro rechazos | `[TODOS]` | click chip filtro | mostrar solo razon X |
| Toggle Shadow/OP1 | `Ambos` | click | filtrar tabla |
| Drawer Reglas_IA | abierto en >=1280px | click icono | colapsado/expandido |

### Atajos de teclado (heredados del visor)

| Tecla | Accion |
|---|---|
| `←` / `↑` | tab anterior |
| `→` / `↓` | tab siguiente |
| `R` | refresh datos (re-fetch operativo_data.json) |
| `?` | overlay con atajos |
| `Esc` | cerrar overlay/drawer |

---

## 7. ACCESIBILIDAD

- **Contraste**: todos los pares fg/bg deben pasar WCAG AA (4.5:1 texto normal, 3:1 texto grande). El verde y rojo actuales del visor cumplen contra `--bg`.
- **Iconos pass/fail** (✓/✗): siempre con `aria-label` y label de texto adyacente. NO solo simbolo.
- **Foco visible**: outline `2px solid var(--accent)` en todos los elementos interactivos.
- **`<details>`/`<summary>`** nativos: ya son accesibles por default.
- **Color como unico canal**: prohibido. El modo se distingue por chip + texto, no solo por color de fondo.
- **Lectura por screen reader**: cada cluster card lleva `aria-label="Cluster Argentina, 4 apuestas, factor 0.500"`.

---

## 8. RESPONSIVE

| Breakpoint | Layout |
|---|---|
| `>= 1280px` | drawer Reglas_IA sticky right (240px), contenido principal max-width 1024px |
| `768-1279px` | drawer Reglas_IA colapsado a icono lateral, expand on click (overlay) |
| `< 768px` | tabs horizontales scrollables, drawer fullscreen modal, cluster cards 1-col |

Limite minimo soportado: 360px (smartphones). Por debajo no se garantiza usabilidad.

---

## 9. PERFORMANCE

- Sin frameworks (vanilla JS, igual que el visor).
- `operativo_data.json` esperado < 500KB para 1 dia de operacion (50 apuestas + 50 rechazos + matrices).
- Si crece, paginar tabla rechazos (>100 filas).
- Sparkline B2: SVG inline, no canvas. 30 puntos = trivial.
- Renderizado inicial < 200ms en hardware modesto (i5 10ma, 8GB).

---

## 10. SHAPE DE DATOS

Contrato propuesto entre T6 (productor) y el HTML (consumidor).

```json
{
  "fecha_corte": "2026-04-16",                 // *
  "modo": "MODO NORMAL",                       // * string exacto: "MODO NORMAL" | "MODO DEFENSIVO"
  "modo_pct": "2.5",                           // * string formateado por backend (ej "2.5", "1.0")
  "banca": 10425.00,                           // *
  "drawdown_vivo_pct": -1.2,                   // *
  "liquidados_total": 187,                     // *
  "equity_30d": [10500, 10480, 10510, /* ... 30 cierres diarios */],  // *

  "clusters": [                                 // * lista por (liga, fecha)
    {
      "id": "ARG_2026-04-16",                  // *
      "liga": "Argentina",                     // * string exacto del backend (clave de matrices)
      "fecha": "2026-04-16",                   // *
      "n": 4,                                  // *
      "factor_corr_str": "x0.500",             // * string formateado por backend
      "factor_corr_num": 0.500,                // * numero crudo (para ordenar)
      "stake_total": 0.0641,
      "apuestas": [
        {
          "id_partido": "<id>",                // *
          "local": "Boca",                     // * string exacto (gestor_nombres.py)
          "visita": "River",                   // *
          "mercado": "1X2",                    // * "1X2" | "OU 2.5"
          "seleccion": "1",                    // * "1" | "X" | "2" | "OVER" | "UNDER"
          "tipo": "OP1",                       // * "OP1" | "SHADOW"
          "ev_pct": 4.2,                       // *
          "kelly_base": 0.030,                 // *
          "factor_cov_str": "x0.500",          // * formateado
          "delta_xg": 0.16,                    // *
          "factor_dxg_str": "x1.30",           // * formateado
          "stake_final": 0.0195,               // *
          "estado": "PENDIENTE",               // * "PENDIENTE" | "Liquidado" | "Calculado" | "Finalizado" (strings exactos)

          "pipeline_xg_local": [               // * para B5
            {"etapa": "xG_base",         "valor": 1.42, "factor": null,    "motivo": null},
            {"etapa": "fatiga",          "valor": 1.21, "factor": "x0.85", "motivo": "descanso 3 dias"},
            {"etapa": "altitud",         "valor": 1.33, "factor": "x1.10", "motivo": "Buenos Aires 25m"},
            {"etapa": "momentum",        "valor": 1.40, "factor": "x1.05", "motivo": null},
            {"etapa": "ajuste_tactico",  "valor": 1.58, "factor": "x1.13", "motivo": "OFE vs DEF"},
            {"etapa": "FINAL",           "valor": 1.58, "factor": null,    "motivo": null}
          ],
          "pipeline_xg_visit": [/* analogo */],

          "stake_pipeline": [                  // * para B6
            {"etapa": "Kelly_base",     "valor": 0.0300, "factor": null},
            {"etapa": "covarianza",     "valor": 0.0150, "factor": "x0.500"},
            {"etapa": "delta_xg",       "valor": 0.0195, "factor": "x1.30"},
            {"etapa": "cap_modo",       "valor": 0.0195, "factor": "min(0.0195, 0.025)"},
            {"etapa": "FINAL",          "valor": 0.0195, "factor": null}
          ],

          "divergencia": {                     // * para B10
            "valor": 0.08,
            "umbral_liga": 0.10,
            "fuera_rango": false
          }
        }
      ]
    }
  ],

  "rechazos": [                                 // * para B4
    {
      "id_partido": "<id>",
      "local": "Sevilla",
      "visita": "Betis",
      "mercado": "1X2",
      "razon": "EV_BAJO",                      // * string exacto del backend
      "detalle": "EV=1.2%"
    }
  ],

  "brier": {                                    // * para B9
    "bs_sistema": 0.218,
    "bs_casa": 0.241,
    "n": 156,
    "fecha_inicio": "2026-01-01"
  },

  "reglas_ia_snapshot": {                       // * para B8 — snapshot de constantes
    "ALFA_EMA_POR_LIGA": { "Argentina": 0.15, "Brasil": 0.20, "Inglaterra": 0.12, "Noruega": 0.18, "Turquia": 0.20 },
    "DIVERGENCIA_MAX_POR_LIGA": { /* ... */ },
    "RHO_POR_LIGA": { "Argentina": -0.074, "Brasil": -0.030, "Inglaterra": -0.030, "Noruega": -0.104, "Turquia": -0.062 },
    "FACTOR_CORR_XG_OU_POR_LIGA": { /* ... */ },
    "matriz_tactica": { "OFE": {/*...*/}, "EQU": {/*...*/}, "DEF": {/*...*/} }
  }
}
```

### Reglas del contrato

1. **Strings**: el frontend NUNCA modifica strings que vienen del backend. Render literal.
2. **Numeros formateados**: cuando el backend ya emite un display canonico (ej `"x0.500"`, `"2.5%"`, `"min(0.0195, 0.025)"`), el frontend lo renderiza tal cual.
3. **Numeros crudos**: cuando viene un `float`, el frontend formatea segun convencion local de la celda (3 decimales para EV%, 4 para Kelly, etc.).
4. **Campos opcionales**: cualquier campo no marcado con `*` puede ser `null`. El frontend muestra `—` o lo oculta.
5. **`reglas_ia_snapshot`**: autoritativo desde `config_sistema.py`. NO duplicar valores en HTML.
6. **Source of truth**: el JSON es regenerado por T6 cada vez que se ejecuta el orquestador. El frontend lo carga al `init()` (igual que `EMBEDDED_DATA` en el visor).

---

## 11. STRINGS EXACTOS

Catalogo no exhaustivo de strings del backend que el frontend renderiza literal:

### Modo operativo
- `"MODO NORMAL"`
- `"MODO DEFENSIVO"`

### Estados de pipeline
- `"PENDIENTE"`
- `"Calculado"`
- `"Finalizado"`
- `"Liquidado"`

### Mercados
- `"1X2"`
- `"OU 2.5"`

### Selecciones
- `"1"` | `"X"` | `"2"` (1X2)
- `"OVER"` | `"UNDER"` (OU 2.5)

### Cuatro Caminos (estrategia V4.3/V4.4)
- `"1"` | `"2"` | `"2B"` | `"3"`

### Ligas/paises (claves de matrices Reglas_IA)
- `"Argentina"`, `"Brasil"`, `"Inglaterra"`, `"Noruega"`, `"Turquia"`

### Razones de rechazo (motivo_rechazo)
Confirmadas:
- `EV_BAJO`
- `DIV_ALTA`
- `FLOOR`
- `CAMINO_2B_FUERA_RANGO`
- `SHADOW_ONLY`

[CONFIRMAR con T6]:
- `MIN_PARTIDOS_INSUFICIENTE`
- `LIGA_NO_CALIBRADA`
- `XG_FUERA_RANGO`
- `OPERAR_LOCAL` / `PASAR` (¿son razones de rechazo o decisiones del motor?)

### Tipo de apuesta
- `"OP1"`
- `"SHADOW"`

### Etapas pipeline xG (ver bloque B5)
[CONFIRMAR con T6 que el backend emite estos labels exactos]:
- `xG_base`, `fatiga`, `altitud`, `momentum`, `ajuste_tactico`, `FINAL`

### Etapas stake desglose (ver bloque B6)
[CONFIRMAR con T6]:
- `Kelly_base`, `covarianza`, `delta_xg`, `cap_modo`, `FINAL`

### Perfiles tacticos (matriz_tactica)
- `"OFE"` | `"EQU"` | `"DEF"`

---

## 12. OPEN QUESTIONS

Pendientes para coordinar con `tech-lead` y `junior-persistencia` (T6):

| # | Pregunta | Owner para responder |
|---|---|---|
| Q1 | ¿Quien produce `operativo_data.json`? Propuesta: T6, agregando un script `generar_operativo.py` en `src/persistencia/` que consulte la DB y emita el JSON | tech-lead |
| Q2 | ¿Donde vive el JSON? `dist/operativo_data.json` o embedido inline (como `EMBEDDED_DATA` en el visor)? | tech-lead |
| Q3 | ¿La lista cerrada de `motivo_rechazo` esta en `motor_calculadora.py`? Necesito validar el catalogo de strings de F2 | junior-prediccion / T1 |
| Q4 | ¿Las etapas del pipeline xG (`fatiga`, `altitud`, `momentum`, `ajuste_tactico`) tienen labels exactos en codigo, o se inventan? | junior-prediccion |
| Q5 | ¿`operativo_data.json` se regenera en cada corrida del orquestador? ¿Frecuencia esperada? | tech-lead |
| Q6 | ¿Hay un equity historico ya persistido o hay que computarlo desde `partidos_backtest.estado='Liquidado'` y stakes? | junior-persistencia |
| Q7 | Brier score: ¿se computa en algun motor existente? Si no, ¿lo agrega T6 como nuevo campo? | junior-persistencia |
| Q8 | El campo `divergencia.umbral_liga` deberia leer la matriz `DIVERGENCIA_MAX_POR_LIGA`. ¿Quien empaqueta la matriz dentro del JSON? | junior-persistencia |
| Q9 | ¿Hay constraints de seguridad para servir el HTML (auth, IP allowlist)? | tech-lead / Lead |
| Q10 | ¿Hay datos sensibles en `operativo_data.json` que requieran cuidado especial al producirlo? | Lead |

---

## NEXT STEPS

1. T2 termina entregables (este doc + MOCKUPS.md + AUDITORIA_VISOR_EVALS.md).
2. T2 envia DM a `tech-lead` con Q1-Q10 para alinear shape de datos con queries que `junior-persistencia` implementara.
3. T2 espera REPORTE_FRICCIONES.md de `analista-riesgos` para refinar:
   - Strings exactos de `motivo_rechazo` (Q3).
   - Strings exactos de etapas pipeline (Q4).
   - Cualquier friccion P1 adicional no cubierta en bloques B1-B10.
4. Implementacion HTML real: **fuera de este ciclo** (PLAN.md Seccion 2).
