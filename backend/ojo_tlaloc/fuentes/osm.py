"""OpenStreetMap como fuente de datos del territorio, no como fondo de mapa.

Que aporta OSM que ningun satelite da
-------------------------------------
Un satelite ve reflectancia; OSM sabe *que es* cada cosa. Eso cambia tres
piezas del modelo y agrega una capa que no existia:

    fraccion_impermeable  -> el coeficiente de escurrimiento por celda deja de
                             ser uniforme. El puerto de Veracruz es asfalto y
                             la zona agricola no, y hasta ahora el modelo no
                             los distinguia.
    fraccion_agua         -> cuerpos de agua y cauces: donde el balance de
                             suelo no aplica.
    densidad_vial         -> proxy de urbanizacion y, para obra, de accesos.
    exposicion            -> QUE y QUIEN esta en las celdas de riesgo:
                             hospitales, escuelas, bomberos, edificios.

La ultima es la que convierte "aqui va a escurrir 60 mm" en "aqui va a
escurrir 60 mm y hay un hospital y dos escuelas". Es la diferencia entre un
mapa y una decision.

Lo que OSM NO da bien en esta zona
----------------------------------
Medido el 10-oct-2026 en el area de interes: 5 603 edificios para una zona
metropolitana de cerca de 900 mil habitantes. Es un orden de magnitud menos
de lo que hay en el terreno: **la cobertura de edificios de OSM aqui esta muy
incompleta**.

Por eso la impermeabilidad no se calcula sumando edificios: se toma el maximo
entre (a) lo que implica el uso de suelo, que si esta mapeado como poligonos
grandes y cubre bien, y (b) lo que suman edificios mas vialidades, que es
exacto donde existe el dato. Asi la estimacion no se hunde donde falta el
mapeo, y mejora sola conforme OSM se completa.

Licencia
--------
ODbL. Exige atribucion visible: "(c) OpenStreetMap contributors". Viaja en la
procedencia de cada capa y la interfaz la tiene que mostrar.
"""

from __future__ import annotations

import json

import numpy as np

from .base import (
    NIVEL_DERIVADO,
    NIVEL_OBSERVADO,
    CapaFuente,
    ErrorFuente,
    FuenteRemota,
    Procedencia,
)
from .geometria import (
    area_poligono_m2,
    centroide_poligono,
    longitud_segmentos,
    puntos_en_poligono,
    rejilla_de_muestreo,
)

#: Servidores de Overpass. Se prueban en orden si uno esta ocupado.
ESPEJOS_OVERPASS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)

#: Fraccion impermeable por uso de suelo. Valores del rango estandar de
#: coeficientes de escurrimiento de la hidrologia urbana (metodo racional).
IMPERMEABILIDAD_USO = {
    "residential": 0.55,
    "commercial": 0.85,
    "retail": 0.85,
    "industrial": 0.80,
    "port": 0.90,
    "harbour": 0.90,
    "railway": 0.50,
    "landfill": 0.40,
    "construction": 0.40,
    "brownfield": 0.35,
    "quarry": 0.30,
    "military": 0.30,
    "cemetery": 0.15,
    "recreation_ground": 0.12,
    "allotments": 0.08,
    "farmland": 0.05,
    "farmyard": 0.25,
    "meadow": 0.04,
    "grass": 0.05,
    "village_green": 0.05,
    "orchard": 0.04,
    "vineyard": 0.04,
    "plant_nursery": 0.06,
    "forest": 0.02,
    "greenhouse_horticulture": 0.60,
    "aquaculture": 1.00,
    "basin": 1.00,
    "reservoir": 1.00,
    "salt_pond": 1.00,
}

#: Ancho tipico de la superficie pavimentada por clase de vialidad, en metros.
#: Incluye carriles y acotamiento. Se usa para estimar area impermeable a
#: partir de la longitud, porque OSM traza las vias como lineas sin ancho.
ANCHO_VIAL_M = {
    "motorway": 24.0, "motorway_link": 12.0,
    "trunk": 18.0, "trunk_link": 10.0,
    "primary": 14.0, "primary_link": 8.0,
    "secondary": 11.0, "secondary_link": 7.0,
    "tertiary": 9.0, "tertiary_link": 6.0,
    "residential": 8.0,
    "unclassified": 7.0,
    "living_street": 7.0,
    "pedestrian": 5.0,
    "service": 5.0,
    "track": 3.5,
    "footway": 1.8, "path": 1.5, "cycleway": 2.0, "steps": 1.5,
}

#: Vialidades que cuentan como urbanizacion (para la densidad vial se excluyen
#: veredas y caminos de terraceria, que no indican lo mismo).
CLASES_VIALES_URBANAS = frozenset({
    "motorway", "trunk", "primary", "secondary", "tertiary",
    "residential", "unclassified", "living_street", "service",
})

#: Infraestructura critica para la capa de exposicion, con su peso relativo.
#: El peso refleja cuanto importa que esa celda quede en riesgo: un hospital
#: concentra personas que no se pueden evacuar rapido.
INFRAESTRUCTURA_CRITICA = {
    "hospital": 10.0,
    "clinic": 5.0,
    "doctors": 3.0,
    "school": 7.0,
    "kindergarten": 7.0,
    "university": 6.0,
    "college": 5.0,
    "fire_station": 8.0,
    "police": 6.0,
    "shelter": 6.0,
    "social_facility": 6.0,
    "nursing_home": 9.0,
}

ATRIBUCION_OSM = "(c) OpenStreetMap contributors (ODbL)"

#: Saturacion y escala de la relacion densidad vial -> impermeabilidad.
#: Ninguna zona urbana llega al 100% impermeable: siempre quedan patios,
#: camellones y areas verdes, y 0.78 es el techo tipico de un centro denso.
IMPERM_VIAL_TECHO = 0.78
IMPERM_VIAL_ESCALA_KM_KM2 = 9.5


class FuenteOSM(FuenteRemota):
    """Descarga de Overpass y agregacion a la malla hexagonal."""

    nombre = "osm"

    def __init__(self, espejos=ESPEJOS_OVERPASS, **kw) -> None:
        super().__init__(**kw)
        self.espejos = tuple(espejos)

    # --- descarga ---------------------------------------------------------

    def _consulta(self, cuerpo: str, clave: str) -> dict:
        """Ejecuta una consulta de Overpass, con cache en disco.

        El cache es por (capa, bbox), asi que la segunda corrida no vuelve a
        pegarle a Overpass. Eso importa: son 6 consultas y unos 5 MB.
        """
        guardado = self._leer_cache(clave)
        if guardado is not None:
            return guardado

        try:
            crudo = self._pedir(self.espejos, {"data": cuerpo}, tiempo_limite=240.0)
            datos = json.loads(crudo)
        except json.JSONDecodeError as e:
            raise ErrorFuente(
                "Overpass respondio algo que no es JSON ({}). Suele pasar "
                "cuando la consulta excede el limite del servidor.".format(e)
            ) from None
        if "remark" in datos:
            # Overpass avisa de consultas truncadas por memoria o tiempo en un
            # campo 'remark' y devuelve 200: sin esta guarda, los datos
            # incompletos entrarian silenciosamente al modelo.
            raise ErrorFuente(
                "Overpass trunco la consulta: {}".format(datos["remark"])
            )
        self._escribir_cache(clave, datos)
        return datos

    def _bbox(self, malla) -> str:
        b = malla.bbox
        return "{},{},{},{}".format(b.lat_min, b.lon_min, b.lat_max, b.lon_max)

    def descargar(self, malla) -> dict:
        """Baja las cinco capas que se usan. Se cachea por bbox."""
        bb = self._bbox(malla)
        amenities = "|".join(INFRAESTRUCTURA_CRITICA)
        consultas = {
            "edificios": 'way["building"]({bb});relation["building"]({bb});',
            "uso_suelo": 'way["landuse"]({bb});way["leisure"="park"]({bb});',
            "agua": ('way["natural"="water"]({bb});way["waterway"="riverbank"]({bb});'
                     'relation["natural"="water"]({bb});'),
            "cauces": 'way["waterway"~"^(river|stream|canal|drain|ditch)$"]({bb});',
            "vialidad": 'way["highway"]({bb});',
        }
        salida = {}
        for nombre, patron in consultas.items():
            cuerpo = "[out:json][timeout:240];({});out geom;".format(
                patron.format(bb=bb)
            )
            salida[nombre] = self._consulta(cuerpo, "{}|{}".format(nombre, bb))

        cuerpo = ('[out:json][timeout:240];'
                  'nwr["amenity"~"^({})$"]({});out center;'.format(amenities, bb))
        salida["infraestructura"] = self._consulta(
            cuerpo, "infraestructura|{}".format(bb)
        )
        return salida

    # --- agregacion a la malla -------------------------------------------

    def capas(self, malla, paso_muestreo_m: float = 200.0) -> dict:
        """Todas las capas de OSM agregadas a la malla. -> dict[str, CapaFuente]."""
        crudo = self.descargar(malla)
        n = malla.n_celdas
        area_celda = malla.area_celda_km2 * 1e6

        proc_obs = lambda nota: Procedencia(   # noqa: E731
            fuente="OpenStreetMap (Overpass)",
            nivel=NIVEL_OBSERVADO,
            resolucion_nativa="vectorial",
            cadencia="continua (mapeo comunitario)",
            licencia="ODbL",
            atribucion=ATRIBUCION_OSM,
            url="https://www.openstreetmap.org",
            nota=nota,
        )

        # -- edificios: area exacta al hexagono del centroide
        area_edificios = np.zeros(n)
        area_pisos = np.zeros(n)        # huella x niveles: proxy de ocupacion
        conteo_edificios = np.zeros(n, dtype=int)
        for el in crudo["edificios"].get("elements", []):
            xy = _geometria_xy(el, malla)
            if xy is None or xy.shape[0] < 3:
                continue
            a = area_poligono_m2(xy)
            if a <= 0:
                continue
            i = _hexagono_de(centroide_poligono(xy), malla)
            if i >= 0:
                area_edificios[i] += a
                area_pisos[i] += a * _niveles(el)
                conteo_edificios[i] += 1

        # -- uso de suelo y agua: muestreo por puntos
        puntos, idx_pto, area_pto = rejilla_de_muestreo(malla, paso_muestreo_m)
        validos = idx_pto >= 0
        puntos_por_celda = np.bincount(idx_pto[validos], minlength=n).astype(float)

        imperm_pto = np.full(puntos.shape[0], np.nan)
        agua_pto = np.zeros(puntos.shape[0], dtype=bool)

        for el in crudo["uso_suelo"].get("elements", []):
            xy = _geometria_xy(el, malla)
            if xy is None or xy.shape[0] < 3:
                continue
            clase = (el.get("tags", {}).get("landuse")
                     or el.get("tags", {}).get("leisure") or "")
            coef = IMPERMEABILIDAD_USO.get(clase)
            if coef is None:
                coef = 0.05 if clase == "park" else None
            if coef is None:
                continue
            dentro = _puntos_dentro(puntos, xy)
            if dentro.any():
                # Si dos usos se traslapan, gana el mas impermeable.
                imperm_pto[dentro] = np.fmax(imperm_pto[dentro], coef)

        for llave in ("agua",):
            for el in crudo[llave].get("elements", []):
                xy = _geometria_xy(el, malla)
                if xy is None or xy.shape[0] < 3:
                    continue
                dentro = _puntos_dentro(puntos, xy)
                agua_pto |= dentro

        # OJO: lo que se necesita es la FRACCION DE AREA impermeable de toda la
        # celda, no el promedio del coeficiente entre los puntos que tienen uso
        # mapeado. La diferencia no es sutil: con el promedio condicionado, un
        # poligono industrial que cubre el 0.3% del hexagono lo pintaba al 80%
        # de impermeabilidad. Se divide entre los puntos TOTALES de la celda.
        imperm_uso = _fraccion_area_ponderada(
            imperm_pto, idx_pto, n, puntos_por_celda
        )
        cobertura_uso = _fraccion_por_celda(
            np.isfinite(imperm_pto), idx_pto, n, puntos_por_celda
        )
        frac_agua = _fraccion_por_celda(agua_pto, idx_pto, n, puntos_por_celda)

        # -- vialidad: longitud por clase -> area pavimentada
        area_vial = np.zeros(n)
        largo_urbano = np.zeros(n)
        for el in crudo["vialidad"].get("elements", []):
            xy = _geometria_xy(el, malla, cerrar=False)
            if xy is None or xy.shape[0] < 2:
                continue
            clase = el.get("tags", {}).get("highway", "")
            ancho = ANCHO_VIAL_M.get(clase, 6.0)
            largos, medios = longitud_segmentos(xy)
            if not largos.size:
                continue
            idx = _hexagonos_de(medios, malla)
            ok = idx >= 0
            if not ok.any():
                continue
            np.add.at(area_vial, idx[ok], largos[ok] * ancho)
            if clase in CLASES_VIALES_URBANAS:
                np.add.at(largo_urbano, idx[ok], largos[ok])

        # -- cauces: longitud de rios y drenes
        largo_cauces = np.zeros(n)
        for el in crudo["cauces"].get("elements", []):
            xy = _geometria_xy(el, malla, cerrar=False)
            if xy is None or xy.shape[0] < 2:
                continue
            largos, medios = longitud_segmentos(xy)
            if not largos.size:
                continue
            idx = _hexagonos_de(medios, malla)
            ok = idx >= 0
            if ok.any():
                np.add.at(largo_cauces, idx[ok], largos[ok])

        # -- infraestructura critica
        peso_critico = np.zeros(n)
        conteo_critico = np.zeros(n, dtype=int)
        detalle_critico = [dict() for _ in range(n)]
        for el in crudo["infraestructura"].get("elements", []):
            lat, lon = _punto_de(el)
            if lat is None:
                continue
            x, y = malla.proy.a_metros(lat, lon)
            i = _hexagono_de(np.array([float(x), float(y)]), malla)
            if i < 0:
                continue
            tipo = el.get("tags", {}).get("amenity", "")
            peso = INFRAESTRUCTURA_CRITICA.get(tipo, 1.0)
            peso_critico[i] += peso
            conteo_critico[i] += 1
            detalle_critico[i][tipo] = detalle_critico[i].get(tipo, 0) + 1

        # -- impermeabilidad: tres estimaciones independientes y su combinacion
        frac_construida = np.clip(area_edificios / area_celda, 0.0, 1.0)
        frac_pavimento = np.clip(area_vial / area_celda, 0.0, 1.0)
        medida = np.clip(frac_construida + frac_pavimento, 0.0, 1.0)

        dens_vial = largo_urbano / (malla.area_celda_km2 * 1000.0)
        proxy_vial = _impermeabilidad_por_densidad_vial(dens_vial)

        # Se toma el maximo de las tres vias. No es arbitrario: las tres
        # subestiman por construccion (lo que no esta mapeado no suma), asi
        # que la mayor es la menos mala. Medido en el puerto de Veracruz: la
        # via directa daba 0.19 cuando OSM solo tiene el 10% del uso de suelo
        # mapeado de esa celda; el proxy vial da 0.71, que es el orden correcto
        # para un centro urbano.
        combinada = np.fmax(np.fmax(medida, np.nan_to_num(imperm_uso, nan=0.0)),
                            proxy_vial)
        # El agua no es suelo impermeable: es agua. Se descuenta para que el
        # balance de suelo no la trate como pavimento.
        combinada = np.clip(combinada * (1.0 - frac_agua), 0.0, 1.0)

        capas = {
            "fraccion_impermeable": CapaFuente(
                "fraccion_impermeable", combinada, "0-1",
                Procedencia(
                    fuente="OpenStreetMap (derivado)",
                    nivel=NIVEL_DERIVADO,
                    resolucion_nativa="vectorial agregada al hexagono",
                    cadencia="continua",
                    licencia="ODbL",
                    atribucion=ATRIBUCION_OSM,
                    incertidumbre=0.15,
                    nota=("maximo de tres vias (edificios+vialidad, uso de "
                          "suelo, proxy de densidad vial) descontando agua. "
                          "Las tres subestiman porque lo no mapeado no suma, "
                          "asi que la mayor es la menos mala"),
                ),
                cobertura=conteo_edificios,
            ),
            "fraccion_construida": CapaFuente(
                "fraccion_construida", frac_construida, "0-1",
                proc_obs("huella de edificios mapeados; incompleta en esta zona"),
                cobertura=conteo_edificios),
            "fraccion_pavimento": CapaFuente(
                "fraccion_pavimento", frac_pavimento, "0-1",
                proc_obs("longitud vial por ancho tipico de clase")),
            "fraccion_agua": CapaFuente(
                "fraccion_agua", frac_agua, "0-1",
                proc_obs("cuerpos de agua por muestreo de puntos")),
            "impermeabilidad_proxy_vial": CapaFuente(
                "impermeabilidad_proxy_vial", proxy_vial, "0-1",
                Procedencia(
                    fuente="OpenStreetMap (proxy calibrado)",
                    nivel=NIVEL_DERIVADO,
                    licencia="ODbL",
                    atribucion=ATRIBUCION_OSM,
                    incertidumbre=0.15,
                    nota=("estimacion a partir de densidad vial, NO una "
                          "medicion de superficie impermeable; reemplazar por "
                          "producto satelital cuando se tenga"),
                )),
            "impermeabilidad_uso_suelo": CapaFuente(
                "impermeabilidad_uso_suelo", imperm_uso, "0-1",
                proc_obs("fraccion de area impermeable segun clase de landuse")),
            "cobertura_uso_suelo": CapaFuente(
                "cobertura_uso_suelo", cobertura_uso, "0-1",
                proc_obs("que fraccion del hexagono tiene uso de suelo mapeado "
                         "en OSM; donde es baja, la impermeabilidad esta "
                         "subestimada por falta de mapeo, no por ser rural")),
            "densidad_vial": CapaFuente(
                "densidad_vial", largo_urbano / (malla.area_celda_km2 * 1000.0),
                "km/km2",
                proc_obs("longitud de vialidad urbana por area")),
            "densidad_cauces": CapaFuente(
                "densidad_cauces", largo_cauces / (malla.area_celda_km2 * 1000.0),
                "km/km2",
                proc_obs("rios, arroyos, canales y drenes")),
            "edificios": CapaFuente(
                "edificios", conteo_edificios.astype(float), "conteo",
                proc_obs("edificios mapeados en OSM")),
            "area_pisos": CapaFuente(
                "area_pisos", area_pisos, "m2",
                proc_obs("huella por building:levels; proxy de ocupacion y de "
                         "valor expuesto. Donde no hay niveles mapeados se "
                         "asume 1, asi que subestima en zona alta")),
            "infraestructura_critica": CapaFuente(
                "infraestructura_critica", conteo_critico.astype(float), "conteo",
                proc_obs("hospitales, escuelas, bomberos, albergues. Puede "
                         "sobrecontar: si un equipamiento esta mapeado como "
                         "poligono y ademas como nodo interior, cuenta dos "
                         "veces. Sirve como indice de exposicion relativa, no "
                         "como censo")),
            "peso_critico": CapaFuente(
                "peso_critico", peso_critico, "ponderado",
                Procedencia(
                    fuente="OpenStreetMap (derivado)",
                    nivel=NIVEL_DERIVADO,
                    licencia="ODbL",
                    atribucion=ATRIBUCION_OSM,
                    nota="suma ponderada de infraestructura critica por celda",
                )),
        }
        self.detalle_critico = detalle_critico
        return capas


# --- utilidades internas ---------------------------------------------------


def _niveles(el) -> float:
    tags = el.get("tags", {})
    for clave in ("building:levels", "levels"):
        if clave in tags:
            try:
                return max(1.0, float(str(tags[clave]).split(";")[0]))
            except (ValueError, TypeError):
                continue
    return 1.0


def _geometria_xy(el, malla, cerrar: bool = True):
    """Geometria de un elemento de Overpass (`out geom`) en metros locales."""
    geom = el.get("geometry")
    if not geom:
        # Las relaciones traen la geometria en members.
        miembros = el.get("members") or []
        for m in miembros:
            if m.get("role") == "outer" and m.get("geometry"):
                geom = m["geometry"]
                break
        if not geom:
            return None
    puntos = [(p["lat"], p["lon"]) for p in geom
              if p and p.get("lat") is not None and p.get("lon") is not None]
    if len(puntos) < 2:
        return None
    lat = np.array([p[0] for p in puntos])
    lon = np.array([p[1] for p in puntos])
    x, y = malla.proy.a_metros(lat, lon)
    return np.stack([np.asarray(x), np.asarray(y)], axis=1)


def _punto_de(el):
    if el.get("lat") is not None:
        return float(el["lat"]), float(el["lon"])
    centro = el.get("center")
    if centro:
        return float(centro["lat"]), float(centro["lon"])
    geom = el.get("geometry")
    if geom:
        validos = [p for p in geom if p and p.get("lat") is not None]
        if validos:
            return (float(np.mean([p["lat"] for p in validos])),
                    float(np.mean([p["lon"] for p in validos])))
    return None, None


def _hexagono_de(xy, malla) -> int:
    d2 = ((malla.centros_xy - xy[None, :]) ** 2).sum(axis=1)
    i = int(np.argmin(d2))
    return i if np.sqrt(d2[i]) <= malla.arista_m else -1


def _hexagonos_de(puntos, malla):
    d2 = ((puntos[:, None, :] - malla.centros_xy[None, :, :]) ** 2).sum(axis=2)
    cercano = np.argmin(d2, axis=1)
    dmin = np.sqrt(d2[np.arange(puntos.shape[0]), cercano])
    return np.where(dmin <= malla.arista_m, cercano, -1)


def _puntos_dentro(puntos, poligono):
    """Point-in-polygon con filtro previo por caja: sin el, cada poligono
    probaria contra los ~140 mil puntos de la rejilla completa."""
    x0, y0 = poligono[:, 0].min(), poligono[:, 1].min()
    x1, y1 = poligono[:, 0].max(), poligono[:, 1].max()
    cerca = ((puntos[:, 0] >= x0) & (puntos[:, 0] <= x1)
             & (puntos[:, 1] >= y0) & (puntos[:, 1] <= y1))
    salida = np.zeros(puntos.shape[0], dtype=bool)
    if not cerca.any():
        return salida
    salida[cerca] = puntos_en_poligono(puntos[cerca], poligono)
    return salida


def _impermeabilidad_por_densidad_vial(densidad_km_km2):
    """Impermeabilidad estimada a partir de la densidad de vialidad urbana.

        imperm = techo * (1 - exp(-densidad / escala))

    POR QUE EXISTE ESTO. En el area de interes OSM tiene 32 422 vialidades y
    solo 5 603 edificios: las calles estan bien mapeadas y los edificios no.
    Contar area de edificios da 1.9% de ocupacion en el centro del puerto de
    Veracruz, que es imposible. La densidad vial, en cambio, es un proxy
    confiable del grado de urbanizacion, y la hidrologia urbana la usa
    justamente para eso cuando no hay censo de construccion.

    Calibracion de la curva contra los rangos tipicos de la literatura:

        densidad (km/km2)   zona                 imperm
                      0-1   rural                  0.00-0.10
                      1-5   periurbano             0.10-0.32
                     5-10   suburbano              0.32-0.51
                    10-15   urbano medio           0.51-0.63
                      >15   urbano denso           0.63-0.78

    ES UN PROXY, NO UNA MEDICION. La via correcta es un producto satelital de
    superficie impermeable (Landsat/Sentinel o el global de impervious
    surface); cuando se tenga, esta funcion se queda solo como respaldo.
    """
    d = np.maximum(np.asarray(densidad_km_km2, dtype=float), 0.0)
    return IMPERM_VIAL_TECHO * (1.0 - np.exp(-d / IMPERM_VIAL_ESCALA_KM_KM2))


def _fraccion_area_ponderada(valor_pto, idx_pto, n, puntos_por_celda):
    """Fraccion de area de la celda cubierta por el valor, ponderada.

        resultado[c] = sum(valor_i para i en c) / puntos_totales_en_c

    Es decir: cada punto aporta su coeficiente multiplicado por la fraccion de
    area que representa. Un poligono industrial (coef 0.80) que cubre 3 de los
    720 puntos del hexagono aporta 0.0033, no 0.80.

    Los puntos sin dato cuentan como cero aporte, que es lo correcto para una
    fraccion de area: lo que no esta mapeado como impermeable no suma area
    impermeable. La incertidumbre que eso introduce se reporta aparte, en la
    capa de cobertura.
    """
    salida = np.zeros(n)
    ok = (idx_pto >= 0) & np.isfinite(valor_pto)
    if not ok.any():
        return salida
    suma = np.bincount(idx_pto[ok], weights=valor_pto[ok], minlength=n)
    total = np.maximum(puntos_por_celda, 1.0)
    return np.clip(suma / total, 0.0, 1.0)


def _fraccion_por_celda(bandera_pto, idx_pto, n, puntos_por_celda):
    """Fraccion de puntos del hexagono que cumplen la bandera."""
    salida = np.zeros(n)
    ok = idx_pto >= 0
    dentro = np.bincount(idx_pto[ok & bandera_pto], minlength=n).astype(float)
    total = np.maximum(puntos_por_celda, 1.0)
    salida = np.clip(dentro / total, 0.0, 1.0)
    return salida
