# EMA forward-strict — especificación

**Define:** EMA exponencial con ventana FORWARD-STRICT (no leakage del partido t en su propia predicción).
**Uso:** alimentación de Poisson DC + Skellam + V12 LR. Métrica RMSE forward-EMA.

---

## Definición matemática

Dado un equipo `e` y una secuencia cronológica de partidos `P_1, P_2, ..., P_T` del equipo:

**Estado inicial:**
```
EMA_e(0) = None
n_e(0)   = 0
```

**Para cada partido `P_t` (t = 1, 2, ..., T) en orden cronológico:**

```
# 1. CAPTURAR estado PRE-partido (predicción para P_t)
prediccion_e(t) = EMA_e(t−1)
n_pre_e(t)      = n_e(t−1)

# 2. UPDATE estado POST-partido
xg_final_e(t) = ... (función del partido P_t — ver motor_v0_xg.md)

if EMA_e(t−1) is None:
    EMA_e(t) = xg_final_e(t)              # cold start
else:
    EMA_e(t) = α · xg_final_e(t) + (1−α) · EMA_e(t−1)

n_e(t) = n_e(t−1) + 1
```

**Crítico:** `prediccion_e(t)` se captura ANTES del update. Garantiza que `P_t` NO contribuye a su propia predicción (forward-strict).

---

## Parámetros

| Parámetro | Valor productivo | Scope | Tabla DB |
|---|---|---|---|
| `α` (alfa) | 0.10-0.20 (per liga) / 0.15 (default) | per liga | `config_motor_valores.alfa_ema` |
| `WARMUP` | 5 partidos | global | constante en código |

---

## Filtro WARMUP

Predicciones con `n_pre_e(t) < WARMUP = 5` se descartan (EMA fría tiene varianza alta y sesgo cold-start).

---

## Pseudocódigo

```python
from collections import defaultdict

WARMUP = 5

def construir_ema_forward(partidos_ordenados, alfa_per_liga):
    """
    partidos_ordenados: list ordenada por fecha ascendente.
    Cada partido genera 2 eventos (local + visita).
    """
    state = defaultdict(lambda: {"ema": None, "n": 0})
    predicciones = []  # forward-strict

    for p in partidos_ordenados:
        for equipo, xg_final, fecha, liga, target in eventos_del_partido(p):
            alfa = alfa_per_liga.get(liga, 0.15)
            s = state[equipo]

            # 1. CAPTURAR (predicción)
            if s["ema"] is not None and s["n"] >= WARMUP:
                predicciones.append({
                    "equipo": equipo, "fecha": fecha, "liga": liga,
                    "prediccion": s["ema"],
                    "n_pre": s["n"],
                    "target": target,
                })

            # 2. UPDATE
            if s["ema"] is None:
                s["ema"] = xg_final
            else:
                s["ema"] = alfa * xg_final + (1 - alfa) * s["ema"]
            s["n"] += 1

    return predicciones
```

---

## Variantes en producción

| Tabla DB | Qué EMA es | Update on |
|---|---|---|
| `historial_equipos.ema_xg_favor` | EMA de `xg_final` ofensivo | cada partido del equipo |
| `historial_equipos.ema_xg_contra` | EMA de `xg_final` del rival (defensa) | cada partido del equipo |
| `historial_equipos_v6_shadow.ema_xg_v6_*` | EMA con xg recalibrado V6 | SHADOW paralelo |
| `historial_equipos_stats.ema_l_*`, `ema_c_*` | EMAs por feature (sots, shot_pct, pos, etc.) | cada partido del equipo |

---

## Edge cases

- **Cold start (n < WARMUP):** EMA todavía inestable, no usar para predicción. Filtro WARMUP=5 obligatorio.
- **Cambio de temporada:** se recomienda NO resetear EMA cross-temp (EMA cubre tendencia atemporal).
- **Cambio de liga (equipo asciende/desciende):** EMA se mantiene pero la liga cambia → calibración rho/gamma se aplica con liga nueva.
- **Equipo nuevo en universo:** primer partido = cold start, predicción del segundo en adelante.

---

## Documentación relacionada

- `docs/definiciones/rmse_forward_ema.md` — métrica de validación que usa esta EMA
- `docs/definiciones/motor_v0_xg.md` — input del update (xg_final)
- `src/ingesta/motor_data.py:296` — implementación productiva
