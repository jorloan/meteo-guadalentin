"""Relleno de 7 días del historial de las estaciones Sencrop (una sola vez).

  python3 sencrop_rellenar.py descargar   # Playwright: baja 7 días horarios -> sencrop_historial_7d.json
  python3 sencrop_rellenar.py inyectar    # sin red: mete esas series en history_24h/2d/7d (idempotente)

Credenciales por entorno (SENCROP_USER / SENCROP_PASSWORD). El token que la web pone a
sus llamadas se usa solo en memoria: no se imprime ni se guarda. Los logs son públicos,
así que solo se imprimen recuentos y una comprobación de unidades.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

try:
    from zoneinfo import ZoneInfo
    ZONA = ZoneInfo('Europe/Madrid')
except Exception:                       # Python antiguo
    ZONA = None

import sencrop_historial as sh
from sencrop_a_wu import leer_sencrop

REPO = os.path.dirname(os.path.abspath(__file__))
F_SENCROP = os.path.join(REPO, 'sencrop.json')
F_SERIES = os.path.join(REPO, 'sencrop_historial_7d.json')
F_24H = os.path.join(REPO, 'history_24h.json')
F_2D = os.path.join(REPO, 'history_2d.json')
F_2D_PRECIP = os.path.join(REPO, 'history_2d_precip.json')
F_7D = os.path.join(REPO, 'history_7d.json')

URL_LOGIN = 'https://app.sencrop.com/login'
URL_DASHBOARD = 'https://app.sencrop.com/station/dashboard'
API = 'https://sencrop-api-production.infra.sencrop.com/app/station/measurement-page/measurements/hourly'
ORGANIZACION = '236298'
DIAS = 7
PROHIBIDAS = {'host', 'content-length', 'cookie', 'origin', 'referer', 'user-agent',
              'accept-encoding', 'connection', 'content-type', 'sec-fetch-site',
              'sec-fetch-mode', 'sec-fetch-dest', 'sec-ch-ua', 'sec-ch-ua-mobile',
              'sec-ch-ua-platform'}


def _iso(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%S.000+00:00')


def _leer(ruta, defecto):
    try:
        with open(ruta, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return defecto


def _guardar(ruta, datos):
    with open(ruta, 'w', encoding='utf-8') as f:
        json.dump(datos, f, ensure_ascii=False, separators=(',', ':'))


def descargar():
    from playwright.sync_api import sync_playwright
    usuario, clave = os.environ.get('SENCROP_USER', ''), os.environ.get('SENCROP_PASSWORD', '')
    if not usuario or not clave:
        print('Faltan SENCROP_USER / SENCROP_PASSWORD')
        return 1
    cab = {}
    ids = {}
    with sync_playwright() as p:
        nav = p.chromium.launch()
        ctx = nav.new_context(locale='es-ES')
        pag = ctx.new_page()

        def al_pedir(req):
            if ('sencrop-api-production' in req.url and 'measurement-page' in req.url
                    and req.method == 'GET'):
                try:
                    h = req.all_headers()
                except Exception:
                    h = dict(req.headers)
                for k, v in h.items():
                    if k.lower() not in PROHIBIDAS and not k.startswith(':'):
                        cab[k] = v

        def al_responder(resp):
            if 'station/dashboard/station-list' in resp.url and resp.status == 200:
                try:
                    for e in resp.json().get('stations') or []:
                        ids[e['id']] = e.get('name')
                except Exception:
                    pass

        pag.on('request', al_pedir)
        pag.on('response', al_responder)
        pag.goto(URL_LOGIN, wait_until='networkidle')
        pag.fill('input[type=email], input[name=email]', usuario)
        pag.fill('input[type=password]', clave)
        pag.click('button[type=submit]')
        pag.wait_for_url('**/home**', timeout=30000)
        pag.wait_for_load_state('networkidle')
        pag.goto(URL_DASHBOARD, wait_until='networkidle')
        pag.wait_for_timeout(3000)
        # Abrir el Historial de una estación: la web hace así su llamada con token
        pag.locator('text=Historial').first.click(timeout=8000)
        pag.wait_for_load_state('networkidle')
        pag.wait_for_timeout(6000)
        if 'authorization' not in {k.lower() for k in cab}:
            print('No se pudo obtener la cabecera de acceso del historial')
            nav.close()
            return 1

        # Todas las estaciones de sencrop.json (la lista del dashboard pagina de 8 en 8)
        objetivo = {e['id']: e.get('name') for e in (_leer(F_SENCROP, {}).get('estaciones') or [])
                    if e.get('id')}
        if not objetivo:
            objetivo = ids
        fin = datetime.now(timezone.utc)
        ini = fin - timedelta(days=DIAS)
        salida = {}
        for sid, nombre in objetivo.items():
            q = {'organisationId': ORGANIZACION, 'stationId': sid,
                 'startDatetime': _iso(ini), 'endDatetime': _iso(fin),
                 'measures': ','.join(sh.MEDIDAS), 'enableFilling': 'true'}
            r = ctx.request.get(f'{API}?{urlencode(q)}', headers=cab)
            if not r.ok:
                print(f'  {nombre}: HTTP {r.status}')
                continue
            series = sh.serie_horaria(r.json())
            salida[sid] = {k: {str(e): v for e, v in pts.items()} for k, pts in series.items()}
            print(f'  {nombre}: ' + ', '.join(f'{k}={len(v)}' for k, v in sorted(series.items())))
        nav.close()
    if not salida:
        print('Sin datos: no se guarda nada')
        return 1

    # Comprobación de unidades (datos meteorológicos públicos, sin credenciales):
    # última lectura horaria frente a la lectura actual de sencrop.json.
    actuales = {o['stationID']: o for o in leer_sencrop(F_SENCROP, (), ZONA)}
    for sid, series in list(salida.items())[:2]:
        o = actuales.get('SC-' + sid)
        if not o:
            continue
        m = o['metric']
        for clave, actual in (('temp', m['temp']), ('viento', m['windSpeed']),
                              ('racha', m['windGust']), ('hr', o['humidity'])):
            pts = series.get(clave)
            if pts:
                ult = pts[max(pts, key=int)]
                print(f'  unidades {clave}: última hora={ult} actual={actual}')
    _guardar(F_SERIES, {'actualizado': datetime.now(timezone.utc).isoformat(),
                        'estaciones': salida})
    print(f'Guardado {os.path.basename(F_SERIES)} con {len(salida)} estaciones')
    return 0


def inyectar():
    datos = _leer(F_SERIES, {}).get('estaciones') or {}
    if not datos:
        print('No hay sencrop_historial_7d.json: nada que inyectar')
        return 0
    series = {'SC-' + sid: {k: {int(e): v for e, v in pts.items()} for k, pts in s.items()}
              for sid, s in datos.items()}
    plantillas = {o['stationID']: o for o in leer_sencrop(F_SENCROP, (), ZONA)
                  if o['stationID'] in series}
    print(f'Estaciones con plantilla y serie: {len(plantillas)}')
    total = 0
    for ruta in (F_24H, F_2D, F_7D):
        h = _leer(ruta, None)
        if not isinstance(h, list):
            print(f'  {os.path.basename(ruta)}: no existe, se omite')
            continue
        n = sh.inyectar(h, plantillas, series, ZONA)
        if n:
            _guardar(ruta, h)
        print(f'  {os.path.basename(ruta)}: +{n} observaciones')
        total += n
        if ruta == F_2D and n:
            _guardar(F_2D_PRECIP, sh.proyectar_precip(h))
            print('  history_2d_precip.json regenerado')
    print(f'Total añadidas: {total}')
    return 0


if __name__ == '__main__':
    modo = sys.argv[1] if len(sys.argv) > 1 else ''
    if modo == 'descargar':
        sys.exit(descargar())
    if modo == 'inyectar':
        sys.exit(inyectar())
    print(__doc__)
    sys.exit(2)
