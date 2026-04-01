import sqlite3
import gspread
import unicodedata
import time

# ==========================================
# MOTOR SINCRONIZADOR V8.8 (INYECCION FORZADA DE METADATOS)
# ==========================================

DB_NAME = 'fondo_quant.db'
CREDENTIALS_FILE = 'credentials.json' 
SHEET_ID = "1UjUY1DZt3jK1N6uZGfVpsJk8QWexPvlKR33YzQUqmQk" 
SHEET_NAME = "Backtest"
BANKROLL_CELL = "AT2" # Celda que contiene el capital actual

def obtener_indice(header, nombres_posibles):
    for n in nombres_posibles:
        for i, h in enumerate(header):
            if n.lower() == str(h).lower().strip(): return i
    return -1

def obtener_letra(col_idx):
    if col_idx < 0: return "ZZ" 
    string = ""
    temp = col_idx + 1
    while temp > 0:
        temp, remainder = divmod(temp - 1, 26)
        string = chr(65 + remainder) + string
    return string

def main():
    print("[SISTEMA] Iniciando Motor Sincronizador V8.8 (Inyeccion Estetica Forzada)...")
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Crear tabla de configuración si no existe
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS configuracion (
            clave TEXT PRIMARY KEY,
            valor TEXT
        )
    """)
    conn.commit()

    try:
        gc = gspread.oauth(credentials_filename=CREDENTIALS_FILE)
        sheet = gc.open_by_key(SHEET_ID).worksheet(SHEET_NAME)

        # --- FASE 0: ACTUALIZACIÓN DE BANKROLL ---
        bankroll_str = sheet.acell(BANKROLL_CELL).value
        if bankroll_str:
            bankroll_val = float(str(bankroll_str).replace('$', '').replace('%', '').replace('.', '').replace(',', '.').strip())
            cursor.execute("INSERT OR REPLACE INTO configuracion (clave, valor) VALUES (?, ?)", ('bankroll', str(bankroll_val)))
            conn.commit()
            print(f"[INFO] Bankroll actualizado desde Google Sheets: ${bankroll_val:,.2f}")

        data_sheet = sheet.get_all_values()
        header = data_sheet[0] if data_sheet else []
    except Exception as e:
        print(f"[ERROR CRITICO] Fallo en conexion a Google Sheets: {e}")
        conn.close()
        return

    idx_id = obtener_indice(header, ["ID Partido", "ID"])
    if idx_id == -1: return

    partidos_excel_ids = {}
    max_fila_activa = 1

    for i, row in enumerate(data_sheet):
        if len(row) > idx_id:
            id_actual = row[idx_id].strip()
            if id_actual and id_actual.lower() not in ["id partido", "id"]:
                partidos_excel_ids[id_actual] = i + 1
                if (i + 1) > max_fila_activa: max_fila_activa = i + 1

    fila_insercion_libre = max_fila_activa + 1

    cursor.execute("SELECT id_partido FROM partidos_backtest WHERE estado = 'Liquidado'")
    ids_liquidados_db = {row[0] for row in cursor.fetchall()}
    ids_a_resucitar = [id_p for id_p in ids_liquidados_db if id_p not in partidos_excel_ids]

    if ids_a_resucitar:
        cursor.executemany("UPDATE partidos_backtest SET estado = 'Calculado' WHERE id_partido = ?", [(i,) for i in ids_a_resucitar])
        conn.commit()

    cursor.execute("""
        SELECT id_partido, fecha, local, visita, pais, 
               prob_1, prob_x, prob_2, prob_o25, prob_u25, 
               apuesta_1x2, apuesta_ou, stake_1x2, stake_ou, 
               cuota_1, cuota_x, cuota_2, cuota_o25, cuota_u25, estado,
               cuota_cierre_1x2, cuota_cierre_ou, goles_l, goles_v
        FROM partidos_backtest
        WHERE estado IN ('Calculado', 'Liquidado')
    """)
    datos_db = {row[0]: row for row in cursor.fetchall()}
    if not datos_db: return

    idx_fec = obtener_indice(header, ["Fecha"])
    idx_loc = obtener_indice(header, ["Local"])
    idx_vis = obtener_indice(header, ["Visita"])
    idx_liga = obtener_indice(header, ["Liga", "Pais"])
    idx_partido = obtener_indice(header, ["Partido", "Encuentro"])
    idx_p1 = obtener_indice(header, ["Prob 1"])
    idx_px = obtener_indice(header, ["Prob X"])
    idx_p2 = obtener_indice(header, ["Prob 2"])
    idx_po = obtener_indice(header, ["Prob +2.5", "Prob O2.5"])
    idx_pu = obtener_indice(header, ["Prob -2.5", "Prob U2.5"])
    idx_ap1x2 = obtener_indice(header, ["Apuesta 1X2"])
    idx_apou = obtener_indice(header, ["Apuesta O/U 2,5", "Apuesta O/U 2.5"])
    idx_stk1x2 = obtener_indice(header, ["Stake", "Stake 1X2"])
    idx_stkou = obtener_indice(header, ["Stake O/U 2,5", "Stake O/U 2.5"])
    idx_c1 = obtener_indice(header, ["Cuota 1"])
    idx_cx = obtener_indice(header, ["Cuota X"])
    idx_c2 = obtener_indice(header, ["Cuota 2"])
    idx_co = obtener_indice(header, ["Cuota +2.5"])
    idx_cu = obtener_indice(header, ["Cuota -2.5"])
    idx_acierto = obtener_indice(header, ["Acierto", "Aciertos"])
    idx_pl = obtener_indice(header, ["P/L Neto", "Profit", "P/L"])
    idx_clv = obtener_indice(header, ["CLV"]) 
    idx_gl = obtener_indice(header, ["Goles L", "Goles Local"])
    idx_gv = obtener_indice(header, ["Goles V", "Goles Visita"])

    l_id = obtener_letra(idx_id)
    l_p1 = obtener_letra(idx_p1)
    l_px = obtener_letra(idx_px)
    l_p2 = obtener_letra(idx_p2)
    l_gl = obtener_letra(idx_gl)
    l_gv = obtener_letra(idx_gv)
    l_c1 = obtener_letra(idx_c1)
    l_cx = obtener_letra(idx_cx)
    l_c2 = obtener_letra(idx_c2)
    l_ap1x2 = obtener_letra(idx_ap1x2)
    l_stk1x2 = obtener_letra(idx_stk1x2)
    l_po = obtener_letra(idx_po)
    l_pu = obtener_letra(idx_pu)
    l_co = obtener_letra(idx_co)
    l_cu = obtener_letra(idx_cu)
    l_apou = obtener_letra(idx_apou)
    l_stkou = obtener_letra(idx_stkou)

    l_acierto = obtener_letra(idx_acierto)

    max_col_allowed = len(header)
    celdas_a_actualizar = []

    def safe_cell(row_idx, col_idx, val):
        if 0 <= col_idx < max_col_allowed:
            celdas_a_actualizar.append(gspread.Cell(row_idx, col_idx + 1, val))

    print("[PROCESO] Mapeo finalizado. Preparando inyeccion y sobreescritura de metadatos...")
    
    def format_prob(v): return f"{round(v * 100, 2)}%".replace('.', ',') if v else ""
    def format_cuota(v): return str(v).replace('.', ',') if v and v > 0 else ""
    # Escribe el stake como un string con formato de coma decimal para ser compatible con la localización.
    def format_stake(v): return str(v).replace('.', ',') if v and v > 0 else "0"
    
    for db_id, row_db in datos_db.items():
        (id_p, fec, loc, vis, pais, p1, px, p2, po, pu, ap1x2, apou, stk1x2, stkou, c1, cx, c2, co, cu, estado, c_cierre_1x2, c_cierre_ou, gl, gv) = row_db
        
        if db_id in partidos_excel_ids:
            fila_excel = partidos_excel_ids[db_id]
        else:
            fila_excel = fila_insercion_libre
            partidos_excel_ids[db_id] = fila_excel
            fila_insercion_libre += 1

        # FIX ESTRUCTURAL: Se fuerza la inyección del texto estético aunque la fila ya exista.
        safe_cell(fila_excel, idx_id, db_id)
        if fec: safe_cell(fila_excel, idx_fec, fec.split(" ")[0])
        safe_cell(fila_excel, idx_partido, f"{loc} vs {vis}")
        safe_cell(fila_excel, idx_loc, loc)
        safe_cell(fila_excel, idx_vis, vis)
        if pais: safe_cell(fila_excel, idx_liga, pais)

        if p1: safe_cell(fila_excel, idx_p1, format_prob(p1))
        if px: safe_cell(fila_excel, idx_px, format_prob(px))
        if p2: safe_cell(fila_excel, idx_p2, format_prob(p2))
        if po: safe_cell(fila_excel, idx_po, format_prob(po))
        if pu: safe_cell(fila_excel, idx_pu, format_prob(pu))
        
        if c1: safe_cell(fila_excel, idx_c1, format_cuota(c1))
        if cx: safe_cell(fila_excel, idx_cx, format_cuota(cx))
        if c2: safe_cell(fila_excel, idx_c2, format_cuota(c2))
        if co: safe_cell(fila_excel, idx_co, format_cuota(co))
        if cu: safe_cell(fila_excel, idx_cu, format_cuota(cu))

        if ap1x2:
            if "[APOSTAR]" in ap1x2:
                ap1x2_formula = ap1x2.replace('"', '""')
                check_logic = ""
                if "LOCAL" in ap1x2: check_logic = f'IF({l_gl}{fila_excel}>{l_gv}{fila_excel}; "[GANADA] LOCAL"; "[PERDIDA] LOCAL")'
                elif "EMPATE" in ap1x2: check_logic = f'IF({l_gl}{fila_excel}={l_gv}{fila_excel}; "[GANADA] EMPATE"; "[PERDIDA] EMPATE")'
                elif "VISITA" in ap1x2: check_logic = f'IF({l_gl}{fila_excel}<{l_gv}{fila_excel}; "[GANADA] VISITA"; "[PERDIDA] VISITA")'
                
                if check_logic:
                    formula = f'=IF(OR({l_gl}{fila_excel}=""; {l_gv}{fila_excel}=""); "{ap1x2_formula}"; {check_logic})'
                    safe_cell(fila_excel, idx_ap1x2, formula)
                else:
                    safe_cell(fila_excel, idx_ap1x2, ap1x2)
            else:
                safe_cell(fila_excel, idx_ap1x2, ap1x2)

        if apou:
            if "[APOSTAR]" in apou:
                apou_formula = apou.replace('"', '""')
                check_logic = ""
                if "OVER" in apou: check_logic = f'IF(({l_gl}{fila_excel}+{l_gv}{fila_excel})>2,5; "[GANADA] OVER 2.5"; "[PERDIDA] OVER 2.5")'
                elif "UNDER" in apou: check_logic = f'IF(({l_gl}{fila_excel}+{l_gv}{fila_excel})<2,5; "[GANADA] UNDER 2.5"; "[PERDIDA] UNDER 2.5")'

                if check_logic:
                    formula = f'=IF(OR({l_gl}{fila_excel}=""; {l_gv}{fila_excel}=""); "{apou_formula}"; {check_logic})'
                    safe_cell(fila_excel, idx_apou, formula)
                else:
                    safe_cell(fila_excel, idx_apou, apou)
            else:
                safe_cell(fila_excel, idx_apou, apou)

        safe_cell(fila_excel, idx_stk1x2, format_stake(stk1x2))
        safe_cell(fila_excel, idx_stkou, format_stake(stkou))

        if estado == 'Liquidado':
            if gl is not None: safe_cell(fila_excel, idx_gl, gl)
            if gv is not None: safe_cell(fila_excel, idx_gv, gv)

        if idx_acierto != -1:
            # Nueva fórmula para la columna Acierto basada en probabilidades y resultado final.
            f_acierto = (
                f'=IF({l_p1}{fila_excel}=""; ""; '
                f'IF((MAX({l_p1}{fila_excel}:{l_p2}{fila_excel}) - MEDIAN({l_p1}{fila_excel}:{l_p2}{fila_excel})) > 0,05; '
                f'IF(OR({l_gl}{fila_excel}=""; {l_gv}{fila_excel}=""); "[PREDICCION] " & IF(MAX({l_p1}{fila_excel}:{l_p2}{fila_excel})={l_p1}{fila_excel}; "LOCAL"; IF(MAX({l_p1}{fila_excel}:{l_p2}{fila_excel})={l_px}{fila_excel}; "EMPATE"; "VISITA")); '
                f'IF(MAX({l_p1}{fila_excel}:{l_p2}{fila_excel})={l_p1}{fila_excel}; IF({l_gl}{fila_excel}>{l_gv}{fila_excel}; "[ACIERTO]"; "[FALLO]"); '
                f'IF(MAX({l_p1}{fila_excel}:{l_p2}{fila_excel})={l_px}{fila_excel}; IF({l_gl}{fila_excel}={l_gv}{fila_excel}; "[ACIERTO]"; "[FALLO]"); '
                f'IF({l_gl}{fila_excel}<{l_gv}{fila_excel}; "[ACIERTO]"; "[FALLO]")))); "[PASAR] Margen Insuficiente (<5%)"))'
            )
            safe_cell(fila_excel, idx_acierto, f_acierto)
        if idx_pl != -1:
            # Variables de celda mapeadas para la fila actual
            stk1 = f'{l_stk1x2}{fila_excel}'
            ap1  = f'{l_ap1x2}{fila_excel}'
            c1   = f'{l_c1}{fila_excel}'
            cx   = f'{l_cx}{fila_excel}'
            c2   = f'{l_c2}{fila_excel}'

            stko = f'{l_stkou}{fila_excel}'
            apo  = f'{l_apou}{fila_excel}'
            co   = f'{l_co}{fila_excel}'
            cu   = f'{l_cu}{fila_excel}'

            # Macro-función: Extrae matemáticamente los dígitos y descarta símbolos de moneda/espacios (" $833,33" -> "833,33")
            def num(celda):
                return f'VALUE(REGEXEXTRACT(TO_TEXT({celda}); "[0-9.,]+"))'

            # Fórmulas P/L Blindadas con Extracción por Expresión Regular
            f_pl_1x2 = (
                f'IFERROR(IF({num(stk1)} > 0; '
                f'IF(ISNUMBER(SEARCH("[GANADA]"; {ap1})); '
                f'{num(stk1)} * (IF(ISNUMBER(SEARCH("LOCAL"; {ap1})); {num(c1)}; IF(ISNUMBER(SEARCH("EMPATE"; {ap1})); {num(cx)}; {num(c2)})) - 1); '
                f'IF(ISNUMBER(SEARCH("[PERDIDA]"; {ap1})); -{num(stk1)}; 0)); 0); 0)'
            )
            f_pl_ou = (
                f'IFERROR(IF({num(stko)} > 0; '
                f'IF(ISNUMBER(SEARCH("[GANADA]"; {apo})); '
                f'{num(stko)} * (IF(ISNUMBER(SEARCH("OVER"; {apo})); {num(co)}; {num(cu)}) - 1); '
                f'IF(ISNUMBER(SEARCH("[PERDIDA]"; {apo})); -{num(stko)}; 0)); 0); 0)'
            )
            
            f_pl = f'=IF({l_id}{fila_excel}=""; ""; {f_pl_1x2} + {f_pl_ou})'
            safe_cell(fila_excel, idx_pl, f_pl)
       
        if ap1x2 and "[APOSTAR]" in ap1x2 and c_cierre_1x2 and c_cierre_1x2 > 0:
            cuota_comprada = c1 if "LOCAL" in ap1x2 else (cx if "EMPATE" in ap1x2 else c2)
            formula_clv = f'=({str(cuota_comprada).replace(".", ",")} / {str(c_cierre_1x2).replace(".", ",")}) - 1'
            safe_cell(fila_excel, idx_clv, formula_clv)

    if celdas_a_actualizar:
        max_row_needed = max(cell.row for cell in celdas_a_actualizar)
        if max_row_needed > sheet.row_count:
            sheet.add_rows(max_row_needed - sheet.row_count + 5)
            time.sleep(2) 

        print(f"[REQUERIMIENTO API] Inyectando {len(celdas_a_actualizar)} celdas seguras...")
        chunk_size = 500
        for i in range(0, len(celdas_a_actualizar), chunk_size):
            sheet.update_cells(celdas_a_actualizar[i:i+chunk_size], value_input_option='USER_ENTERED')
            time.sleep(1.5)
        print("[EXITO] Sincronizacion inyectada con exito.")
    else:
        print("[INFO] Matriz al dia.")

    try:
        if idx_id != -1 and fila_insercion_libre > 2:
            requests_sort = [{"sortRange": {"range": {"sheetId": sheet.id, "startRowIndex": 1, "endRowIndex": fila_insercion_libre - 1, "startColumnIndex": 0, "endColumnIndex": max_col_allowed}, "sortSpecs": [{"dimensionIndex": idx_id, "sortOrder": "ASCENDING"}]}}]
            sheet.spreadsheet.batch_update({"requests": requests_sort})
            print("[EXITO] Ordenamiento nativo completado.")
    except Exception as e:
        print(f"[ADVERTENCIA] Fallo el Auto-Sort: {e}")

    conn.close()

if __name__ == "__main__":
    main()