"""Pruebas del resumen probabilistico y de las metricas de verificacion."""

import math

import numpy as np
import pytest

from ojo_tlaloc.ensamble import (
    CORTES_RIESGO,
    ETIQUETA_SIN_DOMINIO,
    ETIQUETAS_RIESGO,
    capa,
    probabilidad_umbral,
    resumen_dominio,
    riesgo,
    serie_celda,
)
from ojo_tlaloc.metricas import (
    brier,
    brier_skill,
    confiabilidad,
    crps,
    crpss,
    descomposicion_brier,
    dispersion_vs_error,
    tabla_contingencia,
)


# --- capas -----------------------------------------------------------------


def test_capa_devuelve_un_valor_por_celda(corrida, malla):
    c = capa(corrida, "lluvia", dia=0, estadistico="p50")
    assert len(c["valores"]) == malla.n_celdas
    assert c["fecha"] == corrida.fechas[0]
    assert c["escala"]["unidad"] == "mm/dia"


def test_los_percentiles_estan_ordenados(corrida):
    p10 = capa(corrida, "lluvia", 3, "p10")["valores"]
    p50 = capa(corrida, "lluvia", 3, "p50")["valores"]
    p90 = capa(corrida, "lluvia", 3, "p90")["valores"]
    assert np.all(p10 <= p50 + 1e-9)
    assert np.all(p50 <= p90 + 1e-9)


def test_la_media_cae_entre_los_extremos(corrida):
    media = capa(corrida, "tmax", 2, "media")["valores"]
    p10 = capa(corrida, "tmax", 2, "p10")["valores"]
    p90 = capa(corrida, "tmax", 2, "p90")["valores"]
    assert np.all(media >= p10 - 1e-6) and np.all(media <= p90 + 1e-6)


def test_el_rango_es_el_intervalo_central_del_80(corrida):
    rango = capa(corrida, "lluvia", 1, "rango")["valores"]
    p10 = capa(corrida, "lluvia", 1, "p10")["valores"]
    p90 = capa(corrida, "lluvia", 1, "p90")["valores"]
    assert np.allclose(rango, p90 - p10)
    assert np.all(rango >= 0)


def test_capa_rechaza_entradas_invalidas(corrida):
    with pytest.raises(IndexError, match="fuera del horizonte"):
        capa(corrida, "lluvia", dia=999)
    with pytest.raises(KeyError):
        capa(corrida, "no_existe", dia=0)
    with pytest.raises(ValueError, match="estadistico"):
        capa(corrida, "lluvia", 0, "promedio_raro")
    with pytest.raises(ValueError, match="percentil"):
        capa(corrida, "lluvia", 0, "p150")


# --- probabilidades --------------------------------------------------------


def test_probabilidad_en_el_rango_valido(corrida):
    p = probabilidad_umbral(corrida, "lluvia", 0, umbral=20.0, ventana_dias=3)
    v = p["valores"]
    assert np.all((v >= 0.0) & (v <= 1.0))
    assert p["modo"] == "acumulado"
    assert p["ventana_dias"] == 3


def test_umbral_mas_alto_da_probabilidad_menor(corrida):
    baja = probabilidad_umbral(corrida, "lluvia", 0, umbral=5.0)["valores"]
    alta = probabilidad_umbral(corrida, "lluvia", 0, umbral=80.0)["valores"]
    assert np.all(alta <= baja + 1e-12)
    assert baja.mean() > alta.mean()


def test_ventana_mas_larga_acumula_mas(corrida):
    un_dia = probabilidad_umbral(corrida, "lluvia", 0, umbral=20.0, ventana_dias=1)
    cinco = probabilidad_umbral(corrida, "lluvia", 0, umbral=20.0, ventana_dias=5)
    assert cinco["valores"].mean() > un_dia["valores"].mean()


def test_las_variables_de_estado_usan_maximo_no_suma(corrida):
    """Sumar temperaturas de varios dias no significa nada: para esas
    variables la ventana tiene que tomar el maximo."""
    p = probabilidad_umbral(corrida, "tmax", 0, umbral=30.0, ventana_dias=3)
    assert p["modo"] == "maximo"
    assert np.all(p["valores"] <= 1.0)


def test_probabilidad_valida_la_ventana(corrida):
    with pytest.raises(ValueError, match="ventana_dias"):
        probabilidad_umbral(corrida, "lluvia", 0, 10.0, ventana_dias=0)


def test_la_ventana_se_recorta_al_final_del_horizonte(corrida):
    p = probabilidad_umbral(corrida, "lluvia", dia=8, umbral=10.0, ventana_dias=10)
    assert p["ventana_dias"] == corrida.n_dias - 8


# --- riesgo ----------------------------------------------------------------


def test_riesgo_devuelve_categorias_coherentes(corrida, clima):
    r = riesgo(corrida, dia=0, ventana_dias=3, umbral_mm=40.0)
    v, cat = r["valores"], r["categoria"]
    tierra = clima.es_tierra
    assert np.all((v[tierra] >= 0) & (v[tierra] <= 1))
    assert len(cat) == len(v)
    assert len(ETIQUETAS_RIESGO) == len(CORTES_RIESGO) + 1
    # La categoria y su etiqueta son consistentes con los cortes declarados,
    # y las celdas sin dominio llevan -1 / "no aplica" en vez de caer en el
    # ultimo cajon por el comportamiento de np.digitize con NaN.
    for i, (prob, k) in enumerate(zip(v, cat)):
        if np.isfinite(prob):
            assert int(k) == int(np.digitize(prob, CORTES_RIESGO))
            assert r["etiqueta_categoria"][i] == ETIQUETAS_RIESGO[int(k)]
        else:
            assert int(k) == -1
            assert r["etiqueta_categoria"][i] == ETIQUETA_SIN_DOMINIO
    assert -1 not in cat[tierra]


def test_umbral_de_riesgo_mas_bajo_da_mas_alerta(corrida):
    laxo = np.nanmean(riesgo(corrida, 0, 3, umbral_mm=10.0)["valores"])
    estricto = np.nanmean(riesgo(corrida, 0, 3, umbral_mm=200.0)["valores"])
    assert laxo > estricto


# --- series y resumen ------------------------------------------------------


def test_serie_celda_trae_bandas_y_trayectorias(corrida):
    s = serie_celda(corrida, 50)
    assert s["id_celda"] == corrida.ids_celdas[50]
    assert len(s["fechas"]) == corrida.n_dias
    lluvia = s["variables"]["lluvia"]
    assert len(lluvia["p50"]) == corrida.n_dias
    assert np.all(lluvia["p10"] <= lluvia["p90"] + 1e-9)
    assert lluvia["miembros_muestra"].shape[1] == corrida.n_dias
    assert 1 <= lluvia["miembros_muestra"].shape[0] <= 20


def test_serie_celda_valida_el_indice(corrida):
    with pytest.raises(IndexError):
        serie_celda(corrida, 10**6)
    with pytest.raises(IndexError):
        serie_celda(corrida, -1)


def test_resumen_dominio(corrida, clima):
    r = resumen_dominio(corrida, clima.es_tierra)
    assert r["dias"] == corrida.n_dias
    assert r["miembros"] == corrida.n_miembros
    assert r["fecha_inicio"] == corrida.fechas[0]
    t = r["lluvia_total_mm"]
    assert t["p10"] <= t["p50"] <= t["p90"]
    assert 0 <= r["dia_mas_lluvioso"] < corrida.n_dias
    assert 0.0 <= r["humedad_suelo_p50_final"] <= 1.0


# --- metricas --------------------------------------------------------------


def test_crps_de_un_deterministra_es_el_error_absoluto():
    assert crps(np.array([[3.0]]), np.array([5.0])).item() == pytest.approx(2.0)


def test_crps_de_la_normal_estandar_contra_su_valor_analitico():
    """Para un pronostico N(0,1) y observacion y=0:
    CRPS = 2*phi(0) - 1/sqrt(pi) = 0.2336949."""
    rng = np.random.default_rng(3)
    ens = rng.standard_normal((40_000, 1))
    analitico = 2.0 / math.sqrt(2 * math.pi) - 1.0 / math.sqrt(math.pi)
    assert crps(ens, np.array([0.0])).item() == pytest.approx(analitico, abs=0.005)


def test_el_crps_premia_acertar():
    rng = np.random.default_rng(1)
    bueno = 2.0 + rng.standard_normal((500, 1)) * 0.5
    malo = 8.0 + rng.standard_normal((500, 1)) * 0.5
    y = np.array([2.0])
    assert crps(bueno, y).item() < crps(malo, y).item()


def test_el_estimador_justo_resta_mas_que_el_clasico():
    """Divide entre m(m-1) en vez de m^2: el termino de dispersion es mayor,
    asi que el CRPS justo queda por debajo del clasico."""
    rng = np.random.default_rng(2)
    ens = rng.standard_normal((20, 1))
    y = np.array([0.0])
    assert crps(ens, y, justo=True).item() < crps(ens, y, justo=False).item()


def test_crps_valida_formas():
    with pytest.raises(ValueError, match="observado"):
        crps(np.zeros((10, 5)), np.zeros(3))


def test_crpss_contra_la_climatologia():
    rng = np.random.default_rng(5)
    verdad = rng.standard_normal(2000)
    afinado = verdad[None, :] + rng.standard_normal((50, 2000)) * 0.3
    climatologia = rng.standard_normal((50, 2000))
    assert crpss(afinado, verdad, climatologia) > 0.5
    # Un pronostico igual a la climatologia no aporta nada: skill ~0.
    assert abs(crpss(climatologia, verdad, rng.standard_normal((50, 2000)))) < 0.1


def test_brier_valores_conocidos():
    p = np.array([0.1, 0.9, 0.5])
    o = np.array([0.0, 1.0, 1.0])
    esperado = (0.01 + 0.01 + 0.25) / 3.0
    assert brier(p, o) == pytest.approx(esperado)
    assert brier(np.array([1.0, 0.0]), np.array([1.0, 0.0])) == 0.0
    assert brier(np.array([0.5, 0.5]), np.array([1.0, 0.0])) == 0.25


def test_brier_valida_entradas():
    with pytest.raises(ValueError, match="misma forma"):
        brier(np.zeros(3), np.zeros(4))
    with pytest.raises(ValueError, match="probabilidad"):
        brier(np.array([1.5]), np.array([1.0]))
    with pytest.raises(ValueError, match="binario"):
        brier(np.array([0.5]), np.array([0.3]))


def test_un_pronostico_calibrado_cae_en_la_diagonal():
    rng = np.random.default_rng(7)
    p = rng.random(50_000)
    o = (rng.random(50_000) < p).astype(float)
    rel = confiabilidad(p, o, 10)
    for pk, ok, n in zip(rel["probabilidad_media"], rel["frecuencia_observada"],
                         rel["casos"]):
        if n > 100:
            assert abs(pk - ok) < 0.03
    assert brier_skill(p, o) > 0.25


def test_la_sobreconfianza_se_detecta():
    """Un pronostico que exagera (estira las probabilidades a los extremos)
    debe perder skill y salirse de la diagonal."""
    rng = np.random.default_rng(8)
    p = rng.random(50_000)
    o = (rng.random(50_000) < p).astype(float)
    exagerado = np.clip((p - 0.5) * 3.0 + 0.5, 0.0, 1.0)
    assert brier_skill(exagerado, o) < brier_skill(p, o)
    rel = confiabilidad(exagerado, o, 10)
    desvios = [abs(a - b) for a, b, n in zip(rel["probabilidad_media"],
                                             rel["frecuencia_observada"],
                                             rel["casos"]) if n > 100]
    assert max(desvios) > 0.1


def test_descomposicion_de_murphy_cierra_con_el_residuo():
    rng = np.random.default_rng(9)
    p = rng.random(20_000)
    o = (rng.random(20_000) < p).astype(float)
    d = descomposicion_brier(p, o, 20)
    assert d["brier"] == pytest.approx(d["suma_verificacion"] + d["residuo_intracaja"],
                                       abs=1e-9)
    assert abs(d["residuo_intracaja"]) < 0.01
    assert d["incertidumbre"] == pytest.approx(d["tasa_base"] * (1 - d["tasa_base"]),
                                               abs=1e-6)


def test_mas_cajas_dejan_menos_residuo():
    rng = np.random.default_rng(10)
    p = rng.random(40_000)
    o = (rng.random(40_000) < p).astype(float)
    pocas = abs(descomposicion_brier(p, o, 4)["residuo_intracaja"])
    muchas = abs(descomposicion_brier(p, o, 40)["residuo_intracaja"])
    assert muchas < pocas


def test_dispersion_vs_error_diagnostica_bien():
    rng = np.random.default_rng(11)
    mu = rng.standard_normal(4000)
    y = mu + rng.standard_normal(4000)
    calibrado = mu[None, :] + rng.standard_normal((60, 4000))
    d = dispersion_vs_error(calibrado, y)
    assert 0.85 < d["razon_dispersion_error"] < 1.15
    assert "consistente" in d["diagnostico"]

    estrecho = mu[None, :] + rng.standard_normal((60, 4000)) * 0.2
    assert "sobreconfiado" in dispersion_vs_error(estrecho, y)["diagnostico"]

    ancho = mu[None, :] + rng.standard_normal((60, 4000)) * 4.0
    assert "timido" in dispersion_vs_error(ancho, y)["diagnostico"]


def test_dispersion_necesita_dos_miembros():
    with pytest.raises(ValueError, match="2 miembros"):
        dispersion_vs_error(np.zeros((1, 5)), np.zeros(5))


def test_tabla_de_contingencia_cuenta_bien():
    p = np.array([0.9, 0.9, 0.1, 0.1])
    o = np.array([1.0, 0.0, 1.0, 0.0])
    t = tabla_contingencia(p, o, corte=0.5)
    assert t["aciertos"] == 1
    assert t["falsas_alarmas"] == 1
    assert t["fallos"] == 1
    assert t["negativos_correctos"] == 1
    assert t["prob_deteccion"] == 0.5
    # Las metricas se redondean a 4 decimales porque viajan en JSON.
    assert t["amenaza_critica"] == pytest.approx(1 / 3, abs=1e-4)


def test_subir_el_corte_baja_la_deteccion():
    rng = np.random.default_rng(12)
    p = rng.random(20_000)
    o = (rng.random(20_000) < p).astype(float)
    bajo = tabla_contingencia(p, o, 0.2)
    alto = tabla_contingencia(p, o, 0.8)
    assert bajo["prob_deteccion"] > alto["prob_deteccion"]
    assert bajo["falsas_alarmas"] > alto["falsas_alarmas"]


def test_el_modelo_le_gana_a_la_climatologia_en_su_propio_mundo(simulador, clima):
    """Prueba de extremo a extremo con verdad sintetica: se toma un miembro
    como la realidad y se verifica que el resto del ensamble la pronostica
    mejor que la climatologia. Es una prueba de consistencia interna, no de
    habilidad real: con observaciones de verdad este numero va a ser mucho
    mas bajo, y ese es el punto de tener las metricas desde el principio."""
    import datetime as dt

    r = simulador.simular(dt.date(2026, 9, 1), n_dias=7, n_miembros=100, semilla=31)
    tierra = clima.es_tierra
    verdad = r.lluvia_mm[0][:, tierra].ravel()
    ensamble = r.lluvia_mm[1:][:, :, tierra].reshape(99, -1)

    # Climatologia: muestras de otra epoca del ano (marzo, mes seco).
    seco = simulador.simular(dt.date(2026, 3, 1), n_dias=7, n_miembros=99, semilla=32)
    referencia = seco.lluvia_mm[:, :, tierra].reshape(99, -1)

    assert crpss(ensamble, verdad, referencia) > 0.2


def test_la_probabilidad_es_nan_donde_la_variable_no_existe(corrida, clima):
    """El oceano no tiene escurrimiento: la probabilidad ahi tiene que ser
    NaN, no 0. Un 0 se pinta igual que "sin riesgo" y es enganoso."""
    p = probabilidad_umbral(corrida, "escurrimiento", 0, umbral=10.0,
                            ventana_dias=3)
    assert np.all(np.isnan(p["valores"][~clima.es_tierra]))
    assert np.all(np.isfinite(p["valores"][clima.es_tierra]))

    # La lluvia si existe sobre el mar: ahi no debe haber NaN.
    q = probabilidad_umbral(corrida, "lluvia", 0, umbral=10.0, ventana_dias=3)
    assert np.all(np.isfinite(q["valores"]))


def test_el_riesgo_no_marca_el_mar(corrida, clima):
    r = riesgo(corrida, dia=0, ventana_dias=3, umbral_mm=40.0)
    assert np.all(np.isnan(r["valores"][~clima.es_tierra]))
