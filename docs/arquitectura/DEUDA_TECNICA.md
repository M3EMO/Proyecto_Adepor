# DEUDA TÉCNICA — Refactor Adepor

> Banderas rojas detectadas por `analista-riesgos` (T1) y confirmadas por `tech-lead` (T3).
> **Estas deudas NO se arreglan en el refactor actual** — solo se documentan.
> Se priorizan en una iteración posterior con autorización explícita del Lead.

Fecha: 2026-04-16. Snapshot: HEAD `508063f`.

---

## D1. `corregir_ventaja_local()` revertida pero presente

- **Ubicación**: `motor_calculadora.py:324` (en post-refactor: `src/nucleo/motor_calculadora.py:324`).
- **Descripción**: Fix A fue implementado, mostró yield -35.9pp en backtest de 32 partidos
  (ver Reglas_IA.txt §II.C) y se revirtió. La función queda en el archivo como referencia
  histórica con flag `CORR_VISITA_ACTIVA = False`.
- **Riesgo**: bajo — código muerto bien documentado. No se ejecuta.
- **Confirmado en código**:
  - `motor_calculadora.py:29` (changelog) y `:171` (constantes CORR_VISITA_*).
  - `auditor/auditor_obsoletos.py:41` ya marca esta función como "revertida pero retenida".
- **Acción futura**: si tras 6 meses sin reactivación, eliminar la función + constantes
  CORR_VISITA_*. Requiere autorización del Lead (toca matemática).

## D2. `DIVERGENCIA_MAX_OU` eliminada — verificar referencias muertas

- **Ubicación**: `motor_calculadora.py:70` (comentario).
- **Descripción**: la constante fue removida en V4.9 porque el filtro `div<=0.05` bloqueaba
  el 100% de apuestas O/U. Se reemplazó por Fix B (margen xG asimétrico).
- **Verificación T3 (grep)**: NO quedan referencias activas en `*.py`. Solo aparece en:
  - `motor_calculadora.py:70` — comentario explicativo (correcto, dejar).
  - Reglas_IA.txt — manifiesto histórico (no se toca).
- **Riesgo**: ninguno — limpieza ya hecha implícitamente.
- **Acción futura**: agregar nota en Reglas_IA.txt §IV.D2 para clarificar la eliminación.

## D3. Hallazgo G no logea su activación

- **Ubicación**: `motor_calculadora.py:258` (`aplicar_hallazgo_g`).
- **Descripción**: cuando `N_liquidados_por_liga >= 50` y se activa el boost, no hay
  `print()` ni `cursor.execute()` que registre el evento. Imposibilita auditar a posteriori
  qué partidos recibieron corrección.
- **Estado actual**: inactivo en todas las ligas (ninguna tiene N >= 50).
- **Riesgo**: medio — cuando se active automáticamente, no podremos diferenciar Op1 vs
  Shadow por el log si el boost cambió la decisión. Bloquea la metodología de validación
  Op1 vs Shadow descrita en Reglas_IA.txt §IV.K.
- **Acción futura**: agregar logging estructurado (`print(f"[HALLAZGO G] {pais} N={N} freq_real={fr} boost={b}")`)
  cuando T6 implemente el sistema de razon_rechazo. Requiere autorización (toca núcleo).

## D4. Documentación del Shadow group incompleta en código

- **Ubicación**: `motor_calculadora.py:17-19` (changelog V4.8).
- **Descripción**: el changelog dice qué hace Shadow pero la función que lo calcula
  (cerca de `calcular_shadow_altitud` en línea 459 + lógica dispersa en `main()`)
  no tiene docstring que explique:
  - Qué fixes EXACTAMENTE se omiten (Fix #5, Hallazgo G, Hallazgo C).
  - Cómo leer la divergencia Op1/Shadow en el log.
- **Riesgo**: bajo — documentado en Reglas_IA.txt §IV.K, pero un dev nuevo leyendo
  el código sin abrir el manifiesto se confunde.
- **Acción futura**: agregar docstrings sin tocar lógica. Cualquier junior puede hacerlo
  en su archivo (no requiere autorización si es solo docstring).

## D5. `DB_NAME = 'fondo_quant.db'` hardcodeado en múltiples archivos (inventario completo)

> **Decisión Lead (2026-04-16)**: en este refactor se RESPETA el hardcode tal cual.
> Documentado aquí como **alta prioridad** para fase de escalabilidad.

### Inventario verificado (grep `'fondo_quant.db'` en todo el repo)

#### A. Scripts del pipeline operativo (in-scope del refactor, hardcode preservado)
- `motor_sincronizador.py:14` — `DB_NAME = 'fondo_quant.db'`
- `motor_liquidador.py:8` — `DB_NAME = 'fondo_quant.db'`
- `motor_purga.py:9` — `DB_NAME = 'fondo_quant.db'`
- `importador_gold.py:11` — `DB_NAME = 'fondo_quant.db'`
- `desbloquear_matriz.py:9` — `DB_NAME = 'fondo_quant.db'`
- `reset_tablas_derivadas.py:9` — `DB_NAME = 'fondo_quant.db'`

#### B. Scripts auxiliares fuera de `src/` (out-of-scope, no se tocan)
- `auditor/auditor_ema.py:10` — `DB_NAME = 'fondo_quant.db'`
- `auditor/auditor_interno.py:14` — `DB_NAME = 'fondo_quant.db'`
- `analisis/analisis_filtros.py:3` — inline `sqlite3.connect('fondo_quant.db')`
- `analisis/analisis_patrones.py:3,257` — inline `sqlite3.connect('fondo_quant.db')` (dos sitios)
- `analisis/analisis_desacuerdo.py:3` — inline `sqlite3.connect('fondo_quant.db')`
- `analisis/analisis_patrones_v2.py:4` — inline `sqlite3.connect('fondo_quant.db')`
- `analisis/contraste.py:12` — `DB_NAME = 'fondo_quant.db'`
- `archivo/motor_live.py:19` — `DB_NAME = 'fondo_quant.db'` (deprecado, en `archivo/`)
- `archivo/purgar_rastreo.py:9` — `DB_NAME = 'fondo_quant.db'`
- `archivo/visualizador_momentum.py:10` — `DB_NAME = 'fondo_quant.db'`

#### C. Documentación de subagentes (no es código ejecutado por pipeline)
- `.claude/agents/fixture_supervisor.md:41` — snippet ilustrativo
- `.claude/agents/optimizador_modelo.md:63` — snippet ilustrativo

### Total: **17 sitios** con la cadena literal `'fondo_quant.db'` (excluyendo el canónico en `src/comun/config_sistema.py:12` y los archivos de docs).

- **Riesgo**: bajo en el corto plazo (los valores son idénticos al canónico
  en `config_sistema.DB_NAME`). **Alto en escalabilidad**: si migramos a otro nombre
  de DB (multi-fondo, ambientes dev/staging/prod, etc.), hay 17 puntos de actualización
  en vez de 1, repartidos en 4 carpetas distintas.
- **Acción futura propuesta por T1**: crear `src/nucleo/constantes.py` que centralice
  las constantes matemáticas (FLOOR_PROB_MIN, RHO_FALLBACK, MAX_KELLY_PCT_*, todos los
  dicts por liga, etc.) — movimiento bit-a-bit, sin alterar valores. El Lead debe aprobar
  EXPLÍCITAMENTE este movimiento porque toca el archivo del manifiesto.
- **Acción en este refactor**: NINGUNA. Se respeta el hardcode tal cual.
- **Acción en fase escalabilidad** (post-refactor, requiere autorización Lead):
  reemplazar todos los hardcodes del grupo A por `from src.comun.config_sistema import DB_NAME`.
  Los grupos B/C se atienden cuando se reorganice `auditor/`, `analisis/`, `archivo/`.

## D6. Tabla `arbitros_historial` con schema vacío

- **Verificación T3**: `PRAGMA table_info(arbitros_historial)` retorna 0 columnas.
- **Descripción**: la tabla existe pero no tiene columnas declaradas.
  `motor_arbitro.py` debe crearla en runtime via `CREATE TABLE IF NOT EXISTS`.
- **Riesgo**: medio — si `motor_calculadora` consulta esta tabla antes de que
  `motor_arbitro` corra al menos una vez post-`--rebuild`, falla silenciosamente.
- **Acción futura**: incluir el `CREATE TABLE` explícito en `importador_gold.py` para que
  `--rebuild` deje el schema completo desde el arranque.
- **Acción en este refactor**: NINGUNA. Documentado para T6.

## D7. Pedidos de T1 que requieren ALTER TABLE (nuevas columnas)

> **NO se ejecutan en este refactor**. Se proponen como schema y se muestran
> al Lead para autorizar en una iteración separada (toca DB de producción).

Columnas nuevas propuestas para `partidos_backtest`:
- `prob_implicita_1`, `prob_implicita_x`, `prob_implicita_2` (REAL) — derivadas `1/cuota`.
- `xg_post_fatiga_l`, `xg_post_fatiga_v` (REAL) — intermedios pipeline calculadora.
- `xg_post_altitud_l`, `xg_post_altitud_v` (REAL) — intermedios.
- `xg_post_momentum_l`, `xg_post_momentum_v` (REAL) — intermedios.
- `kelly_base_1x2`, `kelly_base_ou` (REAL) — antes de covarianza/delta.
- `factor_covarianza_1x2`, `factor_covarianza_ou` (REAL).
- `factor_delta_1x2`, `factor_delta_ou` (REAL).
- `razon_rechazo_1x2`, `razon_rechazo_ou` (TEXT) — `EV_BAJO|FLOOR|DIV_ALTA|CAMINO_2B_FUERA_RANGO|TECHO_CUOTA|EMPATE_BLOQUEADO|NULL`.
- `modo_operativo` (TEXT) — `NORMAL|DEFENSIVO`.
- `es_shadow` (INTEGER 0/1) — flag.

Tabla nueva propuesta (alternativa a columnas):
- `decisiones_log` — un row por evaluación de filtro, FK a partidos_backtest. Más limpio
  que ensanchar `partidos_backtest` a 70+ columnas.

**Recomendación T3**: votar por la **tabla `decisiones_log`** y **columnas mínimas en
partidos_backtest** (solo intermedios xg_*, factor_*, prob_implicita_*, modo_operativo).
La razón_rechazo va a `decisiones_log` por flexibilidad.

Decisión final: del Lead, cuando autorice la fase de schema migration.

---

## D8. Inventario de callers externos a `config_sistema` y `gestor_nombres`

> Soporta el shim de retrocompatibilidad introducido en este refactor (raíz `config_sistema.py`
> y `gestor_nombres.py` apuntando a `src/comun/`). Una vez auditado y migrado, el shim se retira.

### `gestor_nombres` — callers verificados (grep `^import gestor_nombres|^from gestor_nombres`)

#### Dentro del scope del refactor (se reescriben a `from src.comun.gestor_nombres import ...`)
- `motor_arbitro.py:4` (→ `src/ingesta/motor_arbitro.py`)
- `motor_backtest.py:3` (→ `src/persistencia/motor_backtest.py`)
- `motor_cuotas.py:6` (→ `src/ingesta/motor_cuotas.py`)
- `motor_data.py:3` (→ `src/ingesta/motor_data.py`)
- `motor_fixture.py:4` (→ `src/ingesta/motor_fixture.py`)
- `motor_tactico.py:5` (→ `src/ingesta/motor_tactico.py`)

#### Fuera de scope (dependen del shim de raíz)
- `auditor/auditor_espn.py:2` — `import gestor_nombres`
  - **Único caller externo**. Requiere el shim para seguir funcionando post-refactor.

### `config_sistema` — callers verificados (grep `^from config_sistema|^import config_sistema`)

#### Dentro del scope del refactor (se reescriben a `from src.comun.config_sistema import ...`)
- `motor_calculadora.py:8` (→ `src/nucleo/motor_calculadora.py`)
- `motor_arbitro.py:6` (→ `src/ingesta/motor_arbitro.py`)
- `motor_backtest.py:5` (→ `src/persistencia/motor_backtest.py`)
- `motor_cuotas.py:7` (→ `src/ingesta/motor_cuotas.py`)
- `motor_data.py:8` (→ `src/ingesta/motor_data.py`)
- `motor_fixture.py:5` (→ `src/ingesta/motor_fixture.py`)
- `motor_tactico.py:5` (→ `src/ingesta/motor_tactico.py`)

#### Quedan en raíz (NO se mueven, importan canónico vía shim o ya directo)
- `adepor_guard.py:28` — `from config_sistema import DB_NAME` (queda en raíz por PLAN §2; usa shim).
- `calibrar_rho.py:28` — `from config_sistema import DB_NAME, LIGAS_ESPN, ...` (a mover a `src/nucleo/` por PLAN §2; cuando se mueva, reescribe import).

#### Fuera de scope (auditor/analisis/archivo)
- **Ninguno hace `import config_sistema`** (verificado por grep). Solo declaran su propio `DB_NAME` literal — ver §D5.

### Plan de retiro del shim (fase 2, post-refactor)

1. Auditar `auditor/auditor_espn.py` y reescribir su import a `from src.comun.gestor_nombres import ...`
   (1 caller externo, low effort).
2. Verificar que ningún script suelto en `analisis/`, `archivo/`, `auditor/` agrega un nuevo
   `import config_sistema` o `import gestor_nombres` durante la transición.
3. Borrar `config_sistema.py` y `gestor_nombres.py` de la raíz.
4. Borrar `motor_*.py` shims de raíz (ver punto B en `PLAN_MODULAR.md`) cuando los `.bat`
   y `ejecutar_proyecto.py` apunten a invocación con `python -m src.<modulo>.motor_X`.

**Estado actual del shim**: ACTIVO. Comentario marcador: `# SHIM DE RETROCOMPATIBILIDAD`.

---

## D9. Audit de paths obligado por reubicación a `src/` (Tipo 1/2/3)

> Auditoría completa antes de despertar juniors (orden Lead 2026-04-16).
> Clasificación: **Tipo 1** = absoluto hardcodeado; **Tipo 2** = derivado de `__file__`;
> **Tipo 3** = relativo a cwd. Solo Tipo 2 requiere intervención durante el refactor.

### Tipo 1 — paths absolutos hardcodeados

**Hallazgos: NINGUNO** en archivos del scope (motores, calibrar_rho, importador_gold,
desbloquear_matriz, ejecutar_proyecto, adepor_guard, gestor_nombres, config_sistema).

### Tipo 2 — paths derivados de `__file__`

**Hallazgos: 1 sitio**, introducido por este refactor (NO regresión):
- `src/comun/config_sistema.py:77` — `PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))`.
  - **Justificación**: el archivo se movió de raíz a `src/comun/`. Sin la doble-dirname extra,
    `_CONFIG_FILE` apuntaría a `src/comun/config.json` en vez de `<root>/config.json`.
  - **Comentario marcador**: `# AJUSTE OBLIGADO POR REUBICACION (refactor 2026-04-17)`.
  - **Smoke test**: pre y post refactor → `_CONFIG_FILE = C:\Users\map12\Desktop\Proyecto_Adepor\config.json`,
    `len(API_KEYS_ODDS)=6`, `bool(API_KEY_FOOTBALL)=True`. Identidad bit-a-bit verificada.
  - **Aprobación Lead**: Opción 2 aprobada con 3 condiciones (comentario, smoke test, doc) — todas cumplidas.

**Verificación grep `__file__` en motores**: 0 matches en motor_*.py, calibrar_rho.py,
desbloquear_matriz.py, importador_gold.py, ejecutar_proyecto.py, adepor_guard.py,
gestor_nombres.py. Solo aparece en `src/comun/config_sistema.py`.

### Tipo 3 — paths relativos a cwd (cwd-dependent)

**Hallazgos: documentados, NO se tocan en este refactor**. Funcionan correctamente cuando
se invoca desde la raíz del proyecto (`python -m src.X.motor_Y` o `python ejecutar_proyecto.py`).
**Rompen si cwd != raíz**.

#### a) `sqlite3.connect(DB_NAME)` — 14 sitios
Todos pasan la variable `DB_NAME` (string literal `'fondo_quant.db'`). Ya inventariado en §D5.
- 6 sitios in-scope (grupo A de §D5).
- 8 sitios out-of-scope (grupo B de §D5).

#### b) Paths literales en código
- `motor_sincronizador.py:15` — `EXCEL_NAME = 'Backtest_Modelo.xlsx'` (cwd-relative).
- `importador_gold.py:12` — `CSV_GOLD = 'modelo_estable.csv'` (cwd-relative).
- `motor_cuotas.py:17` — `'diccionario_equipos.json'` (cwd-relative, usado al cargar).
- `gestor_nombres.py:11` — `'diccionario_equipos.json'` (cwd-relative, usado al cargar).

**Riesgo en este refactor**: NINGUNO. Tras el refactor:
- `python ejecutar_proyecto.py` corre desde raíz → cwd = raíz → todos los paths Tipo 3 resuelven OK.
- `python -m src.X.motor_Y` corre desde raíz → cwd = raíz → idem.
- Shims en raíz (`config_sistema.py`, `gestor_nombres.py`, `motor_*.py`) son re-exports y
  delegan en código que ya funciona desde la raíz.

**Riesgo en escalabilidad** (futuro, fuera de scope):
- Si ejecutamos desde otro cwd (cron, contenedor con WORKDIR distinto, IDE con working dir custom),
  todos los Tipo 3 fallan con FileNotFoundError o crean DB vacía en otro lugar.
- **Acción futura propuesta**: refactorizar los Tipo 3 a `os.path.join(PROJECT_ROOT, '...')`
  consumiendo `PROJECT_ROOT` de `src.comun.config_sistema`. Requiere autorización del Lead
  porque toca múltiples motores fuera del scope actual.

### Conclusión del audit

- **Tipo 1**: 0 — nada que arreglar.
- **Tipo 2**: 1 — el fix de PROJECT_ROOT, ya aplicado y aprobado.
- **Tipo 3**: ~18 sitios cwd-relativos — **NO se tocan en este refactor**, documentados aquí
  para fase de escalabilidad. El pipeline post-refactor sigue invocándose desde la raíz, igual que hoy.

**Veredicto**: el refactor de carpetas NO introduce regresiones de path más allá del fix Tipo 2
ya autorizado. Los juniors pueden mover archivos sin temor a romper resolución de paths.
