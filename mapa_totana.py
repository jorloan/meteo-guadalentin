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

# Key interna que usa wunderground.com en su propia web (sin cuenta de pago)
API_KEY = "6532d6454b8aa370768e63d6ba5a832e"

ARCHIVO_ESTACIONES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'estaciones.txt')

if not os.path.exists(ARCHIVO_ESTACIONES):
    with open(ARCHIVO_ESTACIONES, 'w', encoding='utf-8') as f:
        f.write("# Añade aquí los IDs de las estaciones, uno por línea.\n")
        for est in ["ITOTAN8","ITOTAN2","ITOTAN16","ITOTAN5","ITOTAN33","ITOTAN43",
                    "ITOTAN31","ITOTAN42","ITOTAN9","ITOTAN41","ITOTAN10","ITOTAN17"]:
            f.write(f"{est}\n")

ESTACIONES = []
with open(ARCHIVO_ESTACIONES, 'r', encoding='utf-8') as f:
    for linea in f:
        linea_limpia = linea.split('#')[0].strip()
        if linea_limpia:
            ESTACIONES.append(linea_limpia)

# ─────────────────────────────────────────────
# OBTENER DATOS DE UNA ESTACIÓN
# ─────────────────────────────────────────────
def obtener_datos_estacion(station_id):
    url = (f"https://api.weather.com/v2/pws/observations/current"
           f"?stationId={station_id}&format=json&units=m&numericPrecision=decimal&apiKey={API_KEY}")
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
            'Referer': 'https://www.wunderground.com/'
        })
        with urllib.request.urlopen(req, context=ctx, timeout=6) as response:
            if response.getcode() == 200:
                data = json.loads(response.read().decode('utf-8'))
                obs = data.get('observations', [])
                if obs:
                    return obs[0]
    except Exception as e:
        print(f"  ⚠ {station_id}: {e}")
    return None

# ─────────────────────────────────────────────
# HISTORIAL 24H
# ─────────────────────────────────────────────
def gestionar_historial(nuevos_datos, ahora):
    url_historico = "https://jorloan.github.io/meteo-guadalentin/history_24h.json"
    historial = []
    try:
        req = urllib.request.Request(url_historico, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=ctx, timeout=5) as response:
            if response.getcode() == 200:
                historial = json.loads(response.read().decode('utf-8'))
                print(f"  ✅ Historial descargado: {len(historial)} registros.")
                # Limpiar entradas de AEMET antiguas
                if historial and any(not e.get('stationID','I').startswith('I')
                                     for e in historial[-1].get('stations', [])):
                    print("  ⚠ Detectadas estaciones AEMET antiguas. Limpiando historial.")
                    historial = []
    except Exception as e:
        print(f"  ℹ Historial previo no disponible ({e})")

    limite = ahora - timedelta(hours=24)
    historial_limpio = []
    for h in historial:
        try:
            t = datetime.fromisoformat(h['timestamp'])
            if t.tzinfo is None:
                t = t.replace(tzinfo=ahora.tzinfo)
            if t > limite:
                historial_limpio.append(h)
        except:
            pass

    historial_limpio.append({
        'timestamp': ahora.isoformat(),
        'stations': nuevos_datos
    })

    directorio_publico = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'public')
    os.makedirs(directorio_publico, exist_ok=True)
    with open(os.path.join(directorio_publico, 'history_24h.json'), 'w', encoding='utf-8') as f:
        json.dump(historial_limpio, f, ensure_ascii=False)

    return historial_limpio

# ─────────────────────────────────────────────
# HISTORIAL AGRÍCOLA 14 DÍAS
# ─────────────────────────────────────────────
def gestionar_historial_agricola(nuevos_datos, ahora):
    url_agricola = "https://jorloan.github.io/meteo-guadalentin/historial_agricola.json"
    historico = {}
    try:
        req = urllib.request.Request(url_agricola, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=ctx, timeout=5) as response:
            if response.getcode() == 200:
                historico = json.loads(response.read().decode('utf-8'))
                print(f"  ✅ Historial agrícola descargado ({len(historico)} días).")
    except Exception as e:
        print(f"  ℹ Historial agrícola no disponible ({e})")

    fecha_hoy = ahora.strftime('%Y-%m-%d')
    if fecha_hoy not in historico:
        historico[fecha_hoy] = {}

    for est in nuevos_datos:
        if not est or 'stationID' not in est:
            continue
        sid = est['stationID']
        temp  = est.get('metric', {}).get('temp')
        precip = est.get('metric', {}).get('precipTotal')
        hum   = est.get('humidity')

        if sid not in historico[fecha_hoy]:
            historico[fecha_hoy][sid] = {
                'tempMax': temp if temp is not None else -99,
                'tempMin': temp if temp is not None else 99,
                'tempSum': temp if temp is not None else 0,
                'tempCount': 1 if temp is not None else 0,
                'precipTotal': precip if precip is not None else 0.0,
                'humedadAltaMinutos': 0
            }
        else:
            d = historico[fecha_hoy][sid]
            if temp is not None:
                if temp > d.get('tempMax', -99): d['tempMax'] = temp
                if temp < d.get('tempMin', 99):  d['tempMin'] = temp
                d['tempSum']   = d.get('tempSum', 0) + temp
                d['tempCount'] = d.get('tempCount', 0) + 1
            if precip is not None:
                if precip > d.get('precipTotal', 0): d['precipTotal'] = precip

        if hum is not None and hum >= 85:
            historico[fecha_hoy][sid]['humedadAltaMinutos'] = (
                historico[fecha_hoy][sid].get('humedadAltaMinutos', 0) + 15
            )

    # Mantener solo los últimos 14 días
    dias = sorted(historico.keys())
    for d in dias[:-14]:
        del historico[d]

    directorio_publico = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'public')
    os.makedirs(directorio_publico, exist_ok=True)
    with open(os.path.join(directorio_publico, 'historial_agricola.json'), 'w', encoding='utf-8') as f:
        json.dump(historico, f, ensure_ascii=False)

    return historico

# ─────────────────────────────────────────────
# CALCULAR RIESGO OIDIO / MILDIU
# Modelos: Gubler-Thomas (UC Davis) para oidio
#          Regla 10-10-10 + EPI para mildiu
# ─────────────────────────────────────────────
def calcular_riesgo_agricola(historico_agricola, datos_actuales):
    """
    Devuelve dict: {stationID: {oidio: 0-3, mildiu: 0-3, detalles: {...}}}
    Nivel 0=Sin riesgo, 1=Bajo, 2=Medio, 3=Alto
    """
    dias_ordenados = sorted(historico_agricola.keys())
    riesgo = {}

    # Índice de datos actuales por estación
    actuales = {e['stationID']: e for e in datos_actuales if e and 'stationID' in e}

    for sid, est_actual in actuales.items():
        temp_actual = est_actual.get('metric', {}).get('temp')
        hum_actual  = est_actual.get('humidity')
        if temp_actual is None:
            continue

        # Acumular datos históricos para este sid
        dias_con_datos = 0
        precip_10dias = 0.0
        tmin_minima   = 99.0
        dias_tmed_sobre_15 = 0
        horas_hum_alta = 0.0  # total horas con humedad >= 85% en últimos 7 días
        dias_recientes = dias_ordenados[-10:] if len(dias_ordenados) >= 10 else dias_ordenados

        for fecha in dias_recientes:
            datos_dia = historico_agricola[fecha].get(sid)
            if not datos_dia:
                continue
            dias_con_datos += 1
            tmax = datos_dia.get('tempMax', -99)
            tmin = datos_dia.get('tempMin', 99)
            prec = datos_dia.get('precipTotal', 0)
            hum_min = datos_dia.get('humedadAltaMinutos', 0)

            precip_10dias += prec
            if tmin < tmin_minima:
                tmin_minima = tmin

            tmed = (tmax + tmin) / 2 if tmax > -99 and tmin < 99 else None
            if tmed is not None and tmed >= 15:
                dias_tmed_sobre_15 += 1

            # Solo últimos 7 días para humedad
            if fecha in dias_ordenados[-7:]:
                horas_hum_alta += hum_min / 60.0

        # ── OIDIO (Gubler-Thomas simplificado) ──────────────────
        # Necesita temperatura media y horas de humedad alta
        nivel_oidio = 0
        detalle_oidio = []

        if temp_actual >= 15:
            if dias_tmed_sobre_15 >= 7:
                detalle_oidio.append(f"{dias_tmed_sobre_15} días con Tmed≥15°C")
                if 15 <= temp_actual < 19:
                    nivel_oidio = 1  # bajo
                    detalle_oidio.append(f"Tact={temp_actual:.1f}°C (rango bajo)")
                elif 19 <= temp_actual <= 26:
                    nivel_oidio = 2  # medio
                    detalle_oidio.append(f"Tact={temp_actual:.1f}°C (rango óptimo)")
                    if horas_hum_alta >= 4:
                        nivel_oidio = 3  # alto
                        detalle_oidio.append(f"{horas_hum_alta:.1f}h HR≥85% (últimos 7d)")
                elif temp_actual > 26:
                    nivel_oidio = 2  # calor alto reduce algo el oidio pero mantiene riesgo
                    detalle_oidio.append(f"Tact={temp_actual:.1f}°C (calor, riesgo moderado)")
                    if hum_actual is not None and hum_actual >= 70:
                        nivel_oidio = 3
                        detalle_oidio.append(f"HR={hum_actual}% favorece esporulación nocturna")
            else:
                nivel_oidio = 1 if temp_actual >= 18 else 0
                detalle_oidio.append(f"Solo {dias_tmed_sobre_15} días cálidos acumulados")

        # ── MILDIU (Regla 10-10-10 + condiciones actuales) ──────
        nivel_mildiu = 0
        detalle_mildiu = []

        cond_temp   = tmin_minima > 10 or temp_actual > 10
        cond_lluvia = precip_10dias >= 10
        cond_dias   = dias_con_datos >= 7  # proxy de brotación/desarrollo vegetativo

        if cond_temp:
            detalle_mildiu.append(f"Tmin>{10}°C ✓")
        if cond_lluvia:
            detalle_mildiu.append(f"Lluvia 10d={precip_10dias:.1f}mm ✓")
        if cond_dias:
            detalle_mildiu.append(f"{dias_con_datos} días de historial ✓")

        condiciones_cumplidas = sum([cond_temp, cond_lluvia, cond_dias])

        if condiciones_cumplidas == 3:
            nivel_mildiu = 2  # riesgo medio: regla 10-10-10 cumplida
            # Refinamiento EPI: temperatura óptima + humedad alta
            if 18 <= temp_actual <= 24 and hum_actual is not None and hum_actual >= 85:
                nivel_mildiu = 3
                detalle_mildiu.append(f"Tact={temp_actual:.1f}°C + HR={hum_actual}% (condiciones óptimas)")
            elif 15 <= temp_actual <= 28:
                detalle_mildiu.append(f"Tact={temp_actual:.1f}°C en rango favorable")
            # Si T > 30°C, inhibición del mildiu
            if temp_actual > 30:
                nivel_mildiu = max(0, nivel_mildiu - 1)
                detalle_mildiu.append(f"T>{30}°C inhibe desarrollo")
        elif condiciones_cumplidas == 2:
            nivel_mildiu = 1
        elif condiciones_cumplidas <= 1:
            nivel_mildiu = 0

        riesgo[sid] = {
            'lat': est_actual.get('lat'),
            'lon': est_actual.get('lon'),
            'oidio': nivel_oidio,
            'mildiu': nivel_mildiu,
            'detalles': {
                'oidio': detalle_oidio,
                'mildiu': detalle_mildiu,
                'temp_actual': temp_actual,
                'hum_actual': hum_actual,
                'precip_10dias': round(precip_10dias, 1),
                'dias_tmed_sobre15': dias_tmed_sobre_15,
                'horas_hum_alta_7d': round(horas_hum_alta, 1),
            }
        }

    return riesgo

# ─────────────────────────────────────────────
# GENERAR HTML
# ─────────────────────────────────────────────
def generar_html(historial_data, riesgo_agricola, ahora):
    fecha_actualizada = ahora.strftime("%d/%m/%Y %H:%M:%S")

    html_content = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Meteo Guadalentín</title>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/@turf/turf@6/turf.min.js"></script>
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 0; background:#f5f7fa; display:flex; flex-direction:column; height:100vh; }}
        header {{ background:#1a252f; color:white; padding:0.8rem 1.5rem; display:flex; justify-content:space-between; align-items:center; z-index:10; box-shadow:0 4px 6px rgba(0,0,0,0.2); flex-wrap:wrap; gap:8px; }}
        .header-left h1 {{ margin:0; font-size:1.3rem; font-weight:600; }}
        .subtitle {{ font-size:0.8rem; color:#bdc3c7; margin-top:3px; }}
        .controls {{ display:flex; gap:10px; align-items:center; flex-wrap:wrap; }}
        .controls select {{ padding:6px 12px; border-radius:6px; border:none; background:#ecf0f1; color:#2c3e50; font-weight:bold; font-size:0.9rem; outline:none; cursor:pointer; }}
        .container {{ display:flex; flex:1; overflow:hidden; position:relative; }}
        #map {{ flex:1; height:100%; }}
        .legend {{ background:rgba(255,255,255,0.95); padding:6px 10px; border-radius:8px; box-shadow:0 2px 10px rgba(0,0,0,0.2); font-size:0.75rem; font-weight:bold; line-height:1.5; color:#333; max-height:55vh; overflow-y:auto; max-width:130px; }}
        .legend i {{ width:14px; height:12px; float:left; margin-right:6px; opacity:0.8; border:1px solid rgba(0,0,0,0.1); }}
        .legend-riesgo {{ max-width:160px; }}
        .grayscale-map {{ filter:grayscale(100%) contrast(1.1) brightness(1.05); }}
        #loading {{ display:none; position:absolute; top:0; left:0; right:0; bottom:0; background:rgba(255,255,255,0.7); z-index:2000; justify-content:center; align-items:center; font-size:1.3rem; font-weight:bold; color:#2c3e50; flex-direction:column; }}
        .riesgo-badge {{ display:inline-block; padding:2px 7px; border-radius:10px; font-size:0.8rem; font-weight:bold; color:white; margin:2px; }}
        .r0 {{ background:#27ae60; }}
        .r1 {{ background:#f39c12; }}
        .r2 {{ background:#e67e22; }}
        .r3 {{ background:#c0392b; }}
        @media(max-width:600px) {{
            header {{ padding:0.6rem 0.8rem; flex-direction:column; align-items:flex-start; }}
            .controls {{ width:100%; }}
            .controls select {{ width:100%; }}
        }}
    </style>
</head>
<body>
    <header>
        <div class="header-left">
            <h1>🌿 Meteo Guadalentín</h1>
            <div class="subtitle">Actualizado: <span id="time-label">{fecha_actualizada}</span></div>
        </div>
        <div class="controls">
            <div style="display:flex;flex-direction:column;align-items:center;">
                <span style="font-size:0.7rem;color:#ecf0f1;font-weight:bold;">⏱ Máquina del Tiempo</span>
                <div style="display:flex;align-items:center;gap:5px;">
                    <button id="play-btn" style="background:transparent;color:white;border:none;cursor:pointer;font-size:1.1rem;padding:0 4px;" title="Reproducir">▶️</button>
                    <input type="range" id="time-slider" min="0" max="0" value="0" style="width:110px;cursor:pointer;" title="Historial 24h">
                </div>
            </div>
            <div style="display:flex;flex-direction:column;align-items:center;">
                <span style="font-size:0.7rem;color:#ecf0f1;font-weight:bold;">🔆 Transparencia</span>
                <input type="range" id="opacity-slider" min="0" max="1" step="0.05" value="0.35" style="width:80px;cursor:pointer;">
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

    <div class="container">
        <div id="map"></div>
        <div id="loading"><div>Calculando...</div></div>
    </div>

    <script>
    var nombresPersonalizados = {{
        "ITOTAN8":  "Mirador - Lebor Alto",
        "ITOTAN2":  "METEO UNDERWORLD",
        "ITOTAN16": "Mortí Bajo - Camino Aleurrosas",
        "ITOTAN5":  "Estación Tierno Galván",
        "ITOTAN33": "Huerto Hostench",
        "ITOTAN43": "Casa Totana",
        "ITOTAN31": "CAMPING - Lebor - Totana",
        "ITOTAN42": "Secanos",
        "ITOTAN9":  "LA CANAL - Raiguero",
        "ITOTAN41": "Ecowitt WN1981",
        "ITOTAN10": "WS Rancho",
        "ITOTAN17": "La Barquilla",
        "IALHAM13": "Alhama Norte",
        "IALHAM81": "Alhama Centro",
        "ILORCA22": "Lorca Sur",
        "IMAZAR7":  "Puerto Mazarrón"
    }};

    var historyData   = {json.dumps(historial_data)};
    var riesgoData    = {json.dumps(riesgo_agricola)};
    var currentTimestampIndex = historyData.length - 1;
    window.globalHeatmapOpacity = 0.35;

    // ── Capas base ──────────────────────────────────────────────
    var terreno = L.tileLayer('http://{{s}}.google.com/vt/lyrs=p&x={{x}}&y={{y}}&z={{z}}', {{
        maxZoom:20, subdomains:['mt0','mt1','mt2','mt3'],
        attribution:'&copy; Google Terrain', className:'grayscale-map'
    }});
    var mapaClaro   = L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{attribution:'&copy; CARTO'}});
    var estandar    = L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{attribution:'&copy; OSM'}});
    var googleSat   = L.tileLayer('http://{{s}}.google.com/vt/lyrs=s,h&x={{x}}&y={{y}}&z={{z}}', {{maxZoom:20, subdomains:['mt0','mt1','mt2','mt3'], attribution:'&copy; Google'}});

    var map = L.map('map', {{center:[37.76,-1.53], zoom:10, layers:[terreno]}});
    map.createPane('heatmapPane');
    map.getPane('heatmapPane').style.zIndex  = 390;
    map.getPane('heatmapPane').style.filter  = 'blur(14px)';

    // Radar RainViewer
    var radarLayer = L.layerGroup();
    fetch('https://api.rainviewer.com/public/weather-maps.json')
        .then(r=>r.json()).then(d=>{{
            var last = d.radar.past[d.radar.past.length-1];
            radarLayer.addLayer(L.tileLayer(
                d.host+last.path+'/256/{{z}}/{{x}}/{{y}}/2/1_1.png',
                {{opacity:0.7, zIndex:400, attribution:'RainViewer', maxNativeZoom:7, maxZoom:18}}
            ));
        }}).catch(()=>{{}});

    var markersLayer     = L.layerGroup();
    var heatmapLayerGroup = L.layerGroup();
    var heatmapLayer     = null;

    L.control.layers(
        {{"Relieve":terreno,"Mapa Claro":mapaClaro,"Satélite":googleSat,"Estándar":estandar}},
        {{"Radar Lluvia":radarLayer,"Mapa Calor":heatmapLayerGroup,"Etiquetas":markersLayer}},
        {{position:'topright', collapsed:true}}
    ).addTo(map);
    heatmapLayerGroup.addTo(map);
    markersLayer.addTo(map);

    // ── Botón localización ───────────────────────────────────────
    var locBtn = L.control({{position:'topleft'}});
    locBtn.onAdd = function(){{
        var d = L.DomUtil.create('div','leaflet-bar leaflet-control');
        d.innerHTML = '<a href="#" title="Mi ubicación" style="font-size:18px;background:white;display:flex;justify-content:center;align-items:center;width:30px;height:30px;text-decoration:none;">🎯</a>';
        d.onclick = function(e){{ e.preventDefault(); map.locate({{setView:true,maxZoom:13}}); }};
        return d;
    }};
    locBtn.addTo(map);
    var userMarker = null;
    map.on('locationfound', function(e){{
        if(userMarker) map.removeLayer(userMarker);
        userMarker = L.circleMarker(e.latlng,{{radius:8,color:'#3498db',fillColor:'#3498db',fillOpacity:0.8}})
            .addTo(map).bindPopup("Estás aquí").openPopup();
    }});

    // ── Colores ──────────────────────────────────────────────────
    function interpolateColor(c1,c2,f){{
        return `rgb(${{Math.round(c1[0]+f*(c2[0]-c1[0]))}},`+
               `${{Math.round(c1[1]+f*(c2[1]-c1[1]))}},`+
               `${{Math.round(c1[2]+f*(c2[2]-c1[2]))}})`;
    }}

    var RIESGO_COLORS = ['#27ae60','#f39c12','#e67e22','#c0392b'];
    var RIESGO_LABELS = ['Sin riesgo','Riesgo bajo','Riesgo medio','Riesgo alto'];

    function getColor(val, param){{
        if(param==='oidio'||param==='mildiu'){{
            var lvl = Math.round(Math.max(0,Math.min(3,val)));
            return RIESGO_COLORS[lvl];
        }}
        if(param==='temp'){{
            var stops=[
                {{v:-5,c:[148,0,211]}},{{v:0,c:[0,0,200]}},{{v:5,c:[0,115,255]}},
                {{v:10,c:[0,200,200]}},{{v:15,c:[50,205,50]}},{{v:20,c:[255,255,0]}},
                {{v:25,c:[255,140,0]}},{{v:30,c:[220,20,60]}},{{v:35,c:[139,0,0]}},{{v:40,c:[200,0,200]}}
            ];
            if(val<=stops[0].v) return `rgb(${{stops[0].c.join(',')}})`;
            if(val>=stops[stops.length-1].v) return `rgb(${{stops[stops.length-1].c.join(',')}})`;
            for(var i=0;i<stops.length-1;i++){{
                if(val>=stops[i].v&&val<=stops[i+1].v){{
                    return interpolateColor(stops[i].c,stops[i+1].c,(val-stops[i].v)/(stops[i+1].v-stops[i].v));
                }}
            }}
        }} else if(param==='precip'){{
            return val>=70?'#ff0000':val>=50?'#ff99ff':val>=40?'#cc66ff':val>=30?'#993399':
                   val>=20?'#660099':val>=10?'#0000ff':val>=4?'#3366ff':val>=2?'#00ccff':
                   val>=0.5?'#99ffff':val>0?'#e6ffff':'transparent';
        }} else if(param==='humidity'){{
            return val>=90?'#0d47a1':val>=70?'#1976d2':val>=50?'#42a5f5':val>=30?'#90caf9':'#e3f2fd';
        }} else if(param==='wind'){{
            return val>=40?'#b71c1c':val>=30?'#e65100':val>=20?'#f57f17':
                   val>=10?'#fbc02d':val>=5?'#81c784':val>=2?'#b2dfdb':'transparent';
        }}
        return '#ccc';
    }}

    function getRawValue(est, param){{
        if(param==='oidio'||param==='mildiu'){{
            var r = riesgoData[est.stationID];
            return r ? r[param] : null;
        }}
        var m = est.metric;
        if(!m) return null;
        if(param==='precip')    return m.precipTotal;
        if(param==='temp')      return m.temp;
        if(param==='humidity')  return est.humidity;
        if(param==='wind')      return m.windGust;
        return null;
    }}

    // ── Leyenda ──────────────────────────────────────────────────
    var legend = L.control({{position:'bottomleft'}});
    legend.onAdd = function(){{
        this._div = L.DomUtil.create('div','legend');
        return this._div;
    }};
    legend.update = function(param){{
        var html = '';
        if(param==='oidio'){{
            html = '<div style="margin-bottom:5px;font-size:0.85rem;">🍇 Riesgo Oídio</div>';
            for(var i=3;i>=0;i--){{
                html+=`<div><i style="background:${{RIESGO_COLORS[i]}}"></i>${{RIESGO_LABELS[i]}}</div>`;
            }}
            html+='<hr style="margin:5px 0;border:0;border-top:1px solid #ddd;">';
            html+='<div style="font-size:0.65rem;color:#555;">Modelo: Gubler-Thomas (UC Davis)<br>Temp + días cálidos + HR</div>';
        }} else if(param==='mildiu'){{
            html = '<div style="margin-bottom:5px;font-size:0.85rem;">🍃 Riesgo Mildiu</div>';
            for(var i=3;i>=0;i--){{
                html+=`<div><i style="background:${{RIESGO_COLORS[i]}}"></i>${{RIESGO_LABELS[i]}}</div>`;
            }}
            html+='<hr style="margin:5px 0;border:0;border-top:1px solid #ddd;">';
            html+='<div style="font-size:0.65rem;color:#555;">Modelo: Regla 10-10-10 + EPI<br>Tmin + lluvia 10d + HR</div>';
        }} else {{
            var grades, title, unit;
            if(param==='precip')  {{ title='Precipitación'; unit='mm'; grades=[0.5,2,4,10,20,30,40,50,70]; }}
            else if(param==='temp'){{ title='Temperatura';   unit='°C'; grades=[5,10,15,20,25,30,35,40]; }}
            else if(param==='humidity'){{ title='Humedad'; unit='%'; grades=[30,50,70,90]; }}
            else if(param==='wind'){{ title='Rachas'; unit='km/h'; grades=[2,5,10,20,30,40]; }}
            html=`<div style="margin-bottom:5px;font-size:0.85rem;">${{title}}<br><span style="font-size:0.7rem;color:#666">${{unit}}</span></div>`;
            html+=`<div><i style="background:${{getColor(grades[grades.length-1],param)}}"></i> >${{grades[grades.length-1]}}</div>`;
            for(var i=grades.length-2;i>=0;i--){{
                html+=`<div><i style="background:${{getColor(grades[i],param)}}"></i>${{grades[i]}}-${{grades[i+1]}}</div>`;
            }}
        }}
        this._div.innerHTML = html;
    }};
    legend.addTo(map);

    // ── Formato etiqueta de tiempo ───────────────────────────────
    function formatTimeLabel(iso){{
        var d = new Date(iso);
        var hoy = new Date();
        var esHoy = d.getDate()===hoy.getDate() && d.getMonth()===hoy.getMonth();
        var t = d.toLocaleTimeString('es-ES',{{hour:'2-digit',minute:'2-digit'}});
        return (esHoy?'Hoy':'Ayer')+', '+t;
    }}

    // ── Actualizar mapa ──────────────────────────────────────────
    function actualizarMapa(){{
        try{{
            var param = document.getElementById('param-select').value;
            legend.update(param);
            heatmapLayerGroup.clearLayers();
            markersLayer.clearLayers();

            var isRiesgo = (param==='oidio'||param==='mildiu');

            // Para riesgo usamos siempre el snapshot más reciente
            var currentData = isRiesgo
                ? historyData[historyData.length-1].stations
                : historyData[currentTimestampIndex].stations;

            var features = [], bounds = [];

            currentData.forEach(function(est){{
                if(!est||!est.lat||!est.lon) return;
                var val = getRawValue(est, param);
                if(val===null||val===undefined) return;

                var textVal, bgColor;
                bgColor = getColor(val, param);

                if(isRiesgo){{
                    textVal = RIESGO_LABELS[Math.round(val)].split(' ')[1]||'—';
                }} else if(param==='precip'){{
                    textVal = val.toFixed(1);
                }} else if(param==='temp'){{
                    textVal = Math.round(val)+'°';
                }} else {{
                    textVal = Math.round(val).toString();
                }}

                // Flecha de viento
                var windHtml = '';
                if(param==='wind' && est.winddir!=null){{
                    windHtml = `<svg style="position:absolute;top:-13px;left:-13px;width:50px;height:50px;transform:rotate(${{est.winddir}}deg);z-index:-1;pointer-events:none;" viewBox="0 0 50 50"><line x1="25" y1="2" x2="25" y2="13" stroke="black" stroke-width="2.5"/></svg>`;
                }}

                var markerHtml = `<div style="position:relative;">
                    <div style="background-color:${{bgColor}};color:white;text-shadow:1px 1px 2px rgba(0,0,0,0.8);border:1px solid white;border-radius:50%;width:24px;height:24px;display:flex;justify-content:center;align-items:center;font-weight:bold;font-size:10px;box-shadow:0 2px 4px rgba(0,0,0,0.4);">${{textVal}}</div>
                    ${{windHtml}}</div>`;

                var marker = L.marker([est.lat,est.lon], {{
                    icon: L.divIcon({{className:'station-badge',html:markerHtml,iconSize:[24,24],iconAnchor:[12,12]}})
                }});

                var nombre = nombresPersonalizados[est.stationID]
                    || (est.neighborhood&&est.neighborhood.trim()!==''?est.neighborhood:est.stationID);
                var linkUrl = 'https://www.wunderground.com/dashboard/pws/'+est.stationID;

                // Popup enriquecido para riesgo
                var popupHtml;
                if(isRiesgo){{
                    var r = riesgoData[est.stationID];
                    if(r){{
                        var nivO = r.oidio, nivM = r.mildiu;
                        var det = r.detalles||{{}};
                        var detO = (r.detalles&&r.detalles.oidio)?r.detalles.oidio.join('<br>• '):'';
                        var detM = (r.detalles&&r.detalles.mildiu)?r.detalles.mildiu.join('<br>• '):'';
                        popupHtml = `<div style="text-align:left;min-width:200px;font-size:0.85rem;">
                            <strong style="font-size:1rem;color:#2c3e50;">${{nombre}}</strong><hr style="margin:5px 0;">
                            <b>🍇 Oídio:</b> <span class="riesgo-badge r${{nivO}}">${{RIESGO_LABELS[nivO]}}</span><br>
                            <span style="color:#666;font-size:0.75rem">• ${{detO||'Sin datos suficientes'}}</span><br><br>
                            <b>🍃 Mildiu:</b> <span class="riesgo-badge r${{nivM}}">${{RIESGO_LABELS[nivM]}}</span><br>
                            <span style="color:#666;font-size:0.75rem">• ${{detM||'Sin datos suficientes'}}</span><br><br>
                            <span style="font-size:0.75rem;color:#888;">T=${{det.temp_actual!=null?det.temp_actual.toFixed(1)+'°C':'—'}} | HR=${{det.hum_actual!=null?det.hum_actual+'%':'—'}}<br>
                            Lluvia 10d=${{det.precip_10dias}}mm | HR alta=${{det.horas_hum_alta_7d}}h (7d)</span>
                        </div>`;
                    }} else {{
                        popupHtml = `<div style="text-align:center;"><strong>${{nombre}}</strong><br>Sin datos de riesgo</div>`;
                    }}
                }} else {{
                    popupHtml = `<div style="text-align:center;">
                        <strong style="font-size:1.1rem;color:#2c3e50;">${{nombre}}</strong><br>
                        <hr style="margin:5px 0;border:0;border-top:1px solid #eee;">
                        <span style="font-size:1.2rem;font-weight:bold;">${{textVal}}</span><br>
                        <a href="${{linkUrl}}" target="_blank" style="display:inline-block;margin-top:8px;padding:4px 10px;background:#3498db;color:white;text-decoration:none;border-radius:5px;font-size:0.8rem;">Ver historial</a>
                    </div>`;
                }}

                marker.bindPopup(popupHtml);
                marker.bindTooltip(`<strong>${{nombre}}</strong>`,{{direction:'top',offset:[0,-10],opacity:0.9}});
                markersLayer.addLayer(marker);

                // Para interpolación (solo en parámetros numéricos continuos, no riesgo)
                if(!isRiesgo){{
                    features.push(turf.point([est.lon,est.lat],{{value:val}}));
                    bounds.push([est.lat,est.lon]);
                }}
            }});

            // Heatmap interpolado (solo para variables continuas)
            if(!isRiesgo && features.length>2){{
                var collection = turf.featureCollection(features);
                var grid = turf.interpolate(collection, 2.5, {{
                    gridType:'square', property:'value', units:'kilometers',
                    weight: param==='temp'?2:4
                }});
                var finalGrid = turf.featureCollection(
                    grid.features.filter(f=>f.properties.value!==null&&!isNaN(f.properties.value))
                );
                heatmapLayer = L.geoJSON(finalGrid, {{
                    pane:'heatmapPane',
                    style: function(f){{
                        return {{fillColor:getColor(f.properties.value,param),
                                fillOpacity:window.globalHeatmapOpacity, stroke:false}};
                    }}
                }});
                heatmapLayerGroup.addLayer(heatmapLayer);
            }}

        }} catch(e) {{ console.error('Error actualizarMapa:', e); }}
    }}

    // ── Slider máquina del tiempo ────────────────────────────────
    // FIX: aseguramos que slider.max se actualiza correctamente
    var slider = document.getElementById('time-slider');
    if(historyData.length>0){{
        slider.max   = (historyData.length-1).toString();
        slider.value = (historyData.length-1).toString();
        document.getElementById('time-label').innerText =
            formatTimeLabel(historyData[historyData.length-1].timestamp)+' (Actual)';
        actualizarMapa();
    }}

    slider.addEventListener('input', function(e){{
        currentTimestampIndex = parseInt(e.target.value);
        var isLatest = currentTimestampIndex===historyData.length-1;
        document.getElementById('time-label').innerText =
            formatTimeLabel(historyData[currentTimestampIndex].timestamp)+
            (isLatest?' (Actual)':' (Histórico)');
        actualizarMapa();
    }});

    var playInterval = null;
    document.getElementById('play-btn').addEventListener('click', function(){{
        if(playInterval){{
            clearInterval(playInterval); playInterval=null;
            this.innerText='▶️'; this.title='Reproducir';
        }} else {{
            this.innerText='⏸️'; this.title='Pausar';
            if(currentTimestampIndex>=historyData.length-1) currentTimestampIndex=0;
            playInterval = setInterval(function(){{
                currentTimestampIndex=(currentTimestampIndex+1)%historyData.length;
                slider.value=currentTimestampIndex;
                slider.dispatchEvent(new Event('input'));
            }}, 1500);
        }}
    }});

    document.getElementById('opacity-slider').addEventListener('input', function(e){{
        window.globalHeatmapOpacity = parseFloat(e.target.value);
        if(heatmapLayer) heatmapLayer.setStyle({{fillOpacity:window.globalHeatmapOpacity}});
    }});

    </script>
</body>
</html>"""

    directorio_publico = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'public')
    os.makedirs(directorio_publico, exist_ok=True)
    ruta = os.path.join(directorio_publico, 'index.html')
    with open(ruta, 'w', encoding='utf-8') as f:
        f.write(html_content)
    return ruta

# ─────────────────────────────────────────────
# PRINCIPAL
# ─────────────────────────────────────────────
def principal():
    try:
        from zoneinfo import ZoneInfo
        ahora = datetime.now(ZoneInfo("Europe/Madrid"))
    except ImportError:
        ahora = datetime.now()

    print(f"\n🚀 Obteniendo datos de {len(ESTACIONES)} estaciones...")
    datos_completos = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=25) as executor:
        resultados = list(executor.map(obtener_datos_estacion, ESTACIONES))
        for datos in resultados:
            if datos:
                datos_completos.append(datos)

    print(f"✅ {len(datos_completos)}/{len(ESTACIONES)} estaciones con datos.")

    if not datos_completos:
        print("❌ No se han podido cargar datos. Comprueba la conexión y la API key.")
        return

    print("📚 Actualizando historial 24h...")
    historial = gestionar_historial(datos_completos, ahora)

    print("🌾 Actualizando historial agrícola 14 días...")
    historial_agri = gestionar_historial_agricola(datos_completos, ahora)

    print("🔬 Calculando riesgo Oídio / Mildiu...")
    riesgo = calcular_riesgo_agricola(historial_agri, datos_completos)

    # Mostrar resumen de riesgo
    niveles = ['Sin riesgo','Bajo','Medio','ALTO']
    for sid, r in riesgo.items():
        nombre = sid
        print(f"  {nombre}: Oídio={niveles[r['oidio']]} | Mildiu={niveles[r['mildiu']]}")

    print("🗺  Generando HTML...")
    ruta_html = generar_html(historial, riesgo, ahora)
    print(f"✅ Listo → {ruta_html}")
    webbrowser.open('file://'+ruta_html)

if __name__ == "__main__":
    principal()
