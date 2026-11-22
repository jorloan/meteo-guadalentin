"""Descarga las estaciones de Sencrop (Comunidad de Regantes de Totana) a sencrop.json.

Se ejecuta en GitHub Actions ANTES de mapa_totana.py. Necesita Playwright
(pip install playwright) porque Sencrop no ofrece una API pública con clave:
se inicia sesión como lo haría una persona y se recoge la respuesta que la
propia web de Sencrop usa para pintar su Dashboard.

    SENCROP_USER=... SENCROP_PASSWORD=... python3 sencrop_descargar.py

Es tolerante a fallos: si algo falla no toca sencrop.json (se conserva la última
descarga buena) y sale con código 0, para no frenar el ciclo de 5 minutos.
El repositorio y sus logs son públicos: no se imprime nada sensible.
"""
import json
import os
import sys
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
F_SENCROP = os.path.join(BASE_DIR, 'sencrop.json')
URL_LOGIN = 'https://app.sencrop.com/login'
URL_DASHBOARD = 'https://app.sencrop.com/station/dashboard'
USUARIO = os.environ.get('SENCROP_USER', '')
CLAVE = os.environ.get('SENCROP_PASSWORD', '')

def tipos(valor, nivel=0):
    """Estructura de un JSON sin valores (para el log público)."""
    if nivel > 3: return '…'
    if isinstance(valor, dict):
        return '{' + ', '.join(f'{k}: {tipos(v, nivel + 1)}' for k, v in list(valor.items())[:20]) + '}'
    if isinstance(valor, list):
        return f'[{len(valor)}]' if not valor else f'[{len(valor)} x {tipos(valor[0], nivel + 1)}]'
    if isinstance(valor, bool): return 'bool'
    if isinstance(valor, (int, float)): return 'num'
    return 'null' if valor is None else 'str'


def reducir(est):
    """Solo lo que necesita mapa_totana.py (sin la parte de interfaz)."""
    return {k: est.get(k) for k in ('id', 'name', 'subtitle', 'latestMeasurementDate',
                                    'type', 'location', 'deviceId', 'state', 'model',
                                    'measurements')}


def descargar():
    from playwright.sync_api import sync_playwright

    mejor = None   # lista de estaciones más completa que se haya visto
    with sync_playwright() as p:
        navegador = p.chromium.launch()
        pagina = navegador.new_context(locale='es-ES').new_page()
        capt = {'req': None}
        todas = {}   # id -> estación; el Dashboard pagina de 8 en 8 al bajar por la lista

        def al_pedir(req):
            if 'station/dashboard/station-list' in req.url and req.method == 'POST':
                capt['req'] = req

        def al_responder(resp):
            if 'station/dashboard/station-list' in resp.url and resp.status == 200:
                try:
                    for e in resp.json().get('stations') or []:
                        if e.get('id'): todas[e['id']] = e
                except Exception:
                    pass

        pagina.on('request', al_pedir)
        pagina.on('response', al_responder)

        pagina.goto(URL_LOGIN, wait_until='networkidle')
        pagina.fill('input[type=email], input[name=email]', USUARIO)
        pagina.fill('input[type=password]', CLAVE)
        pagina.click('button[type=submit]')
        pagina.wait_for_url('**/home**', timeout=30000)
        pagina.wait_for_load_state('networkidle')

        pagina.goto(URL_DASHBOARD, wait_until='networkidle')
        pagina.wait_for_timeout(3000)

        print(f'  Dashboard: {len(todas)} estaciones en la primera página')
        sin_novedad = 0
        for _ in range(12):
            antes = len(todas)
            pagina.evaluate("""() => {
                document.querySelectorAll('*').forEach(e => {
                    if (e.scrollHeight > e.clientHeight + 50 &&
                        ['auto', 'scroll'].includes(getComputedStyle(e).overflowY))
                        e.scrollTop = e.scrollHeight;
                });
                window.scrollTo(0, document.body.scrollHeight);
            }""")
            pagina.wait_for_timeout(1500)
            sin_novedad = sin_novedad + 1 if len(todas) == antes else 0
            if sin_novedad >= 2:
                break
        print(f'  Tras bajar por la lista: {len(todas)} estaciones')
        if capt['req'] is not None:
            try:
                print('  Cuerpo de la petición (solo estructura):',
                      tipos(json.loads(capt['req'].post_data or '{}')))
            except Exception:
                pass
        mejor = list(todas.values())
        navegador.close()
    return mejor


def principal():
    if not USUARIO or not CLAVE:
        print('⚠ Sencrop: faltan los secrets SENCROP_USER / SENCROP_PASSWORD')
        return 0
    try:
        estaciones = descargar()
    except Exception as e:
        print(f'⚠ Sencrop: descarga fallida ({type(e).__name__}); se conserva la anterior')
        return 0
    if not estaciones:
        print('⚠ Sencrop: sin estaciones; se conserva la descarga anterior')
        return 0
    datos = {'actualizado': datetime.now(timezone.utc).isoformat(),
             'estaciones': [reducir(e) for e in estaciones]}
    with open(F_SENCROP, 'w', encoding='utf-8') as f:
        json.dump(datos, f, ensure_ascii=False, separators=(',', ':'))
    print(f'✅ Sencrop: {len(estaciones)} estaciones guardadas en sencrop.json')
    return 0


if __name__ == '__main__':
    sys.exit(principal())
