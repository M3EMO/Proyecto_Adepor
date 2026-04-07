import requests

MAPA_LIGAS = {
    "Argentina": "arg.1", 
    "Brasil": "bra.1", 
    "Inglaterra": "eng.1",
    "Turquia": "tur.1", 
    "Noruega": "nor.1"
}

print("📡 Extrayendo Taxonomía Oficial de ESPN...\n")

for pais, codigo in MAPA_LIGAS.items():
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{codigo}/teams"
    try:
        res = requests.get(url).json()
        equipos = res['sports'][0]['leagues'][0]['teams']
        nombres = sorted([t['team']['name'] for t in equipos])
        
        print(f"====== {pais.upper()} ======")
        for n in nombres:
            print(n)
        print("\n")
    except Exception as e:
        pass