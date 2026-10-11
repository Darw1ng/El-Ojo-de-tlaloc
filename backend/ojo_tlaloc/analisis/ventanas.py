"""Ventanas de obra: traducir el pronostico a decisiones de construccion.

El producto
-----------
Una constructora no necesita saber que van a caer 43 mm. Necesita saber si el
jueves se puede colar. Cada actividad de obra tiene restricciones distintas, y
el mismo pronostico probabilistico responde a todas si se le pone el umbral de
cada una:

    colado de concreto       lluvia casi nula y temperatura acotada
    movimiento de tierras    ni lluvia ni suelo saturado (no se excava lodo)
    compactacion             humedad del suelo cerca de la optima de Proctor
    impermeabilizacion       superficie seca, varias horas sin lluvia
    pintura y acabados       sin lluvia y humedad baja
    obra exterior general    tolera lluvia ligera

La salida es `P(dia trabajable)` por celda, dia y actividad. Y como viene de
un ensamble, no es un si/no: es "87% de probabilidad de poder colar el
jueves", que es con lo que se decide pedir o no la revolvedora.

Lo que hace falta y no esta
---------------------------
**Viento.** Las gruas torre se ponen fuera de servicio del orden de 45 a
72 km/h segun el fabricante, y el viento a 60 metros de altura no es el de una
estacion a 10 metros: hay un perfil logaritmico. El modelo estocastico no
genera viento, asi que las actividades que dependen de el estan declaradas y
desactivadas en lugar de inventadas. Es justo lo que mediria un globo cautivo
a 100-300 m, que es la pieza de hardware mas barata del proyecto.

Sobre la humedad optima de compactacion
---------------------------------------
Un suelo no compacta ni muy seco ni muy mojado: tiene un contenido optimo
(ensayo Proctor) que depende de su textura. Aqui se usa una ventana de
saturacion relativa, que es una aproximacion gruesa al concepto: el valor real
sale del laboratorio para ese suelo. Sirve para planear la semana, no para
aceptar una capa compactada.
"""

from __future__ import annotations

import numpy as np

#: Catalogo de actividades con sus restricciones.
#:
#: lluvia_max_mm       lluvia diaria tolerada
#: suelo_max           saturacion maxima del suelo (None = no aplica)
#: suelo_min           saturacion minima (para compactacion)
#: tmax_max_c          temperatura maxima (concreto y riesgo laboral)
#: necesita_viento     True = requiere dato de viento que el modelo no genera
ACTIVIDADES = {
    "colado_concreto": {
        "etiqueta": "Colado de concreto",
        "lluvia_max_mm": 1.0,
        "suelo_max": None,
        "suelo_min": None,
        "tmax_max_c": 35.0,
        "necesita_viento": False,
        "razon": ("la lluvia sobre concreto fresco altera la relacion "
                  "agua-cemento y arruina el acabado; arriba de 35 C el "
                  "fraguado se acelera y agrieta"),
    },
    "movimiento_tierras": {
        "etiqueta": "Movimiento de tierras",
        "lluvia_max_mm": 5.0,
        "suelo_max": 0.65,
        "suelo_min": None,
        "tmax_max_c": None,
        "necesita_viento": False,
        "razon": ("con el suelo saturado la maquinaria se atasca, el material "
                  "no se puede manejar y el corte se derrumba"),
    },
    "compactacion": {
        "etiqueta": "Compactacion",
        "lluvia_max_mm": 2.0,
        "suelo_max": 0.55,
        "suelo_min": 0.25,
        "tmax_max_c": None,
        "necesita_viento": False,
        "razon": ("el suelo compacta solo cerca de su humedad optima: muy "
                  "seco no liga, muy humedo no transmite la energia"),
    },
    "impermeabilizacion": {
        "etiqueta": "Impermeabilizacion",
        "lluvia_max_mm": 0.2,
        "suelo_max": None,
        "suelo_min": None,
        "tmax_max_c": 38.0,
        "necesita_viento": False,
        "razon": "la superficie tiene que estar seca y seguir seca al curar",
    },
    "acabados_exteriores": {
        "etiqueta": "Pintura y acabados exteriores",
        "lluvia_max_mm": 0.5,
        "suelo_max": None,
        "suelo_min": None,
        "tmax_max_c": 36.0,
        "necesita_viento": False,
        "razon": "la lluvia lava el acabado antes de que cure",
    },
    "obra_exterior_general": {
        "etiqueta": "Obra exterior general",
        "lluvia_max_mm": 10.0,
        "suelo_max": None,
        "suelo_min": None,
        "tmax_max_c": 40.0,
        "necesita_viento": False,
        "razon": "tolera lluvia ligera; se detiene con lluvia franca",
    },
    "montaje_con_grua": {
        "etiqueta": "Montaje con grua",
        "lluvia_max_mm": 5.0,
        "suelo_max": None,
        "suelo_min": None,
        "tmax_max_c": None,
        "necesita_viento": True,
        "razon": ("el limite real es el viento a la altura de la pluma, no la "
                  "lluvia; requiere perfil de viento que este modelo no "
                  "genera"),
    },
}


def ventanas_de_obra(
    resultado,
    actividades=None,
    es_tierra=None,
    incluir_sin_viento: bool = False,
) -> dict:
    """P(dia trabajable) por celda, dia y actividad.

    `resultado` es un ResultadoSimulacion del ensamble. Para cada miembro y
    dia se evalua si cumple TODAS las restricciones de la actividad, y la
    probabilidad es la fraccion de miembros que cumplen. Evaluar por miembro y
    no sobre la mediana es lo correcto: un dia con mediana de 0.5 mm y cola
    larga puede tener 30% de probabilidad de pasarse del umbral, y eso es lo
    que el jefe de obra necesita saber.

    `incluir_sin_viento=False` omite las actividades que necesitan viento en
    lugar de contestarlas con datos que no existen.
    """
    nombres = list(actividades or ACTIVIDADES)
    desconocidas = [n for n in nombres if n not in ACTIVIDADES]
    if desconocidas:
        raise KeyError(
            "actividad desconocida: {}. Disponibles: {}".format(
                ", ".join(desconocidas), ", ".join(sorted(ACTIVIDADES))
            )
        )

    lluvia = resultado.lluvia_mm
    suelo = resultado.humedad_suelo
    tmax = resultado.tmax_c

    salida = {}
    omitidas = []
    for nombre in nombres:
        cfg = ACTIVIDADES[nombre]
        if cfg["necesita_viento"] and not incluir_sin_viento:
            omitidas.append({
                "actividad": nombre,
                "etiqueta": cfg["etiqueta"],
                "motivo": ("requiere perfil de viento; el modelo no lo genera. "
                           "Lo mediria un globo cautivo a altura de pluma"),
            })
            continue

        cumple = lluvia <= cfg["lluvia_max_mm"]
        if cfg["tmax_max_c"] is not None:
            cumple = cumple & (tmax <= cfg["tmax_max_c"])
        if cfg["suelo_max"] is not None:
            # En el mar el suelo es NaN: esas celdas no aplican y se dejan NaN
            # al final, no se cuentan como que cumplen.
            cumple = cumple & (np.nan_to_num(suelo, nan=1.0) <= cfg["suelo_max"])
        if cfg["suelo_min"] is not None:
            cumple = cumple & (np.nan_to_num(suelo, nan=0.0) >= cfg["suelo_min"])

        prob = cumple.mean(axis=0)            # (dias, celdas)
        if es_tierra is not None:
            prob = np.where(np.asarray(es_tierra)[None, :], prob, np.nan)

        salida[nombre] = {
            "etiqueta": cfg["etiqueta"],
            "razon": cfg["razon"],
            "restricciones": {k: v for k, v in cfg.items()
                              if k in ("lluvia_max_mm", "suelo_max",
                                       "suelo_min", "tmax_max_c")
                              and v is not None},
            "probabilidad": prob,                        # (dias, celdas)
            "dias_trabajables_esperados": np.nansum(prob, axis=0),  # (celdas,)
        }

    return {
        "fechas": list(resultado.fechas),
        "horizonte_dias": resultado.n_dias,
        "miembros": resultado.n_miembros,
        "actividades": salida,
        "omitidas": omitidas,
        "advertencias": [
            "Los umbrales son valores de referencia de practica constructiva, "
            "no una norma. Cada obra y cada especificacion manda sobre esto.",
            "La humedad del suelo es saturacion relativa del modelo, una "
            "aproximacion gruesa a la humedad optima de Proctor, que sale de "
            "laboratorio para ese suelo.",
            "Sirve para planear la semana, no para aceptar trabajo ejecutado.",
        ],
    }


def calendario_celda(ventanas: dict, indice_celda: int) -> dict:
    """El calendario de una celda, listo para una tabla de la interfaz."""
    filas = []
    for nombre, bloque in ventanas["actividades"].items():
        prob = bloque["probabilidad"][:, indice_celda]
        filas.append({
            "actividad": nombre,
            "etiqueta": bloque["etiqueta"],
            "por_dia": [None if not np.isfinite(v) else round(float(v), 3)
                        for v in prob],
            "dias_trabajables_esperados": round(float(np.nansum(prob)), 2),
            "mejor_dia": (int(np.nanargmax(prob))
                          if np.any(np.isfinite(prob)) else None),
        })
    filas.sort(key=lambda f: -f["dias_trabajables_esperados"])
    return {
        "fechas": ventanas["fechas"],
        "horizonte_dias": ventanas["horizonte_dias"],
        "actividades": filas,
        "omitidas": ventanas["omitidas"],
    }
