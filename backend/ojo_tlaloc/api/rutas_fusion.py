"""Rutas de la plataforma de fusion: expediente, sondeo y analisis derivados.

Van en un modulo aparte de `app.py` para que la capa de pronostico y la de
fusion se puedan leer por separado. Todas cuelgan de la misma app y del mismo
estado.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
from fastapi import Body, HTTPException, Query

from ..analisis import (
    aptitud_constructiva,
    exposicion_por_riesgo,
    pendiente_desde_elevacion,
    resumen_exposicion,
    ventanas_de_obra,
)
from ..analisis.ventanas import ACTIVIDADES, calendario_celda
from ..climatologia import Climatologia
from ..ensamble import probabilidad_umbral, riesgo
from ..expediente import construir_expediente
from ..fuentes.base import ErrorFuente
from ..fuentes.sondeo import (
    calibrar_probit,
    interpretar_indices,
    leer_sondeo,
    media_campo_latente,
)
from ..modelo import ParametrosModelo, SimuladorEstocastico


def registrar(app, estado) -> None:
    """Cuelga las rutas de fusion en la app."""

    # --- expediente -------------------------------------------------------

    @app.get("/api/expediente", tags=["fusion"])
    def obtener_expediente(
        nivel: int = Query(0, ge=0, le=2),
        usar_osm: bool = Query(True, description="OpenStreetMap via Overpass"),
        usar_power: bool = Query(True, description="NASA POWER"),
        refrescar: bool = Query(False, description="ignora el cache del proceso"),
    ):
        """Resumen del expediente: que capas hay, de donde vienen, que falta.

        Es la radiografia del sistema: cuantas capas son observadas, cuantas
        sinteticas, que advertencias declararon las fuentes y que atribuciones
        hay que mostrar.
        """
        exp = estado.expediente(nivel, usar_osm, usar_power, refrescar)
        return {
            "resumen": exp.resumen(),
            "advertencias": exp.advertencias,
            "faltantes": exp.faltantes(),
            "procedencias": exp.procedencias(),
        }

    @app.get("/api/expediente/capa", tags=["fusion"])
    def obtener_capa_expediente(
        nombre: str = Query(..., description="nombre de la capa"),
        nivel: int = Query(0, ge=0, le=2),
        geojson: bool = Query(False),
    ):
        """Una capa del expediente, con su procedencia."""
        exp = estado.expediente(nivel)
        if not exp.tiene(nombre):
            raise HTTPException(
                status_code=404,
                detail="el expediente no tiene '{}'. Tiene: {}".format(
                    nombre, ", ".join(sorted(exp.capas))
                ),
            )
        capa = exp.capas[nombre]
        if geojson:
            return exp.a_geojson([nombre])
        return {
            "nombre": nombre,
            "unidad": capa.unidad,
            "procedencia": capa.procedencia.a_dict(),
            "resumen": capa.resumen(),
            "ids_celdas": list(exp.malla.ids),
            "valores": _lista(capa.valores),
        }

    @app.get("/api/expediente/celda/{id_celda}", tags=["fusion"])
    def obtener_celda_expediente(id_celda: str, nivel: int = Query(0, ge=0, le=2)):
        """Todo lo que se sabe de un hexagono, agrupado por familia de dato."""
        exp = estado.expediente(nivel)
        try:
            return exp.celda(id_celda)
        except KeyError:
            raise HTTPException(
                status_code=404,
                detail="la celda '{}' no existe en el nivel {}".format(
                    id_celda, nivel),
            ) from None

    @app.get("/api/expediente/atribuciones", tags=["fusion"])
    def obtener_atribuciones(nivel: int = Query(0, ge=0, le=2)):
        """Atribuciones que la interfaz DEBE mostrar.

        No es cortesia: la ODbL de OpenStreetMap lo exige. Si esto no se
        muestra, se incumple la licencia.
        """
        exp = estado.expediente(nivel)
        return {
            "atribuciones": exp.atribuciones(),
            "capas_sinteticas": exp.capas_sinteticas(),
            "nota": ("las capas sinteticas no son dato observado y hay que "
                     "rotularlas como tales en la interfaz"),
        }

    # --- sondeo -----------------------------------------------------------

    @app.post("/api/sondeo", tags=["fusion"])
    def analizar_sondeo(
        texto: str = Body(..., media_type="text/plain",
                          description="texto del sondeo: tabla de Wyoming/IGRA "
                                      "o CSV del globo propio"),
    ):
        """Lee un perfil atmosferico y devuelve sus indices y la mu del modelo.

        Acepta los dos formatos sin que haya que decirle cual es. La `mu` que
        devuelve se pasa a POST /api/pronostico para que el pronostico deje de
        ser climatologico y pase a ser del dia.
        """
        try:
            perfil = leer_sondeo(texto)
        except (ErrorFuente, ValueError) as e:
            raise HTTPException(status_code=400, detail=str(e)) from None

        mu = media_campo_latente(perfil.indices)
        return {
            "perfil": perfil.resumen(),
            "mu_campo_latente": mu,
            "procedencia": perfil.procedencia().a_dict(),
            "nota": ("los coeficientes del probit son PROVISIONALES hasta "
                     "calibrarlos con sondeos historicos y lluvia observada; "
                     "ver POST /api/sondeo/calibrar"),
        }

    @app.post("/api/sondeo/calibrar", tags=["fusion"])
    def calibrar_sondeo(cuerpo: dict = Body(...)):
        """Estima los coeficientes del probit con sondeos historicos.

        Cuerpo: {"indices": [{...}, ...], "ocurrencia": [0, 1, ...]}

        Es lo que convierte el globo de anecdota a dato: con cien sondeos y su
        lluvia observada, los coeficientes dejan de ser supuestos y traen
        error estandar.
        """
        indices = cuerpo.get("indices")
        ocurrencia = cuerpo.get("ocurrencia")
        if not isinstance(indices, list) or not isinstance(ocurrencia, list):
            raise HTTPException(
                status_code=400,
                detail="manda 'indices' (lista de dicts) y 'ocurrencia' "
                       "(lista binaria del mismo largo)",
            )
        try:
            return calibrar_probit(indices, ocurrencia)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None

    # --- analisis derivados ----------------------------------------------

    @app.get("/api/aptitud", tags=["analisis"])
    def obtener_aptitud(
        nivel: int = Query(0, ge=0, le=2),
        id_corrida: str | None = Query(
            None, description="corrida para el criterio de inundabilidad"),
        dia: int = Query(0, ge=0),
        ventana_dias: int = Query(3, ge=1, le=10),
        umbral_mm: float = Query(60.0, gt=0.0),
    ):
        """Aptitud constructiva por hexagono. Tamiz de terreno, no dictamen."""
        exp = estado.expediente(nivel)
        prob = None
        if id_corrida:
            paquete = estado.corrida(id_corrida)
            prob = riesgo(paquete["resultado"], dia, ventana_dias,
                          umbral_mm)["valores"]
        resultado = aptitud_constructiva(exp.malla, exp, prob)
        return {
            "ids_celdas": list(exp.malla.ids),
            "aptitud": _lista(resultado["aptitud"]),
            "criterios": {k: _lista(v) for k, v in resultado["criterios"].items()},
            "pesos_usados": resultado["pesos_usados"],
            "detalle_criterios": resultado["detalle_criterios"],
            "advertencias": resultado["advertencias"],
            "usa_inundabilidad": prob is not None,
        }

    @app.get("/api/pendiente", tags=["analisis"])
    def obtener_pendiente(nivel: int = Query(0, ge=0, le=2)):
        """Pendiente aproximada por celda, de los 6 vecinos del hexagono."""
        exp = estado.expediente(nivel)
        r = pendiente_desde_elevacion(exp.malla, exp.valores("elevacion_m"))
        return {
            "ids_celdas": list(exp.malla.ids),
            "pendiente_max_grados": _lista(r["pendiente_max_grados"]),
            "pendiente_media_grados": _lista(r["pendiente_media_grados"]),
            "paso_m": round(r["paso_m"], 1),
            "advertencia": r["advertencia"],
            "elevacion_sintetica": "elevacion_m" in exp.capas_sinteticas(),
        }

    @app.get("/api/corrida/{id_corrida}/exposicion", tags=["analisis"])
    def obtener_exposicion(
        id_corrida: str,
        nivel: int = Query(0, ge=0, le=2),
        dia: int = Query(0, ge=0),
        ventana_dias: int = Query(3, ge=1, le=10),
        umbral_mm: float = Query(60.0, gt=0.0),
        corte: float = Query(0.3, ge=0.0, le=1.0),
    ):
        """Quien y que esta en las celdas de riesgo.

        Convierte un mapa de probabilidad en una lista de afectados. Es el
        cruce del pronostico con los datos de OpenStreetMap.
        """
        paquete = estado.corrida(id_corrida)
        exp = estado.expediente(nivel)
        if paquete["nivel"] != nivel:
            raise HTTPException(
                status_code=409,
                detail="la corrida es del nivel {} y pediste el {}".format(
                    paquete["nivel"], nivel),
            )
        prob = riesgo(paquete["resultado"], dia, ventana_dias, umbral_mm)["valores"]
        r = exposicion_por_riesgo(exp.malla, exp, prob, corte)
        return {
            "resumen": resumen_exposicion(r),
            "corte": r["corte"],
            "corte_inalcanzable": r["corte_inalcanzable"],
            "probabilidad_maxima_dominio": r["probabilidad_maxima_dominio"],
            "celdas_en_riesgo": r["celdas_en_riesgo"],
            "elementos": r["elementos"],
            "celdas_prioritarias": r["celdas_prioritarias"],
            "ids_celdas": list(exp.malla.ids),
            "indice_exposicion": _lista(r["indice_exposicion"]),
            "advertencias": r["advertencias"],
        }

    @app.get("/api/corrida/{id_corrida}/ventanas", tags=["analisis"])
    def obtener_ventanas(
        id_corrida: str,
        actividad: str | None = Query(
            None, description="una sola actividad; vacio devuelve todas"),
        id_celda: str | None = Query(
            None, description="calendario de una celda en lugar del mapa"),
    ):
        """Ventanas de obra: P(dia trabajable) por celda, dia y actividad."""
        paquete = estado.corrida(id_corrida)
        resultado = paquete["resultado"]
        nivel = paquete["nivel"]
        clima = estado.simulador(nivel).clima

        actividades = None
        if actividad:
            if actividad not in ACTIVIDADES:
                raise HTTPException(
                    status_code=400,
                    detail="actividad desconocida '{}'. Validas: {}".format(
                        actividad, ", ".join(sorted(ACTIVIDADES))),
                )
            actividades = [actividad]

        v = ventanas_de_obra(resultado, actividades, es_tierra=clima.es_tierra)

        if id_celda:
            malla = estado.malla(nivel)
            try:
                i = malla.indice(id_celda)
            except KeyError:
                raise HTTPException(
                    status_code=404,
                    detail="la celda '{}' no existe".format(id_celda),
                ) from None
            salida = calendario_celda(v, i)
            salida["id_celda"] = id_celda
            salida["advertencias"] = v["advertencias"]
            return salida

        return {
            "fechas": v["fechas"],
            "horizonte_dias": v["horizonte_dias"],
            "ids_celdas": list(resultado.ids_celdas),
            "actividades": {
                nombre: {
                    "etiqueta": b["etiqueta"],
                    "razon": b["razon"],
                    "restricciones": b["restricciones"],
                    "dias_trabajables_esperados": _lista(
                        b["dias_trabajables_esperados"]),
                    "probabilidad_por_dia": [
                        _lista(b["probabilidad"][d])
                        for d in range(b["probabilidad"].shape[0])
                    ],
                }
                for nombre, b in v["actividades"].items()
            },
            "omitidas": v["omitidas"],
            "advertencias": v["advertencias"],
        }

    @app.get("/api/actividades", tags=["analisis"])
    def obtener_actividades():
        """Catalogo de actividades de obra con sus umbrales y su razon."""
        return {
            "actividades": {
                nombre: {k: v for k, v in cfg.items()}
                for nombre, cfg in ACTIVIDADES.items()
            },
            "nota": ("los umbrales son valores de referencia de practica "
                     "constructiva, no una norma; cada especificacion de obra "
                     "manda sobre esto"),
        }

    # --- pronostico con fusion -------------------------------------------

    @app.post("/api/pronostico/fusion", tags=["fusion"])
    def pronostico_con_fusion(cuerpo: dict = Body(default={})):
        """Pronostico que usa TODAS las fuentes disponibles.

        Diferencias con POST /api/pronostico:
          - la climatologia sale de NASA POWER, no de los valores sinteticos
          - el escurrimiento usa la impermeabilidad real de OpenStreetMap
          - si se manda un sondeo, el campo latente deja de tener media cero

        Cuerpo (todo opcional):
            fecha_inicio, dias, miembros, nivel, semilla
            sondeo         texto del perfil atmosferico
            usar_osm, usar_power
        """
        nivel = int(cuerpo.get("nivel", 0))
        if not 0 <= nivel <= 2:
            raise HTTPException(status_code=400, detail="nivel debe ser 0, 1 o 2")
        dias = int(cuerpo.get("dias", 14))
        miembros = int(cuerpo.get("miembros", 200))
        semilla = cuerpo.get("semilla", 20261114)
        fecha = cuerpo.get("fecha_inicio")
        try:
            fecha_inicio = (dt.date.fromisoformat(fecha) if fecha
                            else dt.date.today())
        except ValueError:
            raise HTTPException(
                status_code=400, detail="fecha_inicio debe ser YYYY-MM-DD"
            ) from None

        exp = estado.expediente(
            nivel,
            bool(cuerpo.get("usar_osm", True)),
            bool(cuerpo.get("usar_power", True)),
        )
        malla = exp.malla

        # Climatologia real si POWER respondio.
        if exp.series_climatologicas:
            clima = Climatologia.desde_normales(malla, **exp.series_climatologicas)
            origen_clima = "NASA POWER"
        else:
            clima = Climatologia.sintetica(malla)
            origen_clima = "sintetica (POWER no disponible)"

        imperm = (exp.valores("fraccion_impermeable")
                  if exp.tiene("fraccion_impermeable") else 0.0)
        par = ParametrosModelo(fraccion_impermeable=imperm)
        sim = SimuladorEstocastico(malla, clima, par)

        mb = sim.memoria_estimada_mb(dias, miembros)
        if mb > 512:
            raise HTTPException(
                status_code=413,
                detail="la peticion necesita {:.0f} MB y el tope es 512".format(mb),
            )

        # Sondeo -> mu del campo latente.
        mu_info = None
        mu = None
        texto_sondeo = cuerpo.get("sondeo")
        if texto_sondeo:
            try:
                perfil = leer_sondeo(texto_sondeo)
            except (ErrorFuente, ValueError) as e:
                raise HTTPException(status_code=400, detail=str(e)) from None
            mu_info = media_campo_latente(perfil.indices)
            mu_info["perfil"] = perfil.resumen()
            if not mu_info["confiable"]:
                # No se usa una mu derivada de un perfil con indices
                # imposibles: se devuelve el aviso y se corre climatologico.
                mu = None
            else:
                mu = mu_info["mu"]

        try:
            resultado = sim.simular(
                fecha_inicio=fecha_inicio, n_dias=dias, n_miembros=miembros,
                semilla=semilla, mu_campo=mu,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None

        id_corrida = "fusion-{}-{}".format(fecha_inicio.isoformat(),
                                           abs(hash((dias, miembros, nivel,
                                                     semilla, mu))) % 10**10)
        estado.guardar_corrida(id_corrida, {
            "resultado": resultado, "nivel": nivel,
            "creada": dt.datetime.now().isoformat(timespec="seconds"),
        })

        from ..ensamble import resumen_dominio

        return {
            "id_corrida": id_corrida,
            "fusion": {
                "climatologia": origen_clima,
                "impermeabilidad": ("OpenStreetMap"
                                    if exp.tiene("fraccion_impermeable")
                                    else "no disponible"),
                "sondeo": ("aplicado" if mu is not None else
                           ("descartado por indices fuera de rango"
                            if mu_info else "no se mando")),
                "mu_campo_latente": mu,
                "capas_en_expediente": len(exp.capas),
                "atribuciones": exp.atribuciones(),
            },
            "mu_detalle": mu_info,
            "advertencias": exp.advertencias,
            "resumen": {
                **resumen_dominio(resultado, clima.es_tierra),
                "nivel": nivel,
                "escala": "1:{}".format(malla.n_ancho),
                "fechas": resultado.fechas,
            },
        }


def _lista(a) -> list:
    a = np.asarray(a, dtype=float)
    return [None if not np.isfinite(v) else round(float(v), 4) for v in a]
