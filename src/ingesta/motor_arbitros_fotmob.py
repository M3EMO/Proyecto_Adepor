"""
Captura previa al partido del arbitro designado en FotMob (E14, bead adepor-jjx).

La base data/fotmob/raw se baja despues del partido y no dice cuando se publico el arbitro. E14 toma como
referencia la primera captura de bet365 AR posterior a la publicacion del arbitro. Este motor guarda,
por cada partido no empezado de la Liga Profesional en los proximos DIAS dias, una linea JSON con la hora
de captura y el arbitro (null si FotMob todavia no lo publico). Cada corrida agrega lineas: asi se ve
cuando aparece el arbitro y si cambia. Despues baja a data/fotmob/raw los partidos terminados de la temporada
en curso que faltan: E14 los necesita para el resultado y para las variables de M1. No escribe en la base.

Uso:  python -m src.ingesta.motor_arbitros_fotmob
"""
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from src.comun.config_sistema import PROJECT_ROOT
from src.ingesta.motor_cuotas_fotmob import PAUSA, pedir

SALIDA = Path(PROJECT_ROOT) / 'data' / 'fotmob' / 'prepartido' / 'arbitros.jsonl'
RAW = Path(PROJECT_ROOT) / 'data' / 'fotmob' / 'raw'
LIGAS = (112,)  # Liga Profesional (primaryId de FotMob)
DIAS = 8  # OddsPapi captura un partido hasta 10 dias antes; FotMob publica el arbitro 1 o 2 dias antes
TZ = 'America/Argentina/Buenos_Aires'


def capturar(ts, dias, pedir_fn=pedir, pausa=PAUSA):
    """Lineas {ts_captura, match_id, liga, inicio_utc, local, visita, arbitro, arbitro_id} de los partidos
    no empezados de LIGAS. dias: fechas YYYYMMDD. Un pedido caido no frena el lote."""
    out = []
    for dia in dias:
        try:
            ligas = pedir_fn(f'matches?date={dia}&timezone={TZ}&ccode3=ARG')['leagues']
        except Exception as e:
            print(f'[ALERTA] FotMob matches {dia}: {type(e).__name__}')
            continue
        time.sleep(pausa)
        for lg in ligas:
            if lg.get('primaryId') not in LIGAS:
                continue
            for m in lg['matches']:
                st = m.get('status') or {}
                if st.get('started') or st.get('finished') or st.get('cancelled'):
                    continue
                try:
                    d = pedir_fn(f'matchDetails?matchId={m["id"]}')
                except Exception as e:
                    print(f'[ALERTA] FotMob matchDetails {m["id"]}: {type(e).__name__}')
                    continue
                finally:
                    time.sleep(pausa)
                if str((d.get('general') or {}).get('matchId')) != str(m['id']):
                    continue  # FotMob devolvio otro partido
                ref = (((d.get('content') or {}).get('matchFacts') or {}).get('infoBox') or {}).get('Referee') or {}
                out.append({'ts_captura': ts, 'match_id': m['id'], 'liga': lg['primaryId'], 'inicio_utc': st.get('utcTime'),
                            'local': m['home']['name'], 'visita': m['away']['name'],
                            'arbitro': ref.get('text'), 'arbitro_id': ref.get('id')})
    return out


def bajar_terminados(raw=RAW, pedir_fn=pedir, pausa=PAUSA):
    """Guarda en raw el matchDetails de cada partido terminado de LIGAS (temporada en curso) que falte.
    Devuelve los ids guardados. Un pedido caido no frena el lote; el partido se reintenta en la proxima corrida."""
    out = []
    for liga in LIGAS:
        try:
            fixtures = pedir_fn(f'fixtures?id={liga}')  # sin season: la temporada en curso
        except Exception as e:
            print(f'[ALERTA] FotMob fixtures {liga}: {type(e).__name__}')
            continue
        time.sleep(pausa)
        for x in fixtures:
            ruta = raw / f'{x["id"]}.json'
            if not (x.get('status') or {}).get('finished') or ruta.exists():
                continue
            try:
                d = pedir_fn(f'matchDetails?matchId={x["id"]}')
            except Exception as e:
                print(f'[ALERTA] FotMob matchDetails {x["id"]}: {type(e).__name__}')
                continue
            finally:
                time.sleep(pausa)
            g = d.get('general') or {}
            if str(g.get('matchId')) != str(x['id']) or not g.get('finished'):
                continue  # otro partido o todavia sin cerrar: un archivo a medias no se volveria a bajar
            tmp = ruta.with_suffix('.tmp')  # un json cortado romperia cargar() de E13
            tmp.write_text(json.dumps(d, ensure_ascii=False), encoding='utf-8')
            tmp.replace(ruta)
            out.append(x['id'])
    return out


def main():
    ahora = datetime.now(timezone.utc)
    hoy = ahora.astimezone(ZoneInfo(TZ)).date()
    filas = capturar(ahora.strftime('%Y-%m-%dT%H:%M:%SZ'), [(hoy + timedelta(days=k)).strftime('%Y%m%d') for k in range(DIAS)])
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    with SALIDA.open('a', encoding='utf-8') as f:
        f.writelines(json.dumps(x, ensure_ascii=False) + '\n' for x in filas)
    print(f'[EXITO] arbitros FotMob: {len(filas)} partidos, {sum(bool(x["arbitro"]) for x in filas)} con arbitro')
    RAW.mkdir(parents=True, exist_ok=True)
    print(f'[EXITO] partidos terminados FotMob: {len(bajar_terminados())} bajados a {RAW.name}/')


if __name__ == '__main__':
    main()
