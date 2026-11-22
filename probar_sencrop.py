"""Prueba puntual: ¿se puede entrar en Sencrop desde GitHub Actions y qué API usa la web?

Uso (solo en CI, ver .github/workflows/probar-sencrop.yml):
    SENCROP_USER=... SENCROP_PASSWORD=... python3 probar_sencrop.py

El repositorio es público y los logs de Actions también, así que este script
NO imprime credenciales, cabeceras, tokens, cuerpos de respuesta ni query strings.
Solo imprime: si el login funcionó y las rutas (host + path) que la web de Sencrop
llama por XHR/fetch, con el código de respuesta.
"""
import os
import re
import sys
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

URL_LOGIN = "https://app.sencrop.com/login"
USUARIO = os.environ.get("SENCROP_USER", "")
CLAVE = os.environ.get("SENCROP_PASSWORD", "")


def limpiar(url):
    """host + path, sin query ni identificadores largos."""
    partes = urlsplit(url)
    ruta = re.sub(r"[0-9a-fA-F-]{24,}", "<id>", partes.path)
    return partes.netloc + ruta


def main():
    if not USUARIO or not CLAVE:
        print("Faltan los secrets SENCROP_USER / SENCROP_PASSWORD")
        return 1

    llamadas = {}

    with sync_playwright() as p:
        navegador = p.chromium.launch()
        pagina = navegador.new_page()

        def al_responder(resp):
            req = resp.request
            if req.resource_type in ("xhr", "fetch"):
                clave = (req.method, limpiar(resp.url), resp.status)
                llamadas[clave] = llamadas.get(clave, 0) + 1

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
            texto = pagina.inner_text("body")[:300].replace(USUARIO, "***")
            print("Texto de la página:", texto)
            navegador.close()
            return 1

        pagina.wait_for_load_state("networkidle")
        pagina.goto("https://app.sencrop.com/dashboard", wait_until="networkidle")
        navegador.close()

    print("\nLlamadas XHR/fetch observadas (método, ruta, estado, veces):")
    for (metodo, ruta, estado), veces in sorted(llamadas.items(), key=lambda x: x[0][1]):
        print(f"  {metodo:6} {estado} {ruta}  x{veces}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
