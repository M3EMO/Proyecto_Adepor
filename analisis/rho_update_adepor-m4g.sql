-- UPDATE rho_calculado para 9 ligas (adepor-m4g, retry post-429)
-- Generado automaticamente. Aplicar manual post-veredicto Critico.

UPDATE ligas_stats SET rho_calculado = -0.0839 WHERE liga = 'Ecuador';  -- delta=-0.0379, N_ext=725
-- Espana: rho_MLE=0 (post-COVID artifact?), shrinkage->floor=-0.0300. SUSPENDER hasta investigacion (similar a adepor-0yy Inglaterra).
UPDATE ligas_stats SET rho_calculado = -0.085 WHERE liga = 'Francia';  -- delta=-0.0479, N_ext=994
UPDATE ligas_stats SET rho_calculado = -0.0562 WHERE liga = 'Italia';  -- delta=-0.0165, N_ext=1141
UPDATE ligas_stats SET rho_calculado = -0.05 WHERE liga = 'Peru';  -- delta=-0.0101, N_ext=996
UPDATE ligas_stats SET rho_calculado = -0.0612 WHERE liga = 'Uruguay';  -- delta=-0.0197, N_ext=530
UPDATE ligas_stats SET rho_calculado = -0.1491 WHERE liga = 'Venezuela';  -- delta=-0.1068, N_ext=731
