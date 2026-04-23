# R6_AUDIT_COMPLETO — Auditoría bit-a-bit de las 3 lógicas de resolución

**Autor**: `senior` (Tech Lead Fase 3, STEP 0).
**Fecha**: 2026-04-17.
**Snapshot pre-audit**: `snapshots/fondo_quant_20260417_231232.db` (624.0 KB).
**Universo**: `Pendiente=321` (único estado — bug B1 pendiente; no afecta audit de lógica pura).

---

## 1. Las 3 lógicas identificadas

### Lógica A — canónica declarada (`src/nucleo/motor_calculadora.py:366-374`)
```python
def determinar_resultado_apuesta(apuesta, gl, gv):
    if gl is None or gv is None or not isinstance(apuesta, str) or "[APOSTAR]" not in apuesta:
        return "INDETERMINADO"
    if "LOCAL"  in apuesta:    return "GANADA" if gl  >  gv else "PERDIDA"
    if "EMPATE" in apuesta:    return "GANADA" if gl == gv else "PERDIDA"
    if "VISITA" in apuesta:    return "GANADA" if gl  <  gv else "PERDIDA"
    if "OVER 2.5"  in apuesta: return "GANADA" if (gl+gv) > 2.5 else "PERDIDA"
    if "UNDER 2.5" in apuesta: return "GANADA" if (gl+gv) < 2.5 else "PERDIDA"
    return "INDETERMINADO"
```
**Output domain**: `{"GANADA", "PERDIDA", "INDETERMINADO"}` (strings sin brackets).
**Usado por**: `detectar_drawdown` (motor_calculadora:385).

### Lógica B — persistencia DB (`src/persistencia/motor_liquidador.py:44-56`)
```python
if isinstance(ap_1x2, str) and "[APOSTAR]" in ap_1x2:
    if "LOCAL"  in ap_1x2: resultado = "[GANADA]" if gl  >  gv else "[PERDIDA]"
    elif "EMPATE" in ap_1x2: resultado = "[GANADA]" if gl == gv else "[PERDIDA]"
    elif "VISITA" in ap_1x2: resultado = "[GANADA]" if gl  <  gv else "[PERDIDA]"
    else: resultado = "[APOSTAR]"
    nuevo_ap_1x2 = ap_1x2.replace("[APOSTAR]", resultado)

if isinstance(ap_ou, str) and "[APOSTAR]" in ap_ou:
    if "OVER 2.5"  in ap_ou: resultado = "[GANADA]" if (gl+gv) > 2.5 else "[PERDIDA]"
    elif "UNDER 2.5" in ap_ou: resultado = "[GANADA]" if (gl+gv) < 2.5 else "[PERDIDA]"
    ...
```
**Output domain**: bracket tokens `[GANADA]`/`[PERDIDA]` escritos al string de la DB vía `replace("[APOSTAR]", resultado)`.
**Usado por**: liquidación final de `partidos_backtest.apuesta_1x2` y `apuesta_ou`.

### Lógica C — Excel / dashboard (`src/persistencia/motor_sincronizador.py:167-185`)
```python
def _resultado_1x2(ap_text, gl, gv):
    ap = str(ap_text or "")
    if "[GANADA]"  in ap: return  1
    if "[PERDIDA]" in ap: return -1
    if "[APOSTAR]" in ap and gl is not None and gv is not None:
        if "LOCAL"  in ap: return  1 if gl  >  gv else -1
        if "EMPATE" in ap: return  1 if gl == gv else -1
        if "VISITA" in ap: return  1 if gl  <  gv else -1
    return 0

def _resultado_ou(ap_text, gl, gv):
    ap = str(ap_text or "")
    if "[GANADA]"  in ap: return  1
    if "[PERDIDA]" in ap: return -1
    if "[APOSTAR]" in ap and gl is not None and gv is not None:
        total = gl + gv
        if "OVER"  in ap: return  1 if total > 2.5 else -1
        if "UNDER" in ap: return  1 if total < 2.5 else -1
    return 0
```
**Output domain**: enteros `{1, -1, 0}` (agregables para métricas).
**Usado por**: dashboard, hoja sombra, cálculo de agregados Excel (`motor_sincronizador:234/241/670/686/973/983`).

---

## 2. Audit bit-a-bit — 5 casos de prueba del STEP 0

| # | pick | gl | gv | Lógica A | Lógica B | Lógica C | Semántica |
|---|---|---|---|---|---|---|---|
| 1 | `[APOSTAR] LOCAL`    | 2 | 1 | `"GANADA"` (gl>gv)        | `[GANADA]` (gl>gv)   | `+1` (gl>gv)  | GANADA |
| 2 | `[APOSTAR] EMPATE`   | 1 | 1 | `"GANADA"` (gl==gv)       | `[GANADA]` (gl==gv)  | `+1` (gl==gv) | GANADA |
| 3 | `[APOSTAR] VISITA`   | 0 | 2 | `"GANADA"` (gl<gv)        | `[GANADA]` (gl<gv)   | `+1` (gl<gv)  | GANADA |
| 4 | `[APOSTAR] OVER 2.5` | 3 | 1 | `"GANADA"` (total=4>2.5)  | `[GANADA]`           | `+1` (OVER)   | GANADA |
| 5 | `[APOSTAR] UNDER 2.5`| 0 | 0 | `"GANADA"` (total=0<2.5)  | `[GANADA]`           | `+1` (UNDER)  | GANADA |

**Veredicto casos STEP 0**: las tres lógicas coinciden en la semántica de los 5 casos. Cambia la representación (string sin brackets / token con brackets / entero) pero la clasificación GANADA/PERDIDA es idéntica.

---

## 3. Casos borde adicionales

### Caso borde 1 — UNDER con total==2
- A: `(0+2) < 2.5` → `"GANADA"`.
- B: mismo operador → `[GANADA]`.
- C: `total=2 < 2.5` → `+1`.
**Equivalentes.**

### Caso borde 2 — OVER con total==2
- A: `2 > 2.5` → `"PERDIDA"`.
- B: `[PERDIDA]`.
- C: `-1`.
**Equivalentes.**

### Caso borde 3 — Strings protegidos
- A, B, C usan todas los tokens exactos `"LOCAL"`, `"EMPATE"`, `"VISITA"`, `"OVER 2.5"`, `"UNDER 2.5"` (A y B) o `"OVER"/"UNDER"` (C) como sub-string con `in`.
- **Observación C vs A/B**: C matchea `"OVER"` sin el `"2.5"`. Esto es seguro porque el pipeline sólo genera picks con el sufijo `"2.5"` — no hay otros mercados OU activos. Si en el futuro se agrega OU 1.5 / 3.5, C colisionaría (matchearia ambos). No es un bug actual pero sí deuda latente.

### Caso borde 4 — apuesta ya liquidada (string contiene `[GANADA]` o `[PERDIDA]`)
- A: rechaza porque requiere `"[APOSTAR]" in apuesta` → devuelve `"INDETERMINADO"`.
- B: mismo short-circuit → no re-liquida (`if "[APOSTAR]" in ...`).
- C: **diferente contrato** — retorna `+1`/`-1` directo leyendo el token ya escrito. Esto es intencional: C consume lo que B escribió, no re-computa.

**Esta asimetría es CORRECTA por diseño**: A y B trabajan sobre apuestas `[APOSTAR]` (pre-liquidación); C trabaja sobre apuestas ya escritas en DB/Excel (post-liquidación + idempotencia para re-dibujar dashboard sin re-ejecutar liquidador).

### Caso borde 5 — goles None con `[APOSTAR]`
- A: devuelve `"INDETERMINADO"`.
- B: liquidador filtra previamente `if gl is None or gv is None: continue` (línea 40-41). Nunca llega a la lógica.
- C: entra a la rama solo si `gl is not None and gv is not None`; sino retorna `0`.
**Comportamiento consistente**: nadie liquida con goles faltantes.

---

## 4. Veredicto

**GO para STEP 1**. Las tres lógicas son **semánticamente equivalentes** en todos los casos del pipeline actual. Las diferencias son de representación (string / token / entero) y de dominio de uso (liquidar / auditar / agregar en Excel), no de clasificación.

**NO HAY BUG HISTÓRICO**. No hay contradicción entre DB y Excel. Los tres usan los mismos operadores (`>`, `==`, `<`) y los mismos strings de matching.

---

## 5. Deuda técnica registrada (no bloquea Fase 3)

1. **C matchea `"OVER"` sin `"2.5"`** (motor_sincronizador:183-184). Funciona hoy porque sólo existe OU 2.5. Si se agregan OU 1.5/3.5, colisionará. **Fix futuro**: usar `"OVER 2.5"` / `"UNDER 2.5"` como A y B, o primero match del mercado exacto.
2. **Unificación**: las 3 lógicas viven en 3 archivos. Redundancia §5 fila 5 de `PLAN_tech_lead.md` propone extraer helper `src/comun/resultados_apuesta.py`. Esta unificación es **segura** dada la equivalencia probada acá — pero requiere wrappers (A devuelve string, B devuelve token, C devuelve int) que preserven los 3 contratos de retorno.
3. **Camino 3 (Alta Convicción)**: Reglas_IA §IV.C permite picks con `prob >= 0.33`. Las 3 lógicas lo respetan porque no miran prob, sólo el string final ya generado.

---

## 6. Strings protegidos auditados (todos intactos)

`'LOCAL'`, `'EMPATE'`, `'VISITA'`, `'OVER 2.5'`, `'UNDER 2.5'`, `'[APOSTAR]'`, `'[GANADA]'`, `'[PERDIDA]'`, `'Finalizado'`, `'Liquidado'`, `'Pendiente'`, `'Calculado'` — todos presentes y sin alteración.

---

## 7. Referencias cruzadas

- `docs/fase2/R6_AUDITORIA_3_LOGICAS.md` (predecesor): identificó las 3 lógicas pero dejó C como "pendiente de inspección directa". Este doc cierra esa pendiente.
- `docs/fase2/PLAN_tech_lead.md` §5 fila 5: propone unificación a `src/comun/resultados_apuesta.py`. Dada la equivalencia probada, se puede implementar en fase posterior sin riesgo de regresión.
- `Reglas_IA.txt` §1A: strings protegidos intactos.
