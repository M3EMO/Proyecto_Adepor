-- UPDATE rho_calculado por liga - bead adepor-1vt
-- Generado por: analisis/consolidar_rho_adepor-1vt.py
-- Modificado tras veredicto Critico (bead adepor-5ul): OPCION B, 5 de 7 ligas.
-- Snapshot referencia: shadow_adepor-1vt.db
-- SHA256: bd550d9ed7f2bd75cd76f0617adc05bf92919be871dc0ac39c293c6ecda22e1a

BEGIN;

-- Alemania: actual=-0.0411 -> propuesto=-0.1216  [MLE_EXTERNO, dRho=-0.0805]
UPDATE ligas_stats SET rho_calculado = -0.1216 WHERE liga = 'Alemania';

-- Argentina: actual=-0.0521 -> propuesto=-0.08  [MLE_EXTERNO, dRho=-0.0279]
UPDATE ligas_stats SET rho_calculado = -0.08 WHERE liga = 'Argentina';

-- Bolivia: EXCLUIDO POR CRITICO (bead adepor-5ul). dRho=+0.0014 menor que precision shrinkage->floor.
-- UPDATE ligas_stats SET rho_calculado = -0.03 WHERE liga = 'Bolivia';

-- Brasil: actual=-0.0413 -> propuesto=-0.0656  [MLE_EXTERNO, dRho=-0.0243]
UPDATE ligas_stats SET rho_calculado = -0.0656 WHERE liga = 'Brasil';

-- Chile: SIN CAMBIO  [MANTENER_SIN_EVIDENCIA]  (actual=-0.0298, propuesto=-0.0298)

-- Colombia: SIN CAMBIO  [MANTENER_SIN_EVIDENCIA]  (actual=-0.0456, propuesto=-0.0456)

-- Ecuador: SIN CAMBIO  [MANTENER_SIN_EVIDENCIA]  (actual=-0.0462, propuesto=-0.0462)

-- Espana: SIN CAMBIO  [MANTENER_SIN_EVIDENCIA]  (actual=-0.037, propuesto=-0.037)

-- Francia: SIN CAMBIO  [MANTENER_SIN_EVIDENCIA]  (actual=-0.0371, propuesto=-0.0371)

-- Inglaterra: EXCLUIDO POR CRITICO (bead adepor-5ul). rho_MLE=0 sobre 1140 partidos contradice literatura DC; shrinkage hacia -0.12 no esta justificado por evidencia local.
-- UPDATE ligas_stats SET rho_calculado = -0.03 WHERE liga = 'Inglaterra';

-- Italia: SIN CAMBIO  [MANTENER_SIN_EVIDENCIA]  (actual=-0.0397, propuesto=-0.0397)

-- Noruega: actual=-0.0312 -> propuesto=-0.1069  [MLE_EXTERNO, dRho=-0.0757]
UPDATE ligas_stats SET rho_calculado = -0.1069 WHERE liga = 'Noruega';

-- Peru: SIN CAMBIO  [MANTENER_SIN_EVIDENCIA]  (actual=-0.0396, propuesto=-0.0396)

-- Turquia: actual=-0.0466 -> propuesto=-0.0712  [MLE_EXTERNO, dRho=-0.0246]
UPDATE ligas_stats SET rho_calculado = -0.0712 WHERE liga = 'Turquia';

-- Uruguay: SIN CAMBIO  [MANTENER_SIN_EVIDENCIA]  (actual=-0.041, propuesto=-0.041)

-- Venezuela: SIN CAMBIO  [MANTENER_SIN_EVIDENCIA]  (actual=-0.0419, propuesto=-0.0419)

COMMIT;

-- Total ligas con cambio aplicable: 5 (post-veredicto Critico OPCION B)
-- Ligas con cambio: Alemania, Argentina, Brasil, Noruega, Turquia
-- Ligas excluidas: Bolivia (dRho minimo), Inglaterra (rho_MLE=0 sin justificacion para shrinkage)
