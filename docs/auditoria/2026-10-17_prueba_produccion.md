# Prueba de producción — 2026-10-17

Base usada: copia (API de backup) de `fondo_quant.db` real: 6732 partidos procesados, 1308 equipos.
Ninguna prueba escribió en la base real, salvo la corrección de §3 (con backup previo).

## 1. Checklist

| # | Prueba | Resultado |
|---|---|---|
| 1 | Suite de tests (`pytest`) | **142 pasan** |
| 2 | Tests en 4 zonas horarias (ART, Madrid, Tokio, UTC) | **142 pasan** en cada una |
| 3 | Entorno limpio desde `requirements.txt` + tests | **OK**: dependencias completas |
| 4 | Integridad de la base real (`PRAGMA integrity_check`) | **ok**, modo WAL |
| 5 | Pipeline completo sobre la base real (ESPN en vivo) | **14 pasos OK**; aborta en cuotas por falta de API key (esperado) |
| 6 | Calculadora sobre EMAs reales | **96 partidos** calculados; sin cuotas → `[PASAR] Sin Cuotas` |
| 7 | Liquidación contra resultados reales de ESPN | **51 partidos** liquidados; 8 sin resultado publicado |
| 8 | Idempotencia (segunda corrida de liquidación) | **Sin cambios**: hash idéntico |
| 9 | `--status` | **0 errores** |
| 10 | Dashboard Streamlit (`AppTest`) sobre base real | **7 pestañas**, 0 excepciones |
| 11 | Exportación Excel | **OK** |
| 12 | Secretos en archivos trackeados | **Ninguno** en el índice actual |
| 13 | Camino del dinero de punta a punta (`tests/test_flujo_dinero_real.py`) | **OK**: pick → confirmación a 1.95 → cierre 1.80 → resultado 2-0 → `[GANADA]`, CLV +8.33%, bankroll +950 |

## 2. Bugs encontrados en esta prueba y corregidos

- `motor_backtest` solo liquidaba partidos `Calculado`. Si el pipeline abortaba antes de calcular, el partido quedaba `Pendiente` para siempre. Había 57 así.
- El diccionario de nombres tenía dos entradas envenenadas, tipeadas en el prompt interactivo el 13/10:
  - `venezia` → `sudo libinput debug-events --device /dev/input/event19`
  - `coventrycity` → `./iniciar_dashboard.sh`
- Causa: el prompt aceptaba cualquier texto. Ahora `nombre_equipo_valido()` rechaza flags, rutas y caracteres de shell.

## 3. Corrección aplicada a la base real

- Backup previo: `snapshots/fondo_quant_20261017_182804_pre_fix_nombres_corruptos.db`.
- Dos filas de `partidos_backtest` del 12/10 corregidas: `Atalanta vs Venezia` y `Coventry City vs Newcastle United`.

## 4. Veredicto

**El software está listo para operar en modo pretest.** Corre de punta a punta sobre datos reales, liquida contra resultados reales, es idempotente y no depende de la zona horaria.

**No está listo para apostar dinero real.** La validación contra Pinnacle 2024-25 (§2b del informe de auditoría) muestra que el modelo no tiene ventaja.

Bloqueantes antes de la primera corrida diaria:
1. `config.json` con `api_keys_odds`: sin eso el pipeline aborta en cuotas.
2. Rotación de las credenciales expuestas en el repo público.
3. Commit de los cambios: hoy todo está sin commitear en `main`.
