"""Proyeccion local plana.

La malla hexagonal necesita trabajar en metros, no en grados: un hexagono
regular en grados no es regular sobre el terreno porque un grado de longitud
se encoge con el coseno de la latitud.

Se usa una equirectangular local (plate carree escalada) centrada en el area
de interes:

    x = R * (lon - lon0) * cos(lat0)
    y = R * (lat - lat0)

Para el area de interes (~92 x 58 km) el error maximo de distancia frente a
la geodesica es del 0.16%, o sea 170 m en el par de puntos mas separado del
dominio. Frente a hexagonos de 5.8 km de ancho eso es despreciable, y se mide
en tests/test_malla.py contra la formula de haversine, con un tope del 0.3%:
si alguien agranda el bbox lo suficiente para pasarse, la prueba falla y avisa
que hay que cambiar de proyeccion (azimutal equidistante por zona, o UTM 14N).
"""

from __future__ import annotations

import numpy as np

from .config import RADIO_TIERRA_M


class ProyeccionLocal:
    """Convierte entre grados (WGS84) y metros locales respecto a un origen."""

    def __init__(self, lat0: float, lon0: float) -> None:
        self.lat0 = float(lat0)
        self.lon0 = float(lon0)
        self._coslat0 = float(np.cos(np.radians(lat0)))
        if self._coslat0 <= 0:
            raise ValueError("latitud de origen invalida (polo)")

    def a_metros(self, lat, lon):
        """(lat, lon) en grados -> (x, y) en metros. Acepta escalares o arrays."""
        lat = np.asarray(lat, dtype=float)
        lon = np.asarray(lon, dtype=float)
        x = RADIO_TIERRA_M * np.radians(lon - self.lon0) * self._coslat0
        y = RADIO_TIERRA_M * np.radians(lat - self.lat0)
        return x, y

    def a_grados(self, x, y):
        """(x, y) en metros -> (lat, lon) en grados."""
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        lon = self.lon0 + np.degrees(x / (RADIO_TIERRA_M * self._coslat0))
        lat = self.lat0 + np.degrees(y / RADIO_TIERRA_M)
        return lat, lon


def haversine_km(lat1, lon1, lat2, lon2):
    """Distancia sobre la esfera, en km. Se usa para validar la proyeccion."""
    lat1, lon1, lat2, lon2 = (np.radians(np.asarray(v, dtype=float))
                              for v in (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * (RADIO_TIERRA_M / 1000.0) * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))
