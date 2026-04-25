"""
Crea la tabla aportes_capital si no existe.

aportes_capital trackea inyecciones/retiros de capital del usuario, permitiendo
que el bankroll operativo crezca sin reescribir stakes ya liquidados.

Cada aporte es un evento (fecha, monto, descripcion). El monto positivo es
inyeccion, negativo es retiro.

Idempotente: si la tabla ya existe, no hace nada.
"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / 'fondo_quant.db'


def main():
    if not DB.exists():
        print(f"[ERROR] {DB} no existe.")
        sys.exit(1)
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS aportes_capital (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL,           -- YYYY-MM-DD
            monto REAL NOT NULL,           -- positivo=aporte, negativo=retiro
            descripcion TEXT,
            fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_aportes_fecha ON aportes_capital(fecha)")
    conn.commit()
    cur.execute("SELECT COUNT(*) FROM aportes_capital")
    n = cur.fetchone()[0]
    conn.close()
    print(f"[OK] tabla aportes_capital lista. Filas existentes: {n}")


if __name__ == "__main__":
    main()
