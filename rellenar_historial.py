"""
rellenar_historial.py
Descarga los últimos 7 días de historial de todas las estaciones WU
y rellena historial_agricola.json de golpe.
Ejecutar UNA VEZ desde la carpeta del repo:
  python3 rellenar_historial.py
"""
import urllib.request, json, ssl, os, time, concurrent.futures
from datetime import datetime, timedelta

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

WU_KEY = "6532d6454b8aa370768e63d6ba5a832e"

# ── Rutas ─────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def _repo():
    c = BASE_DIR
    for _ in range(4):
        if os.path.isdir(os.path.join(c, '.git')): return c
        c = os.path.dirname(c)
    m = os.path.expanduser("~/Documents/meteo-guadalentin")
    return m if os.path.isdir(m) else BASE_DIR

REPO_DIR = _repo()
F_AGRI   = os.path.join(REPO_DIR, 'historial_agricola.json')

print(f"📁 Repo: {REPO_DIR}")
print(f"📄 Archivo: {F_AGRI}")

# ── Estaciones ────────────────────────────────────────────────
F_EST = os.path.join(BASE_DIR, 'estaciones.txt')
ESTACIONES = [l.split('#')[0].strip() for l in open(F_EST) if l.split('#')[0].strip()]
print(f"📡 Estaciones a procesar: {len(ESTACIONES)}")

# ── API WU historial diario ───────────────────────────────────
def wu_historial_dia(sid, fecha_str):
    """
    Obtiene observaciones de un día concreto para una estación WU.
    fecha_str formato: YYYYMMDD
    Devuelve dict con tmax, tmin, precipTotal, humedadAltaMinutos o None.
    """
    url = (f"https://api.weather.com/v2/pws/history/daily"
           f"?stationId={sid}&format=json&units=m&numericPrecision=decimal"
           f"&date={fecha_str}&apiKey={WU_KEY}")
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
            'Referer':    'https://www.wunderground.com/'})
        with urllib.request.urlopen(req, context=ctx, timeout=8) as r:
            data = json.loads(r.read().decode('utf-8'))

        obs = data.get('observations', [])
        if not obs:
            return None

        # El endpoint daily devuelve resumen del día
        o = obs[0]
        m = o.get('metric', o.get('metricHigh', {}))

        # Intentar obtener métricas de resumen diario
        tmax  = o.get('metric', {}).get('tempHigh') or o.get('metricHigh', {}).get('tempHigh')
        tmin  = o.get('metric', {}).get('tempLow')  or o.get('metricLow',  {}).get('tempLow')
        prec  = o.get('metric', {}).get('precipTotal')
        lat   = o.get('lat')
        lon   = o.get('lon')

        # Si el endpoint daily no da tmax/tmin, calcular de observaciones
        if tmax is None and len(obs) > 1:
            temps = [x.get('metric',{}).get('temp') for x in obs if x.get('metric',{}).get('temp') is not None]
            if temps:
                tmax = max(temps)
                tmin = min(temps)

        # Horas con HR >= 85%
        horas_hum = 0
        for ob in obs:
            hum = ob.get('humidity')
            if hum is not None and hum >= 85:
                horas_hum += 1  # cada observación = ~1h en resumen diario

        return {
            'tempMax':  tmax,
            'tempMin':  tmin,
            'precipTotal': prec if prec is not None else 0.0,
            'humedadAltaMinutos': horas_hum * 60,
            'lat': lat,
            'lon': lon
        }
    except Exception as e:
        return None

def wu_historial_all(sid, fecha_str):
    """
    Alternativa: endpoint all (observaciones individuales del día).
    """
    url = (f"https://api.weather.com/v2/pws/history/all"
           f"?stationId={sid}&format=json&units=m&numericPrecision=decimal"
           f"&date={fecha_str}&apiKey={WU_KEY}")
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
            'Referer':    'https://www.wunderground.com/'})
        with urllib.request.urlopen(req, context=ctx, timeout=10) as r:
            data = json.loads(r.read().decode('utf-8'))

        obs = data.get('observations', [])
        if not obs:
            return None

        temps  = [o.get('metric',{}).get('temp') for o in obs if o.get('metric',{}).get('temp') is not None]
        precs  = [o.get('metric',{}).get('precipTotal') for o in obs if o.get('metric',{}).get('precipTotal') is not None]
        hums   = [o.get('humidity') for o in obs if o.get('humidity') is not None]
        lat    = obs[0].get('lat')
        lon    = obs[0].get('lon')

        horas_hum = sum(1 for h in hums if h >= 85)

        return {
            'tempMax':  max(temps) if temps else None,
            'tempMin':  min(temps) if temps else None,
            'precipTotal': max(precs) if precs else 0.0,
            'humedadAltaMinutos': horas_hum * 15,  # ~15min por obs
            'lat': lat,
            'lon': lon
        }
    except Exception as e:
        return None

# ── Descargar historial ───────────────────────────────────────
def descargar_estacion(sid):
    ahora  = datetime.now()
    resultado = {}
    for dias_atras in range(1, 8):   # últimos 7 días
        fecha_dt  = ahora - timedelta(days=dias_atras)
        fecha_key = fecha_dt.strftime('%Y-%m-%d')    # clave en historial
        fecha_wu  = fecha_dt.strftime('%Y%m%d')      # formato WU

        # Intentar primero endpoint 'all' (más detallado)
        datos = wu_historial_all(sid, fecha_wu)
        if datos is None:
            datos = wu_historial_dia(sid, fecha_wu)

        if datos:
            resultado[fecha_key] = datos

    return sid, resultado

# ── Cargar historial existente ────────────────────────────────
if os.path.exists(F_AGRI):
    with open(F_AGRI, 'r', encoding='utf-8') as f:
        historial = json.load(f)
    print(f"✅ Historial existente: {len(historial)} días")
else:
    historial = {}
    print("ℹ Historial nuevo")

# ── Procesar estaciones ───────────────────────────────────────
print(f"\n⬇️  Descargando últimos 7 días de {len(ESTACIONES)} estaciones...\n")

ok_count = 0
err_count = 0

with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
    futuros = {ex.submit(descargar_estacion, sid): sid for sid in ESTACIONES}
    total   = len(futuros)
    done    = 0

    for fut in concurrent.futures.as_completed(futuros):
        sid = futuros[fut]
        done += 1
        try:
            sid_res, datos_por_fecha = fut.result()
            dias_ok = len(datos_por_fecha)
            if dias_ok > 0:
                ok_count += 1
                # Integrar en historial
                for fecha_key, datos in datos_por_fecha.items():
                    if fecha_key not in historial:
                        historial[fecha_key] = {}
                    if sid_res not in historial[fecha_key]:
                        historial[fecha_key][sid_res] = datos
                    else:
                        # Actualizar solo si mejora los datos existentes
                        ex_data = historial[fecha_key][sid_res]
                        if datos.get('tempMax') is not None:
                            ex_data['tempMax'] = datos['tempMax']
                        if datos.get('tempMin') is not None:
                            ex_data['tempMin'] = datos['tempMin']
                        if datos.get('precipTotal') is not None:
                            ex_data['precipTotal'] = datos['precipTotal']
                        if datos.get('lat') and not ex_data.get('lat'):
                            ex_data['lat'] = datos['lat']
                            ex_data['lon'] = datos['lon']
                print(f"  [{done:3}/{total}] ✅ {sid_res}: {dias_ok} días")
            else:
                err_count += 1
                print(f"  [{done:3}/{total}] ⚠ {sid_res}: sin datos")
        except Exception as e:
            err_count += 1
            print(f"  [{done:3}/{total}] ❌ {sid}: {e}")

# ── Guardar ───────────────────────────────────────────────────
# Mantener solo 14 días
for d in sorted(historial.keys())[:-14]:
    del historial[d]

with open(F_AGRI, 'w', encoding='utf-8') as f:
    json.dump(historial, f, ensure_ascii=False, indent=2)

dias_total = len(historial)
print(f"\n{'='*50}")
print(f"✅ Historial guardado: {dias_total} días")
print(f"   Estaciones con datos: {ok_count}/{len(ESTACIONES)}")
print(f"   Archivo: {F_AGRI}")

if dias_total >= 5:
    print(f"\n🎉 ¡Ya hay {dias_total} días! El riesgo se calculará en la próxima ejecución.")
    print(f"   Ejecuta ahora: python3 mapa_totana.py")
else:
    print(f"\n⏳ Días disponibles: {dias_total}/5")

# ── Subir a GitHub ────────────────────────────────────────────
import subprocess
print(f"\n☁️  Subiendo a GitHub...")
try:
    for cmd in [
        ["git","-C",REPO_DIR,"config","user.email","joseroquel@lopezyandreo.com"],
        ["git","-C",REPO_DIR,"config","user.name","Meteo Guadalentin Bot"],
        ["git","-C",REPO_DIR,"add","historial_agricola.json"],
        ["git","-C",REPO_DIR,"commit","-m",
         f"Historial inicial: {dias_total} días de {ok_count} estaciones WU"],
        ["git","-C",REPO_DIR,"push"],
    ]:
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            if "nothing to commit" in r.stdout+r.stderr:
                print("  ℹ Sin cambios nuevos")
                break
            print(f"  ⚠ {cmd[2]}: {r.stderr.strip()[:100]}")
            break
    else:
        print("  ✅ Subido a GitHub")
except Exception as e:
    print(f"  ⚠ {e}")
