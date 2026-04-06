import requests
import gestor_nombres

# ==========================================
# AUDITOR DE TAXONOMÍA ESPN V2.0 (INTERACTIVO)
# Responsabilidad: Cruzar la lista oficial de equipos de ESPN contra
# nuestro diccionario para detectar huecos o inconsistencias.
# ==========================================

MAPA_LIGAS = {
    "Argentina": "arg.1",
    "Brasil": "bra.1",
    "Inglaterra": "eng.1",
    "Turquia": "tur.1",
    "Noruega": "nor.1"
}

def auditar_nombres_espn():
    print("🔬 Iniciando auditoría de taxonomía interactiva (ESPN vs Diccionario Local)...")
    print("   Este script intentará resolver nombres de equipos de ESPN que no estén en tu diccionario.")
    print("   Se te pedirá confirmación o que ingreses el nombre oficial.\n")
    
    # Iterar por cada liga y cruzar datos
    for pais, codigo_liga in MAPA_LIGAS.items():
        print(f"--- Auditando Liga: {pais.upper()} ---")
        url_teams = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{codigo_liga}/teams"
        
        try:
            res_teams = requests.get(url_teams, timeout=10).json()
            equipos_api = res_teams.get('sports', [{}])[0].get('leagues', [{}])[0].get('teams', [])
            
            if not equipos_api:
                print(f"   ❌ No se encontraron equipos en la API de ESPN para la liga '{pais}'.")
                continue

            nombres_api = {t['team']['name'] for t in equipos_api}

            # El cruce: Para cada nombre de la API, el gestor lo resolverá.
            # Si es desconocido, activará el modo interactivo.
            for nombre_api in sorted(list(nombres_api)):
                gestor_nombres.obtener_nombre_estandar(nombre_api, modo_interactivo=True)
            
            print(f"   ✅ Auditoría para '{pais}' completada.")
            print("-" * (20 + len(pais)) + "\n")

        except requests.exceptions.RequestException as e:
            print(f"   ❌ Error de red al consultar la liga de {pais}: {e}")
        except (KeyError, IndexError):
            print(f"   ❌ Error: La respuesta de la API para {pais} no tiene el formato esperado.")

if __name__ == "__main__":
    auditar_nombres_espn()