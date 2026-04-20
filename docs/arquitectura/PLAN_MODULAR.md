# PLAN MODULAR — Refactor Adepor (T3 tech-lead)

> **Restricción raíz**: este refactor mueve archivos y arregla imports.
> NO renombra funciones públicas, NO altera constantes, NO reordena lógica.
> Cualquier cambio fuera de este alcance requiere autorización del Lead.

---

## 1. Estructura de carpetas objetivo

```
Proyecto_Adepor/
├── ejecutar_proyecto.py        ← raíz (orquestador, cambia paths subprocess)
├── adepor_guard.py             ← raíz (snapshots de DB)
├── config_sistema.py           ← raíz (re-export desde src/comun para retrocompat)*
├── gestor_nombres.py           ← raíz (re-export desde src/comun para retrocompat)*
├── adepor_eval_review.html     ← raíz (FUERA DE SCOPE — visor de evals de skill, no se toca)
├── config.json, credentials.json, token.json
├── diccionario_equipos.json
├── fondo_quant.db
├── Backtest_Modelo.xlsx
│
├── src/
│   ├── __init__.py
│   ├── comun/
│   │   ├── __init__.py
│   │   ├── config_sistema.py       ← copia canónica
│   │   └── gestor_nombres.py       ← copia canónica
│   ├── ingesta/
│   │   ├── __init__.py
│   │   ├── motor_data.py
│   │   ├── motor_fixture.py
│   │   ├── motor_arbitro.py
│   │   ├── motor_tactico.py
│   │   └── motor_cuotas.py
│   ├── nucleo/
│   │   ├── __init__.py
│   │   ├── motor_calculadora.py    ← INTOCABLE (matemática pura)
│   │   ├── calibrar_rho.py
│   │   └── desbloquear_matriz.py
│   └── persistencia/
│       ├── __init__.py
│       ├── motor_sincronizador.py
│       ├── motor_liquidador.py
│       ├── motor_backtest.py
│       ├── motor_purga.py
│       ├── importador_gold.py
│       └── reset_tablas_derivadas.py
│
├── docs/
│   └── arquitectura/
│       ├── DEPENDENCIAS.md
│       ├── PLAN_MODULAR.md     ← este archivo
│       └── ASIGNACIONES_JUNIOR.md
│
├── snapshots/, analisis/, archivo/, auditor/   ← sin cambios
└── __pycache__/                                ← se regenera
```

> *NOTA sobre `config_sistema.py` y `gestor_nombres.py` en raíz:
> Quedan como **shims de retrocompatibilidad** hasta que se confirme que ningún
> script externo (auditor/, archivo/, analisis/) los importa. Contenido del shim:
>
> ```python
> # SHIM DE RETROCOMPATIBILIDAD — retirar tras auditar callers en auditor/, analisis/, archivo/. TODO: fase 2.
> # Fuente canónica: src/comun/config_sistema.py
> # Inventario de callers externos en docs/arquitectura/DEUDA_TECNICA.md §D8.
> from src.comun.config_sistema import *  # noqa: F401,F403
> ```
>
> Si se confirma que nada externo los necesita, el Lead puede borrarlos en una
> iteración posterior. Por ahora se mantienen para no romper `auditor_espn.py`,
> `analisis/*.py`, etc.

### Shims ejecutables `motor_*.py` en raíz (mandato Lead 2026-04-16, punto B)

Cada `motor_*.py` que se mueve a `src/<modulo>/` deja en raíz un **shim ejecutable**
para preservar:
- Compatibilidad con los `.bat` que invocan `python motor_X.py`.
- Compatibilidad con `subprocess.run([sys.executable, 'motor_X.py'])` legado.
- Cualquier import suelto de `from motor_X import ...` en scripts auxiliares.

**Plantilla del shim ejecutable** (raíz `motor_X.py`, reemplaza el archivo original):

```python
# SHIM DE RETROCOMPATIBILIDAD — el código real vive en src/<modulo>/motor_X.py.
# Retirar tras migrar todos los .bat y ejecutar_proyecto.py a `python -m src.<modulo>.motor_X`.
# Inventario de callers en docs/arquitectura/DEUDA_TECNICA.md §D8.
from src.<modulo>.motor_X import *  # noqa: F401,F403

if __name__ == "__main__":
    from src.<modulo>.motor_X import main
    main()
```

**Pre-requisito**: el archivo canónico en `src/<modulo>/` debe exponer una función
`main()` (todos los motores ya tienen su lógica wrapeada en `if __name__ == "__main__":`,
por lo que cada junior debe **encapsular ese bloque dentro de una función `main()`**
y dejar el guard apuntando a `main()`. Es el ÚNICO cambio estructural permitido.

**Ejemplo de transformación bit-a-bit del guard**:

Antes (en raíz, archivo original):
```python
if __name__ == "__main__":
    # ... 80 líneas de orquestación ...
    cursor.execute(...)
    conn.commit()
```

Después (en `src/<modulo>/motor_X.py`):
```python
def main():
    # ... 80 líneas de orquestación, idénticas, indentadas un nivel ...
    cursor.execute(...)
    conn.commit()

if __name__ == "__main__":
    main()
```

**Restricción crítica**: la indentación adicional NO altera comportamiento siempre que
las variables que antes eran globales pasen a ser locales de `main()`. Si alguna función
del archivo lee un global definido en el bloque `if __name__`, ese global desaparece y
hay que pasar el valor por argumento. T3 audita esto en cada motor antes de aprobar el merge
del junior.

**Inventario de motores que requieren el shim ejecutable** (12):
- `motor_data.py`, `motor_fixture.py`, `motor_arbitro.py`, `motor_tactico.py`, `motor_cuotas.py` (junior-ingesta)
- `motor_calculadora.py`, `calibrar_rho.py`, `desbloquear_matriz.py` (junior-prediccion)
- `motor_sincronizador.py`, `motor_liquidador.py`, `motor_backtest.py`, `motor_purga.py`, `importador_gold.py`, `reset_tablas_derivadas.py` (junior-persistencia)

Total con shim ejecutable en raíz: **14 motores** (los 14 archivos de la tabla §2 que
hoy son scripts `python X.py`).

---

## 2. Path mapping exacto (16 archivos)

| Origen (raíz)              | Destino                             | Owner            |
|---|---|---|
| `motor_data.py`            | `src/ingesta/motor_data.py`         | junior-ingesta   |
| `motor_fixture.py`         | `src/ingesta/motor_fixture.py`      | junior-ingesta   |
| `motor_arbitro.py`         | `src/ingesta/motor_arbitro.py`      | junior-ingesta   |
| `motor_tactico.py`         | `src/ingesta/motor_tactico.py`      | junior-ingesta   |
| `motor_cuotas.py`          | `src/ingesta/motor_cuotas.py`       | junior-ingesta   |
| `motor_calculadora.py`     | `src/nucleo/motor_calculadora.py`   | junior-prediccion|
| `calibrar_rho.py`          | `src/nucleo/calibrar_rho.py`        | junior-prediccion|
| `desbloquear_matriz.py`    | `src/nucleo/desbloquear_matriz.py`  | junior-prediccion|
| `motor_sincronizador.py`   | `src/persistencia/motor_sincronizador.py` | junior-persistencia |
| `motor_liquidador.py`      | `src/persistencia/motor_liquidador.py`    | junior-persistencia |
| `motor_backtest.py`        | `src/persistencia/motor_backtest.py`      | junior-persistencia |
| `motor_purga.py`           | `src/persistencia/motor_purga.py`         | junior-persistencia |
| `importador_gold.py`       | `src/persistencia/importador_gold.py`     | junior-persistencia |
| `reset_tablas_derivadas.py`| `src/persistencia/reset_tablas_derivadas.py` | junior-persistencia |
| `config_sistema.py`        | `src/comun/config_sistema.py` (+ shim raíz) | tech-lead     |
| `gestor_nombres.py`        | `src/comun/gestor_nombres.py` (+ shim raíz) | tech-lead     |

**Quedan en raíz**: `ejecutar_proyecto.py`, `adepor_guard.py`,
`adepor_eval_review.html` (intacto, FUERA DE SCOPE — visor de evals de skill,
NO es el dashboard operativo de Adepor), archivos de datos (.db, .json, .xlsx),
shims de retrocompat.

---

## 3. Contrato de imports (qué expone cada módulo)

### 3.1 `src/comun/` (compartido por todos)

**Importable por:** todos los módulos.
**Expone:**
- `from src.comun.config_sistema import DB_NAME, LIGAS_ESPN, MAPA_LIGAS_ODDS, MAPA_LIGAS_API_FOOTBALL, API_KEYS_ODDS, API_KEY_FOOTBALL, ESTADO_PENDIENTE, ESTADO_CALCULADO, ESTADO_FINALIZADO, ESTADO_LIQUIDADO`
- `from src.comun.gestor_nombres import obtener_nombre_estandar, son_equivalentes, limpiar_texto, cargar_diccionario, guardar_diccionario, generar_candidatos_raiz, SUFIJOS_RUIDO, DICCIONARIO_FILE`

> NOTA: `DICCIONARIO_FILE = 'diccionario_equipos.json'` apunta a la raíz del repo.
> Como los procesos se lanzan vía `subprocess` desde la raíz, el `cwd` es la raíz
> y la ruta relativa funciona. **NO cambiar a path absoluto en este refactor.**

### 3.2 `src/ingesta/`

**Importable por:** nadie (los motores se ejecutan vía subprocess; no son librería).
**Importa:** `src.comun.config_sistema`, `src.comun.gestor_nombres`.
**Restricción de tablas (lectura/escritura):**
- `motor_data` → `historial_equipos`, `ema_procesados`, `ligas_stats`, `equipos_stats`
- `motor_fixture` → `partidos_backtest` (insert PENDIENTE), `diccionario_equipos.json`
- `motor_arbitro` → `arbitros_historial`
- `motor_tactico` → `partidos_backtest` (formacion_l/v), `equipos_stats` (dt_*)
- `motor_cuotas` → `partidos_backtest` (cuotas)

**Boundary**: ningún archivo de `src/ingesta/` puede importar de `src/nucleo/`
o `src/persistencia/`. Si necesita una constante matemática del núcleo, copia
hardcodeada NO permitida — pedir a tech-lead que mueva la constante a `comun/`.

### 3.3 `src/nucleo/` (matemática pura — INTOCABLE)

**Importable por:** nadie (mismo modelo subprocess).
**Importa:** `src.comun.config_sistema` (solo `DB_NAME`, `LIGAS_ESPN`, `MAPA_LIGAS_API_FOOTBALL`, `API_KEY_FOOTBALL`).
**Funciones bloqueadas (firmas exactas, ver DEPENDENCIAS.md §5):**
- `min_ev_escalado`, `multiplicador_delta_stake`, `aplicar_hallazgo_g`,
  `corregir_calibracion`, `corregir_ventaja_local`, `evaluar_mercado_1x2`,
  `evaluar_mercado_ou`, `calcular_stake_independiente`,
  `ajustar_stakes_por_covarianza`, `tau`, `poisson`, `detectar_drawdown`.
**Constantes bloqueadas:** ver DEPENDENCIAS.md §6.

**REGLA DE ORO PARA T5 (junior-prediccion)**:
- Cambia SOLO la línea `from config_sistema import DB_NAME` → `from src.comun.config_sistema import DB_NAME`.
- Todo lo demás se copia bit-a-bit.

### 3.4 `src/persistencia/`

**Importable por:** nadie.
**Importa:** `src.comun.config_sistema`, `src.comun.gestor_nombres` (solo backtest).
**Tablas/archivos:**
- `motor_sincronizador` → lee `partidos_backtest`, escribe `Backtest_Modelo.xlsx`
- `motor_liquidador` → `partidos_backtest` (transición FINALIZADO→LIQUIDADO)
- `motor_backtest` → `partidos_backtest` (resultados reales)
- `motor_purga` → `ema_procesados`, `equipos_stats`
- `importador_gold` → seed inicial de tablas
- `reset_tablas_derivadas` → trunca tablas derivadas

**Restricción especial**: `motor_sincronizador` tiene `DB_NAME` hardcodeado
(línea 14). Se respeta esa decisión (puede ser intencional para snapshot
test del Excel). El junior puede agregar `from src.comun.config_sistema import DB_NAME`
**solo si elimina** la línea hardcoded — si elige hacerlo, debe verificar
que el valor es idéntico.

---

## 4. Cambios en `ejecutar_proyecto.py` (raíz)

T3 (tech-lead) ejecuta este cambio en la fase de ensamblaje, NO los juniors.

### Opción canónica (recomendada): invocación con `-m`

```python
MOTORES_DIARIOS = [
    {"modulo": "src.persistencia.motor_purga",         ...},
    {"modulo": "src.persistencia.motor_backtest",      ...},
    {"modulo": "src.persistencia.motor_liquidador",    ...},
    {"modulo": "src.ingesta.motor_arbitro",            ...},
    {"modulo": "src.ingesta.motor_data",               ...},
    {"modulo": "src.ingesta.motor_fixture",            ...},
    {"modulo": "src.ingesta.motor_tactico",            ...},
    {"modulo": "src.ingesta.motor_cuotas",             ...},
    {"modulo": "src.nucleo.motor_calculadora",         ...},
    {"modulo": "src.persistencia.motor_backtest",      ...},
    {"modulo": "src.persistencia.motor_liquidador",    ...},
    {"modulo": "src.persistencia.motor_sincronizador", ...},
]
# subprocess.run([sys.executable, '-m', motor['modulo'], ...args])
```

Y los modos `--rebuild`, `--unlock`, `--purge-history` análogos.

**Por qué `-m`**: cuando se ejecuta `subprocess.run([sys.executable, 'src/ingesta/motor_data.py'])`,
Python establece `sys.path[0]` como `src/ingesta/`, lo cual NO permite resolver
`from src.comun...`. Con `-m`, el cwd queda en la raíz y los imports `src.comun.X` resuelven.

### Opción de compatibilidad: invocación legada `python motor_X.py`

Gracias a los **shims ejecutables en raíz** (ver §1, sección "Shims ejecutables"), el comando
`python motor_X.py` SIGUE FUNCIONANDO post-refactor. El shim hace `from src.<modulo>.motor_X import *`
+ `if __name__=="__main__": main()`, lo que delega al canónico sin cambiar el comportamiento.

Esto preserva:
- Los `.bat` que invoquen `python motor_data.py` etc.
- Cualquier llamada manual del usuario.
- `subprocess.run([sys.executable, 'motor_X.py'])` legado (si quedara alguno).

**Decisión Lead**: `ejecutar_proyecto.py` se migra a la opción `-m` (más limpia, evita
ambigüedad de path). Los shims ejecutables existen como red de seguridad para invocaciones
externas, NO como camino preferido.

---

## 5. Orden de ensamblaje (cuando los 3 juniors terminen)

1. T3 valida que `src/comun/config_sistema.py` y `src/comun/gestor_nombres.py`
   son idénticos al original (`diff`), excepto el ajuste de path autorizado
   por el Lead para `_CONFIG_FILE` (ver mensaje BLOQUEO config.json).
2. T3 valida que cada `motor_*.py` en raíz es el shim ejecutable (3 líneas comentario
   + `from src.<modulo>.motor_X import *` + bloque `if __name__`).
3. T3 ejecuta `python -m src.ingesta.motor_data --help` (smoke test import).
   Análogo para los 14 motores.
4. T3 ejecuta `python motor_data.py --help` (smoke test del shim ejecutable).
   Análogo para los 14 motores que tienen shim.
5. T3 actualiza `ejecutar_proyecto.py` (cambio de `archivo`→`modulo` + flag `-m`).
6. T3 corre `python ejecutar_proyecto.py --audit-names` (modo NO destructivo, sale al inicio).
7. T3 corre `python -c "import src.nucleo.motor_calculadora as m; print([x for x in dir(m) if not x.startswith('_')][:30])"` y verifica que las funciones bloqueadas siguen exportadas.
8. T3 envía reporte al `team-lead` con resultado de los 7 chequeos.

> NO se ejecuta el pipeline completo end-to-end aquí (eso requiere snapshot DB
> previo + auditoría matemática Lead). El criterio de "compila verde" es:
> `python -c "import <módulo>"` en los 14 archivos sin error + `python motor_X.py --help`
> sin error en los 14 shims.

---

## 6. Lo que NO se hace en este refactor

- Eliminar shims de raíz (esperar confirmación de que nada externo los usa).
- Tocar `adepor_eval_review.html` (FUERA DE SCOPE — visor de evals de skill, ortogonal al proyecto cuantitativo).
- Implementar el dashboard operativo NUEVO (proyecto futuro). T2 entrega solo
  mockups + spec `OPERATIVO_DATA` en `docs/ux/`. T3 valida que el data layer de
  T6 (`queries_dashboard.py`) puede producir esa shape sin tocar matemática.
- Crear tests automatizados (no estaba en el alcance).
- Mover archivos de `auditor/`, `analisis/`, `archivo/` (legacy, fuera de alcance).
- Convertir `motor_*.py` a librerías importables (siguen siendo scripts subprocess).
- Refactorizar lógica matemática (Lead lo audita bit-a-bit).
- Centralizar `DB_NAME` en archivos que lo hardcodean (deuda menor documentada).

---

## 7. Checklist de criterios de éxito (PLAN §7)

- [ ] Árbol en 3 carpetas + raíz limpia.
- [ ] `python ejecutar_proyecto.py --audit-names` corre sin error.
- [ ] `diff` pre/post de constantes y matrices: vacío.
- [ ] Reporte de T3 al Lead: paths actualizados + smoke imports OK.
- [ ] Lead audita y aprueba.
