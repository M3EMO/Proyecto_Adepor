import sys
import sqlite3
import requests
import time
import re
from datetime import datetime
import unicodedata

# ==========================================
# MOTOR LIVE V4.2 (CACHE PERSISTENTE)
# Responsabilidad: Alertas de Apuestas, Traduccion de Cuotas e Insercion SQL Segura con memoria persistente.
# ==========================================

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

TELEGRAM_TOKEN = "8608474072:AAExuuk_Fncpsxlr6VfHpnRkSAKd15X7U54"
TELEGRAM_CHAT_ID = "6589570908"
DB_NAME = 'fondo_quant.db'

LIGAS_ESPN = {"arg.1", "eng.1", "bra.1", "nor.1", "tur.1"}

def cargar_cache_alertas():
    """
    Precarga las alertas ya enviadas desde la base de datos para evitar duplicados al reiniciar.
    """
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS log_alertas (
                id_alerta TEXT PRIMARY KEY, 
                partido TEXT, 
                mercado TEXT, 
                pick TEXT, 
                stake_enviado REAL
            )
        """)
        conn.commit()
        cursor.execute("SELECT id_alerta FROM log_alertas")
        alertas_enviadas = {row[0] for row in cursor.fetchall()}
        print(f"[SISTEMA] Cache de persistencia cargada. Se recuperaron {len(alertas_enviadas)} alertas historicas.")
        return alertas_enviadas
    except sqlite3.Error as e:
        print(f"[ERROR CRITICO] No se pudo cargar la cache de alertas desde SQLite: {e}")
        return set()
    finally:
        if conn:
            conn.close()

def enviar_telegram(mensaje):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "Markdown"}
    try:
        requests.post(url, data=data, timeout=10)
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Fallo al enviar mensaje a Telegram: {e}")

def normalizar(texto):
    if not texto: return ""
    crudo = ''.join(c for c in unicodedata.normalize('NFD', str(texto).lower().strip()) if unicodedata.category(c) != 'Mn')
    return crudo.replace(" ", "").replace("-", "").replace("_", "").replace("'", "")

def convertir_americano_a_decimal(americano_str):
    try:
        val = int(americano_str.replace('+', ''))
        if val > 0: return round((val / 100) + 1, 2)
        elif val < 0: return round((100 / abs(val)) + 1, 2)
    except (ValueError, TypeError):
        return 0.0
    return 0.0

def rastrear_clv_espn(cursor, conn):
    cursor.execute("""
        SELECT id_partido, local, visita 
        FROM partidos_backtest 
        WHERE estado != 'Liquidado' AND clv_registrado IS NULL AND (apuesta_1x2 IS NOT NULL OR apuesta_ou IS NOT NULL)
    """)
    partidos_vivos = cursor.fetchall()
    if not partidos_vivos: return

    fecha_api = datetime.now().strftime('%Y%m%d')
    
    for liga in LIGAS_ESPN:
        url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{liga}/scoreboard?dates={fecha_api}"
        try:
            resp = requests.get(url, timeout=5)
            if resp.status_code != 200: continue
            
            for evento in resp.json().get('events', []):
                estado = evento.get('status', {}).get('type', {}).get('name', '')
                if estado not in ['STATUS_IN_PROGRESS', 'STATUS_HALFTIME']: continue

                loc_api = evento['competitions'][0]['competitors'][0]['team']['displayName']
                vis_api = evento['competitions'][0]['competitors'][1]['team']['displayName']
                loc_norm = normalizar(loc_api)
                
                for p in partidos_vivos:
                    id_p, loc_db, vis_db = p
                    
                    if loc_norm in normalizar(loc_db) or normalizar(loc_db) in loc_norm:
                        odds = evento['competitions'][0].get('odds', [])
                        if odds:
                            detalles = odds[0].get('details', '') 
                            over_under = odds[0].get('overUnder', 0.0)
                            
                            cierre_1x2 = 0.0
                            match_americano = re.search(r'[-+]\d{3,}', detalles)
                            if match_americano:
                                cierre_1x2 = convertir_americano_a_decimal(match_americano.group())
                            
                            cierre_ou = 1.90 if over_under > 0 else 0.0 
                            
                            cursor.execute("""
                                UPDATE partidos_backtest 
                                SET clv_registrado = 'SI', cuota_cierre_1x2 = ?, cuota_cierre_ou = ?
                                WHERE id_partido = ?
                            """, (cierre_1x2, cierre_ou, id_p))
                            conn.commit()
                            
                            msg = f"[ALERTA CLV]\nPartido en curso: {loc_db} vs {vis_db}\nLineas de Cierre capturadas."
                            enviar_telegram(msg)
                            print(f"[TRACKING] Lineas de cierre guardadas para {loc_db} vs {vis_db}")
        except requests.exceptions.RequestException as e:
            print(f"[ERROR] Fallo en la solicitud a ESPN para CLV: {e}")
        except Exception as e:
            print(f"[ERROR] Error inesperado en rastrear_clv_espn: {e}")

def main():
    print("[SISTEMA] Iniciando Sniper Bot V4.2 (Cache Persistente y SQL Seguro)...")
    
    # Precarga de Memoria (Fuera del Bucle)
    enviadas = cargar_cache_alertas()
    
    while True:
        try:
            conn = sqlite3.connect(DB_NAME, isolation_level=None)
            cursor = conn.cursor()
            cursor.execute('PRAGMA journal_mode=WAL;')
            
            cursor.execute("SELECT id_partido, local, visita, apuesta_1x2, stake_1x2, apuesta_ou, stake_ou FROM partidos_backtest WHERE estado = 'Calculado'")
            for row in cursor.fetchall():
                id_partido, local, visita, ap_1x2, stk_1x2, ap_ou, stk_ou = row
                partido = f"{local} vs {visita}"
                
                # Mercado 1X2
                if ap_1x2 and "[APOSTAR]" in ap_1x2 and stk_1x2 > 0:
                    id_alerta = f"{id_partido}_1X2"
                    if id_alerta not in enviadas:
                        msg = f"[SEÑAL 1X2]\nPartido: {partido}\nPick: {ap_1x2}\nStake: ${round(stk_1x2, 2)}"
                        enviar_telegram(msg)
                        
                        # Persistencia Continua
                        cursor.execute("INSERT OR IGNORE INTO log_alertas (id_alerta, partido, mercado, pick, stake_enviado) VALUES (?, ?, '1X2', ?, ?)", (id_alerta, partido, ap_1x2, stk_1x2))
                        enviadas.add(id_alerta)
                        print(f"[SISTEMA] Alerta 1X2 enviada y persistida para el partido: {partido}")
                        
                # Mercado O/U
                if ap_ou and "[APOSTAR]" in ap_ou and stk_ou > 0:
                    id_alerta = f"{id_partido}_OU"
                    if id_alerta not in enviadas:
                        msg = f"[SEÑAL GOLES]\nPartido: {partido}\nPick: {ap_ou}\nStake: ${round(stk_ou, 2)}"
                        enviar_telegram(msg)
                        
                        # Persistencia Continua
                        cursor.execute("INSERT OR IGNORE INTO log_alertas (id_alerta, partido, mercado, pick, stake_enviado) VALUES (?, ?, 'O/U', ?, ?)", (id_alerta, partido, ap_ou, stk_ou))
                        enviadas.add(id_alerta)
                        print(f"[SISTEMA] Alerta O/U enviada y persistida para el partido: {partido}")
            
            rastrear_clv_espn(cursor, conn)
            conn.close()
        except sqlite3.Error as e:
            print(f"[ERROR] Error de base de datos en bucle principal: {e}")
        except Exception as e:
            print(f"[ERROR] Error inesperado en bucle principal: {e}")
            
        time.sleep(60)

if __name__ == "__main__":
    main()