# DB_FIX_ESTADO — diagnóstico y fix del bug del campo `estado`

**Autor**: team-lead (Lead produjo este doc directo por bloqueo de `analista-datos`).
**Fecha**: 2026-04-17.

---

## 1. Evidencia empírica del bug

```sql
SELECT estado, COUNT(*) FROM partidos_backtest GROUP BY estado;
-- Resultado: Pendiente: 321  (único estado presente)

SELECT estado, COUNT(*) FROM partidos_backtest
WHERE goles_l IS NOT NULL AND goles_v IS NOT NULL GROUP BY estado;
-- Resultado: Pendiente: 201 (deberían estar en 'Liquidado' o 'Finalizado')
```

Cruzando con la categoría de apuesta (bracket token):

| goles | cat apuesta | count | estado REAL esperado |
|---|---|---|---|
| sí | GANADA | 22 | Liquidado |
| sí | PERDIDA | 28 | Liquidado |
| sí | PASAR | 128 | Liquidado (nada que resolver) |
| sí | APOSTAR | 23 | Finalizado (pendiente de liquidar por motor_liquidador) |
| no | APOSTAR | 28 | Calculado |
| no | PASAR | 92 | Calculado |

**Total con goles**: 201. De los cuales **178 ya están resueltos** (GANADA/PERDIDA/PASAR) y **23 están en `[APOSTAR]` esperando que el liquidador los marque**.

---

## 2. Causa raíz

El flujo correcto es: `Pendiente → Calculado → Finalizado → Liquidado`.

Dos puntos de falla identificados:

### 2A. `motor_backtest.py:107` marca 'Finalizado' cuando carga goles (OK)
```python
UPDATE partidos_backtest
SET goles_l = ?, goles_v = ?, estado = 'Finalizado'
WHERE id_partido = ?
```
Esto es correcto según el flujo.

### 2B. `motor_liquidador.py:59` marca 'Liquidado' cuando liquida la apuesta (OK)
```python
updates_a_realizar.append((nuevo_ap_1x2, nuevo_ap_ou, 'Liquidado', id_partido))
```
Tambien correcto.

### 2C. **`desbloquear_matriz.py:23` hace RESET a 'Pendiente'** (CULPABLE)
```python
cursor.execute("UPDATE partidos_backtest SET estado = 'Pendiente'")
```
**Sin filtro WHERE**. Pone TODOS los partidos en 'Pendiente', borrando el progreso del pipeline. Este es el script utilitario que alguien corrió en algún momento y dejó la DB en estado inconsistente.

**Hipótesis**: `desbloquear_matriz.py` se corrió (intencional o accidental) después de que motor_backtest y motor_liquidador hicieron su trabajo. Resultado: 201 partidos con goles, cero con estado correcto.

---

## 3. Query canónico de fix (retroactivo)

```sql
-- Paso 1: snapshot obligatorio
-- (ejecutar `py adepor_guard.py snapshot` antes)

-- Paso 2: pasar los que están liquidados (GANADA/PERDIDA/PASAR con goles) a 'Liquidado'
UPDATE partidos_backtest
SET estado = 'Liquidado'
WHERE goles_l IS NOT NULL
  AND goles_v IS NOT NULL
  AND (apuesta_1x2 LIKE '[GANADA]%'
    OR apuesta_1x2 LIKE '[PERDIDA]%'
    OR apuesta_1x2 LIKE '[PASAR]%');
-- Filas afectadas esperadas: 178

-- Paso 3: pasar los que tienen goles pero apuesta [APOSTAR] (pendiente) a 'Finalizado'
UPDATE partidos_backtest
SET estado = 'Finalizado'
WHERE goles_l IS NOT NULL
  AND goles_v IS NOT NULL
  AND apuesta_1x2 LIKE '[APOSTAR]%'
  AND estado = 'Pendiente';
-- Filas afectadas esperadas: 23

-- Paso 4: pasar los sin goles con apuesta calculada a 'Calculado'
UPDATE partidos_backtest
SET estado = 'Calculado'
WHERE goles_l IS NULL
  AND apuesta_1x2 IS NOT NULL
  AND estado = 'Pendiente';
-- Filas afectadas esperadas: 120 (28 APOSTAR + 92 PASAR)

-- Paso 5: verificar
SELECT estado, COUNT(*) FROM partidos_backtest GROUP BY estado;
-- Esperado: Calculado=120, Finalizado=23, Liquidado=178, Pendiente=0
```

---

## 4. Fix preventivo (código)

### 4A. `desbloquear_matriz.py` debe agregar confirmación manual obligatoria

Actualmente hace UPDATE sin filtro ni protección. Propuesta: agregar prompt `input("Escribir RESET para confirmar: ")` antes del UPDATE.

### 4B. NO modificar motor_backtest ni motor_liquidador

Ambos tienen la lógica correcta de transición de estado. El bug es que `desbloquear_matriz` lo revierte. Los motores del pipeline producen el estado correcto cuando se ejecutan sin interferencia.

---

## 5. Prerequisito para implementación

- Snapshot previo con `adepor_guard.py snapshot`.
- Verificar manualmente que los 23 [APOSTAR] con goles no son apuestas del futuro cercano que todavía no se jugaron (no debería, porque tienen goles).
