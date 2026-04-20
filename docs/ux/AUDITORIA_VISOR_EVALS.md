# AUDITORIA VISOR EVALS — adepor_eval_review.html (referencia visual)

> Autor: T2 disenador-ux | Fecha: 2026-04-16 (renombrado 2026-04-17 por decision del Lead)
>
> **PROPOSITO ACTUAL**: este documento sirve como **referencia visual heredable** para el `dashboard_operativo.html` (artefacto futuro). No se va a aplicar al visor — el visor queda intacto. Lo conservamos porque demuestra patrones que el dashboard operativo nuevo deberia heredar:
>
> - Paleta sobria (cremas, negro, naranja accent).
> - Tipografia dual Poppins (UI) + Lora (cuerpo).
> - Color-coding semantico consistente (verde/rojo/azul/ambar).
> - Tabs limpios para separar vistas (analogo a Outputs/Benchmark).
> - Atajos de teclado.
> - Colapsables (`<details>`/`<summary>`).
>
> Las fricciones del visor (F1-F12) se documentan abajo como **anti-patrones a evitar** en el dashboard operativo nuevo.
>
> **NO toca este archivo el refactor** — PLAN.md Seccion 2 (correccion 2026-04-17) lo deja explicito.
>
> Mockups del dashboard operativo nuevo: [MOCKUPS.md](MOCKUPS.md).
> Spec completa del dashboard operativo: [SPEC_DASHBOARD_OPERATIVO.md](SPEC_DASHBOARD_OPERATIVO.md).

---

## 0. CONTEXTO DEL ARTEFACTO

`adepor_eval_review.html` (1325 LOC) es un visor estatico de evaluaciones del skill `adepor`. Renderiza:

- **Outputs panel**: prompt + outputs (texto/imagen/pdf/xlsx/binary) + grades formales + feedback editable.
- **Benchmark panel**: tabla resumen with_skill vs without_skill (pass_rate, time_seconds, tokens) + breakdown por eval + assertions matrix + notas.
- **Navegacion**: tabs (Outputs/Benchmark), prev/next, Submit All Reviews, atajos de teclado.

Se sirve como pagina unica con `EMBEDDED_DATA` inyectado por `generate_review.py`. Tres modos de despliegue: con servidor local (POST `/api/feedback`), estatico (descarga JSON), keyboard-only.

---

## 1. INVENTARIO DE BLOQUES VISUALES

| # | Bloque | Componente | Densidad visual | Carga cognitiva |
|---|---|---|---|---|
| 1 | Header negro | `.header` (titulo + instrucciones + progress) | baja | baja |
| 2 | Tabs vista | `.view-tabs` (Outputs / Benchmark) | baja | baja |
| 3 | Prompt | `.section` con `.config-badge` (with_skill / without_skill) | media | media |
| 4 | Output | `.section` -> `.output-file` (header + content) | ALTA | ALTA |
| 5 | Previous Output (collapsible, oculto si vacio) | `.section` colapsable | media | baja (esta cerrada) |
| 6 | Formal Grades (collapsible, oculto si vacio) | `.section` colapsable + `.assertion-list` | media | media |
| 7 | Feedback | `<textarea>` + status + previous feedback | baja | baja |
| 8 | Nav inferior | Prev / Submit All / Next | baja | baja |
| 9 | Benchmark — header + meta | `<h2>` + skill name + timestamp + evals + runs | baja | baja |
|10 | Benchmark — summary table | 3 filas (Pass Rate / Time / Tokens) x 3 columnas | media | media |
|11 | Benchmark — per-eval breakdown | `<h4>` + tabla por config con avg row | ALTA | ALTA |
|12 | Benchmark — assertions matrix | tabla N assertions x M configs (icons + tooltip) | ALTA | ALTA |
|13 | Benchmark — analysis notes | `.benchmark-notes` con `<ul>` | media | media |
|14 | Done overlay | modal de exito | n/a | n/a |
|15 | Toast | mensajes efimeros | n/a | n/a |

KPIs explicitos NO existen como tarjetas: las metricas estan empaquetadas en tablas. Esto pierde escaneo rapido.

---

## 2. PRIMERA IMPRESION (CARGA COGNITIVA)

### 2.1. Lo que funciona bien (mantener)

- **Paleta sobria** (cremas, negro, acento naranja). Coherente con identidad Anthropic. No competir con datos.
- **Tipografia dual**: Poppins (UI/headers) + Lora (cuerpo). Buena jerarquia tipografica.
- **Colapsables** para Previous Output y Formal Grades — reducen ruido cuando no aportan.
- **Color-coding semantico** consistente: verde (pass / delta positivo), rojo (fail / delta negativo), azul (with_skill), ambar (without_skill / baseline).
- **Tabs Outputs vs Benchmark**: separa la mirada cualitativa de la cuantitativa.
- **Atajos de teclado** (flechas) — fricción cero para revisar muchos runs.

### 2.2. Fricciones identificadas (pre-T1)

Lista enumerada y priorizada (P1 = critica para el reviewer humano, P3 = cosmetica).

#### F1 [P1] — La metrica clave del benchmark esta enterrada en una tabla

`run_summary` con `with_skill` vs `without_skill` se muestra como tabla densa.
**Problema**: el dato mas importante ("el skill mejora 33pp y 2.1x mas rapido") requiere leer una tabla 3x4 con notacion `mean ± stddev`.
**Impacto**: el revisor no obtiene el mensaje en menos de 5s.

#### F2 [P1] — No hay KPI cards arriba de Benchmark

El bloque `Benchmark Results` arranca directo con `<h2>` y va a la tabla. No hay 3 tarjetas grandes ("100% vs 67%", "60s vs 124s", "37k vs 47k tokens") que funcionen como hero metric.

#### F3 [P2] — La config (with_skill / without_skill) en Outputs es un badge pequeno al lado del header "Prompt"

El badge `.config-badge` es visualmente debil (0.6875rem, padding 0.2rem). Sin embargo es la pieza que indica "estas viendo el run con o sin skill". Deberia ser ancla visual mas fuerte (chip lateral, banda de color, o background del header).

#### F4 [P2] — Pass rate en Grades usa un solo badge sin contexto

Se ve "100% — 5 passed, 0 failed of 5". No hay barra de progreso ni indicador visual al lado del titulo del run. El reviewer tiene que abrir el colapsable para ver assertions. Sugerencia: mostrar el badge en el header de la seccion `Output` para no requerir abrir Grades.

#### F5 [P2] — Outputs tipo texto largo crecen sin limite y empujan Feedback fuera de viewport

En runs donde `response.txt` es muy largo (eval-backtest-protection-with_skill ronda los 80 lineas), Feedback queda far below the fold. El usuario debe scrollear a ciegas para llegar al textarea — y la nav buttons quedan cubiertos por la altura de Output.

Solucion candidata: `.output-file-content pre` con `max-height: 60vh; overflow-y: auto` y un fade-bottom + boton "Expandir todo".

#### F6 [P2] — La tabla Per-Eval Breakdown en Benchmark concatena 3 sub-tablas + 1 assertions matrix sin titulares de columna persistentes

Scroll vertical largo, headers no son sticky. Cuando el usuario llega a Eval 3 ya no recuerda cuales columnas eran "Time" y "Crashes". Sticky `<thead>` y/o un sticky `<h4>` por eval ayudaria.

#### F7 [P3] — Inputs y bordes son demasiado tenues

`--border: #e8e6dc` casi se confunde con `--bg: #faf9f5`. En pantallas claras o brillo bajo, las secciones se desdibujan. Un border-bottom mas marcado en `.section-header` o un drop-shadow sutil (`0 1px 2px rgba(0,0,0,0.04)`) reforzaria los grupos.

#### F8 [P3] — `<pre>` usa `white-space: pre-wrap`, lo que rompe code blocks de markdown

El output viene en markdown plano dentro de un `<pre>` sin highlighting. Markdown pierde su formato (las `## Headings` son texto plano). Esto **no** se debe a un bug de presentacion, sino a una decision: el visor trata el output como texto crudo. Nota: agregar markdown rendering modificaria fidelidad de output. **Consultar al Lead** si se puede convertir a markdown via marked.js o mantener como texto monoespaciado fiel.

#### F9 [P3] — Assertions matrix usa simbolos check/cross sin etiqueta

`✓` y `✗` con tooltip — el tooltip requiere hover (no en touch). Anadir aria-label y un fallback visible (e.g. "✓ pass" pequeno debajo del icono) ayudaria a accesibilidad.

#### F10 [P3] — Header negro fijo es alto (~80px en viewport tipico)

Roba viewport en pantallas pequenas. El instructions text "Review each output and leave feedback below..." se podria ocultar tras un icono de help o mostrar solo en primera carga.

#### F11 [P3] — `.assertion-evidence` con `padding-left: 1.5rem` y color muted no diferencia jerarquia con `.assertion-item`

El texto de evidencia se mezcla visualmente con el siguiente item. Anadir border-left de color muted, o un background sutil, separaria mejor las assertions.

#### F12 [P3] — Toast aparece en bottom: 5rem fijo. En viewports cortos puede taparse con la nav inferior.

Mover a top-right o respetar safe-area-inset.

---

## 3. PATRONES VISUALES — DIAGNOSTICO POR DIMENSION

### 3.1. Espaciado

- `.main` usa `gap: 1.25rem` entre secciones — correcto.
- `.section-body` con `padding: 1rem` — apretado para contenido denso (output largo).
- `.benchmark-view` con `padding: 1.5rem 2rem` — coherente con `.main`.
- **Cambio sugerido**: aumentar padding interno de `.section-body` a `1.25rem 1.5rem` para outputs largos.

### 3.2. Jerarquia tipografica

| Elemento | Font-size actual | Comentario |
|---|---|---|
| `.header h1` | 1.25rem (Poppins 600) | OK |
| `.section-header` | 0.75rem (uppercase) | OK pero **muy debil** vs el contenido |
| `<h2>` benchmark | inline-style, sin tamano explicito | hereda — flotante visualmente |
| `.benchmark-table th` | 0.75rem uppercase | OK |
| `.assertion-item` | 0.8125rem | OK |
| Output `<pre>` | 0.8125rem | OK |
| Feedback textarea | 0.9375rem | bien (es el input principal) |

**Cambio sugerido**: definir clases explicitas `.h-section` (1rem 600) y `.h-block` (0.875rem 600) para los `<h2>/<h3>/<h4>` actuales hardcoded. Estandariza la jerarquia.

### 3.3. Color hierarchy

Paleta actual: `--text` (negro), `--text-muted` (#b0aea5), `--accent` (naranja).

**Problema**: `--text-muted` se usa para 3 cosas distintas (labels, placeholders, evidence). Pierde significado.
**Sugerencia**: dividir en `--text-label` (mas oscuro #6b6963) y `--text-meta` (mas claro). Las labels actuales se diluyen.

### 3.4. Grouping / Gestalt

- Las secciones tienen `border + radius` — bien.
- **Falta agrupar visualmente** el bloque "Output + Grades + Feedback" como un solo flujo de revision (hoy son 3 cards independientes con gap igual al gap entre secciones cualquiera).
- Sugerencia: rodear esos 3 con un wrapper sutil o un divisor semantico (linea horizontal con label "REVIEW THIS RUN").

---

## 4. AREAS DE MEJORA SIN TOCAR DATOS

Estas son piezas seguras de modificar (cero impacto en datos comparados):

1. **Reordenar Benchmark**: KPI cards arriba -> tabla resumen -> per-eval breakdown -> notas.
2. **Sticky thead en tablas largas** (`position: sticky; top: 0`).
3. **Max-height + scroll interno** en outputs muy largos.
4. **Reforzar config badge** en header del run.
5. **Wrapper visual** para la tripleta Output/Grades/Feedback.
6. **Accesibilidad**: aria-labels en iconos pass/fail, focus rings visibles, contraste de muted text.
7. **Tonificar bordes** sin cambiar paleta (subir `--border` a `#dcd9cc`).

---

## 5. AREAS QUE NO TOCO (HARD STOP)

- Cualquier `EMBEDDED_DATA.runs[i].outputs[j].content` y su renderizado fiel (es el output del modelo).
- Strings de assertions (`"mentions_snapshot"`, etc.) — vienen del eval grader.
- Etiquetas de configuracion (`with_skill`, `without_skill`, `new_skill`, `old_skill`) — comparadas en `configMatch` regex.
- Estructura de `EMBEDDED_DATA` — esto lo emite `generate_review.py`, fuera de mi scope.
- Cualquier valor numerico (pass_rate, time_seconds, tokens) — solo se reformatea presentacion, no recalcula.

---

## 6. SIGUIENTE PASO

Esperando reporte de `analista-riesgos`. Cuando llegue:

1. Cruzar fricciones reportadas con F1-F12 (priorizar las que coincidan).
2. Completar `MOCKUPS.md` con antes/despues por bloque.
3. Pedir aprobacion al Lead antes de tocar el HTML real.
