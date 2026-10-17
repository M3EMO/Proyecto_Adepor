# Auditoría 2026-10 (12 al 17 de octubre)

Epic: `adepor-thv`. Regla: ningún número se acepta sin recomputarlo desde datos crudos.

## 1. Números verificados

### Dinero real 2026 (`analisis/_liq_2026_picks.csv`)

| Población | N | Yield | IC95 |
|---|---|---|---|
| Apuestas con stake > 0, ponderado por stake | 52 | **−12.5%** | [−42%, +19%] |
| Todas las filas, incluido pretest con stake 0 | 281 | +30.0% | [+13%, +47%] |

- El "+30%" proviene de picks sin stake.
- El 44% de ese profit sale de 25 picks con cuota ≥ 4, compatibles con cuotas invertidas (D-007).

### Validación walk-forward contra Pinnacle (`analisis/validacion_fdco_walkforward.py`)

Datos: football-data.co.uk, Inglaterra, España, Italia y Alemania. 2023-24 calienta; 2024-25 evalúa (1445 partidos).

| Métrica | Motor viejo | Motor nuevo | Pinnacle cierre |
|---|---|---|---|
| k = goles / λ | 0.577 | 0.928 | — |
| P(empate) media | 0.184 | 0.262 | real ≈ 0.25 |
| Brier 1X2 | 0.649 | 0.637 | **0.572** |
| Log-loss 1X2 | 1.080 | 1.056 | **0.961** |
| Yield plano | −17.0% [−30%, −4%] | −15.8% [−36%, +4%] | — |
| CLV medio | −0.65% | −0.92% | — |

- Todos los picks son underdogs (cuota media 3.2–3.4).
- La mezcla modelo + apertura de Pinnacle tiene peso óptimo 0.

### Afirmaciones previas refutadas

| Afirmación | Veredicto |
|---|---|
| H4 X-rescue: yield +0.246, N=127 | No sostenida: el walk-forward propio da +0.011 [−0.040, +0.060] |
| Layer 3: Δ +0.426, N=160 | No sostenida: un filtro elegido entre cuatro, post-hoc |
| M.2: umbral n_acum < 60 | No sostenida: borde de bin, evaluado sobre la misma muestra |
| Layer 2 V12 Turquía: +0.116 | Débil: una liga entre 16 probadas |

## 2. Bugs corregidos

| Área | Bug |
|---|---|
| Track record | Picks recalculados post-kickoff y con resultado conocido |
| Cuotas | Cuotas en vivo sobrescribían las del pick |
| Modelo | Prior de EMA por partido usado como prior por equipo |
| Riesgo | Detector de drawdown nunca disparaba |
| Riesgo | Filtro M.2 nunca bloqueaba (nombre normalizado vs nombre ESPN) |
| Riesgo | Pretest pasaba a dinero real ignorando cuotas |
| Liquidación | CLV nunca se calculaba (tokens `1/X/2` vs `LOCAL/VISITA`) |
| Liquidación | Resultados emparejados sin liga ni fecha |
| Liquidación | Score ausente liquidado como 0-0 |
| Liquidación | Partidos `Pendiente` pasados nunca se liquidaban |
| Métricas | El dashboard sumaba P/L de partidos no liquidados |
| Ingesta | `motor_arbitro` nunca corría (formato de fecha) |
| Ingesta | El id de partido usaba la fecha local y perdía stats nocturnas |
| Ingesta | El prompt de nombres guardaba comandos de shell como equipos |
| Operación | El orquestador podía bloquearse con stderr lleno |
| Operación | `--rebuild` purgaba tablas aunque el import fallara |
| Operación | `rebuild_ema_v2` borraba a diario la historia de `motor_data` |
| Operación | Snapshots con `shutil.copy2` perdían páginas del WAL |
| Operación | Varias columnas existían solo por `ALTER` manuales en la base perdida |

## 3. Prueba de producción (2026-10-17)

| Prueba | Resultado |
|---|---|
| Tests | 141 pasan en 4 zonas horarias |
| Entorno limpio desde `requirements.txt` | Pasa |
| Pipeline completo con cuotas reales (copia de la base real) | 60 partidos con cuotas, 94 calculados, 8 picks con stake 0 |
| Liquidación contra ESPN real | 51 partidos liquidados |
| Idempotencia de la liquidación | Hash idéntico entre corridas |
| Camino del dinero de punta a punta (`tests/test_flujo_dinero_real.py`) | `[GANADA]`, CLV +8.33%, bankroll +950 |
| Dashboard, `--status`, exportación Excel | Sin errores |

## 4. Veredicto

- El software opera en modo pretest sobre datos reales, de punta a punta.
- El modelo actual no tiene ventaja contra Pinnacle y no debe apostar dinero real (D-014).
- El modelo nuevo se diseña con specs (D-018).
