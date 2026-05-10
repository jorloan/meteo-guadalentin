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

API_KEY = "e1f10a1e78da46f5b10a1e78da96f525"

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

def gestionar_historial(nuevos_datos_estaciones):
    url_historico = "https://jorloan.github.io/meteo-guadalentin/history_24h.json"
    historial = []
    
    try:
        req = urllib.request.Request(url_historico, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=ctx, timeout=5) as response:
            if response.getcode() == 200:
                historial = json.loads(response.read().decode('utf-8'))
                print(f"✅ Historial descargado. Contenía {len(historial)} registros.")
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
    
    directorio_publico = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'public')
    os.makedirs(directorio_publico, exist_ok=True)
    with open(os.path.join(directorio_publico, 'history_24h.json'), 'w', encoding='utf-8') as f:
        json.dump(historial_limpio, f, ensure_ascii=False)
        
    return historial_limpio, ahora

def generar_html(historial_data, ahora):
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
            
            .legend {{ background: rgba(255,255,255,0.95); padding: 8px 12px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.2); font-size: 0.8rem; font-weight: bold; line-height: 1.5; color: #333; max-height: 50vh; overflow-y: auto; }}
            .legend i {{ width: 18px; height: 14px; float: left; margin-right: 8px; opacity: 0.7; border: 1px solid rgba(0,0,0,0.1); }}
            
            .station-label {{ background: transparent; border: none; box-shadow: none; font-size: 11px; font-weight: bold; color: black; text-shadow: 1px 1px 2px white, -1px -1px 2px white; text-align: center; }}
            
            #loading {{ display: none; position: absolute; top: 0; left: 0; right: 0; bottom: 0; background: rgba(255,255,255,0.7); z-index: 2000; justify-content: center; align-items: center; font-size: 1.5rem; font-weight: bold; color: #2c3e50; flex-direction: column; }}
            
            @media (max-width: 600px) {{
                header {{ padding: 0.8rem 1rem; flex-direction: column; align-items: flex-start; gap: 10px; }}
                .controls {{ width: 100%; }}
                .controls select {{ width: 100%; padding: 10px; font-size: 1rem; }}
                .legend {{ font-size: 0.75rem; padding: 6px 8px; }}
                .legend i {{ width: 14px; height: 12px; }}
            }}
        </style>
    </head>
    <body>
        <header>
            <div class="header-left">
                <h1>Meteo Guadalentín</h1>
                <div class="subtitle">Actualizado: <span id="time-label">{fecha_actualizada}</span></div>
                <div style="font-size: 0.65rem; color: #95a5a6; margin-top: 5px; font-style: italic;">Por Jose Roque López Andreo</div>
            </div>
            <div class="controls">
                <div style="display:flex; flex-direction:column; align-items:center;">
                    <span style="font-size:0.75rem; color:#ecf0f1; font-weight:bold;">Máquina del Tiempo</span>
                    <div style="display:flex; align-items:center; gap:5px;">
                        <button id="play-btn" style="background:#3498db; color:white; border:none; border-radius:4px; cursor:pointer; font-size:0.8rem; padding:2px 8px;" title="Reproducir Animación">▶️</button>
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
            var currentTimestampIndex = historyData.length - 1;
            window.globalHeatmapOpacity = 0.35;

            var mapaClaro = L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{ attribution: '&copy; CARTO' }});
            var mapaOscuro = L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{ attribution: '&copy; CARTO' }});
            var satelite = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}', {{ attribution: '&copy; Esri' }});
            var terreno = L.tileLayer('https://{{s}}.tile.opentopomap.org/{{z}}/{{x}}/{{y}}.png', {{ attribution: '&copy; OpenTopoMap' }});
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
                zoom: 18,
                layers: [mapaClaro]
            }});

            map.createPane('heatmapPane');
            map.getPane('heatmapPane').style.zIndex = 390; 
            map.getPane('heatmapPane').style.filter = 'blur(15px)';

            var baseMaps = {{
                "Mapa Claro": mapaClaro,
                "Mapa Oscuro": mapaOscuro,
                "Google Maps": googleStreets,
                "Google Satélite": googleSatelite,
                "Satélite (Esri)": satelite,
                "Relieve": terreno,
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

                let html = `<div style="margin-bottom:8px;font-size:1.1rem">${{title}}<br><span style="font-size:0.8rem;color:#666">${{unit}}</span></div>`;
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
                                    
                                    var textVal = (param === 'temp') ? val.toFixed(1) + "°" : val.toString();
                                    var bgColor = getColor(val, param);
                                    
                                    var markerHtml = `<div style="
                                        background-color: ${{bgColor}};
                                        color: white;
                                        text-shadow: 1px 1px 2px rgba(0,0,0,0.8);
                                        border: 1px solid white;
                                        border-radius: 50%;
                                        width: 28px;
                                        height: 28px;
                                        display: flex;
                                        justify-content: center;
                                        align-items: center;
                                        font-weight: bold;
                                        font-size: 10px;
                                        box-shadow: 0 2px 4px rgba(0,0,0,0.4);
                                    ">${{textVal}}</div>`;

                                    var marker = L.marker([est.lat, est.lon], {{
                                        icon: L.divIcon({{
                                            className: 'station-badge',
                                            html: markerHtml,
                                            iconSize: [28, 28],
                                            iconAnchor: [14, 14]
                                        }})
                                    }});
                                    
                                    var nombrePersonalizado = nombresPersonalizados[est.stationID];
                                    var nombreEstacion = nombrePersonalizado ? nombrePersonalizado : (est.neighborhood ? est.neighborhood : "Estación de Totana");
                                    var wundergroundUrl = "https://www.wunderground.com/dashboard/pws/" + est.stationID;
                                    var popupHtml = `<div style="text-align:center;">
                                        <strong style="font-size:1.1rem; color:#2c3e50;">${{nombreEstacion}}</strong><br>
                                        <hr style="margin:5px 0; border:0; border-top:1px solid #eee;">
                                        <span style="font-size:1.2rem; font-weight:bold; display:block; margin-bottom:10px;">${{textVal}}</span>
                                        <a href="${{wundergroundUrl}}" target="_blank" style="display:inline-block; padding:5px 10px; background-color:#3498db; color:white; text-decoration:none; border-radius:5px; font-size:0.85rem; font-weight:bold;">Ver historial completo</a>
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
                            
                            map.setView([37.76, -1.53], 10);
                        }}
                }} catch (e) {{
                    console.error("Error dibujando el mapa de calor:", e);
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
    directorio_publico = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'public')
    if not os.path.exists(directorio_publico):
        os.makedirs(directorio_publico)
        
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
                
    print(f"✅ Descarga completada. Se han cargado datos de {len(datos_completos)} estaciones.")
    if datos_completos:
        historial, ahora = gestionar_historial(datos_completos)
        ruta_html = generar_html(historial, ahora)
        print("Mapa y Máquina del Tiempo generados correctamente.")
    else:
        print("No se han podido cargar datos.")

if __name__ == "__main__":
    principal()
