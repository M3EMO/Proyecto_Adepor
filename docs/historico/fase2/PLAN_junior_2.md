# PLAN — Junior #2 (adepor-fase2)

**Rol:** Programador Junior #2. Jefe directo: `tech-lead`. Lead/juez: `team-lead`.
**Fecha:** 2026-04-16
**Estado:** PRE-LECTURA — sin asignación todavía. NO se toca código hasta OK del tech-lead.

---

## 1. Confirmación de lecturas obligatorias

- [x] `C:\Users\map12\.claude\teams\adepor-fase2\PLAN.md` — leído completo (§0 contexto fase 1, §1A-1E restricciones inmutables, §2 roster, §3 workflow, §4 protocolo, §5 criterios de éxito).
- [x] `C:\Users\map12\Desktop\Proyecto_Adepor\Reglas_IA.txt` — leído completo (§I arquitectura, §II A-K biblia matemática, §III máximas, §IV A-K estrategia V4.3/V4.9).

**Restricciones internalizadas (lista negra, NO TOCAR):**
- Constantes/fórmulas Reglas_IA.txt §II completo y §IV (FLOOR_PROB_MIN, EV escalado, Cuatro Caminos, DIVERGENCIA_MAX_POR_LIGA, Fix B, Hallazgo G, Hallazgo C, Shadow).
- Funciones públicas listadas en PLAN §1A.
- Strings exactos: `'GANADA'`, `'PERDIDA'`, `'ANULADA'`, `'Pendiente'`, `'Calculado'`, `'Finalizado'`, `'Liquidado'`, `'OPERAR LOCAL'`, `'OPERAR VISITA'`, `'PASAR'`, `'OVER'`, `'UNDER'`, `'[APOSTAR]'`, nombres de país canónicos sin tildes.
- Workflow matemático §1B: cualquier mejora a fórmula central → propuesta a `docs/fase2/PROPUESTAS_MATEMATICAS.md`, NO implementar sin OK del usuario.

---

## 2. Familiarización con `src/`

Recorrido superficial de los 4 paquetes:

- **`src/comun/`** — `config_sistema.py` (DB_NAME, LIGAS_ESPN, MAPA_LIGAS_ODDS, MAPA_LIGAS_API_FOOTBALL, ESTADOS, carga de API keys desde `config.json`), `gestor_nombres.py` (alias + fuzzy + diccionario JSON externo).
- **`src/ingesta/`** — `motor_data` (xG híbrido + EMA + Bayes), `motor_fixture`, `motor_cuotas`, `motor_arbitro` (auditoría arbitral con EMA propio), `motor_tactico` (formaciones API-Football).
- **`src/nucleo/`** — `motor_calculadora` (Dixon-Coles + Poisson + Cuatro Caminos), `calibrar_rho` (MLE rho por liga), `desbloquear_matriz`.
- **`src/persistencia/`** — `motor_sincronizador` (Excel + DB), `motor_liquidador` (estados de apuestas), `motor_backtest` (resultados ESPN), `motor_purga` (equipos obsoletos), `importador_gold` (CSV → DB), `reset_tablas_derivadas`, `queries_dashboard`.

`src/comun/config_sistema.py` ya es la **única fuente de verdad** para `DB_NAME`, ligas y estados. Varios módulos lo importan correctamente; otros aún definen `DB_NAME` localmente (ver §3).

---

## 3. Hardcodes detectados (insumo para tech-lead)

> **Coordinación con junior-1:** asumo que junior-1 atacará el grueso de tablas matemáticas en `motor_calculadora.py` (FACTOR_CORR_XG_OU_POR_LIGA, DIVERGENCIA_MAX_POR_LIGA, CORR_VISITA_POR_LIGA, ALTITUD_NIVELES, CALIBRACION_*, DELTA_STAKE_*, N_MIN_HALLAZGO_G/BOOST_G_FRACCION, RHO_FALLBACK) y posiblemente `motor_data.py` (ALFA_EMA_POR_LIGA, N0_ANCLA). Esos están bajo §1A — solo migrables a DB con autorización. **YO me enfoco en hardcodes operativos NO matemáticos**, complementarios a los suyos.

### 3A. `DB_NAME` duplicado en 5 archivos (redundancia pura)

`config_sistema.DB_NAME = 'fondo_quant.db'` ya existe, pero estos archivos lo redefinen en lugar de importarlo:

| Archivo | Línea | Acción |
|---|---|---|
| `src/persistencia/motor_purga.py` | 9 | Borrar literal, importar de `config_sistema` |
| `src/persistencia/motor_liquidador.py` | 8 | idem |
| `src/persistencia/importador_gold.py` | 11 | idem |
| `src/persistencia/reset_tablas_derivadas.py` | 9 | idem |
| `src/persistencia/motor_sincronizador.py` | 14 | idem |

**Riesgo:** ninguno funcional; cero impacto en lógica. Pura limpieza.
**Impacto si se cambia el nombre de la DB:** hoy hay que tocar 6 archivos; tras refactor, 1.

### 3B. Hardcodes operativos candidatos a migrar a DB (tabla `config_motor_valores`)

| Constante | Archivo | Línea | Tipo | Justificación |
|---|---|---|---|---|
| `INACTIVITY_MONTHS = 6` | `motor_purga.py` | 10 | parámetro de retención | Política operativa, no matemática. Cambiable sin tocar código. |
| `LAMBDA_EMA = 0.15` (árbitros) | `motor_arbitro.py` | 14 | EMA arbitral | OJO: distinto de ALFA_EMA del motor_data; EMA de árbitros (faltas/amarillas/rojas/penales). NO está en Reglas_IA.txt — es parámetro auxiliar, libre de migrar previa confirmación con experto-deportivo. |
| `BASE_URL` API-Football | `motor_tactico.py` | 13 | endpoint externo | Si la API cambia versión, hoy hay que recompilar. |
| `CSV_GOLD_STANDARD = 'modelo_estable.csv'` | `importador_gold.py` | 12 | path | Bajo, pero candidato si se versionan CSVs gold. |
| `EXCEL_FILE = 'Backtest_Modelo.xlsx'` | `motor_sincronizador.py` | 15 | path | Idem DB_NAME — debería estar en `config_sistema`. |
| `ligas_temporada_dividida = {"Inglaterra", "Turquia"}` | `motor_tactico.py` `_get_current_season()` | 37 | calendario por liga | Set hardcoded; al sumar liga europea hay que tocar código. Migrable a `ligas_stats.tipo_calendario`. |

### 3C. Set inverso derivado en runtime (limpieza menor)

`motor_backtest.py:18` y `motor_arbitro.py:17` definen exactamente:
```python
MAPA_LIGAS_ESPN = {pais: codigo for codigo, pais in LIGAS_ESPN.items()}
```
Misma línea, dos archivos. Candidato a moverlo a `config_sistema.py` como `MAPA_LIGAS_ESPN_INVERSO` (o directamente exponer `LIGAS_ESPN_POR_PAIS`).

### 3D. Lógicas redundantes detectadas (no migración a DB, sino refactor)

- `safe_int` / `safe_float`: definidas localmente en `motor_data.py`, `motor_backtest.py`, `motor_calculadora.py`, `importador_gold.py` (con variantes). Candidato a centralizar en `src/comun/utils.py`. **Riesgo:** firma debe ser idéntica a la usada por la calculadora — verificar antes.
- `determinar_resultado_apuesta()` en `motor_calculadora.py:366` y la lógica equivalente inline en `motor_liquidador.py:43-56`. El liquidador reimplementa el mismo árbol de strings. Hay riesgo: si junior-1 toca strings de apuesta en la calculadora pero el liquidador queda desincronizado, los estados se rompen. **Acción propuesta:** que el liquidador importe `determinar_resultado_apuesta` (firma pública estable, no se modifica).

**OJO §1A:** los strings `'[APOSTAR]'`, `'LOCAL'`, `'EMPATE'`, `'VISITA'`, `'OVER 2.5'`, `'UNDER 2.5'`, `'GANADA'`, `'PERDIDA'` son de la lista negra. La centralización mueve la lógica, NO los strings.

### 3E. Dependencia de `analista-datos` (bloqueante)

Toda migración a DB depende de que `analista-datos` defina la tabla canónica (PLAN §5.4 menciona `config_motor_valores` o equivalente). Hasta que esa tabla exista con esquema firmado, mi rol es solo:
1. Limpiar redundancias internas de `.py` (§3A, §3C — no requieren DB).
2. Documentar la lista de hardcodes (§3B) para que `analista-datos` los considere en su esquema.

---

## 4. Riesgos y zonas de cuidado

1. **Strings de estado de apuesta**: `[APOSTAR]`, `[GANADA]`, `[PERDIDA]` aparecen con corchetes en `motor_liquidador.py` y como `GANADA`/`PERDIDA` sin corchetes en `motor_calculadora.determinar_resultado_apuesta`. Verificar con tech-lead cuál es el formato canónico antes de cualquier centralización (puede ser un bug heredado, no un refactor mío).
2. **`MAPA_LIGAS_ESPN` inverso**: si lo expongo en config_sistema, hay que actualizar 2 imports. Cambio puramente interno pero requiere confirmar que ningún consumidor externo (scripts, juniors paralelos) lo importe del módulo viejo.
3. **`LAMBDA_EMA` de árbitros**: NO está en Reglas_IA.txt, pero es un EMA y conceptualmente similar a los matemáticos. Antes de migrarlo, confirmo con tech-lead si está bajo §1A o no.
4. **Boundary**: solo escribo en el bloque que tech-lead apruebe. Por defecto, NO toco `src/nucleo/` (territorio matemático), NO toco `src/comun/config_sistema.py` sin OK explícito (tabla central, único punto de verdad).

---

## 5. Confirmación final

- NO ejecuté ningún cambio en código.
- NO toqué la DB (`fondo_quant.db`).
- NO modifiqué `Backtest_Modelo.xlsx`.
- NO hice migraciones de schema.
- Espero asignación específica del `tech-lead` antes de tocar nada.
- Después de entregar este doc → IDLE hasta DM del tech-lead.
