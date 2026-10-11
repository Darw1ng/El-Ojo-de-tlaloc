"""Asimilacion de humedad de suelo observada por radar (NISAR).

Por que esto es el centro del proyecto y no un adorno
-----------------------------------------------------
NISAR no mide la lluvia de manana. Mide el estado de la superficie hoy: entre
otras cosas, la humedad del suelo, con banda L, cada 12 dias, de dia o de
noche y a traves de las nubes. Esa es justamente la condicion inicial que le
falta a cualquier pronostico de inundacion:

    60 mm de lluvia sobre suelo seco      -> se infiltran
    60 mm de lluvia sobre suelo saturado  -> corren al rio

Es la misma lluvia y no es el mismo riesgo. El modelo estocastico propone la
lluvia; el radar dice sobre que suelo va a caer. Sin la asimilacion, la
humedad inicial sale del calentamiento del modelo, que arrastra el error
acumulado de semanas.

Metodo
------
Filtro de Kalman de ensamble (EnKF) escalar por celda, con observaciones
perturbadas:

    K       = var_modelo / (var_modelo + var_obs)
    S_i^+   = S_i + K (y + eps_i - S_i),   eps_i ~ N(0, var_obs)

La perturbacion de la observacion es lo que mantiene la dispersion del
ensamble correcta despues de actualizar; sin ella el ensamble colapsa (todos los
miembros terminan en el mismo valor) y el pronostico se vuelve
sobreconfiado.

El dato de NISAR llega como humedad volumetrica (m3/m3) y el modelo trabaja
en saturacion relativa (0-1), asi que hay una conversion que depende de la
textura del suelo. Esa conversion es la fuente de error mas grande de toda
la cadena y esta explicita en `volumetrica_a_saturacion`.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np

#: Incertidumbre objetivo del producto de humedad de suelo de NISAR, en
#: saturacion relativa equivalente. El requisito de mision de NISAR para
#: humedad de suelo es del orden de 0.06 m3/m3; con una porosidad tipica de
#: 0.45 eso equivale a ~0.13 de saturacion relativa.
SIGMA_OBS_DEFECTO = 0.13

#: Contenido de agua residual y de saturacion por textura (m3/m3). Valores de
#: tabla de Rawls/Carsel-Parrish, los que usa cualquier modelo de suelo.
TEXTURAS = {
    "arena":          {"residual": 0.045, "saturacion": 0.43},
    "franco_arenoso": {"residual": 0.065, "saturacion": 0.41},
    "franco":         {"residual": 0.078, "saturacion": 0.43},
    "franco_arcilloso": {"residual": 0.095, "saturacion": 0.41},
    "arcilla":        {"residual": 0.068, "saturacion": 0.38},
}
TEXTURA_DEFECTO = "franco"


def volumetrica_a_saturacion(theta, textura: str = TEXTURA_DEFECTO):
    """Humedad volumetrica (m3/m3) -> saturacion relativa (0-1).

        S = (theta - theta_res) / (theta_sat - theta_res)

    OJO: esta conversion necesita la textura del suelo de cada celda. Usar una
    textura unica para todo el dominio, como se hace por defecto aqui, mete un
    sesgo sistematico que puede llegar a 0.15 de saturacion en suelos muy
    arcillosos o muy arenosos. Con el mapa de suelos (INEGI serie edafologica
    o SoilGrids) se pasa la textura por celda y el sesgo se va.
    """
    if textura not in TEXTURAS:
        raise ValueError(
            "textura desconocida '{}'; validas: {}".format(
                textura, ", ".join(sorted(TEXTURAS))
            )
        )
    t = TEXTURAS[textura]
    theta = np.asarray(theta, dtype=float)
    s = (theta - t["residual"]) / (t["saturacion"] - t["residual"])
    return np.clip(s, 0.0, 1.0)


@dataclass
class ObservacionHumedad:
    """Humedad de suelo observada, ya agregada a la malla.

    valores   (n_celdas,) saturacion relativa 0-1; NaN donde no hay dato
    sigma     escalar o (n_celdas,) incertidumbre en saturacion relativa
    fecha     ISO, solo informativa
    fuente    de donde viene el dato (NISAR GCOV, estacion, sintetico)
    """

    valores: np.ndarray
    sigma: object = SIGMA_OBS_DEFECTO
    fecha: str = ""
    fuente: str = "NISAR"

    def __post_init__(self) -> None:
        self.valores = np.asarray(self.valores, dtype=float)
        if self.valores.ndim != 1:
            raise ValueError("valores debe ser un array (n_celdas,)")
        finitos = np.isfinite(self.valores)
        if np.any(self.valores[finitos] < 0.0) or np.any(self.valores[finitos] > 1.0):
            raise ValueError("la saturacion observada debe estar en [0, 1]")

    @property
    def n_observadas(self) -> int:
        return int(np.isfinite(self.valores).sum())


def agregar_a_malla(malla, lat, lon, valores, minimo_pixeles: int = 1):
    """Promedia observaciones puntuales (pixeles de radar) a cada hexagono.

    Asigna cada punto al hexagono de centro mas cercano, que para una malla
    hexagonal regular equivale a la celda de Voronoi (el hexagono es
    exactamente su propia celda de Voronoi; esa es otra razon para usar
    hexagonos). Devuelve (promedios, conteo); promedio NaN donde no se
    alcanzo `minimo_pixeles`.
    """
    lat = np.asarray(lat, dtype=float).ravel()
    lon = np.asarray(lon, dtype=float).ravel()
    valores = np.asarray(valores, dtype=float).ravel()
    if not (lat.shape == lon.shape == valores.shape):
        raise ValueError("lat, lon y valores deben tener el mismo largo")

    x, y = malla.proy.a_metros(lat, lon)
    puntos = np.stack([x, y], axis=1)

    suma = np.zeros(malla.n_celdas)
    conteo = np.zeros(malla.n_celdas, dtype=int)

    # Por bloques para no armar una matriz (n_puntos x n_celdas) completa.
    bloque = 20000
    for ini in range(0, len(puntos), bloque):
        trozo = puntos[ini:ini + bloque]
        d2 = ((trozo[:, None, :] - malla.centros_xy[None, :, :]) ** 2).sum(axis=2)
        cercano = np.argmin(d2, axis=1)
        v = valores[ini:ini + bloque]
        ok = np.isfinite(v)
        np.add.at(suma, cercano[ok], v[ok])
        np.add.at(conteo, cercano[ok], 1)

    promedio = np.full(malla.n_celdas, np.nan)
    suficiente = conteo >= max(1, minimo_pixeles)
    promedio[suficiente] = suma[suficiente] / conteo[suficiente]
    return promedio, conteo


def asimilar(ensamble_s: np.ndarray, obs: ObservacionHumedad, rng=None) -> dict:
    """Actualiza un ensamble de humedad de suelo con una observacion.

    ensamble_s  (n_miembros, n_celdas) saturacion previa del modelo
    obs         observacion ya agregada a la malla
    rng         generador; si es None se usa uno nuevo (no reproducible)

    Devuelve dict con el ensamble actualizado y el diagnostico de la
    asimilacion, que es lo que hay que ensenar para que el jurado vea que el
    dato de radar de verdad movio el pronostico.
    """
    s = np.asarray(ensamble_s, dtype=float)
    if s.ndim != 2:
        raise ValueError("ensamble_s debe ser (n_miembros, n_celdas)")
    m, n = s.shape
    if obs.valores.shape != (n,):
        raise ValueError("la observacion no coincide con el numero de celdas")

    rng = np.random.default_rng() if rng is None else rng

    sigma = np.broadcast_to(np.asarray(obs.sigma, dtype=float), (n,)).astype(float)
    if np.any(sigma <= 0):
        raise ValueError("sigma de la observacion debe ser positiva")

    var_obs = sigma ** 2
    # Varianza del modelo: la dispersion del propio ensamble. Si el ensamble
    # esta colapsado (varianza ~0) la ganancia tiende a 0 y la observacion no
    # entra: eso es correcto formalmente pero suele indicar sub-dispersion, asi
    # que se reporta en el diagnostico.
    # Las columnas de mar son NaN completo: nanvar/nanmean avisan por slice
    # vacio y devuelven NaN, que es justo lo que se quiere. Se silencia el
    # aviso porque es esperado, no un problema.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        var_mod = np.nanvar(s, axis=0, ddof=1) if m > 1 else np.zeros(n)
        media_previa = np.nanmean(s, axis=0)

    hay_obs = np.isfinite(obs.valores) & np.isfinite(media_previa)
    k = np.zeros(n)
    k[hay_obs] = var_mod[hay_obs] / (var_mod[hay_obs] + var_obs[hay_obs])

    actualizado = s.copy()
    if np.any(hay_obs):
        idx = np.where(hay_obs)[0]
        eps = rng.normal(0.0, sigma[idx], size=(m, idx.size))
        y = obs.valores[idx][None, :]
        actualizado[:, idx] = s[:, idx] + k[idx][None, :] * (y + eps - s[:, idx])
        actualizado[:, idx] = np.clip(actualizado[:, idx], 0.0, 1.0)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        media_post = np.nanmean(actualizado, axis=0)
        var_post = np.nanvar(actualizado, axis=0, ddof=1) if m > 1 else np.zeros(n)

    with np.errstate(invalid="ignore", divide="ignore"):
        reduccion = np.where(var_mod > 0, 1.0 - var_post / var_mod, 0.0)

    return {
        "ensamble": actualizado,
        "diagnostico": {
            "fuente": obs.fuente,
            "fecha": obs.fecha,
            "celdas_observadas": int(hay_obs.sum()),
            "celdas_totales": int(n),
            "ganancia_media": _redondea(np.nanmean(k[hay_obs]) if hay_obs.any() else 0.0),
            "incremento_medio": _redondea(
                np.nanmean((media_post - media_previa)[hay_obs]) if hay_obs.any() else 0.0
            ),
            "incremento_absoluto_max": _redondea(
                np.nanmax(np.abs(media_post - media_previa)[hay_obs])
                if hay_obs.any() else 0.0
            ),
            "reduccion_varianza_media": _redondea(
                np.nanmean(reduccion[hay_obs]) if hay_obs.any() else 0.0
            ),
            "sigma_obs_media": _redondea(np.mean(sigma)),
            "dispersion_previa_media": _redondea(np.sqrt(np.nanmean(var_mod))),
            "dispersion_posterior_media": _redondea(np.sqrt(np.nanmean(var_post))),
        },
    }


def observacion_sintetica(malla, clima, fecha, saturacion_base=None, sesgo=0.0,
                          ruido=0.03, cobertura=0.85, semilla=None):
    """Genera una observacion falsa de humedad, para probar la cadena.

    Mientras no haya granulos de NISAR descargados (los datos de banda L
    provisionales empiezan el 20-jul-2026, ver docs/05-datos-y-nisar.md), esta
    funcion permite demostrar el ciclo completo: observar, asimilar, pronosticar.
    Esta marcada como sintetica en `fuente` para que nunca se presente como dato
    real por accidente.

    cobertura simula los huecos del radar (agua, vegetacion densa, sombra de
    radar): esa fraccion de celdas de tierra se queda sin dato.
    """
    rng = np.random.default_rng(semilla)
    n = malla.n_celdas
    base = (0.5 if saturacion_base is None else float(saturacion_base))
    # Un gradiente suave oeste-este mas ruido, para que no sea un valor plano.
    gradiente = 0.15 * (malla.lon - malla.lon.mean()) / (
        malla.lon.max() - malla.lon.min()
    )
    valores = base + sesgo - gradiente + rng.normal(0.0, ruido, n)
    valores = np.clip(valores, 0.0, 1.0)
    sin_dato = (rng.random(n) > cobertura) | (~clima.es_tierra)
    valores[sin_dato] = np.nan
    return ObservacionHumedad(
        valores=valores,
        sigma=SIGMA_OBS_DEFECTO,
        fecha=str(fecha),
        fuente="sintetico (no es NISAR)",
    )


def _redondea(v) -> float:
    v = float(v)
    return 0.0 if not np.isfinite(v) else round(v, 4)
