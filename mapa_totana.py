import urllib.request, json, ssl, os, webbrowser, concurrent.futures, subprocess
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
F_AGRI   = os.path.join(REPO_DIR, 'historial_agricola.json')
F_DSV    = os.path.join(REPO_DIR, 'historial_dsv.json')
os.makedirs(DIR_PUB, exist_ok=True)

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
def hist24(nuevos, ahora):
    h   = leer(F_H24, [])
    lim = ahora - timedelta(hours=24)
    ok  = []
    for e in h:
        try:
            t = datetime.fromisoformat(e['timestamp'])
            if t.tzinfo is None: t = t.replace(tzinfo=ahora.tzinfo)
            if t > lim: ok.append(e)
        except: pass
    ok.append({'timestamp': ahora.isoformat(), 'stations': nuevos})
    guardar(F_H24, ok)
    print(f"  ✅ Historial 24h: {len(ok)} entradas")
    return ok

# ── Historial agrícola 14 días ────────────────────────────────
def hist_agri(nuevos, ahora):
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
            h[hoy][sid]['humedadAltaMinutos'] = h[hoy][sid].get('humedadAltaMinutos', 0) + 15

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

# ── Git push ──────────────────────────────────────────────────
def git_push(ahora):
    print("\n☁️  Subiendo a GitHub...")
    try:
        fecha_str = ahora.strftime("%Y-%m-%d %H:%M")
        for cmd in [
            ["git","-C",REPO_DIR,"config","user.email","joseroquel@lopezyandreo.com"],
            ["git","-C",REPO_DIR,"config","user.name","Meteo Guadalentin Bot"],
            ["git","-C",REPO_DIR,"add","history_24h.json","historial_agricola.json",
             "public/index.html"],
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
}

def generar_html(historial, riesgo_data, ahora, dias_acum):
    fa = ahora.strftime("%d/%m/%Y %H:%M:%S")
    aviso_dias = ""
    if dias_acum < MIN_DIAS:
        falt = MIN_DIAS - dias_acum
        aviso_dias = (f"⏳ Acumulando historial: {dias_acum}/{MIN_DIAS} días. "
                      f"Faltan {falt} día{'s' if falt>1 else ''} para activar el cálculo de riesgo.")

    js = ("var NOMBRES="+json.dumps(NOMBRES, ensure_ascii=False)+";\n"
         +"var historyData="+json.dumps(historial, ensure_ascii=False)+";\n"
         +"var riesgoData="+json.dumps(riesgo_data, ensure_ascii=False)+";\n"
         +"var AVISO_DIAS="+json.dumps(aviso_dias)+";\n"
         + JS_LOGICA)

    html = HTML_BASE.replace('__FECHA__', fa).replace('__JS__', js)
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
window.HO=0.35;

// ── Mapa base ──────────────────────────────────────────────
var terreno=L.tileLayer('http://{s}.google.com/vt/lyrs=p&x={x}&y={y}&z={z}',
  {maxZoom:20,subdomains:['mt0','mt1','mt2','mt3'],attribution:'© Google',className:'gmap'});
var claro=L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',{attribution:'© CARTO'});
var osm=L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'© OSM'});
var sat=L.tileLayer('http://{s}.google.com/vt/lyrs=s,h&x={x}&y={y}&z={z}',
  {maxZoom:20,subdomains:['mt0','mt1','mt2','mt3'],attribution:'© Google'});

var map=L.map('map',{center:[37.76,-1.53],zoom:10,layers:[terreno]});
map.createPane('hp');
map.getPane('hp').style.zIndex=390;
map.getPane('hp').style.filter='blur(14px)';

var rLG=L.layerGroup();
fetch('https://api.rainviewer.com/public/weather-maps.json')
  .then(function(r){return r.json();})
  .then(function(d){
    var l=d.radar.past[d.radar.past.length-1];
    rLG.addLayer(L.tileLayer(d.host+l.path+'/256/{z}/{x}/{y}/2/1_1.png',
      {opacity:0.7,zIndex:400,maxNativeZoom:7,maxZoom:18}));
  }).catch(function(){});

var mLG=L.layerGroup(),hLG=L.layerGroup(),HL=null;
var heatActive=true; // mapa de calor activo por defecto
L.control.layers(
  {'Relieve':terreno,'Claro':claro,'Satélite':sat,'OSM':osm},
  {
    'Radar lluvia':rLG,
    '🌈 Mapa de calor':hLG,
    '📍 Marcadores':mLG
  },
  {position:'topright',collapsed:true}
).addTo(map);
hLG.addTo(map);
mLG.addTo(map);
// Detectar cuando el usuario activa/desactiva el mapa de calor
map.on('overlayadd',   function(e){ if(e.name==='🌈 Mapa de calor'){ heatActive=true;  render(); }});
map.on('overlayremove',function(e){ if(e.name==='🌈 Mapa de calor'){ heatActive=false; hLG.clearLayers(); }});

// Botón ubicación
(function(){
  var b=L.control({position:'topleft'});
  b.onAdd=function(){
    var d=L.DomUtil.create('div','leaflet-bar leaflet-control');
    d.innerHTML='<a href="#" style="font-size:18px;background:white;display:flex;justify-content:center;align-items:center;width:30px;height:30px;text-decoration:none;" title="Mi ubicación">🎯</a>';
    L.DomEvent.on(d,'click',function(e){L.DomEvent.preventDefault(e);map.locate({setView:true,maxZoom:13});});
    return d;
  };
  b.addTo(map);
})();
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
function raw(est,p){
  if(p==='oidio'||p==='mildiu'){var r=riesgoData[est.stationID];return r?r[p]:null;}
  var m=est.metric; if(!m) return null;
  if(p==='precip')   return m.precipTotal;
  if(p==='temp')     return m.temp;
  if(p==='humidity') return est.humidity;
  if(p==='wind')     return m.windGust;
  return null;
}
function wdL(d){
  if(d==null) return '—';
  return['N','NNE','NE','ENE','E','ESE','SE','SSE','S','SSO','SO','OSO','O','ONO','NO','NNO'][Math.round(d/22.5)%16];
}
function fmtT(iso){
  var d=new Date(iso),n=new Date();
  return(d.getDate()===n.getDate()&&d.getMonth()===n.getMonth()?'Hoy':'Ayer')+
    ', '+d.toLocaleTimeString('es-ES',{hour:'2-digit',minute:'2-digit'});
}

// ── Leyenda ────────────────────────────────────────────────
var leg=L.control({position:'bottomleft'});
leg.onAdd=function(){this._d=L.DomUtil.create('div','legend');return this._d;};
leg.upd=function(p){
  var h='';
  if(p==='oidio'||p==='mildiu'){
    h='<b>'+(p==='oidio'?'🍇 Oídio':'🍃 Mildiu')+'</b><br>';
    h+='<i style="background:#aaa"></i>Sin datos<br>';
    for(var i=3;i>=0;i--) h+='<i style="background:'+RC[i]+'"></i>'+RL[i]+'<br>';
    h+='<small style="color:#888">'+(p==='oidio'?'Gubler-Thomas (UC Davis)':'Regla 10-10-10 + EPI')+'</small>';
  } else {
    var g,ti,u;
    if(p==='precip')   {ti='🌧 Precipitación';u='mm';   g=[0.5,2,4,10,20,30,40,50,70];}
    else if(p==='temp'){ti='🌡 Temperatura';  u='°C';   g=[5,10,15,20,25,30,35,40];}
    else if(p==='humidity'){ti='💧 Humedad'; u='%';    g=[30,50,70,90];}
    else               {ti='💨 Viento';      u='km/h'; g=[2,5,10,20,30,40];}
    h='<b>'+ti+'</b> <small>'+u+'</small><br>';
    h+='<i style="background:'+col(g[g.length-1],p)+'"></i>&gt;'+g[g.length-1]+'<br>';
    for(var i=g.length-2;i>=0;i--)
      h+='<i style="background:'+col(g[i],p)+'"></i>'+g[i]+'-'+g[i+1]+'<br>';
  }
  this._d.innerHTML=h;
};
leg.addTo(map);

// ── Panel lateral fijo ─────────────────────────────────────
var PS=null;
function showPanel(sid,html){
  document.getElementById('dc').innerHTML=html;
  document.getElementById('dp').style.display='flex';
  PS=sid;
}
function hidePanel(){
  document.getElementById('dp').style.display='none';
  PS=null;
}

// Mostrar aviso de días si procede
if(AVISO_DIAS){
  var av=document.getElementById('aviso-dias');
  if(av){av.textContent=AVISO_DIAS;av.style.display='block';}
}

// ── Render principal ───────────────────────────────────────
function render(){
  var p=document.getElementById('ps').value;
  var isR=p==='oidio'||p==='mildiu';
  leg.upd(p);
  if(heatActive) hLG.clearLayers(); mLG.clearLayers(); HL=null;

  var snap=isR?historyData[historyData.length-1]:historyData[CI];
  if(!snap) return;
  var feats=[];

  (snap.stations||[]).forEach(function(est){
    if(!est||est.lat==null||est.lon==null) return;
    var v=raw(est,p); if(v==null) return;
    var bg=col(v,p);
    var lb;
    if(isR)        lb=v<0?'?':['0','B','M','A'][Math.min(3,Math.max(0,Math.round(v)))];
    else if(p==='precip') lb=v.toFixed(1);
    else if(p==='temp')   lb=Math.round(v)+'°';
    else                   lb=Math.round(v)+'';

    var ws='';
    if(p==='wind'&&est.winddir!=null)
      ws='<svg style="position:absolute;top:-13px;left:-13px;width:50px;height:50px;'
        +'transform:rotate('+est.winddir+'deg);z-index:-1;pointer-events:none;"'
        +' viewBox="0 0 50 50"><line x1="25" y1="2" x2="25" y2="13" stroke="#333" stroke-width="2.5"/></svg>';

    var ih='<div style="position:relative;">'
      +'<div style="background:'+bg+';color:#fff;text-shadow:1px 1px 2px rgba(0,0,0,.7);'
      +'border:1.5px solid #fff;border-radius:50%;width:26px;height:26px;display:flex;'
      +'justify-content:center;align-items:center;font-weight:700;font-size:10px;'
      +'box-shadow:0 2px 5px rgba(0,0,0,.35);cursor:pointer;">'+lb+'</div>'+ws+'</div>';

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
        // Barra de progreso DSV
        var dsv=r.dsv_temporada||0;
        var dsvPct=Math.min(100,Math.round(dsv/60*100));
        var dsvCol=dsv<20?'#27ae60':dsv<40?'#f39c12':dsv<60?'#e67e22':'#c0392b';
        var dsvLabel=dsv<20?'Sin riesgo':dsv<40?'Vigilancia':dsv<60?'Tratar pronto':'Urgente';
        var dsvBar='<div style="margin-bottom:10px;">'
          +'<div style="display:flex;justify-content:space-between;font-size:11px;color:#888;margin-bottom:3px;">'
          +'<span>🍇 DSV Oídio temporada</span><span style="font-weight:700;color:'+dsvCol+'">'+dsv+' pts — '+dsvLabel+'</span></div>'
          +'<div style="background:#eee;border-radius:4px;height:8px;overflow:hidden;">'
          +'<div style="background:'+dsvCol+';width:'+dsvPct+'%;height:100%;border-radius:4px;transition:width .5s;"></div></div>'
          +'<div style="display:flex;justify-content:space-between;font-size:10px;color:#bbb;margin-top:2px;">'
          +'<span>0</span><span>20 ⚠</span><span>40 🔶</span><span>60 🔴</span></div>'
          +'<div style="font-size:11px;color:#aaa;margin-top:3px;">DSV 7d='+(r.dsv_7d||0)+' | DSV hoy='+(r.dsv_hoy||0)+'</div>'
          +'</div>';

        ph=av+dsvBar
          +'<div style="margin-bottom:6px;">'
          +'<b>🍇 Oídio:</b> <span style="padding:2px 9px;border-radius:10px;font-size:12px;'
          +'font-weight:700;color:#fff;background:'+(nO<0?'#aaa':RC[nO])+'">'
          +(nO<0?'Pendiente':RL[nO])+'</span></div>'
          +'<div style="font-size:12px;color:#555;margin-bottom:10px;">&bull; '+(dO||'—')+'</div>'
          +'<div style="margin-bottom:6px;">'
          +'<b>🍃 Mildiu:</b> <span style="padding:2px 9px;border-radius:10px;font-size:12px;'
          +'font-weight:700;color:#fff;background:'+(nM<0?'#aaa':RC[nM])+'">'
          +(nM<0?'Pendiente':RL[nM])+'</span></div>'
          +'<div style="font-size:12px;color:#555;margin-bottom:10px;">&bull; '+(dM||'—')+'</div>'
          +(r.fecha_sintomas?'<div style="background:#fef9e7;border:1px solid #f39c12;border-radius:6px;padding:6px 10px;font-size:12px;margin-bottom:10px;">📅 Síntomas mildiu estimados: <b>'+r.fecha_sintomas+'</b></div>':'')
          +'<hr style="border:0;border-top:1px solid #eee;margin:8px 0;">'
          +'<div style="font-size:12px;color:#666;">'
          +'🌡 '+(det.temp_actual!=null?det.temp_actual.toFixed(1)+'°C Tmed':'—')
          +' &nbsp;💧 '+(det.hum_actual!=null?det.hum_actual+'%':'—')+'<br>'
          +'🌧 Lluvia 10d='+(det.precip_10dias||0)+'mm'
          +' &nbsp;⏱ HR alta='+(det.horas_hum_alta_7d||0)+'h (7d)</div>'
          +'<div style="font-size:11px;color:#aaa;margin-top:8px;">📊 '+r.fuente_datos+'</div>';
      } else {
        ph='<div style="color:#999;font-size:13px;line-height:1.7;">Sin datos de riesgo.</div>';
      }
    } else {
      var m=est.metric||{};
      ph='<table style="width:100%;font-size:13px;border-collapse:collapse;line-height:2;">'
        +'<tr><td style="color:#888">🌡 Temperatura</td>'
        +'<td style="font-weight:700">'+(m.temp!=null?m.temp.toFixed(1)+'°C':'—')+'</td></tr>'
        +'<tr><td style="color:#888">🌧 Precipitación</td>'
        +'<td style="font-weight:700">'+(m.precipTotal!=null?m.precipTotal.toFixed(1)+' mm':'—')+'</td></tr>'
        +'<tr><td style="color:#888">💨 Viento</td>'
        +'<td style="font-weight:700">'+(m.windSpeed!=null?m.windSpeed.toFixed(0)+' km/h':'—')+' '+wdL(est.winddir)+'</td></tr>'
        +'<tr><td style="color:#888">⬆ Racha</td>'
        +'<td style="font-weight:700">'+(m.windGust!=null?m.windGust.toFixed(0)+' km/h':'—')+'</td></tr>'
        +'<tr><td style="color:#888">💧 Humedad</td>'
        +'<td style="font-weight:700">'+(est.humidity!=null?est.humidity+'%':'—')+'</td></tr>'
        +'<tr><td style="color:#888">🕒 Observación</td>'
        +'<td>'+(est.obsTimeLocal?est.obsTimeLocal.slice(11,16):'—')+'</td></tr>'
        +'</table>'
        +'<a href="https://www.wunderground.com/dashboard/pws/'+est.stationID
        +'" target="_blank" style="display:inline-block;margin-top:12px;padding:7px 16px;'
        +'background:#3498db;color:#fff;text-decoration:none;border-radius:6px;font-size:12px;">'
        +'Ver historial en WU ↗</a>';
    }

    var fh='<div style="font-size:15px;font-weight:700;color:#2c3e50;margin-bottom:4px;">'+nm+'</div>'
      +'<div style="font-size:11px;color:#bbb;margin-bottom:12px;">'+est.stationID+'</div>'+ph;

    (function(id,h){mk.on('click',function(){showPanel(id,h);});})(est.stationID,fh);
    mk.bindTooltip('<b>'+nm+'</b>',{direction:'top',offset:[0,-16],opacity:0.9});
    mLG.addLayer(mk);
    feats.push(turf.point([est.lon,est.lat],{value:v}));
  });

  // Heatmap interpolado para TODAS las variables incluidas oidio y mildiu
  // Para riesgo: solo estaciones con datos válidos (v>=0)
  var validFeats = isR ? feats.filter(function(f){return f.properties.value>=0;}) : feats;
  if(validFeats.length>2){
    try{
      var c=turf.featureCollection(validFeats);
      var weight=p==='temp'?2:p==='oidio'||p==='mildiu'?6:4;
      var g=turf.interpolate(c,p==='oidio'||p==='mildiu'?3:2.5,
        {gridType:'square',property:'value',units:'kilometers',weight:weight});
      var cl=turf.featureCollection(g.features.filter(function(f){
        return f.properties.value!=null&&!isNaN(f.properties.value);
      }));
      HL=L.geoJSON(cl,{pane:'hp',style:function(f){
        var v=f.properties.value;
        // Para riesgo: redondear al nivel más cercano para colores discretos
        if(p==='oidio'||p==='mildiu') v=Math.min(3,Math.max(0,Math.round(v)));
        return{fillColor:col(v,p),fillOpacity:window.HO,stroke:false};
      }});
      // Añadir a la capa correspondiente
      if(heatActive){
        hLG.clearLayers();
        hLG.addLayer(HL);
      }
    }catch(e){console.error('Heatmap:',e);}
  }
}

// ── Slider máquina del tiempo ──────────────────────────────
var sl=document.getElementById('sl');
var tl=document.getElementById('tl');
function initSl(){
  var n=historyData.length;
  if(!n){tl.innerText='Sin datos';return;}
  sl.min=0; sl.max=n-1; sl.value=n-1; CI=n-1;
  tl.innerText=fmtT(historyData[n-1].timestamp)+' (Actual)';
  render();
}
sl.addEventListener('input',function(){
  CI=parseInt(this.value);
  var last=CI===historyData.length-1;
  tl.innerText=fmtT(historyData[CI].timestamp)+(last?' (Actual)':' (Histórico)');
  render();
});
var PT=null;
document.getElementById('pb').addEventListener('click',function(){
  if(PT){clearInterval(PT);PT=null;this.textContent='▶️';}
  else{
    this.textContent='⏸️';
    if(CI>=historyData.length-1) CI=0;
    var s=this;
    PT=setInterval(function(){
      CI=(CI+1)%historyData.length;
      sl.value=CI;
      sl.dispatchEvent(new Event('input'));
      if(CI===historyData.length-1){clearInterval(PT);PT=null;s.textContent='▶️';}
    },1500);
  }
});
document.getElementById('op').addEventListener('input',function(){
  window.HO=parseFloat(this.value);
  if(HL) HL.setStyle({fillOpacity:window.HO});
});

initSl();
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
    *{box-sizing:border-box}
    body{font-family:'Segoe UI',sans-serif;margin:0;display:flex;flex-direction:column;height:100vh}
    header{background:#1a252f;color:#fff;padding:.6rem 1rem;display:flex;
      justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;
      flex-shrink:0;box-shadow:0 3px 8px rgba(0,0,0,.3)}
    h1{margin:0;font-size:1.1rem}
    .sub{font-size:.72rem;color:#bdc3c7;margin-top:2px}
    .ct{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
    select{padding:5px 9px;border-radius:6px;border:none;background:#ecf0f1;
      color:#2c3e50;font-weight:700;font-size:.82rem;cursor:pointer}
    #aviso-dias{display:none;background:#d6eaf8;border-left:4px solid #2980b9;
      padding:7px 14px;font-size:12px;color:#1a5276;flex-shrink:0}
    .ma{display:flex;flex:1;overflow:hidden}
    #map{flex:1;height:100%}
    #dp{display:none;flex-direction:column;width:285px;min-width:240px;
      background:#fff;border-left:1px solid #e0e0e0;overflow:hidden;flex-shrink:0}
    #dh{background:#1a252f;color:#fff;padding:9px 12px;display:flex;
      justify-content:space-between;align-items:center;flex-shrink:0;
      font-size:13px;font-weight:600}
    #cp{background:none;border:none;color:#fff;font-size:18px;cursor:pointer;padding:0 4px}
    #dc{padding:14px;font-size:13px;overflow-y:auto;flex:1}
    .legend{background:rgba(255,255,255,.95);padding:7px 10px;border-radius:8px;
      box-shadow:0 2px 10px rgba(0,0,0,.2);font-size:.75rem;line-height:1.8;
      color:#333;max-height:55vh;overflow-y:auto;max-width:150px}
    .legend i{width:14px;height:12px;float:left;margin-right:6px;
      opacity:.85;border:1px solid rgba(0,0,0,.1)}
    .gmap{filter:grayscale(100%) contrast(1.1) brightness(1.05)}
    @media(max-width:600px){
      header{flex-direction:column;align-items:flex-start}
      .ct{width:100%}
      #dp{width:100%;max-height:45vh}
    }
  </style>
</head>
<body>
<header>
  <div>
    <h1>🌿 Meteo Guadalentín</h1>
    <div class="sub">Actualizado: <span id="tl">__FECHA__</span></div>
  </div>
  <div class="ct">
    <div style="display:flex;flex-direction:column;align-items:center;gap:2px">
      <span style="font-size:.68rem;color:#ecf0f1;font-weight:700">⏱ Máquina del Tiempo</span>
      <div style="display:flex;align-items:center;gap:4px">
        <button id="pb" style="background:transparent;color:#fff;border:none;cursor:pointer;font-size:1rem;padding:0 3px">▶️</button>
        <input type="range" id="sl" min="0" max="0" value="0" style="width:120px;cursor:pointer">
      </div>
    </div>
    <div style="display:flex;flex-direction:column;align-items:center;gap:2px">
      <span style="font-size:.68rem;color:#ecf0f1;font-weight:700">🔆 Opacidad</span>
      <input type="range" id="op" min="0" max="1" step="0.05" value="0.35" style="width:75px;cursor:pointer">
    </div>
    <select id="ps" onchange="render()">
      <option value="temp" selected>🌡 Temperatura (°C)</option>
      <option value="precip">🌧 Precipitación (mm)</option>
      <option value="humidity">💧 Humedad (%)</option>
      <option value="wind">💨 Viento (km/h)</option>
      <option value="oidio">🍇 Riesgo Oídio</option>
      <option value="mildiu">🍃 Riesgo Mildiu</option>
    </select>
  </div>
</header>
<div id="aviso-dias"></div>
<div class="ma">
  <div id="map"></div>
  <div id="dp">
    <div id="dh">
      <span>Detalle de estación</span>
      <button id="cp" onclick="hidePanel()" title="Cerrar">✕</button>
    </div>
    <div id="dc">
      <p style="color:#aaa;font-size:13px;line-height:1.7">
        Haz clic en una estación del mapa para ver sus datos aquí.
      </p>
    </div>
  </div>
</div>
<script>__JS__</script>
<script>
// Auto-recarga de datos cada 5 minutos
setTimeout(function(){ location.reload(); }, 5*60*1000);
</script>
</body>
</html>"""

# ── Principal ─────────────────────────────────────────────────
def principal():
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

    print("\n📚 Historial 24h...")
    h24 = hist24(datos_wu, ahora)

    print("\n🌾 Historial agrícola...")
    hagri = hist_agri(datos_wu, ahora)
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

    print("\n🗺  Generando HTML...")
    ruta = generar_html(h24, r, ahora, dias_acum)

    print("\n☁️  Subiendo a GitHub...")
    git_push(ahora)

    print(f"\n✅ Listo")
    print(f"🌐 https://jorloan.github.io/meteo-guadalentin/")
    if not os.environ.get('CI'):
        webbrowser.open('file://' + ruta)

if __name__ == "__main__":
    principal()
