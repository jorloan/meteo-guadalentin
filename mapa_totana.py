import urllib.request, json, ssl, os, webbrowser, concurrent.futures, subprocess
from datetime import datetime, timedelta

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

WU_KEY    = "6532d6454b8aa370768e63d6ba5a832e"
AEMET_KEY = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJqb3Nlcm9xdWVAbG9wZXp5YW5kcmVvLmNvbSIsImp0aSI6ImM5OWQwMjdhLWFkOTgtNDI1Yi04ZGRiLTY3ZGNjNzdjMzRkYyIsImlzcyI6IkFFTUVUIiwiaWF0IjoxNzc4NDQ2MTgxLCJ1c2VySWQiOiJjOTlkMDI3YS1hZDk4LTQyNWItOGRkYi02N2RjYzc3YzM0ZGMiLCJyb2xlIjoiIn0.QAttE468tO9unX9oJMFIjEyhlDEr5IkBpdMOFR6-tyg"

# ── Rutas ─────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
REPO_DIR   = os.path.expanduser("~/Documents/meteo-guadalentin")
DIR_PUB    = os.path.join(BASE_DIR, 'public')

# Datos se guardan EN EL REPO (para subirlos a GitHub)
F_H24    = os.path.join(REPO_DIR, 'history_24h.json')
F_AGRI   = os.path.join(REPO_DIR, 'historial_agricola.json')
F_AEMET  = os.path.join(REPO_DIR, 'historial_aemet.json')

os.makedirs(DIR_PUB, exist_ok=True)

MIN_DIAS = 3

AEMET_EST = [
    ("7228",  "Totana AEMET",         37.769, -1.504),
    ("7228B", "Lorca AEMET",          37.679, -1.701),
    ("7213",  "Alhama AEMET",         37.852, -1.425),
    ("7031",  "Mazarrón AEMET",       37.631, -1.316),
    ("7209",  "Lorca/Zarzilla AEMET", 37.901, -1.810),
]

F_EST = os.path.join(BASE_DIR, 'estaciones.txt')
if not os.path.exists(F_EST):
    with open(F_EST,'w') as f:
        for e in ["ITOTAN8","ITOTAN2","ITOTAN16","ITOTAN5","ITOTAN33",
                  "ITOTAN43","ITOTAN31","ITOTAN42","ITOTAN9","ITOTAN41","ITOTAN10","ITOTAN17"]:
            f.write(e+"\n")

ESTACIONES = [l.split('#')[0].strip() for l in open(F_EST) if l.split('#')[0].strip()]

# ── Utilidades ────────────────────────────────────────────────
def leer(ruta, default):
    if os.path.exists(ruta):
        try: return json.load(open(ruta,'r',encoding='utf-8'))
        except: pass
    return default

def guardar(ruta, data):
    with open(ruta,'w',encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def dist(la1,lo1,la2,lo2):
    return ((la1-la2)**2+(lo1-lo2)**2)**0.5

# ── GitHub: subir cambios ─────────────────────────────────────
def git_push(ahora):
    print("\n☁️  Subiendo datos a GitHub...")
    try:
        fecha_str = ahora.strftime("%Y-%m-%d %H:%M")
        cmds = [
            ["git", "-C", REPO_DIR, "add",
             "history_24h.json", "historial_agricola.json",
             "historial_aemet.json"],
            ["git", "-C", REPO_DIR, "commit", "-m",
             f"Actualización automática {fecha_str}"],
            ["git", "-C", REPO_DIR, "push"],
        ]
        for cmd in cmds:
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                # "nothing to commit" no es error real
                if "nothing to commit" in r.stdout or "nothing to commit" in r.stderr:
                    print("  ℹ Sin cambios nuevos que subir.")
                    return
                print(f"  ⚠ {' '.join(cmd[2:])}: {r.stderr.strip()}")
                return
        print("  ✅ Datos subidos a GitHub correctamente.")
        print(f"  🔗 https://github.com/jorloan/meteo-guadalentin")
    except Exception as e:
        print(f"  ⚠ Error git: {e}")

# ── WU: observación actual ────────────────────────────────────
def wu(sid):
    url = (f"https://api.weather.com/v2/pws/observations/current"
           f"?stationId={sid}&format=json&units=m&numericPrecision=decimal&apiKey={WU_KEY}")
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent':'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
            'Referer':'https://www.wunderground.com/'})
        with urllib.request.urlopen(req, context=ctx, timeout=6) as r:
            obs = json.loads(r.read().decode('utf-8')).get('observations',[])
            return obs[0] if obs else None
    except Exception as e:
        print(f"  ⚠ WU {sid}: {e}")
    return None

# ── AEMET: datos diarios ──────────────────────────────────────
def cargar_aemet(dias=14):
    cache = leer(F_AEMET, {})
    ahora = datetime.now()
    dias_nec  = [(ahora-timedelta(days=i)).strftime('%Y-%m-%d') for i in range(1, dias+1)]
    en_cache  = set(d for v in cache.values() for d in v.keys())
    faltantes = [d for d in dias_nec if d not in en_cache]

    if not faltantes:
        print(f"  ✅ AEMET: {len(en_cache)} días en caché (GitHub)")
        return _fmt(cache)

    fi = min(faltantes)+'T00:00:00UTC'
    ff = max(faltantes)+'T23:59:59UTC'
    print(f"  📡 AEMET: descargando {fi[:10]} → {ff[:10]}...")

    def pf(v):
        if v is None: return None
        try: return float(str(v).replace(',','.'))
        except: return None

    for idema, nombre, lat, lon in AEMET_EST:
        path = (f"/api/valores/climatologicos/diarios/datos"
                f"/fechaini/{fi}/fechafin/{ff}/estacion/{idema}")
        try:
            req = urllib.request.Request(
                "https://opendata.aemet.es/opendata/api"+path,
                headers={'api_key': AEMET_KEY})
            with urllib.request.urlopen(req, context=ctx, timeout=12) as r:
                meta = json.loads(r.read().decode('utf-8'))
            if meta.get('estado') != 200:
                raise Exception(meta.get('descripcion',''))
            with urllib.request.urlopen(
                    urllib.request.Request(meta['datos']),
                    context=ctx, timeout=12) as r2:
                datos = json.loads(r2.read().decode('ISO-8859-15'))
            if idema not in cache: cache[idema] = {}
            for d in datos:
                cache[idema][d.get('fecha','')] = {
                    'tmax':pf(d.get('tmax')), 'tmin':pf(d.get('tmin')),
                    'prec':pf(d.get('prec')), 'hrmax':pf(d.get('hrmax')),
                    'lat':lat, 'lon':lon, 'nombre':nombre}
            lim = (ahora-timedelta(days=30)).strftime('%Y-%m-%d')
            cache[idema] = {k:v for k,v in cache[idema].items() if k>=lim}
            print(f"    ✅ {idema} ({nombre}): {len(datos)} días")
        except Exception as e:
            print(f"    ⚠ AEMET {idema}: {e}")

    guardar(F_AEMET, cache)
    return _fmt(cache)

def _fmt(cache):
    return {k:[dict(fecha=f,**v) for f,v in sorted(vv.items())]
            for k,vv in cache.items()}

# ── Historial 24h ─────────────────────────────────────────────
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
    limpio.append({'timestamp': ahora.isoformat(), 'stations': nuevos})
    guardar(F_H24, limpio)
    print(f"  ✅ Historial 24h: {len(limpio)} entradas → {F_H24}")
    return limpio

# ── Historial agrícola ────────────────────────────────────────
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
            h[hoy][sid] = {
                'tempMax':  t if t is not None else -99,
                'tempMin':  t if t is not None else  99,
                'precipTotal': p if p is not None else 0,
                'humedadAltaMinutos': 0,
                'lat': est.get('lat',0), 'lon': est.get('lon',0)}
        else:
            d = h[hoy][sid]
            if t is not None:
                if t > d.get('tempMax',-99): d['tempMax'] = t
                if t < d.get('tempMin', 99): d['tempMin'] = t
            if p is not None and p > d.get('precipTotal',0):
                d['precipTotal'] = p
        if hm is not None and hm >= 85:
            h[hoy][sid]['humedadAltaMinutos'] = h[hoy][sid].get('humedadAltaMinutos',0)+15
    for d in sorted(h.keys())[:-14]: del h[d]
    guardar(F_AGRI, h)
    print(f"  ✅ Historial agrícola: {len(h)} días → {F_AGRI}")
    return h

# ── Riesgo Oídio / Mildiu ─────────────────────────────────────
def calcular_riesgo(hwu, hae, actuales_list):
    act  = {e['stationID']:e for e in actuales_list if e and 'stationID' in e}
    dias = sorted(hwu.keys())
    res  = {}

    posiciones = {}
    for fecha in dias:
        for sid, dd in hwu[fecha].items():
            if sid not in posiciones and dd.get('lat'):
                posiciones[sid] = (dd['lat'], dd['lon'])
    for sid, est in act.items():
        if sid not in posiciones and est.get('lat'):
            posiciones[sid] = (est['lat'], est['lon'])

    for sid, est in act.items():
        ta = est.get('metric',{}).get('temp')
        ha = est.get('humidity')
        la = est.get('lat', posiciones.get(sid,(37.77,0))[0])
        lo = est.get('lon', posiciones.get(sid,(0,-1.5))[1])
        if ta is None: continue

        # 1. WU propio
        filas = []
        for f in (dias[-14:] if len(dias)>=14 else dias):
            dd = hwu[f].get(sid)
            if dd:
                filas.append({'fecha':f,'tmax':dd.get('tempMax'),'tmin':dd.get('tempMin'),
                              'prec':dd.get('precipTotal',0),'hum_min':dd.get('humedadAltaMinutos',0),
                              'src':'WU-propio'})

        # 2. WU vecinos cercanos
        if len(filas) < MIN_DIAS and la and lo:
            fechas_ok = {f['fecha'] for f in filas}
            vecinos = sorted(
                [(s,dist(la,lo,p[0],p[1])) for s,p in posiciones.items() if s!=sid],
                key=lambda x:x[1])
            for vsid, vd in vecinos[:4]:
                if vd > 0.3: break
                for f in (dias[-14:] if len(dias)>=14 else dias):
                    if f in fechas_ok: continue
                    dd = hwu[f].get(vsid)
                    if dd:
                        filas.append({'fecha':f,'tmax':dd.get('tempMax'),'tmin':dd.get('tempMin'),
                                      'prec':dd.get('precipTotal',0),'hum_min':dd.get('humedadAltaMinutos',0),
                                      'src':f'WU-vecino:{vsid}'})
                        fechas_ok.add(f)
                if len(filas) >= MIN_DIAS: break

        # 3. AEMET más cercana
        ae_src = None
        if len(filas) < MIN_DIAS and hae:
            mejor = min(hae.keys(),
                key=lambda k: dist(la,lo,hae[k][0].get('lat',99),hae[k][0].get('lon',99)))
            ae_src = mejor
            fechas_ok = {f['fecha'] for f in filas}
            for da in hae[mejor]:
                if da['fecha'] not in fechas_ok:
                    filas.append({'fecha':da['fecha'],
                                  'tmax':da.get('tmax'),'tmin':da.get('tmin'),
                                  'prec':da.get('prec') or 0,
                                  'hum_min':240 if (da.get('hrmax') or 0)>=85 else 0,
                                  'src':f'AEMET:{mejor}'})

        filas.sort(key=lambda x:x['fecha'])
        filas = filas[-14:]
        nd = len(filas)

        n_wu_p = sum(1 for f in filas if f['src']=='WU-propio')
        n_wu_v = sum(1 for f in filas if f['src'].startswith('WU-vecino'))
        n_ae   = sum(1 for f in filas if f['src'].startswith('AEMET'))
        partes = []
        if n_wu_p: partes.append(f"WU propio {n_wu_p}d")
        if n_wu_v: partes.append(f"WU vecinos {n_wu_v}d")
        if n_ae:
            nb = next((e[1] for e in AEMET_EST if e[0]==ae_src), ae_src) if ae_src else '?'
            partes.append(f"AEMET {nb} {n_ae}d")
        flbl = " + ".join(partes) if partes else "Sin datos"
        ok   = nd >= MIN_DIAS

        p10   = sum(f['prec'] or 0 for f in filas[-10:])
        tminm = min((f['tmin'] for f in filas if f['tmin'] is not None), default=99)
        dt15  = sum(1 for f in filas
                    if f['tmax'] is not None and f['tmin'] is not None
                    and (f['tmax']+f['tmin'])/2 >= 15)
        h85   = sum(f.get('hum_min',0) for f in filas[-7:]) / 60.0

        # Oídio
        no, do = 0, []
        if not ok:
            no=-1; do.append(f"⚠ Solo {nd} días disponibles")
        else:
            if ta>=15 and dt15>=MIN_DIAS:
                do.append(f"{dt15} días con Tmed≥15°C")
                if 15<=ta<19:    no=1; do.append(f"T={ta:.1f}°C — rango bajo")
                elif 19<=ta<=26: no=3 if h85>=4 else 2; do.append(f"T={ta:.1f}°C — rango óptimo"); (do.append(f"{h85:.1f}h HR≥85% (7d)") if h85>=4 else None)
                else:            no=3 if (ha or 0)>=70 else 2; do.append(f"T={ta:.1f}°C + HR={ha}%")
            elif ta>=18: no=1; do.append(f"Solo {dt15} días cálidos")
            else: do.append(f"T={ta:.1f}°C — bajo umbral 15°C")

        # Mildiu
        nm, dm = 0, []
        if not ok:
            nm=-1; dm.append(f"⚠ Solo {nd} días disponibles")
        else:
            ct=tminm>10 or ta>10; cl=p10>=10; cd=nd>=MIN_DIAS
            if ct: dm.append("✓ Tmin>10°C")
            if cl: dm.append(f"✓ Lluvia 10d={p10:.1f}mm")
            if cd: dm.append(f"✓ {nd} días historial")
            nc=sum([ct,cl,cd])
            if nc==3:
                nm=3 if (18<=ta<=24 and (ha or 0)>=85) else 2
                if ta>30: nm=max(0,nm-1); dm.append("T>30°C inhibe esporulación")
                elif 18<=ta<=24 and (ha or 0)>=85: dm.append(f"T={ta:.1f}°C+HR={ha}% condiciones óptimas")
            elif nc==2: nm=1
            if not cl: dm.append(f"Lluvia 10d={p10:.1f}mm (necesita ≥10mm)")

        res[sid]={'lat':la,'lon':lo,'oidio':no,'mildiu':nm,'datos_ok':ok,
                  'dias_disponibles':nd,'fuente_datos':flbl,
                  'detalles':{'oidio':do,'mildiu':dm,'temp_actual':ta,'hum_actual':ha,
                              'precip_10dias':round(p10,1),'dias_tmed_sobre15':dt15,
                              'horas_hum_alta_7d':round(h85,1)}}
    return res

# ── HTML ──────────────────────────────────────────────────────
def generar_html(historial, riesgo_data, ahora):
    fa = ahora.strftime("%d/%m/%Y %H:%M:%S")
    NOMBRES={"ITOTAN8":"Mirador - Lebor Alto","ITOTAN2":"METEO UNDERWORLD","ITOTAN16":"Mortí Bajo",
             "ITOTAN5":"Tierno Galván","ITOTAN33":"Huerto Hostench","ITOTAN43":"Casa Totana",
             "ITOTAN31":"CAMPING Lebor","ITOTAN42":"Secanos","ITOTAN9":"LA CANAL",
             "ITOTAN41":"Ecowitt WN1981","ITOTAN10":"WS Rancho","ITOTAN17":"La Barquilla",
             "IALHAM13":"Alhama Norte","IALHAM81":"Alhama Centro","ILORCA22":"Lorca Sur","IMAZAR7":"Puerto Mazarrón"}
    js=("var NOMBRES="+json.dumps(NOMBRES,ensure_ascii=False)+";\n"
       +"var historyData="+json.dumps(historial,ensure_ascii=False)+";\n"
       +"var riesgoData="+json.dumps(riesgo_data,ensure_ascii=False)+";\n"
       +JS_LOGICA)
    html=HTML_BASE.replace('__FECHA__',fa).replace('__JS__',js)
    # Guardar también en el repo para GitHub Pages
    ruta_repo = os.path.join(REPO_DIR,'index.html')
    ruta_pub  = os.path.join(DIR_PUB,'index.html')
    for ruta in [ruta_repo, ruta_pub]:
        with open(ruta,'w',encoding='utf-8') as f: f.write(html)
    print(f"  ✅ HTML guardado en repo y en public/")
    return ruta_pub

JS_LOGICA = r"""
var RC=['#27ae60','#f39c12','#e67e22','#c0392b'];
var RL=['Sin riesgo','Riesgo bajo','Riesgo medio','Riesgo ALTO'];
var CI=historyData.length-1;
window.HO=0.35;
var terreno=L.tileLayer('http://{s}.google.com/vt/lyrs=p&x={x}&y={y}&z={z}',{maxZoom:20,subdomains:['mt0','mt1','mt2','mt3'],attribution:'© Google',className:'gmap'});
var claro=L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',{attribution:'© CARTO'});
var osm=L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'© OSM'});
var sat=L.tileLayer('http://{s}.google.com/vt/lyrs=s,h&x={x}&y={y}&z={z}',{maxZoom:20,subdomains:['mt0','mt1','mt2','mt3'],attribution:'© Google'});
var map=L.map('map',{center:[37.76,-1.53],zoom:10,layers:[terreno]});
map.createPane('hp');map.getPane('hp').style.zIndex=390;map.getPane('hp').style.filter='blur(14px)';
var rLG=L.layerGroup();
fetch('https://api.rainviewer.com/public/weather-maps.json').then(function(r){return r.json();}).then(function(d){var l=d.radar.past[d.radar.past.length-1];rLG.addLayer(L.tileLayer(d.host+l.path+'/256/{z}/{x}/{y}/2/1_1.png',{opacity:0.7,zIndex:400,maxNativeZoom:7,maxZoom:18}));}).catch(function(){});
var mLG=L.layerGroup(),hLG=L.layerGroup(),HL=null;
L.control.layers({'Relieve':terreno,'Claro':claro,'Satélite':sat,'OSM':osm},{'Radar':rLG,'Calor':hLG,'Marcadores':mLG},{position:'topright',collapsed:true}).addTo(map);
hLG.addTo(map);mLG.addTo(map);
function lerp(c1,c2,t){return 'rgb('+Math.round(c1[0]+t*(c2[0]-c1[0]))+','+Math.round(c1[1]+t*(c2[1]-c1[1]))+','+Math.round(c1[2]+t*(c2[2]-c1[2]))+')'; }
function col(v,p){
  if(p==='oidio'||p==='mildiu'){if(v<0)return '#aaa';return RC[Math.min(3,Math.max(0,Math.round(v)))];}
  if(p==='temp'){var s=[{v:-5,c:[148,0,211]},{v:0,c:[0,0,200]},{v:5,c:[0,115,255]},{v:10,c:[0,200,200]},{v:15,c:[50,205,50]},{v:20,c:[255,255,0]},{v:25,c:[255,140,0]},{v:30,c:[220,20,60]},{v:35,c:[139,0,0]},{v:40,c:[200,0,200]}];if(v<=s[0].v)return 'rgb('+s[0].c+')';if(v>=s[s.length-1].v)return 'rgb('+s[s.length-1].c+')';for(var i=0;i<s.length-1;i++)if(v>=s[i].v&&v<=s[i+1].v)return lerp(s[i].c,s[i+1].c,(v-s[i].v)/(s[i+1].v-s[i].v));}
  if(p==='precip')return v>=70?'#f00':v>=50?'#f9f':v>=40?'#c6f':v>=30?'#939':v>=20?'#609':v>=10?'#00f':v>=4?'#36f':v>=2?'#0cf':v>=0.5?'#9ff':v>0?'#eff':'transparent';
  if(p==='humidity')return v>=90?'#0d47a1':v>=70?'#1976d2':v>=50?'#42a5f5':'#90caf9';
  if(p==='wind')return v>=40?'#b71c1c':v>=30?'#e65100':v>=20?'#f57f17':v>=10?'#fbc02d':v>=5?'#81c784':'#b2dfdb';
  return '#aaa';
}
function raw(e,p){if(p==='oidio'||p==='mildiu'){var r=riesgoData[e.stationID];return r?r[p]:null;}var m=e.metric;if(!m)return null;if(p==='precip')return m.precipTotal;if(p==='temp')return m.temp;if(p==='humidity')return e.humidity;if(p==='wind')return m.windGust;return null;}
function wd(d){if(d==null)return '—';return['N','NNE','NE','ENE','E','ESE','SE','SSE','S','SSO','SO','OSO','O','ONO','NO','NNO'][Math.round(d/22.5)%16];}
function ft(iso){var d=new Date(iso),n=new Date();return(d.getDate()===n.getDate()&&d.getMonth()===n.getMonth()?'Hoy':'Ayer')+', '+d.toLocaleTimeString('es-ES',{hour:'2-digit',minute:'2-digit'});}
var leg=L.control({position:'bottomleft'});
leg.onAdd=function(){this._d=L.DomUtil.create('div','legend');return this._d;};
leg.upd=function(p){
  var h='';
  if(p==='oidio'||p==='mildiu'){h='<b>'+(p==='oidio'?'🍇 Oídio':'🍃 Mildiu')+'</b><br><i style="background:#aaa"></i>Sin datos<br>';for(var i=3;i>=0;i--)h+='<i style="background:'+RC[i]+'"></i>'+RL[i]+'<br>';h+='<small>'+(p==='oidio'?'Gubler-Thomas':'10-10-10+EPI')+'</small>';}
  else{var g,ti,u;if(p==='precip'){ti='🌧 Precipitación';u='mm';g=[0.5,2,4,10,20,30,40,50,70];}else if(p==='temp'){ti='🌡 Temperatura';u='°C';g=[5,10,15,20,25,30,35,40];}else if(p==='humidity'){ti='💧 Humedad';u='%';g=[30,50,70,90];}else{ti='💨 Viento';u='km/h';g=[2,5,10,20,30,40];}h='<b>'+ti+'</b> <small>'+u+'</small><br><i style="background:'+col(g[g.length-1],p)+'"></i>&gt;'+g[g.length-1]+'<br>';for(var i=g.length-2;i>=0;i--)h+='<i style="background:'+col(g[i],p)+'"></i>'+g[i]+'-'+g[i+1]+'<br>';}
  this._d.innerHTML=h;
};leg.addTo(map);
var PS=null;
function showPanel(sid,html){document.getElementById('dc').innerHTML=html;document.getElementById('dp').style.display='flex';PS=sid;}
function hidePanel(){document.getElementById('dp').style.display='none';PS=null;}
function render(){
  var p=document.getElementById('ps').value;
  var isR=p==='oidio'||p==='mildiu';
  leg.upd(p);hLG.clearLayers();mLG.clearLayers();HL=null;
  var snap=isR?historyData[historyData.length-1]:historyData[CI];
  if(!snap)return;
  var feats=[];
  (snap.stations||[]).forEach(function(est){
    if(!est||est.lat==null||est.lon==null)return;
    var v=raw(est,p);if(v==null)return;
    var bg=col(v,p);
    var lb=isR?(v<0?'?':['0','B','M','A'][Math.min(3,Math.max(0,Math.round(v)))]):(p==='precip'?v.toFixed(1):p==='temp'?Math.round(v)+'°':Math.round(v)+'');
    var ws='';if(p==='wind'&&est.winddir!=null)ws='<svg style="position:absolute;top:-13px;left:-13px;width:50px;height:50px;transform:rotate('+est.winddir+'deg);z-index:-1;pointer-events:none;"viewBox="0 0 50 50"><line x1="25"y1="2"x2="25"y2="13"stroke="black"stroke-width="2.5"/></svg>';
    var ih='<div style="position:relative;"><div style="background:'+bg+';color:#fff;text-shadow:1px 1px 2px rgba(0,0,0,.8);border:1.5px solid #fff;border-radius:50%;width:26px;height:26px;display:flex;justify-content:center;align-items:center;font-weight:700;font-size:10px;box-shadow:0 2px 5px rgba(0,0,0,.4);cursor:pointer;">'+lb+'</div>'+ws+'</div>';
    var mk=L.marker([est.lat,est.lon],{icon:L.divIcon({className:'',html:ih,iconSize:[26,26],iconAnchor:[13,13]})});
    var nm=NOMBRES[est.stationID]||(est.neighborhood&&est.neighborhood.trim()!==''?est.neighborhood:est.stationID);
    var ph;
    if(isR){
      var r=riesgoData[est.stationID];
      if(r){
        var nO=r.oidio,nM=r.mildiu,det=r.detalles||{};
        var dO=(det.oidio||[]).join('<br>&bull; '),dM=(det.mildiu||[]).join('<br>&bull; ');
        var av='';
        if(!r.datos_ok){av='<div style="background:#fff3cd;border:1px solid #ffc107;border-radius:6px;padding:8px;margin-bottom:10px;font-size:12px;">⚠️ <b>Datos limitados</b> ('+r.dias_disponibles+' días)<br><span style="color:#666;">Se usaron estaciones vecinas y/o AEMET como respaldo.</span></div>';}
        ph=av
          +'<div style="margin-bottom:6px;"><b>🍇 Oídio:</b> <span style="padding:2px 9px;border-radius:10px;font-size:12px;font-weight:700;color:#fff;background:'+(nO<0?'#aaa':RC[nO])+'">'+(nO<0?'Sin datos':RL[nO])+'</span></div>'
          +'<div style="font-size:12px;color:#555;margin-bottom:10px;">&bull; '+(dO||'—')+'</div>'
          +'<div style="margin-bottom:6px;"><b>🍃 Mildiu:</b> <span style="padding:2px 9px;border-radius:10px;font-size:12px;font-weight:700;color:#fff;background:'+(nM<0?'#aaa':RC[nM])+'">'+(nM<0?'Sin datos':RL[nM])+'</span></div>'
          +'<div style="font-size:12px;color:#555;margin-bottom:10px;">&bull; '+(dM||'—')+'</div>'
          +'<hr style="border:0;border-top:1px solid #eee;margin:8px 0;">'
          +'<div style="font-size:12px;color:#666;">🌡 '+(det.temp_actual!=null?det.temp_actual.toFixed(1)+'°C':'—')+' &nbsp;💧 '+(det.hum_actual!=null?det.hum_actual+'%':'—')+'<br>🌧 Lluvia 10d='+(det.precip_10dias||0)+'mm &nbsp;⏱ HR alta='+(det.horas_hum_alta_7d||0)+'h (7d)</div>'
          +'<div style="font-size:11px;color:#aaa;margin-top:8px;">📊 '+r.fuente_datos+'</div>';
      }else{ph='<div style="color:#999;font-size:13px;">Sin datos.</div>';}
    }else{
      var m=est.metric||{};
      ph='<table style="width:100%;font-size:13px;border-collapse:collapse;line-height:2;">'
        +'<tr><td style="color:#888">🌡 Temperatura</td><td style="font-weight:700">'+(m.temp!=null?m.temp.toFixed(1)+'°C':'—')+'</td></tr>'
        +'<tr><td style="color:#888">🌧 Precipitación</td><td style="font-weight:700">'+(m.precipTotal!=null?m.precipTotal.toFixed(1)+' mm':'—')+'</td></tr>'
        +'<tr><td style="color:#888">💨 Viento</td><td style="font-weight:700">'+(m.windSpeed!=null?m.windSpeed.toFixed(0)+' km/h':'—')+' '+wd(est.winddir)+'</td></tr>'
        +'<tr><td style="color:#888">⬆ Racha</td><td style="font-weight:700">'+(m.windGust!=null?m.windGust.toFixed(0)+' km/h':'—')+'</td></tr>'
        +'<tr><td style="color:#888">💧 Humedad</td><td style="font-weight:700">'+(est.humidity!=null?est.humidity+'%':'—')+'</td></tr>'
        +'<tr><td style="color:#888">🕒 Obs.</td><td>'+(est.obsTimeLocal?est.obsTimeLocal.slice(11,16):'—')+'</td></tr>'
        +'</table>'
        +'<a href="https://www.wunderground.com/dashboard/pws/'+est.stationID+'" target="_blank" style="display:inline-block;margin-top:12px;padding:7px 16px;background:#3498db;color:#fff;text-decoration:none;border-radius:6px;font-size:12px;">Ver historial WU ↗</a>';
    }
    var fh='<div style="font-size:15px;font-weight:700;color:#2c3e50;margin-bottom:4px;">'+nm+'</div><div style="font-size:11px;color:#bbb;margin-bottom:12px;">'+est.stationID+'</div>'+ph;
    (function(id,h){mk.on('click',function(){showPanel(id,h);});})(est.stationID,fh);
    mk.bindTooltip('<b>'+nm+'</b>',{direction:'top',offset:[0,-16],opacity:0.9});
    mLG.addLayer(mk);
    if(!isR)feats.push(turf.point([est.lon,est.lat],{value:v}));
  });
  if(!isR&&feats.length>2){try{var c=turf.featureCollection(feats);var g=turf.interpolate(c,2.5,{gridType:'square',property:'value',units:'kilometers',weight:p==='temp'?2:4});var cl=turf.featureCollection(g.features.filter(function(f){return f.properties.value!=null&&!isNaN(f.properties.value);}));HL=L.geoJSON(cl,{pane:'hp',style:function(f){return{fillColor:col(f.properties.value,p),fillOpacity:window.HO,stroke:false};}});hLG.addLayer(HL);}catch(e){console.error(e);}}
}
var sl=document.getElementById('sl'),tl=document.getElementById('tl');
function initSl(){var n=historyData.length;if(!n){tl.innerText='Sin datos';return;}sl.min=0;sl.max=n-1;sl.value=n-1;CI=n-1;tl.innerText=ft(historyData[n-1].timestamp)+' (Actual)';render();}
sl.addEventListener('input',function(){CI=parseInt(this.value);var last=CI===historyData.length-1;tl.innerText=ft(historyData[CI].timestamp)+(last?' (Actual)':' (Histórico)');render();});
var PT=null;
document.getElementById('pb').addEventListener('click',function(){if(PT){clearInterval(PT);PT=null;this.textContent='▶️';}else{this.textContent='⏸️';if(CI>=historyData.length-1)CI=0;var s=this;PT=setInterval(function(){CI=(CI+1)%historyData.length;sl.value=CI;sl.dispatchEvent(new Event('input'));if(CI===historyData.length-1){clearInterval(PT);PT=null;s.textContent='▶️';}},1500);}});
document.getElementById('op').addEventListener('input',function(){window.HO=parseFloat(this.value);if(HL)HL.setStyle({fillOpacity:window.HO});});
initSl();
"""

HTML_BASE="""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>Meteo Guadalentín</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/@turf/turf@6/turf.min.js"></script>
  <style>
    *{box-sizing:border-box}body{font-family:'Segoe UI',sans-serif;margin:0;display:flex;flex-direction:column;height:100vh}
    header{background:#1a252f;color:#fff;padding:.6rem 1rem;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;flex-shrink:0;box-shadow:0 3px 8px rgba(0,0,0,.3)}
    h1{margin:0;font-size:1.1rem}.sub{font-size:.72rem;color:#bdc3c7;margin-top:2px}
    .ct{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
    select{padding:5px 9px;border-radius:6px;border:none;background:#ecf0f1;color:#2c3e50;font-weight:700;font-size:.82rem;cursor:pointer}
    .ma{display:flex;flex:1;overflow:hidden}
    #map{flex:1;height:100%}
    #dp{display:none;flex-direction:column;width:285px;min-width:240px;background:#fff;border-left:1px solid #e0e0e0;overflow:hidden;flex-shrink:0}
    #dh{background:#1a252f;color:#fff;padding:9px 12px;display:flex;justify-content:space-between;align-items:center;flex-shrink:0;font-size:13px;font-weight:600}
    #cp{background:none;border:none;color:#fff;font-size:18px;cursor:pointer;padding:0 4px}
    #dc{padding:14px;font-size:13px;overflow-y:auto;flex:1}
    .legend{background:rgba(255,255,255,.95);padding:7px 10px;border-radius:8px;box-shadow:0 2px 10px rgba(0,0,0,.2);font-size:.75rem;line-height:1.8;color:#333;max-height:55vh;overflow-y:auto;max-width:145px}
    .legend i{width:14px;height:12px;float:left;margin-right:6px;opacity:.85;border:1px solid rgba(0,0,0,.1)}
    .gmap{filter:grayscale(100%) contrast(1.1) brightness(1.05)}
    @media(max-width:600px){header{flex-direction:column;align-items:flex-start}.ct{width:100%}#dp{width:100%;max-height:45vh}}
  </style>
</head>
<body>
<header>
  <div><h1>🌿 Meteo Guadalentín</h1><div class="sub">Actualizado: <span id="tl">__FECHA__</span></div></div>
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
<div class="ma">
  <div id="map"></div>
  <div id="dp">
    <div id="dh"><span>Detalle de estación</span><button id="cp" onclick="hidePanel()">✕</button></div>
    <div id="dc"><p style="color:#aaa;font-size:13px;line-height:1.7">Haz clic en una estación del mapa para ver sus datos aquí.</p></div>
  </div>
</div>
<script>__JS__</script>
</body>
</html>"""

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
        print("  ❌ Sin datos WU."); return

    print("\n📡 Cargando datos AEMET (14 días)...")
    hae = cargar_aemet(dias=14)

    print("\n📚 Historial 24h...")
    h24 = hist24(datos_wu, ahora)

    print("\n🌾 Historial agrícola...")
    hagri = hist_agri(datos_wu, ahora)
    print(f"  📊 {len(hagri)} días acumulados en GitHub")

    print("\n🔬 Calculando riesgo Oídio/Mildiu...")
    r = calcular_riesgo(hagri, hae, datos_wu)
    niveles=['Sin riesgo','Bajo','Medio','ALTO']
    for sid,rv in r.items():
        ot=niveles[rv['oidio']]  if rv['oidio'] >=0 else '⚠ Insuf.'
        mt=niveles[rv['mildiu']] if rv['mildiu']>=0 else '⚠ Insuf.'
        print(f"  {sid}: Oídio={ot} | Mildiu={mt} | {rv['fuente_datos']}")

    print("\n🗺  Generando HTML...")
    ruta = generar_html(h24, r, ahora)

    print("\n☁️  Subiendo a GitHub...")
    git_push(ahora)

    print(f"\n✅ Listo → {ruta}")
    print(f"🌐 Web pública: https://jorloan.github.io/meteo-guadalentin/")
    webbrowser.open('file://'+ruta)

if __name__ == "__main__":
    principal()
