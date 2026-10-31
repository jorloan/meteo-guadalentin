"""
Control de calidad de las estaciones WU: estaciones desactivadas a mano y
filtro automático de lecturas imposibles.

Las estaciones particulares fallan mucho (sensor al sol, pluviómetro que
cuenta de golpe 200 mm al limpiarlo, humedad clavada en 0, una estación que
deja de transmitir y WU sigue sirviendo su última lectura…) y un solo dato
absurdo tuerce el mapa de calor de toda la zona. Aquí hay dos defensas:

1. `estaciones_desactivadas.txt`: lista a mano. Una estación ahí no se
   descarga y el mapa la quita también de los históricos ya guardados
   (máquina del tiempo, lluvia acumulada, riesgo). Los archivos no se tocan:
   al sacarla de la lista vuelve con todo su historial.

2. `filtrar_lecturas()`: cada lectura nueva pasa por rangos físicos, saltos
   imposibles respecto a la lectura anterior de la misma estación y
   comparación con sus vecinas. Lo que no pasa se guarda como `None` (no se
   pinta) y queda anotado en `est['descartado']` y en
   `filtro_estaciones.json`, para saber qué estaciones conviene desactivar.

Solo stdlib, como el resto del proyecto.
"""
import math, os
from datetime import datetime, timedelta

# ── Estaciones desactivadas a mano ─────────────────────────────
def leer_desactivadas(ruta):
    """IDs de estaciones desactivadas. Una por línea; lo que va tras '#' es
    el motivo (o un comentario si la línea empieza por '#')."""
    if not os.path.exists(ruta): return set()
    ids = set()
    with open(ruta, encoding='utf-8') as f:
        for l in f:
            sid = l.split('#')[0].strip()
            if sid: ids.add(sid.split()[0].upper())
    return ids

# ── Umbrales del filtro automático ─────────────────────────────
# Rangos físicos para el valle del Guadalentín y alrededores (Murcia,
# Almería, Albacete, Alicante). Holgados a propósito: solo deben caer
# lecturas imposibles, no un día extremo de verdad (récord en Murcia ~47 °C).
RANGOS = {
    'temp':           (-15, 50),     # °C
    'dewpt':          (-35, 35),     # °C
    'humidity':       (1, 100),      # % — 0 exacto es el fallo típico del sensor
    'pressure':       (900, 1070),   # hPa (algunas en altura dan la de la estación, ~940)
    'windSpeed':      (0, 150),      # km/h
    'windGust':       (0, 200),      # km/h
    'precipTotal':    (0, 250),      # mm acumulados del día
    'solarRadiation': (0, 1400),     # W/m²
    'uv':             (0, 16),
}
CAMPOS_METRIC = {'temp', 'dewpt', 'pressure', 'windSpeed', 'windGust', 'precipTotal',
                 'heatIndex', 'windChill'}

SALTO_TEMP       = 10    # °C (una tormenta puede bajar 8-9 de verdad) entre dos lecturas seguidas (≤ VENTANA_SALTO)
SALTO_HUMEDAD    = 50    # puntos de % entre dos lecturas seguidas
SALTO_LLUVIA     = 50    # mm que suma el contador del día de una lectura a otra
VENTANA_SALTO    = 30    # min: más separadas ya no se comparan
VECINAS_RADIO_KM = 20
VECINAS_MIN      = 4     # con menos vecinas no se compara (no hay con qué)
DESVIO_TEMP      = 9     # °C respecto a la mediana de las vecinas (holgado por la altitud)
LECTURA_VIEJA_H  = 3     # una observación más antigua no es "actual": no se pinta
RETENCION_LOG_D  = 7     # días que se recuerda una estación en filtro_estaciones.json

# Lo que se calcula a partir de la temperatura o la humedad cae con ellas.
DERIVADOS = {
    'temp':     ('dewpt', 'heatIndex', 'windChill'),
    'humidity': ('dewpt',),
}

def _get(est, campo):
    if campo in CAMPOS_METRIC: return (est.get('metric') or {}).get(campo)
    return est.get(campo)

def _set_none(est, campo):
    if campo in CAMPOS_METRIC:
        if est.get('metric') is not None: est['metric'][campo] = None
    else:
        est[campo] = None

def _km(la1, lo1, la2, lo2):
    r = math.pi / 180
    x = (lo2 - lo1) * r * math.cos((la1 + la2) / 2 * r)
    y = (la2 - la1) * r
    return 6371 * math.hypot(x, y)

def _mediana(v):
    v = sorted(v); n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2

def _anteriores(h_prev, ahora):
    """Última lectura válida de cada campo por estación, de las instantáneas
    del historial con menos de VENTANA_SALTO minutos. {sid: {campo: valor}}"""
    lim = ahora - timedelta(minutes=VENTANA_SALTO)
    res = {}
    for snap in reversed(h_prev or []):
        try:
            t = datetime.fromisoformat(snap['timestamp'])
            if t.tzinfo is None and ahora.tzinfo is not None: t = t.replace(tzinfo=ahora.tzinfo)
        except Exception:
            continue
        if t < lim: break
        for est in snap.get('stations') or []:
            if not est or not est.get('stationID'): continue
            d = res.setdefault(est['stationID'], {})
            for c in ('temp', 'humidity', 'precipTotal'):
                v = _get(est, c)
                if v is not None and c not in d: d[c] = v
    return res

def filtrar_lecturas(nuevos, h_prev, ahora):
    """Limpia en el sitio las lecturas absurdas de `nuevos` (observaciones de
    WU) y devuelve (lecturas_que_quedan, descartes). Una observación entera
    se quita solo si es vieja; si no, se anulan los campos malos y el resto
    de la estación sigue valiendo. descartes = [(sid, campo, valor, motivo)]."""
    descartes = []
    def descartar(est, campo, motivo):
        v = _get(est, campo)
        if v is None: return
        descartes.append((est['stationID'], campo, v, motivo))
        est.setdefault('descartado', {})[campo] = motivo
        _set_none(est, campo)
        for d in DERIVADOS.get(campo, ()):
            if _get(est, d) is not None:
                _set_none(est, d)
                est['descartado'].setdefault(d, f'depende de {campo}')

    quedan = []
    ahora_ts = ahora.timestamp()
    for est in nuevos:
        if not est or not est.get('stationID'): continue
        ep = est.get('epoch')
        if isinstance(ep, (int, float)) and ahora_ts - ep > LECTURA_VIEJA_H * 3600:
            horas = (ahora_ts - ep) / 3600
            descartes.append((est['stationID'], 'observacion', est.get('obsTimeLocal'),
                              f'lectura de hace {horas:.0f} h'))
            continue
        quedan.append(est)

    # 1. Rangos físicos y coherencia
    for est in quedan:
        for campo, (lo, hi) in RANGOS.items():
            v = _get(est, campo)
            if v is None: continue
            if not isinstance(v, (int, float)) or not (lo <= v <= hi):
                descartar(est, campo, f'fuera de rango ({lo} a {hi})')
        t, dp = _get(est, 'temp'), _get(est, 'dewpt')
        if t is not None and dp is not None and dp > t + 1:
            descartar(est, 'dewpt', 'punto de rocío por encima de la temperatura')

    # 2. Saltos respecto a la lectura anterior de la misma estación
    prev = _anteriores(h_prev, ahora)
    for est in quedan:
        p = prev.get(est['stationID'])
        if not p: continue
        t = _get(est, 'temp')
        if t is not None and 'temp' in p and abs(t - p['temp']) > SALTO_TEMP:
            descartar(est, 'temp', f'salto de {t - p["temp"]:+.1f} °C en ≤{VENTANA_SALTO} min')
        h = _get(est, 'humidity')
        if h is not None and 'humidity' in p and abs(h - p['humidity']) > SALTO_HUMEDAD:
            descartar(est, 'humidity', f'salto de {h - p["humidity"]:+.0f} % en ≤{VENTANA_SALTO} min')
        # El contador de lluvia vuelve a 0 a medianoche: bajar es normal,
        # solo se mira lo que sube.
        pr = _get(est, 'precipTotal')
        if pr is not None and 'precipTotal' in p and pr - p['precipTotal'] > SALTO_LLUVIA:
            descartar(est, 'precipTotal', f'+{pr - p["precipTotal"]:.1f} mm en ≤{VENTANA_SALTO} min')

    # 3. Temperatura frente a las vecinas (sensor al sol, mal instalado…).
    # Se compara con los valores ya limpios de los pasos 1 y 2, todos a la
    # vez (antes de quitar ninguna), para que el orden no influya.
    con_temp = [(e, e['lat'], e['lon'], _get(e, 'temp')) for e in quedan
                if _get(e, 'temp') is not None
                and isinstance(e.get('lat'), (int, float)) and isinstance(e.get('lon'), (int, float))]
    raros = []
    for est, la, lo, t in con_temp:
        vec = [t2 for e2, la2, lo2, t2 in con_temp
               if e2 is not est and _km(la, lo, la2, lo2) <= VECINAS_RADIO_KM]
        if len(vec) < VECINAS_MIN: continue
        med = _mediana(vec)
        if abs(t - med) > DESVIO_TEMP:
            raros.append((est, t - med, len(vec)))
    for est, dif, n in raros:
        descartar(est, 'temp', f'{dif:+.1f} °C respecto a la mediana de {n} vecinas')

    return quedan, descartes

def anotar_descartes(registro, descartes, ahora):
    """Acumula los descartes en el registro de filtro_estaciones.json:
    {sid: {campo: {veces, primera, ultima, valor, motivo}}}, olvidando lo que
    lleva más de RETENCION_LOG_D días sin repetirse."""
    iso = ahora.isoformat(timespec='minutes')
    for sid, campo, valor, motivo in descartes:
        c = registro.setdefault(sid, {}).setdefault(campo, {'veces': 0, 'primera': iso})
        c['veces'] += 1
        c['ultima'] = iso
        c['valor'] = valor
        c['motivo'] = motivo
    lim = ahora - timedelta(days=RETENCION_LOG_D)
    for sid in list(registro):
        for campo in list(registro[sid]):
            try:
                u = datetime.fromisoformat(registro[sid][campo].get('ultima', ''))
                if u.tzinfo is None and ahora.tzinfo is not None: u = u.replace(tzinfo=ahora.tzinfo)
                if u < lim: del registro[sid][campo]
            except Exception:
                del registro[sid][campo]
        if not registro[sid]: del registro[sid]
    return registro
