"""Pruebas de las fuentes que bajan de internet: OpenStreetMap y NASA POWER.

Estan separadas del resto porque dependen de red o de cache en disco. Si no
hay ninguno de los dos, se SALTAN en lugar de fallar: un pipeline de CI sin
salida a internet no deberia reportar rojo por eso, y pegarle a Overpass en
cada corrida de pruebas seria abusar de un servicio publico gratuito.

Para correrlas: basta haber ejecutado `python demo_fusion.py` una vez, que
deja el cache poblado en datos/entrada/cache/.
"""

import numpy as np
import pytest

from ojo_tlaloc.fuentes.base import (
    NIVEL_DERIVADO,
    NIVEL_OBSERVADO,
    NIVEL_REANALISIS,
    ErrorFuente,
    FuenteRemota,
)
from ojo_tlaloc.fuentes.osm import (
    ANCHO_VIAL_M,
    IMPERMEABILIDAD_USO,
    FuenteOSM,
    _impermeabilidad_por_densidad_vial,
)
from ojo_tlaloc.fuentes.power import (
    DIAS_POR_MES_MEDIO,
    FuentePOWER,
    _weibull_forma_por_cuantiles,
    _weibull_forma_por_momentos,
)


def _sin_red(fuente, malla, excepcion):
    return pytest.skip(
        "{} no disponible y sin cache: {}".format(fuente, str(excepcion)[:120])
    )


# --- cosas que se prueban sin red -----------------------------------------


def test_la_curva_de_impermeabilidad_por_densidad_vial():
    """Calibrada contra los rangos tipicos de hidrologia urbana."""
    f = _impermeabilidad_por_densidad_vial
    assert float(f(0.0)) == pytest.approx(0.0)
    assert 0.0 < float(f(1.0)) < 0.15        # rural
    assert 0.25 < float(f(5.0)) < 0.40       # periurbano
    assert 0.45 < float(f(10.0)) < 0.60      # suburbano
    assert 0.60 < float(f(22.0)) < 0.78      # urbano denso
    # Nunca llega a 1: siempre quedan patios y areas verdes.
    assert float(f(1000.0)) < 0.79


def test_la_curva_es_monotona():
    d = np.linspace(0, 40, 200)
    v = _impermeabilidad_por_densidad_vial(d)
    assert np.all(np.diff(v) >= 0)


def test_los_coeficientes_de_uso_de_suelo_son_coherentes():
    """Lo urbano impermeabiliza mas que lo agricola, y el agua es 1."""
    assert IMPERMEABILIDAD_USO["commercial"] > IMPERMEABILIDAD_USO["residential"]
    assert IMPERMEABILIDAD_USO["residential"] > IMPERMEABILIDAD_USO["farmland"]
    assert IMPERMEABILIDAD_USO["farmland"] > IMPERMEABILIDAD_USO["forest"]
    assert IMPERMEABILIDAD_USO["basin"] == 1.0
    for clase, v in IMPERMEABILIDAD_USO.items():
        assert 0.0 <= v <= 1.0, clase


def test_los_anchos_viales_son_coherentes():
    assert ANCHO_VIAL_M["motorway"] > ANCHO_VIAL_M["primary"]
    assert ANCHO_VIAL_M["primary"] > ANCHO_VIAL_M["residential"]
    assert ANCHO_VIAL_M["residential"] > ANCHO_VIAL_M["footway"]
    for clase, v in ANCHO_VIAL_M.items():
        assert 1.0 <= v <= 40.0, clase


def test_el_ajuste_por_cuantiles_recupera_una_weibull_conocida():
    """Se generan muestras de una Weibull con forma conocida y se verifica que
    el estimador la recupera. Es lo que hace valida la calibracion."""
    rng = np.random.default_rng(5)
    for forma_real in (0.7, 0.85, 1.0, 1.3):
        u = rng.random(200_000)
        x = 12.0 * np.power(-np.log1p(-u), 1.0 / forma_real)
        estimada = _weibull_forma_por_cuantiles(x)
        assert estimada == pytest.approx(forma_real, rel=0.08), forma_real


def test_momentos_y_cuantiles_coinciden_en_datos_sin_truncar():
    rng = np.random.default_rng(6)
    u = rng.random(100_000)
    x = 10.0 * np.power(-np.log1p(-u), 1.0 / 0.85)
    assert _weibull_forma_por_cuantiles(x) == pytest.approx(
        _weibull_forma_por_momentos(x), rel=0.1)


def test_el_truncamiento_sesga_los_momentos_y_no_los_cuantiles():
    """La razon de usar cuantiles: con las intensidades truncadas por el
    umbral de dia humedo, el metodo de momentos sobreestima la forma (cola mas
    ligera de la real) y el de cuantiles altos aguanta mucho mejor."""
    rng = np.random.default_rng(7)
    u = rng.random(200_000)
    x = 12.0 * np.power(-np.log1p(-u), 1.0 / 0.8)
    truncado = x[x >= 3.5]
    por_momentos = _weibull_forma_por_momentos(truncado)
    por_cuantiles = _weibull_forma_por_cuantiles(truncado)
    assert por_momentos > 0.8 + 0.15       # sesgado hacia arriba
    assert abs(por_cuantiles - 0.8) < abs(por_momentos - 0.8)


def test_pocas_muestras_devuelven_el_valor_tipico():
    assert _weibull_forma_por_cuantiles(np.array([1.0, 2.0])) == 0.85
    assert _weibull_forma_por_momentos(np.array([1.0, 2.0])) == 0.85


def test_la_espera_entre_peticiones_esta_puesta():
    """Overpass y POWER son gratuitos: pegarles en rafaga es abusar de ellos."""
    assert FuenteRemota.espera_entre_peticiones >= 1.0
    assert FuenteOSM().espera_entre_peticiones >= 1.0


def test_los_codigos_transitorios_incluyen_los_de_saturacion():
    """429 y 504 son "estoy ocupado", no "tu peticion esta mal"."""
    for codigo in (429, 500, 502, 503, 504):
        assert codigo in FuenteRemota.CODIGOS_TRANSITORIOS
    for codigo in (400, 401, 404, 422):
        assert codigo not in FuenteRemota.CODIGOS_TRANSITORIOS


def test_power_valida_los_anios():
    with pytest.raises(ValueError, match="anio_fin"):
        FuentePOWER(anio_inicio=2020, anio_fin=2010)


# --- integracion con OpenStreetMap ----------------------------------------


@pytest.fixture(scope="module")
def capas_osm(malla):
    try:
        return FuenteOSM().capas(malla)
    except (ErrorFuente, OSError) as e:
        _sin_red("Overpass", malla, e)


def test_osm_entrega_las_capas_esperadas(capas_osm):
    esperadas = {
        "fraccion_impermeable", "fraccion_construida", "fraccion_pavimento",
        "fraccion_agua", "impermeabilidad_uso_suelo", "cobertura_uso_suelo",
        "impermeabilidad_proxy_vial", "densidad_vial", "densidad_cauces",
        "edificios", "area_pisos", "infraestructura_critica", "peso_critico",
    }
    assert esperadas <= set(capas_osm)


def test_las_fracciones_de_osm_estan_en_rango(capas_osm):
    for nombre in ("fraccion_impermeable", "fraccion_construida",
                   "fraccion_pavimento", "fraccion_agua",
                   "impermeabilidad_uso_suelo", "cobertura_uso_suelo",
                   "impermeabilidad_proxy_vial"):
        v = capas_osm[nombre].valores
        finitos = np.isfinite(v)
        assert np.all((v[finitos] >= 0.0) & (v[finitos] <= 1.0)), nombre


def test_los_conteos_de_osm_no_son_negativos(capas_osm):
    for nombre in ("edificios", "area_pisos", "infraestructura_critica",
                   "peso_critico", "densidad_vial", "densidad_cauces"):
        v = capas_osm[nombre].valores
        assert np.all(v[np.isfinite(v)] >= 0.0), nombre


def test_la_celda_del_puerto_es_la_mas_urbana(capas_osm, malla):
    """OT0.0.0 es el centro del enlace de OSM, o sea el puerto de Veracruz.
    Si la celda mas impermeable no cae en la zona urbana, algo se rompio en la
    agregacion espacial.

    Esta prueba caza un bug real que ya ocurrio: al promediar la
    impermeabilidad solo entre los puntos CON uso de suelo mapeado, una celda
    rural con un poligono industrial diminuto salia al 85%, por encima del
    puerto.
    """
    imperm = capas_osm["fraccion_impermeable"].valores
    i_max = int(np.argmax(np.nan_to_num(imperm)))
    # La celda mas impermeable tiene que estar a menos de 15 km del centro.
    from ojo_tlaloc.geo import haversine_km

    d = float(haversine_km(malla.lat[i_max], malla.lon[i_max],
                           19.1704, -96.1654))
    assert d < 15.0, "la celda mas impermeable quedo a {:.0f} km del puerto".format(d)
    assert imperm[i_max] > 0.4, "el centro de una ciudad no puede ser 40% permeable"


def test_la_densidad_vial_distingue_ciudad_de_campo(capas_osm):
    vial = capas_osm["densidad_vial"].valores
    assert vial.max() > 10.0      # zona urbana
    assert np.median(vial) < 3.0  # el dominio es mayormente rural y mar


def test_osm_declara_licencia_y_atribucion(capas_osm):
    for capa in capas_osm.values():
        assert capa.procedencia.licencia == "ODbL"
        assert "OpenStreetMap" in capa.procedencia.atribucion


def test_el_proxy_vial_se_declara_como_proxy(capas_osm):
    """No es una medicion de superficie impermeable y no puede presentarse
    como tal."""
    p = capas_osm["impermeabilidad_proxy_vial"].procedencia
    assert p.nivel == NIVEL_DERIVADO
    assert "NO una medicion" in p.nota
    assert p.incertidumbre is not None


def test_la_impermeabilidad_combinada_domina_a_sus_componentes(capas_osm):
    """Se toma el maximo de las tres vias, asi que no puede quedar por debajo
    de ninguna (salvo por el descuento de agua)."""
    comb = capas_osm["fraccion_impermeable"].valores
    agua = capas_osm["fraccion_agua"].valores
    for nombre in ("impermeabilidad_proxy_vial", "impermeabilidad_uso_suelo"):
        componente = np.nan_to_num(capas_osm[nombre].valores)
        assert np.all(comb >= componente * (1.0 - agua) - 1e-9), nombre


def test_el_cache_de_osm_evita_volver_a_descargar(malla, capas_osm):
    """La segunda construccion debe salir del cache y ser mucho mas rapida."""
    import time

    t0 = time.perf_counter()
    FuenteOSM().capas(malla)
    assert time.perf_counter() - t0 < 60.0


# --- integracion con NASA POWER -------------------------------------------


@pytest.fixture(scope="module")
def paquete_power(malla):
    try:
        fuente = FuentePOWER()
        fuente.calibrar_umbral_por_dias(malla)
        return fuente.series_para_malla(malla)
    except (ErrorFuente, OSError) as e:
        _sin_red("NASA POWER", malla, e)


def test_power_entrega_las_seis_series(paquete_power):
    """Son exactamente las que consume Climatologia.desde_normales()."""
    s = paquete_power["series"]
    for nombre in ("frac_dias_lluvia", "lluvia_mensual_mm", "weibull_forma",
                   "rho_persistencia", "tmax_mensual", "tmin_mensual"):
        assert nombre in s
        assert len(s[nombre]) == 12, nombre


def test_las_series_de_power_son_fisicamente_posibles(paquete_power):
    s = paquete_power["series"]
    assert np.all((s["frac_dias_lluvia"] > 0) & (s["frac_dias_lluvia"] < 1))
    assert np.all(s["lluvia_mensual_mm"] >= 0)
    assert np.all((s["weibull_forma"] > 0.3) & (s["weibull_forma"] < 3.0))
    assert np.all((s["rho_persistencia"] >= 0) & (s["rho_persistencia"] < 1))
    assert np.all(s["tmax_mensual"] > s["tmin_mensual"])
    assert np.all((s["tmax_mensual"] > 10) & (s["tmax_mensual"] < 45))


def test_power_reproduce_el_clima_de_veracruz(paquete_power):
    """Normales conocidas de la zona: del orden de 1650 mm al ano concentrados
    de junio a octubre."""
    s = paquete_power["series"]
    anual = float(s["lluvia_mensual_mm"].sum())
    assert 1200.0 < anual < 2300.0, "lluvia anual de {:.0f} mm".format(anual)
    # Temporada de lluvias de junio a octubre: mas de la mitad del total.
    temporada = float(s["lluvia_mensual_mm"][5:10].sum())
    assert temporada / anual > 0.55
    # El mes mas lluvioso cae en la temporada.
    assert 5 <= int(np.argmax(s["lluvia_mensual_mm"])) <= 9


def test_el_umbral_calibrado_corrige_el_sesgo_de_llovizna(malla, paquete_power):
    """Con el umbral de 1 mm de la OMM, POWER daba 195 dias de lluvia al ano
    contra los 115-130 de las normales: es el sesgo de llovizna de los
    reanalisis."""
    s = paquete_power["series"]
    dias = float((s["frac_dias_lluvia"] * DIAS_POR_MES_MEDIO).sum())
    assert 100.0 < dias < 150.0, "{:.0f} dias de lluvia al ano".format(dias)


def test_power_declara_sus_sesgos(paquete_power):
    """Una fuente que conoce sus propios limites vale mucho mas que una que
    entrega numeros sin contexto."""
    advertencias = paquete_power["advertencias"]
    variables = {a["variable"] for a in advertencias}
    assert "weibull_forma" in variables
    assert "frac_dias_lluvia" in variables
    assert "tmax_mensual" in variables
    for a in advertencias:
        assert a["detalle"] and a["como_se_corrige"]


def test_power_se_marca_como_reanalisis_no_como_observacion(paquete_power):
    """MERRA-2 es un modelo alimentado con observaciones, no una medicion."""
    assert paquete_power["procedencia"].nivel == NIVEL_REANALISIS
    for capa in paquete_power["capas"].values():
        assert capa.procedencia.nivel == NIVEL_REANALISIS


def test_las_capas_por_celda_de_power_son_suaves(paquete_power):
    """La resolucion nativa es de ~50 km, asi que dentro del dominio la
    variacion tiene que ser suave: si saliera ruidosa, la interpolacion
    estaria inventando detalle que la fuente no tiene."""
    v = paquete_power["capas"]["lluvia_anual_power_mm"].valores
    assert np.all(v > 500) and np.all(v < 4000)
    assert (v.max() - v.min()) / v.mean() < 0.6


def test_la_climatologia_de_power_alimenta_el_modelo(malla, paquete_power):
    """La prueba que importa: las series reales entran al modelo y producen un
    clima consistente."""
    from ojo_tlaloc.climatologia import Climatologia

    clima = Climatologia.desde_normales(malla, **paquete_power["series"])
    # La calibracion de la cadena de Markov sigue siendo exacta con datos
    # reales, no solo con los sinteticos.
    for mes in range(1, 13):
        assert np.abs(clima.prob_estacionaria(mes)
                      - clima.prob_lluvia[:, mes - 1]).max() < 1e-12
    resumen = clima.resumen()
    assert 1000 < resumen["lluvia_anual_media_mm"] < 2600
    assert 90 < resumen["dias_lluvia_anuales"] < 160
