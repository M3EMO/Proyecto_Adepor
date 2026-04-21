# Cierre de sesión — 2026-04-21

Sesión operativa de onboarding europeo + refinamiento de filtros.

---

## 📦 Commits de la sesión (en `origin/main`)

```
dfd88d9  analisis: threshold test C1 Brasil (A/B/C + 4 combinaciones)
fc2b567  fix: revertir 4 alias fuzzy incorrectos + subir AUTO_LEARN_CUTOFF 0.80->0.92
74d6848  feat(dashboard): seccion PERFORMANCE POR LIGA + script resimular_liquidadas
86022a6  feat(ligas): completar Big 5 europeo (Italia/Alemania/Francia) + paleta 16 colores
d96b787  feat(ligas): onboarding Espana/LaLiga como piloto europeo
```

---

## 🎯 Cambios en el sistema

### Ligas
- **Big 5 europeo completo**: Inglaterra + España + Italia + Alemania + Francia
- **16 ligas totales** (9 sudamericanas + 7 europeas)
- Paleta de 16 colores en el Backtest (tonos bandera/pastel diferenciados)

### Pretest / LIVE
- **LIVE**: Brasil, Argentina (flip manual), Noruega (flip manual)
- **Pretest**: Turquía, Inglaterra, Chile, España, Italia, Alemania, Francia, 6 sudamericanas restantes
- Config: `N≥15 + hit≥55% + p-valor binomial ≤ 0.30`
- Auto-revert en pipeline diario si hit cae <55% con N≥15

### Dashboard mejorado
- Nueva sección **"PERFORMANCE POR LIGA"** con N / Hit% / Yield / Apostado / Estado LIVE-pretest
- Semáforo de colores verde/amarillo/rojo sobre hit 55/45
- Estado LIVE verde vs pretest amarillo

### Parámetros Big 5 europeo
| Liga | ALFA | DIV | FACTOR_CORR | Perfil |
|------|------|-----|-------------|--------|
| España | 0.12 | 0.10 | 0.627 | EPL-like (eficiente) |
| Italia | 0.12 | 0.10 | 0.627 | EPL-like (defensiva) |
| Alemania | 0.13 | 0.10 | 0.627 | Ofensiva, varianza alta |
| Francia | 0.14 | 0.12 | 0.627 | Dispersión PSG, tolerancia + |

---

## 🚨 Bug grave detectado y corregido

**Fuzzy matching cross-liga con AUTO_LEARN_CUTOFF=0.80** estaba creando aliases falsos durante el onboarding Big 5:

```
"barcelona"     (FC Barcelona ESP)   -> "Barcelona SC" (Ecuador)  ❌
"juventus"      (Juventus Italia)    -> "Juventud" (Brasil)       ❌
"lens"          (RC Lens Francia)    -> "Leones" (Ecuador)        ❌
"internazionale"(Inter Milan Italia) -> "Internacional" (Brasil)  ❌
```

**Evidencia del daño:** 4 equipos sudamericanos con EMAs contaminados (xG absurdamente altos 2.4-3.1).

**Fix aplicado:**
1. Diccionario: 4 aliases corregidos
2. `AUTO_LEARN_CUTOFF`: 0.80 → 0.92 (solo acepta nombres casi idénticos)
3. DB: 4 filas contaminadas eliminadas de `historial_equipos` (se recrean fresh)

---

## 🔬 Análisis hechos (sin aplicar cambios)

### 1. Resimulación in-sample de criterios actuales
- **Baseline real:** N=83 picks, hit 57.8%
- **Con criterios 3.3.5 retroactivos:** N=189 (+128%), hit 62.4%, yield +60.9%
- 5 de 6 ligas cumplirían criterio pretest (solo Chile quedaría fuera)
- **⚠️ Look-ahead bias**: útil como visibilidad, no justifica flipear manual. Lo hicimos igual con Arg/Nor asumiendo riesgo controlado (red de seguridad auto-revierte).

### 2. Threshold test C1 Brasil (3 opciones + 4 combos)
C1 en Brasil tiene 38% hit en 21 picks. Se probaron:
- A) FLOOR_C1 = 0.50
- B) EV_C1 = 0.05
- C) CUOTA_C1 entre 1.50 y 3.00

**Hallazgo contraintuitivo:** el C1 Brasil, aunque con hit bajo, tiene yield +79% (cuotas medio-altas compensan). Ninguna opción mejora el sistema global:
- Cualquier restricción a C1 corta picks rentables en Argentina (73%), Noruega (69%), Turquía (64%)
- Global yield cae 3-6pp en TODAS las opciones

**Conclusión: NO aplicar cambios a C1.** El sistema actual está en un óptimo local empírico.

---

## 📊 Diagnóstico por Camino

```
Liga         C1           C2         C2B        C3         C4          TOTAL
Argentina    8/11 73%     7/15 47%   2/3 67%    1/1 100%   18/20 90%   36/50 72%
Brasil       8/21 38%⚠⚠   0/2 0%     5/5 100%   4/4 100%   12/17 71%   29/49 59%
Chile        1/2 50%      0/2 0%     0/2 0%     -          1/3 33%     2/9 22%
Inglaterra   2/6 33%      1/2 50%    3/5 60%    -          8/11 73%    14/24 58%
Noruega      9/13 69%     -          2/3 67%    0/1 0%     6/7 86%     17/24 71%
Turquia      9/14 64%     -          1/3 33%    -          7/12 58%    17/29 59%

Resumen: C4 es MVP consistente (~76% global), C2B funciona (62% global),
         C1 varía por liga (Brasil es outlier).
```

---

## ⚠️ Tareas pendientes / ideas futuras

### Accionables
- **Monitorear Arg/Nor en LIVE**: si en 2 semanas caen <55% hit, el pretest auto-revierte
- **Turquía**: esperar 3-5 partidos nuevos para bajar p-valor (hoy 0.40, umbral 0.30)
- **España/Italia/Alemania/Francia**: primeros ~380 partidos/liga deben cargar durante las próximas 1-2 corridas; primer pick real estimado en 2-3 semanas

### Deferidas
- **Recalibrar FACTOR_CORR_XG_OU por liga europea** cuando N≥30 liquidados por liga
- **Correr `calibrar_rho.py`** para ligas europeas cuando N≥30
- **BetExplorer (Capa B)**: pendiente si quota API-Football se agota (hoy 200+ req/día = suficiente)

### No recomendadas (ya descartadas con evidencia)
- ~~Temperature scaling de probs~~ → rompe yield -10pp
- ~~Ajustar C1~~ → el óptimo actual ya es el mejor
- ~~Doble Chance / Over 1.5~~ → margen del bookie come el edge
- ~~Rotar keys expuestas en git history~~ (decisión del usuario)

---

## 🏁 Estado final del sistema

```
PIPELINE:    V8.0 (orquestador con subcomandos --status/--summary/--analisis)
CALCULADORA: Fase 3.3.5 (C4 prob_min=0.36, cuota_min=1.12)
PRETEST:     N≥15 + hit≥55% + p≤0.30 (con auto-revert)
LIGAS:       16 totales (3 LIVE, 13 pretest)
COBERTURA:   The Odds API + API-Football (multi-key)
SEGURIDAD:   Snapshots en snapshots/fondo_quant_20260421_*.db
DASHBOARD:   V10.0 modular (7 archivos en src/persistencia/excel_*)
```

### Comandos diarios
```bash
# Pipeline completo
py ejecutar_proyecto.py

# Info rápida
py ejecutar_proyecto.py --status       # Snapshot del sistema
py ejecutar_proyecto.py --summary      # Resumen post-corrida

# Análisis puntuales
py ejecutar_proyecto.py --analisis volumen
py ejecutar_proyecto.py --analisis pretest
```

---

**Sesión cerrada.** Sistema estable, sin cambios operativos urgentes. Esperar datos out-of-sample para re-evaluar en 1-2 semanas.
