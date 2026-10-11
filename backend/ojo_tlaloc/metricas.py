"""Metricas de verificacion probabilistica.

Un pronostico probabilistico no se evalua con error medio absoluto. Si el
modelo dice "60% de probabilidad de lluvia" y llueve, no acerto ni fallo: hay
que medir sobre muchos casos si de los dias a los que les puso 60%, llovio en
el 60%. Este modulo implementa el minimo defendible:

    crps()            error del pronostico de ensamble completo
    brier()           error de un pronostico de probabilidad binaria
    confiabilidad()   el diagrama que revela sobreconfianza
    descomposicion()  Murphy: fiabilidad - resolucion + incertidumbre
    dispersion_vs_error()  si el ensamble esta bien dispersado

Sin esto el proyecto es una animacion bonita. Con esto se puede responder
"que tan bueno es" con un numero y una grafica.

Referencias de las formulas: Hersbach (2000) para el CRPS de ensamble,
Murphy (1973) para la descomposicion del Brier, Fortin et al. (2014) para la
relacion dispersion-error.
"""

from __future__ import annotations

import numpy as np


def crps(ensamble: np.ndarray, observado, justo: bool = True):
    """CRPS del pronostico de ensamble, en las unidades de la variable.

    ensamble   (n_miembros, ...) trayectorias
    observado  (...) valor que ocurrio
    justo      True usa el estimador sin sesgo ("fair CRPS", Ferro 2014)

    CRPS = E|X - y| - 0.5 E|X - X'|

    El primer termino castiga el error; el segundo premia tener dispersion.
    Un pronostico determinista (un solo miembro) degenera en |x - y|, asi que
    el CRPS compara de forma justa deterministas contra ensambles: eso es lo
    que lo hace la metrica correcta aqui.

    El estimador clasico (justo=False) divide la suma de pares entre m^2, lo
    que incluye los pares i=i y por lo tanto subestima E|X-X'|: resta menos y
    deja el CRPS mas alto de lo que corresponde. El sesgo crece cuando el
    ensamble es chico, asi que castiga a los sistemas con pocos miembros y no
    deja comparar dos sistemas con distinto m. El estimador justo divide entre
    m(m-1) y es insesgado. Con 200 miembros la diferencia es de decimas de por
    ciento; con 20 ya se nota.

    Menor es mejor. 0 es perfecto.
    """
    x = np.asarray(ensamble, dtype=float)
    y = np.asarray(observado, dtype=float)
    if x.ndim < 1:
        raise ValueError("ensamble debe tener al menos un eje de miembros")
    m = x.shape[0]
    if m < 1:
        raise ValueError("el ensamble esta vacio")
    if x.shape[1:] != y.shape:
        raise ValueError(
            "observado debe tener forma {} y tiene {}".format(x.shape[1:], y.shape)
        )

    termino_error = np.abs(x - y[None, ...]).mean(axis=0)
    if m == 1:
        return termino_error

    # E|X - X'| sin armar la matriz m x m: con el ensamble ordenado,
    #   sum_i sum_j |x_i - x_j| = 2 sum_i (2i - m + 1) x_(i)
    orden = np.sort(x, axis=0)
    pesos = (2.0 * np.arange(m) - m + 1.0).reshape((m,) + (1,) * (x.ndim - 1))
    suma_pares = 2.0 * (pesos * orden).sum(axis=0)
    divisor = (m * (m - 1)) if justo else (m * m)
    termino_dispersion = suma_pares / (2.0 * divisor)

    return termino_error - termino_dispersion


def crps_climatologico(climatologia_muestras: np.ndarray, observado):
    """CRPS del pronostico de referencia (la climatologia). Para el skill."""
    return crps(climatologia_muestras, observado)


def crpss(ensamble, observado, referencia):
    """Skill score del CRPS contra una referencia. 1 perfecto, 0 = la referencia.

    CRPSS = 1 - CRPS_modelo / CRPS_referencia

    Negativo significa que el modelo es PEOR que decir simplemente "lo normal
    para esta epoca del ano". Es la pregunta honesta que hay que hacerle a
    cualquier pronostico.
    """
    num = np.nanmean(crps(ensamble, observado))
    den = np.nanmean(crps(referencia, observado))
    if den == 0:
        return float("nan")
    return 1.0 - num / den


def brier(probabilidad, ocurrio):
    """Brier score: media de (p - o)^2. Menor es mejor, 0 perfecto, 0.25 = azar.

    probabilidad  (...) probabilidad pronosticada del evento, en [0, 1]
    ocurrio       (...) 1 si el evento ocurrio, 0 si no
    """
    p = np.asarray(probabilidad, dtype=float)
    o = np.asarray(ocurrio, dtype=float)
    if p.shape != o.shape:
        raise ValueError("probabilidad y ocurrio deben tener la misma forma")
    if np.any((p < -1e-9) | (p > 1 + 1e-9)):
        raise ValueError("la probabilidad debe estar en [0, 1]")
    if not np.all(np.isin(o[np.isfinite(o)], (0.0, 1.0))):
        raise ValueError("ocurrio debe ser binario (0 o 1)")
    valido = np.isfinite(p) & np.isfinite(o)
    return float(np.mean((p[valido] - o[valido]) ** 2))


def brier_skill(probabilidad, ocurrio, tasa_base=None):
    """BSS contra la frecuencia base del evento (climatologia).

    BSS = 1 - BS / BS_climatologico.  0 = no aporta nada sobre decir siempre
    la frecuencia historica; negativo = peor que eso.
    """
    o = np.asarray(ocurrio, dtype=float)
    valido = np.isfinite(o)
    base = float(np.mean(o[valido])) if tasa_base is None else float(tasa_base)
    bs = brier(probabilidad, ocurrio)
    bs_clim = brier(np.full(o.shape, base), ocurrio)
    if bs_clim == 0:
        return float("nan")
    return 1.0 - bs / bs_clim


def confiabilidad(probabilidad, ocurrio, n_cajas: int = 10) -> dict:
    """Diagrama de confiabilidad: frecuencia observada por caja de probabilidad.

    Un pronostico bien calibrado cae sobre la diagonal: de los casos a los que
    les puso 0.7, el evento ocurrio el 70% de las veces. Arriba de la diagonal
    = subestima; abajo = sobreconfiado, que es el defecto tipico de un ensamble
    con muy pocos miembros o con la dispersion mal especificada.
    """
    p = np.asarray(probabilidad, dtype=float).ravel()
    o = np.asarray(ocurrio, dtype=float).ravel()
    if p.shape != o.shape:
        raise ValueError("probabilidad y ocurrio deben tener la misma forma")
    valido = np.isfinite(p) & np.isfinite(o)
    p, o = p[valido], o[valido]

    bordes = np.linspace(0.0, 1.0, n_cajas + 1)
    caja = np.clip(np.digitize(p, bordes[1:-1]), 0, n_cajas - 1)

    centros, observadas, pronosticadas, conteos = [], [], [], []
    for k in range(n_cajas):
        sel = caja == k
        centros.append(float((bordes[k] + bordes[k + 1]) / 2.0))
        conteos.append(int(sel.sum()))
        observadas.append(float(o[sel].mean()) if sel.any() else float("nan"))
        pronosticadas.append(float(p[sel].mean()) if sel.any() else float("nan"))

    return {
        "centro_caja": centros,
        "probabilidad_media": pronosticadas,
        "frecuencia_observada": observadas,
        "casos": conteos,
        "tasa_base": float(o.mean()) if o.size else float("nan"),
    }


def descomposicion_brier(probabilidad, ocurrio, n_cajas: int = 10) -> dict:
    """Descomposicion de Murphy: BS = fiabilidad - resolucion + incertidumbre.

    fiabilidad     que tan lejos de la diagonal esta (menor mejor)
    resolucion     que tanto distingue casos (mayor mejor)
    incertidumbre  varianza climatologica del evento; no depende del modelo

    La identidad de Murphy es exacta cuando el pronostico toma un numero
    finito de valores distintos. Con probabilidades continuas hay que
    agruparlas en cajas, y entonces aparece un residuo: la varianza de las
    probabilidades DENTRO de cada caja (termino de Stephenson et al. 2008).
    Se devuelve como `residuo_intracaja` en lugar de esconderlo; si es grande
    frente al Brier, hay que subir n_cajas.
    """
    rel = confiabilidad(probabilidad, ocurrio, n_cajas)
    o = np.asarray(ocurrio, dtype=float).ravel()
    o = o[np.isfinite(o)]
    n = o.size
    if n == 0:
        raise ValueError("no hay observaciones validas")
    base = float(o.mean())

    fiabilidad = 0.0
    resolucion = 0.0
    for pk, ok, nk in zip(rel["probabilidad_media"],
                          rel["frecuencia_observada"],
                          rel["casos"]):
        if nk == 0 or not np.isfinite(pk) or not np.isfinite(ok):
            continue
        fiabilidad += nk * (pk - ok) ** 2
        resolucion += nk * (ok - base) ** 2
    fiabilidad /= n
    resolucion /= n
    incertidumbre = base * (1.0 - base)

    bs = brier(probabilidad, ocurrio)
    suma = fiabilidad - resolucion + incertidumbre
    return {
        "brier": round(bs, 6),
        "fiabilidad": round(fiabilidad, 6),
        "resolucion": round(resolucion, 6),
        "incertidumbre": round(incertidumbre, 6),
        "suma_verificacion": round(suma, 6),
        "residuo_intracaja": round(bs - suma, 6),
        "cajas": int(n_cajas),
        "tasa_base": round(base, 6),
    }


def dispersion_vs_error(ensamble: np.ndarray, observado) -> dict:
    """Compara la dispersion del ensamble con su error real.

    Un ensamble bien calibrado cumple, en promedio sobre muchos casos:

        desviacion_ensamble ~= error cuadratico medio de la media del ensamble

    (con el factor sqrt((m+1)/m) de Fortin et al. 2014). Si la razon es menor
    que 1 el ensamble esta SUB-dispersado: se cree mas seguro de lo que es, y
    eso es exactamente lo que no debe pasar en una capa de alerta.
    """
    x = np.asarray(ensamble, dtype=float)
    y = np.asarray(observado, dtype=float)
    m = x.shape[0]
    if m < 2:
        raise ValueError("se necesitan al menos 2 miembros")

    media = x.mean(axis=0)
    rmse = float(np.sqrt(np.nanmean((media - y) ** 2)))
    # Varianza del ensamble con correccion de muestra finita.
    var = np.nanmean(x.var(axis=0, ddof=1))
    dispersion = float(np.sqrt(var * (m + 1.0) / m))
    return {
        "rmse_media_ensamble": round(rmse, 6),
        "dispersion_ensamble": round(dispersion, 6),
        "razon_dispersion_error": round(dispersion / rmse, 4) if rmse > 0 else float("nan"),
        "diagnostico": _diagnostico_dispersion(dispersion / rmse if rmse > 0 else 1.0),
        "miembros": int(m),
    }


def _diagnostico_dispersion(razon: float) -> str:
    if razon < 0.8:
        return "sub-dispersado: el ensamble es sobreconfiado"
    if razon > 1.25:
        return "sobre-dispersado: el ensamble es demasiado timido"
    return "dispersion consistente con el error"


def tabla_contingencia(probabilidad, ocurrio, corte: float = 0.5) -> dict:
    """Aciertos, falsas alarmas y fallos al convertir la probabilidad en aviso.

    Es la traduccion operativa: alguien tiene que decidir a partir de que
    probabilidad se emite el aviso, y cada corte cambia el balance entre
    perderse un evento y dar una falsa alarma.
    """
    p = np.asarray(probabilidad, dtype=float).ravel()
    o = np.asarray(ocurrio, dtype=float).ravel()
    valido = np.isfinite(p) & np.isfinite(o)
    aviso = p[valido] >= corte
    paso = o[valido] > 0.5

    aciertos = int(np.sum(aviso & paso))
    falsas = int(np.sum(aviso & ~paso))
    fallos = int(np.sum(~aviso & paso))
    correctos = int(np.sum(~aviso & ~paso))

    def _div(a, b):
        return round(a / b, 4) if b else float("nan")

    return {
        "corte": corte,
        "aciertos": aciertos,
        "falsas_alarmas": falsas,
        "fallos": fallos,
        "negativos_correctos": correctos,
        "prob_deteccion": _div(aciertos, aciertos + fallos),
        "razon_falsas_alarmas": _div(falsas, falsas + correctos),
        "proporcion_falsas_alarmas": _div(falsas, aciertos + falsas),
        "amenaza_critica": _div(aciertos, aciertos + falsas + fallos),
    }
