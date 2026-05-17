"""
inicializar_dsv.py
Descarga datos diarios de AEMET desde 01/03/2026 hasta ayer
y calcula el DSV acumulado de oídio (Gubler-Thomas) para cada
estación WU usando la estación AEMET más cercana como referencia.

Ejecutar UNA SOLA VEZ desde la carpeta del repo:
  python3 inicializar_dsv.py
"""
import urllib.request, json, ssl, os, subprocess
from datetime import datetime, timedelta

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

AEMET_KEY = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJqb3Nlcm9xdWVAbG9wZXp5YW5kcmVvLmNvbSIsImp0aSI6ImFkNDI4NjkxLTI2ZWMtNDM2Ni04Zjc3LTAyNTBkOTE2ODk4NyIsImlzcyI6IkFFTUVUIiwiaWF0IjoxNzc4OTc2NjU2LCJ1c2VySWQiOiJhZDQyODY5MS0yNmVjLTQzNjYtOGY3Ny0wMjUwZDkxNjg5ODciLCJyb2xlIjoiIn0.0ncG0BPkrmqHDKbasNRAgVb_SlNNJl3Xz5LL9xE75l8"

REPO_DIR = os.path.expanduser("~/Documents/meteo-guadalentin")
F_DSV    = os.path.join(REPO_DIR, "historial_dsv.json")
F_AGRI   = os.path.join(REPO_DIR, "historial_agricola.json")
F_EST    = os.path.join(REPO_DIR, "estaciones.txt")

# Estaciones AEMET de referencia (IDs verificados)
AEMET_EST = [
    ("7218Y", "Totana",           37.769, -1.504),
    ("7209",  "Lorca",            37.679, -1.701),
    ("7227X", "Alhama de Murcia", 37.852, -1.425),
    ("7007Y", "Mazarrón",         37.598, -1.314),
    ("7211B", "Puerto Lumbreras", 37.561, -1.803),
    ("7023X", "Fuente Álamo",     37.712, -1.176),
    ("7203A", "Lorca/Zarcilla",   37.901, -1.810),
]

# Estaciones WU con sus coordenadas (del historial agrícola)
ESTACIONES_WU = [l.split('#')[0].strip() for l in open(F_EST) if l.split('#')[0].strip()]

# ── Tabla DSV Gubler-Thomas (1982) ────────────────────────────
# Tmed × horas humectación foliar (HR≥85%)
DSV_TABLE = {
    (15, 19): {(0,6):1,  (7,12):2,  (13,18):3,  (19,24):4},
    (19, 22): {(0,6):2,  (7,12):3,  (13,18):4,  (19,24):5},
    (22, 26): {(0,6):3,  (7,12):4,  (13,18):5,  (19,24):6},
    (26, 40): {(0,6):2,  (7,12):3,  (13,18):4,  (19,24):5},
}

def dsv_dia(tmed, horas_hum, prec=0):
    """DSV para un día. Lluvia >2.5mm lava esporas → DSV=0."""
    if prec and prec > 2.5: return 0
    if tmed is None or tmed < 15: return 0
    for (tmin_r, tmax_r), cols in DSV_TABLE.items():
        if tmin_r <= tmed < tmax_r:
            for (h_min, h_max), val in cols.items():
                if h_min <= horas_hum <= h_max:
                    return val
            return list(cols.values())[-1]
    return 0

def pf(v):
    if v is None: return None
    try: return float(str(v).replace(',', '.'))
    except: return None

def dist(la1, lo1, la2, lo2):
    return ((la1-la2)**2 + (lo1-lo2)**2)**0.5

# ── Descargar AEMET ───────────────────────────────────────────
def descargar_aemet(idema, fi, ff):
    path = (f"/api/valores/climatologicos/diarios/datos"
            f"/fechaini/{fi}/fechafin/{ff}/estacion/{idema}")
    try:
        req = urllib.request.Request(
            "https://opendata.aemet.es/opendata/api" + path,
            headers={'api_key': AEMET_KEY, 'cache-control': 'no-cache'})
        with urllib.request.urlopen(req, context=ctx, timeout=15) as r:
            meta = json.loads(r.read().decode('utf-8'))
        if meta.get('estado') != 200:
            print(f"    ⚠ {idema}: estado={meta.get('estado')} {meta.get('descripcion','')[:50]}")
            return []
        with urllib.request.urlopen(
                urllib.request.Request(meta['datos']),
                context=ctx, timeout=15) as r2:
            datos = json.loads(r2.read().decode('utf-8'))
        return datos
    except Exception as e:
        print(f"    ⚠ {idema}: {e}")
        return []

# ── Principal ─────────────────────────────────────────────────
ahora = datetime.now()

# Período: desde 01/03 de este año hasta ayer
inicio_temporada = datetime(ahora.year, 3, 1)
fi = inicio_temporada.strftime('%Y-%m-%dT00:00:00UTC')
ff = (ahora - timedelta(days=1)).strftime('%Y-%m-%dT23:59:59UTC')
dias_temporada = (ahora - inicio_temporada).days

print(f"📅 Período: {fi[:10]} → {ff[:10]} ({dias_temporada} días)")
print(f"📡 Descargando datos AEMET para {len(AEMET_EST)} estaciones...\n")

# Descargar datos AEMET por estación
aemet_datos = {}  # {idema: {fecha: {tmax, tmin, prec, hrmax}}}

for idema, nombre, lat, lon in AEMET_EST:
    print(f"  Descargando {idema} ({nombre})...")
    datos = descargar_aemet(idema, fi, ff)
    if datos:
        aemet_datos[idema] = {}
        for d in datos:
            fecha = d.get('fecha', '')
            if fecha:
                aemet_datos[idema][fecha] = {
                    'tmax':  pf(d.get('tmax')),
                    'tmin':  pf(d.get('tmin')),
                    'prec':  pf(d.get('prec')),
                    'hrmax': pf(d.get('hrmax')),
                    'hrmin': pf(d.get('hrmin')),
                    'lat': lat, 'lon': lon
                }
        print(f"    ✅ {len(aemet_datos[idema])} días descargados")
    else:
        print(f"    ❌ Sin datos")

if not aemet_datos:
    print("\n❌ No se obtuvieron datos de AEMET. Comprueba la conexión.")
    exit(1)

# ── Cargar posiciones WU del historial agrícola ───────────────
hagri = {}
if os.path.exists(F_AGRI):
    hagri = json.load(open(F_AGRI, 'r', encoding='utf-8'))

pos_wu = {}  # {sid: (lat, lon)}
for fecha_dia in hagri.values():
    for sid, dd in fecha_dia.items():
        if sid not in pos_wu and dd.get('lat'):
            pos_wu[sid] = (dd['lat'], dd['lon'])

print(f"\n📍 Estaciones WU con coordenadas: {len(pos_wu)}")

# ── Calcular DSV para cada estación WU ───────────────────────
print(f"\n🔬 Calculando DSV acumulado desde marzo...\n")

# Cargar DSV existente para no machacar datos ya guardados
dsv_hist = {}
if os.path.exists(F_DSV):
    dsv_hist = json.load(open(F_DSV, 'r', encoding='utf-8'))
    print(f"  ℹ DSV existente cargado: {len(dsv_hist)} estaciones")

# Generar lista de fechas del período
fechas = []
d = inicio_temporada
while d < ahora:
    fechas.append(d.strftime('%Y-%m-%d'))
    d += timedelta(days=1)

total_dsv = {}  # {sid: dsv_acumulado}

for sid in ESTACIONES_WU:
    la, lo = pos_wu.get(sid, (37.77, -1.5))

    # Encontrar estación AEMET más cercana
    mejor_dist = 999
    mejor_id   = None
    for idema, _, alat, alon in AEMET_EST:
        if idema not in aemet_datos: continue
        d2 = dist(la, lo, alat, alon)
        if d2 < mejor_dist:
            mejor_dist, mejor_id = d2, idema

    if not mejor_id:
        continue

    datos_ref = aemet_datos[mejor_id]

    # Calcular DSV acumulado para todas las fechas de la temporada
    dsv_acum  = 0
    fechas_contadas = []
    dsv_por_fecha = {}

    for fecha in fechas:
        dd = datos_ref.get(fecha)
        if not dd:
            continue
        tmax = dd.get('tmax')
        tmin = dd.get('tmin')
        prec = dd.get('prec') or 0
        hrmax = dd.get('hrmax')  # HR máxima del día
        hrmin = dd.get('hrmin')  # HR mínima del día

        if tmax is None or tmin is None:
            continue

        tmed = round((tmax + tmin) / 2, 1)

        # Estimar horas de humectación foliar desde HR
        # Si HRmax >= 85% estimamos horas proporcionales
        horas_hum = 0
        if hrmax is not None and hrmax >= 85:
            if hrmin is not None:
                # Proporción del día con HR alta según rango
                rango = hrmax - hrmin if hrmax > hrmin else 1
                prop_alta = max(0, (hrmax - 85) / rango) if rango > 0 else 0
                horas_hum = min(24, round(prop_alta * 24 + 4))  # mínimo 4h si HRmax>=85
            else:
                horas_hum = 8  # estimación conservadora

        dsv = dsv_dia(tmed, horas_hum, prec)
        dsv_acum += dsv
        fechas_contadas.append(fecha)
        dsv_por_fecha[fecha] = dsv

    total_dsv[sid] = dsv_acum

    # Combinar con DSV previo de WU propio si existe
    dsv_wu_prev = dsv_hist.get(sid, {}).get('dsv_acumulado', 0)
    fechas_wu   = set(dsv_hist.get(sid, {}).get('fechas', []))

    # Si el DSV de AEMET cubre fechas anteriores a las de WU, usarlo como base
    fechas_aemet_set = set(fechas_contadas)
    fechas_solo_wu   = fechas_wu - fechas_aemet_set

    # DSV de días WU que no están en AEMET (los más recientes)
    dsv_wu_extra = 0
    if fechas_solo_wu and sid in dsv_hist:
        # Aproximar: dsv_wu_prev - lo que cubría AEMET
        # Los días recientes de WU ya tienen DSV calculado
        dsv_wu_extra = dsv_hist.get(sid, {}).get('dsv_wu_extra', 0)

    dsv_total = dsv_acum + dsv_wu_extra

    dsv_hist[sid] = {
        'dsv_acumulado': dsv_total,
        'dsv_aemet':     dsv_acum,
        'dsv_wu_extra':  dsv_wu_extra,
        'fechas':        list(fechas_aemet_set | fechas_wu),
        'aemet_ref':     mejor_id,
        'dias_calculados': len(fechas_contadas),
    }

# Mostrar resumen
print(f"{'Estación':15} {'AEMET ref':10} {'Días':6} {'DSV':6} {'Nivel'}")
print("-" * 55)
niveles = ['Sin riesgo', 'Vigilancia', 'Tratar pronto', 'URGENTE']
for sid in sorted(dsv_hist.keys())[:20]:
    d = dsv_hist[sid]
    dsv = d.get('dsv_acumulado', 0)
    nivel = niveles[min(3, dsv//20)] if dsv < 60 else niveles[3]
    print(f"  {sid:15} {d.get('aemet_ref','?'):10} {d.get('dias_calculados',0):4}d  {dsv:4}  {nivel}")

if len(dsv_hist) > 20:
    print(f"  ... y {len(dsv_hist)-20} más")

# Guardar
with open(F_DSV, 'w', encoding='utf-8') as f:
    json.dump(dsv_hist, f, ensure_ascii=False, indent=2)
print(f"\n✅ historial_dsv.json guardado — {len(dsv_hist)} estaciones")

# Subir a GitHub
print("\n☁️  Subiendo a GitHub...")
for cmd in [
    ["git", "-C", REPO_DIR, "config", "user.email", "joseroquel@lopezyandreo.com"],
    ["git", "-C", REPO_DIR, "config", "user.name",  "Meteo Bot"],
    ["git", "-C", REPO_DIR, "add",    "historial_dsv.json"],
    ["git", "-C", REPO_DIR, "commit", "-m",
     f"DSV inicial temporada: {len(dsv_hist)} estaciones desde {fi[:10]}"],
    ["git", "-C", REPO_DIR, "push"],
]:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        if "nothing to commit" in r.stdout + r.stderr:
            print("  ℹ Sin cambios nuevos"); break
        print(f"  ⚠ {r.stderr.strip()[:80]}"); break
else:
    print("  ✅ Subido a GitHub")

print(f"\n🎉 Listo. Ahora ejecuta: python3 mapa_totana.py")
print(f"   El DSV acumulado desde {fi[:10]} ya está disponible.")
