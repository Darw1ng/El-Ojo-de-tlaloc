"""Pruebas de la API HTTP: el contrato con el front."""

import pytest
from fastapi.testclient import TestClient

from ojo_tlaloc.api.app import crear_app


@pytest.fixture(scope="module")
def cliente():
    return TestClient(crear_app())


@pytest.fixture(scope="module")
def id_corrida(cliente):
    r = cliente.post("/api/pronostico", json={
        "fecha_inicio": "2026-09-15", "dias": 7, "miembros": 60,
        "nivel": 0, "semilla": 20261114,
    })
    assert r.status_code == 200
    return r.json()["id_corrida"]


# --- sistema ---------------------------------------------------------------


def test_salud(cliente):
    j = cliente.get("/salud").json()
    assert j["ok"] is True
    assert j["version"]


def test_area_apunta_al_enlace_del_proyecto(cliente):
    j = cliente.get("/api/area").json()
    assert j["centro"]["lat"] == pytest.approx(19.1704)
    assert j["centro"]["lon"] == pytest.approx(-96.1654)
    assert j["zoom_osm"] == 11
    assert "openstreetmap.org" in j["enlace_osm"]
    assert "OpenStreetMap" in j["atribucion"], "falta la atribucion de OSM"


def test_escalas_para_que_el_front_no_invente_rangos(cliente):
    j = cliente.get("/api/escalas").json()
    assert "lluvia" in j["escalas"]
    assert j["escalas"]["lluvia"]["dominio"][0] == 0
    assert "p50" in j["estadisticos"]
    assert 50.0 in j["umbrales_lluvia_mm"]


def test_documentacion_openapi(cliente):
    j = cliente.get("/openapi.json").json()
    assert "/api/pronostico" in j["paths"]
    assert "Tlaloc" in j["info"]["title"]


# --- malla -----------------------------------------------------------------


def test_malla_geojson(cliente):
    j = cliente.get("/api/malla").json()
    assert j["type"] == "FeatureCollection"
    assert j["metadata"]["escala"] == "1:16"
    assert len(j["features"]) == j["metadata"]["n_celdas"]
    props = j["features"][0]["properties"]
    for clave in ("id", "lat", "lon", "elevacion_m", "es_tierra"):
        assert clave in props


def test_malla_sin_geografia_es_mas_ligera(cliente):
    con = cliente.get("/api/malla?incluir_geografia=true").json()
    sin = cliente.get("/api/malla?incluir_geografia=false").json()
    assert "elevacion_m" in con["features"][0]["properties"]
    assert "elevacion_m" not in sin["features"][0]["properties"]


def test_niveles_de_malla(cliente):
    n0 = cliente.get("/api/malla?nivel=0").json()["metadata"]
    n1 = cliente.get("/api/malla?nivel=1").json()["metadata"]
    assert n1["escala"] == "1:32"
    assert n1["n_celdas"] > n0["n_celdas"]
    assert n1["area_celda_km2"] == pytest.approx(n0["area_celda_km2"] / 4, rel=1e-6)


def test_nivel_invalido(cliente):
    assert cliente.get("/api/malla?nivel=9").status_code == 422


def test_climatologia_anual_y_mensual(cliente):
    anual = cliente.get("/api/climatologia?mes=0").json()
    assert anual["resumen"]["celdas_tierra"] > 0
    assert "sintetica" in anual["nota"].lower(), "hay que declarar que es sintetica"

    sep = cliente.get("/api/climatologia?mes=9").json()
    assert sep["nombre_mes"] == "septiembre"
    v = [x for x in sep["valores"]["lluvia_mensual_mm"] if x is not None]
    assert max(v) > 200, "septiembre tiene que ser lluvioso en Veracruz"


# --- pronostico ------------------------------------------------------------


def test_pronostico_devuelve_resumen_util(cliente, id_corrida):
    j = cliente.post("/api/pronostico", json={
        "fecha_inicio": "2026-09-15", "dias": 7, "miembros": 60, "semilla": 20261114,
    }).json()
    r = j["resumen"]
    assert r["dias"] == 7 and r["miembros"] == 60
    assert len(r["fechas"]) == 7
    assert r["escala"] == "1:16"
    assert r["segundos_calculo"] > 0
    t = r["lluvia_total_mm"]
    assert t["p10"] <= t["p50"] <= t["p90"]


def test_el_id_de_corrida_es_deterministico(cliente):
    cuerpo = {"fecha_inicio": "2026-10-01", "dias": 5, "miembros": 40,
              "semilla": 123}
    a = cliente.post("/api/pronostico", json=cuerpo).json()["id_corrida"]
    b = cliente.post("/api/pronostico", json=cuerpo).json()["id_corrida"]
    assert a == b
    cuerpo["semilla"] = 124
    c = cliente.post("/api/pronostico", json=cuerpo).json()["id_corrida"]
    assert c != a


def test_peticion_demasiado_grande(cliente):
    r = cliente.post("/api/pronostico", json={
        "dias": 60, "miembros": 1000, "nivel": 2, "semilla": 1,
    })
    assert r.status_code == 413
    assert "tope" in r.json()["detail"]


def test_parametros_fuera_de_rango(cliente):
    assert cliente.post("/api/pronostico", json={"dias": 0}).status_code == 422
    assert cliente.post("/api/pronostico", json={"miembros": 1}).status_code == 422
    assert cliente.post("/api/pronostico",
                        json={"humedad_inicial": 2.0}).status_code == 422


def test_capa_ligera_y_geojson(cliente, id_corrida):
    ligera = cliente.get(
        "/api/corrida/{}/capa?variable=lluvia&dia=1&estadistico=p50".format(id_corrida)
    ).json()
    assert len(ligera["valores"]) == len(ligera["ids_celdas"])
    assert ligera["escala"]["unidad"] == "mm/dia"

    gj = cliente.get(
        "/api/corrida/{}/capa?variable=lluvia&dia=1&geojson=true".format(id_corrida)
    ).json()
    assert gj["type"] == "FeatureCollection"
    assert "lluvia" in gj["features"][0]["properties"]


def test_todas_las_variables_responden(cliente, id_corrida):
    for var in ("lluvia", "tmax", "tmin", "humedad_suelo", "escurrimiento", "et0"):
        r = cliente.get("/api/corrida/{}/capa?variable={}".format(id_corrida, var))
        assert r.status_code == 200, var
        assert r.json()["variable"] == var


def test_probabilidad_y_riesgo(cliente, id_corrida):
    p = cliente.get(
        "/api/corrida/{}/probabilidad?variable=lluvia&umbral=20&ventana_dias=3"
        .format(id_corrida)
    ).json()
    assert all(v is None or 0.0 <= v <= 1.0 for v in p["valores"])
    assert p["modo"] == "acumulado"

    r = cliente.get(
        "/api/corrida/{}/riesgo?ventana_dias=3&umbral_mm=50".format(id_corrida)
    ).json()
    # -1 es "no aplica" (mar); 0 a 3 son las categorias de alerta.
    assert all(-1 <= k <= 3 for k in r["categoria"])
    assert -1 in r["categoria"], "el mar debe salir como no aplica"
    assert "P(escurrimiento" in r["escala"]["etiqueta"]
    assert len(r["escala"]["categorias"]) == 4
    assert r["escala"]["categoria_sin_dominio"]["valor"] == -1


def test_serie_de_una_celda(cliente, id_corrida):
    j = cliente.get(
        "/api/corrida/{}/celda/OT0.0.0".format(id_corrida)
    ).json()
    assert j["id_celda"] == "OT0.0.0"
    assert len(j["fechas"]) == 7
    lluvia = j["variables"]["lluvia"]
    assert len(lluvia["p50"]) == 7
    assert all(a <= b + 1e-6 for a, b in zip(lluvia["p10"], lluvia["p90"]))
    assert j["geografia"]["lat"] == pytest.approx(19.1704, abs=0.01)
    assert len(lluvia["miembros_muestra"]) <= 20


def test_errores_de_capa(cliente, id_corrida):
    assert cliente.get(
        "/api/corrida/{}/capa?variable=inventada".format(id_corrida)
    ).status_code == 400
    assert cliente.get(
        "/api/corrida/{}/capa?dia=999".format(id_corrida)
    ).status_code == 400
    assert cliente.get(
        "/api/corrida/{}/capa?estadistico=mediana".format(id_corrida)
    ).status_code == 400
    assert cliente.get("/api/corrida/inexistente/capa").status_code == 404
    assert cliente.get(
        "/api/corrida/{}/celda/OT0.999.999".format(id_corrida)
    ).status_code == 404


# --- asimilacion -----------------------------------------------------------


def test_asimilacion_sintetica(cliente):
    j = cliente.post("/api/asimilar", json={
        "fecha": "2026-09-14", "nivel": 0, "sintetica": True,
        "miembros": 60, "semilla": 20261114,
    }).json()
    d = j["diagnostico"]
    assert "sintetico" in d["fuente"]
    assert d["celdas_observadas"] > 0
    assert 0.0 < d["ganancia_media"] < 1.0
    assert j["id_asimilacion"].startswith("asim-")
    assert len(j["humedad_posterior"]) == len(j["ids_celdas"])


def test_asimilacion_por_celda(cliente):
    malla = cliente.get("/api/malla").json()
    tierra = [f["properties"]["id"] for f in malla["features"]
              if f["properties"]["es_tierra"]][:12]
    j = cliente.post("/api/asimilar", json={
        "fecha": "2026-09-14", "por_celda": {cid: 0.25 for cid in tierra},
        "miembros": 60, "semilla": 7,
    }).json()
    assert j["diagnostico"]["celdas_observadas"] == 12
    # La posterior quedo entre la previa y la observacion.
    idx = j["ids_celdas"].index(tierra[0])
    previa, post = j["humedad_previa"][idx], j["humedad_posterior"][idx]
    assert min(previa, 0.25) <= post <= max(previa, 0.25)


def test_asimilacion_por_puntos(cliente):
    malla = cliente.get("/api/malla").json()
    f = next(x for x in malla["features"] if x["properties"]["es_tierra"])
    lat, lon = f["properties"]["lat"], f["properties"]["lon"]
    j = cliente.post("/api/asimilar", json={
        "fecha": "2026-09-14",
        "puntos_lat": [lat, lat, lat], "puntos_lon": [lon, lon, lon],
        "puntos_valor": [0.2, 0.3, 0.4],
        "miembros": 60, "semilla": 7,
    }).json()
    assert j["diagnostico"]["celdas_observadas"] == 1
    idx = j["ids_celdas"].index(f["properties"]["id"])
    assert j["humedad_observada"][idx] == pytest.approx(0.3)


def test_asimilacion_volumetrica(cliente):
    malla = cliente.get("/api/malla").json()
    cid = next(x["properties"]["id"] for x in malla["features"]
               if x["properties"]["es_tierra"])
    j = cliente.post("/api/asimilar", json={
        "fecha": "2026-09-14", "por_celda": {cid: 0.25},
        "unidad": "volumetrica", "textura": "franco",
        "miembros": 60, "semilla": 7,
    }).json()
    idx = j["ids_celdas"].index(cid)
    # (0.25 - 0.078) / (0.43 - 0.078) = 0.4886
    assert j["humedad_observada"][idx] == pytest.approx(0.4886, abs=1e-3)


def test_el_pronostico_usa_la_asimilacion(cliente):
    asim = cliente.post("/api/asimilar", json={
        "fecha": "2026-09-14", "sintetica": True, "miembros": 60, "semilla": 5,
    }).json()["id_asimilacion"]
    j = cliente.post("/api/pronostico", json={
        "fecha_inicio": "2026-09-15", "dias": 5, "miembros": 60,
        "semilla": 20261114, "id_asimilacion": asim,
    }).json()
    assert j["resumen"]["asimilacion_aplicada"] is True
    assert j["aviso"] is None


def test_avisa_si_los_miembros_no_coinciden(cliente):
    """No se puede conservar la estructura del ensamble asimilado si el
    pronostico pide otro numero de miembros: hay que decirlo, no callarlo."""
    asim = cliente.post("/api/asimilar", json={
        "fecha": "2026-09-14", "sintetica": True, "miembros": 60, "semilla": 5,
    }).json()["id_asimilacion"]
    j = cliente.post("/api/pronostico", json={
        "fecha_inicio": "2026-09-15", "dias": 5, "miembros": 30,
        "semilla": 1, "id_asimilacion": asim,
    }).json()
    assert j["aviso"] is not None
    assert "media" in j["aviso"]


def test_errores_de_asimilacion(cliente):
    assert cliente.post("/api/asimilar", json={"nivel": 0}).status_code == 400
    assert cliente.post("/api/asimilar", json={
        "por_celda": {"OT0.999.999": 0.5},
    }).status_code == 400
    assert cliente.post("/api/asimilar", json={
        "puntos_lat": [19.0], "puntos_lon": [-96.0, -96.1], "puntos_valor": [0.3],
    }).status_code == 400
    assert cliente.post("/api/pronostico", json={
        "id_asimilacion": "no-existe",
    }).status_code == 404


def test_asimilacion_y_pronostico_de_niveles_distintos_choca(cliente):
    asim = cliente.post("/api/asimilar", json={
        "fecha": "2026-09-14", "nivel": 0, "sintetica": True,
        "miembros": 40, "semilla": 3,
    }).json()["id_asimilacion"]
    r = cliente.post("/api/pronostico", json={
        "nivel": 1, "miembros": 40, "dias": 3, "id_asimilacion": asim,
    })
    assert r.status_code == 409
