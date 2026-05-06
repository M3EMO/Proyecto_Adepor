# Filtros de picks V5.1 (M.1, M.2, M.3)

**Define:** los 3 filtros de la sección §M del manifiesto V5.1.
**Código:** `src/nucleo/motor_calculadora.py:208-231` (`_FILTRO_PICKS_V51`).
**Manifiesto:** Reglas_IA.txt §M (V5.1.2).

---

## M.1 — Whitelist por liga

**Definición:**
```
apostar_solo_si_liga_in : Set[liga]
default productivo: {"Argentina", "Brasil", "Inglaterra", "Noruega", "Turquía"}
```

**Aplicación:** si `liga(pick) ∉ apostar_solo_si_liga_in` → SKIP.

**Origen empírico:** ligas seleccionadas tienen yield positivo histórico (V4.x backtest). Las excluidas (Italia, España, Francia, Alemania, LATAM no-top) sangran yield contra cuotas.

**Estado:** ✓ ACTIVO en producción.

---

## M.2 — Madurez EMA local

**Definición:**
```
n_acum_max = 60
apostar_solo_si n_acum_l < n_acum_max
```

`n_acum_l` = número de partidos previos del equipo local en `historial_equipos_stats` (madurez de la EMA).

**Aplicación:** si `n_acum_l ≥ 60` → SKIP.

**Origen empírico:** equipos con EMA muy madura (>60 partidos) tienen yield negativo sistemático (`docs/findings_n_acum_drift.md`). EMAs frescas (n < 60) capturan mejor cambios de plantel.

**Fail-safe:** si `n_acum_l = None` (cobertura faltante), NO bloquea el pick.

**Estado:** ✓ ACTIVO en producción.

---

## M.3 — Cierre temporada (Q4)

**Definición:**
```
excluir_q4 : bool
default productivo: false  (DESACTIVADO en V5.1.2)

apostar_solo_si momento_bin_4 != 3   (cuando excluir_q4 = true)
```

`momento_bin_4 ∈ {0, 1, 2, 3}` = cuartil temporal del partido en su temporada (ver `docs/definiciones/bin_temporal.md`).

**Aplicación cuando ACTIVO:** si `momento_bin_4 = 3` (último cuartil temporada) → SKIP.

**Origen empírico:** OOS 2024 N=160 mostró Q4 yield −16.1% sig. PERO in-sample 2026 mostró Q4 +50-70% en Inglaterra/Turquía. Régimen distinto → desactivado.

**Fail-safe:** si `momento_bin_4 = None`, NO bloquea.

**Re-activación condicional planeada (`adepor-09s` Fase 2):**
- Si `yield_rolling(liga) < umbral_2σ` → activar M.3 esa liga.
- Si régimen detectado como "tipo 2023" → activar selectivamente.

**Estado:** ✗ DESACTIVADO en producción (V5.1.2).

---

## Tabla de configuración

| Filtro | Estado | Parámetro | Default |
|---|---|---|---|
| M.1 | ✓ ACTIVO | `filtro_picks_v51.apostar_solo_si_liga_in` | {ARG, BRA, ENG, NOR, TUR} |
| M.2 | ✓ ACTIVO | `filtro_picks_v51.n_acum_max` | 60 |
| M.3 | ✗ DESACTIVADO | `filtro_picks_v51.excluir_q4` | false |

Persistencia: `config_motor_valores.filtro_picks_v51` (JSON tipo).

---

## Pseudocódigo

```python
import json

def cargar_filtro_picks_v51():
    raw = get_param("filtro_picks_v51", scope="global")
    if not raw: return None
    cfg = json.loads(raw)
    return {
        "apostar_solo_si_liga_in": set(cfg.get("apostar_solo_si_liga_in", [])),
        "n_acum_max": cfg.get("n_acum_max", 60),
        "excluir_q4": cfg.get("excluir_q4", False),
    }

def filtro_pick_v51(liga, n_acum_l, momento_bin_4, cfg):
    # M.1
    if liga not in cfg["apostar_solo_si_liga_in"]:
        return False, "M.1 (liga)"
    # M.2 (fail-safe: si None, NO bloquea)
    if n_acum_l is not None and n_acum_l >= cfg["n_acum_max"]:
        return False, "M.2 (n_acum)"
    # M.3 (fail-safe: si None o desactivado, NO bloquea)
    if cfg["excluir_q4"] and momento_bin_4 is not None and momento_bin_4 == 3:
        return False, "M.3 (q4)"
    return True, "OK"
```

---

## Documentación relacionada

- `docs/findings_n_acum_drift.md` — investigación M.2
- `docs/findings_audit_posicion_y_M3.md` — recalibración M.3 con calendario fix
- `docs/definiciones/bin_temporal.md` — definición `momento_bin_4`
