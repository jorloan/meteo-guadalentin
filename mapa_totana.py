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
        
    limite = ahora - timedelta(hours=6)
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


def _goidanich(dias):
    """Puntuación Goidanich para una lista de días."""
    puntos = 0
    dias_inf = 0
    for dia in dias:
        tmax, tmin = dia['tempMax'], dia['tempMin']
        prec  = dia['precipTotal']
        hum_h = dia['humedadAltaMinutos'] / 60.0
        if tmax is None or tmin is None:
            continue
        tmed = (tmax + tmin) / 2.0
        if tmed < 11 or tmed > 30:
            continue
        if prec < 2.0 and hum_h < 2.0:
            continue
        dias_inf += 1
        if 18 <= tmed <= 22:
            p = 3
        elif (14 <= tmed < 18) or (22 < tmed <= 25):
            p = 2
        else:
            p = 1
        if prec >= 10:
            p += 1
        puntos += p
    nivel = 3 if puntos >= 15 else 2 if puntos >= 5 else 1
    return nivel, puntos, dias_inf


def calcular_historial_agro(historial_agricola, historial_riesgo, historial_dsv, coordenadas):
    """
    Calcula mildiu (Goidanich, ventana deslizante 14 días) y oídio (DSV) para cada
    fecha disponible en historial_agricola.
    Retorna {YYYY-MM-DD: {station_id: {lat, lon, mildiu_nivel, mildiu_puntos,
                                       mildiu_dias, oidio_nivel, dsv_7d, dsv_temporada}}}.
    """
    fechas_ord = sorted(historial_agricola.keys())
    resultado  = {}

    for i, fecha_actual in enumerate(fechas_ord):
        ventana = fechas_ord[max(0, i - 13): i + 1]   # hasta 14 días

        datos_por_estacion = {}
        for f in ventana:
            for sid, d in historial_agricola[f].items():
                datos_por_estacion.setdefault(sid, []).append({
                    'tempMax':            d.get('tempMax'),
                    'tempMin':            d.get('tempMin'),
                    'precipTotal':        d.get('precipTotal', 0) or 0,
                    'humedadAltaMinutos': d.get('humedadAltaMinutos', 0) or 0
                })

        oidio_fecha = historial_riesgo.get(fecha_actual, {})
        resultado_fecha = {}

        for sid, dias in datos_por_estacion.items():
            lat, lon = coordenadas.get(sid, (None, None))
            if not lat or not lon:
                continue

            mildiu_nivel, puntos, dias_inf = _goidanich(dias)

            oidio_d = oidio_fecha.get(sid, {})
            if oidio_d and oidio_d.get('datos_ok'):
                oidio_nivel  = oidio_d.get('oidio', 1)
                dsv_7d       = oidio_d.get('dsv_7d', 0)
                dsv_temp     = oidio_d.get('dsv_temporada', 0)
            else:
                dsv_acum    = historial_dsv.get(sid, {}).get('dsv_acumulado', 0)
                oidio_nivel = 3 if dsv_acum >= 60 else 2 if dsv_acum >= 20 else 1
                dsv_7d      = 0
                dsv_temp    = dsv_acum

            resultado_fecha[sid] = {
                'lat':           lat,   'lon':          lon,
                'mildiu_nivel':  mildiu_nivel,
                'mildiu_puntos': puntos, 'mildiu_dias': dias_inf,
                'oidio_nivel':   oidio_nivel,
                'dsv_7d':        dsv_7d, 'dsv_temporada': dsv_temp
            }

        if resultado_fecha:
            resultado[fecha_actual] = resultado_fecha

    n_est = round(sum(len(v) for v in resultado.values()) / len(resultado)) if resultado else 0
    print(f"✅ Historial agro: {len(resultado)} fechas · ~{n_est} estaciones/día "
          f"(Goidanich mildiu · DSV oídio)")
    return resultado


def generar_html(historial_data, ahora, historial_agro=None):
    if historial_agro is None:
        historial_agro = {}
    fecha_actualizada = ahora.strftime("%d/%m/%Y %H:%M:%S")

    html_content = f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Meteo Guadalentín</title>

        <script async src="https://www.googletagmanager.com/gtag/js?id=G-SP9MPQ1FFN"></script>
        <script>
          window.dataLayer = window.dataLayer || [];
          function gtag(){{dataLayer.push(arguments);}}
          gtag('js', new Date());
          gtag('config', 'G-SP9MPQ1FFN');
        </script>

        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/@turf/turf@6/turf.min.js"></script>
        
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 0; background-color: #0d1117; display: flex; flex-direction: column; height: 100vh; }}
            header {{ background-color: #161b22; color: #e6edf3; padding: 1rem 2rem; display: flex; justify-content: space-between; align-items: center; z-index: 10; box-shadow: 0 1px 0 #30363d; flex-wrap: wrap; gap: 10px; border-bottom: 1px solid #30363d; }}
            .header-left h1 {{ margin: 0; font-size: 1.5rem; font-weight: 600; color: #58a6ff; letter-spacing: 0.5px; }}
            .subtitle {{ font-size: 0.85rem; color: #8b949e; margin-top: 4px; }}
            .controls {{ display: flex; gap: 15px; align-items: center; flex-wrap: wrap; }}
            .controls select {{ padding: 8px 15px; border-radius: 6px; border: 1px solid #30363d; background: #21262d; color: #e6edf3; font-weight: bold; font-size: 1rem; outline: none; cursor: pointer; box-shadow: 0 2px 4px rgba(0,0,0,0.4); }}

            .container {{ display: flex; flex: 1; overflow: hidden; position: relative; }}
            #map {{ flex: 1; height: 100%; }}

            .legend {{ background: rgba(13,17,23,0.92); padding: 6px 10px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.5); font-size: 0.75rem; font-weight: bold; line-height: 1.4; color: #e6edf3; max-height: 50vh; overflow-y: auto; max-width: 110px; border: 1px solid #30363d; }}
            .legend i {{ width: 14px; height: 12px; float: left; margin-right: 6px; opacity: 0.85; border: 1px solid rgba(255,255,255,0.1); }}

            .station-label {{ background: transparent; border: none; box-shadow: none; font-size: 11px; font-weight: bold; color: #e6edf3; text-shadow: 1px 1px 3px #0d1117, -1px -1px 3px #0d1117; text-align: center; }}
            .grayscale-map {{ filter: grayscale(100%) contrast(1.1) brightness(1.05); }}

            #loading {{ display: none; position: absolute; top: 0; left: 0; right: 0; bottom: 0; background: rgba(13,17,23,0.8); z-index: 2000; justify-content: center; align-items: center; font-size: 1.5rem; font-weight: bold; color: #58a6ff; flex-direction: column; }}
            #mapa-tiempo-label {{ position: absolute; bottom: 36px; left: 50%; transform: translateX(-50%); background: rgba(13,17,23,0.72); color: #e6edf3; font-size: 3rem; font-weight: bold; padding: 10px 28px; border-radius: 14px; z-index: 1000; pointer-events: none; text-align: center; line-height: 1.2; text-shadow: 0 2px 8px rgba(0,0,0,0.9); display: none; backdrop-filter: blur(4px); border: 1px solid #30363d; }}

            @media (max-width: 600px) {{
                header {{ padding: 0.8rem 1rem; flex-direction: column; align-items: flex-start; gap: 10px; }}
                .controls {{ width: 100%; }}
                .controls select, #controles-agro select {{ width: 100%; padding: 10px; font-size: 1rem; }}
                .legend {{ font-size: 0.75rem; padding: 6px 8px; }}
                .legend i {{ width: 14px; height: 12px; }}
            }}
            .tab-btn {{ background: rgba(88,166,255,0.08); color: #8b949e; border: 1px solid #30363d; border-radius: 6px; padding: 5px 12px; cursor: pointer; font-size: 0.8rem; font-weight: bold; transition: all 0.2s; }}
            .tab-btn.active {{ background: #58a6ff; color: #0d1117; border-color: #58a6ff; }}
            .tab-btn:hover:not(.active) {{ background: rgba(88,166,255,0.15); color: #e6edf3; }}
            .btn-capa {{ border-radius: 6px; padding: 6px 16px; cursor: pointer; font-size: 0.85rem; font-weight: bold; border: 1px solid #30363d; color: #8b949e; opacity: 0.5; transition: opacity 0.2s, border-color 0.2s, color 0.2s; }}
            .btn-capa.activo {{ opacity: 1; border-color: #58a6ff; color: #e6edf3; }}
            .btn-filtro-agro {{ background: rgba(88,166,255,0.08); color: #8b949e; border: 1px solid #30363d; border-radius: 4px; padding: 3px 10px; cursor: pointer; font-size: 0.78rem; font-weight: bold; transition: all 0.2s; }}
            .btn-filtro-agro.activo {{ background: #58a6ff; color: #0d1117; border-color: #58a6ff; }}
            .btn-filtro-agro:hover:not(.activo) {{ background: rgba(88,166,255,0.18); color: #e6edf3; }}
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
                <div id="controles-agro" style="display:none; gap:10px; align-items:center; flex-wrap:wrap;">
                    <button id="btn-capa-mildiu" class="btn-capa activo" onclick="toggleCapa('mildiu')" style="background:#1565c0;">● Mildiu</button>
                    <button id="btn-capa-oidio"  class="btn-capa activo" onclick="toggleCapa('oidio')"  style="background:#e65100;">■ Oídio</button>
                    <div style="display:flex; flex-direction:column; align-items:center; gap:3px;">
                        <span style="font-size:0.72rem;color:#ecf0f1;font-weight:bold;">Máquina del Tiempo</span>
                        <div style="display:flex; gap:4px;">
                            <button id="filtro-7d"   class="btn-filtro-agro activo" onclick="setFiltroAgro(7)">7d</button>
                            <button id="filtro-15d"  class="btn-filtro-agro"        onclick="setFiltroAgro(15)">15d</button>
                            <button id="filtro-todo" class="btn-filtro-agro"        onclick="setFiltroAgro(0)">Todo</button>
                        </div>
                        <div style="display:flex; align-items:center; gap:5px;">
                            <button id="agro-play-btn" style="background:transparent;color:white;border:none;cursor:pointer;font-size:1.1rem;padding:0 5px;" onclick="toggleAgroPlay()" title="Reproducir">▶️</button>
                            <input type="range" id="agro-time-slider" min="0" max="0" value="0" style="width:100px;cursor:pointer;">
                            <span id="agro-date-label" style="font-size:0.78rem;color:#ecf0f1;min-width:90px;"></span>
                        </div>
                    </div>
                    <span style="font-size:0.7rem;color:#bdc3c7;line-height:1.4;">B=Bajo&nbsp; M=Mod&nbsp; A=Alto</span>
                </div>
            </div>
        </header>
        
        <div class="container">
            <div id="map"></div>
            <div id="mapa-tiempo-label"></div>
            <div id="info-agro-panel" style="display:none;position:absolute;bottom:90px;left:16px;z-index:1500;background:rgba(13,17,23,0.95);color:#e6edf3;border:1px solid #30363d;border-radius:10px;padding:14px 16px;max-width:260px;font-size:0.8rem;line-height:1.6;box-shadow:0 4px 20px rgba(0,0,0,0.6);backdrop-filter:blur(4px);">
                <button onclick="toggleInfoAgro(null)" style="position:absolute;top:8px;right:10px;background:none;border:none;color:#8b949e;font-size:1rem;cursor:pointer;">✕</button>
                <div id="info-agro-contenido"></div>
            </div>
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

            var historyData = (function(raw) {{
                var porHora = {{}};
                raw.forEach(function(e) {{
                    var d = new Date(e.timestamp);
                    var k = d.getFullYear()+'-'+d.getMonth()+'-'+d.getDate()+'-'+d.getHours();
                    porHora[k] = e;
                }});
                return Object.values(porHora).sort(function(a,b) {{
                    return new Date(a.timestamp)-new Date(b.timestamp);
                }});
            }})({json.dumps(historial_data)});
            var historialAgro = {json.dumps(historial_agro)};
            var currentTimestampIndex = historyData.length - 1;
            var modoActivo = 'meteo';
            window.globalHeatmapOpacity = 0.35;
            var capaMildiuActiva = true;
            var capaOidioActiva  = true;
            var capaMildiuGroup     = L.layerGroup();
            var capaOidioGroup      = L.layerGroup();
            var heatmapMildiuGroup  = L.layerGroup();
            var heatmapOidioGroup   = L.layerGroup();
            var historialAgroFechas = [];
            var filtroAgroDias      = 7;
            var agroSliderIndex     = 0;
            var agroPlayInterval    = null;

            var mapaOscuro = L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{ attribution: '&copy; CARTO Dark Matter' }});
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
            map.createPane('heatmapMildiuPane');
            map.getPane('heatmapMildiuPane').style.zIndex = 387;
            map.getPane('heatmapMildiuPane').style.filter = 'blur(18px)';
            map.createPane('heatmapOidioPane');
            map.getPane('heatmapOidioPane').style.zIndex = 388;
            map.getPane('heatmapOidioPane').style.filter = 'blur(18px)';

            var baseMaps = {{
                "Oscuro": mapaOscuro,
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

            var legendMildiu = L.control({{position: 'bottomleft'}});
            legendMildiu.onAdd = function(map) {{
                this._div = L.DomUtil.create('div', 'legend');
                this._div.style.display = 'none';
                this._div.innerHTML = `
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:5px;">
                        <span style="font-size:0.85rem;font-weight:bold;color:#58a6ff;">● Mildiu</span>
                        <span onclick="toggleInfoAgro('mildiu')" title="Ver modelo" style="cursor:pointer;font-size:0.9rem;color:#8b949e;margin-left:8px;">ⓘ</span>
                    </div>
                    <div><i style="background:#0d47a1"></i> Alto</div>
                    <div><i style="background:#1976d2"></i> Moderado</div>
                    <div><i style="background:#64b5f6"></i> Bajo</div>`;
                L.DomEvent.disableClickPropagation(this._div);
                return this._div;
            }};
            legendMildiu.addTo(map);

            var legendOidio = L.control({{position: 'bottomleft'}});
            legendOidio.onAdd = function(map) {{
                this._div = L.DomUtil.create('div', 'legend');
                this._div.style.display = 'none';
                this._div.innerHTML = `
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:5px;">
                        <span style="font-size:0.85rem;font-weight:bold;color:#e65100;">■ Oídio</span>
                        <span onclick="toggleInfoAgro('oidio')" title="Ver modelo" style="cursor:pointer;font-size:0.9rem;color:#8b949e;margin-left:8px;">ⓘ</span>
                    </div>
                    <div><i style="background:#b71c1c"></i> Alto</div>
                    <div><i style="background:#e65100"></i> Moderado</div>
                    <div><i style="background:#ffa000"></i> Bajo</div>`;
                L.DomEvent.disableClickPropagation(this._div);
                return this._div;
            }};
            legendOidio.addTo(map);

            var _infoAgroActual = null;
            var INFO_AGRO = {{
                mildiu: `<div style="font-weight:bold;color:#58a6ff;margin-bottom:8px;font-size:0.88rem;">● Mildiu — Modelo Goidanich</div>
                    <b>Condición de infección diaria:</b><br>
                    T<sub>med</sub> entre 11 °C y 30 °C<br>
                    + lluvia &ge;2 mm <em>o</em> HR&ge;85% durante &ge;2 h<br><br>
                    <b>Puntuación diaria:</b><br>
                    18–22 °C → 3 pts (óptimo)<br>
                    14–18 °C o 22–25 °C → 2 pts<br>
                    Resto → 1 pt<br>
                    Lluvia &ge;10 mm → +1 pt extra<br><br>
                    <b>Ventana:</b> 14 días deslizantes<br><br>
                    <b>Niveles:</b><br>
                    &ge;15 pts → <span style="color:#0d47a1;font-weight:bold;">Alto</span><br>
                    5–14 pts → <span style="color:#1976d2;font-weight:bold;">Moderado</span><br>
                    &lt;5 pts &nbsp;→ <span style="color:#64b5f6;font-weight:bold;">Bajo</span>`,
                oidio: `<div style="font-weight:bold;color:#e65100;margin-bottom:8px;font-size:0.88rem;">■ Oídio — DSV Gubler-Thomas (1982)</div>
                    <b>Condición:</b> T<sub>med</sub> entre 15 °C y 40 °C<br>
                    + horas con HR &ge;85%<br>
                    (precipitación &gt;2,5 mm anula el día)<br><br>
                    <b>Tabla DSV diario:</b><br>
                    15–19 °C: 1–4 pts según horas HR<br>
                    19–22 °C: 2–5 pts<br>
                    22–26 °C: 3–6 pts (óptimo)<br>
                    26–40 °C: 2–5 pts<br><br>
                    <b>Niveles (DSV acumulado 7 días):</b><br>
                    &ge;20 → <span style="color:#b71c1c;font-weight:bold;">Alto</span><br>
                    1–19 &nbsp;→ <span style="color:#e65100;font-weight:bold;">Moderado</span><br>
                    0 &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;→ <span style="color:#ffa000;font-weight:bold;">Bajo</span>`
            }};
            function toggleInfoAgro(enfermedad) {{
                var panel = document.getElementById('info-agro-panel');
                if (!enfermedad || _infoAgroActual === enfermedad) {{
                    panel.style.display = 'none';
                    _infoAgroActual = null;
                }} else {{
                    document.getElementById('info-agro-contenido').innerHTML = INFO_AGRO[enfermedad];
                    panel.style.display = '';
                    _infoAgroActual = enfermedad;
                }}
            }}

            function actualizarOverlayMeteo(isoString) {{
                var d = new Date(isoString);
                var today = new Date();
                var isToday = (d.getDate() === today.getDate() && d.getMonth() === today.getMonth());
                var hora = d.toLocaleTimeString('es-ES', {{hour:'2-digit', minute:'2-digit'}});
                var dia = isToday ? 'Hoy' : 'Ayer ' + d.getDate() + '/' + String(d.getMonth()+1).padStart(2,'0');
                var el = document.getElementById('mapa-tiempo-label');
                el.innerHTML = `<div>${{hora}}</div><div style="font-size:1rem;font-weight:normal;opacity:0.85;">${{dia}}</div>`;
                el.style.display = '';
            }}

            function actualizarOverlayAgro(fecha) {{
                var el = document.getElementById('mapa-tiempo-label');
                if (fecha) {{
                    var hoy = new Date().toISOString().slice(0,10);
                    var etiq = fecha === hoy ? 'Hoy' : '';
                    el.innerHTML = `<div style="font-size:2.2rem;">${{formatFechaAgro(fecha)}}</div>` +
                                   (etiq ? `<div style="font-size:0.95rem;font-weight:normal;opacity:0.85;">${{etiq}}</div>` : '');
                    el.style.display = '';
                }} else {{
                    el.style.display = 'none';
                }}
            }}

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
                var ts = historyData[currentTimestampIndex].timestamp;
                document.getElementById('time-label').innerText = formatTimeLabel(ts) + (isLatest ? " (Actual)" : " (Histórico)");
                actualizarOverlayMeteo(ts);
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
                    }}, 500); // 0.5 segundos por fotograma
                }}
            }});

            document.getElementById('opacity-slider').addEventListener('input', function(e) {{
                window.globalHeatmapOpacity = parseFloat(e.target.value);
                if (heatmapLayer) {{
                    heatmapLayer.setStyle({{fillOpacity: window.globalHeatmapOpacity}});
                }}
            }});

            document.getElementById('agro-time-slider').addEventListener('input', function(e) {{
                agroSliderIndex = parseInt(e.target.value);
                actualizarCapasAgro();
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

            function formatFechaAgro(dateStr) {{
                var p = dateStr.split('-');
                return p[2] + '/' + p[1] + '/' + p[0];
            }}

            function getAgroFechasFiltradas() {{
                var todas = Object.keys(historialAgro).sort();
                if (filtroAgroDias === 0) return todas;
                return todas.slice(-filtroAgroDias);
            }}

            function setFiltroAgro(dias) {{
                filtroAgroDias = dias;
                ['filtro-7d','filtro-15d','filtro-todo'].forEach(function(id) {{
                    document.getElementById(id).classList.remove('activo');
                }});
                var idActivo = dias === 7 ? 'filtro-7d' : dias === 15 ? 'filtro-15d' : 'filtro-todo';
                document.getElementById(idActivo).classList.add('activo');
                inicializarAgroSlider();
            }}

            function inicializarAgroSlider() {{
                historialAgroFechas = getAgroFechasFiltradas();
                var slider = document.getElementById('agro-time-slider');
                var maxIdx = Math.max(0, historialAgroFechas.length - 1);
                slider.min = 0;
                slider.max = maxIdx;
                slider.value = maxIdx;
                agroSliderIndex = maxIdx;
                actualizarCapasAgro();
            }}

            function actualizarCapasAgro() {{
                var fecha = historialAgroFechas[agroSliderIndex] || null;
                var label = document.getElementById('agro-date-label');
                if (fecha) {{
                    var hoy = new Date().toISOString().slice(0,10);
                    label.innerText = formatFechaAgro(fecha) + (fecha === hoy ? ' (Hoy)' : '');
                }} else {{
                    label.innerText = '';
                }}
                actualizarOverlayAgro(fecha);
                dibujarCapaMildiu(fecha);
                dibujarCapaOidio(fecha);
            }}

            function toggleAgroPlay() {{
                var btn = document.getElementById('agro-play-btn');
                var slider = document.getElementById('agro-time-slider');
                if (agroPlayInterval) {{
                    clearInterval(agroPlayInterval);
                    agroPlayInterval = null;
                    btn.innerText = '▶️';
                    btn.title = 'Reproducir';
                }} else {{
                    btn.innerText = '⏸️';
                    btn.title = 'Pausar';
                    if (agroSliderIndex >= historialAgroFechas.length - 1) {{
                        agroSliderIndex = 0;
                    }}
                    agroPlayInterval = setInterval(function() {{
                        agroSliderIndex++;
                        if (agroSliderIndex >= historialAgroFechas.length) {{
                            agroSliderIndex = 0;
                        }}
                        slider.value = agroSliderIndex;
                        actualizarCapasAgro();
                    }}, 400);
                }}
            }}

            function colorMildiu(nivel) {{
                if (nivel >= 3) return '#0d47a1';
                if (nivel >= 2) return '#1976d2';
                return '#64b5f6';
            }}
            function colorOidio(nivel) {{
                if (nivel >= 3) return '#b71c1c';
                if (nivel >= 2) return '#e65100';
                return '#ffa000';
            }}

            var NIVEL_TEXTO = {{1:'Bajo', 2:'Moderado', 3:'Alto'}};
            var NIVEL_LETRA = {{1:'B', 2:'M', 3:'A'}};

            function dibujarCapaMildiu(fecha) {{
                capaMildiuGroup.clearLayers();
                heatmapMildiuGroup.clearLayers();
                if (!capaMildiuActiva) return;
                var datosF = fecha ? (historialAgro[fecha] || {{}}) : {{}};
                if (Object.keys(datosF).length === 0) return;
                var features = [];
                Object.entries(datosF).forEach(function([estId, d]) {{
                    if (!d.lat || !d.lon) return;
                    var nivel = d.mildiu_nivel || 1;
                    var color = colorMildiu(nivel);
                    var letra = NIVEL_LETRA[nivel] || '?';
                    var markerHtml = `<div style="background:${{color}};color:white;text-shadow:1px 1px 2px rgba(0,0,0,0.7);border:2px solid white;border-radius:50%;width:24px;height:24px;display:flex;justify-content:center;align-items:center;font-weight:bold;font-size:11px;box-shadow:0 2px 5px rgba(0,0,0,0.5);">${{letra}}</div>`;
                    var marker = L.marker([d.lat, d.lon], {{
                        icon: L.divIcon({{className:'station-badge', html:markerHtml, iconSize:[24,24], iconAnchor:[12,12]}})
                    }});
                    var nombre = nombresPersonalizados[estId] || estId;
                    marker.bindPopup(`<div style="min-width:165px;">
                        <div style="text-align:center;padding-bottom:5px;">
                            <strong style="font-size:1rem;color:#1565c0;">● Mildiu</strong><br>
                            <strong style="color:#2c3e50;">${{nombre}}</strong>
                            <div style="font-size:0.75rem;color:#999;">${{estId}}</div>
                        </div>
                        <div style="background:#e3f2fd;border-radius:4px;padding:8px;text-align:center;">
                            <div style="font-size:1.4rem;font-weight:bold;color:${{color}};">${{NIVEL_TEXTO[nivel]}}</div>
                        </div>
                        <div style="font-size:0.78rem;color:#555;margin-top:7px;line-height:1.6;">
                            Modelo: Goidanich (14 días)<br>
                            Puntos acumulados: <strong>${{d.mildiu_puntos}}</strong><br>
                            Días con condición de infección: <strong>${{d.mildiu_dias}}</strong><br>
                            <span style="color:#888;font-size:0.72rem;">T 11–30°C + lluvia≥2mm o HR≥85%≥2h</span>
                        </div>
                    </div>`);
                    marker.bindTooltip(`<strong>${{nombre}}</strong><br>Mildiu: ${{NIVEL_TEXTO[nivel]}}`, {{direction:'top', offset:[0,-12], opacity:0.95}});
                    capaMildiuGroup.addLayer(marker);
                    features.push(turf.point([d.lon, d.lat], {{value: nivel}}));
                }});
                if (features.length > 2) {{
                    try {{
                        var col = turf.featureCollection(features);
                        var grid = turf.interpolate(col, 3, {{gridType:'square', property:'value', units:'kilometers', weight:2}});
                        var filtered = turf.featureCollection(grid.features.filter(function(f) {{ return f.properties.value !== null && !isNaN(f.properties.value); }}));
                        var heatLayer = L.geoJSON(filtered, {{
                            pane: 'heatmapMildiuPane',
                            style: function(feature) {{
                                var v = Math.max(1, Math.min(3, Math.round(feature.properties.value)));
                                return {{fillColor: colorMildiu(v), fillOpacity: window.globalHeatmapOpacity, stroke: false}};
                            }}
                        }});
                        heatmapMildiuGroup.addLayer(heatLayer);
                    }} catch(e) {{ console.error('Heatmap mildiu:', e); }}
                }}
            }}

            function dibujarCapaOidio(fecha) {{
                capaOidioGroup.clearLayers();
                heatmapOidioGroup.clearLayers();
                if (!capaOidioActiva) return;
                var datosF = fecha ? (historialAgro[fecha] || {{}}) : {{}};
                if (Object.keys(datosF).length === 0) return;
                var features = [];
                Object.entries(datosF).forEach(function([estId, d]) {{
                    if (!d.lat || !d.lon) return;
                    var nivel = d.oidio_nivel || 1;
                    var color = colorOidio(nivel);
                    var letra = NIVEL_LETRA[nivel] || '?';
                    var markerHtml = `<div style="background:${{color}};color:white;text-shadow:1px 1px 2px rgba(0,0,0,0.7);border:2px solid white;border-radius:3px;width:22px;height:22px;display:flex;justify-content:center;align-items:center;font-weight:bold;font-size:11px;box-shadow:0 2px 5px rgba(0,0,0,0.5);">${{letra}}</div>`;
                    var marker = L.marker([d.lat, d.lon], {{
                        icon: L.divIcon({{className:'station-badge', html:markerHtml, iconSize:[22,22], iconAnchor:[11,11]}})
                    }});
                    var nombre = nombresPersonalizados[estId] || estId;
                    marker.bindPopup(`<div style="min-width:165px;">
                        <div style="text-align:center;padding-bottom:5px;">
                            <strong style="font-size:1rem;color:#e65100;">■ Oídio</strong><br>
                            <strong style="color:#2c3e50;">${{nombre}}</strong>
                            <div style="font-size:0.75rem;color:#999;">${{estId}}</div>
                        </div>
                        <div style="background:#fff3e0;border-radius:4px;padding:8px;text-align:center;">
                            <div style="font-size:1.4rem;font-weight:bold;color:${{color}};">${{NIVEL_TEXTO[nivel]}}</div>
                        </div>
                        <div style="font-size:0.78rem;color:#555;margin-top:7px;line-height:1.6;">
                            Modelo: DSV Gubler-Thomas<br>
                            DSV últimos 7 días: <strong>${{d.dsv_7d}}</strong><br>
                            DSV temporada (desde 1-Mar): <strong>${{d.dsv_temporada}}</strong><br>
                            <span style="color:#888;font-size:0.72rem;">T 15–40°C + HR≥85% acumuladas</span>
                        </div>
                    </div>`);
                    marker.bindTooltip(`<strong>${{nombre}}</strong><br>Oídio: ${{NIVEL_TEXTO[nivel]}}`, {{direction:'top', offset:[0,-12], opacity:0.95}});
                    capaOidioGroup.addLayer(marker);
                    features.push(turf.point([d.lon, d.lat], {{value: nivel}}));
                }});
                if (features.length > 2) {{
                    try {{
                        var col = turf.featureCollection(features);
                        var grid = turf.interpolate(col, 3, {{gridType:'square', property:'value', units:'kilometers', weight:2}});
                        var filtered = turf.featureCollection(grid.features.filter(function(f) {{ return f.properties.value !== null && !isNaN(f.properties.value); }}));
                        var heatLayer = L.geoJSON(filtered, {{
                            pane: 'heatmapOidioPane',
                            style: function(feature) {{
                                var v = Math.max(1, Math.min(3, Math.round(feature.properties.value)));
                                return {{fillColor: colorOidio(v), fillOpacity: window.globalHeatmapOpacity, stroke: false}};
                            }}
                        }});
                        heatmapOidioGroup.addLayer(heatLayer);
                    }} catch(e) {{ console.error('Heatmap oidio:', e); }}
                }}
            }}

            function toggleCapa(enfermedad) {{
                var fecha = historialAgroFechas[agroSliderIndex] || null;
                // Solo una capa activa a la vez (radio button)
                capaMildiuActiva = (enfermedad === 'mildiu');
                capaOidioActiva  = (enfermedad === 'oidio');

                document.getElementById('btn-capa-mildiu').classList.toggle('activo', capaMildiuActiva);
                document.getElementById('btn-capa-oidio').classList.toggle('activo',  capaOidioActiva);
                legendMildiu._div.style.display = capaMildiuActiva ? '' : 'none';
                legendOidio._div.style.display  = capaOidioActiva  ? '' : 'none';

                capaMildiuGroup.clearLayers();   heatmapMildiuGroup.clearLayers();
                capaOidioGroup.clearLayers();    heatmapOidioGroup.clearLayers();

                if (capaMildiuActiva) dibujarCapaMildiu(fecha);
                if (capaOidioActiva)  dibujarCapaOidio(fecha);
            }}

            function switchTab(modo) {{
                modoActivo = modo;
                document.getElementById('tab-meteo-btn').classList.toggle('active', modo === 'meteo');
                document.getElementById('tab-agro-btn').classList.toggle('active', modo === 'agro');
                document.getElementById('controles-meteo').style.display = (modo === 'meteo') ? 'flex' : 'none';
                document.getElementById('controles-agro').style.display = (modo === 'agro') ? 'flex' : 'none';

                if (modo === 'meteo') {{
                    if (agroPlayInterval) {{ clearInterval(agroPlayInterval); agroPlayInterval = null; document.getElementById('agro-play-btn').innerText = '▶️'; }}
                    capaMildiuGroup.clearLayers();
                    capaOidioGroup.clearLayers();
                    heatmapMildiuGroup.clearLayers();
                    heatmapOidioGroup.clearLayers();
                    if (map.hasLayer(capaMildiuGroup))    map.removeLayer(capaMildiuGroup);
                    if (map.hasLayer(capaOidioGroup))     map.removeLayer(capaOidioGroup);
                    if (map.hasLayer(heatmapMildiuGroup)) map.removeLayer(heatmapMildiuGroup);
                    if (map.hasLayer(heatmapOidioGroup))  map.removeLayer(heatmapOidioGroup);
                    legend._div.style.display       = '';
                    legendMildiu._div.style.display = 'none';
                    legendOidio._div.style.display  = 'none';
                    heatmapLayerGroup.clearLayers();
                    markersLayer.clearLayers();
                    if (historyData.length > 0) actualizarOverlayMeteo(historyData[currentTimestampIndex].timestamp);
                    actualizarMapa();
                }} else {{
                    heatmapLayerGroup.clearLayers();
                    markersLayer.clearLayers();
                    legend._div.style.display = 'none';
                    // Al entrar en agro: mildiu activo por defecto, oidio desactivado
                    capaMildiuActiva = true;
                    capaOidioActiva  = false;
                    document.getElementById('btn-capa-mildiu').classList.add('activo');
                    document.getElementById('btn-capa-oidio').classList.remove('activo');
                    legendMildiu._div.style.display = '';
                    legendOidio._div.style.display  = 'none';
                    capaMildiuGroup.addTo(map);
                    capaOidioGroup.addTo(map);
                    heatmapMildiuGroup.addTo(map);
                    heatmapOidioGroup.addTo(map);
                    inicializarAgroSlider();
                }}
            }}

            // Inicializar
            if (historyData.length > 0) {{
                document.getElementById('time-slider').max = historyData.length - 1;
                document.getElementById('time-slider').value = historyData.length - 1;
                var tsInit = historyData[currentTimestampIndex].timestamp;
                document.getElementById('time-label').innerText = formatTimeLabel(tsInit) + " (Actual)";
                actualizarOverlayMeteo(tsInit);
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

        historial_agro = calcular_historial_agro(historial_agri, historial_riesgo, historial_dsv, coordenadas)
        ruta_html = generar_html(historial, ahora, historial_agro)
        print("Mapa, Máquina del Tiempo y Datos Agrícolas generados correctamente.")
    else:
        print("No se han podido cargar datos.")

if __name__ == "__main__":
    principal()
