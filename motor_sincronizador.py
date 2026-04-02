import sqlite3
import os
from datetime import datetime
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side, numbers
from openpyxl.formatting.rule import FormulaRule
from openpyxl.utils import get_column_letter

# ==========================================
# MOTOR SINCRONIZADOR V9.0 (EXCEL LOCAL)
# Migrado de Google Sheets a Excel (.xlsx).
# Responsabilidad: Generar el archivo Excel de backtest con formulas vivas
# a partir de la base de datos SQLite (fuente de verdad).
# ==========================================

DB_NAME = 'fondo_quant.db'
EXCEL_FILE = 'Backtest_Modelo.xlsx'

# --- Mapa de columnas (1-indexed para openpyxl) ---
COL = {
    'fecha': 1, 'id': 2, 'partido': 3, 'local': 4, 'visita': 5,
    'c1': 6, 'cx': 7, 'c2': 8, 'co': 9, 'cu': 10,
    'liga': 11, 'p1': 12, 'px': 13, 'p2': 14, 'po': 15, 'pu': 16,
    'gl': 17, 'gv': 18,
    'ap1x2': 19, 'apou': 20, 'stk1x2': 21, 'stkou': 22,
    'acierto': 23, 'pl': 24, 'equity': 25, 'brier': 26,
    'incert': 27, 'auditoria': 28
}
HEADERS = {
    1: 'Fecha', 2: 'ID Partido', 3: 'Partido', 4: 'Local', 5: 'Visita',
    6: 'Cuota 1', 7: 'Cuota X', 8: 'Cuota 2', 9: 'Cuota +2.5', 10: 'Cuota -2.5',
    11: 'Liga', 12: 'Prob 1', 13: 'Prob X', 14: 'Prob 2', 15: 'Prob +2.5', 16: 'Prob -2.5',
    17: 'Goles L', 18: 'Goles V',
    19: 'Apuesta 1X2', 20: 'Apuesta O/U 2.5', 21: 'Stake 1X2', 22: 'Stake O/U 2.5',
    23: 'Acierto', 24: 'P/L Neto', 25: 'Equity Curve', 26: 'Brier Score',
    27: 'Incertidumbre', 28: 'Auditoria'
}
MAX_COL = max(COL.values())

# Letras de columna (precalculadas para formulas)
CL = {k: get_column_letter(v) for k, v in COL.items()}

# --- Estilos ---
FONT_HEADER = Font(name='Arial', bold=True, color='FFFFFF', size=10)
FONT_DATA = Font(name='Arial', size=10)
FILL_HEADER = PatternFill('solid', fgColor='1F4E79')
FILL_GANADA = PatternFill('solid', fgColor='C6EFCE')
FILL_PERDIDA = PatternFill('solid', fgColor='FFC7CE')
FILL_APOSTAR = PatternFill('solid', fgColor='FFEB9C')
ALIGN_CENTER = Alignment(horizontal='center', vertical='center')
ALIGN_LEFT = Alignment(horizontal='left', vertical='center')
BORDER_THIN = Border(
    left=Side(style='thin', color='D9D9D9'), right=Side(style='thin', color='D9D9D9'),
    top=Side(style='thin', color='D9D9D9'), bottom=Side(style='thin', color='D9D9D9')
)

# --- Anchos de columna ---
COL_WIDTHS = {
    'fecha': 12, 'id': 32, 'partido': 30, 'local': 20, 'visita': 20,
    'c1': 9, 'cx': 9, 'c2': 9, 'co': 9, 'cu': 9,
    'liga': 12, 'p1': 9, 'px': 9, 'p2': 9, 'po': 9, 'pu': 9,
    'gl': 8, 'gv': 8,
    'ap1x2': 28, 'apou': 28, 'stk1x2': 13, 'stkou': 13,
    'acierto': 22, 'pl': 13, 'equity': 15, 'brier': 12,
    'incert': 13, 'auditoria': 11
}


# ==========================================================================
# GENERADORES DE FORMULAS EXCEL
# ==========================================================================

def f_apuesta_1x2(r, ap_text):
    """Formula de auto-liquidacion para Apuesta 1X2."""
    ap = str(ap_text or "")
    if "[APOSTAR]" not in ap:
        return ap
    g = f'{CL["gl"]}{r}'
    v = f'{CL["gv"]}{r}'
    vacio = f'OR({g}="",{v}="")'
    if "LOCAL" in ap:
        return f'=IF({vacio},"[APOSTAR] LOCAL",IF({g}>{v},"[GANADA] LOCAL","[PERDIDA] LOCAL"))'
    if "EMPATE" in ap:
        return f'=IF({vacio},"[APOSTAR] EMPATE",IF({g}={v},"[GANADA] EMPATE","[PERDIDA] EMPATE"))'
    if "VISITA" in ap:
        return f'=IF({vacio},"[APOSTAR] VISITA",IF({g}<{v},"[GANADA] VISITA","[PERDIDA] VISITA"))'
    return ap

def f_apuesta_ou(r, ap_text):
    """Formula de auto-liquidacion para Apuesta O/U."""
    ap = str(ap_text or "")
    if "[APOSTAR]" not in ap:
        return ap
    g = f'{CL["gl"]}{r}'
    v = f'{CL["gv"]}{r}'
    vacio = f'OR({g}="",{v}="")'
    total = f'({g}+{v})'
    if "OVER" in ap:
        return f'=IF({vacio},"[APOSTAR] OVER 2.5",IF({total}>2.5,"[GANADA] OVER 2.5","[PERDIDA] OVER 2.5"))'
    if "UNDER" in ap:
        return f'=IF({vacio},"[APOSTAR] UNDER 2.5",IF({total}<2.5,"[GANADA] UNDER 2.5","[PERDIDA] UNDER 2.5"))'
    return ap

def f_acierto(r):
    """Formula: Compara prediccion del modelo (prob mas alta) vs resultado real."""
    p1, px, p2 = f'{CL["p1"]}{r}', f'{CL["px"]}{r}', f'{CL["p2"]}{r}'
    gl, gv = f'{CL["gl"]}{r}', f'{CL["gv"]}{r}'
    mx = f'MAX({p1},{px},{p2})'
    md = f'MEDIAN({p1},{px},{p2})'
    pred = f'IF({p1}={mx},"LOCAL",IF({px}={mx},"EMPATE","VISITA"))'
    res_l = f'IF({p1}={mx},IF({gl}>{gv},"[ACIERTO]","[FALLO]"),IF({px}={mx},IF({gl}={gv},"[ACIERTO]","[FALLO]"),IF({gl}<{gv},"[ACIERTO]","[FALLO]")))'
    return f'=IF({p1}="","",IF(({mx}-{md})>0.05,IF(OR({gl}="",{gv}=""),"[PREDICCION] "&{pred},{res_l}),"[PASAR] Margen Insuf"))'

def f_pl_neto(r):
    """Formula: P/L combinado de 1X2 + O/U."""
    s1, a1 = f'{CL["stk1x2"]}{r}', f'{CL["ap1x2"]}{r}'
    c1, cx, c2 = f'{CL["c1"]}{r}', f'{CL["cx"]}{r}', f'{CL["c2"]}{r}'
    so, ao = f'{CL["stkou"]}{r}', f'{CL["apou"]}{r}'
    co, cu = f'{CL["co"]}{r}', f'{CL["cu"]}{r}'
    pl1 = (f'IFERROR(IF({s1}=0,0,IF(ISNUMBER(SEARCH("[GANADA]",{a1})),'
           f'{s1}*(IF(ISNUMBER(SEARCH("LOCAL",{a1})),{c1},IF(ISNUMBER(SEARCH("EMPATE",{a1})),{cx},{c2}))-1),'
           f'IF(ISNUMBER(SEARCH("[PERDIDA]",{a1})),-{s1},0))),0)')
    plo = (f'IFERROR(IF({so}=0,0,IF(ISNUMBER(SEARCH("[GANADA]",{ao})),'
           f'{so}*(IF(ISNUMBER(SEARCH("OVER",{ao})),{co},{cu})-1),'
           f'IF(ISNUMBER(SEARCH("[PERDIDA]",{ao})),-{so},0))),0)')
    return f'={pl1}+{plo}'

def f_equity(r, bankroll):
    """Formula: Curva de equity acumulada."""
    pl = f'{CL["pl"]}{r}'
    eq_prev = f'{CL["equity"]}{r-1}'
    if r == 2:
        return f'={bankroll}+{pl}'
    return f'={eq_prev}+{pl}'

def f_brier(r):
    """Formula: Brier Score para mercado 1X2. Menor = mejor calibracion."""
    p1, px, p2 = f'{CL["p1"]}{r}', f'{CL["px"]}{r}', f'{CL["p2"]}{r}'
    gl, gv = f'{CL["gl"]}{r}', f'{CL["gv"]}{r}'
    return (f'=IF(OR({gl}="",{gv}=""),"",'
            f'({p1}-IF({gl}>{gv},1,0))^2+({px}-IF({gl}={gv},1,0))^2+({p2}-IF({gl}<{gv},1,0))^2)')


# ==========================================================================
# FUNCION PRINCIPAL
# ==========================================================================

def main():
    print("[SISTEMA] Iniciando Motor Sincronizador V9.0 (Excel Local)...")

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # --- Resurrection: partidos Liquidados sin goles vuelven a Calculado ---
    cursor.execute("""
        SELECT id_partido FROM partidos_backtest
        WHERE estado = 'Liquidado' AND (goles_l IS NULL OR goles_v IS NULL)
    """)
    resurrecciones = [r[0] for r in cursor.fetchall()]
    if resurrecciones:
        cursor.executemany(
            "UPDATE partidos_backtest SET estado = 'Calculado' WHERE id_partido = ?",
            [(i,) for i in resurrecciones]
        )
        conn.commit()
        print(f"[INFO] {len(resurrecciones)} partidos resucitados (Liquidado sin goles -> Calculado).")

    # --- Bankroll ---
    try:
        cursor.execute("SELECT valor FROM configuracion WHERE clave = 'bankroll'")
        BANKROLL = float(cursor.fetchone()[0])
    except (TypeError, IndexError):
        BANKROLL = 100000.00

    # --- Datos principales ---
    cursor.execute("""
        SELECT id_partido, fecha, local, visita, pais,
               prob_1, prob_x, prob_2, prob_o25, prob_u25,
               apuesta_1x2, apuesta_ou, stake_1x2, stake_ou,
               cuota_1, cuota_x, cuota_2, cuota_o25, cuota_u25,
               estado, goles_l, goles_v, incertidumbre, auditoria
        FROM partidos_backtest
        WHERE estado IN ('Calculado', 'Liquidado')
        ORDER BY fecha ASC, id_partido ASC
    """)
    datos = cursor.fetchall()
    conn.close()

    if not datos:
        print("[INFO] No hay partidos para sincronizar.")
        return

    print(f"[INFO] {len(datos)} partidos a sincronizar. Bankroll: ${BANKROLL:,.2f}")

    # --- Crear workbook ---
    wb = Workbook()
    ws = wb.active
    ws.title = "Backtest"

    # --- Headers ---
    for col_idx, header_text in HEADERS.items():
        cell = ws.cell(row=1, column=col_idx, value=header_text)
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER
        cell.alignment = ALIGN_CENTER
        cell.border = BORDER_THIN

    # --- Anchos de columna ---
    for key, width in COL_WIDTHS.items():
        ws.column_dimensions[CL[key]].width = width

    # --- Freeze y autofiltro ---
    ws.freeze_panes = 'A2'
    ws.auto_filter.ref = f'A1:{get_column_letter(MAX_COL)}1'

    # --- Estadisticas por liga (para hoja Resumen) ---
    stats_liga = {}

    # --- Escribir datos ---
    for idx, row_data in enumerate(datos):
        r = idx + 2  # Fila de Excel (1 = header)
        (id_p, fecha, local, visita, pais,
         p1, px, p2, po, pu,
         ap1x2, apou, stk1x2, stkou,
         c1, cx, c2, co, cu,
         estado, gl, gv, incert, auditoria) = row_data

        # --- Datos estaticos ---
        ws.cell(r, COL['fecha'], (fecha.split(" ")[0] if fecha else "")).font = FONT_DATA
        ws.cell(r, COL['id'], id_p).font = FONT_DATA
        ws.cell(r, COL['partido'], f"{local} vs {visita}").font = FONT_DATA
        ws.cell(r, COL['local'], local).font = FONT_DATA
        ws.cell(r, COL['visita'], visita).font = FONT_DATA
        ws.cell(r, COL['liga'], pais or "").font = FONT_DATA

        # Cuotas (como numeros)
        for key, val in [('c1', c1), ('cx', cx), ('c2', c2), ('co', co), ('cu', cu)]:
            cell = ws.cell(r, COL[key], val if val and val > 0 else None)
            cell.font = FONT_DATA
            cell.number_format = '0.00'

        # Probabilidades (como decimales, formato porcentaje)
        for key, val in [('p1', p1), ('px', px), ('p2', p2), ('po', po), ('pu', pu)]:
            cell = ws.cell(r, COL[key], val if val else None)
            cell.font = FONT_DATA
            cell.number_format = '0.0%'

        # Goles
        if gl is not None: ws.cell(r, COL['gl'], gl).font = FONT_DATA
        if gv is not None: ws.cell(r, COL['gv'], gv).font = FONT_DATA

        # Stakes (como numeros)
        for key, val in [('stk1x2', stk1x2), ('stkou', stkou)]:
            cell = ws.cell(r, COL[key], val if val and val > 0 else 0)
            cell.font = FONT_DATA
            cell.number_format = '#,##0.00'

        # Incertidumbre
        if incert:
            cell = ws.cell(r, COL['incert'], incert)
            cell.font = FONT_DATA
            cell.number_format = '0.000'

        # Auditoria
        ws.cell(r, COL['auditoria'], auditoria or "").font = FONT_DATA

        # --- Formulas de auto-liquidacion ---
        val_ap1x2 = f_apuesta_1x2(r, ap1x2)
        val_apou = f_apuesta_ou(r, apou)
        ws.cell(r, COL['ap1x2'], val_ap1x2).font = FONT_DATA
        ws.cell(r, COL['apou'], val_apou).font = FONT_DATA

        # --- Formulas calculadas ---
        ws.cell(r, COL['acierto'], f_acierto(r)).font = FONT_DATA
        ws.cell(r, COL['pl'], f_pl_neto(r)).font = FONT_DATA
        ws.cell(r, COL['pl']).number_format = '#,##0.00'
        ws.cell(r, COL['equity'], f_equity(r, BANKROLL)).font = FONT_DATA
        ws.cell(r, COL['equity']).number_format = '#,##0.00'
        ws.cell(r, COL['brier'], f_brier(r)).font = FONT_DATA
        ws.cell(r, COL['brier']).number_format = '0.0000'

        # --- Bordes ---
        for c in range(1, MAX_COL + 1):
            ws.cell(r, c).border = BORDER_THIN
            ws.cell(r, c).alignment = ALIGN_CENTER if c not in [COL['partido'], COL['local'], COL['visita'], COL['ap1x2'], COL['apou'], COL['acierto'], COL['id']] else ALIGN_LEFT

        # --- Acumular stats por liga ---
        if pais:
            if pais not in stats_liga:
                stats_liga[pais] = {'apuestas': 0, 'ganadas': 0, 'perdidas': 0, 'vol': 0.0, 'pl': 0.0}
            s = stats_liga[pais]
            for ap, stk, cuotas_dict in [
                (str(ap1x2 or ""), stk1x2 or 0, {'LOCAL': c1, 'EMPATE': cx, 'VISITA': c2}),
                (str(apou or ""), stkou or 0, {'OVER': co, 'UNDER': cu})
            ]:
                if stk > 0 and ("[GANADA]" in ap or "[PERDIDA]" in ap):
                    s['apuestas'] += 1
                    s['vol'] += stk
                    if "[GANADA]" in ap:
                        s['ganadas'] += 1
                        for k, v in cuotas_dict.items():
                            if k in ap and v and v > 0:
                                s['pl'] += stk * (v - 1)
                    else:
                        s['perdidas'] += 1
                        s['pl'] -= stk

    max_row = len(datos) + 1

    # --- Conditional formatting (colores en apuestas) ---
    rango_ap = f'{CL["ap1x2"]}2:{CL["apou"]}{max_row}'
    ws.conditional_formatting.add(rango_ap, FormulaRule(
        formula=[f'ISNUMBER(SEARCH("[GANADA]",{CL["ap1x2"]}2))'], fill=FILL_GANADA))
    ws.conditional_formatting.add(rango_ap, FormulaRule(
        formula=[f'ISNUMBER(SEARCH("[PERDIDA]",{CL["ap1x2"]}2))'], fill=FILL_PERDIDA))
    ws.conditional_formatting.add(rango_ap, FormulaRule(
        formula=[f'ISNUMBER(SEARCH("[APOSTAR]",{CL["ap1x2"]}2))'], fill=FILL_APOSTAR))

    # --- Hoja de Resumen ---
    ws2 = wb.create_sheet("Resumen")
    res_headers = ['Liga', 'Apuestas', 'Ganadas', 'Perdidas', '% Acierto', 'P/L Neto', 'Yield', 'Volumen']
    for i, h in enumerate(res_headers, 1):
        cell = ws2.cell(1, i, h)
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER
        cell.alignment = ALIGN_CENTER

    row_r = 2
    total_ap, total_g, total_p, total_vol, total_pl = 0, 0, 0, 0.0, 0.0
    for liga, s in sorted(stats_liga.items()):
        pct = (s['ganadas'] / s['apuestas'] * 100) if s['apuestas'] > 0 else 0
        yld = (s['pl'] / s['vol'] * 100) if s['vol'] > 0 else 0
        ws2.cell(row_r, 1, liga).font = FONT_DATA
        ws2.cell(row_r, 2, s['apuestas']).font = FONT_DATA
        ws2.cell(row_r, 3, s['ganadas']).font = FONT_DATA
        ws2.cell(row_r, 4, s['perdidas']).font = FONT_DATA
        c_pct = ws2.cell(row_r, 5, pct / 100)
        c_pct.font = FONT_DATA
        c_pct.number_format = '0.0%'
        c_pl = ws2.cell(row_r, 6, round(s['pl'], 2))
        c_pl.font = FONT_DATA
        c_pl.number_format = '#,##0.00'
        c_yld = ws2.cell(row_r, 7, yld / 100)
        c_yld.font = FONT_DATA
        c_yld.number_format = '0.0%'
        c_vol = ws2.cell(row_r, 8, round(s['vol'], 2))
        c_vol.font = FONT_DATA
        c_vol.number_format = '#,##0.00'
        total_ap += s['apuestas']
        total_g += s['ganadas']
        total_p += s['perdidas']
        total_vol += s['vol']
        total_pl += s['pl']
        row_r += 1

    # Fila de totales
    ws2.cell(row_r, 1, "TOTAL").font = Font(name='Arial', bold=True, size=10)
    ws2.cell(row_r, 2, total_ap).font = Font(name='Arial', bold=True, size=10)
    ws2.cell(row_r, 3, total_g).font = Font(name='Arial', bold=True, size=10)
    ws2.cell(row_r, 4, total_p).font = Font(name='Arial', bold=True, size=10)
    c = ws2.cell(row_r, 5, (total_g / total_ap) if total_ap > 0 else 0)
    c.font = Font(name='Arial', bold=True, size=10)
    c.number_format = '0.0%'
    c = ws2.cell(row_r, 6, round(total_pl, 2))
    c.font = Font(name='Arial', bold=True, size=10)
    c.number_format = '#,##0.00'
    c = ws2.cell(row_r, 7, (total_pl / total_vol) if total_vol > 0 else 0)
    c.font = Font(name='Arial', bold=True, size=10)
    c.number_format = '0.0%'
    c = ws2.cell(row_r, 8, round(total_vol, 2))
    c.font = Font(name='Arial', bold=True, size=10)
    c.number_format = '#,##0.00'

    # Anchos resumen
    for i, w in enumerate([14, 10, 10, 10, 10, 14, 10, 14], 1):
        ws2.column_dimensions[get_column_letter(i)].width = w
    ws2.freeze_panes = 'A2'

    # --- Metadata ---
    ws2.cell(row_r + 2, 1, f"Generado: {datetime.now().strftime('%d/%m/%Y %H:%M')}").font = Font(name='Arial', italic=True, size=9, color='888888')
    ws2.cell(row_r + 3, 1, f"Bankroll base: ${BANKROLL:,.2f}").font = Font(name='Arial', italic=True, size=9, color='888888')

    # --- Guardar ---
    wb.save(EXCEL_FILE)
    print(f"[EXITO] Excel generado: {os.path.abspath(EXCEL_FILE)}")
    print(f"[INFO] {len(datos)} partidos escritos. {len(stats_liga)} ligas resumidas.")
    print("[SISTEMA] Motor Sincronizador V9.0 ha finalizado su ejecucion.")

if __name__ == "__main__":
    main()
