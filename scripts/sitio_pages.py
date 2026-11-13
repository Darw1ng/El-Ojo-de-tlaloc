"""Arma el sitio estatico de la historia NISAR para GitHub Pages.

    python scripts/sitio_pages.py _sitio

Copia frontend/nisar (sin los videos de la entrega, que la pagina no usa), el vendor
que comparte con el tablero, logo y favicon, y pone en la raiz un index.html que manda
a nisar/. El tablero de pronostico NO va: necesita el backend. En el sitio estatico la
historia lo detecta (no hay /tiles) y usa la base oscura de CARTO (datos de OSM) y
manda los enlaces del tablero al repositorio.
"""

import shutil
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
FRONT = RAIZ / "frontend"
FUERA = ("medios",)  # videos y GIF de la entrega: ~110 MB que la pagina no carga

REDIRECCION = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>El Ojo de Tlaloc</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="0; url=nisar/">
<link rel="canonical" href="nisar/">
<link rel="icon" type="image/png" href="favicon.png">
<style>body{background:#0f1214;color:#e7e9eb;font:16px system-ui,sans-serif;padding:24px}a{color:#7cc4dc}</style>
</head>
<body><p><a href="nisar/">El baile del agua, visto por radar &rarr;</a></p></body>
</html>
"""


def main(destino: str) -> None:
    out = Path(destino).resolve()
    if out == RAIZ or RAIZ not in out.parents:
        sys.exit("el destino tiene que ser una carpeta dentro del repositorio")
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    shutil.copytree(
        FRONT / "nisar", out / "nisar",
        ignore=lambda d, nombres: [n for n in nombres if n in FUERA and Path(d).name == "datos"],
    )
    shutil.copytree(FRONT / "vendor", out / "vendor")
    for f in ("logo.png", "favicon.png"):
        shutil.copy2(FRONT / f, out / f)
    (out / "index.html").write_text(REDIRECCION, encoding="utf-8")

    total = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print("sitio en {} ({:.1f} MB)".format(out, total / 1e6))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "_sitio")
