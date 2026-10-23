# Registro de decisiones

Cada entrada registra una decisión vigente. Una decisión nueva que reemplaza a otra la marca como **Reemplazada**.

Formato: fecha · decisión · motivo · evidencia · bead.

---

## D-001 · 2026-10-12 · Solo se calculan partidos futuros, sin goles y sin apuesta confirmada
- **Motivo:** el motor recalculaba picks después del kickoff y con el resultado ya absorbido por las EMAs.
- **Evidencia:** en un snapshot de abril, 23 picks con stake tenían goles conocidos; 19 ya estaban en las EMAs.
- **Bead:** `adepor-thv.2`.

## D-002 · 2026-10-12 · Las cuotas de un partido no se sobrescriben tras el kickoff ni tras confirmar la apuesta
- **Motivo:** The Odds API devuelve cuotas en vivo, y el P/L se valoraba con la última cuota capturada.
- **Evidencia:** `commenceTimeFrom` excluye eventos en juego; la cuota de cierre se sigue capturando para el CLV.

## D-003 · 2026-10-12 · El prior de las EMAs se calcula por equipo, no por partido
- **Motivo:** el prior por partido (~2.6 goles) inflaba las lambdas ~1.7x, con sesgo dependiente del N de cada equipo.
- **Evidencia:** con datos reales de Pinnacle 2024-25, k = goles/λ pasa de 0.577 a 0.928.
- **Bead:** `adepor-thv.3`.

## D-004 · 2026-10-13 · Hallazgo G, Fix #5 y Hallazgo C salen del camino de decisión
- **Motivo:** Hallazgo G inflaba locales no favoritos; Fix #5 no era monótono; Hallazgo C se basaba en 5 aciertos.
- **Evidencia:** el OOS propio midió que Hallazgo G empeoraba hit y Brier.
- **Bead:** `adepor-thv.12` (aprobado por el usuario).

## D-005 · 2026-10-13 · Layer 3 H4 queda en modo shadow
- **Motivo:** con el empate bloqueado, Layer 3 nunca apostaba X; apostaba LOCAL o VISITA con probabilidades V12.
- **Bead:** `adepor-thv.12`.

## D-006 · 2026-10-13 · El filtro M.2 requiere opt-in explícito (`m2_activo`)
- **Motivo:** M.2 nunca bloqueó en vivo, y su umbral 60 salió in-sample.
- **Bead:** `adepor-thv.12`.

## D-007 · 2026-10-13 · Un pick con EV ≥ 100% se trata como error de datos
- **Motivo:** había cuotas local/visita invertidas; en 8 de 8 casos ganó el favorito del modelo.
- **Regla:** `RATIO_MIN_IMPLICITA = 0.5`. El camino C3 "Alta Convicción" queda inalcanzable.
- **Bead:** `adepor-thv.18`.

## D-008 · 2026-10-13 · El pretest pasa a dinero real solo con yield positivo significativo y aprobación humana
- **Motivo:** el criterio anterior usaba hit ≥ 55% contra p0 = 0.5, sin mirar cuotas.
- **Regla:** yield plano > 0, binomial contra el break-even, N ≥ 15 y `--aprobar-live`.

## D-009 · 2026-10-13 · Kelly usa el capital real cuando cae bajo `bankroll_piso`
- **Motivo:** el clamp al piso dimensionaba stakes con capital inexistente.

## D-010 · 2026-10-13 · Las fuentes de datos son ESPN y The Odds API
- **Motivo:** el usuario quiere menos dependencias; SofaScore bloquea esta IP con 403.
- **Consecuencia:** API-Football se retira; Sofa queda como enriquecimiento opcional.

## D-011 · 2026-10-13 · La presentación es un Streamlit local único; Telegram se retira
- **Regla:** "Confirmar apuesta" guarda la cuota tomada y el stake real, y congela el pick.
- **Consecuencia:** el Excel queda como exportación a pedido (`--exportar-excel`). Reemplazada por D-023: el Excel se borró.

## D-012 · 2026-10-13 · La base arranca desde cero con `scripts/db/inicializar_db.py`
- **Motivo:** la base de producción anterior se perdió.

## D-013 · 2026-10-13 · Ningún pick pasa si un equipo tiene menos de 5 partidos en su EMA
- **Motivo:** en arranque en frío la EMA es casi el prior de la liga, y el edge es ruido.

## D-014 · 2026-10-13 · El modelo actual no apuesta dinero real
- **Evidencia:** contra Pinnacle 2024-25 en 4 ligas, Brier 0.637 contra 0.572 y yield −15.8% con CLV negativo.
- **Evidencia:** mezclar el modelo con la cuota de apertura da peso óptimo 0: el modelo no agrega información.
- **Bead:** `adepor-thv.22`.

## D-015 · 2026-10-13 · Los pesos xG dinámicos (Kalman) no se promueven
- **Evidencia:** explican mejor los goles (z = 7.7), pero empeoran el Brier 1X2 (0.6393 contra 0.6366).
- **Bead:** `adepor-thv.21`.

## D-016 · 2026-10-17 · El riesgo de credenciales expuestas queda aceptado por el usuario
- **Estado:** las credenciales salieron del índice de git, pero siguen en el historial público.
- **Bead:** `adepor-thv.1`.

## D-017 · 2026-10-17 · La documentación pasa a `docs/specs/` y `docs/decisiones/`
- **Motivo:** 132 archivos MD con afirmaciones refutadas y sin estructura.
- **Consecuencia:** la investigación de `docs/papers` va al vault global (`research/betdeportivo-papers-2026`).

## D-018 · 2026-10-17 · El modelo nuevo se diseña desde cero con una sesión de specs
- **Regla:** solo apuesta si le gana a Pinnacle fuera de muestra, con métricas fijadas por adelantado.
- **Spec:** `docs/specs/10-modelo-v2.md`.

## D-019 · 2026-10-17 · Se aprueba el diseño del v2: Pinnacle como verdad y comparación manual con la casa del usuario
- **Regla:** el dashboard muestra la probabilidad justa de Pinnacle y la cuota mínima de cada pick.
- **Regla:** el usuario confirma solo si su casa paga más; el CLV de lo confirmado mide el edge.
- **Spec:** `docs/specs/10-modelo-v2.md`.

## D-020 · 2026-10-17 · El stake sale del frente de Pareto entre crecimiento y Max DD
- **Motivo:** el yield no depende del tamaño del stake; el crecimiento y el drawdown sí.
- **Regla:** se elige la fracción de Kelly y el tope con mayor crecimiento y Max DD p95 bajo la tolerancia.
- **Tolerancia:** Max DD p95 ≤ 15% (decisión del usuario, 2026-10-17). El bankroll sigue sin decidir.
- **Herramienta:** `analisis/pareto_stake.py`; necesita al menos 50 picks liquidados.
- **Default provisorio:** tope de 0.5% del bankroll; con un edge sintético de 5% es lo que cumple el 15%.

## D-021 · 2026-10-17 · El v2 queda implementado
- **Prueba real:** con cuotas en vivo, `motor_cuotas` capturó Pinnacle en 57 partidos (11 con O/U 2.5).
- **Prueba de punta a punta:** confirmación en BetWarrior a 2.20, cierre Pinnacle 1.90, `[GANADA]` y CLV v2 positivo.
- **Spec:** `docs/specs/10-modelo-v2.md` §Implementación.

## D-022 · 2026-10-18 · El motor v1 sale del camino diario
- **Motivo:** el v1 no le gana a Pinnacle (D-014), y el v2 decide con Pinnacle sin margen (D-019).
- **Regla:** la cascada diaria corre solo `motor_backtest`, `motor_liquidador`, `motor_fixture` y `motor_cuotas`.
- **Fase 2:** el código v1, sus tests y sus pestañas del dashboard se borran en un bead aparte.
- **Bead:** `adepor-i1n`.

## D-023 · 2026-10-19 · El código del motor v1 se borra
- **Motivo:** el v1 salió del camino diario (D-022) y el v2 no usa su código.
- **Borrado:** motores v1 (calculadora, EMAs, árbitro, táctico, adaptativo, purga, rho), scrapers de SofaScore, scripts que dependían de ellos y sus tests.
- **Borrado:** la exportación a Excel (`--exportar-excel`), por decisión del usuario; el Streamlit queda como única vista.
- **Borrado:** los subcomandos `--rebuild`, `--unlock`, `--purge-history` y `--analisis`.
- **Dashboard:** quedan Valor v2, Dinero real, Yield potencial e Historial.
- **Fuera de alcance:** `analisis/` (research congelado) y las tablas y claves v1 de la base.
- **Bead:** `adepor-q54`.

## D-024 · 2026-10-20 · Una base nueva nace solo con el esquema del v2
- **Motivo:** `inicializar_db.py` creaba tablas, columnas y semillas del v1 que ningún módulo vivo lee.
- **Regla:** una base nueva tiene `partidos_backtest`, `configuracion`, `apuestas_confirmadas` y `config_motor_valores`.
- **Semillas:** solo `umbral_ev_v2`, `fraccion_kelly_v2` y `tope_stake_v2`, con los defaults de `valor_v2.py`.
- **Fusión:** `crear_config_motor.py` se borra; su tabla, índice y trigger viven en `inicializar_db.py`.
- **Fuera de alcance:** la base de producción conserva sus tablas v1 (fase B, no aprobada).
- **Bead:** `adepor-xue`.

## D-025 · 2026-10-22 · motor_cuotas empareja eventos solo dentro de 12 horas del partido
- **Evidencia:** la corrida del 2026-10-20 emparejó Corinthians con Coritiba y Barracas Central con Rosario Central.
- **Regla:** un evento de The Odds API compite solo si su kickoff cae a 12 horas o menos de la fecha del partido.
- **Bead:** `adepor-bh4`.

## D-026 · 2026-10-22 · `prob_justa` sigue proporcional y los tiros no corrigen a Pinnacle
- **Evidencia A:** en Europa, Shin mejora la log-loss del cierre (1X2 −0.00026, IC95 [−0.00049, −0.00004]).
- **Evidencia A:** en Argentina, Brasil y Noruega, Shin no mejora (1X2 +0.00007, IC95 [−0.00024, +0.00036]).
- **Regla pre-registrada:** un método se adopta solo si pasa en los dos estratos, así que el proporcional se queda.
- **Evidencia B:** los tiros al arco no mejoran el cierre (−0.00009, IC95 [−0.00052, +0.00031]) ni el pre-cierre.
- **Hallazgo:** en Europa, el proporcional muestra sesgo favorito-underdog; el decil favorito gana 2,4 puntos más de lo predicho.
- **Pendiente:** probar Shin solo para ligas europeas, fuera de muestra, con los `pin_cierre_*` que captura el pipeline.
- **Bead:** `adepor-4kg`. Datos: `analisis/margen_y_tiros_pinnacle_eu.json` y `_latam_nor.json`.

## D-027 · 2026-10-22 · Captura forward de casas contra Pinnacle en OddsPapi
- **Regla:** la cascada guarda una vez por día el 1X2 de Pinnacle y bet365 AR en `cuotas_forward`.
- **Betano:** salió el mismo día, porque su feed en OddsPapi es Betano Rumania (`ro.betano.com`).
- **Cupo:** el plan gratis da 250 pedidos por mes y la API acepta una casa y 5 torneos por pedido: 6 pedidos por día.
- **Uso:** el estudio pre-registrado en `adepor-6kk` compara margen y EV de cada casa contra Pinnacle.
- **Bead:** `adepor-6kk`.

## D-028 · 2026-10-22 · Mezclar casas no mejora al cierre de Pinnacle
- **Evidencia:** ninguna mezcla de Pinnacle con el promedio del mercado, Bet365 o Betfair Exchange baja la log-loss fuera de muestra.
- **Evidencia:** el acierto del favorito no cambia: 54,0% contra 53,9% en Europa y 48,4% contra 48,4% en LATAM.
- **Exploratorio:** en Europa, el peso óptimo de Pinnacle sale mayor que 1, pero esa ventaja no se sostiene fuera de muestra.
- **Regla:** el v2 sigue tomando la probabilidad justa solo de Pinnacle.
- **Bead:** `adepor-u3x`. Datos: `analisis/mezcla_casas_pinnacle.json`.

## D-029 · 2026-10-23 · El xG de FotMob no mejora al cierre de Pinnacle
- **Evidencia, Europa:** el candidato con xG sale peor que Pinnacle: log-loss +0.0071, IC95 [+0.0002, +0.0140], n=656.
- **Evidencia, Argentina:** el candidato con xG no se distingue de Pinnacle: +0.0059, IC95 [−0.0109, +0.0227], n=388.
- **Control:** el candidato con goles tampoco pasa en ningún estrato.
- **Límite:** en Europa la prueba cubre media temporada, porque football-data trae el cierre de Pinnacle en unos 900 de 1.752 partidos de 2025/26.
- **Límite:** el diseño detecta efectos grandes, no chicos.
- **Regla:** el xG de FotMob no entra al modelo. La probabilidad justa sigue saliendo solo de Pinnacle.
- **Protocolo:** `analisis/fotmob_xg_vs_pinnacle_prereg.md`, fijado antes de ver resultados. Datos: `analisis/fotmob_xg_vs_pinnacle_eu.json` y `_arg.json`.

## D-030 · 2026-10-23 · Elegir divisiones por EV contra el cierre no persiste
- **Evidencia:** se eligieron 5 de 22 divisiones con 2023/24. En 2024/25 su EV medio contra el cierre fue −0.6%, IC95 [−2.5%, +1.3%], n=179.
- **Control:** las divisiones no elegidas dieron +0.1%, IC95 [−1.4%, +1.6%], n=327.
- **Regla:** no se filtran divisiones por EV histórico. El volumen sale de sumar divisiones, no de elegir las mejores.
- **Límite:** el diseño usa una temporada para elegir y una para validar. Detecta efectos grandes, no chicos.
- **Protocolo:** `docs/specs/12-producto-deploy.md`, fijado antes de correr. Datos: `analisis/seleccion_divisiones_ev.json`.
