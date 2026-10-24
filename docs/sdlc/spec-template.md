# Spec: <nombre de la feature>

Fuente de la estructura: spec-kit `templates/spec-template.md` (MIT), recortada a lo que un gate puede verificar.
Cada requisito lleva un ID `R<n>` unico. El gate `trazabilidad` cruza esos IDs con `plan.md` y con los tests.

## Contrato

Cada archivo, clase y metodo con firma y tipos exactos. Paths exactos.

## Requisitos

Uno por linea. Comportamiento observable, no implementacion. Sin marcadores pendientes.

- R1: <regla de comportamiento con su orden de evaluacion>
- R2: <...>

## Casos borde

- R<n>: <caso limite que el requisito cubre (recarga fraccionaria, cap, vacio, key nueva, tiempo negativo)>

## Criterios de exito

Medibles y verificables por un test, sin juicio.

- R<n>: <entrada exacta -> salida exacta>

## Trazabilidad

Tabla obligatoria. Cada `R<n>` cita al menos un test de aceptacion por su nombre exacto (`def test_...`).
Un test puede cubrir varios IDs. Un ID sin test es un fallo del gate.

| ID | tests |
|---|---|
| R1 | test_<nombre> |
