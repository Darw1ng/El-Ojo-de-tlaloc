"""Pruebas de los endpoints de la plataforma de fusion.

Los que necesitan OSM o POWER se saltan si no hay red ni cache, igual que en
test_fuentes_remotas.py.
"""

import pytest
from fastapi.testclient import TestClient

from ojo_tlaloc.api.app import crear_app

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


@pytest.fixture(scope="module")
def cliente():
    return TestClient(crear_app())


@pytest.fixture(scope="module")
def expediente_sin_red(cliente):
    """Expediente con las fuentes remotas apagadas: siempre disponible."""
    r = cliente.get("/api/expediente?usar_osm=false&usar_power=false")
    assert r.status_code == 200
    return r.json()


@pytest.fixture(scope="module")
def expediente_completo(cliente):
    r = cliente.get("/api/expediente")
    assert r.status_code == 200
    j = r.json()
    caidas = [a["variable"] for a in j["advertencias"]
              if a.get("sesgo") == "fuente no disponible"]
    if caidas:
        pytest.skip("fuentes no disponibles: {}".format(", ".join(caidas)))
    return j


@pytest.fixture(scope="module")
def corrida_fusion(cliente, expediente_completo):
    r = cliente.post("/api/pronostico/fusion", json={
        "fecha_inicio": "2026-09-15", "dias": 7, "miembros": 60,
        "semilla": 20261114,
    })
    assert r.status_code == 200
    return r.json()["id_corrida"]


# --- expediente ------------------------------------------------------------


def test_el_expediente_responde_sin_fuentes_remotas(expediente_sin_red):
    """El sistema tiene que funcionar sin internet y decir que le falta."""
    r = expediente_sin_red["resumen"]
    assert r["capas"] >= 4
    assert r["por_nivel"]["sintetico"] >= 1
    assert "elevacion_m" in r["sinteticas"]


def test_el_expediente_declara_lo_que_falta(expediente_sin_red):
    faltan = expediente_sin_red["faltantes"]
    assert "humedad_suelo_obs" in faltan["observado"]
    assert isinstance(faltan["derivado"], list)


def test_cada_capa_trae_procedencia_completa(expediente_sin_red):
    for nombre, proc in expediente_sin_red["procedencias"].items():
        assert proc["fuente"], nombre
        assert proc["nivel"] in ("observado", "reanalisis", "derivado",
                                 "sintetico"), nombre
        assert proc["obtenido"], nombre


def test_capa_del_expediente(cliente):
    j = cliente.get("/api/expediente/capa?nombre=elevacion_m").json()
    assert j["nombre"] == "elevacion_m"
    assert len(j["valores"]) == len(j["ids_celdas"])
    assert j["procedencia"]["nivel"] == "sintetico"
    assert j["resumen"]["celdas_con_dato"] > 0


def test_capa_del_expediente_en_geojson(cliente):
    j = cliente.get(
        "/api/expediente/capa?nombre=elevacion_m&geojson=true").json()
    assert j["type"] == "FeatureCollection"
    assert "elevacion_m" in j["features"][0]["properties"]
    assert j["atribuciones"] is not None


def test_capa_inexistente_dice_cuales_hay(cliente):
    r = cliente.get("/api/expediente/capa?nombre=inventada")
    assert r.status_code == 404
    assert "Tiene:" in r.json()["detail"]


def test_celda_del_expediente(cliente):
    j = cliente.get("/api/expediente/celda/OT0.0.0").json()
    assert j["id_celda"] == "OT0.0.0"
    assert j["geografia"]["lat"] == pytest.approx(19.1704, abs=0.01)
    assert j["geografia"]["escala"] == "1:16"
    assert "estatico" in j["datos"]
    # Cada dato trae su fuente, no solo el numero.
    alguna = next(iter(j["datos"]["estatico"].values()))
    assert "fuente" in alguna and "nivel" in alguna and "unidad" in alguna


def test_celda_inexistente(cliente):
    assert cliente.get(
        "/api/expediente/celda/OT0.999.999").status_code == 404


def test_atribuciones_declaradas(cliente):
    """La ODbL de OSM exige atribucion visible. Esto no es cortesia."""
    j = cliente.get("/api/expediente/atribuciones").json()
    assert isinstance(j["atribuciones"], list)
    assert isinstance(j["capas_sinteticas"], list)
    assert "rotularlas" in j["nota"]


# --- sondeo ----------------------------------------------------------------


def test_analizar_sondeo(cliente):
    r = cliente.post("/api/sondeo", content=CSV_GLOBO,
                     headers={"Content-Type": "text/plain"})
    assert r.status_code == 200
    j = r.json()
    ix = j["perfil"]["indices"]
    assert 500 < ix["cape_j_kg"] < 6000
    assert 35 < ix["pwat_mm"] < 65
    assert j["perfil"]["es_propio"] is True
    mu = j["mu_campo_latente"]
    assert -1.5 <= mu["mu"] <= 1.5
    assert mu["confiable"] is True
    assert mu["coeficientes_provisionales"] is True
    assert "PROVISIONALES" in j["nota"]


def test_el_sondeo_trae_interpretacion_en_lenguaje_operativo(cliente):
    j = cliente.post("/api/sondeo", content=CSV_GLOBO,
                     headers={"Content-Type": "text/plain"}).json()
    i = j["perfil"]["interpretacion"]
    for clave in ("inestabilidad", "inhibicion", "humedad_columna",
                  "potencial_tormenta"):
        assert clave in i


def test_sondeo_invalido(cliente):
    r = cliente.post("/api/sondeo", content="esto no es un sondeo\n",
                     headers={"Content-Type": "text/plain"})
    assert r.status_code == 400


def test_calibrar_probit_por_api(cliente):
    import numpy as np

    from ojo_tlaloc.estadistica import norm_cdf
    from ojo_tlaloc.fuentes.sondeo import normalizar_indices

    rng = np.random.default_rng(3)
    n = 800
    indices = [{"cape_j_kg": float(c), "pwat_mm": float(w)}
               for c, w in zip(rng.uniform(0, 3000, n), rng.uniform(25, 65, n))]
    z = np.array([[normalizar_indices(ix)["raiz_cape"],
                   normalizar_indices(ix)["pwat_mm"]] for ix in indices])
    eta = 0.7 * z[:, 0] + 0.4 * z[:, 1]
    y = (rng.random(n) < np.asarray(norm_cdf(eta), dtype=float)).astype(int)

    j = cliente.post("/api/sondeo/calibrar", json={
        "indices": indices, "ocurrencia": y.tolist(),
    }).json()
    assert j["coeficientes"]["raiz_cape"] == pytest.approx(0.7, abs=0.2)
    assert j["casos"] == n
    assert j["pseudo_r2_mcfadden"] > 0.05


def test_calibrar_valida_el_cuerpo(cliente):
    assert cliente.post("/api/sondeo/calibrar", json={}).status_code == 400
    assert cliente.post("/api/sondeo/calibrar", json={
        "indices": [{"cape_j_kg": 1.0}], "ocurrencia": [1],
    }).status_code == 400


# --- analisis --------------------------------------------------------------


def test_aptitud_sin_corrida(cliente):
    j = cliente.get("/api/aptitud").json()
    assert j["usa_inundabilidad"] is False
    assert len(j["aptitud"]) == len(j["ids_celdas"])
    assert j["advertencias"]
    texto = " ".join(j["advertencias"]).lower()
    assert "topografico" in texto


def test_pendiente(cliente):
    j = cliente.get("/api/pendiente").json()
    assert len(j["pendiente_max_grados"]) == len(j["ids_celdas"])
    assert j["paso_m"] > 1000
    assert "elevacion_sintetica" in j
    assert "esconder" in j["advertencia"]


def test_catalogo_de_actividades(cliente):
    j = cliente.get("/api/actividades").json()
    acts = j["actividades"]
    assert "colado_concreto" in acts and "montaje_con_grua" in acts
    for nombre, cfg in acts.items():
        assert cfg["razon"], nombre
        assert cfg["lluvia_max_mm"] > 0, nombre
    assert acts["montaje_con_grua"]["necesita_viento"] is True
    assert "no una norma" in j["nota"]


# --- pronostico con fusion -------------------------------------------------


def test_pronostico_de_fusion_declara_sus_fuentes(cliente, corrida_fusion):
    j = cliente.post("/api/pronostico/fusion", json={
        "fecha_inicio": "2026-09-15", "dias": 7, "miembros": 60,
        "semilla": 20261114,
    }).json()
    f = j["fusion"]
    assert f["climatologia"] == "NASA POWER"
    assert f["impermeabilidad"] == "OpenStreetMap"
    assert f["sondeo"] == "no se mando"
    assert f["capas_en_expediente"] > 10
    assert f["atribuciones"]


def test_el_sondeo_cambia_el_pronostico(cliente, expediente_completo):
    """La prueba que sostiene la propuesta: con el perfil atmosferico el
    pronostico deja de ser climatologico."""
    base = cliente.post("/api/pronostico/fusion", json={
        "fecha_inicio": "2026-09-15", "dias": 7, "miembros": 100,
        "semilla": 20261114,
    }).json()
    con = cliente.post("/api/pronostico/fusion", json={
        "fecha_inicio": "2026-09-15", "dias": 7, "miembros": 100,
        "semilla": 20261114, "sondeo": CSV_GLOBO,
    }).json()
    assert con["fusion"]["sondeo"] == "aplicado"
    assert con["fusion"]["mu_campo_latente"] > 0
    assert (con["resumen"]["lluvia_total_mm"]["p50"]
            > base["resumen"]["lluvia_total_mm"]["p50"])
    assert con["mu_detalle"]["aportes"]


def test_un_sondeo_imposible_se_descarta_en_lugar_de_usarse(cliente,
                                                            expediente_completo):
    """Un perfil con indices fuera de rango fisico no debe mover el
    pronostico: se corre climatologico y se avisa."""
    malo = ("presion_hpa,temp_c,humedad_rel\n"
            "1000,25,100\n900,25,100\n800,25,100\n700,25,100\n"
            "600,25,100\n500,25,100\n400,25,100\n300,25,100\n")
    j = cliente.post("/api/pronostico/fusion", json={
        "fecha_inicio": "2026-09-15", "dias": 5, "miembros": 60,
        "semilla": 1, "sondeo": malo,
    }).json()
    assert "descartado" in j["fusion"]["sondeo"]
    assert j["fusion"]["mu_campo_latente"] is None
    assert j["mu_detalle"]["confiable"] is False


def test_fusion_valida_sus_parametros(cliente):
    assert cliente.post("/api/pronostico/fusion",
                        json={"nivel": 9}).status_code == 400
    assert cliente.post("/api/pronostico/fusion",
                        json={"fecha_inicio": "ayer"}).status_code == 400
    assert cliente.post("/api/pronostico/fusion", json={
        "sondeo": "basura\n"}).status_code == 400


def test_exposicion_cruza_pronostico_con_osm(cliente, corrida_fusion):
    j = cliente.get("/api/corrida/{}/exposicion?corte=0.05".format(
        corrida_fusion)).json()
    assert "resumen" in j
    assert j["celdas_en_riesgo"] >= 0
    assert "infraestructura_critica" in j["elementos"]
    assert len(j["indice_exposicion"]) == len(j["ids_celdas"])
    assert any("censo" in a for a in j["advertencias"])


def test_exposicion_declara_corte_inalcanzable(cliente, corrida_fusion):
    j = cliente.get("/api/corrida/{}/exposicion?corte=0.999".format(
        corrida_fusion)).json()
    if j["corte_inalcanzable"]:
        assert "maxima del dominio" in j["resumen"]


def test_exposicion_de_nivel_equivocado_choca(cliente, corrida_fusion):
    r = cliente.get("/api/corrida/{}/exposicion?nivel=1".format(corrida_fusion))
    assert r.status_code == 409


def test_ventanas_de_obra_por_mapa(cliente, corrida_fusion):
    j = cliente.get("/api/corrida/{}/ventanas".format(corrida_fusion)).json()
    assert j["horizonte_dias"] == 7
    assert "colado_concreto" in j["actividades"]
    bloque = j["actividades"]["colado_concreto"]
    assert len(bloque["probabilidad_por_dia"]) == 7
    assert len(bloque["dias_trabajables_esperados"]) == len(j["ids_celdas"])
    assert bloque["razon"]
    # Las que necesitan viento se omiten en lugar de inventarse.
    assert any(o["actividad"] == "montaje_con_grua" for o in j["omitidas"])


def test_ventanas_de_obra_por_celda(cliente, corrida_fusion):
    j = cliente.get("/api/corrida/{}/ventanas?id_celda=OT0.0.0".format(
        corrida_fusion)).json()
    assert j["id_celda"] == "OT0.0.0"
    dias = [a["dias_trabajables_esperados"] for a in j["actividades"]]
    assert dias == sorted(dias, reverse=True)
    for a in j["actividades"]:
        assert 0 <= a["dias_trabajables_esperados"] <= j["horizonte_dias"] + 1e-6


def test_ventanas_de_una_sola_actividad(cliente, corrida_fusion):
    j = cliente.get("/api/corrida/{}/ventanas?actividad=colado_concreto".format(
        corrida_fusion)).json()
    assert list(j["actividades"]) == ["colado_concreto"]


def test_ventanas_actividad_invalida(cliente, corrida_fusion):
    r = cliente.get("/api/corrida/{}/ventanas?actividad=colar_oro".format(
        corrida_fusion))
    assert r.status_code == 400
    assert "Validas:" in r.json()["detail"]


def test_ventanas_celda_invalida(cliente, corrida_fusion):
    assert cliente.get(
        "/api/corrida/{}/ventanas?id_celda=OT0.999.999".format(corrida_fusion)
    ).status_code == 404


def test_la_documentacion_openapi_incluye_la_fusion(cliente):
    j = cliente.get("/openapi.json").json()
    for ruta in ("/api/expediente", "/api/sondeo", "/api/aptitud",
                 "/api/pronostico/fusion", "/api/actividades"):
        assert ruta in j["paths"], ruta
