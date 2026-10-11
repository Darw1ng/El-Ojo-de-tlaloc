"""Parametros climatologicos por celda.

El simulador estocastico no inventa el clima: necesita, para cada hexagono y
cada mes, cuatro cosas.

    1. Con que frecuencia llueve          -> probabilidad marginal de dia con lluvia
    2. Cuanto llueve cuando llueve        -> forma y escala de la Weibull
    3. Que temperatura hace               -> tmax y tmin medias
    4. Cuanta agua aguanta el suelo       -> capacidad de campo

Este modulo entrega esos parametros. Hoy los construye de forma SINTETICA a
partir de las normales climatologicas del puerto de Veracruz mas gradientes
espaciales (orografia y distancia a la costa). Eso basta para que el modelo
corra y se demuestre punta a punta, y NO es lo que se va a presentar como
verdad: la via de entrada de datos reales es `Climatologia.desde_normales()`,
que recibe las mismas 12 series mensuales y aplica los mismos gradientes, de
modo que enchufar CHIRPS, ERA5-Land o las normales de la CONAGUA es cambiar
doce listas de numeros, no reescribir el modelo.

Fuentes de los valores de referencia (normales mensuales del puerto, redondeadas):
    - Lluvia anual del orden de 1650 mm, concentrada de junio a octubre.
    - Alrededor de 115 dias con lluvia al ano.
    - Temporada seca de marzo a mayo, nortes de noviembre a febrero.
Ver docs/05-datos-y-nisar.md para el detalle de que dataset reemplaza a que
parametro.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .estadistica import weibull_media

MESES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)

# --- Normales mensuales de referencia (puerto de Veracruz, nivel del mar) ---

#: Fraccion de dias con lluvia (>= 1 mm) por mes.
FRAC_DIAS_LLUVIA = np.array(
    [0.13, 0.09, 0.07, 0.08, 0.17, 0.60, 0.63, 0.62, 0.67, 0.40, 0.23, 0.16]
)

#: Lluvia acumulada mensual, mm.
LLUVIA_MENSUAL_MM = np.array(
    [23.0, 14.0, 11.0, 18.0, 50.0, 290.0, 330.0, 310.0, 350.0, 170.0, 60.0, 30.0]
)

#: Temperatura maxima y minima media diaria, grados C.
TMAX_MENSUAL = np.array(
    [25.0, 26.0, 28.0, 30.0, 31.5, 31.5, 31.5, 32.0, 31.0, 30.0, 28.0, 26.0]
)
TMIN_MENSUAL = np.array(
    [19.0, 19.5, 21.5, 23.5, 25.0, 25.0, 24.5, 24.5, 24.0, 23.0, 21.5, 20.0]
)

#: Forma de la Weibull de intensidad. Menor que 1 = cola pesada. En temporada
#: convectiva (jun-oct) la cola es mas pesada que con los nortes de invierno.
WEIBULL_FORMA = np.array(
    [0.95, 0.95, 0.95, 0.92, 0.88, 0.80, 0.80, 0.80, 0.78, 0.82, 0.90, 0.95]
)

#: Exceso de persistencia de la cadena de Markov de ocurrencia (rho).
#: 0 = dias independientes; cerca de 1 = rachas largas. Para lluvia diaria en
#: clima tropical esta entre 0.3 y 0.5; en temporada de lluvias es mas alta.
RHO_PERSISTENCIA = np.array(
    [0.35, 0.35, 0.30, 0.30, 0.35, 0.45, 0.48, 0.48, 0.50, 0.42, 0.38, 0.35]
)

DIAS_POR_MES = np.array([31, 28.25, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])

# --- Geografia aproximada --------------------------------------------------

#: Linea de costa aproximada: lon de la costa para tres latitudes conocidas
#: (Chachalacas / puerto de Veracruz / Anton Lizardo). Entre ellas se
#: interpola linealmente. Es una aproximacion de trazo grueso, suficiente para
#: no pintar pronostico de suelo sobre el mar; la costa real se carga de
#: Natural Earth o del extracto de OSM (ver docs/05-datos-y-nisar.md).
_COSTA_LAT = np.array([18.95, 19.19, 19.40])
_COSTA_LON = np.array([-95.90, -96.09, -96.38])

#: Gradiente adiabatico del aire saturado, grados C por km de elevacion.
GRADIENTE_TERMICO_C_KM = 6.5

#: Realce orografico: cuanto sube la frecuencia y la intensidad de lluvia por
#: cada 1000 m de elevacion. Valores conservadores para el piedemonte central
#: de Veracruz, donde la lluvia anual pasa de ~1650 mm en la costa a mas de
#: 2000 mm en el piedemonte.
REALCE_FRECUENCIA_POR_KM = 0.45
REALCE_INTENSIDAD_POR_KM = 0.35


def lon_costa(lat):
    """Longitud aproximada de la linea de costa para una latitud dada."""
    return np.interp(np.asarray(lat, dtype=float), _COSTA_LAT, _COSTA_LON)


#: Escala del piedemonte: a que distancia de la costa se alcanzaria la cota
#: de 1400 m siguiendo el perfil sintetico. El valor es grande a proposito:
#: el area de interes es planicie costera casi completa (el ascenso de verdad
#: a la sierra empieza al oeste de 96.7 W, ya fuera del bbox), asi que dentro
#: del dominio la elevacion sintetica no pasa de unos 240 m.
ESCALA_PIEDEMONTE_KM = 150.0


def elevacion_sintetica(lat, lon):
    """Elevacion aproximada en metros, a partir de la distancia a la costa.

    PLACEHOLDER, y conservador por diseno: es preferible subestimar el relieve
    a inventar montanas que no existen en el dominio. El terreno real se carga
    de un DEM (SRTM 30 m o Copernicus GLO-30) pasando `elevacion_m` a
    `Climatologia.desde_normales()`; ver docs/05-datos-y-nisar.md.
    """
    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    # Grados al oeste de la costa -> km (1 grado de lon ~ 105 km a esta latitud).
    oeste_km = np.maximum(lon_costa(lat) - lon, 0.0) * 105.0
    return 1400.0 * np.power(np.clip(oeste_km / ESCALA_PIEDEMONTE_KM, 0.0, 1.0), 2.0)


@dataclass
class Climatologia:
    """Parametros por celda y mes. Todos los arrays son (n_celdas, 12)."""

    n_celdas: int
    es_tierra: np.ndarray          # (n,) bool
    elevacion_m: np.ndarray        # (n,) float
    dist_costa_km: np.ndarray      # (n,) float, negativa mar adentro
    prob_lluvia: np.ndarray        # (n, 12) probabilidad marginal de dia lluvioso
    p01: np.ndarray                # (n, 12) P(llueve hoy | ayer seco)
    p11: np.ndarray                # (n, 12) P(llueve hoy | ayer llovio)
    weibull_forma: np.ndarray      # (n, 12)
    weibull_escala: np.ndarray     # (n, 12) mm
    tmax_media: np.ndarray         # (n, 12) grados C
    tmin_media: np.ndarray         # (n, 12) grados C
    capacidad_suelo_mm: np.ndarray  # (n,) mm

    # --- construccion ------------------------------------------------------

    @classmethod
    def desde_normales(
        cls,
        malla,
        frac_dias_lluvia=FRAC_DIAS_LLUVIA,
        lluvia_mensual_mm=LLUVIA_MENSUAL_MM,
        tmax_mensual=TMAX_MENSUAL,
        tmin_mensual=TMIN_MENSUAL,
        weibull_forma=WEIBULL_FORMA,
        rho_persistencia=RHO_PERSISTENCIA,
        elevacion_m=None,
    ) -> "Climatologia":
        """Construye la climatologia por celda a partir de 12 series mensuales.

        Las series son las normales de un punto de referencia a nivel del mar
        (por defecto el puerto de Veracruz). Los gradientes espaciales que se
        aplican encima son: realce orografico de lluvia, gradiente termico por
        elevacion y amortiguamiento del rango diurno sobre el mar.

        Para calibrar con datos reales se pasan otras series y, si se tiene, el
        DEM en `elevacion_m` (array de largo n_celdas).
        """
        for nombre, serie in (
            ("frac_dias_lluvia", frac_dias_lluvia),
            ("lluvia_mensual_mm", lluvia_mensual_mm),
            ("tmax_mensual", tmax_mensual),
            ("tmin_mensual", tmin_mensual),
            ("weibull_forma", weibull_forma),
            ("rho_persistencia", rho_persistencia),
        ):
            if len(serie) != 12:
                raise ValueError("'{}' debe tener 12 valores".format(nombre))

        frac = np.asarray(frac_dias_lluvia, dtype=float)
        acum = np.asarray(lluvia_mensual_mm, dtype=float)
        tmax0 = np.asarray(tmax_mensual, dtype=float)
        tmin0 = np.asarray(tmin_mensual, dtype=float)
        forma0 = np.asarray(weibull_forma, dtype=float)
        rho = np.clip(np.asarray(rho_persistencia, dtype=float), 0.0, 0.95)

        if np.any(frac <= 0) or np.any(frac >= 1):
            raise ValueError("frac_dias_lluvia debe estar en (0, 1)")

        lat, lon = malla.lat, malla.lon
        n = malla.n_celdas

        # Geografia
        dist_costa_km = (lon_costa(lat) - lon) * 105.0
        es_tierra = dist_costa_km > 0.0
        elev = (elevacion_sintetica(lat, lon) if elevacion_m is None
                else np.asarray(elevacion_m, dtype=float))
        if elev.shape != (n,):
            raise ValueError("elevacion_m debe tener largo n_celdas")
        elev = np.where(es_tierra, elev, 0.0)
        elev_km = elev / 1000.0

        # --- Frecuencia de lluvia: realce orografico en espacio logit, para
        # que la probabilidad no se pase de 1 por mucho que suba el terreno.
        realce_f = 1.0 + REALCE_FRECUENCIA_POR_KM * elev_km   # (n,)
        logit0 = np.log(frac / (1.0 - frac))                  # (12,)
        logit = logit0[None, :] + np.log(realce_f)[:, None]
        prob = 1.0 / (1.0 + np.exp(-logit))
        prob = np.clip(prob, 1e-3, 0.95)

        # --- Cadena de Markov de ocurrencia, calibrada a esa probabilidad.
        # Con p01 = pi (1 - rho) y p11 = pi + (1 - pi) rho, la distribucion
        # estacionaria de la cadena es exactamente pi (se demuestra en
        # docs/03-modelo-estocastico.md y se verifica en los tests).
        p01 = prob * (1.0 - rho[None, :])
        p11 = prob + (1.0 - prob) * rho[None, :]

        # --- Intensidad: la escala sale de exigir que el acumulado mensual
        # cuadre con la normal. media_dia_lluvioso = acum / (dias * pi), y
        # para la Weibull media = escala * Gamma(1 + 1/forma).
        forma = np.repeat(forma0[None, :], n, axis=0)
        realce_i = 1.0 + REALCE_INTENSIDAD_POR_KM * elev_km
        media_obj = (acum / (DIAS_POR_MES * frac))[None, :] * realce_i[:, None]
        factor_gamma = weibull_media(forma0, 1.0)             # (12,)
        escala = media_obj / factor_gamma[None, :]

        # --- Temperatura: gradiente por elevacion; sobre el mar el rango
        # diurno se amortigua (inercia termica del agua).
        caida = (GRADIENTE_TERMICO_C_KM * elev_km)[:, None]
        tmax = tmax0[None, :] - caida
        tmin = tmin0[None, :] - caida
        rango = tmax - tmin
        amort = np.where(es_tierra, 1.0, 0.6)[:, None]
        medio = (tmax + tmin) / 2.0
        tmax = medio + rango * amort / 2.0
        tmin = medio - rango * amort / 2.0

        # --- Capacidad de agua del suelo: menos en pendiente (suelo delgado).
        cap = np.clip(150.0 - 60.0 * elev_km, 60.0, 180.0)
        cap = np.where(es_tierra, cap, np.nan)

        return cls(
            n_celdas=n,
            es_tierra=es_tierra,
            elevacion_m=elev,
            dist_costa_km=dist_costa_km,
            prob_lluvia=prob,
            p01=np.clip(p01, 1e-4, 0.99),
            p11=np.clip(p11, 1e-4, 0.99),
            weibull_forma=forma,
            weibull_escala=escala,
            tmax_media=tmax,
            tmin_media=tmin,
            capacidad_suelo_mm=cap,
        )

    @classmethod
    def sintetica(cls, malla) -> "Climatologia":
        """Atajo: climatologia por defecto de la zona de Veracruz."""
        return cls.desde_normales(malla)

    # --- consultas ---------------------------------------------------------

    def prob_estacionaria(self, mes: int):
        """Probabilidad marginal de dia con lluvia que implica la cadena.

        pi = p01 / (1 + p01 - p11). Debe coincidir con `prob_lluvia`; es la
        verificacion de que la calibracion de la cadena quedo bien.
        """
        i = _mes_idx(mes)
        return self.p01[:, i] / (1.0 + self.p01[:, i] - self.p11[:, i])

    def lluvia_mensual_esperada(self, mes: int):
        """Acumulado mensual que produce el modelo, mm. Para validar."""
        i = _mes_idx(mes)
        media_dia = weibull_media(self.weibull_forma[:, i], self.weibull_escala[:, i])
        return self.prob_lluvia[:, i] * DIAS_POR_MES[i] * media_dia

    def resumen(self) -> dict:
        """Resumen agregado, util para el panel de diagnostico del front."""
        tierra = self.es_tierra
        anual = sum(float(np.nanmean(self.lluvia_mensual_esperada(m)[tierra]))
                    for m in range(1, 13))
        return {
            "n_celdas": int(self.n_celdas),
            "celdas_tierra": int(tierra.sum()),
            "celdas_mar": int((~tierra).sum()),
            "elevacion_min_m": round(float(self.elevacion_m.min()), 1),
            "elevacion_max_m": round(float(self.elevacion_m.max()), 1),
            "lluvia_anual_media_mm": round(anual, 1),
            "dias_lluvia_anuales": round(
                float(sum(self.prob_lluvia[tierra, m].mean() * DIAS_POR_MES[m]
                          for m in range(12))), 1),
        }


def _mes_idx(mes: int) -> int:
    if not 1 <= int(mes) <= 12:
        raise ValueError("el mes debe estar entre 1 y 12")
    return int(mes) - 1
