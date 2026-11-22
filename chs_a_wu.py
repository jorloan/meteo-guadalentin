"""Estaciones de la Confederación Hidrográfica del Segura (SAIH, saihweb.chsegura.es)
convertidas al formato de observación de Weather Underground que usa todo mapa_totana.py.

El SAIH publica, por punto de medición: temperatura y humedad (estaciones «EM.») y lluvia
acumulada en ventanas móviles (instantánea, 1, 3, 4, 6, 12 y 24 h) en los pluviómetros.
No publica coordenadas en el visor: están en chs_coordenadas.json (fichas oficiales).
La lluvia «de hoy» (desde medianoche, como WU) no existe en el SAIH: se reconstruye aquí
sumando la ventana de 1 h tomada cerca de cada hora en punto (acumular_lluvia).

Solo biblioteca estándar. Pruebas: python3 -m unittest test_chs_a_wu
"""
import json
import os
import re
from datetime import datetime

PREFIJO = 'CH-'
VENTANAS = ('inst', '1h', '3h', '4h', '6h', '12h', '24h')      # tipo 0..6 de consultar_pluvios
HORAS_VENTANA = {'1h': 1, '3h': 3, '4h': 4, '6h': 6, '12h': 12, '24h': 24}
LECTURA_VIEJA_H = 3        # un dato más viejo no se usa (sensor caído)
MINUTO_CIERRE_HORA = 10    # la ventana de 1 h se toma como «hora anterior» si el ciclo cae en :00-:09


def num(texto):
    """'12,3' -> 12.3; '-' / vacío / basura -> None."""
    try:
        t = str(texto).strip().replace(',', '.')
        return None if t in ('', '-') else float(t)
    except Exception:
        return None


def fecha(texto, zona):
    """'22-11-2026 17:05' (hora local de Madrid) -> datetime con zona, o None."""
    try:
        d = datetime.strptime(str(texto).strip(), '%d-%m-%Y %H:%M')
        return d.replace(tzinfo=zona) if zona else d
    except Exception:
        return None


def limpiar_nombre(nombre):
    n = re.sub(r'^\s*(EM\.?|Pl\.?|Pln\.?|PL\.?)\s*', '', str(nombre or '')).strip()
    return n or str(nombre or '').strip()


def acumular_lluvia(estado, codigo, ventanas, ahora):
    """Lluvia desde la medianoche local (mm) de un pluviómetro. `estado` (dict, se
    modifica) guarda, por punto y día, la lluvia de cada hora cerrada: se anota la ventana
    de 1 h del primer ciclo que cae en los 10 primeros minutos de la hora siguiente. La hora
    en curso se estima con la ventana de 1 h menos lo que aún cuenta de la hora anterior, y
    nunca baja de la mayor ventana (1-24 h) que cabe entera dentro de hoy. Devuelve mm o None."""
    w1 = ventanas.get('1h')
    hoy = ahora.strftime('%Y-%m-%d')
    st = estado.get(codigo)
    if not st or st.get('dia') != hoy:
        st = {'dia': hoy, 'horas': {}}
        estado[codigo] = st
    h, m = ahora.hour, ahora.minute
    if w1 is None:
        return None
    if m < MINUTO_CIERRE_HORA and h > 0:
        st['horas'].setdefault(str(h - 1), w1)
    cerradas = sum(v for k, v in st['horas'].items() if int(k) < h)
    previa = st['horas'].get(str(h - 1))
    if h == 0:
        parcial = w1 * m / 60.0
    elif previa is not None:
        parcial = max(0.0, w1 - previa * (60 - m) / 60.0)
    else:
        parcial = w1
    total = cerradas + min(parcial, w1)
    horas_hoy = h + m / 60.0
    cotas = [ventanas[k] for k, hh in HORAS_VENTANA.items()
             if ventanas.get(k) is not None and hh <= horas_hoy]
    if cotas:
        total = max(total, max(cotas))
    return round(total, 1)


def convertir(codigo, punto, lat, lon, zona, ahora):
    """Un punto del SAIH (dict de chs.json) -> observación tipo WU, o None si no sirve."""
    if lat is None or lon is None:
        return None
    limite = LECTURA_VIEJA_H * 3600
    marcas = []

    def fresco(campo_fecha):
        d = fecha(punto.get(campo_fecha), zona)
        if d is None or (ahora - d).total_seconds() > limite or (ahora - d).total_seconds() < -3600:
            return None
        return d

    d_t = fresco('fecha_temp')
    temp = num(punto.get('temp')) if d_t else None
    hum = num(punto.get('humedad')) if d_t else None
    if d_t:
        marcas.append(d_t)
    d_l = fresco('fecha_lluvia')
    lluvia = punto.get('lluvia_hoy') if d_l and isinstance(punto.get('lluvia_hoy'), (int, float)) else None
    if d_l:
        marcas.append(d_l)
    if not marcas or (temp is None and lluvia is None):
        return None
    ref = max(marcas)
    return {
        'stationID': PREFIJO + codigo,
        'lat': lat, 'lon': lon,
        'neighborhood': 'CHS · ' + limpiar_nombre(punto.get('nombre')),
        'humidity': hum,
        'winddir': None, 'uv': None, 'solarRadiation': None,
        'obsTimeLocal': ref.strftime('%Y-%m-%d %H:%M:%S'),
        'epoch': int(ref.timestamp()),
        'metric': {'temp': temp, 'heatIndex': None, 'windChill': None, 'dewpt': None,
                   'pressure': None, 'windSpeed': None, 'windGust': None, 'precipTotal': lluvia},
    }


def leer_chs(ruta_chs, ruta_coords, desactivadas=(), zona=None, ahora=None):
    """Lee chs.json + chs_coordenadas.json -> lista de observaciones tipo WU. Si algo falta
    o está mal devuelve [] (la CHS nunca debe romper el ciclo)."""
    try:
        with open(ruta_chs, 'r', encoding='utf-8') as f:
            datos = json.load(f)
        with open(ruta_coords, 'r', encoding='utf-8') as f:
            coords = json.load(f).get('puntos', {})
    except Exception:
        return []
    ahora = ahora or datetime.now(zona)
    off = {d.upper() for d in desactivadas}
    salida = []
    for codigo, punto in (datos.get('puntos') or {}).items():
        c = coords.get(codigo)
        if not c or (PREFIJO + codigo).upper() in off:
            continue
        obs = convertir(codigo, punto, c[0], c[1], zona, ahora)
        if obs:
            salida.append(obs)
    return salida
