"""Descarga el informe de las últimas 24 h de las estaciones del SIAM (IMIDA) a imida.json.

Datos públicos de siam.imida.es (sin login; la página APEX acepta la sesión 0). Solo biblioteca
estándar. Si algo falla, se conserva el imida.json anterior y se sale con 0 (nunca rompe el ciclo).
Las estaciones que no envían datos en tiempo real devuelven un informe vacío y se omiten.
"""
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import urllib.request

try:
    from zoneinfo import ZoneInfo
    ZONA = ZoneInfo('Europe/Madrid')
except Exception:
    ZONA = None

REPO = os.path.dirname(os.path.abspath(__file__))
F_IMIDA = os.path.join(REPO, 'imida.json')
F_COORDS = os.path.join(REPO, 'imida_coordenadas.json')
URL = 'http://siam.imida.es/apex/f?p=101:116000:0::::P116000_ID:'
UA = 'Mozilla/5.0 (compatible; MeteoGuadalentin/1.0; +https://meteoguadalentin.com)'
CAMPOS = ('fecha', 'tmed', 'tmax', 'tmin', 'hrmed', 'hrmax', 'hrmin', 'radmed', 'radmax',
          'radacu', 'vvmed', 'vvmax', 'dvmed', 'prec', 'dewpt', 'dpv')


def parsear(html):
    """HTML del informe de 24 h -> lista de dicts (más reciente primero)."""
    filas = []
    for tr in re.findall(r'<tr onmouseover[\s\S]*?</tr>', html):
        celdas = [c.strip() for c in re.findall(r'<td[^>]*>([^<]*)</td>', tr)]
        if len(celdas) >= len(CAMPOS):
            filas.append(dict(zip(CAMPOS, celdas)))
    return filas


def _bajar(codigo):
    try:
        req = urllib.request.Request(URL + codigo, headers={'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            return codigo, parsear(r.read().decode('utf-8', 'replace'))
    except Exception as e:
        print(f'  ⚠ IMIDA {codigo}: {type(e).__name__}: {e}')
        return codigo, None


def principal():
    try:
        with open(F_COORDS, 'r', encoding='utf-8') as f:
            codigos = list(json.load(f)['estaciones'])
    except Exception as e:
        print(f'  ⚠ IMIDA: sin coordenadas ({e})')
        return 0
    with ThreadPoolExecutor(max_workers=6) as ex:
        res = list(ex.map(_bajar, codigos))
    est = {c: f for c, f in res if f}
    if not est:
        print('  ⚠ IMIDA no disponible: se conserva el fichero anterior')
        return 0
    with open(F_IMIDA, 'w', encoding='utf-8') as f:
        json.dump({'actualizado': datetime.now(ZONA).isoformat(), 'estaciones': est},
                  f, ensure_ascii=False, separators=(',', ':'))
    print(f'  ✅ IMIDA: {len(est)} estaciones con datos de {len(codigos)}')
    return 0


if __name__ == '__main__':
    sys.exit(principal())
