"""NASA POWER como climatologia real, en lugar de la sintetica.

Que es POWER
------------
Prediction Of Worldwide Energy Resources: series meteorologicas por punto
derivadas de MERRA-2 (reanalisis de la NASA) y de GEOS. API abierta, sin
credenciales y sin llave. Es, por mucho, la fuente de la NASA mas facil de
enchufar, y la que mas rapido quita un placeholder del modelo.

Decision: datos DIARIOS, no las normales
----------------------------------------
POWER ofrece un endpoint de climatologia que devuelve las doce medias
mensuales. Es tentador y no alcanza: el modelo necesita **frecuencia de dias
con lluvia** e **intensidad en los dias que llueve**, y de una media mensual
no se pueden separar. 100 mm al mes pueden ser 20 dias de 5 mm o 2 dias de
50 mm, y para riesgo de inundacion son dos mundos distintos.

Asi que se bajan ~20 anos de datos diarios y la climatologia se calcula aqui:

    frac_dias_lluvia   fraccion de dias con al menos 1 mm, por mes
    lluvia_mensual_mm  acumulado medio mensual
    weibull_forma      ajustada por momentos a la intensidad observada
    rho_persistencia   P(llueve|llovio ayer) medida, convertida a exceso
    tmax/tmin          medias mensuales

Eso reemplaza las seis series que hoy estan escritas a mano en
climatologia.py, con la ventaja de que la persistencia y la forma de la cola
dejan de ser supuestos y pasan a ser mediciones.

Resolucion
----------
La nativa de MERRA-2 es ~0.5 x 0.625 grados, unos 50 x 65 km. El area de
interes (0.88 x 0.52 grados) cabe en dos o tres celdas nativas, asi que pedir
nueve puntos en rejilla 3x3 e interpolar NO inventa detalle: representa
exactamente lo que la fuente tiene. El detalle fino dentro del dominio lo
sigue aportando el gradiente orografico de climatologia.py.
"""

from __future__ import annotations

import datetime as dt
import math

import numpy as np

from .base import NIVEL_REANALISIS, CapaFuente, ErrorFuente, FuenteRemota, Procedencia

URL_DIARIA = "https://power.larc.nasa.gov/api/temporal/daily/point"

#: Parametros que se piden. Nombres de POWER.
PARAMETROS = ("PRECTOTCORR", "T2M_MAX", "T2M_MIN", "T2M", "RH2M", "WS10M",
              "ALLSKY_SFC_SW_DWN")

#: POWER marca los datos faltantes con este centinela.
SIN_DATO = -999.0

#: Umbral de "dia con lluvia", en mm.
#:
#: La convencion de la OMM es 1 mm, y con 1 mm POWER dice que en esta zona
#: llueve 195 dias al ano. Las normales del puerto de Veracruz dan entre 115 y
#: 130. La diferencia no es un error de POWER: es el **sesgo de llovizna** de
#: los reanalisis, documentado en MERRA-2 y en los demas: el modelo reparte la
#: precipitacion en demasiados dias con intensidad pequena en vez de
#: concentrarla en eventos.
#:
#: Medido sobre 21 anos en el centro del area:
#:
#:     umbral   dias/ano   % del acumulado que conserva
#:        1.0      195.1       97.8%
#:        2.0      158.5       94.6%
#:        3.5     ~122         ~89%
#:        5.0      101.3       83.2%
#:
#: Se usa 3.5 mm porque es el umbral que reproduce la frecuencia observada.
#: El acumulado NO se recorta: se pasa completo a la climatologia, que
#: redistribuye la misma masa de agua entre menos dias y con mas intensidad.
#: Conservar el agua importa mas que conservar la intensidad por evento
#: cuando lo que se calcula es escurrimiento, y el sesgo que queda va en
#: direccion conservadora (eventos algo mas intensos de lo observado).
UMBRAL_DIA_HUMEDO_MM = 3.5

#: Dias con lluvia al ano de referencia para esta zona (normales del puerto).
#: Se usa para calibrar el umbral con `calibrar_umbral_por_dias()`.
DIAS_LLUVIA_REFERENCIA = 122.0

DIAS_POR_MES_MEDIO = np.array(
    [31, 28.25, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31], dtype=float
)


class FuentePOWER(FuenteRemota):
    """Climatologia diaria de NASA POWER agregada a la malla."""

    nombre = "power"
    espera_entre_peticiones = 1.5

    def __init__(self, anio_inicio: int = 2005, anio_fin: int | None = None,
                 lado_rejilla: int = 3,
                 umbral_dia_humedo_mm: float = UMBRAL_DIA_HUMEDO_MM, **kw) -> None:
        super().__init__(**kw)
        self.umbral_dia_humedo_mm = float(umbral_dia_humedo_mm)
        self.anio_inicio = int(anio_inicio)
        # POWER va con unos dias de retraso; se pide hasta el anio pasado
        # completo para no toparse con meses incompletos.
        self.anio_fin = int(anio_fin) if anio_fin else dt.date.today().year - 1
        if self.anio_fin < self.anio_inicio:
            raise ValueError("anio_fin debe ser mayor o igual que anio_inicio")
        self.lado_rejilla = max(2, int(lado_rejilla))

    # --- descarga ---------------------------------------------------------

    def _puntos_rejilla(self, malla):
        """Rejilla de puntos sobre el bbox, a la resolucion de la fuente."""
        b = malla.bbox
        lats = np.linspace(b.lat_min, b.lat_max, self.lado_rejilla)
        lons = np.linspace(b.lon_min, b.lon_max, self.lado_rejilla)
        return [(float(la), float(lo)) for la in lats for lo in lons]

    def _serie_punto(self, lat: float, lon: float) -> dict:
        clave = "diaria|{:.4f}|{:.4f}|{}|{}|{}".format(
            lat, lon, self.anio_inicio, self.anio_fin, ",".join(PARAMETROS)
        )
        guardado = self._leer_cache(clave)
        if guardado is not None:
            return guardado

        consulta = (
            "{}?parameters={}&community=AG&longitude={:.4f}&latitude={:.4f}"
            "&start={}0101&end={}1231&format=JSON".format(
                URL_DIARIA, ",".join(PARAMETROS), lon, lat,
                self.anio_inicio, self.anio_fin,
            )
        )
        import json
        crudo = self._pedir(consulta, tiempo_limite=240.0)
        try:
            datos = json.loads(crudo)
        except json.JSONDecodeError:
            raise ErrorFuente("POWER devolvio algo que no es JSON") from None
        if "properties" not in datos:
            raise ErrorFuente(
                "POWER no devolvio datos para ({:.3f}, {:.3f}): {}".format(
                    lat, lon, str(datos)[:200]
                )
            )
        self._escribir_cache(clave, datos)
        return datos

    # --- climatologia -----------------------------------------------------

    def climatologia_punto(self, lat: float, lon: float) -> dict:
        """Series mensuales calculadas de los datos diarios de un punto."""
        datos = self._serie_punto(lat, lon)
        par = datos["properties"]["parameter"]

        fechas, lluvia, tmax, tmin = [], [], [], []
        for clave in sorted(par["PRECTOTCORR"]):
            p = par["PRECTOTCORR"][clave]
            if p is None or p <= SIN_DATO:
                continue
            fechas.append(dt.datetime.strptime(clave, "%Y%m%d").date())
            lluvia.append(float(p))
            tmax.append(_valor(par, "T2M_MAX", clave))
            tmin.append(_valor(par, "T2M_MIN", clave))

        if len(fechas) < 365:
            raise ErrorFuente(
                "POWER devolvio solo {} dias utiles para ({:.3f}, {:.3f})".format(
                    len(fechas), lat, lon
                )
            )

        lluvia = np.array(lluvia)
        tmax = np.array(tmax, dtype=float)
        tmin = np.array(tmin, dtype=float)
        meses = np.array([f.month for f in fechas])
        humedo = lluvia >= self.umbral_dia_humedo_mm

        frac = np.zeros(12)
        acum = np.zeros(12)
        forma = np.zeros(12)
        rho = np.zeros(12)
        tmax_m = np.zeros(12)
        tmin_m = np.zeros(12)
        n_anios = (self.anio_fin - self.anio_inicio + 1)

        # Secuencia de ayer para medir la persistencia; se marca el corte
        # cuando los dias no son consecutivos (hueco en la serie).
        consecutivo = np.zeros(len(fechas), dtype=bool)
        consecutivo[1:] = [
            (fechas[i] - fechas[i - 1]).days == 1 for i in range(1, len(fechas))
        ]

        for m in range(12):
            sel = meses == m + 1
            frac[m] = float(humedo[sel].mean())
            acum[m] = float(lluvia[sel].sum()) / n_anios
            tmax_m[m] = float(np.nanmean(tmax[sel]))
            tmin_m[m] = float(np.nanmean(tmin[sel]))

            intensidades = lluvia[sel & humedo]
            forma[m] = _weibull_forma_por_cuantiles(intensidades)

            # Persistencia: P(humedo hoy | humedo ayer) medida.
            hoy = sel & consecutivo
            ayer_humedo = np.zeros(len(fechas), dtype=bool)
            ayer_humedo[1:] = humedo[:-1]
            cond = hoy & ayer_humedo
            if cond.sum() > 30:
                p11 = float(humedo[cond].mean())
                pi = frac[m]
                # Invertir la parametrizacion: p11 = pi + (1-pi) rho
                rho[m] = float(np.clip((p11 - pi) / max(1e-6, 1.0 - pi), 0.0, 0.9))
            else:
                rho[m] = 0.35

        return {
            "lat": lat, "lon": lon,
            "anios": n_anios,
            "dias_utiles": len(fechas),
            "frac_dias_lluvia": frac,
            "lluvia_mensual_mm": acum,
            "weibull_forma": forma,
            "rho_persistencia": rho,
            "tmax_mensual": tmax_m,
            "tmin_mensual": tmin_m,
            "lluvia_anual_mm": float(acum.sum()),
            "dias_lluvia_anuales": float((frac * DIAS_POR_MES_MEDIO).sum()),
        }

    def calibrar_umbral_por_dias(self, malla,
                                 dias_objetivo: float = DIAS_LLUVIA_REFERENCIA,
                                 candidatos=None) -> float:
        """Busca el umbral de dia humedo que reproduce `dias_objetivo` al ano.

        Es correccion de frecuencia (una forma simple de quantile mapping):
        el reanalisis acierta cuanta agua cae y se equivoca en cuantos dias la
        reparte, asi que se corrige la frecuencia y se conserva la masa.

        Devuelve el umbral y lo deja puesto en la instancia.
        """
        b = malla.bbox
        lat = (b.lat_min + b.lat_max) / 2.0
        lon = (b.lon_min + b.lon_max) / 2.0
        datos = self._serie_punto(lat, lon)
        par = datos["properties"]["parameter"]["PRECTOTCORR"]
        ll = np.array([v for v in par.values()
                       if v is not None and v > SIN_DATO], dtype=float)
        if ll.size < 365:
            raise ErrorFuente("serie demasiado corta para calibrar el umbral")
        anios = max(1.0, ll.size / 365.25)

        if candidatos is None:
            candidatos = np.arange(0.5, 12.01, 0.1)
        mejor, mejor_error = self.umbral_dia_humedo_mm, float("inf")
        for u in candidatos:
            dias = float((ll >= u).sum()) / anios
            error = abs(dias - dias_objetivo)
            if error < mejor_error:
                mejor, mejor_error = float(u), error
        self.umbral_dia_humedo_mm = mejor
        return mejor

    def series_para_malla(self, malla) -> dict:
        """Climatologia del punto representativo del area, mas el campo por celda.

        Devuelve las seis series mensuales que consume
        `Climatologia.desde_normales()`, promediadas sobre la rejilla, y
        ademas las capas por celda interpoladas para el expediente.
        """
        puntos = self._puntos_rejilla(malla)
        climas = []
        for lat, lon in puntos:
            try:
                climas.append(self.climatologia_punto(lat, lon))
            except ErrorFuente:
                continue
        if not climas:
            raise ErrorFuente(
                "POWER no devolvio datos para ningun punto de la rejilla"
            )

        def promedio(clave):
            return np.mean([c[clave] for c in climas], axis=0)

        series = {
            "frac_dias_lluvia": promedio("frac_dias_lluvia"),
            "lluvia_mensual_mm": promedio("lluvia_mensual_mm"),
            "weibull_forma": promedio("weibull_forma"),
            "rho_persistencia": promedio("rho_persistencia"),
            "tmax_mensual": promedio("tmax_mensual"),
            "tmin_mensual": promedio("tmin_mensual"),
        }

        # Interpolacion por distancia inversa a los centros de hexagono.
        lats = np.array([c["lat"] for c in climas])
        lons = np.array([c["lon"] for c in climas])
        anual = np.array([c["lluvia_anual_mm"] for c in climas])
        dias = np.array([c["dias_lluvia_anuales"] for c in climas])

        proc = Procedencia(
            fuente="NASA POWER (MERRA-2)",
            nivel=NIVEL_REANALISIS,
            resolucion_nativa="~0.5 x 0.625 grados (50 x 65 km)",
            cadencia="diaria, {}-{}".format(self.anio_inicio, self.anio_fin),
            licencia="dominio publico (NASA)",
            atribucion="Datos de NASA POWER (Prediction Of Worldwide Energy Resources)",
            url="https://power.larc.nasa.gov/",
            nota=("climatologia calculada aqui a partir de {} anos de datos "
                  "diarios en {} puntos de rejilla, con umbral de dia humedo "
                  "de {:.1f} mm para corregir el sesgo de llovizna del "
                  "reanalisis. La temperatura viene de una celda nativa que "
                  "mezcla mar y tierra, asi que la maxima sale unos 3 C por "
                  "debajo de la de una estacion costera".format(
                      climas[0]["anios"], len(climas),
                      self.umbral_dia_humedo_mm)),
        )

        capas = {
            "lluvia_anual_power_mm": CapaFuente(
                "lluvia_anual_power_mm",
                _idw(malla, lats, lons, anual), "mm/ano", proc),
            "dias_lluvia_power": CapaFuente(
                "dias_lluvia_power",
                _idw(malla, lats, lons, dias), "dias/ano", proc),
        }
        # Una fuente que conoce sus propios sesgos vale mucho mas que una que
        # entrega numeros sin contexto. Esto viaja hasta la API y la interfaz.
        advertencias = [
            {
                "variable": "weibull_forma",
                "sesgo": "cola subestimada",
                "detalle": (
                    "MERRA-2 tiene celdas de ~50 x 65 km, asi que suaviza los "
                    "maximos: un evento convectivo de 150 mm sobre 20 km2 se "
                    "diluye en 3000 km2. La forma medida ({:.2f} a {:.2f}) "
                    "queda por encima del 0.7-0.9 que reporta la literatura "
                    "para lluvia diaria tropical, lo que da una cola mas "
                    "ligera que la real."
                ).format(float(series["weibull_forma"].min()),
                         float(series["weibull_forma"].max())),
                "como_se_corrige": "GPM IMERG (0.1 grados, 30 min) o datos de estacion",
            },
            {
                "variable": "frac_dias_lluvia",
                "sesgo": "sesgo de llovizna, ya corregido",
                "detalle": (
                    "Con el umbral de 1 mm de la OMM, POWER daba 195 dias de "
                    "lluvia al ano contra los 115-130 de las normales. Se "
                    "corrigio subiendo el umbral de dia humedo a {:.1f} mm, "
                    "conservando el acumulado completo."
                ).format(self.umbral_dia_humedo_mm),
                "como_se_corrige": "ya aplicado",
            },
            {
                "variable": "tmax_mensual",
                "sesgo": "maxima subestimada",
                "detalle": (
                    "La celda nativa mezcla mar y tierra y el mar amortigua: "
                    "la maxima sale unos 3 C por debajo de una estacion "
                    "costera. El PATRON estacional si es correcto, y de hecho "
                    "corrige un error de la climatologia sintetica: el pico "
                    "esta en mayo, antes de que la nubosidad de la temporada "
                    "de lluvias baje la maxima, no en agosto."
                ),
                "como_se_corrige": "estacion del SMN, o MODIS LST para el patron espacial",
            },
        ]
        return {"series": series, "capas": capas, "puntos": climas,
                "procedencia": proc, "advertencias": advertencias}


# --- utilidades ------------------------------------------------------------


def _valor(par, nombre, clave) -> float:
    v = par.get(nombre, {}).get(clave)
    if v is None or v <= SIN_DATO:
        return float("nan")
    return float(v)


def _weibull_forma_por_cuantiles(muestras, p_bajo=0.5, p_alto=0.99) -> float:
    """Forma de la Weibull ajustada por dos cuantiles. Solucion cerrada.

    Para una Weibull, x_p = escala * (-ln(1-p))^(1/k), asi que la razon de dos
    cuantiles no depende de la escala:

        x_alto / x_bajo = [ ln(1-p_alto) / ln(1-p_bajo) ]^(1/k)

        k = ln( ln(1-p_alto)/ln(1-p_bajo) ) / ln( x_alto / x_bajo )

    POR QUE NO MOMENTOS. El metodo de momentos sobre intensidades truncadas
    por el umbral de dia humedo da una forma sesgada hacia arriba: recortar la
    parte baja reduce el coeficiente de variacion y eso se traduce en una cola
    mas ligera de la real. Medido en esta serie: momentos daba k = 1.0 a 1.9 y
    cuantiles da k = 0.7 a 1.0, que es el rango que reporta la literatura para
    lluvia diaria tropical.

    Para riesgo de inundacion lo que importa es la cola alta, asi que ajustar
    con el percentil 99 es la eleccion correcta: preserva justo la parte de la
    distribucion con la que se decide.
    """
    x = np.asarray(muestras, dtype=float)
    x = x[np.isfinite(x) & (x > 0)]
    if x.size < 30:
        return 0.85
    x_bajo = float(np.percentile(x, p_bajo * 100.0))
    x_alto = float(np.percentile(x, p_alto * 100.0))
    if not (x_alto > x_bajo > 0):
        return _weibull_forma_por_momentos(x)
    razon_p = math.log(1 - p_alto) / math.log(1 - p_bajo)
    k = math.log(razon_p) / math.log(x_alto / x_bajo)
    if not np.isfinite(k) or k <= 0:
        return _weibull_forma_por_momentos(x)
    return float(np.clip(k, 0.4, 3.0))


def _weibull_forma_por_momentos(muestras) -> float:
    """Forma de la Weibull ajustada por el metodo de momentos.

    El coeficiente de variacion de una Weibull depende solo de la forma:

        CV(k) = sqrt( G(1+2/k) / G(1+1/k)^2 - 1 )

    y es monotono decreciente en k, asi que se invierte por biseccion. Se usa
    momentos y no maxima verosimilitud porque no hace falta scipy y porque con
    miles de dias la diferencia entre los dos estimadores es menor que la
    incertidumbre del propio dato de reanalisis.

    Lluvia diaria tropical: se espera k entre 0.6 y 1.0 (cola pesada).
    """
    x = np.asarray(muestras, dtype=float)
    x = x[np.isfinite(x) & (x > 0)]
    if x.size < 30:
        return 0.85   # el valor tipico de lluvia diaria tropical
    cv = float(x.std(ddof=1) / x.mean())
    if not np.isfinite(cv) or cv <= 0:
        return 0.85

    def cv_de(k: float) -> float:
        return math.sqrt(
            max(1e-12, math.gamma(1 + 2 / k) / math.gamma(1 + 1 / k) ** 2 - 1)
        )

    lo, hi = 0.25, 4.0
    if cv > cv_de(lo):
        return lo
    if cv < cv_de(hi):
        return hi
    for _ in range(60):
        medio = (lo + hi) / 2
        if cv_de(medio) > cv:
            lo = medio
        else:
            hi = medio
    return (lo + hi) / 2


def _idw(malla, lats, lons, valores, potencia: float = 2.0):
    """Interpolacion por distancia inversa a los centros de hexagono."""
    from ..geo import haversine_km

    salida = np.zeros(malla.n_celdas)
    for i in range(malla.n_celdas):
        d = np.asarray(haversine_km(malla.lat[i], malla.lon[i], lats, lons),
                       dtype=float)
        if np.any(d < 1e-6):
            salida[i] = float(valores[int(np.argmin(d))])
            continue
        w = 1.0 / np.power(d, potencia)
        salida[i] = float((w * valores).sum() / w.sum())
    return salida
