"""
Dashboard Adepor (Streamlit, local). Reemplaza el workbook Excel.

Lanzar: ./iniciar_dashboard.sh  (solo 127.0.0.1, sin red externa).
Los loaders son funciones puras: se prueban sin Streamlit corriendo.
"""
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from src.comun.config_motor import get_param
from src.comun.config_sistema import DB_NAME
from src.comun.picks import cuota_para_pick
from src.comun.reglas_actuales import evaluar_actual, evaluar_actual_ou
from src.comun.resolucion import determinar_resultado_entero
from src.comun.tiempo import ahora_art
from src.persistencia.confirmaciones import confirmar_apuesta, ids_confirmados
from src.persistencia.excel_formulas import cuota_1x2, cuota_ou
from src.persistencia.excel_hoja_resimulacion import _stake_kelly
from src.persistencia.excel_metricas import _pl_apuesta, calcular_metricas_dashboard
from src.persistencia.motor_sincronizador import (
    _cargar_apuestas_live, _cargar_aportes, _cargar_partidos, _leer_configuracion,
)
from src.persistencia.yield_potencial import apuestas_potenciales, yield_potencial

TABS = ["Picks vivos", "Dinero real", "Yield potencial", "Historial",
        "Resumen por liga", "Sombra", "Si hubiera"]
CAMINOS = ("C1", "C2", "C2B", "C3", "C4", "OU")


# ============================================================================
# LOADERS (puros: reciben conexion o listas, devuelven datos)
# ============================================================================
def conectar_ro():
    """Conexion de solo lectura a la DB del pipeline (respeta ADEPOR_DB)."""
    return sqlite3.connect(Path(DB_NAME).resolve().as_uri() + "?mode=ro", uri=True)


def _fecha_dt(raw):
    s = str(raw or "").strip()
    for fmt in ("%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _fecha_txt(raw):
    d = _fecha_dt(raw)
    return d.strftime("%d/%m/%Y") if d else str(raw or "")[:10]


def _pl_pick(estado, ap, stk, cuota, gl, gv):
    """P/L real de un mercado. None si no hay apuesta liquidada valorable."""
    if estado != "Liquidado" or not ap or not stk or stk <= 0 or gl is None or gv is None:
        return None
    res = determinar_resultado_entero(ap, gl, gv)
    return None if res == 0 else _pl_apuesta(res, stk, cuota or 0)


def apuestas_reales(datos):
    """Apuestas liquidadas con stake > 0, con la formula de excel_metricas."""
    out = []
    for r in datos:
        estado, gl, gv = r[19], r[20], r[21]
        for ap, stk, cuota in ((r[10], r[12], cuota_1x2(r[10], r[14], r[15], r[16])),
                               (r[11], r[13], cuota_ou(r[11], r[17], r[18]))):
            pl = _pl_pick(estado, ap, stk, cuota, gl, gv)
            if pl is not None:
                out.append({"fecha": str(r[1] or ""), "pl": pl})
    return out


def equity_df(datos, aportes, bankroll_base):
    """Bankroll base + P/L real + aportes, en orden de fecha."""
    eventos = [(a["fecha"], a["pl"]) for a in apuestas_reales(datos)]
    eventos += [(str(f), float(m)) for f, m in aportes]
    eventos.sort(key=lambda e: e[0])
    filas, acum = [{"n": 0, "fecha": "", "equity": float(bankroll_base)}], float(bankroll_base)
    for i, (f, delta) in enumerate(eventos, 1):
        acum += delta
        filas.append({"n": i, "fecha": _fecha_txt(f), "equity": acum})
    return pd.DataFrame(filas)


def estado_confirmaciones(con):
    """Set de (id_partido, mercado) confirmados. Alertas legacy cuentan en ambos mercados."""
    conf = set()
    try:
        conf.update(con.execute("SELECT id_partido, mercado FROM apuestas_confirmadas").fetchall())
    except sqlite3.OperationalError:
        pass  # la tabla se crea en la primera confirmacion
    con_tabla = {i for i, _ in conf}
    for id_p in ids_confirmados(con.cursor()) - con_tabla:
        conf.update({(id_p, "1X2"), (id_p, "OU")})
    return conf


def picks_vivos(datos, confirmados=frozenset()):
    """Picks [APOSTAR] de partidos que no empezaron. Incluye pretest (stake sugerido 0):
    el usuario decide el stake al confirmar."""
    ahora = ahora_art().strftime("%Y-%m-%d %H:%M")
    out = []
    for r in datos:
        id_p, fecha, local, visita, pais = r[0:5]
        estado, gl = r[19], r[20]
        if estado == "Liquidado" or gl is not None or str(fecha or "") <= ahora:
            continue
        mercados = (
            ("1X2", r[10], r[12], {"LOCAL": r[5], "EMPATE": r[6], "VISITA": r[7]}),
            ("OU", r[11], r[13], {"OVER 2.5": r[8], "UNDER 2.5": r[9]}),
        )
        for mercado, ap, stk, probs in mercados:
            if not str(ap or "").startswith("[APOSTAR]"):
                continue
            pick = str(ap)[len("[APOSTAR]"):].strip().upper()
            cuota = cuota_para_pick(ap, r[14], r[15], r[16], r[17], r[18])
            prob = probs.get(pick)
            if prob is None or cuota <= 1:
                continue
            out.append({
                "id": id_p, "mercado": mercado, "pais": pais, "fecha": _fecha_txt(fecha),
                "orden": str(fecha or ""), "partido": f"{local} vs {visita}", "pick": pick,
                "cuota": cuota, "prob_modelo": prob, "prob_mercado": 1 / cuota,
                "ev_pct": (prob * cuota - 1) * 100, "stake": stk or 0.0,
                "confirmada": (id_p, mercado) in confirmados,
            })
    out.sort(key=lambda p: p["orden"])
    return out


def historial_df(datos):
    """Una fila por partido, como la hoja Backtest. P/L neto de ambos mercados."""
    filas = []
    for r in datos:
        estado, gl, gv = r[19], r[20], r[21]
        ap1, apou, stk1, stko = r[10], r[11], r[12], r[13]
        c1, cx, c2, co, cu = r[14:19]
        pls = [_pl_pick(estado, ap1, stk1, cuota_1x2(ap1, c1, cx, c2), gl, gv),
               _pl_pick(estado, apou, stko, cuota_ou(apou, co, cu), gl, gv)]
        validos = [x for x in pls if x is not None]
        d = _fecha_dt(r[1])
        filas.append({
            "fecha_dt": pd.Timestamp(d) if d else pd.NaT,
            "Fecha": _fecha_txt(r[1]), "Liga": r[4], "Partido": f"{r[2]} vs {r[3]}",
            "Goles": f"{gl}-{gv}" if gl is not None and gv is not None else "",
            "Estado": estado,
            "Prob 1 %": round((r[5] or 0) * 100, 1), "Prob X %": round((r[6] or 0) * 100, 1),
            "Prob 2 %": round((r[7] or 0) * 100, 1),
            "Cuota 1": c1, "Cuota X": cx, "Cuota 2": c2,
            "Apuesta 1X2": ap1 or "", "Stake 1X2": stk1 or 0,
            "Apuesta O/U": apou or "", "Stake O/U": stko or 0,
            "P/L neto": sum(validos) if validos else None,
        })
    df = pd.DataFrame(filas, columns=["fecha_dt", "Fecha", "Liga", "Partido", "Goles", "Estado",
                                      "Prob 1 %", "Prob X %", "Prob 2 %", "Cuota 1", "Cuota X",
                                      "Cuota 2", "Apuesta 1X2", "Stake 1X2", "Apuesta O/U",
                                      "Stake O/U", "P/L neto"])
    return df.sort_values("fecha_dt", ascending=False, na_position="last").reset_index(drop=True)


def filas_yield(cur):
    """Filas crudas de partidos_backtest para el yield potencial."""
    cur.execute("SELECT pais, fecha, apuesta_1x2, apuesta_ou, cuota_1, cuota_x, cuota_2, "
                "cuota_o25, cuota_u25 FROM partidos_backtest")
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, fila)) for fila in cur.fetchall()]


def curva_yield_df(filas):
    """Yield acumulado a 1 unidad por apuesta, en orden de fecha."""
    ap = sorted(apuestas_potenciales(filas), key=lambda a: str(a["fecha"] or ""))
    acum, out = 0.0, []
    for i, a in enumerate(ap, 1):
        acum += a["pl"]
        out.append({"n": i, "fecha": _fecha_txt(a["fecha"]), "pl_acum": acum})
    return pd.DataFrame(out, columns=["n", "fecha", "pl_acum"])


def resumen_liga_df(datos, fk, live):
    """Una fila por liga y total. Usa calcular_metricas_dashboard (stake > 0, liquidado)."""
    filas = []
    for pais in sorted({r[4] for r in datos if r[4]}):
        t = calcular_metricas_dashboard([r for r in datos if r[4] == pais], fk)["total"]
        filas.append(_fila_resumen(pais, t, "LIVE" if live.get(pais) else "pretest"))
    filas.append(_fila_resumen("TOTAL", calcular_metricas_dashboard(datos, fk)["total"], ""))
    return pd.DataFrame(filas)


def _fila_resumen(nombre, t, estado):
    n = t["n"]
    g = round(t["acierto_bets"] * n) if n else 0
    return {"Liga": nombre, "Apuestas": n, "Ganadas": g, "Perdidas": n - g,
            "% Acierto": t["acierto_bets"] if n else None, "P/L $": t["pl"],
            "Yield": t["yield"] if n else None, "Volumen $": t["vol"], "Estado": estado}


def sombra(datos):
    """Op1 (activa) vs Op4 (shadow) por partido, como la hoja Sombra."""
    acum = {"op1": {"n": 0, "g": 0, "vol": 0.0, "pl": 0.0},
            "op4": {"n": 0, "g": 0, "vol": 0.0, "pl": 0.0}}
    filas = []
    for r in datos:
        estado, gl, gv = r[19], r[20], r[21]
        c1, cx, c2 = r[14:17]
        ap1, stk1, ap4, stk4 = r[10], r[12], r[24], r[25]
        t1 = bool(stk1 and stk1 > 0 and _es_pick(ap1))
        t4 = bool(stk4 and stk4 > 0 and _es_pick(ap4))
        if not (t1 or t4):
            continue
        res1, pl1 = _op_sombra(estado, t1, ap1, stk1, c1, cx, c2, gl, gv, acum["op1"])
        res4, pl4 = _op_sombra(estado, t4, ap4, stk4, c1, cx, c2, gl, gv, acum["op4"])
        filas.append({
            "Fecha": _fecha_txt(r[1]), "Partido": f"{r[2]} vs {r[3]}", "Liga": r[4],
            "Apuesta Op1": ap1 or "-", "Stake Op1": stk1 if t1 else None,
            "Resultado Op1": res1, "P/L Op1": pl1,
            "Apuesta Op4": ap4 or "-", "Stake Op4": stk4 if t4 else None,
            "Resultado Op4": res4, "P/L Op4": pl4,
            "Dif P/L": pl1 - pl4 if pl1 is not None and pl4 is not None else None,
        })
    cols = ["Fecha", "Partido", "Liga", "Apuesta Op1", "Stake Op1", "Resultado Op1", "P/L Op1",
            "Apuesta Op4", "Stake Op4", "Resultado Op4", "P/L Op4", "Dif P/L"]
    return {"filas": pd.DataFrame(filas, columns=cols), **acum}


def _es_pick(ap):
    return any(t in str(ap or "") for t in ("[APOSTAR]", "[GANADA]", "[PERDIDA]"))


def _op_sombra(estado, tiene, ap, stk, c1, cx, c2, gl, gv, stats):
    """Resultado y P/L de una opcion. Acumula n, g, vol y pl en stats."""
    if not tiene:
        return "-", None
    if estado != "Liquidado":
        return "PENDIENTE", None
    pl = _pl_pick(estado, ap, stk, cuota_1x2(ap, c1, cx, c2), gl, gv)
    if pl is None:
        return "-", None
    gana = pl > 0
    stats["n"] += 1
    stats["g"] += int(gana)
    stats["vol"] += stk
    stats["pl"] += pl
    return ("GANADA" if gana else "PERDIDA"), pl


def simular_si_hubiera(datos, bankroll, fraccion_kelly, max_kelly_pct):
    """Resimula todo el historico con las reglas actuales. IN-SAMPLE. Compounding."""
    real = defaultdict(dict)
    candidatos = []
    for r in datos:
        estado, gl, gv = r[19], r[20], r[21]
        if estado != "Liquidado" or gl is None or gv is None:
            continue
        pais, fecha, local, visita = r[4], r[1], r[2], r[3]
        p1, px, p2, po, pu = r[5], r[6], r[7], r[8], r[9]
        c1, cx, c2, co, cu = r[14], r[15], r[16], r[17], r[18]
        ap_real, ap_ou = str(r[10] or ""), str(r[11] or "")
        xg_l = r[26] if len(r) > 26 else None
        xg_v = r[27] if len(r) > 27 else None
        tiene_1x2 = all(isinstance(x, (int, float)) and x > 0 for x in [p1, px, p2, c1, cx, c2])
        tiene_ou = all(isinstance(x, (int, float)) and x > 0 for x in [po, pu, co, cu])

        if tiene_1x2 and ("[GANADA]" in ap_real or "[PERDIDA]" in ap_real):
            _sumar_real(real[pais], "[GANADA]" in ap_real)
        if "[GANADA]" in ap_ou or "[PERDIDA]" in ap_ou:
            _sumar_real(real[pais], "[GANADA]" in ap_ou)

        if tiene_1x2:
            pick, cuota, camino = evaluar_actual(p1, px, p2, c1, cx, c2, pais)
            if pick is not None:
                gana = ((pick == "LOCAL" and gl > gv) or (pick == "EMPATE" and gl == gv)
                        or (pick == "VISITA" and gl < gv))
                candidatos.append(_candidato(fecha, local, visita, pais, pick, cuota, camino,
                                             "1X2", gl, gv, gana,
                                             {"LOCAL": p1, "EMPATE": px, "VISITA": p2}[pick]))
        if tiene_ou:
            pick_ou, cuota_o, _ = evaluar_actual_ou(po, pu, co, cu, xg_l, xg_v)
            if pick_ou is not None:
                total = gl + gv
                gana = (pick_ou == "OVER 2.5" and total > 2.5) or (pick_ou == "UNDER 2.5" and total < 2.5)
                candidatos.append(_candidato(fecha, local, visita, pais, pick_ou, cuota_o, "OU",
                                             "O/U", gl, gv, gana,
                                             po if pick_ou == "OVER 2.5" else pu))

    picks, bank = [], float(bankroll)
    for p in sorted(candidatos, key=lambda x: str(x["fecha_raw"] or "")):
        stake = _stake_kelly(p["prob"], p["cuota"], bank, fraccion_kelly, max_kelly_pct)
        if stake <= 0:
            continue  # Kelly <= 0: no es apuesta, no cuenta en N ni en hit
        pl = round(stake * (p["cuota"] - 1), 2) if p["gana"] else round(-stake, 2)
        bank = round(bank + pl, 2)
        picks.append({**p, "stake": stake, "pl": pl, "equity": bank})
    return {"picks": picks, "real": dict(real), "bankroll": float(bankroll)}


def _sumar_real(d, gano):
    d["n"] = d.get("n", 0) + 1
    d["g"] = d.get("g", 0) + int(gano)


def _candidato(fecha, local, visita, pais, pick, cuota, camino, mercado, gl, gv, gana, prob):
    return {"fecha_raw": fecha, "fecha": _fecha_txt(fecha), "partido": f"{local} vs {visita}",
            "pais": pais, "pick": pick, "cuota": cuota, "camino": camino, "mercado": mercado,
            "gl": gl, "gv": gv, "gana": gana, "prob": prob}


def resumen_si_hubiera(sim):
    """KPIs REAL vs SIMULADO, tabla por liga y por camino."""
    picks, real, bank = sim["picks"], sim["real"], sim["bankroll"]
    n_r = sum(v.get("n", 0) for v in real.values())
    g_r = sum(v.get("g", 0) for v in real.values())
    stake = sum(p["stake"] for p in picks)
    pl = sum(p["pl"] for p in picks)
    kpi = {"n_real": n_r, "g_real": g_r, "n_sim": len(picks),
           "g_sim": sum(p["gana"] for p in picks), "stake": stake, "pl": pl,
           "bankroll": bank, "equity": bank + pl}
    filas_liga, filas_camino = [], []
    for liga in sorted(set(real) | {p["pais"] for p in picks}):
        rl = real.get(liga, {})
        ps = [p for p in picks if p["pais"] == liga]
        n_l, g_l = len(ps), sum(p["gana"] for p in ps)
        stk_l, pl_l = sum(p["stake"] for p in ps), sum(p["pl"] for p in ps)
        hit_r = rl["g"] / rl["n"] if rl.get("n") else None
        hit_s = g_l / n_l if n_l else None
        filas_liga.append({
            "Liga": liga, "N real": rl.get("n", 0), "Hit real": hit_r,
            "N sim": n_l, "G sim": g_l, "Hit sim": hit_s, "Volumen $": stk_l, "P/L $": pl_l,
            "Yield sim": pl_l / stk_l if stk_l else None,
            "dN": n_l - rl.get("n", 0),
            "dHit": hit_s - hit_r if hit_s is not None and hit_r is not None else None,
        })
        fila = {"Liga": liga}
        for cam in CAMINOS:
            cp = [p for p in ps if p["camino"] == cam]
            fila[cam] = f"{sum(p['gana'] for p in cp)}/{len(cp)}" if cp else "-"
        fila["Total"] = n_l
        filas_camino.append(fila)
    return {"kpi": kpi, "por_liga": pd.DataFrame(filas_liga),
            "por_camino": pd.DataFrame(filas_camino)}


def cargar_todo(con):
    """Carga todo lo que muestra el dashboard. Solo lee la DB."""
    cur = con.cursor()
    datos = _cargar_partidos(cur)
    base, operativo, fk = _leer_configuracion(cur)
    live = _cargar_apuestas_live(cur)
    aportes = _cargar_aportes(cur)
    confirmados = estado_confirmaciones(con)
    filas = filas_yield(cur)
    fk_sim = float(get_param("fraccion_kelly", default=0.50) or 0.50)
    mk_sim = float(get_param("max_kelly_pct_normal", default=0.025) or 0.025)
    sim = simular_si_hubiera(datos, base, fk_sim, mk_sim)
    return {
        "picks": picks_vivos(datos, confirmados),
        "base": base, "operativo": operativo, "fk": fk,
        "metricas": calcular_metricas_dashboard(datos, fk),
        "equity": equity_df(datos, aportes, base),
        "yield": yield_potencial(filas),
        "curva_yield": curva_yield_df(filas),
        "historial": historial_df(datos),
        "resumen": resumen_liga_df(datos, fk, live),
        "sombra": sombra(datos),
        "si_hubiera": sim,
        "si_resumen": resumen_si_hubiera(sim),
    }


@st.cache_data(ttl=60)
def _bundle():
    con = conectar_ro()
    try:
        return cargar_todo(con)
    finally:
        con.close()


# ============================================================================
# FORMATO Y GRAFICOS
# ============================================================================
def _pct(x, signo=False):
    if x is None or pd.isna(x):
        return "—"
    return f"{x * 100:{'+' if signo else ''}.1f}%"


def _usd(x, signo=False):
    if x is None or pd.isna(x):
        return "—"
    signo_txt = "-" if x < 0 else ("+" if signo else "")
    return f"{signo_txt}${abs(x):,.2f}"


def _ratio(a, b):
    return a / b if b else None


def _formatear(df, reglas):
    """Aplica una funcion de formato por columna. Devuelve copia."""
    out = df.copy()
    for col, fn in reglas.items():
        if col in out:  # tabla vacia: sin columnas
            out[col] = out[col].map(fn)
    return out


def _linea(df, x, y, titulo_x, titulo_y, cero=False):
    base = alt.Chart(df).mark_line(color="#1db954", strokeWidth=2).encode(
        x=alt.X(f"{x}:Q", title=titulo_x),
        y=alt.Y(f"{y}:Q", title=titulo_y, scale=alt.Scale(zero=False)),
        tooltip=[alt.Tooltip(f"{x}:Q", title=titulo_x), alt.Tooltip(f"{y}:Q", title=titulo_y, format=",.2f")],
    )
    if cero:
        base = base + alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(
            color="#666", strokeDash=[4, 4]).encode(y="y:Q")
    return base.properties(height=300)


# ============================================================================
# PESTAÑAS
# ============================================================================
def _confirmar(id_p, mercado, cuota, stake):
    try:
        con = sqlite3.connect(DB_NAME)
        try:
            pick = confirmar_apuesta(con, id_p, mercado, cuota, stake)
        finally:
            con.close()
    except ValueError as e:
        st.error(str(e))
        return
    st.session_state["aviso"] = ("ok", f"Confirmada: {pick} a {cuota:.2f} con stake {_usd(stake)}.")
    st.cache_data.clear()
    st.rerun()


def _tab_picks(b):
    aviso = st.session_state.pop("aviso", None)
    if aviso:
        (st.success if aviso[0] == "ok" else st.error)(aviso[1])
    picks = b["picks"]
    if not picks:
        st.info("No hay picks vivos para partidos que no empezaron.")
        return
    c = st.columns(3)
    c[0].metric("Picks vivos", len(picks))
    c[1].metric("Stake total", f"${sum(p['stake'] for p in picks):,.0f}")
    c[2].metric("Confirmados", sum(p["confirmada"] for p in picks))

    tabla = pd.DataFrame([{
        "Fecha": p["fecha"], "Liga": p["pais"], "Partido": p["partido"], "Mercado": p["mercado"],
        "Pick": p["pick"], "Cuota": f"{p['cuota']:.2f}", "Prob modelo": _pct(p["prob_modelo"]),
        "Prob mercado": _pct(p["prob_mercado"]), "EV %": f"{p['ev_pct']:+.1f}%",
        "Stake sugerido": f"${p['stake']:,.0f}",
        "P/L potencial": f"${p['stake'] * (p['cuota'] - 1):,.0f}",
        "Estado": "Confirmada" if p["confirmada"] else "Pendiente",
    } for p in picks])
    st.dataframe(tabla, hide_index=True)

    st.subheader("Confirmar apuesta")
    st.caption("Cuota y stake vienen del motor. Cambielos si difieren de lo que tomo.")
    for p in picks:
        etiqueta = f"{p['partido']} · {p['mercado']} {p['pick']} @ {p['cuota']:.2f}"
        if p["confirmada"]:
            st.caption(f"Confirmada: {etiqueta}")
            continue
        clave = f"{p['id']}|{p['mercado']}"
        with st.expander(f"Confirmar apuesta · {etiqueta}"):
            with st.form(f"form|{clave}"):
                col1, col2 = st.columns(2)
                cuota = col1.number_input("Cuota tomada", min_value=1.01,
                                          value=max(1.01, float(p["cuota"])), step=0.01,
                                          format="%.2f", key=f"cuota|{clave}")
                stake = col2.number_input("Stake ($)", min_value=0.01,
                                          value=max(0.01, float(p["stake"])), step=10.0,
                                          format="%.2f", key=f"stake|{clave}")
                enviar = st.form_submit_button("Confirmar apuesta")
            if enviar:
                _confirmar(p["id"], p["mercado"], cuota, stake)


def _tab_dinero(b):
    m = b["metricas"]
    t = m["total"]
    st.caption("Solo apuestas liquidadas con stake > 0. Fuente: calcular_metricas_dashboard.")
    c = st.columns(4)
    c[0].metric("Ganancia neta", _usd(t["pl"], True))
    c[1].metric("Yield", _pct(t["yield"], True) if t["n"] else "—")
    c[2].metric("% acierto $", _pct(t["acierto_bets"]) if t["n"] else "—")
    c[3].metric("Apuestas liquidadas", t["n"])
    c = st.columns(4)
    c[0].metric("Volumen apostado", _usd(t["vol"]))
    c[1].metric("Bankroll base", _usd(b["base"]))
    c[2].metric("Bankroll operativo", _usd(b["operativo"]))
    c[3].metric("Fraccion Kelly", f"{b['fk']:.0%}")
    c = st.columns(4)
    c[0].metric("T-score", f"{t['t']:.2f}")
    c[1].metric("p-valor", f"{t['p']:.4f}")
    c[2].metric("% acierto P (modelo)", _pct(m["acierto_partidos"]))
    c[3].metric("Brier sistema - casa", f"{m['bs_glob']:+.4f}",
                help="Negativo: el modelo supera al mercado.")

    st.subheader("Equity curve")
    eq = b["equity"]
    if len(eq) < 2:
        st.info("Todavia no hay apuestas reales liquidadas.")
    else:
        st.altair_chart(_linea(eq, "n", "equity", "Apuesta #", "Equity ($)"))


def _fila_yield(nombre, s):
    return {"Grupo": nombre, "N": s["n"], "Ganadas": s["ganadas"], "Hit": _pct(s["hit"]),
            "Profit (u)": f"{s['profit']:+.2f}", "Yield": _pct(s["yield"], True),
            "Break-even": _pct(s["break_even"]), "IC 95% inf": _pct(s["ci_low"], True),
            "IC 95% sup": _pct(s["ci_high"], True)}


def _tab_yield(b):
    st.warning("Incluye picks de pretest con stake 0: no es dinero real.")
    y = b["yield"]
    g = y["global"]
    if g["n"] == 0:
        st.info("No hay picks liquidados con cuota valida.")
        return
    c = st.columns(4)
    c[0].metric("Picks liquidados", g["n"])
    c[1].metric("Hit rate", _pct(g["hit"]))
    c[2].metric("Profit (unidades)", f"{g['profit']:+.1f} u")
    c[3].metric("Break-even", _pct(g["break_even"]))
    c = st.columns(2)
    c[0].metric("Yield por apuesta", _pct(g["yield"], True))
    c[1].caption(f"IC 95% bootstrap del yield: {_pct(g['ci_low'], True)} a {_pct(g['ci_high'], True)}")

    st.subheader("Por liga")
    ligas = sorted(y["por_liga"].items(), key=lambda kv: -kv[1]["n"])
    st.dataframe(pd.DataFrame([_fila_yield(k, v) for k, v in ligas]), hide_index=True)

    st.subheader("Por mercado")
    nombres = {"1X2": "1X2", "OU": "O/U 2.5"}
    st.dataframe(pd.DataFrame([_fila_yield(nombres[k], v) for k, v in y["por_mercado"].items()]),
                 hide_index=True)

    st.subheader("Curva acumulada (unidades, 1 por apuesta)")
    curva = b["curva_yield"]
    if curva.empty:
        st.info("Sin apuestas para graficar.")
    else:
        st.altair_chart(_linea(curva, "n", "pl_acum", "Apuesta #", "P/L acumulado (u)", cero=True))


def _tab_historial(b):
    df = b["historial"]
    if df.empty:
        st.info("No hay partidos en la base.")
        return
    fechas = df["fecha_dt"].dropna()
    c = st.columns(4)
    ligas = c[0].multiselect("Liga", sorted(df["Liga"].dropna().unique()),
                             default=sorted(df["Liga"].dropna().unique()))
    estado = c[1].selectbox("Estado", ["Todos"] + sorted(df["Estado"].dropna().unique()))
    mask = df["Liga"].isin(ligas)
    if estado != "Todos":
        mask &= df["Estado"].eq(estado)
    if not fechas.empty:
        f_min, f_max = fechas.min().date(), fechas.max().date()
        desde = c[2].date_input("Desde", f_min, min_value=f_min, max_value=f_max)
        hasta = c[3].date_input("Hasta", f_max, min_value=f_min, max_value=f_max)
        mask &= df["fecha_dt"].between(pd.Timestamp(desde), pd.Timestamp(hasta))
    vista = df[mask].drop(columns=["fecha_dt"])
    st.caption(f"{len(vista)} partidos")
    st.dataframe(_formatear(vista, {"P/L neto": _usd}), hide_index=True)


def _tab_resumen(b):
    df = b["resumen"]
    if df.empty:
        st.info("Sin ligas con partidos.")
        return
    st.caption("Apuestas liquidadas con stake > 0 (dinero real). Fuente: calcular_metricas_dashboard por liga.")
    st.dataframe(_formatear(df, {"% Acierto": _pct, "Yield": lambda x: _pct(x, True),
                                 "P/L $": lambda x: _usd(x, True), "Volumen $": _usd}),
                 hide_index=True)


def _tab_sombra(b):
    s = b["sombra"]
    o1, o4 = s["op1"], s["op4"]
    st.caption("Op1 = opcion activa (dinero real). Op4 = shadow, solo auditoria.")
    filas = [
        ("N apuestas liquidadas", o1["n"], o4["n"], str, False),
        ("Ganadas", o1["g"], o4["g"], str, True),
        ("Hit rate", _ratio(o1["g"], o1["n"]), _ratio(o4["g"], o4["n"]), _pct, True),
        ("Volumen apostado", o1["vol"], o4["vol"], _usd, False),
        ("P/L neto", o1["pl"], o4["pl"], _usd, True),
        ("Yield", _ratio(o1["pl"], o1["vol"]), _ratio(o4["pl"], o4["vol"]), _pct, True),
    ]
    kpi = []
    for nombre, v1, v4, fmt, compara in filas:
        if compara and v1 is not None and v4 is not None and v1 != v4:
            mejor = "Op1" if v1 > v4 else "Op4"
        else:
            mejor = "="
        kpi.append({"KPI": nombre, "Opcion 1 (activa)": fmt(v1) if v1 is not None else "—",
                    "Opcion 4 (shadow)": fmt(v4) if v4 is not None else "—", "Mejor": mejor})
    st.dataframe(pd.DataFrame(kpi), hide_index=True)

    st.subheader("Detalle por partido")
    st.dataframe(_formatear(s["filas"], {"P/L Op1": _usd, "P/L Op4": _usd, "Dif P/L": _usd}),
                 hide_index=True)


def _tab_si_hubiera(b):
    st.warning("Backtest IN-SAMPLE: las reglas se calibraron con estos mismos datos. "
               "Sirve para ver, no para decidir LIVE.")
    sim, r = b["si_hubiera"], b["si_resumen"]
    k = r["kpi"]
    kpi_filas = [
        ("N picks", k["n_real"], k["n_sim"], str),
        ("Ganados", k["g_real"], k["g_sim"], str),
        ("Hit rate", _ratio(k["g_real"], k["n_real"]), _ratio(k["g_sim"], k["n_sim"]), _pct),
        ("Volumen apostado", None, k["stake"], _usd),
        ("Yield (P/L / volumen)", None, _ratio(k["pl"], k["stake"]), _pct),
        ("P/L neto", None, k["pl"], _usd),
        ("ROI sobre bankroll", None, _ratio(k["pl"], k["bankroll"]), _pct),
        ("Equity final", k["bankroll"], k["equity"], _usd),
    ]
    st.dataframe(pd.DataFrame([{
        "KPI": nombre,
        "REAL (historico)": fmt(v1) if v1 is not None else "—",
        "SIMULADO (reglas actuales)": fmt(v4) if v4 is not None else "—",
    } for nombre, v1, v4, fmt in kpi_filas]), hide_index=True)

    st.subheader("Detalle por liga")
    st.dataframe(_formatear(r["por_liga"], {
        "Hit real": _pct, "Hit sim": _pct, "Yield sim": lambda x: _pct(x, True),
        "Volumen $": _usd, "P/L $": lambda x: _usd(x, True),
        "dHit": lambda x: _pct(x, True)}), hide_index=True)

    st.subheader("Picks simulados por camino (ganados/total)")
    st.dataframe(r["por_camino"], hide_index=True)

    st.subheader("Equity simulada")
    picks = sim["picks"]
    if not picks:
        st.info("Ninguna regla actual genera picks en el historico.")
        return
    eq = pd.DataFrame([{"n": i, "equity": p["equity"]} for i, p in enumerate(picks, 1)])
    st.altair_chart(_linea(eq, "n", "equity", "Pick #", "Equity ($)"))
    st.subheader(f"Detalle de picks simulados (n={len(picks)})")
    det = pd.DataFrame([{
        "Fecha": p["fecha"], "Partido": p["partido"], "Liga": p["pais"], "Pick": p["pick"],
        "Cuota": p["cuota"], "Camino": p["camino"], "Goles": f"{p['gl']}-{p['gv']}",
        "Resultado": "GANADA" if p["gana"] else "PERDIDA", "Stake $": p["stake"],
        "P/L $": p["pl"], "Equity $": p["equity"],
    } for p in picks])
    st.dataframe(_formatear(det, {"P/L $": lambda x: _usd(x, True), "Stake $": _usd,
                                  "Equity $": _usd}), hide_index=True)


# ============================================================================
# APP
# ============================================================================
def render():
    st.set_page_config(page_title="Adepor — Dashboard", page_icon="🎯", layout="wide")
    st.title("Adepor — Dashboard")
    try:
        b = _bundle()
    except Exception as e:
        st.error(f"Error cargando DB: {e}")
        st.stop()
    st.caption(f"Base: {DB_NAME} · Cargado {datetime.now():%d/%m/%Y %H:%M} · cache 60 s")
    pestañas = st.tabs(TABS)
    vistas = (_tab_picks, _tab_dinero, _tab_yield, _tab_historial,
              _tab_resumen, _tab_sombra, _tab_si_hubiera)
    for pestaña, vista in zip(pestañas, vistas):
        with pestaña:
            vista(b)


if __name__ == "__main__":  # Streamlit ejecuta el script como __main__
    render()
