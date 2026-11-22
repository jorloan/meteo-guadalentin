"""Estaciones del SIAM (Red Agrometeorológica del IMIDA, Murcia) convertidas al formato de
observación de Weather Underground que usa todo mapa_totana.py.

El SIAM publica, por estación GPRS, el informe de las últimas 24 h: una fila por hora con
medias de temperatura, humedad, radiación, viento (m/s), dirección, rocío y lluvia (mm).
La hora de cada fila es UTC y es el INICIO del periodo (la fila 15:00 cubre 15:00-16:00 UTC).
Coordenadas en imida_coordenadas.json (UTM de las fichas oficiales, ya pasadas a lat/lon).
Solo biblioteca estándar. Pruebas: python3 -m unittest test_imida_a_wu
"""
import json
import os
from datetime import datetime, timedelta, timezone

PREFIJO = 'IM-'
LECTURA_VIEJA_H = 3         # un dato más viejo no se usa (estación sin enviar)
MS_A_KMH = 3.6


def num(texto):
    """'12,3' -> 12.3; vacío / basura -> None."""
    try:
        t = str(texto).strip().replace(',', '.')
        return None if t in ('', '-') else float(t)
    except Exception:
        return None


def inicio_fila(texto):
    """'22/11/2026 15:00' (UTC) -> datetime UTC, o None."""
    try:
        return datetime.strptime(str(texto).strip(), '%d/%m/%Y %H:%M').replace(tzinfo=timezone.utc)
    except Exception:
        return None


def nombre_legible(nombre):
    """'TOTANA (Lebor)' -> 'Totana (Lebor)'."""
    return ' '.join(p.capitalize() if p.isupper() else p for p in str(nombre or '').split())


def lluvia_hoy(filas, ahora):
    """mm caídos desde la medianoche local, sumando las filas horarias cuyo final cae hoy."""
    medianoche = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
    total, hay = 0.0, False
    for f in filas:
        ini = inicio_fila(f.get('fecha'))
        p = num(f.get('prec'))
        if ini is None or p is None:
            continue
        if ini + timedelta(hours=1) > medianoche and ini <= ahora:
            total += p
            hay = True
    return round(total, 1) if hay else None


def convertir(codigo, nombre, lat, lon, filas, zona, ahora):
    """Filas del informe de 24 h (más reciente primero) -> observación tipo WU, o None."""
    validas = [(inicio_fila(f.get('fecha')), f) for f in filas or []]
    validas = [(d, f) for d, f in validas if d is not None and num(f.get('tmed')) is not None]
    if not validas:
        return None
    ini, f = max(validas, key=lambda x: x[0])
    fin = ini + timedelta(hours=1)                  # el dato vale al cierre de la hora
    ahora_utc = ahora.astimezone(timezone.utc)
    espera = (ahora_utc - fin).total_seconds()
    if espera > LECTURA_VIEJA_H * 3600 or espera < -3600:
        return None
    vv, rafaga = num(f.get('vvmed')), num(f.get('vvmax'))
    ref = fin if fin <= ahora_utc else ahora_utc
    ref_local = ref.astimezone(zona) if zona else ref
    return {
        'stationID': PREFIJO + codigo,
        'lat': lat, 'lon': lon,
        'neighborhood': 'IMIDA · ' + nombre_legible(nombre),
        'humidity': num(f.get('hrmed')),
        'winddir': num(f.get('dvmed')), 'uv': None,
        'solarRadiation': num(f.get('radmed')),
        'obsTimeLocal': ref_local.strftime('%Y-%m-%d %H:%M:%S'),
        'epoch': int(ref.timestamp()),
        'metric': {'temp': num(f.get('tmed')), 'heatIndex': None, 'windChill': None,
                   'dewpt': num(f.get('dewpt')), 'pressure': None,
                   'windSpeed': round(vv * MS_A_KMH, 1) if vv is not None else None,
                   'windGust': round(rafaga * MS_A_KMH, 1) if rafaga is not None else None,
                   'precipTotal': lluvia_hoy(filas, ahora)},
    }


def leer_imida(ruta_imida, ruta_coords, desactivadas=(), zona=None, ahora=None):
    """Lee imida.json + imida_coordenadas.json -> lista de observaciones tipo WU. Si algo
    falta o está mal devuelve [] (el IMIDA nunca debe romper el ciclo)."""
    try:
        with open(ruta_imida, 'r', encoding='utf-8') as f:
            datos = json.load(f)
        with open(ruta_coords, 'r', encoding='utf-8') as f:
            coords = json.load(f).get('estaciones', {})
    except Exception:
        return []
    ahora = ahora or datetime.now(zona)
    off = {d.upper() for d in desactivadas}
    salida = []
    for codigo, filas in (datos.get('estaciones') or {}).items():
        c = coords.get(codigo)
        if not c or (PREFIJO + codigo).upper() in off:
            continue
        try:
            obs = convertir(codigo, c[0], c[1], c[2], filas, zona, ahora)
        except Exception:
            obs = None
        if obs:
            salida.append(obs)
    return salida
