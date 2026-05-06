"""
Desglose yield x liga x año para los top findings post walk-forward TRUE-OOS.

Para cada finding:
- Aplica el filtro (lo, hi) sobre todo el universo
- Tabla: filas=liga, cols=temp (2022-2026), celda = yield (N)
"""
from __future__ import annotations
import sqlite3
import json
import numpy as np
from pathlib import Path

DB = "fondo_quant.db"
ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    universo = [dict(r) for r in cur.execute("SELECT * FROM universo_filtros_ema_v3")]

    findings_data = json.load(open(ROOT / "analisis" / "filtros_ema_v3_exploration.json", encoding="utf-8"))
    top_findings = findings_data.get("wf_pass", [])[:8]

    LIGAS = ["Argentina", "Italia", "Brasil", "Espana", "Francia", "Inglaterra", "Turquia", "Alemania"]
    TEMPS = [2022, 2023, 2024, 2025, 2026]

    desglose_global = {}
    for f in top_findings:
        feature = f["feature"]
        target = f["target"]
        pick = f["pick"]
        lo, hi = f["lo"], f["hi"]
        finding_id = f"{feature}_{pick}"

        matriz = {}
        for liga in LIGAS:
            row = {}
            for temp in TEMPS:
                sub = [e for e in universo
                       if e["liga"] == liga and e["temp"] == temp
                       and e.get(feature) is not None
                       and e.get(target) is not None
                       and lo <= e[feature] <= hi]
                if not sub:
                    row[temp] = {"n": 0, "yield": None}
                    continue
                ys = [e[target] for e in sub]
                row[temp] = {"n": len(ys), "yield": sum(ys) / len(ys)}
            matriz[liga] = row

        # Total per liga (todos años)
        total_per_liga = {}
        for liga in LIGAS:
            sub = [e for e in universo
                   if e["liga"] == liga
                   and e.get(feature) is not None
                   and e.get(target) is not None
                   and lo <= e[feature] <= hi]
            if not sub:
                total_per_liga[liga] = {"n": 0, "yield": None}
                continue
            ys = [e[target] for e in sub]
            total_per_liga[liga] = {"n": len(ys), "yield": sum(ys) / len(ys)}

        # Total per año (todas ligas)
        total_per_temp = {}
        for temp in TEMPS:
            sub = [e for e in universo
                   if e["temp"] == temp
                   and e.get(feature) is not None
                   and e.get(target) is not None
                   and lo <= e[feature] <= hi]
            if not sub:
                total_per_temp[temp] = {"n": 0, "yield": None}
                continue
            ys = [e[target] for e in sub]
            total_per_temp[temp] = {"n": len(ys), "yield": sum(ys) / len(ys)}

        desglose_global[finding_id] = {
            "feature": feature,
            "target": target,
            "pick": pick,
            "lo": lo, "hi": hi,
            "n_pool": f["n"], "yield_pool": f["yield_mean"],
            "matriz_liga_x_temp": matriz,
            "total_per_liga": total_per_liga,
            "total_per_temp": total_per_temp,
        }

        print(f"\n=== {finding_id} (lo={lo:.4f}, hi={hi:.4f}) ===")
        print(f"Pool yield: {f['yield_mean']:+.3%} N={f['n']}")
        print()

        # Tabla liga x temp
        header = f"{'liga':<13}"
        for t in TEMPS:
            header += f"  {t:>4}"
        header += f"  {'Total':>7}"
        print(header)
        for liga in LIGAS:
            line = f"{liga:<13}"
            for t in TEMPS:
                cell = matriz[liga][t]
                if cell["n"] == 0:
                    line += f"  {'.':>4}"
                else:
                    line += f"  {cell['yield']:+.0%}({cell['n']:>2})"
            tot = total_per_liga[liga]
            if tot["n"] == 0:
                line += f"  {'.':>7}"
            else:
                line += f"  {tot['yield']:+.0%}({tot['n']:>3})"
            print(line)

        line = f"{'Total':<13}"
        for t in TEMPS:
            cell = total_per_temp[t]
            if cell["n"] == 0:
                line += f"  {'.':>4}"
            else:
                line += f"  {cell['yield']:+.0%}({cell['n']:>2})"
        print(line)

    out = ROOT / "analisis" / "filtros_ema_v3_desglose_liga_anio.json"
    out.write_text(json.dumps(desglose_global, indent=2, default=float, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
