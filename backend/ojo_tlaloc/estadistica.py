"""Primitivas estadisticas del modelo, con numpy y nada mas.

No se usa scipy a proposito: el backend tiene que arrancar en una maquina
limpia y en el contenedor del hackathon sin compilar nada. Lo que se necesita
de scipy.stats son cuatro funciones y las cuatro tienen forma cerrada o una
aproximacion racional publicada y verificable:

    norm_cdf   erfc de Numerical Recipes (error fraccional < 1.2e-7)
    norm_ppf   algoritmo de Acklam / Wichura AS241 (error relativo ~1.15e-9)
    weibull    CDF e inversa en forma cerrada
    campo      Cholesky de la covarianza (numpy.linalg)

Las tres primeras se validan contra math.erfc y contra identidades en
tests/test_estadistica.py.
"""

from __future__ import annotations

import numpy as np

# --- Normal estandar -------------------------------------------------------

# Coeficientes de la erfc de Numerical Recipes (Press et al., 2.ed, 6.2).
_ERFC_COEF = (
    -1.26551223, 1.00002368, 0.37409196, 0.09678418, -0.18628806,
    0.27886807, -1.13520398, 1.48851587, -0.82215223, 0.17087277,
)


def erfc(x):
    """Funcion de error complementaria, vectorizada. Error fraccional < 1.2e-7."""
    x = np.asarray(x, dtype=float)
    z = np.abs(x)
    t = 2.0 / (2.0 + z)
    # Horner sobre el polinomio en t; el primer coeficiente es el termino
    # constante y va dentro del exponente junto con -z^2.
    poly = _ERFC_COEF[-1]
    for c in reversed(_ERFC_COEF[:-1]):
        poly = c + t * poly
    res = t * np.exp(-z * z + poly)
    return np.where(x >= 0.0, res, 2.0 - res)


def norm_cdf(x):
    """Phi(x): probabilidad acumulada de la normal estandar."""
    return 0.5 * erfc(-np.asarray(x, dtype=float) / np.sqrt(2.0))


# Coeficientes del algoritmo de Acklam para la inversa de la normal.
_A = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
      1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
_B = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
      6.680131188771972e+01, -1.328068155288572e+01)
_C = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
      -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00)
_D = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
      3.754408661907416e+00)

_P_BAJO = 0.02425
_P_ALTO = 1.0 - _P_BAJO


def norm_ppf(p):
    """Phi^-1(p): cuantil de la normal estandar. Error relativo ~1.15e-9.

    p=0 devuelve -inf y p=1 devuelve +inf; fuera de [0, 1] devuelve nan.
    """
    p = np.asarray(p, dtype=float)
    salida = np.full(p.shape, np.nan, dtype=float)

    cola_baja = (p > 0.0) & (p < _P_BAJO)
    centro = (p >= _P_BAJO) & (p <= _P_ALTO)
    cola_alta = (p > _P_ALTO) & (p < 1.0)

    if np.any(cola_baja):
        q = np.sqrt(-2.0 * np.log(p[cola_baja]))
        salida[cola_baja] = (
            (((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5])
            / ((((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1.0)
        )
    if np.any(centro):
        q = p[centro] - 0.5
        r = q * q
        salida[centro] = (
            (((((_A[0] * r + _A[1]) * r + _A[2]) * r + _A[3]) * r + _A[4]) * r + _A[5]) * q
            / (((((_B[0] * r + _B[1]) * r + _B[2]) * r + _B[3]) * r + _B[4]) * r + 1.0)
        )
    if np.any(cola_alta):
        q = np.sqrt(-2.0 * np.log(1.0 - p[cola_alta]))
        salida[cola_alta] = -(
            (((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5])
            / ((((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1.0)
        )

    salida = np.where(p == 0.0, -np.inf, salida)
    salida = np.where(p == 1.0, np.inf, salida)
    return salida


# --- Weibull ---------------------------------------------------------------
#
# La intensidad de lluvia diaria (dado que llueve) se modela Weibull en vez de
# Gamma por dos razones:
#   1. CDF e inversa en forma cerrada -> se puede acoplar al campo espacial con
#      una copula gaussiana sin necesitar la inversa de la gamma incompleta.
#   2. Con forma k < 1 reproduce la cola pesada de la lluvia convectiva, que es
#      justo lo que importa para el riesgo de inundacion.
# Wilks (1999) compara gamma, Weibull y exponencial mixta para lluvia diaria y
# las tres ajustan de forma comparable; la Weibull gana en costo.


def weibull_ppf(u, forma, escala):
    """Inversa de la Weibull: F^-1(u) = escala * (-ln(1-u))^(1/forma)."""
    u = np.clip(np.asarray(u, dtype=float), 1e-12, 1.0 - 1e-12)
    return escala * np.power(-np.log1p(-u), 1.0 / forma)


def weibull_cdf(x, forma, escala):
    """F(x) = 1 - exp(-(x/escala)^forma)."""
    x = np.maximum(np.asarray(x, dtype=float), 0.0)
    return -np.expm1(-np.power(x / escala, forma))


_gamma_vec = np.vectorize(__import__("math").gamma, otypes=[float])


def weibull_media(forma, escala):
    """Media de la Weibull: escala * Gamma(1 + 1/forma). Se usa al calibrar."""
    forma = np.asarray(forma, dtype=float)
    return np.asarray(escala, dtype=float) * _gamma_vec(1.0 + 1.0 / forma)


# --- Campo aleatorio espacialmente correlacionado --------------------------


class CampoEspacial:
    """Generador de campos gaussianos con correlacion espacial y temporal.

    El modelo necesita que la lluvia de celdas vecinas este correlacionada: una
    tormenta cubre decenas de kilometros, no una celda aislada. Se usa un campo
    gaussiano latente con covarianza exponencial sobre la distancia entre
    centros de hexagono:

        Cov(i, j) = exp(-d_ij / L)

    L es la longitud de correlacion en km (para precipitacion diaria
    convectiva, del orden de 20-40 km). Se factoriza con Cholesky una vez:

        Sigma = A A^T    ->    w = A z   con z ~ N(0, I)

    da un vector con exactamente esa correlacion. La persistencia dia a dia se
    mete con un AR(1) sobre el campo:

        w_t = phi w_{t-1} + sqrt(1 - phi^2) A z_t

    que conserva la varianza marginal en 1 (campo estacionario), de modo que
    los umbrales calibrados en unidades de normal estandar siguen siendo
    validos en todo el horizonte.

    Costo: Cholesky es O(n^3). Con n = 221 celdas son ~4 ms. A partir de unos
    4000 hexagonos hay que pasar a descomposicion espectral truncada; el tope
    esta en config.MAX_CELDAS.
    """

    def __init__(
        self,
        distancias_km,
        longitud_correlacion_km: float = 30.0,
        persistencia: float = 0.0,
        jitter: float = 1e-8,
    ) -> None:
        d = np.asarray(distancias_km, dtype=float)
        if d.ndim != 2 or d.shape[0] != d.shape[1]:
            raise ValueError("distancias_km debe ser una matriz cuadrada")
        if longitud_correlacion_km <= 0:
            raise ValueError("la longitud de correlacion debe ser positiva")
        if not (0.0 <= persistencia < 1.0):
            raise ValueError("la persistencia debe estar en [0, 1)")

        self.n = d.shape[0]
        self.longitud_correlacion_km = float(longitud_correlacion_km)
        self.persistencia = float(persistencia)

        sigma = np.exp(-d / longitud_correlacion_km)
        # Jitter creciente: la exponencial es definida positiva en teoria, pero
        # con celdas muy cercanas la matriz queda mal condicionada en float64.
        for intento in range(8):
            try:
                self._factor = np.linalg.cholesky(
                    sigma + np.eye(self.n) * jitter * (10.0 ** intento)
                )
                break
            except np.linalg.LinAlgError:
                continue
        else:
            raise np.linalg.LinAlgError(
                "no se pudo factorizar la covarianza espacial; "
                "revisa que no haya celdas duplicadas"
            )

    def muestra(self, rng, n_muestras: int = 1):
        """Campos independientes sin correlacion temporal. (n_muestras, n)."""
        z = rng.standard_normal((self.n, n_muestras))
        return (self._factor @ z).T

    def serie(self, rng, n_pasos: int, estado_inicial=None):
        """Serie temporal AR(1) de campos correlacionados. (n_pasos, n).

        `estado_inicial` permite continuar una corrida previa; si es None se
        arranca del equilibrio estacionario (una muestra del campo).
        """
        phi = self.persistencia
        w = (self.muestra(rng, 1)[0] if estado_inicial is None
             else np.asarray(estado_inicial, dtype=float))
        if w.shape != (self.n,):
            raise ValueError("estado_inicial no coincide con el tamano del campo")

        salida = np.empty((n_pasos, self.n), dtype=float)
        innov = np.sqrt(1.0 - phi * phi)
        for t in range(n_pasos):
            w = phi * w + innov * self.muestra(rng, 1)[0]
            salida[t] = w
        return salida
