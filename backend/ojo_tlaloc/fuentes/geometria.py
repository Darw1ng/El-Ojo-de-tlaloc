"""Geometria de poligonos y polilineas, en numpy puro.

Se necesita para pasar vectores de OpenStreetMap a fracciones de area por
hexagono. No se usa shapely por la misma razon que no se usa scipy (ver
docs/adr/0003-sin-scipy.md): son cuatro funciones de geometria elemental y
una dependencia binaria menos.

Tres estrategias segun el tamano del poligono frente al hexagono (5.8 km):

    poligono MUCHO menor   ->  area exacta por el teorema del area
                               (shoelace) asignada al hexagono del centroide.
                               Es el caso de los edificios (10-50 m).
    poligono comparable    ->  muestreo por puntos: se cuenta cuantos puntos
                               de una rejilla caen dentro. Es el caso del uso
                               de suelo y de los cuerpos de agua.
    polilinea              ->  longitud por segmento, asignada al hexagono
                               del punto medio. Es el caso de las vialidades.
"""

from __future__ import annotations

import numpy as np


def area_poligono_m2(xy) -> float:
    """Area de un poligono por el teorema del area (shoelace), en m2.

    Devuelve el valor absoluto, asi que no importa la orientacion del anillo.
    `xy` es (n, 2) en metros; el anillo puede venir cerrado o abierto.
    """
    p = np.asarray(xy, dtype=float)
    if p.ndim != 2 or p.shape[1] != 2 or p.shape[0] < 3:
        return 0.0
    # Si el anillo viene cerrado, quitar el punto repetido.
    if np.allclose(p[0], p[-1]):
        p = p[:-1]
        if p.shape[0] < 3:
            return 0.0
    x, y = p[:, 0], p[:, 1]
    return float(abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) / 2.0)


def centroide_poligono(xy):
    """Centroide del area de un poligono (no el promedio de los vertices).

    Para un poligono degenerado (area cero) cae al promedio de los vertices,
    que es lo razonable.
    """
    p = np.asarray(xy, dtype=float)
    if p.ndim != 2 or p.shape[1] != 2 or p.shape[0] < 3:
        return p.mean(axis=0) if p.size else np.zeros(2)
    if np.allclose(p[0], p[-1]):
        p = p[:-1]
    if p.shape[0] < 3:
        return p.mean(axis=0)
    x, y = p[:, 0], p[:, 1]
    x1, y1 = np.roll(x, -1), np.roll(y, -1)
    cruz = x * y1 - x1 * y
    area2 = cruz.sum()
    if abs(area2) < 1e-12:
        return p.mean(axis=0)
    cx = ((x + x1) * cruz).sum() / (3.0 * area2)
    cy = ((y + y1) * cruz).sum() / (3.0 * area2)
    return np.array([cx, cy])


def longitud_segmentos(xy):
    """Largo de cada segmento de una polilinea y su punto medio.

    Devuelve (largos, medios) con largos (n-1,) en metros y medios (n-1, 2).
    """
    p = np.asarray(xy, dtype=float)
    if p.ndim != 2 or p.shape[0] < 2:
        return np.zeros(0), np.zeros((0, 2))
    d = np.diff(p, axis=0)
    largos = np.hypot(d[:, 0], d[:, 1])
    medios = (p[:-1] + p[1:]) / 2.0
    return largos, medios


def puntos_en_poligono(puntos, poligono):
    """Cuales de `puntos` caen dentro de `poligono`. Ray casting vectorizado.

    puntos    (m, 2) en metros
    poligono  (n, 2) en metros
    Devuelve  (m,) bool

    El algoritmo cuenta cruces de una semirrecta horizontal hacia la derecha:
    numero impar de cruces = dentro. Los puntos exactamente sobre el borde
    quedan indefinidos, lo que no importa cuando se usa para estimar areas.
    """
    pts = np.asarray(puntos, dtype=float)
    poly = np.asarray(poligono, dtype=float)
    if pts.ndim != 2 or pts.shape[1] != 2:
        raise ValueError("puntos debe ser (m, 2)")
    if poly.ndim != 2 or poly.shape[1] != 2 or poly.shape[0] < 3:
        return np.zeros(pts.shape[0], dtype=bool)
    if np.allclose(poly[0], poly[-1]):
        poly = poly[:-1]
        if poly.shape[0] < 3:
            return np.zeros(pts.shape[0], dtype=bool)

    x, y = pts[:, 0], pts[:, 1]
    x1, y1 = poly[:, 0], poly[:, 1]
    x2, y2 = np.roll(x1, -1), np.roll(y1, -1)

    # Para cada lado (j) y cada punto (i): el lado cruza la horizontal del
    # punto, y el cruce queda a la derecha del punto.
    cruza = ((y1[None, :] > y[:, None]) != (y2[None, :] > y[:, None]))
    with np.errstate(divide="ignore", invalid="ignore"):
        x_corte = (
            (x2 - x1)[None, :] * (y[:, None] - y1[None, :])
            / (y2 - y1)[None, :]
            + x1[None, :]
        )
    dentro = (cruza & (x[:, None] < x_corte)).sum(axis=1) % 2 == 1
    return dentro


def rejilla_de_muestreo(malla, paso_m: float = 200.0):
    """Rejilla regular de puntos sobre el bbox de la malla, con su hexagono.

    Devuelve (puntos_xy, indice_hexagono, area_por_punto_m2). Se usa para
    estimar fracciones de area de poligonos grandes: cada punto representa
    `paso_m^2` de terreno, asi que contar puntos dentro de un poligono y
    dividir entre los puntos del hexagono da la fraccion cubierta.

    El error de la estimacion es del orden de 1/sqrt(puntos por hexagono).
    Con paso de 200 m y hexagonos de 28.8 km2 son ~720 puntos por celda, o sea
    unos 4 puntos porcentuales. Suficiente para un coeficiente de
    escurrimiento, que de por si es una aproximacion mas gruesa que eso.
    """
    xs, ys = malla.centros_xy[:, 0], malla.centros_xy[:, 1]
    margen = malla.arista_m
    rx = np.arange(xs.min() - margen, xs.max() + margen + paso_m, paso_m)
    ry = np.arange(ys.min() - margen, ys.max() + margen + paso_m, paso_m)
    gx, gy = np.meshgrid(rx, ry)
    puntos = np.stack([gx.ravel(), gy.ravel()], axis=1)

    # Hexagono mas cercano = hexagono que contiene el punto (el hexagono
    # regular es su propia celda de Voronoi).
    idx = np.full(puntos.shape[0], -1, dtype=int)
    bloque = 20000
    for ini in range(0, puntos.shape[0], bloque):
        trozo = puntos[ini:ini + bloque]
        d2 = ((trozo[:, None, :] - malla.centros_xy[None, :, :]) ** 2).sum(axis=2)
        cercano = np.argmin(d2, axis=1)
        # Fuera del hexagono mas cercano (mas alla del radio circunscrito) no
        # cuenta: el punto esta fuera de la malla.
        dmin = np.sqrt(d2[np.arange(trozo.shape[0]), cercano])
        idx[ini:ini + bloque] = np.where(dmin <= malla.arista_m, cercano, -1)

    return puntos, idx, paso_m * paso_m
