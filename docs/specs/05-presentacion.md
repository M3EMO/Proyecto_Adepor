# Dashboard (dashboard.py)

## Propósito

El dashboard muestra el estado del v2 en una app Streamlit local. Es la única vista del sistema: la exportación a Excel se borró en D-023. Permite confirmar apuestas reales desde la pestaña Valor v2. Solo escribe en la base cuando el usuario confirma una apuesta.

## Entradas

| Fuente | Tabla o clave | Dónde se lee |
|---|---|---|
| SQLite (solo lectura) | `partidos_backtest`, incluidas `pin_*` y `pin_cierre_*` | `dashboard.py:42-53`, `dashboard.py:204-222` |
| SQLite (solo lectura) | `configuracion` (bankroll, bankroll_modo, piso, techo, fecha de corte) | `dashboard.py:56-67`, `src/persistencia/bankroll.py` |
| SQLite (solo lectura) | `aportes_capital` | `dashboard.py:70-76` |
| SQLite (solo lectura) | `apuestas_confirmadas`, `log_alertas` | `dashboard.py:126-136`, `dashboard.py:225-244` |
| SQLite (solo lectura) | Columnas de cuota y resultado para yield | `dashboard.py:166-171` |
| `config_motor_valores` | `umbral_ev_v2`, `fraccion_kelly_v2`, `tope_stake_v2` | `src/nucleo/valor_v2.py` |
| Ruta de la base | `DB_NAME` | `src/comun/config_sistema.py:15` |

## Salidas (tablas y columnas que escribe)

El dashboard escribe solo al confirmar una apuesta. Las dos escrituras van en una transacción (`src/persistencia/confirmaciones.py`).

| Tabla | Operación | Columnas |
|---|---|---|
| `apuestas_confirmadas` | INSERT. Crea la tabla si no existe. | `id_partido`, `mercado`, `pick`, `cuota_tomada`, `stake`, `casa`, `ts` |
| `partidos_backtest` | UPDATE | `apuesta_1x2` o `apuesta_ou` (`[APOSTAR] <pick>`); la cuota del pick; `stake_1x2` o `stake_ou` |

Pestañas que muestra la app (`dashboard.py:26`, render en `dashboard.py:488-501`):

| Pestaña | Función que la renderiza | Línea |
|---|---|---|
| Valor v2 | `_tab_valor_v2` | `dashboard.py:329` |
| Dinero real | `_tab_dinero` | `dashboard.py:397` |
| Yield potencial | `_tab_yield` | `dashboard.py:429` |
| Historial | `_tab_historial` | `dashboard.py:462` |

## Comportamiento

Reglas en orden de ejecución:

1. Abre la base en modo solo lectura (`dashboard.py:37-39`).
2. Carga todos los datos con `cargar_todo` (`dashboard.py:247-262`).
3. Guarda el resultado en caché durante 60 segundos (`dashboard.py:265-272`).
4. Valor v2 lista los resultados de partidos futuros sin goles, con su probabilidad justa de Pinnacle y su cuota mínima (`dashboard.py:204-222`).
5. Valor v2 marca como Confirmada cada par partido y mercado ya registrado (`dashboard.py:126-136`).
6. El formulario sugiere el stake con `stake_v2` y el bankroll operativo (`dashboard.py:352-374`).
7. El botón se deshabilita si la cuota de la casa está bajo la mínima o el stake es 0 (`dashboard.py:369-372`).
8. Al confirmar, llama a `confirmar_apuesta` con el pick y la casa (`dashboard.py:314-326`).
9. Si `confirmar_apuesta` lanza ValueError, muestra el error y no escribe (`dashboard.py:321-323`).
10. Si la confirmación sale bien, guarda el aviso, limpia la caché y recarga (`dashboard.py:324-326`).
11. El bloque CLV muestra el CLV de cada apuesta confirmada contra el cierre de Pinnacle sin margen, total y por casa (`dashboard.py:225-244`, `dashboard.py:377-394`).
12. Dinero real usa solo apuestas liquidadas con stake mayor a 0 (`src/persistencia/metricas.py`).
13. Equity suma bankroll base, P/L real y aportes, en orden de fecha (`dashboard.py:114-123`).
14. Yield potencial incluye los picks del v1 con stake 0 que siguen en la base (`dashboard.py:429-459`).
15. Historial muestra una fila por partido con el P/L neto de ambos mercados (`dashboard.py:139-163`).
16. Valor v2 tiene una tabla editable: el usuario carga la cuota de su casa por pick, y la sesión la guarda (`_tab_valor_v2`).
17. `tabla_ev` calcula `EV = cuota casa × prob justa − 1` y recomienda apostar si la cuota iguala o supera la mínima.
18. El formulario de confirmación aparece solo para picks recomendados y todavía no confirmados (`_bloque_ev`).
19. Historial muestra, para cada partido jugado, el favorito de Pinnacle, si acertó, su Brier y su log-loss (`resultados_pinnacle`).
20. `resultados_pinnacle` usa el cierre si se capturó; si no, usa la última cuota previa al kickoff.

## Invariantes (lo que nunca debe pasar)

- El dashboard nunca escribe en la base fuera de `_confirmar` (`dashboard.py:314-326`).
- Una apuesta nunca se confirma después del kickoff (`src/persistencia/confirmaciones.py`).
- Una apuesta nunca se guarda con cuota menor o igual a 1 o stake menor o igual a 0 (`src/persistencia/confirmaciones.py`).
- Un par (partido, mercado) nunca tiene dos confirmaciones (clave primaria de `apuestas_confirmadas`).
- Dinero real nunca cuenta picks con stake 0.
- La carga de datos nunca abre la base con permisos de escritura (`dashboard.py:37-39`).

## Parámetros (clave de config_motor_valores o archivo de config, default, efecto)

| Clave o archivo | Scope | Default en código | Efecto |
|---|---|---|---|
| `umbral_ev_v2`, `fraccion_kelly_v2`, `tope_stake_v2` | global | Ver `docs/specs/10-modelo-v2.md` | Cuota mínima y stake sugerido |
| `bankroll` (tabla `configuracion`) | no aplica | 100000.00 (`dashboard.py:56-67`) | Bankroll base del equity |
| Caché de datos | no aplica | ttl=60 (`dashboard.py:265`) | Segundos antes de recargar la base |
| Zona horaria | no aplica | UTC-3 (`src/comun/tiempo.py:32-39`) | Corte de partidos vivos y control de kickoff |
| `DB_NAME` | no aplica | `fondo_quant.db` en la raíz o `ADEPOR_DB` (`src/comun/config_sistema.py:15`) | Base que lee el dashboard |

## Tests de aceptación (tests existentes en tests/ que lo cubren + huecos sin test)

| Test | Archivo:línea | Cubre |
|---|---|---|
| `test_cargar_todo_con_filas_de_prueba` | `tests/test_dashboard_smoke.py:37` | Dinero real, equity, yield e historial |
| `test_app_renderiza_las_cuatro_pestanas` | `tests/test_dashboard_smoke.py:62` | Render de las cuatro pestañas |
| `test_app_sin_liquidados_no_falla` | `tests/test_dashboard_smoke.py:70` | Base recién creada |
| Siete tests de Valor v2 | `tests/test_dashboard_v2.py` | Partidos vivos, EV, confirmación, CLV, resultados de Pinnacle y bases sin `pin_*` |
| Siete tests de confirmación | `tests/test_confirmaciones.py:18-65` | Validaciones, kickoff, duplicados y casa |
| `test_flujo_v2_pinnacle_como_verdad` | `tests/test_flujo_dinero_real.py:26` | Camino del dinero v2 de punta a punta, con bankroll |
| Dos tests de métricas | `tests/test_metricas.py` | P/L, volumen y p-valor t de Student |
| Ocho tests de yield | `tests/test_yield_potencial.py` | Cálculo de yield y bootstrap IC95 |

Huecos sin test directo:

- `historial_df`, `equity_df` y `curva_yield_df` no tienen test por nombre.
- `estado_confirmaciones` no tiene test por nombre.

## Limitaciones conocidas

- Los datos pueden quedar atrasados hasta 60 segundos por la caché (`dashboard.py:265`).
- El dashboard no tiene autenticación. Solo debe escuchar en 127.0.0.1 (ver Lanzador).
- `confirmar_apuesta` conserva el camino v1 sin `pick`, que exige un `[APOSTAR]` del motor. El dashboard ya no lo usa.
- Las listas de valores TRUE no coinciden entre módulos. `config_motor.py` solo acepta TRUE (`src/comun/config_motor.py:26`).

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
