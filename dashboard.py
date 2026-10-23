"""
Dashboard Adepor (Streamlit, local). Reemplaza el workbook Excel.

Lanzar: ./iniciar_dashboard.sh  (solo 127.0.0.1, sin red externa).
Los loaders son funciones puras: se prueban sin Streamlit corriendo.
"""
import math
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from scripts.ops import salud
from src.comun.config_sistema import DB_NAME
from src.comun.picks import cuota_para_pick
from src.comun.resolucion import determinar_resultado_entero
from src.comun.tiempo import ahora_art
from src.nucleo.valor_v2 import clv_v2, prob_justa, stake_v2, tabla_valor
from src.persistencia.bankroll import obtener_bankroll_operativo
from src.persistencia.confirmaciones import confirmar_apuesta, ids_confirmados
from src.persistencia.metricas import _pl_apuesta, metricas_dinero
from src.persistencia.yield_potencial import apuestas_potenciales, yield_potencial

TABS = ["Valor v2", "Dinero real", "Yield potencial", "Historial"]
CASAS_V2 = ("BetWarrior", "Bet365", "Casa local")
PIN_PRE = ("pin_1", "pin_x", "pin_2", "pin_o25", "pin_u25")  # Pinnacle pre-partido
PIN_CIERRE = ("pin_cierre_1", "pin_cierre_x", "pin_cierre_2", "pin_cierre_o25", "pin_cierre_u25")
PICKS_V2 = {"1X2": ("LOCAL", "EMPATE", "VISITA"), "OU": ("OVER 2.5", "UNDER 2.5")}
CIERRE_V2 = {"1X2": PIN_CIERRE[:3], "OU": PIN_CIERRE[3:]}


# ============================================================================
# LOADERS (puros: reciben conexion o listas, devuelven datos)
# ============================================================================
def conectar_ro():
    """Conexion de solo lectura a la DB del pipeline (respeta ADEPOR_DB)."""
    return sqlite3.connect(Path(DB_NAME).resolve().as_uri() + "?mode=ro", uri=True)


def cargar_partidos(cur):
    """Partidos de partidos_backtest en orden fijo de columnas (los indices los usan los loaders)."""
    cur.execute("""
        SELECT id_partido, fecha, local, visita, pais,
               apuesta_1x2, apuesta_ou, stake_1x2, stake_ou,
               cuota_1, cuota_x, cuota_2, cuota_o25, cuota_u25,
               estado, goles_l, goles_v
        FROM partidos_backtest
        ORDER BY id_partido ASC
    """)
    return cur.fetchall()


def leer_bankroll(cur):
    """(bankroll base, bankroll operativo). Base: punto de partida fijo de la equity curve."""
    try:
        cur.execute("SELECT valor FROM configuracion WHERE clave = 'bankroll'")
        base = float(cur.fetchone()[0])
    except (TypeError, IndexError, ValueError):
        base = 100000.00
    try:
        operativo = obtener_bankroll_operativo(cur)
    except Exception:
        operativo = base
    return base, operativo


def cargar_aportes(cur):
    """[(fecha, monto)] de aportes y retiros de capital, o [] si la tabla no existe."""
    try:
        rows = cur.execute("SELECT fecha, monto FROM aportes_capital ORDER BY fecha ASC, id ASC").fetchall()
    except sqlite3.OperationalError:
        return []
    return [(str(f), float(m)) for f, m in rows]


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
    """Apuestas liquidadas con stake > 0, con la formula de metricas_dinero."""
    out = []
    for r in datos:
        estado, gl, gv = r[14], r[15], r[16]
        for ap, stk in ((r[5], r[7]), (r[6], r[8])):
            pl = _pl_pick(estado, ap, stk, cuota_para_pick(ap, *r[9:14]), gl, gv)
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


def historial_df(datos):
    """Una fila por partido, como la hoja Backtest. P/L neto de ambos mercados."""
    filas = []
    for r in datos:
        estado, gl, gv = r[14], r[15], r[16]
        ap1, apou, stk1, stko = r[5], r[6], r[7], r[8]
        c1, cx, c2, co, cu = r[9:14]
        pls = [_pl_pick(estado, ap1, stk1, cuota_para_pick(ap1, c1, cx, c2, co, cu), gl, gv),
               _pl_pick(estado, apou, stko, cuota_para_pick(apou, c1, cx, c2, co, cu), gl, gv)]
        validos = [x for x in pls if x is not None]
        d = _fecha_dt(r[1])
        filas.append({
            "fecha_dt": pd.Timestamp(d) if d else pd.NaT,
            "Fecha": _fecha_txt(r[1]), "Liga": r[4], "Partido": f"{r[2]} vs {r[3]}",
            "Goles": f"{gl}-{gv}" if gl is not None and gv is not None else "",
            "Estado": estado,
            "Cuota 1": c1, "Cuota X": cx, "Cuota 2": c2,
            "Apuesta 1X2": ap1 or "", "Stake 1X2": stk1 or 0,
            "Apuesta O/U": apou or "", "Stake O/U": stko or 0,
            "P/L neto": sum(validos) if validos else None,
        })
    df = pd.DataFrame(filas, columns=["fecha_dt", "Fecha", "Liga", "Partido", "Goles", "Estado",
                                      "Cuota 1", "Cuota X", "Cuota 2", "Apuesta 1X2", "Stake 1X2", "Apuesta O/U",
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


def _columnas(con, tabla):
    return {r[1] for r in con.execute(f"PRAGMA table_info({tabla})")}


def _sel_pin(cols, nombres):
    """Columnas que existen en la DB; NULL para las que faltan (bases viejas)."""
    return ", ".join(n if n in cols else f"NULL AS {n}" for n in nombres)


def _dicts(con, sql):
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, fila)) for fila in cur.fetchall()]


def _media(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def valor_v2_vivos(con):
    """Un row por resultado de partidos vivos con cuotas Pinnacle (D-019)."""
    cols = _columnas(con, "partidos_backtest")
    filas = _dicts(con, "SELECT id_partido, fecha, pais, local, visita, estado, goles_l, goles_v, "
                        f"{_sel_pin(cols, PIN_PRE)} FROM partidos_backtest ORDER BY fecha")
    ahora = ahora_art().strftime("%Y-%m-%d %H:%M")
    confirmados = estado_confirmaciones(con)
    out = []
    for r in filas:
        if r["estado"] == "Liquidado" or r["goles_l"] is not None or r["goles_v"] is not None:
            continue
        if str(r["fecha"] or "") <= ahora:
            continue
        for mercado, pick, p, minima in tabla_valor(r):
            out.append({"id": r["id_partido"], "fecha": _fecha_txt(r["fecha"]), "liga": r["pais"],
                        "partido": f"{r['local']} vs {r['visita']}", "mercado": mercado, "pick": pick,
                        "prob_justa": p, "cuota_minima": minima,
                        "confirmada": (r["id_partido"], mercado) in confirmados})
    return out


def tabla_ev(filas, cuotas_casa):
    """Filas de valor_v2_vivos con cuota cargada, su EV contra la prob justa y si conviene apostar.
    cuotas_casa: {(id_partido, pick): cuota}. Ordena de mayor a menor EV."""
    out = []
    for f in filas:
        c = cuotas_casa.get((f["id"], f["pick"]))
        if c and c > 1:
            out.append({**f, "cuota_casa": c, "ev": c * f["prob_justa"] - 1, "apostar": c >= f["cuota_minima"]})
    return sorted(out, key=lambda f: -f["ev"])


def resultados_pinnacle(con):
    """Partidos jugados con la prob justa de Pinnacle: favorito, acierto, Brier y log-loss del 1X2.
    Usa el cierre si se capturo; si no, la ultima cuota previa al kickoff."""
    cols = _columnas(con, "partidos_backtest")
    filas = _dicts(con, "SELECT fecha, pais, local, visita, goles_l, goles_v, "
                        f"{_sel_pin(cols, PIN_PRE[:3] + PIN_CIERRE[:3])} FROM partidos_backtest "
                        "WHERE goles_l IS NOT NULL AND goles_v IS NOT NULL ORDER BY fecha DESC")
    out = []
    for r in filas:
        fuente, p = "cierre", prob_justa([r[c] for c in PIN_CIERRE[:3]])
        if p is None:
            fuente, p = "previa", prob_justa([r[c] for c in PIN_PRE[:3]])
        if p is None:
            continue
        gl, gv = r["goles_l"], r["goles_v"]
        y = 0 if gl > gv else (1 if gl == gv else 2)
        fav = max(range(3), key=lambda i: p[i])
        out.append({"Fecha": _fecha_txt(r["fecha"]), "Liga": r["pais"],
                    "Partido": f"{r['local']} vs {r['visita']}", "Goles": f"{gl}-{gv}",
                    "Favorito": PICKS_V2["1X2"][fav], "Prob favorito": p[fav], "Acerto": fav == y,
                    "Brier": sum((p[i] - (i == y)) ** 2 for i in range(3)),
                    "Log-loss": -math.log(p[y]), "Fuente": fuente})
    n = len(out)
    return {"filas": out, "n": n,
            "acierto": _media([f["Acerto"] for f in out]),
            "brier": _media([f["Brier"] for f in out]),
            "logloss": _media([f["Log-loss"] for f in out]),
            "n_cierre": sum(f["Fuente"] == "cierre" for f in out)}


def clv_v2_confirmadas(con):
    """Apuestas confirmadas con CLV contra el cierre Pinnacle (None sin cierre)."""
    try:
        cols = _columnas(con, "partidos_backtest")
        filas = _dicts(con, "SELECT a.id_partido, a.mercado, a.pick, a.casa, a.cuota_tomada, a.stake, "
                            "p.local, p.visita, p.estado, "
                            f"{_sel_pin(cols, PIN_CIERRE)} FROM apuestas_confirmadas a "
                            "JOIN partidos_backtest p ON p.id_partido = a.id_partido ORDER BY a.ts")
    except sqlite3.OperationalError:
        filas = []  # la tabla se crea en la primera confirmacion
    out = [{"id": f["id_partido"], "partido": f"{f['local']} vs {f['visita']}",
            "mercado": f["mercado"], "pick": f["pick"], "casa": f["casa"],
            "cuota_tomada": f["cuota_tomada"], "stake": f["stake"], "estado": f["estado"],
            "clv": clv_v2(f["cuota_tomada"], [f[c] for c in CIERRE_V2[f["mercado"]]],
                          PICKS_V2[f["mercado"]].index(f["pick"]))} for f in filas]
    clvs = [f["clv"] for f in out]
    return {"filas": out, "n": len(out), "n_clv": sum(c is not None for c in clvs),
            "clv_medio": _media(clvs),
            "clv_por_casa": {c: _media([f["clv"] for f in out if f["casa"] == c])
                             for c in {f["casa"] for f in out}}}


def cargar_todo(con):
    """Carga todo lo que muestra el dashboard. Solo lee la DB."""
    cur = con.cursor()
    datos = cargar_partidos(cur)
    base, operativo = leer_bankroll(cur)
    filas = filas_yield(cur)
    return {
        "valor_v2": valor_v2_vivos(con),
        "clv_v2": clv_v2_confirmadas(con),
        "resultados": resultados_pinnacle(con),
        "base": base, "operativo": operativo,
        "metricas": metricas_dinero(datos),
        "equity": equity_df(datos, cargar_aportes(cur), base),
        "yield": yield_potencial(filas),
        "curva_yield": curva_yield_df(filas),
        "historial": historial_df(datos),
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
def _confirmar(id_p, mercado, cuota, stake, clave_aviso, pick, casa):
    try:
        con = sqlite3.connect(DB_NAME)
        try:
            confirmada = confirmar_apuesta(con, id_p, mercado, cuota, stake, pick=pick, casa=casa)
        finally:
            con.close()
    except ValueError as e:
        st.error(str(e))
        return
    st.session_state[clave_aviso] = ("ok", f"Confirmada: {confirmada} a {cuota:.2f} con stake {_usd(stake)}.")
    st.cache_data.clear()
    st.rerun()


def _tab_valor_v2(b):
    aviso = st.session_state.pop("aviso_v2", None)
    if aviso:
        (st.success if aviso[0] == "ok" else st.error)(aviso[1])
    st.caption("Prob justa = cuotas Pinnacle sin margen. Cargue en la tabla la cuota de su casa: "
               "el EV se calcula solo, y un pick conviene si su cuota supera la minima.")
    filas = b["valor_v2"]
    if not filas:
        st.info("No hay partidos vivos con cuotas Pinnacle.")
    else:
        # Las cuotas cargadas viven en la sesion: sobreviven a cada recarga de la tabla.
        cuotas = st.session_state.setdefault("cuotas_casa", {})
        df = pd.DataFrame([{
            "id": f["id"], "Fecha": f["fecha"], "Liga": f["liga"], "Partido": f["partido"],
            "Mercado": f["mercado"], "Pick": f["pick"], "Prob justa %": round(f["prob_justa"] * 100, 1),
            "Cuota minima": round(f["cuota_minima"], 2),
            "Cuota casa": cuotas.get((f["id"], f["pick"]), float("nan")),
            "Estado": "Confirmada" if f["confirmada"] else "Pendiente",
        } for f in filas])
        editada = st.data_editor(
            df, key="tabla_v2", hide_index=True,
            disabled=[c for c in df.columns if c != "Cuota casa"],
            column_config={"id": None, "Cuota casa": st.column_config.NumberColumn(
                min_value=1.01, step=0.01, format="%.2f", help="Cuota que paga su casa")})
        for id_p, pick, c in zip(editada["id"], editada["Pick"], editada["Cuota casa"]):
            if pd.notna(c):
                cuotas[(id_p, pick)] = float(c)
        _bloque_ev(tabla_ev(filas, cuotas), b["operativo"])
    _bloque_clv_v2(b["clv_v2"])


def _bloque_ev(ev, bankroll):
    st.subheader("Picks con cuota cargada")
    if not ev:
        st.info("Cargue la cuota de su casa en la tabla para ver el EV.")
        return
    st.dataframe(pd.DataFrame([{
        "Partido": f["partido"], "Mercado": f["mercado"], "Pick": f["pick"],
        "Cuota casa": f"{f['cuota_casa']:.2f}", "Cuota minima": f"{f['cuota_minima']:.2f}",
        "EV": _pct(f["ev"], True), "Recomendacion": "Apostar" if f["apostar"] else "No apostar",
    } for f in ev]), hide_index=True)
    for f in ev:
        if f["apostar"] and not f["confirmada"]:
            _formulario_v2(f, bankroll)


def _formulario_v2(f, bankroll):
    """Compara la cuota de mi casa con la minima. Confirma solo si hay valor."""
    clave = f"v2|{f['id']}|{f['pick']}"
    p, minima = f["prob_justa"], f["cuota_minima"]
    with st.expander(f"Confirmar apuesta · {f['partido']} · {f['mercado']} {f['pick']}"):
        c = st.columns(2)
        casa = c[0].selectbox("Casa", CASAS_V2, key=f"casa|{clave}")
        cuota = c[1].number_input("Cuota de mi casa", min_value=1.01,
                                  value=f.get("cuota_casa") or math.ceil(minima * 100) / 100, step=0.01,
                                  format="%.2f", key=f"cuota|{clave}")
        ev = cuota * p - 1
        sugerido = stake_v2(p, cuota, bankroll)
        st.caption(f"Minima {minima:.2f} · EV vs prob justa {ev * 100:+.1f}% · "
                   f"Stake sugerido {_usd(sugerido)}")
        # Se registra el stake real: la casa puede limitar el monto aceptado.
        stake = st.number_input("Stake apostado ($)", min_value=0.0, value=float(sugerido),
                                step=10.0, key=f"stake|{clave}")
        sin_valor = cuota < minima or stake <= 0
        if sin_valor:
            st.error("Cuota por debajo de la minima: su casa no paga valor.")
        if st.button("Confirmar apuesta", key=f"btn|{clave}", disabled=sin_valor):
            _confirmar(f["id"], f["mercado"], cuota, stake, clave_aviso="aviso_v2",
                       pick=f["pick"], casa=casa)


def _bloque_clv_v2(c):
    st.subheader("CLV de mis apuestas v2")
    st.caption("CLV = cuota tomada vs cierre Pinnacle sin margen. CLV > 0 sostenido es la señal de edge.")
    if not c["filas"]:
        st.info("Todavia no hay apuestas confirmadas en v2.")
        return
    k = st.columns(3)
    k[0].metric("Apuestas confirmadas", c["n"])
    k[1].metric("CLV medio", _pct(c["clv_medio"], True))
    k[2].metric("Con cierre Pinnacle", c["n_clv"])
    if c["clv_por_casa"]:
        st.dataframe(pd.DataFrame([{"Casa": casa or "-", "CLV medio": _pct(v, True)}
                                   for casa, v in c["clv_por_casa"].items()]), hide_index=True)
    st.dataframe(pd.DataFrame([{
        "Partido": f["partido"], "Casa": f["casa"] or "-", "Mercado": f["mercado"],
        "Pick": f["pick"], "Cuota tomada": f"{f['cuota_tomada']:.2f}",
        "Stake": _usd(f["stake"]), "Estado": f["estado"] or "-", "CLV": _pct(f["clv"], True),
    } for f in c["filas"]]), hide_index=True)


def _tab_dinero(b):
    m = b["metricas"]
    t = m["total"]
    st.caption("Solo apuestas liquidadas con stake > 0. Fuente: metricas_dinero.")
    c = st.columns(4)
    c[0].metric("Ganancia neta", _usd(t["pl"], True))
    c[1].metric("Yield", _pct(t["yield"], True) if t["n"] else "—")
    c[2].metric("% acierto $", _pct(t["acierto_bets"]) if t["n"] else "—")
    c[3].metric("Apuestas liquidadas", t["n"])
    c = st.columns(3)
    c[0].metric("Volumen apostado", _usd(t["vol"]))
    c[1].metric("Bankroll base", _usd(b["base"]))
    c[2].metric("Bankroll operativo", _usd(b["operativo"]))
    c = st.columns(2)
    c[0].metric("T-score", f"{t['t']:.2f}")
    c[1].metric("p-valor", f"{t['p']:.4f}")

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
    st.warning("Incluye picks del v1 con stake 0: no es dinero real.")
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
    _bloque_resultados(b["resultados"])
    st.subheader("Partidos")
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


def _bloque_resultados(r):
    st.subheader("Pinnacle en partidos jugados (1X2)")
    st.caption("Favorito = resultado con mayor prob justa. Brier: 0 es perfecto; adivinar al azar da 0.667. "
               "Es la calibracion del mercado, no el edge: el edge se mide con el CLV.")
    if not r["n"]:
        st.info("Todavia no hay partidos jugados con cuota Pinnacle.")
        return
    k = st.columns(4)
    k[0].metric("Partidos", r["n"])
    k[1].metric("Acierto del favorito", _pct(r["acierto"]))
    k[2].metric("Brier medio", f"{r['brier']:.4f}")
    k[3].metric("Con cierre capturado", r["n_cierre"])
    st.dataframe(_formatear(pd.DataFrame(r["filas"]), {
        "Prob favorito": _pct, "Brier": lambda x: f"{x:.3f}", "Log-loss": lambda x: f"{x:.3f}",
        "Acerto": lambda x: "Si" if x else "No"}), hide_index=True)


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
    estado = salud.leer_estado(salud.ESTADO, time.time())
    if estado and not estado[0]:
        st.error("Salud del pipeline: " + "; ".join(estado[1]))
    st.caption(f"Base: {DB_NAME} · Cargado {datetime.now():%d/%m/%Y %H:%M} · cache 60 s")
    pestañas = st.tabs(TABS)
    vistas = (_tab_valor_v2, _tab_dinero, _tab_yield, _tab_historial)
    for pestaña, vista in zip(pestañas, vistas):
        with pestaña:
            vista(b)


if __name__ == "__main__":  # Streamlit ejecuta el script como __main__
    render()
