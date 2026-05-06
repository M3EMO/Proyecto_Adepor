"""Persistir alphas per liga + flag modo en config_motor_valores."""
import sqlite3

con = sqlite3.connect('fondo_quant.db')
cur = con.cursor()

alphas = {
    # LATAM exóticas - ESPN da xg=0, SOFA puro óptimo (validado POC ablation v2)
    'Bolivia': 1.0,
    'Venezuela': 1.0,
    'Uruguay': 1.0,
    'Ecuador': 0.95,
    # LATAM híbrido alto SOFA
    'Peru': 0.85,
    # LATAM mainstream
    'Argentina': 0.50,
    'Brasil': 0.50,
    # EUR mainstream
    'Inglaterra': 0.30,
    'Espana': 0.30,
    'Italia': 0.40,
    'Alemania': 0.30,
    'Francia': 0.25,
    'Turquia': 0.35,
    'Noruega': 0.30,
    'Chile': 0.30,
    'Colombia': 0.30,
}

cur.execute("DELETE FROM config_motor_valores WHERE clave='alpha_xg_v2_hibrido_sofa'")

for liga, alpha in alphas.items():
    cur.execute('''
        INSERT INTO config_motor_valores (clave, scope, valor_real, valor_texto, tipo, fuente)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', ('alpha_xg_v2_hibrido_sofa', liga, alpha, None, 'float',
          'POC_2026-05-04_motor_xg_v2_19_comparacion'))

cur.execute('''
    INSERT INTO config_motor_valores (clave, scope, valor_real, valor_texto, tipo, fuente)
    VALUES (?, ?, ?, ?, ?, ?)
''', ('alpha_xg_v2_hibrido_sofa', 'global', 0.30, None, 'float',
      'POC_2026-05-04'))

# Modo: shadow | active
cur.execute('''
    INSERT OR REPLACE INTO config_motor_valores (clave, scope, valor_real, valor_texto, tipo, fuente)
    VALUES (?, ?, ?, ?, ?, ?)
''', ('xg_v2_hibrido_modo', 'global', None, 'shadow', 'string',
      'POC_2026-05-04'))

con.commit()
print('Persistido alpha_xg_v2_hibrido_sofa per liga:')
for r in cur.execute("SELECT scope, valor_real FROM config_motor_valores WHERE clave='alpha_xg_v2_hibrido_sofa' ORDER BY scope"):
    print(f'  alpha[{r[0]:<14s}] = {r[1]}')

modo = cur.execute("SELECT valor_texto FROM config_motor_valores WHERE clave='xg_v2_hibrido_modo'").fetchone()
print(f'\nModo activo: {modo[0]}')
con.close()
