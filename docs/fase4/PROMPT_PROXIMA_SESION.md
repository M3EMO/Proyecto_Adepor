# Prompt para la próxima sesión

Copiar y pegar el bloque de abajo al iniciar la siguiente sesión de Claude.

---

## Bloque para pegar

```
Hola. Soy Mateo, seguimos el proyecto Adepor (motor cuantitativo de apuestas
deportivas en Python + SQLite). Cerramos la sesión anterior el 2026-04-23
con el sistema estable y varias mejoras grandes deployadas.

**Estado actual del sistema:**
- 16 ligas registradas (9 sudamericanas + 7 europeas incl. Big 5 completo)
- 3 ligas LIVE 1X2: Brasil, Argentina, Noruega
- 1 liga LIVE O/U: Turquía (pretest O/U desacoplado del 1X2)
- 12 ligas en pretest
- Pipeline V8.0 con subcomandos --status/--summary/--analisis
- Calculadora fase 3.3.5 (C4 prob_min=0.36, cuota 1.12–2.00)
- Bankroll dinámico: base $280k, clampeado [100k, 10M]
- Brier Score CALIBRADO (display-only, yield intacto): piecewise + beta fallback
- Motor Live V5.0 con Telegram (16 ligas, mensajes enriquecidos)
- Excel con 5 hojas: Dashboard · Backtest · Sombra · Resumen · Si Hubiera

**Antes de cualquier cambio corré:**
    py ejecutar_proyecto.py --status

Eso muestra:
- Apuestas vivas y liquidadas globales
- Pretest por liga (N, hit%, estado LIVE/pretest)
- Config actual de parámetros
- Bankroll operativo (base · modo · P/L acumulado · piso/techo)
- Quota restante de las 3 keys de API-Football
- Antigüedad del Excel

**Lee primero este archivo para contexto:**
    docs/fase4/CIERRE_SESION_2026-04-23.md

Ahí están los commits de la última sesión, los 6 cambios grandes
(bankroll dinámico, pretest O/U, hoja Si Hubiera, calibración Brier,
motor live V5.0, limpieza), y los temas cerrados con evidencia.

**Cosas que podríamos atacar (por prioridad):**

1. **Monitorear Turquía O/U** recién flipeada a LIVE (N=9, hit 66.7%).
   Los 12 picks O/U vivos hoy están con stake=0; se lanzan con stake>0
   en la próxima corrida del motor. Watch hit real out-of-sample.

2. **Observar Arg/Bra/Nor LIVE 1X2**: si hit cae <55% con N≥15, el
   pipeline auto-revierte a pretest (script evaluar_pretest.py).

3. **Recalibrar Beta-scaling y Piecewise** cada ~30 días o cuando
   acumule +50 liquidados:
      py scripts/calibrar_beta.py
      py scripts/calibrar_piecewise.py
   Re-guardan coefs en config_motor_valores (scope=global).

4. **España/Italia/Alemania/Francia**: esperar a que carguen fixtures
   (primer pick real estimado 1-2 semanas más).

5. **Retirar shims en root** (13 archivos) — plan documentado en
   DEUDA_TECNICA.md §D8.

**Archivos clave:**
- `ejecutar_proyecto.py` — pipeline central
- `src/nucleo/motor_calculadora.py` — lógica de decisión (Caminos C1-C4 + OU)
- `src/nucleo/motor_calculadora.py::obtener_bankroll_operativo()` — Kelly dinámico
- `src/persistencia/motor_sincronizador.py` — orquestador Excel
- `src/persistencia/excel_hoja_*.py` — módulos del dashboard (5 hojas)
- `src/comun/reglas_actuales.py` — lógica 1X2 + O/U de 3.3.5 (shared)
- `src/comun/calibracion_piecewise.py` — calibración Brier display
- `src/comun/calibracion_beta.py` — fallback beta-scaling
- `scripts/evaluar_pretest.py` — auto-flip 1X2 + O/U (paso 1.6 pipeline)
- `scripts/calibrar_beta.py` / `calibrar_piecewise.py` — recalibrar mensual
- `scripts/analisis/test_comparativo_brier.py` — hold-out BS
- `scripts/analisis/brier_diag*.py` — diagnóstico Brier profundo
- `motor_live.py` — sniper Telegram V5.0 (en root)
- `docs/fase4/CIERRE_SESION_2026-04-23.md` — contexto completo

**Filosofía de trabajo (reglas no-negociables):**
- Nada se toca sin evidencia empírica (backtest, hold-out, test comparativo)
- Commits atómicos con justificación técnica en el mensaje
- Snapshots de seguridad antes de cambios de DB
- "Yield no se rompe" es regla: cambios al motor requieren validación de yield, no solo Brier
- "Brier no se rompe" tampoco (rompe calibración => rompe todo)
- Preferir agentes especializados (onboarder_liga, cazador_datos, optimizador_modelo,
  investigador_xg, critico) cuando el scope matchea
- Display-only > motor: calibraciones que tocan display NO requieren re-calibrar rho/gamma/EMA;
  cambios al motor sí → cascada de recalibración

**Decime qué querés atacar hoy o si es sesión de mantenimiento
(--status + --summary para ver cómo evolucionó el sistema).**
```

---

## Notas complementarias (NO pegar)

**Contexto que Claude ya conoce del MEMORY.md:**
- rho_por_liga implementado
- Refactor Módulo C aprobado
- Bankroll dinámico implementado
- Pretest O/U independiente
- Opción B xG vetada (shadow permanente)

**Tono esperado:**
- Conversación técnica directa
- Respuestas concretas con tablas/números
- Commits pusheados al terminar cada logical unit
- Challenges conceptuales del usuario son bienvenidos

**Si el sistema se rompe al correr pipeline:**
1. `--status` primero para diagnóstico
2. Snapshots en `snapshots/`
3. Si motor crítico falla, revertir con `git log` y `git revert <hash>`
4. `onboarder_liga` hace snapshot pre-cambio automáticamente

**Comandos operativos rápidos:**
```bash
# Corrida diaria
py ejecutar_proyecto.py

# Sniper Telegram (post-pipeline)
py motor_live.py --once

# Status + bankroll
py ejecutar_proyecto.py --status

# Test BS hold-out
py scripts/analisis/test_comparativo_brier.py

# Recalibración Brier mensual (sugerido)
py scripts/calibrar_beta.py
py scripts/calibrar_piecewise.py
```

**Temas tabú (ya descartados con evidencia, no re-proponer):**
- ~~Temperature scaling global~~ (rompe yield)
- ~~Winsor Poisson~~ (mejora BS pero yield -2pp)
- ~~Subir C4 a 0.45~~ (yield -3 a -6pp)
- ~~Rediseñar motor xG con OLS crudo~~ (vetado por 3 agentes, ver project_opcion_B_xg_veto.md)
- ~~Ajustes a Camino 1~~ (sistema en óptimo local empírico)
- ~~Doble Chance / Over 1.5~~ (margen bookie come el edge)
- ~~Rotar keys expuestas~~ (decisión del usuario)

**Si se quiere AVANZAR con Opción B xG en el futuro:**
- Usar NNLS (scipy.optimize.nnls), no OLS crudo
- Cumplir checklist de 6 items en `memory/project_opcion_B_xg_veto.md`
- Condición mínima: N_OLS Argentina ≥200 Y N_min_liga ≥80 en ≥10 ligas (hoy 0/14)
