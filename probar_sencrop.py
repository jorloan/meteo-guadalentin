"""Prueba puntual: ¿se puede entrar en Sencrop desde GitHub Actions y qué API usa la web?

Uso (solo en CI, ver .github/workflows/probar-sencrop.yml):
    SENCROP_USER=... SENCROP_PASSWORD=... python3 probar_sencrop.py

El repositorio es público y los logs de Actions también, así que este script
NO imprime credenciales, cabeceras, tokens, valores de respuesta ni query strings.
Solo imprime: si el login funcionó, las rutas (host + path) que la web llama por
XHR/fetch con su código de respuesta, y, para las rutas de estaciones/mediciones,
la ESTRUCTURA de la respuesta JSON (nombres de campos y tipos, sin valores).
"""
import os
import re
import sys
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

URL_LOGIN = "https://app.sencrop.com/login"
URL_DASHBOARD = "https://app.sencrop.com/station/dashboard"
USUARIO = os.environ.get("SENCROP_USER", "")
CLAVE = os.environ.get("SENCROP_PASSWORD", "")
# Solo se describe la estructura de respuestas de estas rutas (datos de estaciones)
INTERESANTES = ("station", "device", "measure", "weather", "dashboard", "observation", "history")
MAX_ESTRUCTURAS = 25


def limpiar(url):
    """host + path, sin query ni identificadores largos."""
    partes = urlsplit(url)
    ruta = re.sub(r"[0-9a-fA-F-]{24,}", "<id>", partes.path)
    return partes.netloc + ruta


def estructura(valor, profundidad=0, maximo=7):
    """Describe un JSON con nombres de campos y tipos, sin ningún valor."""
    if profundidad >= maximo:
        return "…"
    if isinstance(valor, dict):
        return "{" + ", ".join(f"{k}: {estructura(v, profundidad + 1, maximo)}"
                               for k, v in list(valor.items())[:40]) + "}"
    if isinstance(valor, list):
        if not valor:
            return "[]"
        return f"[{len(valor)} x " + estructura(valor[0], profundidad + 1, maximo) + "]"
    if isinstance(valor, bool):
        return "bool"
    if isinstance(valor, (int, float)):
        return "num"
    if valor is None:
        return "null"
    return "str"


def main():
    if not USUARIO or not CLAVE:
        print("Faltan los secrets SENCROP_USER / SENCROP_PASSWORD")
        return 1

    llamadas = {}
    estructuras = {}

    with sync_playwright() as p:
        navegador = p.chromium.launch()
        pagina = navegador.new_page()

        def al_responder(resp):
            req = resp.request
            if req.resource_type not in ("xhr", "fetch"):
                return
            ruta = limpiar(resp.url)
            clave = (req.method, ruta, resp.status)
            llamadas[clave] = llamadas.get(clave, 0) + 1
            if ("sencrop" in ruta and resp.status == 200
                    and (req.method == "GET" or "station-list" in ruta)
                    and any(k in ruta.lower() for k in INTERESANTES)
                    and ruta not in estructuras and len(estructuras) < MAX_ESTRUCTURAS):
                try:
                    estructuras[ruta] = estructura(resp.json())
                except Exception:
                    estructuras[ruta] = "(no es JSON)"

        pagina.on("response", al_responder)

        pagina.goto(URL_LOGIN, wait_until="networkidle")
        pagina.fill("input[type=email], input[name=email]", USUARIO)
        pagina.fill("input[type=password]", CLAVE)
        pagina.click("button[type=submit]")

        try:
            pagina.wait_for_url("**/home**", timeout=30000)
            print("LOGIN: OK (llegó a /home)")
        except Exception:
            print("LOGIN: FALLÓ. URL final:", limpiar(pagina.url))
            navegador.close()
            return 1

        pagina.wait_for_load_state("networkidle")

        # Dashboard: lista de estaciones con sus lecturas actuales
        pagina.goto(URL_DASHBOARD, wait_until="networkidle")
        pagina.wait_for_timeout(4000)
        print("DASHBOARD URL:", limpiar(pagina.url))

        # Entrar en la primera estación para ver la llamada de mediciones/histórico
        try:
            pagina.locator("text=Pluviometría").first.click(timeout=8000)
            pagina.wait_for_load_state("networkidle")
            pagina.wait_for_timeout(4000)
            print("ESTACIÓN URL:", limpiar(pagina.url))
        except Exception as e:
            print("No se pudo abrir la primera estación:", type(e).__name__)

        navegador.close()

    print("\nLlamadas a Sencrop (método, estado, ruta, veces):")
    for (metodo, ruta, estado), veces in sorted(llamadas.items(), key=lambda x: x[0][1]):
        if "sencrop" in ruta:
            print(f"  {metodo:5} {estado} {ruta}  x{veces}")

    print("\nEstructura de las respuestas de estaciones/mediciones (sin valores):")
    for ruta, est in estructuras.items():
        print(f"  {ruta}\n     {est[:900]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
