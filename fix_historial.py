import urllib.request, json, ssl, os, concurrent.futures
from datetime import datetime, timedelta

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
WU_KEY = "6532d6454b8aa370768e63d6ba5a832e"
REPO_DIR = os.path.expanduser("~/Documents/meteo-guadalentin")
F_AGRI = os.path.join(REPO_DIR, "historial_agricola.json")
F_EST  = os.path.join(REPO_DIR, "estaciones.txt")
ESTACIONES = [l.split("#")[0].strip() for l in open(F_EST) if l.split("#")[0].strip()]
print(f"Estaciones: {len(ESTACIONES)}")

def wu_dia(sid, fecha_wu):
    url = (f"https://api.weather.com/v2/pws/history/all"
           f"?stationId={sid}&format=json&units=m&numericPrecision=decimal"
           f"&date={fecha_wu}&apiKey={WU_KEY}")
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.wunderground.com/"})
        with urllib.request.urlopen(req, context=ctx, timeout=10) as r:
            obs = json.loads(r.read().decode("utf-8")).get("observations", [])
        if not obs:
            return None
        # WU history/all usa tempHigh y tempLow por intervalo de 5min
        temps_high = [o["metric"]["tempHigh"] for o in obs if o.get("metric", {}).get("tempHigh") is not None]
        temps_low  = [o["metric"]["tempLow"]  for o in obs if o.get("metric", {}).get("tempLow")  is not None]
        precs      = [o["metric"]["precipTotal"] for o in obs if o.get("metric", {}).get("precipTotal") is not None]
        hums_high  = [o.get("humidityHigh", 0) for o in obs]
        if not temps_high:
            return None
        return {
            "tempMax":  round(max(temps_high), 1),
            "tempMin":  round(min(temps_low), 1) if temps_low else round(min(temps_high), 1),
            "precipTotal": round(max(precs), 1) if precs else 0.0,
            "humedadAltaMinutos": sum(1 for h in hums_high if h >= 85) * 5,
            "lat": obs[0].get("lat"),
            "lon": obs[0].get("lon")
        }
    except Exception as e:
        return None

def descargar(sid):
    ahora = datetime.now()
    res = {}
    for i in range(1, 8):
        dt = ahora - timedelta(days=i)
        d = wu_dia(sid, dt.strftime("%Y%m%d"))
        if d:
            res[dt.strftime("%Y-%m-%d")] = d
    return sid, res

historial = {}
if os.path.exists(F_AGRI):
    historial = json.load(open(F_AGRI, "r", encoding="utf-8"))

ok = 0
with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
    futuros = {ex.submit(descargar, sid): sid for sid in ESTACIONES}
    done = 0
    for fut in concurrent.futures.as_completed(futuros):
        sid = futuros[fut]
        done += 1
        sid_r, datos = fut.result()
        if datos:
            ok += 1
            for fecha, d in datos.items():
                if fecha not in historial:
                    historial[fecha] = {}
                historial[fecha][sid_r] = d
            v = list(datos.values())[0]
            print(f"  [{done:3}/{len(ESTACIONES)}] OK {sid_r} Tmax={v.get('tempMax')} Tmin={v.get('tempMin')}")
        else:
            print(f"  [{done:3}/{len(ESTACIONES)}] -- {sid_r}: sin datos")

for d in sorted(historial.keys())[:-14]:
    del historial[d]

with open(F_AGRI, "w", encoding="utf-8") as f:
    json.dump(historial, f, ensure_ascii=False, indent=2)

dias = len(historial)
print(f"\nGuardado: {dias} dias, {ok}/{len(ESTACIONES)} estaciones")

# Verificacion
sid = "ITOTAN16"
print(f"\nVerificacion {sid}:")
tmed15 = 0
for fecha in sorted(historial.keys()):
    d = historial[fecha].get(sid, {})
    tmax = d.get("tempMax")
    tmin = d.get("tempMin")
    if tmax is not None and tmin is not None:
        tmed = round((tmax + tmin) / 2, 1)
        if tmed >= 15:
            tmed15 += 1
        print(f"  {fecha}: Tmax={tmax} Tmin={tmin} Tmed={tmed}")
    else:
        print(f"  {fecha}: sin temperatura")

print(f"\nDias Tmed>=15C: {tmed15}/{dias}")
if tmed15 >= 5:
    print("RIESGO ACTIVO - Ejecuta: python3 mapa_totana.py")
else:
    print(f"Faltan {5 - tmed15} dias con Tmed>=15C")
