import urllib.request, json, ssl, os, webbrowser, concurrent.futures, subprocess, math, shutil
from datetime import datetime, timedelta

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

WU_KEY = "6532d6454b8aa370768e63d6ba5a832e"

# ── Rutas (funciona en Mac y en GitHub Actions) ───────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def _repo():
    c = BASE_DIR
    for _ in range(4):
        if os.path.isdir(os.path.join(c, '.git')): return c
        c = os.path.dirname(c)
    m = os.path.expanduser("~/Documents/meteo-guadalentin")
    return m if os.path.isdir(m) else BASE_DIR

REPO_DIR = _repo()
DIR_PUB  = os.path.join(REPO_DIR, 'public')
F_H24    = os.path.join(REPO_DIR, 'history_24h.json')
F_H2D    = os.path.join(REPO_DIR, 'history_2d.json')
F_H7D    = os.path.join(REPO_DIR, 'history_7d.json')
F_AGRI   = os.path.join(REPO_DIR, 'historial_agricola.json')
F_DSV    = os.path.join(REPO_DIR, 'historial_dsv.json')
F_RIESGO = os.path.join(REPO_DIR, 'historial_riesgo.json')
DIR_RADAR = os.path.join(REPO_DIR, 'radar_tiles')
F_RADAR_MANIFEST = os.path.join(DIR_RADAR, 'manifest.json')
os.makedirs(DIR_PUB, exist_ok=True)
os.makedirs(DIR_RADAR, exist_ok=True)

MIN_DIAS = 5   # días mínimos para calcular riesgo

# ── Estaciones WU ─────────────────────────────────────────────
F_EST = os.path.join(BASE_DIR, 'estaciones.txt')
if not os.path.exists(F_EST):
    with open(F_EST, 'w') as f:
        for e in ["ITOTAN8","ITOTAN2","ITOTAN16","ITOTAN5","ITOTAN33",
                  "ITOTAN43","ITOTAN31","ITOTAN42","ITOTAN9","ITOTAN41",
                  "ITOTAN10","ITOTAN17"]:
            f.write(e+"\n")

ESTACIONES = [l.split('#')[0].strip() for l in open(F_EST) if l.split('#')[0].strip()]

# ── Utilidades ────────────────────────────────────────────────
def leer(ruta, default):
    if os.path.exists(ruta):
        try: return json.load(open(ruta, 'r', encoding='utf-8'))
        except: pass
    return default

def guardar(ruta, data):
    with open(ruta, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def dist(la1, lo1, la2, lo2):
    return ((la1-la2)**2 + (lo1-lo2)**2)**0.5

# ── WU: observación actual ────────────────────────────────────
def wu(sid):
    url = (f"https://api.weather.com/v2/pws/observations/current"
           f"?stationId={sid}&format=json&units=m&numericPrecision=decimal&apiKey={WU_KEY}")
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
            'Referer':    'https://www.wunderground.com/'})
        with urllib.request.urlopen(req, context=ctx, timeout=6) as r:
            obs = json.loads(r.read().decode('utf-8')).get('observations', [])
            return obs[0] if obs else None
    except Exception as e:
        print(f"  ⚠ WU {sid}: {e}")
    return None

# ── Historial 24h ─────────────────────────────────────────────
# Solo se guardan los campos que realmente lee el frontend (comprobado por
# grep sobre mapa_totana.py: est.* / m.*), para no arrastrar en cada
# snapshot campos muertos (country, softwareType, qcStatus, obsTimeUtc,
# realtimeFrequency, metric.elev, metric.precipRate) que no se muestran
# en ningún sitio pero sí engordan history_24h/2d/7d.json.
def _recortar_estacion(est):
    if not est: return est
    m = est.get('metric') or {}
    return {
        'stationID': est.get('stationID'),
        'lat': est.get('lat'), 'lon': est.get('lon'),
        'neighborhood': est.get('neighborhood'),
        'humidity': est.get('humidity'),
        'winddir': est.get('winddir'),
        'uv': est.get('uv'),
        'solarRadiation': est.get('solarRadiation'),
        'obsTimeLocal': est.get('obsTimeLocal'),
        'epoch': est.get('epoch'),
        'metric': {
            'temp': m.get('temp'), 'heatIndex': m.get('heatIndex'),
            'windChill': m.get('windChill'), 'dewpt': m.get('dewpt'),
            'pressure': m.get('pressure'), 'windSpeed': m.get('windSpeed'),
            'windGust': m.get('windGust'), 'precipTotal': m.get('precipTotal'),
        },
    }

def hist24(nuevos, ahora, minutos_intervalo=15):
    h   = leer(F_H24, [])
    lim = ahora - timedelta(hours=24)
    ok  = []
    for e in h:
        try:
            t = datetime.fromisoformat(e['timestamp'])
            if t.tzinfo is None: t = t.replace(tzinfo=ahora.tzinfo)
            if t > lim: ok.append(e)
        except: pass

    debe_anadir = True
    if ok:
        try:
            t_ult = datetime.fromisoformat(ok[-1]['timestamp'])
            if t_ult.tzinfo is None: t_ult = t_ult.replace(tzinfo=ahora.tzinfo)
            debe_anadir = (ahora - t_ult) >= timedelta(minutes=minutos_intervalo)
        except: pass

    if debe_anadir:
        ok.append({'timestamp': ahora.isoformat(),
                   'stations': [_recortar_estacion(e) for e in nuevos]})
    guardar(F_H24, ok)
    print(f"  ✅ Historial 24h: {len(ok)} entradas")
    return ok

# ── Historial extendido (2 días / 7 días) a resolución reducida ──
# Se usan para los periodos largos de la "máquina del tiempo": no se
# guarda cada ejecución (cada 5 min), solo cuando ha pasado el
# intervalo indicado, para no disparar el tamaño del archivo.
def hist_extendido(nuevos, ahora, ruta, horas_retencion, minutos_intervalo):
    h   = leer(ruta, [])
    lim = ahora - timedelta(hours=horas_retencion)
    ok  = []
    for e in h:
        try:
            t = datetime.fromisoformat(e['timestamp'])
            if t.tzinfo is None: t = t.replace(tzinfo=ahora.tzinfo)
            if t > lim: ok.append(e)
        except: pass

    debe_anadir = True
    if ok:
        try:
            t_ult = datetime.fromisoformat(ok[-1]['timestamp'])
            if t_ult.tzinfo is None: t_ult = t_ult.replace(tzinfo=ahora.tzinfo)
            debe_anadir = (ahora - t_ult) >= timedelta(minutes=minutos_intervalo)
        except: pass

    if debe_anadir:
        ok.append({'timestamp': ahora.isoformat(),
                   'stations': [_recortar_estacion(e) for e in nuevos]})

    guardar(ruta, ok)
    return ok

# ── Archivado de radar (tiles propios) ─────────────────────────
# RainViewer solo da ~2h de histórico público. Para poder ver radar de
# días anteriores en la máquina del tiempo, archivamos aquí mismo los
# tiles PNG de cada frame nuevo (uno cada ~10 min, que es lo que tarda
# RainViewer en publicar un frame nuevo) y los servimos desde el propio
# repo. Retención acotada para no disparar el tamaño del repositorio.
RADAR_ZOOM = 7          # mismo zoom nativo que ya usa la capa en vivo
RADAR_RETENCION_H = 48  # hasta 48h de histórico propio
RADAR_LAT_MIN, RADAR_LAT_MAX = 36.7, 38.8   # bounding box de la zona cubierta
RADAR_LON_MIN, RADAR_LON_MAX = -3.0, -0.3

def _tile_xy(lat, lon, z):
    lat_rad = math.radians(lat)
    n = 2.0 ** z
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return x, y

def archivar_radar(ahora):
    manifest = leer(F_RADAR_MANIFEST, [])

    try:
        req = urllib.request.Request(
            "https://api.rainviewer.com/public/weather-maps.json",
            headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=ctx, timeout=8) as r:
            d = json.loads(r.read().decode('utf-8'))
        host = d['host']
        ultimo = d['radar']['past'][-1]
        epoch, path = ultimo['time'], ultimo['path']
    except Exception as e:
        print(f"  ⚠ Radar (archivado): no se pudo consultar RainViewer: {e}")
        host = None

    if host and (not manifest or manifest[-1].get('epoch') != epoch):
        x0, y1 = _tile_xy(RADAR_LAT_MIN, RADAR_LON_MIN, RADAR_ZOOM)
        x1, y0 = _tile_xy(RADAR_LAT_MAX, RADAR_LON_MAX, RADAR_ZOOM)
        carpeta = os.path.join(DIR_RADAR, str(epoch))
        os.makedirs(carpeta, exist_ok=True)
        tiles_ok = []
        for x in range(min(x0, x1), max(x0, x1) + 1):
            for y in range(min(y0, y1), max(y0, y1) + 1):
                url = f"{host}{path}/256/{RADAR_ZOOM}/{x}/{y}/2/1_1.png"
                try:
                    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                    with urllib.request.urlopen(req, context=ctx, timeout=8) as r:
                        data = r.read()
                    with open(os.path.join(carpeta, f"{x}_{y}.png"), 'wb') as f:
                        f.write(data)
                    tiles_ok.append([x, y])
                except Exception as e:
                    print(f"  ⚠ Radar tile {x},{y}: {e}")
        if tiles_ok:
            manifest.append({'epoch': epoch, 'z': RADAR_ZOOM, 'tiles': tiles_ok})
            print(f"  ✅ Radar archivado: frame {epoch} ({len(tiles_ok)} tiles)")
        else:
            shutil.rmtree(carpeta, ignore_errors=True)
    elif host:
        print("  ℹ Radar: frame ya archivado, nada nuevo")

    # Podar frames fuera de la ventana de retención
    limite = ahora.timestamp() - RADAR_RETENCION_H * 3600
    conservar = [m for m in manifest if m.get('epoch', 0) >= limite]
    for m in manifest:
        if m not in conservar:
            shutil.rmtree(os.path.join(DIR_RADAR, str(m.get('epoch'))), ignore_errors=True)
    guardar(F_RADAR_MANIFEST, conservar)
    if len(conservar) != len(manifest):
        print(f"  🗑 Radar: {len(manifest)-len(conservar)} frames antiguos podados")

# ── Historial agrícola 14 días ────────────────────────────────
def hist_agri(nuevos, ahora, minutos=15):
    h   = leer(F_AGRI, {})
    hoy = ahora.strftime('%Y-%m-%d')
    if hoy not in h: h[hoy] = {}

    for est in nuevos:
        if not est or 'stationID' not in est: continue
        sid = est['stationID']
        t   = est.get('metric', {}).get('temp')
        p   = est.get('metric', {}).get('precipTotal')
        hm  = est.get('humidity')

        if sid not in h[hoy]:
            h[hoy][sid] = {
                'tempMax':  t if t is not None else -99,
                'tempMin':  t if t is not None else  99,
                'precipTotal': p if p is not None else 0.0,
                'humedadAltaMinutos': 0,
                'lat': est.get('lat', 0),
                'lon': est.get('lon', 0)}
        else:
            d = h[hoy][sid]
            if t is not None:
                if t > d.get('tempMax', -99): d['tempMax'] = t
                if t < d.get('tempMin',  99): d['tempMin'] = t
            if p is not None and p > d.get('precipTotal', 0):
                d['precipTotal'] = p
        if hm is not None and hm >= 85:
            h[hoy][sid]['humedadAltaMinutos'] = h[hoy][sid].get('humedadAltaMinutos', 0) + minutos

    for d in sorted(h.keys())[:-14]: del h[d]
    guardar(F_AGRI, h)
    print(f"  ✅ Historial agrícola: {len(h)} días acumulados")
    return h

# ── Riesgo Oídio / Mildiu ─────────────────────────────────────
# Oídio:  Modelo Gubler-Thomas (UC Davis)
# Mildiu: Regla 10-10-10 + EPI
# Si faltan datos propios → usa WU de estaciones vecinas dentro del historial
# ── Tabla DSV diario Gubler-Thomas (UC Davis 1982) ───────────────────────────
# DSV = Disease Severity Value
# Filas: rangos Tmed | Columnas: horas de humectación foliar (HR≥85%)
# Ref: Gubler & Thomas, Plant Disease 66:4 (1982)
DSV_TABLE = {
    (15, 19): {(0,6):1,  (7,12):2,  (13,18):3,  (19,24):4},
    (19, 22): {(0,6):2,  (7,12):3,  (13,18):4,  (19,24):5},
    (22, 26): {(0,6):3,  (7,12):4,  (13,18):5,  (19,24):6},
    (26, 40): {(0,6):2,  (7,12):3,  (13,18):4,  (19,24):5},
}

def dsv_dia(tmed, horas_hum):
    """Calcula DSV para un día según Gubler-Thomas."""
    if tmed is None or tmed < 15: return 0
    for (tmin_r, tmax_r), cols in DSV_TABLE.items():
        if tmin_r <= tmed < tmax_r:
            for (h_min, h_max), val in cols.items():
                if h_min <= horas_hum <= h_max:
                    return val
            return list(cols.values())[-1]
    return 0

def periodo_incubacion_mildiu(tmed):
    """Días de incubación de Plasmopara viticola según temperatura."""
    if tmed is None or tmed < 12: return None   # no hay desarrollo
    if tmed < 15: return 21
    if tmed < 18: return 15
    if tmed < 21: return 10
    if tmed < 25: return 7
    if tmed < 30: return 6
    return None  # >30°C inhibe

def calcular_riesgo(hwu, actuales_list):
    act  = {e['stationID']: e for e in actuales_list if e and 'stationID' in e}
    dias = sorted(hwu.keys())
    res  = {}

    # Cargar historial DSV acumulado (temporada)
    dsv_hist = leer(F_DSV, {})
    hoy_str  = dias[-1] if dias else ''

    # Mapa de posiciones
    pos = {}
    for fecha in dias:
        for sid, dd in hwu[fecha].items():
            if sid not in pos and dd.get('lat'):
                pos[sid] = (dd['lat'], dd['lon'])
    for sid, est in act.items():
        if sid not in pos and est.get('lat'):
            pos[sid] = (est['lat'], est['lon'])

    for sid, est in act.items():
        ta_inst = est.get('metric', {}).get('temp')
        ha      = est.get('humidity')
        la      = est.get('lat', pos.get(sid, (37.77, 0))[0])
        lo      = est.get('lon', pos.get(sid, (0, -1.5))[1])
        if ta_inst is None: continue

        # Temperatura media del día actual
        hoy = sorted(hwu.keys())[-1] if hwu else None
        tmed_hoy = None
        if hoy and hwu.get(hoy, {}).get(sid):
            dd = hwu[hoy][sid]
            if dd.get('tempMax') is not None and dd.get('tempMin') is not None:
                tmed_hoy = round((dd['tempMax'] + dd['tempMin']) / 2, 1)
        ta = tmed_hoy if tmed_hoy is not None else ta_inst

        # 1. Historial WU propio
        filas = []
        for f in (dias[-14:] if len(dias) >= 14 else dias):
            dd = hwu[f].get(sid)
            if dd:
                filas.append({
                    'fecha':   f,
                    'tmax':    dd.get('tempMax'),
                    'tmin':    dd.get('tempMin'),
                    'prec':    dd.get('precipTotal', 0),
                    'hum_min': dd.get('humedadAltaMinutos', 0),
                    'src':     'propio'})

        # 2. Vecinos WU si faltan días
        if len(filas) < MIN_DIAS and la and lo:
            fechas_ok = {f['fecha'] for f in filas}
            vecinos   = sorted(
                [(s, dist(la, lo, p[0], p[1])) for s, p in pos.items() if s != sid],
                key=lambda x: x[1])
            for vsid, vd in vecinos[:5]:
                if vd > 0.5: break
                for f in (dias[-14:] if len(dias) >= 14 else dias):
                    if f in fechas_ok: continue
                    dd = hwu[f].get(vsid)
                    if dd:
                        filas.append({
                            'fecha':   f,
                            'tmax':    dd.get('tempMax'),
                            'tmin':    dd.get('tempMin'),
                            'prec':    dd.get('precipTotal', 0),
                            'hum_min': dd.get('humedadAltaMinutos', 0),
                            'src':     f'vecino:{vsid}'})
                        fechas_ok.add(f)
                if len(filas) >= MIN_DIAS: break

        filas.sort(key=lambda x: x['fecha'])
        filas = filas[-14:]
        nd    = len(filas)

        n_prop = sum(1 for f in filas if f['src'] == 'propio')
        n_vec  = sum(1 for f in filas if f['src'].startswith('vecino'))
        partes = []
        if n_prop: partes.append(f"WU propio {n_prop}d")
        if n_vec:  partes.append(f"WU vecinos {n_vec}d")
        flbl = " + ".join(partes) if partes else "Sin datos"
        ok   = nd >= MIN_DIAS

        # Métricas base
        p10   = sum(f['prec'] or 0 for f in filas[-10:])
        tminm = min((f['tmin'] for f in filas if f['tmin'] is not None), default=99)
        h85   = sum(f.get('hum_min', 0) for f in filas[-7:]) / 60.0

        # ── OÍDIO: Modelo Gubler-Thomas completo con DSV ─────
        no, do = 0, []
        dsv_temporada = 0
        dsv_7d        = 0
        dsv_hoy_val   = 0

        if not ok:
            no = -1
            falt = MIN_DIAS - nd
            do.append(f"⚠ {nd} días disponibles — faltan {falt} día{'s' if falt>1 else ''} más")
        else:
            # Calcular DSV de cada día del historial
            dsv_dias = []
            for f in filas:
                tm = f['tmax']
                tn = f['tmin']
                tmed_f = round((tm + tn) / 2, 1) if tm is not None and tn is not None else None
                horas_f = f.get('hum_min', 0) / 60.0
                # Inhibición por lluvia: >2.5mm lava esporas → DSV=0 ese día
                prec_f = f.get('prec', 0) or 0
                d = 0 if prec_f > 2.5 else dsv_dia(tmed_f, horas_f)
                dsv_dias.append({'fecha': f['fecha'], 'dsv': d, 'tmed': tmed_f})

            # DSV acumulado en temporada (desde inicio de marzo)
            dsv_prev = dsv_hist.get(sid, {}).get('dsv_acumulado', 0)
            # Sumar DSV de días nuevos no contabilizados antes
            fechas_contadas = set(dsv_hist.get(sid, {}).get('fechas', []))
            nuevos_dsv = sum(d['dsv'] for d in dsv_dias if d['fecha'] not in fechas_contadas)
            dsv_temporada = dsv_prev + nuevos_dsv

            # Actualizar historial DSV
            if sid not in dsv_hist:
                dsv_hist[sid] = {'dsv_acumulado': 0, 'fechas': []}
            dsv_hist[sid]['dsv_acumulado'] = dsv_temporada
            dsv_hist[sid]['fechas'] = list(set(
                dsv_hist[sid].get('fechas', []) + [d['fecha'] for d in dsv_dias]))

            dsv_7d      = sum(d['dsv'] for d in dsv_dias[-7:])
            dsv_hoy_val = dsv_dias[-1]['dsv'] if dsv_dias else 0

            # Nivel de riesgo según DSV acumulado (temporada)
            # Umbrales estándar Gubler-Thomas para viticultura española
            if dsv_temporada < 20:
                no = 0
                do.append(f"DSV temporada={dsv_temporada} (umbral tratamiento: 20)")
            elif dsv_temporada < 40:
                no = 1
                do.append(f"DSV temporada={dsv_temporada} ⚠ Zona de vigilancia (20-40)")
            elif dsv_temporada < 60:
                no = 2
                do.append(f"DSV temporada={dsv_temporada} 🔶 Tratar pronto (40-60)")
            else:
                no = 3
                do.append(f"DSV temporada={dsv_temporada} 🔴 Tratamiento urgente (>60)")

            do.append(f"DSV últimos 7d={dsv_7d} | DSV hoy={dsv_hoy_val}")
            do.append(f"Tmed hoy={ta:.1f}°C | HR alta={h85:.1f}h (7d)")
            if dsv_hoy_val == 0 and ta and ta >= 15:
                do.append("Lluvia >2.5mm lavó esporas hoy")

        # Guardar DSV actualizado
        guardar(F_DSV, dsv_hist)

        # ── MILDIU: 10-10-10 + período de incubación EPI ────
        nm, dm = 0, []
        incubacion_dias = None
        fecha_sintomas  = None

        if not ok:
            nm = -1
            falt = MIN_DIAS - nd
            dm.append(f"⚠ {nd} días disponibles — faltan {falt} día{'s' if falt>1 else ''} más")
        else:
            ct = tminm > 10 or ta > 10
            cl = p10 >= 10
            cd = nd >= MIN_DIAS

            if ct: dm.append(f"✓ Tmin>10°C")
            if cl: dm.append(f"✓ Lluvia 10d={p10:.1f}mm")
            if cd: dm.append(f"✓ {nd} días historial")

            nc = sum([ct, cl, cd])
            if nc == 3:
                # Condiciones de infección cumplidas
                nm = 2
                # Temperatura óptima + humedad alta → riesgo alto
                if 18 <= ta <= 24 and (ha or 0) >= 85:
                    nm = 3
                    dm.append(f"Tmed={ta:.1f}°C + HR={ha}% — condiciones óptimas infección")
                elif 15 <= ta <= 30:
                    dm.append(f"Tmed={ta:.1f}°C — condiciones favorables")
                if ta > 30:
                    nm = max(1, nm - 1)
                    dm.append("T>30°C — reduce esporulación")

                # Calcular período de incubación
                incubacion_dias = periodo_incubacion_mildiu(ta)
                if incubacion_dias:
                    from datetime import datetime, timedelta
                    fecha_inf = datetime.strptime(filas[-1]['fecha'], '%Y-%m-%d')
                    fecha_sint = fecha_inf + timedelta(days=incubacion_dias)
                    fecha_sintomas = fecha_sint.strftime('%d/%m/%Y')
                    dm.append(f"⏱ Período incubación: {incubacion_dias} días")
                    dm.append(f"📅 Síntomas esperados: {fecha_sintomas}")
            elif nc == 2:
                nm = 1
                dm.append("Condiciones parcialmente cumplidas")

            if not cl:
                dm.append(f"Lluvia 10d={p10:.1f}mm (necesita ≥10mm)")
            if not ct:
                dm.append("Temperatura mínima aún baja")

        res[sid] = {
            'lat': la, 'lon': lo,
            'oidio':  no, 'mildiu': nm,
            'datos_ok': ok, 'dias_disponibles': nd, 'fuente_datos': flbl,
            'dsv_temporada':  dsv_temporada,
            'dsv_7d':         dsv_7d,
            'dsv_hoy':        dsv_hoy_val,
            'incubacion_dias': incubacion_dias,
            'fecha_sintomas':  fecha_sintomas,
            'detalles': {
                'oidio':  do, 'mildiu': dm,
                'temp_actual':       ta,
                'hum_actual':        ha,
                'precip_10dias':     round(p10, 1),
                'dias_tmed_sobre15': sum(1 for f in filas if f['tmax'] is not None and f['tmin'] is not None and (f['tmax']+f['tmin'])/2 >= 15),
                'horas_hum_alta_7d': round(h85, 1)}}
    return res

# ── Guardar snapshot de riesgo diario ────────────────────────
def guardar_riesgo_dia(riesgo_data, ahora):
    """
    Guarda un snapshot del riesgo calculado hoy en historial_riesgo.json
    Formato: {fecha: {stationID: {oidio, mildiu, dsv, lat, lon}}}
    """
    hist = leer(F_RIESGO, {})
    fecha_hoy = ahora.strftime('%Y-%m-%d')

    snapshot = {}
    for sid, r in riesgo_data.items():
        snapshot[sid] = {
            'oidio':          r.get('oidio', -1),
            'mildiu':         r.get('mildiu', -1),
            'dsv_temporada':  r.get('dsv_temporada', 0),
            'dsv_7d':         r.get('dsv_7d', 0),
            'lat':            r.get('lat'),
            'lon':            r.get('lon'),
            'datos_ok':       r.get('datos_ok', False),
            'fuente_datos':   r.get('fuente_datos', ''),
        }

    hist[fecha_hoy] = snapshot

    # Mantener solo 90 días (temporada completa)
    for d in sorted(hist.keys())[:-90]:
        del hist[d]

    guardar(F_RIESGO, hist)
    print(f"  ✅ Riesgo diario guardado: {len(hist)} días en {F_RIESGO}")
    return hist

# ── Recalcular riesgo para días anteriores ────────────────────
def recalcular_riesgo_dias_anteriores(hwu, dsv_hist_orig, actuales_list, ahora, n_dias=3):
    """
    Recalcula el riesgo para los N días anteriores usando el historial agrícola.
    Útil para rellenar historial_riesgo.json con datos pasados.
    """
    from datetime import timedelta
    hist_riesgo = leer(F_RIESGO, {})
    act = {e['stationID']: e for e in actuales_list if e and 'stationID' in e}
    dias = sorted(hwu.keys())

    for dias_atras in range(n_dias, 0, -1):
        fecha_dt  = ahora - timedelta(days=dias_atras)
        fecha_str = fecha_dt.strftime('%Y-%m-%d')

        if fecha_str in hist_riesgo:
            print(f"  ℹ {fecha_str}: ya existe, saltando")
            continue

        if fecha_str not in hwu:
            print(f"  ⚠ {fecha_str}: sin datos en historial agrícola")
            continue

        print(f"  🔄 Recalculando {fecha_str}...")

        # Construir datos "actuales" simulados para ese día
        actuales_dia = []
        for sid, dd in hwu[fecha_str].items():
            if not dd.get('lat'): continue
            # Simular observación con los datos del día
            tmax = dd.get('tempMax')
            tmin = dd.get('tempMin')
            tmed = round((tmax+tmin)/2, 1) if tmax is not None and tmin is not None else None
            actuales_dia.append({
                'stationID': sid,
                'lat': dd.get('lat', 0),
                'lon': dd.get('lon', 0),
                'metric': {
                    'temp': tmed,
                    'precipTotal': dd.get('precipTotal', 0),
                    'windSpeed': 0, 'windGust': 0
                },
                'humidity': max(0, 85 - dd.get('humedadAltaMinutos', 0) // 60 * 5)
            })

        if not actuales_dia:
            continue

        # Usar solo historial hasta ese día para el cálculo
        dias_hasta = [d for d in dias if d <= fecha_str]
        hwu_hasta  = {d: hwu[d] for d in dias_hasta}

        # Recalcular riesgo con snapshot de ese día
        r_dia = calcular_riesgo(hwu_hasta, actuales_dia)

        snapshot = {}
        for sid, r in r_dia.items():
            snapshot[sid] = {
                'oidio':         r.get('oidio', -1),
                'mildiu':        r.get('mildiu', -1),
                'dsv_temporada': r.get('dsv_temporada', 0),
                'dsv_7d':        r.get('dsv_7d', 0),
                'lat':           r.get('lat'),
                'lon':           r.get('lon'),
                'datos_ok':      r.get('datos_ok', False),
                'fuente_datos':  r.get('fuente_datos', ''),
            }
        hist_riesgo[fecha_str] = snapshot
        print(f"    ✅ {fecha_str}: {len(snapshot)} estaciones")

    guardar(F_RIESGO, hist_riesgo)
    print(f"  ✅ historial_riesgo.json: {len(hist_riesgo)} días")
    return hist_riesgo

# ── Git push ──────────────────────────────────────────────────
def git_push(ahora):
    print("\n☁️  Subiendo a GitHub...")
    try:
        fecha_str = ahora.strftime("%Y-%m-%d %H:%M")
        for cmd in [
            ["git","-C",REPO_DIR,"config","user.email","joseroquel@lopezyandreo.com"],
            ["git","-C",REPO_DIR,"config","user.name","Meteo Guadalentin Bot"],
            ["git","-C",REPO_DIR,"add","history_24h.json","history_2d.json","history_7d.json",
             "historial_agricola.json","radar_tiles","public/index.html"],
            ["git","-C",REPO_DIR,"commit","-m",f"Auto {fecha_str}"],
            ["git","-C",REPO_DIR,"push"],
        ]:
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                if "nothing to commit" in r.stdout+r.stderr:
                    print("  ℹ Sin cambios nuevos")
                    return
                print(f"  ⚠ {cmd[2]}: {r.stderr.strip()[:120]}")
                return
        print("  ✅ Datos subidos a GitHub")
        print(f"  🌐 https://jorloan.github.io/meteo-guadalentin/")
    except Exception as e:
        print(f"  ⚠ Git error: {e}")

# ── HTML ──────────────────────────────────────────────────────
NOMBRES = {
    "ITOTAN8":"Mirador - Lebor Alto","ITOTAN2":"METEO UNDERWORLD",
    "ITOTAN16":"Mortí Bajo","ITOTAN5":"Tierno Galván",
    "ITOTAN33":"Huerto Hostench","ITOTAN43":"Casa Totana",
    "ITOTAN31":"CAMPING Lebor","ITOTAN42":"Secanos",
    "ITOTAN9":"LA CANAL","ITOTAN41":"Ecowitt WN1981",
    "ITOTAN10":"WS Rancho","ITOTAN17":"La Barquilla",
    "IALHAM13":"Alhama Norte","IALHAM23":"Alhama Oeste",
    "IALHAM31":"Alhama Sur","IALHAM36":"Alhama Este",
    "IALHAM4":"Alhama Centro","IALHAM54":"Alhama Alt",
    "IALHAM64":"Alhama de Murcia","IALHAM81":"Alhama Baja",
    "IALHAM88":"Alhama Sierra","IALHAM90":"Alhama Río",
    "IALHAM92":"Las Canales",
    "ILORCA22":"Lorca Sur","IMAZAR7":"Puerto Mazarrón",
    "IGUILA10":"Club Náutico de Águilas",
    "IPULP6":"Meteobaraza Pulpí",
    "IVERA31":"Thalassa",
    "ICARTA267":"Palmasol",
    "IJUMIL46":"Fuente de las Perdices",
    "IJUMILLA5":"Casa Navarros",
    "IYECLA52":"Senda de los Jinetes - La Decarada",
    "IABARN30":"Abarán - Áureo Natura",
    "IVILLA1263":"Israel",
    "ISANTO462":"RyA",
    "IMURCI180":"Colegio Luis Vives",
}

WEBCAMS = [
    # ── A-7 Autovía del Mediterráneo (coords exactas DGT DATEX2) ─────
    {"id":"dgt_a7_librilla_s",  "nombre":"A-7 Librilla Sur",           "lat":37.875866,"lon":-1.3689584,
     "url":"https://etraffic.dgt.es/camarasEtraffic/1234.jpg",
     "tipo":"DGT","descripcion":"A-7 km 595 · dirección Murcia"},
    {"id":"dgt_a7_alhama_n",   "nombre":"A-7 Alhama Norte",            "lat":37.859783,"lon":-1.3986695,
     "url":"https://etraffic.dgt.es/camarasEtraffic/1239.jpg",
     "tipo":"DGT","descripcion":"A-7 km 598 · acceso norte Alhama"},
    {"id":"dgt_a7_ciruelo",    "nombre":"A-7 El Ciruelo (Alhama)",     "lat":37.827564,"lon":-1.4044806,
     "url":"https://etraffic.dgt.es/camarasEtraffic/1238.jpg",
     "tipo":"DGT","descripcion":"A-7 km 601,7 · Alhama de Murcia"},
    {"id":"dgt_a7_totana",     "nombre":"A-7 Totana",                  "lat":37.75156, "lon":-1.4734666,
     "url":"https://etraffic.dgt.es/camarasEtraffic/1237.jpg",
     "tipo":"DGT","descripcion":"A-7 km 611,95 · Totana"},
    {"id":"dgt_a7_sanjulian",  "nombre":"A-7 Ventas de San Julián",    "lat":37.696415,"lon":-1.6577473,
     "url":"https://etraffic.dgt.es/camarasEtraffic/1236.jpg",
     "tipo":"DGT","descripcion":"A-7 km 628,8"},
    {"id":"dgt_a7_torrecilla", "nombre":"A-7 Torrecilla",              "lat":37.68845, "lon":-1.7109778,
     "url":"https://etraffic.dgt.es/camarasEtraffic/1235.jpg",
     "tipo":"DGT","descripcion":"A-7 km 634,15"},
    {"id":"dgt_a7_itv_lorca",  "nombre":"A-7 ITV Centro Lorca",        "lat":37.662685,"lon":-1.7135389,
     "url":"https://etraffic.dgt.es/camarasEtraffic/1240.jpg",
     "tipo":"DGT","descripcion":"A-7 km 637 · Lorca"},
    {"id":"dgt_a7_lorca_sur",  "nombre":"A-7 Lorca Sur (Méndez)",      "lat":37.64078, "lon":-1.7399278,
     "url":"https://etraffic.dgt.es/camarasEtraffic/1241.jpg",
     "tipo":"DGT","descripcion":"A-7 km 640,5 · Hospital Méndez Lorca"},
    {"id":"dgt_a7_saprelorca", "nombre":"A-7 Polígono Saprelorca",     "lat":37.619812,"lon":-1.7493556,
     "url":"https://etraffic.dgt.es/camarasEtraffic/1242.jpg",
     "tipo":"DGT","descripcion":"A-7 km 642,85 · Repsol Lorca"},
    {"id":"dgt_a7_plumb_n",    "nombre":"A-7 Puerto Lumbreras Norte",  "lat":37.575436,"lon":-1.7984195,
     "url":"https://etraffic.dgt.es/camarasEtraffic/1243.jpg",
     "tipo":"DGT","descripcion":"A-7 km 649,5"},
    {"id":"dgt_a7_plumb_c",    "nombre":"A-7 Puerto Lumbreras Centro", "lat":37.566555,"lon":-1.81915,
     "url":"https://etraffic.dgt.es/camarasEtraffic/1244.jpg",
     "tipo":"DGT","descripcion":"A-7 km 651,7"},
    # ── A-91 ─────────────────────────────────────────────────────────
    {"id":"dgt_a91_henares",   "nombre":"A-91 Henares (Pto. Lumbreras)","lat":37.611923,"lon":-1.9163889,
     "url":"https://etraffic.dgt.es/camarasEtraffic/1247.jpg",
     "tipo":"DGT","descripcion":"A-91 km 6,45 · enlace A-7/A-91"},
    # ── Ayuntamiento de Totana ────────────────────────────────────────
    {"id":"totana_plaza_const", "nombre":"Totana · Plaza Constitución",  "lat":37.7697643,"lon":-1.5027122,
     "url":"https://www.totana.es/webcam/PLAZA_CONSTITUCION.jpg",
     "tipo":"Ayuntamiento","descripcion":"Plaza de la Constitución · Totana"},
    {"id":"totana_balsa",       "nombre":"Totana · Plaza Balsa Vieja",   "lat":37.7700940,"lon":-1.5022171,
     "url":"https://www.totana.es/webcam/PLAZA_BALSA.jpg",
     "tipo":"Ayuntamiento","descripcion":"Plaza Balsa Vieja · Totana"},
    # ── Webcams públicas (webcamgalore.com) ───────────────────────────
    {"id":"aguilas_puerto",    "nombre":"Águilas · Puerto",             "lat":37.4040191,"lon":-1.5781299,
     "url":"https://images.webcamgalore.com/28892-current-webcam-Aguilas.jpg",
     "tipo":"Pública","descripcion":"Puerto de Águilas · vista panorámica"},
    {"id":"mula_plaza",        "nombre":"Mula · Plaza Ayuntamiento",    "lat":38.0416059,"lon":-1.4910892,
     "url":"https://images.webcamgalore.com/12619-current-webcam-Mula.jpg",
     "tipo":"Pública","descripcion":"Plaza del Ayuntamiento · Mula"},
    {"id":"bullas_plaza",      "nombre":"Bullas · Plaza de España",     "lat":38.0495514,"lon":-1.6708465,
     "url":"https://images.webcamgalore.com/11960-current-webcam-Bullas.jpg",
     "tipo":"Pública","descripcion":"Plaza de España · Bullas"},
]

def generar_html(historial, riesgo_data, ahora, dias_acum):
    aviso_dias = ""
    if dias_acum < MIN_DIAS:
        falt = MIN_DIAS - dias_acum
        aviso_dias = (f"⏳ Acumulando historial: {dias_acum}/{MIN_DIAS} días. "
                      f"Faltan {falt} día{'s' if falt>1 else ''} para activar el cálculo de riesgo.")

    # historyData y riesgoHistData ya NO se embeben completos: solo se
    # incluye una "semilla" (el último snapshot) para que el mapa renderice
    # de inmediato con las condiciones actuales; el histórico completo se
    # descarga aparte (fetch) justo después de cargar la página. Sin esto,
    # con el cron ahora disparando cada 5 min de verdad, history_24h.json
    # llega a ~25MB/día y se embebía entero dentro del HTML.
    js = ("var NOMBRES="+json.dumps(NOMBRES, ensure_ascii=False)+";\n"
         +"var WEBCAMS_DATA="+json.dumps(WEBCAMS, ensure_ascii=False)+";\n"
         +"var historyData="+json.dumps(historial[-1:], ensure_ascii=False)+";\n"
         +"var riesgoData="+json.dumps(riesgo_data, ensure_ascii=False)+";\n"
         +"var riesgoHistData={};\n"
         +"var AVISO_DIAS="+json.dumps(aviso_dias)+";\n"
         + JS_LOGICA)

    html = HTML_BASE.replace('__JS__', js)
    ruta_pub  = os.path.join(DIR_PUB,   'index.html')
    ruta_repo = os.path.join(REPO_DIR,  'index.html')
    for ruta in [ruta_pub, ruta_repo]:
        with open(ruta, 'w', encoding='utf-8') as f:
            f.write(html)
    print(f"  ✅ HTML generado ({dias_acum} días historial)")
    return ruta_pub

JS_LOGICA = r"""
var RC=['#27ae60','#f39c12','#e67e22','#c0392b'];
var RL=['Sin riesgo','Riesgo bajo','Riesgo medio','Riesgo ALTO'];
var CI=historyData.length-1;
var PT=null;
window.HO=0.35;

// ── Mapa base ──────────────────────────────────────────────
var terreno=L.tileLayer('http://{s}.google.com/vt/lyrs=p&x={x}&y={y}&z={z}',
  {maxZoom:20,subdomains:['mt0','mt1','mt2','mt3'],attribution:'© Google',className:'gmap'});
// Fondo claro: CARTO pasó a exigir clave de API y estampa "API KEY
// REQUIRED" sobre sus tiles, así que el gris claro sale de Esri (World
// Light Gray, sin clave). vigilarFondo() cambia a OSM si Esri fallara,
// para no quedarnos nunca con el mapa en blanco.
var ESRI_GRIS='https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}';
var ESRI_GRIS_ETIQ='https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}';

// Capas de Google servidas por https (las de más abajo siguen en http por
// compatibilidad histórica; aquí no, para no mezclar contenido inseguro).
// lyrs=s satélite, lyrs=t relieve sin rótulos, lyrs=h solo carreteras y
// rótulos sobre fondo transparente — esta última es la que se superpone
// por encima del sombreado de lluvia.
var GOOGLE_SUB=['mt0','mt1','mt2','mt3'];
var GOOGLE_SAT='https://{s}.google.com/vt/lyrs=s&x={x}&y={y}&z={z}';
var GOOGLE_RELIEVE='https://{s}.google.com/vt/lyrs=t&x={x}&y={y}&z={z}';
var GOOGLE_CALLES='https://{s}.google.com/vt/lyrs=h&x={x}&y={y}&z={z}';

// Si el fondo elegido deja de responder, se cae a OSM en vez de quedarse
// el mapa en blanco. alCaer() permite al llamante seguir la pista de la
// capa nueva, para poder retirarla si luego se cambia de fondo.
function vigilarFondo(mapa,capas,alCaer){
  var fallos=0,cambiado=false;
  capas[0].on('tileerror',function(){
    if(cambiado||++fallos<4) return;   // un tile suelto no basta para descartar la capa
    cambiado=true;
    capas.forEach(function(c){ if(c&&mapa.hasLayer(c)) mapa.removeLayer(c); });
    var osmR=L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
      {attribution:'© OSM',className:'mapa-atenuado'}).addTo(mapa);
    if(alCaer) alCaer(osmR);
  });
}

var claro=L.layerGroup([
  L.tileLayer(ESRI_GRIS,{attribution:'© Esri',maxNativeZoom:16,maxZoom:20}),
  L.tileLayer(ESRI_GRIS_ETIQ,{maxNativeZoom:16,maxZoom:20})
]);
var osm=L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'© OSM'});
var sat=L.tileLayer('http://{s}.google.com/vt/lyrs=s,h&x={x}&y={y}&z={z}',
  {maxZoom:20,subdomains:['mt0','mt1','mt2','mt3'],attribution:'© Google'});

var map=L.map('map',{center:[37.76,-1.53],zoom:10,layers:[terreno],zoomControl:false});
L.control.zoom({position:'bottomleft'}).addTo(map);
map.createPane('hp');
map.getPane('hp').style.zIndex=390;
map.getPane('hp').style.filter='blur(14px)';

// ── Radar de lluvia ────────────────────────────────────────────
// Dos fuentes:
//  1) RainViewer en vivo: todos los frames disponibles (~2h de histórico
//     público), para el momento actual y el pasado reciente.
//  2) Archivo propio (radar_tiles/manifest.json): tiles que vamos
//     guardando nosotros mismos en cada ejecución, para poder ver radar
//     de momentos más antiguos que esas ~2h (hasta ~48h).
// Si el momento pedido no está en ninguna de las dos, se avisa en vez
// de dejar "congelado" un frame que no corresponde a ese momento.
var RADAR_ZOOM=7;
var rLG=L.layerGroup();
var radarFrames=[];   // [{time:epochSeg, path:'...'}], orden cronológico (RainViewer)
var radarHost='';
var radarArchivo=[];  // [{epoch,z,tiles:[[x,y],...]}], orden cronológico (propio)
var radarArchivoCargado=false;
var radarModoActual=null;   // 'vivo' | 'archivo' | null
var radarClaveActual=null;  // frame ya mostrado, para no recrear la capa si no cambia

function cargarManifiestoRadar(cb){
  if(radarArchivoCargado){ cb(); return; }
  fetch('radar_tiles/manifest.json?v='+Date.now())
    .then(function(r){return r.json();})
    .then(function(datos){ radarArchivo=(datos&&datos.length)?datos:[]; radarArchivoCargado=true; cb(); })
    .catch(function(){ radarArchivo=[]; radarArchivoCargado=true; cb(); });
}

function mostrarCapaRadar(url, modo, clave, chk){
  if(radarModoActual===modo && radarClaveActual===clave){
    if(chk && chk.checked && !map.hasLayer(rLG)) rLG.addTo(map);
    return;
  }
  radarModoActual=modo; radarClaveActual=clave;
  rLG.clearLayers();
  rLG.addLayer(L.tileLayer(url,{opacity:0.7,zIndex:400,maxNativeZoom:RADAR_ZOOM,maxZoom:18}));
  if(chk && chk.checked && !map.hasLayer(rLG)) rLG.addTo(map);
}

function ocultarCapaRadar(chk){
  var aviso=document.getElementById('radar-fuera-rango');
  if(aviso) aviso.style.display='inline';
  if(chk && chk.checked && map.hasLayer(rLG)) rLG.remove();
  radarModoActual=null; radarClaveActual=null;
}

function actualizarFrameRadar(epochSeg){
  var chk=document.getElementById('radar-chk');
  var aviso=document.getElementById('radar-fuera-rango');
  if(!radarFrames.length) return;

  var MARGEN=1200; // 20 min de tolerancia (desfase entre ciclos propios y de RainViewer)
  var minT=radarFrames[0].time-MARGEN, maxT=radarFrames[radarFrames.length-1].time+MARGEN;

  if(epochSeg>=minT && epochSeg<=maxT){
    if(aviso) aviso.style.display='none';
    var mejor=0, mejorDif=Infinity;
    for(var i=0;i<radarFrames.length;i++){
      var dif=Math.abs(radarFrames[i].time-epochSeg);
      if(dif<mejorDif){ mejorDif=dif; mejor=i; }
    }
    var url=radarHost+radarFrames[mejor].path+'/256/{z}/{x}/{y}/2/1_1.png';
    mostrarCapaRadar(url,'vivo',mejor,chk);
    return;
  }

  // Fuera de la ventana en vivo de RainViewer: buscar en el archivo propio.
  cargarManifiestoRadar(function(){
    var mejorA=null, mejorDifA=Infinity;
    for(var j=0;j<radarArchivo.length;j++){
      var difA=Math.abs(radarArchivo[j].epoch-epochSeg);
      if(difA<mejorDifA){ mejorDifA=difA; mejorA=radarArchivo[j]; }
    }
    if(mejorA && mejorDifA<=900){ // 15 min de tolerancia (nuestro propio ciclo es cada ~10 min)
      if(aviso) aviso.style.display='none';
      var urlA='radar_tiles/'+mejorA.epoch+'/{x}_{y}.png';
      mostrarCapaRadar(urlA,'archivo',mejorA.epoch,chk);
    } else {
      ocultarCapaRadar(chk);
    }
  });
}

fetch('https://api.rainviewer.com/public/weather-maps.json')
  .then(function(r){return r.json();})
  .then(function(d){
    radarHost=d.host;
    radarFrames=(d.radar.past||[]).slice();
    if(radarFrames.length) actualizarFrameRadar(radarFrames[radarFrames.length-1].time);
  }).catch(function(){});

var mLG=L.layerGroup(),hLG=L.layerGroup(),HL=null;
var camLG=L.layerGroup();
(WEBCAMS_DATA||[]).forEach(function(cam){
  var mk=L.marker([cam.lat,cam.lon],{icon:L.divIcon({
    className:'',
    html:'<div style="background:rgba(20,20,30,0.82);border:2px solid rgba(255,255,255,0.6);border-radius:8px;padding:3px 5px;font-size:15px;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.5);">📷</div>',
    iconSize:[34,30],iconAnchor:[17,15]
  })});
  mk.bindTooltip('<b>'+cam.nombre+'</b><br><small>'+cam.tipo+'</small>',{direction:'top'});
  mk.on('click',function(){
    var ts=Date.now();
    var html='<div style="min-width:280px;text-align:center;">'
      +'<div style="font-weight:700;font-size:13px;margin-bottom:8px;">📷 '+cam.nombre+'</div>'
      +'<img id="wci_'+cam.id+'" src="'+cam.url+'?_t='+ts+'" style="max-width:320px;max-height:240px;width:100%;border-radius:8px;display:block;border:1px solid rgba(255,255,255,0.15);" onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'block\';" />'
      +'<div style="display:none;padding:20px;color:#94a3b8;font-size:12px;">⚠ No se pudo cargar la imagen</div>'
      +'<div style="font-size:11px;color:#94a3b8;margin-top:6px;">'+cam.descripcion+'</div>'
      +'<div style="display:flex;gap:8px;justify-content:center;margin-top:8px;">'
      +'<button onclick="var i=document.getElementById(\'wci_'+cam.id+'\');i.style.display=\'block\';i.nextElementSibling.style.display=\'none\';i.src=\''+cam.url+'?_t=\'+Date.now();" style="background:rgba(59,130,246,.8);border:none;border-radius:6px;color:#fff;padding:4px 12px;cursor:pointer;font-size:12px;">🔄 Actualizar</button>'
      +'<a href="'+cam.url+'" target="_blank" style="background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.2);border-radius:6px;color:#e6edf3;padding:4px 12px;font-size:12px;text-decoration:none;">↗ Ver original</a>'
      +'</div></div>';
    L.popup({maxWidth:360}).setLatLng([cam.lat,cam.lon]).setContent(html).openOn(map);
  });
  camLG.addLayer(mk);
});
var heatActive=true; // mapa de calor activo por defecto
L.control.layers(
  {'Relieve':terreno,'Claro':claro,'Satélite':sat,'OSM':osm},
  {
    '🌈 Mapa de calor':hLG,
    '📍 Marcadores':mLG,
    '📷 Webcams':camLG
  },
  {position:'bottomright',collapsed:true}
).addTo(map);
hLG.addTo(map);
mLG.addTo(map);
// camLG (webcams) se deja desactivada por defecto; el usuario la activa
// desde el control de capas si quiere verla.
// Detectar cuando el usuario activa/desactiva el mapa de calor
map.on('overlayadd',   function(e){ if(e.name==='🌈 Mapa de calor'){ heatActive=true;  render(); }});
map.on('overlayremove',function(e){ if(e.name==='🌈 Mapa de calor'){ heatActive=false; hLG.clearLayers(); }});

function locateMe(){map.locate({setView:true,maxZoom:13});}
var uMk=null;
map.on('locationfound',function(e){
  if(uMk) map.removeLayer(uMk);
  uMk=L.circleMarker(e.latlng,{radius:8,color:'#3498db',fillColor:'#3498db',fillOpacity:0.8})
    .addTo(map).bindPopup('📍 Estás aquí').openPopup();
});

// ── Colores ────────────────────────────────────────────────
function lerp(c1,c2,t){
  return 'rgb('+Math.round(c1[0]+t*(c2[0]-c1[0]))+','+Math.round(c1[1]+t*(c2[1]-c1[1]))+','+Math.round(c1[2]+t*(c2[2]-c1[2]))+')';
}
function col(v,p){
  if(p==='oidio'||p==='mildiu'){if(v<0)return '#aaa';return RC[Math.min(3,Math.max(0,Math.round(v)))];}
  if(p==='temp'){
    var s=[{v:-5,c:[148,0,211]},{v:0,c:[0,0,200]},{v:5,c:[0,115,255]},{v:10,c:[0,200,200]},
           {v:15,c:[50,205,50]},{v:20,c:[255,255,0]},{v:25,c:[255,140,0]},{v:30,c:[220,20,60]},
           {v:35,c:[139,0,0]},{v:40,c:[200,0,200]}];
    if(v<=s[0].v) return 'rgb('+s[0].c+')';
    if(v>=s[s.length-1].v) return 'rgb('+s[s.length-1].c+')';
    for(var i=0;i<s.length-1;i++)
      if(v>=s[i].v&&v<=s[i+1].v) return lerp(s[i].c,s[i+1].c,(v-s[i].v)/(s[i+1].v-s[i].v));
  }
  if(p==='precip') return v>=70?'#f00':v>=50?'#f9f':v>=40?'#c6f':v>=30?'#939':v>=20?'#609':v>=10?'#00f':v>=4?'#36f':v>=2?'#0cf':v>=0.5?'#9ff':v>0?'#eff':'transparent';
  if(p==='humidity') return v>=90?'#0d47a1':v>=70?'#1976d2':v>=50?'#42a5f5':'#90caf9';
  if(p==='wind') return v>=40?'#b71c1c':v>=30?'#e65100':v>=20?'#f57f17':v>=10?'#fbc02d':v>=5?'#81c784':'#b2dfdb';
  return '#aaa';
}
// Precipitación en la hora anterior AL MOMENTO MOSTRADO en la máquina del
// tiempo (no respecto al reloj real): diferencia entre el precipTotal en
// ese momento y el de 1h antes (precipTotal es acumulado desde medianoche,
// así que la resta da lo llovido en esa hora concreta). Busca en el mismo
// dataset (activeData) que está usando el slider en ese momento, para no
// mezclar datos de otro periodo.
function getPrecipHoraDe(sid, tsRef){
  var refT = new Date(tsRef).getTime();
  var haceHora = refT - 3600*1000;
  var datos = activeData;
  var valorRef = null, valorHace = null;
  for(var i=datos.length-1; i>=0; i--){
    var snap = datos[i];
    var t = new Date(snap.timestamp).getTime();
    if(t > refT) continue; // ignorar frames posteriores al momento mostrado
    var ests = snap.stations || [];
    var p = null;
    for(var j=0; j<ests.length; j++){
      if(ests[j] && ests[j].stationID === sid){
        p = ests[j].metric && ests[j].metric.precipTotal != null ? ests[j].metric.precipTotal : null;
        break;
      }
    }
    if(p === null) continue;
    if(valorRef === null){ valorRef = p; continue; }
    if(t <= haceHora){ valorHace = p; break; }
  }
  if(valorRef === null) return null;
  if(valorHace === null) return Math.round(valorRef*10)/10; // aún sin 1h de histórico antes de ese momento
  var delta = valorRef - valorHace;
  return Math.round((delta>=0?delta:valorRef)*10)/10;
}

function raw(est,p,tsRef){
  if(p==='oidio'||p==='mildiu'){var r=riesgoData[est.stationID];return r?r[p]:null;}
  var m=est.metric; if(!m) return null;
  if(p==='precip'){
    var acum=getPrecipHoraDe(est.stationID, tsRef||new Date());
    return acum!=null?acum:(m.precipTotal!=null?m.precipTotal:0);
  }
  if(p==='temp')     return m.temp;
  if(p==='humidity') return est.humidity;
  if(p==='wind')     return m.windGust;
  return null;
}
function wdL(d){
  if(d==null) return '—';
  return['N','NNE','NE','ENE','E','ESE','SE','SSE','S','SSO','SO','OSO','O','ONO','NO','NNO'][Math.round(d/22.5)%16];
}

// ── Leyenda ────────────────────────────────────────────────
var leg=L.control({position:'bottomleft'});
var _legCollapsed=(window.innerWidth<=600);
var _prevParam=null; // para colapsar la leyenda solo al ENTRAR en modo riesgo
leg.onAdd=function(){
  this._d=L.DomUtil.create('div','legend');
  L.DomEvent.disableClickPropagation(this._d);
  return this._d;
};
leg.upd=function(p){
  var title='',body='';
  if(p==='oidio'||p==='mildiu'){
    title=(p==='oidio'?'🍇 Oídio':'🍃 Mildiu');
    body+='<span class="li-row"><i style="background:#aaa"></i>Sin datos</span>';
    for(var i=3;i>=0;i--) body+='<span class="li-row"><i style="background:'+RC[i]+'"></i>'+RL[i]+'</span>';
    body+='<div style="color:#6b7280;font-size:.66rem;margin-top:4px">'+(p==='oidio'?'Gubler-Thomas':'10-10-10+EPI')+'</div>';
  } else {
    var g,ti,u;
    if(p==='precip'){
      ti='🌧 Precip 1h';u='mm';g=[0.5,2,4,10,20,30,40,50,70];
    } else if(p==='temp'){ti='🌡 Temp';u='°C';g=[5,10,15,20,25,30,35,40];}
    else if(p==='humidity'){ti='💧 Humedad';u='%';g=[30,50,70,90];}
    else{ti='💨 Viento';u='km/h';g=[2,5,10,20,30,40];}
    title=ti+' <span style="color:#6b7280;font-weight:400;font-size:.68rem">'+u+'</span>';
    body+='<span class="li-row"><i style="background:'+col(g[g.length-1],p)+'"></i>&gt;'+g[g.length-1]+'</span>';
    for(var i=g.length-2;i>=0;i--)
      body+='<span class="li-row"><i style="background:'+col(g[i],p)+'"></i>'+g[i]+'–'+g[i+1]+'</span>';
  }
  var tog=_legCollapsed?'▼':'▲';
  var bst=_legCollapsed?'display:none':'';
  this._d.innerHTML='<div class="leg-hdr" onclick="legToggle()"><span>'+title+'</span><span class="leg-tog">'+tog+'</span></div>'
    +'<div class="leg-body" id="leg-body" style="'+bst+'">'+body+'</div>';
};
leg.addTo(map);
function legToggle(){
  _legCollapsed=!_legCollapsed;
  var b=document.getElementById('leg-body');
  var t=document.querySelector('.leg-tog');
  if(b){b.style.display=_legCollapsed?'none':'';}
  if(t){t.textContent=_legCollapsed?'▼':'▲';}
}

// ── Panel lateral fijo ─────────────────────────────────────
var PS=null;
function showPanel(sid,html,titulo){
  document.getElementById('dc').innerHTML=html;
  document.getElementById('dh-title').textContent=titulo||'Detalle de estación';
  document.getElementById('dp').style.display='flex';
  PS=sid;
}
function hidePanel(){
  document.getElementById('dp').style.display='none';
  PS=null;
}

// ── Buscador de población + comparativa de modelos de pronóstico ───
// Open-Meteo (open-meteo.com): API pública sin clave, con CORS habilitado
// para uso directo desde el navegador. Se usa el geocoder para localizar
// cualquier población del mundo y la API de pronóstico pidiendo varios
// modelos a la vez (parámetro "models"), que devuelve un campo por
// modelo (ej. temperature_2m_max_ecmwf_ifs025) para poder compararlos.
var MODELOS_PRON=[
  {id:'ecmwf_ifs025',        nombre:'ECMWF',        estrella:true},
  {id:'icon_seamless',       nombre:'ICON',         estrella:false},
  {id:'gfs_seamless',        nombre:'GFS',          estrella:false},
  {id:'meteofrance_seamless',nombre:'AROME/ARPEGE', estrella:false}
];
var COL_MODELO={
  ecmwf_ifs025:'#3b82f6', icon_seamless:'#f59e0b',
  gfs_seamless:'#10b981', meteofrance_seamless:'#ef4444'
};
var pronData=null;

function wxInfo(code){
  if(code==null) return {ic:'❓'};
  if(code===0) return {ic:'☀️'};
  if(code<=2) return {ic:'🌤'};
  if(code===3) return {ic:'☁️'};
  if(code===45||code===48) return {ic:'🌫'};
  if(code>=51&&code<=57) return {ic:'🌦'};
  if(code>=61&&code<=67) return {ic:'🌧'};
  if(code>=71&&code<=77) return {ic:'🌨'};
  if(code>=80&&code<=82) return {ic:'🌦'};
  if(code===85||code===86) return {ic:'🌨'};
  if(code>=95) return {ic:'⛈'};
  return {ic:'☁️'};
}

var DIAS_SEM=['dom','lun','mar','mié','jue','vie','sáb'];
function fmtDiaCorto(iso){
  var d=new Date(iso+'T00:00:00');
  return DIAS_SEM[d.getDay()]+' '+d.getDate()+'/'+(d.getMonth()+1);
}

function debounce(fn,ms){
  var t=null;
  return function(){
    var args=arguments,ctx=this;
    clearTimeout(t);
    t=setTimeout(function(){fn.apply(ctx,args);},ms);
  };
}

// ── Pantalla completa de pronóstico ─────────────────────────
// Separada del mapa de datos climáticos: aquí vive el buscador de
// población y toda la comparativa de modelos, a pantalla completa
// para poder seguir añadiendo información sin pelear por espacio
// con el panel lateral de 300px.
function mostrarVistaPronostico(){
  document.getElementById('vp').classList.add('open');
  if(!pronData){
    var ultima=cargarUltimaPoblacion();
    if(ultima){ seleccionarPoblacion(ultima); return; }
  }
  setTimeout(function(){
    var i=document.getElementById('vp-buscador-input');
    if(i) i.focus();
  },50);
}
function mostrarVistaMapa(){
  document.getElementById('vp').classList.remove('open');
}

// Recuerda la última población consultada (localStorage, por navegador)
// para que al volver a abrir el pronóstico no haga falta buscarla de nuevo.
function guardarUltimaPoblacion(loc){
  try{ localStorage.setItem('meteo_ultima_poblacion',JSON.stringify(loc)); }catch(e){}
}
function cargarUltimaPoblacion(){
  try{
    var raw=localStorage.getItem('meteo_ultima_poblacion');
    return raw?JSON.parse(raw):null;
  }catch(e){ return null; }
}

var buscadorInput=document.getElementById('vp-buscador-input');
var buscadorRes=document.getElementById('vp-buscador-resultados');

var ejecutarBusqueda=debounce(function(q){
  if(!q||q.trim().length<2){buscadorRes.classList.remove('open');buscadorRes.innerHTML='';return;}
  fetch('https://geocoding-api.open-meteo.com/v1/search?name='+encodeURIComponent(q.trim())+'&count=6&language=es&format=json')
    .then(function(r){return r.json();})
    .then(function(d){
      var res=(d&&d.results)||[];
      if(!res.length){
        buscadorRes.innerHTML='<div class="br-empty">Sin resultados</div>';
        buscadorRes.classList.add('open');
        return;
      }
      buscadorRes.innerHTML=res.map(function(r,i){
        var sub=[r.admin2,r.admin1,r.country].filter(Boolean).join(', ');
        return '<div class="br-item" data-i="'+i+'"><b>'+r.name+'</b><small>'+sub+'</small></div>';
      }).join('');
      buscadorRes.classList.add('open');
      buscadorRes.querySelectorAll('.br-item').forEach(function(el){
        el.addEventListener('click',function(){
          seleccionarPoblacion(res[+el.getAttribute('data-i')]);
        });
      });
    })
    .catch(function(){
      buscadorRes.innerHTML='<div class="br-empty">Error al buscar</div>';
      buscadorRes.classList.add('open');
    });
},350);

if(buscadorInput){
  buscadorInput.addEventListener('input',function(){ejecutarBusqueda(buscadorInput.value);});
  document.addEventListener('click',function(e){
    if(!buscadorInput.contains(e.target)&&!buscadorRes.contains(e.target)) buscadorRes.classList.remove('open');
  });
}

function pintarVistaPronostico(html){
  document.getElementById('vp-contenido').innerHTML='<div id="vp-inner">'+html+'</div>';
}

function seleccionarPoblacion(loc){
  buscadorRes.classList.remove('open');
  buscadorInput.value=loc.name;
  guardarUltimaPoblacion(loc);
  var sub=[loc.admin2,loc.admin1,loc.country].filter(Boolean).join(', ');
  pintarVistaPronostico('<div style="text-align:center;padding:60px 10px;color:#6b7280;font-size:13px;">⏳ Cargando pronóstico…</div>');
  cargarPronostico(loc,sub);
}

function cargarPronostico(loc,sub){
  var vars='weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max';
  var models=MODELOS_PRON.map(function(m){return m.id;}).join(',');
  var url='https://api.open-meteo.com/v1/forecast?latitude='+loc.latitude+'&longitude='+loc.longitude
    +'&daily='+vars+'&models='+models+'&forecast_days=16&timezone=auto';
  fetch(url).then(function(r){return r.json();}).then(function(d){
    if(!d||!d.daily) throw new Error('sin datos');
    pronData={loc:loc,sub:sub,daily:d.daily};
    renderPronostico(5);
  }).catch(function(){
    pintarVistaPronostico('<div style="text-align:center;color:#999;font-size:13px;line-height:1.7;padding:60px 10px;">⚠ No se pudo obtener el pronóstico para esta ubicación.</div>');
  });
}

function valModelo(daily,campo,modelo,i){
  var arr=daily[campo+'_'+modelo];
  if(!arr) return null;
  var v=arr[i];
  return (v===undefined)?null:v;
}

// Etiqueta corta "5/9" a partir de la fecha, para el eje X de los gráficos
function fmtEjeX(iso){ return fmtDiaCorto(iso).split(' ')[1]; }

// Construye el <path> de una serie, cortando el trazo cuando faltan datos
// (para que un modelo de corto alcance -p.ej. AROME- no dibuje una línea
// recta hasta cero al acabarse sus días).
function trazarSerie(daily,campo,modeloId,n,xAt,yAt){
  var d='',enCurso=false;
  for(var i=0;i<n;i++){
    var v=valModelo(daily,campo,modeloId,i);
    if(v==null){enCurso=false;continue;}
    d+=(enCurso?'L':'M')+xAt(i).toFixed(1)+','+yAt(v).toFixed(1)+' ';
    enCurso=true;
  }
  return d;
}

function construirGraficoTemp(daily,tiempos,n){
  var W=272,H=140,mL=24,mR=6,mT=10,mB=16;
  var pw=W-mL-mR,ph=H-mT-mB;

  var vals=[];
  MODELOS_PRON.forEach(function(m){
    for(var i=0;i<n;i++){
      var vx=valModelo(daily,'temperature_2m_max',m.id,i); if(vx!=null) vals.push(vx);
      var vn=valModelo(daily,'temperature_2m_min',m.id,i); if(vn!=null) vals.push(vn);
    }
  });
  if(!vals.length) return '';
  var vMin=Math.min.apply(null,vals)-2,vMax=Math.max.apply(null,vals)+2;
  function xAt(i){ return n>1?mL+i*(pw/(n-1)):mL+pw/2; }
  function yAt(v){ return mT+ph-((v-vMin)/(vMax-vMin))*ph; }

  var svg='<svg viewBox="0 0 '+W+' '+H+'" style="width:100%;height:auto;display:block;">';
  [vMin,(vMin+vMax)/2,vMax].forEach(function(v){
    var y=yAt(v);
    svg+='<line x1="'+mL+'" y1="'+y.toFixed(1)+'" x2="'+(W-mR)+'" y2="'+y.toFixed(1)+'" stroke="rgba(15,23,42,0.08)"/>';
    svg+='<text x="1" y="'+(y+3).toFixed(1)+'" font-size="8" fill="#64748b">'+Math.round(v)+'°</text>';
  });
  MODELOS_PRON.forEach(function(m){
    var col=COL_MODELO[m.id];
    var dMax=trazarSerie(daily,'temperature_2m_max',m.id,n,xAt,yAt);
    if(dMax) svg+='<path d="'+dMax+'" fill="none" stroke="'+col+'" stroke-width="2"/>';
    var dMin=trazarSerie(daily,'temperature_2m_min',m.id,n,xAt,yAt);
    if(dMin) svg+='<path d="'+dMin+'" fill="none" stroke="'+col+'" stroke-width="1.2" stroke-dasharray="3,2" opacity="0.55"/>';
  });
  for(var i=0;i<n;i++){
    var vRef=valModelo(daily,'temperature_2m_max',MODELOS_PRON[0].id,i);
    if(vRef==null) continue;
    svg+='<circle cx="'+xAt(i).toFixed(1)+'" cy="'+yAt(vRef).toFixed(1)+'" r="3.5" fill="'+COL_MODELO[MODELOS_PRON[0].id]+'" stroke="#fff" stroke-width="1" style="cursor:pointer" onclick="abrirDetalleDia(\''+tiempos[i]+'\')"><title>Ver detalle del '+fmtEjeX(tiempos[i])+'</title></circle>';
  }
  var paso=n>8?3:1;
  for(var i=0;i<n;i+=paso){
    svg+='<text x="'+xAt(i).toFixed(1)+'" y="'+(H-4)+'" font-size="7.5" fill="#64748b" text-anchor="middle">'+fmtEjeX(tiempos[i])+'</text>';
  }
  svg+='</svg>';

  var leyenda='<div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:2px;">'
    +MODELOS_PRON.map(function(m){
      return '<span style="font-size:9px;color:#64748b;display:inline-flex;align-items:center;gap:3px;">'
        +'<span style="width:8px;height:8px;border-radius:2px;background:'+COL_MODELO[m.id]+';display:inline-block;"></span>'+m.nombre+'</span>';
    }).join('')
    +'</div>';

  return '<div style="background:#f8f8f8;border-radius:8px;padding:8px 6px 4px;margin-bottom:10px;">'
    +'<div style="font-size:10px;color:#888;margin-bottom:2px;padding-left:4px;">🌡 Máx/mín por modelo (línea continua=máx, discontinua=mín)</div>'
    +svg+leyenda+'</div>';
}

function construirGraficoLluvia(daily,tiempos,n){
  var refId=MODELOS_PRON[0].id;
  var vals=[];
  for(var i=0;i<n;i++){ var v=valModelo(daily,'precipitation_sum',refId,i); vals.push(v==null?0:v); }
  var vMax=Math.max(2,Math.max.apply(null,vals));
  var W=272,H=64,mL=24,mR=6,mT=6,mB=16;
  var pw=W-mL-mR,ph=H-mT-mB;
  var bw=Math.max(3,(pw/n)*0.6);
  function xAt(i){ return n>1?mL+i*(pw/(n-1)):mL+pw/2; }

  var svg='<svg viewBox="0 0 '+W+' '+H+'" style="width:100%;height:auto;display:block;">';
  svg+='<line x1="'+mL+'" y1="'+(mT+ph)+'" x2="'+(W-mR)+'" y2="'+(mT+ph)+'" stroke="rgba(15,23,42,0.14)"/>';
  for(var i=0;i<n;i++){
    var h=(vals[i]/vMax)*ph,x=xAt(i)-bw/2,y=mT+ph-h;
    svg+='<rect x="'+x.toFixed(1)+'" y="'+y.toFixed(1)+'" width="'+bw.toFixed(1)+'" height="'+Math.max(0,h).toFixed(1)+'" rx="1.5" fill="#3b82f6" opacity="'+(vals[i]>0?0.85:0.22)+'" style="cursor:pointer" onclick="abrirDetalleDia(\''+tiempos[i]+'\')"><title>Ver detalle del '+fmtEjeX(tiempos[i])+'</title></rect>';
  }
  var paso=n>8?3:1;
  for(var i=0;i<n;i+=paso){
    svg+='<text x="'+xAt(i).toFixed(1)+'" y="'+(H-4)+'" font-size="7.5" fill="#64748b" text-anchor="middle">'+fmtEjeX(tiempos[i])+'</text>';
  }
  svg+='</svg>';

  return '<div style="background:#f8f8f8;border-radius:8px;padding:8px 6px 4px;margin-bottom:10px;">'
    +'<div style="font-size:10px;color:#888;margin-bottom:2px;padding-left:4px;">🌧 Lluvia prevista — ⭐ ECMWF (mm/día)</div>'
    +svg+'</div>';
}

function renderPronostico(numDias){
  if(!pronData) return;
  var loc=pronData.loc,sub=pronData.sub,daily=pronData.daily;
  var tiempos=daily.time||[];
  var n=Math.min(numDias,tiempos.length);

  var filas='';
  for(var i=0;i<n;i++){
    var wx=wxInfo(valModelo(daily,'weather_code',MODELOS_PRON[0].id,i));
    filas+='<div class="vp-day-card" style="background:#f8f8f8;border-radius:10px;padding:12px 14px;" onclick="abrirDetalleDia(\''+tiempos[i]+'\')">'
      +'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">'
      +'<span style="font-weight:700;font-size:14px;color:#2c3e50;text-transform:capitalize;">'+fmtDiaCorto(tiempos[i])+'</span>'
      +'<span style="font-size:22px;">'+wx.ic+'</span>'
      +'</div>'
      +'<table style="width:100%;font-size:12px;border-collapse:collapse;">'
      +'<tr style="background:#dce8f5;"><td style="padding:3px 5px;font-weight:bold;">Modelo</td>'
      +'<td style="padding:3px 5px;text-align:center;font-weight:bold;">Máx/Mín</td>'
      +'<td style="padding:3px 5px;text-align:center;font-weight:bold;">Lluvia</td></tr>'
      +MODELOS_PRON.map(function(m,mi){
        var tmax=valModelo(daily,'temperature_2m_max',m.id,i);
        var tmin=valModelo(daily,'temperature_2m_min',m.id,i);
        var pr=valModelo(daily,'precipitation_sum',m.id,i);
        var pp=valModelo(daily,'precipitation_probability_max',m.id,i);
        var tTxt=(tmax!=null&&tmin!=null)?(Math.round(tmax)+'°/'+Math.round(tmin)+'°'):'—';
        var lTxt=(pr!=null)?((pp!=null?pp+'% · ':'')+pr.toFixed(1)+'mm'):'—';
        return '<tr'+(mi%2?' style="background:#f5f5f5;"':'')+'>'
          +'<td style="padding:3px 5px;">'+(m.estrella?'⭐ ':'')+m.nombre+'</td>'
          +'<td style="text-align:center;padding:3px 5px;font-weight:700;">'+tTxt+'</td>'
          +'<td style="text-align:center;padding:3px 5px;">'+lTxt+'</td></tr>';
      }).join('')
      +'</table></div>';
  }

  var html='<div style="font-size:24px;font-weight:700;color:#0f172a;margin-bottom:2px;">📍 '+loc.name+'</div>'
    +'<div style="font-size:13px;color:#64748b;margin-bottom:16px;">'+(sub||'')+'</div>'
    +'<div style="display:flex;gap:8px;margin-bottom:14px;">'
    +'<button type="button" class="fc-tab'+(numDias===5?' active':'')+'" onclick="renderPronostico(5)">📅 4-5 días</button>'
    +'<button type="button" class="fc-tab'+(numDias===16?' active':'')+'" onclick="renderPronostico(16)">📆 16 días</button>'
    +'</div>'
    +'<div style="background:#f0f7ff;border-left:3px solid #3498db;border-radius:6px;padding:10px 14px;font-size:12.5px;color:#444;margin-bottom:16px;line-height:1.6;">'
    +'⭐ <b style="color:#2c3e50;">ECMWF (IFS-HRES)</b> se toma como referencia — el de mayor precisión global según verificaciones independientes — comparado con ICON (DWD), GFS (NOAA) y AROME/ARPEGE (Météo-France). '
    +(numDias>7?'Más allá de 4-7 días solo ECMWF y GFS ofrecen datos; ICON y AROME tienen alcance corto.':'')
    +' Toca un día (tarjeta o punto del gráfico) para ver su detalle horario.'
    +'</div>'
    +'<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px;margin-bottom:16px;">'
    +'<div id="vp-mapa"></div>'
    +construirGraficoTemp(daily,tiempos,n)
    +construirGraficoLluvia(daily,tiempos,n)
    +'</div>'
    +'<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px;">'
    +filas
    +'</div>'
    +'<div style="font-size:11px;color:#6b7280;margin-top:16px;">Fuente: Open-Meteo (datos abiertos ECMWF/DWD/NOAA/Météo-France)</div>';

  pintarVistaPronostico(html);
  inicializarMapaPronostico(loc);
}

// Mapa de localización de la pantalla de pronóstico. Se (re)crea en cada
// renderPronostico() porque pintarVistaPronostico() sustituye el HTML de
// #vp-contenido (incluido el <div id="vp-mapa">), lo que deja huérfana
// cualquier instancia de Leaflet anterior atada a ese nodo.
var mapaPron=null;
function inicializarMapaPronostico(loc){
  if(mapaPron){ try{ mapaPron.remove(); }catch(e){} mapaPron=null; }
  if(!document.getElementById('vp-mapa')) return;
  mapaPron=L.map('vp-mapa',{zoomControl:false,scrollWheelZoom:false}).setView([loc.latitude,loc.longitude],11);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'© OSM'}).addTo(mapaPron);
  L.marker([loc.latitude,loc.longitude],{icon:L.divIcon({
    className:'',
    html:'<div style="background:#e6474c;border:2px solid #fff;border-radius:50% 50% 50% 0;width:22px;height:22px;transform:rotate(-45deg);box-shadow:0 2px 8px rgba(0,0,0,.35);"></div>',
    iconSize:[22,22],iconAnchor:[11,22]
  })}).addTo(mapaPron);
}

// ── Detalle horario de un día concreto ──────────────────────
var MESES_LARGO=['enero','febrero','marzo','abril','mayo','junio','julio','agosto','septiembre','octubre','noviembre','diciembre'];
var DIAS_LARGO=['domingo','lunes','martes','miércoles','jueves','viernes','sábado'];
function fmtDiaLargo(iso){
  var d=new Date(iso+'T00:00:00');
  var s=DIAS_LARGO[d.getDay()]+' '+d.getDate()+' de '+MESES_LARGO[d.getMonth()];
  return s.charAt(0).toUpperCase()+s.slice(1);
}

function construirGraficoTempHoraria(hourly){
  var horas=hourly.time||[],temps=hourly.temperature_2m||[];
  var n=horas.length;
  var vals=temps.filter(function(v){return v!=null;});
  if(!n||!vals.length) return '';
  var W=560,H=150,mL=28,mR=10,mT=12,mB=20;
  var pw=W-mL-mR,ph=H-mT-mB;
  var vMin=Math.min.apply(null,vals)-1,vMax=Math.max.apply(null,vals)+1;
  function xAt(i){ return n>1?mL+i*(pw/(n-1)):mL+pw/2; }
  function yAt(v){ return mT+ph-((v-vMin)/(vMax-vMin))*ph; }

  var svg='<svg viewBox="0 0 '+W+' '+H+'" style="width:100%;height:auto;display:block;">';
  [vMin,(vMin+vMax)/2,vMax].forEach(function(v){
    var y=yAt(v);
    svg+='<line x1="'+mL+'" y1="'+y.toFixed(1)+'" x2="'+(W-mR)+'" y2="'+y.toFixed(1)+'" stroke="rgba(15,23,42,0.08)"/>';
    svg+='<text x="1" y="'+(y+3).toFixed(1)+'" font-size="10" fill="#64748b">'+Math.round(v)+'°</text>';
  });
  var d='',en=false;
  for(var i=0;i<n;i++){
    var v=temps[i]; if(v==null){en=false;continue;}
    d+=(en?'L':'M')+xAt(i).toFixed(1)+','+yAt(v).toFixed(1)+' '; en=true;
  }
  if(d) svg+='<path d="'+d+'" fill="none" stroke="#3b82f6" stroke-width="2.2"/>';
  var paso=n>12?3:(n>6?2:1);
  for(var i=0;i<n;i+=paso){
    if(temps[i]!=null) svg+='<circle cx="'+xAt(i).toFixed(1)+'" cy="'+yAt(temps[i]).toFixed(1)+'" r="2" fill="#3b82f6"/>';
    svg+='<text x="'+xAt(i).toFixed(1)+'" y="'+(H-4)+'" font-size="9" fill="#64748b" text-anchor="middle">'+horas[i].slice(11,16)+'</text>';
  }
  svg+='</svg>';
  return svg;
}

function construirGraficoLluviaHoraria(hourly){
  var horas=hourly.time||[],precs=hourly.precipitation||[];
  var n=horas.length;
  if(!n) return '';
  var vMax=Math.max(1,Math.max.apply(null,precs.map(function(v){return v==null?0:v;})));
  var W=560,H=90,mL=28,mR=10,mT=6,mB=20;
  var pw=W-mL-mR,ph=H-mT-mB;
  var bw=Math.max(2,(pw/n)*0.6);
  function xAt(i){ return n>1?mL+i*(pw/(n-1)):mL+pw/2; }

  var svg='<svg viewBox="0 0 '+W+' '+H+'" style="width:100%;height:auto;display:block;">';
  svg+='<line x1="'+mL+'" y1="'+(mT+ph)+'" x2="'+(W-mR)+'" y2="'+(mT+ph)+'" stroke="rgba(15,23,42,0.14)"/>';
  var paso=n>12?3:(n>6?2:1);
  for(var i=0;i<n;i++){
    var v=precs[i]==null?0:precs[i];
    var h=(v/vMax)*ph,x=xAt(i)-bw/2,y=mT+ph-h;
    svg+='<rect x="'+x.toFixed(1)+'" y="'+y.toFixed(1)+'" width="'+bw.toFixed(1)+'" height="'+Math.max(0,h).toFixed(1)+'" rx="1.5" fill="#3b82f6" opacity="'+(v>0?0.85:0.18)+'"/>';
    if(i%paso===0) svg+='<text x="'+xAt(i).toFixed(1)+'" y="'+(H-4)+'" font-size="9" fill="#64748b" text-anchor="middle">'+horas[i].slice(11,16)+'</text>';
  }
  svg+='</svg>';
  return svg;
}

function abrirDetalleDia(fechaISO){
  if(!pronData) return;
  var modal=document.getElementById('vp-detalle-dia');
  var body=document.getElementById('vpd-body');
  document.getElementById('vpd-titulo').textContent=fmtDiaLargo(fechaISO);
  body.innerHTML='<div style="text-align:center;padding:40px 10px;color:#64748b;font-size:13px;">⏳ Cargando detalle horario…</div>';
  modal.classList.add('open');

  var loc=pronData.loc;
  var url='https://api.open-meteo.com/v1/forecast?latitude='+loc.latitude+'&longitude='+loc.longitude
    +'&hourly=temperature_2m,precipitation&models=ecmwf_ifs025'
    +'&start_date='+fechaISO+'&end_date='+fechaISO+'&timezone=auto';
  fetch(url).then(function(r){return r.json();}).then(function(d){
    if(!d||!d.hourly) throw new Error('sin datos');
    body.innerHTML=
      '<div style="font-size:11px;color:#64748b;margin-bottom:12px;">⭐ Detalle horario — ECMWF (IFS-HRES)</div>'
      +'<div style="font-size:11px;font-weight:700;color:#2c3e50;margin-bottom:4px;">🌡 Temperatura por hora</div>'
      +construirGraficoTempHoraria(d.hourly)
      +'<div style="font-size:11px;font-weight:700;color:#2c3e50;margin:16px 0 4px;">🌧 Precipitación por hora (mm)</div>'
      +construirGraficoLluviaHoraria(d.hourly);
  }).catch(function(){
    body.innerHTML='<div style="text-align:center;color:#999;font-size:13px;padding:40px 10px;">⚠ No se pudo cargar el detalle horario.</div>';
  });
}
function cerrarDetalleDia(){
  document.getElementById('vp-detalle-dia').classList.remove('open');
}

// ── Mapa de precipitación acumulada prevista (multi-modelo) ──
// Rejilla de puntos sobre la Región de Murcia y alrededores. Para cada
// punto se pide a Open-Meteo la precipitación horaria del modelo elegido
// y se acumula desde la hora en curso hasta el plazo seleccionado
// (24h/48h/72h/5d/7d). El campo resultante se interpola con turf (IDW,
// igual que el heatmap de estaciones) y se pinta con la escala de color
// habitual de las webs meteorológicas (mm acumulados).
//
// Para no castigar la cuota gratuita de Open-Meteo se piden dos cosas
// distintas y separadas:
//   · la rejilla (~100 puntos) solo del modelo activo, bajo demanda;
//   · la comparativa de modelos solo en las poblaciones del valle
//     (8 puntos), que es barata y es lo que de verdad interesa aquí.
// Todo queda cacheado en memoria por (modelo, ámbito, días).

// Ventana geográfica: toda la Región de Murcia más un margen (Almería,
// Granada, Albacete, Alicante) para que el campo interpolado no se corte
// justo en el borde de la zona de interés. Paso de 0,25° (~22 km): es la
// resolución nativa de ECMWF-IFS y deja la rejilla en ~100 puntos, que es
// lo que la cuota gratuita de Open-Meteo admite con holgura.
var LL_BBOX={la0:37.00,la1:38.90,lo0:-3.00,lo1:0.00};
var LL_PASO=0.25;
var LL_LIMITES=[[LL_BBOX.la0,LL_BBOX.lo0],[LL_BBOX.la1,LL_BBOX.lo1]];

// Modelos disponibles en Open-Meteo que cubren el sureste peninsular.
// Los marcados con "top" son los de mejor comportamiento verificado en
// esta zona: ECMWF (referencia global) e ICON-EU (el de más resolución
// que llega a Murcia). AROME/HARMONIE de alta resolución no tienen
// dominio abierto sobre España, por eso no aparecen.
// "alt" es un identificador de reserva: si Open-Meteo retira o renombra
// una variante concreta, se reintenta con el alias equivalente en vez de
// dejar el modelo sin datos.
var LL_MODELOS=[
  {id:'ecmwf_ifs025',              alt:null,                             nombre:'ECMWF',    top:true,  det:'IFS 0,25° · referencia mundial (2-7 días)'},
  {id:'icon_eu',                   alt:'icon_seamless',                  nombre:'ICON-EU',  top:true,  det:'DWD 7 km · máxima resolución que cubre Murcia'},
  {id:'meteofrance_arpege_europe', alt:'meteofrance_seamless',           nombre:'ARPEGE',   top:false, det:'Météo-France 11 km · buen comportamiento en el Mediterráneo'},
  {id:'ukmo_seamless',             alt:'ukmo_global_deterministic_10km', nombre:'UKMO',     top:false, det:'Met Office ~10 km'},
  {id:'gfs_seamless',              alt:'gfs_global',                     nombre:'GFS',      top:false, det:'NOAA 13-25 km'},
  {id:'ecmwf_aifs025_single',      alt:'ecmwf_aifs025',                  nombre:'ECMWF AI', top:false, det:'AIFS 0,25° · modelo de IA de ECMWF'}
];

var LL_PLAZOS=[
  {h:24, txt:'24 h'},{h:48, txt:'48 h'},{h:72, txt:'72 h'},
  {h:120,txt:'5 días'},{h:168,txt:'7 días'}
];

// Fondos del mapa. Cada uno tiene una capa base (debajo del sombreado) y
// otra de rótulos/carreteras que va en el panel de encima, para que la
// información del mapa se siga leyendo sobre la mancha de precipitación.
var LL_FONDOS=[
  {id:'claro',   txt:'🗺 Claro',   base:ESRI_GRIS,      etiq:ESRI_GRIS_ETIQ, attr:'© Esri',   maxNat:16},
  {id:'relieve', txt:'⛰ Relieve', base:GOOGLE_RELIEVE, etiq:GOOGLE_CALLES,  attr:'© Google', maxNat:20, sub:GOOGLE_SUB},
  {id:'hibrido', txt:'🛰 Híbrido', base:GOOGLE_SAT,     etiq:GOOGLE_CALLES,  attr:'© Google', maxNat:20, sub:GOOGLE_SUB}
];

// Poblaciones de referencia del valle del Guadalentín (+ Murcia capital)
var LL_POBLACIONES=[
  {n:'Totana',           lat:37.771,lon:-1.502,pri:1},
  {n:'Aledo',            lat:37.798,lon:-1.573,pri:8},
  {n:'Lorca',            lat:37.676,lon:-1.700,pri:2},
  {n:'Alhama de Murcia', lat:37.851,lon:-1.425,pri:3},
  {n:'Librilla',         lat:37.891,lon:-1.352,pri:7},
  {n:'Puerto Lumbreras', lat:37.564,lon:-1.812,pri:6},
  {n:'Mazarrón',         lat:37.599,lon:-1.315,pri:5},
  {n:'Murcia',           lat:37.983,lon:-1.130,pri:4}
];

// Escala de color por mm acumulados (estilo Meteologix/AEMET)
var LL_ESCALA=[
  {v:0.1,c:'#eef3fc'},{v:1,c:'#d5e3f8'},{v:2,c:'#b5d1f3'},{v:3,c:'#90bbeb'},
  {v:5,c:'#67a1e1'},{v:7,c:'#3f84d5'},{v:10,c:'#2065c0'},{v:15,c:'#17489f'},
  {v:20,c:'#12347a'},{v:25,c:'#2e8b57'},{v:30,c:'#45b649'},{v:40,c:'#84c93f'},
  {v:50,c:'#c9d92f'},{v:60,c:'#f2e02a'},{v:70,c:'#f9bd23'},{v:80,c:'#f59331'},
  {v:100,c:'#ee6a2c'},{v:125,c:'#e03b2c'},{v:150,c:'#bd2130'},{v:200,c:'#8d1b3d'},
  {v:250,c:'#7a1a6e'},{v:300,c:'#a83bb0'},{v:400,c:'#cf86d6'},{v:500,c:'#c9c9c9'}
];
var LL_ETIQ_LEYENDA=[0.1,1,2,5,10,20,30,50,70,100,150,250];

function llColor(v){
  if(v==null||isNaN(v)||v<0.1) return null;
  for(var i=0;i<LL_ESCALA.length;i++) if(v<LL_ESCALA[i].v) return LL_ESCALA[Math.max(0,i-1)].c;
  return LL_ESCALA[LL_ESCALA.length-1].c;
}
// Texto blanco a partir del azul medio, para que se lea sobre el fondo
function llColorTexto(v){ return (v!=null&&v>=5)?'#fff':'#1e293b'; }

var llModelo='ecmwf_ifs025';
var llHoras=48;
var llFondo=llRecordado('meteo_ll_fondo','claro');
var llOpacidad=parseFloat(llRecordado('meteo_ll_opacidad','0.75'))||0.75;
var llCapaBase=null, llCapaEtiq=null;

function llRecordado(clave,porDefecto){
  try{ return localStorage.getItem(clave)||porDefecto; }catch(e){ return porDefecto; }
}
function llRecordar(clave,valor){
  try{ localStorage.setItem(clave,valor); }catch(e){}
}
var llMapa=null, llCapaCampo=null, llCapaPtos=null;
var llRejillaPts=null;
var llCache={};        // 'modelo|ambito|dias' -> [{lat,lon,t,p}]
var llPeticion=0;      // token para descartar respuestas de peticiones viejas

function llRejilla(){
  if(llRejillaPts) return llRejillaPts;
  llRejillaPts=[];
  for(var la=LL_BBOX.la0; la<=LL_BBOX.la1+1e-9; la+=LL_PASO)
    for(var lo=LL_BBOX.lo0; lo<=LL_BBOX.lo1+1e-9; lo+=LL_PASO)
      llRejillaPts.push({lat:Math.round(la*100)/100, lon:Math.round(lo*100)/100});
  return llRejillaPts;
}

// Días de pronóstico que hay que pedir para poder acumular "horas" desde
// la hora en curso (uno más, porque el día de hoy ya va empezado).
function llDias(horas){ return Math.min(16, Math.ceil(horas/24)+1); }

function llDeCache(modelo,ambito,dias){
  for(var k in llCache){
    var pz=k.split('|');
    if(pz[0]===modelo && pz[1]===ambito && (+pz[2])>=dias) return llCache[k];
  }
  return null;
}

function llAlt(modelo){
  for(var i=0;i<LL_MODELOS.length;i++) if(LL_MODELOS[i].id===modelo) return LL_MODELOS[i].alt||null;
  return null;
}

function llDescargar(pts,modelo,dias){
  var lats=[],lons=[];
  pts.forEach(function(p){ lats.push(p.lat); lons.push(p.lon); });
  var url='https://api.open-meteo.com/v1/forecast?latitude='+lats.join(',')
    +'&longitude='+lons.join(',')+'&hourly=precipitation&models='+modelo
    +'&forecast_days='+dias+'&timeformat=unixtime&timezone=UTC&cell_selection=land';
  return fetch(url).then(function(r){
    if(!r.ok) throw new Error('HTTP '+r.status);
    return r.json();
  }).then(function(d){
    if(d&&d.error) throw new Error(d.reason||'error API');
    var arr=Array.isArray(d)?d:[d];
    return arr.map(function(o,i){
      var h=o.hourly||{};
      return {lat:pts[i]?pts[i].lat:o.latitude, lon:pts[i]?pts[i].lon:o.longitude,
              t:h.time||[], p:h.precipitation||h['precipitation_'+modelo]||[]};
    });
  });
}

function llPedir(pts,modelo,ambito,dias){
  var cache=llDeCache(modelo,ambito,dias);
  if(cache) return Promise.resolve(cache);
  return llDescargar(pts,modelo,dias).catch(function(e){
    var alt=llAlt(modelo);
    if(!alt) throw e;
    return llDescargar(pts,alt,dias);
  }).then(function(res){
    llCache[modelo+'|'+ambito+'|'+dias]=res;
    return res;
  });
}

// Ventana de acumulación: desde el inicio de la hora en curso
function llVentana(horas){
  var ini=Math.floor(Date.now()/3600000)*3600;
  return {ini:ini, fin:ini+horas*3600};
}

// Devuelve {v: mm acumulados, cob: fracción del plazo con datos}. La
// cobertura importa porque los modelos de alcance corto (ICON-EU,
// ARPEGE) no llegan a 7 días: su acumulado se marca con * en vez de
// hacerlo pasar por un total comparable con el de ECMWF o GFS.
function llAcumular(serie,ven){
  if(!serie||!serie.t||!serie.t.length) return null;
  var s=0,con=0,total=Math.max(1,Math.round((ven.fin-ven.ini)/3600));
  for(var i=0;i<serie.t.length;i++){
    var t=serie.t[i];
    if(t<ven.ini) continue;
    if(t>=ven.fin) break;
    var v=serie.p[i];
    if(v!=null&&!isNaN(v)){ s+=v; con++; }
  }
  return con?{v:s, cob:con/total}:null;
}

function llVal(a){ return a?a.v:null; }

function llFmt(a){
  if(a==null||isNaN(a.v)) return '—';
  return (a.v<10?a.v.toFixed(1):String(Math.round(a.v)))+(a.cob<0.9?'*':'');
}

function llFechaTxt(epochSeg){
  return new Date(epochSeg*1000).toLocaleString('es-ES',
    {timeZone:'Europe/Madrid',weekday:'short',day:'2-digit',month:'2-digit',
     hour:'2-digit',minute:'2-digit'});
}

// ── Vista ───────────────────────────────────────────────────
var llAjustado=false;
function mostrarVistaLluvia(){
  document.getElementById('vl').classList.add('open');
  llInitMapa();
  // El mapa se crea con el contenedor recién mostrado: hay que recalcular
  // su tamaño. El encuadre solo se ajusta la primera vez, para no deshacer
  // el zoom del usuario cada vez que vuelve a abrir la pantalla.
  setTimeout(function(){
    if(!llMapa) return;
    llMapa.invalidateSize();
    if(!llAjustado){ llMapa.fitBounds(LL_LIMITES); llAjustado=true; }
  },60);
  llRender();
}
function ocultarVistaLluvia(){
  document.getElementById('vl').classList.remove('open');
}

function llInitMapa(){
  if(llMapa) return;
  llMapa=L.map('vl-mapa',{scrollWheelZoom:false});
  llMapa.fitBounds(LL_LIMITES);
  llMapa.createPane('llcampo');
  llMapa.getPane('llcampo').style.zIndex=390;
  llMapa.getPane('llcampo').style.filter='blur(9px)';
  // Rótulos y carreteras en un panel por encima del campo de lluvia: si
  // fueran parte del fondo quedarían tapados por la mancha de color.
  llMapa.createPane('lletiq');
  llMapa.getPane('lletiq').style.zIndex=450;
  llMapa.getPane('lletiq').style.pointerEvents='none';
  llCapaCampo=L.layerGroup().addTo(llMapa);
  llAplicarFondo();
  llCapaPtos=L.layerGroup().addTo(llMapa);
  llMapa.on('click',llClickMapa);
  llMapa.on('zoomend',llDibujarPoblaciones);
  llPintarLeyenda();
}

function llAplicarFondo(){
  if(!llMapa) return;
  var f=LL_FONDOS[0];
  LL_FONDOS.forEach(function(x){ if(x.id===llFondo) f=x; });
  [llCapaBase,llCapaEtiq].forEach(function(c){ if(c&&llMapa.hasLayer(c)) llMapa.removeLayer(c); });
  var comun={maxNativeZoom:f.maxNat,maxZoom:18};
  if(f.sub) comun.subdomains=f.sub;
  llCapaBase=L.tileLayer(f.base,Object.assign({attribution:f.attr},comun)).addTo(llMapa);
  llCapaEtiq=L.tileLayer(f.etiq,Object.assign({pane:'lletiq'},comun)).addTo(llMapa);
  vigilarFondo(llMapa,[llCapaBase,llCapaEtiq],function(nueva){ llCapaBase=nueva; llCapaEtiq=null; });
}

function llSetFondo(id){
  if(id===llFondo) return;
  llFondo=id; llRecordar('meteo_ll_fondo',id);
  llAplicarFondo(); llPintarChips();
}

// La opacidad se aplica sobre las celdas ya pintadas: no hace falta
// recalcular la interpolación, que es lo caro.
function llSetOpacidad(v){
  llOpacidad=parseFloat(v)||0.75;
  llRecordar('meteo_ll_opacidad',String(llOpacidad));
  if(llCapaCampo) llCapaCampo.eachLayer(function(c){
    if(c.setStyle) c.setStyle({fillOpacity:llOpacidad});
  });
}

function llPintarChips(){
  var cm=document.getElementById('vl-modelos');
  if(cm) cm.innerHTML=LL_MODELOS.map(function(m){
    return '<button type="button" class="ll-chip'+(m.id===llModelo?' active':'')+'"'
      +' title="'+m.det+'" onclick="llSetModelo(\''+m.id+'\')">'
      +(m.top?'⭐ ':'')+m.nombre+'</button>';
  }).join('');
  var cp=document.getElementById('vl-plazos');
  if(cp) cp.innerHTML=LL_PLAZOS.map(function(p){
    return '<button type="button" class="ll-chip'+(p.h===llHoras?' active':'')+'"'
      +' onclick="llSetPlazo('+p.h+')">'+p.txt+'</button>';
  }).join('');
  var cf=document.getElementById('vl-fondos');
  if(cf) cf.innerHTML=LL_FONDOS.map(function(f){
    return '<button type="button" class="ll-chip'+(f.id===llFondo?' active':'')+'"'
      +' onclick="llSetFondo(\''+f.id+'\')">'+f.txt+'</button>';
  }).join('');
  var so=document.getElementById('vl-opacidad');
  if(so && so.value!=llOpacidad) so.value=llOpacidad;
}

function llSetModelo(id){ if(id===llModelo) return; llModelo=id; llRender(); }
function llSetPlazo(h){ if(h===llHoras) return; llHoras=h; llRender(); }

function llCargando(activo,txt){
  var el=document.getElementById('vl-cargando');
  if(!el) return;
  el.textContent=txt||'⏳ Descargando pronóstico…';
  el.style.display=activo?'block':'none';
}

function llNombreModelo(id){
  for(var i=0;i<LL_MODELOS.length;i++) if(LL_MODELOS[i].id===id) return LL_MODELOS[i].nombre;
  return id;
}

function llRender(){
  llInitMapa();
  llPintarChips();
  var ven=llVentana(llHoras), dias=llDias(llHoras);
  var plazo='';
  LL_PLAZOS.forEach(function(p){ if(p.h===llHoras) plazo=p.txt; });

  var cab=document.getElementById('vl-rango');
  if(cab) cab.innerHTML='<b>Precipitación total acumulada '+plazo+'</b> — '
    +llNombreModelo(llModelo)+' · de '+llFechaTxt(ven.ini)+' a '+llFechaTxt(ven.fin)+' (hora local)';

  var token=++llPeticion;
  llCargando(true);
  llPedir(llRejilla(),llModelo,'rejilla',dias).then(function(datos){
    if(token!==llPeticion) return;
    llPintarCampo(datos,ven);
    llCargando(false);
  }).catch(function(){
    if(token!==llPeticion) return;
    llCapaCampo.clearLayers();
    llCargando(true,'⚠ '+llNombreModelo(llModelo)+' no ha devuelto datos. Prueba con otro modelo.');
  });

  llRenderComparativa(ven,dias,token);
}

function llPintarCampo(datos,ven){
  llCapaCampo.clearLayers();
  var feats=[];
  datos.forEach(function(s){
    var a=llAcumular(s,ven);
    if(a==null) return;
    feats.push(turf.point([s.lon,s.lat],{value:a.v}));
  });
  if(feats.length<3) return;
  try{
    var g=turf.interpolate(turf.featureCollection(feats),5,
      {gridType:'square',property:'value',units:'kilometers',weight:2.2});
    var cl=turf.featureCollection(g.features.filter(function(f){
      var v=f.properties.value;
      return v!=null&&!isNaN(v)&&v>=0.1;
    }));
    llCapaCampo.addLayer(L.geoJSON(cl,{pane:'llcampo',style:function(f){
      return {fillColor:llColor(f.properties.value),fillOpacity:llOpacidad,stroke:false};
    }}));
  }catch(e){ console.error('Campo lluvia:',e); }
}

// Etiquetas de las poblaciones sobre el mapa. Con el mapa alejado varias
// caen casi encima (Totana-Aledo, Alhama-Librilla), así que se colocan por
// orden de prioridad y se descarta la que pisaría a otra ya puesta; al
// hacer zoom vuelven a aparecer. Los valores exactos de todas están
// siempre en la tabla de abajo.
var llPobDatos=null, llPobVen=null;
function llPintarPoblaciones(datosPob,ven){
  llPobDatos=datosPob||null;
  llPobVen=ven||null;
  llDibujarPoblaciones();
}
// Separado del anterior para poder recolocar las etiquetas al hacer zoom
// sin tocar los datos (y sin arrastrar los del modelo anterior si el
// modelo activo se ha quedado sin respuesta).
function llDibujarPoblaciones(){
  if(!llCapaPtos) return;
  llCapaPtos.clearLayers();
  if(!llPobDatos||!llPobVen) return;
  var puestos=[];
  LL_POBLACIONES.map(function(p,i){ return {p:p,i:i}; })
    .sort(function(a,b){ return (a.p.pri||9)-(b.p.pri||9); })
    .forEach(function(o){
      var pt=llMapa.latLngToLayerPoint([o.p.lat,o.p.lon]);
      for(var k=0;k<puestos.length;k++)
        if(Math.abs(puestos[k].x-pt.x)<38 && Math.abs(puestos[k].y-pt.y)<20) return;
      puestos.push(pt);
      var a=llAcumular(llPobDatos[o.i],llPobVen), v=llVal(a);
      var bg=llColor(v)||'#f1f5f9';
      var html='<div class="ll-pin" style="background:'+bg+';color:'+llColorTexto(v)+';">'
        +llFmt(a)+'</div>';
      L.marker([o.p.lat,o.p.lon],{icon:L.divIcon({className:'',html:html,iconSize:[34,18],iconAnchor:[17,9]})})
        .bindTooltip('<b>'+o.p.n+'</b><br>'+llFmt(a)+' mm',{direction:'top',offset:[0,-10]})
        .addTo(llCapaPtos);
    });
}

function llPintarLeyenda(){
  var el=document.getElementById('vl-leyenda');
  if(!el) return;
  var celdas=LL_ESCALA.slice(0,LL_ESCALA.length-1).map(function(e){
    var et=LL_ETIQ_LEYENDA.indexOf(e.v)>=0?String(e.v):'';
    return '<div class="ll-lg-cel"><span class="ll-lg-col" style="background:'+e.c+'"></span>'
      +'<span class="ll-lg-txt">'+et+'</span></div>';
  }).join('');
  el.innerHTML='<div class="ll-lg-tit">Precipitación acumulada (mm)</div>'
    +'<div class="ll-lg-barra">'+celdas+'</div>';
}

// ── Comparativa de modelos en las poblaciones del valle ─────
function llRenderComparativa(ven,dias,token){
  var cont=document.getElementById('vl-tabla');
  if(!cont) return;
  cont.innerHTML='<div class="ll-nota">⏳ Comparando modelos en el valle…</div>';
  var pts=LL_POBLACIONES.map(function(p){ return {lat:p.lat,lon:p.lon}; });
  var pend=LL_MODELOS.map(function(m){
    return llPedir(pts,m.id,'pob',dias)
      .then(function(d){ return {id:m.id,datos:d}; })
      .catch(function(){ return {id:m.id,datos:null}; });
  });
  Promise.all(pend).then(function(res){
    if(token!==llPeticion) return;
    var porModelo={};
    res.forEach(function(r){ porModelo[r.id]=r.datos; });
    llPintarPoblaciones(porModelo[llModelo],ven);

    var disponibles=LL_MODELOS.filter(function(m){ return porModelo[m.id]; });
    if(!disponibles.length){
      cont.innerHTML='<div class="ll-nota">⚠ No se ha podido cargar la comparativa de modelos.</div>';
      return;
    }
    var th=disponibles.map(function(m){
      return '<th'+(m.id===llModelo?' class="ll-col-act"':'')+' title="'+m.det+'">'
        +(m.top?'⭐ ':'')+m.nombre+'</th>';
    }).join('');
    var filas=LL_POBLACIONES.map(function(p,i){
      var vals=[],tds='';
      disponibles.forEach(function(m){
        var a=llAcumular(porModelo[m.id][i],ven), v=llVal(a);
        if(v!=null) vals.push(v);
        var bg=llColor(v);
        tds+='<td'+(m.id===llModelo?' class="ll-col-act"':'')+' style="'
          +(bg?'background:'+bg+';color:'+llColorTexto(v)+';':'')+'">'+llFmt(a)+'</td>';
      });
      var media=vals.length?vals.reduce(function(x,y){return x+y;},0)/vals.length:null;
      var bgm=llColor(media);
      return '<tr><th class="ll-pob">'+p.n+'</th>'+tds
        +'<td class="ll-media" style="'+(bgm?'background:'+bgm+';color:'+llColorTexto(media)+';':'')+'">'
        +llFmt(media==null?null:{v:media,cob:1})+'</td></tr>';
    }).join('');

    cont.innerHTML='<div class="ll-tabla-tit">🌧 Acumulado previsto por modelo (mm) — poblaciones del valle</div>'
      +'<div class="ll-tabla-scroll"><table class="ll-tabla"><tr><th></th>'+th
      +'<th class="ll-media">Media</th></tr>'+filas+'</table></div>'
      +'<div class="ll-nota">⭐ <b>ECMWF</b> (referencia mundial) e <b>ICON-EU</b> (7 km, la mayor resolución que cubre Murcia) '
      +'son los más fiables en el sureste peninsular; ARPEGE aporta bien los temporales mediterráneos. '
      +'Cuando los modelos coinciden, la previsión es sólida; si se separan mucho, la incertidumbre es alta y conviene '
      +'quedarse con la <b>media</b>. Un <b>*</b> indica que ese modelo no alcanza todo el plazo (acumulado parcial). '
      +'Toca cualquier punto del mapa para ver la comparativa ahí mismo.</div>'
      +'<div class="ll-fuente">Fuente: Open-Meteo (datos abiertos ECMWF · DWD · Météo-France · Met Office · NOAA)</div>';
  });
}

// ── Consulta puntual al pinchar en el mapa ──────────────────
function llClickMapa(e){
  var lat=Math.round(e.latlng.lat*1000)/1000, lon=Math.round(e.latlng.lng*1000)/1000;
  var ven=llVentana(llHoras), dias=llDias(llHoras);
  var pop=L.popup({maxWidth:260}).setLatLng(e.latlng)
    .setContent('<div style="font-size:12px;">⏳ Consultando modelos…</div>').openOn(llMapa);
  var pts=[{lat:lat,lon:lon}], amb='punto'+lat+','+lon;
  Promise.all(LL_MODELOS.map(function(m){
    return llPedir(pts,m.id,amb,dias)
      .then(function(d){ return {m:m,a:llAcumular(d[0],ven)}; })
      .catch(function(){ return {m:m,a:null}; });
  })).then(function(res){
    var vals=res.filter(function(r){return r.a!=null;}).map(function(r){return r.a.v;});
    var media=vals.length?vals.reduce(function(x,y){return x+y;},0)/vals.length:null;
    var filas=res.map(function(r){
      var v=llVal(r.a), bg=llColor(v);
      return '<tr><td style="padding:2px 6px;">'+(r.m.top?'⭐ ':'')+r.m.nombre+'</td>'
        +'<td style="padding:2px 6px;text-align:right;font-weight:700;'
        +(bg?'background:'+bg+';color:'+llColorTexto(v)+';':'')+'">'+llFmt(r.a)+'</td></tr>';
    }).join('');
    pop.setContent('<div style="font-size:12px;">'
      +'<div style="font-weight:700;margin-bottom:4px;">📍 '+lat.toFixed(2)+', '+lon.toFixed(2)+'</div>'
      +'<div style="color:#64748b;font-size:10.5px;margin-bottom:6px;">Acumulado '+llHoras+' h (mm)</div>'
      +'<table style="border-collapse:collapse;font-size:11.5px;">'+filas
      +'<tr><td style="padding:2px 6px;border-top:1px solid rgba(15,23,42,.15);font-weight:700;">Media</td>'
      +'<td style="padding:2px 6px;text-align:right;font-weight:700;border-top:1px solid rgba(15,23,42,.15);">'
      +llFmt(media==null?null:{v:media,cob:1})+'</td></tr></table></div>');
  });
}

// Mostrar aviso de días si procede
if(AVISO_DIAS){
  var av=document.getElementById('aviso-dias');
  if(av){av.textContent=AVISO_DIAS;av.style.display='block';}
}

// Devuelve true si la estación lleva >30 min sin datos nuevos (solo en frame actual)
function esEstiado(est){
  var indices=getModoIndices();
  if(idxActual<indices.length-1) return false; // no aplicar en historial
  if(!est.epoch) return false;
  return (Date.now()/1000-est.epoch)>1800;
}

// ── Render principal ───────────────────────────────────────
function render(){
  var p=document.getElementById('ps').value;
  var isR=p==='oidio'||p==='mildiu';
  var pRender=p;
  leg.upd(p);
  if(heatActive) hLG.clearLayers(); mLG.clearLayers(); HL=null;

  var snap=isR?historyData[historyData.length-1]:activeData[CI];
  if(!snap) return;
  var feats=[];

  (snap.stations||[]).forEach(function(est){
    if(!est||est.lat==null||est.lon==null) return;
    var v=raw(est,pRender,snap.timestamp); if(v==null) return;
    var bg=col(v,pRender);
    var lb;
    if(isR)             lb=v<0?'?':['0','B','M','A'][Math.min(3,Math.max(0,Math.round(v)))];
    else if(pRender==='precip') lb=v.toFixed(1);
    else if(pRender==='temp')   lb=Math.round(v)+'°';
    else                        lb=Math.round(v)+'';

    var ws='';
    if(pRender==='wind'&&est.winddir!=null)
      ws='<svg style="position:absolute;top:-13px;left:-13px;width:50px;height:50px;'
        +'transform:rotate('+est.winddir+'deg);z-index:-1;pointer-events:none;"'
        +' viewBox="0 0 50 50"><line x1="25" y1="2" x2="25" y2="13" stroke="#333" stroke-width="2.5"/></svg>';

    var estiado=esEstiado(est);
    var ih='<div style="position:relative;'+(estiado?'opacity:0.45;filter:grayscale(55%);':'')+'">'
      +'<div style="background:'+bg+';color:#fff;text-shadow:1px 1px 2px rgba(0,0,0,.7);'
      +'border:1.5px solid '+(estiado?'#aaa':'#fff')+';border-radius:50%;width:26px;height:26px;display:flex;'
      +'justify-content:center;align-items:center;font-weight:700;font-size:10px;'
      +'box-shadow:0 2px 5px rgba(0,0,0,.35);cursor:pointer;">'+lb+'</div>'
      +(estiado?'<div style="position:absolute;bottom:-6px;right:-6px;font-size:9px;line-height:1;">⏱</div>':'')
      +ws+'</div>';

    var mk=L.marker([est.lat,est.lon],{
      icon:L.divIcon({className:'',html:ih,iconSize:[26,26],iconAnchor:[13,13]})
    });

    var nm=NOMBRES[est.stationID]
      ||(est.neighborhood&&est.neighborhood.trim()!==''?est.neighborhood:est.stationID);

    // ── Contenido panel ────────────────────────────────
    var ph;
    if(isR){
      var r=riesgoData[est.stationID];
      if(r){
        var nO=r.oidio, nM=r.mildiu, det=r.detalles||{};
        var dO=(det.oidio||[]).join('<br>&bull; ');
        var dM=(det.mildiu||[]).join('<br>&bull; ');
        var av='';
        if(!r.datos_ok){
          var nd=r.dias_disponibles, falt=5-nd;
          av='<div style="background:#e8f4fd;border:1px solid #b3d7f0;border-radius:6px;'
            +'padding:8px 10px;margin-bottom:10px;font-size:12px;color:#1a5276;">'
            +'⏳ <b>Acumulando historial</b><br>'
            +nd+' de 5 días necesarios. Faltan <b>'+falt+'</b> día'+(falt>1?'s':'')+'.<br>'
            +'<span style="color:#666;">El mapa calculará el riesgo automáticamente.</span></div>';
        }
        // ── Panel según enfermedad seleccionada ──────────────
        var esOidio = (p==='oidio');

        if(esOidio) {
          // ── OÍDIO ────────────────────────────────────────────
          var dsv=r.dsv_temporada||0;
          var dsvPct=Math.min(100,Math.round(dsv/60*100));
          var dsvCol=dsv<20?'#27ae60':dsv<40?'#f39c12':dsv<60?'#e67e22':'#c0392b';
          var dsvLabel=dsv<20?'Sin riesgo':dsv<40?'Vigilancia':dsv<60?'Tratar pronto':'Urgente';

          ph=av
            // Nivel y barra DSV
            +'<div style="margin-bottom:6px;">'
            +'<b>🍇 Oídio:</b> <span style="padding:2px 9px;border-radius:10px;font-size:12px;'
            +'font-weight:700;color:#fff;background:'+(nO<0?'#aaa':RC[nO])+'">'
            +(nO<0?'Pendiente':RL[nO])+'</span></div>'
            +'<div style="font-size:12px;color:#555;margin-bottom:10px;">&bull; '+(dO||'—')+'</div>'
            // Barra DSV temporada
            +'<div style="background:#f8f8f8;border-radius:8px;padding:10px;margin-bottom:10px;">'
            +'<div style="display:flex;justify-content:space-between;font-size:11px;color:#888;margin-bottom:4px;">'
            +'<span>DSV acumulado temporada</span>'
            +'<span style="font-weight:700;color:'+dsvCol+'">'+dsv+' pts — '+dsvLabel+'</span></div>'
            +'<div style="background:#e0e0e0;border-radius:4px;height:10px;overflow:hidden;">'
            +'<div style="background:'+dsvCol+';width:'+dsvPct+'%;height:100%;border-radius:4px;"></div></div>'
            +'<div style="display:flex;justify-content:space-between;font-size:10px;color:#bbb;margin-top:3px;">'
            +'<span>0</span><span>20⚠</span><span>40🔶</span><span>60🔴</span></div>'
            +'<div style="font-size:11px;color:#999;margin-top:4px;">DSV últimos 7d='+(r.dsv_7d||0)+' &nbsp;|&nbsp; DSV hoy='+(r.dsv_hoy||0)+'</div>'
            +'</div>'
            // Datos actuales
            +'<hr style="border:0;border-top:1px solid #eee;margin:8px 0;">'
            +'<div style="font-size:12px;color:#666;margin-bottom:10px;">'
            +'🌡 Tmed='+(det.temp_actual!=null?det.temp_actual.toFixed(1)+'°C':'—')
            +' &nbsp;💧 HR='+(det.hum_actual!=null?det.hum_actual+'%':'—')+'<br>'
            +'⏱ HR alta='+(det.horas_hum_alta_7d||0)+'h (últimos 7d)'
            +'</div>'
            // Explicación del modelo
            +'<div style="background:#f0f7ff;border-left:3px solid #3498db;border-radius:4px;padding:10px;font-size:11px;color:#444;line-height:1.6;">'
            +'<b style="color:#2c3e50;">📖 Modelo Gubler-Thomas (UC Davis, 1982)</b><br><br>'
            +'Acumula puntos <b>DSV</b> (Disease Severity Values) diarios cruzando temperatura media y horas de humedad alta:<br><br>'
            +'<table style="width:100%;border-collapse:collapse;font-size:10px;margin-bottom:6px;">'
            +'<tr style="background:#dce8f5;"><td style="padding:2px 4px;font-weight:bold;">Tmed</td><td style="padding:2px 4px;text-align:center;">0-6h</td><td style="padding:2px 4px;text-align:center;">7-12h</td><td style="padding:2px 4px;text-align:center;">13-18h</td><td style="padding:2px 4px;text-align:center;">&gt;18h</td></tr>'
            +'<tr><td style="padding:2px 4px;">15-19°C</td><td style="text-align:center;padding:2px 4px;">1</td><td style="text-align:center;padding:2px 4px;">2</td><td style="text-align:center;padding:2px 4px;">3</td><td style="text-align:center;padding:2px 4px;">4</td></tr>'
            +'<tr style="background:#f5f5f5;"><td style="padding:2px 4px;">19-22°C</td><td style="text-align:center;padding:2px 4px;">2</td><td style="text-align:center;padding:2px 4px;">3</td><td style="text-align:center;padding:2px 4px;">4</td><td style="text-align:center;padding:2px 4px;">5</td></tr>'
            +'<tr><td style="padding:2px 4px;">22-26°C</td><td style="text-align:center;padding:2px 4px;">3</td><td style="text-align:center;padding:2px 4px;">4</td><td style="text-align:center;padding:2px 4px;">5</td><td style="text-align:center;padding:2px 4px;">6</td></tr>'
            +'<tr style="background:#f5f5f5;"><td style="padding:2px 4px;">26-40°C</td><td style="text-align:center;padding:2px 4px;">2</td><td style="text-align:center;padding:2px 4px;">3</td><td style="text-align:center;padding:2px 4px;">4</td><td style="text-align:center;padding:2px 4px;">5</td></tr>'
            +'<tr><td style="padding:2px 4px;color:#888;">&lt;15°C o &gt;40°C</td><td colspan="4" style="text-align:center;padding:2px 4px;color:#888;">0 — sin desarrollo</td></tr>'
            +'</table>'
            +'<b>Lluvia &gt;2.5mm:</b> lava las esporas → DSV=0 ese día<br>'
            +'<b>Umbrales de tratamiento:</b><br>'
            +'&nbsp;· &lt;20 pts → Sin riesgo<br>'
            +'&nbsp;· 20-40 pts → Vigilancia<br>'
            +'&nbsp;· 40-60 pts → Tratar pronto<br>'
            +'&nbsp;· &gt;60 pts → Tratamiento urgente'
            +'</div>'
            +'<div style="font-size:11px;color:#aaa;margin-top:8px;">📊 '+r.fuente_datos+'</div>';

        } else {
          // ── MILDIU ───────────────────────────────────────────
          ph=av
            +'<div style="margin-bottom:6px;">'
            +'<b>🍃 Mildiu:</b> <span style="padding:2px 9px;border-radius:10px;font-size:12px;'
            +'font-weight:700;color:#fff;background:'+(nM<0?'#aaa':RC[nM])+'">'
            +(nM<0?'Pendiente':RL[nM])+'</span></div>'
            +'<div style="font-size:12px;color:#555;margin-bottom:10px;">&bull; '+(dM||'—')+'</div>'
            // Fecha síntomas si procede
            +(r.fecha_sintomas?'<div style="background:#fef9e7;border:1px solid #f39c12;'
            +'border-radius:6px;padding:8px 10px;font-size:12px;margin-bottom:10px;">'
            +'📅 Síntomas estimados: <b>'+r.fecha_sintomas+'</b><br>'
            +'<span style="font-size:11px;color:#888;">Período de incubación según Tmed actual</span></div>':'')
            // Datos actuales
            +'<hr style="border:0;border-top:1px solid #eee;margin:8px 0;">'
            +'<div style="font-size:12px;color:#666;margin-bottom:10px;">'
            +'🌡 Tmed='+(det.temp_actual!=null?det.temp_actual.toFixed(1)+'°C':'—')
            +' &nbsp;💧 HR='+(det.hum_actual!=null?det.hum_actual+'%':'—')+'<br>'
            +'🌧 Lluvia 10d='+(det.precip_10dias||0)+'mm'
            +'</div>'
            // Explicación del modelo
            +'<div style="background:#f0fff4;border-left:3px solid #27ae60;border-radius:4px;padding:10px;font-size:11px;color:#444;line-height:1.6;">'
            +'<b style="color:#2c3e50;">📖 Modelo 10-10-10 + EPI (Plasmopara viticola)</b><br><br>'
            +'Requiere las <b>3 condiciones simultáneas</b> para infección primaria:<br><br>'
            +'<b>1. Temperatura mínima &gt;10°C</b><br>'
            +'&nbsp;&nbsp;El hongo necesita suelo &gt;8-10°C para activarse.<br><br>'
            +'<b>2. Lluvia acumulada ≥10mm en 10 días</b><br>'
            +'&nbsp;&nbsp;Activa las oosporas del suelo y permite la infección.<br><br>'
            +'<b>3. Historial suficiente (≥5 días)</b><br>'
            +'&nbsp;&nbsp;Proxy del desarrollo vegetativo de la vid.<br><br>'
            +'<b>Refinamiento EPI:</b><br>'
            +'&nbsp;· Tmed 18-24°C + HR≥85% → riesgo máximo<br>'
            +'&nbsp;· T&gt;30°C → inhibe esporulación<br><br>'
            +'<b>Período de incubación (aparición síntomas):</b><br>'
            +'<table style="width:100%;border-collapse:collapse;font-size:10px;">'
            +'<tr style="background:#c8f0d8;"><td style="padding:2px 4px;font-weight:bold;">Tmed</td><td style="padding:2px 4px;font-weight:bold;">Días hasta síntomas</td></tr>'
            +'<tr><td style="padding:2px 4px;">&lt;12°C</td><td style="padding:2px 4px;">Sin desarrollo</td></tr>'
            +'<tr style="background:#f5f5f5;"><td style="padding:2px 4px;">12-15°C</td><td style="padding:2px 4px;">21 días</td></tr>'
            +'<tr><td style="padding:2px 4px;">15-18°C</td><td style="padding:2px 4px;">15 días</td></tr>'
            +'<tr style="background:#f5f5f5;"><td style="padding:2px 4px;">18-21°C</td><td style="padding:2px 4px;">10 días</td></tr>'
            +'<tr><td style="padding:2px 4px;">21-25°C</td><td style="padding:2px 4px;">7 días</td></tr>'
            +'<tr style="background:#f5f5f5;"><td style="padding:2px 4px;">25-30°C</td><td style="padding:2px 4px;">6 días</td></tr>'
            +'<tr><td style="padding:2px 4px;">&gt;30°C</td><td style="padding:2px 4px;">Inhibición</td></tr>'
            +'</table>'
            +'</div>'
            +'<div style="font-size:11px;color:#aaa;margin-top:8px;">📊 '+r.fuente_datos+'</div>';
        }
      } else {
        ph='<div style="color:#999;font-size:13px;line-height:1.7;">Sin datos de riesgo.</div>';
      }
    } else {
      var m=est.metric||{};
      var minutos_sin_datos=est.epoch?Math.round((Date.now()/1000-est.epoch)/60):null;
      var avisoEstiado=(minutos_sin_datos!=null&&minutos_sin_datos>30)
        ?'<div style="background:#fff3cd;border:1px solid #ffc107;border-radius:6px;'
        +'padding:6px 10px;margin-bottom:10px;font-size:11px;color:#856404;">'
        +'⏱ Sin actualizar desde hace <b>'+minutos_sin_datos+' min</b> — dato antiguo</div>':'';
      var sensacion=m.heatIndex!=null&&m.heatIndex!==m.temp?m.heatIndex:(m.windChill!=null&&m.windChill!==m.temp?m.windChill:null);
      ph=avisoEstiado
        +'<table style="width:100%;font-size:13px;border-collapse:collapse;line-height:2;">'
        +'<tr><td style="color:#888">🌡 Temperatura</td>'
        +'<td style="font-weight:700">'+(m.temp!=null?m.temp.toFixed(1)+'°C':'—')+'</td></tr>'
        +(sensacion!=null?'<tr><td style="color:#888">🌡 Sensación</td>'
        +'<td style="font-weight:700">'+sensacion.toFixed(1)+'°C</td></tr>':'')
        +'<tr><td style="color:#888">🌧 Precipitación</td>'
        +'<td style="font-weight:700">'+(function(){
          var acum=getPrecipHoraDe(est.stationID,snap.timestamp);
          return acum!=null?(acum.toFixed(1)+' mm (1h)'):( m.precipTotal!=null?m.precipTotal.toFixed(1)+' mm':'—');
        })()+' </td></tr>'
        +'<tr><td style="color:#888">💨 Viento</td>'
        +'<td style="font-weight:700">'+(m.windSpeed!=null?m.windSpeed.toFixed(0)+' km/h':'—')+' '+wdL(est.winddir)+'</td></tr>'
        +'<tr><td style="color:#888">⬆ Racha</td>'
        +'<td style="font-weight:700">'+(m.windGust!=null?m.windGust.toFixed(0)+' km/h':'—')+'</td></tr>'
        +'<tr><td style="color:#888">💧 Humedad</td>'
        +'<td style="font-weight:700">'+(est.humidity!=null?est.humidity+'%':'—')+'</td></tr>'
        +(m.dewpt!=null?'<tr><td style="color:#888">💧 Pto. rocío</td>'
        +'<td style="font-weight:700">'+m.dewpt.toFixed(1)+'°C</td></tr>':'')
        +(m.pressure!=null?'<tr><td style="color:#888">📊 Presión</td>'
        +'<td style="font-weight:700">'+m.pressure.toFixed(1)+' hPa</td></tr>':'')
        +(est.solarRadiation!=null?'<tr><td style="color:#888">☀️ Radiación</td>'
        +'<td style="font-weight:700">'+Math.round(est.solarRadiation)+' W/m²</td></tr>':'')
        +(est.uv!=null?'<tr><td style="color:#888">🔆 Índice UV</td>'
        +'<td style="font-weight:700">'+est.uv+'</td></tr>':'')
        +'<tr><td style="color:#888">🕒 Observación</td>'
        +'<td>'+(est.obsTimeLocal?est.obsTimeLocal.slice(11,16):'—')+'</td></tr>'
        +'</table>'
        +'<a href="https://www.wunderground.com/dashboard/pws/'+est.stationID
        +'" target="_blank" style="display:inline-block;margin-top:12px;padding:7px 16px;'
        +'background:#3498db;color:#fff;text-decoration:none;border-radius:6px;font-size:12px;">'
        +'Ver historial en WU ↗</a>';
    }

    var fh='<div style="font-size:15px;font-weight:700;color:#f1f5f9;margin-bottom:4px;">'+nm+'</div>'
      +'<div style="font-size:11px;color:#6b7280;margin-bottom:12px;">'+est.stationID+'</div>'+ph;

    (function(id,h){mk.on('click',function(){showPanel(id,h);});})(est.stationID,fh);
    mk.bindTooltip('<b>'+nm+'</b>'+(estiado?' ⏱':''),{direction:'top',offset:[0,-16],opacity:0.9});
    mLG.addLayer(mk);
    feats.push(turf.point([est.lon,est.lat],{value:v}));
  });

  // Heatmap interpolado — nos ahorramos el cálculo entero (turf.interpolate
  // es lo más caro con diferencia, ~200ms con las estaciones actuales) si
  // la capa ni siquiera está activa, ya que el resultado no se usaría.
  var validFeats = isR ? feats.filter(function(f){return f.properties.value>=0;}) : feats;
  if(heatActive && validFeats.length>2){
    try{
      var c=turf.featureCollection(validFeats);
      var weight=pRender==='temp'?2:pRender==='oidio'||pRender==='mildiu'?6:4;
      // Celda de rejilla más grande que el original (2.5-3km): con la
      // zona cubierta ahora mucho más extensa (Almería-Albacete-Benidorm)
      // y más estaciones, una rejilla fina dispara el nº de celdas y el
      // tiempo de cálculo. Con 4-4.5km se ve igual de suave y es ~2.5x
      // más rápido.
      var g=turf.interpolate(c,pRender==='oidio'||pRender==='mildiu'?4.5:4,
        {gridType:'square',property:'value',units:'kilometers',weight:weight});
      var cl=turf.featureCollection(g.features.filter(function(f){
        return f.properties.value!=null&&!isNaN(f.properties.value);
      }));
      HL=L.geoJSON(cl,{pane:'hp',style:function(f){
        var v=f.properties.value;
        if(pRender==='oidio'||pRender==='mildiu') v=Math.min(3,Math.max(0,Math.round(v)));
        return{fillColor:col(v,pRender),fillOpacity:window.HO,stroke:false};
      }});
      hLG.clearLayers();
      hLG.addLayer(HL);
    }catch(e){console.error('Heatmap:',e);}
  }
}

// ── Slider máquina del tiempo ──────────────────────────────
var sl=document.getElementById('sl');
var tl=document.getElementById('tl');
var tlSub=document.getElementById('tl-sub');
var tmOffset=document.getElementById('tm-offset');
var tmCounter=document.getElementById('tm-counter');
var tmLive=document.getElementById('tm-live');
var tmPeriodos=document.getElementById('tm-periodos');
var slFechaIni=document.getElementById('sl-fecha-ini');
var slFechaFin=document.getElementById('sl-fecha-fin');
var slSep=document.getElementById('sl-sep');
var velocidadMs=500;

// ── Periodos disponibles ──────────────────────────────────────
// 24h: usa historyData embebido (resolución 5 min, ya viene con la página)
// 2d/7d: se descargan bajo demanda (resolución 30 min / 3 h) para no
// disparar el tamaño de la página en la carga inicial.
// 6h y 12h no descargan nada: son el propio historial de 24h recortado a
// las últimas N horas. Conservan su misma resolución, pero repartida en
// una ventana más corta, así que cada paso del slider cubre menos tiempo
// real: es lo que hace falta para seguir un chubasco de cerca.
var PERIODOS={
  '6h': {archivo:null, horas:6},
  '12h':{archivo:null, horas:12},
  '24h':{archivo:null},
  '2d': {archivo:'history_2d.json'},
  '7d': {archivo:'history_7d.json'}
};

// Recorta un historial a sus últimas N horas. Si el recorte se quedara
// vacío (hueco de datos), se devuelve el último snapshot para no dejar
// el slider sin nada que mostrar.
function recortarHoras(datos,horas){
  if(!horas||!datos||!datos.length) return datos;
  var limite=Date.now()-horas*3600*1000;
  var r=datos.filter(function(e){
    var t=new Date(e.timestamp).getTime();
    return !isNaN(t) && t>=limite;
  });
  return r.length?r:datos.slice(-1);
}

// Dataset que corresponde al periodo activo cuando no hay descarga de por
// medio (6h/12h/24h). Se usa también al refrescar historyData.
function datosLocales(){
  var cfg=PERIODOS[periodoActivo];
  return (cfg&&cfg.horas)?recortarHoras(historyData,cfg.horas):historyData;
}
var periodoActivo='24h';
var extData={};        // caché de periodos descargados: {'2d':[...], '7d':[...]}
var activeData=historyData;   // dataset que alimenta el slider en modo no-riesgo

// ── Índices por día (para oidio/mildiu) ────────────────────────
var diaIdx = [];   // índices en historyData, uno por día

function construirDiaIdx(){
  diaIdx = [];
  var porDia={};
  historyData.forEach(function(e,i){
    var d=new Date(e.timestamp);
    var mm=String(d.getMonth()+1).padStart(2,'0');
    var dd=String(d.getDate()).padStart(2,'0');
    var dk=d.getFullYear()+'-'+mm+'-'+dd;
    porDia[dk]=i;   // última lectura de cada día
  });
  Object.keys(porDia).sort().forEach(function(k){
    diaIdx.push({key:k, idx:porDia[k]});
  });
}
construirDiaIdx();

var modoRiesgo=false;
var idxActual=activeData.length-1;  // índice dentro de activeData o diaIdx
var diaFiltroIni='', diaFiltroFin='';

function getModoIndices(){
  if(!modoRiesgo){
    var idxs=[];
    for(var i=0;i<activeData.length;i++) idxs.push(i);
    return idxs;
  }
  // Filtrar diaIdx por rango seleccionado
  if(!diaFiltroIni && !diaFiltroFin) return diaIdx.map(function(d){return d.idx;});
  return diaIdx.filter(function(d){
    return (!diaFiltroIni || d.key>=diaFiltroIni) && (!diaFiltroFin || d.key<=diaFiltroFin);
  }).map(function(d){return d.idx;});
}

// Descarga (con caché) el histórico del periodo seleccionado y lo
// convierte en el dataset activo del slider.
function cargarPeriodo(p, cb){
  var cfg=PERIODOS[p]||PERIODOS['24h'];
  if(!cfg.archivo){ activeData=cfg.horas?recortarHoras(historyData,cfg.horas):historyData; cb(); return; }
  if(extData[p]){ activeData=extData[p]; cb(); return; }
  sl.disabled=true;
  fetch(PERIODOS[p].archivo+'?v='+Date.now())
    .then(function(r){return r.json();})
    .then(function(datos){
      extData[p]=(datos&&datos.length)?datos:historyData;
      activeData=extData[p];
      sl.disabled=false;
      cb();
    })
    .catch(function(){
      periodoActivo='24h';
      tmPeriodos.querySelectorAll('.tm-per-btn').forEach(function(b){
        b.classList.toggle('active', b.getAttribute('data-per')==='24h');
      });
      activeData=historyData;
      sl.disabled=false;
      cb();
    });
}

function actualizarModoSlider(){
  var p=document.getElementById('ps').value;
  modoRiesgo=(p==='oidio'||p==='mildiu');
  var indices=getModoIndices();
  sl.min=0; sl.max=Math.max(0,indices.length-1); sl.value=indices.length-1;
  idxActual=indices.length-1;

  if(modoRiesgo){
    tmPeriodos.style.display='none';
    sl.style.display='none';
    tmCounter.style.display='none';
    slFechaIni.style.display='';
    slFechaFin.style.display='';
    slSep.style.display='';
    if(diaIdx.length>0){
      slFechaIni.value=diaIdx[0].key;
      slFechaFin.value=diaIdx[diaIdx.length-1].key;
      diaFiltroIni=diaIdx[0].key;
      diaFiltroFin=diaIdx[diaIdx.length-1].key;
    }
  } else {
    tmPeriodos.style.display='';
    sl.style.display='';
    tmCounter.style.display='';
    slFechaIni.style.display='none';
    slFechaFin.style.display='none';
    slSep.style.display='none';
  }
  actualizarLabel();
}

tmPeriodos.querySelectorAll('.tm-per-btn').forEach(function(btn){
  btn.addEventListener('click', function(){
    var p=this.getAttribute('data-per');
    if(p===periodoActivo) return;
    periodoActivo=p;
    tmPeriodos.querySelectorAll('.tm-per-btn').forEach(function(b){
      b.classList.toggle('active', b===btn);
    });
    cargarPeriodo(periodoActivo, function(){
      actualizarModoSlider();
      render();
    });
  });
});

document.getElementById('tm-speed').querySelectorAll('.tm-vel-btn').forEach(function(btn){
  btn.addEventListener('click', function(){
    velocidadMs=parseInt(this.getAttribute('data-vel'));
    document.getElementById('tm-speed').querySelectorAll('.tm-vel-btn').forEach(function(b){
      b.classList.toggle('active', b===btn);
    });
    if(PT){ clearInterval(PT); PT=setInterval(avanzarFrame, velocidadMs); }
  });
});

tmLive.addEventListener('click', function(){
  if(PT){ clearInterval(PT); PT=null; document.getElementById('pb').textContent='▶'; }
  var indices=getModoIndices();
  idxActual=indices.length-1;
  sl.value=idxActual;
  actualizarLabel();
  render();
});

function actualizarLabel(){
  var indices=getModoIndices();
  if(!indices.length){
    tl.textContent='--:--'; tlSub.textContent='Sin datos';
    return;
  }
  var idx=indices[Math.min(idxActual,indices.length-1)];
  var fuente=modoRiesgo?historyData:activeData;
  var ts=fuente[idx].timestamp;
  var last=idxActual===indices.length-1;
  if(radarChk&&radarChk.checked){
    // En el frame "actual" usamos el reloj real (no el timestamp del último
    // dato propio, que puede llevar unos minutos de retraso) para no marcar
    // la vista en vivo como fuera de rango por un desfase de ciclos.
    var refRadar=last?Date.now()/1000:new Date(ts).getTime()/1000;
    actualizarFrameRadar(Math.round(refRadar));
  }

  tmCounter.textContent=(Math.min(idxActual,indices.length-1)+1)+' / '+indices.length;
  tmLive.classList.toggle('mostrar', !last);

  if(modoRiesgo){
    var d=new Date(ts);
    var fechaCorta=d.toLocaleDateString('es-ES',{day:'2-digit',month:'2-digit'});
    var fechaLarga=d.toLocaleDateString('es-ES',{weekday:'long',day:'2-digit',month:'long'});
    fechaLarga=fechaLarga.charAt(0).toUpperCase()+fechaLarga.slice(1);
    tl.textContent=fechaCorta;
    tlSub.textContent=fechaLarga;
    tmOffset.textContent=last?'HOY':'HISTÓRICO';
    tmOffset.classList.toggle('en-vivo', last);
  } else {
    var d2=new Date(ts);
    var horaStr=d2.toLocaleTimeString('es-ES',{hour:'2-digit',minute:'2-digit'});
    var fechaStr=d2.toLocaleDateString('es-ES',{day:'2-digit',month:'short'}).replace('.','').toUpperCase();
    var diffMin=Math.round((Date.now()-d2.getTime())/60000);
    var relTxt;
    if(last || diffMin<=1) relTxt='EN VIVO';
    else if(diffMin<60) relTxt='hace '+diffMin+' min';
    else{
      var h=Math.floor(diffMin/60), m=diffMin%60;
      relTxt='hace '+h+'h'+(m?' '+m+'min':'');
    }
    tl.textContent=horaStr;
    tlSub.textContent=fechaStr+' · '+relTxt;
    tmOffset.textContent=relTxt;
    tmOffset.classList.toggle('en-vivo', last);
  }
}

// ── Render con soporte historial ─────────────────────────────
// ── Render con historial de riesgo ──────────────────────────
var _renderOriginal = render;

render = function(){
  var p   = document.getElementById('ps').value;
  var isR = p==='oidio' || p==='mildiu';

  // Calcular índice correcto según modo
  var indices = getModoIndices();
  if(indices.length > 0){
    CI = indices[Math.min(idxActual, indices.length-1)];
  }

  // En modo riesgo usar datos históricos del día seleccionado
  if(isR && riesgoHistData && Object.keys(riesgoHistData).length > 0){
    var ts       = historyData[CI] ? historyData[CI].timestamp : '';
    var fechaDia = ts.slice(0, 10);
    if(riesgoHistData[fechaDia]){
      var rdBak = riesgoData;
      var rTemp = {};
      Object.keys(rdBak).forEach(function(sid){
        rTemp[sid] = Object.assign({}, rdBak[sid]);
        var h = riesgoHistData[fechaDia][sid];
        if(h){
          rTemp[sid].oidio         = h.oidio;
          rTemp[sid].mildiu        = h.mildiu;
          rTemp[sid].dsv_temporada = h.dsv_temporada;
          rTemp[sid].dsv_7d        = h.dsv_7d;
          rTemp[sid].datos_ok      = h.datos_ok;
        }
      });
      riesgoData = rTemp;
      _renderOriginal();
      riesgoData = rdBak;
      return;
    }
  }
  _renderOriginal();
};

// ── Slider listeners ─────────────────────────────────────────
var sl2 = document.getElementById('sl');
sl2.addEventListener('input', function(){
  idxActual = parseInt(this.value);
  actualizarLabel();
  render();
});

function avanzarFrame(){
  var indices = getModoIndices();
  idxActual = (idxActual+1) % indices.length;
  sl2.value = idxActual;
  actualizarLabel();
  render();
  if(idxActual === indices.length-1){
    clearInterval(PT); PT=null;
    document.getElementById('pb').textContent='▶';
  }
}

document.getElementById('pb').addEventListener('click', function(){
  if(PT){ clearInterval(PT); PT=null; this.textContent='▶'; return; }
  this.textContent = '⏸';
  var indices = getModoIndices();
  if(idxActual >= indices.length-1) idxActual = 0;
  PT = setInterval(avanzarFrame, velocidadMs);
});

document.getElementById('op').addEventListener('input', function(){
  window.HO = parseFloat(this.value);
  if(HL) HL.setStyle({fillOpacity: window.HO});
});

var riesgoHistCargado=false;
function cargarRiesgoHistorico(cb){
  if(riesgoHistCargado){ if(cb) cb(); return; }
  fetch('historial_riesgo.json?v='+Date.now())
    .then(function(r){return r.json();})
    .then(function(datos){
      riesgoHistData=datos||{};
      riesgoHistCargado=true;
      if(cb) cb();
    })
    .catch(function(){ riesgoHistCargado=true; if(cb) cb(); });
}

function onParamChange(){
  var p = document.getElementById('ps').value;
  var esRiesgo = (p==='oidio'||p==='mildiu');
  var eraRiesgo = (_prevParam==='oidio'||_prevParam==='mildiu');
  if(esRiesgo && !eraRiesgo) _legCollapsed = true; // al entrar en riesgo, plegada por defecto
  _prevParam = p;
  actualizarModoSlider();
  render();
  if(esRiesgo && !riesgoHistCargado) cargarRiesgoHistorico(render);
}

// ── Radar de lluvia: capa independiente, combinable con cualquier parámetro ──
var radarChk = document.getElementById('radar-chk');
if(radarChk){
  radarChk.addEventListener('change', function(){
    if(this.checked){
      actualizarLabel(); // añade la capa y sincroniza el frame con la posición del slider
    } else {
      if(map.hasLayer(rLG)) rLG.remove();
      var aviso=document.getElementById('radar-fuera-rango');
      if(aviso) aviso.style.display='none';
    }
  });
}

// ── Selector de parámetro personalizado (grupo Riesgos plegable) ──
(function(){
  var btn=document.getElementById('ps-btn');
  var btnLabel=document.getElementById('ps-btn-label');
  var menu=document.getElementById('ps-menu');
  var sel=document.getElementById('ps');
  var riesgoHdr=document.getElementById('ps-riesgo-hdr');
  var riesgoSub=document.getElementById('ps-riesgo-sub');
  var opts=menu.querySelectorAll('.ps-opt');

  function etiquetaDe(v){
    for(var i=0;i<opts.length;i++) if(opts[i].getAttribute('data-v')===v) return opts[i].textContent;
    return '';
  }
  function marcarActiva(v){
    for(var i=0;i<opts.length;i++) opts[i].classList.toggle('active', opts[i].getAttribute('data-v')===v);
  }
  function cerrarMenu(){
    menu.classList.remove('open');
    riesgoSub.classList.remove('open'); // se pliega de nuevo al cerrar
    riesgoHdr.querySelector('.ps-caret').textContent='▸';
  }
  function abrirMenu(){
    marcarActiva(sel.value);
    menu.classList.add('open');
  }
  btn.addEventListener('click', function(e){
    e.stopPropagation();
    if(menu.classList.contains('open')) cerrarMenu(); else abrirMenu();
  });
  riesgoHdr.addEventListener('click', function(e){
    e.stopPropagation();
    var abierto=riesgoSub.classList.toggle('open');
    riesgoHdr.querySelector('.ps-caret').textContent=abierto?'▾':'▸';
  });
  for(var i=0;i<opts.length;i++){
    opts[i].addEventListener('click', function(e){
      e.stopPropagation();
      var v=this.getAttribute('data-v');
      sel.value=v;
      btnLabel.textContent=etiquetaDe(v);
      cerrarMenu();
      onParamChange();
    });
  }
  document.addEventListener('click', function(){
    if(menu.classList.contains('open')) cerrarMenu();
  });
})();

function initSl(){
  var n = historyData.length;
  if(!n){ document.getElementById('tl').innerText='Sin datos'; return; }
  actualizarModoSlider();
  render();
}

// Solo se embebe el último snapshot en el HTML (para que el mapa aparezca
// de inmediato con las condiciones actuales); el histórico completo de
// 24h se descarga aparte justo después, y al llegar se reconstruyen los
// índices y se refresca el slider con el rango completo.
function cargarHistoria24hInicial(cb){
  fetch('history_24h.json?v='+Date.now())
    .then(function(r){return r.json();})
    .then(function(datos){
      if(datos && datos.length){
        historyData=datos;
        construirDiaIdx();
        if(!PERIODOS[periodoActivo].archivo) activeData=datosLocales();
      }
    })
    .catch(function(){})
    .then(cb);
}

initSl();
cargarHistoria24hInicial(function(){
  actualizarModoSlider();
  render();
});
"""

HTML_BASE = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>Meteo Guadalentín</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/@turf/turf@6/turf.min.js"></script>
  <style>
    *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
    body{font-family:'Segoe UI',system-ui,sans-serif;background:#0d1117;color:#e6edf3;height:100vh;overflow:hidden}

    /* Mapa a pantalla completa */
    #map{position:fixed;inset:0;z-index:1}

    /* ── Barra superior flotante ── */
    #topbar{
      position:fixed;top:12px;left:12px;right:12px;z-index:1000;
      display:flex;align-items:center;gap:10px;padding:10px 16px;
      background:rgba(13,17,23,0.82);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);
      border:1px solid rgba(255,255,255,0.09);border-radius:16px;
      box-shadow:0 4px 24px rgba(0,0,0,.5);flex-wrap:wrap;
    }
    #logo{display:flex;flex-direction:column;line-height:1.15;flex-shrink:0;user-select:none}
    #logo .lm{font-size:.92rem;font-weight:800;letter-spacing:.5px;color:#fff}
    #logo .ls{font-size:.58rem;color:#6e7f9a;font-weight:600;letter-spacing:.6px;text-transform:uppercase}
    .sep{width:1px;height:26px;background:rgba(255,255,255,0.1);flex-shrink:0}

    /* Selector de parámetro personalizado (permite plegar Riesgos agrícolas) */
    #ps-wrap{position:relative}
    #ps-btn{
      background:rgba(255,255,255,0.07);border:1px solid rgba(255,255,255,0.13);
      border-radius:8px;color:#e6edf3;font-size:.82rem;font-weight:600;
      padding:6px 10px;cursor:pointer;outline:none;display:flex;align-items:center;gap:6px;
      font-family:inherit;
    }
    #ps-btn:hover,#ps-btn:focus{border-color:rgba(59,130,246,.55)}
    .ps-caret{font-size:.62rem;color:#6e7f9a}
    #ps-menu{
      display:none;position:absolute;top:calc(100% + 6px);left:0;min-width:210px;
      background:#1c2433;border:1px solid rgba(255,255,255,0.13);border-radius:10px;
      box-shadow:0 8px 28px rgba(0,0,0,.5);padding:4px;z-index:2000;
    }
    #ps-menu.open{display:block}
    .ps-opt{padding:7px 10px;border-radius:6px;font-size:.8rem;color:#e6edf3;cursor:pointer;white-space:nowrap}
    .ps-opt:hover{background:rgba(255,255,255,0.08)}
    .ps-opt.active{background:rgba(59,130,246,.28)}
    .ps-sep{height:1px;background:rgba(255,255,255,0.1);margin:4px 2px}
    .ps-grp-hdr{
      padding:7px 10px;border-radius:6px;font-size:.72rem;font-weight:700;color:#9aa7bd;
      cursor:pointer;display:flex;align-items:center;justify-content:space-between;user-select:none;
    }
    .ps-grp-hdr:hover{background:rgba(255,255,255,0.06)}
    .ps-sub{display:none;padding-left:4px}
    .ps-sub.open{display:block}

    /* Botón de acceso a la pantalla de pronóstico */
    #btn-pronostico{
      background:rgba(59,130,246,.18);border:1px solid rgba(59,130,246,.4);
      border-radius:8px;color:#93c5fd;font-size:.8rem;font-weight:700;padding:7px 12px;
      cursor:pointer;font-family:inherit;flex-shrink:0;
    }
    #btn-pronostico:hover{background:rgba(59,130,246,.3)}

    /* Resultados del buscador de población (tema claro, solo se usa en #vp) */
    .br-item{padding:8px 10px;border-radius:6px;font-size:.78rem;color:#1e293b;cursor:pointer}
    .br-item:hover{background:rgba(15,23,42,0.05)}
    .br-item small{display:block;color:#64748b;font-size:.68rem;margin-top:1px}
    .br-empty{padding:8px 10px;font-size:.76rem;color:#64748b}

    /* Pestañas de plazo en el pronóstico */
    .fc-tab{
      background:#fff;border:1px solid rgba(15,23,42,0.13);
      border-radius:7px;color:#475569;font-size:.72rem;font-weight:700;padding:6px 10px;
      cursor:pointer;font-family:inherit;
    }
    .fc-tab.active{background:#3b82f6;border-color:transparent;color:#fff}

    /* ── Pantalla completa de pronóstico (tema claro, estilo web del tiempo) ── */
    #vp{
      display:none;position:fixed;inset:0;z-index:3000;color:#1e293b;
      background:linear-gradient(160deg,#eaf4fb 0%,#dbe9f6 45%,#eef6fb 100%);
      flex-direction:column;
    }
    #vp.open{display:flex}
    #vp-topbar{
      display:flex;align-items:center;gap:14px;padding:12px 20px;flex-wrap:wrap;flex-shrink:0;
      background:rgba(255,255,255,0.75);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);
      border-bottom:1px solid rgba(15,23,42,0.08);
    }
    #vp-logo{display:flex;flex-direction:column;line-height:1.15;flex-shrink:0;user-select:none}
    #vp-logo .lm{font-size:.92rem;font-weight:800;letter-spacing:.5px;color:#0f172a}
    #vp-logo .ls{font-size:.58rem;color:#64748b;font-weight:600;letter-spacing:.6px;text-transform:uppercase}
    #vp-buscador-wrap{position:relative;flex:1;max-width:420px;min-width:180px}
    #vp-buscador-input{
      width:100%;background:#fff;border:1px solid rgba(15,23,42,0.13);
      border-radius:9px;color:#0f172a;font-size:.88rem;padding:9px 14px;outline:none;font-family:inherit;
    }
    #vp-buscador-input::placeholder{color:#94a3b8}
    #vp-buscador-input:focus{border-color:rgba(59,130,246,.55)}
    #vp-buscador-resultados{
      display:none;position:absolute;top:calc(100% + 6px);left:0;right:0;
      background:#fff;border:1px solid rgba(15,23,42,0.1);border-radius:10px;
      box-shadow:0 8px 28px rgba(15,23,42,.18);padding:4px;z-index:3100;max-height:300px;overflow-y:auto;
    }
    #vp-buscador-resultados.open{display:block}
    #vp-volver{
      background:#fff;border:1px solid rgba(15,23,42,0.13);
      border-radius:8px;color:#1e293b;font-size:.8rem;font-weight:600;padding:8px 14px;
      cursor:pointer;font-family:inherit;flex-shrink:0;margin-left:auto;
    }
    #vp-volver:hover{background:#f1f5f9}
    #vp-contenido{flex:1;overflow-y:auto;padding:26px 20px 60px;}
    #vp-contenido::-webkit-scrollbar{width:6px}
    #vp-contenido::-webkit-scrollbar-track{background:transparent}
    #vp-contenido::-webkit-scrollbar-thumb{background:rgba(15,23,42,.15);border-radius:3px}
    #vp-inner{max-width:980px;margin:0 auto}
    #vp-vacio{
      max-width:420px;margin:60px auto 0;text-align:center;color:#64748b;font-size:.92rem;line-height:1.6;
    }
    #vp-mapa{border-radius:10px;overflow:hidden;height:220px;background:#e2e8f0;}

    /* Tarjetas de día clicables (abren el detalle horario) */
    .vp-day-card{cursor:pointer;transition:transform .15s,box-shadow .15s}
    .vp-day-card:hover{transform:translateY(-2px);box-shadow:0 6px 18px rgba(15,23,42,.14)}

    /* Modal de detalle horario de un día */
    #vp-detalle-dia{
      display:none;position:fixed;inset:0;z-index:3200;background:rgba(15,23,42,.45);
      align-items:center;justify-content:center;padding:20px;
    }
    #vp-detalle-dia.open{display:flex}
    #vpd-card{
      background:#fff;border-radius:14px;max-width:640px;width:100%;max-height:85vh;
      overflow-y:auto;box-shadow:0 20px 60px rgba(15,23,42,.35);
    }
    #vpd-header{
      display:flex;align-items:center;justify-content:space-between;gap:10px;
      padding:16px 20px;border-bottom:1px solid rgba(15,23,42,.08);position:sticky;top:0;
      background:#fff;border-radius:14px 14px 0 0;
    }
    #vpd-titulo{font-size:1rem;font-weight:700;color:#0f172a}
    #vpd-cerrar{
      background:rgba(15,23,42,.06);border:none;border-radius:6px;color:#475569;font-size:.8rem;
      width:26px;height:26px;display:flex;align-items:center;justify-content:center;cursor:pointer;flex-shrink:0;
    }
    #vpd-cerrar:hover{background:rgba(15,23,42,.12)}
    #vpd-body{padding:18px 20px 22px}
    @media(max-width:700px){
      #vp-topbar{padding:10px 12px;gap:8px}
      #vp-contenido{padding:16px 12px 50px}
      #vp-volver{margin-left:0;order:3;width:100%}
    }


    /* ── Pantalla completa: mapa de lluvia prevista ── */
    #btn-lluvia{
      background:rgba(14,165,233,.16);border:1px solid rgba(14,165,233,.42);
      border-radius:8px;color:#7dd3fc;font-size:.8rem;font-weight:700;padding:7px 12px;
      cursor:pointer;font-family:inherit;flex-shrink:0;
    }
    #btn-lluvia:hover{background:rgba(14,165,233,.3)}
    #vl{
      display:none;position:fixed;inset:0;z-index:3000;color:#1e293b;
      background:linear-gradient(160deg,#eaf4fb 0%,#dbe9f6 45%,#eef6fb 100%);
      flex-direction:column;
    }
    #vl.open{display:flex}
    #vl-topbar{
      display:flex;align-items:center;gap:12px;padding:12px 20px;flex-wrap:wrap;flex-shrink:0;
      background:rgba(255,255,255,0.75);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);
      border-bottom:1px solid rgba(15,23,42,0.08);
    }
    #vl-titulo{font-size:.95rem;font-weight:800;color:#0f172a;line-height:1.2}
    #vl-titulo small{display:block;font-size:.6rem;font-weight:600;color:#64748b;text-transform:uppercase;letter-spacing:.6px}
    .vl-btn{
      background:#fff;border:1px solid rgba(15,23,42,0.13);
      border-radius:8px;color:#1e293b;font-size:.8rem;font-weight:600;padding:8px 14px;
      cursor:pointer;font-family:inherit;flex-shrink:0;
    }
    .vl-btn:hover{background:#f1f5f9}
    #vl-volver{margin-left:auto}
    #vl-cuerpo{flex:1;overflow-y:auto;padding:16px 18px 46px}
    #vl-cuerpo::-webkit-scrollbar{width:6px}
    #vl-cuerpo::-webkit-scrollbar-thumb{background:rgba(15,23,42,.15);border-radius:3px}
    #vl-inner{max-width:1040px;margin:0 auto}
    .ll-chips{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:7px}
    .ll-chips-tit{font-size:.62rem;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:.5px;margin:0 0 4px}
    .ll-chip{
      background:#fff;border:1px solid rgba(15,23,42,0.13);border-radius:7px;
      color:#334155;font-size:.72rem;font-weight:700;padding:6px 11px;
      cursor:pointer;font-family:inherit;
    }
    .ll-chip:hover{background:#f1f5f9}
    .ll-chip.active{background:#1d4ed8;border-color:transparent;color:#fff}
    #vl-fila-fondo{display:flex;flex-wrap:wrap;align-items:center;gap:10px}
    #vl-op-wrap{
      display:flex;align-items:center;gap:7px;font-size:.66rem;font-weight:700;
      color:#64748b;text-transform:uppercase;letter-spacing:.4px;white-space:nowrap;
    }
    #vl-op-wrap input[type=range]{width:110px;accent-color:#1d4ed8;cursor:pointer}
    #vl-rango{font-size:.76rem;color:#334155;margin:10px 0 8px}
    #vl-mapa-wrap{position:relative;border-radius:12px;overflow:hidden;box-shadow:0 6px 22px rgba(15,23,42,.15)}
    #vl-mapa{height:52vh;min-height:300px;background:#e2e8f0}
    #vl-cargando{
      display:none;position:absolute;top:10px;left:50%;transform:translateX(-50%);z-index:1200;
      background:rgba(255,255,255,.94);border:1px solid rgba(15,23,42,.1);border-radius:8px;
      padding:6px 12px;font-size:.74rem;font-weight:700;color:#334155;
      box-shadow:0 3px 12px rgba(15,23,42,.18);max-width:90%;text-align:center;
    }
    .ll-pin{
      border:1.5px solid #fff;border-radius:6px;width:34px;height:18px;
      display:flex;align-items:center;justify-content:center;
      font-size:10.5px;font-weight:700;box-shadow:0 1px 5px rgba(0,0,0,.35);
    }
    #vl-leyenda{margin-top:10px}
    .ll-lg-tit{font-size:.68rem;font-weight:700;color:#475569;margin-bottom:3px}
    .ll-lg-barra{display:flex;align-items:flex-end;gap:0}
    .ll-lg-cel{flex:1;text-align:center;min-width:0}
    .ll-lg-col{display:block;height:12px}
    .ll-lg-txt{display:block;font-size:.53rem;color:#475569;margin-top:2px}
    #vl-tabla{margin-top:16px}
    .ll-tabla-tit{font-size:.76rem;font-weight:700;color:#0f172a;margin-bottom:6px}
    .ll-tabla-scroll{overflow-x:auto;border-radius:10px;background:#fff;box-shadow:0 3px 12px rgba(15,23,42,.1)}
    .ll-tabla{border-collapse:collapse;font-size:.72rem;width:100%;min-width:520px}
    .ll-tabla th,.ll-tabla td{padding:5px 8px;text-align:center;border-bottom:1px solid rgba(15,23,42,.06)}
    .ll-tabla th{background:#eef2f8;color:#0f172a;font-weight:700;font-size:.68rem}
    .ll-tabla th.ll-pob{background:#fff;text-align:left;font-weight:700;color:#0f172a;white-space:nowrap}
    .ll-tabla th.ll-col-act{background:#1d4ed8;color:#fff}
    .ll-tabla td.ll-col-act{box-shadow:inset 2px 0 0 rgba(29,78,216,.45),inset -2px 0 0 rgba(29,78,216,.45)}
    .ll-tabla .ll-media{font-weight:800}
    .ll-nota{
      background:#f0f7ff;border-left:3px solid #3498db;border-radius:6px;
      padding:9px 13px;font-size:.72rem;color:#334155;margin-top:10px;line-height:1.6;
    }
    .ll-fuente{font-size:.64rem;color:#6b7280;margin-top:8px}
    @media(max-width:700px){
      #vl-topbar{padding:10px 12px;gap:8px}
      #vl-cuerpo{padding:12px 12px 40px}
      #vl-volver{margin-left:0;order:3}
      #vl-mapa{height:46vh;min-height:250px}
      .ll-lg-txt{font-size:.48rem}
    }

    /* ── Máquina del tiempo (formato tipo radarspain.es) ───────── */
    #tm-bar{
      position:fixed;left:50%;bottom:14px;transform:translateX(-50%);z-index:999;
      width:min(720px,94vw);
      background:rgba(13,17,23,0.92);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);
      border:1px solid rgba(255,255,255,0.09);border-radius:16px;
      box-shadow:0 8px 32px rgba(0,0,0,.5);
      padding:10px 14px 12px;display:flex;flex-direction:column;gap:7px;
    }
    #tm-row1{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
    .tm-play{
      width:32px;height:32px;border-radius:50%;flex-shrink:0;
      background:rgba(59,130,246,.85);border:none;color:#fff;font-size:.8rem;
      display:flex;align-items:center;justify-content:center;cursor:pointer;padding:0;
    }
    .tm-play:hover{background:#3b82f6}
    #tm-clock{display:flex;flex-direction:column;line-height:1.05;flex-shrink:0}
    .tm-clock-lbl{font-size:.54rem;color:#6e7f9a;font-weight:700;letter-spacing:.6px;text-transform:uppercase}
    #tl{font-size:1.28rem;font-weight:800;color:#fff;font-variant-numeric:tabular-nums}
    #tm-info{display:flex;flex-direction:column;line-height:1.35;flex-shrink:0;margin-right:auto}
    #tm-offset{font-size:.64rem;font-weight:800;color:#3b82f6;letter-spacing:.3px}
    #tm-offset.en-vivo{color:#27ae60}
    #tl-sub{font-size:.62rem;color:#6e7f9a}
    #tm-periodos,#tm-speed{display:flex;gap:2px;background:rgba(255,255,255,0.05);border-radius:8px;padding:2px;flex-shrink:0}
    .tm-per-btn,.tm-vel-btn{
      background:transparent;border:none;color:#94a3b8;font-size:.66rem;font-weight:700;
      padding:5px 8px;border-radius:6px;cursor:pointer;white-space:nowrap;
    }
    .tm-per-btn:hover,.tm-vel-btn:hover{color:#e6edf3}
    .tm-per-btn.active,.tm-vel-btn.active{background:rgba(59,130,246,.85);color:#fff}
    #tm-live{
      flex-shrink:0;background:rgba(59,130,246,.15);border:1px solid rgba(59,130,246,.4);
      color:#93c5fd;font-size:.64rem;font-weight:700;padding:5px 9px;border-radius:8px;cursor:pointer;
      display:none;
    }
    #tm-live:hover{background:rgba(59,130,246,.3)}
    #tm-live.mostrar{display:block}
    #tm-row2{display:flex;align-items:center;gap:8px}
    #sl{flex:1}
    #tm-counter{font-size:.6rem;color:#6e7f9a;font-variant-numeric:tabular-nums;flex-shrink:0;min-width:42px;text-align:right}

    /* Sliders */
    input[type=range]{
      -webkit-appearance:none;appearance:none;
      height:4px;border-radius:2px;background:rgba(255,255,255,0.14);outline:none;cursor:pointer;
    }
    input[type=range]::-webkit-slider-thumb{
      -webkit-appearance:none;width:14px;height:14px;border-radius:50%;
      background:#3b82f6;cursor:pointer;box-shadow:0 0 6px rgba(59,130,246,.55);
    }
    input[type=date]{
      background:rgba(255,255,255,0.07);border:1px solid rgba(255,255,255,0.13);
      border-radius:6px;color:#e6edf3;font-size:.7rem;padding:4px 6px;cursor:pointer;outline:none;
    }
    input[type=date]::-webkit-calendar-picker-indicator{filter:invert(1);opacity:.4;cursor:pointer}

    /* Control de opacidad */
    #ctrl-op{display:flex;flex-direction:column;align-items:center;gap:3px;flex-shrink:0}
    #ctrl-op label{font-size:.58rem;color:#6e7f9a;font-weight:700;letter-spacing:.3px}

    /* Toggle radar (independiente del parámetro) */
    #ctrl-radar{display:flex;align-items:center;gap:6px;flex-shrink:0}
    #ctrl-radar label{display:flex;align-items:center;gap:4px;font-size:.72rem;color:#e6edf3;font-weight:600;cursor:pointer;user-select:none}
    #ctrl-radar input[type=checkbox]{cursor:pointer;accent-color:#3b82f6}
    #radar-fuera-rango{display:none;font-size:.62rem;color:#f0ad4e;font-weight:700;white-space:nowrap;cursor:help}

    /* Botón ubicación */
    #btn-loc{
      background:rgba(255,255,255,0.07);border:1px solid rgba(255,255,255,0.13);
      border-radius:8px;color:#e6edf3;font-size:1rem;
      width:34px;height:34px;display:flex;align-items:center;justify-content:center;
      cursor:pointer;flex-shrink:0;padding:0;
    }
    #btn-loc:hover{background:rgba(255,255,255,0.15)}

    /* Aviso días */
    #aviso-dias{
      display:none;position:fixed;top:80px;left:50%;transform:translateX(-50%);z-index:998;
      background:rgba(30,58,95,0.9);border:1px solid rgba(59,130,246,.3);
      border-radius:8px;padding:7px 14px;font-size:.7rem;color:#93c5fd;
      white-space:nowrap;backdrop-filter:blur(8px);
    }

    /* Dejar hueco para el panel de la máquina del tiempo (fijo abajo) */
    .leaflet-bottom.leaflet-left{bottom:104px!important}

    /* Leyenda (Leaflet control) */
    .legend{
      background:rgba(13,17,23,0.88)!important;
      backdrop-filter:blur(16px)!important;-webkit-backdrop-filter:blur(16px)!important;
      border:1px solid rgba(255,255,255,0.09)!important;border-radius:12px!important;
      box-shadow:0 4px 20px rgba(0,0,0,.45)!important;
      color:#cbd5e1!important;font-size:.72rem!important;
      padding:0!important;max-width:150px;overflow:hidden;
    }
    .leg-hdr{
      display:flex;align-items:center;justify-content:space-between;gap:8px;
      padding:7px 11px;cursor:pointer;user-select:none;
      border-bottom:1px solid rgba(255,255,255,0.06);
    }
    .leg-hdr:hover{background:rgba(255,255,255,0.04)}
    .leg-hdr span:first-child{color:#f1f5f9;font-weight:700;font-size:.73rem}
    .leg-tog{color:#6b7280;font-size:.65rem;flex-shrink:0}
    .leg-body{padding:7px 11px 9px;line-height:1;}
    .li-row{display:flex;align-items:center;gap:5px;padding:2px 0;white-space:nowrap}
    .legend i{
      display:inline-block!important;width:12px!important;height:12px!important;
      border-radius:2px!important;border:none!important;flex-shrink:0;
    }

    /* Panel lateral de estación */
    #dp{
      position:fixed;top:80px;right:12px;bottom:104px;width:300px;
      display:none;flex-direction:column;z-index:1001;
      background:rgba(13,17,23,0.90);backdrop-filter:blur(22px);-webkit-backdrop-filter:blur(22px);
      border:1px solid rgba(255,255,255,0.09);border-radius:16px;
      box-shadow:0 8px 32px rgba(0,0,0,.55);overflow:hidden;
    }
    #dh{
      padding:14px 16px 12px;display:flex;justify-content:space-between;align-items:center;
      border-bottom:1px solid rgba(255,255,255,0.07);flex-shrink:0;
    }
    #dh span{font-size:.85rem;font-weight:700;color:#e6edf3}
    #cp{
      background:rgba(255,255,255,0.07);border:1px solid rgba(255,255,255,0.12);
      border-radius:6px;color:#94a3b8;font-size:.78rem;
      width:26px;height:26px;display:flex;align-items:center;justify-content:center;cursor:pointer;
    }
    #cp:hover{background:rgba(255,255,255,0.14);color:#e6edf3}
    #dc{padding:14px;font-size:.8rem;overflow-y:auto;flex:1;color:#cbd5e1}
    #dc::-webkit-scrollbar{width:4px}
    #dc::-webkit-scrollbar-track{background:transparent}
    #dc::-webkit-scrollbar-thumb{background:rgba(255,255,255,0.1);border-radius:2px}

    /* Overrides de contenido dinámico del panel para tema oscuro */
    #dc [style*="color:#2c3e50"]{color:#f1f5f9!important}
    #dc [style*="color:#555"]{color:#9ca3af!important}
    #dc [style*="color:#666"]{color:#9ca3af!important}
    #dc [style*="color:#888"]{color:#6b7280!important}
    #dc [style*="color:#444"]{color:#cbd5e1!important}
    #dc [style*="color:#aaa"]{color:#374151!important}
    #dc [style*="color:#999"]{color:#4b5563!important}
    #dc [style*="color:#1a5276"]{color:#93c5fd!important}
    #dc [style*="color:#856404"]{color:#fbbf24!important}
    #dc [style*="background:#f8f8f8"]{background:rgba(255,255,255,0.04)!important}
    #dc [style*="background:#e0e0e0"]{background:rgba(255,255,255,0.13)!important}
    #dc [style*="background:#e8f4fd"]{background:rgba(30,58,95,0.55)!important;border-color:rgba(59,130,246,.3)!important}
    #dc [style*="background:#fef9e7"]{background:rgba(92,53,15,0.45)!important;border-color:rgba(251,191,36,.3)!important}
    #dc [style*="background:#fff3cd"]{background:rgba(92,53,15,0.45)!important;border-color:rgba(251,191,36,.3)!important}
    #dc [style*="background:#f0f7ff"]{background:rgba(30,58,95,0.38)!important;border-color:rgba(59,130,246,.22)!important}
    #dc [style*="background:#f0fff4"]{background:rgba(5,46,22,0.45)!important;border-color:rgba(34,197,94,.22)!important}
    #dc tr[style*="background:#dce8f5"]{background:rgba(59,130,246,0.11)!important}
    #dc tr[style*="background:#c8f0d8"]{background:rgba(34,197,94,0.11)!important}
    #dc tr[style*="background:#f5f5f5"]{background:rgba(255,255,255,0.03)!important}
    #dc td[style*="background:#dce8f5"]{background:rgba(59,130,246,0.11)!important}
    #dc hr{border-top-color:rgba(255,255,255,0.07)!important}
    #dc a[href*="wunderground"]{background:#2563eb!important;border-radius:8px!important}
    #dc [style*="border-left:3px solid #3498db"]{border-left-color:#3b82f6!important}
    #dc [style*="border-left:3px solid #27ae60"]{border-left-color:#22c55e!important}

    /* Overrides de controles Leaflet para tema oscuro */
    .leaflet-control-layers{
      background:rgba(13,17,23,0.88)!important;backdrop-filter:blur(16px)!important;
      border:1px solid rgba(255,255,255,0.09)!important;
      border-radius:12px!important;color:#e6edf3!important;
    }
    .leaflet-control-layers-toggle{background-color:rgba(13,17,23,0.85)!important}
    .leaflet-control-layers-expanded{padding:8px 12px!important}
    .leaflet-control-layers label{color:#cbd5e1!important;font-size:.8rem}
    .leaflet-control-layers-separator{border-top-color:rgba(255,255,255,0.1)!important}
    .leaflet-bar{border:none!important;box-shadow:0 2px 12px rgba(0,0,0,.45)!important}
    .leaflet-bar a{
      background:rgba(13,17,23,0.88)!important;color:#e6edf3!important;
      border-bottom:1px solid rgba(255,255,255,0.08)!important;backdrop-filter:blur(8px)!important;
    }
    .leaflet-bar a:hover{background:rgba(40,55,75,0.95)!important}
    .leaflet-popup-content-wrapper{
      background:rgba(13,17,23,0.95)!important;backdrop-filter:blur(16px)!important;
      border:1px solid rgba(255,255,255,0.1)!important;border-radius:12px!important;
      color:#e6edf3!important;box-shadow:0 8px 32px rgba(0,0,0,.55)!important;
    }
    .leaflet-popup-tip{background:rgba(13,17,23,0.95)!important}
    .leaflet-tooltip{
      background:rgba(13,17,23,0.92)!important;border:1px solid rgba(255,255,255,0.1)!important;
      border-radius:8px!important;color:#e6edf3!important;
      box-shadow:0 4px 16px rgba(0,0,0,.45)!important;font-size:.78rem!important;padding:5px 10px!important;
    }
    .leaflet-tooltip::before{border-top-color:rgba(13,17,23,0.92)!important}
    .leaflet-attribution-flag{display:none!important}
    .leaflet-control-attribution{
      background:rgba(13,17,23,0.7)!important;color:#4b5563!important;
      border-radius:6px 0 0 0!important;font-size:.6rem!important;
    }
    .leaflet-control-attribution a{color:#6b7280!important}

    .gmap{filter:grayscale(100%) contrast(1.1) brightness(1.05)}
    /* Fondo de reserva (OSM) cuando el gris claro de Esri no responde */
    .mapa-atenuado{filter:grayscale(72%) brightness(1.08)}

    @media(max-width:600px){
      #topbar{top:6px;left:6px;right:6px;border-radius:12px;gap:7px;padding:8px 12px}
      .sep{display:none}
      #dp{top:auto;right:6px;left:6px;bottom:150px;width:auto;max-height:44vh;border-radius:12px}
      #aviso-dias{top:70px}
      .legend{max-width:130px!important;font-size:.68rem!important}
      .leg-hdr{padding:5px 9px}
      .leg-body{padding:5px 9px 7px}
      .leaflet-bottom.leaflet-left{bottom:150px!important}
      #tm-bar{bottom:6px;left:6px;right:6px;width:auto;transform:none;padding:8px 10px 10px}
      #tm-row1{gap:6px}
      #tl{font-size:1.05rem}
      #tm-info{margin-right:0}
      .tm-per-btn,.tm-vel-btn{padding:4px 6px;font-size:.6rem}
      #tm-live{font-size:.58rem;padding:4px 7px}
    }
  </style>
</head>
<body>
<div id="map"></div>

<!-- Barra superior flotante -->
<div id="topbar">
  <div id="logo">
    <span class="lm">🌿 METEO</span>
    <span class="ls">Guadalentín</span>
  </div>
  <div class="sep"></div>
  <div id="ps-wrap">
    <button type="button" id="ps-btn"><span id="ps-btn-label">🌡 Temperatura (°C)</span><span class="ps-caret">▾</span></button>
    <div id="ps-menu">
      <div class="ps-opt active" data-v="temp">🌡 Temperatura (°C)</div>
      <div class="ps-opt" data-v="precip">🌧 Precipitación (mm)</div>
      <div class="ps-opt" data-v="humidity">💧 Humedad (%)</div>
      <div class="ps-opt" data-v="wind">💨 Viento (km/h)</div>
      <div class="ps-sep"></div>
      <div class="ps-grp-hdr" id="ps-riesgo-hdr"><span>🌿 Riesgos agrícolas</span><span class="ps-caret">▸</span></div>
      <div class="ps-sub" id="ps-riesgo-sub">
        <div class="ps-opt" data-v="oidio">🍇 Riesgo Oídio</div>
        <div class="ps-opt" data-v="mildiu">🍃 Riesgo Mildiu</div>
      </div>
    </div>
    <select id="ps" onchange="onParamChange()" style="display:none">
      <option value="temp" selected>🌡 Temperatura (°C)</option>
      <option value="precip">🌧 Precipitación (mm)</option>
      <option value="humidity">💧 Humedad (%)</option>
      <option value="wind">💨 Viento (km/h)</option>
      <option value="oidio">🍇 Riesgo Oídio</option>
      <option value="mildiu">🍃 Riesgo Mildiu</option>
    </select>
  </div>
  <div class="sep"></div>
  <button type="button" id="btn-pronostico" onclick="mostrarVistaPronostico()">🔮 Pronóstico</button>
  <button type="button" id="btn-lluvia" onclick="mostrarVistaLluvia()">🌧 Lluvia prevista</button>
  <div class="sep"></div>
  <div id="ctrl-radar">
    <label><input type="checkbox" id="radar-chk"> 📡 Radar</label>
    <span id="radar-fuera-rango" title="Radar disponible: en vivo (~2h vía RainViewer) y hasta ~48h atrás (archivo propio)">⚠ sin radar aquí</span>
  </div>
  <div class="sep"></div>
  <div id="ctrl-op">
    <label>🔆 Opacidad</label>
    <input type="range" id="op" min="0" max="1" step="0.05" value="0.35" style="width:65px">
  </div>
  <button id="btn-loc" title="Mi ubicación" onclick="locateMe()">🎯</button>
</div>

<!-- Máquina del tiempo ─────────────────────────────────────── -->
<div id="tm-bar">
  <div id="tm-row1">
    <button type="button" id="pb" class="tm-play">▶</button>
    <div id="tm-clock">
      <span class="tm-clock-lbl">Hora local</span>
      <span id="tl">--:--</span>
    </div>
    <div id="tm-info">
      <span id="tm-offset">EN VIVO</span>
      <span id="tl-sub">-</span>
    </div>
    <div id="tm-periodos">
      <button type="button" class="tm-per-btn" data-per="6h">6h</button>
      <button type="button" class="tm-per-btn" data-per="12h">12h</button>
      <button type="button" class="tm-per-btn active" data-per="24h">24h</button>
      <button type="button" class="tm-per-btn" data-per="2d">2 días</button>
      <button type="button" class="tm-per-btn" data-per="7d">Semana</button>
    </div>
    <div id="tm-speed">
      <button type="button" class="tm-vel-btn" data-vel="1500">0,5×</button>
      <button type="button" class="tm-vel-btn active" data-vel="500">1×</button>
      <button type="button" class="tm-vel-btn" data-vel="200">2×</button>
    </div>
    <button type="button" id="tm-live">⟲ Volver al directo</button>
  </div>
  <div id="tm-row2">
    <input type="range" id="sl" min="0" max="0" value="0">
    <span id="tm-counter">0 / 0</span>
    <input type="date" id="sl-fecha-ini" style="display:none">
    <span id="sl-sep" style="display:none">→</span>
    <input type="date" id="sl-fecha-fin" style="display:none">
  </div>
</div>

<div id="aviso-dias"></div>

<!-- Panel lateral de estación -->
<div id="dp">
  <div id="dh">
    <span id="dh-title">Detalle de estación</span>
    <button id="cp" onclick="hidePanel()">✕</button>
  </div>
  <div id="dc">
    <p style="color:#475569;font-size:.8rem;line-height:1.7">
      Haz clic en una estación del mapa para ver sus datos aquí.
    </p>
  </div>
</div>

<!-- Pantalla completa de pronóstico (independiente del mapa de datos climáticos) -->
<div id="vp">
  <div id="vp-topbar">
    <div id="vp-logo">
      <span class="lm">🔮 PRONÓSTICO</span>
      <span class="ls">Guadalentín</span>
    </div>
    <div id="vp-buscador-wrap">
      <input type="text" id="vp-buscador-input" placeholder="🔍 Buscar población…" autocomplete="off">
      <div id="vp-buscador-resultados"></div>
    </div>
    <button type="button" class="vl-btn" onclick="mostrarVistaMapa();mostrarVistaLluvia()">🌧 Mapa de lluvia</button>
    <button type="button" id="vp-volver" onclick="mostrarVistaMapa()">← Mapa</button>
  </div>
  <div id="vp-contenido">
    <div id="vp-vacio">
      <div style="font-size:42px;margin-bottom:10px;">🔮</div>
      <div>Busca una población para ver su pronóstico y comparar modelos.</div>
    </div>
  </div>

  <!-- Detalle horario de un día concreto (se abre al pinchar una tarjeta o un punto del gráfico) -->
  <div id="vp-detalle-dia" onclick="if(event.target===this) cerrarDetalleDia()">
    <div id="vpd-card">
      <div id="vpd-header">
        <span id="vpd-titulo">Detalle del día</span>
        <button type="button" id="vpd-cerrar" onclick="cerrarDetalleDia()">✕</button>
      </div>
      <div id="vpd-body"></div>
    </div>
  </div>
</div>


<!-- Pantalla completa: mapa de precipitación acumulada prevista -->
<div id="vl">
  <div id="vl-topbar">
    <div id="vl-titulo">🌧 Lluvia prevista<small>Precipitación acumulada · Región de Murcia</small></div>
    <button type="button" class="vl-btn" onclick="ocultarVistaLluvia();mostrarVistaPronostico()">🔮 Pronóstico por población</button>
    <button type="button" class="vl-btn" id="vl-volver" onclick="ocultarVistaLluvia()">← Mapa</button>
  </div>
  <div id="vl-cuerpo">
    <div id="vl-inner">
      <div class="ll-chips-tit">Modelo</div>
      <div class="ll-chips" id="vl-modelos"></div>
      <div class="ll-chips-tit">Plazo acumulado</div>
      <div class="ll-chips" id="vl-plazos"></div>
      <div class="ll-chips-tit">Fondo del mapa</div>
      <div id="vl-fila-fondo">
        <div class="ll-chips" id="vl-fondos"></div>
        <label id="vl-op-wrap">Opacidad de la lluvia
          <input type="range" id="vl-opacidad" min="0.2" max="1" step="0.05" value="0.75"
                 oninput="llSetOpacidad(this.value)">
        </label>
      </div>
      <div id="vl-rango"></div>
      <div id="vl-mapa-wrap">
        <div id="vl-mapa"></div>
        <div id="vl-cargando">⏳ Descargando pronóstico…</div>
      </div>
      <div id="vl-leyenda"></div>
      <div id="vl-tabla"></div>
    </div>
  </div>
</div>

<script>__JS__</script>
<script>
(function(){
  var INTERVALO=5*60*1000,RECARGA_COMPLETA=60*60*1000,tInicioSesion=Date.now(),timer=null;
  function actualizarDatos(){
    if(document.visibilityState==='hidden') return;
    if(Date.now()-tInicioSesion>=RECARGA_COMPLETA){location.reload();return;}
    fetch('history_24h.json?v='+Date.now())
      .then(function(r){return r.json();})
      .then(function(datos){
        if(!datos||!datos.length) return;
        historyData=datos;
        if(!PERIODOS[periodoActivo].archivo) activeData=datosLocales();
        var indices=getModoIndices();
        var eraActual=(idxActual>=indices.length-1);
        actualizarModoSlider();
        if(!eraActual){
          var newIndices=getModoIndices();
          idxActual=Math.min(idxActual,newIndices.length-1);
          document.getElementById('sl').value=idxActual;
          actualizarLabel();
        }
        render();
      }).catch(function(){});
  }
  function programar(){clearTimeout(timer);timer=setTimeout(function(){actualizarDatos();programar();},INTERVALO);}
  document.addEventListener('visibilitychange',function(){
    if(document.visibilityState==='visible'){actualizarDatos();programar();}
    else clearTimeout(timer);
  });
  programar();
})();
</script>
</body>
</html>"""

# ── Principal ─────────────────────────────────────────────────
def principal():
    # Sincronizar con el remoto antes de leer/escribir el historial local.
    # Evita que una ejecución manual con un checkout desactualizado
    # sobrescriba (al hacer push) el historial ya acumulado en producción.
    print("\n🔄 Sincronizando historial con el remoto...")
    try:
        subprocess.run(["git","-C",REPO_DIR,"config","pull.rebase","false"],
                        capture_output=True, text=True, timeout=10)
        r = subprocess.run(["git","-C",REPO_DIR,"pull","origin","main","--no-edit"],
                            capture_output=True, text=True, timeout=20)
        if r.returncode != 0:
            print(f"  ⚠ No se pudo sincronizar: {r.stderr.strip()[:150]}")
    except Exception as e:
        print(f"  ⚠ Git pull error: {e}")

    try:
        from zoneinfo import ZoneInfo
        ahora = datetime.now(ZoneInfo("Europe/Madrid"))
    except ImportError:
        ahora = datetime.now()

    print(f"\n🚀 Obteniendo datos WU de {len(ESTACIONES)} estaciones...")
    datos_wu = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=25) as ex:
        for d in ex.map(wu, ESTACIONES):
            if d: datos_wu.append(d)
    print(f"  ✅ {len(datos_wu)}/{len(ESTACIONES)} con datos.")
    if not datos_wu:
        print("  ❌ Sin datos WU. Comprueba la conexión."); return

    h_prev = leer(F_H24, [])
    minutos = 15
    if h_prev:
        try:
            t_prev = datetime.fromisoformat(h_prev[-1]['timestamp'])
            if t_prev.tzinfo is None: t_prev = t_prev.replace(tzinfo=ahora.tzinfo)
            minutos = min(60, max(1, round((ahora - t_prev).total_seconds() / 60)))
        except Exception:
            pass

    print("\n📚 Historial 24h...")
    h24 = hist24(datos_wu, ahora)

    print("\n📚 Historial 2 días (resolución 30 min)...")
    hist_extendido(datos_wu, ahora, F_H2D, horas_retencion=48, minutos_intervalo=30)

    print("\n📚 Historial 7 días (resolución 3 h)...")
    hist_extendido(datos_wu, ahora, F_H7D, horas_retencion=24*7, minutos_intervalo=180)

    print("\n📡 Archivando radar propio...")
    archivar_radar(ahora)

    print(f"\n🌾 Historial agrícola... (+{minutos} min)")
    hagri = hist_agri(datos_wu, ahora, minutos)
    dias_acum = len(hagri)

    if dias_acum < MIN_DIAS:
        falt = MIN_DIAS - dias_acum
        print(f"\n  ⏳ Faltan {falt} día{'s' if falt>1 else ''} más para activar el cálculo de riesgo.")
        print(f"     Ejecuta el script diariamente — el riesgo se activará solo.")

    print("\n🔬 Calculando riesgo...")
    r = calcular_riesgo(hagri, datos_wu)
    niveles = ['Sin riesgo','Bajo','Medio','ALTO']
    for sid, rv in r.items():
        ot = niveles[rv['oidio']]  if rv['oidio']  >= 0 else '⏳ Pendiente'
        mt = niveles[rv['mildiu']] if rv['mildiu'] >= 0 else '⏳ Pendiente'
        print(f"  {sid}: Oídio={ot} | Mildiu={mt} | {rv['fuente_datos']}")

    print("\n📈 Guardando snapshot de riesgo diario...")
    guardar_riesgo_dia(r, ahora)

    print("\n🔄 Rellenando riesgo de días anteriores...")
    recalcular_riesgo_dias_anteriores(hagri, {}, datos_wu, ahora, n_dias=3)

    print("\n🗺  Generando HTML...")
    ruta = generar_html(h24, r, ahora, dias_acum)

    if os.environ.get('CI'):
        print("\n☁️  En GitHub Actions: el workflow hace el push.")
    else:
        print("\n☁️  Subiendo a GitHub...")
        git_push(ahora)

    print(f"\n✅ Listo")
    print(f"🌐 https://jorloan.github.io/meteo-guadalentin/")
    if not os.environ.get('CI'):
        webbrowser.open('file://' + ruta)

if __name__ == "__main__":
    principal()
