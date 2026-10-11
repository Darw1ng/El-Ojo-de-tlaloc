"""Pruebas de geometria: proyeccion y malla hexagonal."""

import math

import numpy as np
import pytest

from ojo_tlaloc.config import AREA_VERACRUZ, MAX_CELDAS, BBox
from ojo_tlaloc.geo import ProyeccionLocal, haversine_km
from ojo_tlaloc.malla import SQRT3, MallaHexagonal


# --- proyeccion ------------------------------------------------------------


def test_proyeccion_ida_y_vuelta():
    p = ProyeccionLocal(19.17, -96.17)
    lat, lon = 19.4, -96.5
    x, y = p.a_metros(lat, lon)
    lat2, lon2 = p.a_grados(x, y)
    assert abs(float(lat2) - lat) < 1e-9
    assert abs(float(lon2) - lon) < 1e-9


def test_proyeccion_el_origen_queda_en_cero():
    p = ProyeccionLocal(19.17, -96.17)
    x, y = p.a_metros(19.17, -96.17)
    assert abs(float(x)) < 1e-6 and abs(float(y)) < 1e-6


def test_proyeccion_error_despreciable_en_el_dominio():
    """La equirectangular local es valida solo si el error es despreciable a la
    escala del area de interes. Hoy el peor par da 0.16% (unos 170 m sobre
    110 km), contra hexagonos de 5.8 km de ancho. El tope se pone en 0.3%: si
    alguien agranda el bbox lo suficiente, esta prueba falla y avisa que hay
    que cambiar de proyeccion."""
    p = ProyeccionLocal(*AREA_VERACRUZ.centro)
    rng = np.random.default_rng(0)
    peor = 0.0
    for _ in range(300):
        la1 = rng.uniform(AREA_VERACRUZ.lat_min, AREA_VERACRUZ.lat_max)
        lo1 = rng.uniform(AREA_VERACRUZ.lon_min, AREA_VERACRUZ.lon_max)
        la2 = rng.uniform(AREA_VERACRUZ.lat_min, AREA_VERACRUZ.lat_max)
        lo2 = rng.uniform(AREA_VERACRUZ.lon_min, AREA_VERACRUZ.lon_max)
        x1, y1 = p.a_metros(la1, lo1)
        x2, y2 = p.a_metros(la2, lo2)
        plano = math.hypot(float(x2 - x1), float(y2 - y1)) / 1000.0
        real = float(haversine_km(la1, lo1, la2, lo2))
        if real > 1.0:
            peor = max(peor, abs(plano - real) / real)
    assert peor < 3e-3, "error de proyeccion {:.4%}".format(peor)


def test_bbox_invalido():
    with pytest.raises(ValueError):
        BBox(lat_min=20, lat_max=19, lon_min=-96, lon_max=-95)
    with pytest.raises(ValueError):
        BBox(lat_min=19, lat_max=20, lon_min=-95, lon_max=-96)


# --- escala de la malla ----------------------------------------------------


def test_escala_1_16_da_16_hexagonos_a_lo_ancho(malla):
    """La definicion de escala del proyecto: n_ancho hexagonos cubren el ancho."""
    ancho_bbox_km = float(
        haversine_km(
            *AREA_VERACRUZ.centro[:1], AREA_VERACRUZ.lon_min,
            AREA_VERACRUZ.centro[0], AREA_VERACRUZ.lon_max,
        )
    )
    assert malla.n_ancho == 16
    assert malla.ancho_celda_km * 16 == pytest.approx(ancho_bbox_km, rel=0.01)


def test_geometria_del_hexagono(malla):
    a = malla.arista_m
    assert malla.ancho_celda_km == pytest.approx(SQRT3 * a / 1000.0)
    assert malla.area_celda_km2 == pytest.approx(1.5 * SQRT3 * (a / 1000.0) ** 2)
    # Los 6 vertices estan a distancia `a` del centro (hexagono regular).
    v = malla.vertices_xy(malla.n_celdas // 2)
    centro = malla.centros_xy[malla.n_celdas // 2]
    d = np.hypot(v[:, 0] - centro[0], v[:, 1] - centro[1])
    assert np.allclose(d, a, rtol=1e-9)


def test_los_vecinos_estan_a_una_distancia_de_centro(malla):
    """La propiedad que justifica usar hexagonos: todos los vecinos a la misma
    distancia, que es sqrt(3)*a (el ancho del hexagono)."""
    d = malla.matriz_distancias_km()
    vecinos = malla.vecinos()
    esperada = malla.ancho_celda_km
    for i, fila in enumerate(vecinos):
        for j in fila:
            assert d[i, j] == pytest.approx(esperada, rel=1e-6)


def test_vecindad_reciproca_y_acotada(malla):
    vecinos = malla.vecinos()
    assert all(len(f) <= 6 for f in vecinos)
    for i, fila in enumerate(vecinos):
        for j in fila:
            assert i in vecinos[j], "la vecindad no es reciproca"
    # Las celdas interiores tienen exactamente 6 vecinos.
    assert max(len(f) for f in vecinos) == 6


def test_nivel_siguiente_cuadruplica_y_cuarta_el_area(malla):
    hijo = malla.nivel_siguiente()
    assert hijo.n_ancho == malla.n_ancho * 2
    assert hijo.nivel == malla.nivel + 1
    assert hijo.area_celda_km2 == pytest.approx(malla.area_celda_km2 / 4.0, rel=1e-9)
    assert 3.2 < hijo.n_celdas / malla.n_celdas < 4.4


def test_dos_niveles_arriba_es_1_a_16_en_area(malla):
    """La otra lectura posible de 1:16, por si es la que se buscaba."""
    nieto = malla.nivel_siguiente().nivel_siguiente()
    assert nieto.area_celda_km2 == pytest.approx(malla.area_celda_km2 / 16.0, rel=1e-9)


# --- cobertura e ids -------------------------------------------------------


def test_la_malla_cubre_el_bbox(malla):
    """Ninguna esquina del bbox debe quedar fuera del alcance de la malla."""
    for lat in (AREA_VERACRUZ.lat_min, AREA_VERACRUZ.lat_max):
        for lon in (AREA_VERACRUZ.lon_min, AREA_VERACRUZ.lon_max):
            x, y = malla.proy.a_metros(lat, lon)
            d = np.hypot(malla.centros_xy[:, 0] - float(x),
                         malla.centros_xy[:, 1] - float(y))
            assert d.min() <= malla.arista_m * 1.01, "esquina sin cubrir"


def test_ids_unicos_y_consultables(malla):
    assert len(set(malla.ids)) == malla.n_celdas
    for i in (0, malla.n_celdas // 2, malla.n_celdas - 1):
        assert malla.indice(malla.ids[i]) == i
    with pytest.raises(KeyError):
        malla.indice("no-existe")


def test_ids_estables_entre_construcciones():
    """El id tiene que ser deterministico: el front guarda celdas por id."""
    a = MallaHexagonal()
    b = MallaHexagonal()
    assert a.ids == b.ids


def test_distancias_simetricas_con_diagonal_cero(malla):
    d = malla.matriz_distancias_km()
    assert d.shape == (malla.n_celdas, malla.n_celdas)
    assert np.allclose(d, d.T)
    assert np.allclose(np.diag(d), 0.0)


# --- geojson ---------------------------------------------------------------


def test_geojson_valido(malla):
    gj = malla.a_geojson()
    assert gj["type"] == "FeatureCollection"
    assert len(gj["features"]) == malla.n_celdas
    assert gj["metadata"]["escala"] == "1:16"
    for f in gj["features"][:20]:
        anillo = f["geometry"]["coordinates"][0]
        assert len(anillo) == 7, "el hexagono debe traer 6 vertices + cierre"
        assert anillo[0] == anillo[-1], "el anillo tiene que estar cerrado"
        # Orden (lon, lat), no (lat, lon): es el error clasico de GeoJSON.
        for lon, lat in anillo:
            assert -97.5 < lon < -95.0
            assert 18.0 < lat < 20.5


def test_geojson_con_propiedades(malla):
    valores = np.arange(malla.n_celdas, dtype=float)
    gj = malla.a_geojson({"prueba": valores})
    assert gj["features"][5]["properties"]["prueba"] == 5.0


def test_geojson_nan_sale_como_null(malla):
    valores = np.full(malla.n_celdas, np.nan)
    gj = malla.a_geojson({"prueba": valores})
    assert gj["features"][0]["properties"]["prueba"] is None


def test_geojson_rechaza_propiedad_de_largo_equivocado(malla):
    with pytest.raises(ValueError, match="valores"):
        malla.a_geojson({"mala": np.zeros(3)})


# --- limites ---------------------------------------------------------------


def test_n_ancho_minimo():
    with pytest.raises(ValueError, match="n_ancho"):
        MallaHexagonal(n_ancho=1)


def test_tope_de_celdas():
    """El tope existe porque el Cholesky de la covarianza es O(n^3): sin el,
    una peticion con nivel alto tumbaria el proceso."""
    with pytest.raises(ValueError, match="tope"):
        MallaHexagonal(n_ancho=400)
    assert MAX_CELDAS >= 4096
