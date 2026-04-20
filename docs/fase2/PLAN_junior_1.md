# PLAN — Junior #1 (Fase 2 Adepor)

> Estado: **PRE-LECTURA / IDLE**. NO se va a tocar nada hasta que `tech-lead` me asigne un bloque concreto y me confirme que está aprobado por el Lead.

---

## 1. Confirmaciones de lectura

- [x] Leí `C:\Users\map12\.claude\teams\adepor-fase2\PLAN.md` completo, con foco en:
  - §1A (lista negra: Reglas_IA.txt, fórmulas, constantes Sección II, funciones públicas, tablas dict, strings de estado).
  - §1B (workflow obligatorio: cualquier mejora matemática va a `PROPUESTAS_MATEMATICAS.md` y espera OK del usuario).
  - §1D (strings exactos del Excel: `'GANADA'`, `'PERDIDA'`, `'ANULADA'`, headers consumidos por HTML viewer, lógica de cálculo en `motor_sincronizador.py`).
  - §1E (`adepor_eval_review.html` fuera de scope).
- [x] Leí `C:\Users\map12\Desktop\Proyecto_Adepor\Reglas_IA.txt` completo (Manifiesto Cuantitativo: I arquitectura, II biblia matemática A–K, III máximas, IV estrategia V4.3/4.4 con sus cuatro caminos, EV escalado, fix B, hallazgos C/G, shadow).

## 2. Familiarización con `src/`

Estructura recorrida (lectura, sin modificar):

- `src/comun/`
  - `config_sistema.py` → fuente única para `DB_NAME`, `LIGAS_ESPN`, `MAPA_LIGAS_ODDS`, `MAPA_LIGAS_API_FOOTBALL`, estados `'Pendiente'/'Calculado'/'Finalizado'/'Liquidado'`, carga de claves API desde `config.json`.
  - `gestor_nombres.py` → diccionario de equipos, `SUFIJOS_RUIDO`.
- `src/ingesta/` → `motor_data`, `motor_fixture`, `motor_arbitro`, `motor_tactico`, `motor_cuotas`.
- `src/nucleo/` → `motor_calculadora` (Dixon-Coles, EV escalado, cuatro caminos, Hallazgo C/G, Fix #5), `calibrar_rho`, `desbloquear_matriz`.
- `src/persistencia/` → `motor_sincronizador` (Excel openpyxl), `motor_liquidador`, `motor_backtest`, `motor_purga`, `importador_gold`, `reset_tablas_derivadas`, `queries_dashboard`.

Observaciones de coherencia ya aplicadas en fase 1:
- `LIGAS_ESPN` y `DB_NAME` ya importados desde `config_sistema` por `motor_data`, `motor_arbitro`, `motor_calculadora`, `motor_backtest`. La centralización está hecha para esos cuatro.
- Sigue habiendo módulos que **NO** importan de `config_sistema` y redeclaran `DB_NAME`. Ver §3.

## 3. Hallazgos preliminares (insumo para `tech-lead`, sin actuar)

### 3.1 — `DB_NAME` redeclarado fuera de `config_sistema` (redundancia lógica)

Constante ya canónica en `src/comun/config_sistema.py:12`. Aún se redefine localmente en:

| Archivo | Línea | Constante hardcodeada |
|---|---|---|
| `src/persistencia/motor_sincronizador.py` | 14 | `DB_NAME = 'fondo_quant.db'` |
| `src/persistencia/motor_purga.py` | 9 | `DB_NAME = 'fondo_quant.db'` |
| `src/persistencia/motor_liquidador.py` | 8 | `DB_NAME = 'fondo_quant.db'` |
| `src/persistencia/reset_tablas_derivadas.py` | 9 | `DB_NAME = 'fondo_quant.db'` |
| `src/persistencia/importador_gold.py` | 11 | `DB_NAME = 'fondo_quant.db'` |

Propuesta (sujeta a aprobación): reemplazar por `from src.comun.config_sistema import DB_NAME`. Cambio puramente mecánico, no toca lógica ni strings de estado, no toca firmas públicas. Riesgo: bajo (mismo valor, mismo nombre).

### 3.2 — `EXCEL_FILE` y `CSV_GOLD_STANDARD` hardcodeados

- `src/persistencia/motor_sincronizador.py:15` → `EXCEL_FILE = 'Backtest_Modelo.xlsx'`
- `src/persistencia/importador_gold.py:12` → `CSV_GOLD_STANDARD = 'modelo_estable.csv'`

Propuesta: candidatos a `config_sistema` (paths de artefactos del proyecto). Esperar criterio del `analista-datos` sobre si prefiere consolidar en `config_sistema.py` o en una tabla `config_motor_valores` de la DB (alineado con §5.4 del PLAN.md).

### 3.3 — `INACTIVITY_MONTHS` en `motor_purga`

`src/persistencia/motor_purga.py:10` → `INACTIVITY_MONTHS = 6`. Es un parámetro operativo (no Biblia matemática). Buen candidato para migrar a `config_motor_valores` cuando `analista-datos` defina el schema de esa tabla.

### 3.4 — `LAMBDA_EMA` arbitral en `motor_arbitro`

`src/ingesta/motor_arbitro.py:14` → `LAMBDA_EMA = 0.15`. **No tocar sin consultar**: aunque el Manifiesto define ALFA por liga para xG (II.B), aquí se aplica al EMA arbitral, que es un parámetro paralelo. Es un valor empírico no listado explícitamente en la Sección II del Manifiesto, pero comparte la filosofía de la regresión bayesiana. Elevar duda al `tech-lead` antes de cualquier cambio.

### 3.5 — `BASE_URL` y `HEADERS` API-Football en `motor_tactico`

`src/ingesta/motor_tactico.py:13-14` → URL fija de `v3.football.api-sports.io`. Pertinente si se quisiera hacer mockable para tests, pero no es prioridad de fase 2 según el PLAN.

### 3.6 — Diccionarios canónicos de Excel en `motor_sincronizador`

Las tablas `COL`, `HEADERS`, `COL_WIDTHS`, `PAISES_CF` (`motor_sincronizador.py:18-79`) son hardcodes de presentación. **Boundary del `disenador-excel` por §1D del PLAN**, NO me corresponde tocar.

### 3.7 — Hardcodes que **NO** se deben tocar (lista negra confirmada)

Estos los identifiqué para asegurarme de **NO** proponerlos como migración:

- Toda la sección de constantes de `motor_calculadora.py:60-231` (`MAX_KELLY_PCT_*`, `FRACCION_KELLY`, `UMBRAL_EV_BASE`, `TECHO_CUOTA_*`, `FACTOR_CORR_XG_OU_POR_LIGA`, `DIVERGENCIA_MAX_POR_LIGA`, `MARGEN_*`, `FLOOR_PROB_MIN`, `CONVICCION_EV_MIN`, `DESACUERDO_*`, `CALIBRACION_*`, `DELTA_STAKE_*`, `N_MIN_HALLAZGO_G`, `BOOST_G_FRACCION`, `RHO_FALLBACK`, `RANGO_POISSON`, `ALTITUD_NIVELES`, `CORR_VISITA_*`).
- `ALFA_EMA`, `ALFA_EMA_POR_LIGA`, `N0_ANCLA` en `motor_data.py:16-51`.
- Estados `'Pendiente'/'Calculado'/'Finalizado'/'Liquidado'` y resultados `'GANADA'/'PERDIDA'/'ANULADA'`.
- Picks `'OPERAR LOCAL/VISITA/PASAR'`, `'OVER/UNDER/PASAR'`.
- Strings de país canónicos sin tildes (`"Turquia"`, no `"Turquía"`, etc.).

## 4. Riesgos identificados

1. **Riesgo de scope creep**: hay tentación de "limpiar" constantes que parecen redundantes pero están en la Biblia. Mitigación: para cualquier constante usada en `motor_calculadora.py` o `motor_data.py`, pedir confirmación explícita aunque parezca trivial.
2. **Riesgo de romper imports cruzados**: cambiar `DB_NAME` en módulos de `persistencia/` requiere verificar que el import path `from src.comun.config_sistema import DB_NAME` resuelve correctamente bajo el nuevo layout (`src.<modulo>`). En motor_data ya funciona, debería ser análogo, pero conviene un smoke test post-cambio (`python -m src.persistencia.motor_purga` etc.).
3. **Riesgo de migración prematura a DB**: migrar constantes operativas (`INACTIVITY_MONTHS`, `EXCEL_FILE`, `CSV_GOLD_STANDARD`) a `fondo_quant.db` requiere coordinación con `analista-datos` (schema de `config_motor_valores`) y con `tech-lead` (orden de inicialización: el módulo necesita la DB antes de leer el config). No avanzar hasta que la tabla canónica esté definida.

## 5. Confirmación de NO-acción

Confirmo que **no voy a modificar ningún archivo** hasta que `tech-lead` me asigne un bloque específico y me confirme que está aprobado por el Lead, conforme al §1B/§3 del `PLAN.md` y a las restricciones de mi rol.

Próximo paso: DM a `tech-lead` con resumen y path de este documento. Después → IDLE.
