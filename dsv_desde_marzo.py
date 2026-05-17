"""
dsv_desde_marzo.py
Descarga historial diario desde 01/03/2026 usando la API key de propietario WU
para las estaciones propias, y calcula el DSV acumulado de toda la temporada.
Ejecutar UNA SOLA VEZ:
  python3 dsv_desde_marzo.py
"""
import urllib.request, json, ssl, os, subprocess, time
from datetime import datetime, timedelta
import concurrent.futures

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

WU_KEY_OWNER = "1db09e2eed2740aeb09e2eed2790ae32"   # tu API key de propietario
WU_KEY_PUBLIC = "6532d6454b8aa370768e63d6ba5a832e"  # key pública para otras estaciones

REPO_DIR = os.path.expanduser("~/Documents/meteo-guadalentin")
F_DSV    = os.path.join(REPO_DIR, "historial_dsv.json")
F_AGRI   = os.path.join(REPO_DIR, "historial_agricola.json")
F_EST    = os.path.join(REPO_DIR, "estaciones.txt")

# Estaciones propias — con API key de propietario podemos ir más atrás
ESTACIONES_PROPIAS = [
    "ITOTAN2","ITOTAN5","ITOTAN8","ITOTAN9","ITOTAN10",
    "ITOTAN16","ITOTAN17","ITOTAN28","ITOTAN31","ITOTAN33",
    "ITOTAN41","ITOTAN42","ITOTAN43"
]

ESTACIONES_WU = [l.split('#')[0].strip() for l in open(F_EST) if l.split('#')[0].strip()]

# ── Tabla DSV Gubler-Thomas (1982) ────────────────────────────
DSV_TABLE = {
    (15,19): {(0,6):1,  (7,12):2,  (13,18):3,  (19,24):4},
    (19,22): {(0,6):2,  (7,12):3,  (13,18):4,  (19,24):5},
    (22,26): {(0,6):3,  (7,12):4,  (13,18):5,  (19,24):6},
    (26,40): {(0,6):2,  (7,12):3,  (13,18):4,  (19,24):5},
}

def dsv_dia(tmed, horas, prec=0):
    if prec and prec > 2.5: return 0
    if not tmed or tmed < 15: return 0
    for (a,b), cols in DSV_TABLE.items():
        if a <= tmed < b:
            for (h1,h2), v in cols.items():
                if h1 <= horas <= h2: return v
            return list(cols.values())[-1]
    return 0

def dist(la1, lo1, la2, lo2):
    return ((la1-la2)**2 + (lo1-lo2)**2)**0.5

# ── Descargar un día de una estación ─────────────────────────
def wu_dia(sid, fecha_wu, key):
    url = (f"https://api.weather.com/v2/pws/history/all"
           f"?stationId={sid}&format=json&units=m&numericPrecision=decimal"
           f"&date={fecha_wu}&apiKey={key}")
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://www.wunderground.com/'})
        with urllib.request.urlopen(req, context=ctx, timeout=10) as r:
            obs = json.loads(r.read().decode('utf-8')).get('observations', [])
        if not obs: return None
        temps_h = [o['metric']['tempHigh'] for o in obs if o.get('metric',{}).get('tempHigh') is not None]
        temps_l = [o['metric']['tempLow']  for o in obs if o.get('metric',{}).get('tempLow')  is not None]
        precs   = [o['metric']['precipTotal'] for o in obs if o.get('metric',{}).get('precipTotal') is not None]
        hums    = [o.get('humidityHigh', 0) for o in obs]
        if not temps_h: return None
        return {
            'tempMax':  round(max(temps_h), 1),
            'tempMin':  round(min(temps_l), 1) if temps_l else round(min(temps_h), 1),
            'precipTotal': round(max(precs), 1) if precs else 0.0,
            'hum_alta_h':  sum(1 for h in hums if h >= 85) * 5 / 60,  # horas
            'lat': obs[0].get('lat'),
            'lon': obs[0].get('lon')
        }
    except:
        return None

# ── Descargar historial completo de una estación propia ───────
def descargar_estacion_completa(sid, fechas, key):
    resultado = {}
    errores   = 0
    for fecha_dt in fechas:
        fecha_wu  = fecha_dt.strftime('%Y%m%d')
        fecha_key = fecha_dt.strftime('%Y-%m-%d')
        datos = wu_dia(sid, fecha_wu, key)
        if datos:
            resultado[fecha_key] = datos
        else:
            errores += 1
        time.sleep(0.05)  # pequeña pausa para no saturar la API
    return sid, resultado

# ── Principal ─────────────────────────────────────────────────
ahora  = datetime.now()
inicio = datetime(ahora.year, 3, 1)
fechas = [inicio + timedelta(days=i) for i in range((ahora - inicio).days)]

print(f"📅 Período: {inicio.strftime('%Y-%m-%d')} → {ahora.strftime('%Y-%m-%d')} ({len(fechas)} días)")
print(f"📡 Descargando historial de {len(ESTACIONES_PROPIAS)} estaciones propias...\n")

# Historial completo por estación propia {sid: {fecha: datos}}
historial_propio = {}

for sid in ESTACIONES_PROPIAS:
    print(f"  Descargando {sid}...", end=' ', flush=True)
    _, datos = descargar_estacion_completa(sid, fechas, WU_KEY_OWNER)
    historial_propio[sid] = datos
    dias_ok = len(datos)
    if dias_ok > 0:
        tmax_med = round(sum(d['tempMax'] for d in datos.values() if d.get('tempMax')) / dias_ok, 1)
        print(f"✅ {dias_ok} días (Tmax media={tmax_med}°C)")
    else:
        print(f"⚠ Sin datos")

print(f"\n✅ Historial descargado: {sum(len(v) for v in historial_propio.values())} entradas totales")

# ── Calcular DSV para cada estación WU ───────────────────────
print(f"\n🔬 Calculando DSV acumulado desde {inicio.strftime('%d/%m/%Y')}...\n")

# Cargar coordenadas WU
hagri   = json.load(open(F_AGRI,'r',encoding='utf-8')) if os.path.exists(F_AGRI) else {}
pos_wu  = {}
for fd in hagri.values():
    for sid, dd in fd.items():
        if sid not in pos_wu and dd.get('lat'):
            pos_wu[sid] = (dd['lat'], dd['lon'])

# Coordenadas de estaciones propias
for sid, datos in historial_propio.items():
    for dd in datos.values():
        if dd.get('lat') and sid not in pos_wu:
            pos_wu[sid] = (dd['lat'], dd['lon'])
            break

# Cargar DSV existente
dsv_hist = json.load(open(F_DSV,'r',encoding='utf-8')) if os.path.exists(F_DSV) else {}

# Para cada estación WU, asignar la estación propia más cercana como referencia
niveles = ['Sin riesgo','Vigilancia','Tratar pronto','URGENTE']
print(f"{'Estación':18} {'Ref':12} {'Días':5} {'DSV':5} {'Nivel'}")
print("─" * 60)

for sid in ESTACIONES_WU:
    la, lo = pos_wu.get(sid, (37.77, -1.5))

    # Buscar estación propia más cercana
    mejor_dist = 999
    mejor_ref  = None
    for sid_p in ESTACIONES_PROPIAS:
        if not historial_propio.get(sid_p): continue
        la_p, lo_p = pos_wu.get(sid_p, (37.77, -1.5))
        d2 = dist(la, lo, la_p, lo_p)
        if d2 < mejor_dist:
            mejor_dist, mejor_ref = d2, sid_p

    if not mejor_ref:
        continue

    ref_datos = historial_propio[mejor_ref]

    # Calcular DSV día a día
    dsv_acum = 0
    fechas_contadas = []

    for fecha_dt in fechas:
        fecha_key = fecha_dt.strftime('%Y-%m-%d')
        dd = ref_datos.get(fecha_key)
        if not dd: continue
        tmax = dd.get('tempMax')
        tmin = dd.get('tempMin')
        prec = dd.get('precipTotal', 0) or 0
        horas_hum = dd.get('hum_alta_h', 0)

        if tmax is None or tmin is None: continue
        tmed = round((tmax + tmin) / 2, 1)
        dsv  = dsv_dia(tmed, horas_hum, prec)
        dsv_acum += dsv
        fechas_contadas.append(fecha_key)

    # Añadir DSV de días WU recientes no cubiertos por estación de referencia
    dsv_wu_extra = dsv_hist.get(sid, {}).get('dsv_wu_extra', 0)
    dsv_total    = dsv_acum + dsv_wu_extra

    nivel = niveles[min(3, dsv_total // 20)]
    print(f"  {sid:18} {mejor_ref:12} {len(fechas_contadas):4}d {dsv_total:5}  {nivel}")

    dsv_hist[sid] = {
        'dsv_acumulado':   dsv_total,
        'dsv_temporada':   dsv_acum,
        'dsv_wu_extra':    dsv_wu_extra,
        'fechas':          fechas_contadas,
        'ref_estacion':    mejor_ref,
        'dias_calculados': len(fechas_contadas),
    }

# ── Guardar y subir ───────────────────────────────────────────
with open(F_DSV, 'w', encoding='utf-8') as f:
    json.dump(dsv_hist, f, ensure_ascii=False, indent=2)

print(f"\n✅ historial_dsv.json guardado — {len(dsv_hist)} estaciones")
print(f"\n☁️  Subiendo a GitHub...")

for cmd in [
    ["git","-C",REPO_DIR,"config","user.email","joseroquel@lopezyandreo.com"],
    ["git","-C",REPO_DIR,"config","user.name","Meteo Bot"],
    ["git","-C",REPO_DIR,"add","historial_dsv.json"],
    ["git","-C",REPO_DIR,"commit","-m",f"DSV temporada desde {inicio.strftime('%Y-%m-%d')}: {len(dsv_hist)} estaciones"],
    ["git","-C",REPO_DIR,"push"],
]:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        if "nothing to commit" in r.stdout+r.stderr:
            print("  ℹ Sin cambios nuevos"); break
        print(f"  ⚠ {r.stderr.strip()[:80]}"); break
else:
    print("  ✅ Subido a GitHub")

print(f"\n🎉 Listo. Ejecuta: python3 mapa_totana.py")
