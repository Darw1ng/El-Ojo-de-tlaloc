"""Simulador estocastico del clima sobre la malla hexagonal.

Que es y que no es
------------------
NO es un modelo numerico de la atmosfera. No resuelve ecuaciones de fluidos ni
asimila condiciones de frontera de un modelo global: eso no cabe en un
hackathon ni corre en un servidor chico.

SI es un generador estocastico de clima ("weather generator") espacialmente
coherente, de la familia Richardson/WGEN pero con dos cosas que los
generadores clasicos no tienen: campo latente gaussiano para que las celdas
vecinas esten correlacionadas, y asimilacion del estado del suelo observado
por radar. Produce, por celda y por dia, un ensamble de trayectorias posibles
del que se sacan probabilidades: "P(lluvia > 50 mm el jueves en esta celda) =
0.23". Eso es la salida util: no un numero, una distribucion.

Estructura del modelo
---------------------
Para el dia t y la celda c:

1. CAMPO LATENTE. w_t = phi w_{t-1} + sqrt(1-phi^2) A z_t, con A el factor de
   Cholesky de Cov(i,j) = exp(-d_ij/L). w queda N(0,1) marginal, con
   correlacion espacial exponencial y persistencia temporal phi.

2. OCURRENCIA. Llueve si w_t(c) > tau(c), donde tau depende del estado de
   ayer:  tau = Phi^-1(1 - p01) si ayer estuvo seco, Phi^-1(1 - p11) si
   llovio. Es una cadena de Markov de primer orden por celda, acoplada en el
   espacio por w. La calibracion de p01/p11 esta en climatologia.py.

3. INTENSIDAD. Dado que llueve, se usa el mismo w con una copula gaussiana:
       u = (Phi(w) - (1-p)) / p        en (0, 1)
       lluvia = Weibull^-1(u)
   Asi el centro de la mancha de lluvia (w alto) es tambien donde mas llueve,
   que es lo que hace una tormenta de verdad. Sin la copula, la ocurrencia
   seria espacial pero la intensidad seria ruido blanco.

4. TEMPERATURA. Anomalia AR(1) con su propio campo espacial (mas suave, L
   mayor) mas el efecto de la lluvia: los dias de lluvia bajan la tmax por
   nubosidad y suben la tmin.

5. BALANCE DE AGUA EN EL SUELO. Deposito de una capa (tipo Manabe):
       escurrimiento = P * S^beta         (mas saturado, mas escurre)
       ET real       = ET0 * S            (ET0 por Hargreaves)
       S_{t+1}       = S_t + (P - escurrimiento - ET) / capacidad
   S es la saturacion relativa en [0, 1]. Es la variable que conecta con
   NISAR: el radar mide humedad de suelo, y ese dato corrige S (ver
   asimilacion.py).

Honestidad sobre los limites
----------------------------
- La persistencia vive en dos lados: phi del campo y p01/p11 de la cadena.
  Con datos reales hay que calibrar los dos juntos, porque se solapan.
- La climatologia es estacionaria: no hay tendencia de cambio climatico ni
  ENSO. Para horizontes de dias no importa; para proyecciones a anos, si.
- La escala Weibull se calibra contra el acumulado mensual, no contra la
  frecuencia de dias con mas de 1 mm. Con forma 0.8 eso hace que ~10% de los
  dias humedos salgan por debajo de 1 mm, asi que el conteo de dias con
  lluvia apreciable queda ligeramente por debajo de la normal mientras el
  acumulado cuadra. Se eligio cuadrar el acumulado porque es lo que manda en
  riesgo de inundacion.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import numpy as np

from .climatologia import Climatologia
from .estadistica import CampoEspacial, norm_cdf, norm_ppf, weibull_ppf
from .malla import MallaHexagonal

#: Constante solar, MJ m-2 min-1 (FAO-56).
CONSTANTE_SOLAR = 0.0820
#: Factor de conversion de MJ m-2 dia-1 a mm de agua equivalente (FAO-56).
MJ_A_MM = 0.408


@dataclass
class ParametrosModelo:
    """Parametros fisicos y estadisticos del simulador.

    Los valores por defecto son los de referencia para clima tropical humedo
    costero. Cada uno dice de donde sale y que pasa si se mueve.
    """

    #: Longitud de correlacion espacial de la lluvia, km. Tamano tipico de un
    #: sistema convectivo. Subirla hace manchas de lluvia mas grandes.
    longitud_correlacion_lluvia_km: float = 30.0

    #: Longitud de correlacion de la temperatura, km. Los campos termicos son
    #: mucho mas suaves que los de lluvia.
    longitud_correlacion_temp_km: float = 90.0

    #: Persistencia dia a dia del campo de lluvia (AR1). 0.55 da rachas de
    #: 2-3 dias, que es lo que se observa en temporada de lluvias.
    persistencia_campo_lluvia: float = 0.55

    #: Persistencia de la anomalia de temperatura. Alta: las masas de aire
    #: tardan en cambiar.
    persistencia_temp: float = 0.80

    #: Desviacion estandar de la anomalia diaria de temperatura, grados C.
    sigma_temp_c: float = 1.8

    #: Cuanto baja la tmax un dia de lluvia, grados C (nubosidad).
    enfriamiento_por_lluvia_c: float = 2.2

    #: Cuanto sube la tmin un dia de lluvia, grados C (nubes que atrapan calor).
    calentamiento_nocturno_lluvia_c: float = 0.8

    #: Separacion minima garantizada entre tmax y tmin, grados C.
    brecha_minima_temp_c: float = 1.0

    #: Exponente del escurrimiento: fraccion de la lluvia que escurre crece
    #: como S^beta. beta alto = el suelo seco absorbe casi todo.
    beta_escurrimiento: float = 1.5

    #: Fraccion impermeable por celda (0-1), de OpenStreetMap. Escalar o
    #: array (n_celdas,). La fraccion impermeable escurre TODA la lluvia sin
    #: importar como este el suelo, y la permeable escurre segun su
    #: saturacion:
    #:
    #:     escurrimiento = imperm * P  +  (1 - imperm) * P * S^beta
    #:
    #: Es el modelo de area impermeable directamente conectada, el estandar de
    #: hidrologia urbana. Con imperm = 0 se recupera exactamente el
    #: comportamiento anterior, asi que pasarlo es opcional.
    #:
    #: Y tiene un efecto que suele olvidarse: en la zona impermeable el suelo
    #: tampoco se moja, porque el agua se va por el drenaje antes de
    #: infiltrarse. Asi que la ciudad escurre mas Y se seca mas.
    fraccion_impermeable: object = 0.0

    #: Dias de calentamiento del balance de agua antes del pronostico. Sirve
    #: para que la humedad inicial del suelo sea consistente con la lluvia
    #: reciente y no un numero puesto a mano.
    dias_calentamiento: int = 45

    #: Saturacion inicial del suelo al arrancar el calentamiento.
    humedad_inicial_defecto: float = 0.45


@dataclass
class ResultadoSimulacion:
    """Salida del simulador. Arrays (n_miembros, n_dias, n_celdas) en float32.

    Convencion de dominio, importante para el front y para las metricas:

        lluvia_mm, tmax_c, tmin_c, et0_mm    definidas en TODAS las celdas
                                             (en el mar tambien llueve)
        humedad_suelo, escurrimiento_mm      solo en tierra; NaN en el mar

    El NaN es deliberado y no es un hueco de datos: significa "esta variable no
    existe aqui". El front no debe pintar esas celdas, y pintarlas como 0 seria
    peor que no pintarlas, porque 0 de escurrimiento se lee como "seguro".
    """

    fechas: list
    ids_celdas: list
    lluvia_mm: np.ndarray
    tmax_c: np.ndarray
    tmin_c: np.ndarray
    humedad_suelo: np.ndarray
    escurrimiento_mm: np.ndarray
    et0_mm: np.ndarray
    semilla: int
    parametros: ParametrosModelo = field(default=None)

    @property
    def n_miembros(self) -> int:
        return self.lluvia_mm.shape[0]

    @property
    def n_dias(self) -> int:
        return self.lluvia_mm.shape[1]

    @property
    def n_celdas(self) -> int:
        return self.lluvia_mm.shape[2]

    def variable(self, nombre: str) -> np.ndarray:
        try:
            return getattr(self, _VARIABLES[nombre])
        except KeyError:
            raise KeyError(
                "variable desconocida '{}'; validas: {}".format(
                    nombre, ", ".join(sorted(_VARIABLES))
                )
            ) from None


#: Nombres publicos de las variables -> atributo del resultado.
_VARIABLES = {
    "lluvia": "lluvia_mm",
    "tmax": "tmax_c",
    "tmin": "tmin_c",
    "humedad_suelo": "humedad_suelo",
    "escurrimiento": "escurrimiento_mm",
    "et0": "et0_mm",
}


def radiacion_extraterrestre_mm(lat_grados, dia_juliano: int):
    """Radiacion extraterrestre Ra en mm/dia (FAO-56, ecuacion 21).

    Es el tope fisico de energia disponible, funcion solo de latitud y fecha.
    Entra en la ET0 de Hargreaves.
    """
    phi = np.radians(np.asarray(lat_grados, dtype=float))
    j = float(dia_juliano)
    dr = 1.0 + 0.033 * np.cos(2.0 * np.pi * j / 365.0)
    delta = 0.409 * np.sin(2.0 * np.pi * j / 365.0 - 1.39)
    # Angulo horario de la puesta de sol, con guarda para latitudes polares.
    x = np.clip(-np.tan(phi) * np.tan(delta), -1.0, 1.0)
    omega = np.arccos(x)
    ra_mj = (
        (24.0 * 60.0 / np.pi)
        * CONSTANTE_SOLAR
        * dr
        * (
            omega * np.sin(phi) * np.sin(delta)
            + np.cos(phi) * np.cos(delta) * np.sin(omega)
        )
    )
    return ra_mj * MJ_A_MM


def et0_hargreaves(ra_mm, tmax, tmin):
    """ET0 diaria por Hargreaves-Samani, mm/dia.

    ET0 = 0.0023 * Ra * (Tmed + 17.8) * sqrt(Tmax - Tmin)

    Se usa Hargreaves y no Penman-Monteith porque solo necesita temperatura:
    no hay viento ni humedad relativa por celda en el pronostico. El sesgo
    tipico es del 10-15% en clima humedo, aceptable para el balance de agua.
    """
    rango = np.maximum(tmax - tmin, 0.0)
    tmed = (tmax + tmin) / 2.0
    return 0.0023 * ra_mm * (tmed + 17.8) * np.sqrt(rango)


class SimuladorEstocastico:
    """Genera ensambles de trayectorias de clima sobre la malla."""

    def __init__(
        self,
        malla: MallaHexagonal,
        clima: Climatologia | None = None,
        parametros: ParametrosModelo | None = None,
    ) -> None:
        self.malla = malla
        self.clima = clima if clima is not None else Climatologia.sintetica(malla)
        self.par = parametros or ParametrosModelo()

        if self.clima.n_celdas != malla.n_celdas:
            raise ValueError("la climatologia no corresponde a esta malla")

        d = malla.matriz_distancias_km()
        self.campo_lluvia = CampoEspacial(
            d,
            longitud_correlacion_km=self.par.longitud_correlacion_lluvia_km,
            persistencia=self.par.persistencia_campo_lluvia,
        )
        self.campo_temp = CampoEspacial(
            d,
            longitud_correlacion_km=self.par.longitud_correlacion_temp_km,
            persistencia=self.par.persistencia_temp,
        )

        # Umbrales de ocurrencia en unidades de normal estandar, (n, 12).
        self.tau_seco = norm_ppf(1.0 - self.clima.p01)
        self.tau_humedo = norm_ppf(1.0 - self.clima.p11)

        # Fraccion impermeable por celda: escalar o array.
        imp = np.asarray(self.par.fraccion_impermeable, dtype=float)
        if imp.ndim == 0:
            imp = np.full(malla.n_celdas, float(imp))
        elif imp.shape != (malla.n_celdas,):
            raise ValueError(
                "fraccion_impermeable debe ser escalar o de largo {}".format(
                    malla.n_celdas))
        if np.nanmin(imp) < 0.0 or np.nanmax(imp) > 1.0:
            raise ValueError("fraccion_impermeable debe estar en [0, 1]")
        self.fraccion_impermeable = np.nan_to_num(imp, nan=0.0)

        # Radiacion extraterrestre por celda y dia juliano, (n, 366). Se
        # precalcula porque solo depende de latitud y fecha.
        self._ra = np.stack(
            [radiacion_extraterrestre_mm(malla.lat, j) for j in range(1, 367)],
            axis=1,
        )

    # --- simulacion --------------------------------------------------------

    def simular(
        self,
        fecha_inicio: dt.date,
        n_dias: int,
        n_miembros: int = 1,
        semilla: int | None = None,
        humedad_inicial=None,
        dias_calentamiento: int | None = None,
        mu_campo=None,
    ) -> ResultadoSimulacion:
        """Corre el ensamble.

        fecha_inicio        primer dia del pronostico
        n_dias              horizonte
        n_miembros          trayectorias independientes del ensamble
        semilla             None = aleatorio; un entero fija la corrida
        humedad_inicial     saturacion (0-1) al arrancar el calentamiento;
                            escalar, array (n,) o array (n_miembros, n).
                            Aqui entra el dato asimilado de NISAR.
        dias_calentamiento  None usa el de los parametros
        mu_campo            media del campo latente de lluvia, en unidades de
                            normal estandar. Escalar, array (n_celdas,) o
                            array (n_dias,). Aqui entra el sondeo: con
                            mu > 0 sube la probabilidad Y la intensidad de
                            lluvia de todo el dominio de forma coherente.
                            Ver docs/03-modelo-estocastico.md.

        OJO con mu_campo: con mu distinta de cero el modelo YA NO reproduce la
        climatologia, y eso es a proposito, porque deja de ser climatologia y
        pasa a ser pronostico del dia. La consistencia climatologica se
        recupera solo si mu tiene media cero a lo largo de muchos dias, de lo
        que se encarga el intercepto del probit cuando se calibra.
        """
        if n_dias < 1:
            raise ValueError("n_dias debe ser al menos 1")
        if n_miembros < 1:
            raise ValueError("n_miembros debe ser al menos 1")

        semilla = int(np.random.SeedSequence().entropy % (2**31)) if semilla is None \
            else int(semilla)
        rng = np.random.default_rng(semilla)

        calent = (self.par.dias_calentamiento if dias_calentamiento is None
                  else int(dias_calentamiento))
        calent = max(0, calent)

        n = self.malla.n_celdas
        m = n_miembros
        total = calent + n_dias
        fecha_0 = fecha_inicio - dt.timedelta(days=calent)
        fechas_todas = [fecha_0 + dt.timedelta(days=k) for k in range(total)]

        # --- estado inicial
        # Ocurrencia de ayer: se muestrea de la climatologia del mes para no
        # arrancar con un sesgo seco o humedo.
        mes0 = fechas_todas[0].month - 1
        lluvio_ayer = rng.random((m, n)) < self.clima.prob_lluvia[None, :, mes0]

        s = self._humedad_inicial(humedad_inicial, m, n)
        anom_t = np.zeros((m, n), dtype=float)

        # Media del campo latente, por dia y por celda.
        mu = self._preparar_mu(mu_campo, total, n, calent)

        # Campos latentes iniciales: una muestra del equilibrio estacionario,
        # centrada en la media del primer dia.
        w = self.campo_lluvia.muestra(rng, m) + mu[0][None, :]
        wt = self.campo_temp.muestra(rng, m)

        phi_ll = self.par.persistencia_campo_lluvia
        phi_t = self.par.persistencia_temp
        innov_ll = np.sqrt(1.0 - phi_ll * phi_ll)
        innov_t = np.sqrt(1.0 - phi_t * phi_t)

        cap = self.clima.capacidad_suelo_mm
        cap_segura = np.where(np.isnan(cap), 1.0, cap)   # el mar no tiene suelo
        es_tierra = self.clima.es_tierra

        # --- salida (solo se guardan los dias del pronostico)
        forma = (m, n_dias, n)
        out_lluvia = np.zeros(forma, dtype=np.float32)
        out_tmax = np.zeros(forma, dtype=np.float32)
        out_tmin = np.zeros(forma, dtype=np.float32)
        out_suelo = np.zeros(forma, dtype=np.float32)
        out_escurr = np.zeros(forma, dtype=np.float32)
        out_et0 = np.zeros(forma, dtype=np.float32)

        mu_ayer = mu[0][None, :]
        for k, fecha in enumerate(fechas_todas):
            mes = fecha.month - 1
            jul = min(fecha.timetuple().tm_yday, 366)

            # 1. campos latentes. El AR(1) va sobre la ANOMALIA respecto a la
            # media, no sobre el campo: asi la media del campo es mu y la
            # varianza marginal sigue siendo 1, que es lo que mantiene validos
            # los umbrales de ocurrencia.
            mu_hoy = mu[k][None, :]
            w = (mu_hoy + phi_ll * (w - mu_ayer)
                 + innov_ll * self.campo_lluvia.muestra(rng, m))
            mu_ayer = mu_hoy
            wt = phi_t * wt + innov_t * self.campo_temp.muestra(rng, m)

            # 2. ocurrencia: umbral segun el estado de ayer
            tau = np.where(
                lluvio_ayer,
                self.tau_humedo[None, :, mes],
                self.tau_seco[None, :, mes],
            )
            llueve = w > tau

            # 3. intensidad por copula gaussiana
            p = np.where(
                lluvio_ayer,
                self.clima.p11[None, :, mes],
                self.clima.p01[None, :, mes],
            )
            u = (norm_cdf(w) - (1.0 - p)) / np.maximum(p, 1e-12)
            u = np.clip(u, 1e-9, 1.0 - 1e-9)
            lluvia = np.where(
                llueve,
                weibull_ppf(
                    u,
                    self.clima.weibull_forma[None, :, mes],
                    self.clima.weibull_escala[None, :, mes],
                ),
                0.0,
            )
            lluvio_ayer = llueve

            # 4. temperatura
            anom_t = wt * self.par.sigma_temp_c
            tmax = (
                self.clima.tmax_media[None, :, mes]
                + anom_t
                - self.par.enfriamiento_por_lluvia_c * llueve
            )
            tmin = (
                self.clima.tmin_media[None, :, mes]
                + anom_t * 0.7
                + self.par.calentamiento_nocturno_lluvia_c * llueve
            )
            tmin = np.minimum(tmin, tmax - self.par.brecha_minima_temp_c)

            # 5. balance de agua
            ra = self._ra[None, :, jul - 1]
            et0 = et0_hargreaves(ra, tmax, tmin)
            # Area impermeable directamente conectada: lo pavimentado escurre
            # todo, lo permeable escurre segun su saturacion.
            imp = self.fraccion_impermeable[None, :]
            escurr = lluvia * (imp + (1.0 - imp)
                               * np.power(s, self.par.beta_escurrimiento))
            infiltra = lluvia - escurr
            et_real = et0 * s
            s = s + (infiltra - et_real) / cap_segura[None, :]
            # El exceso sobre la saturacion se va como percolacion profunda y
            # se suma al escurrimiento: es agua que ya no esta en el suelo.
            exceso = np.maximum(s - 1.0, 0.0) * cap_segura[None, :]
            escurr = escurr + exceso
            s = np.clip(s, 0.0, 1.0)
            # Suelo y escurrimiento no existen sobre el mar (ver la convencion
            # en ResultadoSimulacion). Se marcan explicitamente en vez de
            # dejar que el NaN se propague solo, para que la intencion quede
            # en el codigo y no dependa de la aritmetica.
            s = np.where(es_tierra[None, :], s, np.nan)
            escurr = np.where(es_tierra[None, :], escurr, np.nan)

            # 6. guardar si ya pasamos el calentamiento
            i = k - calent
            if i >= 0:
                out_lluvia[:, i, :] = lluvia
                out_tmax[:, i, :] = tmax
                out_tmin[:, i, :] = tmin
                out_suelo[:, i, :] = s
                out_escurr[:, i, :] = escurr
                out_et0[:, i, :] = et0

        return ResultadoSimulacion(
            fechas=[f.isoformat() for f in fechas_todas[calent:]],
            ids_celdas=list(self.malla.ids),
            lluvia_mm=out_lluvia,
            tmax_c=out_tmax,
            tmin_c=out_tmin,
            humedad_suelo=out_suelo,
            escurrimiento_mm=out_escurr,
            et0_mm=out_et0,
            semilla=semilla,
            parametros=self.par,
        )

    # --- apoyo -------------------------------------------------------------

    def _humedad_inicial(self, valor, m: int, n: int) -> np.ndarray:
        if valor is None:
            valor = self.par.humedad_inicial_defecto
        arr = np.asarray(valor, dtype=float)
        if arr.ndim == 0:
            s = np.full((m, n), float(arr))
        elif arr.shape == (n,):
            s = np.repeat(arr[None, :], m, axis=0)
        elif arr.shape == (m, n):
            s = arr.copy()
        else:
            raise ValueError(
                "humedad_inicial debe ser escalar, ({},) o ({}, {})".format(n, m, n)
            )
        if np.nanmin(s) < 0.0 or np.nanmax(s) > 1.0:
            raise ValueError("la humedad inicial debe estar en [0, 1]")
        return np.where(self.clima.es_tierra[None, :], s, np.nan)

    def _preparar_mu(self, mu_campo, total: int, n: int, calent: int):
        """Media del campo latente como array (total_dias, n_celdas).

        Acepta escalar, array por celda o array por dia del PRONOSTICO (no del
        calentamiento). En ese ultimo caso los dias de calentamiento se dejan
        en cero: el calentamiento sirve para que el suelo llegue a un estado
        consistente con la climatologia, y meterle la anomalia del dia de hoy
        lo contaminaria.
        """
        if mu_campo is None:
            return np.zeros((total, n))
        arr = np.asarray(mu_campo, dtype=float)
        n_dias = total - calent

        if arr.ndim == 0:
            mu = np.zeros((total, n))
            mu[calent:] = float(arr)
            return mu
        if arr.shape == (n,):
            mu = np.zeros((total, n))
            mu[calent:] = arr[None, :]
            return mu
        if arr.shape == (n_dias,):
            mu = np.zeros((total, n))
            mu[calent:] = arr[:, None]
            return mu
        if arr.shape == (n_dias, n):
            mu = np.zeros((total, n))
            mu[calent:] = arr
            return mu
        raise ValueError(
            "mu_campo debe ser escalar, ({},), ({},) o ({}, {}); recibi {}"
            .format(n, n_dias, n_dias, n, arr.shape)
        )

    def memoria_estimada_mb(self, n_dias: int, n_miembros: int) -> float:
        """MB que va a ocupar el ensamble crudo. Lo usa la API para rechazar
        peticiones que tumbarian el proceso."""
        n_vars = 6
        celdas = self.malla.n_celdas
        return n_miembros * n_dias * celdas * n_vars * 4 / (1024.0 * 1024.0)
