"""Convierte las estaciones de Sencrop (sencrop.json) al formato de observación de
Weather Underground que usa todo mapa_totana.py (historiales, riesgo, mapa).

Solo biblioteca estándar. Pruebas: python3 -m unittest test_sencrop_a_wu
"""
import json
import os
from datetime import datetime

PREFIJO = 'SC-'   # stationID = 'SC-' + id de Sencrop, para no chocar con los de WU


def _num(valor):
    return valor if isinstance(valor, (int, float)) and not isinstance(valor, bool) else None


def _epoch(texto):
    try:
        return int(datetime.fromisoformat(str(texto).replace('Z', '+00:00')).timestamp())
    except Exception:
        return None


def convertir(est, zona=None):
    """Una estación de Sencrop -> observación tipo WU (o None si no sirve)."""
    loc = est.get('location') or {}
    lat, lon = _num(loc.get('lat')), _num(loc.get('lng'))
    if not est.get('id') or lat is None or lon is None:
        return None
    if (est.get('state') or {}).get('isActive') is False:
        return None
    m = est.get('measurements') or {}
    temp = (m.get('temperature') or {})
    lluvia = (m.get('rainfall') or {})
    viento = (m.get('windSpeed') or {})
    racha = (m.get('windGust') or {})
    direccion = (m.get('windDirection') or {})
    epoch = _epoch(est.get('latestMeasurementDate'))
    local = ''
    if epoch is not None:
        local = datetime.fromtimestamp(epoch, zona).strftime('%Y-%m-%d %H:%M:%S')
    return {
        'stationID': PREFIJO + est['id'],
        'lat': lat, 'lon': lon,
        'neighborhood': est.get('name') or '',
        'humidity': _num((m.get('relativeHumidity') or {}).get('latestPercent')),
        'winddir': _num(direccion.get('latestDirectionDegree')),
        'uv': None,
        'solarRadiation': None,
        'obsTimeLocal': local,
        'epoch': epoch,
        'metric': {
            'temp': _num(temp.get('latestCelsius')),
            'heatIndex': None,
            'windChill': None,
            'dewpt': _num((m.get('dewPoint') or {}).get('latestCelsius')),
            'pressure': None,
            'windSpeed': _num(viento.get('latestSpeedKph')),
            'windGust': _num(racha.get('lastHourMaxSpeedKph')),
            'precipTotal': _num(lluvia.get('todayMm')),   # acumulado desde medianoche, como WU
        },
    }


def leer_sencrop(ruta, desactivadas=(), zona=None):
    """Lee sencrop.json y devuelve la lista de observaciones tipo WU. Si el fichero
    no existe o está mal, devuelve [] (Sencrop nunca debe romper el ciclo)."""
    try:
        with open(ruta, 'r', encoding='utf-8') as f:
            datos = json.load(f)
    except Exception:
        return []
    salida = []
    for est in datos.get('estaciones', []):
        obs = convertir(est, zona)
        if obs and obs['stationID'].upper() not in {d.upper() for d in desactivadas}:
            salida.append(obs)
    return salida
