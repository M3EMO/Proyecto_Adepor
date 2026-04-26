"""Backfill shadow_xg_local/visita para Liquidados con equipos nuevos en equipos_altitud.

ALCANCE: solo partidos donde local (o visita, para mod_vis) ahora caen en
ALTITUD_NIVELES post-migracion adepor-om4 pero su shadow_xg_local en DB
fue calculado con el catalogo viejo (= xg_crudo, sin multiplicador).

LOGICA:
- shadow_xg_local actual en DB = xg_crudo (sin multiplicador) cuando local no
  estaba en catalogo viejo
- Nuevo shadow_xg_local = xg_crudo * mod_loc (donde mod_loc viene de ALTITUD_NIVELES)
- Verificacion: ratio shadow/xg_crudo debe coincidir con mod_loc post-update

Idempotente: solo actualiza si el ratio actual indica que NO se aplico mod.
"""
import sqlite3
import sys
import unicodedata
import re
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "fondo_quant.db"

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Identico a motor_calculadora.ALTITUD_NIVELES
ALTITUD_NIVELES = [
    (3601, 99999, 0.75, 1.35, "Zona de la Muerte"),
    (3001, 3600, 0.80, 1.25, "Extremo"),
    (2501, 3000, 0.85, 1.15, "Alto"),
    (1501, 2500, 0.90, 1.10, "Medio"),
]

GAMMA_DEFAULT = 0.59  # mismo default que motor_calculadora
EPS_RATIO = 0.02      # margen para clasificar shadow como "sin altitud"


def normalizar_extremo(texto):
    if not texto:
        return ""
    sin_tildes = ''.join(
        c for c in unicodedata.normalize('NFD', str(texto).lower().strip())
        if unicodedata.category(c) != 'Mn'
    )
    return re.sub(r'[^a-z0-9]', '', sin_tildes)


def get_mods(altitud):
    """Devuelve (mod_visita, mod_local) o (1.0, 1.0) si <=1500."""
    if altitud is None or altitud <= 1500:
        return 1.0, 1.0
    for alt_min, alt_max, mod_v, mod_l, _ in ALTITUD_NIVELES:
        if alt_min <= altitud <= alt_max:
            return mod_v, mod_l
    return 1.0, 1.0


def main():
    if not DB_PATH.exists():
        print(f"ERROR: DB not found at {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    # Cargar gamma_map de configuracion (si existe)
    try:
        gamma_rows = cur.execute(
            "SELECT clave, valor FROM configuracion WHERE clave LIKE 'gamma_display%'"
        ).fetchall()
        gamma_map = {}
        for clave, valor in gamma_rows:
            try:
                gamma_map[clave] = float(valor)
            except (ValueError, TypeError):
                pass
    except sqlite3.OperationalError:
        gamma_map = {}

    def gamma_for(pais):
        return gamma_map.get(f"gamma_display_{pais}",
                             gamma_map.get("gamma_display", GAMMA_DEFAULT))

    # Cargar catalogo altitud actualizado
    altitudes = dict(cur.execute(
        "SELECT equipo_norm, altitud FROM equipos_altitud"
    ).fetchall())
    print(f"[CATALOGO] {len(altitudes)} entries en equipos_altitud")

    # Liquidados andinos con shadow poblado
    cur.execute("""
        SELECT id_partido, pais, local, visita,
               xg_local, xg_visita, shadow_xg_local, shadow_xg_visita
        FROM partidos_backtest
        WHERE estado='Liquidado'
          AND pais IN ('Bolivia','Peru','Ecuador','Colombia')
          AND shadow_xg_local IS NOT NULL
          AND xg_local > 0 AND xg_visita > 0
    """)
    rows = cur.fetchall()
    print(f"[QUERY] {len(rows)} Liquidados andinos con shadow")
    print()

    actualizar = []
    sin_cambio = 0
    sin_altitud = 0

    for r in rows:
        (id_p, pais, local, visita, xg_l, xg_v, sh_l, sh_v) = r
        loc_norm = normalizar_extremo(local)
        alt_local = altitudes.get(loc_norm, 0)
        if alt_local <= 1500:
            sin_altitud += 1
            continue

        gamma = gamma_for(pais)
        xg_l_crudo = xg_l / gamma
        xg_v_crudo = xg_v / gamma

        mod_v, mod_l = get_mods(alt_local)

        # shadow esperado segun nuevo catalogo
        sh_l_nuevo = xg_l_crudo * mod_l
        sh_v_nuevo = xg_v_crudo * mod_v

        # Estado actual: ratio sh/xg_crudo
        ratio_l_actual = sh_l / xg_l_crudo if xg_l_crudo > 0 else 0
        ratio_v_actual = sh_v / xg_v_crudo if xg_v_crudo > 0 else 0

        # Si ya tiene mod aplicado (ratio cerca de mod_l), saltar (idempotente)
        ya_aplicado = (
            abs(ratio_l_actual - mod_l) < EPS_RATIO
            and abs(ratio_v_actual - mod_v) < EPS_RATIO
        )
        if ya_aplicado:
            sin_cambio += 1
            continue

        actualizar.append({
            "id_partido": id_p, "pais": pais, "local": local, "visita": visita,
            "alt_local": alt_local, "mod_l": mod_l, "mod_v": mod_v,
            "sh_l_old": sh_l, "sh_l_nuevo": sh_l_nuevo,
            "sh_v_old": sh_v, "sh_v_nuevo": sh_v_nuevo,
        })

    print(f"=== A ACTUALIZAR: {len(actualizar)} partidos ===")
    for u in actualizar:
        print(f"  [{u['pais']}] {u['local']:<28} (alt {u['alt_local']}m, mod_l={u['mod_l']:.2f})")
        print(f"     sh_l: {u['sh_l_old']:.3f} -> {u['sh_l_nuevo']:.3f}   "
              f"sh_v: {u['sh_v_old']:.3f} -> {u['sh_v_nuevo']:.3f}")

    print(f"\n=== SIN CAMBIO ===")
    print(f"  Ya tenian mod aplicado (idempotente): {sin_cambio}")
    print(f"  Local sin altitud > 1500: {sin_altitud}")

    if not actualizar:
        print("\n[INFO] Nada que actualizar. Saliendo sin tocar DB.")
        con.close()
        return

    # Confirmar y escribir
    if "--apply" not in sys.argv:
        print("\n[DRY RUN] Re-ejecutar con --apply para escribir cambios.")
        con.close()
        return

    n_writes = 0
    for u in actualizar:
        cur.execute("""
            UPDATE partidos_backtest
            SET shadow_xg_local = ?, shadow_xg_visita = ?
            WHERE id_partido = ?
        """, (u["sh_l_nuevo"], u["sh_v_nuevo"], u["id_partido"]))
        n_writes += cur.rowcount

    con.commit()
    print(f"\n[APPLIED] {n_writes} rows updated.")
    con.close()


if __name__ == "__main__":
    main()
