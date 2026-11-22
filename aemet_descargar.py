"""Descarga las observaciones de las últimas 24 h de AEMET (OpenData) a aemet.json.

Necesita la clave en la variable de entorno AEMET_API_KEY (secreto de GitHub Actions). Se queda
con las estaciones de la zona del mapa. Si algo falla (sin clave, clave caducada, sin red) se
conserva el aemet.json anterior y se sale con 0 (nunca rompe el ciclo). Solo biblioteca estándar.
"""
import json
import os
import ssl
import sys
import urllib.request
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
    ZONA = ZoneInfo('Europe/Madrid')
except Exception:
    ZONA = None

REPO = os.path.dirname(os.path.abspath(__file__))
F_AEMET = os.path.join(REPO, 'aemet.json')
BASE = 'https://opendata.aemet.es/opendata/api'
UA = 'Mozilla/5.0 (compatible; MeteoGuadalentin/1.0; +https://meteoguadalentin.com)'
BBOX = (36.5, 39.2, -3.3, -0.0)          # lat_min, lat_max, lon_min, lon_max (ventana del mapa)
CAMPOS = ('fint', 'ta', 'hr', 'vv', 'vmax', 'dv', 'pres', 'prec', 'tpr')


def _get(url, clave=None):
    cab = {'User-Agent': UA, 'Cache-Control': 'no-cache'}
    if clave:
        cab['api_key'] = clave
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(urllib.request.Request(url, headers=cab), timeout=60, context=ctx) as r:
        crudo = r.read()
    try:
        return json.loads(crudo.decode('utf-8'))
    except UnicodeDecodeError:
        return json.loads(crudo.decode('latin-1'))


def agrupar(registros):
    """Lista plana de AEMET -> {idema: {ubi, lat, lon, alt, filas}} solo de la zona."""
    la0, la1, lo0, lo1 = BBOX
    est = {}
    for r in registros:
        try:
            lat, lon = float(r['lat']), float(r['lon'])
        except Exception:
            continue
        if not (la0 <= lat <= la1 and lo0 <= lon <= lo1) or not r.get('idema'):
            continue
        e = est.setdefault(str(r['idema']), {'ubi': r.get('ubi'), 'lat': lat, 'lon': lon,
                                             'alt': r.get('alt'), 'filas': []})
        e['filas'].append({k: r.get(k) for k in CAMPOS})
    for e in est.values():
        e['filas'].sort(key=lambda f: str(f.get('fint')), reverse=True)
    return est


def principal():
    clave = os.environ.get('AEMET_API_KEY', '').strip()
    if not clave:
        print('  ⚠ AEMET: falta el secreto AEMET_API_KEY')
        return 0
    try:
        resp = _get(BASE + '/observacion/convencional/todas', clave)
        if not isinstance(resp, dict) or not resp.get('datos'):
            print(f"  ⚠ AEMET: {resp.get('estado') if isinstance(resp, dict) else '?'} "
                  f"{resp.get('descripcion') if isinstance(resp, dict) else resp}")
            return 0
        registros = _get(resp['datos'])
    except Exception as e:
        print(f'  ⚠ AEMET no disponible: {type(e).__name__}: {e}')
        return 0
    est = agrupar(registros if isinstance(registros, list) else [])
    if not est:
        print('  ⚠ AEMET: sin estaciones en la zona; se conserva el fichero anterior')
        return 0
    with open(F_AEMET, 'w', encoding='utf-8') as f:
        json.dump({'actualizado': datetime.now(ZONA).isoformat(), 'estaciones': est},
                  f, ensure_ascii=False, separators=(',', ':'))
    print(f'  ✅ AEMET: {len(est)} estaciones en la zona ({len(registros)} registros)')
    return 0


if __name__ == '__main__':
    sys.exit(principal())
