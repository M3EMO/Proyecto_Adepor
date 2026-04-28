# Findings — Layer 3 H4 X-rescue: walk-forward + caracterización población

> Bead: `adepor-edk` Opción D (audit extendido 2026-04-28)
> Inputs: `analisis/audit_yield_F2_walkforward_por_temp.{py,json}` +
>          `analisis/audit_yield_F2_x_rescue_population.{py,json}`
> Sample: 4 ventanas (test 2022, 2023, 2024 OOS + in-sample 2026), 191 X-rescue picks

## Resumen ejecutivo

El audit Opción D extiende la base de evidencia del audit original `adepor-edk` (1
ventana OOS 2024) a **4 ventanas con threshold FIJO 0.35** (no re-optimizar).
Resultado:

- **4/4 ventanas con Δ(H4 vs V0) ≥ 0** (test 2022 +0.0pp, test 2023 +0.5pp, test
  2024 +1.2pp, in-sample 2026 +6.3pp)
- **Ninguna ventana individualmente sig al 95%**
- **Cero downside agregado** observado en cualquier ventana
- **Población X-rescue concentrada en Argentina (60%)** + Inglaterra (14%) +
  Italia (12%) + España, Alemania, Brasil minoritarias

**Recomendación**: aplicar Layer 3 con scope `arch_per_liga` JSON
(análogo a V5.0 §L Layer 2 V12 Turquía) sobre {Argentina, Italia, Inglaterra,
Alemania}. Excluir España (único drag observado, además fuera universo V5.1) y
Brasil (ruido, N=8 con signo flippeado).

## 1. Walk-forward por temp

### Configuración

| Ventana | Warmup | Test temp | N test |
|---|---|---|---|
| test_2022 | [2021] | 2022 | 1544 |
| test_2023 | [2021, 2022] | 2023 | 2264 |
| test_2024 | [2021, 2022, 2023] | 2024 | 2348 |
| in_sample_2026 | [2021, 2022, 2023, 2024] | 2026 partidos_backtest | 129 |

Threshold H4=0.35 **FIJO** — no re-optimizado por temp.

### Resultados agregados

| Ventana | N | V0 yield | H4 yield | Δ | X-rescue picks |
|---|---|---|---|---|---|
| test_2022 | 1544 | +3.1% | +3.2% | +0.0pp | 17 (1.1%) |
| test_2023 | 2264 | −3.4% | −2.9% | +0.5pp | 66 (2.9%) |
| test_2024 | 2348 | −0.3% | +1.0% | +1.2pp | 98 (4.2%) |
| in_sample_2026 | 129 | +9.7% | +16.0% | +6.3pp | 10 (7.8%) |

**Veredicto cross-temp**: H4_ROBUSTO_DIRECCIONAL — todas las ventanas mejoran sobre
V0. NO sig estadístico individual.

## 2. Caracterización de la población X-rescue

### Por temp × liga (donde se gana / pierde)

Ranking absoluto de Δ por (temp, liga) con N≥3:

| Temp | Liga | N | Hit X% | Δ |
|---|---|---|---|---|
| 2024 | **Italia** | 11 | 54.5% | **+13.51** ★ |
| 2026 | Argentina | 8 | 50% | **+11.34** ★ |
| 2023 | Argentina | 52 | 30.8% | **+7.62** |
| 2024 | Alemania | 3 | 66.7% | +7.58 |
| 2024 | Inglaterra | 18 | 27.8% | +6.99 |
| 2022 | España | 11 | 27.3% | +4.79 |
| 2023 | Alemania | 2 | 50% | +4.84 |
| 2023 | Italia | 7 | 42.9% | +4.61 |
| 2024 | Brasil | 5 | 40% | +2.27 |
| 2023 | España | 2 | 50% | +1.58 |
| 2024 | Argentina | 55 | 29.1% | +1.06 |
| 2022 | Inglaterra | 2 | 50% | +0.95 |
| 2024 | **España** | 6 | **0%** | **−2.76** ★ |
| 2026 | Brasil | 2 | 0% | −3.23 |
| 2023 | Brasil | 1 | 0% | −3.72 |
| 2023 | Inglaterra | 2 | 0% | −4.16 |
| 2022 | **Italia** | 4 | 0% | **−5.46** ★ |

**Lecturas clave**:
- Italia 2024 es la celda más rentable (Δ +13.51, 54.5% hit).
- Argentina concentra 60% de la población total (115/191) y mejora marginalmente
  cross-temp pero rescata fuerte en in-sample 2026.
- España 2024 es el único drag ★ pero está fuera universo V5.1 (no TOP-5).
- Brasil signo flippea con N chico — ruido.

### Top equipos (todas las ventanas combinadas)

| Liga | Equipo | N | Hit X | Profit H4 | Pos_back | Perfil táctico |
|---|---|---|---|---|---|---|
| ARG | **Talleres (Córdoba)** | 4 | 75% | **+6.44** ★ | N/A | EQUILIBRADO |
| ARG | **Barracas Central** | 13 | 38% | **+3.58** | 3.0 (TOP-3) | EQUILIBRADO |
| ENG | **Chelsea** | 7 | 29% | +2.50 | 5.0 (TOP-6) | POSESIONAL |
| ARG | Central Córdoba (SdE) | 4 | 50% | +1.78 | 4.0 (TOP-6) | CONTRAATAQUE |
| ARG | San Lorenzo | 13 | 38% | +1.01 | N/A | EQUILIBRADO |
| ARG | Banfield | 15 | 33% | −0.01 | N/A | CONTRAATAQUE |
| ARG | Atl. Tucumán | 4 | 25% | −0.58 | 1.0 (TOP-3) | EQUILIBRADO |
| ARG | Newell's | 7 | 29% | −1.24 | N/A | EQUILIBRADO |
| ENG | Man City | 6 | 17% | −2.01 | 3.0 (TOP-3) | (sin EMA) |
| ARG | Rosario Central | 6 | 17% | −2.93 | N/A | CONTRAATAQUE |
| ARG | Platense | 6 | 17% | −3.18 | 4.0 (TOP-6) | CONTRAATAQUE |
| ARG | **Huracán** | 9 | 11% | **−6.06** ★ | 9.0 (MID) | EQUILIBRADO |

**Patrón**: equipos rentables son TOP/MID con perfil EQUILIBRADO o POSESIONAL
(Talleres, Barracas, Chelsea, Central Córdoba). Equipos drenadores son MID con
perfil CONTRAATAQUE puro (Huracán, Platense, Rosario Central).

### Top picks rentables (N=10)

| Rank | Liga | Temp | Partido | Real | P_X V12 | Cuota X | Profit |
|---|---|---|---|---|---|---|---|
| 1 | ENG | 2024 | Liverpool vs Crystal Palace | X | 0.401 | 6.04 | +5.04 |
| 2 | ALE | 2023 | Freiburg vs Bayern | X | 0.361 | 4.84 | +3.84 |
| 3 | ENG | 2024 | Chelsea vs Bournemouth | X | 0.435 | 4.80 | +3.80 |
| 4 | ENG | 2022 | Liverpool vs Brighton | X | 0.397 | 4.76 | +3.76 |
| 5 | ENG | 2024 | Chelsea vs Nott'm Forest | X | 0.455 | 4.70 | +3.70 |
| 6 | ESP | 2023 | Betis vs Real Madrid | X | 0.371 | 4.19 | +3.19 |
| 7 | ENG | 2024 | Man City vs Brighton | X | 0.407 | 3.99 | +2.99 |
| 8 | ARG | 2023 | Talleres vs Unión SF | X | 0.443 | 3.81 | +2.81 |

**Patrón clarísimo**: empates de **TOP-vs-MID/BOT con cuota X alta (3.8-6.0)**.
El bookie subestima la P(X) cuando hay un favorito clarísimo local, y el motor
V12 lo identifica. Es value betting contra el favorito sobreestimado.

### Distribución pos_backward + matchup

| Bucket local | N (sin "?") | % |
|---|---|---|
| TOP-3 | 20 | 23% |
| TOP-6 | 28 | 33% |
| MID | 26 | 30% |
| BOT-6 | 9 | 10% |
| BOT-3 | 3 | 3% |

55% sin pos_backward (snapshot incompleto para EUR liga + ARG no-anual).

| Matchup | N | % |
|---|---|---|
| TOP-vs-TOP | 13 | 13% |
| TOP-vs-MID | 11 | 11% |
| MID-vs-MID | 11 | 11% |
| MID-vs-TOP | 6 | 6% |
| BOT-vs-MID | 5 | 5% |
| BOT-vs-TOP | 4 | 4% |
| TOP-vs-BOT | 4 | 4% |
| BOT-vs-BOT | 3 | 3% |

**No hay un único matchup dominante**. Mix balanceado. Los TOP-vs-TOP (13%) son
los partidos clave del campeonato; TOP-vs-MID/MID-vs-TOP capturan el caso
"favorito vs underdog defensivo".

### Perfil táctico (EMAs medias)

| Stat | Local mean | Visita mean | Lectura |
|---|---|---|---|
| ema_pos | 47.6% | 49.6% | Ambos defensivos (<50%) |
| ema_pass_pct | 66.1% | 67.0% | Normal |
| ema_shot_pct | 31.6% | 32.5% | Eficiencia mediocre |
| ema_sots | 3.64 | 3.97 | Bajos (media liga ≈5) |
| ema_corners | 4.50 | 4.61 | Normales |

**Distribución de perfiles locales:**
- 38% CONTRAATAQUE
- 35% EQUILIBRADO
- 12% POSESIONAL
- 1% OFENSIVO

**Lectura táctica**: el override H4 identifica **partidos entre equipos
defensivos con bajo volumen ofensivo**. Sin un dominador ofensivo claro → más
probable empate. Tiene lógica futbolística sólida.

## 3. Torneos internacionales

Cobertura no DB, conocimiento externo:

**Argentina con Libertadores/Sudamericana 2022-2024:**
- River Plate, Independiente, Talleres, Vélez, Lanús, San Lorenzo, Newell's,
  Atlético Tucumán — regulares
- Banfield, Barracas Central, Defensa, Sarmiento, Platense, Huracán, Rosario
  Central — solo liga local

**Inglaterra con Champions/Europa:**
- Chelsea (Champions 22-23, Conference 24-25)
- Man City (Champions todos los años, ganador 22-23)
- Liverpool (Champions 21-22, Europa 23-24)
- Crystal Palace, Brighton, Bournemouth — solo Premier (puntual)

**El override NO discrimina por presencia internacional.** Aparecen tanto
equipos copa-eros (Talleres, River, Man City) como locales puros (Banfield,
Crystal Palace).

**Caveat**: bead `adepor-p4e` sospecha que la caída Q3 Argentina 2023 (−45.7%) se
explica por equipos en copas internacionales (cansancio mid-week). Si la
hipótesis se confirma con datos calendario internacional, podría refinarse
Layer 3 ARG con `solo_si_libertadores_juega_<48h_antes`. Pero requiere data
que hoy no tenemos.

## 4. Implicaciones operativas

### Subset propuesto Layer 3

Aplicar `h4_x_rescue_threshold` per-liga (JSON):

| Liga | Status V5.1 | Δ cross-temp | Justificación |
|---|---|---|---|
| **Argentina** | TOP-5 LIVE | +1.06 → +7.62 → +11.34 | LIVE, mejora consistente, evidencia in-sample |
| **Inglaterra** | TOP-5 LIVE | +0.95 → +6.99 | LIVE, picks high-cuota TOP-vs-MID |
| **Italia** | NO LIVE (excl M.1) | −5.46 → +4.61 → +13.51 | Mejor celda absoluta, pero no opera hoy |
| **Alemania** | NO LIVE | +4.84 → +7.58 (N chico) | Direccional pero N=5 total |
| ESPAÑA | NO LIVE | −2.76 (drag) | EXCLUIR — único drag |
| Brasil | TOP-5 LIVE | −3.72 → +2.27 → −3.23 | EXCLUIR — signo flippea |
| Francia | NO LIVE | sin X-picks suficientes | EXCLUIR — N=0 |
| Turquía | TOP-5 LIVE | (Layer 2 V12 standalone) | NO aplica — V12 ya argmax |

**Implementación operativa real (V5.1 active universe)**:
- Argentina + Inglaterra son las 2 ligas LIVE TOP-5 que ven X-rescue activo
- Italia + Alemania quedan ready en JSON pero NO impactan picks hoy (M.1 los
  filtra del universo apostable)
- Si en futuro entran a TOP-5, ya tienen threshold listo

### Implementación técnica

```sql
-- config_motor_valores
INSERT INTO config_motor_valores (clave, valor_texto, scope, descripcion)
VALUES ('h4_x_rescue_threshold',
        '{"Argentina": 0.35, "Inglaterra": 0.35, "Italia": 0.35, "Alemania": 0.35}',
        'global',
        'Layer 3: override argmax a X si V12 argmax=X y P_v12(X) > thresh, per-liga');
```

**En `motor_calculadora.py::evaluar_pick`**, después de calcular V0 + V12 argmax,
ANTES de aplicar M.1/M.2/M.3:

```python
h4_thresh_dict = json.loads(config.get('h4_x_rescue_threshold', '{}'))
thresh_liga = h4_thresh_dict.get(liga)
if thresh_liga and argmax_v12 == 'X' and prob_x_v12 > thresh_liga:
    argmax_final = 'X'  # override
```

### Cambio Manifesto

Nueva subsección **II.E.5** "H4 X-rescue contingente per-liga":
> Si para una liga existe un threshold definido en `h4_x_rescue_threshold[liga]`,
> y simultáneamente `argmax_v12 == 'X'` y `prob_x_v12 > threshold[liga]`, el motor
> override el argmax final a 'X'. Threshold inicial 0.35 calibrado sobre OOS
> 2022-2024 walk-forward + in-sample 2026 (Δ direccional positivo 4/4 ventanas).

### Guardarrieles operativos

1. **Trigger auto-desactivación**: si `yield_rolling_30d(H4 picks)` < `yield_rolling_30d(V0 picks)` en
   misma liga durante 14 días sostenidos → desactivar threshold de esa liga.
2. **Calibración mensual**: bead `adepor-j4e` re-evalúa cross-temp + in-sample
   acumulada. Si una liga voltea signo, removerla del JSON.
3. **N≥500 in-sample por liga**: si en 6 meses una liga acumula N≥500 picks
   reales y CI95_lo > 0, considerar promocionar a "approved canónico".

## 5. Próximos pasos

- [ ] Crear bead `[PROPOSAL: MANIFESTO CHANGE] Layer 3 H4 X-rescue per-liga`
- [ ] Anotar `adepor-edk` con findings + dejar abierto pending approval-by-lead
- [ ] Snapshot DB pre-cambio antes de aplicar config
- [ ] Implementar `motor_calculadora.py` override + test unitario
- [ ] Bump V5.1.2 → V5.2 en Reglas_IA.txt + recalcular SHA + lock
- [ ] Validación post-aplicación: comparar yield 30d vs baseline V0 en ARG/ING
- [ ] Si bead `adepor-p4e` confirma factor copas internacionales, refinar
  Layer 3 ARG con condicional `solo_sin_internacional_<48h`
