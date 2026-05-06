"""Nichos sostenibles cross-anio."""
import sqlite3, json, math, re, unicodedata
from collections import defaultdict
from pathlib import Path

DB = Path(__file__).parent.parent / "fondo_quant.db"
EV_MIN = 1.03

def norm(s):
    if not s: return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii","ignore").decode().lower()
    s = re.sub(r"[\s\.\-_]+", "", s).replace(chr(39), "")
    return re.sub(r"[^a-z0-9]", "", s)

def cargar_universo():
    con = sqlite3.connect(str(DB))
    con.create_function("norm", 1, norm)
    c = con.cursor()
    SQ = chr(39)
    q = (
        "WITH match_a AS ("
        " SELECT p.id AS pid, p.liga, p.temp, p.fecha_partido, p.ht, p.at, p.outcome,"
        " p.prob_1, p.prob_x, p.prob_2,"
        " f.cuota_1, f.cuota_x, f.cuota_2"
        " FROM predicciones_walkforward p"
        " JOIN stats_partido_espn s ON p.liga=s.liga AND substr(p.fecha_partido,1,10)=s.fecha"
        " AND norm(p.ht)=norm(s.ht) AND norm(p.at)=norm(s.at)"
        " JOIN cuotas_historicas_fdco f ON s.liga=f.liga AND s.fecha_fdco=f.fecha"
        " AND s.ht_fdco_norm=f.equipo_local_norm AND s.at_fdco_norm=f.equipo_visita_norm"
        " WHERE f.cuota_1 IS NOT NULL AND p.fuente=" + SQ + "walk_forward_persistente" + SQ
        + "), match_b AS ("
        + " SELECT p.id AS pid, p.liga, p.temp, p.fecha_partido, p.ht, p.at, p.outcome,"
        + " p.prob_1, p.prob_x, p.prob_2,"
        + " f.cuota_1, f.cuota_x, f.cuota_2"
        + " FROM predicciones_walkforward p"
        + " JOIN cuotas_historicas_fdco f ON p.liga=f.liga AND substr(p.fecha_partido,1,10)=f.fecha"
        + " AND norm(p.ht)=norm(f.equipo_local) AND norm(p.at)=norm(f.equipo_visita)"
        + " WHERE f.cuota_1 IS NOT NULL AND p.fuente=" + SQ + "walk_forward_persistente" + SQ
        + "), unionall AS (SELECT * FROM match_a UNION SELECT * FROM match_b)"
        + " SELECT pid, liga, temp, fecha_partido, ht, at, outcome,"
        + " prob_1, prob_x, prob_2, cuota_1, cuota_x, cuota_2"
        + " FROM unionall GROUP BY pid"
    )
    rows = c.execute(q).fetchall()
    con.close()
    return rows


def calcular_picks(rows):
    picks = []
    for r in rows:
        pid, liga, temp, fecha, ht, at, outcome, p1, px, p2, c1, cx, c2 = r
        if any(v is None for v in (p1, px, p2, c1, cx, c2)): continue
        opts = [("1", p1, c1), ("X", px, cx), ("V", p2, c2)]
        pick_label, pick_prob, pick_cuota = max(opts, key=lambda x: x[1])
        ev = pick_prob * pick_cuota
        if ev < EV_MIN: continue
        outcome_v0 = "V" if outcome == "2" else outcome
        acerto = 1 if pick_label == outcome_v0 else 0
        profit = (pick_cuota - 1.0) if acerto else -1.0
        mes = int(fecha[5:7]) if fecha and len(fecha) >= 7 else 0
        if mes in (1,2,3): bin4 = 1
        elif mes in (4,5,6): bin4 = 2
        elif mes in (7,8,9): bin4 = 3
        else: bin4 = 4
        if pick_cuota < 1.5: banda = "<1.5"
        elif pick_cuota < 2.0: banda = "1.5-2.0"
        elif pick_cuota < 2.5: banda = "2.0-2.5"
        elif pick_cuota < 3.0: banda = "2.5-3.0"
        elif pick_cuota < 4.0: banda = "3.0-4.0"
        else: banda = "4.0+"
        picks.append({"pid":pid,"liga":liga,"temp":temp,"fecha":fecha,"ht":ht,"at":at,
                      "pick":pick_label,"cuota":pick_cuota,"prob":pick_prob,"ev":ev,
                      "acerto":acerto,"profit":profit,"mes":mes,"bin4":bin4,"banda":banda})
    return picks

def yield_de(grupo):
    if not grupo: return None
    n = len(grupo)
    profit = sum(g["profit"] for g in grupo)
    aciertos = sum(g["acerto"] for g in grupo)
    return {"N":n,"aciertos":aciertos,"hit":aciertos/n,"profit_total":profit,
            "yield":profit/n,"cuota_avg":sum(g["cuota"] for g in grupo)/n}

def evaluar_sost(grupo, dim, desc):
    is_grp = [g for g in grupo if g["temp"] in (2022,2023,2024)]
    m = yield_de(is_grp)
    if not m or m["N"] < 15: return None
    if m["yield"] < 0.10: return None
    py = {}
    for y in (2022,2023,2024):
        sub = [g for g in is_grp if g["temp"]==y]
        py[y] = yield_de(sub)
    av = sum(1 for y in (2022,2023,2024) if py[y] and py[y]["N"]>=5 and py[y]["yield"]>0)
    if av < 2: return None
    sub26 = [g for g in grupo if g["temp"]==2026]
    m26 = yield_de(sub26) if sub26 else None
    py_out = {}
    for y,v in py.items():
        if v: py_out[str(y)] = {"N":v["N"], "yield":round(v["yield"],4), "hit":round(v["hit"],4)}
        else: py_out[str(y)] = None
    p26_out = None
    if m26 and m26["N"]>0:
        p26_out = {"N":m26["N"],"yield":round(m26["yield"],4),"hit":round(m26["hit"],4)}
    return {"dimension":dim,"descripcion":desc,"N_IS":m["N"],
            "yield_IS":round(m["yield"],4),"hit_IS":round(m["hit"],4),
            "cuota_avg":round(m["cuota_avg"],3),"aciertos":m["aciertos"],
            "profit_total":round(m["profit_total"],3),"aniosvalidos":av,
            "por_year":py_out,"parcial_2026":p26_out,
            "priority_score":round(m["yield"]*math.sqrt(m["N"]),4)}

def detectar_trampa(grupo, dim, desc):
    is_grp = [g for g in grupo if g["temp"] in (2022,2023,2024)]
    m = yield_de(is_grp)
    if not m or m["N"] < 15: return None
    if m["yield"] < 0.10: return None
    av = 0
    for y in (2022,2023,2024):
        sub = [g for g in is_grp if g["temp"]==y]
        mm = yield_de(sub)
        if mm and mm["N"]>=5 and mm["yield"]>0: av += 1
    if av >= 2: return None
    return {"dimension":dim,"descripcion":desc,"N_IS":m["N"],
            "yield_IS_aparente":round(m["yield"],4),"aniosvalidos":av}


def main():
    print("Cargando universo...")
    rows = cargar_universo()
    print("  predicciones matched a cuotas:", len(rows))
    print("Calculando picks V0 con EV>=1.03...")
    picks = calcular_picks(rows)
    print("  picks apostables:", len(picks))
    by_year = defaultdict(int)
    for p in picks: by_year[p["temp"]] += 1
    print("  distribucion:", dict(sorted(by_year.items())))
    candidatos = []
    trampas = []
    def proc(grupos, dim):
        for k, g in grupos.items():
            desc = "{} {}".format(dim, k)
            s = evaluar_sost(g, dim, desc)
            if s: candidatos.append(s)
            else:
                t = detectar_trampa(g, dim, desc)
                if t: trampas.append(t)
    grupos = defaultdict(list)
    for p in picks:
        if p["pick"]=="1": grupos[(p["liga"], p["ht"])].append(p)
    proc(grupos, "EQUIPO_LOCAL")
    grupos = defaultdict(list)
    for p in picks:
        if p["pick"]=="V": grupos[(p["liga"], p["at"])].append(p)
    proc(grupos, "EQUIPO_VISITA")
    grupos = defaultdict(list)
    for p in picks:
        if p["pick"]=="X": grupos[(p["liga"], p["ht"])].append(p)
    proc(grupos, "EQUIPO_LOCAL_X")
    grupos = defaultdict(list)
    for p in picks: grupos[(p["liga"], p["bin4"])].append(p)
    proc(grupos, "LIGA_BIN4")
    grupos = defaultdict(list)
    for p in picks: grupos[(p["liga"], p["banda"])].append(p)
    proc(grupos, "LIGA_BANDA")
    grupos = defaultdict(list)
    for p in picks: grupos[(p["liga"], p["mes"])].append(p)
    proc(grupos, "LIGA_MES")
    grupos = defaultdict(list)
    for p in picks: grupos[(p["liga"], p["pick"])].append(p)
    proc(grupos, "LIGA_PICK")
    grupos = defaultdict(list)
    for p in picks: grupos[(p["liga"], p["pick"], p["banda"])].append(p)
    proc(grupos, "LIGA_PICK_BANDA")
    grupos = defaultdict(list)
    for p in picks: grupos[(p["liga"], p["bin4"], p["pick"])].append(p)
    proc(grupos, "LIGA_BIN4_PICK")
    candidatos.sort(key=lambda x: x["priority_score"], reverse=True)
    print()
    print("=== CANDIDATOS SOSTENIBLES: {} ===".format(len(candidatos)))
    for i, c in enumerate(candidatos[:30], 1):
        py = c["por_year"]
        print("{:2d}. [{}] {}".format(i, c["dimension"], c["descripcion"]))
        print("     N={} yield={:+.3f} hit={:.3f} cuota_avg={} score={}".format(
            c["N_IS"], c["yield_IS"], c["hit_IS"], c["cuota_avg"], c["priority_score"]))
        for y in ("2022","2023","2024"):
            if py[y]:
                print("       {}: N={:3d} yield={:+.3f} hit={:.3f}".format(
                    y, py[y]["N"], py[y]["yield"], py[y]["hit"]))
        if c["parcial_2026"]:
            p26 = c["parcial_2026"]
            print("       2026 (parcial): N={:3d} yield={:+.3f} hit={:.3f}".format(
                p26["N"], p26["yield"], p26["hit"]))
    print()
    print("=== TRAMPAS ONE-SHOT: {} ===".format(len(trampas)))
    trampas.sort(key=lambda x: x["yield_IS_aparente"], reverse=True)
    for i, t in enumerate(trampas[:15], 1):
        print("{:2d}. [{}] {} N={} yield_aparente={:+.3f} (av={})".format(
            i, t["dimension"], t["descripcion"], t["N_IS"],
            t["yield_IS_aparente"], t["aniosvalidos"]))
    out_json = Path(__file__).parent / "nichos_sostenibles_universo_expandido.json"
    out_json.write_text(json.dumps({
        "universe_size": len(rows),
        "picks_apostables_total": len(picks),
        "distribucion_year": dict(sorted(by_year.items())),
        "top_sostenibles": candidatos[:30],
        "trampas": trampas[:30],
        "criterio": "yield_IS>=0.10 N>=15 + 2/3 anios N>=5 yield>0",
        "EV_min": EV_MIN
    }, indent=2, default=str))
    print()
    print("JSON guardado:", out_json)
    return candidatos, trampas, len(picks), len(rows)

if __name__ == "__main__":
    main()
