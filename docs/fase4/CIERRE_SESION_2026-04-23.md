# Cierre de sesión — 2026-04-22/23

Sesión larga (2 días). Foco: **capital + calibración del modelo + infraestructura live**.

---

## 📦 Commits de la sesión (en `origin/main`)

```
39572e8  chore(analisis): tools de diagnostico Brier (test comparativo + calibrar_xg)
ff27a2c  feat(live): re-armar motor_live V5.0 con 16 ligas + mensajes enriquecidos
3bda69a  feat(brier): calibracion piecewise 5pp (paso 2/6 plan Brier)
1108189  feat(brier): calibracion beta-scaling display-only (paso 1/6 plan Brier)
447681e  chore: limpieza de obsoletos + archivado docs historicos + tools brier_diag
9e5d666  fix(pipeline): --audit-names invoca auditor/auditor_espn.py con path correcto
e8e8e58  feat(incert): umbral SHADOW configurable + columna Incert % en Excel
e90e3ec  fix(bat): rutas portables con %~dp0 + ejecutar_live apunta a archivo/
dc11275  feat(excel): 'Si Hubiera' con P/L en $ y compounding sobre bankroll base
acf8789  feat(sim): hoja 'Si Hubiera' incluye mercado O/U 2.5
589ff84  feat(pretest): auto-flip O/U por liga con flag scoped
e4ba2ca  feat(excel): pestana 'Si Hubiera' con resimulacion in-sample (reglas 3.3.5)
ac2915a  feat(motor): bankroll dinamico con Kelly sobre base+P/L acumulado
35cfd20  config(db): profundidad_profunda 140 -> 210 dias
```

---

## 🎯 Cambios grandes aplicados

### 1. Bankroll dinámico (Kelly canónico)
- Base $280k (subido de $100k tras apuesta manual Boca–River del usuario).
- Clampeado a [$100k, $10M]. Corre sobre base + P/L liquidado desde `bankroll_fecha_corte=2026-04-21`.
- Función centralizada: `src/nucleo/motor_calculadora.py::obtener_bankroll_operativo(cursor)`.
- Impacta Kelly real (stakes crecen con ganancias, bajan con drawdown).
- Bug fix colateral: `importador_gold.py` migrado de DELETE+INSERT a UPSERT → preserva stakes en `--rebuild`.

### 2. Pretest O/U independiente
- Flag `apuesta_ou_live` ahora es **scoped por liga**, desacoplado de `apuestas_live` 1X2.
- `scripts/evaluar_pretest.py` extendido: evalúa ambos mercados en el paso 1.6 del pipeline.
- Umbrales separados: `pretest_ou_n_minimo=5` (vs 15 de 1X2), `pretest_ou_hit_threshold=0.55`, `pretest_ou_p_max=0.30`.
- **Turquía: única liga O/U LIVE** hoy (N=9, hit 66.7%, p=0.254).

### 3. Hoja "Si Hubiera" (Excel)
- Resimulación in-sample con reglas 3.3.5 sobre todos los liquidados.
- Cubre **1X2 + O/U**. Compounding real sobre bankroll base.
- Módulo nuevo: `src/persistencia/excel_hoja_resimulacion.py`.
- Lógica compartida entre script y Excel: `src/comun/reglas_actuales.py`.
- Números al cierre: REAL N=118 · SIM N=219 hit 63.0% yield +57.7% · P/L simulado +$3.32M.

### 4. Calibración Brier (display-only, yield intacto)
Dos capas aplicadas, motor de picks **no cambia**:
- **Beta-scaling** (`src/comun/calibracion_beta.py`): coefs a,b lineales por salida. Gain −0.009 hold-out.
- **Piecewise 5pp** (`src/comun/calibracion_piecewise.py`): mapeo bucket→freq empírica. Gain −0.023 hold-out (−3.6%). Fallback a beta si bucket N<5.
- Nueva columna `BS Calibrado` en Excel junto a `BS Sistema` (cruda) y `BS Casa`.
- Scripts: `scripts/calibrar_beta.py` y `scripts/calibrar_piecewise.py` (re-ejecutar mensualmente).

### 5. Motor Live V5.0 — Telegram enriquecido
- 16 ligas (antes 5 hardcodeadas).
- Mensaje nuevo: Liga · Partido · Fecha+hora · Pick · Cuota · Prob modelo · Prob mercado · EV% · Stake $.
- 4 modos: `--once`, `--dry-run`, `--test-msg`, loop 60s (legacy).
- Respeta pretest automáticamente (filtro `stake > 0`).
- Cache persistente en `log_alertas` (evita duplicados entre corridas).
- Legacy V4.2 sigue en `archivo/motor_live.py` como backup.

### 6. Limpieza + archivado
Borrados: `log_diario.txt`, `temp_espn_odds.json`, `Ejemplo_Stats_ESPN.txt`, `scripts/analisis_c1_brasil.py`, `scripts/resimular_liquidadas.py`.
Archivado: `docs/fase2/` completa y `docs/fase3/AUDIT_XG_FOTMOB.*` → `docs/historico/`.
Bug fixed: `ejecutar_proyecto.py:511` invocaba `auditor_espn.py` sin prefijo `auditor/`.

### 7. Columna `Incert %` + umbral SHADOW configurable
- Nueva columna `Incert %` en hoja Backtest: `min(incert/2.0, 1.0)` en formato porcentual.
- Bolivia 100% (altitud), Argentina 42%, Brasil 52%.
- Umbral SHADOW log de 0.15 (obsoleto, disparaba siempre) → 1.40 (captura ~20% superior). Configurable.

### 8. Otros parámetros actualizados
- `profundidad_profunda` 140→210 días (re-calibración profunda).
- `bankroll_techo` 1M→10M (pedido del usuario).

---

## 🧪 Tests y decisiones con evidencia

### ✅ Aprobados
- **Beta-scaling**: hold-out N=163. BS 0.610→0.601 (−0.009). Yield intacto.
- **Piecewise 5pp**: hold-out N=163. BS 0.610→0.559 (−0.051 in-sample) / −0.023 real. Yield intacto.
- **Pretest O/U**: Turquía pasa 3 criterios (N≥5, hit≥55%, p≤0.30).

### ❌ Rechazados con evidencia empírica
- **Subir C4 a 0.45**: mejora BS −0.015 pero sacrifica yield 2-6pp.
- **Winsor Poisson 15%+15%**: mejora BS pero yield −2pp (N=150→201 incluye picks marginales de baja calidad).
- **Sacar ligas nuevas del BS**: impacto solo +0.001 (22/233 filas).
- **Recalibrar gamma_1x2 por liga**: NO afecta Brier (solo cosmético).

### 🔒 Shadow permanente (3 agentes vetaron)
- **Opción B: rediseño motor xG con intercepto + coefs libres por liga**.
  - `optimizador_modelo` propuso, `investigador_xg` detectó artefactos de colinealidad, `critico` vetó.
  - Problemas: 269 partidos (no 491) con stats completas, 5/14 ligas con N≥60, 3 ligas con OLS singular.
  - Cascada de recalibración (rho, gamma, EMA, piecewise, factores O/U) es show-stopper.
  - Precedente Manifiesto: Fix A → yield −35.9pp por tocar xG.
  - Recomendación técnica: si se avanza en el futuro, **usar NNLS** (no OLS crudo) y cumplir checklist de 6 items en `memory/project_opcion_B_xg_veto.md`.

---

## 🔬 Diagnóstico Brier detallado

Pico histórico del sistema: **sem2 30/03** (BS 0.560, delta vs casa **−0.127**).
Hoy: **sem5 20/04** (BS 0.617, delta vs casa **+0.029**). **Degradación −0.156 pt.**

Causas identificadas (por magnitud):
1. Mezcla de ligas nuevas (sem2: 4 ligas → sem5: 11 ligas, varias con EMAs <10 partidos)
2. Contaminación fuzzy matching 13-20/abril (arreglada pero EMAs residuales tardan)
3. Bajada C4 prob_min 0.45→0.36 (más picks marginales con peor Brier)

Diagnósticos con código reutilizable en `scripts/analisis/brier_diag*.py`.

---

## 🏁 Estado final del sistema

```
PIPELINE:    V8.0 (orquestador con subcomandos --status/--summary/--analisis)
CALCULADORA: Fase 3.3.5 (C4 prob_min=0.36, cuota_min=1.12)
PRETEST 1X2: N≥15 + hit≥55% + p≤0.30 (con auto-revert)
PRETEST O/U: N≥5  + hit≥55% + p≤0.30 (scoped por liga, desacoplado de 1X2)
LIGAS:       16 totales (3 LIVE 1X2: Arg/Bra/Nor · 1 LIVE O/U: Turquia · 13 pretest)
BANKROLL:    $280k base · dinamico · clampeado [100k, 10M]
BRIER:       BS Sistema (crudo) + BS Calibrado (piecewise, display-only)
MOTOR LIVE:  V5.0, 4 modos, cache persistente, Telegram enriquecido
DASHBOARD:   V10.0 modular (7 archivos en src/persistencia/excel_*)
EXCEL:       5 hojas (Dashboard · Backtest · Sombra · Resumen · Si Hubiera)
SEGURIDAD:   Snapshots en snapshots/fondo_quant_20260421_150937_bankroll_change.db
```

### Comandos diarios
```bash
py ejecutar_proyecto.py              # pipeline completo
py ejecutar_proyecto.py --status     # snapshot del sistema (incluye bankroll)
py ejecutar_proyecto.py --summary    # resumen post-corrida

py motor_live.py --once              # una corrida del sniper (post-pipeline)
py motor_live.py --test-msg          # ping a Telegram

py scripts/calibrar_beta.py          # recalibrar coefs beta-scaling
py scripts/calibrar_piecewise.py     # recalibrar mapas piecewise
py scripts/analisis/test_comparativo_brier.py   # hold-out BS comparativo
```

---

## ⚠️ Pendientes / temas futuros

### Accionables en próximas sesiones
- **Monitorear Turquía O/U** (recién LIVE, 12 picks pendientes con stake=0 hasta próxima corrida motor).
- **Recalibrar Beta + Piecewise mensualmente** (cada ~30 días o cuando N+50 liquidados).
- **Ligas europeas en pretest**: esperar a que carguen fixtures (2-3 semanas más).

### Deferidas (sin urgencia)
- **Retirar shims** en root (13 archivos) — plan en `DEUDA_TECNICA.md §D8`.
- **Migrar `MOTORES_DIARIOS`** a `python -m src.X.Y`.
- **Reconsiderar Opción B** solo si N_OLS Argentina ≥200 Y N_min_liga ≥80 en ≥10 ligas (hoy 0/14).

### No recomendadas (ya descartadas con evidencia)
- ~~Temperature scaling global de probs~~
- ~~Winsor Poisson para probs~~ (rompe yield −2pp)
- ~~Subir C4 prob_min a 0.45~~ (mejora Brier pero sacrifica yield 3-6pp)
- ~~Doble Chance / Over 1.5~~ (margen bookie)
- ~~Ajustes a xG del motor~~ (vetado en shadow, ver `memory/project_opcion_B_xg_veto.md`)
- ~~Rotar keys expuestas~~ (decisión del usuario)

---

**Sesión cerrada.** Sistema más robusto (bankroll dinámico, calibración Brier, O/U independiente, motor live enriquecido). Foco próximo: observar Turquía O/U y Arg/Nor LIVE 1X2 acumulando hit real out-of-sample.
