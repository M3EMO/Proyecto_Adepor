"""
Generadores de formulas Excel para las celdas computadas del Backtest.

Cada funcion retorna un string que Excel evalua como formula al abrir el
archivo. Las formulas dependen de la fila `r` y del schema CL de columnas
definido en excel_estilos.

Extraido del motor_sincronizador.py monolitico (V9.2) en fase 4 (2026-04-21).
"""
from src.persistencia.excel_estilos import CL


def f_apuesta_1x2(r, ap_text):
    """Devuelve formula que recalcula GANADA/PERDIDA del pick 1X2 segun goles."""
    ap = str(ap_text or "")
    if "[APOSTAR]" not in ap:
        return ap
    g = f'{CL["gl"]}{r}'
    v = f'{CL["gv"]}{r}'
    vacio = f'OR({g}="",{v}="")'
    if "LOCAL"  in ap: return f'=IF({vacio},"[APOSTAR] LOCAL",IF({g}>{v},"[GANADA] LOCAL","[PERDIDA] LOCAL"))'
    if "EMPATE" in ap: return f'=IF({vacio},"[APOSTAR] EMPATE",IF({g}={v},"[GANADA] EMPATE","[PERDIDA] EMPATE"))'
    if "VISITA" in ap: return f'=IF({vacio},"[APOSTAR] VISITA",IF({g}<{v},"[GANADA] VISITA","[PERDIDA] VISITA"))'
    return ap


def f_apuesta_ou(r, ap_text):
    """Formula GANADA/PERDIDA del pick O/U 2.5 segun total de goles."""
    ap = str(ap_text or "")
    if "[APOSTAR]" not in ap:
        return ap
    g = f'{CL["gl"]}{r}'
    v = f'{CL["gv"]}{r}'
    vacio = f'OR({g}="",{v}="")'
    total = f'({g}+{v})'
    if "OVER"  in ap: return f'=IF({vacio},"[APOSTAR] OVER 2.5",IF({total}>2.5,"[GANADA] OVER 2.5","[PERDIDA] OVER 2.5"))'
    if "UNDER" in ap: return f'=IF({vacio},"[APOSTAR] UNDER 2.5",IF({total}<2.5,"[GANADA] UNDER 2.5","[PERDIDA] UNDER 2.5"))'
    return ap


def f_acierto(r):
    """Formula del 'acierto sistema': compara prob max vs resultado real.
    Si el margen entre max y mediana es < 5pp marca [PASAR] Margen Insuf."""
    p1, px, p2 = f'{CL["p1"]}{r}', f'{CL["px"]}{r}', f'{CL["p2"]}{r}'
    gl, gv = f'{CL["gl"]}{r}', f'{CL["gv"]}{r}'
    mx   = f'MAX({p1},{px},{p2})'
    md   = f'MEDIAN({p1},{px},{p2})'
    pred = f'IF({p1}={mx},"LOCAL",IF({px}={mx},"EMPATE","VISITA"))'
    res  = (f'IF({p1}={mx},IF({gl}>{gv},"[ACIERTO]","[FALLO]"),'
            f'IF({px}={mx},IF({gl}={gv},"[ACIERTO]","[FALLO]"),'
            f'IF({gl}<{gv},"[ACIERTO]","[FALLO]")))')
    return (f'=IF({p1}="","",IF(({mx}-{md})>0.05,'
            f'IF(OR({gl}="",{gv}=""),"[PREDICCION] "&{pred},{res}),'
            f'"[PASAR] Margen Insuf"))')


def f_pl_neto(r):
    """Formula P/L neto: stake * (cuota-1) si gana, -stake si pierde, 0 si no jugo."""
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


def f_equity(r, bankroll, aporte=0.0):
    """Equity curve acumulada.
    r=2 arranca en bankroll (BASE — sin P/L acumulado, sin aportes).
    r>=3 suma al anterior.
    Si la fila tiene un aporte (inyeccion/retiro de capital con fecha <= fecha_partido
    y > fecha_partido_anterior), se suma antes que el P/L.
    """
    pl = f'{CL["pl"]}{r}'
    aporte_term = f'+{aporte}' if aporte else ''
    if r == 2:
        return f'={bankroll}{aporte_term}+{pl}'
    return f'={CL["equity"]}{r-1}{aporte_term}+{pl}'


def f_brier(r):
    """Brier Score SISTEMA: probs Dixon-Coles vs resultado real. Rango 0-2."""
    p1, px, p2 = f'{CL["p1"]}{r}', f'{CL["px"]}{r}', f'{CL["p2"]}{r}'
    gl, gv = f'{CL["gl"]}{r}', f'{CL["gv"]}{r}'
    return (f'=IF(OR({gl}="",{gv}=""),"",'
            f'({p1}-IF({gl}>{gv},1,0))^2+'
            f'({px}-IF({gl}={gv},1,0))^2+'
            f'({p2}-IF({gl}<{gv},1,0))^2)')


def f_brier_casa(r):
    """Brier Score CASA: probs implicitas del mercado (cuotas normalizadas). Rango 0-2."""
    c1, cx, c2 = f'{CL["c1"]}{r}', f'{CL["cx"]}{r}', f'{CL["c2"]}{r}'
    gl, gv = f'{CL["gl"]}{r}', f'{CL["gv"]}{r}'
    chk = f'OR({gl}="",{gv}="",{c1}="",{c1}=0,{cx}="",{cx}=0,{c2}="",{c2}=0)'
    den = f'(1/{c1}+1/{cx}+1/{c2})'
    p1n = f'(1/{c1}/{den})'
    pxn = f'(1/{cx}/{den})'
    p2n = f'(1/{c2}/{den})'
    o1 = f'IF({gl}>{gv},1,0)'
    ox = f'IF({gl}={gv},1,0)'
    o2 = f'IF({gl}<{gv},1,0)'
    return f'=IF({chk},"",({p1n}-{o1})^2+({pxn}-{ox})^2+({p2n}-{o2})^2)'


# --- Helpers Python (no formulas) para metricas/sombra ---
def cuota_1x2(ap_text, c1, cx, c2):
    """Devuelve la cuota asociada al pick 1X2. None si no aplica."""
    ap = str(ap_text or "")
    if "LOCAL"  in ap: return c1
    if "EMPATE" in ap: return cx
    if "VISITA" in ap: return c2
    return None


def cuota_ou(ap_text, co, cu):
    """Devuelve la cuota asociada al pick O/U 2.5. None si no aplica."""
    ap = str(ap_text or "")
    if "OVER"  in ap: return co
    if "UNDER" in ap: return cu
    return None
