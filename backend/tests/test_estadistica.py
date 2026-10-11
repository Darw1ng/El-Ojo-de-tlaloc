"""Pruebas de las primitivas estadisticas.

Todas se verifican contra algo independiente: la stdlib (math.erfc), valores
publicados, o una identidad analitica. Una prueba que solo compare la funcion
consigo misma no sirve de nada.
"""

import math

import numpy as np
import pytest

from ojo_tlaloc.estadistica import (
    CampoEspacial,
    erfc,
    norm_cdf,
    norm_ppf,
    weibull_cdf,
    weibull_media,
    weibull_ppf,
)


# --- normal ----------------------------------------------------------------


def test_erfc_contra_la_stdlib():
    xs = np.linspace(-6.0, 6.0, 1201)
    mio = erfc(xs)
    ref = np.array([math.erfc(float(x)) for x in xs])
    error = np.abs(mio - ref) / np.maximum(ref, 1e-300)
    assert error.max() < 1.2e-7, "error fraccional {:.2e}".format(error.max())


def test_norm_cdf_valores_conocidos():
    # La tolerancia es 1e-7 porque esa es la precision real de la erfc de
    # Numerical Recipes que usa norm_cdf. Pedir mas seria fingir una exactitud
    # que la implementacion no tiene: norm_cdf(0) da 0.50000002, no 0.5.
    assert float(norm_cdf(0.0)) == pytest.approx(0.5, abs=1e-7)
    assert float(norm_cdf(1.959963985)) == pytest.approx(0.975, abs=1e-7)
    assert float(norm_cdf(-1.959963985)) == pytest.approx(0.025, abs=1e-7)
    assert float(norm_cdf(-8.0)) < 1e-14
    assert float(norm_cdf(8.0)) == pytest.approx(1.0, abs=1e-14)


def test_norm_cdf_monotona():
    xs = np.linspace(-5, 5, 500)
    v = norm_cdf(xs)
    assert np.all(np.diff(v) >= 0)


def test_norm_ppf_valores_publicados():
    assert float(norm_ppf(0.975)) == pytest.approx(1.959963985, abs=1e-6)
    assert float(norm_ppf(0.95)) == pytest.approx(1.644853627, abs=1e-6)
    assert float(norm_ppf(0.5)) == pytest.approx(0.0, abs=1e-12)
    assert float(norm_ppf(0.01)) == pytest.approx(-2.326347874, abs=1e-6)


def test_norm_ppf_es_inversa_de_cdf():
    ps = np.array([1e-9, 1e-5, 0.001, 0.02, 0.0242, 0.025, 0.3, 0.5,
                   0.7, 0.975, 0.999, 1 - 1e-5])
    assert np.abs(norm_cdf(norm_ppf(ps)) - ps).max() < 1e-7


def test_norm_ppf_bordes_y_fuera_de_rango():
    assert float(norm_ppf(0.0)) == -np.inf
    assert float(norm_ppf(1.0)) == np.inf
    assert math.isnan(float(norm_ppf(-0.1)))
    assert math.isnan(float(norm_ppf(1.1)))


# --- weibull ---------------------------------------------------------------


def test_weibull_cdf_y_ppf_son_inversas():
    u = np.linspace(1e-6, 1 - 1e-6, 999)
    for forma in (0.7, 0.85, 1.0, 1.5):
        x = weibull_ppf(u, forma, 12.0)
        assert np.abs(weibull_cdf(x, forma, 12.0) - u).max() < 1e-9


def test_weibull_mediana_analitica():
    """La mediana de la Weibull es escala * (ln 2)^(1/forma)."""
    for forma, escala in ((0.8, 15.0), (1.2, 7.0)):
        esperada = escala * math.log(2.0) ** (1.0 / forma)
        assert float(weibull_ppf(0.5, forma, escala)) == pytest.approx(esperada)


def test_weibull_media_contra_montecarlo():
    rng = np.random.default_rng(11)
    forma, escala = 0.85, 14.0
    muestras = weibull_ppf(rng.random(400_000), forma, escala)
    assert float(weibull_media(forma, escala)) == pytest.approx(
        float(muestras.mean()), rel=0.02
    )


def test_forma_menor_a_uno_tiene_cola_mas_pesada():
    """Es el motivo de usar forma < 1 para lluvia convectiva."""
    u = 0.999
    cola_pesada = float(weibull_ppf(u, 0.7, 10.0)) / float(weibull_media(0.7, 10.0))
    cola_ligera = float(weibull_ppf(u, 1.5, 10.0)) / float(weibull_media(1.5, 10.0))
    assert cola_pesada > cola_ligera


# --- campo espacial --------------------------------------------------------


@pytest.fixture(scope="module")
def distancias():
    """Rejilla de 12x12 puntos separados 5 km."""
    xs, ys = np.meshgrid(np.arange(12) * 5.0, np.arange(12) * 5.0)
    p = np.stack([xs.ravel(), ys.ravel()], axis=1)
    return np.sqrt(((p[:, None, :] - p[None, :, :]) ** 2).sum(axis=2))


def test_campo_reproduce_la_correlacion_objetivo(distancias):
    L = 25.0
    campo = CampoEspacial(distancias, longitud_correlacion_km=L)
    rng = np.random.default_rng(42)
    w = campo.muestra(rng, 6000)
    empirica = np.corrcoef(w.T)
    objetivo = np.exp(-distancias / L)
    assert np.abs(empirica - objetivo).max() < 0.07


def test_campo_tiene_varianza_unitaria(distancias):
    campo = CampoEspacial(distancias, longitud_correlacion_km=25.0)
    rng = np.random.default_rng(1)
    w = campo.muestra(rng, 8000)
    assert float(w.var(axis=0).mean()) == pytest.approx(1.0, abs=0.05)


def test_serie_ar1_respeta_la_persistencia(distancias):
    phi = 0.7
    campo = CampoEspacial(distancias, longitud_correlacion_km=25.0, persistencia=phi)
    rng = np.random.default_rng(3)
    s = campo.serie(rng, 4000)
    lags = [np.corrcoef(s[:-1, i], s[1:, i])[0, 1] for i in range(0, s.shape[1], 10)]
    assert float(np.mean(lags)) == pytest.approx(phi, abs=0.05)


def test_la_serie_ar1_conserva_varianza_marginal(distancias):
    """Si no la conservara, los umbrales de ocurrencia calibrados en unidades
    de normal estandar dejarian de ser validos con el paso de los dias."""
    campo = CampoEspacial(distancias, longitud_correlacion_km=25.0, persistencia=0.8)
    rng = np.random.default_rng(5)
    s = campo.serie(rng, 3000)
    assert float(s.var()) == pytest.approx(1.0, abs=0.08)
    # Y tampoco debe derivar: la varianza del final como la del principio.
    assert float(s[-500:].var()) == pytest.approx(float(s[:500].var()), rel=0.15)


def test_longitud_de_correlacion_mas_larga_da_campos_mas_suaves(distancias):
    rng = np.random.default_rng(7)
    corto = CampoEspacial(distancias, longitud_correlacion_km=5.0).muestra(rng, 2000)
    largo = CampoEspacial(distancias, longitud_correlacion_km=80.0).muestra(rng, 2000)
    # Vecinos inmediatos en la rejilla (indices contiguos, 5 km aparte).
    c_corto = np.corrcoef(corto[:, 0], corto[:, 1])[0, 1]
    c_largo = np.corrcoef(largo[:, 0], largo[:, 1])[0, 1]
    assert c_largo > c_corto


def test_campo_valida_sus_argumentos(distancias):
    with pytest.raises(ValueError, match="cuadrada"):
        CampoEspacial(np.zeros((3, 4)))
    with pytest.raises(ValueError, match="correlacion"):
        CampoEspacial(distancias, longitud_correlacion_km=0.0)
    with pytest.raises(ValueError, match="persistencia"):
        CampoEspacial(distancias, persistencia=1.0)


def test_estado_inicial_de_tamano_equivocado(distancias):
    campo = CampoEspacial(distancias, persistencia=0.5)
    with pytest.raises(ValueError, match="estado_inicial"):
        campo.serie(np.random.default_rng(0), 5, estado_inicial=np.zeros(3))
