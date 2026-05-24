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

API_KEY = os.environ.get('WUNDERGROUND_API_KEY', 'e1f10a1e78da46f5b10a1e78da96f525')

ARCHIVO_ESTACIONES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'estaciones.txt')

if not os.path.exists(ARCHIVO_ESTACIONES):
    with open(ARCHIVO_ESTACIONES, 'w', encoding='utf-8') as f:
        f.write("# Añade aquí los IDs de las estaciones, uno por línea.\n")
        f.write("# Por ejemplo, las de Alhama o Lorca.\n")
        for est in ["ITOTAN8", "ITOTAN2", "ITOTAN16", "ITOTAN5", "ITOTAN33", "ITOTAN43", "ITOTAN31", "ITOTAN42", "ITOTAN9", "ITOTAN41", "ITOTAN10", "ITOTAN17"]:
            f.write(f"{est}\n")

ESTACIONES = []
with open(ARCHIVO_ESTACIONES, 'r', encoding='utf-8') as f:
    for linea in f:
        linea_limpia = linea.split('#')[0].strip()
        if linea_limpia:
            ESTACIONES.append(linea_limpia)

def obtener_datos_estacion(station_id):
    url = f"https://api.weather.com/v2/pws/observations/current?stationId={station_id}&format=json&units=m&apiKey={API_KEY}"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=ctx, timeout=5) as response:
            if response.getcode() == 200:
                data = json.loads(response.read().decode('utf-8'))
                return data['observations'][0]
    except Exception as e:
        print(f"Error al obtener datos de {station_id}: {e}")
    return None



def gestionar_historial_agricola(nuevos_datos_estaciones, ahora):
    url_agricola = "https://jorloan.github.io/meteo-guadalentin/historial_agricola.json"
    historico_agricola = {}
    
    try:
        req = urllib.request.Request(url_agricola, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=ctx, timeout=5) as response:
            if response.getcode() == 200:
                historico_agricola = json.loads(response.read().decode('utf-8'))
                print("✅ Historial agrícola descargado.")
    except Exception as e:
        print("No se encontró historial agrícola previo. Se creará uno nuevo.")
        
    fecha_hoy = ahora.strftime('%Y-%m-%d')
    if fecha_hoy not in historico_agricola:
        historico_agricola[fecha_hoy] = {}
        
    for est in nuevos_datos_estaciones:
        if not est or "stationID" not in est: continue
        sid = est["stationID"]
        temp = est.get("metric", {}).get("temp")
        precip = est.get("metric", {}).get("precipTotal")
        hum = est.get("humidity")
        
        if sid not in historico_agricola[fecha_hoy]:
            historico_agricola[fecha_hoy][sid] = {
                "tempMax": temp if temp is not None else -99,
                "tempMin": temp if temp is not None else 99,
                "precipTotal": precip if precip is not None else 0.0,
                "humedadAltaMinutos": 0
            }
        else:
            datos_dia = historico_agricola[fecha_hoy][sid]
            if temp is not None:
                if temp > datos_dia.get("tempMax", -99): datos_dia["tempMax"] = temp
                if temp < datos_dia.get("tempMin", 99): datos_dia["tempMin"] = temp
            if precip is not None:
                if precip > datos_dia.get("precipTotal", 0): datos_dia["precipTotal"] = precip
                
        # Si la humedad es >= 85%, sumamos 15 minutos de riesgo por la actualización actual
        if hum is not None and hum >= 85:
            historico_agricola[fecha_hoy][sid]["humedadAltaMinutos"] = historico_agricola[fecha_hoy][sid].get("humedadAltaMinutos", 0) + 15
            
    # Mantener solo los últimos 14 días (Fase 1 completada)
    dias_ordenados = sorted(historico_agricola.keys())
    if len(dias_ordenados) > 14:
        for d in dias_ordenados[:-14]:
            del historico_agricola[d]
            
    directorio_publico = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(directorio_publico, 'historial_agricola.json'), 'w', encoding='utf-8') as f:
        json.dump(historico_agricola, f, ensure_ascii=False)
        
    return historico_agricola

def gestionar_historial(nuevos_datos_estaciones):
    url_historico = "https://jorloan.github.io/meteo-guadalentin/history_24h.json"
    historial = []
    
    try:
        req = urllib.request.Request(url_historico, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=ctx, timeout=5) as response:
            if response.getcode() == 200:
                historial = json.loads(response.read().decode('utf-8'))
                print(f"✅ Historial descargado. Contenía {len(historial)} registros.")
                
                # Reset automático: Si el historial descargado tiene estaciones de AEMET antiguas, lo borramos.
                if historial and any(not est.get('stationID', 'I').startswith('I') for est in historial[-1].get('stations', [])):
                    print("⚠️ Detectadas estaciones de AEMET antiguas en el historial. Borrando datos para empezar limpio...")
                    historial = []
    except Exception as e:
        print(f"No se pudo descargar historial previo (es normal si es la primera vez): {e}")
    
    try:
        from zoneinfo import ZoneInfo
        ahora = datetime.now(ZoneInfo("Europe/Madrid"))
    except ImportError:
        ahora = datetime.now()
        
    limite = ahora - timedelta(hours=24)
    historial_limpio = []
    for h in historial:
        try:
            t = datetime.fromisoformat(h['timestamp'])
            if t > limite:
                historial_limpio.append(h)
        except:
            pass
            
    historial_limpio.append({
        'timestamp': ahora.isoformat(),
        'stations': nuevos_datos_estaciones
    })
    
    directorio_publico = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(directorio_publico, 'history_24h.json'), 'w', encoding='utf-8') as f:
        json.dump(historial_limpio, f, ensure_ascii=False)
        
    return historial_limpio, ahora

def generar_json(datos_estaciones, ahora):
    """Genera data.json con datos actuales de todas las estaciones para la app L&A"""
    estaciones_json = []
    for est in datos_estaciones:
        m = est.get('metric', {})
        estaciones_json.append({
            "id":          est.get('stationID', ''),
            "nombre":      est.get('neighborhood', est.get('stationID', '')),
            "lat":         est.get('lat'),
            "lon":         est.get('lon'),
            "temp":        m.get('temp'),
            "tempMin":     m.get('tempLow'),
            "tempMax":     m.get('tempHigh'),
            "humedad":     est.get('humidity'),
            "lluvia":      m.get('precipTotal', 0),
            "lluviaHora":  m.get('precipRate', 0),
            "viento":      m.get('windSpeed'),
            "rachaViento": m.get('windGust'),
            "presion":     m.get('pressure'),
            "dewPoint":    m.get('dewpt'),
            "uv":          est.get('uv'),
            "solar":       est.get('solarRadiation'),
            "actualizado": ahora.strftime("%d/%m/%Y %H:%M:%S")
        })

    payload = {
        "actualizado": ahora.strftime("%d/%m/%Y %H:%M:%S"),
        "timestamp":   ahora.isoformat(),
        "estaciones":  estaciones_json
    }

    directorio_publico = os.path.dirname(os.path.abspath(__file__))
    ruta_json = os.path.join(directorio_publico, 'data.json')
    with open(ruta_json, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"✅ data.json generado con {len(estaciones_json)} estaciones")


def calcular_riesgo_agro(historial_agricola, historial_riesgo, historial_dsv, coordenadas):
    """
    Calcula riesgo de mildiu (modelo Goidanich, ventana 14 días) y oídio (DSV Gubler-Thomas)
    por estación. Retorna dict plano {station_id: {lat, lon, mildiu_nivel, mildiu_puntos,
    mildiu_dias, oidio_nivel, dsv_7d, dsv_temporada}}.
    """
    # Niveles de oídio desde historial_riesgo (fecha más reciente)
    oidio_por_estacion = {}
    if historial_riesgo:
        fecha_rec = sorted(historial_riesgo.keys())[-1]
        for sid, d in historial_riesgo[fecha_rec].items():
            if d.get('datos_ok'):
                oidio_por_estacion[sid] = {
                    'nivel': d.get('oidio', 1),
                    'dsv_7d': d.get('dsv_7d', 0),
                    'dsv_temporada': d.get('dsv_temporada', 0)
                }

    def nivel_oidio_desde_dsv(sid):
        dsv = historial_dsv.get(sid, {}).get('dsv_acumulado', 0)
        if dsv >= 60: return 3
        if dsv >= 20: return 2
        return 1

    # Datos diarios por estación (últimos 14 días de historial_agricola)
    fechas_ordenadas = sorted(historial_agricola.keys())[-14:]
    datos_por_estacion = {}
    for fecha in fechas_ordenadas:
        for sid, d in historial_agricola[fecha].items():
            if sid not in datos_por_estacion:
                datos_por_estacion[sid] = []
            datos_por_estacion[sid].append({
                'tempMax':          d.get('tempMax'),
                'tempMin':          d.get('tempMin'),
                'precipTotal':      d.get('precipTotal', 0) or 0,
                'humedadAltaMinutos': d.get('humedadAltaMinutos', 0) or 0
            })

    resultado = {}
    for sid, dias in datos_por_estacion.items():
        lat, lon = coordenadas.get(sid, (None, None))
        if not lat or not lon:
            continue

        # ── Modelo Goidanich para Plasmopara viticola (mildiu) ──────────
        # Día de infección: T 11-30°C + (lluvia ≥ 2mm o HR≥85% ≥ 2h)
        # Puntuación: óptimo térmico 18-22°C + bonus por lluvia intensa
        puntos_mildiu = 0
        dias_infeccion = 0

        for dia in dias:
            tmax = dia['tempMax']
            tmin = dia['tempMin']
            prec = dia['precipTotal']
            hum_h = dia['humedadAltaMinutos'] / 60.0

            if tmax is None or tmin is None:
                continue
            tmed = (tmax + tmin) / 2.0

            if tmed < 11 or tmed > 30:
                continue
            if prec < 2.0 and hum_h < 2.0:
                continue

            dias_infeccion += 1
            if 18 <= tmed <= 22:
                puntos = 3          # óptimo esporulación
            elif (14 <= tmed < 18) or (22 < tmed <= 25):
                puntos = 2
            else:
                puntos = 1

            if prec >= 10:
                puntos += 1         # infección primaria desde oosporas

            puntos_mildiu += puntos

        if puntos_mildiu >= 15:
            mildiu_nivel = 3
        elif puntos_mildiu >= 5:
            mildiu_nivel = 2
        else:
            mildiu_nivel = 1

        # ── Oídio desde historial_riesgo o fallback DSV ─────────────────
        if sid in oidio_por_estacion:
            oidio = oidio_por_estacion[sid]
        else:
            oidio = {
                'nivel':         nivel_oidio_desde_dsv(sid),
                'dsv_7d':        historial_dsv.get(sid, {}).get('dsv_wu_extra', 0),
                'dsv_temporada': historial_dsv.get(sid, {}).get('dsv_acumulado', 0)
            }

        resultado[sid] = {
            'lat':            lat,
            'lon':            lon,
            'mildiu_nivel':   mildiu_nivel,
            'mildiu_puntos':  puntos_mildiu,
            'mildiu_dias':    dias_infeccion,
            'oidio_nivel':    oidio['nivel'],
            'dsv_7d':         oidio['dsv_7d'],
            'dsv_temporada':  oidio['dsv_temporada']
        }

    print(f"✅ Riesgo agro calculado: {len(resultado)} estaciones "
          f"(mildiu Goidanich · oídio DSV Gubler-Thomas)")
    return resultado


def generar_html(historial_data, ahora, datos_agro=None):
    if datos_agro is None:
        datos_agro = {}
    fecha_actualizada = ahora.strftime("%d/%m/%Y %H:%M:%S")

    html_content = f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Meteo Guadalentín</title>
        
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/@turf/turf@6/turf.min.js"></script>
        
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 0; background-color: #f5f7fa; display: flex; flex-direction: column; height: 100vh; }}
            header {{ background-color: #1a252f; color: white; padding: 1rem 2rem; display: flex; justify-content: space-between; align-items: center; z-index: 10; box-shadow: 0 4px 6px rgba(0,0,0,0.1); flex-wrap: wrap; gap: 10px; }}
            .header-left h1 {{ margin: 0; font-size: 1.5rem; font-weight: 600; }}
            .subtitle {{ font-size: 0.85rem; color: #bdc3c7; margin-top: 4px; }}
            .controls {{ display: flex; gap: 15px; align-items: center; flex-wrap: wrap; }}
            .controls select {{ padding: 8px 15px; border-radius: 6px; border: none; background: #ecf0f1; color: #2c3e50; font-weight: bold; font-size: 1rem; outline: none; cursor: pointer; box-shadow: 0 2px 4px rgba(0,0,0,0.2); }}
            
            .container {{ display: flex; flex: 1; overflow: hidden; position: relative; }}
            #map {{ flex: 1; height: 100%; }}
            
            .legend {{ background: rgba(255,255,255,0.95); padding: 6px 10px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.2); font-size: 0.75rem; font-weight: bold; line-height: 1.4; color: #333; max-height: 50vh; overflow-y: auto; max-width: 110px; }}
            .legend i {{ width: 14px; height: 12px; float: left; margin-right: 6px; opacity: 0.7; border: 1px solid rgba(0,0,0,0.1); }}
            
            .station-label {{ background: transparent; border: none; box-shadow: none; font-size: 11px; font-weight: bold; color: black; text-shadow: 1px 1px 2px white, -1px -1px 2px white; text-align: center; }}
            .grayscale-map {{ filter: grayscale(100%) contrast(1.1) brightness(1.05); }}
            
            #loading {{ display: none; position: absolute; top: 0; left: 0; right: 0; bottom: 0; background: rgba(255,255,255,0.7); z-index: 2000; justify-content: center; align-items: center; font-size: 1.5rem; font-weight: bold; color: #2c3e50; flex-direction: column; }}
            
            @media (max-width: 600px) {{
                header {{ padding: 0.8rem 1rem; flex-direction: column; align-items: flex-start; gap: 10px; }}
                .controls {{ width: 100%; }}
                .controls select, #controles-agro select {{ width: 100%; padding: 10px; font-size: 1rem; }}
                .legend {{ font-size: 0.75rem; padding: 6px 8px; }}
                .legend i {{ width: 14px; height: 12px; }}
            }}
            .tab-btn {{ background: rgba(255,255,255,0.15); color: white; border: 1px solid rgba(255,255,255,0.3); border-radius: 6px; padding: 5px 12px; cursor: pointer; font-size: 0.8rem; font-weight: bold; transition: background 0.2s; }}
            .tab-btn.active {{ background: rgba(255,255,255,0.9); color: #1a252f; }}
            .tab-btn:hover:not(.active) {{ background: rgba(255,255,255,0.25); }}
        </style>
    </head>
    <body>
        <header>
            <div class="header-left">
                <h1>Meteo Guadalentín</h1>
                <div class="subtitle">Actualizado: <span id="time-label">{fecha_actualizada}</span></div>
                <div style="display:flex; gap:6px; margin-top:6px;">
                    <button class="tab-btn active" id="tab-meteo-btn" onclick="switchTab('meteo')">Meteorológico</button>
                    <button class="tab-btn" id="tab-agro-btn" onclick="switchTab('agro')">Agrometeorológico</button>
                </div>
            </div>
            <div class="controls">
                <div id="controles-meteo" style="display:flex; gap:15px; align-items:center; flex-wrap:wrap;">
                    <div style="display:flex; flex-direction:column; align-items:center;">
                        <span style="font-size:0.75rem; color:#ecf0f1; font-weight:bold;">Máquina del Tiempo</span>
                        <div style="display:flex; align-items:center; gap:5px;">
                            <button id="play-btn" style="background:transparent; color:white; border:none; border-radius:4px; cursor:pointer; font-size:1.1rem; padding:0 5px;" title="Reproducir Animación">▶️</button>
                            <input type="range" id="time-slider" min="0" max="0" value="0" style="width: 100px; cursor: pointer;" title="Desliza para ver el historial">
                        </div>
                    </div>
                    <div style="display:flex; flex-direction:column; align-items:center;">
                        <span style="font-size:0.75rem; color:#ecf0f1; font-weight:bold;">Transparencia</span>
                        <input type="range" id="opacity-slider" min="0" max="1" step="0.05" value="0.35" style="width: 80px; cursor: pointer;">
                    </div>
                    <select id="param-select" onchange="actualizarMapa()">
                        <option value="precip">Precipitación Acumulada (mm)</option>
                        <option value="temp" selected>Temperatura (°C)</option>
                        <option value="humidity">Humedad (%)</option>
                        <option value="wind">Rachas de Viento (km/h)</option>
                    </select>
                </div>
                <div id="controles-agro" style="display:none; gap:15px; align-items:center; flex-wrap:wrap;">
                    <select id="param-agro-select" onchange="actualizarMapaAgro()">
                        <option value="mildiu">Riesgo Mildiu (Goidanich)</option>
                        <option value="oidio">Riesgo Oídio (DSV)</option>
                        <option value="dsv_temporada">DSV Temporada</option>
                        <option value="dsv_7d">DSV Últimos 7 días</option>
                    </select>
                    <div style="font-size:0.75rem; color:#bdc3c7; line-height:1.3;">
                        Marcadores: <strong style="color:white;">Mil · Oid</strong><br>
                        B=Bajo · M=Medio · A=Alto
                    </div>
                </div>
            </div>
        </header>
        
        <div class="container">
            <div id="map"></div>
            <div id="loading">
                <div>Calculando mapa de calor...</div>
            </div>
        </div>

        <script>
            var nombresPersonalizados = {{
                "ITOTAN8": "Mirador - Lebor Alto",
                "ITOTAN2": "METEO UNDERWORLD",
                "ITOTAN16": "Mortí Bajo -  Camino Aleurrosas",
                "ITOTAN5": "Estación Meteorológica Tierno Galván",
                "ITOTAN33": "Huerto Hostench",
                "ITOTAN43": "Casa Totana",
                "ITOTAN31": "CAMPING - Lebor - Totana",
                "ITOTAN42": "Secanos",
                "ITOTAN9": "LA CANAL - Raiguero",
                "ITOTAN41": "Ecowitt WN1981",
                "ITOTAN10": "WS Rancho",
                "ITOTAN17": "La Barquilla"
            }};

            var historyData = {json.dumps(historial_data)};
            var datosAgro = {json.dumps(datos_agro)};
            var currentTimestampIndex = historyData.length - 1;
            var modoActivo = 'meteo';
            window.globalHeatmapOpacity = 0.35;

            var mapaClaro = L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{ attribution: '&copy; CARTO' }});
            var terreno = L.tileLayer('http://{{s}}.google.com/vt/lyrs=p&x={{x}}&y={{y}}&z={{z}}', {{
                maxZoom: 20,
                subdomains:['mt0','mt1','mt2','mt3'],
                attribution: '&copy; Google Terrain',
                className: 'grayscale-map'
            }});
            var estandar = L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{ attribution: '&copy; OpenStreetMap' }});
            
            var googleStreets = L.tileLayer('http://{{s}}.google.com/vt/lyrs=m&x={{x}}&y={{y}}&z={{z}}', {{
                maxZoom: 20,
                subdomains:['mt0','mt1','mt2','mt3'],
                attribution: '&copy; Google'
            }});
            var googleSatelite = L.tileLayer('http://{{s}}.google.com/vt/lyrs=s,h&x={{x}}&y={{y}}&z={{z}}', {{
                maxZoom: 20,
                subdomains:['mt0','mt1','mt2','mt3'],
                attribution: '&copy; Google'
            }});

            var map = L.map('map', {{
                center: [37.76, -1.53],
                zoom: 10,
                layers: [terreno]
            }});

            map.createPane('heatmapPane');
            map.getPane('heatmapPane').style.zIndex = 390; 
            map.getPane('heatmapPane').style.filter = 'blur(15px)';

            var baseMaps = {{
                "Relieve": terreno,
                "Mapa Claro": mapaClaro,
                "Google Maps": googleStreets,
                "Google Satélite": googleSatelite,
                "Estándar": estandar
            }};

            var radarLayer = L.layerGroup();
            fetch('https://api.rainviewer.com/public/weather-maps.json')
                .then(res => res.json())
                .then(data => {{
                    var lastPast = data.radar.past[data.radar.past.length - 1];
                    var radarUrl = data.host + lastPast.path + '/256/{{z}}/{{x}}/{{y}}/2/1_1.png';
                    var realRadarLayer = L.tileLayer(radarUrl, {{ opacity: 0.7, zIndex: 400, attribution: 'RainViewer', maxNativeZoom: 7, maxZoom: 18 }});
                    radarLayer.addLayer(realRadarLayer);
                }});

            var markersLayer = L.layerGroup();
            var heatmapLayerGroup = L.layerGroup();
            var heatmapLayer = null;

            var overlayMaps = {{
                "Radar de Lluvia": radarLayer,
                "Mapa de Calor": heatmapLayerGroup,
                "Etiquetas de Datos": markersLayer
            }};
            
            L.control.layers(baseMaps, overlayMaps, {{position: 'topright', collapsed: true}}).addTo(map);

            heatmapLayerGroup.addTo(map);
            markersLayer.addTo(map);

            var locateControl = L.control({{position: 'topleft'}});
            locateControl.onAdd = function (map) {{
                var div = L.DomUtil.create('div', 'leaflet-bar leaflet-control');
                div.innerHTML = '<a href="#" title="Mi Ubicación" style="font-size:20px; font-weight:normal; color:#2c3e50; background:white; display:flex; justify-content:center; align-items:center; text-decoration:none; width:30px; height:30px;">🎯</a>';
                div.onclick = function(e){{
                    e.preventDefault();
                    map.locate({{setView: true, maxZoom: 13}});
                }};
                return div;
            }};
            locateControl.addTo(map);

            var userMarker = null;
            map.on('locationfound', function(e){{
                if(userMarker) map.removeLayer(userMarker);
                userMarker = L.circleMarker(e.latlng, {{radius: 8, color: '#3498db', fillColor: '#3498db', fillOpacity: 0.8}}).addTo(map)
                 .bindPopup("Estás aquí").openPopup();
            }});
            map.on('locationerror', function(e){{
                alert("No se pudo obtener tu ubicación. Verifica los permisos de localización en tu navegador o dispositivo.");
            }});

            function interpolateColor(c1, c2, factor) {{
                var r = Math.round(c1[0] + factor * (c2[0] - c1[0]));
                var g = Math.round(c1[1] + factor * (c2[1] - c1[1]));
                var b = Math.round(c1[2] + factor * (c2[2] - c1[2]));
                return `rgb(${{r}}, ${{g}}, ${{b}})`;
            }}

            function getColor(val, param) {{
                if (param === 'temp') {{
                    var stops = [
                        {{v: -5, c: [148, 0, 211]}},   // Violeta
                        {{v: 0,  c: [0, 0, 200]}},     // Azul oscuro
                        {{v: 5,  c: [0, 115, 255]}},   // Azul
                        {{v: 10, c: [0, 200, 200]}},   // Cian
                        {{v: 15, c: [50, 205, 50]}},   // Verde Lima
                        {{v: 20, c: [255, 255, 0]}},   // Amarillo
                        {{v: 25, c: [255, 140, 0]}},   // Naranja oscuro
                        {{v: 30, c: [220, 20, 60]}},   // Rojo Carmesí
                        {{v: 35, c: [139, 0, 0]}},     // Rojo oscuro
                        {{v: 40, c: [200, 0, 200]}}    // Magenta
                    ];
                    if (val <= stops[0].v) return `rgb(${{stops[0].c.join(',')}})`;
                    if (val >= stops[stops.length-1].v) return `rgb(${{stops[stops.length-1].c.join(',')}})`;
                    
                    for (var i = 0; i < stops.length - 1; i++) {{
                        if (val >= stops[i].v && val <= stops[i+1].v) {{
                            var factor = (val - stops[i].v) / (stops[i+1].v - stops[i].v);
                            return interpolateColor(stops[i].c, stops[i+1].c, factor);
                        }}
                    }}

                }} else if (param === 'precip') {{
                    return val >= 70 ? '#ff0000' :
                           val >= 50 ? '#ff99ff' :
                           val >= 40 ? '#cc66ff' :
                           val >= 30 ? '#993399' :
                           val >= 20 ? '#660099' :
                           val >= 10 ? '#0000ff' :
                           val >= 4  ? '#3366ff' :
                           val >= 2  ? '#00ccff' :
                           val >= 0.5 ? '#99ffff':
                           val >  0   ? '#e6ffff': 'transparent';
                }} else if (param === 'humidity') {{
                    return val >= 90 ? '#0d47a1' :
                           val >= 70 ? '#1976d2' :
                           val >= 50 ? '#42a5f5' :
                           val >= 30 ? '#90caf9' : '#e3f2fd';
                }} else if (param === 'wind') {{
                    return val >= 40 ? '#b71c1c' : 
                           val >= 30 ? '#e65100' : 
                           val >= 20 ? '#f57f17' : 
                           val >= 10 ? '#fbc02d' : 
                           val >= 5  ? '#81c784' : 
                           val >= 2  ? '#b2dfdb' : 'transparent';
                }}
            }}

            function getRawValue(est, param) {{
                var m = est.metric;
                if (!m) return null;
                if (param === 'precip') return m.precipTotal;
                if (param === 'temp') return m.temp;
                if (param === 'humidity') return est.humidity;
                if (param === 'wind') return m.windGust;
                return null;
            }}

            var legend = L.control({{position: 'bottomleft'}});
            legend.onAdd = function (map) {{
                this._div = L.DomUtil.create('div', 'legend');
                return this._div;
            }};
            legend.update = function (param) {{
                var grades, title, unit;
                if (param === 'precip') {{
                    title = 'Precipitación'; unit = 'L/m² o mm'; grades = [0.5, 2, 4, 10, 20, 30, 40, 50, 70];
                }} else if (param === 'temp') {{
                    title = 'Temperatura'; unit = '°C'; grades = [5, 10, 15, 20, 25, 30, 35, 40];
                }} else if (param === 'humidity') {{
                    title = 'Humedad'; unit = '%'; grades = [30, 50, 70, 90];
                }} else if (param === 'wind') {{
                    title = 'Rachas Viento'; unit = 'km/h'; grades = [2, 5, 10, 20, 30, 40];
                }}

                let html = `<div style="margin-bottom:6px;font-size:0.85rem;line-height:1.1;">${{title}}<br><span style="font-size:0.7rem;color:#666">${{unit}}</span></div>`;
                html += `<div><i style="background:${{getColor(grades[grades.length-1], param)}}"></i> > ${{grades[grades.length-1]}}</div>`;
                for (var i = grades.length - 2; i >= 0; i--) {{
                    html += `<div><i style="background:${{getColor(grades[i], param)}}"></i> ${{grades[i]}} - ${{grades[i+1]}}</div>`;
                }}
                if (param === 'precip') {{
                    html += `<div><i style="background:transparent; border:1px solid #ccc;"></i> 0</div>`;
                }}
                this._div.innerHTML = html;
            }};
            legend.addTo(map);

            var legendAgro = L.control({{position: 'bottomleft'}});
            legendAgro.onAdd = function(map) {{
                this._div = L.DomUtil.create('div', 'legend');
                this._div.style.display = 'none';
                return this._div;
            }};
            legendAgro.update = function(param) {{
                var html = '';
                if (param === 'mildiu') {{
                    html = `<div style="margin-bottom:5px;font-size:0.85rem;font-weight:bold;">Mildiu</div>
                        <div style="font-size:0.65rem;color:#555;margin-bottom:6px;line-height:1.3;">
                            Goidanich · 14 días<br>
                            T: 11–30°C<br>
                            + lluvia ≥ 2mm<br>
                            o HR≥85% ≥ 2h
                        </div>
                        <div><i style="background:#d32f2f"></i> Alto (&ge;15 pts)</div>
                        <div><i style="background:#f57c00"></i> Moderado (5–14)</div>
                        <div><i style="background:#388e3c"></i> Bajo (&lt;5 pts)</div>`;
                }} else if (param === 'oidio') {{
                    html = `<div style="margin-bottom:5px;font-size:0.85rem;font-weight:bold;">Oídio</div>
                        <div style="font-size:0.65rem;color:#555;margin-bottom:6px;line-height:1.3;">
                            DSV Gubler-Thomas<br>
                            T: 15–40°C<br>
                            + HR≥85% acumuladas
                        </div>
                        <div><i style="background:#d32f2f"></i> Alto (3)</div>
                        <div><i style="background:#f57c00"></i> Moderado (2)</div>
                        <div><i style="background:#388e3c"></i> Bajo (1)</div>`;
                }} else if (param === 'dsv_temporada') {{
                    html = `<div style="margin-bottom:5px;font-size:0.85rem;font-weight:bold;">DSV</div>
                        <div style="font-size:0.65rem;color:#555;margin-bottom:6px;">Temporada (desde 1-Mar)</div>
                        <div><i style="background:#b71c1c"></i> &gt; 100</div>
                        <div><i style="background:#e53935"></i> 60–100</div>
                        <div><i style="background:#fb8c00"></i> 40–60</div>
                        <div><i style="background:#fdd835"></i> 20–40</div>
                        <div><i style="background:#66bb6a"></i> 5–20</div>
                        <div><i style="background:#c8e6c9"></i> &lt; 5</div>`;
                }} else if (param === 'dsv_7d') {{
                    html = `<div style="margin-bottom:5px;font-size:0.85rem;font-weight:bold;">DSV</div>
                        <div style="font-size:0.65rem;color:#555;margin-bottom:6px;">Últimos 7 días</div>
                        <div><i style="background:#b71c1c"></i> &gt; 30</div>
                        <div><i style="background:#e53935"></i> 20–30</div>
                        <div><i style="background:#fb8c00"></i> 10–20</div>
                        <div><i style="background:#fdd835"></i> 5–10</div>
                        <div><i style="background:#66bb6a"></i> 1–5</div>
                        <div><i style="background:#c8e6c9"></i> 0</div>`;
                }}
                this._div.innerHTML = html;
            }};
            legendAgro.addTo(map);

            function formatTimeLabel(isoString) {{
                var d = new Date(isoString);
                var today = new Date();
                var isToday = (d.getDate() === today.getDate() && d.getMonth() === today.getMonth());
                var timePart = d.toLocaleTimeString('es-ES', {{hour: '2-digit', minute:'2-digit'}});
                if (isToday) {{
                    return "Hoy, " + timePart;
                }} else {{
                    return "Ayer, " + timePart;
                }}
            }}

            document.getElementById('time-slider').addEventListener('input', function(e) {{
                currentTimestampIndex = parseInt(e.target.value);
                
                var isLatest = (currentTimestampIndex === historyData.length - 1);
                if (isLatest) {{
                    document.getElementById('time-label').innerText = formatTimeLabel(historyData[currentTimestampIndex].timestamp) + " (Actual)";
                }} else {{
                    document.getElementById('time-label').innerText = formatTimeLabel(historyData[currentTimestampIndex].timestamp) + " (Histórico)";
                }}
                
                actualizarMapa();
            }});

            var playInterval = null;
            document.getElementById('play-btn').addEventListener('click', function() {{
                var btn = this;
                var slider = document.getElementById('time-slider');
                
                if (playInterval) {{
                    clearInterval(playInterval);
                    playInterval = null;
                    btn.innerText = "▶️";
                    btn.title = "Reproducir Animación";
                }} else {{
                    btn.innerText = "⏸️";
                    btn.title = "Pausar Animación";
                    
                    if (currentTimestampIndex >= historyData.length - 1) {{
                        currentTimestampIndex = 0; // Si está al final, vuelve al principio
                    }}
                    
                    playInterval = setInterval(function() {{
                        currentTimestampIndex++;
                        if (currentTimestampIndex >= historyData.length) {{
                            currentTimestampIndex = 0; // Bucle infinito
                        }}
                        slider.value = currentTimestampIndex;
                        slider.dispatchEvent(new Event('input')); 
                    }}, 1500); // 1.5 segundos por fotograma
                }}
            }});

            document.getElementById('opacity-slider').addEventListener('input', function(e) {{
                window.globalHeatmapOpacity = parseFloat(e.target.value);
                if (heatmapLayer) {{
                    heatmapLayer.setStyle({{fillOpacity: window.globalHeatmapOpacity}});
                }}
            }});

            function actualizarMapa() {{
                try {{
                    var param = document.getElementById('param-select').value;
                        legend.update(param);
                        
                        heatmapLayerGroup.clearLayers();
                        markersLayer.clearLayers();

                        var currentData = historyData[currentTimestampIndex].stations;
                        
                        var features = [];
                        var bounds = [];
                        
                        currentData.forEach(function(est) {{
                            if (est && est.lat && est.lon) {{
                                var val = getRawValue(est, param);
                                if (val !== null && val !== undefined) {{
                                    features.push(turf.point([est.lon, est.lat], {{value: val}}));
                                    bounds.push([est.lat, est.lon]);
                                    
                                    var textVal;
                                    if (param === 'precip') {{
                                        textVal = val.toFixed(1);
                                    }} else if (param === 'temp') {{
                                        textVal = Math.round(val).toString() + "°";
                                    }} else {{
                                        textVal = Math.round(val).toString();
                                    }}
                                    
                                    var windBarbHtml = "";
                                    if (param === 'wind' && est.winddir !== null && est.winddir !== undefined) {{
                                        windBarbHtml = `<svg style="position: absolute; top: -13px; left: -13px; width: 50px; height: 50px; transform: rotate(${{est.winddir}}deg); z-index: -1; pointer-events: none;" viewBox="0 0 50 50">
                                            <line x1="25" y1="2" x2="25" y2="13" stroke="black" stroke-width="2.5" />
                                        </svg>`;
                                    }}
                                    var bgColor = getColor(val, param);
                                    
                                    var markerHtml = `<div style="position: relative;">
                                        <div style="
                                            background-color: ${{bgColor}};
                                            color: white;
                                            text-shadow: 1px 1px 2px rgba(0,0,0,0.8);
                                            border: 1px solid white;
                                            border-radius: 50%;
                                            width: 24px;
                                            height: 24px;
                                            display: flex;
                                            justify-content: center;
                                            align-items: center;
                                            font-weight: bold;
                                            font-size: 11px;
                                            letter-spacing: -0.5px;
                                            box-shadow: 0 2px 4px rgba(0,0,0,0.4);
                                        ">${{textVal}}</div>
                                        ${{windBarbHtml}}
                                    </div>`;

                                    var marker = L.marker([est.lat, est.lon], {{
                                        icon: L.divIcon({{
                                            className: 'station-badge',
                                            html: markerHtml,
                                            iconSize: [24, 24],
                                            iconAnchor: [12, 12]
                                        }})
                                    }});
                                    
                                    var nombrePersonalizado = nombresPersonalizados[est.stationID];
                                    var nombreEstacion = nombrePersonalizado ? nombrePersonalizado : (est.neighborhood && est.neighborhood.trim() !== "" ? est.neighborhood : est.stationID);
                                    var isAemet = !est.stationID.startsWith('I');
                                    var linkUrl = isAemet ? "https://www.aemet.es/es/eltiempo/observacion/ultimosdatos" : "https://www.wunderground.com/dashboard/pws/" + est.stationID;
                                    var linkText = isAemet ? "Ver en AEMET" : "Ver historial completo";
                                    var linkColor = isAemet ? "#e67e22" : "#3498db";
                                    var popupHtml = `<div style="text-align:center;">
                                        <strong style="font-size:1.1rem; color:#2c3e50;">${{nombreEstacion}}</strong><br>
                                        <hr style="margin:5px 0; border:0; border-top:1px solid #eee;">
                                        <span style="font-size:1.2rem; font-weight:bold; display:block; margin-bottom:10px;">${{textVal}}</span>
                                        <a href="${{linkUrl}}" target="_blank" style="display:inline-block; padding:5px 10px; background-color:${{linkColor}}; color:white; text-decoration:none; border-radius:5px; font-size:0.85rem; font-weight:bold;">${{linkText}}</a>
                                    </div>`;
                                    marker.bindPopup(popupHtml);
                                    marker.bindTooltip(`<strong>${{nombreEstacion}}</strong>`, {{ direction: 'top', offset: [0, -10], opacity: 0.9 }});
                                    markersLayer.addLayer(marker);
                                }}
                            }}
                        }});
                        
                        if (features.length > 2) {{
                            var collection = turf.featureCollection(features);
                            var isTemp = (param === 'temp');
                            var gridOptions = {{
                                gridType: 'square',
                                property: 'value',
                                units: 'kilometers',
                                weight: isTemp ? 2 : 4
                            }};
                            
                            var cellSide = 2.5; 
                            var interpolatedGrid = turf.interpolate(collection, cellSide, gridOptions);
                            
                            var finalGrid = turf.featureCollection(
                                interpolatedGrid.features.filter(f => f.properties.value !== null && !isNaN(f.properties.value))
                            );
                            
                            heatmapLayer = L.geoJSON(finalGrid, {{
                                pane: 'heatmapPane',
                                style: function(feature) {{
                                    var val = feature.properties.value;
                                    return {{
                                        fillColor: getColor(val, param),
                                        fillOpacity: window.globalHeatmapOpacity, 
                                        stroke: false
                                    }};
                                }}
                            }});
                            heatmapLayerGroup.addLayer(heatmapLayer);
                        }}
                }} catch (e) {{
                    console.error("Error dibujando el mapa de calor:", e);
                }}
            }}

            function getColorRiesgo(val, param) {{
                if (param === 'mildiu' || param === 'oidio') {{
                    if (val >= 3) return '#d32f2f';
                    if (val >= 2) return '#f57c00';
                    if (val >= 1) return '#388e3c';
                    return '#9e9e9e';
                }} else if (param === 'dsv_temporada') {{
                    if (val >= 100) return '#b71c1c';
                    if (val >= 60)  return '#e53935';
                    if (val >= 40)  return '#fb8c00';
                    if (val >= 20)  return '#fdd835';
                    if (val >= 5)   return '#66bb6a';
                    return '#c8e6c9';
                }} else if (param === 'dsv_7d') {{
                    if (val >= 30) return '#b71c1c';
                    if (val >= 20) return '#e53935';
                    if (val >= 10) return '#fb8c00';
                    if (val >= 5)  return '#fdd835';
                    if (val >= 1)  return '#66bb6a';
                    return '#c8e6c9';
                }}
                return '#9e9e9e';
            }}

            function actualizarMapaAgro() {{
                try {{
                    var param = document.getElementById('param-agro-select').value;
                    heatmapLayerGroup.clearLayers();
                    markersLayer.clearLayers();

                    if (Object.keys(datosAgro).length === 0) return;

                    var esDual = (param === 'mildiu' || param === 'oidio');
                    var nivelTextoMap = {{1:'Bajo', 2:'Moderado', 3:'Alto'}};
                    var nivelLetraMap = {{1:'B', 2:'M', 3:'A'}};
                    var features = [];

                    Object.entries(datosAgro).forEach(function([estId, datos]) {{
                        if (!datos.lat || !datos.lon) return;

                        var markerHtml, iconSize, iconAnchor, val, bgColor;

                        if (esDual) {{
                            var nivelMil = datos.mildiu_nivel || 1;
                            var nivelOid = datos.oidio_nivel || 1;
                            bgColor = getColorRiesgo(param === 'mildiu' ? nivelMil : nivelOid, param);
                            val     = param === 'mildiu' ? nivelMil : nivelOid;

                            var lMil = nivelLetraMap[nivelMil] || '?';
                            var lOid = nivelLetraMap[nivelOid] || '?';

                            markerHtml = `<div style="background:${{bgColor}};color:white;text-shadow:1px 1px 1px rgba(0,0,0,0.7);border:2px solid white;border-radius:5px;width:38px;height:28px;display:flex;flex-direction:column;justify-content:center;align-items:center;font-weight:bold;font-size:9px;box-shadow:0 2px 5px rgba(0,0,0,0.4);line-height:1.35;">
                                <span>Mil: ${{lMil}}</span>
                                <span style="border-top:1px solid rgba(255,255,255,0.45);padding-top:1px;width:100%;text-align:center;">Oid: ${{lOid}}</span>
                            </div>`;
                            iconSize   = [38, 28];
                            iconAnchor = [19, 14];
                        }} else {{
                            val = param === 'dsv_temporada' ? datos.dsv_temporada : datos.dsv_7d;
                            if (val === null || val === undefined) return;
                            bgColor    = getColorRiesgo(val, param);
                            markerHtml = `<div style="background:${{bgColor}};color:white;text-shadow:1px 1px 2px rgba(0,0,0,0.8);border:1px solid white;border-radius:50%;width:24px;height:24px;display:flex;justify-content:center;align-items:center;font-weight:bold;font-size:11px;box-shadow:0 2px 4px rgba(0,0,0,0.4);">${{Math.round(val)}}</div>`;
                            iconSize   = [24, 24];
                            iconAnchor = [12, 12];
                        }}

                        var marker = L.marker([datos.lat, datos.lon], {{
                            icon: L.divIcon({{className:'station-badge', html:markerHtml, iconSize:iconSize, iconAnchor:iconAnchor}})
                        }});

                        var nombreEstacion = nombresPersonalizados[estId] || estId;
                        var colorMil = getColorRiesgo(datos.mildiu_nivel, 'mildiu');
                        var colorOid = getColorRiesgo(datos.oidio_nivel, 'oidio');

                        var popupHtml = `<div style="min-width:190px;">
                            <div style="text-align:center;padding-bottom:6px;">
                                <strong style="font-size:1rem;color:#2c3e50;">${{nombreEstacion}}</strong><br>
                                <small style="color:#7f8c8d;">${{estId}}</small>
                            </div>
                            <table style="width:100%;font-size:0.82rem;border-collapse:collapse;border-top:1px solid #eee;">
                                <tr style="background:#e8f5e9;">
                                    <td style="padding:5px 8px;font-weight:bold;">🍇 Mildiu</td>
                                    <td style="padding:5px 8px;font-weight:bold;color:${{colorMil}};">${{nivelTextoMap[datos.mildiu_nivel] || '-'}}</td>
                                </tr>
                                <tr>
                                    <td style="padding:3px 8px;font-size:0.72rem;color:#777;">Pts 14d / Días infec.</td>
                                    <td style="padding:3px 8px;font-size:0.72rem;">${{datos.mildiu_puntos}} / ${{datos.mildiu_dias}}</td>
                                </tr>
                                <tr style="background:#f3e5f5;border-top:1px solid #eee;">
                                    <td style="padding:5px 8px;font-weight:bold;">🌿 Oídio</td>
                                    <td style="padding:5px 8px;font-weight:bold;color:${{colorOid}};">${{nivelTextoMap[datos.oidio_nivel] || '-'}}</td>
                                </tr>
                                <tr>
                                    <td style="padding:3px 8px;font-size:0.72rem;color:#777;">DSV 7d / temporada</td>
                                    <td style="padding:3px 8px;font-size:0.72rem;">${{datos.dsv_7d}} / ${{datos.dsv_temporada}}</td>
                                </tr>
                            </table>
                        </div>`;

                        marker.bindPopup(popupHtml);
                        marker.bindTooltip(
                            `<strong>${{nombreEstacion}}</strong> · Mil: ${{nivelLetraMap[datos.mildiu_nivel]}} · Oid: ${{nivelLetraMap[datos.oidio_nivel]}}`,
                            {{direction:'top', offset:[0,-10], opacity:0.9}}
                        );
                        markersLayer.addLayer(marker);
                        features.push(turf.point([datos.lon, datos.lat], {{value: val}}));
                    }});

                    if (!esDual && features.length > 2) {{
                        var collection = turf.featureCollection(features);
                        var grid = turf.interpolate(collection, 2.5, {{gridType:'square', property:'value', units:'kilometers', weight:2}});
                        var finalGrid = turf.featureCollection(grid.features.filter(f => f.properties.value !== null && !isNaN(f.properties.value)));
                        heatmapLayer = L.geoJSON(finalGrid, {{
                            pane: 'heatmapPane',
                            style: function(feature) {{
                                return {{fillColor: getColorRiesgo(feature.properties.value, param), fillOpacity: window.globalHeatmapOpacity, stroke: false}};
                            }}
                        }});
                        heatmapLayerGroup.addLayer(heatmapLayer);
                    }}
                    legendAgro.update(param);
                }} catch(e) {{
                    console.error("Error en mapa agrometeorológico:", e);
                }}
            }}

            function switchTab(modo) {{
                modoActivo = modo;
                document.getElementById('tab-meteo-btn').classList.toggle('active', modo === 'meteo');
                document.getElementById('tab-agro-btn').classList.toggle('active', modo === 'agro');
                document.getElementById('controles-meteo').style.display = (modo === 'meteo') ? 'flex' : 'none';
                document.getElementById('controles-agro').style.display = (modo === 'agro') ? 'flex' : 'none';
                legend._div.style.display = (modo === 'meteo') ? '' : 'none';
                legendAgro._div.style.display = (modo === 'agro') ? '' : 'none';
                heatmapLayerGroup.clearLayers();
                markersLayer.clearLayers();
                if (modo === 'meteo') {{
                    actualizarMapa();
                }} else {{
                    actualizarMapaAgro();
                }}
            }}

            // Inicializar
            if (historyData.length > 0) {{
                document.getElementById('time-slider').max = historyData.length - 1;
                document.getElementById('time-slider').value = historyData.length - 1;
                document.getElementById('time-label').innerText = formatTimeLabel(historyData[currentTimestampIndex].timestamp) + " (Actual)";
                actualizarMapa();
            }}

        </script>
    </body>
    </html>
    """
    directorio_publico = os.path.dirname(os.path.abspath(__file__))
        
    ruta_archivo = os.path.join(directorio_publico, 'index.html')
    with open(ruta_archivo, 'w', encoding='utf-8') as f:
        f.write(html_content)
    return ruta_archivo

def principal():
    print(f"Obteniendo datos en tiempo real de {len(ESTACIONES)} estaciones (Multihilo)...")
    datos_completos = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=25) as executor:
        resultados = executor.map(obtener_datos_estacion, ESTACIONES)
        
        for estacion, datos in zip(ESTACIONES, resultados):
            if datos:
                datos_completos.append(datos)
                
                

                
    print(f"✅ Descarga completada. Se han cargado datos de {len(datos_completos)} estaciones en total.")
    if datos_completos:
        historial, ahora = gestionar_historial(datos_completos)
        historial_agri = gestionar_historial_agricola(datos_completos, ahora)
        generar_json(datos_completos, ahora)

        directorio = os.path.dirname(os.path.abspath(__file__))

        historial_riesgo = {}
        try:
            ruta = os.path.join(directorio, 'historial_riesgo.json')
            if os.path.exists(ruta):
                with open(ruta, 'r', encoding='utf-8') as f:
                    historial_riesgo = json.load(f)
                print(f"✅ historial_riesgo.json cargado ({len(historial_riesgo)} fechas).")
        except Exception as e:
            print(f"No se pudo cargar historial_riesgo.json: {e}")

        historial_dsv = {}
        try:
            ruta = os.path.join(directorio, 'historial_dsv.json')
            if os.path.exists(ruta):
                with open(ruta, 'r', encoding='utf-8') as f:
                    historial_dsv = json.load(f)
                print(f"✅ historial_dsv.json cargado ({len(historial_dsv)} estaciones).")
        except Exception as e:
            print(f"No se pudo cargar historial_dsv.json: {e}")

        # Coordenadas por estación: desde observaciones actuales + historial_riesgo
        coordenadas = {}
        for est in datos_completos:
            sid = est.get('stationID')
            if sid and est.get('lat') and est.get('lon'):
                coordenadas[sid] = (est['lat'], est['lon'])
        for fecha_datos in historial_riesgo.values():
            for sid, d in fecha_datos.items():
                if sid not in coordenadas and d.get('lat') and d.get('lon'):
                    coordenadas[sid] = (d['lat'], d['lon'])

        datos_agro = calcular_riesgo_agro(historial_agri, historial_riesgo, historial_dsv, coordenadas)
        ruta_html = generar_html(historial, ahora, datos_agro)
        print("Mapa, Máquina del Tiempo y Datos Agrícolas generados correctamente.")
    else:
        print("No se han podido cargar datos.")

if __name__ == "__main__":
    principal()
