"""Pruebas del simulador estocastico y de la climatologia que lo alimenta.

La pregunta que contestan: el modelo produce clima con las propiedades
estadisticas que dice producir, o solo numeros que se ven bien.
"""

import datetime as dt
import math

import numpy as np
import pytest

from ojo_tlaloc.climatologia import (
    DIAS_POR_MES,
    FRAC_DIAS_LLUVIA,
    LLUVIA_MENSUAL_MM,
    Climatologia,
    elevacion_sintetica,
    lon_costa,
)
from ojo_tlaloc.config import RADIO_TIERRA_M
from ojo_tlaloc.modelo import (
    CONSTANTE_SOLAR,
    MJ_A_MM,
    ParametrosModelo,
    SimuladorEstocastico,
    et0_hargreaves,
    radiacion_extraterrestre_mm,
)

from .conftest import FECHA_PRUEBA, SEMILLA


# --- climatologia ----------------------------------------------------------


def test_la_cadena_de_markov_reproduce_la_probabilidad_marginal(clima):
    """Es la identidad que justifica la calibracion: con
    p01 = pi(1-rho) y p11 = pi + (1-pi)rho, la estacionaria es exactamente pi.
    Si alguien cambia la parametrizacion, esta prueba lo caza."""
    for mes in range(1, 13):
        estacionaria = clima.prob_estacionaria(mes)
        assert np.abs(estacionaria - clima.prob_lluvia[:, mes - 1]).max() < 1e-12


def test_el_acumulado_al_nivel_del_mar_cuadra_con_las_normales(malla, clima):
    """En una celda a elevacion cero el modelo debe devolver la normal que se
    le dio, sin realce orografico."""
    costa = int(np.argmin(np.where(clima.es_tierra, clima.elevacion_m, 1e9)))
    assert clima.elevacion_m[costa] < 5.0
    for mes in range(1, 13):
        esperado = LLUVIA_MENSUAL_MM[mes - 1]
        obtenido = float(clima.lluvia_mensual_esperada(mes)[costa])
        assert obtenido == pytest.approx(esperado, rel=0.03)


def test_persistencia_implica_p11_mayor_que_p01(clima):
    """Si llovio ayer, hoy es mas probable que llueva. Sin esto no hay rachas."""
    assert np.all(clima.p11 > clima.p01)


def test_realce_orografico_sube_la_lluvia_con_la_elevacion(clima):
    tierra = clima.es_tierra
    anual = sum(clima.lluvia_mensual_esperada(m) for m in range(1, 13))
    alto = clima.elevacion_m > 200.0
    bajo = tierra & (clima.elevacion_m < 20.0)
    if alto.sum() and bajo.sum():
        assert anual[alto].mean() > anual[bajo].mean()


def test_gradiente_termico_por_elevacion(clima):
    """-6.5 C/km: la celda mas alta debe estar mas fria que la costa."""
    tierra = clima.es_tierra
    i_alto = int(np.argmax(np.where(tierra, clima.elevacion_m, -1)))
    i_bajo = int(np.argmin(np.where(tierra, clima.elevacion_m, 1e9)))
    delta_km = (clima.elevacion_m[i_alto] - clima.elevacion_m[i_bajo]) / 1000.0
    caida = clima.tmax_media[i_bajo, 7] - clima.tmax_media[i_alto, 7]
    assert caida == pytest.approx(6.5 * delta_km, rel=0.05)


def test_mar_y_tierra_se_separan(clima, malla):
    assert clima.es_tierra.sum() > 0 and (~clima.es_tierra).sum() > 0
    # El mar no tiene capacidad de suelo.
    assert np.all(np.isnan(clima.capacidad_suelo_mm[~clima.es_tierra]))
    assert np.all(np.isfinite(clima.capacidad_suelo_mm[clima.es_tierra]))
    # El mar queda al este de la costa aproximada.
    assert np.all(malla.lon[~clima.es_tierra] >= lon_costa(malla.lat[~clima.es_tierra]))


def test_elevacion_sintetica_es_conservadora():
    """El dominio es planicie costera: el placeholder no debe inventar sierra.
    Si alguien cambia el perfil y mete montanas de 1000 m aqui, se cae."""
    assert float(elevacion_sintetica(19.19, -96.09)) == pytest.approx(0.0, abs=1.0)
    assert float(elevacion_sintetica(19.19, -96.60)) < 400.0
    assert float(elevacion_sintetica(19.19, -95.80)) == 0.0  # mar


def test_climatologia_rechaza_series_malas(malla):
    with pytest.raises(ValueError, match="12 valores"):
        Climatologia.desde_normales(malla, frac_dias_lluvia=[0.5] * 11)
    with pytest.raises(ValueError, match="frac_dias_lluvia"):
        Climatologia.desde_normales(malla, frac_dias_lluvia=[0.0] * 12)
    with pytest.raises(ValueError, match="elevacion_m"):
        Climatologia.desde_normales(malla, elevacion_m=np.zeros(5))


def test_se_puede_calibrar_con_otras_normales(malla):
    """La via de entrada de datos reales: otras 12 series y nada mas."""
    seco = Climatologia.desde_normales(
        malla,
        frac_dias_lluvia=[0.05] * 12,
        lluvia_mensual_mm=[10.0] * 12,
    )
    costa = int(np.argmin(np.where(seco.es_tierra, seco.elevacion_m, 1e9)))
    assert float(seco.lluvia_mensual_esperada(7)[costa]) == pytest.approx(10.0, rel=0.03)


# --- radiacion y evapotranspiracion ----------------------------------------


def test_radiacion_extraterrestre_identidad_del_equinoccio():
    """En el equinoccio la declinacion es ~0 y el angulo horario es pi/2, con
    lo que Ra = (1440/pi) * Gsc * dr * cos(lat). Es un valor analitico
    independiente de la implementacion."""
    j = 81  # 22 de marzo
    dr = 1.0 + 0.033 * math.cos(2.0 * math.pi * j / 365.0)
    for lat in (0.0, 19.17, 40.0):
        esperado = ((24 * 60 / math.pi) * CONSTANTE_SOLAR * dr
                    * math.cos(math.radians(lat)) * MJ_A_MM)
        obtenido = float(radiacion_extraterrestre_mm(lat, j))
        assert obtenido == pytest.approx(esperado, rel=0.01)


def test_radiacion_es_mayor_en_verano_en_el_hemisferio_norte():
    verano = float(radiacion_extraterrestre_mm(19.17, 172))   # 21 jun
    invierno = float(radiacion_extraterrestre_mm(19.17, 355))  # 21 dic
    assert verano > invierno
    # Orden de magnitud fisico: 25-45 MJ/m2/dia = 10-18 mm/dia
    assert 10.0 < verano < 18.0


def test_et0_hargreaves_crece_con_temperatura_y_rango():
    ra = float(radiacion_extraterrestre_mm(19.17, 200))
    base = float(et0_hargreaves(ra, 30.0, 22.0))
    assert float(et0_hargreaves(ra, 34.0, 26.0)) > base   # mas calor
    assert float(et0_hargreaves(ra, 32.0, 20.0)) > base   # mas rango
    assert float(et0_hargreaves(ra, 30.0, 30.0)) == 0.0   # sin rango, sin ET
    # Valor fisicamente razonable para el tropico humedo.
    assert 2.0 < base < 8.0


# --- simulador -------------------------------------------------------------


def test_misma_semilla_mismo_resultado(simulador):
    a = simulador.simular(FECHA_PRUEBA, n_dias=5, n_miembros=20, semilla=7)
    b = simulador.simular(FECHA_PRUEBA, n_dias=5, n_miembros=20, semilla=7)
    assert np.array_equal(a.lluvia_mm, b.lluvia_mm)
    assert np.array_equal(a.humedad_suelo, b.humedad_suelo, equal_nan=True)


def test_distinta_semilla_distinto_resultado(simulador):
    a = simulador.simular(FECHA_PRUEBA, n_dias=5, n_miembros=20, semilla=7)
    b = simulador.simular(FECHA_PRUEBA, n_dias=5, n_miembros=20, semilla=8)
    assert not np.array_equal(a.lluvia_mm, b.lluvia_mm)


def test_formas_y_fechas(corrida, malla):
    assert corrida.lluvia_mm.shape == (120, 10, malla.n_celdas)
    assert len(corrida.fechas) == 10
    assert corrida.fechas[0] == FECHA_PRUEBA.isoformat()
    assert corrida.fechas[-1] == (FECHA_PRUEBA + dt.timedelta(days=9)).isoformat()
    assert corrida.ids_celdas == list(malla.ids)


def test_rangos_fisicos(corrida, clima):
    tierra = clima.es_tierra
    assert corrida.lluvia_mm.min() >= 0.0
    assert corrida.lluvia_mm.max() < 1000.0, "lluvia diaria imposible"
    assert np.nanmin(corrida.escurrimiento_mm[:, :, tierra]) >= 0.0
    assert np.all(corrida.tmax_c > corrida.tmin_c), "tmax debe superar a tmin"
    assert corrida.tmax_c[:, :, tierra].max() < 50.0
    assert corrida.tmin_c[:, :, tierra].min() > 0.0
    assert corrida.et0_mm.min() >= 0.0
    s = corrida.humedad_suelo[:, :, tierra]
    assert np.nanmin(s) >= 0.0 and np.nanmax(s) <= 1.0


def test_la_convencion_de_dominio_se_respeta(corrida, clima):
    """lluvia, tmax, tmin y et0 existen en todo el dominio; suelo y
    escurrimiento solo en tierra. El NaN en el mar es intencional: significa
    "no aplica", y el front no debe pintar esas celdas. Si alguien convierte
    esos NaN en ceros, el mapa va a mostrar el oceano como zona sin riesgo."""
    mar = ~clima.es_tierra
    tierra = clima.es_tierra
    for nombre in ("lluvia", "tmax", "tmin", "et0"):
        assert not np.isnan(corrida.variable(nombre)).any(), nombre
    for nombre in ("humedad_suelo", "escurrimiento"):
        v = corrida.variable(nombre)
        assert np.all(np.isnan(v[:, :, mar])), nombre
        assert not np.isnan(v[:, :, tierra]).any(), nombre


def test_el_escurrimiento_nunca_supera_la_lluvia_mas_el_suelo(corrida, clima):
    """El balance de agua no puede inventar agua: lo que escurre viene de la
    lluvia del dia mas, como mucho, el agua que ya estaba en el suelo."""
    tierra = clima.es_tierra
    cap = clima.capacidad_suelo_mm[tierra]
    escurre = corrida.escurrimiento_mm[:, :, tierra]
    llueve = corrida.lluvia_mm[:, :, tierra]
    assert np.all(escurre <= llueve + cap[None, None, :] + 1e-3)


def test_la_frecuencia_de_lluvia_se_parece_a_la_climatologia(simulador, clima):
    """Un mes de septiembre con muchos miembros: la fraccion de dias con
    lluvia tiene que quedar cerca de la climatologia. Se compara contra
    lluvia > 0 porque la escala Weibull esta calibrada por acumulado y eso
    deja ~10% de dias humedos por debajo de 1 mm (limitacion documentada)."""
    r = simulador.simular(dt.date(2026, 9, 1), n_dias=30, n_miembros=150, semilla=3)
    tierra = clima.es_tierra
    frac = (r.lluvia_mm[:, :, tierra] > 0).mean()
    objetivo = clima.prob_lluvia[tierra, 8].mean()
    assert frac == pytest.approx(objetivo, abs=0.06)


def test_el_acumulado_simulado_cuadra_con_la_climatologia(simulador, clima):
    r = simulador.simular(dt.date(2026, 9, 1), n_dias=30, n_miembros=200, semilla=4)
    tierra = clima.es_tierra
    simulado = r.lluvia_mm[:, :, tierra].sum(axis=1).mean()
    esperado = clima.lluvia_mensual_esperada(9)[tierra].mean()
    assert simulado == pytest.approx(esperado, rel=0.12)


def test_coherencia_espacial_vecinos_contra_lejanos(simulador, malla, clima):
    """El aporte del campo latente: celdas vecinas correlacionadas, celdas
    lejanas practicamente independientes. Si el campo se rompe, la lluvia se
    vuelve ruido blanco y esta prueba lo caza."""
    r = simulador.simular(dt.date(2026, 9, 1), n_dias=20, n_miembros=100, semilla=9)
    tierra = clima.es_tierra
    plano = r.lluvia_mm.reshape(-1, malla.n_celdas)
    d = malla.matriz_distancias_km()

    cercanos = []
    for i, fila in enumerate(malla.vecinos()):
        for j in fila:
            if j > i and tierra[i] and tierra[j]:
                cercanos.append(np.corrcoef(plano[:, i], plano[:, j])[0, 1])

    lejanos = []
    idx = np.where(tierra)[0]
    for i in idx[::7]:
        for j in idx[::11]:
            if d[i, j] > 60.0:
                lejanos.append(np.corrcoef(plano[:, i], plano[:, j])[0, 1])

    assert float(np.mean(cercanos)) > 0.5
    assert float(np.mean(lejanos)) < 0.2
    assert float(np.mean(cercanos)) > float(np.mean(lejanos)) + 0.3


def test_hay_rachas_de_lluvia_no_dias_independientes(simulador, clima):
    """La persistencia tiene que notarse: P(llueve hoy | llovio ayer) debe
    superar la probabilidad marginal."""
    r = simulador.simular(dt.date(2026, 9, 1), n_dias=30, n_miembros=150, semilla=12)
    tierra = clima.es_tierra
    mojado = r.lluvia_mm[:, :, tierra] > 0
    ayer = mojado[:, :-1, :]
    hoy = mojado[:, 1:, :]
    condicional = hoy[ayer].mean()
    marginal = mojado.mean()
    assert condicional > marginal + 0.05


def test_la_dispersion_del_ensamble_crece_con_el_horizonte(simulador, clima):
    """Un pronostico honesto es mas incierto a 10 dias que a 1. Se mide sobre
    la lluvia acumulada, que es la cantidad con la que se decide."""
    r = simulador.simular(FECHA_PRUEBA, n_dias=12, n_miembros=200, semilla=15)
    tierra = clima.es_tierra
    acum = np.cumsum(r.lluvia_mm[:, :, tierra], axis=1)
    disp = acum.std(axis=0).mean(axis=1)
    assert disp[-1] > disp[0]
    assert np.all(np.diff(disp) > -1e-6), "la incertidumbre no debe encogerse"


def test_la_humedad_inicial_mueve_el_primer_dia(simulador, clima):
    """Lo que hace util la asimilacion: si el suelo arranca distinto, el
    escurrimiento del primer dia cambia. Si esto no pasara, asimilar NISAR
    seria decorativo."""
    tierra = clima.es_tierra
    seco = simulador.simular(FECHA_PRUEBA, n_dias=1, n_miembros=200, semilla=21,
                             humedad_inicial=0.05, dias_calentamiento=0)
    mojado = simulador.simular(FECHA_PRUEBA, n_dias=1, n_miembros=200, semilla=21,
                               humedad_inicial=0.95, dias_calentamiento=0)
    assert (mojado.escurrimiento_mm[:, 0, tierra].mean()
            > seco.escurrimiento_mm[:, 0, tierra].mean() * 1.5)
    assert (float(np.nanmean(mojado.humedad_suelo[:, 0, tierra]))
            > float(np.nanmean(seco.humedad_suelo[:, 0, tierra])))


def test_el_calentamiento_olvida_la_humedad_inicial(simulador, clima):
    """Al reves del anterior: con suficientes dias de calentamiento el estado
    inicial deja de importar. Eso acota cuanto vale la asimilacion (dias, no
    meses) y es honesto decirlo."""
    tierra = clima.es_tierra
    a = simulador.simular(FECHA_PRUEBA, n_dias=1, n_miembros=200, semilla=21,
                          humedad_inicial=0.05, dias_calentamiento=90)
    b = simulador.simular(FECHA_PRUEBA, n_dias=1, n_miembros=200, semilla=21,
                          humedad_inicial=0.95, dias_calentamiento=90)
    ma = float(np.nanmean(a.humedad_suelo[:, 0, tierra]))
    mb = float(np.nanmean(b.humedad_suelo[:, 0, tierra]))
    assert abs(ma - mb) < 0.05


def test_validacion_de_argumentos(simulador):
    with pytest.raises(ValueError, match="n_dias"):
        simulador.simular(FECHA_PRUEBA, n_dias=0)
    with pytest.raises(ValueError, match="n_miembros"):
        simulador.simular(FECHA_PRUEBA, n_dias=1, n_miembros=0)
    with pytest.raises(ValueError, match="humedad inicial"):
        simulador.simular(FECHA_PRUEBA, n_dias=1, humedad_inicial=1.5)
    with pytest.raises(ValueError, match="humedad_inicial"):
        simulador.simular(FECHA_PRUEBA, n_dias=1, humedad_inicial=np.zeros(3))


def test_el_simulador_rechaza_climatologia_de_otra_malla(malla):
    otra = Climatologia.sintetica(malla.nivel_siguiente())
    with pytest.raises(ValueError, match="climatologia"):
        SimuladorEstocastico(malla, otra)


def test_variable_por_nombre(corrida):
    assert corrida.variable("lluvia") is corrida.lluvia_mm
    assert corrida.variable("humedad_suelo") is corrida.humedad_suelo
    with pytest.raises(KeyError, match="desconocida"):
        corrida.variable("no_existe")


def test_memoria_estimada_es_realista(simulador, corrida):
    estimado = simulador.memoria_estimada_mb(10, 120)
    real = sum(
        a.nbytes for a in (corrida.lluvia_mm, corrida.tmax_c, corrida.tmin_c,
                           corrida.humedad_suelo, corrida.escurrimiento_mm,
                           corrida.et0_mm)
    ) / (1024.0 * 1024.0)
    assert estimado == pytest.approx(real, rel=0.01)


def test_parametros_se_respetan(malla, clima):
    """Si se apaga la persistencia del campo, las rachas deben debilitarse."""
    sin_memoria = SimuladorEstocastico(
        malla, clima, ParametrosModelo(persistencia_campo_lluvia=0.0)
    )
    assert sin_memoria.campo_lluvia.persistencia == 0.0
    r = sin_memoria.simular(dt.date(2026, 9, 1), n_dias=20, n_miembros=100, semilla=2)
    assert r.parametros.persistencia_campo_lluvia == 0.0
    assert r.lluvia_mm.shape[1] == 20
