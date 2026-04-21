# Prompt para la próxima sesión

Copiar y pegar el bloque de abajo al iniciar la siguiente sesión de Claude.

---

## Bloque para pegar

```
Hola. Soy Mateo, seguimos el proyecto Adepor (motor cuantitativo de apuestas
deportivas en Python + SQLite). Cerramos la sesión anterior el 2026-04-21
con el sistema estable y sin cambios operativos urgentes.

**Estado actual del sistema:**
- 16 ligas registradas (9 sudamericanas + 7 europeas incl. Big 5 completo)
- 3 ligas en LIVE: Brasil, Argentina, Noruega (stake real)
- 13 ligas en pretest (stake=0, auto-flip cuando N≥15 + hit≥55% + p≤0.30)
- Pipeline central V8.0 con subcomandos --status/--summary/--analisis
- Motor calculadora fase 3.3.5 (Camino 4 Consenso: prob≥0.36, cuota 1.12-2.00)
- Motor sincronizador V10.0 modular (7 archivos en src/persistencia/)
- Dashboard con sección "Performance por Liga" (N/Hit/Yield/Estado)

**Antes de cualquier cambio corré:**
    py ejecutar_proyecto.py --status

Eso muestra:
- Apuestas vivas y liquidadas globales
- Pretest por liga (N, hit%, estado LIVE/pretest)
- Config actual de todos los parámetros
- Quota restante de las 3 keys de API-Football
- Antigüedad del Excel

**Lee primero este archivo para contexto:**
    docs/fase4/CIERRE_SESION_2026-04-21.md

Ahí están los commits de la última sesión, los hallazgos principales,
el bug de fuzzy matching corregido, y el threshold test de C1 Brasil
(conclusión: NO tocar C1, el sistema está en su óptimo).

**Cosas que podríamos atacar (por prioridad):**

1. Monitorear Arg/Nor recién flipeadas a LIVE. Si pierden hit, el
   auto-revert del pipeline las vuelve a pretest solo.

2. Primer check out-of-sample: una vez que pasen 2 semanas desde el
   flip (2026-05-05 aprox), los picks nuevos son data genuinamente
   out-of-sample. Correr:
      py ejecutar_proyecto.py --analisis volumen
   y comparar hit/yield real vs el simulado in-sample de hoy.

3. Esperar a que España/Italia/Alemania/Francia carguen sus ~380
   partidos/liga. Primer pick real estimado 2-3 semanas después de
   la primera corrida que las incluya.

4. Turquía está en pretest con p-valor 0.40 (umbral 0.30). Si acumula
   2-3 picks ganadores más baja el p. Auto-flipea sola.

5. Cuando alguna liga europea alcance N≥30 liquidados, recalibrar
   FACTOR_CORR_XG_OU con AVG(goles_real / xG_ema) sobre su muestra,
   y correr scripts/calibrar_rho.py para su rho específico.

**Archivos clave:**
- `ejecutar_proyecto.py` — pipeline central con subcomandos
- `src/nucleo/motor_calculadora.py` — lógica de decisión (4 Caminos)
- `src/persistencia/motor_sincronizador.py` — orquestador Excel
- `src/persistencia/excel_*.py` — módulos del dashboard
- `scripts/evaluar_pretest.py` — flip auto LIVE/pretest (paso 1.6)
- `scripts/analisis_*.py` — análisis puntuales
- `docs/fase4/CIERRE_SESION_2026-04-21.md` — contexto completo

**Filosofía de trabajo de las sesiones pasadas:**
- Nada se toca sin evidencia empírica (threshold test, backtest, etc)
- Commits atómicos con justificación técnica en el mensaje
- Snapshots de seguridad antes de cambios de DB
- "Brier no se rompe" es regla no-negociable (rompe calibración => rompe todo)
- Preferir agentes especializados (onboarder_liga, cazador_datos) cuando el scope matchea

Decime qué querés atacar hoy o si es sesión de mantenimiento
(--status + --summary para ver cómo evolucionó el sistema).
```

---

## Notas complementarias (NO pegar)

**Contexto que Claude ya conoce del MEMORY.md:**
- rho_por_liga implementado (calibrar_rho.py)
- Refactor Módulo C aprobado (Persistencia + queries_dashboard)

**Tono esperado:**
- Conversación técnica directa
- Respuestas concretas con tablas/números
- Commits pusheados al terminar cada logical unit
- Challenges conceptuales del usuario son bienvenidos (ej. "¿no es muestra demasiado grande como para decir que hay sesgo?")

**Si el sistema se rompe al correr pipeline:**
1. `--status` primero para diagnóstico
2. Los snapshots están en `snapshots/`
3. Si es un motor crítico, revertir con `git log` y `git revert <hash>`
4. Onboarder_liga agent siempre hace snapshot pre-cambio

**Temas tabú (ya descartados, no re-proponer):**
- Temperature scaling de probs (rompe yield -10pp)
- Doble Chance / Over 1.5 (margen bookie come el edge)
- Ajustes a Camino 1 (sistema está en óptimo local)
- Rotar keys expuestas en git history (decisión del usuario, no re-proponer)
