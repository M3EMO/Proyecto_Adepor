"""
[adepor v14 v3] Análisis granular bin8 + bin12 sobre cuotas_historicas_fdco
con calibración yield contrafactual.
"""
from __future__ import annotations
import json
import math
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "fondo_quant.db"


def calcular_bin(fecha_str, ini, fin, n):
    try:
        f = datetime.strptime(fecha_str[:10], "%Y-%m-%d")
        i = datetime.strptime(ini[:10], "%Y-%m-%d")
        e = datetime.strptime(fin[:10], "%Y-%m-%d")
        if f < i: return 1
        if f > e: return n
        delta = (e - i).days
        if delta <= 0: return 1
        return max(1, min(n, int((f - i).days / delta * n) + 1))
    except: return None


def main():
    conn = sqlite3.connect(DB); conn.text_factory = str
    cur = conn.cursor()

    cal = {}
    for r in cur.execute("SELECT liga, temp, fecha_inicio, fecha_fin FROM liga_calendario_temp"):
        cal[(r[0], r[1])] = (r[2], r[3])

    print("=" * 100)
    print("BIN8 + BIN12 GRANULAR (LIGAS, OOS 2022-2025 vs IS 2026)")
    print("=" * 100)

    for n_bins in [8, 12]:
        print()
        print(f"--- bin{n_bins} (granularidad {100/n_bins:.1f}% temporada) ---")
        print(f"{'liga':<13} {'bin':>4} {'N_OOS':>6} {'g_OOS':>7} {'N_IS':>5} {'g_IS':>7} {'bias':>7}")

        bias_data = {}
        for liga in ["Inglaterra","Italia","Espana","Francia","Alemania","Turquia","Holanda","Argentina","Brasil"]:
            buckets = {b: {"oos": [], "is": []} for b in range(1, n_bins+1)}
            for temp in [2022, 2023, 2024, 2025, 2026]:
                cal_key = (liga, temp)
                if cal_key not in cal: continue
                ini, fin = cal[cal_key]
                rows = cur.execute("""
                    SELECT fecha, goles_l, goles_v
                    FROM cuotas_historicas_fdco
                    WHERE liga=? AND temp=? AND goles_l IS NOT NULL
                """, (liga, temp)).fetchall()
                for r in rows:
                    b = calcular_bin(r[0], ini, fin, n_bins)
                    if not b: continue
                    g_t = r[1] + r[2]
                    if temp <= 2025:
                        buckets[b]["oos"].append(g_t)
                    elif temp == 2026:
                        buckets[b]["is"].append(g_t)
            bias_data[liga] = {}
            for b in range(1, n_bins+1):
                noos = len(buckets[b]["oos"]); nis = len(buckets[b]["is"])
                if noos < 30 or nis < 15: continue
                g_oos = sum(buckets[b]["oos"]) / noos
                g_is = sum(buckets[b]["is"]) / nis
                bias = g_is/g_oos if g_oos>0 else 1.0
                marker = "+" if bias>=1.10 else ("-" if bias<=0.90 else "")
                print(f"  {liga:<11} {b:>4} {noos:>6d} {g_oos:>7.3f} {nis:>5d} {g_is:>7.3f} {bias:>+7.4f} {marker}")
                bias_data[liga][b] = {"g_oos": round(g_oos,3), "g_is": round(g_is,3),
                                      "bias": round(bias,4), "n_oos": noos, "n_is": nis}

        # Persistir
        payload = {
            "name": f"v14_v3_bias_bin{n_bins}_ligas",
            "created": "2026-04-29",
            "method": f"bin{n_bins} = posición fracción dentro temporada (1..{n_bins})",
            "bins": bias_data,
        }
        cur.execute("""INSERT OR REPLACE INTO config_motor_valores
                        (clave, scope, valor_real, valor_texto, tipo, fuente, bloqueado, fecha_actualizacion)
                        VALUES (?, ?, NULL, ?, ?, ?, 0, datetime('now'))""",
                    (f"v14_v3_bias_bin{n_bins}_ligas", "global", json.dumps(payload), "json", "analisis_2026-04-29"))
    conn.commit()

    # Identificar BINS con shift fuerte (|bias-1| >= 0.15)
    print()
    print("=" * 100)
    print("BINS CON SHIFT FUERTE IS 2026 (|bias-1| >= 15%)")
    print("=" * 100)
    for n_bins in [4, 8, 12]:
        r = cur.execute(f"SELECT valor_texto FROM config_motor_valores WHERE clave='v14_v3_bias_bin{n_bins}_ligas'").fetchone()
        if not r: continue
        data = json.loads(r[0])
        print(f"\n--- bin{n_bins} ---")
        shifts = []
        for liga, bins in data.get("bins", {}).items():
            for b, info in bins.items():
                if abs(info["bias"] - 1.0) >= 0.15:
                    shifts.append((abs(info["bias"]-1.0), liga, int(b), info["bias"], info["n_is"]))
        shifts.sort(reverse=True)
        for diff, liga, b, bias, n in shifts[:15]:
            direction = "ALCISTA" if bias>1 else "BAJISTA"
            print(f"  {liga:<13} bin{b:<3} bias={bias:.3f} ({direction}) N_IS={n}")

    conn.close()


if __name__ == "__main__":
    main()
