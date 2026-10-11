"""Resumen probabilistico del ensamble.

El simulador entrega un cubo (miembros, dias, celdas). Nadie pinta un cubo en
un mapa: hay que colapsar la dimension de miembros en estadisticos. Este
modulo es la unica frontera entre el modelo y el front, y define el contrato:

    capa()            un valor por celda para un dia -> se colorea
    serie_celda()     percentiles por dia para una celda -> panel lateral
    riesgo()          probabilidad de escurrimiento alto -> capa de alerta

Decision de diseno: el riesgo NO es un indice inventado con pesos a mano.
Se reporta como probabilidad de que el escurrimiento acumulado pase un
umbral, porque el escurrimiento ya integra lluvia y saturacion del suelo por
construccion del balance de agua. Un indice con pesos arbitrarios se ve bien
en una demo y no se puede defender ante una pregunta.
"""

from __future__ import annotations

import numpy as np

from .modelo import ResultadoSimulacion

#: Percentiles que se exponen por defecto. P10/P50/P90 es el minimo para
#: comunicar incertidumbre sin abrumar; P99 importa para extremos.
PERCENTILES = (10, 25, 50, 75, 90, 99)

#: Umbral de escurrimiento acumulado en 72 h (mm) a partir del cual se
#: considera evento de escurrimiento alto. CALIBRABLE: sin datos de aforo de
#: la cuenca del Jamapa no se puede mapear a un caudal ni a un nivel de rio.
#: 60 mm en 72 h es el orden de magnitud de un evento con encharcamiento
#: urbano en planicie costera.
UMBRAL_ESCURRIMIENTO_72H_MM = 60.0

#: Cortes de probabilidad para las 4 categorias del mapa de alerta.
CORTES_RIESGO = (0.10, 0.30, 0.60)
ETIQUETAS_RIESGO = ("bajo", "moderado", "alto", "muy alto")

#: Etiqueta de las celdas donde la variable no existe (mar). Categoria -1.
ETIQUETA_SIN_DOMINIO = "no aplica"

#: Escalas de color sugeridas por variable. El front no tiene que inventar
#: rangos: si cada quien elige los suyos, dos capas dejan de ser comparables.
#: dominio esta en unidades de la variable; `paleta` es una sugerencia.
ESCALAS = {
    "lluvia": {
        "unidad": "mm/dia",
        "dominio": [0, 1, 5, 20, 50, 100, 150],
        "paleta": "azules",
        "etiqueta": "Lluvia acumulada en 24 h",
    },
    "tmax": {
        "unidad": "C",
        "dominio": [18, 22, 26, 30, 34, 38],
        "paleta": "calidos",
        "etiqueta": "Temperatura maxima",
    },
    "tmin": {
        "unidad": "C",
        "dominio": [12, 16, 20, 24, 28],
        "paleta": "calidos",
        "etiqueta": "Temperatura minima",
    },
    "humedad_suelo": {
        "unidad": "saturacion 0-1",
        "dominio": [0, 0.2, 0.4, 0.6, 0.8, 1.0],
        "paleta": "cafes_verdes",
        "etiqueta": "Humedad del suelo",
    },
    "escurrimiento": {
        "unidad": "mm/dia",
        "dominio": [0, 1, 5, 15, 40, 80],
        "paleta": "morados",
        "etiqueta": "Escurrimiento",
    },
    "et0": {
        "unidad": "mm/dia",
        "dominio": [0, 2, 4, 6, 8],
        "paleta": "naranjas",
        "etiqueta": "Evapotranspiracion de referencia",
    },
    "probabilidad": {
        "unidad": "probabilidad 0-1",
        "dominio": [0, 0.1, 0.3, 0.6, 0.8, 1.0],
        "paleta": "amarillo_rojo",
        "etiqueta": "Probabilidad",
    },
}

ESTADISTICOS = ("media", "p10", "p25", "p50", "p75", "p90", "p99", "desv", "rango")


def _reduce(muestras: np.ndarray, estadistico: str) -> np.ndarray:
    """Colapsa el eje 0 (miembros) con el estadistico pedido."""
    if estadistico == "media":
        return np.nanmean(muestras, axis=0)
    if estadistico == "desv":
        return np.nanstd(muestras, axis=0)
    if estadistico == "rango":
        # Ancho del intervalo central del 80%: la medida de incertidumbre que
        # se le ensena al usuario.
        return (np.nanpercentile(muestras, 90, axis=0)
                - np.nanpercentile(muestras, 10, axis=0))
    if estadistico.startswith("p"):
        try:
            q = float(estadistico[1:])
        except ValueError:
            raise ValueError("estadistico invalido: " + estadistico) from None
        if not 0.0 <= q <= 100.0:
            raise ValueError("el percentil debe estar entre 0 y 100")
        return np.nanpercentile(muestras, q, axis=0)
    raise ValueError(
        "estadistico invalido '{}'; validos: {}".format(
            estadistico, ", ".join(ESTADISTICOS)
        )
    )


def capa(
    resultado: ResultadoSimulacion,
    variable: str = "lluvia",
    dia: int = 0,
    estadistico: str = "p50",
) -> dict:
    """Un valor por celda, listo para colorear.

    dia es el indice dentro del horizonte (0 = primer dia del pronostico).
    """
    datos = resultado.variable(variable)
    _valida_dia(dia, resultado.n_dias)
    valores = _reduce(datos[:, dia, :], estadistico)
    return {
        "variable": variable,
        "estadistico": estadistico,
        "dia": dia,
        "fecha": resultado.fechas[dia],
        "escala": ESCALAS.get(variable, ESCALAS["probabilidad"]),
        "valores": valores,
    }


def probabilidad_umbral(
    resultado: ResultadoSimulacion,
    variable: str = "lluvia",
    dia: int = 0,
    umbral: float = 20.0,
    ventana_dias: int = 1,
) -> dict:
    """P(variable acumulada en la ventana > umbral), por celda.

    Con ventana_dias > 1 se acumula desde `dia` hacia adelante. Para variables
    de estado (humedad, temperatura) la acumulacion no tiene sentido fisico:
    ahi se usa el maximo de la ventana.
    """
    datos = resultado.variable(variable)
    _valida_dia(dia, resultado.n_dias)
    if ventana_dias < 1:
        raise ValueError("ventana_dias debe ser al menos 1")
    fin = min(dia + ventana_dias, resultado.n_dias)
    trozo = datos[:, dia:fin, :]

    if variable in ("lluvia", "escurrimiento", "et0"):
        agregado = np.nansum(trozo, axis=1)
        modo = "acumulado"
    else:
        agregado = np.nanmax(trozo, axis=1)
        modo = "maximo"

    # Donde la variable no existe (mar) el resultado es NaN, no 0. Comparar
    # NaN > umbral da False, asi que sin esta mascara el oceano saldria con
    # probabilidad 0 y el mapa lo pintaria como "seguro" en vez de "no aplica".
    sin_dominio = np.all(~np.isfinite(trozo), axis=(0, 1))
    prob = np.nanmean(agregado > umbral, axis=0)
    prob = np.where(sin_dominio, np.nan, prob)
    return {
        "variable": variable,
        "umbral": umbral,
        "ventana_dias": fin - dia,
        "modo": modo,
        "dia": dia,
        "fecha": resultado.fechas[dia],
        "escala": ESCALAS["probabilidad"],
        "valores": prob,
    }


def riesgo(
    resultado: ResultadoSimulacion,
    dia: int = 0,
    ventana_dias: int = 3,
    umbral_mm: float = UMBRAL_ESCURRIMIENTO_72H_MM,
) -> dict:
    """Capa de alerta: probabilidad de escurrimiento acumulado alto.

    Devuelve la probabilidad y su categoria (bajo/moderado/alto/muy alto)
    segun CORTES_RIESGO. El escurrimiento es la variable adecuada y no la
    lluvia cruda porque 60 mm sobre suelo seco se infiltran y 60 mm sobre
    suelo saturado corren hacia el rio: es la misma lluvia y no es el mismo
    riesgo. Esa diferencia es exactamente la que aporta el dato de NISAR.
    """
    p = probabilidad_umbral(
        resultado, "escurrimiento", dia=dia, umbral=umbral_mm,
        ventana_dias=ventana_dias,
    )
    prob = p["valores"]
    # np.digitize manda los NaN al ultimo cajon, o sea que el oceano saldria
    # clasificado como "muy alto". Las celdas sin dominio se marcan con -1 y
    # su propia etiqueta para que el front las pueda dejar sin pintar.
    sin_dato = ~np.isfinite(prob)
    categoria = np.digitize(np.where(sin_dato, 0.0, prob), CORTES_RIESGO)
    categoria = np.where(sin_dato, -1, categoria)
    return {
        "variable": "riesgo_escurrimiento",
        "umbral_mm": umbral_mm,
        "ventana_dias": p["ventana_dias"],
        "dia": dia,
        "fecha": p["fecha"],
        "escala": {
            "unidad": "probabilidad 0-1",
            "dominio": [0.0] + list(CORTES_RIESGO) + [1.0],
            "paleta": "verde_rojo",
            "etiqueta": "P(escurrimiento {} h > {:.0f} mm)".format(
                p["ventana_dias"] * 24, umbral_mm
            ),
            "categorias": list(ETIQUETAS_RIESGO),
            "categoria_sin_dominio": {"valor": -1, "etiqueta": ETIQUETA_SIN_DOMINIO},
        },
        "valores": prob,
        "categoria": categoria,
        "etiqueta_categoria": [
            ETIQUETA_SIN_DOMINIO if int(k) < 0 else ETIQUETAS_RIESGO[int(k)]
            for k in categoria
        ],
    }


def serie_celda(
    resultado: ResultadoSimulacion,
    indice_celda: int,
    variables=("lluvia", "tmax", "tmin", "humedad_suelo"),
    percentiles=PERCENTILES,
) -> dict:
    """Serie temporal con bandas de incertidumbre para una celda.

    Es lo que alimenta el panel lateral: una linea (mediana) y bandas
    (percentiles) por dia. Tambien devuelve `miembros_muestra`, 20
    trayectorias individuales, porque el abanico de trayectorias comunica la
    incertidumbre mucho mejor que una banda sombreada.
    """
    if not 0 <= indice_celda < resultado.n_celdas:
        raise IndexError("indice de celda fuera de rango")

    salida = {
        "id_celda": resultado.ids_celdas[indice_celda],
        "fechas": list(resultado.fechas),
        "variables": {},
    }
    paso = max(1, resultado.n_miembros // 20)
    for var in variables:
        datos = resultado.variable(var)[:, :, indice_celda]   # (m, dias)
        bloque = {
            "unidad": ESCALAS.get(var, {}).get("unidad", ""),
            "media": np.nanmean(datos, axis=0),
        }
        for q in percentiles:
            bloque["p{}".format(q)] = np.nanpercentile(datos, q, axis=0)
        bloque["miembros_muestra"] = datos[::paso][:20]
        salida["variables"][var] = bloque
    return salida


def resumen_dominio(resultado: ResultadoSimulacion, es_tierra=None) -> dict:
    """Numeros agregados del pronostico, para el encabezado del tablero."""
    mascara = slice(None) if es_tierra is None else es_tierra
    lluvia = resultado.lluvia_mm[:, :, mascara]
    acum_miembro = np.nansum(lluvia, axis=1).mean(axis=1)   # (m,) media espacial
    return {
        "dias": resultado.n_dias,
        "miembros": resultado.n_miembros,
        "celdas": resultado.n_celdas,
        "fecha_inicio": resultado.fechas[0],
        "fecha_fin": resultado.fechas[-1],
        "semilla": resultado.semilla,
        "lluvia_total_mm": {
            "p10": round(float(np.percentile(acum_miembro, 10)), 1),
            "p50": round(float(np.percentile(acum_miembro, 50)), 1),
            "p90": round(float(np.percentile(acum_miembro, 90)), 1),
        },
        "dia_mas_lluvioso": int(
            np.argmax(np.nanmean(lluvia, axis=(0, 2)))
        ),
        "tmax_p90_c": round(float(np.nanpercentile(
            resultado.tmax_c[:, :, mascara], 90)), 1),
        "humedad_suelo_p50_final": round(float(np.nanpercentile(
            resultado.humedad_suelo[:, -1, mascara], 50)), 3),
    }


def _valida_dia(dia: int, n_dias: int) -> None:
    if not 0 <= dia < n_dias:
        raise IndexError(
            "dia {} fuera del horizonte de {} dias".format(dia, n_dias)
        )
