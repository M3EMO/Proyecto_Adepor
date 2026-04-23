"""
Dashboard Adepor — vista de apuestas vivas + historial por liga.

Launch local:
    streamlit run dashboard.py

Expone en http://localhost:8501. Para compartir con amigos:
    ngrok http 8501    (URL temporal)

Sin autenticacion (link abierto).
"""
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st


DB = Path(__file__).parent / "fondo_quant.db"

FLAGS = {
    "Argentina": "🇦🇷", "Brasil": "🇧🇷", "Uruguay": "🇺🇾",
    "Chile": "🇨🇱", "Peru": "🇵🇪", "Ecuador": "🇪🇨",
    "Colombia": "🇨🇴", "Bolivia": "🇧🇴", "Venezuela": "🇻🇪",
    "Espana": "🇪🇸", "Italia": "🇮🇹", "Alemania": "🇩🇪",
    "Francia": "🇫🇷", "Inglaterra": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "Turquia": "🇹🇷",
    "Noruega": "🇳🇴",
}


st.set_page_config(
    page_title="Adepor — Picks del Día",
    page_icon="🎯",
    layout="wide",
)


@st.cache_data(ttl=60)
def cargar_datos():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row

    # Hit rate por liga (pretest + real)
    ligas = pd.read_sql_query("""
        WITH evaluados AS (
            SELECT pais,
                   COUNT(*) AS n_eval,
                   SUM(CASE WHEN apuesta_1x2 LIKE '[GANADA]%' OR apuesta_ou LIKE '[GANADA]%' THEN 1 ELSE 0 END) AS n_ganados
            FROM partidos_backtest
            WHERE estado='Liquidado'
              AND (apuesta_1x2 LIKE '[GANADA]%' OR apuesta_1x2 LIKE '[PERDIDA]%'
                OR apuesta_ou  LIKE '[GANADA]%' OR apuesta_ou  LIKE '[PERDIDA]%')
            GROUP BY pais
        ),
        reales AS (
            SELECT pais,
                   COUNT(*) AS n_real,
                   SUM(CASE WHEN apuesta_1x2 LIKE '[GANADA]%' OR apuesta_ou LIKE '[GANADA]%' THEN 1 ELSE 0 END) AS n_real_g
            FROM partidos_backtest
            WHERE estado='Liquidado' AND (stake_1x2>0 OR stake_ou>0)
            GROUP BY pais
        ),
        vivas AS (
            SELECT pais, COUNT(*) AS n_vivas
            FROM partidos_backtest
            WHERE estado!='Liquidado' AND (stake_1x2>0 OR stake_ou>0)
            GROUP BY pais
        )
        SELECT e.pais,
               e.n_eval, e.n_ganados,
               ROUND(100.0 * e.n_ganados / NULLIF(e.n_eval,0), 1) AS hit_pretest,
               COALESCE(r.n_real, 0) AS n_real,
               COALESCE(r.n_real_g, 0) AS n_real_g,
               ROUND(100.0 * r.n_real_g / NULLIF(r.n_real,0), 1) AS hit_real,
               COALESCE(v.n_vivas, 0) AS n_vivas
        FROM evaluados e
        LEFT JOIN reales r ON r.pais = e.pais
        LEFT JOIN vivas  v ON v.pais = e.pais
        ORDER BY e.n_eval DESC
    """, con)

    # Estado LIVE/pretest por liga (1X2 y O/U)
    cur = con.cursor()
    cur.execute("""
        SELECT clave, scope, valor_texto FROM config_motor_valores
        WHERE clave IN ('apuestas_live','apuesta_ou_live')
    """)
    live_map = {}
    for clave, scope, val in cur.fetchall():
        is_live = str(val).upper() in ("TRUE", "1")
        live_map.setdefault(scope, {})[clave] = is_live

    # Apuestas vivas (futuras con stake>0) — separado 1X2 de O/U
    vivas_1x2 = pd.read_sql_query("""
        SELECT pais, fecha, local, visita,
               SUBSTR(apuesta_1x2, INSTR(apuesta_1x2, ']') + 2) AS pick,
               CASE
                   WHEN apuesta_1x2 LIKE '% LOCAL' THEN cuota_1
                   WHEN apuesta_1x2 LIKE '% VISITA' THEN cuota_2
                   WHEN apuesta_1x2 LIKE '% EMPATE' THEN cuota_x
               END AS cuota,
               CASE
                   WHEN apuesta_1x2 LIKE '% LOCAL' THEN prob_1
                   WHEN apuesta_1x2 LIKE '% VISITA' THEN prob_2
                   WHEN apuesta_1x2 LIKE '% EMPATE' THEN prob_x
               END AS prob_modelo,
               stake_1x2 AS stake
        FROM partidos_backtest
        WHERE estado != 'Liquidado'
          AND apuesta_1x2 LIKE '[APOSTAR]%'
          AND stake_1x2 > 0
        ORDER BY fecha ASC
    """, con)
    if not vivas_1x2.empty:
        vivas_1x2["mercado"] = "1X2"
        vivas_1x2["prob_mercado"] = 1.0 / vivas_1x2["cuota"]
        vivas_1x2["ev_pct"] = (vivas_1x2["prob_modelo"] * vivas_1x2["cuota"] - 1.0) * 100.0

    vivas_ou = pd.read_sql_query("""
        SELECT pais, fecha, local, visita,
               SUBSTR(apuesta_ou, INSTR(apuesta_ou, ']') + 2) AS pick,
               CASE WHEN apuesta_ou LIKE '% OVER%' THEN cuota_o25 ELSE cuota_u25 END AS cuota,
               CASE WHEN apuesta_ou LIKE '% OVER%' THEN prob_o25 ELSE prob_u25 END AS prob_modelo,
               stake_ou AS stake
        FROM partidos_backtest
        WHERE estado != 'Liquidado'
          AND apuesta_ou LIKE '[APOSTAR]%'
          AND stake_ou > 0
        ORDER BY fecha ASC
    """, con)
    if not vivas_ou.empty:
        vivas_ou["mercado"] = "O/U 2.5"
        vivas_ou["prob_mercado"] = 1.0 / vivas_ou["cuota"]
        vivas_ou["ev_pct"] = (vivas_ou["prob_modelo"] * vivas_ou["cuota"] - 1.0) * 100.0

    vivas = pd.concat([vivas_1x2, vivas_ou], ignore_index=True) if not (vivas_1x2.empty and vivas_ou.empty) else pd.DataFrame()

    # Historial: últimas 10 liquidadas por liga (picks 1X2 + O/U con stake>0, o solo evaluados si no hay stake>0)
    historial = pd.read_sql_query("""
        SELECT pais, fecha, local, visita,
               CASE WHEN apuesta_1x2 LIKE '[GANADA]%' OR apuesta_1x2 LIKE '[PERDIDA]%'
                    THEN SUBSTR(apuesta_1x2, INSTR(apuesta_1x2, ']') + 2) END AS pick_1x2,
               CASE WHEN apuesta_1x2 LIKE '[GANADA]%' THEN 'GANADA'
                    WHEN apuesta_1x2 LIKE '[PERDIDA]%' THEN 'PERDIDA' END AS resultado_1x2,
               stake_1x2,
               CASE WHEN apuesta_ou LIKE '[GANADA]%' OR apuesta_ou LIKE '[PERDIDA]%'
                    THEN SUBSTR(apuesta_ou, INSTR(apuesta_ou, ']') + 2) END AS pick_ou,
               CASE WHEN apuesta_ou LIKE '[GANADA]%' THEN 'GANADA'
                    WHEN apuesta_ou LIKE '[PERDIDA]%' THEN 'PERDIDA' END AS resultado_ou,
               stake_ou,
               goles_l, goles_v,
               CASE WHEN apuesta_1x2 LIKE '[GANADA]%' THEN
                      CASE WHEN apuesta_1x2 LIKE '% LOCAL' THEN cuota_1
                           WHEN apuesta_1x2 LIKE '% VISITA' THEN cuota_2
                           WHEN apuesta_1x2 LIKE '% EMPATE' THEN cuota_x END
               END AS cuota_ganada_1x2,
               CASE WHEN apuesta_ou LIKE '[GANADA]%' THEN
                      CASE WHEN apuesta_ou LIKE '% OVER%' THEN cuota_o25 ELSE cuota_u25 END
               END AS cuota_ganada_ou
        FROM partidos_backtest
        WHERE estado='Liquidado'
          AND (apuesta_1x2 LIKE '[GANADA]%' OR apuesta_1x2 LIKE '[PERDIDA]%'
            OR apuesta_ou  LIKE '[GANADA]%' OR apuesta_ou  LIKE '[PERDIDA]%')
        ORDER BY fecha DESC
    """, con)

    con.close()

    # Enriquecer ligas con LIVE tags
    def _tag_live(row):
        lv = live_map.get(row["pais"], {})
        tags = []
        if lv.get("apuestas_live"): tags.append("LIVE 1X2")
        if lv.get("apuesta_ou_live"): tags.append("LIVE O/U")
        return " · ".join(tags) if tags else "pretest"
    ligas["estado"] = ligas.apply(_tag_live, axis=1)

    return ligas, vivas, historial


def _color_hit(val):
    if pd.isna(val):
        return "color: #888"
    if val >= 60: return "color: #1db954; font-weight: bold"  # verde
    if val >= 50: return "color: #d4a017; font-weight: bold"  # amarillo
    return "color: #e74c3c; font-weight: bold"  # rojo


def _color_ev(val):
    if pd.isna(val): return ""
    if val >= 15: return "background-color: #0a5c2a; color: white; font-weight: bold"
    if val >= 8:  return "background-color: #1db954; color: white"
    if val >= 3:  return "background-color: #d4a017; color: white"
    return "background-color: #e74c3c; color: white"


def _color_resultado(val):
    if val == "GANADA": return "background-color: #1db954; color: white; font-weight: bold"
    if val == "PERDIDA": return "background-color: #e74c3c; color: white"
    return ""


def _flag(pais):
    return FLAGS.get(pais, "🌍")


# ============================================================================
# UI
# ============================================================================
st.title("🎯 Adepor — Picks del Día")
st.caption(f"Última actualización: {datetime.now().strftime('%d/%m/%Y %H:%M')}")

try:
    ligas, vivas, historial = cargar_datos()
except Exception as e:
    st.error(f"Error cargando DB: {e}")
    st.stop()

# ====================== HIT RATE POR LIGA ======================
st.header("📊 Hit rate por liga")

if ligas.empty:
    st.info("No hay datos de liquidaciones todavía.")
else:
    # Grid de cards colorido
    ligas_show = ligas.copy()
    ligas_show["Liga"] = ligas_show["pais"].apply(lambda p: f"{_flag(p)} {p}")
    ligas_show = ligas_show.rename(columns={
        "n_eval": "Evaluados",
        "n_ganados": "Ganados",
        "hit_pretest": "Hit %",
        "n_vivas": "Vivas",
        "estado": "Estado",
        "hit_real": "Hit real %",
        "n_real": "Reales liquidadas",
    })
    cols_show = ["Liga", "Estado", "Vivas", "Evaluados", "Ganados", "Hit %", "Reales liquidadas", "Hit real %"]
    st.dataframe(
        ligas_show[cols_show].style
            .map(_color_hit, subset=["Hit %", "Hit real %"])
            .format({"Hit %": "{:.1f}%", "Hit real %": "{:.1f}%"}, na_rep="—"),
        use_container_width=True,
        hide_index=True,
    )

# ====================== APUESTAS VIVAS POR LIGA ======================
st.header("🔴 Apuestas vivas (stake > 0)")

if vivas.empty:
    st.info("No hay apuestas vivas con stake > 0 en este momento.")
else:
    total_stake = vivas["stake"].sum()
    st.metric("Total stake activo", f"${total_stake:,.0f}", f"{len(vivas)} picks")

    paises_orden = ligas["pais"].tolist() + sorted(set(vivas["pais"]) - set(ligas["pais"]))
    for pais in paises_orden:
        sub = vivas[vivas["pais"] == pais].copy()
        if sub.empty:
            continue
        stake_liga = sub["stake"].sum()
        st.subheader(f"{_flag(pais)} {pais} — {len(sub)} picks · ${stake_liga:,.0f} en stake")

        sub["Partido"] = sub["local"] + " vs " + sub["visita"]
        sub = sub.rename(columns={
            "fecha": "Fecha",
            "mercado": "Mercado",
            "pick": "Pick",
            "cuota": "Cuota",
            "prob_modelo": "Prob modelo",
            "prob_mercado": "Prob mercado",
            "ev_pct": "EV %",
            "stake": "Stake $",
        })
        cols = ["Partido", "Fecha", "Mercado", "Pick", "Cuota",
                "Prob modelo", "Prob mercado", "EV %", "Stake $"]
        st.dataframe(
            sub[cols].style
                .map(_color_ev, subset=["EV %"])
                .format({
                    "Cuota": "{:.2f}",
                    "Prob modelo": "{:.1%}",
                    "Prob mercado": "{:.1%}",
                    "EV %": "+{:.1f}%",
                    "Stake $": "${:,.0f}",
                }, na_rep="—"),
            use_container_width=True,
            hide_index=True,
        )

# ====================== HISTORIAL POR LIGA ======================
st.header("📜 Historial por liga (últimas 10)")

if historial.empty:
    st.info("No hay historial liquidado todavía.")
else:
    paises_historial = historial["pais"].drop_duplicates().tolist()
    for pais in paises_historial:
        sub = historial[historial["pais"] == pais].head(10).copy()
        ganados = ((sub["resultado_1x2"] == "GANADA") | (sub["resultado_ou"] == "GANADA")).sum()
        total = len(sub)
        hit_recent = f"{100*ganados/total:.0f}%" if total else "—"

        with st.expander(f"{_flag(pais)} {pais} — {total} últimas · hit {hit_recent}"):
            sub["Partido"] = sub["local"] + " vs " + sub["visita"]
            sub["Resultado"] = sub["goles_l"].astype("Int64").astype(str) + "–" + sub["goles_v"].astype("Int64").astype(str)

            def _render_pick(row, mercado):
                pick = row[f"pick_{mercado}"]
                res = row[f"resultado_{mercado}"]
                if pick is None or (isinstance(pick, float) and pd.isna(pick)):
                    return "—"
                return f"{mercado.upper()}: {pick} [{res}]"

            sub["Pick 1X2"] = sub.apply(lambda r: _render_pick(r, "1x2"), axis=1)
            sub["Pick O/U"] = sub.apply(lambda r: _render_pick(r, "ou"), axis=1)
            sub = sub.rename(columns={
                "fecha": "Fecha",
                "resultado_1x2": "_res_1x2",
                "resultado_ou": "_res_ou",
                "stake_1x2": "Stake 1X2",
                "stake_ou":  "Stake O/U",
            })
            cols = ["Partido", "Fecha", "Resultado", "Pick 1X2", "Stake 1X2", "Pick O/U", "Stake O/U"]
            st.dataframe(
                sub[cols].style
                    .format({"Stake 1X2": "${:,.0f}", "Stake O/U": "${:,.0f}"}, na_rep="—"),
                use_container_width=True,
                hide_index=True,
            )

st.caption("Datos reales del motor cuantitativo Adepor. Read-only. Refresh automático cada 60s.")
