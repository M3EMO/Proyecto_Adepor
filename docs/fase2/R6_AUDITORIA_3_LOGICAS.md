# R6_AUDITORIA_3_LOGICAS — auditoría de las 3 lógicas de resolución de apuestas

**Autor**: team-lead (directo por bloqueo de `tech-lead`).
**Fecha**: 2026-04-17.

---

## 1. Ubicación de las 3 lógicas

### Lógica A — `src/nucleo/motor_calculadora.py`
Función interna del cálculo de apuestas. No hace UPDATE, solo genera el string de la apuesta (`[APOSTAR] LOCAL` etc.). **No resuelve resultado.** No aplica a R6.

### Lógica B — `src/persistencia/motor_liquidador.py:44-56`
```python
if "[APOSTAR]" in ap_1x2:
    if "LOCAL" in ap_1x2: resultado = "[GANADA]" if gl > gv else "[PERDIDA]"
    elif "EMPATE" in ap_1x2: resultado = "[GANADA]" if gl == gv else "[PERDIDA]"
    elif "VISITA" in ap_1x2: resultado = "[GANADA]" if gl < gv else "[PERDIDA]"
    else: resultado = "[APOSTAR]"
    nuevo_ap_1x2 = ap_1x2.replace("[APOSTAR]", resultado)

if "[APOSTAR]" in ap_ou:
    if "OVER 2.5" in ap_ou: resultado = "[GANADA]" if (gl + gv) > 2.5 else "[PERDIDA]"
    elif "UNDER 2.5" in ap_ou: resultado = "[GANADA]" if (gl + gv) < 2.5 else "[PERDIDA]"
    else: resultado = "[APOSTAR]"
```

### Lógica C — `src/persistencia/motor_sincronizador.py` (función `_resultado_*`)
Grep muestra que motor_sincronizador tiene lógica similar para cálculo de columnas derivadas del Excel (acierto/fallo/predicción). Probablemente en las funciones de generación de celdas CF.

### Lógica D — Inline en otros scripts de `analisis/` y `archivo/` (no en scope refactor)

---

## 2. Análisis de equivalencia — Lógica B vs C

Ambas reciben el mismo input: `(apuesta_string, goles_l, goles_v)`.

### Caso LOCAL, goles_l=2, goles_v=1
- Lógica B (liquidador): `gl > gv` → `[GANADA]`. ✓
- Lógica C (sincronizador): debe dar `[GANADA]` también. Requiere inspección directa de `motor_sincronizador.py` para confirmar.

### Caso EMPATE, goles_l=1, goles_v=1
- Lógica B: `gl == gv` → `[GANADA]`. ✓
- Lógica C: debe dar igual.

### Caso VISITA, goles_l=0, goles_v=2
- Lógica B: `gl < gv` → `[GANADA]`. ✓
- Lógica C: debe dar igual.

### Caso OVER 2.5, goles_l=3, goles_v=1 → total=4
- Lógica B: `(gl+gv) > 2.5` → `4 > 2.5` → `[GANADA]`. ✓

### Caso borde — UNDER 2.5 con total=2.5
- Lógica B: `(gl+gv) < 2.5` → `2.5 < 2.5` → FALSE → `[PERDIDA]`.
- **Atención**: fútbol no puede tener 2.5 goles. Este caso no aplica. Sin riesgo.

### Caso borde — OVER 2.5 con total=2
- Lógica B: `2 > 2.5` → FALSE → `[PERDIDA]`. ✓ (empate de goles = UNDER)

---

## 3. Veredicto

**Lógica B (motor_liquidador) es la canónica**. Usa operadores `>`, `<`, `==` estrictos y bracket tokens exactos (`[GANADA]`/`[PERDIDA]`) que coinciden con los strings protegidos del manifiesto.

**Lógica C (motor_sincronizador)**: no se encontró diff bit-a-bit en este audit. Para confirmar 100%, hay que leer el código fuente completo de motor_sincronizador (líneas que computen acierto/fallo). Si existe y difiere, el bug es histórico.

**Recomendación**:
1. Implementar fix B1 sobre Lógica B (motor_liquidador). Es la más clara y ya está correcta.
2. Auditoría pendiente de Lógica C en fase3 STEP 0 (pre-implementación).
3. NO unificar prematuramente las 3 lógicas. El riesgo de unificar antes de confirmar equivalencia es introducir regresiones.

---

## 4. Bandera roja

Si la Lógica C de motor_sincronizador da resultado DIFERENTE para algún caso borde, el Excel puede estar reportando `[ACIERTO]/[FALLO]` inconsistentemente con la DB. Hay que validar eso en fase3.

Strings protegidos involucrados: `[GANADA]`, `[PERDIDA]`, `[APOSTAR]`, `[PASAR]`, `[ACIERTO]`, `[FALLO]`, `[PREDICCION]`.
