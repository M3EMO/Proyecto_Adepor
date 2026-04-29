# Papers: Entity Resolution / Name Disambiguation en datos deportivos

> **Fecha:** 2026-04-28
> **Workflow:** WebSearch + WebFetch (Semantic Scholar API rate-limited).
> **Decisión a fundamentar:** Audit profundo del diccionario_equipos.json para
> dictaminar mappings sospechosos.
> **Process gate:** decisión usuario 2026-04-28 — toda investigación de problemas
> requiere fundamentación académica.

---

## Q1: Entity resolution / record linkage state of the art

### Hallazgos consolidados

**Frameworks principales** ([Stoerts et al., PMC11636688 — review 2024](https://pmc.ncbi.nlm.nih.gov/articles/PMC11636688/)):

1. **Deterministic/Rule-Based**: string distance (Levenshtein, Jaro-Winkler).
   - Computacionalmente eficiente.
   - **EMPÍRICAMENTE INFERIOR** a probabilistic en datos ruidosos.
   - Es lo que hace `gestor_nombres.obtener_nombre_estandar` actualmente (FASE 3 fuzzy).

2. **Probabilistic Record Linkage (Fellegi-Sunter, 1969)**:
   - Computa likelihood ratios match-vs-no-match.
   - Estima distribuciones m(γ) y u(γ) sin training data.
   - **Permite frequency weighting**: nombres raros pesan más.

3. **Bayesian Extensions + Clustering**:
   - Enforca transitive closure (`a→b ∧ b→c ⇒ a→c`).
   - Cuantifica incertidumbre.

### Best practices fundamentadas

| Práctica | Detalle | Estado en Adepor |
|---|---|---|
| **Blocking** | Solo comparar records en mismo bloque (liga/contexto). | ✓ Hecho via `_resolver_ligas_contexto` |
| **Normalization** | Lowercase + sin acentos + sin no-alfa. | ✓ Hecho via `limpiar_texto` |
| **Frequency weighting** | Nombres raros pesan más. | ✗ Faltante (Levenshtein plano) |
| **Auxiliary attributes** | País, fecha, liga adicional. | ✓ Parcial (`_meta.equipo_a_liga_home`) |
| **Transitive closure** | `a≡b, b≡c ⇒ a≡c`. | ✗ Faltante |
| **Manual review queue** | Borderline cases → review humano. | ✓ Hecho (FASE 4 modo_interactivo) |
| **Hierarchical context** | Country→League→Club. | ✓ Hecho via _meta + safety cross-country |

### Caso específico sports betting

[Beat the Bookie blog 2023](https://beatthebookie.blog/2023/04/18/matching-team-names-in-sports-betting-data-a-fuzzy-matching-approach/):
- Approach: fuzzywuzzy (Levenshtein), threshold 90%.
- Reconoce explícitamente: **NO discute false positives**, recomienda manual checking.
- Ofrece servicio comercial proprietario para casos complejos.

→ La industria reconoce limitaciones del fuzzy puro. Manual review es estandar.

### Implicación para Adepor

`gestor_nombres` actual:
- Levenshtein puro (FASE 3) sin frequency weighting.
- Auto-persiste matches fuzzy → envenenamiento progresivo (descubierto en bug-critico).
- Patches aplicados 2026-04-28: AUTO_LEARN_CUTOFF=0.95, safety cross-country, bloqueo fallback global.

**Próximas mejoras fundamentadas:**
1. Implementar **Jaro-Winkler** además de Levenshtein (mejor para typos al inicio del string,
   común en nombres deportivos: "FK Qarabag" vs "Qarabag", "AC Milan" vs "Milan").
2. **Frequency weighting**: pre-computar IDF de tokens en el corpus de equipos. Dar peso
   alto a tokens distintivos ("Qarabag", "Atletico", "Bayer") y bajo a comunes
   ("FC", "Club", "Athletic", "Real").
3. **Transitive closure verification**: si A se mapea a B y existe match a C, validar
   que B≡C; rechazar el mapping si no.

[REF: Stoerts et al. 2024 — "Almost all of entity resolution"]

### Fuentes

- [PMC11636688 — Stoerts et al. (2024) "Almost all of entity resolution"](https://pmc.ncbi.nlm.nih.gov/articles/PMC11636688/)
- [Wikipedia: Record Linkage](https://en.wikipedia.org/wiki/Record_linkage)
- [Wikipedia: Entity Linking](https://en.wikipedia.org/wiki/Entity_linking)
- [Beat the Bookie — Matching Team Names in Sports Betting Data (2023)](https://beatthebookie.blog/2023/04/18/matching-team-names-in-sports-betting-data-a-fuzzy-matching-approach/)
- [Microsoft Tech Community — Fuzzy Matching for Real-World Data (2024)](https://techcommunity.microsoft.com/blog/educatordeveloperblog/what%E2%80%99s-in-a-name-fuzzy-matching-for-real-world-data/4462152)
- [Babel Street — Fuzzy Name Matching Techniques](https://www.babelstreet.com/blog/fuzzy-name-matching-techniques)

---

## Q2: Heurísticas para audit manual de mappings

### Patrones sintácticos para club football

Basado en literatura + dominio:

1. **Sufijos / prefijos comunes que NO son discriminantes**:
   - `FC`, `AFC`, `AC`, `CF`, `CD`, `SC`, `BK`, `FK`, `KS`, `IK`, `OFI`
   - `Club`, `Athletic`, `Atletico`, `United`, `City`, `Real`, `Sporting`
   - **Implicación**: si dos nombres difieren SOLO en uno de estos prefijos, son alias del mismo equipo.
   - Ej OK: "Bournemouth" = "AFC Bournemouth", "Inter" = "Internazionale" (Italia)
   - Ej NO: "Manchester United" ≠ "Manchester City" (cambia sufijo de identidad: United/City)

2. **Discriminadores fuertes**:
   - Nombres de ciudad/región distintos (Manchester, Madrid, Barcelona, etc.) → DISTINTOS clubes.
   - Sufijos con país/estado (Botafogo SP vs Botafogo) → potencialmente distintos.
   - Apellido de fundador o patron (Bayer Leverkusen vs Bayer Leverkusen) → mismo.

3. **Casos especiales históricos confirmados**:
   - **Independiente** (Argentina) ≠ **Independiente del Valle** (Ecuador) ≠ **Independiente Medellín** (Colombia).
     Tres clubes distintos del mundo hispanohablante.
   - **Universidad Católica** (Chile, Quito, Paraguay) → tres clubes distintos.
   - **Atlético** prefijo: Atlético Madrid ≠ Atlético Mineiro ≠ Atlético Tucumán ≠ Atlético Nacional ≠ Atlético-MG ≠ Atlético-PR.
   - **Botafogo**: Botafogo (RJ) ≠ Botafogo SP (São Paulo) ≠ Botafogo PB (Paraíba).
   - **Rangers** (Escocia, Glasgow Rangers) ≠ **Angers** (Francia, SCO Angers) — falso match fuzzy clásico.
   - **Hatayspor** ≠ **Antalyaspor** (clubes turcos, ambos con sufijo `-spor`).

### Reglas de decisión propuestas para audit Adepor

Para cada mapping `alias → oficial` en el diccionario:

| Regla | Decisión |
|---|---|
| Mismo país + diferencia es prefijo/sufijo común (FC/AFC/Club/CF) | KEEP |
| Mismo país + diferencia es región (Cordoba/SP/PB) y nombre base coincide | INVESTIGATE — pueden ser distintos clubes mismo nombre |
| Mismo país + diferencia es alias conocido (Inter/Internazionale, Athletic/Athletic Club) | KEEP |
| Cross-country sin meta.equipo_a_liga_home consistente | DELETE (envenenamiento clásico) |
| Mismo país + nombres claramente distintos (Tucuman/Huracan) | DELETE (falso fuzzy) |

[REF: docs/papers/entity_resolution_sports.md Q1 — manual review queue best practice]

---

## Conclusión y plan operativo

### Decisión 1: Refactor gestor_nombres.py mediano plazo

Implementar:
- **Jaro-Winkler** como segundo similarity además de Levenshtein
- **Token IDF weighting** (frequency-aware)
- **Transitive closure check** antes de persistir match

Bead nuevo: `[F3 sub-X] Refactor gestor_nombres con Jaro-Winkler + token IDF + transitive closure`

### Decisión 2: Audit manual con reglas heurísticas

Aplicar las reglas de Q2 a los 25 sospechosos medios + 292 clusters detectados.
Generar dictamen por mapping. Aplicar solo los DELETE seguros + dejar INVESTIGATE
en review queue persistente para sesión futura.

[REF: docs/papers/entity_resolution_sports.md Q2 — heurísticas dominio fútbol]
