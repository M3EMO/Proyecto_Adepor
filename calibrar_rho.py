# ============================================================
# calibrar_rho.py — Estimador MLE de rho por liga (Dixon-Coles)
# Camino A: datos históricos externos
# ============================================================
# Fuentes:
#   - football-data.co.uk (CSV): Inglaterra, Noruega, Turquia
#   - API-Football (JSON):       Argentina, Brasil
#
# Algoritmo MLE:
#   Para cada partido k, se estiman lambda_k y mu_k a partir
#   de los promedios INDIVIDUALES de cada equipo (goles anotados
#   en casa / fuera). Esto es crítico: usar lambda/mu de liga
#   produce rho=0 por sesgo de heterogeneidad entre equipos.
#   Con lambda_k y mu_k por equipo, el grid search MLE sobre
#   rho converge al estimador de Dixon-Coles (1997).
#
# Salida:
#   Actualiza ligas_stats.rho_calculado en fondo_quant.db.
#   motor_calculadora.py lo lee automáticamente en la próxima
#   ejecución via rho_por_liga.get(pais, RHO_FALLBACK).
# ============================================================

import math
import sqlite3
import json
import os
import requests
from config_sistema import DB_NAME, LIGAS_ESPN, API_KEY_FOOTBALL, MAPA_LIGAS_API_FOOTBALL

# --- Constantes ---
RHO_FALLBACK  = -0.09   # Fallback del sistema (Manifiesto V4.8)
RHO_MIN       = -0.30   # Limite inferior del grid search
RHO_FLOOR     = -0.03   # Floor minimo: siempre se aplica alguna correccion DC.
                         # Nota: el PL moderno (2022-25) tiene menos 0-0 que Poisson
                         # predice (4.39% obs vs 4.87% esperado), lo que implica rho~0.
                         # El floor -0.03 asegura que el modelo mantenga una correccion
                         # minima en caso de que la senal de datos sea ambigua.
MIN_PARTIDOS  = 80      # Minimo para que el MLE sea confiable
TIMEOUT_HTTP  = 20      # segundos por request

# --- Fuentes: football-data.co.uk (formato CSV antiguo) ---
# Columnas: HomeTeam, AwayTeam, FTHG (Full Time Home Goals), FTAG
FUENTES_CSV = {
    "Inglaterra": [
        "https://www.football-data.co.uk/mmz4281/2425/E0.csv",
        "https://www.football-data.co.uk/mmz4281/2324/E0.csv",
        "https://www.football-data.co.uk/mmz4281/2223/E0.csv",
    ],
    "Noruega": [
        "https://www.football-data.co.uk/mmz4281/2425/N1.csv",
        "https://www.football-data.co.uk/mmz4281/2324/N1.csv",
        "https://www.football-data.co.uk/mmz4281/2223/N1.csv",
    ],
    "Turquia": [
        "https://www.football-data.co.uk/mmz4281/2425/T1.csv",
        "https://www.football-data.co.uk/mmz4281/2324/T1.csv",
        "https://www.football-data.co.uk/mmz4281/2223/T1.csv",
    ],
}

# --- Fuentes: API-Football (para ligas sin CSV disponible) ---
# Temporadas a descargar (mas recientes primero)
TEMPORADAS_API = [2024, 2023, 2022]

# ============================================================
# Matematica: MLE de rho con estimacion de lambda/mu por equipo
# ============================================================

def _poisson_log_pmf(k, lam):
    """log P(X=k) bajo Poisson(lambda). Retorna -inf si imposible."""
    if lam <= 0 or k < 0:
        return -math.inf
    try:
        log_p = k * math.log(lam) - lam - sum(math.log(i) for i in range(1, k + 1))
        return log_p
    except (ValueError, OverflowError):
        return -math.inf


def _tau(i, j, lam, mu, rho):
    """
    Factor de correccion Dixon-Coles para marcadores bajos.
    Solo modifica las 4 celdas {(0,0),(1,0),(0,1),(1,1)}.
    """
    if i == 0 and j == 0:
        return 1.0 - lam * mu * rho
    elif i == 1 and j == 0:
        return 1.0 + mu * rho
    elif i == 0 and j == 1:
        return 1.0 + lam * rho
    elif i == 1 and j == 1:
        return 1.0 - rho
    return 1.0


def _log_verosimilitud_total(partidos_con_lm, rho):
    """
    Log-verosimilitud Dixon-Coles con lambda/mu POR PARTIDO.
    partidos_con_lm: lista de (goles_local, goles_visita, lambda_k, mu_k)
    """
    ll = 0.0
    for h, a, lam, mu in partidos_con_lm:
        t = _tau(h, a, lam, mu, rho)
        if t <= 1e-10:
            return -math.inf
        ll += math.log(t) + _poisson_log_pmf(h, lam) + _poisson_log_pmf(a, mu)
    return ll


def _estimar_lambdas_por_equipo(partidos_full):
    """
    Calcula promedios de goles anotados Y concedidos por equipo.
    Esto permite estimar lambda/mu por partido con el metodo bilineal:
        lambda_k = (scored_home[H] + conceded_away[A]) / 2
        mu_k     = (scored_away[A] + conceded_home[H]) / 2

    Incluir la defensa del rival es critico: sin ella, el MLE no puede
    separar la varianza de fuerza entre equipos de la correlacion de
    marcador, y tiende a subestimar |rho| (a veces hasta rho ~ 0).

    partidos_full: lista de (home_team, away_team, h_goals, a_goals)
    """
    stats = {}
    # sh=scored_home, ch=count_home, sa=scored_away, ca=count_away
    # cch=conceded_home, cca=conceded_away
    for ht, at, hg, ag in partidos_full:
        for eq in [ht, at]:
            if eq not in stats:
                stats[eq] = {"sh": 0, "ch": 0, "sa": 0, "ca": 0, "cch": 0, "cca": 0}
        stats[ht]["sh"]  += hg   # local anoto
        stats[ht]["cch"] += ag   # local concedio (en casa)
        stats[ht]["ch"]  += 1
        stats[at]["sa"]  += ag   # visitante anoto
        stats[at]["cca"] += hg   # visitante concedio (fuera)
        stats[at]["ca"]  += 1

    n = len(partidos_full)
    league_avg_h = sum(hg for _, _, hg, _ in partidos_full) / n
    league_avg_a = sum(ag for _, _, _, ag in partidos_full) / n

    scored_home    = {}  # goles que anota jugando en casa
    scored_away    = {}  # goles que anota jugando fuera
    conceded_home  = {}  # goles que concede jugando en casa
    conceded_away  = {}  # goles que concede jugando fuera

    for eq, s in stats.items():
        scored_home[eq]   = s["sh"]  / s["ch"] if s["ch"] > 0 else league_avg_h
        conceded_home[eq] = s["cch"] / s["ch"] if s["ch"] > 0 else league_avg_a
        scored_away[eq]   = s["sa"]  / s["ca"] if s["ca"] > 0 else league_avg_a
        conceded_away[eq] = s["cca"] / s["ca"] if s["ca"] > 0 else league_avg_h

    return scored_home, scored_away, conceded_home, conceded_away, league_avg_h, league_avg_a


def estimar_rho_mle(partidos_full):
    """
    Estima rho via grid search MLE sobre [-0.30, 0.00] con paso 0.001.

    Por que lambda/mu por equipo (y no promedio de liga):
        Usar un solo lambda/mu promedio subestima la varianza real
        del marcador (los partidos desiguales generan 0-3, 4-0, etc.
        que la distribucion Poisson uniforme no puede explicar sin
        asignar rho positivo). Esto provoca que el MLE converja a
        rho ~ 0 aunque el verdadero valor sea -0.09.
        Con lambda_k especifico para cada partido, el MLE captura
        correctamente la correlacion de bajo marcador.

    Retorna None si N < MIN_PARTIDOS.
    """
    n = len(partidos_full)
    if n < MIN_PARTIDOS:
        return None

    scored_home, scored_away, conceded_home, conceded_away, lav_h, lav_a = _estimar_lambdas_por_equipo(partidos_full)

    # Construir lista con (h, a, lambda_k, mu_k) por partido
    # Metodo bilineal: promedia ataque del local + defensa del visitante
    partidos_lm = []
    for ht, at, hg, ag in partidos_full:
        lam = (scored_home.get(ht, lav_h) + conceded_away.get(at, lav_h)) / 2
        mu  = (scored_away.get(at, lav_a) + conceded_home.get(ht, lav_a)) / 2
        lam = max(lam, 0.1)  # evitar lambda=0 (equipos con pocos datos)
        mu  = max(mu,  0.1)
        partidos_lm.append((hg, ag, lam, mu))

    mejor_rho = RHO_FALLBACK
    mejor_ll  = -math.inf

    pasos = int((0.0 - RHO_MIN) * 1000) + 1
    for k in range(pasos):
        rho_c = round(RHO_MIN + k * 0.001, 4)
        ll = _log_verosimilitud_total(partidos_lm, rho_c)
        if ll > mejor_ll:
            mejor_ll = ll
            mejor_rho = rho_c

    return mejor_rho


# ============================================================
# Descarga y parseo: football-data.co.uk (CSV)
# ============================================================

def _parsear_csv(texto):
    """
    Parsea CSV de football-data.co.uk (formato antiguo).
    Retorna lista de (home_team, away_team, home_goals, away_goals).
    Solo incluye filas con resultado completo.
    """
    lineas = texto.strip().splitlines()
    if not lineas:
        return []

    sep = ";" if lineas[0].count(";") > lineas[0].count(",") else ","
    encabezado = [c.strip().strip('"') for c in lineas[0].split(sep)]

    # Buscar columnas de equipos y goles
    candidatos_ht = ["HomeTeam", "Home", "home_team"]
    candidatos_at = ["AwayTeam", "Away", "away_team"]
    candidatos_hg = ["FTHG", "HG", "home_score"]
    candidatos_ag = ["FTAG", "AG", "away_score"]

    col_ht = next((c for c in candidatos_ht if c in encabezado), None)
    col_at = next((c for c in candidatos_at if c in encabezado), None)
    col_hg = next((c for c in candidatos_hg if c in encabezado), None)
    col_ag = next((c for c in candidatos_ag if c in encabezado), None)

    if not all([col_ht, col_at, col_hg, col_ag]):
        return []

    idx = {c: encabezado.index(c) for c in [col_ht, col_at, col_hg, col_ag]}
    max_idx = max(idx.values())

    partidos = []
    for linea in lineas[1:]:
        cols = linea.split(sep)
        if len(cols) <= max_idx:
            continue
        try:
            ht = cols[idx[col_ht]].strip().strip('"')
            at = cols[idx[col_at]].strip().strip('"')
            hg = int(float(cols[idx[col_hg]].strip().strip('"')))
            ag = int(float(cols[idx[col_ag]].strip().strip('"')))
            if ht and at:
                partidos.append((ht, at, hg, ag))
        except (ValueError, IndexError):
            continue

    return partidos


def descargar_partidos_csv(liga, urls):
    """Descarga y acumula partidos de URLs de football-data.co.uk."""
    todos = []
    for url in urls:
        try:
            resp = requests.get(url, timeout=TIMEOUT_HTTP)
            if resp.status_code != 200:
                print(f"   [SKIP] HTTP {resp.status_code} -> {url}")
                continue
            try:
                texto = resp.content.decode("utf-8")
            except UnicodeDecodeError:
                texto = resp.content.decode("latin-1")

            partidos = _parsear_csv(texto)
            if partidos:
                print(f"   [OK] {len(partidos)} partidos <- {url}")
                todos.extend(partidos)
            else:
                print(f"   [VACÍO] No se encontraron columnas válidas -> {url}")
        except requests.exceptions.RequestException as e:
            print(f"   [ERROR RED] {url}: {e}")
    return todos


# ============================================================
# Descarga y parseo: API-Football (JSON)
# ============================================================

def descargar_partidos_api_football(liga_nombre, temporadas, api_key_override=None):
    """
    Descarga partidos históricos desde API-Sports / API-Football.
    Endpoint: https://v3.football.api-sports.io/ (nuevo desde 2024)
    Header:   x-apisports-key (reemplaza x-rapidapi-key)
    Liga ID sacado de MAPA_LIGAS_API_FOOTBALL.
    """
    key = api_key_override or API_KEY_FOOTBALL
    if not key:
        print("   [SKIP] api_key_football no configurada en config.json")
        return []

    liga_id = MAPA_LIGAS_API_FOOTBALL.get(liga_nombre)
    if not liga_id:
        print(f"   [SKIP] {liga_nombre} no está en MAPA_LIGAS_API_FOOTBALL")
        return []

    # Nota: el endpoint v3.api-football.com fue deprecado.
    # El nuevo host es v3.football.api-sports.io con header x-apisports-key.
    headers = {"x-apisports-key": key}
    todos = []

    for temporada in temporadas:
        url = "https://v3.football.api-sports.io/fixtures"
        params = {"league": liga_id, "season": temporada, "status": "FT"}
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            if resp.status_code != 200:
                print(f"   [SKIP] API-Football HTTP {resp.status_code} temporada {temporada}")
                continue

            data = resp.json()
            fixtures = data.get("response", [])

            if not fixtures:
                print(f"   [SKIP] API-Football: 0 fixtures para temporada {temporada}")
                continue

            partidos = []
            for f in fixtures:
                try:
                    ht = f["teams"]["home"]["name"]
                    at = f["teams"]["away"]["name"]
                    hg = f["goals"]["home"]
                    ag = f["goals"]["away"]
                    if hg is not None and ag is not None:
                        partidos.append((ht, at, int(hg), int(ag)))
                except (KeyError, TypeError):
                    continue

            print(f"   [OK] {len(partidos)} partidos <- API-Football {liga_nombre} {temporada}")
            todos.extend(partidos)

        except requests.exceptions.RequestException as e:
            print(f"   [ERROR RED] API-Football temporada {temporada}: {e}")

    return todos


# ============================================================
# Actualizacion de la DB
# ============================================================

def actualizar_rho_en_db(resultados):
    """Actualiza rho_calculado en ligas_stats para cada liga."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ligas_stats (
            liga TEXT PRIMARY KEY,
            total_partidos INTEGER DEFAULT 0,
            empates INTEGER DEFAULT 0,
            rho_calculado REAL DEFAULT -0.09,
            total_goles INTEGER DEFAULT 0,
            total_corners INTEGER DEFAULT 0,
            coef_corner_calculado REAL DEFAULT 0.02
        )
    """)
    for liga, rho in resultados.items():
        cursor.execute("""
            INSERT INTO ligas_stats (liga, rho_calculado)
            VALUES (?, ?)
            ON CONFLICT(liga) DO UPDATE SET rho_calculado = excluded.rho_calculado
        """, (liga, rho))
        print(f"   DB actualizada: {liga} -> rho_calculado = {rho}")
    conn.commit()
    conn.close()


# ============================================================
# Main
# ============================================================

def main():
    print("=" * 62)
    print("calibrar_rho.py  —  Estimacion MLE de rho por liga")
    print("MLE con lambda/mu especifico por equipo (Dixon-Coles 1997)")
    print("=" * 62)

    ligas_activas = set(LIGAS_ESPN.values())
    resultados = {}

    # --- Ligas con datos CSV (football-data.co.uk) ---
    for liga, urls in FUENTES_CSV.items():
        if liga not in ligas_activas:
            continue
        print(f"\n[{liga}] Fuente: football-data.co.uk")
        partidos = descargar_partidos_csv(liga, urls)
        _procesar_liga(liga, partidos, resultados)

    # --- Ligas sin CSV: usar API-Football ---
    ligas_sin_csv = ligas_activas - set(FUENTES_CSV.keys())
    for liga in sorted(ligas_sin_csv):
        print(f"\n[{liga}] Fuente: API-Football")
        partidos = descargar_partidos_api_football(liga, TEMPORADAS_API)
        _procesar_liga(liga, partidos, resultados)

    # --- Resumen ---
    print("\n" + "=" * 62)
    print("Resumen de rho estimados por liga:")
    for liga in sorted(resultados.keys()):
        rho = resultados[liga]
        origen = "FALLBACK" if rho == RHO_FALLBACK else "MLE"
        print(f"   {liga:15s}: {rho:+.4f}  [{origen}]")

    print("\nActualizando base de datos...")
    actualizar_rho_en_db(resultados)

    print("\n[HECHO] rho_calculado actualizado en ligas_stats.")
    print("motor_calculadora.py lo leerá en la próxima ejecución.")
    print("=" * 62)


def _procesar_liga(liga, partidos, resultados):
    """Corre MLE sobre los partidos y guarda el resultado."""
    if not partidos:
        print(f"   [FALLBACK] Sin datos. rho = {RHO_FALLBACK}")
        resultados[liga] = RHO_FALLBACK
        return

    n = len(partidos)
    goles_loc = [hg for _, _, hg, _ in partidos]
    goles_vis = [ag for _, _, _, ag in partidos]
    lam_avg = sum(goles_loc) / n
    mu_avg  = sum(goles_vis) / n
    empates = sum(1 for _, _, hg, ag in partidos if hg == ag)

    print(f"   Total: {n} partidos | avg_goles_L={lam_avg:.3f} | avg_goles_V={mu_avg:.3f} | empates={empates} ({100*empates/n:.1f}%)")

    rho = estimar_rho_mle(partidos)
    if rho is None:
        print(f"   [FALLBACK] Solo {n} partidos (min={MIN_PARTIDOS}). rho = {RHO_FALLBACK}")
        resultados[liga] = RHO_FALLBACK
    else:
        rho_final = min(rho, RHO_FLOOR)   # rho siempre <= -0.03 (floor negativo)
        if rho > RHO_FLOOR:
            print(f"   [INFO] MLE dio rho={rho} (>= floor {RHO_FLOOR}). Aplicando floor.")
            print(f"          Interpretacion: datos empiricos sugieren rho cercano a 0 en")
            print(f"          esta liga/temporadas. El floor garantiza correccion DC minima.")
        elif rho < -0.25:
            print(f"   [ADVERTENCIA] rho={rho} muy negativo. Revisar calidad de datos.")
        print(f"   [MLE] rho estimado = {rho}  ->  rho final (con floor) = {rho_final}")
        resultados[liga] = rho_final


if __name__ == "__main__":
    main()
