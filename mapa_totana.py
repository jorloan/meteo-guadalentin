import urllib.request
import json
import ssl
import os
import webbrowser
from datetime import datetime, timedelta
import concurrent.futures

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

# ── Keys ──────────────────────────────────────────────────────
WU_KEY   = "6532d6454b8aa370768e63d6ba5a832e"   # key interna wunderground.com
AEMET_KEY = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJqb3Nlcm9xdWVAbG9wZXp5YW5kcmVvLmNvbSIsImp0aSI6ImM5OWQwMjdhLWFkOTgtNDI1Yi04ZGRiLTY3ZGNjNzdjMzRkYyIsImlzcyI6IkFFTUVUIiwiaWF0IjoxNzc4NDQ2MTgxLCJ1c2VySWQiOiJjOTlkMDI3YS1hZDk4LTQyNWItOGRkYi02N2RjYzc3YzM0ZGMiLCJyb2xlIjoiIn0.QAttE468tO9unX9oJMFIjEyhlDEr5IkBpdMOFR6-tyg"

# Estaciones AEMET de referencia para la zona (idema, nombre, lat, lon)
AEMET_ESTACIONES = [
    ("7228",  "Totana (AEMET)",          37.769, -1.504),
    ("7228B", "Lorca (AEMET)",           37.679, -1.701),
    ("7213",  "Alhama de Murcia (AEMET)",37.852, -1.425),
    ("7031",  "Mazarrón (AEMET)",        37.631, -1.316),
    ("7209",  "Lorca/Zarzilla (AEMET)",  37.901, -1.810),
]

ARCHIVO_ESTACIONES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'estaciones.txt')
if not os.path.exists(ARCHIVO_ESTACIONES):
    with open(ARCHIVO_ESTACIONES, 'w', encoding='utf-8') as f:
        f.write("# Estaciones Weather Underground\n")
        for e in ["ITOTAN8","ITOTAN2","ITOTAN16","ITOTAN5","ITOTAN33","ITOTAN43",
                  "ITOTAN31","ITOTAN42","ITOTAN9","ITOTAN41","ITOTAN10","ITOTAN17"]:
            f.write(f"{e}\n")

ESTACIONES_WU = []
with open(ARCHIVO_ESTACIONES, 'r', encoding='utf-8') as f:
    for linea in f:
        l = linea.split('#')[0].strip()
        if l:
            ESTACIONES_WU.append(l)

DIR_PUBLICO = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'public')

# ─────────────────────────────────────────────────────────────
# WU: obtener observación actual de una estación
# ─────────────────────────────────────────────────────────────
def obtener_wu(station_id):
    url = (f"https://api.weather.com/v2/pws/observations/current"
           f"?stationId={station_id}&format=json&units=m&numericPrecision=decimal&apiKey={WU_KEY}")
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
            'Referer': 'https://www.wunderground.com/'
        })
        with urllib.request.urlopen(req, context=ctx, timeout=6) as r:
            if r.getcode() == 200:
                obs = json.loads(r.read().decode('utf-8')).get('observations', [])
                return obs[0] if obs else None
    except Exception as e:
        print(f"  ⚠ WU {station_id}: {e}")
    return None

# ─────────────────────────────────────────────────────────────
# AEMET: datos climatológicos diarios últimos N días
# Devuelve dict {idema: [{'fecha','tmax','tmin','prec','hrmax','hrmin'}, ...]}
# ─────────────────────────────────────────────────────────────
def obtener_aemet_diarios(dias=14):
    ahora = datetime.now()
    fi = (ahora - timedelta(days=dias)).strftime('%Y-%m-%dT00:00:00UTC')
    ff = (ahora - timedelta(days=1)).strftime('%Y-%m-%dT23:59:59UTC')

    resultado = {}
    for idema, nombre, lat, lon in AEMET_ESTACIONES:
        path = f"/api/valores/climatologicos/diarios/datos/fechaini/{fi}/fechafin/{ff}/estacion/{idema}"
        try:
            url = "https://opendata.aemet.es/opendata/api" + path
            req = urllib.request.Request(url, headers={'api_key': AEMET_KEY})
            with urllib.request.urlopen(req, context=ctx, timeout=10) as r:
                meta = json.loads(r.read().decode('utf-8'))
            if meta.get('estado') != 200:
                print(f"  ⚠ AEMET {idema}: estado={meta.get('estado')}")
                continue
            req2 = urllib.request.Request(meta['datos'])
            with urllib.request.urlopen(req2, context=ctx, timeout=10) as r2:
                datos = json.loads(r2.read().decode('ISO-8859-15'))

            dias_lista = []
            for d in datos:
                def parse_float(v):
                    if v is None: return None
                    try: return float(str(v).replace(',', '.'))
                    except: return None
                dias_lista.append({
                    'fecha': d.get('fecha', ''),
                    'tmax':  parse_float(d.get('tmax')),
                    'tmin':  parse_float(d.get('tmin')),
                    'prec':  parse_float(d.get('prec')),
                    'hrmax': parse_float(d.get('hrmax')),
                    'hrmin': parse_float(d.get('hrmin')),
                    'lat': lat, 'lon': lon, 'nombre': nombre
                })
            resultado[idema] = dias_lista
            print(f"  ✅ AEMET {idema} ({nombre}): {len(dias_lista)} días")
        except Exception as e:
            print(f"  ⚠ AEMET {idema} ({nombre}): {e}")

    return resultado

# ─────────────────────────────────────────────────────────────
# HISTORIAL 24H
# ─────────────────────────────────────────────────────────────
def gestionar_historial(nuevos_datos, ahora):
    url_historico = "https://jorloan.github.io/meteo-guadalentin/history_24h.json"
    historial = []
    try:
        req = urllib.request.Request(url_historico, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=ctx, timeout=5) as r:
            if r.getcode() == 200:
                historial = json.loads(r.read().decode('utf-8'))
                print(f"  ✅ Historial 24h: {len(historial)} registros.")
                if historial and any(
                    not e.get('stationID','I').startswith('I')
                    for e in historial[-1].get('stations', [])
                ):
                    historial = []
    except Exception as e:
        print(f"  ℹ Historial previo no disponible: {e}")

    limite = ahora - timedelta(hours=24)
    historial_limpio = []
    for h in historial:
        try:
            t = datetime.fromisoformat(h['timestamp'])
            if t.tzinfo is None:
                t = t.replace(tzinfo=ahora.tzinfo)
            if t > limite:
                historial_limpio.append(h)
        except Exception:
            pass

    historial_limpio.append({'timestamp': ahora.isoformat(), 'stations': nuevos_datos})
    os.makedirs(DIR_PUBLICO, exist_ok=True)
    with open(os.path.join(DIR_PUBLICO, 'history_24h.json'), 'w', encoding='utf-8') as f:
        json.dump(historial_limpio, f, ensure_ascii=False)
    return historial_limpio

# ─────────────────────────────────────────────────────────────
# HISTORIAL AGRÍCOLA 14 DÍAS (WU)
# ─────────────────────────────────────────────────────────────
def gestionar_historial_agricola(nuevos_datos, ahora):
    url_agricola = "https://jorloan.github.io/meteo-guadalentin/historial_agricola.json"
    historico = {}
    try:
        req = urllib.request.Request(url_agricola, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=ctx, timeout=5) as r:
            if r.getcode() == 200:
                historico = json.loads(r.read().decode('utf-8'))
                print(f"  ✅ Historial agrícola: {len(historico)} días.")
    except Exception as e:
        print(f"  ℹ Historial agrícola no disponible: {e}")

    fecha_hoy = ahora.strftime('%Y-%m-%d')
    if fecha_hoy not in historico:
        historico[fecha_hoy] = {}

    for est in nuevos_datos:
        if not est or 'stationID' not in est:
            continue
        sid    = est['stationID']
        temp   = est.get('metric', {}).get('temp')
        precip = est.get('metric', {}).get('precipTotal')
        hum    = est.get('humidity')

        if sid not in historico[fecha_hoy]:
            historico[fecha_hoy][sid] = {
                'tempMax': temp if temp is not None else -99,
                'tempMin': temp if temp is not None else  99,
                'precipTotal': precip if precip is not None else 0.0,
                'humedadAltaMinutos': 0
            }
        else:
            d = historico[fecha_hoy][sid]
            if temp is not None:
                if temp > d.get('tempMax', -99): d['tempMax'] = temp
                if temp < d.get('tempMin',  99): d['tempMin'] = temp
            if precip is not None:
                if precip > d.get('precipTotal', 0): d['precipTotal'] = precip
        if hum is not None and hum >= 85:
            historico[fecha_hoy][sid]['humedadAltaMinutos'] = (
                historico[fecha_hoy][sid].get('humedadAltaMinutos', 0) + 15)

    dias = sorted(historico.keys())
    for d in dias[:-14]:
        del historico[d]

    os.makedirs(DIR_PUBLICO, exist_ok=True)
    with open(os.path.join(DIR_PUBLICO, 'historial_agricola.json'), 'w', encoding='utf-8') as f:
        json.dump(historico, f, ensure_ascii=False)
    return historico

# ─────────────────────────────────────────────────────────────
# CALCULAR RIESGO OÍDIO / MILDIU
# Fuentes: historial WU propio + datos AEMET oficiales como respaldo
# Mínimo requerido: 5 días de datos para calcular riesgo
# ─────────────────────────────────────────────────────────────
MIN_DIAS_RIESGO = 5

def calcular_riesgo(historico_wu, aemet_diarios, datos_actuales):
    """
    Para cada estación WU activa calcula riesgo oidio/mildiu.
    Si no hay suficientes días propios, busca la estación AEMET más cercana.
    Devuelve dict {stationID: {...riesgo, fuente_datos, dias_disponibles}}
    """
    actuales = {e['stationID']: e for e in datos_actuales if e and 'stationID' in e}
    dias_wu   = sorted(historico_wu.keys())
    riesgo    = {}

    for sid, est in actuales.items():
        temp_act = est.get('metric', {}).get('temp')
        hum_act  = est.get('humidity')
        lat_est  = est.get('lat', 0)
        lon_est  = est.get('lon', 0)
        if temp_act is None:
            continue

        # ── 1. Recopilar datos WU propios ──────────────────────
        dias_propios = dias_wu[-14:] if len(dias_wu) >= 14 else dias_wu
        filas_wu = []
        for fecha in dias_propios:
            dd = historico_wu[fecha].get(sid)
            if dd:
                filas_wu.append({
                    'fecha': fecha,
                    'tmax':  dd.get('tempMax', None),
                    'tmin':  dd.get('tempMin', None),
                    'prec':  dd.get('precipTotal', 0),
                    'hum_alta_min': dd.get('humedadAltaMinutos', 0),
                    'fuente': 'WU'
                })

        # ── 2. Si faltan días, rellenar con AEMET más cercana ──
        fuente_aemet = None
        if len(filas_wu) < MIN_DIAS_RIESGO and aemet_diarios:
            # Buscar estación AEMET más cercana
            mejor_dist = 999
            mejor_id   = None
            for idema, (_, _, alat, alon) in zip(
                    [e[0] for e in AEMET_ESTACIONES],
                    AEMET_ESTACIONES):
                dist = ((lat_est - alat)**2 + (lon_est - alon)**2)**0.5
                if dist < mejor_dist and idema in aemet_diarios:
                    mejor_dist = dist
                    mejor_id   = idema

            if mejor_id:
                fuente_aemet = mejor_id
                fechas_wu_set = {f['fecha'] for f in filas_wu}
                for da in aemet_diarios[mejor_id]:
                    if da['fecha'] not in fechas_wu_set:
                        # Humedad alta estimada: si hrmin < 60 y hrmax > 85 → ~4h alta
                        hum_est = 0
                        if da.get('hrmax') and da['hrmax'] >= 85:
                            hum_est = 240  # estimamos 4h en minutos
                        filas_wu.append({
                            'fecha': da['fecha'],
                            'tmax':  da.get('tmax'),
                            'tmin':  da.get('tmin'),
                            'prec':  da.get('prec') or 0,
                            'hum_alta_min': hum_est,
                            'fuente': f"AEMET:{mejor_id}"
                        })
                filas_wu.sort(key=lambda x: x['fecha'])
                filas_wu = filas_wu[-14:]

        dias_disponibles = len(filas_wu)
        fuente_label = "WU propio"
        if fuente_aemet:
            n_aemet = sum(1 for f in filas_wu if 'AEMET' in f.get('fuente',''))
            if n_aemet > 0:
                nombre_aemet = next((e[1] for e in AEMET_ESTACIONES if e[0]==fuente_aemet), fuente_aemet)
                fuente_label = f"WU + AEMET ({nombre_aemet}, {n_aemet}d)"

        # ── 3. Calcular métricas acumuladas ────────────────────
        precip_10d    = sum(f['prec'] or 0 for f in filas_wu[-10:])
        tmin_min      = min((f['tmin'] for f in filas_wu if f['tmin'] is not None), default=99)
        dias_tmed15   = sum(
            1 for f in filas_wu
            if f['tmax'] is not None and f['tmin'] is not None
            and (f['tmax']+f['tmin'])/2 >= 15
        )
        horas_hum85   = sum(f.get('hum_alta_min',0) for f in filas_wu[-7:]) / 60.0

        # ── 4. Aviso insuficiencia ─────────────────────────────
        datos_ok = dias_disponibles >= MIN_DIAS_RIESGO

        # ── 5. Modelo OÍDIO (Gubler-Thomas UC Davis) ──────────
        nivel_oidio   = 0
        detalle_oidio = []
        if not datos_ok:
            detalle_oidio.append(f"⚠ Solo {dias_disponibles} días de datos (mínimo {MIN_DIAS_RIESGO})")
            nivel_oidio = -1  # señal de "no calculable"
        else:
            if temp_act >= 15 and dias_tmed15 >= 5:
                detalle_oidio.append(f"{dias_tmed15} días con Tmed≥15°C")
                if 15 <= temp_act < 19:
                    nivel_oidio = 1
                    detalle_oidio.append(f"T={temp_act:.1f}°C (rango bajo)")
                elif 19 <= temp_act <= 26:
                    nivel_oidio = 3 if horas_hum85 >= 4 else 2
                    detalle_oidio.append(f"T={temp_act:.1f}°C (rango óptimo)")
                    if horas_hum85 >= 4:
                        detalle_oidio.append(f"{horas_hum85:.1f}h con HR≥85% (7d)")
                elif temp_act > 26:
                    nivel_oidio = 3 if (hum_act or 0) >= 70 else 2
                    detalle_oidio.append(f"T={temp_act:.1f}°C + HR={hum_act}%")
            elif temp_act >= 18:
                nivel_oidio = 1
                detalle_oidio.append(f"Solo {dias_tmed15} días cálidos acumulados")
            else:
                detalle_oidio.append(f"T={temp_act:.1f}°C — por debajo del umbral")

        # ── 6. Modelo MILDIU (10-10-10 + EPI) ─────────────────
        nivel_mildiu   = 0
        detalle_mildiu = []
        if not datos_ok:
            detalle_mildiu.append(f"⚠ Solo {dias_disponibles} días de datos (mínimo {MIN_DIAS_RIESGO})")
            nivel_mildiu = -1
        else:
            cond_temp   = tmin_min > 10 or temp_act > 10
            cond_lluvia = precip_10d >= 10
            cond_dias   = dias_disponibles >= 7
            if cond_temp:   detalle_mildiu.append(f"Tmin>{10}°C ✓")
            if cond_lluvia: detalle_mildiu.append(f"Lluvia 10d={precip_10d:.1f}mm ✓")
            if cond_dias:   detalle_mildiu.append(f"{dias_disponibles} días historial ✓")
            nc = sum([cond_temp, cond_lluvia, cond_dias])
            if nc == 3:
                nivel_mildiu = 3 if (18<=temp_act<=24 and (hum_act or 0)>=85) else 2
                if temp_act > 30:
                    nivel_mildiu = max(0, nivel_mildiu-1)
                    detalle_mildiu.append("T>30°C inhibe desarrollo")
            elif nc == 2:
                nivel_mildiu = 1
            if nc < 3 and not cond_lluvia:
                detalle_mildiu.append(f"Lluvia 10d={precip_10d:.1f}mm (necesita ≥10mm)")
            if nc < 3 and not cond_dias:
                detalle_mildiu.append(f"Acumulando historial ({dias_disponibles}/{MIN_DIAS_RIESGO} días)")

        riesgo[sid] = {
            'lat': lat_est, 'lon': lon_est,
            'oidio':  nivel_oidio,
            'mildiu': nivel_mildiu,
            'datos_ok': datos_ok,
            'dias_disponibles': dias_disponibles,
            'fuente_datos': fuente_label,
            'detalles': {
                'oidio':  detalle_oidio,
                'mildiu': detalle_mildiu,
                'temp_actual':       temp_act,
                'hum_actual':        hum_act,
                'precip_10dias':     round(precip_10d, 1),
                'dias_tmed_sobre15': dias_tmed15,
                'horas_hum_alta_7d': round(horas_hum85, 1),
            }
        }

    return riesgo

# ─────────────────────────────────────────────────────────────
# GENERAR HTML
# ─────────────────────────────────────────────────────────────
def generar_html(historial_data, riesgo_agricola, ahora):
    fecha_actualizada = ahora.strftime("%d/%m/%Y %H:%M:%S")
    history_json = json.dumps(historial_data,   ensure_ascii=False)
    riesgo_json  = json.dumps(riesgo_agricola,  ensure_ascii=False)
    nombres_json = json.dumps({
        "ITOTAN8":  "Mirador - Lebor Alto",
        "ITOTAN2":  "METEO UNDERWORLD",
        "ITOTAN16": "Mortí Bajo - Camino Aleurrosas",
        "ITOTAN5":  "Estación Tierno Galván",
        "ITOTAN33": "Huerto Hostench",
        "ITOTAN43": "Casa Totana",
        "ITOTAN31": "CAMPING Lebor - Totana",
        "ITOTAN42": "Secanos",
        "ITOTAN9":  "LA CANAL - Raiguero",
        "ITOTAN41": "Ecowitt WN1981",
        "ITOTAN10": "WS Rancho",
        "ITOTAN17": "La Barquilla",
        "IALHAM13": "Alhama Norte",
        "IALHAM81": "Alhama Centro",
        "ILORCA22": "Lorca Sur",
        "IMAZAR7":  "Puerto Mazarrón"
    }, ensure_ascii=False)

    # JavaScript completamente separado del f-string de Python
    js = (
        "var NOMBRES      = " + nombres_json    + ";\n"
        "var historyData  = " + history_json    + ";\n"
        "var riesgoData   = " + riesgo_json     + ";\n"
        + r"""
var RIESGO_COLORS = ['#27ae60','#f39c12','#e67e22','#c0392b'];
var RIESGO_LABELS = ['Sin riesgo','Riesgo bajo','Riesgo medio','Riesgo ALTO'];
var currentIndex  = historyData.length - 1;
window.heatOpacity = 0.35;

// ── Capas base ─────────────────────────────────────────────
var terreno = L.tileLayer('http://{s}.google.com/vt/lyrs=p&x={x}&y={y}&z={z}',
    {maxZoom:20,subdomains:['mt0','mt1','mt2','mt3'],attribution:'© Google',className:'grayscale-map'});
var mapaClaro = L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',{attribution:'© CARTO'});
var estandar  = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'© OSM'});
var googleSat = L.tileLayer('http://{s}.google.com/vt/lyrs=s,h&x={x}&y={y}&z={z}',
    {maxZoom:20,subdomains:['mt0','mt1','mt2','mt3'],attribution:'© Google'});

var map = L.map('map',{center:[37.76,-1.53],zoom:10,layers:[terreno]});
map.createPane('heatPane');
map.getPane('heatPane').style.zIndex = 390;
map.getPane('heatPane').style.filter = 'blur(14px)';

var radarLG = L.layerGroup();
fetch('https://api.rainviewer.com/public/weather-maps.json')
    .then(function(r){return r.json();})
    .then(function(d){
        var last=d.radar.past[d.radar.past.length-1];
        radarLG.addLayer(L.tileLayer(d.host+last.path+'/256/{z}/{x}/{y}/2/1_1.png',
            {opacity:0.7,zIndex:400,attribution:'RainViewer',maxNativeZoom:7,maxZoom:18}));
    }).catch(function(){});

var markersLG = L.layerGroup();
var heatLG    = L.layerGroup();
var heatLayer = null;

L.control.layers(
    {'Relieve':terreno,'Mapa Claro':mapaClaro,'Satélite':googleSat,'Estándar':estandar},
    {'Radar Lluvia':radarLG,'Mapa Calor':heatLG,'Etiquetas':markersLG},
    {position:'topright',collapsed:true}
).addTo(map);
heatLG.addTo(map);
markersLG.addTo(map);

// Botón localización
(function(){
    var btn=L.control({position:'topleft'});
    btn.onAdd=function(){
        var d=L.DomUtil.create('div','leaflet-bar leaflet-control');
        d.innerHTML='<a href="#" title="Mi ubicación" style="font-size:18px;background:white;display:flex;justify-content:center;align-items:center;width:30px;height:30px;text-decoration:none;">🎯</a>';
        L.DomEvent.on(d,'click',function(e){L.DomEvent.preventDefault(e);map.locate({setView:true,maxZoom:13});});
        return d;
    };
    btn.addTo(map);
})();
var userMk=null;
map.on('locationfound',function(e){
    if(userMk) map.removeLayer(userMk);
    userMk=L.circleMarker(e.latlng,{radius:8,color:'#3498db',fillColor:'#3498db',fillOpacity:0.8})
        .addTo(map).bindPopup('Estás aquí').openPopup();
});

// ── Colores ───────────────────────────────────────────────
function lerpColor(c1,c2,t){
    return 'rgb('+Math.round(c1[0]+t*(c2[0]-c1[0]))+','+Math.round(c1[1]+t*(c2[1]-c1[1]))+','+Math.round(c1[2]+t*(c2[2]-c1[2]))+')';
}
function getColor(val,param){
    if(param==='oidio'||param==='mildiu'){
        if(val<0) return '#aaa';
        return RIESGO_COLORS[Math.min(3,Math.max(0,Math.round(val)))];
    }
    if(param==='temp'){
        var s=[{v:-5,c:[148,0,211]},{v:0,c:[0,0,200]},{v:5,c:[0,115,255]},
               {v:10,c:[0,200,200]},{v:15,c:[50,205,50]},{v:20,c:[255,255,0]},
               {v:25,c:[255,140,0]},{v:30,c:[220,20,60]},{v:35,c:[139,0,0]},{v:40,c:[200,0,200]}];
        if(val<=s[0].v) return 'rgb('+s[0].c+')';
        if(val>=s[s.length-1].v) return 'rgb('+s[s.length-1].c+')';
        for(var i=0;i<s.length-1;i++){if(val>=s[i].v&&val<=s[i+1].v)
            return lerpColor(s[i].c,s[i+1].c,(val-s[i].v)/(s[i+1].v-s[i].v));}
    }
    if(param==='precip')  return val>=70?'#ff0000':val>=50?'#ff99ff':val>=40?'#cc66ff':val>=30?'#993399':val>=20?'#660099':val>=10?'#0000ff':val>=4?'#3366ff':val>=2?'#00ccff':val>=0.5?'#99ffff':val>0?'#e6ffff':'transparent';
    if(param==='humidity') return val>=90?'#0d47a1':val>=70?'#1976d2':val>=50?'#42a5f5':'#90caf9';
    if(param==='wind')    return val>=40?'#b71c1c':val>=30?'#e65100':val>=20?'#f57f17':val>=10?'#fbc02d':val>=5?'#81c784':'#b2dfdb';
    return '#aaa';
}
function getRaw(est,param){
    if(param==='oidio'||param==='mildiu'){var r=riesgoData[est.stationID];return r?r[param]:null;}
    var m=est.metric;if(!m)return null;
    if(param==='precip')   return m.precipTotal;
    if(param==='temp')     return m.temp;
    if(param==='humidity') return est.humidity;
    if(param==='wind')     return m.windGust;
    return null;
}

// ── Leyenda ───────────────────────────────────────────────
var legend=L.control({position:'bottomleft'});
legend.onAdd=function(){this._div=L.DomUtil.create('div','legend');return this._div;};
legend.update=function(param){
    var h='';
    if(param==='oidio'||param==='mildiu'){
        h='<div style="margin-bottom:5px;font-weight:bold;">'+(param==='oidio'?'🍇 Oídio':'🍃 Mildiu')+'</div>';
        h+='<div><i style="background:#aaa"></i>Sin datos</div>';
        for(var i=3;i>=0;i--) h+='<div><i style="background:'+RIESGO_COLORS[i]+'"></i>'+RIESGO_LABELS[i]+'</div>';
        h+='<div style="margin-top:5px;font-size:0.65rem;color:#666;">'+(param==='oidio'?'Gubler-Thomas (UC Davis)':'10-10-10 + EPI')+'</div>';
    } else {
        var grades,title,unit;
        if(param==='precip')   {title='🌧 Precipitación';unit='mm';   grades=[0.5,2,4,10,20,30,40,50,70];}
        if(param==='temp')     {title='🌡 Temperatura';  unit='°C';   grades=[5,10,15,20,25,30,35,40];}
        if(param==='humidity') {title='💧 Humedad';      unit='%';    grades=[30,50,70,90];}
        if(param==='wind')     {title='💨 Viento';       unit='km/h'; grades=[2,5,10,20,30,40];}
        h='<div style="margin-bottom:4px;font-weight:bold;">'+title+'<br><span style="font-size:0.7rem;color:#666">'+unit+'</span></div>';
        h+='<div><i style="background:'+getColor(grades[grades.length-1],param)+'"></i>&gt;'+grades[grades.length-1]+'</div>';
        for(var i=grades.length-2;i>=0;i--)
            h+='<div><i style="background:'+getColor(grades[i],param)+'"></i>'+grades[i]+'-'+grades[i+1]+'</div>';
    }
    this._div.innerHTML=h;
};
legend.addTo(map);

// ── Panel lateral de detalle (fijo, no desaparece) ────────
var panelVisible = false;
var panelSid = null;

function mostrarPanel(sid, html) {
    var panel = document.getElementById('detail-panel');
    var content = document.getElementById('detail-content');
    content.innerHTML = html;
    panel.style.display = 'flex';
    panelVisible = true;
    panelSid = sid;
    // Centrar mapa en la estación
    var r = riesgoData[sid];
    if (r && r.lat && r.lon) {
        map.setView([r.lat, r.lon], map.getZoom() < 12 ? 12 : map.getZoom());
    }
}
function cerrarPanel() {
    document.getElementById('detail-panel').style.display = 'none';
    panelVisible = false;
    panelSid = null;
}

// ── Formato hora ──────────────────────────────────────────
function fmtTime(iso){
    var d=new Date(iso),n=new Date();
    var esHoy=d.getDate()===n.getDate()&&d.getMonth()===n.getMonth();
    return (esHoy?'Hoy':'Ayer')+', '+d.toLocaleTimeString('es-ES',{hour:'2-digit',minute:'2-digit'});
}
function wdirLabel(d){
    if(d==null) return '—';
    return ['N','NNE','NE','ENE','E','ESE','SE','SSE','S','SSO','SO','OSO','O','ONO','NO','NNO'][Math.round(d/22.5)%16];
}

// ── Actualizar mapa ───────────────────────────────────────
function actualizarMapa(){
    var param  = document.getElementById('param-select').value;
    var isRisk = param==='oidio'||param==='mildiu';
    legend.update(param);
    heatLG.clearLayers();
    markersLG.clearLayers();
    heatLayer = null;

    var snapshot = isRisk ? historyData[historyData.length-1] : historyData[currentIndex];
    if(!snapshot) return;
    var stations = snapshot.stations || [];
    var features = [];

    stations.forEach(function(est){
        if(!est||est.lat==null||est.lon==null) return;
        var val = getRaw(est,param);
        if(val==null) return;

        var bgColor = getColor(val,param);
        var label;
        if(isRisk){
            if(val<0) label='?';
            else label=['0','B','M','A'][Math.min(3,Math.max(0,Math.round(val)))];
        } else if(param==='precip'){
            label=val.toFixed(1);
        } else if(param==='temp'){
            label=Math.round(val)+'°';
        } else {
            label=Math.round(val)+'';
        }

        var windSvg='';
        if(param==='wind'&&est.winddir!=null){
            windSvg='<svg style="position:absolute;top:-13px;left:-13px;width:50px;height:50px;transform:rotate('+est.winddir+'deg);z-index:-1;pointer-events:none;" viewBox="0 0 50 50"><line x1="25" y1="2" x2="25" y2="13" stroke="black" stroke-width="2.5"/></svg>';
        }
        var iconHtml='<div style="position:relative;">'
            +'<div style="background:'+bgColor+';color:white;text-shadow:1px 1px 2px rgba(0,0,0,0.8);'
            +'border:1.5px solid white;border-radius:50%;width:26px;height:26px;display:flex;'
            +'justify-content:center;align-items:center;font-weight:bold;font-size:10px;'
            +'box-shadow:0 2px 5px rgba(0,0,0,0.4);cursor:pointer;">'+label+'</div>'
            +windSvg+'</div>';

        var marker = L.marker([est.lat,est.lon],{
            icon:L.divIcon({className:'',html:iconHtml,iconSize:[26,26],iconAnchor:[13,13]})
        });

        var nombre = NOMBRES[est.stationID]||(est.neighborhood&&est.neighborhood.trim()!==''?est.neighborhood:est.stationID);

        // ── Contenido del panel lateral (fijo) ───────────────
        var panelHtml;
        if(isRisk){
            var r=riesgoData[est.stationID];
            if(r){
                var nivO=r.oidio, nivM=r.mildiu;
                var det=r.detalles||{};
                var dO=(det.oidio||[]).join('<br>&bull; ');
                var dM=(det.mildiu||[]).join('<br>&bull; ');
                var alertaHtml='';
                if(!r.datos_ok){
                    alertaHtml='<div style="background:#fff3cd;border:1px solid #ffc107;border-radius:6px;padding:8px 10px;margin-bottom:10px;font-size:12px;">'
                        +'⚠️ <b>Datos insuficientes</b> ('+r.dias_disponibles+' días disponibles, mínimo '+5+')<br>'
                        +'<span style="color:#666;">El cálculo de riesgo requiere más historial. '
                        +'Ejecuta el script diariamente para acumular datos.</span></div>';
                }
                var fuenteHtml='<div style="font-size:11px;color:#888;margin-top:8px;">📊 Fuente: '+r.fuente_datos+' ('+r.dias_disponibles+' días)</div>';
                panelHtml=alertaHtml
                    +'<b>🍇 Oídio:</b> <span style="display:inline-block;padding:2px 9px;border-radius:10px;font-size:12px;font-weight:bold;color:white;background:'+(nivO<0?'#aaa':RIESGO_COLORS[nivO])+'">'+(nivO<0?'Sin datos':RIESGO_LABELS[nivO])+'</span>'
                    +'<div style="font-size:12px;color:#666;margin:4px 0 10px 0;">&bull; '+(dO||'—')+'</div>'
                    +'<b>🍃 Mildiu:</b> <span style="display:inline-block;padding:2px 9px;border-radius:10px;font-size:12px;font-weight:bold;color:white;background:'+(nivM<0?'#aaa':RIESGO_COLORS[nivM])+'">'+(nivM<0?'Sin datos':RIESGO_LABELS[nivM])+'</span>'
                    +'<div style="font-size:12px;color:#666;margin:4px 0 10px 0;">&bull; '+(dM||'—')+'</div>'
                    +'<hr style="border:0;border-top:1px solid #eee;margin:8px 0;">'
                    +'<div style="font-size:12px;color:#555;">'
                    +'🌡 T='+( det.temp_actual!=null?det.temp_actual.toFixed(1)+'°C':'—')+' &nbsp;'
                    +'💧 HR='+(det.hum_actual!=null?det.hum_actual+'%':'—')+'<br>'
                    +'🌧 Lluvia 10d='+(det.precip_10dias||0)+'mm &nbsp;'
                    +'⏱ HR alta='+(det.horas_hum_alta_7d||0)+'h (7d)</div>'
                    +fuenteHtml;
            } else {
                panelHtml='<div style="color:#999;font-size:13px;">Sin datos de riesgo.<br>Ejecuta el script durante varios días para acumular historial agrícola.</div>';
            }
        } else {
            var m=est.metric||{};
            var t=m.temp!=null?m.temp.toFixed(1)+'°C':'—';
            var p=m.precipTotal!=null?m.precipTotal.toFixed(1)+' mm':'—';
            var w=m.windSpeed!=null?m.windSpeed.toFixed(0)+' km/h':'—';
            var wg=m.windGust!=null?m.windGust.toFixed(0)+' km/h':'—';
            var wd=wdirLabel(est.winddir);
            var h=est.humidity!=null?est.humidity+'%':'—';
            var obs=est.obsTimeLocal?est.obsTimeLocal.slice(11,16):'—';
            panelHtml='<table style="width:100%;border-collapse:collapse;font-size:13px;">'
                +'<tr><td style="color:#888;padding:4px 2px;">🌡 Temperatura</td><td style="font-weight:bold;padding:4px 2px;">'+t+'</td></tr>'
                +'<tr><td style="color:#888;padding:4px 2px;">🌧 Precipitación</td><td style="font-weight:bold;padding:4px 2px;">'+p+'</td></tr>'
                +'<tr><td style="color:#888;padding:4px 2px;">💨 Viento</td><td style="font-weight:bold;padding:4px 2px;">'+w+' '+wd+'</td></tr>'
                +'<tr><td style="color:#888;padding:4px 2px;">⬆ Racha máx.</td><td style="font-weight:bold;padding:4px 2px;">'+wg+'</td></tr>'
                +'<tr><td style="color:#888;padding:4px 2px;">💧 Humedad</td><td style="font-weight:bold;padding:4px 2px;">'+h+'</td></tr>'
                +'<tr><td style="color:#888;padding:4px 2px;">🕒 Observación</td><td style="padding:4px 2px;">'+obs+'</td></tr>'
                +'</table>'
                +'<a href="https://www.wunderground.com/dashboard/pws/'+est.stationID+'" target="_blank"'
                +' style="display:inline-block;margin-top:10px;padding:6px 14px;background:#3498db;color:white;'
                +'text-decoration:none;border-radius:6px;font-size:12px;">Ver historial en WU ↗</a>';
        }

        var panelFull = '<div style="font-size:15px;font-weight:bold;color:#2c3e50;margin-bottom:10px;">'+nombre+'</div>'
            +'<div style="font-size:11px;color:#aaa;margin-bottom:10px;">'
            +est.stationID+' &nbsp;·&nbsp; '+est.lat.toFixed(4)+'°N '+Math.abs(est.lon).toFixed(4)+'°W</div>'
            + panelHtml;

        // Al hacer clic en el marcador → panel lateral fijo
        (function(stId, html){
            marker.on('click', function(){ mostrarPanel(stId, html); });
        })(est.stationID, panelFull);

        marker.bindTooltip('<b>'+nombre+'</b>',{direction:'top',offset:[0,-16],opacity:0.9});
        markersLG.addLayer(marker);

        if(!isRisk){
            features.push(turf.point([est.lon,est.lat],{value:val}));
        }
    });

    // Heatmap interpolado
    if(!isRisk && features.length>2){
        try{
            var col=turf.featureCollection(features);
            var grid=turf.interpolate(col,2.5,{gridType:'square',property:'value',units:'kilometers',weight:param==='temp'?2:4});
            var clean=turf.featureCollection(grid.features.filter(function(f){return f.properties.value!=null&&!isNaN(f.properties.value);}));
            heatLayer=L.geoJSON(clean,{pane:'heatPane',style:function(f){return {fillColor:getColor(f.properties.value,param),fillOpacity:window.heatOpacity,stroke:false};}});
            heatLG.addLayer(heatLayer);
        } catch(e){console.error('Heatmap:',e);}
    }
}

// ── Slider máquina del tiempo ─────────────────────────────
var slider    = document.getElementById('time-slider');
var timeLabel = document.getElementById('time-label');

function initSlider(){
    var n=historyData.length;
    if(n===0){timeLabel.innerText='Sin datos';return;}
    slider.min=0; slider.max=n-1; slider.value=n-1;
    currentIndex=n-1;
    timeLabel.innerText=fmtTime(historyData[n-1].timestamp)+' (Actual)';
    actualizarMapa();
}
slider.addEventListener('input',function(){
    currentIndex=parseInt(this.value);
    var isLatest=currentIndex===historyData.length-1;
    timeLabel.innerText=fmtTime(historyData[currentIndex].timestamp)+(isLatest?' (Actual)':' (Histórico)');
    actualizarMapa();
    // Actualizar panel si está abierto
    if(panelVisible && panelSid) markersLG.eachLayer(function(m){
        if(m._panelSid===panelSid) m.fire('click');
    });
});

var playTimer=null;
document.getElementById('play-btn').addEventListener('click',function(){
    if(playTimer){clearInterval(playTimer);playTimer=null;this.textContent='▶️';this.title='Reproducir';}
    else{
        this.textContent='⏸️';this.title='Pausar';
        if(currentIndex>=historyData.length-1) currentIndex=0;
        var self=this;
        playTimer=setInterval(function(){
            currentIndex=(currentIndex+1)%historyData.length;
            slider.value=currentIndex;
            slider.dispatchEvent(new Event('input'));
            if(currentIndex===historyData.length-1){
                clearInterval(playTimer);playTimer=null;self.textContent='▶️';
            }
        },1500);
    }
});

document.getElementById('opacity-slider').addEventListener('input',function(){
    window.heatOpacity=parseFloat(this.value);
    if(heatLayer) heatLayer.setStyle({fillOpacity:window.heatOpacity});
});

initSlider();
"""
    )

    html = (
"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Meteo Guadalentín</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/@turf/turf@6/turf.min.js"></script>
  <style>
    *{box-sizing:border-box}
    body{font-family:'Segoe UI',sans-serif;margin:0;padding:0;background:#f5f7fa;display:flex;flex-direction:column;height:100vh}
    header{background:#1a252f;color:white;padding:0.6rem 1rem;display:flex;justify-content:space-between;align-items:center;z-index:10;box-shadow:0 3px 8px rgba(0,0,0,0.25);flex-wrap:wrap;gap:8px;flex-shrink:0}
    .header-left h1{margin:0;font-size:1.15rem;font-weight:600}
    .subtitle{font-size:0.72rem;color:#bdc3c7;margin-top:2px}
    .controls{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
    .controls select{padding:5px 9px;border-radius:6px;border:none;background:#ecf0f1;color:#2c3e50;font-weight:bold;font-size:0.82rem;cursor:pointer}
    .main-area{display:flex;flex:1;overflow:hidden}
    #map{flex:1;height:100%}
    /* Panel lateral fijo */
    #detail-panel{display:none;flex-direction:column;width:280px;min-width:240px;background:#fff;border-left:1px solid #e0e0e0;overflow-y:auto;flex-shrink:0}
    #detail-header{background:#1a252f;color:white;padding:8px 12px;display:flex;justify-content:space-between;align-items:center;flex-shrink:0}
    #detail-header span{font-size:13px;font-weight:600}
    #close-panel{background:none;border:none;color:white;font-size:18px;cursor:pointer;line-height:1;padding:0 4px}
    #detail-content{padding:14px;font-size:13px;flex:1}
    .legend{background:rgba(255,255,255,0.95);padding:7px 10px;border-radius:8px;box-shadow:0 2px 10px rgba(0,0,0,0.2);font-size:0.75rem;line-height:1.6;color:#333;max-height:55vh;overflow-y:auto;max-width:145px}
    .legend i{width:14px;height:12px;float:left;margin-right:6px;opacity:0.85;border:1px solid rgba(0,0,0,0.1)}
    .grayscale-map{filter:grayscale(100%) contrast(1.1) brightness(1.05)}
    @media(max-width:600px){
      header{flex-direction:column;align-items:flex-start}
      .controls{width:100%}
      .controls select{width:100%}
      #detail-panel{width:100%;min-width:unset;max-height:40vh}
      .main-area{flex-direction:column}
    }
  </style>
</head>
<body>
<header>
  <div class="header-left">
    <h1>🌿 Meteo Guadalentín</h1>
    <div class="subtitle">Actualizado: <span id="time-label">""" + fecha_actualizada + """</span></div>
  </div>
  <div class="controls">
    <div style="display:flex;flex-direction:column;align-items:center;gap:2px;">
      <span style="font-size:0.68rem;color:#ecf0f1;font-weight:bold;">⏱ Máquina del Tiempo</span>
      <div style="display:flex;align-items:center;gap:4px;">
        <button id="play-btn" title="Reproducir" style="background:transparent;color:white;border:none;cursor:pointer;font-size:1rem;padding:0 3px;">▶️</button>
        <input type="range" id="time-slider" min="0" max="0" value="0" style="width:120px;cursor:pointer;">
      </div>
    </div>
    <div style="display:flex;flex-direction:column;align-items:center;gap:2px;">
      <span style="font-size:0.68rem;color:#ecf0f1;font-weight:bold;">🔆 Opacidad</span>
      <input type="range" id="opacity-slider" min="0" max="1" step="0.05" value="0.35" style="width:75px;cursor:pointer;">
    </div>
    <select id="param-select" onchange="actualizarMapa()">
      <option value="temp" selected>🌡 Temperatura (°C)</option>
      <option value="precip">🌧 Precipitación (mm)</option>
      <option value="humidity">💧 Humedad (%)</option>
      <option value="wind">💨 Viento (km/h)</option>
      <option value="oidio">🍇 Riesgo Oídio</option>
      <option value="mildiu">🍃 Riesgo Mildiu</option>
    </select>
  </div>
</header>
<div class="main-area">
  <div id="map"></div>
  <div id="detail-panel">
    <div id="detail-header">
      <span>Detalle de estación</span>
      <button id="close-panel" onclick="cerrarPanel()" title="Cerrar">✕</button>
    </div>
    <div id="detail-content">
      <p style="color:#aaa;font-size:13px;">Haz clic en cualquier estación del mapa para ver sus datos aquí.</p>
    </div>
  </div>
</div>
<script>
""" + js + """
</script>
</body>
</html>"""
    )

    os.makedirs(DIR_PUBLICO, exist_ok=True)
    ruta = os.path.join(DIR_PUBLICO, 'index.html')
    with open(ruta, 'w', encoding='utf-8') as f:
        f.write(html)
    return ruta

# ─────────────────────────────────────────────────────────────
# PRINCIPAL
# ─────────────────────────────────────────────────────────────
def principal():
    try:
        from zoneinfo import ZoneInfo
        ahora = datetime.now(ZoneInfo("Europe/Madrid"))
    except ImportError:
        ahora = datetime.now()

    print(f"\n🚀 Obteniendo datos WU de {len(ESTACIONES_WU)} estaciones...")
    datos_wu = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=25) as executor:
        for datos in executor.map(obtener_wu, ESTACIONES_WU):
            if datos:
                datos_wu.append(datos)
    print(f"  ✅ {len(datos_wu)}/{len(ESTACIONES_WU)} estaciones WU con datos.")

    if not datos_wu:
        print("  ❌ Sin datos WU. Comprueba la conexión.")
        return

    print("\n📡 Obteniendo datos históricos AEMET (últimos 14 días)...")
    aemet_diarios = obtener_aemet_diarios(dias=14)
    if not aemet_diarios:
        print("  ⚠ Sin datos AEMET. El riesgo se calculará solo con historial WU propio.")

    print("\n📚 Actualizando historial 24h...")
    historial = gestionar_historial(datos_wu, ahora)

    print("\n🌾 Actualizando historial agrícola 14 días...")
    historial_agri = gestionar_historial_agricola(datos_wu, ahora)

    print("\n🔬 Calculando riesgo Oídio/Mildiu...")
    riesgo = calcular_riesgo(historial_agri, aemet_diarios, datos_wu)

    niveles = ['Sin riesgo','Bajo','Medio','ALTO']
    advertencias = []
    for sid, r in riesgo.items():
        dias = r['dias_disponibles']
        ok   = r['datos_ok']
        oidio_txt  = niveles[r['oidio']]  if r['oidio']  >= 0 else '⚠ Insuficiente'
        mildiu_txt = niveles[r['mildiu']] if r['mildiu'] >= 0 else '⚠ Insuficiente'
        print(f"  {sid}: Oídio={oidio_txt} | Mildiu={mildiu_txt} | Días={dias} | Fuente={r['fuente_datos']}")
        if not ok:
            advertencias.append(sid)

    if advertencias:
        print(f"\n  ⚠ AVISO: {len(advertencias)} estaciones con datos insuficientes para cálculo fiable:")
        for sid in advertencias:
            print(f"    - {sid}: {riesgo[sid]['dias_disponibles']} días disponibles (mínimo {MIN_DIAS_RIESGO})")
        print("  → Ejecuta el script diariamente para acumular historial.")

    print("\n🗺  Generando HTML...")
    ruta_html = generar_html(historial, riesgo, ahora)
    print(f"✅ Listo → {ruta_html}")
    webbrowser.open('file://' + ruta_html)

if __name__ == "__main__":
    principal()
