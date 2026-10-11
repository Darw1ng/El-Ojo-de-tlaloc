"""API HTTP de El Ojo de Tlaloc.

Patron de uso desde el front
----------------------------
    1. GET  /api/malla                  una vez: la geometria de los hexagonos
    2. POST /api/pronostico             corre el ensamble -> id_corrida
    3. GET  /api/corrida/{id}/capa      una capa por dia/variable -> se colorea
    4. GET  /api/corrida/{id}/celda/{c} serie con bandas para el panel lateral

La malla se pide una sola vez porque no cambia; las capas se piden por dia y
traen solo los valores, no la geometria. Asi mover la barra de tiempo cuesta
unos KB y no un GeoJSON completo.

Las corridas viven en memoria con un tope LRU. Para el hackathon alcanza; en
produccion esto va a Redis o a archivos en disco, y el id de corrida se vuelve
la llave de cache (es deterministico si se fija la semilla).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
from collections import OrderedDict

import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .. import __version__
from ..asimilacion import (
    ObservacionHumedad,
    agregar_a_malla,
    asimilar,
    observacion_sintetica,
    volumetrica_a_saturacion,
)
from ..climatologia import Climatologia, MESES
from ..config import (
    AREA_VERACRUZ,
    CENTRO_LAT,
    CENTRO_LON,
    MAX_MEMORIA_ENSAMBLE_MB,
    N_ANCHO_DEFECTO,
    UMBRALES_LLUVIA_MM,
    ZOOM_OSM,
)
from ..ensamble import (
    ESCALAS,
    ESTADISTICOS,
    capa,
    probabilidad_umbral,
    resumen_dominio,
    riesgo,
    serie_celda,
)
from ..malla import MallaHexagonal
from ..modelo import ParametrosModelo, SimuladorEstocastico
from .esquemas import PeticionAsimilacion, PeticionPronostico

#: Tope de corridas guardadas en memoria.
MAX_CORRIDAS = 8

#: Variables que acepta la API (las del modelo).
VARIABLES = tuple(ESCALAS.keys() - {"probabilidad"})


class Estado:
    """Caches del proceso: mallas, simuladores y corridas."""

    def __init__(self) -> None:
        self.mallas: dict[int, MallaHexagonal] = {}
        self.simuladores: dict[int, SimuladorEstocastico] = {}
        self.corridas: OrderedDict = OrderedDict()
        self.asimilaciones: OrderedDict = OrderedDict()
        self.expedientes: dict = {}

    def malla(self, nivel: int) -> MallaHexagonal:
        if nivel not in self.mallas:
            self.mallas[nivel] = MallaHexagonal(
                bbox=AREA_VERACRUZ,
                n_ancho=N_ANCHO_DEFECTO * (2 ** nivel),
                nivel=nivel,
            )
        return self.mallas[nivel]

    def simulador(self, nivel: int) -> SimuladorEstocastico:
        """El simulador cachea el Cholesky de la covarianza espacial, que es
        lo caro de construir. Por eso se reutiliza entre peticiones."""
        if nivel not in self.simuladores:
            m = self.malla(nivel)
            self.simuladores[nivel] = SimuladorEstocastico(
                m, Climatologia.sintetica(m), ParametrosModelo()
            )
        return self.simuladores[nivel]

    def expediente(self, nivel: int, usar_osm: bool = True,
                   usar_power: bool = True, refrescar: bool = False):
        """Expediente de fusion, cacheado por (nivel, fuentes).

        Construirlo baja de Overpass y de POWER, asi que se cachea en el
        proceso; las fuentes ademas cachean en disco. Sin esto, cada peticion
        le pegaria a dos servicios publicos gratuitos.
        """
        from ..expediente import construir_expediente

        clave = (nivel, bool(usar_osm), bool(usar_power))
        if refrescar or clave not in self.expedientes:
            malla = self.malla(nivel)
            self.expedientes[clave] = construir_expediente(
                malla, clima=self.simulador(nivel).clima,
                usar_osm=usar_osm, usar_power=usar_power,
            )
        return self.expedientes[clave]

    def guardar_corrida(self, id_corrida: str, paquete: dict) -> None:
        self.corridas[id_corrida] = paquete
        self.corridas.move_to_end(id_corrida)
        while len(self.corridas) > MAX_CORRIDAS:
            self.corridas.popitem(last=False)

    def corrida(self, id_corrida: str) -> dict:
        if id_corrida not in self.corridas:
            raise HTTPException(
                status_code=404,
                detail="corrida '{}' no encontrada o ya expiro; vuelve a "
                       "llamar POST /api/pronostico".format(id_corrida),
            )
        self.corridas.move_to_end(id_corrida)
        return self.corridas[id_corrida]


def crear_app() -> FastAPI:
    estado = Estado()
    app = FastAPI(
        title="El Ojo de Tlaloc",
        version=__version__,
        description=(
            "Prediccion estocastica de clima sobre malla hexagonal, con "
            "asimilacion de humedad de suelo observada por radar (NISAR). "
            "NASA Space Apps Challenge 2026, reto Dancing with the SARs."
        ),
    )

    # El front corre en otro puerto durante el desarrollo. En produccion hay
    # que cerrar esto al dominio real.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    # --- basicos ----------------------------------------------------------

    @app.get("/salud", tags=["sistema"])
    def salud():
        return {
            "ok": True,
            "version": __version__,
            "corridas_en_memoria": len(estado.corridas),
        }

    @app.get("/api/area", tags=["sistema"])
    def area():
        """Area de interes y su origen, para que el front centre el mapa."""
        return {
            "centro": {"lat": CENTRO_LAT, "lon": CENTRO_LON},
            "zoom_osm": ZOOM_OSM,
            "bbox": {
                "lat_min": AREA_VERACRUZ.lat_min,
                "lat_max": AREA_VERACRUZ.lat_max,
                "lon_min": AREA_VERACRUZ.lon_min,
                "lon_max": AREA_VERACRUZ.lon_max,
            },
            "enlace_osm": "https://www.openstreetmap.org/#map={}/{}/{}".format(
                ZOOM_OSM, CENTRO_LAT, CENTRO_LON
            ),
            "mosaico_sugerido": (
                "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
            ),
            "atribucion": "(c) OpenStreetMap contributors (ODbL)",
        }

    @app.get("/api/escalas", tags=["sistema"])
    def escalas():
        """Escalas de color sugeridas por variable.

        Existe para que dos capas distintas sean comparables: si el front
        inventa el rango de cada una, el usuario no puede comparar dias.
        """
        return {
            "escalas": ESCALAS,
            "estadisticos": list(ESTADISTICOS),
            "umbrales_lluvia_mm": list(UMBRALES_LLUVIA_MM),
        }

    # --- malla y climatologia ---------------------------------------------

    @app.get("/api/malla", tags=["malla"])
    def obtener_malla(
        nivel: int = Query(0, ge=0, le=2, description="0 = escala 1:16"),
        incluir_geografia: bool = Query(
            True, description="Agrega elevacion, tierra/mar y distancia a la costa."
        ),
    ):
        """GeoJSON de los hexagonos. Se pide una sola vez por nivel."""
        m = estado.malla(nivel)
        props = None
        if incluir_geografia:
            c = estado.simulador(nivel).clima
            props = {
                "elevacion_m": c.elevacion_m,
                "es_tierra": c.es_tierra.astype(int),
                "dist_costa_km": c.dist_costa_km,
                "capacidad_suelo_mm": c.capacidad_suelo_mm,
            }
        return m.a_geojson(props)

    @app.get("/api/climatologia", tags=["malla"])
    def obtener_climatologia(
        nivel: int = Query(0, ge=0, le=2),
        mes: int = Query(0, ge=0, le=12,
                         description="1-12; 0 devuelve el resumen anual."),
    ):
        """Climatologia por celda: con que se compara el pronostico."""
        m = estado.malla(nivel)
        c = estado.simulador(nivel).clima
        if mes == 0:
            return {
                "resumen": c.resumen(),
                "meses": list(MESES),
                "nota": "Climatologia sintetica derivada de las normales del "
                        "puerto de Veracruz mas gradientes. Ver "
                        "docs/05-datos-y-nisar.md.",
            }
        return {
            "mes": mes,
            "nombre_mes": MESES[mes - 1],
            "valores": {
                "prob_lluvia": _lista(c.prob_lluvia[:, mes - 1]),
                "lluvia_mensual_mm": _lista(c.lluvia_mensual_esperada(mes)),
                "tmax_media_c": _lista(c.tmax_media[:, mes - 1]),
                "tmin_media_c": _lista(c.tmin_media[:, mes - 1]),
            },
            "ids_celdas": list(m.ids),
        }

    # --- pronostico -------------------------------------------------------

    @app.post("/api/pronostico", tags=["pronostico"])
    def correr_pronostico(peticion: PeticionPronostico):
        """Corre el ensamble y devuelve el id para pedir capas.

        El calculo es sincrono porque con los tamanos por defecto tarda menos
        de un segundo. Si se sube a 1000 miembros y 60 dias conviene pasarlo a
        una tarea en segundo plano.
        """
        sim = estado.simulador(peticion.nivel)

        mb = sim.memoria_estimada_mb(peticion.dias, peticion.miembros)
        if mb > MAX_MEMORIA_ENSAMBLE_MB:
            raise HTTPException(
                status_code=413,
                detail=(
                    "la peticion necesita {:.0f} MB y el tope es {} MB; "
                    "baja miembros, dias o nivel".format(mb, MAX_MEMORIA_ENSAMBLE_MB)
                ),
            )

        humedad = peticion.humedad_inicial
        aviso = None
        if peticion.id_asimilacion:
            if peticion.id_asimilacion not in estado.asimilaciones:
                raise HTTPException(
                    status_code=404,
                    detail="id_asimilacion no encontrado; vuelve a llamar "
                           "POST /api/asimilar",
                )
            guardado = estado.asimilaciones[peticion.id_asimilacion]
            if guardado["nivel"] != peticion.nivel:
                raise HTTPException(
                    status_code=409,
                    detail="la asimilacion es del nivel {} y el pronostico "
                           "del {}".format(guardado["nivel"], peticion.nivel),
                )
            humedad = guardado["estado_suelo"]
            if humedad.shape[0] != peticion.miembros:
                # Se reconcilian los tamanos promediando o repitiendo: no es
                # ideal (pierde la estructura del ensamble asimilado) y por eso
                # se avisa en la respuesta.
                humedad = np.nanmean(humedad, axis=0)
                aviso = (
                    "la asimilacion se hizo con {} miembros y el pronostico "
                    "pide {}: se uso la media del estado asimilado. Para "
                    "conservar el ensamble, corre los dos con el mismo "
                    "numero de miembros.".format(
                        guardado["estado_suelo"].shape[0], peticion.miembros
                    )
                )

        t0 = time.perf_counter()
        resultado = sim.simular(
            fecha_inicio=peticion.fecha_inicio,
            n_dias=peticion.dias,
            n_miembros=peticion.miembros,
            semilla=peticion.semilla,
            humedad_inicial=humedad,
        )
        segundos = time.perf_counter() - t0

        id_corrida = _id_corrida(peticion, resultado.semilla)
        estado.guardar_corrida(
            id_corrida,
            {
                "resultado": resultado,
                "nivel": peticion.nivel,
                "creada": dt.datetime.now().isoformat(timespec="seconds"),
            },
        )

        clima = sim.clima
        return {
            "id_corrida": id_corrida,
            "aviso": aviso,
            "resumen": {
                **resumen_dominio(resultado, clima.es_tierra),
                "nivel": peticion.nivel,
                "escala": "1:{}".format(sim.malla.n_ancho),
                "segundos_calculo": round(segundos, 3),
                "memoria_mb": round(mb, 1),
                "fechas": resultado.fechas,
                "asimilacion_aplicada": bool(peticion.id_asimilacion),
            },
            "malla": sim.malla.metadata,
        }

    @app.get("/api/corrida/{id_corrida}/capa", tags=["pronostico"])
    def obtener_capa(
        id_corrida: str,
        variable: str = Query("lluvia"),
        dia: int = Query(0, ge=0),
        estadistico: str = Query("p50"),
        geojson: bool = Query(
            False,
            description="true devuelve GeoJSON completo; false solo los "
                        "valores alineados con los ids de la malla (mas ligero).",
        ),
    ):
        """Una capa para colorear: un valor por celda."""
        paquete = estado.corrida(id_corrida)
        resultado = paquete["resultado"]
        _valida_variable(variable)
        try:
            salida = capa(resultado, variable, dia, estadistico)
        except (IndexError, ValueError, KeyError) as e:
            raise HTTPException(status_code=400, detail=str(e)) from None

        valores = salida.pop("valores")
        if geojson:
            m = estado.malla(paquete["nivel"])
            gj = m.a_geojson({variable: valores})
            gj["capa"] = salida
            return gj
        return {**salida, "ids_celdas": resultado.ids_celdas,
                "valores": _lista(valores)}

    @app.get("/api/corrida/{id_corrida}/probabilidad", tags=["pronostico"])
    def obtener_probabilidad(
        id_corrida: str,
        variable: str = Query("lluvia"),
        dia: int = Query(0, ge=0),
        umbral: float = Query(20.0, description="En unidades de la variable."),
        ventana_dias: int = Query(1, ge=1, le=30),
    ):
        """P(variable > umbral) por celda. Es la salida que justifica el modelo."""
        paquete = estado.corrida(id_corrida)
        resultado = paquete["resultado"]
        _valida_variable(variable)
        try:
            salida = probabilidad_umbral(
                resultado, variable, dia, umbral, ventana_dias
            )
        except (IndexError, ValueError, KeyError) as e:
            raise HTTPException(status_code=400, detail=str(e)) from None
        valores = salida.pop("valores")
        return {**salida, "ids_celdas": resultado.ids_celdas,
                "valores": _lista(valores)}

    @app.get("/api/corrida/{id_corrida}/riesgo", tags=["pronostico"])
    def obtener_riesgo(
        id_corrida: str,
        dia: int = Query(0, ge=0),
        ventana_dias: int = Query(3, ge=1, le=10),
        umbral_mm: float = Query(60.0, gt=0.0),
    ):
        """Capa de alerta por escurrimiento acumulado."""
        paquete = estado.corrida(id_corrida)
        resultado = paquete["resultado"]
        try:
            salida = riesgo(resultado, dia, ventana_dias, umbral_mm)
        except (IndexError, ValueError) as e:
            raise HTTPException(status_code=400, detail=str(e)) from None
        valores = salida.pop("valores")
        categoria = salida.pop("categoria")
        return {
            **salida,
            "ids_celdas": resultado.ids_celdas,
            "valores": _lista(valores),
            "categoria": [int(k) for k in categoria],
        }

    @app.get("/api/corrida/{id_corrida}/celda/{id_celda}", tags=["pronostico"])
    def obtener_celda(id_corrida: str, id_celda: str):
        """Serie temporal con bandas de incertidumbre para una celda."""
        paquete = estado.corrida(id_corrida)
        resultado = paquete["resultado"]
        m = estado.malla(paquete["nivel"])
        try:
            i = m.indice(id_celda)
        except KeyError:
            raise HTTPException(
                status_code=404,
                detail="la celda '{}' no existe en el nivel {}".format(
                    id_celda, paquete["nivel"]
                ),
            ) from None
        serie = serie_celda(resultado, i)
        c = estado.simulador(paquete["nivel"]).clima
        serie["geografia"] = {
            "lat": round(float(m.lat[i]), 6),
            "lon": round(float(m.lon[i]), 6),
            "elevacion_m": round(float(c.elevacion_m[i]), 1),
            "es_tierra": bool(c.es_tierra[i]),
            "dist_costa_km": round(float(c.dist_costa_km[i]), 2),
        }
        return json.loads(json.dumps(serie, default=_json_numpy))

    # --- asimilacion ------------------------------------------------------

    @app.post("/api/asimilar", tags=["asimilacion"])
    def asimilar_observacion(peticion: PeticionAsimilacion):
        """Corrige el estado del suelo con una observacion de humedad.

        Devuelve el diagnostico (cuanto movio el dato al modelo) y un
        id_asimilacion para pasarlo a POST /api/pronostico.
        """
        sim = estado.simulador(peticion.nivel)
        m = sim.malla
        clima = sim.clima
        rng = np.random.default_rng(peticion.semilla)

        # Estado previo del suelo: un dia de modelo para tener el ensamble
        # con su dispersion propia.
        previo = sim.simular(
            fecha_inicio=peticion.fecha,
            n_dias=1,
            n_miembros=peticion.miembros,
            semilla=peticion.semilla,
        ).humedad_suelo[:, 0, :].astype(float)

        if peticion.sintetica:
            obs = observacion_sintetica(
                m, clima, peticion.fecha, semilla=peticion.semilla
            )
        elif peticion.por_celda:
            valores = np.full(m.n_celdas, np.nan)
            desconocidas = []
            for cid, v in peticion.por_celda.items():
                try:
                    valores[m.indice(cid)] = v
                except KeyError:
                    desconocidas.append(cid)
            if desconocidas:
                raise HTTPException(
                    status_code=400,
                    detail="celdas desconocidas en el nivel {}: {}".format(
                        peticion.nivel, ", ".join(desconocidas[:5])
                    ),
                )
            if peticion.unidad == "volumetrica":
                finito = np.isfinite(valores)
                valores[finito] = volumetrica_a_saturacion(
                    valores[finito], peticion.textura
                )
            obs = ObservacionHumedad(
                valores=valores, sigma=peticion.sigma,
                fecha=str(peticion.fecha), fuente="por_celda",
            )
        elif peticion.puntos_lat and peticion.puntos_lon and peticion.puntos_valor:
            if not (len(peticion.puntos_lat) == len(peticion.puntos_lon)
                    == len(peticion.puntos_valor)):
                raise HTTPException(
                    status_code=400,
                    detail="puntos_lat, puntos_lon y puntos_valor deben tener "
                           "el mismo largo",
                )
            v = np.asarray(peticion.puntos_valor, dtype=float)
            if peticion.unidad == "volumetrica":
                v = volumetrica_a_saturacion(v, peticion.textura)
            promedios, conteo = agregar_a_malla(
                m, peticion.puntos_lat, peticion.puntos_lon, v
            )
            obs = ObservacionHumedad(
                valores=promedios, sigma=peticion.sigma,
                fecha=str(peticion.fecha), fuente="puntos",
            )
        else:
            raise HTTPException(
                status_code=400,
                detail="manda por_celda, los tres arrays de puntos, o "
                       "sintetica=true",
            )

        try:
            res = asimilar(previo, obs, rng=rng)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None

        id_asim = "asim-{}-{}".format(
            peticion.fecha.isoformat(),
            hashlib.sha1(
                "{}{}{}".format(obs.fuente, obs.n_observadas, peticion.semilla)
                .encode()
            ).hexdigest()[:8],
        )
        estado.asimilaciones[id_asim] = {
            "nivel": peticion.nivel,
            "estado_suelo": res["ensamble"],
            "creada": dt.datetime.now().isoformat(timespec="seconds"),
        }
        while len(estado.asimilaciones) > MAX_CORRIDAS:
            estado.asimilaciones.popitem(last=False)

        return {
            "id_asimilacion": id_asim,
            "diagnostico": res["diagnostico"],
            "ids_celdas": list(m.ids),
            "humedad_previa": _lista(np.nanmean(previo, axis=0)),
            "humedad_observada": _lista(obs.valores),
            "humedad_posterior": _lista(np.nanmean(res["ensamble"], axis=0)),
        }

    # Rutas de la plataforma de fusion (expediente, sondeo, analisis).
    from .rutas_fusion import registrar as registrar_fusion

    registrar_fusion(app, estado)

    return app


# --- utilidades ------------------------------------------------------------


def _lista(a) -> list:
    """Array de numpy -> lista JSON, con NaN como null y 4 decimales."""
    a = np.asarray(a, dtype=float)
    return [None if not np.isfinite(v) else round(float(v), 4) for v in a]


def _json_numpy(o):
    if isinstance(o, np.ndarray):
        return [None if not np.isfinite(v) else round(float(v), 4)
                for v in o.ravel()] if o.ndim == 1 else [
            _json_numpy(x) for x in o
        ]
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(float(o)) else round(float(o), 4)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    raise TypeError("no serializable: {}".format(type(o)))


def _valida_variable(variable: str) -> None:
    if variable not in VARIABLES:
        raise HTTPException(
            status_code=400,
            detail="variable '{}' invalida; validas: {}".format(
                variable, ", ".join(sorted(VARIABLES))
            ),
        )


def _id_corrida(peticion, semilla: int) -> str:
    """Id deterministico: la misma peticion con la misma semilla da el mismo id.

    Eso permite cachear del lado del front y reproducir una vista exacta desde
    una URL compartida.
    """
    crudo = "{}|{}|{}|{}|{}|{}".format(
        peticion.fecha_inicio, peticion.dias, peticion.miembros,
        peticion.nivel, semilla, peticion.id_asimilacion or "",
    )
    return "{}-{}".format(
        peticion.fecha_inicio.isoformat(),
        hashlib.sha1(crudo.encode()).hexdigest()[:10],
    )


#: Instancia para `uvicorn ojo_tlaloc.api.app:app`.
app = crear_app()
