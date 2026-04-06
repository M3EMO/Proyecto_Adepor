import sqlite3, math, re

conn = sqlite3.connect('fondo_quant.db')
c = conn.cursor()
c.execute("""
    SELECT id_partido, local, visita, pais, fecha,
           prob_1, prob_x, prob_2,
           cuota_1, cuota_x, cuota_2,
           apuesta_1x2, stake_1x2,
           goles_l, goles_v
    FROM partidos_backtest
    WHERE estado = 'Liquidado'
      AND goles_l IS NOT NULL AND goles_v IS NOT NULL
    ORDER BY fecha
""")
rows = c.fetchall()
conn.close()

BANKROLL       = 100000.0
MAX_KELLY_PCT  = 0.025
FRACCION_KELLY = 0.50
FLOOR_MIN      = 0.33
EV_BASE        = 0.03
TECHO          = 5.0

def sf(v):
    try: return float(v) if v else 0.0
    except: return 0.0

def min_ev_esc(prob):
    if prob >= 0.50: return 0.03
    if prob >= 0.40: return 0.08
    if prob >= FLOOR_MIN: return 0.12
    return 999.0

def kelly_stake(prob, cuota):
    ev = prob * cuota - 1
    if ev <= 0 or cuota <= 1: return 0.0
    kelly = (prob * cuota - 1) / (cuota - 1)
    return round(BANKROLL * min(kelly * FRACCION_KELLY, MAX_KELLY_PCT), 2)

def gano_bet(pick, gl, gv):
    if 'LOCAL'  in pick: return gl > gv
    if 'VISITA' in pick: return gv > gl
    return None

bets_reales      = []
pasar_rv         = []
pasar_floor      = []
pasar_ev_esc     = []
pasar_margen     = []
pasar_sin_cuotas = []

for row in rows:
    (id_p, local, visita, pais, fecha,
     p1, px, p2, c1, cx, c2,
     apuesta, stake, gl, gv) = row
    p1,px,p2 = sf(p1),sf(px),sf(p2)
    c1,cx,c2 = sf(c1),sf(cx),sf(c2)
    gl,gv = int(gl),int(gv)
    stake = sf(stake)
    apuesta = str(apuesta)
    info = dict(local=local,visita=visita,pais=pais,fecha=fecha,
                p1=p1,px=px,p2=p2,c1=c1,cx=cx,c2=c2,gl=gl,gv=gv)
    if '[GANADA]' in apuesta or '[PERDIDA]' in apuesta:
        ganada = '[GANADA]' in apuesta
        pick = 'LOCAL' if 'LOCAL' in apuesta else 'VISITA'
        cuota = c1 if pick=='LOCAL' else c2
        bets_reales.append({**info,'pick':pick,'ganada':ganada,'stake':stake,'cuota':cuota})
    elif '[PASAR] Riesgo/Beneficio' in apuesta:
        pasar_rv.append(info)
    elif '[PASAR] Floor Prob' in apuesta:
        pasar_floor.append(info)
    elif '[PASAR] EV Insuf' in apuesta:
        m = re.search(r'EV Insuf \(([0-9.]+)<', apuesta)
        ev_val = float(m.group(1)) if m else 0.0
        pasar_ev_esc.append({**info,'ev_registrado':ev_val,'apuesta':apuesta})
    elif '[PASAR] Margen Predictivo' in apuesta:
        pasar_margen.append(info)
    elif '[PASAR] Sin Cuotas' in apuesta:
        pasar_sin_cuotas.append(info)

def implied_pick(info):
    p1,p2,c1,c2 = info['p1'],info['p2'],info['c1'],info['c2']
    if p1<=0 or p2<=0 or c1<=0 or c2<=0: return None,None,None
    if p1>=p2: return 'LOCAL',p1,c1
    else: return 'VISITA',p2,c2

n_act  = len(bets_reales)
g_act  = sum(1 for b in bets_reales if b['ganada'])
st_act = sum(b['stake'] for b in bets_reales)
pnl_act = sum(b['stake']*(b['cuota']-1) if b['ganada'] else -b['stake'] for b in bets_reales)

print('='*78)
print('ANALISIS DE FILTROS - BACKTEST LIQUIDADOS')
print('='*78)
print('\n[BASELINE] SISTEMA ACTUAL')
print(f'  Apuestas: {n_act}  |  Ganadoras: {g_act}  |  Hit: {g_act/n_act*100:.1f}%')
print(f'  Stake total: EUR {st_act:,.0f}  |  P&L: EUR {pnl_act:+,.0f}  |  Yield: {pnl_act/st_act*100:+.1f}%')

def analizar_grupo(grupo, etiqueta, descripcion):
    print(f'\n{etiqueta}  ({len(grupo)} casos)')
    print(f'  Descripcion: {descripcion}')
    det = []
    for info_raw in grupo:
        if 'ev_registrado' in info_raw:
            info = {k:v for k,v in info_raw.items() if k not in ('ev_registrado','apuesta')}
            ev_reg = info_raw.get('ev_registrado',0)
        else:
            info = info_raw
            ev_reg = None
        pick,prob,cuota = implied_pick(info)
        if pick is None: continue
        ev = prob*cuota-1
        umb_base = EV_BASE*(0.5/prob) if prob>0 else 999
        umb_esc  = min_ev_esc(prob)
        stk = kelly_stake(prob,cuota)
        g = gano_bet(pick,info['gl'],info['gv'])
        if g is None: continue
        det.append(dict(pick=pick,prob=round(prob,3),cuota=cuota,ev=round(ev,4),
                        umb_base=round(umb_base,4),umb_esc=round(umb_esc,3),
                        stake=stk,gano=g,info=info,ev_reg=ev_reg))
        icon = 'V' if g else 'X'
        ev_show = ev_reg if ev_reg is not None else ev
        print(f'  [{icon}] {info["fecha"][:10]} | {info["pais"]:10} | '
              f'{info["local"][:16]:16} vs {info["visita"][:14]:14} | '
              f'{pick:6} p={prob:.2f} c={cuota:.2f} EV={ev_show:+.3f} stk=EUR{stk:.0f}')
    # Separar casos con stake posible (EV>0 -> Kelly>0) de casos con EV<0 (no apostables)
    det_apostables = [d for d in det if d['stake'] > 0]
    det_neg_ev     = [d for d in det if d['stake'] <= 0]
    if det_neg_ev:
        print(f'  *** {len(det_neg_ev)} casos con EV<0: aunque se quite el filtro, Kelly=0 (no apostables)')
        print(f'      Esto ocurre cuando el mercado esta MAS seguro que el modelo: cuota muy baja vs prob modelo.')
    if det_apostables:
        nD=len(det_apostables); gD=sum(1 for d in det_apostables if d['gano'])
        sD=sum(d['stake'] for d in det_apostables)
        pD=sum(d['stake']*(d['cuota']-1) if d['gano'] else -d['stake'] for d in det_apostables)
        print(f'  -> Casos con EV>0 que si podrian abrirse: N={nD}  Hit={gD/nD*100:.0f}%  '
              f'Yield={pD/sD*100:+.1f}%  P&L=EUR{pD:+,.0f}')
    else:
        print(f'  -> Ninguno con EV positivo: eliminar este filtro no abrirîa ninguna apuesta adicional.')
    return det_apostables  # solo devolver los apostables para el resumen

det_rv    = analizar_grupo(pasar_rv,    '[A] Riesgo/Beneficio', 'EV positivo pero bajo el umbral minimo EV*0.5/p')
det_floor = analizar_grupo(pasar_floor, '[B] Floor Prob <33%',  'Modelo tiene pick pero prob entre 30-33%')
det_evesc = analizar_grupo(pasar_ev_esc,'[C] EV Insuf (escalado)','Paso EV basico pero no el umbral escalado por confianza')

print()
print('='*78)
print('TABLA RESUMEN: BASELINE vs CADA FILTRO ELIMINADO')
print('='*78)
print(f'  {"ESCENARIO":46s} | {"N":>4} | {"HIT%":>5} | {"YIELD%":>7} | {"P&L EUR":>9}')
print('  '+'-'*75)

def fila(label, extras):
    nE=len(extras); gE=sum(1 for d in extras if d['gano'])
    stE=sum(d['stake'] for d in extras)
    pE=sum(d['stake']*(d['cuota']-1) if d['gano'] else -d['stake'] for d in extras)
    nT=n_act+nE; gT=g_act+gE; stT=st_act+stE; pT=pnl_act+pE
    hit=gT/nT*100 if nT else 0
    yld=pT/stT*100 if stT else 0
    delta=pT-pnl_act
    d_str=f'({delta:+.0f})'
    print(f'  {label:46s} | {nT:>4} | {hit:>4.1f}% | {yld:>+6.1f}% | {pT:>+9.0f} {d_str}')

fila(f'ACTUAL  ({n_act} apuestas)',                       [])
print('  '+'-'*75)
fila(f'Sin Riesgo/Beneficio   (+{len(det_rv)} nuevas)',    det_rv)
fila(f'Sin Floor Prob         (+{len(det_floor)} nuevas)', det_floor)
fila(f'Sin EV Insuf escalado  (+{len(det_evesc)} nuevas)', det_evesc)
print('  '+'-'*75)
all_ex = det_rv+det_floor+det_evesc
fila(f'Sin TODOS los filtros  (+{len(all_ex)} nuevas)',    all_ex)
print()
print(f'  [INFO] {len(pasar_margen)} PASAR Margen Predictivo: modelo sin conviccion entre probs, no evaluable')
print(f'  [INFO] {len(pasar_sin_cuotas)} PASAR Sin Cuotas: sin datos de odds en ese momento, no evaluable')
print(f'  [INFO] Techo Cuota (>5.0): 0 casos en el backtest actual')
