"""Estaciones automáticas de AEMET (OpenData, observacion/convencional/todas) convertidas al
formato de observación de Weather Underground que usa todo mapa_totana.py.

AEMET da, por estación, una fila cada 10 min de las últimas 24 h: `fint` (UTC, fin del periodo),
ta (°C), hr (%), vv y vmax (m/s), dv (°), pres (hPa, de la estación), prec (mm del periodo),
tpr (rocío °C), con lat/lon/alt/ubi. Solo biblioteca estándar.
Pruebas: python3 -m unittest test_aemet_a_wu
"""
import json
from datetime import datetime, timedelta, timezone

PREFIJO = 'AE-'
LECTURA_VIEJA_H = 3
MS_A_KMH = 3.6


def num(v):
    try:
        if v is None or str(v).strip() in ('', '-'):
            return None
        return float(str(v).replace(',', '.'))
    except Exception:
        return None


def fecha_utc(texto):
    """'2026-11-22T20:10:00' (UTC) -> datetime con zona, o None."""
    try:
        t = str(texto).strip().replace('Z', '')
        return datetime.fromisoformat(t).replace(tzinfo=timezone.utc)
    except Exception:
        return None


def nombre_legible(ubi):
    """'MURCIA/ALCANTARILLA' -> 'Murcia/Alcantarilla'; 'ARCHENA' -> 'Archena'."""
    return '/'.join(' '.join(p.capitalize() for p in parte.split()) for parte in str(ubi or '').split('/'))


def lluvia_hoy(filas, ahora):
    """mm desde la medianoche local: suma de `prec` de las filas de 10 min cuyo final cae hoy."""
    medianoche = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
    total, hay = 0.0, False
    for f in filas:
        d, p = fecha_utc(f.get('fint')), num(f.get('prec'))
        if d is None or p is None or p < 0:
            continue
        if medianoche < d <= ahora:
            total += p
            hay = True
    return round(total, 1) if hay else None


def convertir(idema, est, zona, ahora):
    """`est` = {ubi, lat, lon, alt, filas:[...]} -> observación tipo WU, o None."""
    filas = est.get('filas') or []
    validas = [(fecha_utc(f.get('fint')), f) for f in filas]
    validas = [(d, f) for d, f in validas if d is not None and num(f.get('ta')) is not None]
    if not validas or num(est.get('lat')) is None or num(est.get('lon')) is None:
        return None
    d, f = max(validas, key=lambda x: x[0])
    ahora_utc = ahora.astimezone(timezone.utc)
    espera = (ahora_utc - d).total_seconds()
    if espera > LECTURA_VIEJA_H * 3600 or espera < -3600:
        return None
    vv, vmax = num(f.get('vv')), num(f.get('vmax'))
    ref = min(d, ahora_utc)
    ref_local = ref.astimezone(zona) if zona else ref
    return {
        'stationID': PREFIJO + idema,
        'lat': num(est.get('lat')), 'lon': num(est.get('lon')),
        'neighborhood': 'AEMET · ' + nombre_legible(est.get('ubi') or idema),
        'humidity': num(f.get('hr')),
        'winddir': num(f.get('dv')), 'uv': None, 'solarRadiation': None,
        'obsTimeLocal': ref_local.strftime('%Y-%m-%d %H:%M:%S'),
        'epoch': int(ref.timestamp()),
        'metric': {'temp': num(f.get('ta')), 'heatIndex': None, 'windChill': None,
                   'dewpt': num(f.get('tpr')), 'pressure': num(f.get('pres')),
                   'windSpeed': round(vv * MS_A_KMH, 1) if vv is not None else None,
                   'windGust': round(vmax * MS_A_KMH, 1) if vmax is not None else None,
                   'precipTotal': lluvia_hoy(filas, ahora)},
    }


def leer_aemet(ruta, desactivadas=(), zona=None, ahora=None):
    """Lee aemet.json -> lista de observaciones tipo WU. Si algo falta o está mal devuelve []."""
    try:
        with open(ruta, 'r', encoding='utf-8') as f:
            datos = json.load(f)
    except Exception:
        return []
    ahora = ahora or datetime.now(zona)
    off = {d.upper() for d in desactivadas}
    salida = []
    for idema, est in (datos.get('estaciones') or {}).items():
        if (PREFIJO + idema).upper() in off:
            continue
        try:
            obs = convertir(idema, est, zona, ahora)
        except Exception:
            obs = None
        if obs:
            salida.append(obs)
    return salida
