import urllib.request
import json
import ssl
import os
import webbrowser
from datetime import datetime
import concurrent.futures

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

API_KEY = "e1f10a1e78da46f5b10a1e78da96f525"

# Archivo donde guardaremos las estaciones para que sea fácil editarlas
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
        # Ignoramos lo que haya después de un '#' (comentarios) y los espacios en blanco
        linea_limpia = linea.split('#')[0].strip()
        if linea_limpia:
            ESTACIONES.append(linea_limpia)

def obtener_datos_estacion(station_id):
    url = f"https://api.weather.com/v2/pws/observations/current?stationId={station_id}&format=json&units=m&apiKey={API_KEY}"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=ctx) as response:
            if response.getcode() == 200:
                data = json.loads(response.read().decode())
                return data['observations'][0]
    except Exception as e:
        print(f"Error al obtener datos de {station_id}: {e}")
    return None

def generar_html(datos_estaciones):
    try:
        from zoneinfo import ZoneInfo
        ahora = datetime.now(ZoneInfo("Europe/Madrid"))
    except ImportError:
        ahora = datetime.now()
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
            header {{ background-color: #1a252f; color: white; padding: 1rem 2rem; display: flex; justify-content: space-between; align-items: center; z-index: 10; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
            .header-left h1 {{ margin: 0; font-size: 1.5rem; font-weight: 600; }}
            .subtitle {{ font-size: 0.85rem; color: #bdc3c7; margin-top: 4px; }}
            .controls {{ display: flex; gap: 15px; align-items: center; }}
            .controls label {{ font-weight: bold; font-size: 0.9rem; color: #ecf0f1; }}
            .controls select {{ padding: 8px 15px; border-radius: 6px; border: none; background: #ecf0f1; color: #2c3e50; font-weight: bold; font-size: 1rem; outline: none; cursor: pointer; box-shadow: 0 2px 4px rgba(0,0,0,0.2); }}
            
            .container {{ display: flex; flex: 1; overflow: hidden; position: relative; }}
            #map {{ flex: 1; height: 100%; }}
            
            .legend {{ background: rgba(255,255,255,0.95); padding: 8px 12px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.2); font-size: 0.8rem; font-weight: bold; line-height: 1.5; color: #333; max-height: 50vh; overflow-y: auto; }}
            .legend i {{ width: 18px; height: 14px; float: left; margin-right: 8px; opacity: 0.7; border: 1px solid rgba(0,0,0,0.1); }}
            
            .station-label {{ background: transparent; border: none; box-shadow: none; font-size: 11px; font-weight: bold; color: black; text-shadow: 1px 1px 2px white, -1px -1px 2px white; text-align: center; }}
            
            #loading {{ display: none; position: absolute; top: 0; left: 0; right: 0; bottom: 0; background: rgba(255,255,255,0.7); z-index: 2000; justify-content: center; align-items: center; font-size: 1.5rem; font-weight: bold; color: #2c3e50; }}
            
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
                <div class="subtitle">Actualizado: {fecha_actualizada}</div>
                <div style="font-size: 0.65rem; color: #95a5a6; margin-top: 5px; font-style: italic;">Por Jose Roque López Andreo</div>
            </div>
            <div class="controls">
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
            <div id="loading">Calculando mapa de calor...</div>
        </div>

        <script>
            var mapaClaro = L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{ attribution: '&copy; CARTO' }});
            var mapaOscuro = L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{ attribution: '&copy; CARTO' }});
            var satelite = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}', {{ attribution: '&copy; Esri' }});
            var terreno = L.tileLayer('https://{{s}}.tile.opentopomap.org/{{z}}/{{x}}/{{y}}.png', {{ attribution: '&copy; OpenTopoMap' }});
            var estandar = L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{ attribution: '&copy; OpenStreetMap' }});

            var map = L.map('map', {{
                center: [37.76, -1.53],
                zoom: 18,
                layers: [mapaClaro]
            }});

            // Crear una capa especial para el mapa de calor difuminado
            map.createPane('heatmapPane');
            map.getPane('heatmapPane').style.zIndex = 390; // Por debajo de los marcadores
            map.getPane('heatmapPane').style.filter = 'blur(15px)'; // Efecto difuminado clave

            var baseMaps = {{
                "Mapa Claro": mapaClaro,
                "Mapa Oscuro": mapaOscuro,
                "Satélite": satelite,
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

            var overlayMaps = {{
                "Radar de Lluvia": radarLayer
            }};
            
            // Selector de mapas tipo icono
            L.control.layers(baseMaps, overlayMaps, {{position: 'topright', collapsed: true}}).addTo(map);

            // Control de Mi Ubicación
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

            var estaciones = {json.dumps(datos_estaciones)};
            var heatmapLayer = null;
            var markersLayer = L.featureGroup().addTo(map);
            
            function getColor(val, param) {{
                if (param === 'precip') {{
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
                }} else if (param === 'temp') {{
                    return val >= 40 ? '#4a0000' :
                           val >= 35 ? '#d32f2f' :
                           val >= 30 ? '#f4511e' :
                           val >= 25 ? '#fb8c00' :
                           val >= 20 ? '#fdd835' :
                           val >= 15 ? '#8bc34a' :
                           val >= 10 ? '#4caf50' :
                           val >= 5  ? '#039be5' : '#01579b';
                }} else if (param === 'humidity') {{
                    return val >= 90 ? '#0d47a1' :
                           val >= 70 ? '#1976d2' :
                           val >= 50 ? '#42a5f5' :
                           val >= 30 ? '#90caf9' : '#e3f2fd';
                }} else if (param === 'wind') {{
                    return val >= 40 ? '#b71c1c' : // Rojo
                           val >= 30 ? '#e65100' : // Naranja oscuro
                           val >= 20 ? '#f57f17' : // Naranja
                           val >= 10 ? '#fbc02d' : // Amarillo
                           val >= 5  ? '#81c784' : // Verde
                           val >= 2  ? '#b2dfdb' : 'transparent'; // Azul clarito
                }}
            }}

            function getRawValue(est, param) {{
                var m = est.metric;
                if (param === 'temp') return m.temp;
                if (param === 'humidity') return est.humidity;
                if (param === 'wind') return m.windGust || m.windSpeed;
                if (param === 'precip') return m.precipTotal;
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

            function actualizarMapa() {{
                document.getElementById('loading').style.display = 'flex';
                
                setTimeout(function() {{
                    try {{
                        var param = document.getElementById('param-select').value;
                        legend.update(param);
                        
                        if (heatmapLayer) map.removeLayer(heatmapLayer);
                        markersLayer.clearLayers();

                        var features = [];
                        var bounds = [];
                        var coordsUsadas = new Set(); // Para evitar puntos duplicados que cuelgan Turf

                        estaciones.forEach(function(est) {{
                            var val = getRawValue(est, param);
                            var coordStr = est.lat.toFixed(4) + "," + est.lon.toFixed(4);
                            
                            // Ignorar si hay estaciones superpuestas en las mismas coordenadas exactas
                            if(val !== null && val !== undefined && !coordsUsadas.has(coordStr)) {{
                                coordsUsadas.add(coordStr);
                                features.push(turf.point([est.lon, est.lat], {{value: val}}));
                                bounds.push([est.lat, est.lon]);
                                
                                var colorLetra = 'black';
                                if(param === 'precip' && val > 10) colorLetra = 'white';
                                if(param === 'temp' && (val > 35 || val < 10)) colorLetra = 'white';
                                
                                var textShadow = colorLetra === 'white' ? '1px 1px 2px black, -1px -1px 2px black' : '1px 1px 2px white, -1px -1px 2px white';

                                var textVal = (param === 'temp') ? val.toFixed(1) + "°" : val.toString();
                                var marker = L.marker([est.lat, est.lon], {{
                                    icon: L.divIcon({{
                                        className: 'station-label',
                                        html: `<div style="color:${{colorLetra}};text-shadow:${{textShadow}}">${{textVal}}</div>`,
                                        iconSize: [30, 15],
                                        iconAnchor: [15, 7]
                                    }})
                                }});
                                
                                var nombreEstacion = est.neighborhood ? est.neighborhood : est.stationID;
                                var wundergroundUrl = "https://www.wunderground.com/dashboard/pws/" + est.stationID;
                                var popupHtml = `<div style="text-align:center;">
                                    <strong style="font-size:1.1rem; color:#2c3e50;">${{nombreEstacion}}</strong><br>
                                    <span style="font-size:0.85rem; color:#7f8c8d;">ID: ${{est.stationID}}</span><br>
                                    <hr style="margin:5px 0; border:0; border-top:1px solid #eee;">
                                    <span style="font-size:1.2rem; font-weight:bold; display:block; margin-bottom:10px;">${{textVal}}</span>
                                    <a href="${{wundergroundUrl}}" target="_blank" style="display:inline-block; padding:5px 10px; background-color:#3498db; color:white; text-decoration:none; border-radius:5px; font-size:0.85rem; font-weight:bold;">Ver todos los datos</a>
                                </div>`;
                                marker.bindPopup(popupHtml);
                                marker.bindTooltip(nombreEstacion, {{ direction: 'top', offset: [0, -10] }});
                                markersLayer.addLayer(marker);
                            }}
                        }});

                        if (features.length > 2) {{
                            var points = turf.featureCollection(features);
                            // Usar cuadrados grandes sin bordes, con el blur se seguirán viendo totalmente difuminados
                            // pero evitamos que el navegador se congele al cubrir una zona tan inmensa
                            var options = {{ gridType: 'square', property: 'value', units: 'kilometers', weight: 2 }};
                            var finalGrid = turf.interpolate(points, 2.5, options);
                            
                            heatmapLayer = L.geoJSON(finalGrid, {{
                                pane: 'heatmapPane',
                                style: function(feature) {{
                                    var val = feature.properties.value;
                                    return {{
                                        fillColor: getColor(val, param),
                                        fillOpacity: 0.65, 
                                        stroke: false // Quitar el borde para que el difuminado sea perfecto
                                    }};
                                }}
                            }}).addTo(map);
                            
                            markersLayer.bringToFront();
                            
                            // Para predefinir un zoom concreto, desactivamos el fitBounds automático
                            // map.fitBounds(L.latLngBounds(bounds).pad(0.3));
                            
                            // Y usamos setView pasándole las coordenadas del centro (Totana) y el nivel de zoom (ej: 10 u 11)
                            map.setView([37.76, -1.53], 10);
                        }}
                    }} catch (e) {{
                        console.error("Error dibujando el mapa de calor:", e);
                    }} finally {{
                        document.getElementById('loading').style.display = 'none';
                    }}
                }}, 100);
            }}

            actualizarMapa();

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
        ruta_html = generar_html(datos_completos)
        url_local = f"file://{ruta_html}"
        webbrowser.open(url_local)
        print("Mapa generado y abierto en el navegador.")
    else:
        print("No se han podido cargar datos.")

if __name__ == "__main__":
    principal()
