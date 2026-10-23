# Producto terminado: calculadora, medición y deploy

Estado: borrador del 2026-10-22. Define qué significa "terminado" y cómo se integran las piezas.

## Propósito

El producto es una calculadora de apuestas con medición honesta. Calcula la probabilidad justa y la cuota mínima de cada pick. Mide yield y CLV con las cuotas realmente tomadas.

El producto no promete edge. El edge es un resultado empírico que el sistema mide. La regla de promoción está en `10-modelo-v2.md`.

## Piezas e integración

| Pieza | Código | Spec | Estado |
|---|---|---|---|
| Fixtures y resultados | `src/ingesta/motor_fixture.py` | `01-ingesta.md` | Existe |
| Cuotas vivas y cierre de Pinnacle | `src/ingesta/motor_cuotas.py` | `01-ingesta.md` | Existe |
| Captura forward de casas | `src/ingesta/motor_oddspapi.py` | `01-ingesta.md` (anexo) | Existe |
| Calculadora: prob justa, cuota mínima, stake | `src/nucleo/valor_v2.py` | `10-modelo-v2.md` | Existe |
| Confirmación de apuesta con cuota real | `src/persistencia/confirmaciones.py` | `04-liquidacion.md` | Existe |
| Liquidación, CLV y yield | `src/persistencia/` | `04-liquidacion.md` | Existe |
| Dashboard | `dashboard.py` | `05-presentacion.md` | Existe |
| Orquestador y cron | `ejecutar_proyecto.py`, `ejecutar_robot.sh` | `06-operacion.md` | Existe |
| Estudio xG de FotMob | `scripts/research/fotmob_pedir.py`, `analisis/fotmob_xg_vs_pinnacle.py` | `07-fotmob.md`, `11-evaluacion-xg.md` | Nuevo |
| Chequeo de salud | `scripts/ops/salud.py` | Esta spec | Nuevo, con pruebas en `tests/test_salud.py` |
| Informe de medición | `scripts/ops/informe_medicion.py` | Esta spec | Nuevo, con pruebas en `tests/test_informe_medicion.py` |

Flujo de datos:
1. `motor_fixture` crea los partidos próximos.
2. `motor_cuotas` captura las cuotas de Pinnacle y las de otras casas.
3. `valor_v2` calcula probabilidad justa, cuota mínima y stake sugerido.
4. El usuario compara la cuota mínima con su casa y confirma la apuesta con la cuota real.
5. La captura de cierre guarda el cierre de Pinnacle antes del kickoff.
6. La liquidación calcula P/L y CLV por apuesta.
7. El informe de medición resume yield, CLV y calibración con IC95.

## Chequeo de salud (nuevo)

`scripts/ops/salud.py` sale con código 0 si todo está bien y distinto de 0 si algo falla.

| Chequeo | Falla si |
|---|---|
| Pipeline diario | El log `pipeline_YYYYMMDD.log` más reciente tiene más de 26 h |
| Captura de cierre | `cierre_YYYYMM.log` no cambió en 30 min |
| Base | `PRAGMA integrity_check` no devuelve `ok` |
| Snapshot | El último snapshot en `snapshots/` tiene más de 7 días |
| Cuotas Pinnacle | Más del 20% de los partidos de las próximas 48 h con cuota de mercado no tiene `pin_1` |
| Ligas sin cuotas | Solo avisa: lista las ligas con partidos próximos y ninguna cuota |
| Cupo de cuotas | No implementado: exige red. Queda como mejora |

## Informe de medición (nuevo)

`scripts/ops/informe_medicion.py` lee solo apuestas `Liquidado` con stake > 0 (contrato, regla 4).

| Métrica | Definición |
|---|---|
| Yield | P/L sobre stake total, con la cuota tomada, IC95 bootstrap |
| CLV medio | EV de la cuota tomada contra el cierre de Pinnacle sin margen, IC95 |
| Calibración | Log-loss de la prob justa contra el resultado, por decil, de todos los picks |
| N | Apuestas liquidadas con stake > 0 |

- Con N menor que 50, el informe muestra los números y avisa que no concluyen (trigger `adepor-hm9`).
- La regla de promoción del modelo propio no cambia (`10-modelo-v2.md`, punto 5).

## Criterios de "terminado"

| Id | Criterio | Estado al 2026-10-22 |
|---|---|---|
| P1 | `pytest` pasa completo | Cumple |
| P2 | Cron instalado para pipeline (9 y 17 h) y cierre (cada 15 min) | Instalado, sin historial largo |
| P3 | `salud.py` corre desde cron cada hora y avisa si falla | Cumple: cron cada hora, primera corrida a las 01:00 del 2026-10-23 detectó la falla real del pipeline. El dashboard muestra un aviso rojo (`tests/test_dashboard_smoke.py`) |
| P4 | `informe_medicion.py` genera el informe con N, yield, CLV y calibración | Script listo y probado; hoy N=0 y los 25 liquidados no tienen Pinnacle previo |
| P5 | El runbook (`06-operacion.md`) cubre instalación desde cero en una máquina limpia | Cumple (2026-10-23): clon limpio, venv, `pip install -r requirements.txt`, `inicializar_db.py`, `pytest` y `--status` pasan. En una máquina nueva falta copiar `config.example.json` a `config.json` y cargar las claves. Esta máquina ya lo tiene |
| P6 | Una prueba de punta a punta cubre el flujo v2 con apuesta confirmada | Existe: `tests/test_flujo_dinero_real.py` |
| P7 | Hay un backup automático de la base antes del pipeline | Cumple: `ejecutar_robot.sh` hace `adepor_guard.py snapshot` antes del pipeline (`tests/test_robot_snapshot.py`) |
| P8 | Al menos 50 apuestas liquidadas con CLV para el primer veredicto de edge | Pendiente: hoy hay 0 |

P1 a P7 son de ingeniería y se cierran con código y pruebas. P8 depende del tiempo y de las apuestas reales del usuario.

## Limitaciones conocidas

- Un fallo de `salud.py` queda en `data/logs/salud.log`, en `data/logs/salud_estado.json` y como aviso rojo en el dashboard. No hay mail ni notificación de escritorio.
- El dashboard ignora el estado si tiene más de 3 h, porque entonces el cron de salud no corre.
- Los snapshots se acumulan sin retención: dos por día, cerca de 2.5 MB por día.
- Perú, Uruguay, Ecuador, Colombia, Bolivia y Venezuela no tienen cuotas. `config_sistema.py` las marca sin cobertura en The Odds API. Los partidos se crean y no generan picks.
- Los 25 partidos liquidados de hoy no tienen Pinnacle previo. La calibración empieza vacía.

## Cambios que requieren aprobación

- Esta spec no cambia decisiones, probabilidades ni riesgo. No requiere bead `[PROPOSAL: MANIFESTO CHANGE]`.
- Una tabla nueva en la base requiere bead `[PROPOSAL: SCHEMA CHANGE]`.
- Una mejora de modelo con xG entra por shadow y por bead, aunque `11-evaluacion-xg.md` dé positivo.
