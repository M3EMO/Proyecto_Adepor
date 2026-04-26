VEREDICTO: CONDICIONAL — implementar SHADOW MODE primero, NO aplicar a produccion ya.

CLAIMS VERIFICADAS (reproducidas exactamente):
  V_actual: yield +47.93%, hit 42.53%, N=87 - VERIFICADO
  V_sin_HG: yield +182.51%, hit 74.07%, N=27 - VERIFICADO
  V_sin_FIX5: yield +53.95%, hit 42.11%, N=76 - VERIFICADO
  V_sin_FIX5_HG: yield +223.64%, hit 81.82%, N=22 - VERIFICADO

VACIOS LOGICOS DETECTADOS:
1. La 'mejora yield +175pp' colapsa a N=4 en Argentina (4/4 hit 100%) y N=9 Brasil (8/9 hit 88.9%).
   Resto: 9 picks con hit 6/9 (67%). Sin HG/FIX5 simplemente PASA mas: el motor SOLO opera 22 picks de 342.
2. Picks con HG/FIX5 ON pero sin equivalente OFF: 66 picks (FLIPS). Hit 30.3%.
   Estos 66 picks DESTRUYEN el yield agregado. Si el agente identifica esos casos como toxicos
   selectivamente, no es necesario desactivar HG GLOBAL.
3. La justificacion 'reliability diagram muestra HG empeora' tiene logica invertida:
   - Bucket [40-45): gap -2.6pp (motor casi calibrado)
   - Bucket [45-50): gap +17.8pp (motor SUB-estima — HG corrige BIEN aca)
   Fix #5 corrige bucket [40-45) que NO necesita correccion. FIX5 es el problema, NO HG.
4. Brier: HG+FIX5 0.61979 vs SIN 0.62829. HG/FIX5 MEJORAN Brier (-0.0085).
   Desactivar empeora calibracion global (consistente con Manifesto: 'Brier no se rompe').

RIESGOS NO MENCIONADOS:
1. Drift temporal severo: V_sin_FIX5_HG yield primera mitad +333.55% (N=11, hit 100%),
   segunda mitad +113.73% (N=11, hit 63.6%). El yield de la segunda mitad ya esta cayendo —
   mas data probable converge a yield mas modesto. ESTO ES SEÑAL DE OVERFITTING.
2. N efectivo ridiculamente chico: 22 picks total. Bootstrap CI 95% [144%, 299%] suena bien
   pero la variance real es altisima — un solo partido movera el yield 15pp.
3. Brasil aporta 8 de 18 wins. Si Brasil cambia de tendencia (cualquier 4 partidos malos
   en sequence) reverse el yield.
4. La doctrina ya prohibe 'simulacion de cuotas historicas' como evidencia conclusiva.
   Lead intenta saltarse la regla apoyandose en 'direccion robusta 5/5 folds'.
   PERO los 5/5 folds son sobre los MISMOS datos (el folding es solo split, no temporal hold-out).

ANALISIS DE OVERFITTING:
  N de la muestra: 22 picks (V_sin_FIX5_HG)
  Grados de libertad: 6 filtros simulados (FLOOR, MARGEN, EV, KELLY_CAP, FIX5, HG)
  Ratio datos/parametros: 22/6 = 3.67 - CRITICO (minimo aceptable: 10:1)
  Test de robustez:
    - Sin top-1 pick: yield cae de +223% a +208%
    - Sin top-3 picks: yield cae a +179%
    - Drift: primera mitad +333% / segunda mitad +113% (diferencia 220pp)
  CONCLUSION: el yield reportado depende de pocos partidos especificos.

ALTERNATIVA ARQUITECTURAL (mejor que la propuesta):
  En lugar de KILLSWITCH GLOBAL HG+FIX5, considerar:
  A. Fix #5: DESACTIVAR (evidence solido). Bucket [40-45) NO necesita correccion segun reliability.
     El bucket que necesita boost es [45-50) y FIX5 no lo cubre. FIX5 es net-negative.
  B. HG: REVISAR aplicacion selectiva por bucket en lugar de boost incondicional.
     - Mantener HG en bucket [45-50) donde gap +17.8pp (motor sub-estima — HG ayuda).
     - Limitar HG en bucket [30-40) donde gap -28pp/-14pp (motor sobre-estima — HG empeora).
     Esta es la lectura CORRECTA del reliability diagram.

CONDICIONES PARA APROBACION:
  COND-A: SHADOW MODE 60 dias minimo (target N>=80 picks live).
  COND-B: registrar picks_shadow_sin_hg_fix5 + picks_actual paralelo en DB.
  COND-C: Fix #5 podria considerarse para desactivar SOLO si shadow N>=50 confirma yield positivo.
  COND-D: HG NO desactivar global. Diseñar HG selectivo por bucket (bead nuevo).
  COND-E: Tests adicionales obligatorios:
    - Hold-out temporal real (entrenar pre-2026-04-01, test post)
    - Yield por liga separado (Argentina/Brasil aislados)
    - Test sensibilidad a cuotas alternativas (overround diferente)

ROLL-BACK PLAN:
  Si shadow muestra yield <50% en N=80: REVERTIR a V_actual (no cambiar produccion).
  Kill-switch en DB hace reversion trivial.

Bead-id: adepor-6rv (PROPUESTA original)
Snapshot reliability: analisis/reliability_diagram_motor.json (N=434)
Snapshot ablation: analisis/ablation_completa_todos_filtros.py (N=342)
Snapshot critico audit: analisis/critico_audit_6rv.py (script de verificacion)
Yield Brier delta: HG+FIX5 mejoran Brier (-0.0085) — desactivar EMPEORA calibracion global

Razon del CONDICIONAL en lugar de VETO:
  Yield +47% baseline vs +223% sin filtros es señal interesante. NO ignorar.
  Pero N=22 con drift visible y mejora colapsada en 2 ligas es INSUFICIENTE.
  Shadow forward con N>=80 en live puede CONFIRMAR o REFUTAR.

Razon del CONDICIONAL en lugar de APROBADO:
  Manifesto V4.5/V4.6 doctrinas NO se rompen sin evidencia FORWARD live.
  Las pruebas son in-sample sobre cuotas historicas — la doctrina del proyecto
  ('yield no se rompe') requiere evidencia robusta. N=22 NO ES robusto.

CRITICO firma: 2026-04-26
