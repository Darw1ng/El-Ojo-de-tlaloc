"""Malla hexagonal regular sobre el area de interes.

Por que hexagonos y no una cuadricula
-------------------------------------
1. Todos los vecinos estan a la misma distancia (6 vecinos, un solo paso).
   En una cuadricula los diagonales estan a 1.41 pasos, lo que deforma
   cualquier modelo de vecindad o de difusion espacial.
2. El area de la celda es casi constante en todo el dominio.
3. Visualmente no genera los artefactos de escalera de la cuadricula.

Escala "1:16"
-------------
La escala del proyecto se define como el numero de hexagonos que caben a lo
ancho del area de interes:

    1:16  ->  16 hexagonos a lo ancho

Con el bbox por defecto (92.4 km de ancho) eso da:

    ancho_hex = 92.4 / 16 = 5.78 km
    arista    = ancho_hex / sqrt(3) = 3.34 km
    area      = 1.5 * sqrt(3) * arista^2 = 28.9 km2

Niveles: nivel_siguiente() duplica el numero de hexagonos a lo ancho, asi que
cada nivel cuadruplica el conteo de celdas (1:4 en area). Dos niveles arriba
del base dan exactamente 1:16 en area, por si la lectura buscada era esa:

    nivel 0 -> 1:16 a lo ancho, 28.9 km2 por celda
    nivel 1 -> 1:32 a lo ancho,  7.2 km2 por celda
    nivel 2 -> 1:64 a lo ancho,  1.8 km2 por celda

Geometria
---------
Hexagonos "pointy-top" (vertice arriba) en coordenadas axiales (q, r):

    ancho  = sqrt(3) * a          separacion horizontal = sqrt(3) * a
    alto   = 2 * a                separacion vertical   = 1.5 * a
    centro = (a*sqrt(3)*(q + r/2), a*1.5*r)

El id de celda es OT<nivel>.<q>.<r>: estable, legible y reproducible sin
depender de una libreria externa de indexacion (H3 se evaluo y se descarto,
ver docs/adr/0002-malla-propia-vs-h3.md).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .config import MAX_CELDAS, N_ANCHO_DEFECTO, AREA_VERACRUZ, BBox
from .geo import ProyeccionLocal

SQRT3 = math.sqrt(3.0)

#: Vecinos en coordenadas axiales, en orden: E, NE, NO, O, SO, SE.
VECINOS_AXIALES = ((1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1))


@dataclass
class MallaHexagonal:
    """Malla hexagonal regular que cubre un bbox.

    Atributos derivados (todos alineados por indice de celda):
        ids        lista de str,  id estable de cada celda
        qr         (n, 2) int,    coordenadas axiales
        centros_xy (n, 2) float,  centros en metros locales
        lat, lon   (n,) float,    centros en grados
    """

    bbox: BBox = AREA_VERACRUZ
    n_ancho: int = N_ANCHO_DEFECTO
    nivel: int = 0

    arista_m: float = field(init=False, default=0.0)
    ids: list = field(init=False, repr=False, default_factory=list)
    qr: object = field(init=False, repr=False, default=None)
    centros_xy: object = field(init=False, repr=False, default=None)
    lat: object = field(init=False, repr=False, default=None)
    lon: object = field(init=False, repr=False, default=None)
    proy: object = field(init=False, repr=False, default=None)
    _dist: object = field(init=False, repr=False, default=None)
    _indice: dict = field(init=False, repr=False, default_factory=dict)

    def __post_init__(self) -> None:
        if self.n_ancho < 2:
            raise ValueError("n_ancho debe ser al menos 2")
        lat0, lon0 = self.bbox.centro
        self.proy = ProyeccionLocal(lat0, lon0)

        # Esquinas del bbox en metros locales.
        xs, ys = self.proy.a_metros(
            [self.bbox.lat_min, self.bbox.lat_max],
            [self.bbox.lon_min, self.bbox.lon_max],
        )
        x_min, x_max = float(xs[0]), float(xs[1])
        y_min, y_max = float(ys[0]), float(ys[1])

        ancho_m = x_max - x_min
        alto_m = y_max - y_min

        # Escala: n_ancho hexagonos a lo ancho -> arista.
        self.arista_m = ancho_m / (self.n_ancho * SQRT3)
        a = self.arista_m

        paso_x = SQRT3 * a
        paso_y = 1.5 * a

        # Rango de filas (r) y columnas (q) necesarias para cubrir el bbox.
        # El centro geometrico del bbox se ancla en (q=0, r=0).
        cx = (x_min + x_max) / 2.0
        cy = (y_min + y_max) / 2.0
        r_max = int(math.ceil(alto_m / (2.0 * paso_y))) + 1
        q_extra = int(math.ceil(r_max / 2.0)) + 1
        q_max = int(math.ceil(ancho_m / (2.0 * paso_x))) + 1 + q_extra

        ids = []
        qr = []
        xy = []

        # Margen: se admite el centro si el hexagono toca el bbox, para que
        # la malla cubra el borde completo y el mapa no quede con huecos.
        margen_x = paso_x / 2.0
        margen_y = a

        for r in range(-r_max, r_max + 1):
            y = cy + paso_y * r
            if not (y_min - margen_y <= y <= y_max + margen_y):
                continue
            for q in range(-q_max, q_max + 1):
                x = cx + paso_x * (q + r / 2.0)
                if not (x_min - margen_x <= x <= x_max + margen_x):
                    continue
                ids.append("OT{}.{}.{}".format(self.nivel, q, r))
                qr.append((q, r))
                xy.append((x, y))

        if not xy:
            raise ValueError("la malla quedo vacia; revisa bbox y n_ancho")
        if len(xy) > MAX_CELDAS:
            raise ValueError(
                "la malla tiene {} celdas y el tope es {}; "
                "baja el nivel o recorta el bbox".format(len(xy), MAX_CELDAS)
            )

        self.ids = ids
        self.qr = np.asarray(qr, dtype=np.int32)
        self.centros_xy = np.asarray(xy, dtype=float)
        self.lat, self.lon = self.proy.a_grados(
            self.centros_xy[:, 0], self.centros_xy[:, 1]
        )
        self._indice = {cid: i for i, cid in enumerate(ids)}

    # --- propiedades basicas ----------------------------------------------

    def __len__(self) -> int:
        return len(self.ids)

    @property
    def n_celdas(self) -> int:
        return len(self.ids)

    @property
    def area_celda_km2(self) -> float:
        """Area de un hexagono regular: 1.5*sqrt(3)*a^2."""
        return 1.5 * SQRT3 * (self.arista_m / 1000.0) ** 2

    @property
    def ancho_celda_km(self) -> float:
        return SQRT3 * self.arista_m / 1000.0

    def indice(self, id_celda: str) -> int:
        """Indice interno de una celda por su id. Lanza KeyError si no existe."""
        return self._indice[id_celda]

    def nivel_siguiente(self) -> "MallaHexagonal":
        """Malla del nivel de abajo: el doble de hexagonos a lo ancho."""
        return MallaHexagonal(
            bbox=self.bbox, n_ancho=self.n_ancho * 2, nivel=self.nivel + 1
        )

    # --- geometria ---------------------------------------------------------

    def vertices_xy(self, i: int):
        """Los 6 vertices de la celda i, en metros locales. (6, 2)."""
        cx, cy = self.centros_xy[i]
        a = self.arista_m
        # Pointy-top: el primer vertice apunta al norte.
        ang = np.radians(np.array([90.0, 150.0, 210.0, 270.0, 330.0, 30.0]))
        return np.stack([cx + a * np.cos(ang), cy + a * np.sin(ang)], axis=1)

    def vertices_geo(self, i: int) -> list:
        """Los 6 vertices de la celda i como [(lon, lat), ...] para GeoJSON."""
        v = self.vertices_xy(i)
        lat, lon = self.proy.a_grados(v[:, 0], v[:, 1])
        return [(round(float(lo), 6), round(float(la), 6))
                for lo, la in zip(lon, lat)]

    def matriz_distancias_km(self):
        """Distancias entre centros, (n, n) en km. Se cachea: la usa el modelo."""
        if self._dist is None:
            p = self.centros_xy / 1000.0
            d = np.sqrt(((p[:, None, :] - p[None, :, :]) ** 2).sum(axis=-1))
            np.fill_diagonal(d, 0.0)
            self._dist = d
        return self._dist

    def vecinos(self) -> list:
        """Indices de los vecinos de cada celda (6 dentro, menos en el borde)."""
        pares = {(int(q), int(r)): i for i, (q, r) in enumerate(self.qr)}
        salida = []
        for q, r in self.qr:
            fila = []
            for dq, dr in VECINOS_AXIALES:
                j = pares.get((int(q) + dq, int(r) + dr))
                if j is not None:
                    fila.append(j)
            salida.append(fila)
        return salida

    # --- salida ------------------------------------------------------------

    @property
    def metadata(self) -> dict:
        return {
            "nivel": self.nivel,
            "escala": "1:{}".format(self.n_ancho),
            "n_celdas": self.n_celdas,
            "arista_km": round(self.arista_m / 1000.0, 4),
            "ancho_celda_km": round(self.ancho_celda_km, 4),
            "area_celda_km2": round(self.area_celda_km2, 4),
            "bbox": [
                self.bbox.lon_min,
                self.bbox.lat_min,
                self.bbox.lon_max,
                self.bbox.lat_max,
            ],
        }

    def a_geojson(self, propiedades: dict | None = None) -> dict:
        """FeatureCollection con un Polygon por celda.

        `propiedades` es un dict nombre -> secuencia de largo n_celdas; cada
        valor se adjunta a su feature. Es lo que consume el front para colorear.
        """
        propiedades = propiedades or {}
        for nombre, valores in propiedades.items():
            if len(valores) != self.n_celdas:
                raise ValueError(
                    "la propiedad '{}' tiene {} valores y la malla {} celdas"
                    .format(nombre, len(valores), self.n_celdas)
                )

        features = []
        for i, cid in enumerate(self.ids):
            anillo = self.vertices_geo(i)
            anillo.append(anillo[0])  # GeoJSON exige el anillo cerrado
            props = {
                "id": cid,
                "q": int(self.qr[i, 0]),
                "r": int(self.qr[i, 1]),
                "lat": round(float(self.lat[i]), 6),
                "lon": round(float(self.lon[i]), 6),
            }
            for nombre, valores in propiedades.items():
                props[nombre] = _limpio(valores[i])
            features.append(
                {
                    "type": "Feature",
                    "id": cid,
                    "geometry": {"type": "Polygon", "coordinates": [anillo]},
                    "properties": props,
                }
            )

        return {
            "type": "FeatureCollection",
            "metadata": self.metadata,
            "features": features,
        }


def _limpio(v):
    """Convierte un valor de numpy a algo serializable, NaN -> None."""
    if v is None:
        return None
    if isinstance(v, (np.floating, float)):
        f = float(v)
        return None if math.isnan(f) else round(f, 4)
    if isinstance(v, (np.integer, int)):
        return int(v)
    if isinstance(v, np.ndarray):
        return [_limpio(x) for x in v.tolist()]
    return v
