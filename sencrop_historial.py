"""Rellenado de historial de las estaciones Sencrop (formato Weather Underground).

Sencrop da series horarias de los últimos días; los historiales del mapa
(history_24h / history_2d / history_7d) son listas de «fotos» de toda la red con
estaciones en formato WU. Aquí se convierten las series horarias de Sencrop y se
inyectan en las fotos que ya existen, en las que esa estación no está.

Solo biblioteca estándar. Pruebas: python3 -m unittest test_sencrop_historial
"""
import json
from datetime import datetime, timedelta

# (clave interna) -> (medida de la API, nombre de la serie)
SERIES = {
    'temp':   ('temperature', 'temperature:interpolated'),
    'hr':     ('relativeHumidity', 'relativeHumidity:interpolated'),
    'viento': ('windSpeed', 'windSpeed:2m:interpolated'),
    'racha':  ('windGust', 'windGust:2m:max'),
    'dir':    ('windDirection', 'windDirection:2m:interpolated'),
    'rocio':  ('dewPoint', 'dewPoint:interpolated'),
    'lluvia': ('rainfall', 'rainfall:sum'),
}
MEDIDAS = sorted({m for m, _ in SERIES.values()})


def _epoch(ts):
    """Marca de tiempo de la API (ISO o epoch en s/ms) -> epoch en segundos, o None."""
    try:
        if isinstance(ts, (int, float)) and not isinstance(ts, bool):
            return int(ts / 1000) if ts > 1e11 else int(ts)
        return int(datetime.fromisoformat(str(ts).replace('Z', '+00:00')).timestamp())
    except Exception:
        return None


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def serie_horaria(respuesta):
    """Respuesta JSON de la API -> {clave: {epoch_hora: valor}} (solo valores numéricos)."""
    try:
        medidas = respuesta['response']['stationMeasurements']
    except Exception:
        return {}
    salida = {}
    for clave, (medida, nombre) in SERIES.items():
        for s in medidas.get(medida) or []:
            if s.get('metric') != nombre:
                continue
            puntos = {}
            for p in s.get('timeseries') or []:
                e, v = _epoch(p.get('timestamp')), _num(p.get('value'))
                if e is not None and v is not None:
                    puntos[e] = v
            if puntos:
                salida[clave] = puntos
    return salida


def _interpolar(puntos, t, tolerancia=5400):
    """Valor en el instante t (epoch) por interpolación lineal entre horas vecinas."""
    if not puntos:
        return None
    antes = [e for e in puntos if e <= t]
    despues = [e for e in puntos if e >= t]
    a = max(antes) if antes else None
    d = min(despues) if despues else None
    if a is None and d is None:
        return None
    if a is None:
        return puntos[d] if d - t <= tolerancia else None
    if d is None:
        return puntos[a] if t - a <= tolerancia else None
    if a == d:
        return puntos[a]
    if d - a > 3 * 3600:      # hueco largo: no inventar
        return None
    return puntos[a] + (puntos[d] - puntos[a]) * (t - a) / (d - a)


def _angulo(puntos, t):
    """Dirección: el valor de la hora más cercana (no se interpola un ángulo)."""
    if not puntos:
        return None
    e = min(puntos, key=lambda x: abs(x - t))
    return puntos[e] if abs(e - t) <= 5400 else None


def _lluvia_acumulada(puntos, t, zona):
    """mm caídos desde la medianoche local hasta t (horas completas + fracción de la actual).
    None si no hay datos de lluvia en ese día."""
    if not puntos:
        return None
    local = datetime.fromtimestamp(t, zona)
    medianoche = int(local.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    total, hay = 0.0, False
    for e, v in puntos.items():
        if e < medianoche or e >= t:
            continue
        hay = True
        total += v * min(1.0, (t - e) / 3600.0)
    return round(total, 2) if hay else None


def _r(v, n=1):
    return None if v is None else round(v, n)


def observacion(plantilla, series, t, zona):
    """Observación tipo WU de la estación en el instante t (epoch), o None si no hay datos."""
    temp = _interpolar(series.get('temp'), t)
    if temp is None:
        return None
    obs = json.loads(json.dumps(plantilla))
    obs['humidity'] = _r(_interpolar(series.get('hr'), t), 0)
    obs['winddir'] = _r(_angulo(series.get('dir'), t), 0)
    obs['epoch'] = t
    obs['obsTimeLocal'] = datetime.fromtimestamp(t, zona).strftime('%Y-%m-%d %H:%M:%S')
    m = obs['metric']
    m['temp'] = _r(temp)
    m['dewpt'] = _r(_interpolar(series.get('rocio'), t))
    m['windSpeed'] = _r(_interpolar(series.get('viento'), t))
    m['windGust'] = _r(_interpolar(series.get('racha'), t))
    m['precipTotal'] = _lluvia_acumulada(series.get('lluvia'), t, zona)
    return obs


def inyectar(historial, plantillas, series_por_estacion, zona):
    """Añade a cada foto del historial las estaciones Sencrop que le faltan (o que están
    sin temperatura). Devuelve cuántas observaciones se añadieron. Modifica `historial`."""
    añadidas = 0
    for foto in historial:
        try:
            t = datetime.fromisoformat(foto['timestamp'])
            if t.tzinfo is None:
                t = t.replace(tzinfo=zona)
            t = int(t.timestamp())
        except Exception:
            continue
        ests = foto.setdefault('stations', [])
        existentes = {e.get('stationID'): e for e in ests if e}
        for sid, plantilla in plantillas.items():
            ya = existentes.get(sid)
            if ya and (ya.get('metric') or {}).get('temp') is not None:
                continue
            obs = observacion(plantilla, series_por_estacion.get(sid) or {}, t, zona)
            if obs is None:
                continue
            if ya:
                ests.remove(ya)
            ests.append(obs)
            añadidas += 1
    return añadidas


def proyectar_precip(historial):
    """history_2d_precip.json: solo stationID + precipTotal de cada foto."""
    out = []
    for e in historial:
        ests = []
        for est in (e.get('stations') or []):
            if not est:
                continue
            p = (est.get('metric') or {}).get('precipTotal')
            if p is None:
                continue
            ests.append({'stationID': est.get('stationID'), 'metric': {'precipTotal': p}})
        out.append({'timestamp': e.get('timestamp'), 'stations': ests})
    return out
