"""Pruebas de la plataforma de fusion: geometria, expediente y analisis.

Las fuentes que bajan de internet se prueban aparte, en test_fuentes.py, para
que esta suite corra sin red.
"""

import datetime as dt
import math

import numpy as np
import pytest

from ojo_tlaloc.analisis import (
    aptitud_constructiva,
    exposicion_por_riesgo,
    pendiente_desde_elevacion,
    resumen_exposicion,
    ventanas_de_obra,
)
from ojo_tlaloc.analisis.ventanas import ACTIVIDADES, calendario_celda
from ojo_tlaloc.expediente import Expediente, construir_expediente
from ojo_tlaloc.fuentes.base import (
    NIVEL_DERIVADO,
    NIVEL_OBSERVADO,
    NIVEL_SINTETICO,
    CapaFuente,
    Procedencia,
)
from ojo_tlaloc.fuentes.geometria import (
    area_poligono_m2,
    centroide_poligono,
    longitud_segmentos,
    puntos_en_poligono,
    rejilla_de_muestreo,
)
from ojo_tlaloc.modelo import ParametrosModelo, SimuladorEstocastico

from .conftest import FECHA_PRUEBA, SEMILLA


# --- geometria -------------------------------------------------------------


def test_area_de_un_cuadrado():
    cuadrado = [(0, 0), (10, 0), (10, 10), (0, 10)]
    assert area_poligono_m2(cuadrado) == pytest.approx(100.0)
    # Con el anillo cerrado da lo mismo.
    assert area_poligono_m2(cuadrado + [(0, 0)]) == pytest.approx(100.0)


def test_area_de_un_triangulo():
    assert area_poligono_m2([(0, 0), (4, 0), (0, 3)]) == pytest.approx(6.0)


def test_el_area_no_depende_de_la_orientacion():
    horario = [(0, 0), (0, 10), (10, 10), (10, 0)]
    antihorario = [(0, 0), (10, 0), (10, 10), (0, 10)]
    assert area_poligono_m2(horario) == pytest.approx(area_poligono_m2(antihorario))


def test_area_de_poligono_degenerado_es_cero():
    assert area_poligono_m2([(0, 0), (1, 1)]) == 0.0
    assert area_poligono_m2([(0, 0), (1, 1), (2, 2)]) == pytest.approx(0.0)


def test_centroide_de_un_cuadrado():
    c = centroide_poligono([(0, 0), (10, 0), (10, 10), (0, 10)])
    assert c[0] == pytest.approx(5.0) and c[1] == pytest.approx(5.0)


def test_centroide_de_area_no_es_promedio_de_vertices():
    """Un poligono con vertices concentrados en un lado: el centroide del area
    y el promedio de vertices no coinciden, y el que sirve es el del area."""
    poly = [(0, 0), (10, 0), (10, 1), (5, 1), (4, 1), (3, 1), (2, 1), (0, 1)]
    c = centroide_poligono(poly)
    promedio = np.mean(poly, axis=0)
    assert c[0] == pytest.approx(5.0, abs=0.3)
    assert abs(c[0] - promedio[0]) > 0.2


def test_punto_en_poligono():
    cuadrado = np.array([(0, 0), (10, 0), (10, 10), (0, 10)], dtype=float)
    puntos = np.array([(5, 5), (1, 1), (9, 9), (-1, 5), (5, 11), (15, 5)],
                      dtype=float)
    dentro = puntos_en_poligono(puntos, cuadrado)
    assert list(dentro) == [True, True, True, False, False, False]


def test_punto_en_poligono_concavo():
    """Una L: el hueco de la concavidad tiene que quedar fuera."""
    ele = np.array([(0, 0), (10, 0), (10, 4), (4, 4), (4, 10), (0, 10)],
                   dtype=float)
    assert bool(puntos_en_poligono(np.array([[2.0, 2.0]]), ele)[0]) is True
    assert bool(puntos_en_poligono(np.array([[8.0, 8.0]]), ele)[0]) is False


def test_la_fraccion_por_muestreo_se_acerca_al_area_real():
    """El metodo que usa el adaptador de OSM para poligonos grandes."""
    circulo_r = 300.0
    ang = np.linspace(0, 2 * np.pi, 180, endpoint=False)
    circulo = np.stack([circulo_r * np.cos(ang), circulo_r * np.sin(ang)], axis=1)
    paso = 20.0
    rx = np.arange(-400, 400 + paso, paso)
    gx, gy = np.meshgrid(rx, rx)
    puntos = np.stack([gx.ravel(), gy.ravel()], axis=1)
    dentro = puntos_en_poligono(puntos, circulo)
    area_estimada = dentro.sum() * paso * paso
    assert area_estimada == pytest.approx(math.pi * circulo_r ** 2, rel=0.02)


def test_longitud_de_segmentos():
    largos, medios = longitud_segmentos([(0, 0), (3, 4), (3, 14)])
    assert list(np.round(largos, 6)) == [5.0, 10.0]
    assert list(medios[0]) == [1.5, 2.0]


def test_longitud_de_polilinea_degenerada():
    largos, medios = longitud_segmentos([(0, 0)])
    assert largos.size == 0 and medios.size == 0


def test_rejilla_de_muestreo_cubre_la_malla(malla):
    puntos, idx, area = rejilla_de_muestreo(malla, paso_m=400.0)
    assert area == 400.0 ** 2
    dentro = idx >= 0
    assert dentro.sum() > 0
    # Toda celda debe recibir al menos un punto con un paso de 400 m frente a
    # hexagonos de 5.8 km.
    cuenta = np.bincount(idx[dentro], minlength=malla.n_celdas)
    assert cuenta.min() > 0
    # El area sumada de los puntos se parece al area de la malla.
    area_puntos = dentro.sum() * area / 1e6
    assert area_puntos == pytest.approx(
        malla.n_celdas * malla.area_celda_km2, rel=0.15)


# --- expediente ------------------------------------------------------------


@pytest.fixture
def expediente_simple(malla):
    exp = Expediente(malla)
    exp.agregar(CapaFuente(
        "elevacion_m", np.linspace(0, 300, malla.n_celdas), "m",
        Procedencia(fuente="prueba", nivel=NIVEL_SINTETICO)))
    exp.agregar(CapaFuente(
        "fraccion_impermeable", np.linspace(0, 0.8, malla.n_celdas), "0-1",
        Procedencia(fuente="OpenStreetMap", nivel=NIVEL_DERIVADO,
                    atribucion="(c) OpenStreetMap contributors (ODbL)")))
    exp.agregar(CapaFuente(
        "infraestructura_critica", np.arange(malla.n_celdas, dtype=float),
        "conteo", Procedencia(fuente="OpenStreetMap", nivel=NIVEL_OBSERVADO,
                              atribucion="(c) OpenStreetMap contributors (ODbL)")))
    return exp


def test_el_expediente_rechaza_capas_de_otro_tamano(malla):
    exp = Expediente(malla)
    with pytest.raises(ValueError, match="celdas"):
        exp.agregar(CapaFuente("mala", np.zeros(5), "x",
                               Procedencia(fuente="prueba")))


def test_valores_con_defecto(expediente_simple, malla):
    assert expediente_simple.valores("elevacion_m").size == malla.n_celdas
    # Una capa que no existe, con defecto, devuelve el relleno.
    v = expediente_simple.valores("no_existe", defecto=0.5)
    assert v.shape == (malla.n_celdas,) and np.all(v == 0.5)
    # Sin defecto, lanza con un mensaje que dice que si hay.
    with pytest.raises(KeyError, match="no_existe"):
        expediente_simple.valores("no_existe")


def test_la_procedencia_llega_hasta_la_celda(expediente_simple, malla):
    celda = expediente_simple.celda(malla.ids[10])
    assert celda["id_celda"] == malla.ids[10]
    assert "estatico" in celda["datos"]
    entrada = celda["datos"]["estatico"]["fraccion_impermeable"]
    assert entrada["fuente"] == "OpenStreetMap"
    assert entrada["nivel"] == NIVEL_DERIVADO
    assert entrada["unidad"] == "0-1"


def test_la_celda_se_puede_pedir_por_id_o_por_indice(expediente_simple, malla):
    por_id = expediente_simple.celda(malla.ids[7])
    por_indice = expediente_simple.celda(7)
    assert por_id == por_indice


def test_celda_invalida(expediente_simple):
    with pytest.raises(IndexError):
        expediente_simple.celda(10 ** 6)
    with pytest.raises(KeyError):
        expediente_simple.celda("OT0.999.999")


def test_las_atribuciones_no_se_repiten(expediente_simple):
    atrib = expediente_simple.atribuciones()
    assert len(atrib) == len(set(atrib))
    assert any("OpenStreetMap" in a for a in atrib)


def test_la_atribucion_de_osm_esta_presente(expediente_simple):
    """La ODbL exige atribucion visible. Si esto falla, se incumple la
    licencia, no es un detalle cosmetico."""
    assert any("ODbL" in a for a in expediente_simple.atribuciones())


def test_las_capas_sinteticas_se_pueden_distinguir(expediente_simple):
    sinteticas = expediente_simple.capas_sinteticas()
    assert "elevacion_m" in sinteticas
    assert "fraccion_impermeable" not in sinteticas


def test_conteo_por_nivel(expediente_simple):
    conteo = expediente_simple.conteo_por_nivel()
    assert conteo[NIVEL_SINTETICO] == 1
    assert conteo[NIVEL_DERIVADO] == 1
    assert conteo[NIVEL_OBSERVADO] == 1


def test_geojson_del_expediente_lleva_procedencia(expediente_simple):
    gj = expediente_simple.a_geojson(["fraccion_impermeable"])
    assert gj["type"] == "FeatureCollection"
    assert "fraccion_impermeable" in gj["procedencia"]
    assert gj["atribuciones"]
    with pytest.raises(KeyError):
        expediente_simple.a_geojson(["no_existe"])


def test_el_expediente_tolera_fuentes_caidas(malla, clima):
    """Si no hay internet el sistema tiene que seguir y DECIR que le falto,
    no caerse. Una plataforma que exige todas sus fuentes no sirve en campo."""
    exp = construir_expediente(malla, clima=clima, usar_osm=False,
                               usar_power=False)
    assert exp.capas            # al menos las de la climatologia
    assert "elevacion_m" in exp.capas
    assert exp.series_climatologicas is None
    assert exp.perfil_atmosferico is None


def test_el_expediente_registra_el_sondeo(malla, clima):
    csv = ("presion_hpa,temp_c,humedad_rel\n1008,29.5,78\n950,25.1,85\n"
           "850,18.2,84\n700,8.1,60\n500,-7.5,35\n300,-34.2,25\n")
    exp = construir_expediente(malla, clima=clima, usar_osm=False,
                               usar_power=False, sondeo_texto=csv)
    assert exp.perfil_atmosferico is not None
    assert exp.perfil_atmosferico.es_propio is True
    assert any("Ojo de Tlaloc" in a for a in exp.atribuciones())


def test_el_sondeo_malo_no_tumba_el_expediente(malla, clima):
    exp = construir_expediente(malla, clima=clima, usar_osm=False,
                               usar_power=False, sondeo_texto="basura\nno\n")
    assert exp.perfil_atmosferico is None
    assert any(a["variable"] == "sondeo atmosferico" for a in exp.advertencias)


def test_faltantes_sirve_de_hoja_de_ruta(malla, clima):
    exp = construir_expediente(malla, clima=clima, usar_osm=False,
                               usar_power=False)
    faltan = exp.faltantes()
    assert "humedad_suelo_obs" in faltan["observado"]
    assert "elevacion_m" not in faltan["estatico"]


# --- analisis: pendiente ---------------------------------------------------


def test_pendiente_de_terreno_plano_es_cero(malla):
    r = pendiente_desde_elevacion(malla, np.zeros(malla.n_celdas))
    assert np.all(r["pendiente_max_grados"] == 0.0)


def test_pendiente_de_un_escalon_conocido(malla):
    """Desnivel de 1 ancho de celda entre vecinos debe dar 45 grados."""
    elev = np.zeros(malla.n_celdas)
    vecinos = malla.vecinos()
    i = next(k for k, f in enumerate(vecinos) if len(f) == 6)
    elev[vecinos[i][0]] = malla.ancho_celda_km * 1000.0
    r = pendiente_desde_elevacion(malla, elev)
    assert r["pendiente_max_grados"][i] == pytest.approx(45.0, abs=0.01)


def test_pendiente_valida_el_tamano(malla):
    with pytest.raises(ValueError, match="n_celdas"):
        pendiente_desde_elevacion(malla, np.zeros(3))


def test_pendiente_trae_su_advertencia(malla):
    r = pendiente_desde_elevacion(malla, np.zeros(malla.n_celdas))
    assert "esconder" in r["advertencia"]


# --- analisis: aptitud -----------------------------------------------------


def test_aptitud_en_rango_y_con_pesos_declarados(malla, expediente_simple):
    r = aptitud_constructiva(malla, expediente_simple)
    v = r["aptitud"]
    finitos = np.isfinite(v)
    assert np.all((v[finitos] >= 0) & (v[finitos] <= 1))
    # Los pesos se redondean a 4 decimales para que viajen en JSON, asi que
    # suman 1 con esa precision y no exactamente.
    assert abs(sum(r["pesos_usados"].values()) - 1.0) < 1e-3
    assert r["detalle_criterios"]


def test_la_aptitud_renormaliza_si_falta_la_inundabilidad(malla, expediente_simple):
    """Y lo DICE, para que nadie compare dos indices con criterios distintos
    sin saberlo."""
    sin = aptitud_constructiva(malla, expediente_simple)
    assert "no_inundable" not in sin["pesos_usados"]
    assert sin["pesos_renormalizados"] is True
    assert "OMITIDO" in sin["detalle_criterios"]["no_inundable"]

    con = aptitud_constructiva(malla, expediente_simple,
                               probabilidad_inundacion=np.zeros(malla.n_celdas))
    assert "no_inundable" in con["pesos_usados"]
    assert con["pesos_renormalizados"] is False


def test_mas_riesgo_de_inundacion_baja_la_aptitud(malla, expediente_simple):
    seca = aptitud_constructiva(
        malla, expediente_simple,
        probabilidad_inundacion=np.zeros(malla.n_celdas))["aptitud"]
    inundable = aptitud_constructiva(
        malla, expediente_simple,
        probabilidad_inundacion=np.ones(malla.n_celdas))["aptitud"]
    assert np.nanmean(inundable) < np.nanmean(seca)


def test_el_criterio_de_disponibilidad_castiga_lo_ya_construido(malla,
                                                               expediente_simple):
    """Sin este criterio el indice premiaba las celdas mas densas del puerto,
    donde no hay terreno que comprar."""
    r = aptitud_constructiva(malla, expediente_simple)
    disponible = r["criterios"]["disponible"]
    imperm = expediente_simple.valores("fraccion_impermeable")
    # A mayor impermeabilidad, menor disponibilidad.
    assert np.corrcoef(imperm, disponible)[0, 1] < -0.8


def test_la_aptitud_advierte_que_no_sustituye_un_topografo(malla,
                                                           expediente_simple):
    """Si alguien decide una nivelacion con esto y sale mal, el problema es
    nuestro. La advertencia es parte del producto."""
    r = aptitud_constructiva(malla, expediente_simple)
    texto = " ".join(r["advertencias"]).lower()
    assert "topografico" in texto
    assert "mecanica de suelos" in texto
    assert "tamiz" in texto


def test_la_aptitud_valida_la_probabilidad(malla, expediente_simple):
    with pytest.raises(ValueError, match="n_celdas"):
        aptitud_constructiva(malla, expediente_simple,
                             probabilidad_inundacion=np.zeros(5))


# --- analisis: exposicion --------------------------------------------------


def test_exposicion_cuenta_lo_que_cae_en_riesgo(malla, expediente_simple):
    prob = np.zeros(malla.n_celdas)
    prob[:10] = 0.9                      # solo las primeras 10 en riesgo
    r = exposicion_por_riesgo(malla, expediente_simple, prob, corte=0.5)
    assert r["celdas_en_riesgo"] == 10
    critica = expediente_simple.valores("infraestructura_critica")
    assert r["elementos"]["infraestructura_critica"]["expuesto"] == pytest.approx(
        float(critica[:10].sum()))


def test_un_corte_mas_bajo_expone_mas(malla, expediente_simple):
    prob = np.linspace(0, 1, malla.n_celdas)
    alto = exposicion_por_riesgo(malla, expediente_simple, prob, corte=0.8)
    bajo = exposicion_por_riesgo(malla, expediente_simple, prob, corte=0.2)
    assert bajo["celdas_en_riesgo"] > alto["celdas_en_riesgo"]


def test_el_corte_inalcanzable_se_declara(malla, expediente_simple):
    """Distinguir "no hay nada expuesto" de "pediste un umbral que este
    escenario nunca alcanza": lo segundo no es tranquilizador."""
    prob = np.full(malla.n_celdas, 0.1)
    r = exposicion_por_riesgo(malla, expediente_simple, prob, corte=0.9)
    assert r["corte_inalcanzable"] is True
    assert r["probabilidad_maxima_dominio"] == pytest.approx(0.1)
    texto = resumen_exposicion(r)
    assert "maxima del dominio" in texto

    r2 = exposicion_por_riesgo(malla, expediente_simple, prob, corte=0.05)
    assert r2["corte_inalcanzable"] is False


def test_el_indice_de_exposicion_es_riesgo_por_consecuencia(malla,
                                                            expediente_simple):
    prob = np.linspace(0, 1, malla.n_celdas)
    r = exposicion_por_riesgo(malla, expediente_simple, prob, corte=0.3)
    indice = r["indice_exposicion"]
    assert indice.shape == (malla.n_celdas,)
    assert np.all(indice >= 0)
    # Probabilidad cero implica exposicion cero, aunque haya mucho expuesto.
    assert indice[0] == pytest.approx(0.0)


def test_celdas_prioritarias_ordenadas(malla, expediente_simple):
    prob = np.linspace(0, 1, malla.n_celdas)
    r = exposicion_por_riesgo(malla, expediente_simple, prob, corte=0.3)
    indices = [f["indice_exposicion"] for f in r["celdas_prioritarias"]]
    assert indices == sorted(indices, reverse=True)


def test_exposicion_valida_entradas(malla, expediente_simple):
    with pytest.raises(ValueError, match="n_celdas"):
        exposicion_por_riesgo(malla, expediente_simple, np.zeros(3))
    with pytest.raises(ValueError, match="corte"):
        exposicion_por_riesgo(malla, expediente_simple,
                              np.zeros(malla.n_celdas), corte=1.5)


def test_la_exposicion_advierte_que_osm_esta_incompleto(malla, expediente_simple):
    r = exposicion_por_riesgo(malla, expediente_simple,
                              np.zeros(malla.n_celdas))
    assert any("censo" in a for a in r["advertencias"])


# --- analisis: ventanas de obra --------------------------------------------


def test_ventanas_devuelve_probabilidades_validas(corrida, clima):
    v = ventanas_de_obra(corrida, es_tierra=clima.es_tierra)
    for nombre, bloque in v["actividades"].items():
        p = bloque["probabilidad"]
        assert p.shape == (corrida.n_dias, corrida.n_celdas)
        finitos = np.isfinite(p)
        assert np.all((p[finitos] >= 0) & (p[finitos] <= 1)), nombre


def test_una_actividad_mas_estricta_tiene_menos_dias(corrida, clima):
    v = ventanas_de_obra(corrida, es_tierra=clima.es_tierra)
    general = v["actividades"]["obra_exterior_general"]
    impermeabilizacion = v["actividades"]["impermeabilizacion"]
    assert (np.nanmean(general["dias_trabajables_esperados"])
            > np.nanmean(impermeabilizacion["dias_trabajables_esperados"]))


def test_las_actividades_que_necesitan_viento_se_omiten(corrida):
    """Se declaran y se omiten en lugar de contestarlas con datos que no
    existen. El modelo no genera viento."""
    v = ventanas_de_obra(corrida)
    omitidas = {o["actividad"] for o in v["omitidas"]}
    assert "montaje_con_grua" in omitidas
    assert "montaje_con_grua" not in v["actividades"]
    assert any("globo cautivo" in o["motivo"] for o in v["omitidas"])

    con = ventanas_de_obra(corrida, incluir_sin_viento=True)
    assert "montaje_con_grua" in con["actividades"]


def test_cada_actividad_declara_su_razon():
    """Un umbral sin su motivo no se puede discutir con un jefe de obra."""
    for nombre, cfg in ACTIVIDADES.items():
        assert cfg["razon"], nombre
        assert cfg["etiqueta"], nombre
        assert cfg["lluvia_max_mm"] > 0, nombre


def test_ventanas_rechaza_actividad_desconocida(corrida):
    with pytest.raises(KeyError, match="desconocida"):
        ventanas_de_obra(corrida, actividades=["colar_oro"])


def test_calendario_de_celda_ordenado(corrida, clima):
    v = ventanas_de_obra(corrida, es_tierra=clima.es_tierra)
    i = int(np.where(clima.es_tierra)[0][0])
    cal = calendario_celda(v, i)
    dias = [f["dias_trabajables_esperados"] for f in cal["actividades"]]
    assert dias == sorted(dias, reverse=True)
    assert len(cal["fechas"]) == corrida.n_dias
    for f in cal["actividades"]:
        assert len(f["por_dia"]) == corrida.n_dias


def test_la_compactacion_necesita_suelo_ni_seco_ni_mojado(simulador, clima):
    """El suelo compacta solo cerca de su humedad optima: es la restriccion
    que distingue a esta actividad de todas las demas."""
    seco = simulador.simular(FECHA_PRUEBA, n_dias=3, n_miembros=100,
                             semilla=SEMILLA, humedad_inicial=0.05,
                             dias_calentamiento=0)
    mojado = simulador.simular(FECHA_PRUEBA, n_dias=3, n_miembros=100,
                               semilla=SEMILLA, humedad_inicial=0.95,
                               dias_calentamiento=0)
    v_seco = ventanas_de_obra(seco, ["compactacion"], clima.es_tierra)
    v_mojado = ventanas_de_obra(mojado, ["compactacion"], clima.es_tierra)
    p_seco = np.nanmean(v_seco["actividades"]["compactacion"]["probabilidad"][0])
    p_mojado = np.nanmean(v_mojado["actividades"]["compactacion"]["probabilidad"][0])
    # Con suelo saturado no se compacta.
    assert p_mojado < 0.1
    # Con suelo muy seco tampoco (esta por debajo del minimo).
    assert p_seco < 0.5


def test_las_ventanas_traen_sus_advertencias(corrida):
    v = ventanas_de_obra(corrida)
    texto = " ".join(v["advertencias"]).lower()
    assert "no una norma" in texto
    assert "proctor" in texto


# --- integracion del modelo con la fusion ---------------------------------


def test_la_impermeabilidad_sube_el_escurrimiento_en_suelo_seco(malla, clima):
    """El efecto es grande en suelo seco y chico en saturado, porque el suelo
    saturado ya escurria casi todo. Medido: +565% en seco, +10% en saturado."""
    imperm = np.full(malla.n_celdas, 0.7)
    sin = SimuladorEstocastico(malla, clima, ParametrosModelo())
    con = SimuladorEstocastico(
        malla, clima, ParametrosModelo(fraccion_impermeable=imperm))
    tierra = clima.es_tierra

    a = sin.simular(dt.date(2026, 9, 15), n_dias=3, n_miembros=150, semilla=3,
                    humedad_inicial=0.1, dias_calentamiento=0)
    b = con.simular(dt.date(2026, 9, 15), n_dias=3, n_miembros=150, semilla=3,
                    humedad_inicial=0.1, dias_calentamiento=0)
    assert np.allclose(a.lluvia_mm, b.lluvia_mm), "debe ser la misma lluvia"
    assert (np.nanmean(b.escurrimiento_mm[:, :, tierra])
            > 2.0 * np.nanmean(a.escurrimiento_mm[:, :, tierra]))


def test_la_ciudad_se_seca_mas(malla, clima):
    """Consecuencia que suele olvidarse: en la zona impermeable el suelo
    tampoco se moja, porque el agua se va por el drenaje."""
    imperm = np.full(malla.n_celdas, 0.8)
    sin = SimuladorEstocastico(malla, clima, ParametrosModelo())
    con = SimuladorEstocastico(
        malla, clima, ParametrosModelo(fraccion_impermeable=imperm))
    tierra = clima.es_tierra
    a = sin.simular(dt.date(2026, 9, 15), n_dias=10, n_miembros=100, semilla=5)
    b = con.simular(dt.date(2026, 9, 15), n_dias=10, n_miembros=100, semilla=5)
    assert (np.nanmean(b.humedad_suelo[:, :, tierra])
            < np.nanmean(a.humedad_suelo[:, :, tierra]))


def test_la_impermeabilidad_valida_su_rango(malla, clima):
    with pytest.raises(ValueError, match="\\[0, 1\\]"):
        SimuladorEstocastico(malla, clima,
                             ParametrosModelo(fraccion_impermeable=1.5))
    with pytest.raises(ValueError, match="escalar o de largo"):
        SimuladorEstocastico(
            malla, clima, ParametrosModelo(fraccion_impermeable=np.zeros(5)))


def test_mu_positiva_aumenta_la_lluvia(simulador, clima):
    """El aporte del sondeo: con atmosfera inestable sube la probabilidad Y la
    intensidad, de forma espacialmente coherente."""
    tierra = clima.es_tierra
    base = simulador.simular(FECHA_PRUEBA, n_dias=7, n_miembros=200,
                             semilla=11)
    alta = simulador.simular(FECHA_PRUEBA, n_dias=7, n_miembros=200,
                             semilla=11, mu_campo=1.0)
    baja = simulador.simular(FECHA_PRUEBA, n_dias=7, n_miembros=200,
                             semilla=11, mu_campo=-1.0)

    def resumen(r):
        return (float((r.lluvia_mm[:, :, tierra] > 0).mean()),
                float(r.lluvia_mm[:, :, tierra].sum(axis=1).mean()))

    f_baja, a_baja = resumen(baja)
    f_base, a_base = resumen(base)
    f_alta, a_alta = resumen(alta)
    assert f_baja < f_base < f_alta
    assert a_baja < a_base < a_alta


def test_mu_acepta_escalar_por_celda_y_por_dia(simulador, malla):
    n = malla.n_celdas
    for mu in (0.5, np.full(n, 0.5), np.full(5, 0.5), np.full((5, n), 0.5)):
        r = simulador.simular(FECHA_PRUEBA, n_dias=5, n_miembros=20,
                              semilla=2, mu_campo=mu)
        assert r.lluvia_mm.shape == (20, 5, n)


def test_mu_de_forma_invalida(simulador):
    with pytest.raises(ValueError, match="mu_campo"):
        simulador.simular(FECHA_PRUEBA, n_dias=5, n_miembros=10,
                          mu_campo=np.zeros((3, 3)))


def test_mu_no_contamina_el_calentamiento(simulador, clima):
    """El calentamiento sirve para que el suelo llegue a un estado consistente
    con la climatologia; meterle la anomalia de hoy lo falsearia."""
    mu = simulador._preparar_mu(1.0, total=50, n=simulador.malla.n_celdas,
                                calent=45)
    assert np.all(mu[:45] == 0.0)
    assert np.all(mu[45:] == 1.0)
