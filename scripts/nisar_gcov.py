"""NISAR GCOV sobre la zona conurbada Veracruz-Boca del Rio.

buscar: granulos en el catalogo de ASF (sin cuenta). vista: recorta la vista
previa publica de cada fecha y arma un GIF (sin cuenta). extraer: lee del HDF5
remoto solo la ventana de la zona (HH y HV, gamma0 lineal) y guarda GeoTIFF,
PNG en dB y un resumen por fecha. Requiere EARTHDATA_TOKEN o ~/.netrc.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parents[1]
ENTRADA = RAIZ / "datos" / "entrada" / "nisar"
SALIDA = RAIZ / "datos" / "salida" / "nisar"
MANIFIESTO = ENTRADA / "manifiesto.json"

BBOX_CONURBADA = (-96.26, 19.03, -96.06, 19.24)
API_ASF = "https://api.daac.asf.alaska.edu/services/search/param"
RANGOS_DB = {"HHHH": (-25.0, 0.0), "HVHV": (-32.0, -8.0), "RAZON": (0.0, 15.0)}
UMBRAL_OSCURO_HH_DB = -18.0


def _poligono_wkt(bbox):
    w, s, e, n = bbox
    return "POLYGON(({w} {s},{e} {s},{e} {n},{w} {n},{w} {s}))".format(
        w=w, s=s, e=e, n=n)


def _dentro(lon, lat, anillo):
    adentro = False
    j = len(anillo) - 1
    for i in range(len(anillo)):
        xi, yi = anillo[i]
        xj, yj = anillo[j]
        if (yi > lat) != (yj > lat) and \
                lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            adentro = not adentro
        j = i
    return adentro


def _cubre(geometria, bbox):
    w, s, e, n = bbox
    anillo = geometria["coordinates"][0]
    return all(_dentro(x, y, anillo) for x, y in ((w, s), (e, s), (e, n), (w, n)))


def _partes(nombre):
    p = nombre.split("_")
    return {
        "ciclo": p[4], "pista": p[5], "direccion": p[6], "cuadro": p[7],
        "modo": p[8], "polarizacion": p[9], "fecha": p[11][:8],
        "contador": p[-1],
    }


def _clave_pista(g):
    return "{}{}{}".format(g["pista"], g["direccion"], g["cuadro"])


def buscar(bbox, desde, hasta):
    params = {
        "dataset": "NISAR", "processingLevel": "GCOV",
        "intersectsWith": _poligono_wkt(bbox), "output": "geojson",
        "maxResults": 2000,
    }
    if desde:
        params["start"] = desde + "T00:00:00Z"
    if hasta:
        params["end"] = hasta + "T23:59:59Z"
    url = API_ASF + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=120) as r:
        rasgos = json.load(r)["features"]

    granulos = []
    for f in rasgos:
        p = f["properties"]
        nombre = p["fileID"]
        h5 = [v["bytes"] for k, v in p["bytes"].items()
              if k.endswith(".h5") and "QA" not in k]
        g = _partes(nombre)
        g.update({
            "nombre": nombre, "url": p["url"],
            "vista": next((b for b in p.get("browse") or []
                           if b.endswith("_LATLON.png")), None),
            "procesado": p.get("processingDate"),
            "bytes": h5[0] if h5 else None,
            "cubre_zona": _cubre(f["geometry"], bbox),
        })
        granulos.append(g)

    unicos = {}
    for g in sorted(granulos, key=lambda g: (g["contador"], g["procesado"] or "")):
        unicos[(_clave_pista(g), g["modo"], g["fecha"])] = g
    granulos = sorted(unicos.values(), key=lambda g: (_clave_pista(g), g["modo"], g["fecha"]))

    ENTRADA.mkdir(parents=True, exist_ok=True)
    MANIFIESTO.write_text(json.dumps(
        {"bbox": bbox, "granulos": granulos}, indent=1, ensure_ascii=False))
    return granulos


def _pistas(granulos):
    grupos = {}
    for g in granulos:
        if g["cubre_zona"]:
            grupos.setdefault((_clave_pista(g), g["modo"]), []).append(g)
    return grupos


def _elegir(granulos, pista, modo, maximo):
    grupos = _pistas(granulos)
    if not grupos:
        sys.exit("ningun granulo cubre la zona completa")
    if pista is None:
        pista, modo_auto = max(grupos, key=lambda k: (len(grupos[k]), k[1]))
        modo = modo or modo_auto
    if modo is None:
        modo = max((k[1] for k in grupos if k[0] == pista), default=None)
    elegidos = grupos.get((pista, modo))
    if not elegidos:
        sys.exit("no hay granulos para la pista {} modo {}; opciones: {}".format(
            pista, modo, ", ".join("{} modo {}".format(*k) for k in grupos)))
    if maximo and len(elegidos) > maximo:
        idx = np.unique(np.linspace(0, len(elegidos) - 1, maximo).round().astype(int))
        elegidos = [elegidos[i] for i in idx]
    return pista, modo, elegidos


def _cargar_manifiesto(args):
    if args.rebuscar or not MANIFIESTO.exists():
        return buscar(tuple(args.bbox), args.desde, args.hasta)
    datos = json.loads(MANIFIESTO.read_text())
    if tuple(datos["bbox"]) != tuple(args.bbox):
        return buscar(tuple(args.bbox), args.desde, args.hasta)
    return datos["granulos"]


def cmd_buscar(args):
    granulos = buscar(tuple(args.bbox), args.desde, args.hasta)
    print("{} granulos GCOV tocan la zona; manifiesto en {}".format(
        len(granulos), MANIFIESTO.relative_to(RAIZ)))
    for (pista, modo), gs in sorted(_pistas(granulos).items(), key=lambda kv: -len(kv[1])):
        gb = sum(g["bytes"] or 0 for g in gs) / 1e9
        print("  pista {} modo {}: {} fechas, {:.0f} GB completos  {}".format(
            pista, modo, len(gs), gb, " ".join(g["fecha"][4:] for g in gs)))
    fuera = sum(not g["cubre_zona"] for g in granulos)
    if fuera:
        print("  ({} granulos solo la tocan en parte y se ignoran)".format(fuera))


def _descargar(url):
    with urllib.request.urlopen(url, timeout=180) as r:
        return r.read()


def _limites_kml(url_png):
    from PIL import Image

    if not url_png:
        return None
    try:
        kml = _descargar(url_png[:-4] + ".kml").decode()
    except urllib.error.HTTPError:
        return None
    coords = re.search(r"<coordinates>(.*?)</coordinates>", kml, re.S).group(1)
    pares = [tuple(map(float, c.split(","))) for c in coords.split()]
    tam = Image.open(io.BytesIO(_descargar(url_png))).size
    return (min(p[0] for p in pares), min(p[1] for p in pares),
            max(p[0] for p in pares), max(p[1] for p in pares), tam)


def cmd_vista(args):
    from PIL import Image

    granulos = _cargar_manifiesto(args)
    pista, modo, elegidos = _elegir(granulos, args.pista, args.modo, args.max)
    w, s, e, n = args.bbox
    destino = SALIDA / "vista" / "{}_{}".format(pista, modo)
    destino.mkdir(parents=True, exist_ok=True)
    limites = None
    for g in reversed(elegidos):
        limites = _limites_kml(g["vista"])
        if limites:
            break
    if not limites:
        sys.exit("ninguna fecha de la pista {} trae KML publico; usa extraer".format(pista))
    lon0, lat0, lon1, lat1, tam = limites
    cuadros = []
    for g in elegidos:
        if not g["vista"]:
            continue
        img = Image.open(io.BytesIO(_descargar(g["vista"]))).convert("RGB")
        if img.size != tam:
            print("  {}  vista de otro tamano, se omite".format(g["fecha"]))
            continue
        ancho, alto = img.size
        caja = (
            round((w - lon0) / (lon1 - lon0) * ancho),
            round((lat1 - n) / (lat1 - lat0) * alto),
            round((e - lon0) / (lon1 - lon0) * ancho),
            round((lat1 - s) / (lat1 - lat0) * alto),
        )
        recorte = img.crop(caja)
        recorte = recorte.resize((recorte.width * 4, recorte.height * 4), Image.NEAREST)
        recorte.save(destino / "{}.png".format(g["fecha"]))
        cuadros.append(recorte)
        print("  {}  {}x{} px de vista previa".format(g["fecha"], *recorte.size))
    if cuadros:
        cuadros[0].save(destino / "serie.gif", save_all=True,
                        append_images=cuadros[1:], duration=700, loop=0)
        print("vista previa en {}".format(destino.relative_to(RAIZ)))


def _abrir_remotos(urls):
    import earthaccess

    auth = None
    for estrategia in ("environment", "netrc"):
        try:
            auth = earthaccess.login(strategy=estrategia)
        except Exception:
            auth = None
        if auth is not None and auth.authenticated:
            break
    if auth is None or not auth.authenticated:
        sys.exit("falta login de Earthdata: exporta EARTHDATA_TOKEN o crea "
                 "~/.netrc con machine urs.earthdata.nasa.gov")
    return earthaccess.open(urls, show_progress=False, open_kwargs={
        "cache_type": "blockcache", "block_size": 8 * 2**20})


def _grilla(h5):
    for ruta in ("science/LSAR/GCOV/grids/frequencyA",
                 "science/SSAR/GCOV/grids/frequencyA"):
        if ruta in h5:
            return h5[ruta]
    encontrados = []
    h5.visit(lambda k: encontrados.append(k) if k.endswith("frequencyA") else None)
    if not encontrados:
        raise KeyError("no encuentro grids/frequencyA en el HDF5")
    return h5[encontrados[0]]


def _epsg(grilla):
    proy = grilla["projection"]
    for clave in ("epsg_code", "epsg"):
        if clave in proy.attrs:
            return int(np.asarray(proy.attrs[clave]).ravel()[0])
    return int(np.asarray(proy[()]).ravel()[0])


def _ventana(coords, bajo, alto):
    idx = np.flatnonzero((coords >= bajo) & (coords <= alto))
    if idx.size == 0:
        raise ValueError("la zona cae fuera de la grilla")
    return int(idx.min()), int(idx.max()) + 1


def _a_db(lineal):
    with np.errstate(divide="ignore", invalid="ignore"):
        return 10.0 * np.log10(np.where(lineal > 0, lineal, np.nan))


def _escalar(db, rango):
    lo, hi = rango
    u = np.clip((db - lo) / (hi - lo), 0.0, 1.0)
    return np.where(np.isfinite(u), u * 255.0, 0.0).astype(np.uint8)


def _png(bandas, ruta):
    from PIL import Image

    hh = _a_db(bandas["HHHH"])
    if "HVHV" in bandas:
        hv = _a_db(bandas["HVHV"])
        rgb = np.dstack([_escalar(hh, RANGOS_DB["HHHH"]),
                         _escalar(hv, RANGOS_DB["HVHV"]),
                         _escalar(hh - hv, RANGOS_DB["RAZON"])])
        Image.fromarray(rgb, "RGB").save(ruta)
    else:
        Image.fromarray(_escalar(hh, RANGOS_DB["HHHH"]), "L").save(ruta)


def _extraer_uno(archivo, g, bbox, destino):
    import h5py
    import rasterio
    from rasterio.transform import from_origin
    from rasterio.warp import transform_bounds

    with h5py.File(archivo, "r") as h5:
        grilla = _grilla(h5)
        epsg = _epsg(grilla)
        x = grilla["xCoordinates"][()]
        y = grilla["yCoordinates"][()]
        minx, miny, maxx, maxy = transform_bounds(
            "EPSG:4326", "EPSG:{}".format(epsg), *bbox, densify_pts=21)
        c0, c1 = _ventana(x, minx, maxx)
        f0, f1 = _ventana(y, miny, maxy)
        pols = [p for p in ("HHHH", "HVHV", "VVVV", "VHVH") if p in grilla]
        bandas = {}
        for p in pols:
            datos = grilla[p][f0:f1, c0:c1].astype(np.float32)
            datos[~np.isfinite(datos) | (datos <= 0)] = np.nan
            bandas[p] = datos

    dx = float(x[1] - x[0])
    dy = float(y[1] - y[0])
    origen_x = float(x[c0]) - dx / 2.0
    origen_y = float(y[f0]) - dy / 2.0
    if dy < 0:
        transformada = from_origin(origen_x, origen_y, dx, -dy)
        orden = slice(None)
    else:
        transformada = from_origin(origen_x, float(y[f1 - 1]) + dy / 2.0, dx, dy)
        orden = slice(None, None, -1)

    nombre = "{}_{}".format(g["fecha"], _clave_pista(g))
    tif = destino / (nombre + ".tif")
    perfil = {
        "driver": "GTiff", "dtype": "float32", "count": len(bandas),
        "width": c1 - c0, "height": f1 - f0, "crs": "EPSG:{}".format(epsg),
        "transform": transformada, "nodata": np.nan, "compress": "deflate",
        "predictor": 3, "tiled": True,
    }
    with rasterio.open(tif, "w", **perfil) as dst:
        for i, (p, datos) in enumerate(bandas.items(), start=1):
            dst.write(datos[orden], i)
            dst.set_band_description(i, "gamma0_" + p)
        dst.update_tags(granulo=g["nombre"], fecha=g["fecha"],
                        pista=g["pista"], direccion=g["direccion"],
                        cuadro=g["cuadro"], unidades="gamma0 lineal (potencia)")
    _png({k: v[orden] for k, v in bandas.items()}, destino / (nombre + ".png"))

    hh_db = _a_db(bandas["HHHH"])
    validos = np.isfinite(hh_db)
    resumen = {
        "fecha": g["fecha"], "granulo": g["nombre"], "epsg": epsg,
        "pixel_m": abs(dx), "ancho_px": c1 - c0, "alto_px": f1 - f0,
        "fraccion_valida": round(float(validos.mean()), 4),
        "hh_db_mediana": round(float(np.nanmedian(hh_db)), 2),
        "fraccion_hh_bajo_{:g}db".format(UMBRAL_OSCURO_HH_DB): round(
            float((hh_db[validos] < UMBRAL_OSCURO_HH_DB).mean()), 4),
    }
    if "HVHV" in bandas:
        resumen["hv_db_mediana"] = round(float(np.nanmedian(_a_db(bandas["HVHV"]))), 2)
    return resumen


def cmd_extraer(args):
    granulos = _cargar_manifiesto(args)
    pista, modo, elegidos = _elegir(granulos, args.pista, args.modo, args.max)
    destino = SALIDA / "gcov" / "{}_{}".format(pista, modo)
    destino.mkdir(parents=True, exist_ok=True)
    pendientes = [g for g in elegidos if args.forzar or not
                  (destino / "{}_{}.tif".format(g["fecha"], _clave_pista(g))).exists()]
    print("pista {} modo {}: {} fechas, {} por extraer".format(
        pista, modo, len(elegidos), len(pendientes)))

    archivos = _abrir_remotos([g["url"] for g in pendientes]) if pendientes else []
    for g, archivo in zip(pendientes, archivos):
        try:
            r = _extraer_uno(archivo, g, tuple(args.bbox), destino)
        except Exception as exc:
            print("  {}  fallo: {}".format(g["fecha"], exc))
            continue
        (destino / "{}_{}.json".format(g["fecha"], _clave_pista(g))).write_text(
            json.dumps(r, indent=1))
        print("  {}  {}x{} px a {:.0f} m, HH mediana {} dB".format(
            g["fecha"], r["ancho_px"], r["alto_px"], r["pixel_m"], r["hh_db_mediana"]))

    filas = [json.loads(p.read_text()) for p in sorted(destino.glob("*.json"))]
    if filas:
        with open(destino / "resumen.csv", "w", newline="") as f:
            campos = sorted({k for fila in filas for k in fila},
                            key=lambda k: (k != "fecha", k))
            escritor = csv.DictWriter(f, fieldnames=campos)
            escritor.writeheader()
            escritor.writerows(filas)
        print("resultado en {}".format(destino.relative_to(RAIZ)))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="comando", required=True)
    for nombre, fn in (("buscar", cmd_buscar), ("vista", cmd_vista),
                       ("extraer", cmd_extraer)):
        sp = sub.add_parser(nombre)
        sp.set_defaults(fn=fn)
        sp.add_argument("--bbox", type=float, nargs=4, default=list(BBOX_CONURBADA),
                        metavar=("OESTE", "SUR", "ESTE", "NORTE"))
        sp.add_argument("--desde", default=None, help="AAAA-MM-DD")
        sp.add_argument("--hasta", default=None, help="AAAA-MM-DD")
        if nombre != "buscar":
            sp.add_argument("--pista", default=None, help="p. ej. 163A011")
            sp.add_argument("--modo", default=None, help="p. ej. 4005")
            sp.add_argument("--max", type=int, default=0,
                            help="cuantas fechas, repartidas en la serie")
            sp.add_argument("--rebuscar", action="store_true")
        if nombre == "extraer":
            sp.add_argument("--forzar", action="store_true")
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
