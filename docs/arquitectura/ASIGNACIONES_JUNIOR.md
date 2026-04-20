# ASIGNACIONES JUNIOR — Refactor Adepor

> Generado por `tech-lead` (T3) tras integrar specs de `analista-riesgos` (T1).
> **Esperando luz verde del `team-lead` antes de despertar a los juniors.**

---

## REGLAS COMUNES (los 3 juniors deben leer esto antes de tocar nada)

1. **Lectura obligatoria primero**:
   - `C:\Users\map12\.claude\teams\adepor-refactor\PLAN.md` (todo).
   - `C:\Users\map12\Desktop\Proyecto_Adepor\Reglas_IA.txt` (todo).
   - `docs/arquitectura/DEPENDENCIAS.md`, `PLAN_MODULAR.md` (este folder).
2. **Boundary rule**: solo escribís dentro de TU carpeta `src/<modulo>/`.
   La ÚNICA excepción es el shim ejecutable de tu motor en raíz (ver §0 abajo).
   Si necesitás cruzar frontera más allá de eso, mandás DM al `tech-lead`.
3. **Restricción bit-a-bit**:
   - Constantes, fórmulas, dicts por liga, matriz táctica, strings exactos: copiar tal cual.
   - Firmas de funciones públicas (ver DEPENDENCIAS.md §5): nunca renombrar ni reordenar parámetros.
   - Orden de aplicación: Hallazgo G **antes** de Fix #5. **Nunca invertir.**
4. **Cómo importar** (después del refactor):
   - `from src.comun.config_sistema import DB_NAME, LIGAS_ESPN, ...`
   - `from src.comun.gestor_nombres import obtener_nombre_estandar, ...`
   - **NO** importes entre módulos hermanos. Cada motor sigue siendo un script subprocess.
5. **Tu tarea NO incluye**:
   - Tocar la matemática (Hallazgo G/C, Dixon-Coles, EMA, etc.).
   - Cambiar firmas de funciones públicas.
   - Hacer migraciones SQL (ALTER TABLE). Si tu spec lo necesita, **DOCUMENTÁS** el schema
     propuesto en un comentario y mandás DM al tech-lead. **NO ejecutás el ALTER.**
   - Tocar `fondo_quant.db`. Para todo lo destructivo, `adepor_guard.py` saca snapshot primero.
6. **Verificación al terminar**:
   - `py -c "import src.<modulo>.<motor> as m; print('OK')"` en CADA archivo movido.
   - `py <motor>.py --help` (si el motor soporta `--help`) o `py -c "import <motor>; print('shim OK')"`
     desde la raíz, para validar el shim ejecutable.
   - Mandar DM al tech-lead con: archivos movidos, smoke test passed, columnas/tablas pendientes (si aplica).
7. **Stub policy (Conflicto C resuelto, Lead 2026-04-16)**: si T1 te pidió persistir
   un valor que el código aún no expone, **NO marcás TODO ni comentario en el archivo
   movido**. Cero diff vs HEAD pre-refactor más allá del cambio de import. La spec de
   migración futura vive 100% en `docs/arquitectura/MIGRACION_SCHEMA_PENDIENTE.md`. Sólo
   T6 puede crear archivos NUEVOS (como `queries_dashboard.py`), porque por ser nuevos
   no generan diff con código existente.

---

## §0 — SHIM EJECUTABLE EN RAÍZ (mandato Lead 2026-04-16, aplica a los 3 juniors)

Cada `motor_*.py` que movés a `src/<modulo>/` debe dejar en raíz un **shim ejecutable**
para preservar `.bat` legacy y subprocess legados.

### Paso A — verificar `main()` en el archivo canónico

T3 verificó (grep `^def main()`) que **12 de los 14 motores YA tienen `def main()` definida
y el guard `if __name__ == "__main__": main()` correcto**. NO requieren encapsulación.

**Excepciones — sólo estos 2 motores requieren encapsulación**:
- `motor_arbitro.py` (T4 junior-ingesta): el archivo termina en `if __name__ == "__main__":`
  con la lógica inline, sin `def main()`. T4 debe encapsular el bloque dentro de una
  función `main()` y dejar el guard apuntando a `main()`. **Sin alterar el código indentado** —
  solo cambiar el wrapping. Si encontrás variables que antes eran globales del bloque
  `if __name__` y son leídas por otras funciones top-level → STOP, DM al tech-lead.
- `motor_tactico.py` (T4 junior-ingesta): mismo caso. Mismo procedimiento.

**Para los otros 12 motores**: NO toques el bloque `main()` ni el guard. Solo el cambio
de import (ver spec por archivo más abajo).

**ESPECIAL**: `motor_calculadora.py` YA tiene `def main()` en línea 644 y el guard
correcto en línea 954. T5 solo cambia la línea del import. **Cero diff adicional**
(decisión Lead Conflicto C, mensajes 2026-04-16/17).

### Paso B — escribir el shim ejecutable en raíz

En la raíz `Proyecto_Adepor/motor_X.py` (reemplazás el archivo original por completo):

```python
# SHIM DE RETROCOMPATIBILIDAD — el código real vive en src/<modulo>/motor_X.py.
# Retirar tras migrar todos los .bat y ejecutar_proyecto.py a `python -m src.<modulo>.motor_X`.
# Inventario de callers en docs/arquitectura/DEUDA_TECNICA.md §D8.
from src.<modulo>.motor_X import *  # noqa: F401,F403

if __name__ == "__main__":
    from src.<modulo>.motor_X import main
    main()
```

Reemplazá `<modulo>` por `ingesta`, `nucleo`, o `persistencia` según corresponda.
Reemplazá `motor_X` por el nombre del archivo (sin `.py`).

### Paso C — verificación

Desde la raíz del repo:
```bash
py -c "import src.<modulo>.motor_X as m; assert hasattr(m,'main'), 'main() falta'; print('main() OK')"
py motor_X.py --help    # si el motor soporta --help
# o, si no soporta --help:
py -c "import motor_X; print('shim raíz OK')"
```

### Inventario de motores a los que aplica §0

| Junior | Motores con shim ejecutable obligatorio |
|---|---|
| junior-ingesta (T4) | motor_data, motor_fixture, motor_arbitro, motor_tactico, motor_cuotas |
| junior-prediccion (T5) | motor_calculadora, calibrar_rho, desbloquear_matriz |
| junior-persistencia (T6) | motor_sincronizador, motor_liquidador, motor_backtest, motor_purga, importador_gold, reset_tablas_derivadas |

Total: **14 motores** con shim ejecutable en raíz.

---

## T4 — junior-ingesta (Módulo A)

### Carpeta de escritura
`src/ingesta/**` (ya existe el `__init__.py` puesto por tech-lead).

### Tarea principal: mover 5 archivos
Copiar bit-a-bit desde la raíz a `src/ingesta/`, cambiando SOLO los imports:

| Origen                   | Destino                          |
|---|---|
| `motor_data.py`          | `src/ingesta/motor_data.py`      |
| `motor_fixture.py`       | `src/ingesta/motor_fixture.py`   |
| `motor_arbitro.py`       | `src/ingesta/motor_arbitro.py`   |
| `motor_tactico.py`       | `src/ingesta/motor_tactico.py`   |
| `motor_cuotas.py`        | `src/ingesta/motor_cuotas.py`    |

### Cambios EXACTOS por archivo (solo imports)

`motor_data.py`:
```diff
- import gestor_nombres
+ from src.comun import gestor_nombres
- from config_sistema import LIGAS_ESPN, DB_NAME
+ from src.comun.config_sistema import LIGAS_ESPN, DB_NAME
```

`motor_arbitro.py`:
```diff
- import gestor_nombres
+ from src.comun import gestor_nombres
- from config_sistema import LIGAS_ESPN, DB_NAME
+ from src.comun.config_sistema import LIGAS_ESPN, DB_NAME
```

`motor_fixture.py`:
```diff
- import gestor_nombres
+ from src.comun import gestor_nombres
- from config_sistema import LIGAS_ESPN, MAPA_LIGAS_ODDS, DB_NAME, API_KEYS_ODDS
+ from src.comun.config_sistema import LIGAS_ESPN, MAPA_LIGAS_ODDS, DB_NAME, API_KEYS_ODDS
```

`motor_tactico.py`:
```diff
- import gestor_nombres
+ from src.comun import gestor_nombres
- from config_sistema import DB_NAME, API_KEY_FOOTBALL, MAPA_LIGAS_API_FOOTBALL
+ from src.comun.config_sistema import DB_NAME, API_KEY_FOOTBALL, MAPA_LIGAS_API_FOOTBALL
```

`motor_cuotas.py`:
```diff
- import gestor_nombres
+ from src.comun import gestor_nombres
- from config_sistema import MAPA_LIGAS_ODDS, DB_NAME, API_KEYS_ODDS
+ from src.comun.config_sistema import MAPA_LIGAS_ODDS, DB_NAME, API_KEYS_ODDS
```

### Spec T1 — `prob_implicita` en `motor_cuotas.py`

T1 pidió persistir `prob_implicita_1 = 1/cuota_1` (y x, 2) cuando se cargan las cuotas.

**Decisión Lead 2026-04-16 (Conflicto C, aplicada por consistencia a T4)**: NO agregás
TODO ni comentario alguno en `motor_cuotas.py`. Por el mismo principio que rige T5:
cero diff vs HEAD pre-refactor más allá de la línea de import. Cualquier comentario
nuevo cuenta como diff y rompe el criterio bit-a-bit.

Acción concreta:
- NO modifiques `motor_cuotas.py` más allá del cambio de import (líneas 6 y 7).
- NO calculás ni persistís `prob_implicita_*`. Es trivialmente derivable como `1/cuota_*`
  on-the-fly por cualquier consumidor.
- Lectura derivable on-the-fly desde `cuota_1`/`cuota_x`/`cuota_2` — NO es bloqueante para el dashboard.
- La spec completa (qué columnas crear, qué UPDATE escribir, en qué línea) vive en
  `docs/arquitectura/MIGRACION_SCHEMA_PENDIENTE.md §1.3` y `§3`. La fase de implementación
  la autoriza el Lead, fuera del scope de este team.

### Boundary
- NO toques `motor_calculadora.py` ni nada de `src/nucleo/` o `src/persistencia/`.
- NO toques `gestor_nombres.py` en `src/comun/` (lo gestiona tech-lead).
- NO toques los `auditor/` ni `archivo/` legacy.
- **SÍ podés** reemplazar tus 5 `motor_*.py` en raíz por su shim ejecutable (ver §0).

### Verificación al terminar (canónico + shims)
```bash
# Imports canónicos
py -c "import src.ingesta.motor_data; print('motor_data OK')"
py -c "import src.ingesta.motor_fixture; print('motor_fixture OK')"
py -c "import src.ingesta.motor_arbitro; print('motor_arbitro OK')"
py -c "import src.ingesta.motor_tactico; print('motor_tactico OK')"
py -c "import src.ingesta.motor_cuotas; print('motor_cuotas OK')"

# Verificación main() existe
py -c "from src.ingesta.motor_data import main; print('main OK')"
# (idem para los otros 4)

# Shims ejecutables en raíz
py -c "import motor_data; print('shim motor_data OK')"
py -c "import motor_fixture; print('shim motor_fixture OK')"
py -c "import motor_arbitro; print('shim motor_arbitro OK')"
py -c "import motor_tactico; print('shim motor_tactico OK')"
py -c "import motor_cuotas; print('shim motor_cuotas OK')"
```
Los 15 deben imprimir OK sin ninguna excepción. Si algo falla → STOP, DM al tech-lead.

---

## T5 — junior-prediccion (Módulo B — NÚCLEO INTOCABLE)

### Carpeta de escritura
`src/nucleo/**`.

### Tarea principal: mover 3 archivos
| Origen                  | Destino                           |
|---|---|
| `motor_calculadora.py`  | `src/nucleo/motor_calculadora.py` |
| `calibrar_rho.py`       | `src/nucleo/calibrar_rho.py`      |
| `desbloquear_matriz.py` | `src/nucleo/desbloquear_matriz.py`|

### Cambios EXACTOS por archivo (solo imports)

`motor_calculadora.py`:
```diff
- from config_sistema import DB_NAME
+ from src.comun.config_sistema import DB_NAME
```

`calibrar_rho.py`:
```diff
- from config_sistema import DB_NAME, LIGAS_ESPN, API_KEY_FOOTBALL, MAPA_LIGAS_API_FOOTBALL
+ from src.comun.config_sistema import DB_NAME, LIGAS_ESPN, API_KEY_FOOTBALL, MAPA_LIGAS_API_FOOTBALL
```

`desbloquear_matriz.py`:
```diff
- DB_NAME = 'fondo_quant.db'
+ from src.comun.config_sistema import DB_NAME
```
> NOTA: `desbloquear_matriz.py` actualmente hardcodea `DB_NAME` (línea 9). Lo
> centralizamos porque el archivo es un script utilitario de mantenimiento (no del
> núcleo matemático del manifiesto). Esto NO viola la restricción bit-a-bit
> matemática — el valor de la constante es idéntico (`'fondo_quant.db'`).

### Spec T1 — Exposición de intermedios xG (xg_post_fatiga, etc.)

NO APLICA a este refactor. La persistencia de intermedios xG queda 100% diferida
a la fase futura de schema migration, especificada en
`docs/arquitectura/MIGRACION_SCHEMA_PENDIENTE.md`.

**T5 NO modifica `motor_calculadora.py` más allá del cambio de import** (línea
de `DB_NAME`). Cero TODOs nuevos, cero líneas comentadas, cero refactors.

Justificación: cualquier modificación al archivo del manifiesto — incluyendo
comentarios o bloques UPDATE comentados — genera diff vs HEAD pre-refactor y
rompe el criterio "diff de constantes/matrices = vacío" del PLAN §7. Decisión
explícita y reiterada del Lead (Conflicto C, mensajes 2026-04-17).

**[FIX APLICADO POR EL LEAD 2026-04-17]**: este bloque fue corregido
directamente por el team-lead tras detectar que la versión previa del documento
(escrita por tech-lead) reintroducía un bloque UPDATE comentado en
`motor_calculadora.py`, violando el veto explícito. Cualquier reedición de esta
sección requiere aprobación nueva del Lead.

**Lista de funciones públicas bloqueadas (firmas exactas que NO podés cambiar)**:
- `min_ev_escalado(prob)`
- `multiplicador_delta_stake(delta_xg)`
- `aplicar_hallazgo_g(p1, px, p2, pais, hallazgo_g_data)`
- `corregir_calibracion(p1, px, p2)`
- `corregir_ventaja_local(xg_local, xg_visita, liga=None)` (revertida pero presente — no tocar)
- `evaluar_mercado_1x2(p1, px, p2, c1, cx, c2, liga=None)`
- `evaluar_mercado_ou(po, pu, co, cu, p1, px, p2, xg_local=None, xg_visita=None)`
- `calcular_stake_independiente(pick, ev, cuota, bankroll, max_kelly_pct)`
- `ajustar_stakes_por_covarianza(lista_apuestas)`
- `tau(i, j, lam, mu, rho)`
- `poisson(k, lmbda)`
- `detectar_drawdown(cursor, umbral=DRAWDOWN_THRESHOLD)`

**Constantes/dicts bloqueados** (cualquier cambio = STOP):
- `RHO_FALLBACK = -0.09`, `FLOOR_PROB_MIN = 0.33`, `MARGEN_PREDICTIVO_1X2 = 0.03`
- `APUESTA_EMPATE_PERMITIDA = False`
- `DIVERGENCIA_MAX_POR_LIGA`, `FACTOR_CORR_XG_OU_POR_LIGA`, `CORR_VISITA_POR_LIGA`
- `MAX_KELLY_PCT_NORMAL = 0.025`, `MAX_KELLY_PCT_DRAWDOWN = 0.010`
- `DRAWDOWN_THRESHOLD = 5`, `FRACCION_KELLY = 0.50`
- `DELTA_STAKE_MULT_*`, `N_MIN_HALLAZGO_G = 50`, `BOOST_G_FRACCION = 0.50`
- `TECHO_CUOTA_OU = 6.0`, `MARGEN_XG_OU_OVER = 0.30`, `MARGEN_XG_OU_UNDER = 0.25`

### Boundary
- **NO toques `src/comun/`** (lo gestiona tech-lead).
- **NO toques `src/ingesta/` ni `src/persistencia/`**.
- **NO toques `Reglas_IA.txt`**. Es el manifiesto.
- **SÍ podés** reemplazar tus 3 `motor_*.py` (`motor_calculadora.py`, `calibrar_rho.py`,
  `desbloquear_matriz.py`) en raíz por su shim ejecutable (ver §0). Aplicar `main()` al
  bloque `if __name__` del CANÓNICO. **PRECAUCIÓN ESPECIAL en `motor_calculadora`**:
  este archivo es el más sensible. Si encapsular en `main()` mueve cualquier variable
  global usada por funciones top-level, **STOP** y DM al tech-lead.

### Verificación al terminar (canónico + shims)
```bash
# Imports canónicos + funciones públicas presentes
py -c "import src.nucleo.motor_calculadora as m; \
       fns=['min_ev_escalado','multiplicador_delta_stake','aplicar_hallazgo_g', \
            'corregir_calibracion','evaluar_mercado_1x2','evaluar_mercado_ou', \
            'calcular_stake_independiente','ajustar_stakes_por_covarianza', \
            'tau','poisson','detectar_drawdown','corregir_ventaja_local','main']; \
       missing=[f for f in fns if not hasattr(m,f)]; \
       print('OK' if not missing else 'MISSING: '+str(missing))"
py -c "import src.nucleo.calibrar_rho as m; assert hasattr(m,'main'); print('calibrar_rho OK')"
py -c "import src.nucleo.desbloquear_matriz as m; assert hasattr(m,'main'); print('desbloquear_matriz OK')"

# Constantes intactas
py -c "import src.nucleo.motor_calculadora as m; \
       assert m.RHO_FALLBACK == -0.09, 'RHO drift'; \
       assert m.FLOOR_PROB_MIN == 0.33, 'FLOOR drift'; \
       assert m.FRACCION_KELLY == 0.50, 'Kelly drift'; \
       assert m.APUESTA_EMPATE_PERMITIDA == False, 'Empate drift'; \
       print('Constantes intactas')"

# Shims ejecutables en raíz
py -c "import motor_calculadora; print('shim motor_calculadora OK')"
py -c "import calibrar_rho; print('shim calibrar_rho OK')"
py -c "import desbloquear_matriz; print('shim desbloquear_matriz OK')"
```
Los 7 prints deben pasar. Si UNO falla → STOP, DM al tech-lead.

---

## T6 — junior-persistencia (Módulo C)

### Carpeta de escritura
`src/persistencia/**`.

### Tarea principal: mover 6 archivos
| Origen                       | Destino                                       |
|---|---|
| `motor_sincronizador.py`     | `src/persistencia/motor_sincronizador.py`     |
| `motor_liquidador.py`        | `src/persistencia/motor_liquidador.py`        |
| `motor_backtest.py`          | `src/persistencia/motor_backtest.py`          |
| `motor_purga.py`             | `src/persistencia/motor_purga.py`             |
| `importador_gold.py`         | `src/persistencia/importador_gold.py`         |
| `reset_tablas_derivadas.py`  | `src/persistencia/reset_tablas_derivadas.py`  |

### Cambios EXACTOS por archivo (solo imports)

`motor_backtest.py`:
```diff
- import gestor_nombres
+ from src.comun import gestor_nombres
- from config_sistema import LIGAS_ESPN, MAPA_LIGAS_ODDS, DB_NAME, API_KEYS_ODDS
+ from src.comun.config_sistema import LIGAS_ESPN, MAPA_LIGAS_ODDS, DB_NAME, API_KEYS_ODDS
```

`motor_sincronizador.py`, `motor_liquidador.py`, `motor_purga.py`,
`importador_gold.py`, `reset_tablas_derivadas.py`:
- **NO TIENEN imports a config_sistema/gestor_nombres** — todos hardcodean
  `DB_NAME = 'fondo_quant.db'`.
- **Decisión T3**: NO los modifiques. Mové el archivo bit-a-bit. La deuda está
  documentada en `DEUDA_TECNICA.md §D5`. Es intencional dejarla para una iteración
  futura con autorización explícita.

### Spec T1 — Nuevas queries y schema migration

T1 pidió 7 capacidades de lectura. **TODAS requieren columnas/tablas que no existen
todavía** (verificado por T3 con `PRAGMA table_info` — ver `MIGRACION_SCHEMA_PENDIENTE.md`).

**Tu tarea NO es ejecutar el ALTER TABLE.** Tu tarea es:

1. Crear un archivo nuevo `src/persistencia/queries_dashboard.py` (NO existe aún —
   permitido porque está dentro de tu carpeta y es código de soporte, no toca lógica
   matemática; al ser un archivo nuevo no genera diff vs HEAD pre-refactor). Contenido
   propuesto:

```python
# ==========================================
# QUERIES DASHBOARD V0.1 (STUBS — schema pendiente)
# Ver docs/arquitectura/MIGRACION_SCHEMA_PENDIENTE.md para schema propuesto y plan de
# implementación post-refactor. Cada stub retorna None/[] hasta que el Lead apruebe
# la migración.
# ==========================================
import sqlite3
from src.comun.config_sistema import DB_NAME

def get_clusters_correlacion(fecha):
    """Returns rows agrupadas por (liga, fecha) con conteo N por cluster."""
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    rows = cur.execute("""
        SELECT pais, fecha, COUNT(*) AS n
        FROM partidos_backtest
        WHERE fecha = ?
          AND (apuesta_1x2 IS NOT NULL OR apuesta_ou IS NOT NULL)
        GROUP BY pais, fecha
    """, (fecha,)).fetchall()
    conn.close()
    return rows

def get_razon_rechazo(partido_id):
    """Stub — requiere tabla decisiones_log o columnas razon_rechazo_*.
    Ver MIGRACION_SCHEMA_PENDIENTE.md §1.4 / §1.5 / §2.2.
    """
    return None

def get_xg_desglose(partido_id):
    """Stub — requiere columnas xg_post_{fatiga,altitud,momentum}_{l,v}.
    Persistencia la hace motor_calculadora SOLO cuando se ejecute la fase de schema
    migration documentada en MIGRACION_SCHEMA_PENDIENTE.md — fase futura fuera de
    este refactor.
    """
    return None

def get_stake_desglose(apuesta_id):
    """Stub — requiere columnas kelly_base_*, factor_covarianza_*, factor_delta_*.
    Ver MIGRACION_SCHEMA_PENDIENTE.md §1.2.
    """
    return None

def get_modo_operativo():
    """Stub — requiere columna modo_operativo en partidos_backtest.
    Ver MIGRACION_SCHEMA_PENDIENTE.md §1.4.
    """
    return "NORMAL"

def get_equity_curve(desde_fecha):
    """Stub — derivable HOY de partidos_backtest WHERE estado='Liquidado' agrupando por
    fecha. NO implementado aquí para no duplicar lógica de calcular_metricas_dashboard()
    en motor_sincronizador.py:200. Ver MIGRACION_SCHEMA_PENDIENTE.md §4.
    """
    return []

def get_shadow_vs_op1():
    """Flag por apuesta indicando Shadow u Op1. Funcional con schema actual."""
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    rows = cur.execute("""
        SELECT id_partido,
               CASE WHEN apuesta_1x2 IS NOT NULL THEN 1 ELSE 0 END AS es_op1,
               CASE WHEN apuesta_shadow_1x2 IS NOT NULL THEN 1 ELSE 0 END AS es_shadow
        FROM partidos_backtest
        WHERE estado IN ('Calculado', 'Finalizado', 'Liquidado')
    """).fetchall()
    conn.close()
    return rows
```

2. NO ejecutar este archivo en producción (es solo lectura, pero los stubs no aportan
   valor todavía). Existe para documentar el contrato y darle a T2 (disenador-ux) un
   punto de import claro.

3. En el DM final al tech-lead, listar:
   - Cuáles de las 7 funciones quedaron operativas con el schema actual (`get_clusters_correlacion`, `get_shadow_vs_op1`, parcialmente `get_equity_curve`).
   - Cuáles quedaron como stub esperando schema (las 4 restantes).

### Spec T1 — Razon de rechazo (D6 deuda)

T1 pidió `get_razon_rechazo(partido_id)`. Esto requiere que `motor_calculadora` LOGUEE
la razón cuando rechaza una apuesta. **Esa modificación NO la hacés vos** (no podés
tocar `src/nucleo/`). La implementación completa queda diferida a la fase de migración:
- Schema migration (`razon_rechazo_1x2 TEXT` en `partidos_backtest`, o tabla `decisiones_log`).
  Ver `MIGRACION_SCHEMA_PENDIENTE.md §1.4` y `§1.5`.
- Modificación de `motor_calculadora` para escribir la razón. Spec en
  `MIGRACION_SCHEMA_PENDIENTE.md §2.2`. Requiere autorización Lead.

### Boundary
- **NO toques `src/comun/`, `src/ingesta/`, `src/nucleo/`**.
- **NO ejecutes `ALTER TABLE`** sobre `fondo_quant.db`.
- **NO toques `adepor_eval_review.html`** (FUERA DE SCOPE — es un visor de
  evals de skill de Anthropic skill-creator, no es el dashboard operativo de
  Adepor. Queda en la raíz, intacto. Confirmado por Lead 2026-04-17). El
  dashboard operativo NUEVO es proyecto futuro; T2 entrega solo mockups +
  spec `OPERATIVO_DATA` en `docs/ux/`.
- **`queries_dashboard.py`** que vas a crear NO sirve a `adepor_eval_review.html`
  — sirve al data layer del futuro dashboard operativo y a auditoría manual
  del usuario. Tu trabajo de exponer esas 7 funciones SIGUE VIGENTE.
- **SÍ podés** reemplazar tus 6 `motor_*.py` en raíz por su shim ejecutable (ver §0).
  Recordá que `motor_sincronizador`, `motor_liquidador`, `motor_purga`, `importador_gold`,
  `reset_tablas_derivadas` hardcodean `DB_NAME` — eso se preserva tal cual en el canónico
  (no centralizar; ver `DEUDA_TECNICA.md §D5`).

### Verificación al terminar (canónico + shims)
```bash
# Imports canónicos
py -c "import src.persistencia.motor_sincronizador as m; assert hasattr(m,'main'); print('sincronizador OK')"
py -c "import src.persistencia.motor_liquidador as m;    assert hasattr(m,'main'); print('liquidador OK')"
py -c "import src.persistencia.motor_backtest as m;      assert hasattr(m,'main'); print('backtest OK')"
py -c "import src.persistencia.motor_purga as m;         assert hasattr(m,'main'); print('purga OK')"
py -c "import src.persistencia.importador_gold as m;     assert hasattr(m,'main'); print('importador OK')"
py -c "import src.persistencia.reset_tablas_derivadas as m; assert hasattr(m,'main'); print('reset OK')"
py -c "import src.persistencia.queries_dashboard as q; \
       print(q.get_shadow_vs_op1()[:3] if q.get_shadow_vs_op1() else 'sin datos aún')"

# Shims ejecutables en raíz (queries_dashboard NO necesita shim — es módulo nuevo, no script legado)
py -c "import motor_sincronizador; print('shim sincronizador OK')"
py -c "import motor_liquidador; print('shim liquidador OK')"
py -c "import motor_backtest; print('shim backtest OK')"
py -c "import motor_purga; print('shim purga OK')"
py -c "import importador_gold; print('shim importador OK')"
py -c "import reset_tablas_derivadas; print('shim reset OK')"
```
Los 13 deben imprimir OK. Si alguno falla → STOP, DM al tech-lead.

---

## COORDINACIÓN T3 ↔ T2 (disenador-ux) — `OPERATIVO_DATA`

`disenador-ux` (T2) está produciendo en `docs/ux/`:
- Mockups ASCII del dashboard operativo NUEVO.
- Spec del JSON `OPERATIVO_DATA` que el dashboard consumirá.

**Responsabilidad T3** (NO de los juniors): cuando T2 publique la spec, T3:
1. Compara los campos requeridos contra las 7 funciones de `queries_dashboard.py`.
2. Si todos los campos se pueden producir vía las queries actuales (con o sin
   schema migration documentada en `DEUDA_TECNICA.md §D7`), T3 confirma a T2.
3. Si T2 pide algún campo que requiere tocar el núcleo matemático
   (`src/nucleo/`), T3 hace **STOP** y consulta al Lead. NO autoriza a juniors
   a tocar matemática para servir el dashboard.

Los juniors **NO** participan de esta coordinación. `junior-persistencia`
construye `queries_dashboard.py` según la spec de este doc; cuando T2 + T3
acuerden la shape final, T3 puede pedir ajustes en una iteración posterior.

---

## ORDEN DE EJECUCIÓN

Los 3 juniors trabajan EN PARALELO. No hay dependencia entre módulos durante esta fase
(porque los motores no se importan entre sí). El tech-lead ensambla cuando los 3 reporten OK.

Cada junior, al terminar, manda DM al tech-lead con:
```
Tarea N → completed
Archivos movidos: [...]
Smoke tests: 5/5 OK
TODOs(spec-T1) dejados: [...]
Bloqueos pendientes: [...] (si aplica)
```

---

## CHECKLIST FINAL PRE-LEAD

T3 (tech-lead) hace ANTES de avisar al Lead:
- [ ] `diff` entre `src/comun/config_sistema.py` y la copia raíz pre-shim: SOLO las líneas
      documentadas en el comentario "AJUSTE OBLIGADO POR REUBICACION" (Opción 2).
      Smoke test confirma `_CONFIG_FILE` resuelve idéntico, `API_KEYS_ODDS` y
      `API_KEY_FOOTBALL` cargan idéntico.
- [ ] `diff` entre `src/comun/gestor_nombres.py` y la copia raíz pre-shim: vacío.
- [ ] `diff` entre `src/nucleo/desbloquear_matriz.py` y la copia raíz pre-shim: SOLO la línea de import de `DB_NAME` (excepción aprobada Lead 2026-04-17).
- [ ] Shim de raíz `config_sistema.py` y `gestor_nombres.py` con comentario marcador correcto.
- [ ] Shim ejecutable de raíz para los 14 `motor_*.py` (pattern: 3 líneas comentario + `from src.<modulo>.motor_X import *` + `if __name__=="__main__": from src... import main; main()`).
- [ ] Smoke import canónico de los 14 motores: 14/14 OK.
- [ ] Smoke import shim raíz de los 14 motores: 14/14 OK.
- [ ] Cada motor expone `main()` (asserts en verificación de cada junior).
- [ ] Constantes intactas (RHO_FALLBACK, FLOOR, Kelly, etc.) verificadas con asserts.
- [ ] `ejecutar_proyecto.py` actualizado a `python -m src.<modulo>.motor_X`.
- [ ] `python ejecutar_proyecto.py --audit-names` corre sin error (modo no destructivo).
- [ ] `DEUDA_TECNICA.md §D5` con inventario completo (17 sitios), `§D8` con callers externos
      y `§D9` con audit de paths Tipo 1/2/3: los tres completos.
- [ ] AUDIT_PATHS (§D9) sigue siendo válido tras el refactor: ningún Tipo 2 nuevo apareció.
