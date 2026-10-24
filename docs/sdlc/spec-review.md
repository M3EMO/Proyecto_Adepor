# Revision de spec (derivada de spec-kit `templates/commands/clarify.md`, MIT)

Objetivo: detectar ambiguedad o decisiones faltantes en `docs/sdlc/spec.md` y dejar las respuestas
escritas dentro de la spec. Tope: 5 preguntas. Sin humano en la corrida: la respuesta sale de la TAREA
y de los tests de aceptacion; si no sale de ahi, se escribe como supuesto explicito.

## Barrido de cobertura

Para cada categoria marcar Claro / Parcial / Falta. Preguntar solo por lo Parcial o Falta que cambie el codigo.

- Alcance funcional: objetivos, criterios de exito, fuera de alcance explicito.
- Modelo de datos: entidades, atributos, identidad, ciclo de vida, estado.
- Casos borde y fallos: escenarios negativos, limites, conflictos, valores fuera de rango.
- Restricciones: lenguaje, dependencias, tiempo, determinismo.
- Terminologia: un nombre por concepto; sin sinonimos.
- Señales de completitud: cada requisito `R<n>` es testeable por nombre.

## Reglas

1. Maximo 5 preguntas, ordenadas por impacto en el codigo.
2. Cada pregunta se responde en la misma pasada, con la TAREA o los tests como fuente.
3. Si la fuente no responde, la respuesta es un supuesto marcado `SUPUESTO:`.
4. No tocar `tests_accept/`. No borrar nada de la spec. No agregar requisitos nuevos sin ID.
5. Si un requisito cambia por una respuesta, se edita en su lugar y conserva su ID.

## Salida obligatoria (la verifica un gate)

Agregar al final de `docs/sdlc/spec.md` una seccion exacta:

```
## Clarificaciones

- P1: <pregunta> | R: <respuesta o SUPUESTO: ...> | afecta: R<n>
```

Con 0 preguntas, la seccion lleva una sola linea: `- sin preguntas: la spec cubre el barrido.`
