import sqlite3
import requests
from datetime import datetime
import gestor_nombres
from collections import defaultdict

# ==========================================
# MOTOR ÁRBITRO V6.0 (AUDITORÍA CENTRALIZADA Y ROBUSTA)
# Responsabilidad: Extracción de Árbitro, Cálculo EMA y Auditoría con Gestor de Nombres.
# ==========================================

DB_NAME = 'fondo_quant.db'
LAMBDA_EMA = 0.15 

MAPA_LIGAS_ESPN = {
    "Argentina": "arg.1", "Brasil": "bra.1", "Inglaterra": "eng.1", 
    "Noruega": "nor.1", "Turquia": "tur.1"
}

def calcular_ema(valor_nuevo, ema_anterior):
    if ema_anterior == 0.0: return float(valor_nuevo)
    return round((LAMBDA_EMA * valor_nuevo) + ((1 - LAMBDA_EMA) * ema_anterior), 3)

def auditar_partidos():
    print("[SISTEMA] Iniciando Motor Arbitro V6.0 (Auditoria Centralizada)...")
    conn = sqlite3.connect(DB_NAME, isolation_level=None)
    cursor = conn.cursor()
    cursor.execute('PRAGMA journal_mode=WAL;')

    # 1. Buscar partidos que ya terminaron (Liquidados) pero no han sido auditados
    cursor.execute("""
        SELECT id_partido, fecha, pais, local, visita 
        FROM partidos_backtest 
        WHERE estado = 'Liquidado' AND (auditoria IS NULL OR auditoria != 'SI')
    """)
    pendientes = cursor.fetchall()

    if not pendientes:
        print("[INFO] No hay partidos nuevos pendientes de auditoria arbitral.")
        conn.close()
        return

    # Optimización: Agrupar partidos por (fecha, pais) para reducir llamadas API
    partidos_agrupados = defaultdict(list)
    for p in pendientes:
        fecha_corta = p[1].split(' ')[0]
        partidos_agrupados[(fecha_corta, p[2])].append(p)

    # Cargar memorias una sola vez
    cursor.execute("SELECT id_arbitro, nombre, partidos, ema_faltas, ema_amarillas, ema_rojas, ema_penales FROM arbitros_stats")
    memoria_arbitros = {row[0]: {"nombre": row[1], "pj": row[2], "f": row[3], "a": row[4], "r": row[5], "p": row[6]} for row in cursor.fetchall()}
    diccionario_nombres = gestor_nombres.cargar_diccionario()

    auditados = 0

    # Iterar sobre los grupos optimizados
    for (fecha_corta, pais), partidos_del_dia in partidos_agrupados.items():
        if pais not in MAPA_LIGAS_ESPN: continue

        codigo_liga = MAPA_LIGAS_ESPN[pais]
        try:
            fecha_api = datetime.strptime(fecha_corta, "%d/%m/%Y").strftime("%Y%m%d")
        except ValueError:
            print(f"[ADVERTENCIA] Formato de fecha invalido para el grupo {fecha_corta}, omitiendo.")
            continue

        # Una única llamada API por grupo (día y liga)
        url_sb = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{codigo_liga}/scoreboard?dates={fecha_api}"
        try:
            res_sb = requests.get(url_sb, timeout=10).json()
            eventos_api = res_sb.get('events', [])
        except requests.exceptions.RequestException as e:
            print(f"[ERROR] Fallo de red al buscar scoreboard para {pais} en {fecha_corta}: {e}")
            continue
        except Exception as e:
            print(f"[ERROR] Fallo inesperado al procesar scoreboard para {pais} en {fecha_corta}: {e}")
            continue

        # Procesar cada evento de la API contra nuestra lista de pendientes para ese día
        for ev in eventos_api:
            try:
                loc_api = ev['competitions'][0]['competitors'][0]['team']['displayName']
                vis_api = ev['competitions'][0]['competitors'][1]['team']['displayName']

                # Usar el gestor de nombres para un emparejamiento robusto
                partido_db = next((p for p in partidos_del_dia if gestor_nombres.son_equivalentes(p[3], loc_api, diccionario_nombres) and gestor_nombres.son_equivalentes(p[4], vis_api, diccionario_nombres)), None)
                if not partido_db: continue

                id_db, _, _, loc_db, vis_db = partido_db
                id_espn = ev['id']

                # B. Extraer Boxscore (Tarjetas y Árbitro)
                url_sum = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{codigo_liga}/summary?event={id_espn}"
                res_sum = requests.get(url_sum, timeout=10).json()
                
                competicion = res_sum.get('header', {}).get('competitions', [{}])[0]
                oficiales = competicion.get('officials', [])
                if not oficiales or not oficiales[0].get('fullName'): continue
                
                arbitro_nombre = oficiales[0]['fullName']
                id_arbitro = gestor_nombres.limpiar_texto(arbitro_nombre)

                # C. Contar Stats del partido
                stats_partido = {'f': 0.0, 'a': 0.0, 'r': 0.0, 'p': 0.0}
                for equipo in res_sum.get('boxscore', {}).get('teams', []):
                    for stat in equipo.get('statistics', []):
                        name = stat.get('name')
                        try: val = float(stat.get('displayValue', 0))
                        except (ValueError, TypeError): val = 0.0
                        
                        if name == 'foulsCommitted': stats_partido['f'] += val
                        elif name == 'yellowCards': stats_partido['a'] += val
                        elif name == 'redCards': stats_partido['r'] += val
                        elif name == 'penaltyKicks': stats_partido['p'] += val

                # D. Aplicar Teorema de EMA y actualizar memoria
                if id_arbitro in memoria_arbitros:
                    arb = memoria_arbitros[id_arbitro]
                    arb['pj'] += 1
                    arb['f'] = calcular_ema(stats_partido['f'], arb['f'])
                    arb['a'] = calcular_ema(stats_partido['a'], arb['a'])
                    arb['r'] = calcular_ema(stats_partido['r'], arb['r'])
                    arb['p'] = calcular_ema(stats_partido['p'], arb['p'])
                else:
                    memoria_arbitros[id_arbitro] = {"nombre": arbitro_nombre, "pj": 1, "f": stats_partido['f'], "a": stats_partido['a'], "r": stats_partido['r'], "p": stats_partido['p']}
                
                arb_actualizado = memoria_arbitros[id_arbitro]

                # E. Guardar en Base de Datos (Doble Update)
                cursor.execute('''
                    INSERT INTO arbitros_stats (id_arbitro, nombre, partidos, ema_faltas, ema_amarillas, ema_rojas, ema_penales)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id_arbitro) DO UPDATE SET
                    partidos=excluded.partidos, ema_faltas=excluded.ema_faltas,
                    ema_amarillas=excluded.ema_amarillas, ema_rojas=excluded.ema_rojas, ema_penales=excluded.ema_penales
                ''', (id_arbitro, arb_actualizado['nombre'], arb_actualizado['pj'], arb_actualizado['f'], arb_actualizado['a'], arb_actualizado['r'], arb_actualizado['p']))

                cursor.execute("UPDATE partidos_backtest SET arbitro = ?, id_arbitro = ?, auditoria = 'SI' WHERE id_partido = ?", (arbitro_nombre, id_arbitro, id_db))
                
                auditados += 1
                print(f"[AUDITORIA] {loc_db} vs {vis_db} | Arbitro: {arbitro_nombre} (Procesado)")
                partidos_del_dia.remove(partido_db) # Evitar doble procesamiento

            except requests.exceptions.RequestException as e:
                print(f"[ERROR] Fallo de red al auditar {partido_db[3]} vs {partido_db[4]}: {e}")
            except (KeyError, IndexError, TypeError) as e:
                print(f"[ERROR] Estructura de datos inesperada al auditar {partido_db[3]} vs {partido_db[4]}: {e}")
            except Exception as e:
                print(f"[ERROR] Fallo inesperado al auditar partido: {e}")

    conn.close()
    print(f"[SISTEMA] Proceso de auditoria finalizado. {auditados} partidos nuevos auditados.")

if __name__ == "__main__":
    auditar_partidos()