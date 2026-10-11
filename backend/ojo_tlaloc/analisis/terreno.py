"""Analisis del terreno: pendiente y aptitud constructiva.

Para que sirve esto y para que NO
---------------------------------
Sirve para **tamizar terrenos**: reducir una lista de veinte predios
candidatos a los tres que vale la pena medir en serio. Responde preguntas de
escala de hexagono (29 km2 o 1.8 km2 segun el nivel) sobre inundabilidad,
pendiente aproximada, uso de suelo, accesos y servicios.

NO sirve para:

    - Levantamiento topografico de obra. Eso necesita precision
      centimetrica: GNSS RTK, estacion total o LiDAR de dron. Un DEM
      satelital da +-5 a 10 m en vertical y esta malla da 1.4 km de lado en su
      nivel mas fino. **No sustituye a un topografo**, y un plano topografico
      lo firma un perito con responsabilidad legal.
    - Mecanica de suelos. La capacidad de carga, el nivel de agua freatica y
      el tipo de cimentacion salen de un estudio con sondeos y laboratorio.
    - Decidir una nivelacion, un corte o un relleno.

Lo que si aporta con rigor es el **cambio relativo** de elevacion medido por
InSAR, que tiene precision milimetrica en cuanto se hundio algo (no en a que
altura esta). Para una constructora eso es asentamiento diferencial y
hundimiento regional, y es exactamente lo que el producto GUNW de NISAR hace
mejor que cualquier otra tecnica. Esa capa todavia no esta conectada; cuando
lo este, entra aqui.

Todas las funciones devuelven sus advertencias junto con los numeros, porque
separar el dato de su limite es como se construyen los malentendidos caros.
"""

from __future__ import annotations

import numpy as np

#: Pesos por defecto del indice de aptitud. Suman 1 y son EXPLICITOS a
#: proposito: un indice multicriterio con pesos escondidos no se puede
#: discutir, y estos son discutibles por diseno. Quien use el sistema para
#: decidir deberia ajustarlos a su criterio.
PESOS_APTITUD = {
    "no_inundable": 0.30,     # lo que mas pesa: si se inunda, lo demas sobra
    "pendiente": 0.15,        # plano es mas barato de construir
    "suelo_firme": 0.15,      # no humedal, no cuerpo de agua
    "accesos": 0.15,          # llegar con material y maquinaria
    "servicios": 0.10,        # cercania a infraestructura existente
    "disponible": 0.15,       # queda suelo sin construir
}

#: Pendiente, en grados, a partir de la cual construir encarece mucho.
#: Hasta 5 grados es terreno comodo; arriba de 15 se necesitan terrazas y
#: muros de contencion.
PENDIENTE_COMODA_GRADOS = 5.0
PENDIENTE_DIFICIL_GRADOS = 15.0

#: Densidad vial (km/km2) que se considera buen acceso.
DENSIDAD_VIAL_BUEN_ACCESO = 6.0


def pendiente_desde_elevacion(malla, elevacion_m) -> dict:
    """Pendiente aproximada por celda, en grados, usando los 6 vecinos.

    La malla hexagonal ayuda aqui: los 6 vecinos estan todos a la misma
    distancia (el ancho del hexagono), asi que la pendiente hacia cada uno es
    simplemente la diferencia de altura entre esa distancia, sin corregir por
    geometria de rejilla.

    Se devuelve la pendiente MAXIMA (la del vecino con mayor desnivel) y la
    media. La maxima es la que importa para escurrimiento y para costo de
    construccion; la media suaviza el ruido del DEM.

    Precision: hereda la del dato de elevacion. Con la elevacion sintetica de
    hoy esto es una forma suave y no el relieve real; con un DEM de 30 m
    agregado a hexagonos de 5.8 km, la pendiente que sale es la del terreno
    "promedio" de la celda y puede esconder barrancas y taludes completos.
    """
    elev = np.asarray(elevacion_m, dtype=float)
    if elev.shape != (malla.n_celdas,):
        raise ValueError("elevacion_m debe tener largo n_celdas")

    paso_m = malla.ancho_celda_km * 1000.0
    vecinos = malla.vecinos()
    maxima = np.zeros(malla.n_celdas)
    media = np.zeros(malla.n_celdas)
    n_vecinos = np.zeros(malla.n_celdas, dtype=int)

    for i, fila in enumerate(vecinos):
        if not fila or not np.isfinite(elev[i]):
            continue
        desniveles = []
        for j in fila:
            if np.isfinite(elev[j]):
                desniveles.append(abs(elev[j] - elev[i]))
        if not desniveles:
            continue
        d = np.asarray(desniveles)
        maxima[i] = np.degrees(np.arctan(d.max() / paso_m))
        media[i] = np.degrees(np.arctan(d.mean() / paso_m))
        n_vecinos[i] = d.size

    return {
        "pendiente_max_grados": maxima,
        "pendiente_media_grados": media,
        "vecinos_usados": n_vecinos,
        "paso_m": paso_m,
        "advertencia": (
            "pendiente promediada a la escala del hexagono ({:.1f} km de "
            "lado): puede esconder taludes y barrancas enteros. No usar para "
            "diseno de terracerias."
        ).format(malla.ancho_celda_km),
    }


def aptitud_constructiva(
    malla,
    expediente,
    probabilidad_inundacion=None,
    pesos=None,
) -> dict:
    """Indice de aptitud constructiva por hexagono, 0 (mala) a 1 (buena).

    Combina cinco criterios normalizados a [0, 1] con pesos explicitos. Cada
    criterio dice de donde sale y cual es su punto flaco.

    `probabilidad_inundacion` es la capa de riesgo del pronostico; si no se
    pasa, ese criterio se omite y los pesos se renormalizan (y se dice en la
    respuesta, para que nadie compare dos indices calculados con criterios
    distintos sin saberlo).
    """
    pesos = dict(pesos or PESOS_APTITUD)
    n = malla.n_celdas
    criterios: dict[str, np.ndarray] = {}
    detalle: dict[str, str] = {}

    # --- no inundable
    if probabilidad_inundacion is not None:
        p = np.asarray(probabilidad_inundacion, dtype=float)
        if p.shape != (n,):
            raise ValueError("probabilidad_inundacion debe tener largo n_celdas")
        criterios["no_inundable"] = 1.0 - np.clip(np.nan_to_num(p, nan=0.0), 0, 1)
        detalle["no_inundable"] = ("1 - P(escurrimiento acumulado alto) del "
                                   "ensamble estocastico")
    else:
        pesos.pop("no_inundable", None)
        detalle["no_inundable"] = "OMITIDO: no se paso capa de riesgo"

    # --- pendiente
    elev = expediente.valores("elevacion_m", defecto=0.0)
    pend = pendiente_desde_elevacion(malla, elev)["pendiente_max_grados"]
    criterios["pendiente"] = np.clip(
        1.0 - (pend - PENDIENTE_COMODA_GRADOS)
        / (PENDIENTE_DIFICIL_GRADOS - PENDIENTE_COMODA_GRADOS),
        0.0, 1.0,
    )
    detalle["pendiente"] = (
        "1 en terreno de hasta {:.0f} grados, 0 arriba de {:.0f}".format(
            PENDIENTE_COMODA_GRADOS, PENDIENTE_DIFICIL_GRADOS)
    )

    # --- suelo firme: ni agua ni muy cerca de cauce
    agua = expediente.valores("fraccion_agua", defecto=0.0)
    cauces = expediente.valores("densidad_cauces", defecto=0.0)
    es_tierra = expediente.valores("es_tierra", defecto=1.0) > 0.5
    firme = (1.0 - np.clip(np.nan_to_num(agua, nan=0.0) * 3.0, 0, 1)) * \
            (1.0 - np.clip(np.nan_to_num(cauces, nan=0.0) / 1.5, 0, 0.6))
    criterios["suelo_firme"] = np.where(es_tierra, np.clip(firme, 0, 1), 0.0)
    detalle["suelo_firme"] = ("penaliza cuerpos de agua y densidad de cauces; "
                              "el mar vale 0")

    # --- accesos
    vial = expediente.valores("densidad_vial", defecto=0.0)
    criterios["accesos"] = np.clip(
        np.nan_to_num(vial, nan=0.0) / DENSIDAD_VIAL_BUEN_ACCESO, 0.0, 1.0)
    detalle["accesos"] = ("densidad de vialidad de OSM, saturando en "
                          "{:.0f} km/km2".format(DENSIDAD_VIAL_BUEN_ACCESO))

    # --- suelo disponible
    # Sin este criterio el indice premia lo YA urbanizado, que es justo donde
    # no hay terreno que comprar: medido sin el, las cinco celdas mas aptas
    # eran las cinco mas densas del puerto. Un tamiz para buscar predio tiene
    # que valorar que quede suelo libre.
    imperm = np.nan_to_num(
        expediente.valores("fraccion_impermeable", defecto=0.0), nan=0.0)
    criterios["disponible"] = np.clip(1.0 - imperm / 0.6, 0.0, 1.0)
    detalle["disponible"] = ("1 - fraccion impermeable, saturando en 0.6: "
                             "mide cuanto suelo queda sin construir")

    # --- servicios
    critica = expediente.valores("infraestructura_critica", defecto=0.0)
    edificios = expediente.valores("edificios", defecto=0.0)
    cercania = np.clip(np.nan_to_num(critica, nan=0.0) / 5.0, 0, 1) * 0.6 + \
        np.clip(np.nan_to_num(edificios, nan=0.0) / 100.0, 0, 1) * 0.4
    criterios["servicios"] = np.clip(cercania, 0, 1)
    detalle["servicios"] = ("proxy de urbanizacion: equipamiento y edificios "
                            "mapeados en OSM")

    # --- combinacion
    usados = {k: v for k, v in pesos.items() if k in criterios}
    total_peso = sum(usados.values())
    if total_peso <= 0:
        raise ValueError("no quedo ningun criterio con peso positivo")
    indice = np.zeros(n)
    for nombre, peso in usados.items():
        indice += (peso / total_peso) * criterios[nombre]
    indice = np.where(es_tierra, indice, np.nan)

    return {
        "aptitud": indice,
        "criterios": criterios,
        "pesos_usados": {k: round(v / total_peso, 4) for k, v in usados.items()},
        "pesos_renormalizados": abs(total_peso - 1.0) > 1e-9,
        "detalle_criterios": detalle,
        "advertencias": [
            "Es un TAMIZ, no un dictamen. Sirve para decidir que predios vale "
            "la pena medir, no para decidir si se construye.",
            "NO sustituye levantamiento topografico (precision centimetrica) "
            "ni estudio de mecanica de suelos. Un plano topografico lo firma "
            "un perito.",
            "La pendiente se calcula sobre elevacion {} a escala de hexagono "
            "de {:.1f} km.".format(
                "SINTETICA (placeholder)"
                if "elevacion_m" in expediente.capas_sinteticas() else "real",
                malla.ancho_celda_km),
            "Los pesos de los criterios son una opinion, no un calculo. Estan "
            "expuestos para que se discutan y se ajusten.",
            "El criterio 'disponible' existe porque sin el el indice premiaba "
            "las celdas mas densas del puerto, donde no hay terreno que "
            "comprar. Si lo que se busca es densificar y no terreno nuevo, "
            "ese peso va a cero.",
        ],
    }
