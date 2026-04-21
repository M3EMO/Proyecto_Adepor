import sqlite3
import csv
import os

# ==========================================
# SCRIPT DE IMPORTACION GOLD STANDARD
# Responsabilidad: sincronizar la tabla 'partidos_backtest' desde
# el CSV maestro preservando stakes/apuestas ya calculados por el motor.
#
# 2026-04-21: migrado de DELETE+INSERT a UPSERT para no perder
# stake_1x2/stake_ou/apuesta_1x2/apuesta_ou cuando un partido pasa a
# Liquidado (necesario para Kelly dinamico que suma P/L historico).
# ==========================================

DB_NAME = 'fondo_quant.db'
CSV_GOLD_STANDARD = 'modelo_estable.csv'

def safe_float_from_csv(val_str):
    if not val_str: return None
    try:
        return float(val_str.replace(',', '.'))
    except (ValueError, TypeError):
        return None

def safe_int_from_csv(val_str):
    if not val_str: return None
    try:
        return int(val_str)
    except (ValueError, TypeError):
        return None


def _liquidar_apuesta_1x2(apuesta, goles_l, goles_v):
    """Convierte '[APOSTAR] X' -> '[GANADA] X' o '[PERDIDA] X' segun goles.
    Si la apuesta ya esta liquidada o no es apostable, la devuelve intacta."""
    if not apuesta or goles_l is None or goles_v is None:
        return apuesta
    ap = str(apuesta)
    if '[APOSTAR]' not in ap:
        return apuesta
    if 'LOCAL' in ap:
        ganada = goles_l > goles_v
    elif 'EMPATE' in ap:
        ganada = goles_l == goles_v
    elif 'VISITA' in ap:
        ganada = goles_l < goles_v
    else:
        return apuesta
    return ap.replace('[APOSTAR]', '[GANADA]' if ganada else '[PERDIDA]')


def _liquidar_apuesta_ou(apuesta, goles_l, goles_v):
    if not apuesta or goles_l is None or goles_v is None:
        return apuesta
    ap = str(apuesta)
    if '[APOSTAR]' not in ap:
        return apuesta
    total = goles_l + goles_v
    u = ap.upper()
    if 'OVER' in u or '+2.5' in u or 'MAS' in u:
        ganada = total > 2.5
    elif 'UNDER' in u or '-2.5' in u or 'MENOS' in u:
        ganada = total < 2.5
    else:
        return apuesta
    return ap.replace('[APOSTAR]', '[GANADA]' if ganada else '[PERDIDA]')


def main():
    if not os.path.exists(CSV_GOLD_STANDARD):
        print(f"[ERROR CRITICO] El archivo Gold Standard '{CSV_GOLD_STANDARD}' no fue encontrado. Proceso abortado.")
        return

    print("Iniciando protocolo de sincronizacion desde Gold Standard CSV (UPSERT).")
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        # Snapshot de ids existentes con stake/apuesta para liquidacion post-import
        cursor.execute("""
            SELECT id_partido, apuesta_1x2, apuesta_ou, stake_1x2, stake_ou
            FROM partidos_backtest
        """)
        previos = {r[0]: {'ap1x2': r[1], 'apou': r[2], 'st1x2': r[3], 'stou': r[4]}
                   for r in cursor.fetchall()}

        insertados = 0
        actualizados = 0
        liquidados_ahora = 0

        with open(CSV_GOLD_STANDARD, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                id_partido = row.get('ID Partido')
                if not id_partido:
                    continue

                goles_l = safe_int_from_csv(row.get('Goles L'))
                goles_v = safe_int_from_csv(row.get('Goles V'))
                tiene_goles = (goles_l is not None and goles_v is not None
                               and str(row.get('Goles L','')).strip() != ''
                               and str(row.get('Goles V','')).strip() != '')

                prev = previos.get(id_partido)
                # Si ya habia apuesta calculada y el partido ahora tiene goles,
                # liquidar el prefijo [APOSTAR] -> [GANADA]/[PERDIDA].
                if prev and tiene_goles:
                    prev_ap1x2 = prev['ap1x2']
                    prev_apou  = prev['apou']
                    nuevo_ap1x2 = _liquidar_apuesta_1x2(prev_ap1x2, goles_l, goles_v)
                    nuevo_apou  = _liquidar_apuesta_ou(prev_apou,  goles_l, goles_v)
                    if nuevo_ap1x2 != prev_ap1x2 or nuevo_apou != prev_apou:
                        liquidados_ahora += 1

                # Estado final
                estado = 'Liquidado' if tiene_goles else ('Calculado' if prev and prev.get('st1x2', 0) else 'Pendiente')
                # Si ya estaba Calculado o Liquidado, respetar pendiente->calculado segun stake.
                if not tiene_goles and prev:
                    # mantener estado previo si era Calculado (el motor ya lo proceso)
                    cursor.execute("SELECT estado FROM partidos_backtest WHERE id_partido=?", (id_partido,))
                    r = cursor.fetchone()
                    if r and r[0] in ('Calculado', 'Pendiente'):
                        estado = r[0]

                # UPSERT: INSERT si no existe, UPDATE solo campos externos (preserva stake/apuesta/probs)
                cursor.execute("""
                    INSERT INTO partidos_backtest
                        (id_partido, fecha, local, visita, pais, cuota_1, cuota_x, cuota_2, cuota_o25, cuota_u25,
                         goles_l, goles_v, formacion_l, formacion_v, estado)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id_partido) DO UPDATE SET
                        fecha       = excluded.fecha,
                        local       = excluded.local,
                        visita      = excluded.visita,
                        pais        = excluded.pais,
                        cuota_1     = excluded.cuota_1,
                        cuota_x     = excluded.cuota_x,
                        cuota_2     = excluded.cuota_2,
                        cuota_o25   = excluded.cuota_o25,
                        cuota_u25   = excluded.cuota_u25,
                        goles_l     = excluded.goles_l,
                        goles_v     = excluded.goles_v,
                        formacion_l = excluded.formacion_l,
                        formacion_v = excluded.formacion_v,
                        estado      = excluded.estado
                """, (
                    id_partido, row.get('Fecha'), row.get('Local'), row.get('Visita'), row.get('Liga'),
                    safe_float_from_csv(row.get('Cuota 1')), safe_float_from_csv(row.get('Cuota X')), safe_float_from_csv(row.get('Cuota 2')),
                    safe_float_from_csv(row.get('Cuota +2.5')), safe_float_from_csv(row.get('Cuota -2.5')),
                    goles_l, goles_v, row.get('Formacion L'), row.get('Formacion V'), estado
                ))

                # Aplicar liquidacion de prefijo si corresponde
                if prev and tiene_goles:
                    nuevo_ap1x2 = _liquidar_apuesta_1x2(prev['ap1x2'], goles_l, goles_v)
                    nuevo_apou  = _liquidar_apuesta_ou(prev['apou'],  goles_l, goles_v)
                    if nuevo_ap1x2 != prev['ap1x2'] or nuevo_apou != prev['apou']:
                        cursor.execute("""
                            UPDATE partidos_backtest
                            SET apuesta_1x2 = ?, apuesta_ou = ?
                            WHERE id_partido = ?
                        """, (nuevo_ap1x2, nuevo_apou, id_partido))

                if prev: actualizados += 1
                else:    insertados += 1

        conn.commit()
        print(f"Sincronizacion completada: +{insertados} nuevos, ~{actualizados} actualizados, {liquidados_ahora} liquidados ahora ([APOSTAR] -> [GANADA]/[PERDIDA]).")

    except Exception as e:
        print(f"Error critico durante la operacion: {e}")
        if conn: conn.rollback()
    finally:
        if conn: conn.close()

if __name__ == "__main__":
    main()
