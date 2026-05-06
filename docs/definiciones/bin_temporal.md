# bin_temporal — momento del partido en su temporada

**Define:** discretización del momento temporal de un partido (bin4, bin8, bin12) usando el calendario individual de su (liga, temp).
**Código:** `src/nucleo/motor_calculadora.py:954` (`_get_momento_bin_4`).
**Tabla DB:** `liga_calendario_temp`.

---

## Definición

Para un partido `P` de liga `L` en fecha `f`:

**Paso 1 — Resolver temp del calendario:**
```
ano = int(f[:4])
candidatos: temp = ano  ó  temp = ano + 1   (cubre EUR ago-may)
seleccionar: el (L, temp) en liga_calendario_temp tal que f ∈ [fecha_inicio, fecha_fin]
```

**Paso 2 — Calcular pct dentro de la temporada:**
```
delta_partido = julianday(f) − julianday(fecha_inicio)
delta_temp    = julianday(fecha_fin) − julianday(fecha_inicio)

pct = max(0.0, min(1.0, delta_partido / delta_temp))
```

`pct ∈ [0, 1]` — fracción del torneo transcurrida al momento de `P`.

**Paso 3 — Bin discreto:**
```
bin_N(P) = min(N − 1, floor(pct · N))
```

Para:
- `N = 4` (cuartiles): `bin4 ∈ {0, 1, 2, 3}` = Q1, Q2, Q3, Q4
- `N = 8` (octavos): `bin8 ∈ {0, ..., 7}`
- `N = 12` (doceavos): `bin12 ∈ {0, ..., 11}` (≈ por mes)

---

## Tabla `liga_calendario_temp`

Schema:
```
liga          TEXT NOT NULL
temp          INTEGER NOT NULL
fecha_inicio  TEXT NOT NULL  (YYYY-MM-DD)
fecha_fin     TEXT NOT NULL  (YYYY-MM-DD)
formato       TEXT           (e.g. 'ago-may', 'feb-dic')
notas         TEXT
PRIMARY KEY (liga, temp)
```

**Calendarios típicos:**
- **EUR top (ENG/ESP/ITA/FRA/ALE):** ago-may. `temp = año cierre`. Ej Premier 25-26 → temp=2026.
- **Argentina semestral (Apertura):** feb-jun. `temp = año Apertura`.
- **Brasileirao:** abr-dic. `temp = año torneo`.
- **Noruega:** abr-nov. `temp = año torneo`.

---

## Resolución del temp ambiguo

Para EUR top con calendario ago-may, un partido en ene-may pertenece a la temp con `temp = año`. Un partido en ago-dic pertenece a `temp = año + 1`. El código intenta ambos y selecciona el que cubre la fecha:

```python
ano = int(fecha[:4])
for temp in (ano, ano + 1):
    r = lookup(liga, temp)
    if r and r.fecha_inicio <= fecha <= r.fecha_fin:
        return r
return None  # fail-safe
```

---

## Fail-safe (sin calendario)

Si `(liga, temp)` no está calibrado en `liga_calendario_temp`:
- `bin_N(P) = None`
- Filtros M.3 y similares NO bloquean (fail-safe).

---

## Pseudocódigo completo

```python
from datetime import date

def get_bin_temporal(liga, fecha, calendarios, n_bins):
    """
    calendarios: dict {(liga, temp): (fecha_inicio, fecha_fin)}
    n_bins: 4, 8, o 12
    """
    ano = int(fecha[:4])
    for temp in (ano, ano + 1):
        if (liga, temp) not in calendarios:
            continue
        inicio, fin = calendarios[(liga, temp)]
        if not (inicio <= fecha <= fin):
            continue
        d = date.fromisoformat(fecha[:10])
        di = date.fromisoformat(inicio[:10])
        df = date.fromisoformat(fin[:10])
        total_dias = (df - di).days
        if total_dias <= 0:
            return None
        pct = max(0.0, min(0.9999, (d - di).days / total_dias))
        return min(n_bins - 1, int(pct * n_bins))
    return None  # fail-safe
```

---

## Uso en filtros y análisis

- **M.3 (V5.1.2):** filtra picks con `bin4 = 3` (Q4 cierre temporada). Actualmente DESACTIVADO.
- **Análisis bin × año × liga:** detectar régimen temporal específico (ej Italia bin3 -26% IS 2026).
- **Promovido en V14 v3:** `v14_v3_bias_bin{4,8,12}_ligas` con shifts persistidos por (liga, bin).

---

## Cobertura actual

`liga_calendario_temp` cubre 16 ligas × 5 temps = 80 (`liga, temp`) entries. Argentina tiene 3 formatos paralelos (anual, apertura, clausura).

Equipos en copas internacionales (Champions, Libertadores, etc.) NO tienen calendario individual — el calendario se hereda del partido home (decisión arquitectural).

---

## Documentación relacionada

- `docs/definiciones/filtros_picks_v51.md` — uso de bin4 en M.3
- `docs/findings_audit_posicion_y_M3.md` — recalibración M.3 con calendario individual
