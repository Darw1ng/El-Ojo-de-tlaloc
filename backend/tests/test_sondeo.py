"""Pruebas del perfil atmosferico: fisica, parsers y la mu del campo latente.

La fisica se verifica contra tablas publicadas, no contra si misma.
"""

import math

import numpy as np
import pytest

from ojo_tlaloc.fuentes.base import ErrorFuente
from ojo_tlaloc.fuentes.sondeo import (
    COEFICIENTES_PROBIT_PROVISIONALES,
    PerfilAtmosferico,
    calibrar_probit,
    interpretar_indices,
    leer_csv_globo,
    leer_sondeo,
    leer_texto_wyoming,
    media_campo_latente,
    normalizar_indices,
    presion_vapor_saturacion_hpa,
    razon_mezcla,
    rocio_desde_humedad,
    temperatura_lcl_k,
    temperatura_parcela_saturada,
    theta_e,
    validar_indices,
)

CSV_GLOBO = """presion_hpa,temp_c,humedad_rel,altura_m
1008,29.5,78,20
1000,28.9,80,90
950,25.1,85,540
900,21.8,88,1010
850,18.2,84,1500
800,14.9,75,2010
700,8.1,60,3100
600,1.2,45,4300
500,-7.5,35,5700
400,-18.9,30,7300
300,-34.2,25,9400
200,-54.1,20,12200
"""


# --- termodinamica ---------------------------------------------------------


def test_presion_vapor_contra_tabla():
    """Valores de tabla termodinamica estandar, en hPa."""
    for t, esperado in ((0, 6.11), (10, 12.28), (20, 23.39), (30, 42.47)):
        assert float(presion_vapor_saturacion_hpa(t)) == pytest.approx(
            esperado, rel=0.002)


def test_rocio_con_saturacion_es_la_temperatura():
    assert float(rocio_desde_humedad(25.0, 100.0)) == pytest.approx(25.0, abs=0.02)
    assert float(rocio_desde_humedad(10.0, 100.0)) == pytest.approx(10.0, abs=0.02)


def test_rocio_contra_tabla():
    """25 C con 50% de humedad relativa da rocio de 13.9 C."""
    assert float(rocio_desde_humedad(25.0, 50.0)) == pytest.approx(13.9, abs=0.2)


def test_rocio_siempre_menor_o_igual_que_temperatura():
    for hr in (1, 25, 50, 75, 99, 100):
        assert float(rocio_desde_humedad(30.0, hr)) <= 30.0 + 1e-6


def test_razon_mezcla_crece_con_el_rocio():
    r1 = float(razon_mezcla(1000.0, 10.0))
    r2 = float(razon_mezcla(1000.0, 25.0))
    assert 0 < r1 < r2 < 0.05


def test_lcl_mas_alto_con_aire_mas_seco():
    """Aire seco condensa mas arriba, o sea con temperatura de LCL menor."""
    humedo = float(temperatura_lcl_k(30.0, 28.0))
    seco = float(temperatura_lcl_k(30.0, 10.0))
    assert seco < humedo


def test_theta_e_se_conserva_al_invertir():
    """temperatura_parcela_saturada es la inversa de theta_es: si se levanta
    una parcela saturada y se baja, tiene que volver al mismo theta_e."""
    p, t = 900.0, 20.0
    te = float(theta_e(p, t, t))        # saturada: rocio = temperatura
    t_recuperada = temperatura_parcela_saturada(p, te) - 273.15
    assert t_recuperada == pytest.approx(t, abs=0.1)


def test_parcela_saturada_se_enfria_al_subir():
    te = float(theta_e(1000.0, 28.0, 24.0))
    t900 = temperatura_parcela_saturada(900.0, te)
    t500 = temperatura_parcela_saturada(500.0, te)
    assert t500 < t900


# --- indices ---------------------------------------------------------------


@pytest.fixture(scope="module")
def perfil():
    return leer_csv_globo(CSV_GLOBO, fecha="2026-11-14T12:00Z")


def test_pwat_en_rango_fisico(perfil):
    """Columna tropical humeda: entre 40 y 60 mm."""
    pwat = perfil.agua_precipitable_mm()
    assert 35.0 < pwat < 65.0


def test_pwat_crece_con_la_humedad():
    p = np.arange(1000, 150, -50.0)
    t = 25.0 - 7.0 * np.log(1000.0 / p) * 7.5
    humedo = PerfilAtmosferico(p, t, t - 1.0)
    seco = PerfilAtmosferico(p, t, t - 20.0)
    assert humedo.agua_precipitable_mm() > 3 * seco.agua_precipitable_mm()


def test_cape_de_atmosfera_isoterma_es_casi_cero():
    """Una atmosfera isoterma es muy estable: no hay energia convectiva."""
    p = np.arange(1000, 150, -25.0)
    iso = PerfilAtmosferico(p, np.full_like(p, 25.0), np.full_like(p, 18.0))
    cape, _ = iso.cape_cin()
    assert cape < 50.0


def test_cape_positivo_en_perfil_convectivo(perfil):
    cape, cin = perfil.cape_cin()
    # Tarde convectiva tropical: del orden de miles, no decenas de miles.
    assert 500.0 < cape < 6000.0
    assert 0.0 <= cin < 300.0


def test_cape_crece_con_la_inestabilidad():
    p = np.arange(1000, 150, -25.0)
    suave = 28.0 - 5.0 * np.log(1000.0 / p) * 7.5
    fuerte = 28.0 - 8.0 * np.log(1000.0 / p) * 7.5
    c_suave = PerfilAtmosferico(p, suave, suave - 3).cape_cin()[0]
    c_fuerte = PerfilAtmosferico(p, fuerte, fuerte - 3).cape_cin()[0]
    assert c_fuerte > c_suave


def test_indices_completos(perfil):
    for clave in ("cape_j_kg", "cin_j_kg", "pwat_mm", "lcl_hpa", "lcl_m",
                  "indice_k", "total_totals", "niveles", "tope_hpa"):
        assert clave in perfil.indices
    assert perfil.indices["niveles"] == 12
    assert perfil.indices["tope_hpa"] == pytest.approx(200.0)
    assert 0 < perfil.indices["lcl_m"] < 3000


def test_interpretacion_en_lenguaje_operativo(perfil):
    i = interpretar_indices(perfil.indices)
    for clave in ("inestabilidad", "inhibicion", "humedad_columna",
                  "potencial_tormenta"):
        assert clave in i and isinstance(i[clave], str)


def test_validacion_caza_perfiles_imposibles():
    """Un CAPE de 18000 J/kg no es una tormenta historica: es un error."""
    avisos = validar_indices({"cape_j_kg": 18000.0, "pwat_mm": 340.0})
    nombres = {a["indice"] for a in avisos}
    assert "cape_j_kg" in nombres and "pwat_mm" in nombres
    assert not validar_indices({"cape_j_kg": 1500.0, "pwat_mm": 48.0})


def test_el_perfil_rechaza_datos_insuficientes():
    with pytest.raises(ErrorFuente, match="niveles utiles"):
        PerfilAtmosferico(np.array([1000.0, 900.0]), np.array([25.0, 20.0]),
                          np.array([20.0, 15.0]))


def test_el_perfil_ordena_por_presion():
    """Da igual si el registro viene del ascenso o del descenso."""
    p = np.array([500.0, 1000.0, 700.0, 850.0, 300.0, 200.0])
    t = np.array([-8.0, 28.0, 8.0, 18.0, -35.0, -55.0])
    perf = PerfilAtmosferico(p, t, t - 4.0)
    assert np.all(np.diff(perf.presion_hpa) < 0)
    assert perf.presion_hpa[0] == 1000.0


def test_el_rocio_no_puede_superar_la_temperatura():
    """Pasa por error de sensor y hay que corregirlo, no propagarlo."""
    p = np.arange(1000, 400, -100.0)
    t = np.full_like(p, 20.0)
    perf = PerfilAtmosferico(p, t, t + 5.0)    # rocio imposible
    assert np.all(perf.rocio_c <= perf.temperatura_c + 1e-9)


# --- parsers ---------------------------------------------------------------


def test_csv_del_globo_se_marca_como_propio(perfil):
    assert perfil.es_propio is True
    assert "propio" in perfil.procedencia().fuente
    assert "Ojo de Tlaloc" in perfil.procedencia().atribucion


def test_csv_acepta_alias_de_columnas():
    """La sonda la arma quien la arma: se aceptan varias convenciones."""
    variantes = (
        "pressure,temp,rh\n1000,28,80\n900,22,85\n850,18,84\n700,8,60\n500,-8,35\n",
        "p;t;hr\n1000;28;80\n900;22;85\n850;18;84\n700;8;60\n500;-8;35\n",
        "presion_hpa,temperatura_c,humedad_relativa\n1000,28,80\n900,22,85\n"
        "850,18,84\n700,8,60\n500,-8,35\n",
    )
    for texto in variantes:
        p = leer_csv_globo(texto)
        assert p.presion_hpa.size == 5


def test_csv_acepta_rocio_en_lugar_de_humedad():
    texto = ("presion,temp,rocio\n1000,28,24\n900,22,19\n850,18,16\n"
             "700,8,2\n500,-8,-20\n")
    p = leer_csv_globo(texto)
    assert p.rocio_c[0] == pytest.approx(24.0)


def test_csv_sin_presion_falla_con_mensaje_util():
    with pytest.raises(ErrorFuente, match="presion"):
        leer_csv_globo("temp,rh\n28,80\n22,85\n18,84\n8,60\n-8,35\n")


def test_csv_sin_humedad_falla_porque_no_se_puede_calcular_nada():
    with pytest.raises(ErrorFuente, match="humedad"):
        leer_csv_globo("presion,temp\n1000,28\n900,22\n850,18\n700,8\n500,-8\n")


def test_texto_wyoming_se_lee():
    """Formato de ancho fijo de la Universidad de Wyoming / IGRA."""
    texto = """
-----------------------------------------------------------------------------
   PRES   HGHT   TEMP   DWPT   RELH   MIXR   DRCT   SKNT   THTA   THTE   THTV
    hPa     m      C      C      %    g/kg    deg   knot     K      K      K
-----------------------------------------------------------------------------
 1008.0     20   29.4   24.6     76  19.68    110     10  302.3  359.1  305.8
 1000.0     90   28.8   24.2     76  19.33    115     12  302.4  358.0  305.8
  925.0    745   24.2   21.6     86  17.56    120     15  304.2  354.6  307.3
  850.0   1450   18.6   17.2     92  14.08    130     18  305.6  347.0  308.2
  700.0   3080    8.4    6.1     85   7.44    150     20  312.0  335.3  313.4
  500.0   5820   -7.5  -12.3     68   2.29    200     25  321.9  330.5  322.3
  300.0   9420  -34.1  -44.1     32   0.32    230     35  340.8  342.4  340.9
  200.0  12190  -54.3  -66.3     20   0.04    240     40  360.1  360.6  360.2
"""
    p = leer_texto_wyoming(texto, estacion="Veracruz", fecha="2026-09-15 12Z")
    assert p.presion_hpa.size == 8
    assert p.estacion == "Veracruz"
    assert p.es_propio is False
    assert p.presion_hpa[0] == pytest.approx(1008.0)
    assert p.temperatura_c[0] == pytest.approx(29.4)
    # El viento se convierte de nudos a m/s.
    assert p.viento_vel_ms[0] == pytest.approx(10 * 0.514444, rel=1e-3)
    assert 40.0 < p.agua_precipitable_mm() < 70.0


def test_leer_sondeo_detecta_el_formato():
    assert leer_sondeo(CSV_GLOBO).es_propio is True
    texto_fijo = (
        "   PRES   HGHT   TEMP   DWPT\n"
        " 1000.0     90   28.8   24.2\n"
        "  925.0    745   24.2   21.6\n"
        "  850.0   1450   18.6   17.2\n"
        "  700.0   3080    8.4    6.1\n"
        "  500.0   5820   -7.5  -12.3\n"
    )
    assert leer_sondeo(texto_fijo).es_propio is False


def test_sondeo_basura_falla():
    with pytest.raises(ErrorFuente):
        leer_sondeo("hola\nmundo\nno soy un sondeo\n")


# --- mu del campo latente --------------------------------------------------


def test_el_cape_entra_por_su_raiz():
    """La velocidad vertical va como sqrt(2 CAPE), asi que la raiz es la
    cantidad con significado lineal. Sin esto, un CAPE de tarde de verano
    saturaba mu por si solo."""
    z = normalizar_indices({"cape_j_kg": 2500.0})
    assert "raiz_cape" in z
    assert z["raiz_cape"] == pytest.approx((math.sqrt(2500.0) - 30.0) / 14.0)
    assert abs(z["raiz_cape"]) < 2.0


def test_mu_crece_con_la_inestabilidad():
    estable = media_campo_latente({"cape_j_kg": 50.0, "pwat_mm": 28.0,
                                   "cin_j_kg": 200.0})
    inestable = media_campo_latente({"cape_j_kg": 2500.0, "pwat_mm": 55.0,
                                     "cin_j_kg": 5.0})
    assert inestable["mu"] > estable["mu"]
    assert estable["mu"] < 0 < inestable["mu"]


def test_mu_esta_acotada():
    """mu desplaza la probabilidad de TODO el dominio: sin tope, un valor
    extremo pega la probabilidad a 1 en todas las celdas y destruye la
    dispersion del ensamble, que es la unica salida util."""
    r = media_campo_latente({"cape_j_kg": 7000.0, "pwat_mm": 79.0,
                             "cin_j_kg": 0.0})
    assert r["mu"] == pytest.approx(1.5)
    assert r["acotada"] is True
    assert abs(r["mu_sin_acotar"]) > 1.5


def test_mu_marca_los_perfiles_no_confiables():
    r = media_campo_latente({"cape_j_kg": 20000.0, "pwat_mm": 300.0})
    assert r["confiable"] is False
    assert r["avisos"]


def test_mu_declara_que_los_coeficientes_son_provisionales():
    r = media_campo_latente({"cape_j_kg": 1000.0, "pwat_mm": 45.0})
    assert r["coeficientes_provisionales"] is True
    assert "aportes" in r and r["aportes"]


def test_el_cin_alto_reduce_mu():
    sin_tapa = media_campo_latente({"cape_j_kg": 1500.0, "pwat_mm": 50.0,
                                    "cin_j_kg": 0.0})
    con_tapa = media_campo_latente({"cape_j_kg": 1500.0, "pwat_mm": 50.0,
                                    "cin_j_kg": 300.0})
    assert con_tapa["mu_sin_acotar"] < sin_tapa["mu_sin_acotar"]


# --- calibracion del probit ------------------------------------------------


def test_el_probit_recupera_coeficientes_conocidos():
    """Se generan datos con un coeficiente conocido y se verifica que la
    estimacion lo recupera. Si esta prueba pasa, la calibracion sirve."""
    from ojo_tlaloc.estadistica import norm_cdf

    rng = np.random.default_rng(42)
    n = 4000
    cape = rng.uniform(0, 3000, n)
    pwat = rng.uniform(25, 65, n)
    indices = [{"cape_j_kg": float(c), "pwat_mm": float(w)}
               for c, w in zip(cape, pwat)]
    z = np.array([[normalizar_indices(ix)["raiz_cape"],
                   normalizar_indices(ix)["pwat_mm"]] for ix in indices])
    eta_real = -0.2 + 0.8 * z[:, 0] + 0.5 * z[:, 1]
    y = (rng.random(n) < np.asarray(norm_cdf(eta_real), dtype=float)).astype(float)

    r = calibrar_probit(indices, y)
    assert r["coeficientes"]["raiz_cape"] == pytest.approx(0.8, abs=0.12)
    assert r["coeficientes"]["pwat_mm"] == pytest.approx(0.5, abs=0.12)
    assert r["coeficientes"]["intercepto"] == pytest.approx(-0.2, abs=0.12)
    assert r["detalle"]["raiz_cape"]["significativo_95"] is True
    assert r["pseudo_r2_mcfadden"] > 0.1
    assert r["casos"] == n


def test_el_probit_no_encuentra_senal_donde_no_hay():
    """Con ocurrencia aleatoria independiente de los indices, el coeficiente
    no debe salir significativo. Una prueba que solo verifique que encuentra
    senal es la mitad de la prueba."""
    rng = np.random.default_rng(7)
    n = 2000
    indices = [{"cape_j_kg": float(c), "pwat_mm": float(w)}
               for c, w in zip(rng.uniform(0, 3000, n), rng.uniform(25, 65, n))]
    y = (rng.random(n) < 0.4).astype(float)
    r = calibrar_probit(indices, y)
    assert abs(r["coeficientes"]["raiz_cape"]) < 0.15
    assert r["pseudo_r2_mcfadden"] < 0.02


def test_el_probit_exige_datos_suficientes():
    with pytest.raises(ValueError, match="al menos 30"):
        calibrar_probit([{"cape_j_kg": 100.0, "pwat_mm": 40.0}] * 10,
                        [0] * 10)


def test_el_probit_valida_entradas():
    indices = [{"cape_j_kg": 100.0, "pwat_mm": 40.0}] * 40
    with pytest.raises(ValueError, match="mismo largo"):
        calibrar_probit(indices, [0] * 39)
    with pytest.raises(ValueError, match="binaria"):
        calibrar_probit(indices, [0.5] * 40)
