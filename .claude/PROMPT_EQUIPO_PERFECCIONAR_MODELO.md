# PROMPT MAESTRO — Equipo de Perfeccionamiento del Modelo Adepor

## Cómo usar este prompt

Copiar y pegar en una sesión de Claude Code con `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`:

---

```
Create an agent team to improve the Adepor predictive model. Spawn 4 teammates:

TEAMMATE 1 — "investigador_xg" (agent type: investigador_xg)
OBJETIVO: Investigar mejoras a la fórmula proxy xG de motor_data.py.
TAREAS:
- Buscar coeficientes empíricos publicados para conversion rate de SoT, off-target y corners
- Investigar qué estadísticas adicionales devuelve ESPN que no estamos extrayendo
- Buscar si el peso híbrido 0.70/0.30 (stats/goles) es óptimo
- Buscar modelos de score effects con coeficientes empíricos publicados
- Investigar si FBref/Understat tienen datos que sirvan para CALIBRAR nuestro xG sin usarlo como input directo
Reportar hallazgos en formato estructurado (fuente, propuesta, test, riesgo, prioridad).

TEAMMATE 2 — "optimizador_modelo" (agent type: optimizador_modelo)
OBJETIVO: Analizar las fórmulas matemáticas de motor_calculadora.py y proponer mejoras cuantitativas.
TAREAS:
- Construir un reliability diagram (prob_modelo vs freq_real) por buckets de 5pp sobre todos los Liquidados
- Verificar si el Fix #5 (calibración bucket 40-50%) sigue siendo necesario y si hay buckets nuevos con sesgo
- Analizar si los umbrales de EV escalado (3%, 8%, 12%) siguen siendo óptimos con los datos actuales
- Verificar rendimiento de cada Camino de apuesta (1, 2, 2B, 3) por separado: n, hit%, yield%
- Verificar si el bloqueo de empates sigue justificado (modelo sobreestima empates?)
- Analizar si factor momentum y fatiga (Manifiesto II.F y II.H) están implementados y su impacto potencial
Cada propuesta debe incluir N, backtest comparativo, y código exacto del cambio.

TEAMMATE 3 — "cazador_datos" (agent type: cazador_datos)
OBJETIVO: Encontrar fuentes de datos gratuitas y automatizables que mejoren las predicciones.
TAREAS:
- Investigar FBref/StatsBomb open data: cobertura de ligas, campos disponibles, scrapeabilidad
- Investigar football-data.co.uk: qué CSVs tienen, qué columnas, cobertura sudamericana
- Investigar Understat: xG por partido para calibración, formato de datos
- Investigar si ESPN devuelve posesión u otras stats que no estamos extrayendo
- Evaluar viabilidad de datos meteorológicos (OpenWeatherMap) como feature adicional
- Evaluar TransferMarkt como proxy de calidad de plantilla
Para cada fuente: cobertura, formato, automatizabilidad, fragilidad, impacto en modelo.

TEAMMATE 4 — "critico" (agent type: critico)
OBJETIVO: Auditar las propuestas de los otros 3 agentes, detectar overfitting y vacíos lógicos.
TAREAS:
- Esperar a que los otros 3 terminen sus reportes
- Verificar independientemente cada claim cuantitativa consultando la DB
- Calcular ratio datos/parámetros para cada propuesta (mínimo 10:1)
- Identificar riesgos de overfitting, sesgo de supervivencia, data snooping
- Emitir veredicto por propuesta: APROBADO / CONDICIONAL / DIFERIDO / VETADO
- Generar un reporte final priorizado con las mejoras que pasan la auditoría
El crítico tiene poder de veto. Sus veredictos son finales.

COORDINACIÓN:
- Los teammates 1, 2 y 3 trabajan en paralelo (tareas independientes)
- El teammate 4 (crítico) espera a los otros 3 antes de emitir veredictos
- Al terminar: el lead consolida los veredictos del crítico en un PLAN DE ACCIÓN con prioridades
- Ningún cambio se aplica a código sin aprobación del crítico

ARCHIVOS CLAVE:
- motor_data.py → fórmula xG, EMA, score effects
- motor_calculadora.py → Dixon-Coles, calibración, regímenes de apuesta, sizing
- config_sistema.py → ligas, IDs, parámetros globales
- Reglas_IA.txt → Manifiesto (constitución del proyecto)
- fondo_quant.db → datos reales para backtest
- calibrar_rho.py → calibración de rho por liga
```

---

## Resultado esperado

El equipo entrega:
1. **Investigador xG**: 3-5 hallazgos con fuentes, propuestas concretas y tests
2. **Optimizador**: 3-5 propuestas con backtest cuantitativo y código exacto
3. **Cazador de datos**: tabla comparativa de 4-6 fuentes con viabilidad
4. **Crítico**: veredicto por propuesta + reporte final priorizado

El lead consolida en un PLAN DE ACCIÓN:
- Implementar ahora (aprobadas por crítico)
- Implementar en shadow (condicionales)
- Monitorear (diferidas)
- Descartar (vetadas)
