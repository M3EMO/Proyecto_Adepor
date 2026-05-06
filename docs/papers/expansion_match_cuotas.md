# Expansión Match Stats↔Cuotas (fdco) — 2026-05-02

## Objetivo

Cerrar gap de cobertura match entre stats_partido_espn (13,430 filas) y cuotas_historicas_fdco
para Argentina (55% → 100%), Brasil (71% → 100%), Turquía (97% → ~100%). Pre-fix: 7,990
matched (59.5%). Target: ~8,920 matched.

## Resultado

| Liga | Antes | Después | Delta partidos | Estado |
|---|---|---|---|---|
| Alemania | 927/927 (100%) | 927/927 (100%) | 0 | ya perfecto |
| Argentina | 670/1,217 (55.0%) | **1,217/1,217 (100.0%)** | +547 | OK |
| Brasil | 855/1,209 (70.7%) | **1,209/1,209 (100.0%)** | +354 | OK |
| España | 1,155/1,155 (100%) | 1,155/1,155 (100%) | 0 | ya perfecto |
| Francia | 1,002/1,002 (100%) | 1,002/1,002 (100%) | 0 | ya perfecto |
| Inglaterra | 1,169/1,169 (100%) | 1,169/1,169 (100%) | 0 | ya perfecto |
| Italia | 1,148/1,148 (100%) | 1,148/1,148 (100%) | 0 | ya perfecto |
| Turquía | 1,065/1,094 (97.3%) | 1,065/1,094 (97.3%) | 0 | techo natural fdco |
| **Total ligas con fdco** | **7,990** | **8,892** | **+902** | |
| LATAM-no-fdco (8 ligas) | 0 | 0 | 0 | sin cobertura fdco |
| **Global** | 7,990/13,430 (59.5%) | **8,892/13,430 (66.2%)** | **+902** | |

## Causas raíz identificadas

### 1) Mappings ESPN→fdco_norm faltantes (ARG/BRA)

El script previo solo mapeaba variantes con paréntesis, perdiendo nombres acentuados sin
paréntesis (Lanús, Huracán, Atlético Tucumán, Vélez Sarsfield) y nombres únicos (Godoy
Cruz Antonio Tomba, Red Bull Bragantino, Vasco da Gama, Vitória).

### 2) Timezone shift LATAM (descubrimiento crítico)

ESPN almacena fechas en UTC; fdco usa hora local Argentina/Brasil (UTC-3). Esto produce
desfase de ±1 día sistemático en partidos nocturnos LATAM. EUR sin shift (ESPN y fdco
ambas misma TZ local efectiva).

Ejemplo verificado:
- ESPN 2022-06-11 River vs Atlético Tucumán → fdco 2022-06-12 riverplate vs atl.tucuman
- ESPN 2022-06-25 River vs Lanús → fdco 2022-06-26 riverplate vs lanus

### 3) ESPN INSERT-path inconsistencia capitalización (ARG 2026)

Scrapers ESPN 2026 introdujeron variantes lowercase parciales: Gimnasia la Plata (vs
"La Plata"), Belgrano (cordoba), Talleres (córdoba), Sarmiento (junin), Estudiantes de
la Plata, Unión (santa Fe), Huracan (sin acento). Mappings extendidos.

## Mappings nuevos agregados

### Argentina (+22 entries)


### Brasil (+4 entries)


### Turquía (0 entries — gap es de datos en fdco, no mapping)

## Cambio estructural: nueva columna 

Agregada columna  a . Resolución:

1. EUR/TUR:  (exact match).
2. LATAM (ARG, BRA): exact match prioritario; fallback ventana ±1 día.

JOINs downstream deben usar  en lugar de .

## Techo natural identificado: TUR 29 partidos

Hatayspor + Gaziantep FK 2023-03 a 2023-06: 28 filas existen en fdco con 
(post-terremoto Hatay, 2023-02-06; matches reubicados o pospuestos no recibieron actualización
de odds en football-data.co.uk). 1 partido adicional sin row en fdco. Total 29.

NO es bug de mapping. Es limitación de la fuente fdco para esa ventana específica.

## Limitación residual: ligas LATAM sin cobertura fdco

8 ligas sin cobertura fdco (Bolivia, Chile, Colombia, Ecuador, Noruega, Perú, Uruguay,
Venezuela) → 4,538 partidos ESPN sin posibilidad de match. football-data.co.uk no cubre
estas ligas. Fuente alternativa requerida (BetExplorer scraping + odds-api Pinnacle si
hay liquidez).

## Reproducibilidad

Match-rate post-fix v2 todas ligas (fecha_fdco):
liga             stats   matched    pct
Alemania           927       927 100.0%
Argentina         1217      1217 100.0%
Bolivia            572         0   0.0%
Brasil            1209      1209 100.0%
Chile              739         0   0.0%
Colombia           616         0   0.0%
Ecuador            386         0   0.0%
Espana            1155      1155 100.0%
Francia           1002      1002 100.0%
Inglaterra        1169      1169 100.0%
Italia            1148      1148 100.0%
Noruega            750         0   0.0%
Peru               517         0   0.0%
Turquia           1094      1065  97.3%
Uruguay            379         0   0.0%
Venezuela          550         0   0.0%
GLOBAL: 8892/13430 = 66.2%

Idempotente: resetea cols , ,  y reaplica desde
cero. Snapshot pre-cambio: .
