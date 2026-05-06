"""Crear esquema DB + bead epic para persistir findings de team de agentes.

Tabla `agentes_findings`:
  - id (PK auto)
  - sesion_id (TEXT)              -- e.g. '2026-05-02_team_filtros_oro'
  - agente_id (TEXT)              -- internal id del background task
  - agente_tipo (TEXT)            -- cazador_datos, investigador_xg, optimizador_modelo, critico
  - mision (TEXT)                 -- descripción de la tarea asignada
  - fecha_inicio (TIMESTAMP)
  - fecha_fin (TIMESTAMP)
  - status (TEXT)                 -- running, completed, killed, error
  - finding_resumen (TEXT)        -- síntesis ≤500 palabras
  - doc_persistido (TEXT)         -- ruta al .md generado
  - data_artefactos (TEXT JSON)   -- JSON con métricas clave
  - bead_id (TEXT)                -- ID del bead asociado si aplica
  - veto_critico (INTEGER 0/1)    -- 1 si el critico vetó
  - score_credibilidad (REAL)     -- 0-1 evaluación humana posterior
  - notas (TEXT)
"""
import sqlite3

DB = "fondo_quant.db"


def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS agentes_findings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sesion_id TEXT NOT NULL,
            agente_id TEXT NOT NULL,
            agente_tipo TEXT NOT NULL,
            mision TEXT NOT NULL,
            fecha_inicio TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            fecha_fin TIMESTAMP,
            status TEXT NOT NULL DEFAULT 'running',
            finding_resumen TEXT,
            doc_persistido TEXT,
            data_artefactos TEXT,
            bead_id TEXT,
            veto_critico INTEGER DEFAULT 0,
            score_credibilidad REAL,
            notas TEXT
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_af_sesion ON agentes_findings(sesion_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_af_agente_id ON agentes_findings(agente_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_af_status ON agentes_findings(status)")

    # Insertar el agente 1 (expansión N) que está corriendo
    cur.execute("""
        INSERT INTO agentes_findings (sesion_id, agente_id, agente_tipo, mision, status)
        VALUES (?, ?, ?, ?, ?)
    """, ("2026-05-02_team_filtros_oro", "ace05e324ff87e73f", "cazador_datos",
          "Expansion match cuotas-stats al 100% (mappings ESPN->fdco para ARG/BRA/TUR)",
          "running"))

    # Insertar registros de los 5 agentes detenidos
    killed = [
        ("ab8c0e624a9018077", "investigador_xg", "Nichos sostenibles equipo/liga/año (>=2/3 años positivos)"),
        ("ada2fdebad5b0813e", "optimizador_modelo", "Filtro de oro POR LIGA (8 reglas individuales)"),
        ("aaa52c7368e820fa1", "critico", "V0 crudo baseline + utilidad filtros (audit)"),
        ("a8d8ec7eb2e62fd2c", "optimizador_modelo", "Walk-forward TRUE-OOS protocolo (5 propuestas)"),
        ("ac549991183312d16", "investigador_xg", "Angulos creativos NO probados (patrones contextuales)"),
    ]
    for aid, tipo, mision in killed:
        cur.execute("""
            INSERT INTO agentes_findings (sesion_id, agente_id, agente_tipo, mision, status, notas)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("2026-05-02_team_filtros_oro", aid, tipo, mision, "killed",
              "Detenido por usuario — pendiente expansion N->100% antes de relanzar"))

    conn.commit()
    print("Tabla agentes_findings creada.")
    print(f"Filas iniciales: {cur.execute('SELECT COUNT(*) FROM agentes_findings').fetchone()[0]}")
    for r in cur.execute("SELECT id, agente_tipo, status, substr(mision,1,60) FROM agentes_findings").fetchall():
        print(r)


if __name__ == "__main__":
    main()
