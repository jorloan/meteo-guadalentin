"""Descarga el estado actual de las estaciones del SAIH Segura (CHS) a chs.json.

Datos públicos del visor iVisor (saihweb.chsegura.es): temperatura y humedad de las
estaciones «EM.» y lluvia de los pluviómetros en ventanas de 1-24 h. Solo biblioteca
estándar. Si algo falla, se conserva el chs.json anterior y se sale con 0 (nunca rompe el ciclo).
"""
import http.cookiejar
import json
import os
import ssl
import sys
import urllib.parse
import urllib.request
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
    ZONA = ZoneInfo('Europe/Madrid')
except Exception:
    ZONA = None

from chs_a_wu import VENTANAS, acumular_lluvia, num

REPO = os.path.dirname(os.path.abspath(__file__))
F_CHS = os.path.join(REPO, 'chs.json')
F_ESTADO = os.path.join(REPO, 'chs_estado.json')
BASE = 'https://saihweb.chsegura.es/apps/iVisor/'
UA = 'Mozilla/5.0 (compatible; MeteoGuadalentin/1.0; +https://meteoguadalentin.com)'


def _abridor():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE       # igual que el resto de scripts del repo
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar),
                                       urllib.request.HTTPSHandler(context=ctx))


def _post(op, datos):
    req = urllib.request.Request(
        BASE + 'obtener_datos.php', data=urllib.parse.urlencode(datos).encode(),
        headers={'User-Agent': UA, 'Referer': BASE + 'index.php?salto=1&subsalto=pluviometria1.php',
                 'X-Requested-With': 'XMLHttpRequest',
                 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'})
    with op.open(req, timeout=40) as r:
        return json.loads(r.read().decode('utf-8'))


def _leer(ruta, defecto):
    try:
        with open(ruta, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return defecto


def _guardar(ruta, datos):
    with open(ruta, 'w', encoding='utf-8') as f:
        json.dump(datos, f, ensure_ascii=False, separators=(',', ':'))


def principal():
    ahora = datetime.now(ZONA)
    try:
        op = _abridor()
        op.open(urllib.request.Request(BASE + 'index.php?salto=1&subsalto=pluviometria1.php',
                                       headers={'User-Agent': UA}), timeout=40).read()   # cookie de sesión
        meteos = _post(op, {'action': 'consultar_meteos'})
        pluvios = [_post(op, {'action': 'consultar_pluvios', 'tipo': t}) for t in range(len(VENTANAS))]
    except Exception as e:
        print(f'  ⚠ CHS no disponible: {type(e).__name__}: {e}')
        return 0

    puntos = {}
    for e in meteos:
        c = str(e.get('CodPuntoMedicion', ''))[:5]
        if not c:
            continue
        p = puntos.setdefault(c, {})
        p['nombre'] = e.get('NombreCortoPM')
        p['propietario'] = e.get('Propietario')
        p['temp'] = num(e.get('UltimoDatoTemp'))
        p['humedad'] = num(e.get('UltimoDatoHumedad'))
        p['fecha_temp'] = e.get('FechaUltimoDatoTemp')
    ventanas = {}
    for t, lista in enumerate(pluvios):
        for e in lista:
            c = str(e.get('CodPuntoMedicion', ''))[:5]
            if not c:
                continue
            p = puntos.setdefault(c, {})
            p.setdefault('nombre', e.get('NombreCortoPM'))
            p.setdefault('propietario', e.get('Propietario'))
            p['fecha_lluvia'] = e.get('FechaUltimoDato')
            ventanas.setdefault(c, {})[VENTANAS[t]] = num(e.get('ValorPrecip'))

    estado = _leer(F_ESTADO, {})
    for c, v in ventanas.items():
        puntos[c]['lluvia'] = v
        puntos[c]['lluvia_hoy'] = acumular_lluvia(estado, c, v, ahora)
    # Sin lluvia de ayer: se limpian los días viejos para que el fichero no crezca
    hoy = ahora.strftime('%Y-%m-%d')
    estado = {c: s for c, s in estado.items() if s.get('dia') == hoy}
    _guardar(F_ESTADO, estado)
    _guardar(F_CHS, {'actualizado': ahora.isoformat(), 'puntos': puntos})
    con_t = sum(1 for p in puntos.values() if p.get('temp') is not None)
    print(f'  ✅ CHS: {len(puntos)} puntos ({con_t} con temperatura, {len(ventanas)} pluviómetros)')
    return 0


if __name__ == '__main__':
    sys.exit(principal())
