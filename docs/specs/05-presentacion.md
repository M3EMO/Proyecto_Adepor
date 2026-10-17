# Dashboard (dashboard.py)

## Propósito

El dashboard muestra el estado del pipeline en una app Streamlit local. Es la vista principal del sistema. Permite confirmar apuestas reales desde la pestaña Picks vivos. Solo escribe en la base cuando el usuario confirma una apuesta.

## Entradas

| Fuente | Tabla o clave | Dónde se lee |
|---|---|---|
| SQLite (solo lectura) | `partidos_backtest` | `src/persistencia/motor_sincronizador.py:106-122` |
| SQLite (solo lectura) | `configuracion` (bankroll, bankroll_modo, piso, techo, fecha de corte) | `src/persistencia/motor_sincronizador.py:50-76` |
| SQLite (solo lectura) | `config_motor_valores` (`apuestas_live`, `fraccion_kelly`, `max_kelly_pct_normal`) | `src/persistencia/motor_sincronizador.py:91-103`, `dashboard.py:358-359` |
| SQLite (solo lectura) | `aportes_capital` | `src/persistencia/motor_sincronizador.py:79-88` |
| SQLite (solo lectura) | `apuestas_confirmadas`, `log_alertas` | `dashboard.py:92-102`, `src/persistencia/confirmaciones.py:24-36` |
| SQLite (solo lectura) | Columnas de cuota y resultado para yield | `dashboard.py:170-173` |
| Ruta de la base | `DB_NAME` | `src/comun/config_sistema.py:15` |

## Salidas (tablas y columnas que escribe)

El dashboard escribe solo al confirmar una apuesta. Las dos escrituras van en una transacción (`src/persistencia/confirmaciones.py:59-64`).

| Tabla | Operación | Columnas |
|---|---|---|
| `apuestas_confirmadas` | INSERT. Crea la tabla si no existe. | `id_partido`, `mercado`, `pick`, `cuota_tomada`, `stake`, `ts` |
| `partidos_backtest` | UPDATE | `cuota_1`, `cuota_x`, `cuota_2`, `cuota_o25` o `cuota_u25` (según el pick); `stake_1x2` o `stake_ou` (según el mercado) |

Pestañas que muestra la app:

| Pestaña | Función que la renderiza | Línea |
|---|---|---|
| Picks vivos | `_tab_picks` | `dashboard.py:444` |
| Dinero real | `_tab_dinero` | `dashboard.py:489` |
| Yield potencial | `_tab_yield` | `dashboard.py:525` |
| Historial | `_tab_historial` | `dashboard.py:558` |
| Resumen por liga | `_tab_resumen` | `dashboard.py:581` |
| Sombra | `_tab_sombra` | `dashboard.py:592` |
| Si hubiera | `_tab_si_hubiera` | `dashboard.py:619` |

Las pestañas se listan en `dashboard.py:31-32`. Se renderizan en `dashboard.py:670-684`.

## Comportamiento

Reglas en orden de ejecución:

1. Abre la base en modo solo lectura (`dashboard.py:39-41`).
2. Carga todos los datos con `cargar_todo` (`dashboard.py:349-373`).
3. Guarda el resultado en caché durante 60 segundos (`dashboard.py:376-382`).
4. Toma de `picks_vivos` solo partidos no liquidados, sin goles y con fecha futura (`dashboard.py:113`).
5. Toma solo apuestas cuyo texto empieza con `[APOSTAR]` (`dashboard.py:120`).
6. Descarta picks con cuota menor o igual a 1, o con probabilidad faltante (`dashboard.py:125-126`).
7. Incluye picks de pretest con stake 0 (`dashboard.py:106-107`, `dashboard.py:131`).
8. Marca como Confirmada cada par partido y mercado ya registrado (`dashboard.py:132`).
9. Muestra el formulario solo para picks no confirmados (`dashboard.py:471-473`).
10. Precarga cuota y stake del motor, con mínimos de 1.01 y 0.01 (`dashboard.py:478-483`).
11. Al enviar el formulario, llama a `confirmar_apuesta` (`dashboard.py:429-433`).
12. Si `confirmar_apuesta` lanza ValueError, muestra el error y no escribe (`dashboard.py:436-438`).
13. Si la confirmación sale bien, guarda el aviso, limpia la caché y recarga (`dashboard.py:439-441`).
14. Valida en `confirmar_apuesta` que el pick siga en `[APOSTAR]` (`src/persistencia/confirmaciones.py:51`).
15. Valida en `confirmar_apuesta` que el partido no haya empezado (`src/persistencia/confirmaciones.py:53-54`).
16. Dinero real usa solo apuestas liquidadas con stake mayor a 0 (`dashboard.py:67-77`, `dashboard.py:492`).
17. Equity suma bankroll base, P/L real y aportes, en orden de fecha (`dashboard.py:80-89`).
18. Historial muestra una fila por partido con el P/L neto de ambos mercados (`dashboard.py:138-165`).
19. Sombra compara Op1 (apuesta activa) contra Op4 (apuesta sombra) por partido (`dashboard.py:204-229`).
20. Sombra marca PENDIENTE si el partido no está liquidado (`dashboard.py:240-241`).
21. Si hubiera resimula el histórico con reglas actuales y Kelly, con compounding (`dashboard.py:253-300`).
22. Si hubiera usa solo partidos liquidados con goles cargados (`dashboard.py:259`).
23. Estado de confirmaciones: una alerta legacy cuenta en ambos mercados (`dashboard.py:92-102`).

## Invariantes (lo que nunca debe pasar)

- El dashboard nunca escribe en la base fuera de `_confirmar` (`dashboard.py:429-441`).
- Una apuesta nunca se confirma si el pick no está en `[APOSTAR]` (`src/persistencia/confirmaciones.py:51`).
- Una apuesta nunca se confirma después del kickoff (`src/persistencia/confirmaciones.py:53-54`).
- Una apuesta nunca se guarda con cuota menor o igual a 1 o stake menor o igual a 0 (`src/persistencia/confirmaciones.py:46-47`).
- Un par (partido, mercado) nunca tiene dos confirmaciones (`src/persistencia/confirmaciones.py:20`, clave primaria).
- Dinero real nunca cuenta picks de pretest con stake 0 (`dashboard.py:67-77`).
- La carga de datos nunca abre la base con permisos de escritura (`dashboard.py:39-41`, `dashboard.py:378`).

## Parámetros (clave de config_motor_valores o archivo de config, default, efecto)

| Clave o archivo | Scope | Default en código | Efecto |
|---|---|---|---|
| `fraccion_kelly` | global | 0.50 (`dashboard.py:358`) | Fracción de Kelly en la simulación Si hubiera |
| `max_kelly_pct_normal` | global | 0.025 (`dashboard.py:359`) | Tope de Kelly en la simulación Si hubiera |
| `bankroll` (tabla `configuracion`) | no aplica | 100000.00 (`src/persistencia/motor_sincronizador.py:61`) | Bankroll base del equity y de la simulación |
| `apuestas_live` | por liga | FALSE (`src/nucleo/motor_calculadora.py:2199`) | Marca cada liga como LIVE o pretest en el resumen |
| Caché de datos | no aplica | ttl=60 (`dashboard.py:376`) | Segundos antes de recargar la base |
| Zona horaria | no aplica | UTC-3 (`src/comun/tiempo.py:32-39`) | Corte de picks vivos y control de kickoff |
| `DB_NAME` | no aplica | `fondo_quant.db` en la raíz o `ADEPOR_DB` (`src/comun/config_sistema.py:15`) | Base que lee el dashboard |

## Tests de aceptación (tests existentes en tests/ que lo cubren + huecos sin test)

Tests existentes:

| Test | Archivo:línea | Cubre |
|---|---|---|
| `test_cargar_todo_con_filas_de_prueba` | `tests/test_dashboard_smoke.py:40` | Carga completa con filas de prueba |
| `test_confirmar_marca_solo_el_mercado_confirmado` | `tests/test_dashboard_smoke.py:82` | Confirmación de un solo mercado |
| `test_app_renderiza_las_siete_pestanas` | `tests/test_dashboard_smoke.py:92` | Render de las siete pestañas |
| `test_formulario_confirma_desde_la_app` | `tests/test_dashboard_smoke.py:100` | Flujo del formulario |
| `test_app_sin_liquidados_no_falla` | `tests/test_dashboard_smoke.py:113` | Caso sin partidos liquidados |
| `test_confirmar_guarda_cuota_y_stake_reales` | `tests/test_confirmaciones.py:19` | Escritura de cuota y stake |
| `test_no_confirma_pick_inexistente_ni_valores_invalidos` | `tests/test_confirmaciones.py:26` | Validaciones de entrada |
| `test_partido_confirmado_queda_congelado` | `tests/test_confirmaciones.py:35` | Congelamiento tras confirmar |
| `test_no_confirma_partido_empezado` | `tests/test_confirmaciones.py:43` | Control de kickoff |
| `test_picks_vivos_incluye_pretest_y_excluye_empezados` | `tests/test_confirmaciones.py:53` | Filtro de picks vivos |
| `test_flujo_completo_de_una_apuesta_real` | `tests/test_flujo_dinero_real.py:26` | Camino del dinero de punta a punta |
| Ocho tests de yield | `tests/test_yield_potencial.py:12-87` | Cálculo de yield y bootstrap IC95 |

Huecos sin test directo:

- `historial_df` no tiene test por nombre.
- `simular_si_hubiera` y `resumen_si_hubiera` no tienen test por nombre.
- `equity_df` y `resumen_liga_df` no tienen test por nombre.
- `curva_yield_df` y `filas_yield` no tienen test por nombre.
- `estado_confirmaciones` no tiene test por nombre.
- No hay test de una confirmación duplicada (`dashboard.py:436`).
- No hay test del aviso de la pestaña Picks vivos (`dashboard.py:450`).

## Limitaciones conocidas

- La pestaña Picks vivos dice "con stake > 0" pero la lista incluye picks con stake 0 (`dashboard.py:450` contra `dashboard.py:106-107`).
- Una confirmación duplicada devuelve un `ValueError` claro, que el formulario muestra como error.
- Los datos pueden quedar atrasados hasta 60 segundos por la caché (`dashboard.py:376`).
- El dashboard importa funciones con prefijo `_` desde `motor_sincronizador` (`dashboard.py:26-28`). Un cambio allí rompe el dashboard.
- La simulación Si hubiera es in-sample. La propia vista lo advierte (`dashboard.py:620-621`).
- La fracción de Kelly tiene dos fuentes: `configuracion` en el Excel (`src/persistencia/motor_sincronizador.py:70-74`) y `config_motor_valores` en el dashboard (`dashboard.py:358`).
- El dashboard no tiene autenticación. Solo debe escuchar en 127.0.0.1 (ver Lanzador).

# Lanzador del dashboard (iniciar_dashboard.sh)

## Propósito

Arranca el dashboard Streamlit solo en la interfaz local 127.0.0.1. No usa ngrok ni túneles.

## Entradas

- Intérprete `.venv/bin/python` (`iniciar_dashboard.sh:4`).
- Script `dashboard.py` en la raíz (`iniciar_dashboard.sh:4`).
- Base `fondo_quant.db` o la ruta de `ADEPOR_DB` (vía `src/comun/config_sistema.py:15`).

## Salidas (tablas y columnas que escribe)

- Proceso Streamlit con servidor HTTP local.
- No escribe tablas ni archivos del proyecto.

## Comportamiento

1. Cambia el directorio al del script (`iniciar_dashboard.sh:3`).
2. Reemplaza el proceso del shell con `streamlit run dashboard.py` (`iniciar_dashboard.sh:4`).
3. Fija la dirección del servidor en 127.0.0.1 (`iniciar_dashboard.sh:5`).
4. Activa el modo headless (`iniciar_dashboard.sh:6`).
5. Desactiva la telemetría de Streamlit (`iniciar_dashboard.sh:7`).

## Invariantes (lo que nunca debe pasar)

- El servidor nunca escucha en todas las interfaces (`iniciar_dashboard.sh:5`).
- El dashboard nunca sale a la red externa (`iniciar_dashboard.sh:2`).

## Parámetros (clave de config_motor_valores o archivo de config, default, efecto)

| Parámetro | Default | Efecto |
|---|---|---|
| Puerto | Default de Streamlit (8501). No se fija en el script. | Puerto HTTP local |
| Dirección | 127.0.0.1 (`iniciar_dashboard.sh:5`) | Limita el acceso a la máquina local |
| Telemetría | Desactivada (`iniciar_dashboard.sh:7`) | Ninguna llamada externa de uso |

## Tests de aceptación (tests existentes en tests/ que lo cubren + huecos sin test)

- No hay test del script.
- `tests/test_dashboard_smoke.py` prueba la app, no el lanzador.
- Hueco: no hay prueba de que el servidor enlace solo 127.0.0.1.

## Limitaciones conocidas

- El script usa bash. En Windows se usa `iniciar_dashboard.bat`, que no se revisó en esta spec.
- `exec` reemplaza el shell. Cerrar el terminal detiene el dashboard.
- Requiere el entorno `.venv` ya creado (ver Runbook).

# Exportación Excel (src/persistencia/motor_sincronizador.py)

## Propósito

Genera `Backtest_Modelo.xlsx` bajo demanda. La exportación no forma parte de la cascada diaria. Se lanza con `ejecutar_proyecto.py --exportar-excel` (`ejecutar_proyecto.py:700-702`). La vista principal es el dashboard.

## Entradas

- `partidos_backtest` en estados Calculado o Liquidado (`src/persistencia/motor_sincronizador.py:106-122`).
- `configuracion` para bankroll y Kelly (`src/persistencia/motor_sincronizador.py:50-76`).
- `config_motor_valores` clave `apuestas_live` (`src/persistencia/motor_sincronizador.py:91-103`).
- `aportes_capital` (`src/persistencia/motor_sincronizador.py:79-88`).

## Salidas (tablas y columnas que escribe)

Archivo `Backtest_Modelo.xlsx` en la raíz (`src/persistencia/motor_sincronizador.py:30`, `:182`). Hojas que crea:

| Hoja | Módulo | Línea de llamada |
|---|---|---|
| Backtest y Resumen por liga | `excel_hoja_backtest.py` | `motor_sincronizador.py:154`, `:164` |
| Dashboard | `excel_hoja_dashboard.py` | `motor_sincronizador.py:158` |
| Sombra | `excel_hoja_sombra.py` | `motor_sincronizador.py:161` |
| Si Hubiera | `excel_hoja_resimulacion.py` | `motor_sincronizador.py:168` |
| LIVE | `excel_hoja_live.py` | `motor_sincronizador.py:175` |

Escritura en la base que no es del Excel:

| Tabla | Operación | Columna | Línea |
|---|---|---|---|
| `partidos_backtest` | UPDATE | `estado` pasa de Liquidado a Calculado si faltan goles | `src/persistencia/motor_sincronizador.py:43-45`, commit en `:132` |

## Comportamiento

1. Abre la base (`src/persistencia/motor_sincronizador.py:128`).
2. Vuelve a Calculado los partidos Liquidados sin goles (`src/persistencia/motor_sincronizador.py:33-47`, `:131`).
3. Confirma esa escritura (`src/persistencia/motor_sincronizador.py:132`).
4. Lee bankroll base, bankroll operativo y Kelly (`src/persistencia/motor_sincronizador.py:134`).
5. Lee apuestas LIVE y aportes (`src/persistencia/motor_sincronizador.py:135-136`).
6. Lee los partidos (`src/persistencia/motor_sincronizador.py:138`).
7. Sale sin crear archivo si no hay partidos (`src/persistencia/motor_sincronizador.py:141-143`).
8. Crea la hoja Backtest con bankroll base (`src/persistencia/motor_sincronizador.py:154`).
9. Crea la hoja Dashboard con bankroll operativo (`src/persistencia/motor_sincronizador.py:158`).
10. Crea Sombra, Resumen y Si Hubiera (`src/persistencia/motor_sincronizador.py:161-168`). Si Hubiera tolera errores.
11. Crea LIVE y la inserta como primera pestaña (`src/persistencia/motor_sincronizador.py:172-177`). LIVE tolera errores.
12. Activa el recálculo al abrir y guarda el archivo (`src/persistencia/motor_sincronizador.py:180-182`).

## Invariantes (lo que nunca debe pasar)

- La exportación nunca debe cambiar la base. Hoy la cambia en el paso 2 (ver Limitaciones).
- El Excel nunca debe ser fuente de verdad para otros motores.
- La exportación nunca debe correr dentro de la cascada diaria (`ejecutar_proyecto.py:47-77`).

## Parámetros (clave de config_motor_valores o archivo de config, default, efecto)

| Parámetro | Default | Efecto |
|---|---|---|
| `EXCEL_FILE` | `Backtest_Modelo.xlsx` (`src/persistencia/motor_sincronizador.py:30`) | Nombre del archivo, relativo al directorio actual |
| `bankroll` | 100000.00 (`src/persistencia/motor_sincronizador.py:61`) | Bankroll base si falta la fila |
| `fraccion_kelly` (tabla `configuracion`) | 0.50 (`src/persistencia/motor_sincronizador.py:72-74`) | Fracción de Kelly en el Excel |
| `apuestas_live` | Valores TRUE, 1, T o YES (`src/persistencia/motor_sincronizador.py:102`) | Marca LIVE por liga |

## Tests de aceptación (tests existentes en tests/ que lo cubren + huecos sin test)

- `tests/test_excel_hojas.py:15`: el resumen excluye filas no liquidadas.
- `tests/test_persistencia_equity.py`: prueba parte del equity con este módulo.
- `tests/test_persistencia_excel_metricas.py`: dos tests de métricas del Excel.
- `tests/test_dashboard_smoke.py`: importa funciones de este módulo.
- Hueco: `main()` no tiene test de punta a punta.
- Hueco: la resurrección de partidos (`src/persistencia/motor_sincronizador.py:33-47`) no tiene test.
- Hueco: `excel_hoja_live`, `excel_hoja_sombra` y `excel_hoja_resimulacion` no tienen test por nombre.

## Limitaciones conocidas

- El docstring dice "4 hojas" (`src/persistencia/motor_sincronizador.py:5`). El código crea 5 hojas o 6 si se cuenta Resumen.
- La exportación escribe en la base (`src/persistencia/motor_sincronizador.py:43-45`). Contradice que sea solo exportación (`ejecutar_proyecto.py:701`).
- `EXCEL_FILE` depende del directorio actual. `ejecutar_proyecto.py` lo fija en la raíz (`ejecutar_proyecto.py:32`).
- Los dos valores de Kelly no coinciden entre el Excel y el dashboard (ver Dashboard).
- Las listas de valores TRUE no coinciden entre módulos. `config_motor.py` solo acepta TRUE (`src/comun/config_motor.py:26`).

## Anexo v2 (D-021): pestaña "Valor v2"

- Es la primera pestaña del dashboard.
- Muestra para cada resultado de los partidos futuros la probabilidad justa de Pinnacle y la cuota mínima.
- El usuario elige la casa e ingresa su cuota y su stake real.
- El botón de confirmar se deshabilita si la cuota está bajo la mínima.
- La sección "CLV de mis apuestas v2" muestra el CLV medio total y por casa.
- Tests: `tests/test_dashboard_v2.py`.
