# MIGRACIÓN DE SCHEMA — PENDIENTE (post-refactor)

> Spec ejecutable de la fase de schema migration. **NO se implementa en el refactor actual.**
> Autoriza el Lead, en una iteración separada, fuera del scope de este team.
>
> Origen: pedidos de `analista-riesgos` (T1) que requieren columnas/tablas que no existen.
> Decisión Lead 2026-04-16 (Conflicto C): cero modificaciones a `motor_calculadora.py` ni
> a otros archivos del núcleo durante este refactor — toda la spec vive aquí.

Fecha: 2026-04-16. Snapshot código de referencia: HEAD `508063f` post-refactor (`src/`).

---

## 1. ALTER TABLE — `partidos_backtest`

Columnas nuevas necesarias para implementar las 7 queries de T1 que hoy quedan como stub
en `src/persistencia/queries_dashboard.py`.

### 1.1 Intermedios xG (driver: `get_xg_desglose`)

```sql
ALTER TABLE partidos_backtest ADD COLUMN xg_post_fatiga_l   REAL;
ALTER TABLE partidos_backtest ADD COLUMN xg_post_fatiga_v   REAL;
ALTER TABLE partidos_backtest ADD COLUMN xg_post_altitud_l  REAL;
ALTER TABLE partidos_backtest ADD COLUMN xg_post_altitud_v  REAL;
ALTER TABLE partidos_backtest ADD COLUMN xg_post_momentum_l REAL;
ALTER TABLE partidos_backtest ADD COLUMN xg_post_momentum_v REAL;
```

### 1.2 Intermedios de stake (driver: `get_stake_desglose`)

```sql
ALTER TABLE partidos_backtest ADD COLUMN kelly_base_1x2          REAL;
ALTER TABLE partidos_backtest ADD COLUMN kelly_base_ou           REAL;
ALTER TABLE partidos_backtest ADD COLUMN factor_covarianza_1x2   REAL;
ALTER TABLE partidos_backtest ADD COLUMN factor_covarianza_ou    REAL;
ALTER TABLE partidos_backtest ADD COLUMN factor_delta_1x2        REAL;
ALTER TABLE partidos_backtest ADD COLUMN factor_delta_ou         REAL;
```

### 1.3 Probabilidad implícita derivada (driver: análisis CLV)

```sql
ALTER TABLE partidos_backtest ADD COLUMN prob_implicita_1 REAL;
ALTER TABLE partidos_backtest ADD COLUMN prob_implicita_x REAL;
ALTER TABLE partidos_backtest ADD COLUMN prob_implicita_2 REAL;
```

> **Nota**: `prob_implicita_*` es trivialmente derivable on-the-fly como `1/cuota_*`.
> La columna persistida solo aporta valor si los consumidores son muchos y la query
> tiene que filtrar por ese campo. T3 lo deja documentado pero recomienda **NO crear
> estas tres columnas** si solo se usan para mostrar; calcular `1/cuota_X AS prob_implicita_X`
> en cada SELECT alcanza.

### 1.4 Modo operativo y razón de rechazo (driver: `get_modo_operativo`, `get_razon_rechazo`)

```sql
ALTER TABLE partidos_backtest ADD COLUMN modo_operativo TEXT DEFAULT 'NORMAL';
ALTER TABLE partidos_backtest ADD COLUMN razon_rechazo_1x2 TEXT;
ALTER TABLE partidos_backtest ADD COLUMN razon_rechazo_ou  TEXT;
ALTER TABLE partidos_backtest ADD COLUMN es_shadow INTEGER DEFAULT 0;
```

### 1.5 Alternativa preferida T3: tabla `decisiones_log`

En vez de inflar `partidos_backtest` a 70+ columnas, T3 propone una tabla satelital:

```sql
CREATE TABLE IF NOT EXISTS decisiones_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    id_partido     INTEGER NOT NULL,
    mercado        TEXT NOT NULL,            -- '1x2' | 'OU'
    pick           TEXT,                     -- 'L' | 'X' | 'V' | 'O' | 'U' | NULL
    ev             REAL,
    prob_estimada  REAL,
    cuota          REAL,
    floor_aplicado INTEGER DEFAULT 0,        -- 0/1
    razon_rechazo  TEXT,                     -- EV_BAJO | FLOOR | DIV_ALTA | CAMINO_2B_FUERA_RANGO | TECHO_CUOTA | EMPATE_BLOQUEADO | NULL
    modo_operativo TEXT,                     -- NORMAL | DEFENSIVO
    es_shadow      INTEGER DEFAULT 0,
    timestamp      TEXT NOT NULL,            -- ISO8601 UTC
    FOREIGN KEY (id_partido) REFERENCES partidos_backtest(id_partido)
);
CREATE INDEX IF NOT EXISTS idx_decisiones_partido ON decisiones_log(id_partido);
CREATE INDEX IF NOT EXISTS idx_decisiones_razon   ON decisiones_log(razon_rechazo);
```

Decisión final entre 1.4 y 1.5: del Lead, en la fase de migración.

---

## 2. UPDATEs en `motor_calculadora.py` (post-migración)

> **REFERENCIA**: estos cambios NO se aplican ahora. Se documentan aquí para que la
> fase futura sepa exactamente dónde insertar el código sin tocar el resto del archivo.

### 2.1 Persistencia de intermedios xG

Después del bloque actual de UPDATE en `src/nucleo/motor_calculadora.py` (alrededor de
la línea 912 — fase 4 "ACTUALIZACION EN DB"), agregar al SET las nuevas columnas:

```python
# Pseudocódigo del UPDATE expandido (NO IMPLEMENTAR HOY):
cursor.execute("""
    UPDATE partidos_backtest
    SET prob_1=?, prob_x=?, prob_2=?, prob_o25=?, prob_u25=?,
        apuesta_1x2=?, apuesta_ou=?, stake_1x2=?, stake_ou=?,
        apuesta_shadow_1x2=?, stake_shadow_1x2=?,
        incertidumbre=?, xg_local=?, xg_visita=?,
        shadow_xg_local=?, shadow_xg_visita=?,
        -- NUEVOS (fase migración):
        xg_post_fatiga_l=?, xg_post_fatiga_v=?,
        xg_post_altitud_l=?, xg_post_altitud_v=?,
        xg_post_momentum_l=?, xg_post_momentum_v=?,
        kelly_base_1x2=?, kelly_base_ou=?,
        factor_covarianza_1x2=?, factor_covarianza_ou=?,
        factor_delta_1x2=?, factor_delta_ou=?,
        modo_operativo=?, es_shadow=?,
        estado='Calculado'
    WHERE id_partido=?
""", (...))
```

**Pre-requisito código**: las variables `xg_l_post_fat`, `xg_v_post_fat`, etc., deben
existir como locals en el scope del loop principal de `main()`. T3 verificó que las
fases del pipeline (Fatiga, Altitud, Momentum) operan secuencialmente sobre el mismo
xG, sobrescribiendo la variable. **Para persistir intermedios, el junior de la fase
futura debe RENOMBRAR cada paso intermedio a una variable propia** (`xg_l_post_fat`,
`xg_l_post_alt`, `xg_l_post_mom`) en vez de reusar `xg_local`. Eso ES un refactor del
núcleo y requiere autorización Lead bajo el manifiesto.

### 2.2 Logging de razón de rechazo

Cada vez que `evaluar_mercado_1x2` o `evaluar_mercado_ou` retornen un pick que NO se
apuesta, capturar la razón:

```python
# Pseudocódigo (NO IMPLEMENTAR HOY):
if pick_1x2.startswith("[NO APOSTAR]"):
    razon = extraer_razon(pick_1x2)  # parsear el string del log existente
    cursor.execute("""
        INSERT INTO decisiones_log (id_partido, mercado, pick, ev, prob_estimada,
                                    cuota, razon_rechazo, modo_operativo, es_shadow, timestamp)
        VALUES (?, '1x2', ?, ?, ?, ?, ?, ?, 0, datetime('now'))
    """, (id_partido, pick_real, ev, prob, cuota, razon, modo_op))
```

Las strings exactas de razón vienen del código actual de `evaluar_mercado_*`:
- `EV_BAJO` (EV < min_ev_escalado(prob))
- `FLOOR` (prob < FLOOR_PROB_MIN)
- `DIV_ALTA` (divergencia xG-cuota > DIVERGENCIA_MAX_POR_LIGA[liga])
- `CAMINO_2B_FUERA_RANGO` (Hallazgo C, Camino 2B no aplicable)
- `TECHO_CUOTA` (cuota_OU > TECHO_CUOTA_OU)
- `EMPATE_BLOQUEADO` (pick == 'X' y APUESTA_EMPATE_PERMITIDA == False)

### 2.3 Logging de Hallazgo G activación (resuelve §D3 de DEUDA_TECNICA)

Cuando `aplicar_hallazgo_g` se activa (N >= 50 en una liga), registrar:

```python
# Pseudocódigo (NO IMPLEMENTAR HOY):
print(f"[HALLAZGO G] {pais} N={N} freq_real={freq_real:.4f} boost_aplicado={boost:.4f}")
# o más estructurado:
cursor.execute("""
    INSERT INTO decisiones_log (id_partido, mercado, razon_rechazo, modo_operativo, timestamp)
    VALUES (?, '1x2', 'HALLAZGO_G_APLICADO', ?, datetime('now'))
""", (id_partido, modo_op))
```

---

## 3. UPDATEs en `motor_cuotas.py` (post-migración)

Persistir `prob_implicita_*` cuando se cargan las cuotas:

```python
# Pseudocódigo (NO IMPLEMENTAR HOY) — solo si se decide en 1.4 SÍ persistir las columnas:
cursor.execute("""
    UPDATE partidos_backtest
    SET cuota_1=?, cuota_x=?, cuota_2=?, cuota_o25=?, cuota_u25=?,
        prob_implicita_1=?, prob_implicita_x=?, prob_implicita_2=?
    WHERE id_partido=?
""", (c1, cx, c2, co, cu, 1/c1, 1/cx, 1/c2, id_partido))
```

> **Recomendación T3**: NO persistir. Calcular `1/cuota_X` on-the-fly cuando se lea.
> Cero deuda matemática, cero columnas nuevas.

---

## 4. UPDATEs en `src/persistencia/queries_dashboard.py`

Cuando el schema esté migrado, los stubs actuales se reemplazan por queries reales:

| Función                   | Estado actual    | Post-migración                                                              |
|---|---|---|
| `get_clusters_correlacion(fecha)`| Funcional (no stub)  | Sin cambios.                                                                |
| `get_shadow_vs_op1()`     | Funcional (no stub) | Sin cambios.                                                                |
| `get_equity_curve(desde)` | Stub (returna `[]`)| SELECT sobre `partidos_backtest` WHERE estado='Liquidado' agrupando por fecha. |
| `get_xg_desglose(id)`     | Stub (returna `None`)| SELECT xg_post_fatiga_l/v, xg_post_altitud_l/v, xg_post_momentum_l/v.       |
| `get_stake_desglose(id)`  | Stub (returna `None`)| SELECT kelly_base_*, factor_covarianza_*, factor_delta_*.                   |
| `get_razon_rechazo(id)`   | Stub (returna `None`)| SELECT mercado, razon_rechazo, modo_operativo FROM decisiones_log WHERE id_partido=?. |
| `get_modo_operativo()`    | Stub (returna `'NORMAL'`)| SELECT modo_operativo FROM partidos_backtest ORDER BY fecha DESC LIMIT 1.    |

---

## 5. Orden de aplicación recomendado por T3

Cuando el Lead autorice la fase de migración:

1. **Snapshot DB** vía `adepor_guard.py`. Sin esto, NO se ejecuta nada.
2. Ejecutar los `ALTER TABLE` (sección 1.1, 1.2, 1.4 o 1.5 según decisión Lead).
3. Smoke test: `PRAGMA table_info(partidos_backtest)` muestra las columnas nuevas.
4. **Refactor de motor_calculadora** (sección 2): renombrar las variables intermedias en
   el loop principal de `main()` para que `xg_l_post_fat`, `xg_l_post_alt`, `xg_l_post_mom`
   sean tres locals separados en vez de sobrescribir `xg_local`. Bit-a-bit en valores;
   estructural en nombres. **Requiere autorización explícita Lead bajo restricción §1**.
5. Ampliar el UPDATE de la sección 2.1.
6. Implementar el INSERT en `decisiones_log` (sección 2.2 y 2.3).
7. Reemplazar stubs en `queries_dashboard.py` (sección 4).
8. Backfill: ejecutar el pipeline sobre los partidos `Liquidado` históricos para llenar
   las nuevas columnas con valores recalculados (opcional, solo si se quiere análisis
   retroactivo).
9. Validación matemática Lead: bit-a-bit las apuestas que ya estaban en `Liquidado`
   con su valor de `apuesta_1x2/ou` y `stake_*` deben coincidir antes/después del
   refactor — si difieren, hubo un bug en el renombrado de variables del paso 4.

---

## 6. Riesgos identificados por T3

- **R1**: el renombrado de variables en `motor_calculadora.main()` puede introducir
  bugs sutiles si el código actual reusa la variable `xg_local` en una expresión que
  espera el valor post-momentum. Mitigación: backfill comparativo del paso 9.
- **R2**: si se opta por columnas en `partidos_backtest` (1.4) en vez de tabla
  satelital (1.5), el UPDATE crece a 25+ campos. Riesgo de typo en orden de parámetros
  posicionales. Mitigación: usar named parameters `:nombre` en SQLite.
- **R3**: `decisiones_log` puede crecer rápido (un row por evaluación de mercado, ~24
  por noche × 365 = ~9k/año). Sostenible para SQLite sin index, pero conviene index en
  `id_partido` y `razon_rechazo` desde el día 1.
- **R4**: La spec de `extraer_razon(pick_str)` (sección 2.2) parsea strings que el
  código actual emite. Si `evaluar_mercado_*` cambia el formato del string, el parser
  rompe en silencio. Mitigación: cuando se implemente, refactorizar para que la
  función retorne `(pick, razon)` en una tupla en vez de un string concatenado.
  Eso ES un cambio de firma → autorización Lead.

---

## 7. Estado

- **Refactor actual (2026-04-16)**: NO TOCAR `motor_calculadora.py` más allá del cambio
  de import. Stubs en `queries_dashboard.py` retornan `None` o `[]`. Cero ALTER TABLE.
- **Próxima fase (TBD)**: requerirá autorización Lead caso por caso, snapshot DB previo,
  y validación matemática post-cambio.
