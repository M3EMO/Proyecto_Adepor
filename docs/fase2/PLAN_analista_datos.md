# PLAN — Analista de Datos (DB owner) — Fase 2

> Plan de acción del agente `analista-datos` para el ciclo 2.0.
> **Sólo planificación.** No se ejecuta nada hasta autorización explícita del usuario vía Lead.
> Snapshot de inspección: `fondo_quant.db` HEAD `508063f`, fecha 2026-04-16.

Documentos de referencia leídos:
- `C:\Users\map12\.claude\teams\adepor-fase2\PLAN.md` (fuente única de verdad).
- `C:\Users\map12\Desktop\Proyecto_Adepor\Reglas_IA.txt` (manifiesto matemático, BLOQUEADO).
- `docs/arquitectura/MIGRACION_SCHEMA_PENDIENTE.md` (cubre intermedios xG, `decisiones_log`).
- `docs/arquitectura/DEUDA_TECNICA.md` (cubre DB_NAME hardcode, arbitros_historial vacía).

---

## 1. AUDITORÍA DEL SCHEMA ACTUAL

### 1.1 Inventario de tablas (9 tablas, ningún view/trigger, ninguna FK declarada)

| Tabla | Filas | PK | Observación |
|---|---|---|---|
| `arbitros_stats` | 0 | `id_arbitro` | **Vacía**. `motor_arbitro` nunca pobló. Campo `arbitro/id_arbitro` en `partidos_backtest` siempre `'NO'` (verificado: 0 filas con valor distinto). |
| `configuracion` | 1 | `clave` | Sólo `('bankroll','100000.0')`. `motor_sincronizador` ya intenta leer `'fraccion_kelly'` pero no existe → fallback a 0.50. |
| `ema_procesados` | 3599 | `id_partido` | **3431 huérfanos** (no existen en `partidos_backtest`). Es lo esperado: marca partidos consumidos para EMA, no requieren fila en backtest. NO es zombi. |
| `equipos_altitud` | 25 | `equipo_norm` | 8 entries no aparecen en `historial_equipos` (Cienciano, FBC Melgar, etc.). No es bug — son equipos sin partidos analizados aún. |
| `equipos_stats` | 122 | `id_equipo` | **TODA legacy.** 6 ligas con nombres exóticos ('Primera División', 'Premier League', 'Serie A Brasil', 'Süper Lig', 'Eliteserien', 'Desconocido'). `dt_nombre='Desconocido'` en 122/122. `fecha_actualizacion` máxima 2026-03-24 (antes del cierre fase 1). Ningún motor del pipeline actual la escribe. |
| `historial_equipos` | 238 | `equipo_norm` | **Tabla viva.** 12 ligas canónicas. `motor_data` la escribe en cada ciclo. Es el reemplazo real de `equipos_stats`. |
| `ligas_stats` | 12 | `liga` | Viva. Pero **`total_corners=0` y `coef_corner_calculado=0.02` en TODAS las ligas** (default nunca actualizado) — bug confirmado. |
| `log_alertas` | 107 | `id_alerta` | Viva. 7 entries no mapean a ningún `partidos_backtest` por `id_partido_<sufijo>` — apuntan a partidos purgados. |
| `partidos_backtest` | 321 | `id_partido` | 51 columnas. Tabla principal. Detalles más abajo. |

### 1.2 Hallazgos por tabla

#### A. `partidos_backtest` — INCONSISTENCIA CRÍTICA `estado` vs `apuesta_1x2`

- Las 321 filas tienen `estado='Pendiente'`. **Ninguna en `'Calculado'`/`'Liquidado'`/`'Finalizado'`** (los 4 estados nombrados en el manifiesto §1A).
- Sin embargo, `apuesta_1x2` SÍ refleja el ciclo: `[APOSTAR] LOCAL/VISITA`, `[GANADA] LOCAL/VISITA`, `[PERDIDA] LOCAL/VISITA`, `[PASAR] ...`.
- **Hipótesis**: el código actualiza `apuesta_1x2` pero no migra `estado`. Resultado: la columna `estado` está prácticamente muerta. Eso rompe el plan futuro de §4 de `MIGRACION_SCHEMA_PENDIENTE.md` (queries que filtran `WHERE estado='Liquidado'` retornarían 0 filas).
- Strings `'GANADA'`/`'PERDIDA'`/`'ANULADA'` aparecen embebidos en `apuesta_1x2`, nunca como `estado` propio.
- Conteos: 22 `[GANADA]`, 28 `[PERDIDA]`, 51 `[APOSTAR]` (futuros), resto `[PASAR]`.
- 222/321 con `cuota_1>0`; 99 partidos `[PASAR] Sin Cuotas`.
- 102/321 con `cuota_o25>0`.
- 201/321 con `goles_l NOT NULL` (pero 14 son `0-0` real vs 120 sin goles cargados).
- 54/321 con `corners_l NOT NULL`, **suma de córners = 0** → corners no se cargan desde ESPN aunque el campo exista.

> ⚠️ Esta inconsistencia `estado` ↔ `apuesta_1x2` es **bloqueante** para `MIGRACION_SCHEMA_PENDIENTE.md` §4. Antes de implementar las queries de dashboard, hay que decidir: ¿migramos `estado` a 4 valores reales, o derogamos la columna y las queries filtran por `apuesta_1x2 LIKE '[GANADA]%' OR LIKE '[PERDIDA]%'`?
>
> **Decisión requiere usuario** porque toca strings exactos del manifiesto (§1A).

#### B. `equipos_stats` — TABLA ZOMBI COMPLETA

- 122/122 filas con nombres de liga exóticos ('Primera División', 'Premier League', etc.). Ninguno coincide con los 12 países canónicos.
- 122/122 con `dt_nombre='Desconocido'` (default literal).
- `fecha_actualizacion` máxima 2026-03-24 — anterior a cualquier ciclo post-refactor.
- Verificación grep: `motor_data.py`, `motor_tactico.py`, `motor_calculadora.py` NO escriben en `equipos_stats` actualmente. (`motor_tactico.py` históricamente sí, pero no corrió desde el rename de ligas).
- **Veredicto**: tabla muerta, datos zombi 100%. Candidata a `DROP TABLE`.
- Riesgo: verificar que ningún `motor_*.py` la lea con `SELECT` antes de borrar (probable que `motor_tactico` siga el `INSERT OR REPLACE` esperando esta tabla).

#### C. `ligas_stats` — `total_corners=0` en todas las ligas

- `coef_corner_calculado=0.02` (default literal, nunca calibrado por motor_data).
- Confirma bug fase 1 §3: la fórmula del manifiesto II.A `(Córners * Coef_Liga)` aporta ~0 al xG híbrido.
- Causa raíz (verificada en `motor_data.py:374,457`): el código toma `coef_corner_actual = estado_ligas[pais].get('coef_c', 0.02)`. La clave `'coef_c'` nunca se popula en `estado_ligas` durante el procesamiento de partidos. El `INSERT OR REPLACE` final escribe el default 0.02 indefinidamente.
- Solución matemática (cómo calcular el coef): regresión `goles_reales ~ corners + sot + shots_off` por liga. **TOCA MATEMÁTICA → Manifiesto II.A → propuesta a `PROPUESTAS_MATEMATICAS.md` por `experto-deportivo`, no por mí**.
- Pero el upstream también está roto: `partidos_backtest.corners_l/v` está NULL en 267/321 filas, y suma=0 en las 54 con valor → **`motor_data.py` no parsea córners de ESPN**. Eso es bug de ingesta, no matemática.

#### D. `arbitros_stats` — vacía + schema ya declarado

- Tabla con 7 columnas declaradas pero 0 filas. `partidos_backtest.arbitro/id_arbitro` siempre `'NO'`.
- `motor_arbitro.py` no se ejecuta (verificable por logs). Decidir: ¿se reactiva o se deroga el módulo?

#### E. `configuracion` — sub-utilizada

- Sólo 1 entry (`bankroll`). El código lee también `'fraccion_kelly'` (no existe → fallback). 
- **Esta tabla es la base natural para `config_motor_valores`** (§2 de este plan).

### 1.3 Indexes y FK

- 9 PK auto-indexes, **0 indexes secundarios** definidos.
- **0 FK declaradas** (`PRAGMA foreign_keys` = OFF).
- Queries que se beneficiarían de index:
  - `partidos_backtest(fecha)` — lo recorre `motor_backtest`, `queries_dashboard.get_equity_curve`.
  - `partidos_backtest(pais, fecha)` — calculadora para historial táctico, fatiga.
  - `partidos_backtest(estado)` — si conservamos la columna como filtro.
  - `historial_equipos(liga)` — calculadora para `aplicar_hallazgo_g`.
  - `log_alertas(fecha_envio)` — queries de auditoría temporal.

### 1.4 PRAGMAs operativos

- `journal_mode=WAL` ✓ (correcto para concurrencia lectura/escritura).
- `wal_autocheckpoint=1000` (default).
- `foreign_keys=OFF` — declaración de FK no se enforce. Si agregamos FK en migración, hay que pensar pragma activación.
- `page_size=4096`, `page_count=156` → DB ~640 KB.

---

## 2. SCHEMA PROPUESTO — `config_motor_valores`

### 2.1 Diseño

Tabla canónica para todas las constantes hardcodeadas del manifiesto que tengan dimensión "por liga" o "global tunable". Los valores BLOQUEADOS por el manifiesto (Reglas_IA.txt §1A) **se persisten igual pero NO se editan**: la tabla refleja el estado del manifiesto, no lo reemplaza. Cualquier cambio de valor sigue requiriendo OK del usuario y entrada en `PROPUESTAS_MATEMATICAS.md`.

```sql
CREATE TABLE IF NOT EXISTS config_motor_valores (
    clave             TEXT NOT NULL,           -- ej: 'ALFA_EMA', 'DIVERGENCIA_MAX_1X2', 'FACTOR_CORR_XG_OU'
    scope             TEXT NOT NULL,           -- 'GLOBAL' o nombre de liga ('Argentina', 'Brasil', ...)
    valor_real        REAL,                    -- valor numérico (NULL si es texto)
    valor_texto       TEXT,                    -- valor textual (NULL si es numérico)
    tipo              TEXT NOT NULL,           -- 'REAL' | 'INTEGER' | 'TEXT' | 'BOOL'
    fuente            TEXT NOT NULL,           -- 'MANIFIESTO_V4.4' | 'MANIFIESTO_V4.9' | 'CALIBRACION_AUTO' | 'USUARIO'
    bloqueado         INTEGER NOT NULL DEFAULT 1, -- 1 = está bloqueado por manifiesto, no editar sin propuesta
    descripcion       TEXT,                    -- comentario human-readable
    fecha_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (clave, scope)
);
CREATE INDEX IF NOT EXISTS idx_config_clave ON config_motor_valores(clave);
```

### 2.2 Filas de ejemplo (snapshot del estado actual del código, sin alterar valores)

```sql
-- ALFA_EMA por liga (motor_data.py:29-36)
INSERT INTO config_motor_valores VALUES ('ALFA_EMA','Brasil',     0.20, NULL, 'REAL', 'MANIFIESTO_V4.4', 1, 'Reaccion EMA - alta volatilidad', CURRENT_TIMESTAMP);
INSERT INTO config_motor_valores VALUES ('ALFA_EMA','Turquia',    0.20, NULL, 'REAL', 'MANIFIESTO_V4.4', 1, 'Reaccion EMA - alta varianza',    CURRENT_TIMESTAMP);
INSERT INTO config_motor_valores VALUES ('ALFA_EMA','Noruega',    0.18, NULL, 'REAL', 'MANIFIESTO_V4.4', 1, 'Liga estacional corta',           CURRENT_TIMESTAMP);
INSERT INTO config_motor_valores VALUES ('ALFA_EMA','Argentina',  0.15, NULL, 'REAL', 'MANIFIESTO_V4.4', 1, 'BASE',                            CURRENT_TIMESTAMP);
INSERT INTO config_motor_valores VALUES ('ALFA_EMA','Inglaterra', 0.12, NULL, 'REAL', 'MANIFIESTO_V4.4', 1, 'Mercado eficiente',               CURRENT_TIMESTAMP);
INSERT INTO config_motor_valores VALUES ('ALFA_EMA','GLOBAL',     0.15, NULL, 'REAL', 'MANIFIESTO_V4.4', 1, 'Fallback global',                 CURRENT_TIMESTAMP);

-- DIVERGENCIA_MAX_POR_LIGA (motor_calculadora.py:104-)
INSERT INTO config_motor_valores VALUES ('DIVERGENCIA_MAX_1X2','Inglaterra', 0.10, NULL, 'REAL', 'MANIFIESTO_V4.4', 1, 'Premier mas eficiente', CURRENT_TIMESTAMP);
INSERT INTO config_motor_valores VALUES ('DIVERGENCIA_MAX_1X2','Argentina',  0.15, NULL, 'REAL', 'MANIFIESTO_V4.4', 1, 'BASE',                  CURRENT_TIMESTAMP);
INSERT INTO config_motor_valores VALUES ('DIVERGENCIA_MAX_1X2','Brasil',     0.18, NULL, 'REAL', 'MANIFIESTO_V4.4', 1, 'Algo de ineficiencia',  CURRENT_TIMESTAMP);
INSERT INTO config_motor_valores VALUES ('DIVERGENCIA_MAX_1X2','Noruega',    0.20, NULL, 'REAL', 'MANIFIESTO_V4.4', 1, '',                      CURRENT_TIMESTAMP);
INSERT INTO config_motor_valores VALUES ('DIVERGENCIA_MAX_1X2','Turquia',    0.20, NULL, 'REAL', 'MANIFIESTO_V4.4', 1, '',                      CURRENT_TIMESTAMP);
INSERT INTO config_motor_valores VALUES ('DIVERGENCIA_MAX_1X2','GLOBAL',     0.15, NULL, 'REAL', 'MANIFIESTO_V4.4', 1, 'Fallback',              CURRENT_TIMESTAMP);

-- FACTOR_CORR_XG_OU_POR_LIGA (motor_calculadora.py:80-)
INSERT INTO config_motor_valores VALUES ('FACTOR_CORR_XG_OU','Noruega',   0.524, NULL, 'REAL', 'MANIFIESTO_V4.9', 1, 'OU calibrado', CURRENT_TIMESTAMP);
INSERT INTO config_motor_valores VALUES ('FACTOR_CORR_XG_OU','Brasil',    0.603, NULL, 'REAL', 'MANIFIESTO_V4.9', 1, '',             CURRENT_TIMESTAMP);
INSERT INTO config_motor_valores VALUES ('FACTOR_CORR_XG_OU','Argentina', 0.642, NULL, 'REAL', 'MANIFIESTO_V4.9', 1, '',             CURRENT_TIMESTAMP);
INSERT INTO config_motor_valores VALUES ('FACTOR_CORR_XG_OU','Turquia',   0.648, NULL, 'REAL', 'MANIFIESTO_V4.9', 1, '',             CURRENT_TIMESTAMP);
INSERT INTO config_motor_valores VALUES ('FACTOR_CORR_XG_OU','GLOBAL',    0.627, NULL, 'REAL', 'MANIFIESTO_V4.9', 1, 'Fallback',     CURRENT_TIMESTAMP);

-- Constantes globales (motor_calculadora.py:60-168)
INSERT INTO config_motor_valores VALUES ('N0_ANCLA',                'GLOBAL',    5,    NULL,  'INTEGER', 'MANIFIESTO_V4.4', 1, 'Ancla bayesiana',                       CURRENT_TIMESTAMP);
INSERT INTO config_motor_valores VALUES ('FRACCION_KELLY',          'GLOBAL', 0.50,    NULL,  'REAL',    'MANIFIESTO_V4.0', 1, 'Medio Kelly Thorp 2006',                CURRENT_TIMESTAMP);
INSERT INTO config_motor_valores VALUES ('MAX_KELLY_PCT_NORMAL',    'GLOBAL', 0.025,   NULL,  'REAL',    'MANIFIESTO_V4.0', 1, 'Cap normal',                            CURRENT_TIMESTAMP);
INSERT INTO config_motor_valores VALUES ('MAX_KELLY_PCT_DRAWDOWN',  'GLOBAL', 0.010,   NULL,  'REAL',    'MANIFIESTO_V4.0', 1, 'Cap defensivo',                         CURRENT_TIMESTAMP);
INSERT INTO config_motor_valores VALUES ('DRAWDOWN_THRESHOLD',      'GLOBAL', 5,       NULL,  'INTEGER', 'MANIFIESTO_V4.0', 1, 'Perdidas consecutivas activan defensivo', CURRENT_TIMESTAMP);
INSERT INTO config_motor_valores VALUES ('FLOOR_PROB_MIN',          'GLOBAL', 0.33,    NULL,  'REAL',    'MANIFIESTO_V4.3', 1, 'Floor de probabilidad',                 CURRENT_TIMESTAMP);
INSERT INTO config_motor_valores VALUES ('MARGEN_PREDICTIVO_1X2',   'GLOBAL', 0.03,    NULL,  'REAL',    'MANIFIESTO_V4.3', 1, '',                                      CURRENT_TIMESTAMP);
INSERT INTO config_motor_valores VALUES ('MARGEN_PREDICTIVO_OU',    'GLOBAL', 0.05,    NULL,  'REAL',    'MANIFIESTO',      1, '',                                      CURRENT_TIMESTAMP);
INSERT INTO config_motor_valores VALUES ('TECHO_CUOTA_1X2',         'GLOBAL', 5.0,     NULL,  'REAL',    'MANIFIESTO_V4.3', 1, '',                                      CURRENT_TIMESTAMP);
INSERT INTO config_motor_valores VALUES ('TECHO_CUOTA_OU',          'GLOBAL', 6.0,     NULL,  'REAL',    'MANIFIESTO_V4.9', 1, '',                                      CURRENT_TIMESTAMP);
INSERT INTO config_motor_valores VALUES ('TECHO_CUOTA_ALTA_CONV',   'GLOBAL', 8.0,     NULL,  'REAL',    'MANIFIESTO_V4.3', 1, 'Camino 3',                              CURRENT_TIMESTAMP);
INSERT INTO config_motor_valores VALUES ('DIVERGENCIA_DESACUERDO_MAX','GLOBAL', 0.30,  NULL,  'REAL',    'MANIFIESTO_V4.3', 1, 'Camino 2B',                             CURRENT_TIMESTAMP);
INSERT INTO config_motor_valores VALUES ('MARGEN_XG_OU_OVER',       'GLOBAL', 0.30,    NULL,  'REAL',    'MANIFIESTO_V4.6', 1, 'Fix B',                                 CURRENT_TIMESTAMP);
INSERT INTO config_motor_valores VALUES ('MARGEN_XG_OU_UNDER',      'GLOBAL', 0.25,    NULL,  'REAL',    'MANIFIESTO_V4.6', 1, '',                                      CURRENT_TIMESTAMP);
INSERT INTO config_motor_valores VALUES ('RHO_FALLBACK',            'GLOBAL',-0.09,    NULL,  'REAL',    'MANIFIESTO_V4.4', 1, 'Fix #2',                                CURRENT_TIMESTAMP);
INSERT INTO config_motor_valores VALUES ('RHO_FLOOR',               'GLOBAL',-0.03,    NULL,  'REAL',    'MANIFIESTO_V4.4', 1, 'Floor MLE',                             CURRENT_TIMESTAMP);
INSERT INTO config_motor_valores VALUES ('N_MIN_HALLAZGO_G',        'GLOBAL', 50,      NULL,  'INTEGER', 'MANIFIESTO_V4.8', 1, '',                                      CURRENT_TIMESTAMP);
INSERT INTO config_motor_valores VALUES ('BOOST_G_FRACCION',        'GLOBAL', 0.50,    NULL,  'REAL',    'MANIFIESTO_V4.8', 1, '',                                      CURRENT_TIMESTAMP);
INSERT INTO config_motor_valores VALUES ('CALIBRACION_DELTA',       'GLOBAL', 0.042,   NULL,  'REAL',    'MANIFIESTO_V4.5', 1, 'Fix #5 boost bucket 40-50',             CURRENT_TIMESTAMP);
INSERT INTO config_motor_valores VALUES ('DELTA_STAKE_MULT_ALTO',   'GLOBAL', 1.30,    NULL,  'REAL',    'MANIFIESTO_V4.7', 1, 'Hallazgo C delta>=0.5',                 CURRENT_TIMESTAMP);
INSERT INTO config_motor_valores VALUES ('DELTA_STAKE_MULT_MED',    'GLOBAL', 1.15,    NULL,  'REAL',    'MANIFIESTO_V4.7', 1, 'Hallazgo C delta>=0.3',                 CURRENT_TIMESTAMP);

-- Switches (kill-switches del manifiesto, valor TEXT 'TRUE'/'FALSE' para evitar ambigüedad)
INSERT INTO config_motor_valores VALUES ('CALIBRACION_ACTIVA',       'GLOBAL', NULL, 'TRUE',  'BOOL', 'MANIFIESTO_V4.5', 1, 'Fix #5 on/off',          CURRENT_TIMESTAMP);
INSERT INTO config_motor_valores VALUES ('HALLAZGO_G_ACTIVO',        'GLOBAL', NULL, 'TRUE',  'BOOL', 'MANIFIESTO_V4.8', 1, 'on/off',                  CURRENT_TIMESTAMP);
INSERT INTO config_motor_valores VALUES ('DELTA_STAKE_ACTIVO',       'GLOBAL', NULL, 'TRUE',  'BOOL', 'MANIFIESTO_V4.7', 1, 'on/off',                  CURRENT_TIMESTAMP);
INSERT INTO config_motor_valores VALUES ('CORR_VISITA_ACTIVA',       'GLOBAL', NULL, 'FALSE', 'BOOL', 'MANIFIESTO_V4.6', 1, 'Fix A revertido',         CURRENT_TIMESTAMP);
INSERT INTO config_motor_valores VALUES ('APUESTA_EMPATE_PERMITIDA', 'GLOBAL', NULL, 'FALSE', 'BOOL', 'MANIFIESTO_V4.3', 1, 'Bloqueo total picks X',   CURRENT_TIMESTAMP);

-- Profundidades de scrape (motor_data.py:274-)
INSERT INTO config_motor_valores VALUES ('PROFUNDIDAD_INICIAL',        'GLOBAL',  365, NULL, 'INTEGER', 'MANIFIESTO',     1, 'Liga nueva',           CURRENT_TIMESTAMP);
INSERT INTO config_motor_valores VALUES ('PROFUNDIDAD_PROFUNDA',       'GLOBAL',  140, NULL, 'INTEGER', 'MANIFIESTO',     1, '',                     CURRENT_TIMESTAMP);
INSERT INTO config_motor_valores VALUES ('PROFUNDIDAD_MANTENIMIENTO',  'GLOBAL',    7, NULL, 'INTEGER', 'MANIFIESTO',     1, '',                     CURRENT_TIMESTAMP);
INSERT INTO config_motor_valores VALUES ('PROFUNDIDAD_PROFUNDA',       'Noruega', 365, NULL, 'INTEGER', 'MANIFIESTO',     1, 'Override Noruega',     CURRENT_TIMESTAMP);
```

### 2.3 Cómo el código consume la tabla (NO IMPLEMENTAR, sólo diseño)

```python
# src/comun/config_motor.py (NUEVO archivo, cero lógica matemática)

def get_param(clave, scope='GLOBAL', default=None):
    """Lee config_motor_valores. Cae a GLOBAL si scope no existe."""
    cur = sqlite3.connect(DB_NAME).cursor()
    cur.execute("""
        SELECT valor_real, valor_texto, tipo FROM config_motor_valores
        WHERE clave=? AND scope=?
    """, (clave, scope))
    row = cur.fetchone()
    if row is None and scope != 'GLOBAL':
        cur.execute("""
            SELECT valor_real, valor_texto, tipo FROM config_motor_valores
            WHERE clave=? AND scope='GLOBAL'
        """, (clave,))
        row = cur.fetchone()
    if row is None:
        return default
    valor_real, valor_texto, tipo = row
    if tipo == 'BOOL':  return valor_texto == 'TRUE'
    if tipo == 'TEXT':  return valor_texto
    if tipo == 'INTEGER': return int(valor_real)
    return valor_real

# En motor_calculadora.py el cambio bit-a-bit sería:
# ANTES: alfa = ALFA_EMA_POR_LIGA.get(pais, ALFA_EMA)
# DESPUES: alfa = get_param('ALFA_EMA', pais, default=0.15)
```

**Restricción crítica**: durante la migración, las constantes Python actuales se MANTIENEN como fallback hardcodeado. La función `get_param` lee la DB y compara contra el hardcode al cargar el módulo (asserción debug). Cualquier divergencia DB↔manifiesto → error fatal al boot. Eso garantiza que `bloqueado=1` se respete.

---

## 3. TAREAS PROPUESTAS (numeradas, con prioridad y esfuerzo)

> Esfuerzo: S=horas, M=día, L=multi-día. Prioridad: P0=bloqueante, P1=alto, P2=medio.

| # | Tarea | Prio | Esf | Bloqueado por | Pre-req |
|---|---|---|---|---|---|
| T1 | Snapshot DB obligatorio vía `adepor_guard.py` antes de TODO cambio destructivo. | P0 | S | — | OK usuario |
| T2 | Crear `config_motor_valores` (CREATE TABLE + seed con valores actuales del manifiesto). NO se conecta al código todavía. | P1 | S | T1 | OK usuario |
| T3 | Implementar `src/comun/config_motor.py` con `get_param()`. Tests de paridad con hardcodes. | P1 | M | T2 | tech-lead |
| T4 | DECISIÓN USUARIO: ¿migrar `partidos_backtest.estado` a 4 valores reales, o derogar columna? Necesario para queries dashboard. | P0 | S | — | OK usuario |
| T5 | Corregir `motor_data.py` para que `total_corners` se acumule realmente (no es matemática, es bug de ingesta). | P1 | M | — | tech-lead + experto-deportivo |
| T6 | Recalcular `coef_corner_calculado` por liga vía regresión histórica. **PROPUESTA MATEMÁTICA — owner: experto-deportivo, no yo**. | P1 | L | T5 | propuesta + OK usuario |
| T7 | Limpiar `equipos_stats` zombi: verificar que ningún motor la lea, luego `DROP TABLE` (o backup en `equipos_stats_legacy_2026`). | P2 | S | T1 | tech-lead audit + OK usuario |
| T8 | Decisión sobre `arbitros_stats`: reactivar `motor_arbitro` o derogar tabla. Hoy 0 filas y campo `arbitro='NO'` en 321/321 partidos. | P2 | S | — | OK usuario |
| T9 | Agregar indexes secundarios (lista §1.3): `idx_partidos_fecha`, `idx_partidos_pais_fecha`, `idx_historial_liga`, `idx_log_alertas_fecha`. | P2 | S | T1 | medible improvement |
| T10 | FK opcional declarativa: `log_alertas → partidos_backtest` (vía sufijo extraído). Probablemente no vale la pena por overhead. | P3 | S | — | discusión interna |
| T11 | Limpiar `log_alertas` 7 filas huérfanas (apuntan a partidos purgados). Bajo prio. | P3 | S | T1 | OK usuario |
| T12 | Audit del flujo openpyxl en `motor_sincronizador.py`: ver §4 abajo. | P1 | M | — | coordinar con disenador-excel |
| T13 | Agregar entries faltantes a `configuracion`: `'fraccion_kelly'`, `'modo_operativo_default'`, etc. (se subsume si T2 sale). | P2 | S | T2 | — |
| T14 | Documentar query patterns ineficientes detectados durante futura ejecución de tareas (vivo en `docs/fase2/DB_QUERY_PATTERNS.md`). | P2 | M | — | medir con `EXPLAIN QUERY PLAN` |

---

## 4. AUDIT FLUJO SQLite → Excel (motor_sincronizador.py + openpyxl)

### Hallazgos preliminares (lectura del código, NO ejecutado)

- `motor_sincronizador.py:1094` ejecuta `wb.save(EXCEL_FILE)` — escritura única al final, OK para concurrencia. No hay celda-por-celda.
- Patron correcto Manifiesto III: usa openpyxl bulk, no gspread.
- `motor_sincronizador.py:849-857` lee `bankroll` y `fraccion_kelly` desde tabla `configuracion`. La segunda no existe → fallback silencioso a 0.50. Bug menor.
- **Bloqueo de concurrencia detectado**: si `Backtest_Modelo.xlsx` está abierto en Excel cuando el motor corre → `PermissionError` en `wb.save()`. NO hay manejo defensivo (try/except con mensaje claro o write-to-temp+swap).
- `motor_sincronizador.py:14` usa `EXCEL_FILE = 'Backtest_Modelo.xlsx'` (cwd-relative, ya documentado en `DEUDA_TECNICA.md` §D9.b).
- No hay locks SQLite explícitos (`BEGIN IMMEDIATE`/`PRAGMA locking_mode`) — confiamos en WAL y en que no haya 2 procesos escribiendo al mismo tiempo. Está bien para uso actual (1 proceso a la vez).
- **Tarea propuesta para `disenador-excel`** (le DM ya cuando arranque): coordinar plan de write-to-temp + atomic rename para evitar PermissionError.

---

## 5. RIESGOS

### R1 — Cualquier mod al schema requiere snapshot previo
- Snapshot vía `adepor_guard.py` (verificar que el script funciona después del refactor de paths).
- DB actual ~640 KB → snapshot trivial.

### R2 — `equipos_stats` puede tener consumidor oculto
- Antes de `DROP TABLE`, grep exhaustivo en TODO el repo (`auditor/`, `analisis/`, `archivo/`, `.claude/`, etc.). T7 lo enumera.

### R3 — Tabla `config_motor_valores` debe respetar el manifiesto bit-a-bit
- Cualquier divergencia entre valor en DB y constante en `motor_calculadora.py` o `motor_data.py` → CRASH al boot del proceso (mejor falla fuerte que silenciosa).
- Ningún agente puede `UPDATE config_motor_valores` con `bloqueado=1` sin OK usuario.
- Implementar trigger de protección:
  ```sql
  CREATE TRIGGER trg_config_no_bloqueado
  BEFORE UPDATE ON config_motor_valores
  FOR EACH ROW WHEN OLD.bloqueado = 1 AND NEW.valor_real IS NOT OLD.valor_real
  BEGIN
      SELECT RAISE(ABORT, 'Cambio en valor bloqueado requiere desbloqueo explicito');
  END;
  ```

### R4 — Decisión `estado` partidos_backtest impacta downstream
- Si se conserva la columna y se migra, `MIGRACION_SCHEMA_PENDIENTE.md` §4 puede implementarse tal cual.
- Si se deroga, hay que reescribir todas las queries futuras de dashboard.
- **Esto no lo decido yo. Es DM al usuario.**

### R5 — Todas las migraciones son irreversibles sin snapshot
- Política dura: cualquier `ALTER TABLE`/`DROP TABLE`/`UPDATE` masivo debe ir precedido por `adepor_guard.py snapshot` y verificación post-ejecución.

---

## 6. DEPENDENCIAS CON OTROS AGENTES

| Tarea | Necesito de | Para qué |
|---|---|---|
| T3 (config_motor.py) | `tech-lead` | Implementar la función `get_param()` y migrar callers. Yo diseño el schema, él escribe el código. |
| T5 (corners ingesta) | `tech-lead` + `experto-deportivo` | Tech lead arregla `motor_data.py`; experto-deportivo valida que el cambio matemático no rompe el manifiesto II.A. |
| T6 (recalcular coef_corner) | `experto-deportivo` (owner) | Es propuesta matemática → `PROPUESTAS_MATEMATICAS.md`, no la escribo yo. |
| T7 (limpiar equipos_stats) | `tech-lead` (audit) | Confirmar que ningún motor lee la tabla antes de `DROP`. |
| T8 (arbitros_stats) | usuario | Decisión política: ¿activamos motor_arbitro o derogamos? |
| T12 (Excel concurrency) | `disenador-excel` | Coordinar patrón write-to-temp + rename atómico. |
| `analista-sistemas` (DM cuando arranque) | data flow doc | Validar que nuestro audit de inserts/updates coincide con su diagrama de flujo. |

---

## 7. NECESITO DECIDIR CON EL USUARIO

1. **Columna `partidos_backtest.estado`**: migrar a 4 valores reales (`Pendiente|Calculado|Finalizado|Liquidado`) o derogar la columna.
2. **`equipos_stats` zombi**: `DROP TABLE` o conservar como `equipos_stats_legacy_2026`.
3. **`arbitros_stats` + módulo arbitro**: reactivar o derogar.
4. **Estrategia de calibración `coef_corner` por liga**: cuando experto-deportivo proponga una fórmula, ¿se acepta backtest n>=15 partidos como evidencia mínima, o se exige n>=50?
5. **Tabla `config_motor_valores`**: ¿OK al diseño? ¿Aceptamos la doble redundancia (valor en DB + hardcode en .py + assert al boot) como mecanismo de seguridad?

---

## 8. ESTADO

- Plan escrito, sin tocar la DB ni los .py.
- IDLE hasta autorización Lead → usuario.
- Próxima acción solo cuando reciba OK explícito por DM.
