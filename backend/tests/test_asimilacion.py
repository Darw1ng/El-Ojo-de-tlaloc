"""Pruebas de la asimilacion de humedad de suelo (el enlace con NISAR)."""

import numpy as np
import pytest

from ojo_tlaloc.asimilacion import (
    SIGMA_OBS_DEFECTO,
    TEXTURAS,
    ObservacionHumedad,
    agregar_a_malla,
    asimilar,
    observacion_sintetica,
    volumetrica_a_saturacion,
)

from .conftest import FECHA_PRUEBA, SEMILLA


# --- conversion de unidades ------------------------------------------------


def test_volumetrica_a_saturacion_en_los_extremos():
    t = TEXTURAS["franco"]
    assert float(volumetrica_a_saturacion(t["residual"])) == pytest.approx(0.0)
    assert float(volumetrica_a_saturacion(t["saturacion"])) == pytest.approx(1.0)
    # A medio camino.
    medio = (t["residual"] + t["saturacion"]) / 2.0
    assert float(volumetrica_a_saturacion(medio)) == pytest.approx(0.5)


def test_volumetrica_se_recorta_al_rango_valido():
    assert float(volumetrica_a_saturacion(0.0)) == 0.0
    assert float(volumetrica_a_saturacion(0.9)) == 1.0


def test_la_textura_cambia_el_resultado():
    """El sesgo documentado: la misma lectura de radar da saturaciones
    distintas segun la textura que se le suponga al suelo."""
    theta = 0.25
    arena = float(volumetrica_a_saturacion(theta, "arena"))
    arcilla = float(volumetrica_a_saturacion(theta, "arcilla"))
    assert abs(arena - arcilla) > 0.05


def test_textura_desconocida():
    with pytest.raises(ValueError, match="textura"):
        volumetrica_a_saturacion(0.2, "queso")


# --- agregacion de pixeles a hexagonos -------------------------------------


def test_un_punto_en_el_centro_cae_en_su_celda(malla):
    i = malla.n_celdas // 3
    prom, conteo = agregar_a_malla(
        malla, [float(malla.lat[i])], [float(malla.lon[i])], [0.42]
    )
    assert conteo[i] == 1
    assert prom[i] == pytest.approx(0.42)
    assert np.isnan(prom[(i + 1) % malla.n_celdas])


def test_promedia_varios_pixeles_en_la_misma_celda(malla):
    i = 40
    lat = [float(malla.lat[i])] * 3
    lon = [float(malla.lon[i])] * 3
    prom, conteo = agregar_a_malla(malla, lat, lon, [0.2, 0.4, 0.6])
    assert conteo[i] == 3
    assert prom[i] == pytest.approx(0.4)


def test_minimo_de_pixeles_descarta_celdas_pobres(malla):
    i = 10
    prom, _ = agregar_a_malla(
        malla, [float(malla.lat[i])], [float(malla.lon[i])], [0.5],
        minimo_pixeles=5,
    )
    assert np.isnan(prom[i])


def test_los_nan_no_contaminan_el_promedio(malla):
    i = 15
    prom, conteo = agregar_a_malla(
        malla, [float(malla.lat[i])] * 2, [float(malla.lon[i])] * 2,
        [0.3, np.nan],
    )
    assert conteo[i] == 1
    assert prom[i] == pytest.approx(0.3)


def test_agregar_valida_largos(malla):
    with pytest.raises(ValueError, match="mismo largo"):
        agregar_a_malla(malla, [19.0], [-96.0, -96.1], [0.3])


def test_cada_punto_va_a_su_celda_mas_cercana(malla):
    """Un hexagono regular es su propia celda de Voronoi, asi que asignar al
    centro mas cercano es exactamente asignar al hexagono que contiene el
    punto. Se verifica con muchos puntos al azar."""
    rng = np.random.default_rng(4)
    n = 500
    lat = rng.uniform(malla.bbox.lat_min, malla.bbox.lat_max, n)
    lon = rng.uniform(malla.bbox.lon_min, malla.bbox.lon_max, n)
    _, conteo = agregar_a_malla(malla, lat, lon, np.ones(n))
    assert conteo.sum() == n


# --- observacion -----------------------------------------------------------


def test_la_observacion_valida_su_rango(malla):
    with pytest.raises(ValueError, match="saturacion"):
        ObservacionHumedad(valores=np.full(malla.n_celdas, 1.5))
    with pytest.raises(ValueError, match="n_celdas"):
        ObservacionHumedad(valores=np.zeros((3, 3)))


def test_la_observacion_acepta_huecos(malla):
    v = np.full(malla.n_celdas, np.nan)
    v[:10] = 0.5
    obs = ObservacionHumedad(valores=v)
    assert obs.n_observadas == 10


def test_la_sintetica_se_declara_sintetica(malla, clima):
    """Para que nunca se presente como dato real por accidente."""
    obs = observacion_sintetica(malla, clima, FECHA_PRUEBA, semilla=1)
    assert "sintetico" in obs.fuente.lower()
    assert "no es NISAR" in obs.fuente


def test_la_sintetica_no_observa_el_mar(malla, clima):
    obs = observacion_sintetica(malla, clima, FECHA_PRUEBA, cobertura=1.0, semilla=1)
    assert np.all(np.isnan(obs.valores[~clima.es_tierra]))
    assert np.all(np.isfinite(obs.valores[clima.es_tierra]))


def test_la_cobertura_deja_huecos(malla, clima):
    """El radar no ve todo: agua, vegetacion densa y sombra de radar."""
    completa = observacion_sintetica(malla, clima, FECHA_PRUEBA, cobertura=1.0,
                                     semilla=2)
    parcial = observacion_sintetica(malla, clima, FECHA_PRUEBA, cobertura=0.5,
                                    semilla=2)
    assert parcial.n_observadas < completa.n_observadas


# --- filtro de Kalman de ensamble ------------------------------------------


@pytest.fixture
def ensamble_previo(malla, clima):
    """Ensamble sintetico con media 0.8 y dispersion conocida."""
    rng = np.random.default_rng(5)
    s = np.clip(0.8 + rng.normal(0.0, 0.10, (400, malla.n_celdas)), 0.0, 1.0)
    s[:, ~clima.es_tierra] = np.nan
    return s


def test_la_media_posterior_sigue_la_formula_de_kalman(ensamble_previo, malla, clima):
    """K = var_mod / (var_mod + var_obs) y media+ = media + K(y - media).
    Con 400 miembros el ruido de Monte Carlo del EnKF es chico."""
    i = int(np.where(clima.es_tierra)[0][0])
    v = np.full(malla.n_celdas, np.nan)
    v[i] = 0.30
    obs = ObservacionHumedad(valores=v, sigma=SIGMA_OBS_DEFECTO)

    previa = float(np.nanmean(ensamble_previo[:, i]))
    var_mod = float(np.nanvar(ensamble_previo[:, i], ddof=1))
    k = var_mod / (var_mod + SIGMA_OBS_DEFECTO ** 2)
    esperada = previa + k * (0.30 - previa)

    res = asimilar(ensamble_previo, obs, rng=np.random.default_rng(6))
    obtenida = float(np.nanmean(res["ensamble"][:, i]))
    assert obtenida == pytest.approx(esperada, abs=0.02)


def test_la_asimilacion_acerca_la_media_a_la_observacion(ensamble_previo, malla, clima):
    v = np.where(clima.es_tierra, 0.30, np.nan)
    obs = ObservacionHumedad(valores=v)
    previa = np.nanmean(ensamble_previo, axis=0)
    res = asimilar(ensamble_previo, obs, rng=np.random.default_rng(7))
    post = np.nanmean(res["ensamble"], axis=0)
    tierra = clima.es_tierra
    assert np.all(np.abs(post[tierra] - 0.30) < np.abs(previa[tierra] - 0.30))


def test_la_asimilacion_reduce_la_incertidumbre(ensamble_previo, clima):
    obs = ObservacionHumedad(valores=np.where(clima.es_tierra, 0.30, np.nan))
    res = asimilar(ensamble_previo, obs, rng=np.random.default_rng(8))
    d = res["diagnostico"]
    assert 0.0 < d["ganancia_media"] < 1.0
    assert d["reduccion_varianza_media"] > 0.0
    assert d["dispersion_posterior_media"] < d["dispersion_previa_media"]


def test_el_ensamble_no_colapsa(ensamble_previo, clima):
    """La razon de perturbar la observacion: sin eso todos los miembros
    terminan en el mismo valor y el pronostico se vuelve sobreconfiado."""
    obs = ObservacionHumedad(valores=np.where(clima.es_tierra, 0.30, np.nan))
    res = asimilar(ensamble_previo, obs, rng=np.random.default_rng(9))
    tierra = clima.es_tierra
    disp = np.nanstd(res["ensamble"][:, tierra], axis=0)
    assert np.all(disp > 0.01), "el ensamble colapso"


def test_una_observacion_mas_precisa_pesa_mas(ensamble_previo, clima):
    tierra = clima.es_tierra
    v = np.where(tierra, 0.30, np.nan)
    precisa = asimilar(ensamble_previo, ObservacionHumedad(valores=v, sigma=0.01),
                       rng=np.random.default_rng(10))
    burda = asimilar(ensamble_previo, ObservacionHumedad(valores=v, sigma=0.50),
                     rng=np.random.default_rng(10))
    assert (precisa["diagnostico"]["ganancia_media"]
            > burda["diagnostico"]["ganancia_media"])
    cerca = abs(float(np.nanmean(precisa["ensamble"][:, tierra])) - 0.30)
    lejos = abs(float(np.nanmean(burda["ensamble"][:, tierra])) - 0.30)
    assert cerca < lejos


def test_las_celdas_sin_observacion_no_se_tocan(ensamble_previo, malla, clima):
    i = int(np.where(clima.es_tierra)[0][0])
    j = int(np.where(clima.es_tierra)[0][-1])
    v = np.full(malla.n_celdas, np.nan)
    v[i] = 0.30
    res = asimilar(ensamble_previo, ObservacionHumedad(valores=v),
                   rng=np.random.default_rng(11))
    assert not np.allclose(res["ensamble"][:, i], ensamble_previo[:, i])
    assert np.allclose(res["ensamble"][:, j], ensamble_previo[:, j], equal_nan=True)


def test_el_resultado_se_queda_en_el_rango_fisico(ensamble_previo, clima):
    obs = ObservacionHumedad(valores=np.where(clima.es_tierra, 0.0, np.nan))
    res = asimilar(ensamble_previo, obs, rng=np.random.default_rng(12))
    s = res["ensamble"][:, clima.es_tierra]
    assert np.nanmin(s) >= 0.0 and np.nanmax(s) <= 1.0


def test_asimilar_valida_formas(ensamble_previo, malla):
    with pytest.raises(ValueError, match="n_miembros"):
        asimilar(np.zeros(10), ObservacionHumedad(valores=np.zeros(malla.n_celdas)))
    with pytest.raises(ValueError, match="no coincide"):
        asimilar(ensamble_previo, ObservacionHumedad(valores=np.zeros(5)))
    with pytest.raises(ValueError, match="sigma"):
        asimilar(ensamble_previo,
                 ObservacionHumedad(valores=np.zeros(malla.n_celdas), sigma=0.0))


def test_el_diagnostico_reporta_la_cobertura(ensamble_previo, malla, clima):
    v = np.full(malla.n_celdas, np.nan)
    idx = np.where(clima.es_tierra)[0][:7]
    v[idx] = 0.4
    res = asimilar(ensamble_previo, ObservacionHumedad(valores=v),
                   rng=np.random.default_rng(13))
    assert res["diagnostico"]["celdas_observadas"] == 7
    assert res["diagnostico"]["celdas_totales"] == malla.n_celdas


def test_ciclo_completo_observar_asimilar_pronosticar(simulador, malla, clima):
    """La cadena que se presenta: el radar corrige el suelo y eso cambia el
    escurrimiento del dia siguiente. Si esta prueba falla, la historia del
    proyecto no se sostiene."""
    previo = simulador.simular(
        FECHA_PRUEBA, n_dias=1, n_miembros=150, semilla=SEMILLA
    ).humedad_suelo[:, 0, :].astype(float)

    seco = ObservacionHumedad(valores=np.where(clima.es_tierra, 0.10, np.nan))
    mojado = ObservacionHumedad(valores=np.where(clima.es_tierra, 0.90, np.nan))

    tras_seco = asimilar(previo, seco, rng=np.random.default_rng(14))["ensamble"]
    tras_mojado = asimilar(previo, mojado, rng=np.random.default_rng(14))["ensamble"]

    pron_seco = simulador.simular(
        FECHA_PRUEBA, n_dias=3, n_miembros=150, semilla=99,
        humedad_inicial=np.nan_to_num(tras_seco, nan=0.5), dias_calentamiento=0,
    )
    pron_mojado = simulador.simular(
        FECHA_PRUEBA, n_dias=3, n_miembros=150, semilla=99,
        humedad_inicial=np.nan_to_num(tras_mojado, nan=0.5), dias_calentamiento=0,
    )

    tierra = clima.es_tierra
    assert (pron_mojado.escurrimiento_mm[:, 0, tierra].mean()
            > pron_seco.escurrimiento_mm[:, 0, tierra].mean())
    # Y la misma lluvia: el cambio viene del suelo, no de otra realizacion.
    assert np.allclose(pron_seco.lluvia_mm, pron_mojado.lluvia_mm)
