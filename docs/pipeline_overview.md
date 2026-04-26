# Pipeline Adepor — Overview para LLM/Agentes

> **Para el agente que llega:** este es el flujo COMPLETO del sistema. Antes de proponer
> cambios, consultar las tablas SQL `pipeline_motores`, `motor_filtros_activos`,
> `xg_calibration_history`. Esto evita re-descubrir el sistema por inspección de código.

## Comando único

```bash
py ejecutar_proyecto.py            # Pipeline diario completo (14 motores en cascada)
py ejecutar_proyecto.py --status   # Snapshot estado sin tocar DB
py ejecutar_proyecto.py --summary  # Resumen post-ultima-corrida
py ejecutar_proyecto.py --help     # Lista subcomandos
```

## Flujo del pipeline (4 fases, 14 motores)

| # | Fase | Motor | ¿Crítico? | Qué hace |
|---|---|---|---|---|
| 0 | MANTENIMIENTO | motor_purga | no | Limpia datos derivados obsoletos |
| 1 | LIQUIDACION | motor_backtest | **SI** | Liquida partidos pasados con goles ESPN |
| 1.5 | LIQUIDACION | motor_liquidador | **SI** | Calcula GANO/PERDIO + CLV de Liquidados |
| 1.6 | LIQUIDACION | evaluar_pretest | no | Auto-flip LIVE/PRETEST por liga |
| 2 | LIQUIDACION | motor_arbitro | no | Tarjetas y eventos arbitrales |
| 3 | LIQUIDACION | motor_data | **SI** | EMA + Bayesian + xg_hibrido (scrapea ESPN histórico) |
| 4 | HORIZONTE | motor_fixture | **SI** | Proyecta calendario futuro |
| 5 | HORIZONTE | motor_tactico | no | Formaciones esperadas y DTs |
| 6 | HORIZONTE | motor_cuotas | **SI** | Cuotas 1X2/OU + cuota_cierre (CLV V9.3) |
| 6.5 | HORIZONTE | motor_cuotas_apifootball | no | Cuotas LATAM (API-Football) |
| 7 | DECISIONES | motor_calculadora | **SI** | **Cerebro:** Poisson + Dixon-Coles + 4 Caminos + Kelly |
| 8 | EXCEL | motor_backtest (2da vez) | no | Doble barrido liquidación |
| 8.5 | EXCEL | motor_liquidador (2da vez) | no | Barrido final apuestas |
| 9 | EXCEL | **motor_sincronizador** | **SI** | Genera `Backtest_Modelo.xlsx` |

Query DB para inventario actualizado:
```sql
sqlite3 fondo_quant.db "SELECT orden, fase, motor, critico, descripcion FROM pipeline_motores ORDER BY orden;"
```

## El Excel — Backtest_Modelo.xlsx

Generado por `src/persistencia/motor_sincronizador.py` (paso 9). 6 hojas:

| Hoja | Módulo | Contenido |
|---|---|---|
| Backtest | `excel_hoja_backtest.py` | Tabla principal con todos los partidos + picks + resultados |
| Resumen | `excel_hoja_backtest.crear_hoja_resumen` | KPIs por liga (hit, yield, volumen) |
| Dashboard | `excel_hoja_dashboard.py` | KPIs globales + métricas Python |
| Live | `excel_hoja_live.py` | Partidos próximos con picks activos |
| Sombra | `excel_hoja_sombra.py` | Comparativa Op1 vs Op4 (estrategias alternativas) |
| Resimulacion | `excel_hoja_resimulacion.py` | Re-simulación con parámetros what-if |

Trigger del Excel: el pipeline lo regenera SIEMPRE en el paso 9. Si querés sólo Excel sin recalcular: `py src/persistencia/motor_sincronizador.py` (no recomendado — usa estado DB actual).

## Filtros activos del motor

19 filtros inventariados — query:

```sql
sqlite3 fondo_quant.db "SELECT filtro, default_global, parametro_clave, referencia_manifesto FROM motor_filtros_activos ORDER BY filtro;"
```

Categorías (ver `motor_filtros_activos.referencia_manifesto`):

- **Decisión** (II.E): FLOOR_PROB_MIN, **MARGEN_PREDICTIVO_1X2** (V4.5 = 0.05),
  DIVERGENCIA_MAX_1X2, EV_MIN_ESCALADO, HALLAZGO_G/C, FIX_5
- **xG** (II.A): BETA_SOT, BETA_SHOTS_OFF, COEF_CORNER_LIGA, GAMMA_DISPLAY, RHO_DIXON_COLES
- **EMA** (II.B): ALFA_EMA (scope-liga), N0_ANCLA
- **Stake** (II.I): MAX_KELLY_PCT_NORMAL/ALTO
- **Shadow** (II.G): ALTITUD_NIVELES (en SHADOW por adepor-kc2)

## Tablas DB clave

| Tabla | Filas (~ahora) | Para qué |
|---|---|---|
| `partidos_backtest` | 507 | Estado actual (Liquidado / Calculado / Pendiente) |
| `historial_equipos` | 333 equipos × ligas | EMA actualizado (fav_home, con_home, etc.) |
| `ligas_stats` | 16 | rho_calculado + coef_corner_calculado por liga |
| `config_motor_valores` | ~40 | Parámetros scoped por liga |
| `equipos_altitud` | 48 | Altitudes de estadios (post-om4) |
| `motor_filtros_activos` | 19 | **Inventario filtros del motor** |
| `pipeline_motores` | 14 | **Inventario motores del pipeline** |
| `xg_calibration_history` | 25 | Resultados walk-forward por liga (3 iter) |
| `partidos_historico_externo` | 14,489 | Stats crudos 11 ligas (CSV+ESPN) |
| `picks_shadow_margen_log` | activo | SHADOW MODE V4.5 (Opcion C vs B) |
| `margen_optimo_per_liga` | 15 | Thresholds derivados (para futura PROPOSAL) |

## Si vas a tocar X, consultar Y primero

- **Coeficientes xG**: `motor_filtros_activos` + `config_motor_valores` (scope=<liga>) +
  evidencia previa en bead `adepor-dx8` PARTE B (OLS contraindicado).
- **Filtros de decisión**: `motor_filtros_activos` + `config_motor_valores` + V4.5 history
  en bead `adepor-dx8`.
- **EMA / xg_hibrido**: `partidos_historico_externo` para data + `walk_forward_*.py` para A/B.
- **rho por liga**: `ligas_stats` + bead `adepor-86e` finding mediana 16 ligas + bug `adepor-cae`
  (grid extension).
- **Altitud**: `equipos_altitud` + bead `adepor-23w` (TRIGGER re-eval) + `adepor-kc2`
  (decision-log DIFERIDO).

## Inputs externos del pipeline

| Fuente | Para qué | Limitación |
|---|---|---|
| **ESPN site.api.espn.com** | Goles + stats SoT/shots/corners + tarjetas | Solo ventana ~30 días, requiere `motor_data` profundidad histórica para warmup |
| **ESPN core.api.espn.com** | Eventos históricos por season | Funciona para 2-3 temps atrás (ver `cache_espn/`) |
| **The-Odds-API** | Cuotas 1X2 + O/U 2.5 (Pinnacle, bet365) | Solo 6 ligas grandes |
| **API-Football v3** | Cuotas LATAM + fixtures + (paid: posesión) | Free tier: rate limited 100/día, no stats por partido |
| **football-data.co.uk** | CSV histórico EUR (HF/AF/HY/AY incluido) | Solo EUR, no LATAM. ⚠ N1 = Eredivisie no Noruega (bug `adepor-a0i`) |
| **FBref.com** | xG StatsBomb profesional | Bloqueado 403 (anti-bot agresivo) |

## Snapshot policy

Antes de cualquier mutación a DB:

```python
import sqlite3, datetime, hashlib
ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
src = sqlite3.connect('fondo_quant.db')
dst = sqlite3.connect(f'snapshots/fondo_quant_{ts}_pre_<descripcion>.db')
src.backup(dst); src.close(); dst.close()
```

Snapshots existentes en `snapshots/`. Para rollback: copiar snapshot sobre `fondo_quant.db`.

## Mecanismo Manifesto (anti-cambios sin auditoría)

`Reglas_IA.txt` es el contrato. Su SHA-256 está en `configuracion.manifesto_sha256`.
**ANTES de modificar `Reglas_IA.txt` o constantes protegidas**:

1. Bead `[PROPOSAL: MANIFESTO CHANGE]` con label `proposal-manifesto`
2. Walk-forward A/B con N≥1000
3. Audit del crítico (decision-log bead)
4. Autorización humana explícita en turno: `MANIFESTO-CHANGE-APPROVED:bd-<id>`
5. Snapshot DB pre-cambio
6. Aplicar + recalcular SHA-256 en DB

Ejemplo reciente: bead `adepor-dx8` (V4.5 MARGEN_PREDICTIVO_1X2 = 0.05).

## Beads activos relevantes

```bash
bd list --status open --limit 20
bd ready  # los que se pueden trabajar (sin blockers)
```

Categorías:
- `proposal-manifesto`: cambios al Manifesto pending
- `decision-log` (closed): auditorías ya hechas
- TRIGGER (open): condiciones que disparan future work (ej: `adepor-23w` altitud N≥30)
- BUG/DATA (open): bugs detectados pero no urgentes (ej: `adepor-a0i` N1=Eredivisie)
- INVESTIGATION (open/deferred): research multi-sesión (ej: `adepor-bgt` xG 3 temps)

## Patrones aprendidos (lessons learned)

1. **Consultar inventario antes de proponer** (`motor_filtros_activos`, `pipeline_motores`).
   Caso: Lead propuso "agregar MARGEN_MIN_DECISION_1X2" que ya existía. Crítico lo encontró.
   Sistematizado en commit `b34368e`.

2. **Cambiar coef aislados puede empeorar el sistema integrado** (PARTE B `adepor-dx8`).
   El motor está calibrado holísticamente: gamma_display, EMA, beta_sot todos co-tuneados.
   Cambiar uno sin re-calibrar los otros generalmente empeora.

3. **Faltas NO es buen proxy de posesión** (OLS extendido `analisis/ols_xg_extendido_faltas.py`).
   Δ R² +0.003 promedio, signos inconsistentes entre ligas. NO proponer.

4. **Walk-forward over-estima vs sistema real** (crítico audit `adepor-9gs` COND-4).
   En PROD el delta es ~25% del simulado porque otros filtros del motor ya capturan picks marginales.

5. **Honestidad sobre paciencia humana** (optimizador_modelo.md).
   Si la evidencia A/B contradice la propuesta inicial, NO armar PROPOSAL automáticamente.
