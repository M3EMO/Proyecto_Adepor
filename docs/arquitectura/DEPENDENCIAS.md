# Grafo de Dependencias — Estado actual (pre-refactor)

> Generado por `tech-lead` el 2026-04-16. Snapshot del HEAD `508063f`.
> Todas las rutas son relativas al repo root `C:\Users\map12\Desktop\Proyecto_Adepor`.

---

## 1. Hallazgo clave

**Los `motor_*.py` NO se importan entre sí.** Cada motor es un script independiente
que `ejecutar_proyecto.py` invoca vía `subprocess.run([sys.executable, motor_X.py])`.
La comunicación inter-motor es **exclusivamente por SQLite** (`fondo_quant.db`).

Implicancia para el refactor: mover archivos a `src/<modulo>/` no rompe ningún
import cruzado entre motores. Solo hay que arreglar imports a:

- `config_sistema` (importado por 8 archivos)
- `gestor_nombres` (importado por 7 archivos)

Y actualizar las rutas de `subprocess.run(...)` en `ejecutar_proyecto.py`.

---

## 2. Imports Python (estáticos)

```
config_sistema.py
  └── (sin imports internos del proyecto)

gestor_nombres.py
  └── (sin imports internos del proyecto)
  └── lee: diccionario_equipos.json (raíz)

motor_data.py            ──▶ gestor_nombres, config_sistema (LIGAS_ESPN, DB_NAME)
motor_arbitro.py         ──▶ gestor_nombres, config_sistema (LIGAS_ESPN, DB_NAME)
motor_fixture.py         ──▶ gestor_nombres, config_sistema (LIGAS_ESPN, MAPA_LIGAS_ODDS, DB_NAME, API_KEYS_ODDS)
motor_cuotas.py          ──▶ gestor_nombres, config_sistema (MAPA_LIGAS_ODDS, DB_NAME, API_KEYS_ODDS)
motor_backtest.py        ──▶ gestor_nombres, config_sistema (LIGAS_ESPN, MAPA_LIGAS_ODDS, DB_NAME, API_KEYS_ODDS)
motor_tactico.py         ──▶ gestor_nombres, config_sistema (DB_NAME, API_KEY_FOOTBALL, MAPA_LIGAS_API_FOOTBALL)
motor_calculadora.py     ──▶ config_sistema (DB_NAME)
motor_sincronizador.py   ──▶ (DB_NAME hardcoded — no importa config_sistema)  ⚠️
motor_liquidador.py      ──▶ (DB_NAME hardcoded)                                ⚠️
motor_purga.py           ──▶ (DB_NAME hardcoded)                                ⚠️
importador_gold.py       ──▶ (DB_NAME hardcoded)                                ⚠️
desbloquear_matriz.py    ──▶ (DB_NAME hardcoded)                                ⚠️
reset_tablas_derivadas.py──▶ (DB_NAME hardcoded)                                ⚠️
calibrar_rho.py          ──▶ config_sistema (DB_NAME, LIGAS_ESPN, API_KEY_FOOTBALL, MAPA_LIGAS_API_FOOTBALL)
adepor_guard.py          ──▶ config_sistema (DB_NAME)

ejecutar_proyecto.py
  └── usa subprocess.run([sys.executable, '<motor_X.py>'])  ──no import directo──
```

⚠️ **Deuda menor (no se arregla en este refactor por restricción bit-a-bit):**
6 archivos hardcodean `DB_NAME = 'fondo_quant.db'` en vez de importar de
`config_sistema`. Se respeta tal cual.

---

## 3. Pipeline de ejecución (subprocess)

`ejecutar_proyecto.py` ejecuta en cascada secuencial:

```
FASE 0: motor_purga.py
FASE 1: motor_backtest.py → motor_liquidador.py → motor_arbitro.py → motor_data.py
FASE 2: motor_fixture.py → motor_tactico.py → motor_cuotas.py
FASE 3: motor_calculadora.py
FASE 4: motor_backtest.py → motor_liquidador.py → motor_sincronizador.py
```

Modos especiales (flags CLI):
- `--rebuild`     → importador_gold.py, reset_tablas_derivadas.py, desbloquear_matriz.py + cascada
- `--unlock`      → desbloquear_matriz.py + cascada
- `--purge-history` → reset_tablas_derivadas.py + cascada
- `--audit-names` → auditor/auditor_espn.py (sale antes de la cascada)

---

## 4. Tablas SQLite (contrato implícito entre motores)

Mapeo `motor → tabla` (READ = lee, WRITE = escribe).

| Tabla                       | motor_data | motor_calc | motor_fixture | motor_cuotas | motor_arbitro | motor_tactico | motor_backtest | motor_liquid. | motor_sinc. | motor_purga | calibrar_rho |
|---|---|---|---|---|---|---|---|---|---|---|---|
| historial_equipos           | RW         | R          |               |              |               |               | R              |               |             |             | R            |
| ema_procesados              | RW         |            |               |              |               |               |                |               |             | W (reset)   |              |
| ligas_stats                 | RW         | R          |               |              |               |               |                |               |             |             | RW (rho)     |
| equipos_stats               | RW         | R          |               |              |               | RW (dt)       |                |               |             | W (reset)   |              |
| equipos_altitud             |            | R          |               |              |               |               |                |               |             |             |              |
| arbitros_historial          |            | R          |               |              | RW            |               |                |               |             |             |              |
| partidos_backtest           |            | RW         | RW            | RW (cuotas)  |               | RW (form.)    | RW (resultado) | RW (estado)   | R           | W (purga)   |              |
| diccionario_equipos.json    | R          |            | RW            | RW           | R             | R             | R              |               |             |             |              |
| Backtest_Modelo.xlsx        |            |            |               |              |               |               |                |               | W           |             |              |

> Esto NO es exhaustivo — es el mapa que necesita el ensamblador para garantizar
> que mover archivos a otro folder no cambia el comportamiento. Detalle fino:
> cada junior verifica su carpeta no toca tablas fuera de las indicadas arriba.

---

## 5. Funciones públicas (firmas bloqueadas por PLAN §1.3)

> **Estas firmas NO se renombran ni se reordenan parámetros.**
> Son las que el Lead audita bit-a-bit post-refactor.

`motor_calculadora.py` (Núcleo):
- `min_ev_escalado(prob)`                                          — línea 189
- `multiplicador_delta_stake(delta_xg)`                            — línea 234
- `aplicar_hallazgo_g(p1, px, p2, pais, hallazgo_g_data)`          — línea 258
- `corregir_calibracion(p1, px, p2)`                               — línea 297
- `corregir_ventaja_local(xg_local, xg_visita, liga=None)`         — línea 324  (FIX A REVERTIDO — referencia)
- `evaluar_mercado_1x2(p1, px, p2, c1, cx, c2, liga=None)`         — línea 473
- `evaluar_mercado_ou(po, pu, co, cu, p1, px, p2, xg_local, xg_visita)` — línea 547
- `calcular_stake_independiente(pick, ev, cuota, bankroll, max_kelly_pct)` — línea 608
- `ajustar_stakes_por_covarianza(lista_apuestas)`                  — línea 625
- `tau(i, j, lam, mu, rho)`                                        — línea 428
- `poisson(k, lmbda)`                                              — línea 422
- `detectar_drawdown(cursor, umbral)`                              — línea 376

`motor_data.py` (Ingesta):
- `calcular_xg_hibrido(estadisticas, goles_reales, coef_corner_liga)` — línea 81
- `ajustar_xg_por_estado_juego(xg_crudo, gf, gc)`                  — línea 111
- `extraer_stats_raw(estadisticas)`                                — línea 63

`motor_sincronizador.py` (Persistencia):
- `calcular_metricas_dashboard(datos, fraccion_kelly)`             — línea 200
- `crear_hoja_dashboard(wb, metricas, bankroll)`                   — línea 329
- `crear_hoja_sombra(wb, datos, bankroll)`                         — línea 561

Todos los demás `def` son helpers privados al script (no se llaman desde otro
módulo Python — se llaman vía `subprocess` que ejecuta `main()`).

---

## 6. Constantes/dicts bloqueados (PLAN §1.1, §1.3)

Ubicación actual → ubicación post-refactor (sólo cambia el archivo, NO el contenido).

| Dict/Constante                       | Archivo origen        | Sección Reglas_IA   |
|---|---|---|
| `ALFA_EMA_POR_LIGA`                  | motor_data.py         | II.B                |
| `N0_ANCLA = 5`                       | motor_data.py         | II.B                |
| `RHO_FALLBACK = -0.09`               | motor_calculadora.py  | II.C3               |
| `MATRIZ_TACTICA` (OFE/EQU/DEF)       | motor_calculadora.py  | II.D                |
| `DIVERGENCIA_MAX_POR_LIGA`           | motor_calculadora.py  | IV.D                |
| `FACTOR_CORR_XG_OU_POR_LIGA`         | motor_calculadora.py  | II.E (V4.9)         |
| `FLOOR_PROB_MIN = 0.33`              | motor_calculadora.py  | IV.A                |
| `APUESTA_EMPATE_PERMITIDA = False`   | motor_calculadora.py  | IV.A                |
| `MARGEN_PREDICTIVO_1X2 = 0.03`       | motor_calculadora.py  | IV.A                |
| `TECHO_CUOTA_OU = 6.0`               | motor_calculadora.py  | IV.D2               |
| `MARGEN_XG_OU_OVER/UNDER`            | motor_calculadora.py  | IV.D2 (Fix B)       |
| `FRACCION_KELLY = 0.50`              | motor_calculadora.py  | IV.E                |
| `MAX_KELLY_PCT_NORMAL/DRAWDOWN`      | motor_calculadora.py  | IV.E                |
| `DRAWDOWN_THRESHOLD = 5`             | motor_calculadora.py  | IV.E                |
| `DELTA_STAKE_MULT_*` + flag          | motor_calculadora.py  | IV.G                |
| `N_MIN_HALLAZGO_G = 50` + boost      | motor_calculadora.py  | IV.H                |
| `CALIBRACION_ACTIVA`                 | motor_calculadora.py  | II.C3 (Fix #5)      |
| `HALLAZGO_G_ACTIVO`                  | motor_calculadora.py  | IV.H                |
| `CORR_VISITA_ACTIVA`                 | motor_calculadora.py  | II.C (FIX A REVERT) |
| `LIGAS_ESPN`, `MAPA_LIGAS_ODDS`,     | config_sistema.py     | (config global)     |
|   `MAPA_LIGAS_API_FOOTBALL`          |                       |                     |
| Estados ciclo de vida (PEND/CALC/    | config_sistema.py     | (config global)     |
|   FIN/LIQUIDADO)                     |                       |                     |

---

## 7. Validaciones de strings exactos (NO TOCAR)

Comparaciones literales que sobreviven al refactor sin cambios:
- `pais == 'Argentina'`, `'Brasil'`, `'Inglaterra'`, `'Noruega'`, `'Turquia'`, etc.
- `apuesta == 'LOCAL'`, `'EMPATE'`, `'VISITA'`, `'OVER'`, `'UNDER'`, `'PASAR'`
- `estado == 'Liquidado'`, `'Pendiente'`, `'Calculado'`, `'Finalizado'`
- Keys de matriz táctica: `'OFE'`, `'EQU'`, `'DEF'`
- Status de DT: `'ACTIVO'`, `'CESADO'` (motor_tactico)
- Camino de apuesta: `'Camino 1'`, `'Camino 2'`, `'Camino 2B'`, `'Camino 3'`

---

## 8. Conclusión para el ensamblaje

El refactor es **mecánico**:
1. Mover 14 archivos `.py` a 3 carpetas + raíz.
2. Cambiar `import gestor_nombres` y `from config_sistema import ...` por imports
   absolutos: `from src.comun.gestor_nombres import ...` etc.
3. Cambiar las rutas en `subprocess.run` de `ejecutar_proyecto.py`.
4. Crear `__init__.py` en cada paquete.
5. Verificar que `python -c "import src.ingesta.motor_data; ..."` no rompe.

**No hay grafo de llamadas internas a romper** — esa es la razón por la que el
PLAN puede mover los motores libremente entre módulos sin tocar matemática.
