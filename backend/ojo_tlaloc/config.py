"""Configuracion global del nucleo.

El area de interes sale del enlace de OpenStreetMap que define el proyecto:
    https://www.openstreetmap.org/#map=11/19.1704/-96.1654

Ese enlace fija centro (19.1704 N, 96.1654 W) y zoom 11. El bbox se deriva
asumiendo un viewport de 1280x800 px, que es lo que ve el usuario al abrir
ese enlace en un monitor normal:

    resolucion = 156543.03392 * cos(lat) / 2**zoom          [m/px]
               = 156543.03392 * cos(19.1704) / 2**11
               = 72.2 m/px

    ancho  = 1280 px * 72.2 m/px =  92.4 km  -> 0.879 grados de longitud
    alto   =  800 px * 72.2 m/px =  57.7 km  -> 0.522 grados de latitud

El bbox resultante cubre el puerto de Veracruz, Boca del Rio, la cuenca baja
del Jamapa y del rio La Antigua, y el arranque del piedemonte hacia el oeste.
Es la zona donde el caso de uso (lluvia extrema -> inundacion urbana y
agricola) tiene sentido.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- Area de interes -------------------------------------------------------

CENTRO_LAT = 19.1704
CENTRO_LON = -96.1654
ZOOM_OSM = 11

# Radio medio de la Tierra (IUGG), en metros.
RADIO_TIERRA_M = 6_371_008.8


@dataclass(frozen=True)
class BBox:
    """Caja geografica en grados decimales (WGS84)."""

    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float

    def __post_init__(self) -> None:
        if self.lat_min >= self.lat_max:
            raise ValueError("lat_min debe ser menor que lat_max")
        if self.lon_min >= self.lon_max:
            raise ValueError("lon_min debe ser menor que lon_max")

    @property
    def centro(self) -> tuple[float, float]:
        return (
            (self.lat_min + self.lat_max) / 2.0,
            (self.lon_min + self.lon_max) / 2.0,
        )

    def contiene(self, lat: float, lon: float) -> bool:
        return (
            self.lat_min <= lat <= self.lat_max
            and self.lon_min <= lon <= self.lon_max
        )


#: Area de interes por defecto, derivada del enlace de OSM (ver docstring).
AREA_VERACRUZ = BBox(
    lat_min=18.9095,
    lat_max=19.4313,
    lon_min=-96.6048,
    lon_max=-95.7260,
)

# --- Malla -----------------------------------------------------------------

#: Escala 1:16 -> el ancho del area de interes se parte en 16 hexagonos.
#: Con el bbox de arriba eso da hexagonos de ~5.8 km de ancho (~28 km2),
#: que es la resolucion tipica de un modelo regional de precipitacion.
N_ANCHO_DEFECTO = 16

#: Tope de celdas por peticion. La matriz de covarianza espacial es densa
#: (n x n) y se factoriza con Cholesky: a partir de ~4000 celdas hay que
#: cambiar a descomposicion espectral truncada (ver docs/03-modelo-estocastico.md).
MAX_CELDAS = 4096

# --- Ensamble --------------------------------------------------------------

N_MIEMBROS_DEFECTO = 200
HORIZONTE_DEFECTO_DIAS = 14
MAX_MIEMBROS = 1000
MAX_HORIZONTE_DIAS = 60

#: Tope de memoria para el ensamble crudo, en MB. Evita tumbar la maquina
#: con una peticion grande (celdas x dias x miembros x variables x 8 bytes).
MAX_MEMORIA_ENSAMBLE_MB = 512

#: Umbrales de lluvia diaria (mm) para las capas de probabilidad.
#: Referencia: criterios de la CONAGUA para lluvia puntual en 24 h.
UMBRALES_LLUVIA_MM = (1.0, 20.0, 50.0, 70.0, 150.0)

SEMILLA_DEFECTO = 20261114  # fecha del hackathon, para que la demo sea estable
