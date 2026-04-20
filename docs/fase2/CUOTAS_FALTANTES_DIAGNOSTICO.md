# CUOTAS_FALTANTES_DIAGNOSTICO — audit de cobertura de cuotas por liga

**Autor**: team-lead (directo por bloqueo de `analista-sistemas`).
**Fecha**: 2026-04-17.

---

## 1. Cobertura actual (medida)

| Liga | N total | Sin cuota 1X2 | % sin 1X2 | Sin cuota O/U 2.5 | % sin O/U |
|---|---|---|---|---|---|
| Argentina | 70 | 5 | 7% | 48 | **69%** |
| **Bolivia** | 7 | 7 | **100%** | 7 | **100%** |
| Brasil | 62 | 8 | 13% | 26 | 42% |
| Chile | 11 | 2 | 18% | 7 | 64% |
| **Colombia** | 15 | 15 | **100%** | 15 | **100%** |
| **Ecuador** | 19 | 19 | **100%** | 19 | **100%** |
| Inglaterra | 32 | 0 | 0% ✓ | 14 | 44% |
| Noruega | 32 | 0 | 0% ✓ | 22 | 69% |
| **Peru** | 17 | 17 | **100%** | 17 | **100%** |
| Turquia | 34 | 4 | 12% | 22 | 65% |
| **Uruguay** | 12 | 12 | **100%** | 12 | **100%** |
| **Venezuela** | 10 | 10 | **100%** | 10 | **100%** |

---

## 2. Patrón detectado

### Dos categorías claras:

**Categoría A — Ligas con cobertura 1X2 OK pero O/U parcial** (Argentina, Brasil, Chile, Inglaterra, Noruega, Turquía):
- 1X2: cobertura alta (0-18% missing).
- O/U 2.5: cobertura media/baja (42-69% missing).
- **Causa probable**: The-Odds-API cubre estas ligas para 1X2 pero **ofrece otras líneas O/U distintas a 2.5** (se vio en el log del pipeline: "Linea 2.5 no disponible. Lineas en mercado: [2.0]", [1.75], [2.75], [3.0]). El motor descarta cualquier línea que no sea exactamente 2.5.

**Categoría B — Ligas 100% sin cuotas** (Bolivia, Colombia, Ecuador, Perú, Uruguay, Venezuela):
- Ni 1X2 ni O/U se capturan.
- **Causa probable**: The-Odds-API NO cubre estas ligas sudamericanas secundarias, o el mapeo `MAPA_LIGAS_ODDS` en `src/comun/config_sistema.py` no tiene entrada correcta para ellas.

---

## 3. Hipótesis a validar

1. **Hipótesis 1 — Categoría B**: verificar `MAPA_LIGAS_ODDS` en `config_sistema.py` — ¿estas ligas tienen clave mapeada al slug correcto de The-Odds-API? Ej: `soccer_bolivia_liga` o similar.

2. **Hipótesis 2 — Categoría A (O/U)**: el código `motor_cuotas` descarta líneas O/U != 2.5 sin interpolar. Propuesta: aceptar líneas cercanas (ej. 2.75, 3.0) y convertir el pick a "OVER/UNDER 2.5 implícito" con correlación temporal. Esto requiere validación estadística — no es trivial.

3. **Hipótesis 3 — Categoría A (1X2)**: los pocos partidos sin 1X2 (2-8 por liga) probablemente son `[ALERTA] Sin match en mercado` por mismatch de nombres de equipo. Fix: mejorar el fuzzy match de `gestor_nombres`.

---

## 4. Recomendación concreta

**Prioridad 1 (cero riesgo)**: verificar `MAPA_LIGAS_ODDS`. Si las 6 ligas de Categoría B están mal mapeadas, el fix es una línea de config. Si están correctas pero el API no las cubre, pausar operación de apuestas en ellas hasta tener fuente alternativa.

**Prioridad 2**: investigar el mercado O/U por liga — ¿qué línea usa Argentina típicamente? Si ofrece 1.75 o 3.0, el sistema está fallando porque pide 2.5 estricto. Decidir si:
- (a) aceptar línea más cercana (+0.25) y ajustar umbral xG.
- (b) mantener el filtro estricto y pausar O/U en esas ligas.

**Prioridad 3**: fuzzy match mejorado para los ~20 partidos de Categoría A sin 1X2.
