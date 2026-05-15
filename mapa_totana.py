import urllib.request, json, ssl, os, webbrowser, concurrent.futures
from datetime import datetime, timedelta

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

WU_KEY    = "6532d6454b8aa370768e63d6ba5a832e"
AEMET_KEY = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJqb3Nlcm9xdWVAbG9wZXp5YW5kcmVvLmNvbSIsImp0aSI6ImM5OWQwMjdhLWFkOTgtNDI1Yi04ZGRiLTY3ZGNjNzdjMzRkYyIsImlzcyI6IkFFTUVUIiwiaWF0IjoxNzc4NDQ2MTgxLCJ1c2VySWQiOiJjOTlkMDI3YS1hZDk4LTQyNWItOGRkYi02N2RjYzc3YzM0ZGMiLCJyb2xlIjoiIn0.QAttE468tO9unX9oJMFIjEyhlDEr5IkBpdMOFR6-tyg"

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
DIR_DATOS = os.path.join(BASE_DIR, 'datos')
DIR_PUB   = os.path.join(BASE_DIR, 'public')
F_H24     = os.path.join(DIR_DATOS, 'history_24h.json')
F_AGRI    = os.path.join(DIR_DATOS, 'historial_agricola.json')
F_AEMET   = os.path.join(DIR_DATOS, 'historial_aemet.json')
os.makedirs(DIR_DATOS, exist_ok=True)
os.makedirs(DIR_PUB,   exist_ok=True)
MIN_DIAS = 5

AEMET_EST = [
    ("7228",  "Totana",           37.769, -1.504),
    ("7228B", "Lorca",            37.679, -1.701),
    ("7213",  "Alhama de Murcia", 37.852, -1.425),
    ("7031",  "Mazarrón",         37.631, -1.316),
    ("7209",  "Lorca/Zarzilla",   37.901, -1.810),
]

F_EST = os.path.join(BASE_DIR, 'estaciones.txt')
if not os.path.exists(F_EST):
    with open(F_EST,'w',encoding='utf-8') as f:
        for e in ["ITOTAN8","ITOTAN2","ITOTAN16","ITOTAN5","ITOTAN33","ITOTAN43",
                  "ITOTAN31","ITOTAN42","ITOTAN9","ITOTAN41","ITOTAN10","ITOTAN17"]:
            f.write(e+"\n")
ESTACIONES = [l.split('#')[0].strip() for l in open(F_EST,'r',encoding='utf-8') if l.split('#')[0].strip()]

def leer(ruta, default):
    if os.path.exists(ruta):
        try:
            return json.load(open(ruta,'r',encoding='utf-8'))
        except: pass
    return default

def guardar(ruta, data):
    with open(ruta,'w',encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ── WU ──────────────────────────────────────────────────────
def wu(sid):
    url = f"https://api.weather.com/v2/pws/observations/current?stationId={sid}&format=json&units=m&numericPrecision=decimal&apiKey={WU_KEY}"
    try:
        req = urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0','Referer':'https://www.wunderground.com/'})
        with urllib.request.urlopen(req, context=ctx, timeout=6) as r:
            obs = json.loads(r.read().decode('utf-8')).get('observations',[])
            return obs[0] if obs else None
    except Exception as e:
        print(f"  ⚠ WU {sid}: {e}")
    return None

# ── AEMET ────────────────────────────────────────────────────
def aemet_diarios(dias=14):
    cache = leer(F_AEMET, {})
    ahora = datetime.now()
    dias_nec = [(ahora-timedelta(days=i)).strftime('%Y-%m-%d') for i in range(1,dias+1)]
    dias_cache = set(d for v in cache.values() for d in v.keys())
    faltantes  = [d for d in dias_nec if d not in dias_cache]

    if not faltantes:
        print(f"  ✅ AEMET: caché local ({len(dias_cache)} días)")
        return {k:[dict(fecha=f,**v) for f,v in sorted(vv.items())] for k,vv in cache.items()}

    fi = min(faltantes)+'T00:00:00UTC'
    ff = max(faltantes)+'T23:59:59UTC'
    print(f"  📡 AEMET: descargando {fi[:10]} → {ff[:10]}...")

    def pf(v):
        if v is None: return None
        try: return float(str(v).replace(',','.'))
        except: return None

    for idema, nombre, lat, lon in AEMET_EST:
        path = f"/api/valores/climatologicos/diarios/datos/fechaini/{fi}/fechafin/{ff}/estacion/{idema}"
        try:
            req = urllib.request.Request("https://opendata.aemet.es/opendata/api"+path, headers={'api_key':AEMET_KEY})
            with urllib.request.urlopen(req, context=ctx, timeout=10) as r:
                meta = json.loads(r.read().decode('utf-8'))
            if meta.get('estado') != 200: raise Exception(meta.get('descripcion',''))
            with urllib.request.urlopen(urllib.request.Request(meta['datos']), context=ctx, timeout=10) as r2:
                datos = json.loads(r2.read().decode('ISO-8859-15'))
            if idema not in cache: cache[idema] = {}
            for d in datos:
                cache[idema][d.get('fecha','')] = {'tmax':pf(d.get('tmax')),'tmin':pf(d.get('tmin')),'prec':pf(d.get('prec')),'hrmax':pf(d.get('hrmax')),'lat':lat,'lon':lon,'nombre':nombre}
            lim = (ahora-timedelta(days=30)).strftime('%Y-%m-%d')
            cache[idema] = {k:v for k,v in cache[idema].items() if k>=lim}
            print(f"    ✅ {idema} ({nombre}): {len(datos)} días")
        except Exception as e:
            print(f"    ⚠ AEMET {idema}: {e}")

    guardar(F_AEMET, cache)
    return {k:[dict(fecha=f,**v) for f,v in sorted(vv.items())] for k,vv in cache.items()}

# ── Historial 24h local ──────────────────────────────────────
def hist24(nuevos, ahora):
    h = leer(F_H24, [])
    lim = ahora - timedelta(hours=24)
    limpio = []
    for e in h:
        try:
            t = datetime.fromisoformat(e['timestamp'])
            if t.tzinfo is None: t = t.replace(tzinfo=ahora.tzinfo)
            if t > lim: limpio.append(e)
        except: pass
    limpio.append({'timestamp':ahora.isoformat(),'stations':nuevos})
    guardar(F_H24, limpio)
    print(f"  ✅ Historial 24h: {len(limpio)} registros locales.")
    return limpio

# ── Historial agrícola local ─────────────────────────────────
def hist_agri(nuevos, ahora):
    h = leer(F_AGRI, {})
    hoy = ahora.strftime('%Y-%m-%d')
    if hoy not in h: h[hoy] = {}
    for est in nuevos:
        if not est or 'stationID' not in est: continue
        sid = est['stationID']
        t   = est.get('metric',{}).get('temp')
        p   = est.get('metric',{}).get('precipTotal')
        hm  = est.get('humidity')
        if sid not in h[hoy]:
            h[hoy][sid] = {'tempMax':t if t is not None else -99,'tempMin':t if t is not None else 99,'precipTotal':p if p is not None else 0,'humedadAltaMinutos':0}
        else:
            d = h[hoy][sid]
            if t is not None:
                if t > d.get('tempMax',-99): d['tempMax']=t
                if t < d.get('tempMin', 99): d['tempMin']=t
            if p is not None and p > d.get('precipTotal',0): d['precipTotal']=p
        if hm is not None and hm >= 85:
            h[hoy][sid]['humedadAltaMinutos'] = h[hoy][sid].get('humedadAltaMinutos',0)+15
    for d in sorted(h.keys())[:-14]: del h[d]
    guardar(F_AGRI, h)
    print(f"  ✅ Historial agrícola: {len(h)} días locales.")
    return h

# ── Riesgo ───────────────────────────────────────────────────
def riesgo(hwu, hae, actuales_list):
    act  = {e['stationID']:e for e in actuales_list if e and 'stationID' in e}
    dias = sorted(hwu.keys())
    res  = {}
    for sid, est in act.items():
        ta = est.get('metric',{}).get('temp')
        ha = est.get('humidity')
        la = est.get('lat',0)
        lo = est.get('lon',0)
        if ta is None: continue

        filas = []
        for f in (dias[-14:] if len(dias)>=14 else dias):
            dd = hwu[f].get(sid)
            if dd: filas.append({'fecha':f,'tmax':dd.get('tempMax'),'tmin':dd.get('tempMin'),'prec':dd.get('precipTotal',0),'hum_min':dd.get('humedadAltaMinutos',0),'src':'WU'})

        ae_src = None
        if len(filas) < MIN_DIAS and hae:
            best_d, best_id = 999, None
            for idema,(_,_,alat,alon) in zip([e[0] for e in AEMET_EST], AEMET_EST):
                d2 = ((la-alat)**2+(lo-alon)**2)**0.5
                if d2 < best_d and idema in hae: best_d,best_id = d2,idema
            if best_id:
                ae_src = best_id
                fe_set = {f['fecha'] for f in filas}
                for da in hae[best_id]:
                    if da['fecha'] not in fe_set:
                        filas.append({'fecha':da['fecha'],'tmax':da.get('tmax'),'tmin':da.get('tmin'),'prec':da.get('prec') or 0,'hum_min':240 if (da.get('hrmax') or 0)>=85 else 0,'src':f"AE:{best_id}"})
                filas.sort(key=lambda x:x['fecha'])
                filas = filas[-14:]

        nd = len(filas)
        nae = sum(1 for f in filas if f['src'].startswith('AE'))
        if ae_src and nae:
            nb = next((e[1] for e in AEMET_EST if e[0]==ae_src), ae_src)
            flbl = f"WU({nd-nae}d)+AEMET {nb}({nae}d)"
        else:
            flbl = f"WU propio ({nd}d)"

        ok = nd >= MIN_DIAS
        p10   = sum(f['prec'] or 0 for f in filas[-10:])
        tminm = min((f['tmin'] for f in filas if f['tmin'] is not None), default=99)
        dt15  = sum(1 for f in filas if f['tmax'] is not None and f['tmin'] is not None and (f['tmax']+f['tmin'])/2>=15)
        h85   = sum(f.get('hum_min',0) for f in filas[-7:])/60.0

        # Oídio
        no, do = 0, []
        if not ok:
            no=-1; do.append(f"⚠ {nd} días disponibles (mínimo {MIN_DIAS})")
        else:
            if ta>=15 and dt15>=5:
                do.append(f"{dt15} días Tmed≥15°C")
                if 15<=ta<19:   no=1; do.append(f"T={ta:.1f}°C — rango bajo")
                elif 19<=ta<=26: no=3 if h85>=4 else 2; do.append(f"T={ta:.1f}°C — rango óptimo"); (do.append(f"{h85:.1f}h HR≥85% (7d)") if h85>=4 else None)
                else:            no=3 if (ha or 0)>=70 else 2; do.append(f"T={ta:.1f}°C + HR={ha}%")
            elif ta>=18: no=1; do.append(f"Solo {dt15} días cálidos acumulados")
            else: do.append(f"T={ta:.1f}°C — por debajo umbral")

        # Mildiu
        nm, dm = 0, []
        if not ok:
            nm=-1; dm.append(f"⚠ {nd} días disponibles (mínimo {MIN_DIAS})")
        else:
            ct=tminm>10 or ta>10; cl=p10>=10; cd=nd>=7
            if ct: dm.append("Tmin>10°C ✓")
            if cl: dm.append(f"Lluvia 10d={p10:.1f}mm ✓")
            if cd: dm.append(f"{nd} días historial ✓")
            nc=sum([ct,cl,cd])
            if nc==3:
                nm=3 if (18<=ta<=24 and (ha or 0)>=85) else 2
                if ta>30: nm=max(0,nm-1); dm.append("T>30°C inhibe esporulación")
            elif nc==2: nm=1
            if not cl: dm.append(f"Lluvia 10d={p10:.1f}mm (necesita ≥10mm)")
            if not cd: dm.append(f"Acumulando historial ({nd}/{MIN_DIAS} días)")

        res[sid] = {'lat':la,'lon':lo,'oidio':no,'mildiu':nm,'datos_ok':ok,'dias_disponibles':nd,'fuente_datos':flbl,
                    'detalles':{'oidio':do,'mildiu':dm,'temp_actual':ta,'hum_actual':ha,'precip_10dias':round(p10,1),'dias_tmed_sobre15':dt15,'horas_hum_alta_7d':round(h85,1)}}
    return res

# ── HTML ─────────────────────────────────────────────────────
def generar_html(historial, riesgo_data, ahora):
    fa = ahora.strftime("%d/%m/%Y %H:%M:%S")
    NOMBRES = {"ITOTAN8":"Mirador - Lebor Alto","ITOTAN2":"METEO UNDERWORLD","ITOTAN16":"Mortí Bajo - Camino Aleurrosas","ITOTAN5":"Estación Tierno Galván","ITOTAN33":"Huerto Hostench","ITOTAN43":"Casa Totana","ITOTAN31":"CAMPING Lebor","ITOTAN42":"Secanos","ITOTAN9":"LA CANAL - Raiguero","ITOTAN41":"Ecowitt WN1981","ITOTAN10":"WS Rancho","ITOTAN17":"La Barquilla","IALHAM13":"Alhama Norte","IALHAM81":"Alhama Centro","ILORCA22":"Lorca Sur","IMAZAR7":"Puerto Mazarrón"}

    js = ("var NOMBRES="+json.dumps(NOMBRES,ensure_ascii=False)+";\n"
         +"var historyData="+json.dumps(historial,ensure_ascii=False)+";\n"
         +"var riesgoData="+json.dumps(riesgo_data,ensure_ascii=False)+";\n"
         +open(os.path.join(BASE_DIR,'_map_logic.js'),'r',encoding='utf-8').read()
          if os.path.exists(os.path.join(BASE_DIR,'_map_logic.js')) else
          "var NOMBRES="+json.dumps(NOMBRES,ensure_ascii=False)+";\n"
         +"var historyData="+json.dumps(historial,ensure_ascii=False)+";\n"
         +"var riesgoData="+json.dumps(riesgo_data,ensure_ascii=False)+";\n"
         +MAP_LOGIC_JS)

    html = HTML_TEMPLATE.replace('__FECHA__', fa).replace('__JS__', js)
    ruta = os.path.join(DIR_PUB, 'index.html')
    with open(ruta,'w',encoding='utf-8') as f: f.write(html)
    return ruta

MAP_LOGIC_JS = r"""
var RIESGO_COLORS=['#27ae60','#f39c12','#e67e22','#c0392b'];
var RIESGO_LABELS=['Sin riesgo','Riesgo bajo','Riesgo medio','Riesgo ALTO'];
var currentIndex=historyData.length-1;
window.heatOpacity=0.35;

var terreno=L.tileLayer('http://{s}.google.com/vt/lyrs=p&x={x}&y={y}&z={z}',{maxZoom:20,subdomains:['mt0','mt1','mt2','mt3'],attribution:'© Google',className:'grayscale-map'});
var mapaClaro=L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',{attribution:'© CARTO'});
var estandar=L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'© OSM'});
var googleSat=L.tileLayer('http://{s}.google.com/vt/lyrs=s,h&x={x}&y={y}&z={z}',{maxZoom:20,subdomains:['mt0','mt1','mt2','mt3'],attribution:'© Google'});

var map=L.map('map',{center:[37.76,-1.53],zoom:10,layers:[terreno]});
map.createPane('heatPane');map.getPane('heatPane').style.zIndex=390;map.getPane('heatPane').style.filter='blur(14px)';

var radarLG=L.layerGroup();
fetch('https://api.rainviewer.com/public/weather-maps.json').then(function(r){return r.json();}).then(function(d){var last=d.radar.past[d.radar.past.length-1];radarLG.addLayer(L.tileLayer(d.host+last.path+'/256/{z}/{x}/{y}/2/1_1.png',{opacity:0.7,zIndex:400,attribution:'RainViewer',maxNativeZoom:7,maxZoom:18}));}).catch(function(){});

var markersLG=L.layerGroup(),heatLG=L.layerGroup(),heatLayer=null;
L.control.layers({'Relieve':terreno,'Mapa Claro':mapaClaro,'Satélite':googleSat,'Estándar':estandar},{'Radar Lluvia':radarLG,'Mapa Calor':heatLG,'Etiquetas':markersLG},{position:'topright',collapsed:true}).addTo(map);
heatLG.addTo(map);markersLG.addTo(map);

(function(){var btn=L.control({position:'topleft'});btn.onAdd=function(){var d=L.DomUtil.create('div','leaflet-bar leaflet-control');d.innerHTML='<a href="#" style="font-size:18px;background:white;display:flex;justify-content:center;align-items:center;width:30px;height:30px;text-decoration:none;">🎯</a>';L.DomEvent.on(d,'click',function(e){L.DomEvent.preventDefault(e);map.locate({setView:true,maxZoom:13});});return d;};btn.addTo(map);})();
var userMk=null;map.on('locationfound',function(e){if(userMk)map.removeLayer(userMk);userMk=L.circleMarker(e.latlng,{radius:8,color:'#3498db',fillColor:'#3498db',fillOpacity:0.8}).addTo(map).bindPopup('Estás aquí').openPopup();});

function lerpC(c1,c2,t){return 'rgb('+Math.round(c1[0]+t*(c2[0]-c1[0]))+','+Math.round(c1[1]+t*(c2[1]-c1[1]))+','+Math.round(c1[2]+t*(c2[2]-c1[2]))+')'; }
function getColor(v,p){
  if(p==='oidio'||p==='mildiu'){if(v<0)return '#aaa';return RIESGO_COLORS[Math.min(3,Math.max(0,Math.round(v)))];}
  if(p==='temp'){var s=[{v:-5,c:[148,0,211]},{v:0,c:[0,0,200]},{v:5,c:[0,115,255]},{v:10,c:[0,200,200]},{v:15,c:[50,205,50]},{v:20,c:[255,255,0]},{v:25,c:[255,140,0]},{v:30,c:[220,20,60]},{v:35,c:[139,0,0]},{v:40,c:[200,0,200]}];if(v<=s[0].v)return 'rgb('+s[0].c+')';if(v>=s[s.length-1].v)return 'rgb('+s[s.length-1].c+')';for(var i=0;i<s.length-1;i++){if(v>=s[i].v&&v<=s[i+1].v)return lerpC(s[i].c,s[i+1].c,(v-s[i].v)/(s[i+1].v-s[i].v));}}
  if(p==='precip')return v>=70?'#ff0000':v>=50?'#ff99ff':v>=40?'#cc66ff':v>=30?'#993399':v>=20?'#660099':v>=10?'#0000ff':v>=4?'#3366ff':v>=2?'#00ccff':v>=0.5?'#99ffff':v>0?'#e6ffff':'transparent';
  if(p==='humidity')return v>=90?'#0d47a1':v>=70?'#1976d2':v>=50?'#42a5f5':'#90caf9';
  if(p==='wind')return v>=40?'#b71c1c':v>=30?'#e65100':v>=20?'#f57f17':v>=10?'#fbc02d':v>=5?'#81c784':'#b2dfdb';
  return '#aaa';
}
function getRaw(est,p){if(p==='oidio'||p==='mildiu'){var r=riesgoData[est.stationID];return r?r[p]:null;}var m=est.metric;if(!m)return null;if(p==='precip')return m.precipTotal;if(p==='temp')return m.temp;if(p==='humidity')return est.humidity;if(p==='wind')return m.windGust;return null;}
function wdirL(d){if(d==null)return '—';return['N','NNE','NE','ENE','E','ESE','SE','SSE','S','SSO','SO','OSO','O','ONO','NO','NNO'][Math.round(d/22.5)%16];}
function fmtT(iso){var d=new Date(iso),n=new Date();return(d.getDate()===n.getDate()&&d.getMonth()===n.getMonth()?'Hoy':'Ayer')+', '+d.toLocaleTimeString('es-ES',{hour:'2-digit',minute:'2-digit'});}

var legend=L.control({position:'bottomleft'});
legend.onAdd=function(){this._div=L.DomUtil.create('div','legend');return this._div;};
legend.update=function(p){
  var h='';
  if(p==='oidio'||p==='mildiu'){h='<div style="margin-bottom:5px;font-weight:bold;">'+(p==='oidio'?'🍇 Oídio':'🍃 Mildiu')+'</div><div><i style="background:#aaa"></i>Sin datos</div>';for(var i=3;i>=0;i--)h+='<div><i style="background:'+RIESGO_COLORS[i]+'"></i>'+RIESGO_LABELS[i]+'</div>';h+='<div style="margin-top:4px;font-size:0.65rem;color:#666;">'+(p==='oidio'?'Gubler-Thomas':'10-10-10+EPI')+'</div>';}
  else{var g,ti,u;if(p==='precip'){ti='🌧 Precipitación';u='mm';g=[0.5,2,4,10,20,30,40,50,70];}if(p==='temp'){ti='🌡 Temperatura';u='°C';g=[5,10,15,20,25,30,35,40];}if(p==='humidity'){ti='💧 Humedad';u='%';g=[30,50,70,90];}if(p==='wind'){ti='💨 Viento';u='km/h';g=[2,5,10,20,30,40];}h='<div style="margin-bottom:4px;font-weight:bold;">'+ti+'<br><span style="font-size:0.7rem;color:#666">'+u+'</span></div><div><i style="background:'+getColor(g[g.length-1],p)+'"></i>&gt;'+g[g.length-1]+'</div>';for(var i=g.length-2;i>=0;i--)h+='<div><i style="background:'+getColor(g[i],p)+'"></i>'+g[i]+'-'+g[i+1]+'</div>';}
  this._div.innerHTML=h;
};legend.addTo(map);

var panelSid=null;
function mostrarPanel(sid,html){document.getElementById('detail-content').innerHTML=html;document.getElementById('detail-panel').style.display='flex';panelSid=sid;}
function cerrarPanel(){document.getElementById('detail-panel').style.display='none';panelSid=null;}

function actualizarMapa(){
  var p=document.getElementById('param-select').value;
  var isR=p==='oidio'||p==='mildiu';
  legend.update(p);heatLG.clearLayers();markersLG.clearLayers();heatLayer=null;
  var snap=isR?historyData[historyData.length-1]:historyData[currentIndex];
  if(!snap)return;
  var feats=[];
  (snap.stations||[]).forEach(function(est){
    if(!est||est.lat==null||est.lon==null)return;
    var val=getRaw(est,p);if(val==null)return;
    var bg=getColor(val,p);
    var lbl=isR?(val<0?'?':['0','B','M','A'][Math.min(3,Math.max(0,Math.round(val)))]):(p==='precip'?val.toFixed(1):p==='temp'?Math.round(val)+'°':Math.round(val)+'');
    var ws='';if(p==='wind'&&est.winddir!=null)ws='<svg style="position:absolute;top:-13px;left:-13px;width:50px;height:50px;transform:rotate('+est.winddir+'deg);z-index:-1;pointer-events:none;" viewBox="0 0 50 50"><line x1="25" y1="2" x2="25" y2="13" stroke="black" stroke-width="2.5"/></svg>';
    var ih='<div style="position:relative;"><div style="background:'+bg+';color:white;text-shadow:1px 1px 2px rgba(0,0,0,0.8);border:1.5px solid white;border-radius:50%;width:26px;height:26px;display:flex;justify-content:center;align-items:center;font-weight:bold;font-size:10px;box-shadow:0 2px 5px rgba(0,0,0,0.4);cursor:pointer;">'+lbl+'</div>'+ws+'</div>';
    var mk=L.marker([est.lat,est.lon],{icon:L.divIcon({className:'',html:ih,iconSize:[26,26],iconAnchor:[13,13]})});
    var nm=NOMBRES[est.stationID]||(est.neighborhood&&est.neighborhood.trim()!==''?est.neighborhood:est.stationID);

    // Panel
    var ph;
    if(isR){
      var r=riesgoData[est.stationID];
      if(r){
        var nO=r.oidio,nM=r.mildiu,det=r.detalles||{};
        var dO=(det.oidio||[]).join('<br>&bull; '),dM=(det.mildiu||[]).join('<br>&bull; ');
        var av='';
        if(!r.datos_ok)av='<div style="background:#fff3cd;border:1px solid #ffc107;border-radius:6px;padding:8px 10px;margin-bottom:10px;font-size:12px;">⚠️ <b>Datos insuficientes</b><br><span style="color:#555;">'+r.dias_disponibles+' días disponibles de 5 necesarios.<br>Ejecuta el script diariamente para acumular historial.</span></div>';
        ph=av+'<div style="margin-bottom:8px;"><b>🍇 Oídio:</b> <span style="display:inline-block;padding:2px 9px;border-radius:10px;font-size:12px;font-weight:bold;color:white;background:'+(nO<0?'#aaa':RIESGO_COLORS[nO])+'">'+(nO<0?'Sin datos':RIESGO_LABELS[nO])+'</span></div><div style="font-size:12px;color:#555;margin-bottom:12px;">&bull; '+(dO||'—')+'</div>'
          +'<div style="margin-bottom:8px;"><b>🍃 Mildiu:</b> <span style="display:inline-block;padding:2px 9px;border-radius:10px;font-size:12px;font-weight:bold;color:white;background:'+(nM<0?'#aaa':RIESGO_COLORS[nM])+'">'+(nM<0?'Sin datos':RIESGO_LABELS[nM])+'</span></div><div style="font-size:12px;color:#555;margin-bottom:12px;">&bull; '+(dM||'—')+'</div>'
          +'<hr style="border:0;border-top:1px solid #eee;margin:8px 0;"><div style="font-size:12px;color:#666;">🌡 T='+(det.temp_actual!=null?det.temp_actual.toFixed(1)+'°C':'—')+' &nbsp;💧 HR='+(det.hum_actual!=null?det.hum_actual+'%':'—')+'<br>🌧 Lluvia 10d='+(det.precip_10dias||0)+'mm &nbsp;⏱ HR alta='+(det.horas_hum_alta_7d||0)+'h (7d)</div>'
          +'<div style="font-size:11px;color:#aaa;margin-top:8px;">📊 '+r.fuente_datos+'</div>';
      }else{ph='<div style="color:#999;font-size:13px;line-height:1.7;">Sin datos de riesgo.<br>Ejecuta el script diariamente.</div>';}
    }else{
      var m=est.metric||{};
      ph='<table style="width:100%;border-collapse:collapse;font-size:13px;line-height:2;">'
        +'<tr><td style="color:#888;">🌡 Temperatura</td><td style="font-weight:bold;">'+(m.temp!=null?m.temp.toFixed(1)+'°C':'—')+'</td></tr>'
        +'<tr><td style="color:#888;">🌧 Precipitación</td><td style="font-weight:bold;">'+(m.precipTotal!=null?m.precipTotal.toFixed(1)+' mm':'—')+'</td></tr>'
        +'<tr><td style="color:#888;">💨 Viento</td><td style="font-weight:bold;">'+(m.windSpeed!=null?m.windSpeed.toFixed(0)+' km/h':'—')+' '+wdirL(est.winddir)+'</td></tr>'
        +'<tr><td style="color:#888;">⬆ Racha</td><td style="font-weight:bold;">'+(m.windGust!=null?m.windGust.toFixed(0)+' km/h':'—')+'</td></tr>'
        +'<tr><td style="color:#888;">💧 Humedad</td><td style="font-weight:bold;">'+(est.humidity!=null?est.humidity+'%':'—')+'</td></tr>'
        +'<tr><td style="color:#888;">🕒 Última obs.</td><td>'+(est.obsTimeLocal?est.obsTimeLocal.slice(11,16):'—')+'</td></tr>'
        +'</table><a href="https://www.wunderground.com/dashboard/pws/'+est.stationID+'" target="_blank" style="display:inline-block;margin-top:12px;padding:7px 16px;background:#3498db;color:white;text-decoration:none;border-radius:6px;font-size:12px;">Ver historial WU ↗</a>';
    }
    var fh='<div style="font-size:15px;font-weight:bold;color:#2c3e50;margin-bottom:6px;">'+nm+'</div>'
      +'<div style="font-size:11px;color:#bbb;margin-bottom:12px;">'+est.stationID+(est.lat?' &nbsp;'+est.lat.toFixed(3)+'°N ':' ')+(est.lon?Math.abs(est.lon).toFixed(3)+'°W':'')+'</div>'+ph;
    (function(id,h){mk.on('click',function(){mostrarPanel(id,h);});})(est.stationID,fh);
    mk.bindTooltip('<b>'+nm+'</b>',{direction:'top',offset:[0,-16],opacity:0.9});
    markersLG.addLayer(mk);
    if(!isR)feats.push(turf.point([est.lon,est.lat],{value:val}));
  });

  if(!isR&&feats.length>2){try{var col=turf.featureCollection(feats);var grid=turf.interpolate(col,2.5,{gridType:'square',property:'value',units:'kilometers',weight:p==='temp'?2:4});var clean=turf.featureCollection(grid.features.filter(function(f){return f.properties.value!=null&&!isNaN(f.properties.value);}));heatLayer=L.geoJSON(clean,{pane:'heatPane',style:function(f){return{fillColor:getColor(f.properties.value,p),fillOpacity:window.heatOpacity,stroke:false};}});heatLG.addLayer(heatLayer);}catch(e){console.error('Heatmap:',e);}}
}

var slider=document.getElementById('time-slider');
var tlbl=document.getElementById('time-label');
function initSlider(){var n=historyData.length;if(n===0){tlbl.innerText='Sin datos';return;}slider.min=0;slider.max=n-1;slider.value=n-1;currentIndex=n-1;tlbl.innerText=fmtT(historyData[n-1].timestamp)+' (Actual)';actualizarMapa();}
slider.addEventListener('input',function(){currentIndex=parseInt(this.value);var last=currentIndex===historyData.length-1;tlbl.innerText=fmtT(historyData[currentIndex].timestamp)+(last?' (Actual)':' (Histórico)');actualizarMapa();});
var pt=null;
document.getElementById('play-btn').addEventListener('click',function(){if(pt){clearInterval(pt);pt=null;this.textContent='▶️';}else{this.textContent='⏸️';if(currentIndex>=historyData.length-1)currentIndex=0;var s=this;pt=setInterval(function(){currentIndex=(currentIndex+1)%historyData.length;slider.value=currentIndex;slider.dispatchEvent(new Event('input'));if(currentIndex===historyData.length-1){clearInterval(pt);pt=null;s.textContent='▶️';}},1500);}});
document.getElementById('opacity-slider').addEventListener('input',function(){window.heatOpacity=parseFloat(this.value);if(heatLayer)heatLayer.setStyle({fillOpacity:window.heatOpacity});});
initSlider();
"""

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang='es'>
<head>
  <meta charset='UTF-8'>
  <meta name='viewport' content='width=device-width, initial-scale=1.0'>
  <title>Meteo Guadalentín</title>
  <link rel='stylesheet' href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'/>
  <script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script>
  <script src='https://cdn.jsdelivr.net/npm/@turf/turf@6/turf.min.js'></script>
  <style>
    *{box-sizing:border-box}body{font-family:'Segoe UI',sans-serif;margin:0;padding:0;display:flex;flex-direction:column;height:100vh}
    header{background:#1a252f;color:white;padding:0.6rem 1rem;display:flex;justify-content:space-between;align-items:center;z-index:10;box-shadow:0 3px 8px rgba(0,0,0,0.25);flex-wrap:wrap;gap:8px;flex-shrink:0}
    .header-left h1{margin:0;font-size:1.1rem;font-weight:600}.subtitle{font-size:0.72rem;color:#bdc3c7;margin-top:2px}
    .controls{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
    .controls select{padding:5px 9px;border-radius:6px;border:none;background:#ecf0f1;color:#2c3e50;font-weight:bold;font-size:0.82rem;cursor:pointer}
    .main-area{display:flex;flex:1;overflow:hidden}
    #map{flex:1;height:100%}
    #detail-panel{display:none;flex-direction:column;width:285px;min-width:240px;background:#fff;border-left:1px solid #e0e0e0;overflow:hidden;flex-shrink:0}
    #detail-header{background:#1a252f;color:white;padding:9px 12px;display:flex;justify-content:space-between;align-items:center;flex-shrink:0}
    #detail-header span{font-size:13px;font-weight:600}
    #close-panel{background:none;border:none;color:white;font-size:18px;cursor:pointer;line-height:1;padding:0 4px}
    #detail-content{padding:14px;font-size:13px;overflow-y:auto;flex:1}
    .legend{background:rgba(255,255,255,0.95);padding:7px 10px;border-radius:8px;box-shadow:0 2px 10px rgba(0,0,0,0.2);font-size:0.75rem;line-height:1.6;color:#333;max-height:55vh;overflow-y:auto;max-width:145px}
    .legend i{width:14px;height:12px;float:left;margin-right:6px;opacity:0.85;border:1px solid rgba(0,0,0,0.1)}
    .grayscale-map{filter:grayscale(100%) contrast(1.1) brightness(1.05)}
    @media(max-width:600px){header{flex-direction:column;align-items:flex-start}.controls{width:100%}#detail-panel{width:100%;max-height:45vh}}
  </style>
</head>
<body>
<header>
  <div class='header-left'><h1>🌿 Meteo Guadalentín</h1><div class='subtitle'>Actualizado: <span id='time-label'>__FECHA__</span></div></div>
  <div class='controls'>
    <div style='display:flex;flex-direction:column;align-items:center;gap:2px;'>
      <span style='font-size:0.68rem;color:#ecf0f1;font-weight:bold;'>⏱ Máquina del Tiempo</span>
      <div style='display:flex;align-items:center;gap:4px;'>
        <button id='play-btn' style='background:transparent;color:white;border:none;cursor:pointer;font-size:1rem;padding:0 3px;'>▶️</button>
        <input type='range' id='time-slider' min='0' max='0' value='0' style='width:120px;cursor:pointer;'>
      </div>
    </div>
    <div style='display:flex;flex-direction:column;align-items:center;gap:2px;'>
      <span style='font-size:0.68rem;color:#ecf0f1;font-weight:bold;'>🔆 Opacidad</span>
      <input type='range' id='opacity-slider' min='0' max='1' step='0.05' value='0.35' style='width:75px;cursor:pointer;'>
    </div>
    <select id='param-select' onchange='actualizarMapa()'>
      <option value='temp' selected>🌡 Temperatura (°C)</option>
      <option value='precip'>🌧 Precipitación (mm)</option>
      <option value='humidity'>💧 Humedad (%)</option>
      <option value='wind'>💨 Viento (km/h)</option>
      <option value='oidio'>🍇 Riesgo Oídio</option>
      <option value='mildiu'>🍃 Riesgo Mildiu</option>
    </select>
  </div>
</header>
<div class='main-area'>
  <div id='map'></div>
  <div id='detail-panel'>
    <div id='detail-header'>
      <span>Detalle de estación</span>
      <button id='close-panel' onclick='cerrarPanel()' title='Cerrar'>✕</button>
    </div>
    <div id='detail-content'>
      <p style='color:#aaa;font-size:13px;line-height:1.7;'>Haz clic en cualquier estación del mapa para ver sus datos aquí.</p>
    </div>
  </div>
</div>
<script>
__JS__
</script>
</body>
</html>"""

# ── Principal ────────────────────────────────────────────────
def principal():
    try:
        from zoneinfo import ZoneInfo
        ahora = datetime.now(ZoneInfo("Europe/Madrid"))
    except ImportError:
        ahora = datetime.now()

    print(f"\n🚀 Obteniendo datos WU de {len(ESTACIONES)} estaciones...")
    datos_wu = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=25) as executor:
        for d in executor.map(wu, ESTACIONES):
            if d: datos_wu.append(d)
    print(f"  ✅ {len(datos_wu)}/{len(ESTACIONES)} estaciones con datos.")
    if not datos_wu:
        print("  ❌ Sin datos. Comprueba la conexión."); return

    print("\n📡 Cargando datos AEMET (14 días)...")
    hae = aemet_diarios(dias=14)

    print("\n📚 Historial 24h local...")
    h24 = hist24(datos_wu, ahora)

    print("\n🌾 Historial agrícola local...")
    hagri = hist_agri(datos_wu, ahora)

    dias_acum = len(hagri)
    print(f"\n  📊 Historial local acumulado: {dias_acum} días")
    if dias_acum < MIN_DIAS:
        print(f"  ⚠ Faltan {MIN_DIAS-dias_acum} días más para riesgo propio — usando AEMET como respaldo")

    print("\n🔬 Calculando riesgo Oídio/Mildiu...")
    r = riesgo(hagri, hae, datos_wu)
    niveles = ['Sin riesgo','Bajo','Medio','ALTO']
    for sid, rv in r.items():
        ot = niveles[rv['oidio']]  if rv['oidio']  >= 0 else '⚠ Insuficiente'
        mt = niveles[rv['mildiu']] if rv['mildiu'] >= 0 else '⚠ Insuficiente'
        print(f"  {sid}: Oídio={ot} | Mildiu={mt} | {rv['fuente_datos']}")

    print("\n🗺  Generando HTML...")
    ruta = generar_html(h24, r, ahora)
    print(f"✅ Listo → {ruta}\n")
    webbrowser.open('file://'+ruta)

if __name__ == "__main__":
    principal()
