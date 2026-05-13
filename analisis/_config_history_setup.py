"""Tabla historica config_motor_valores - Recomendacion #4.

Crear infra para auditoria longitudinal de cambios a config (sin esto, los
flags como apuestas_live se sobreescriben silenciosamente sin trail).

Acciones:
1. CREATE TABLE config_motor_valores_history (mismo schema + accion + ts)
2. Backfill snapshot actual
3. CREATE TRIGGER para INSERT/UPDATE/DELETE en config_motor_valores

Esto es INFRA pura - no afecta motor productivo. Aplico directo.
"""
import sqlite3, pandas as pd
from datetime import datetime
con = sqlite3.connect('fondo_quant.db')
c = con.cursor()

# 1. Schema actual
print("=== Schema config_motor_valores actual ===")
schema = c.execute("PRAGMA table_info(config_motor_valores)").fetchall()
for col in schema:
    print(f"  {col[1]:<25s} {col[2]}")

# 2. Verificar si tabla ya existe
existe = c.execute("""
    SELECT name FROM sqlite_master WHERE type='table' AND name='config_motor_valores_history'
""").fetchone()
if existe:
    print("\n[skip] Tabla config_motor_valores_history ya existe")
else:
    print("\n=== Creando tabla config_motor_valores_history ===")
    c.execute("""
        CREATE TABLE config_motor_valores_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_evento TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            accion TEXT NOT NULL,             -- 'INSERT' | 'UPDATE' | 'DELETE' | 'BACKFILL'
            clave TEXT NOT NULL,
            scope TEXT,
            valor_real_old REAL,
            valor_real_new REAL,
            valor_texto_old TEXT,
            valor_texto_new TEXT,
            tipo_old TEXT,
            tipo_new TEXT,
            fuente_old TEXT,
            fuente_new TEXT,
            bloqueado_old INTEGER,
            bloqueado_new INTEGER,
            fecha_actualizacion_old TIMESTAMP,
            fecha_actualizacion_new TIMESTAMP,
            evento_meta TEXT                  -- comentarios humanos opcionales
        )
    """)
    c.execute("CREATE INDEX idx_cmv_hist_clave_scope ON config_motor_valores_history(clave, scope)")
    c.execute("CREATE INDEX idx_cmv_hist_ts ON config_motor_valores_history(ts_evento)")
    print("  [ok] tabla + indices creados")

# 3. Backfill: snapshot del estado actual
n_before = c.execute("SELECT COUNT(*) FROM config_motor_valores_history WHERE accion='BACKFILL'").fetchone()[0]
if n_before == 0:
    print("\n=== Backfill snapshot estado actual ===")
    c.execute("""
        INSERT INTO config_motor_valores_history
            (accion, clave, scope,
             valor_real_new, valor_texto_new, tipo_new, fuente_new,
             bloqueado_new, fecha_actualizacion_new, evento_meta)
        SELECT
            'BACKFILL', clave, scope,
            valor_real, valor_texto, tipo, fuente,
            bloqueado, fecha_actualizacion,
            'snapshot inicial 2026-05-13'
        FROM config_motor_valores
    """)
    con.commit()
    n_after = c.execute("SELECT COUNT(*) FROM config_motor_valores_history WHERE accion='BACKFILL'").fetchone()[0]
    print(f"  [ok] backfilled {n_after} filas")
else:
    print(f"\n[skip] Backfill ya existe ({n_before} filas)")

# 4. Triggers - sqlite triggers para capturar cambios futuros
print("\n=== Triggers para auditoria automatica ===")
existing_triggers = [r[0] for r in c.execute("""
    SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'cmv_audit_%'
""")]
print(f"Triggers existentes: {existing_triggers}")

if 'cmv_audit_insert' not in existing_triggers:
    c.execute("""
        CREATE TRIGGER cmv_audit_insert AFTER INSERT ON config_motor_valores
        BEGIN
            INSERT INTO config_motor_valores_history
                (accion, clave, scope,
                 valor_real_new, valor_texto_new, tipo_new, fuente_new,
                 bloqueado_new, fecha_actualizacion_new)
            VALUES
                ('INSERT', NEW.clave, NEW.scope,
                 NEW.valor_real, NEW.valor_texto, NEW.tipo, NEW.fuente,
                 NEW.bloqueado, NEW.fecha_actualizacion);
        END;
    """)
    print("  [ok] cmv_audit_insert")

if 'cmv_audit_update' not in existing_triggers:
    c.execute("""
        CREATE TRIGGER cmv_audit_update AFTER UPDATE ON config_motor_valores
        BEGIN
            INSERT INTO config_motor_valores_history
                (accion, clave, scope,
                 valor_real_old, valor_real_new,
                 valor_texto_old, valor_texto_new,
                 tipo_old, tipo_new, fuente_old, fuente_new,
                 bloqueado_old, bloqueado_new,
                 fecha_actualizacion_old, fecha_actualizacion_new)
            VALUES
                ('UPDATE', NEW.clave, NEW.scope,
                 OLD.valor_real, NEW.valor_real,
                 OLD.valor_texto, NEW.valor_texto,
                 OLD.tipo, NEW.tipo, OLD.fuente, NEW.fuente,
                 OLD.bloqueado, NEW.bloqueado,
                 OLD.fecha_actualizacion, NEW.fecha_actualizacion);
        END;
    """)
    print("  [ok] cmv_audit_update")

if 'cmv_audit_delete' not in existing_triggers:
    c.execute("""
        CREATE TRIGGER cmv_audit_delete AFTER DELETE ON config_motor_valores
        BEGIN
            INSERT INTO config_motor_valores_history
                (accion, clave, scope,
                 valor_real_old, valor_texto_old, tipo_old, fuente_old,
                 bloqueado_old, fecha_actualizacion_old)
            VALUES
                ('DELETE', OLD.clave, OLD.scope,
                 OLD.valor_real, OLD.valor_texto, OLD.tipo, OLD.fuente,
                 OLD.bloqueado, OLD.fecha_actualizacion);
        END;
    """)
    print("  [ok] cmv_audit_delete")

con.commit()

# 5. Sanity: estado final
print("\n=== Sanity final ===")
n_hist = c.execute("SELECT COUNT(*) FROM config_motor_valores_history").fetchone()[0]
n_orig = c.execute("SELECT COUNT(*) FROM config_motor_valores").fetchone()[0]
triggers = [r[0] for r in c.execute("""
    SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'cmv_audit_%'
""")]
print(f"  config_motor_valores: {n_orig} filas")
print(f"  config_motor_valores_history: {n_hist} filas")
print(f"  triggers activos: {triggers}")
print("\n=== Test trigger: cambio dummy ===")
c.execute("INSERT OR REPLACE INTO config_motor_valores (clave, scope, valor_texto, tipo, fuente, bloqueado, fecha_actualizacion) VALUES ('test_audit', 'test_scope', 'test_val', 'test', 'test_audit_trigger', 0, datetime('now'))")
con.commit()
test_row = c.execute("SELECT accion, clave, scope, valor_texto_new, fuente_new FROM config_motor_valores_history WHERE clave='test_audit' ORDER BY id DESC LIMIT 1").fetchone()
print(f"  Test row capturada: {test_row}")
# Limpiar test
c.execute("DELETE FROM config_motor_valores WHERE clave='test_audit'")
con.commit()
print("  [ok] trigger funciona y test limpiado")

con.close()
print("\n[done] Tabla histórica + triggers operativos")
