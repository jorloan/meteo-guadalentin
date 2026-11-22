"""Prueba puntual: ¿qué medidas y rangos admite el historial de Sencrop?

Uso (solo en CI, ver .github/workflows/probar-sencrop.yml):
    SENCROP_USER=... SENCROP_PASSWORD=... python3 probar_sencrop.py

Repositorio y logs públicos: NO se imprimen credenciales, cabeceras, tokens ni
valores de medidas. Solo: códigos de respuesta, nombres de métricas y número de
puntos de cada serie, para diseñar el rellenado de 7 días.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from playwright.sync_api import sync_playwright

URL_LOGIN = "https://app.sencrop.com/login"
URL_DASHBOARD = "https://app.sencrop.com/station/dashboard"
API = "https://sencrop-api-production.infra.sencrop.com/app/station/measurement-page/measurements"
USUARIO = os.environ.get("SENCROP_USER", "")
CLAVE = os.environ.get("SENCROP_PASSWORD", "")
ORGANIZACION = "236298"   # Comunidad de Regantes (ya aparece en las URLs de la web)

CANDIDATAS = ["temperature", "rainfall", "relativeHumidity", "humidity", "windSpeed",
              "windGust", "windDirection", "dewPoint", "wetTemperature", "precipitation",
              "wind", "rain"]


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000+00:00")


def describir(js):
    """Nombres de métricas y nº de puntos de cada serie, sin valores."""
    try:
        medidas = js["response"]["stationMeasurements"]
    except Exception:
        return "(estructura inesperada: " + str(list(js)[:5]) + ")"
    out = []
    for nombre, series in medidas.items():
        for s in series:
            ts = s.get("timeseries") or []
            out.append(f"{nombre}/{s.get('metric')}: {len(ts)} pts, relleno={s.get('hasFill')}")
    return "; ".join(out) or "(vacío)"


def main():
    if not USUARIO or not CLAVE:
        print("Faltan los secrets SENCROP_USER / SENCROP_PASSWORD")
        return 1
    estaciones = {}
    with sync_playwright() as p:
        navegador = p.chromium.launch()
        ctx = navegador.new_context(locale="es-ES")
        pagina = ctx.new_page()

        def al_responder(resp):
            if "station/dashboard/station-list" in resp.url and resp.status == 200:
                try:
                    for e in resp.json().get("stations") or []:
                        estaciones[e["id"]] = e.get("name")
                except Exception:
                    pass

        pagina.on("response", al_responder)
        pagina.goto(URL_LOGIN, wait_until="networkidle")
        pagina.fill("input[type=email], input[name=email]", USUARIO)
        pagina.fill("input[type=password]", CLAVE)
        pagina.click("button[type=submit]")
        pagina.wait_for_url("**/home**", timeout=30000)
        pagina.wait_for_load_state("networkidle")
        pagina.goto(URL_DASHBOARD, wait_until="networkidle")
        pagina.wait_for_timeout(3000)
        print("LOGIN: OK; estaciones vistas:", len(estaciones))
        if not estaciones:
            navegador.close()
            return 1

        sid = next(iter(estaciones))
        ahora = datetime.now(timezone.utc)

        def pedir(tipo, medida, dias, fin=None):
            fin = fin or ahora
            q = {"organisationId": ORGANIZACION, "stationId": sid,
                 "startDatetime": iso(fin - timedelta(days=dias)),
                 "endDatetime": iso(fin), "measures": medida, "enableFilling": "true"}
            r = ctx.request.get(f"{API}/{tipo}?{urlencode(q)}")
            try:
                return r.status, (describir(r.json()) if r.ok else r.text()[:120].replace("\n", " "))
            except Exception as e:
                return r.status, f"({type(e).__name__})"

        print("\n--- Medidas candidatas (hourly, 1 día) ---")
        for m in CANDIDATAS:
            print(f"  {m}: {pedir('hourly', m, 1)}")

        print("\n--- Rangos con temperature ---")
        for tipo, dias in (("hourly", 2), ("hourly", 7), ("hourly", 8), ("daily", 7), ("daily", 14)):
            print(f"  {tipo} {dias} días: {pedir(tipo, 'temperature', dias)}")

        print("\n--- Varias medidas a la vez (hourly 7 días, separadas por coma) ---")
        print("  ", pedir("hourly", "temperature,rainfall,relativeHumidity,windSpeed", 7))
        navegador.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
