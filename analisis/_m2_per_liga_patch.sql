-- M.2 thresholds per-liga calibrados sobre histórico 2012-2025
-- Aplicar con bead PROPOSAL aprobado (cambia comportamiento del motor)

-- Alemania: thr=50 (yld -0.119 -> -0.002)
INSERT OR REPLACE INTO config_motor_valores (clave, scope, valor_real, tipo, fuente, bloqueado, fecha_actualizacion)
VALUES ('m2_n_acum_max', 'Alemania', 50, 'int', 'calibracion_m2_per_liga_2026-05-13', 0, datetime('now'));



-- Espana: thr=30 (yld -0.032 -> -0.001)
INSERT OR REPLACE INTO config_motor_valores (clave, scope, valor_real, tipo, fuente, bloqueado, fecha_actualizacion)
VALUES ('m2_n_acum_max', 'Espana', 30, 'int', 'calibracion_m2_per_liga_2026-05-13', 0, datetime('now'));

-- Francia: desactivar M.2 (yld_sin_filtro -0.083, best_gap negativo)
INSERT OR REPLACE INTO config_motor_valores (clave, scope, valor_real, tipo, fuente, bloqueado, fecha_actualizacion)
VALUES ('m2_n_acum_max', 'Francia', 9999, 'int', 'calibracion_m2_per_liga_2026-05-13', 0, datetime('now'));

-- Holanda: thr=20 (yld -0.077 -> +0.081)
INSERT OR REPLACE INTO config_motor_valores (clave, scope, valor_real, tipo, fuente, bloqueado, fecha_actualizacion)
VALUES ('m2_n_acum_max', 'Holanda', 20, 'int', 'calibracion_m2_per_liga_2026-05-13', 0, datetime('now'));

-- Inglaterra: thr=100 (yld -0.007 -> +0.018)
INSERT OR REPLACE INTO config_motor_valores (clave, scope, valor_real, tipo, fuente, bloqueado, fecha_actualizacion)
VALUES ('m2_n_acum_max', 'Inglaterra', 100, 'int', 'calibracion_m2_per_liga_2026-05-13', 0, datetime('now'));

-- Italia: thr=70 (yld -0.116 -> -0.061)
INSERT OR REPLACE INTO config_motor_valores (clave, scope, valor_real, tipo, fuente, bloqueado, fecha_actualizacion)
VALUES ('m2_n_acum_max', 'Italia', 70, 'int', 'calibracion_m2_per_liga_2026-05-13', 0, datetime('now'));

-- Turquia: thr=20 (yld +0.004 -> +0.092)
INSERT OR REPLACE INTO config_motor_valores (clave, scope, valor_real, tipo, fuente, bloqueado, fecha_actualizacion)
VALUES ('m2_n_acum_max', 'Turquia', 20, 'int', 'calibracion_m2_per_liga_2026-05-13', 0, datetime('now'));
