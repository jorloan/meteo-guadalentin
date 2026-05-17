import urllib.request, json, ssl, os, subprocess
from datetime import datetime, timedelta

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

AEMET_KEY = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJqb3Nlcm9xdWVAbG9wZXp5YW5kcmVvLmNvbSIsImp0aSI6ImFkNDI4NjkxLTI2ZWMtNDM2Ni04Zjc3LTAyNTBkOTE2ODk4NyIsImlzcyI6IkFFTUVUIiwiaWF0IjoxNzc4OTc2NjU2LCJ1c2VySWQiOiJhZDQyODY5MS0yNmVjLTQzNjYtOGY3Ny0wMjUwZDkxNjg5ODciLCJyb2xlIjoiIn0.0ncG0BPkrmqHDKbasNRAgVb_SlNNJl3Xz5LL9xE75l8"
REPO_DIR = os.path.expanduser("~/Documents/meteo-guadalentin")
F_DSV  = os.path.join(REPO_DIR, "historial_dsv.json")
F_AGRI = os.path.join(REPO_DIR, "historial_agricola.json")
F_EST  = os.path.join(REPO_DIR, "estaciones.txt")
AEMET_EST = [
    ("7218Y","Totana",37.769,-1.504),("7209","Lorca",37.679,-1.701),
    ("7227X","Alhama de Murcia",37.852,-1.425),("7007Y","Mazarron",37.598,-1.314),
    ("7211B","Pto Lumbreras",37.561,-1.803),("7023X","Fuente Alamo",37.712,-1.176),
    ("7203A","Lorca/Zarcilla",37.901,-1.810),
]
ESTACIONES_WU = [l.split("#")[0].strip() for l in open(F_EST) if l.split("#")[0].strip()]
DSV_TABLE = {
    (15,19):{(0,6):1,(7,12):2,(13,18):3,(19,24):4},
    (19,22):{(0,6):2,(7,12):3,(13,18):4,(19,24):5},
    (22,26):{(0,6):3,(7,12):4,(13,18):5,(19,24):6},
    (26,40):{(0,6):2,(7,12):3,(13,18):4,(19,24):5},
}
def dsv_dia(tmed,horas,prec=0):
    if prec and prec>2.5: return 0
    if not tmed or tmed<15: return 0
    for (a,b),cols in DSV_TABLE.items():
        if a<=tmed<b:
            for (h1,h2),v in cols.items():
                if h1<=horas<=h2: return v
            return list(cols.values())[-1]
    return 0
def pf(v):
    if v is None: return None
    try: return float(str(v).replace(",","."))
    except: return None
def dist(a,b,c,d): return ((a-c)**2+(b-d)**2)**0.5

ahora = datetime.now()
fi = datetime(ahora.year,3,1).strftime("%Y-%m-%dT00:00:00UTC")
ff = (ahora-timedelta(days=1)).strftime("%Y-%m-%dT23:59:59UTC")
print(f"Periodo: {fi[:10]} -> {ff[:10]}")

aemet_datos = {}
for idema,nombre,lat,lon in AEMET_EST:
    path = f"/api/valores/climatologicos/diarios/datos/fechaini/{fi}/fechafin/{ff}/estacion/{idema}"
    try:
        req = urllib.request.Request("https://opendata.aemet.es/opendata/api"+path,
            headers={"api_key":AEMET_KEY,"cache-control":"no-cache"})
        with urllib.request.urlopen(req,context=ctx,timeout=15) as r:
            meta = json.loads(r.read().decode("utf-8"))
        if meta.get("estado")!=200: print(f"  {idema}: {meta.get('descripcion','')}"); continue
        with urllib.request.urlopen(urllib.request.Request(meta["datos"]),context=ctx,timeout=15) as r2:
            datos = json.loads(r2.read().decode("utf-8"))
        aemet_datos[idema]={}
        for d in datos:
            f2=d.get("fecha","")
            if f2: aemet_datos[idema][f2]={"tmax":pf(d.get("tmax")),"tmin":pf(d.get("tmin")),"prec":pf(d.get("prec")),"hrmax":pf(d.get("hrmax")),"hrmin":pf(d.get("hrmin")),"lat":lat,"lon":lon}
        print(f"  OK {idema} ({nombre}): {len(aemet_datos[idema])} dias")
    except Exception as e: print(f"  ERR {idema}: {e}")

if not aemet_datos: print("Sin datos AEMET"); exit(1)

hagri = json.load(open(F_AGRI,"r",encoding="utf-8")) if os.path.exists(F_AGRI) else {}
pos_wu = {}
for fd in hagri.values():
    for sid,dd in fd.items():
        if sid not in pos_wu and dd.get("lat"): pos_wu[sid]=(dd["lat"],dd["lon"])

dsv_hist = json.load(open(F_DSV,"r",encoding="utf-8")) if os.path.exists(F_DSV) else {}
inicio = datetime(ahora.year,3,1)
fechas = [(inicio+timedelta(days=i)).strftime("%Y-%m-%d") for i in range((ahora-inicio).days)]

for sid in ESTACIONES_WU:
    la,lo = pos_wu.get(sid,(37.77,-1.5))
    mejor_d,mejor_id = 999,None
    for idema,_,alat,alon in AEMET_EST:
        if idema not in aemet_datos: continue
        d2=dist(la,lo,alat,alon)
        if d2<mejor_d: mejor_d,mejor_id=d2,idema
    if not mejor_id: continue
    ref=aemet_datos[mejor_id]
    dsv_acum,fechas_ok=[],[]
    for fecha in fechas:
        dd=ref.get(fecha)
        if not dd: continue
        tmax,tmin,prec,hrmax,hrmin=dd.get("tmax"),dd.get("tmin"),dd.get("prec") or 0,dd.get("hrmax"),dd.get("hrmin")
        if tmax is None or tmin is None: continue
        tmed=round((tmax+tmin)/2,1)
        horas=0
        if hrmax and hrmax>=85:
            rango=(hrmax-hrmin) if hrmin and hrmax>hrmin else 1
            horas=min(24,round(max(0,(hrmax-85)/rango)*24+4))
        dsv_acum.append(dsv_dia(tmed,horas,prec))
        fechas_ok.append(fecha)
    dsv_total=sum(dsv_acum)
    dsv_wu_extra=dsv_hist.get(sid,{}).get("dsv_wu_extra",0)
    dsv_hist[sid]={"dsv_acumulado":dsv_total+dsv_wu_extra,"dsv_aemet":dsv_total,"dsv_wu_extra":dsv_wu_extra,"fechas":fechas_ok,"aemet_ref":mejor_id,"dias_calculados":len(fechas_ok)}

niveles=["Sin riesgo","Vigilancia","Tratar pronto","URGENTE"]
print(f"\nEstacion        AEMET  Dias  DSV  Nivel")
for sid in sorted(list(dsv_hist.keys()))[:15]:
    d=dsv_hist[sid]; dsv=d.get("dsv_acumulado",0)
    nv=niveles[min(3,dsv//20)]
    print(f"  {sid:15} {d.get('aemet_ref','?'):7} {d.get('dias_calculados',0):4}d {dsv:4}  {nv}")
if len(dsv_hist)>15: print(f"  ... y {len(dsv_hist)-15} mas")

with open(F_DSV,"w",encoding="utf-8") as f: json.dump(dsv_hist,f,ensure_ascii=False,indent=2)
print(f"\nGuardado: {len(dsv_hist)} estaciones en historial_dsv.json")
for cmd in [["git","-C",REPO_DIR,"add","historial_dsv.json"],["git","-C",REPO_DIR,"commit","-m","DSV inicial temporada desde marzo"],["git","-C",REPO_DIR,"push"]]:
    r=subprocess.run(cmd,capture_output=True,text=True)
    if r.returncode!=0:
        if "nothing to commit" in r.stdout+r.stderr: print("Sin cambios"); break
        print(f"Git: {r.stderr.strip()[:60]}"); break
else: print("Subido a GitHub OK")
print("\nAhora ejecuta: python3 mapa_totana.py")
