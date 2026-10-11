"""Exposicion: quien y que esta en las celdas de riesgo.

Por que esta capa cambia el proyecto
------------------------------------
Un mapa de probabilidad dice "aqui hay 60% de que escurran mas de 60 mm". Eso
es correcto y no mueve a nadie. La exposicion lo convierte en:

    "aqui hay 60% de que escurran mas de 60 mm, y en esa celda hay 4
     hospitales, 112 escuelas y 311 edificios mapeados"

Es la diferencia entre un mapa y una decision, y sale completa de cruzar el
pronostico con los datos de OpenStreetMap. Sin OSM no existe; con OSM es una
consulta.

Honestidad sobre el conteo
--------------------------
Los conteos vienen del mapeo comunitario de OSM, que en esta zona esta
incompleto: 5 603 edificios para una zona metropolitana de cerca de 900 mil
habitantes. Asi que los numeros son un **indice de exposicion relativa** —
sirven para ordenar celdas de mayor a menor— y no un censo. Comparar celdas
entre si es valido; decir "hay exactamente 112 escuelas" no lo es.
"""

from __future__ import annotations

import numpy as np

#: Capas de OSM que cuentan como elementos expuestos, con su etiqueta.
ELEMENTOS_EXPUESTOS = {
    "infraestructura_critica": "equipamientos criticos",
    "edificios": "edificios mapeados",
    "area_pisos": "m2 de construccion",
    "peso_critico": "exposicion ponderada",
}


def exposicion_por_riesgo(
    malla,
    expediente,
    probabilidad,
    corte: float = 0.3,
) -> dict:
    """Cruza una capa de probabilidad con los elementos expuestos.

    `corte` es la probabilidad a partir de la cual se considera que la celda
    esta en riesgo. Es una decision operativa, no estadistica: bajarlo
    aumenta la deteccion y las falsas alarmas. Se devuelve el corte usado para
    que la cifra se pueda reproducir.
    """
    p = np.asarray(probabilidad, dtype=float)
    if p.shape != (malla.n_celdas,):
        raise ValueError("probabilidad debe tener largo n_celdas")
    if not 0.0 <= corte <= 1.0:
        raise ValueError("el corte debe estar entre 0 y 1")

    en_riesgo = np.isfinite(p) & (p >= corte)
    totales: dict[str, dict] = {}

    for capa, etiqueta in ELEMENTOS_EXPUESTOS.items():
        if not expediente.tiene(capa):
            continue
        v = np.nan_to_num(expediente.valores(capa), nan=0.0)
        total = float(v.sum())
        expuesto = float(v[en_riesgo].sum())
        totales[capa] = {
            "etiqueta": etiqueta,
            "expuesto": round(expuesto, 1),
            "total_dominio": round(total, 1),
            "fraccion": round(expuesto / total, 4) if total > 0 else None,
        }

    # Indice de exposicion por celda: probabilidad por lo que hay expuesto.
    # Es el producto riesgo x consecuencia, que es la definicion operativa de
    # riesgo en proteccion civil.
    peso = (np.nan_to_num(expediente.valores("peso_critico"), nan=0.0)
            if expediente.tiene("peso_critico") else np.zeros(malla.n_celdas))
    construccion = (np.nan_to_num(expediente.valores("area_pisos"), nan=0.0)
                    if expediente.tiene("area_pisos") else np.zeros(malla.n_celdas))
    # Normalizados a [0,1] por su maximo del dominio, para poder sumarlos.
    norm_peso = peso / max(1e-9, peso.max())
    norm_const = construccion / max(1e-9, construccion.max())
    consecuencia = 0.6 * norm_peso + 0.4 * norm_const
    indice = np.nan_to_num(p, nan=0.0) * consecuencia

    p_max = float(np.nanmax(p)) if np.any(np.isfinite(p)) else float("nan")
    corte_inalcanzable = np.isfinite(p_max) and p_max < corte

    return {
        "corte": corte,
        "probabilidad_maxima_dominio": (None if not np.isfinite(p_max)
                                        else round(p_max, 4)),
        "corte_inalcanzable": bool(corte_inalcanzable),
        "celdas_en_riesgo": int(en_riesgo.sum()),
        "celdas_totales": int(malla.n_celdas),
        "elementos": totales,
        "indice_exposicion": indice,
        "consecuencia": consecuencia,
        "celdas_prioritarias": _prioritarias(malla, expediente, indice, p),
        "advertencias": [
            "Los conteos vienen del mapeo comunitario de OSM, incompleto en "
            "esta zona: son indice de exposicion relativa, no censo.",
            "El indice es probabilidad x consecuencia, con la consecuencia "
            "normalizada al maximo del dominio: sirve para ordenar celdas "
            "dentro de este area, no para comparar con otra ciudad.",
        ],
    }


def _prioritarias(malla, expediente, indice, probabilidad, cuantas: int = 10):
    """Las celdas que un operador deberia mirar primero."""
    orden = np.argsort(-np.nan_to_num(indice, nan=-1.0))[:cuantas]
    detalle = getattr(expediente, "detalle_critico", None)
    salida = []
    for i in orden:
        i = int(i)
        if not np.isfinite(indice[i]) or indice[i] <= 0:
            continue
        fila = {
            "id_celda": malla.ids[i],
            "lat": round(float(malla.lat[i]), 6),
            "lon": round(float(malla.lon[i]), 6),
            "indice_exposicion": round(float(indice[i]), 4),
            "probabilidad": round(float(probabilidad[i]), 4),
        }
        for capa in ("infraestructura_critica", "edificios"):
            if expediente.tiene(capa):
                fila[capa] = int(np.nan_to_num(expediente.valores(capa))[i])
        if detalle and i < len(detalle) and detalle[i]:
            fila["equipamientos"] = dict(detalle[i])
        salida.append(fila)
    return salida


def resumen_exposicion(resultado: dict) -> str:
    """Una linea en lenguaje natural, para el encabezado del tablero."""
    elementos = resultado.get("elementos", {})
    criticos = elementos.get("infraestructura_critica", {})
    edificios = elementos.get("edificios", {})
    partes = []
    if criticos.get("expuesto"):
        partes.append("{:.0f} equipamientos criticos".format(criticos["expuesto"]))
    if edificios.get("expuesto"):
        partes.append("{:.0f} edificios".format(edificios["expuesto"]))
    if not partes:
        if resultado.get("corte_inalcanzable"):
            # Distinguir "no hay nada expuesto" de "el corte era inalcanzable"
            # es importante: lo segundo no es tranquilizador, es que se pidio
            # un umbral que este escenario nunca alcanza.
            return ("Ninguna celda llega al corte de {:.0%}: la probabilidad "
                    "maxima del dominio es {:.0%}. Baja el corte o el umbral "
                    "de escurrimiento para ver exposicion.").format(
                        resultado["corte"],
                        resultado["probabilidad_maxima_dominio"] or 0.0)
        return "Sin elementos expuestos por encima del corte de {:.0%}".format(
            resultado["corte"])
    return "{} en {} celdas con probabilidad mayor o igual a {:.0%}".format(
        " y ".join(partes), resultado["celdas_en_riesgo"], resultado["corte"])
