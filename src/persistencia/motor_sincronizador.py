import sqlite3
import os
import math
from datetime import datetime, date as date_type
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.formatting.rule import FormulaRule
from openpyxl.utils import get_column_letter
from src.comun.resolucion import determinar_resultado_entero

# ==========================================
# MOTOR SINCRONIZADOR V9.2 (EXCEL LOCAL)
# ==========================================

DB_NAME    = 'fondo_quant.db'
EXCEL_FILE = 'Backtest_Modelo.xlsx'

# --- Mapa de columnas (1-indexed para openpyxl) ---
COL = {
    'fecha': 1, 'id': 2, 'partido': 3, 'local': 4, 'visita': 5,
    'c1': 6, 'cx': 7, 'c2': 8, 'co': 9, 'cu': 10,
    'liga': 11, 'p1': 12, 'px': 13, 'p2': 14, 'po': 15, 'pu': 16,
    'gl': 17, 'gv': 18,
    'ap1x2': 19, 'apou': 20, 'stk1x2': 21, 'stkou': 22,
    'acierto': 23, 'pl': 24, 'equity': 25,
    'brier': 26, 'brier_casa': 27,        # BS sistema y BS casa lado a lado
    'incert': 28, 'auditoria': 29
}
HEADERS = {
    1: 'Fecha', 2: 'ID Partido', 3: 'Partido', 4: 'Local', 5: 'Visita',
    6: 'Cuota 1', 7: 'Cuota X', 8: 'Cuota 2', 9: 'Cuota +2.5', 10: 'Cuota -2.5',
    11: 'Liga', 12: 'Prob 1', 13: 'Prob X', 14: 'Prob 2', 15: 'Prob +2.5', 16: 'Prob -2.5',
    17: 'Goles L', 18: 'Goles V',
    19: 'Apuesta 1X2', 20: 'Apuesta O/U 2.5', 21: 'Stake 1X2', 22: 'Stake O/U 2.5',
    23: 'Acierto', 24: 'P/L Neto', 25: 'Equity Curve',
    26: 'BS Sistema', 27: 'BS Casa',
    28: 'Incertidumbre', 29: 'Auditoria'
}
MAX_COL = max(COL.values())
CL = {k: get_column_letter(v) for k, v in COL.items()}

# ==========================================================================
# HELPER FILLS (fgColor + bgColor para que Excel CF renderice correctamente)
# ==========================================================================
def _fill(hex_color):
    return PatternFill(patternType='solid', fgColor=hex_color, bgColor=hex_color)

# --- Estilos generales ---
FONT_HEADER     = Font(name='Arial', bold=True, color='FFFFFF', size=10)
FONT_DATA       = Font(name='Arial', size=10)
FILL_HEADER     = _fill('1F4E79')
FILL_GANADA     = _fill('C6EFCE')
FILL_PERDIDA    = _fill('FFC7CE')
FILL_PASAR      = _fill('FFEB9C')
FILL_APOSTAR    = _fill('BDD7EE')
FILL_PREDICCION = _fill('9DC3E6')
ALIGN_CENTER    = Alignment(horizontal='center', vertical='center')
ALIGN_LEFT      = Alignment(horizontal='left',   vertical='center')
BORDER_THIN     = Border(
    left=Side(style='thin',   color='D9D9D9'), right=Side(style='thin',  color='D9D9D9'),
    top=Side(style='thin',    color='D9D9D9'), bottom=Side(style='thin', color='D9D9D9')
)

# --- Colores semaforo dashboard ---
FILL_VERDE    = _fill('C6EFCE')
FILL_AMARILLO = _fill('FFEB9C')
FILL_ROJO     = _fill('FFC7CE')
FILL_NEUTRO   = _fill('F2F2F2')

# --- Colores por pais (fila A:R en Backtest) ---
PAISES_CF = [
    ("Argentina", _fill('DEEAF1')),
    ("Brasil",    _fill('E2EFDA')),
    ("Noruega",   _fill('FFF2CC')),
    ("Turquia",   _fill('EAE0F0')),
    ("Inglaterra",_fill('FCE4D6')),
]

# --- Anchos de columna ---
COL_WIDTHS = {
    'fecha': 12, 'id': 32, 'partido': 30, 'local': 20, 'visita': 20,
    'c1': 9, 'cx': 9, 'c2': 9, 'co': 9, 'cu': 9,
    'liga': 12, 'p1': 9, 'px': 9, 'p2': 9, 'po': 9, 'pu': 9,
    'gl': 8, 'gv': 8,
    'ap1x2': 28, 'apou': 28, 'stk1x2': 13, 'stkou': 13,
    'acierto': 22, 'pl': 13, 'equity': 15,
    'brier': 12, 'brier_casa': 12,
    'incert': 13, 'auditoria': 11
}


# ==========================================================================
# GENERADORES DE FORMULAS EXCEL
# ==========================================================================

def f_apuesta_1x2(r, ap_text):
    ap = str(ap_text or "")
    if "[APOSTAR]" not in ap:
        return ap
    g = f'{CL["gl"]}{r}'; v = f'{CL["gv"]}{r}'
    vacio = f'OR({g}="",{v}="")'
    if "LOCAL"  in ap: return f'=IF({vacio},"[APOSTAR] LOCAL",IF({g}>{v},"[GANADA] LOCAL","[PERDIDA] LOCAL"))'
    if "EMPATE" in ap: return f'=IF({vacio},"[APOSTAR] EMPATE",IF({g}={v},"[GANADA] EMPATE","[PERDIDA] EMPATE"))'
    if "VISITA" in ap: return f'=IF({vacio},"[APOSTAR] VISITA",IF({g}<{v},"[GANADA] VISITA","[PERDIDA] VISITA"))'
    return ap

def f_apuesta_ou(r, ap_text):
    ap = str(ap_text or "")
    if "[APOSTAR]" not in ap:
        return ap
    g = f'{CL["gl"]}{r}'; v = f'{CL["gv"]}{r}'
    vacio = f'OR({g}="",{v}="")'; total = f'({g}+{v})'
    if "OVER"  in ap: return f'=IF({vacio},"[APOSTAR] OVER 2.5",IF({total}>2.5,"[GANADA] OVER 2.5","[PERDIDA] OVER 2.5"))'
    if "UNDER" in ap: return f'=IF({vacio},"[APOSTAR] UNDER 2.5",IF({total}<2.5,"[GANADA] UNDER 2.5","[PERDIDA] UNDER 2.5"))'
    return ap

def f_acierto(r):
    p1, px, p2 = f'{CL["p1"]}{r}', f'{CL["px"]}{r}', f'{CL["p2"]}{r}'
    gl, gv = f'{CL["gl"]}{r}', f'{CL["gv"]}{r}'
    mx   = f'MAX({p1},{px},{p2})'
    md   = f'MEDIAN({p1},{px},{p2})'
    pred = f'IF({p1}={mx},"LOCAL",IF({px}={mx},"EMPATE","VISITA"))'
    res  = f'IF({p1}={mx},IF({gl}>{gv},"[ACIERTO]","[FALLO]"),IF({px}={mx},IF({gl}={gv},"[ACIERTO]","[FALLO]"),IF({gl}<{gv},"[ACIERTO]","[FALLO]")))'
    return f'=IF({p1}="","",IF(({mx}-{md})>0.05,IF(OR({gl}="",{gv}=""),"[PREDICCION] "&{pred},{res}),"[PASAR] Margen Insuf"))'

def f_pl_neto(r):
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
    pl = f'{CL["pl"]}{r}'
    if r == 2: return f'={bankroll}+{pl}'
    return f'={CL["equity"]}{r-1}+{pl}'

def f_brier(r):
    """BS Sistema: probs del modelo Dixon-Coles vs resultado real. Rango 0-2."""
    p1, px, p2 = f'{CL["p1"]}{r}', f'{CL["px"]}{r}', f'{CL["p2"]}{r}'
    gl, gv = f'{CL["gl"]}{r}', f'{CL["gv"]}{r}'
    return (f'=IF(OR({gl}="",{gv}=""),"",'
            f'({p1}-IF({gl}>{gv},1,0))^2+({px}-IF({gl}={gv},1,0))^2+({p2}-IF({gl}<{gv},1,0))^2)')

def f_brier_casa(r):
    """BS Casa: probs implicitas del mercado (cuotas normalizadas) vs resultado real. Rango 0-2."""
    c1, cx, c2 = f'{CL["c1"]}{r}', f'{CL["cx"]}{r}', f'{CL["c2"]}{r}'
    gl, gv = f'{CL["gl"]}{r}', f'{CL["gv"]}{r}'
    chk = f'OR({gl}="",{gv}="",{c1}="",{c1}=0,{cx}="",{cx}=0,{c2}="",{c2}=0)'
    den = f'(1/{c1}+1/{cx}+1/{c2})'
    p1n = f'(1/{c1}/{den})'
    pxn = f'(1/{cx}/{den})'
    p2n = f'(1/{c2}/{den})'
    o1 = f'IF({gl}>{gv},1,0)'; ox = f'IF({gl}={gv},1,0)'; o2 = f'IF({gl}<{gv},1,0)'
    return f'=IF({chk},"",({p1n}-{o1})^2+({pxn}-{ox})^2+({p2n}-{o2})^2)'


# ==========================================================================
# CALCULO DE METRICAS DASHBOARD
# ==========================================================================

def _cuota_1x2(ap_text, c1, cx, c2):
    ap = str(ap_text or "")
    if "LOCAL"  in ap: return c1
    if "EMPATE" in ap: return cx
    if "VISITA" in ap: return c2
    return None

def _cuota_ou(ap_text, co, cu):
    ap = str(ap_text or "")
    if "OVER"  in ap: return co
    if "UNDER" in ap: return cu
    return None

def calcular_metricas_dashboard(datos, fraccion_kelly):
    bets_1x2, bets_ou = [], []
    bs_sis_list, bs_casa_list = [], []

    # Contadores para % Acierto P (columna Acierto del backtest: prediccion del modelo)
    pred_aciertos = 0
    pred_fallos   = 0

    for row in datos:
        (id_p, fecha, local, visita, pais,
         p1, px, p2, po, pu,
         ap1x2, apou, stk1x2, stkou,
         c1, cx, c2, co, cu,
         estado, gl, gv, incert, auditoria,
         _ap_shadow, _stk_shadow) = row

        if gl is None or gv is None:
            continue

        # --- Replica logica de f_acierto para contar [ACIERTO]/[FALLO] ---
        if p1 and px and p2:
            mx = max(p1, px, p2)
            vals = sorted([p1, px, p2])
            md = vals[1]
            if (mx - md) > 0.05:
                if p1 == mx:   pred = 'LOCAL'
                elif px == mx: pred = 'EMPATE'
                else:          pred = 'VISITA'
                real = 'LOCAL' if gl > gv else ('EMPATE' if gl == gv else 'VISITA')
                if pred == real: pred_aciertos += 1
                else:            pred_fallos   += 1

        # --- Apuestas ---
        if stk1x2 and stk1x2 > 0 and ap1x2:
            res = determinar_resultado_entero(ap1x2, gl, gv)
            if res != 0:
                cuota = _cuota_1x2(ap1x2, c1, cx, c2) or 0
                bets_1x2.append({'res': res, 'stk': stk1x2,
                                  'pl': stk1x2*(cuota-1) if res==1 else -stk1x2})

        if stkou and stkou > 0 and apou:
            res = determinar_resultado_entero(apou, gl, gv)
            if res != 0:
                cuota = _cuota_ou(apou, co, cu) or 0
                bets_ou.append({'res': res, 'stk': stkou,
                                'pl': stkou*(cuota-1) if res==1 else -stkou})

        # --- Brier Score ---
        if p1 and px and p2:
            o1 = 1 if gl > gv else 0
            ox = 1 if gl == gv else 0
            o2 = 1 if gl < gv else 0
            bs_sis_list.append((p1-o1)**2 + (px-ox)**2 + (p2-o2)**2)
            if c1 and c1 > 0 and cx and cx > 0 and c2 and c2 > 0:
                r1, rx, r2 = 1/c1, 1/cx, 1/c2
                tot = r1 + rx + r2
                p1m, pxm, p2m = r1/tot, rx/tot, r2/tot
                bs_casa_list.append((p1m-o1)**2 + (pxm-ox)**2 + (p2m-o2)**2)

    # % Acierto P: precision del modelo sobre todos los partidos con resultado
    pred_total = pred_aciertos + pred_fallos
    acierto_partidos = pred_aciertos / pred_total if pred_total > 0 else 0.0

    def _grupo(bets):
        n = len(bets)
        if n == 0:
            return {'n':0,'pl':0.0,'vol':0.0,'yield':0.0,'acierto_bets':0.0,'t':0.0,'p':1.0}
        pl      = sum(b['pl']  for b in bets)
        vol     = sum(b['stk'] for b in bets)
        ganadas = sum(1 for b in bets if b['res'] == 1)
        yld = pl / vol if vol > 0 else 0.0
        # % Acierto $: apuestas ganadoras / total apuestas
        acierto_bets = ganadas / n
        if n >= 2:
            ys     = [b['pl']/b['stk'] for b in bets]
            mean_y = sum(ys)/n
            var    = sum((y-mean_y)**2 for y in ys)/(n-1)
            std    = math.sqrt(var) if var > 0 else 0.0
            t      = (mean_y/(std/math.sqrt(n))) if std > 0 else 0.0
            p_v    = math.erfc(abs(t)/math.sqrt(2))
        else:
            t, p_v = 0.0, 1.0
        return {'n':n,'pl':pl,'vol':vol,'yield':yld,
                'acierto_bets': acierto_bets,
                't': round(t,4), 'p': round(p_v,4)}

    m_all = _grupo(bets_1x2 + bets_ou)
    m_1x2 = _grupo(bets_1x2)
    m_ou  = _grupo(bets_ou)

    bs_sis  = sum(bs_sis_list)/len(bs_sis_list)   if bs_sis_list  else 0.0
    bs_casa = sum(bs_casa_list)/len(bs_casa_list)  if bs_casa_list else 0.0

    return {
        'total': m_all, '1x2': m_1x2, 'ou': m_ou,
        'acierto_partidos': acierto_partidos,   # col Acierto del backtest
        'pred_aciertos': pred_aciertos,
        'pred_total':    pred_total,
        'bs_sis':  bs_sis,
        'bs_casa': bs_casa,
        'bs_glob': bs_sis - bs_casa,
        'fraccion_kelly': fraccion_kelly,
    }


# ==========================================================================
# SEMAFORO
# ==========================================================================
def _semaforo(valor, bueno, malo, mayor_es_mejor=True):
    if valor is None or valor == '—':
        return FILL_NEUTRO
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return FILL_NEUTRO
    if mayor_es_mejor:
        if v >= bueno: return FILL_VERDE
        if v >= malo:  return FILL_AMARILLO
        return FILL_ROJO
    else:
        if v <= bueno: return FILL_VERDE
        if v <= malo:  return FILL_AMARILLO
        return FILL_ROJO


# ==========================================================================
# HOJA DASHBOARD
# ==========================================================================

def crear_hoja_dashboard(wb, metricas, bankroll):
    ws = wb.create_sheet("Dashboard", 0)

    FONT_TITLE = Font(name='Arial', bold=True, color='FFFFFF', size=13)
    FONT_SEC   = Font(name='Arial', bold=True, color='FFFFFF', size=9)
    FONT_KPI   = Font(name='Arial', bold=True, size=10)
    FONT_VAL   = Font(name='Arial', size=10)
    FONT_SUB   = Font(name='Arial', italic=True, size=9, color='595959')
    FILL_TITLE_D  = _fill('1F4E79')
    FILL_SEC_D    = _fill('4472C4')
    FILL_HDR_COL  = _fill('2E75B6')
    BORDER_DB = Border(
        left=Side(style='thin', color='9DC3E6'), right=Side(style='thin', color='9DC3E6'),
        top=Side(style='thin',  color='9DC3E6'), bottom=Side(style='thin',color='9DC3E6')
    )

    ws.column_dimensions['A'].width = 34
    ws.column_dimensions['B'].width = 20
    ws.column_dimensions['C'].width = 20
    ws.column_dimensions['D'].width = 20

    # Titulo
    ws.merge_cells('A1:D1')
    c = ws.cell(1,1,"DASHBOARD DE RENDIMIENTO")
    c.font=FONT_TITLE; c.fill=FILL_TITLE_D
    c.alignment=Alignment(horizontal='center',vertical='center')
    ws.row_dimensions[1].height = 30

    ws.merge_cells('A2:D2')
    c = ws.cell(2,1,f"Generado: {datetime.now().strftime('%d/%m/%Y %H:%M')}   |   Bankroll: ${bankroll:,.2f}")
    c.font=FONT_SUB; c.fill=_fill('D6E4F0')
    c.alignment=Alignment(horizontal='center',vertical='center')
    ws.row_dimensions[2].height=15

    for ci, h in enumerate(['Metrica','Total','1X2','O/U'],1):
        c = ws.cell(3,ci,h)
        c.font=Font(name='Arial',bold=True,color='FFFFFF',size=10)
        c.fill=FILL_HDR_COL; c.alignment=Alignment(horizontal='center',vertical='center')
        c.border=BORDER_DB
    ws.row_dimensions[3].height=20

    m = metricas
    t_all, t_1x2, t_ou = m['total'], m['1x2'], m['ou']
    row = [4]  # mutable para closures

    def _sep(titulo):
        ws.merge_cells(f'A{row[0]}:D{row[0]}')
        c = ws.cell(row[0],1,titulo)
        c.font=FONT_SEC; c.fill=FILL_SEC_D
        c.alignment=Alignment(horizontal='left',vertical='center',indent=1)
        c.border=BORDER_DB
        ws.row_dimensions[row[0]].height=14
        row[0]+=1

    def _fila(metrica, vals, fmts, fills):
        r = row[0]
        bg = _fill('EBF3FB') if r%2==0 else _fill('FFFFFF')
        ws.row_dimensions[r].height=18
        c=ws.cell(r,1,metrica); c.font=FONT_KPI; c.fill=bg; c.border=BORDER_DB
        c.alignment=Alignment(horizontal='left',vertical='center',indent=1)
        for ci,(val,fmt,fill) in enumerate(zip(vals,fmts,fills),2):
            cell=ws.cell(r,ci,val); cell.font=FONT_VAL; cell.border=BORDER_DB
            cell.alignment=Alignment(horizontal='center',vertical='center')
            cell.fill = fill if fill else bg
            if   fmt=='pct': cell.number_format='0.00%'
            elif fmt=='cur': cell.number_format='#,##0.00'
            elif fmt=='d4':  cell.number_format='0.0000'
            elif fmt=='d2':  cell.number_format='0.00'
            elif fmt=='int': cell.number_format='0'
        row[0]+=1

    NA = '—'

    # ---- FINANCIERO ----
    _sep("  RESULTADOS FINANCIEROS")

    _fila("Ganancia neta",
          (t_all['pl'],    t_1x2['pl'],    t_ou['pl']),
          ('cur','cur','cur'),
          (_semaforo(t_all['pl'],  0, 0),
           _semaforo(t_1x2['pl'], 0, 0),
           _semaforo(t_ou['pl'],  0, 0)))

    # Yield: >5% bueno, 0-5% aceptable, <0% malo
    _fila("Yield",
          (t_all['yield'],   t_1x2['yield'],   t_ou['yield']),
          ('pct','pct','pct'),
          (_semaforo(t_all['yield'],  0.05, 0),
           _semaforo(t_1x2['yield'], 0.05, 0),
           _semaforo(t_ou['yield'],  0.05, 0)))

    _fila("Volumen apostado",
          (t_all['vol'],   t_1x2['vol'],   t_ou['vol']),
          ('cur','cur','cur'),
          (FILL_NEUTRO,FILL_NEUTRO,FILL_NEUTRO))

    _fila("N apuestas liquidadas",
          (t_all['n'],  t_1x2['n'],  t_ou['n']),
          ('int','int','int'),
          (FILL_NEUTRO,FILL_NEUTRO,FILL_NEUTRO))

    # ---- ACIERTO ----
    _sep("  TASA DE ACIERTO")

    # % Acierto P: [ACIERTO] / ([ACIERTO]+[FALLO]) de la columna Acierto del backtest
    # Solo aplica a 1X2 (la columna Acierto evalua las probs 1/X/2)
    ap = m['acierto_partidos']
    pt = m['pred_total']
    _fila(f"% Acierto P  (col. Acierto, {m['pred_aciertos']}/{pt} partidos)",
          (ap, ap, '—'),
          ('pct','pct',''),
          (_semaforo(ap, 0.55, 0.45),
           _semaforo(ap, 0.55, 0.45),
           FILL_NEUTRO))

    # % Acierto $: apuestas ganadoras / total apuestas colocadas
    _fila("% Acierto $  (apuestas ganadoras / total apostado)",
          (t_all['acierto_bets'],  t_1x2['acierto_bets'],  t_ou['acierto_bets']),
          ('pct','pct','pct'),
          (_semaforo(t_all['acierto_bets'],  0.55, 0.45),
           _semaforo(t_1x2['acierto_bets'], 0.55, 0.45),
           _semaforo(t_ou['acierto_bets'],  0.55, 0.45)))

    # % Acierto all = promedio entre % Acierto P (sistema) y % Acierto $ (apuestas).
    # En PRETEST MODE (stake=0 => sin apuestas reales), el promedio es enganoso
    # porque mezcla el buen acierto del sistema con 0% financiero por diseno.
    # Se muestra "N/A (pretest)" hasta que al menos una apuesta se haya movido.
    ap_sistema = m['acierto_partidos']
    pretest_total = (t_all['n'] == 0)
    pretest_1x2   = (t_1x2['n'] == 0)
    pretest_ou    = (t_ou['n']  == 0)
    NA_PRE = 'N/A (pretest)'
    all_total = NA_PRE if pretest_total else (ap_sistema + t_all['acierto_bets']) / 2
    all_1x2   = NA_PRE if pretest_1x2   else (ap_sistema + t_1x2['acierto_bets']) / 2
    all_ou    = NA_PRE if pretest_ou    else t_ou['acierto_bets']
    _fila("% Acierto all  (promedio sistema + apuestas; N/A hasta que corra dinero)",
          (all_total, all_1x2, all_ou),
          ('' if pretest_total else 'pct',
           '' if pretest_1x2   else 'pct',
           '' if pretest_ou    else 'pct'),
          (FILL_NEUTRO if pretest_total else _semaforo(all_total, 0.55, 0.45),
           FILL_NEUTRO if pretest_1x2   else _semaforo(all_1x2,   0.55, 0.45),
           FILL_NEUTRO if pretest_ou    else _semaforo(all_ou,    0.55, 0.45)))

    # ---- ESTADISTICA ----
    _sep("  ESTADISTICA INFERENCIAL")

    _fila("T-score",
          (t_all['t'],  t_1x2['t'],  t_ou['t']),
          ('d2','d2','d2'),
          (_semaforo(abs(t_all['t']),  2.0, 1.0),
           _semaforo(abs(t_1x2['t']), 2.0, 1.0),
           _semaforo(abs(t_ou['t']),  2.0, 1.0)))

    _fila("P-Value  (two-tailed, <0.05 = significativo)",
          (t_all['p'],  t_1x2['p'],  t_ou['p']),
          ('d4','d4','d4'),
          (_semaforo(t_all['p'],  0.05, 0.10, mayor_es_mejor=False),
           _semaforo(t_1x2['p'], 0.05, 0.10, mayor_es_mejor=False),
           _semaforo(t_ou['p'],  0.05, 0.10, mayor_es_mejor=False)))

    fk = m['fraccion_kelly']
    _fila("Fraccion Kelly",
          (fk, fk, NA), ('pct','pct',''),
          (FILL_NEUTRO, FILL_NEUTRO, FILL_NEUTRO))

    # ---- CALIBRACION (BS rango 0-2, aleatorio puro ≈ 0.667) ----
    _sep("  CALIBRACION DEL MODELO  (Brier Score — rango 0 a 2, aleatorio ≈ 0.667, menor es mejor)")

    bs_s = m['bs_sis']; bs_c = m['bs_casa']; bs_g = m['bs_glob']

    # BS por partido (promedio): verde <0.50, amarillo 0.50-0.65, rojo >0.65
    _fila("BS Sistema  (promedio por partido, Dixon-Coles)",
          (bs_s, bs_s, NA), ('d4','d4',''),
          (_semaforo(bs_s, 0.50, 0.65, mayor_es_mejor=False), FILL_NEUTRO, FILL_NEUTRO))

    _fila("BS Casa  (promedio por partido, cuotas mercado)",
          (bs_c, bs_c, NA), ('d4','d4',''),
          (_semaforo(bs_c, 0.50, 0.65, mayor_es_mejor=False), FILL_NEUTRO, FILL_NEUTRO))

    _fila("BS Global  (Sistema - Casa, negativo = modelo supera mercado)",
          (bs_g, bs_g, NA), ('d4','d4',''),
          (_semaforo(bs_g, -0.02, 0.02, mayor_es_mejor=False), FILL_NEUTRO, FILL_NEUTRO))

    # Nota leyenda semáforo
    ws.merge_cells(f'A{row[0]+1}:D{row[0]+1}')
    c = ws.cell(row[0]+1, 1,
        "Yield >5%=verde | 0-5%=amarillo | <0%=rojo    "
        "BS <0.50=verde | 0.50-0.65=amarillo | >0.65=rojo    "
        "P-Value <0.05=verde | 0.05-0.10=amarillo | >0.10=rojo    "
        "BS Global negativo = modelo supera al mercado")
    c.font = Font(name='Arial', italic=True, size=8, color='595959')
    c.alignment = Alignment(horizontal='left', vertical='center', indent=1)
    row[0] += 3

    # ---- ESTRATEGIA ACTIVA ----
    ws.merge_cells(f'A{row[0]}:D{row[0]}')
    c = ws.cell(row[0], 1, "  ESTRATEGIA ACTIVA  (Motor Calculadora V4.3)")
    c.font = FONT_SEC; c.fill = _fill('375623')
    c.alignment = Alignment(horizontal='left', vertical='center', indent=1)
    c.border = BORDER_DB
    ws.row_dimensions[row[0]].height = 14
    row[0] += 1

    FILL_CFG = _fill('EBF3EB')
    FONT_CFG_K = Font(name='Arial', bold=True, size=9)
    FONT_CFG_V = Font(name='Arial', size=9)

    def _cfg(param, valor, nota=''):
        r = row[0]
        bg = FILL_CFG if r % 2 == 0 else _fill('FFFFFF')
        ws.row_dimensions[r].height = 15
        ws.merge_cells(f'A{r}:B{r}')
        ck = ws.cell(r, 1, param)
        ck.font = FONT_CFG_K; ck.fill = bg; ck.border = BORDER_DB
        ck.alignment = Alignment(horizontal='left', vertical='center', indent=2)
        ws.merge_cells(f'C{r}:D{r}')
        cv = ws.cell(r, 3, valor)
        cv.font = FONT_CFG_V; cv.fill = _fill('C6EFCE') if nota == 'activo' else bg
        cv.border = BORDER_DB
        cv.alignment = Alignment(horizontal='left', vertical='center', indent=1)
        row[0] += 1

    _cfg("Floor prob mínima",         "33%  — ningún outcome por debajo de este piso")
    _cfg("EV mínimo escalado",         "prob≥50%->3%  |  prob 40-50%->8%  |  prob 33-40%->12%")
    _cfg("Bloqueo empates",            "ACTIVO — sobreestimación sistémica +7.9% vs real", 'activo')
    _cfg("Camino 2B — Desacuerdo",     "modelo≠mercado + prob≥40% + div 15-30% + EV escalado")
    _cfg("Camino 3 — Alta Convicción", "prob≥33% + EV≥100% + cuota≤8.0")
    _cfg("xG Margen O/U",             "apostar O/U solo si |xG_total − 2.5| ≥ 0.4 goles")
    _cfg("Margen predictivo 1X2",      "diferencia entre 1º y 2º prob del modelo ≥ 3%")
    _cfg("Divergencia normal",         "prob_modelo − prob_implícita_mercado ≤ 15%")
    _cfg("Techo cuota normal",         "≤ 5.0  (relajado a 8.0 en Caminos 2B y 3)")
    _cfg("Kelly fraccionado",          f"{m['fraccion_kelly']:.0%} del Kelly óptimo (Thorp 2006)")

    ws.freeze_panes = 'A4'


# ==========================================================================
# FUNCION PRINCIPAL
# ==========================================================================

def crear_hoja_sombra(wb, datos, bankroll):
    """
    Pestaña de auditoria comparativa entre Opcion 1 (activa) y Opcion 4 (shadow).
    Opcion 1: floor 33% + EV escalado — apuesta activa
    Opcion 4: floor 33% sin EV escalado + fallback si prob baja — guardada para comparar
    """
    ws = wb.create_sheet("Sombra")

    FONT_TITLE = Font(name='Arial', bold=True, color='FFFFFF', size=11)
    FONT_HDR   = Font(name='Arial', bold=True, color='FFFFFF', size=10)
    FONT_KPI   = Font(name='Arial', bold=True, size=10)
    FONT_D     = Font(name='Arial', size=10)
    FONT_SUB   = Font(name='Arial', italic=True, size=9, color='595959')
    FILL_HDR1  = _fill('2E75B6')
    FILL_HDR4  = _fill('548235')
    FILL_NEUTRO_ROW  = _fill('F5F5F5')
    FILL_BLANCO      = _fill('FFFFFF')
    # Colores celdas individuales
    FILL_GANADA_CELL = _fill('C6EFCE')   # verde
    FILL_PERDIDA_CELL= _fill('FFC7CE')   # rojo
    FILL_PEND_CELL   = _fill('FFEB9C')   # amarillo
    # Colores resumen KPI
    FILL_MEJOR  = _fill('C6EFCE')        # verde = estrategia ganadora
    FILL_PEOR   = _fill('FFC7CE')        # rojo  = estrategia perdedora
    FILL_IGUAL  = _fill('F2F2F2')        # gris  = empate o neutro
    BORDER = Border(
        left=Side(style='thin', color='D9D9D9'), right=Side(style='thin', color='D9D9D9'),
        top=Side(style='thin', color='D9D9D9'),  bottom=Side(style='thin', color='D9D9D9')
    )

    # Anchos de columna
    # A=Fecha B=Partido C=Liga | D=Ap1 E=Stk1 F=Res1 G=PL1 | H=Ap4 I=Stk4 J=Res4 K=PL4 | L=Diff M=Op1G N=Op4G
    for ci, w in enumerate([13, 30, 12, 20, 11, 12, 13,  20, 11, 12, 13,  13, 9, 9], 1):
        ws.column_dimensions[get_column_letter(ci)].width = w

    # ---- Titulo ----
    ws.merge_cells('A1:N1')
    c = ws.cell(1, 1, "AUDITORIA COMPARATIVA: OPCION 1 (ACTIVA) vs OPCION 4 (SHADOW)")
    c.font = FONT_TITLE; c.fill = _fill('1F4E79')
    c.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[1].height = 24

    ws.merge_cells('A2:N2')
    c = ws.cell(2, 1,
        "Op1 = Floor 33% + EV escalado + Caminos 2B/3 + Bloqueo empates + xG Margen O/U  (apuesta real)   |   "
        "Op4 = Floor 33% sin EV escalado + fallback prob baja (shadow, solo auditoria)")
    c.font = FONT_SUB; c.fill = _fill('D6E4F0')
    c.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[2].height = 14

    # ---- Headers fila 3 ----
    # Bloque Op1: cols 1-7, Bloque Op4: cols 8-14
    hdrs = [
        ('A3:C3', 'PARTIDO',          _fill('4472C4')),
        ('D3:G3', 'OPCION 1 (ACTIVA)',FILL_HDR1),
        ('H3:K3', 'OPCION 4 (SHADOW)',FILL_HDR4),
        ('L3:N3', 'DIFERENCIA',       _fill('7030A0')),
    ]
    for rng, txt, fill in hdrs:
        ws.merge_cells(rng)
        c = ws.cell(3, ord(rng[0]) - 64, txt)
        c.font = FONT_HDR; c.fill = fill
        c.alignment = Alignment(horizontal='center', vertical='center')
        c.border = BORDER
    ws.row_dimensions[3].height = 16

    # ---- Headers fila 4 (columnas individuales) ----
    col_hdrs = [
        'Fecha','Partido','Liga',
        'Apuesta Op1','Stake Op1','Resultado Op1','P/L Op1',
        'Apuesta Op4','Stake Op4','Resultado Op4','P/L Op4',
        'Dif P/L','Op1 Win','Op4 Win',
    ]
    fills_hdr = [_fill('4472C4')]*3 + [FILL_HDR1]*4 + [FILL_HDR4]*4 + [_fill('7030A0')]*3
    for ci, (h, f) in enumerate(zip(col_hdrs, fills_hdr), 1):
        c = ws.cell(4, ci, h)
        c.font = FONT_HDR; c.fill = f
        c.alignment = Alignment(horizontal='center', vertical='center')
        c.border = BORDER
    ws.row_dimensions[4].height = 18
    ws.freeze_panes = 'A5'

    # ---- Datos ----
    data_row = 5
    stats = {'op1': {'n':0,'g':0,'pl':0.0,'vol':0.0},
             'op4': {'n':0,'g':0,'pl':0.0,'vol':0.0}}

    for rd in datos:
        (id_p, fecha, local, visita, pais,
         p1, px, p2, po, pu,
         ap1x2, apou, stk1x2, stkou,
         c1, cx, c2, co, cu,
         estado, gl, gv, incert, auditoria,
         ap_shadow, stk_shadow) = rd

        tiene_op1 = bool(stk1x2 and stk1x2 > 0 and ap1x2 and "[APOSTAR]" in str(ap1x2))
        tiene_op4 = bool(stk_shadow and stk_shadow > 0 and ap_shadow and "[APOSTAR]" in str(ap_shadow))
        if not tiene_op1 and not tiene_op4:
            continue

        fecha_disp = (fecha or "")[:10]
        for _fmt in ("%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M", "%Y-%m-%d", "%d/%m/%Y"):
            try:
                fecha_disp = datetime.strptime((fecha or "").strip(), _fmt).strftime("%d/%m/%Y")
                break
            except ValueError:
                continue

        # --- Op1 resultado ---
        res_op1 = determinar_resultado_entero(ap1x2, gl, gv) if tiene_op1 else 0
        if tiene_op1 and res_op1 != 0:
            cuota_op1 = _cuota_1x2(ap1x2, c1, cx, c2) or 0
            pl_op1 = round(stk1x2*(cuota_op1-1) if res_op1==1 else -stk1x2, 2)
            stats['op1']['n'] += 1; stats['op1']['vol'] += stk1x2
            if res_op1 == 1: stats['op1']['g'] += 1
            stats['op1']['pl'] += pl_op1
            res_op1_str = "GANADA" if res_op1==1 else "PERDIDA"
            fill_res1   = FILL_GANADA_CELL if res_op1==1 else FILL_PERDIDA_CELL
            fill_pl1    = FILL_GANADA_CELL if pl_op1>0 else FILL_PERDIDA_CELL
        else:
            pl_op1=None; res_op1_str="PENDIENTE" if gl is None else "-"
            fill_res1=FILL_PEND_CELL if gl is None else FILL_BLANCO
            fill_pl1=FILL_BLANCO

        # --- Op4 resultado ---
        res_op4 = determinar_resultado_entero(ap_shadow, gl, gv) if tiene_op4 else 0
        if tiene_op4 and res_op4 != 0:
            cuota_op4 = _cuota_1x2(ap_shadow, c1, cx, c2) or 0
            pl_op4 = round(stk_shadow*(cuota_op4-1) if res_op4==1 else -stk_shadow, 2)
            stats['op4']['n'] += 1; stats['op4']['vol'] += stk_shadow
            if res_op4 == 1: stats['op4']['g'] += 1
            stats['op4']['pl'] += pl_op4
            res_op4_str = "GANADA" if res_op4==1 else "PERDIDA"
            fill_res4   = FILL_GANADA_CELL if res_op4==1 else FILL_PERDIDA_CELL
            fill_pl4    = FILL_GANADA_CELL if pl_op4>0 else FILL_PERDIDA_CELL
        else:
            pl_op4=None; res_op4_str="PENDIENTE" if gl is None else "-"
            fill_res4=FILL_PEND_CELL if gl is None else FILL_BLANCO
            fill_pl4=FILL_BLANCO

        pl_diff = round(pl_op1 - pl_op4, 2) if (pl_op1 is not None and pl_op4 is not None) else None
        fill_diff = (FILL_GANADA_CELL if pl_diff>0 else (FILL_PERDIDA_CELL if pl_diff<0 else FILL_IGUAL)) \
                    if pl_diff is not None else FILL_BLANCO

        bg = FILL_BLANCO if data_row % 2 == 0 else FILL_NEUTRO_ROW

        # Escribir celda a celda con fills individuales
        def _dc(ci, val, fill=None, fmt=None, left_align=False):
            cell = ws.cell(data_row, ci, val)
            cell.font = FONT_D
            cell.fill = fill or bg
            cell.border = BORDER
            cell.alignment = Alignment(
                horizontal='left' if left_align else 'center', vertical='center')
            if fmt: cell.number_format = fmt

        _dc(1, fecha_disp)
        _dc(2, f"{local} vs {visita}", left_align=True)
        _dc(3, pais)
        _dc(4, str(ap1x2 or "-"), left_align=True)
        _dc(5, stk1x2 if tiene_op1 else "-", fmt='#,##0.00')
        _dc(6, res_op1_str, fill=fill_res1)
        _dc(7, pl_op1,      fill=fill_pl1,  fmt='#,##0.00')
        _dc(8, str(ap_shadow or "-"), left_align=True)
        _dc(9, stk_shadow if tiene_op4 else "-", fmt='#,##0.00')
        _dc(10, res_op4_str, fill=fill_res4)
        _dc(11, pl_op4,      fill=fill_pl4,  fmt='#,##0.00')
        _dc(12, pl_diff,     fill=fill_diff, fmt='#,##0.00')
        _dc(13, "SI" if res_op1==1 else ("NO" if res_op1==-1 else "-"),
            fill=FILL_GANADA_CELL if res_op1==1 else (FILL_PERDIDA_CELL if res_op1==-1 else bg))
        _dc(14, "SI" if res_op4==1 else ("NO" if res_op4==-1 else "-"),
            fill=FILL_GANADA_CELL if res_op4==1 else (FILL_PERDIDA_CELL if res_op4==-1 else bg))

        ws.row_dimensions[data_row].height = 16
        data_row += 1

    # ---- Resumen al pie ----
    data_row += 1
    o1, o4 = stats['op1'], stats['op4']
    n1, n4 = o1['n'], o4['n']

    # Header resumen
    ws.merge_cells(f'A{data_row}:N{data_row}')
    c = ws.cell(data_row, 1, "RESUMEN COMPARATIVO DE RENDIMIENTO")
    c.font = FONT_HDR; c.fill = _fill('1F4E79')
    c.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[data_row].height = 18
    data_row += 1

    # Sub-headers del resumen
    for ci, (h, f) in enumerate(zip(
        ['KPI', 'Opcion 1 (Activa)', '', 'Opcion 4 (Shadow)', '', 'Mejor'],
        [_fill('4472C4'), FILL_HDR1, FILL_HDR1, FILL_HDR4, FILL_HDR4, _fill('7030A0')]
    ), 1):
        if h:
            c = ws.cell(data_row, ci, h)
            c.font = FONT_HDR; c.fill = f
            c.alignment = Alignment(horizontal='center', vertical='center')
            c.border = BORDER
    ws.row_dimensions[data_row].height = 16
    data_row += 1

    def _kpi(label, v1, v4, fmt='num', mayor_es_mejor=True, neutro=False):
        """Escribe una fila KPI coloreando verde la mejor y rojo la peor."""
        ws.row_dimensions[data_row].height = 17
        c = ws.cell(data_row, 1, label)
        c.font = FONT_KPI
        c.alignment = Alignment(horizontal='left', vertical='center', indent=1)
        c.border = BORDER

        def fmt_cell(ci, val, fill):
            cell = ws.cell(data_row, ci, val)
            cell.font = FONT_D; cell.fill = fill; cell.border = BORDER
            cell.alignment = Alignment(horizontal='center', vertical='center')
            if fmt == 'cur':  cell.number_format = '#,##0.00'
            elif fmt == 'pct': cell.number_format = '0.00%'
            elif fmt == 'int': cell.number_format = '0'

        if neutro or v1 == v4:
            f1 = f4 = FILL_IGUAL
            mejor_txt = "="
        elif mayor_es_mejor:
            f1 = FILL_MEJOR if v1 > v4 else FILL_PEOR
            f4 = FILL_MEJOR if v4 > v1 else FILL_PEOR
            mejor_txt = "Op1" if v1 > v4 else "Op4"
        else:
            f1 = FILL_MEJOR if v1 < v4 else FILL_PEOR
            f4 = FILL_MEJOR if v4 < v1 else FILL_PEOR
            mejor_txt = "Op1" if v1 < v4 else "Op4"

        fmt_cell(2, v1, f1)
        fmt_cell(3, v1, f1)   # columna extra para visual
        fmt_cell(4, v4, f4)
        fmt_cell(5, v4, f4)
        c6 = ws.cell(data_row, 6, mejor_txt)
        c6.font = Font(name='Arial', bold=True, size=10)
        c6.fill = FILL_MEJOR if mejor_txt not in ("-","=") else FILL_IGUAL
        c6.alignment = Alignment(horizontal='center', vertical='center')
        c6.border = BORDER

    yld1 = o1['pl']/o1['vol'] if o1['vol'] else 0
    yld4 = o4['pl']/o4['vol'] if o4['vol'] else 0
    hit1 = o1['g']/n1 if n1 else 0
    hit4 = o4['g']/n4 if n4 else 0

    _kpi("N apuestas liquidadas", n1,         n4,         'int', neutro=True)
    data_row += 1
    _kpi("Ganadas",               o1['g'],    o4['g'],    'int')
    data_row += 1
    _kpi("Hit rate",              hit1,       hit4,       'pct')
    data_row += 1
    _kpi("Volumen apostado",      o1['vol'],  o4['vol'],  'cur', neutro=True)
    data_row += 1
    _kpi("P/L neto",              o1['pl'],   o4['pl'],   'cur')
    data_row += 1
    _kpi("Yield",                 yld1,       yld4,       'pct')
    data_row += 1

    data_row += 1
    ws.merge_cells(f'A{data_row}:N{data_row}')
    c = ws.cell(data_row, 1,
        "Verde = celda ganadora en ese KPI / partido   |   Rojo = celda perdedora   |   "
        "Amarillo en Resultado = pendiente de liquidar   |   "
        "Op1 activa desde V4.3: empates bloqueados + xG Margen O/U + Camino 2B (desacuerdo) + Camino 3 (alta conv.)")
    c.font = FONT_SUB
    c.alignment = Alignment(horizontal='left', vertical='center', indent=1)


def main():
    print("[SISTEMA] Iniciando Motor Sincronizador V9.3 (Excel Local)...")

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

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
        print(f"[INFO] {len(resurrecciones)} partidos resucitados.")

    try:
        cursor.execute("SELECT valor FROM configuracion WHERE clave = 'bankroll'")
        BANKROLL = float(cursor.fetchone()[0])
    except (TypeError, IndexError):
        BANKROLL = 100000.00

    try:
        cursor.execute("SELECT valor FROM configuracion WHERE clave = 'fraccion_kelly'")
        row_fk = cursor.fetchone()
        FRACCION_KELLY = float(row_fk[0]) if row_fk else 0.50
    except Exception:
        FRACCION_KELLY = 0.50

    cursor.execute("""
        SELECT id_partido, fecha, local, visita, pais,
               prob_1, prob_x, prob_2, prob_o25, prob_u25,
               apuesta_1x2, apuesta_ou, stake_1x2, stake_ou,
               cuota_1, cuota_x, cuota_2, cuota_o25, cuota_u25,
               estado, goles_l, goles_v, incertidumbre, auditoria,
               apuesta_shadow_1x2, stake_shadow_1x2
        FROM partidos_backtest
        WHERE estado IN ('Calculado', 'Liquidado')
        ORDER BY id_partido ASC
    """)
    datos = cursor.fetchall()
    conn.close()

    if not datos:
        print("[INFO] No hay partidos para sincronizar.")
        return

    print(f"[INFO] {len(datos)} partidos a sincronizar. Bankroll: ${BANKROLL:,.2f}")

    wb = Workbook()
    ws = wb.active
    ws.title = "Backtest"

    for col_idx, header_text in HEADERS.items():
        cell = ws.cell(row=1, column=col_idx, value=header_text)
        cell.font = FONT_HEADER; cell.fill = FILL_HEADER
        cell.alignment = ALIGN_CENTER; cell.border = BORDER_THIN

    for key, width in COL_WIDTHS.items():
        ws.column_dimensions[CL[key]].width = width

    ws.freeze_panes = 'A2'
    ws.auto_filter.ref = f'A1:{get_column_letter(MAX_COL)}1'

    stats_liga = {}
    ALIGN_LEFT_COLS = {COL['partido'], COL['local'], COL['visita'],
                       COL['ap1x2'], COL['apou'], COL['acierto'], COL['id']}

    for idx, row_data in enumerate(datos):
        r = idx + 2
        (id_p, fecha, local, visita, pais,
         p1, px, p2, po, pu,
         ap1x2, apou, stk1x2, stkou,
         c1, cx, c2, co, cu,
         estado, gl, gv, incert, auditoria,
         ap_shadow, stk_shadow) = row_data

        # Escribir como objeto date real para que Excel ordene correctamente
        fecha_val = fecha or ""
        for _fmt in ("%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M", "%Y-%m-%d", "%d/%m/%Y"):
            try:
                fecha_val = datetime.strptime((fecha or "").strip(), _fmt).date()
                break
            except ValueError:
                continue
        cell_fecha = ws.cell(r, COL['fecha'], fecha_val)
        cell_fecha.font = FONT_DATA
        if isinstance(fecha_val, date_type):
            cell_fecha.number_format = 'DD/MM/YYYY'
        ws.cell(r, COL['id'],      id_p).font             = FONT_DATA
        ws.cell(r, COL['partido'], f"{local} vs {visita}").font = FONT_DATA
        ws.cell(r, COL['local'],   local).font             = FONT_DATA
        ws.cell(r, COL['visita'],  visita).font            = FONT_DATA
        ws.cell(r, COL['liga'],    pais or "").font        = FONT_DATA

        for key, val in [('c1',c1),('cx',cx),('c2',c2),('co',co),('cu',cu)]:
            cell = ws.cell(r, COL[key], val if val and val > 0 else None)
            cell.font = FONT_DATA; cell.number_format = '0.00'

        for key, val in [('p1',p1),('px',px),('p2',p2),('po',po),('pu',pu)]:
            cell = ws.cell(r, COL[key], val if val else None)
            cell.font = FONT_DATA; cell.number_format = '0.0%'

        if gl is not None: ws.cell(r, COL['gl'], gl).font = FONT_DATA
        if gv is not None: ws.cell(r, COL['gv'], gv).font = FONT_DATA

        for key, val in [('stk1x2', stk1x2), ('stkou', stkou)]:
            cell = ws.cell(r, COL[key], val if val and val > 0 else 0)
            cell.font = FONT_DATA; cell.number_format = '#,##0.00'

        if incert:
            cell = ws.cell(r, COL['incert'], incert)
            cell.font = FONT_DATA; cell.number_format = '0.000'

        ws.cell(r, COL['auditoria'], auditoria or "").font = FONT_DATA

        ws.cell(r, COL['ap1x2'],  f_apuesta_1x2(r, ap1x2)).font = FONT_DATA
        ws.cell(r, COL['apou'],   f_apuesta_ou(r, apou)).font   = FONT_DATA
        ws.cell(r, COL['acierto'],f_acierto(r)).font             = FONT_DATA

        cell = ws.cell(r, COL['pl'], f_pl_neto(r))
        cell.font = FONT_DATA; cell.number_format = '#,##0.00'
        cell = ws.cell(r, COL['equity'], f_equity(r, BANKROLL))
        cell.font = FONT_DATA; cell.number_format = '#,##0.00'

        cell = ws.cell(r, COL['brier'], f_brier(r))
        cell.font = FONT_DATA; cell.number_format = '0.0000'
        cell = ws.cell(r, COL['brier_casa'], f_brier_casa(r))
        cell.font = FONT_DATA; cell.number_format = '0.0000'

        for c in range(1, MAX_COL + 1):
            ws.cell(r, c).border    = BORDER_THIN
            ws.cell(r, c).alignment = ALIGN_LEFT if c in ALIGN_LEFT_COLS else ALIGN_CENTER

        if pais:
            if pais not in stats_liga:
                stats_liga[pais] = {'apuestas':0,'ganadas':0,'perdidas':0,'vol':0.0,'pl':0.0}
            s = stats_liga[pais]
            # Usamos las mismas funciones que el dashboard para que los numeros coincidan.
            # Esto resuelve que partidos con goles pero aun con "[APOSTAR]" en el DB se cuenten.
            if stk1x2 and stk1x2 > 0 and ap1x2:
                res = determinar_resultado_entero(ap1x2, gl, gv)
                if res != 0:
                    s['apuestas'] += 1; s['vol'] += stk1x2
                    if res == 1:
                        s['ganadas'] += 1
                        cuota = _cuota_1x2(ap1x2, c1, cx, c2)
                        if cuota and cuota > 0: s['pl'] += stk1x2 * (cuota - 1)
                    else:
                        s['perdidas'] += 1; s['pl'] -= stk1x2
            if stkou and stkou > 0 and apou:
                res = determinar_resultado_entero(apou, gl, gv)
                if res != 0:
                    s['apuestas'] += 1; s['vol'] += stkou
                    if res == 1:
                        s['ganadas'] += 1
                        cuota = _cuota_ou(apou, co, cu)
                        if cuota and cuota > 0: s['pl'] += stkou * (cuota - 1)
                    else:
                        s['perdidas'] += 1; s['pl'] -= stkou

    max_row = len(datos) + 1

    # ==========================================================================
    # CONDITIONAL FORMATTING
    # ==========================================================================

    # 1. Filas por pais (A:R)
    rango_fila = f'A2:R{max_row}'
    for pais_cf, fill_cf in PAISES_CF:
        ws.conditional_formatting.add(rango_fila, FormulaRule(
            formula=[f'$K2="{pais_cf}"'], fill=fill_cf, stopIfTrue=False))

    # 2. Columna S — Apuesta 1X2
    rango_s = f'{CL["ap1x2"]}2:{CL["ap1x2"]}{max_row}'
    ws.conditional_formatting.add(rango_s, FormulaRule(formula=[f'ISNUMBER(SEARCH("[GANADA]",{CL["ap1x2"]}2))'],  fill=FILL_GANADA,     stopIfTrue=True))
    ws.conditional_formatting.add(rango_s, FormulaRule(formula=[f'ISNUMBER(SEARCH("[PERDIDA]",{CL["ap1x2"]}2))'], fill=FILL_PERDIDA,    stopIfTrue=True))
    ws.conditional_formatting.add(rango_s, FormulaRule(formula=[f'ISNUMBER(SEARCH("[PASAR]",{CL["ap1x2"]}2))'],   fill=FILL_PASAR,      stopIfTrue=True))
    ws.conditional_formatting.add(rango_s, FormulaRule(formula=[f'ISNUMBER(SEARCH("[APOSTAR]",{CL["ap1x2"]}2))'], fill=FILL_APOSTAR,    stopIfTrue=True))

    # 3. Columna T — Apuesta O/U
    rango_t = f'{CL["apou"]}2:{CL["apou"]}{max_row}'
    ws.conditional_formatting.add(rango_t, FormulaRule(formula=[f'ISNUMBER(SEARCH("[GANADA]",{CL["apou"]}2))'],  fill=FILL_GANADA,     stopIfTrue=True))
    ws.conditional_formatting.add(rango_t, FormulaRule(formula=[f'ISNUMBER(SEARCH("[PERDIDA]",{CL["apou"]}2))'], fill=FILL_PERDIDA,    stopIfTrue=True))
    ws.conditional_formatting.add(rango_t, FormulaRule(formula=[f'ISNUMBER(SEARCH("[PASAR]",{CL["apou"]}2))'],   fill=FILL_PASAR,      stopIfTrue=True))
    ws.conditional_formatting.add(rango_t, FormulaRule(formula=[f'ISNUMBER(SEARCH("[APOSTAR]",{CL["apou"]}2))'], fill=FILL_APOSTAR,    stopIfTrue=True))

    # 4. Columna X — P/L Neto (verde positivo, rojo negativo)
    rango_pl = f'{CL["pl"]}2:{CL["pl"]}{max_row}'
    ws.conditional_formatting.add(rango_pl, FormulaRule(formula=[f'{CL["pl"]}2>0'],  fill=FILL_GANADA,  stopIfTrue=True))
    ws.conditional_formatting.add(rango_pl, FormulaRule(formula=[f'{CL["pl"]}2<0'],  fill=FILL_PERDIDA, stopIfTrue=True))

    # 5. Columna W — Acierto
    rango_w = f'{CL["acierto"]}2:{CL["acierto"]}{max_row}'
    ws.conditional_formatting.add(rango_w, FormulaRule(formula=[f'ISNUMBER(SEARCH("[ACIERTO]",{CL["acierto"]}2))'],   fill=FILL_GANADA,     stopIfTrue=True))
    ws.conditional_formatting.add(rango_w, FormulaRule(formula=[f'ISNUMBER(SEARCH("[FALLO]",{CL["acierto"]}2))'],     fill=FILL_PERDIDA,    stopIfTrue=True))
    ws.conditional_formatting.add(rango_w, FormulaRule(formula=[f'ISNUMBER(SEARCH("[PREDICCION]",{CL["acierto"]}2))'],fill=FILL_PREDICCION, stopIfTrue=True))
    ws.conditional_formatting.add(rango_w, FormulaRule(formula=[f'ISNUMBER(SEARCH("[PASAR]",{CL["acierto"]}2))'],     fill=FILL_PASAR,      stopIfTrue=True))

    # ==========================================================================
    # DASHBOARD + RESUMEN
    # ==========================================================================
    metricas = calcular_metricas_dashboard(datos, FRACCION_KELLY)
    crear_hoja_dashboard(wb, metricas, BANKROLL)
    crear_hoja_sombra(wb, datos, BANKROLL)

    ws2 = wb.create_sheet("Resumen")
    res_headers = ['Liga','Apuestas','Ganadas','Perdidas','% Acierto','P/L Neto','Yield','Volumen']
    for i, h in enumerate(res_headers, 1):
        cell = ws2.cell(1, i, h)
        cell.font=FONT_HEADER; cell.fill=FILL_HEADER; cell.alignment=ALIGN_CENTER

    row_r = 2
    total_ap, total_g, total_p, total_vol, total_pl = 0, 0, 0, 0.0, 0.0
    for liga, s in sorted(stats_liga.items()):
        pct = (s['ganadas']/s['apuestas']*100) if s['apuestas'] > 0 else 0
        yld = (s['pl']/s['vol']*100)           if s['vol']      > 0 else 0
        ws2.cell(row_r,1,liga).font           = FONT_DATA
        ws2.cell(row_r,2,s['apuestas']).font  = FONT_DATA
        ws2.cell(row_r,3,s['ganadas']).font   = FONT_DATA
        ws2.cell(row_r,4,s['perdidas']).font  = FONT_DATA
        c=ws2.cell(row_r,5,pct/100);  c.font=FONT_DATA; c.number_format='0.0%'
        c=ws2.cell(row_r,6,round(s['pl'],2)); c.font=FONT_DATA; c.number_format='#,##0.00'
        c=ws2.cell(row_r,7,yld/100);  c.font=FONT_DATA; c.number_format='0.0%'
        c=ws2.cell(row_r,8,round(s['vol'],2));c.font=FONT_DATA; c.number_format='#,##0.00'
        total_ap+=s['apuestas']; total_g+=s['ganadas']
        total_p +=s['perdidas']; total_vol+=s['vol']; total_pl+=s['pl']
        row_r+=1

    FONT_BOLD = Font(name='Arial', bold=True, size=10)
    ws2.cell(row_r,1,"TOTAL").font = FONT_BOLD
    ws2.cell(row_r,2,total_ap).font= FONT_BOLD
    ws2.cell(row_r,3,total_g).font = FONT_BOLD
    ws2.cell(row_r,4,total_p).font = FONT_BOLD
    c=ws2.cell(row_r,5,(total_g/total_ap) if total_ap>0 else 0); c.font=FONT_BOLD; c.number_format='0.0%'
    c=ws2.cell(row_r,6,round(total_pl,2));  c.font=FONT_BOLD; c.number_format='#,##0.00'
    c=ws2.cell(row_r,7,(total_pl/total_vol) if total_vol>0 else 0); c.font=FONT_BOLD; c.number_format='0.0%'
    c=ws2.cell(row_r,8,round(total_vol,2)); c.font=FONT_BOLD; c.number_format='#,##0.00'

    for i, w in enumerate([14,10,10,10,10,14,10,14],1):
        ws2.column_dimensions[get_column_letter(i)].width = w

    # Conditional formatting en Resumen
    rng_yield = f'G2:G{row_r}'     # col 7 = Yield
    rng_pl    = f'F2:F{row_r}'     # col 6 = P/L Neto
    rng_acie  = f'E2:E{row_r}'     # col 5 = % Acierto
    ws2.conditional_formatting.add(rng_yield, FormulaRule(formula=['G2>0.05'],  fill=FILL_VERDE,    stopIfTrue=True))
    ws2.conditional_formatting.add(rng_yield, FormulaRule(formula=['G2>=0'],    fill=FILL_AMARILLO, stopIfTrue=True))
    ws2.conditional_formatting.add(rng_yield, FormulaRule(formula=['G2<0'],     fill=FILL_ROJO,     stopIfTrue=True))
    ws2.conditional_formatting.add(rng_pl,    FormulaRule(formula=['F2>0'],     fill=FILL_VERDE,    stopIfTrue=True))
    ws2.conditional_formatting.add(rng_pl,    FormulaRule(formula=['F2<0'],     fill=FILL_ROJO,     stopIfTrue=True))
    ws2.conditional_formatting.add(rng_acie,  FormulaRule(formula=['E2>=0.6'],  fill=FILL_VERDE,    stopIfTrue=True))
    ws2.conditional_formatting.add(rng_acie,  FormulaRule(formula=['E2>=0.5'],  fill=FILL_AMARILLO, stopIfTrue=True))
    ws2.conditional_formatting.add(rng_acie,  FormulaRule(formula=['E2<0.5'],   fill=FILL_ROJO,     stopIfTrue=True))

    ws2.freeze_panes = 'A2'
    ws2.cell(row_r+2,1,f"Generado: {datetime.now().strftime('%d/%m/%Y %H:%M')}").font=\
        Font(name='Arial',italic=True,size=9,color='888888')
    ws2.cell(row_r+3,1,f"Bankroll base: ${BANKROLL:,.2f}").font=\
        Font(name='Arial',italic=True,size=9,color='888888')

    wb.calculation.fullCalcOnLoad = True
    wb.save(EXCEL_FILE)
    print(f"[EXITO] Excel generado: {os.path.abspath(EXCEL_FILE)}")
    print(f"[INFO] {len(datos)} partidos escritos. {len(stats_liga)} ligas resumidas.")
    print("[SISTEMA] Motor Sincronizador V9.2 ha finalizado su ejecucion.")

if __name__ == "__main__":
    main()
