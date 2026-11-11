"""Productos de NISAR para la historia de Veracruz-Boca del Rio (frontend/nisar).

Filtra el moteado (Lee) de la serie GCOV, la normaliza contra blancos urbanos estables,
clasifica agua con el valle del histograma, separa mar y pistas, mide cambio y humedad
del suelo por deteccion de cambio, lo cruza con lluvia de NASA POWER y con escuelas
y hospitales de OSM en la malla hexagonal, y escribe imagenes Web Mercator.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import urllib.request
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.features import rasterize
from rasterio.warp import Resampling, calculate_default_transform, reproject, transform, transform_geom
from scipy import ndimage
from skimage import filters, measure, morphology

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))

from ojo_tlaloc.fuentes.osm import INFRAESTRUCTURA_CRITICA, FuenteOSM
from ojo_tlaloc.malla import MallaHexagonal

SERIE = RAIZ / "datos" / "salida" / "nisar" / "gcov" / "163A011_4005"
SALIDA = RAIZ / "frontend" / "nisar" / "datos"
BBOX = (-96.26, 19.03, -96.06, 19.24)
PIXEL_WEB_M = 12.0
PASO_SERIE = 8
VENTANA_LEE = 5
RANGO_DB = {"hh": (-24.0, 0.0), "hv": (-31.0, -8.0), "razon": (2.0, 14.0)}
CAMBIO_MIN_DB, CAMBIO_MAX_DB = 1.5, 6.0
CUANTIZA_DB = (-35.0, 5.0)
LLUVIA_PUNTO = (19.15, -96.15)
GRUPOS_EXPOSICION = {
    "escuelas": {"school", "kindergarten", "university", "college"},
    "salud": {"hospital", "clinic", "doctors", "nursing_home"},
    "emergencia": {"fire_station", "police", "shelter", "social_facility"},
}


def leer_serie():
    tifs = sorted(SERIE.glob("2026*_163A011.tif"))
    if not tifs:
        sys.exit("no hay GeoTIFF en {}; corre antes nisar_gcov.py extraer".format(SERIE))
    hh, hv, fechas, granulos = [], [], [], []
    for t in tifs:
        with rasterio.open(t) as src:
            hh.append(src.read(1))
            hv.append(src.read(2))
            perfil = src.profile
            etiquetas = src.tags()
        f = etiquetas["fecha"]
        fechas.append("{}-{}-{}".format(f[:4], f[4:6], f[6:]))
        granulos.append(etiquetas["granulo"])
    return np.stack(hh), np.stack(hv), fechas, granulos, perfil


def lee(img, ventana=VENTANA_LEE):
    img = np.nan_to_num(img, nan=0.0).astype(np.float64)
    media = ndimage.uniform_filter(img, ventana)
    media2 = ndimage.uniform_filter(img * img, ventana)
    var = np.maximum(media2 - media * media, 0.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        cv2 = np.where(media > 0, var / (media * media), np.nan)
    cu2 = float(np.nanpercentile(cv2[::7, ::7], 10))
    with np.errstate(divide="ignore", invalid="ignore"):
        peso = np.clip((var - media * media * cu2) / np.where(var > 0, var, 1.0), 0.0, 1.0)
    return (media + peso * (img - media)).astype(np.float32)


def umbral_valle(muestra, lo=-35.0, hi=0.0, paso=0.5):
    muestra = muestra[np.isfinite(muestra) & (muestra > lo) & (muestra < hi)]
    cuentas, bordes = np.histogram(muestra, bins=int((hi - lo) / paso), range=(lo, hi))
    suave = np.convolve(cuentas, np.ones(7) / 7.0, mode="same")
    centros = (bordes[:-1] + bordes[1:]) / 2.0
    picos = [i for i in range(1, len(suave) - 1) if suave[i] >= suave[i - 1] and suave[i] >= suave[i + 1]
             and suave[i] > 0.05 * suave.max()]
    tierra = max(picos, key=lambda i: suave[i])
    agua = [i for i in picos if centros[tierra] - centros[i] >= 5.0]
    if not agua:
        return float(filters.threshold_otsu(muestra))
    agua = max(agua, key=lambda i: suave[i])
    valle = agua + int(np.argmin(suave[agua:tierra + 1]))
    return float(centros[valle])


def indice_humedad(hh_db, suelo):
    orden = np.sort(hh_db, axis=0)
    seco, mojado = orden[1], orden[-2]
    rango = np.maximum(mojado - seco, 1.5)
    idx = np.clip((hh_db - seco[None]) / rango[None], 0.0, 1.0)
    idx = np.stack([ndimage.uniform_filter(np.where(suelo, x, 0.0), 9) /
                    np.maximum(ndimage.uniform_filter(suelo.astype(np.float32), 9), 1e-3) for x in idx])
    return np.where(suelo[None], idx, np.nan).astype(np.float32)


def a_db(x):
    with np.errstate(divide="ignore", invalid="ignore"):
        return (10.0 * np.log10(np.maximum(x, 1e-7))).astype(np.float32)


def overpass(fuente, cuerpo, clave):
    return fuente._consulta("[out:json][timeout:180];({});out geom;".format(cuerpo), clave)


def osm_zona(fuente):
    s, w, n, e = BBOX[1], BBOX[0], BBOX[3], BBOX[2]
    bb = "{},{},{},{}".format(s, w, n, e)
    agua = overpass(fuente, 'nwr["natural"~"^(water|wetland)$"]({bb});'
                    'way["waterway"~"^(river|stream|canal|drain)$"]({bb});'.format(bb=bb),
                    "nisar-agua|" + bb)
    pistas = overpass(fuente, 'nwr["aeroway"~"^(runway|taxiway|apron)$"]({bb});'.format(bb=bb),
                      "nisar-pistas|" + bb)
    lugares = fuente._consulta(
        '[out:json][timeout:120];node["place"~"^(city|town|suburb|neighbourhood|village|island|islet)$"]({bb});out;'
        .format(bb=bb), "nisar-lugares|" + bb)
    return agua, pistas, lugares


def geometrias(elementos, crs):
    salida = []
    for el in elementos:
        geom = el.get("geometry")
        if el["type"] == "way" and geom:
            coords = [(p["lon"], p["lat"]) for p in geom]
            cerrado = len(coords) > 3 and coords[0] == coords[-1]
            g = {"type": "Polygon", "coordinates": [coords]} if cerrado else \
                {"type": "LineString", "coordinates": coords}
            salida.append((transform_geom("EPSG:4326", crs, g), el.get("tags", {})))
        elif el["type"] == "relation":
            for m in el.get("members", []):
                if m.get("role") == "outer" and m.get("geometry"):
                    coords = [(p["lon"], p["lat"]) for p in m["geometry"]]
                    if len(coords) > 3 and coords[0] == coords[-1]:
                        g = {"type": "Polygon", "coordinates": [coords]}
                    else:
                        g = {"type": "LineString", "coordinates": coords}
                    salida.append((transform_geom("EPSG:4326", crs, g), el.get("tags", {})))
    return salida


def poligonos_osm(elementos):
    for el in elementos:
        tags = el.get("tags", {})
        if el["type"] == "way" and el.get("geometry"):
            anillo = [(p["lon"], p["lat"]) for p in el["geometry"]]
            if len(anillo) > 3 and anillo[0] == anillo[-1]:
                yield anillo, tags
        elif el["type"] == "relation":
            for m in el.get("members", []):
                if m.get("role") == "outer" and m.get("geometry"):
                    anillo = [(p["lon"], p["lat"]) for p in m["geometry"]]
                    if len(anillo) > 3 and anillo[0] == anillo[-1]:
                        yield anillo, tags


def centro_de(el):
    if "center" in el:
        return el["center"]["lon"], el["center"]["lat"]
    if "lon" in el:
        return el["lon"], el["lat"]
    geom = el.get("geometry") or [p for m in el.get("members", []) for p in (m.get("geometry") or [])]
    if not geom:
        return None
    return float(np.mean([p["lon"] for p in geom])), float(np.mean([p["lat"] for p in geom]))


def lluvia_power(fechas):
    inicio = (dt.date.fromisoformat(fechas[0]) - dt.timedelta(days=30)).strftime("%Y%m%d")
    fin = dt.date.fromisoformat(fechas[-1]).strftime("%Y%m%d")
    url = ("https://power.larc.nasa.gov/api/temporal/daily/point?parameters=PRECTOTCORR"
           "&community=AG&longitude={}&latitude={}&start={}&end={}&format=JSON").format(
        LLUVIA_PUNTO[1], LLUVIA_PUNTO[0], inicio, fin)
    cache = RAIZ / "datos" / "entrada" / "nisar" / "power_{}_{}.json".format(inicio, fin)
    if cache.exists():
        datos = json.loads(cache.read_text())
    else:
        with urllib.request.urlopen(url, timeout=120) as r:
            datos = json.load(r)
        cache.write_text(json.dumps(datos))
    serie = datos["properties"]["parameter"]["PRECTOTCORR"]
    diaria = [{"fecha": "{}-{}-{}".format(k[:4], k[4:6], k[6:]),
               "mm": None if v is None or v < 0 else round(float(v), 2)}
              for k, v in sorted(serie.items())]
    return diaria, url


def acumulada(diaria, fecha, dias):
    f = dt.date.fromisoformat(fecha)
    desde = (f - dt.timedelta(days=dias)).isoformat()
    vals = [d["mm"] for d in diaria if desde <= d["fecha"] < fecha and d["mm"] is not None]
    return round(float(sum(vals)), 1)


def grilla_web(perfil):
    alto, ancho = perfil["height"], perfil["width"]
    izq, abajo = perfil["transform"] * (0, alto)
    der, arriba = perfil["transform"] * (ancho, 0)
    trans, w, h = calculate_default_transform(
        perfil["crs"], "EPSG:3857", ancho, alto, izq, abajo, der, arriba, resolution=PIXEL_WEB_M)
    x0, y0 = trans * (0, 0)
    x1, y1 = trans * (w, h)
    lon, lat = transform("EPSG:3857", "EPSG:4326", [x0, x1, x1, x0], [y0, y0, y1, y1])
    esquinas = [[round(lo, 6), round(la, 6)] for lo, la in zip(lon, lat)]
    return trans, w, h, esquinas, (x0, y1, x1, y0)


def a_web(arr, perfil, trans, w, h, metodo=Resampling.bilinear, relleno=np.nan):
    dst = np.full((h, w), relleno, dtype=np.float32)
    reproject(arr.astype(np.float32), dst, src_transform=perfil["transform"], src_crs=perfil["crs"],
              dst_transform=trans, dst_crs="EPSG:3857", resampling=metodo,
              src_nodata=np.nan, dst_nodata=relleno)
    return dst


def escala(db, rango, gamma=1.0):
    lo, hi = rango
    u = np.clip((db - lo) / (hi - lo), 0.0, 1.0) ** gamma
    return np.where(np.isfinite(db), u, 0.0)


def guardar(img, nombre, calidad=82):
    ruta = SALIDA / "img" / nombre
    if nombre.endswith(".webp"):
        img.save(ruta, "WEBP", quality=calidad, method=6)
    else:
        img.save(ruta, optimize=True)
    return "img/" + nombre


def rampa(valores, paradas):
    xs = np.array([p[0] for p in paradas])
    cols = np.array([p[1] for p in paradas], dtype=float)
    salida = np.zeros(valores.shape + (cols.shape[1],))
    for c in range(cols.shape[1]):
        salida[..., c] = np.interp(valores, xs, cols[:, c])
    return salida


def main():
    (SALIDA / "img").mkdir(parents=True, exist_ok=True)
    hh, hv, fechas, granulos, perfil = leer_serie()
    n, alto, ancho = hh.shape
    crs = perfil["crs"].to_string()
    print("serie: {} fechas, {}x{} px, {}".format(n, ancho, alto, crs))

    hh_f = np.stack([lee(x) for x in hh])
    hv_f = np.stack([lee(x) for x in hv])
    hh_db, hv_db = a_db(hh_f), a_db(hv_f)
    del hh_f, hv_f
    estables = np.median(hh_db, axis=0) > -2.0
    crudo_hh = [float(np.median(x[estables])) for x in hh_db]
    crudo_hv = [float(np.median(x[estables])) for x in hv_db]
    ajuste_hh = np.array(crudo_hh) - np.mean(crudo_hh)
    ajuste_hv = np.array(crudo_hv) - np.mean(crudo_hv)
    hh_db -= ajuste_hh[:, None, None].astype(np.float32)
    hv_db -= ajuste_hv[:, None, None].astype(np.float32)
    print("ajuste radiometrico por fecha contra blancos urbanos (dB):", np.round(ajuste_hh, 2).tolist())

    muestra_hh = hh_db[:, ::5, ::5].ravel()
    muestra_hv = hv_db[:, ::5, ::5].ravel()
    t_hh = umbral_valle(muestra_hh)
    t_hv = umbral_valle(muestra_hv)
    otsu_hh = float(filters.threshold_otsu(muestra_hh[(muestra_hh > -35) & (muestra_hh < 5)]))
    print("umbrales de agua (valle): HH < {:.1f} dB y HV < {:.1f} dB (Otsu HH daba {:.1f})".format(
        t_hh, t_hv, otsu_hh))

    agua = (hh_db < t_hh) & (hv_db < t_hv)
    agua = np.stack([morphology.remove_small_holes(
        morphology.remove_small_objects(a, 30), 30) for a in agua])

    fuente = FuenteOSM()
    osm_agua, osm_pistas, osm_lugares = osm_zona(fuente)
    geo_pistas = [g for g, _ in geometrias(osm_pistas["elements"], crs)]
    pista = np.zeros((alto, ancho), bool)
    if geo_pistas:
        pista = rasterize([(g, 1) for g in geo_pistas], out_shape=(alto, ancho),
                          transform=perfil["transform"], all_touched=True).astype(bool)
        pista = ndimage.binary_dilation(pista, iterations=10)

    frec_total = agua.mean(axis=0)
    candidatos = measure.label(frec_total >= 0.5, connectivity=2)
    tocan_este = np.unique(candidatos[:, -1])
    mar = np.isin(candidatos, tocan_este[tocan_este > 0])
    mar = morphology.remove_small_holes(mar, 2000)
    mar = ndimage.binary_dilation(mar, iterations=3)
    playa = ndimage.binary_dilation(mar, iterations=15) & ~mar
    tierra = ~mar & ~pista & ~playa

    agua_tierra = agua & tierra[None]
    frec = np.where(tierra, agua_tierra.mean(axis=0), np.nan).astype(np.float32)
    permanente = tierra & (frec >= 0.8)
    estacional = tierra & (frec >= 0.2) & (frec < 0.8)
    ocasional = tierra & (frec > 0) & (frec < 0.2)
    km2 = 100.0 / 1e6
    area_agua = [round(float(a.sum() * km2), 3) for a in agua_tierra]
    area_temporal = [round(float((a & ~permanente).sum() * km2), 3) for a in agua_tierra]
    print("agua en tierra por fecha (km2):", area_agua)

    mediana_hh = np.median(hh_db, axis=0)
    mediana_hv = np.median(hv_db, axis=0)
    urbano = ndimage.binary_dilation(mediana_hh > -3.0, iterations=2)
    suelo = tierra & ~urbano & ~permanente & (np.nan_to_num(frec) < 0.2)
    humedad = indice_humedad(hh_db, suelo)
    humedad_media = [round(float(np.nanmean(x)), 3) for x in humedad]
    campo_hh = [round(float(np.mean(x[suelo])), 2) for x in hh_db]
    campo_hv = [round(float(np.mean(x[suelo])), 2) for x in hv_db]
    print("indice de humedad medio por fecha:", humedad_media)

    diaria, url_power = lluvia_power(fechas)
    lluvia = []
    for i, f in enumerate(fechas):
        previa = fechas[i - 1] if i else (dt.date.fromisoformat(f) - dt.timedelta(days=12)).isoformat()
        dias = (dt.date.fromisoformat(f) - dt.date.fromisoformat(previa)).days
        lluvia.append({"fecha": f, "previos_3d_mm": acumulada(diaria, f, 3),
                       "previos_7d_mm": acumulada(diaria, f, 7),
                       "desde_paso_anterior_mm": acumulada(diaria, f, dias),
                       "dias_desde_paso_anterior": dias})
    l3 = [l["previos_3d_mm"] for l in lluvia]
    l7 = [l["previos_7d_mm"] for l in lluvia]
    r_lluvia = float(np.corrcoef(l7, area_temporal)[0, 1])
    correlaciones = {
        "agua_temporal_vs_lluvia_7d": round(r_lluvia, 3),
        "agua_temporal_vs_lluvia_3d": round(float(np.corrcoef(l3, area_temporal)[0, 1]), 3),
        "humedad_vs_lluvia_3d": round(float(np.corrcoef(l3, humedad_media)[0, 1]), 3),
        "humedad_vs_lluvia_7d": round(float(np.corrcoef(l7, humedad_media)[0, 1]), 3),
        "campo_hh_vs_lluvia_3d": round(float(np.corrcoef(l3, campo_hh)[0, 1]), 3),
    }
    print("correlaciones:", correlaciones)

    etiquetas_zonas = measure.label(ndimage.binary_closing(estacional | permanente, iterations=3)
                                    & tierra, connectivity=2)
    props = sorted(measure.regionprops(etiquetas_zonas), key=lambda p: -p.area)
    nombres_agua = []
    for el in osm_agua["elements"]:
        nombre = el.get("tags", {}).get("name")
        c = centro_de(el)
        if nombre and c:
            x, y = transform("EPSG:4326", crs, [c[0]], [c[1]])
            nombres_agua.append((nombre, x[0], y[0], el.get("tags", {})))
    zonas = []
    for p in props[:8]:
        filas, cols = p.coords[:, 0], p.coords[:, 1]
        cy, cx = p.centroid
        xm, ym = perfil["transform"] * (cx, cy)
        lon, lat = transform(crs, "EPSG:4326", [xm], [ym])
        cercano = min(nombres_agua, key=lambda t: (t[1] - xm) ** 2 + (t[2] - ym) ** 2, default=None)
        dist = None if cercano is None else float(np.hypot(cercano[1] - xm, cercano[2] - ym))
        sel = np.zeros((alto, ancho), bool)
        sel[filas, cols] = True
        x0, y0 = perfil["transform"] * (cols.min(), filas.max())
        x1, y1 = perfil["transform"] * (cols.max(), filas.min())
        blon, blat = transform(crs, "EPSG:4326", [x0, x1], [y0, y1])
        zonas.append({
            "id": "z{}".format(len(zonas) + 1),
            "centro": [round(lon[0], 5), round(lat[0], 5)],
            "caja": [round(blon[0], 5), round(blat[0], 5), round(blon[1], 5), round(blat[1], 5)],
            "area_max_km2": round(float((agua_tierra[:, sel]).sum(axis=1).max() * km2), 3),
            "area_km2": [round(float(a[sel].sum() * km2), 3) for a in agua_tierra],
            "permanente_km2": round(float((permanente & sel).sum() * km2), 3),
            "estacional_km2": round(float((estacional & sel).sum() * km2), 3),
            "nombre_osm_cercano": cercano[0] if cercano else None,
            "distancia_nombre_m": None if dist is None else round(dist),
            "delta_hh_db": [round(float(np.nanmean(hh_db[i][sel] - mediana_hh[sel])), 2) for i in range(n)],
        })
    print("zonas:", [(z["id"], z["nombre_osm_cercano"], z["distancia_nombre_m"], z["area_max_km2"]) for z in zonas])

    infra = FuenteOSM().descargar(MallaHexagonal())["infraestructura"]["elements"]
    pois = []
    for el in infra:
        c = centro_de(el)
        if not c or not (BBOX[0] <= c[0] <= BBOX[2] and BBOX[1] <= c[1] <= BBOX[3]):
            continue
        tipo = el.get("tags", {}).get("amenity", "")
        grupo = next((g for g, tipos in GRUPOS_EXPOSICION.items() if tipo in tipos), None)
        if grupo:
            pois.append({"lon": c[0], "lat": c[1], "tipo": tipo, "grupo": grupo,
                         "nombre": el.get("tags", {}).get("name")})
    px, py = transform("EPSG:4326", crs, [p["lon"] for p in pois], [p["lat"] for p in pois])
    inv = ~perfil["transform"]
    agua_no_perm = (agua_tierra & ~permanente[None]).any(axis=0) & (estacional | ocasional)
    dist_estacional = ndimage.distance_transform_edt(~agua_no_perm) * 10.0
    for p, x, y in zip(pois, px, py):
        c, f = inv * (x, y)
        c, f = int(c), int(f)
        dentro = 0 <= f < alto and 0 <= c < ancho
        p["dist_agua_temporal_m"] = round(float(dist_estacional[f, c])) if dentro else None
        p["fechas_con_agua_200m"] = []
        if dentro:
            f0, f1 = max(0, f - 20), min(alto, f + 21)
            c0, c1 = max(0, c - 20), min(ancho, c + 21)
            for i in range(n):
                if (agua_tierra[i, f0:f1, c0:c1] & ~permanente[f0:f1, c0:c1]).sum() >= 20:
                    p["fechas_con_agua_200m"].append(fechas[i])
    expuestos = [p for p in pois if p["dist_agua_temporal_m"] is not None and p["dist_agua_temporal_m"] <= 200]
    resumen_exposicion = {g: {"total": sum(p["grupo"] == g for p in pois),
                              "a_200m_de_agua_temporal": sum(p["grupo"] == g for p in expuestos)}
                          for g in GRUPOS_EXPOSICION}
    print("exposicion:", resumen_exposicion)

    malla = MallaHexagonal().nivel_siguiente().nivel_siguiente()
    celdas = [i for i in range(malla.n_celdas)
              if BBOX[0] <= malla.lon[i] <= BBOX[2] and BBOX[1] <= malla.lat[i] <= BBOX[3]]
    formas = []
    for k, i in enumerate(celdas):
        anillo = malla.vertices_geo(i)
        anillo = anillo + [anillo[0]]
        formas.append((transform_geom("EPSG:4326", crs, {"type": "Polygon", "coordinates": [anillo]}), k + 1))
    idx_celda = rasterize(formas, out_shape=(alto, ancho), transform=perfil["transform"], fill=0,
                          dtype="int32")
    rasgos_hex = []
    for k, i in enumerate(celdas):
        sel = idx_celda == k + 1
        tierra_c = sel & tierra
        n_tierra = int(tierra_c.sum())
        anillo = malla.vertices_geo(i)
        props_c = {"id": malla.ids[i], "tierra_ha": round(n_tierra * 0.01, 1)}
        if n_tierra:
            props_c["agua_pct"] = [round(float(a[tierra_c].mean() * 100), 2) for a in agua_tierra]
            props_c["temporal_ha"] = round(float(((estacional | ocasional) & sel).sum() * 0.01), 1)
            props_c["permanente_ha"] = round(float((permanente & sel).sum() * 0.01), 1)
            props_c["delta_hh_db"] = [round(float(np.mean(hh_db[t][tierra_c] - mediana_hh[tierra_c])), 2)
                                      for t in range(n)]
            suelo_c = sel & suelo
            if suelo_c.sum() > 500:
                props_c["humedad_idx"] = [round(float(np.nanmean(humedad[t][suelo_c])), 3) for t in range(n)]
        cuenta = {g: 0 for g in GRUPOS_EXPOSICION}
        cuenta_exp = {g: 0 for g in GRUPOS_EXPOSICION}
        puntaje = 0.0
        for p, x, y in zip(pois, px, py):
            c, f = inv * (x, y)
            c, f = int(c), int(f)
            if 0 <= f < alto and 0 <= c < ancho and idx_celda[f, c] == k + 1:
                cuenta[p["grupo"]] += 1
                if p in expuestos:
                    cuenta_exp[p["grupo"]] += 1
                    puntaje += INFRAESTRUCTURA_CRITICA.get(p["tipo"], 3.0)
        props_c.update({"n_" + g: v for g, v in cuenta.items()})
        props_c.update({"exp_" + g: v for g, v in cuenta_exp.items()})
        props_c["puntaje_exposicion"] = round(puntaje, 1)
        rasgos_hex.append({"type": "Feature", "properties": props_c,
                           "geometry": {"type": "Polygon", "coordinates": [anillo + [anillo[0]]]}})
    (SALIDA / "hex.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": rasgos_hex},
                                                   separators=(",", ":")))
    (SALIDA / "pois.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(p["lon"], 6), round(p["lat"], 6)]},
         "properties": {k: v for k, v in p.items() if k not in ("lon", "lat")}} for p in pois]},
        separators=(",", ":"), ensure_ascii=False))

    rasgos_lugares = []
    for el in osm_lugares["elements"]:
        nombre = el.get("tags", {}).get("name")
        if nombre:
            rasgos_lugares.append({"type": "Feature",
                                   "geometry": {"type": "Point", "coordinates": [el["lon"], el["lat"]]},
                                   "properties": {"nombre": nombre, "tipo": el["tags"].get("place"),
                                                  "clase": "lugar"}})
    vistos = set()
    for el in osm_agua["elements"]:
        tags = el.get("tags", {})
        nombre = tags.get("name")
        c = centro_de(el)
        if nombre and c and nombre not in vistos and BBOX[0] <= c[0] <= BBOX[2] and BBOX[1] <= c[1] <= BBOX[3]:
            vistos.add(nombre)
            rasgos_lugares.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(c[0], 6), round(c[1], 6)]},
                                   "properties": {"nombre": nombre, "clase": "agua",
                                                  "tipo": tags.get("natural") or tags.get("waterway") or tags.get("water")}})
    (SALIDA / "lugares.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": rasgos_lugares},
                                                       separators=(",", ":"), ensure_ascii=False))

    rasgos_lagunas = []
    for anillo, tags in poligonos_osm(osm_agua["elements"]):
        if tags.get("natural") not in ("water", "wetland"):
            continue
        g = transform_geom("EPSG:4326", crs, {"type": "Polygon", "coordinates": [anillo]})
        sel = rasterize([(g, 1)], out_shape=(alto, ancho), transform=perfil["transform"], fill=0).astype(bool) & tierra
        if sel.sum() < 30:
            continue
        hh_s = [round(float(np.median(hh_db[t][sel])), 2) for t in range(n)]
        hv_s = [round(float(np.median(hv_db[t][sel])), 2) for t in range(n)]
        rasgos_lagunas.append({"type": "Feature",
                               "geometry": {"type": "Polygon", "coordinates": [[[round(x, 6), round(y, 6)] for x, y in anillo]]},
                               "properties": {
                                   "nombre": tags.get("name"), "tipo": tags.get("natural"),
                                   "subtipo": tags.get("water") or tags.get("wetland"),
                                   "area_ha": round(float(sel.sum() * 0.01), 2),
                                   "hh_db": hh_s, "hv_db": hv_s,
                                   "agua_abierta_pct": [round(float(agua_tierra[t][sel].mean() * 100), 1) for t in range(n)],
                                   "firma": "agua abierta" if np.median(hh_s) < t_hh else
                                            ("vegetacion sobre agua" if np.median(hv_s) > -17.0 else "mixta")}})
    (SALIDA / "lagunas.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": rasgos_lagunas},
                                                       separators=(",", ":"), ensure_ascii=False))
    firmas = {}
    for r in rasgos_lagunas:
        if r["properties"]["tipo"] == "water":
            firmas[r["properties"]["firma"]] = firmas.get(r["properties"]["firma"], 0) + 1
    print("lagunas de OSM por firma de radar:", firmas)

    trans, w, h, esquinas, limites_web = grilla_web(perfil)
    nombre_fecha = [f.replace("-", "") for f in fechas]
    capas = {"rgb": [], "hh": [], "hv": [], "agua": [], "cambio": [], "humedad": []}
    tierra_web = a_web(tierra.astype(np.float32), perfil, trans, w, h, Resampling.nearest, 0.0) > 0.5
    perm_web = a_web(permanente.astype(np.float32), perfil, trans, w, h, Resampling.nearest, 0.0) > 0.5
    pasos_hh, pasos_hv = [], []
    for i in range(n):
        hh_w = a_web(hh_db[i], perfil, trans, w, h)
        hv_w = a_web(hv_db[i], perfil, trans, w, h)
        valido = np.isfinite(hh_w)
        r = escala(hh_w, RANGO_DB["hh"], 0.9)
        g = escala(hv_w, RANGO_DB["hv"], 0.9)
        b = escala(hh_w - hv_w, RANGO_DB["razon"])
        rgb = (np.dstack([r, g, b]) * 255).astype(np.uint8)
        alfa = (valido * 255).astype(np.uint8)
        capas["rgb"].append(guardar(Image.fromarray(np.dstack([rgb, alfa]), "RGBA"), "rgb_{}.webp".format(nombre_fecha[i])))
        gris = (escala(hh_w, RANGO_DB["hh"]) * 255).astype(np.uint8)
        capas["hh"].append(guardar(Image.fromarray(np.dstack([gris, gris, gris, alfa]), "RGBA"),
                                   "hh_{}.webp".format(nombre_fecha[i])))
        verde = rampa(escala(hv_w, RANGO_DB["hv"]), [(0, (8, 12, 10)), (0.45, (40, 90, 50)),
                                                       (0.75, (120, 190, 90)), (1, (225, 255, 190))])
        capas["hv"].append(guardar(Image.fromarray(np.dstack([verde.astype(np.uint8), alfa]), "RGBA"),
                                   "hv_{}.webp".format(nombre_fecha[i])))

        a_w = a_web(agua_tierra[i].astype(np.float32), perfil, trans, w, h, Resampling.nearest, 0.0) > 0.5
        img_agua = np.zeros((h, w, 4), np.uint8)
        img_agua[perm_web & tierra_web] = (37, 99, 235, 150)
        img_agua[a_w & ~perm_web & tierra_web] = (34, 211, 238, 235)
        capas["agua"].append(guardar(Image.fromarray(img_agua, "RGBA"), "agua_{}.png".format(nombre_fecha[i])))

        delta = a_web(hh_db[i] - mediana_hh, perfil, trans, w, h)
        mag = np.clip((np.abs(delta) - CAMBIO_MIN_DB) / (CAMBIO_MAX_DB - CAMBIO_MIN_DB), 0, 1)
        mag = np.where(np.isfinite(mag) & tierra_web, mag, 0)
        img_cambio = np.zeros((h, w, 4), np.uint8)
        oscurece = delta < 0
        img_cambio[..., :3] = np.where(oscurece[..., None], (56, 189, 248), (251, 146, 60))
        img_cambio[..., 3] = (mag ** 0.8 * 230).astype(np.uint8)
        capas["cambio"].append(guardar(Image.fromarray(img_cambio, "RGBA"), "cambio_{}.webp".format(nombre_fecha[i]), 80))

        hum_w = a_web(humedad[i], perfil, trans, w, h)
        color_h = rampa(np.nan_to_num(hum_w, nan=0.0), [(0, (146, 94, 48)), (0.35, (214, 178, 112)),
                                                        (0.6, (110, 170, 120)), (0.8, (40, 150, 170)),
                                                        (1.0, (30, 90, 200))])
        alfa_h = np.where(np.isfinite(hum_w), 215, 0).astype(np.uint8)
        capas["humedad"].append(guardar(Image.fromarray(np.dstack([color_h.astype(np.uint8), alfa_h]), "RGBA"),
                                        "humedad_{}.webp".format(nombre_fecha[i]), 80))

        sub_hh = hh_w[::PASO_SERIE, ::PASO_SERIE]
        sub_hv = hv_w[::PASO_SERIE, ::PASO_SERIE]
        lo, hi = CUANTIZA_DB
        cuant = lambda a: np.where(np.isfinite(a), np.clip((a - lo) / (hi - lo) * 254 + 1, 1, 255), 0).astype(np.uint8)
        pasos_hh.append(cuant(sub_hh))
        pasos_hv.append(cuant(sub_hv))
        print("  imagenes {} listas".format(fechas[i]))

    frec_w = a_web(np.nan_to_num(frec, nan=0.0), perfil, trans, w, h, Resampling.nearest, 0.0)
    colores = rampa(frec_w, [(0, (0, 0, 0)), (0.05, (250, 204, 21)), (0.3, (34, 211, 238)),
                             (0.8, (37, 99, 235)), (1.0, (30, 58, 138))])
    alfa_f = np.where((frec_w >= 0.05) & tierra_web, np.clip(120 + frec_w * 135, 0, 255), 0).astype(np.uint8)
    img_frec = guardar(Image.fromarray(np.dstack([colores.astype(np.uint8), alfa_f]), "RGBA"), "frecuencia.png")

    mar_w = a_web(mar.astype(np.float32), perfil, trans, w, h, Resampling.nearest, 0.0) > 0.5
    sub_tierra = tierra_web[::PASO_SERIE, ::PASO_SERIE]
    sub_mar = mar_w[::PASO_SERIE, ::PASO_SERIE]
    alto_s, ancho_s = sub_tierra.shape
    bloque = np.concatenate([np.stack(pasos_hh).ravel(), np.stack(pasos_hv).ravel(),
                             (sub_tierra * 1 + sub_mar * 2).astype(np.uint8).ravel()])
    (SALIDA / "pixeles.bin").write_bytes(bloque.tobytes())

    meta = {
        "titulo": "NISAR sobre Veracruz-Boca del Rio, temporada de lluvias 2026",
        "generado": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "bbox": BBOX,
        "fechas": fechas,
        "granulos": granulos,
        "pista": {"numero": 163, "direccion": "ascendente", "cuadro": 11, "modo": "4005",
                  "hora_local": "05:49", "frecuencia": "banda L, frecuencia A", "pixel_m": 10},
        "imagen": {"esquinas": esquinas, "ancho": w, "alto": h, "pixel_web_m": PIXEL_WEB_M, "capas": capas,
                   "frecuencia": img_frec},
        "pixeles": {"archivo": "pixeles.bin", "ancho": ancho_s, "alto": alto_s, "paso": PASO_SERIE,
                    "limites_3857": [round(v, 2) for v in limites_web], "cuantiza_db": list(CUANTIZA_DB),
                    "orden": "hh[fecha][fila][col], hv[fecha][fila][col], mascara[fila][col] (1 tierra, 2 mar)"},
        "umbrales": {"hh_db": round(t_hh, 2), "hv_db": round(t_hv, 2),
                     "metodo": "valle del histograma de la serie filtrada (Lee 5x5) y normalizada"},
        "normalizacion": {"metodo": "por fecha se resta la desviacion de la mediana de blancos urbanos estables "
                                    "(mediana HH de la serie > -2 dB) respecto a su promedio",
                          "pixeles_estables": int(estables.sum()),
                          "ajuste_hh_db": [round(float(v), 3) for v in ajuste_hh],
                          "ajuste_hv_db": [round(float(v), 3) for v in ajuste_hv]},
        "agua": {"tierra_km2": area_agua, "temporal_km2": area_temporal,
                 "permanente_km2": round(float(permanente.sum() * km2), 3),
                 "estacional_km2": round(float(estacional.sum() * km2), 3),
                 "ocasional_km2": round(float(ocasional.sum() * km2), 3),
                 "mar_km2": round(float(mar.sum() * km2), 2), "tierra_km2_total": round(float(tierra.sum() * km2), 2)},
        "retrodispersion": {"hh_db_mediana": [round(float(np.nanmedian(x[tierra])), 2) for x in hh_db],
                            "hv_db_mediana": [round(float(np.nanmedian(x[tierra])), 2) for x in hv_db],
                            "mar_hh_db_mediana": [round(float(np.nanmedian(x[mar])), 2) for x in hh_db],
                            "suelo_hh_db_media": campo_hh, "suelo_hv_db_media": campo_hv},
        "humedad": {"metodo": "deteccion de cambio por pixel: (HH - 2o minimo) / (2o maximo - 2o minimo) "
                              "de la serie, suavizado a 90 m; solo suelo sin agua ni ciudad",
                    "indice_medio": humedad_media, "suelo_km2": round(float(suelo.sum() * km2), 2)},
        "lluvia": {"fuente": "NASA POWER PRECTOTCORR (diaria)", "punto": LLUVIA_PUNTO, "url": url_power,
                   "diaria": diaria, "por_paso": lluvia, "correlaciones": correlaciones,
                   "correlacion_agua_temporal_vs_7d": round(r_lluvia, 3)},
        "zonas": zonas,
        "exposicion": {"radio_m": 200, "grupos": resumen_exposicion,
                       "expuestos": sorted([{k: p[k] for k in ("nombre", "tipo", "grupo", "dist_agua_temporal_m", "fechas_con_agua_200m", "lon", "lat")}
                                            for p in expuestos], key=lambda p: p["dist_agua_temporal_m"])},
        "hex": {"archivo": "hex.geojson", "nivel": 2, "ancho_km": round(malla.ancho_celda_km, 3), "celdas": len(celdas)},
        "lagunas": {"archivo": "lagunas.geojson", "poligonos": len(rasgos_lagunas), "firmas_cuerpos_de_agua": firmas,
                    "criterio": "agua abierta si la mediana HH < umbral de agua; vegetacion sobre agua si la "
                                "mediana HV > -17 dB; mixta en otro caso",
                    "ramsar": {"sitio": 1450, "nombre": "Sistema de Lagunas Interdunarias de la Ciudad de Veracruz",
                               "area_ha": 140.6, "designado": "2005-02-02", "lagunas": 18}},
        "playa_excluida_m": 150,
    }
    (SALIDA / "meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False))
    print("listo: {} ({} imagenes)".format(SALIDA.relative_to(RAIZ), sum(len(v) for v in capas.values()) + 1))


if __name__ == "__main__":
    main()
