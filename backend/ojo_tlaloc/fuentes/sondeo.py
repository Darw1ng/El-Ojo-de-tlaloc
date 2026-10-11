"""Perfil atmosferico vertical: globo sonda propio o sondeo publico.

Que aporta un perfil vertical que nada mas aporta
-------------------------------------------------
El modelo estocastico, tal como esta, es climatologico: sabe que en septiembre
llueve mucho en Veracruz, no sabe si llueve *el jueves*. Ni OpenStreetMap ni
un satelite de superficie arreglan eso. Lo que lo arregla es saber como esta
la atmosfera **en la vertical**: cuanta energia hay disponible para
conveccion y cuanta agua hay en la columna.

Un sondeo da exactamente eso:

    CAPE   energia potencial convectiva disponible, J/kg
    CIN    inhibicion convectiva, J/kg (cuanto cuesta arrancar)
    PWAT   agua precipitable total en la columna, mm
    LCL    nivel de condensacion, hPa y m
    K, TT  indices de inestabilidad clasicos, mas robustos que el CAPE

Donde entra en el modelo
------------------------
En la media del campo latente. Hoy el campo es `w ~ N(0, 1)` y la ocurrencia
es `w > tau`. Con el sondeo:

    w_t = mu_t + phi (w_{t-1} - mu_{t-1}) + sqrt(1-phi^2) A z_t
    mu_t = b0 + b1 z(CAPE) + b2 z(PWAT) - b3 z(CIN)

Y como `P(lluvia) = Phi(mu - tau)` cuando `w ~ N(mu, 1)`, ajustar `mu` a
partir de los indices **es literalmente una regresion probit**. No es un
factor de correccion inventado: es un modelo estadistico estandar, con
coeficientes que se estiman por maxima verosimilitud contra ocurrencia
observada y que traen error estandar. Ver `calibrar_probit()`.

Un solo perfil alcanza para todo el dominio
-------------------------------------------
Parece poco un punto para 92 km, y no lo es: la inestabilidad atmosferica es
propiedad de la masa de aire, de escala sinoptica (cientos de km), mientras el
campo espacial del modelo tiene longitud de correlacion de 30 km. Una `mu`
comun para todo el dominio es fisicamente correcta. No hace falta una red de
globos; hace falta uno bien puesto.

El limite honesto
-----------------
La informacion de un sondeo decae en dos o tres dias. El sondeo mejora el
horizonte de 0 a 72 horas y no el de 14 dias. Eso deja al sistema con dos
regimenes declarados, que es como funcionan los pronosticos de verdad:

    0-3 dias   sonda (atmosfera) + radar (suelo)  -> habilidad real
    3-14 dias  climatologia con incertidumbre creciente

Formatos que lee
----------------
El mismo codigo sirve para los dos casos, asi que el modelo no depende de
tener hardware:

    texto de sondeo publico   el formato de tabla de la Universidad de
                              Wyoming / IGRA, que es el que publican el SMN y
                              los archivos historicos.
    CSV del globo propio      columnas presion/temperatura/humedad(/altura),
                              que es lo que escribe una sonda casera con
                              BME280 y GPS. Acepta nombres en espanol y en
                              ingles, y ordena por presion por si el registro
                              viene de ascenso o de descenso.
"""

from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass, field

import numpy as np

from .base import NIVEL_OBSERVADO, ErrorFuente, Procedencia

# --- constantes fisicas ----------------------------------------------------

G = 9.80665              # m/s2
RD = 287.058             # J/(kg K), aire seco
RV = 461.5               # J/(kg K), vapor
CPD = 1005.7             # J/(kg K)
EPSILON = RD / RV        # 0.622
DENSIDAD_AGUA = 1000.0   # kg/m3
CERO_C = 273.15

#: Niveles estandar para los indices clasicos, en hPa.
NIVELES_ESTANDAR = (1000, 925, 850, 700, 500, 400, 300, 250, 200)

#: Hasta donde tiene que llegar el perfil para que cada indice sea confiable.
#:
#: Esto importa mucho mas de lo que parece, y define que sensor hay que
#: comprar. El CAPE es una integral desde el nivel de conveccion libre hasta
#: el nivel de equilibrio, que en el tropico humedo esta entre 150 y 200 hPa
#: (12 a 14 km). Un perfil que termina a 500 hPa no da un CAPE "aproximado":
#: da un CAPE severamente subestimado, y sin aviso parece un dato bueno.
#:
#: Caso concreto: el BME280, que es el sensor de presion/temperatura/humedad
#: mas usado en proyectos caseros, especifica presion de 300 a 1100 hPa. Eso
#: corta el perfil alrededor de 9 km y trunca el CAPE.
TOPE_REQUERIDO_HPA = {
    "lcl": 800.0,            # el LCL esta en los primeros 1-2 km
    "pwat": 400.0,           # ~95% del agua de la columna esta debajo
    "indice_k": 500.0,       # necesita 850, 700 y 500
    "total_totals": 500.0,   # necesita 850 y 500
    "cape_parcial": 400.0,   # algo de CAPE, pero truncado
    "cape_j_kg": 200.0,      # CAPE completo: hay que alcanzar el equilibrio
}

#: Fraccion tipica del agua precipitable que queda por DEBAJO de cada nivel,
#: en atmosfera tropical humeda. Sirve para decir cuanto PWAT falta cuando el
#: perfil se queda corto, en lugar de entregar un numero incompleto a secas.
FRACCION_PWAT_BAJO = {
    850.0: 0.60,
    700.0: 0.80,
    600.0: 0.87,
    500.0: 0.92,
    400.0: 0.96,
    300.0: 0.98,
    200.0: 0.995,
}


def presion_vapor_saturacion_hpa(t_c):
    """Presion de vapor de saturacion por la formula de Bolton (1980), en hPa.

    es = 6.112 exp( 17.67 T / (T + 243.5) )  con T en grados C.
    Error menor al 0.3% entre -35 y 35 C, que cubre toda la troposfera util.
    """
    t = np.asarray(t_c, dtype=float)
    return 6.112 * np.exp(17.67 * t / (t + 243.5))


def razon_mezcla(presion_hpa, t_rocio_c):
    """Razon de mezcla de vapor, kg/kg."""
    e = presion_vapor_saturacion_hpa(t_rocio_c)
    p = np.asarray(presion_hpa, dtype=float)
    return EPSILON * e / np.maximum(p - e, 1e-6)


def rocio_desde_humedad(t_c, humedad_rel):
    """Temperatura de rocio a partir de temperatura y humedad relativa (%).

    Se invierte la formula de Bolton. Es lo que se necesita para la sonda
    casera, que mide humedad relativa y no rocio.
    """
    t = np.asarray(t_c, dtype=float)
    hr = np.clip(np.asarray(humedad_rel, dtype=float), 0.5, 100.0)
    e = hr / 100.0 * presion_vapor_saturacion_hpa(t)
    ln = np.log(np.maximum(e, 1e-6) / 6.112)
    return 243.5 * ln / (17.67 - ln)


def temperatura_potencial(presion_hpa, t_c):
    """Theta, en K. Referencia 1000 hPa."""
    t = np.asarray(t_c, dtype=float) + CERO_C
    p = np.asarray(presion_hpa, dtype=float)
    return t * np.power(1000.0 / p, RD / CPD)


def temperatura_lcl_k(t_c, t_rocio_c):
    """Temperatura del nivel de condensacion, K. Bolton (1980) ec. 22."""
    t = np.asarray(t_c, dtype=float) + CERO_C
    td = np.asarray(t_rocio_c, dtype=float) + CERO_C
    return 1.0 / (1.0 / (td - 56.0) + np.log(t / td) / 800.0) + 56.0


def theta_e(presion_hpa, t_c, t_rocio_c):
    """Temperatura potencial equivalente, K. Bolton (1980) ec. 39.

    Se conserva en el ascenso pseudoadiabatico, y por eso es lo que permite
    levantar una parcela sin integrar la ecuacion diferencial.
    """
    p = np.asarray(presion_hpa, dtype=float)
    t = np.asarray(t_c, dtype=float) + CERO_C
    r = razon_mezcla(p, t_rocio_c)
    tl = temperatura_lcl_k(t_c, t_rocio_c)
    # theta del aire humedo, con la correccion de Bolton.
    theta = t * np.power(1000.0 / p, 0.2854 * (1.0 - 0.28 * r))
    return theta * np.exp((3036.0 / tl - 1.78) * r * (1.0 + 0.448 * r))


def _theta_es_saturado(presion_hpa: float, t_k: float) -> float:
    """theta_e de una parcela SATURADA a (p, T). Se usa para invertir."""
    t_c = t_k - CERO_C
    r = razon_mezcla(presion_hpa, t_c)   # saturada: rocio = temperatura
    theta = t_k * (1000.0 / presion_hpa) ** (0.2854 * (1.0 - 0.28 * r))
    return theta * math.exp((3036.0 / t_k - 1.78) * r * (1.0 + 0.448 * r))


def temperatura_parcela_saturada(presion_hpa: float, theta_e_objetivo: float) -> float:
    """T de una parcela saturada con theta_e dada, a presion dada. En K.

    Se resuelve por biseccion porque theta_es es monotona creciente en T.
    Es el paso que sustituye a integrar la pseudoadiabatica.
    """
    lo, hi = 150.0, 350.0
    for _ in range(80):
        medio = (lo + hi) / 2.0
        if _theta_es_saturado(presion_hpa, medio) < theta_e_objetivo:
            lo = medio
        else:
            hi = medio
    return (lo + hi) / 2.0


@dataclass
class PerfilAtmosferico:
    """Un sondeo, ya ordenado y con los indices calculados.

    presion_hpa, temperatura_c, rocio_c  arrays del mismo largo, de abajo
                                         hacia arriba (presion decreciente)
    """

    presion_hpa: np.ndarray
    temperatura_c: np.ndarray
    rocio_c: np.ndarray
    altura_m: np.ndarray | None = None
    viento_dir: np.ndarray | None = None
    viento_vel_ms: np.ndarray | None = None
    estacion: str = ""
    fecha: str = ""
    fuente: str = "sondeo"
    es_propio: bool = False
    indices: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        p = np.asarray(self.presion_hpa, dtype=float)
        t = np.asarray(self.temperatura_c, dtype=float)
        d = np.asarray(self.rocio_c, dtype=float)
        if not (p.shape == t.shape == d.shape):
            raise ValueError("presion, temperatura y rocio deben tener igual largo")

        valido = np.isfinite(p) & np.isfinite(t) & np.isfinite(d) & (p > 50)
        if valido.sum() < 5:
            raise ErrorFuente(
                "el perfil tiene solo {} niveles utiles; se necesitan al "
                "menos 5 para calcular indices".format(int(valido.sum()))
            )
        # El rocio no puede superar la temperatura (pasa por error de sensor).
        d = np.minimum(d, t)

        orden = np.argsort(-p[valido])   # de mayor a menor presion
        self.presion_hpa = p[valido][orden]
        self.temperatura_c = t[valido][orden]
        self.rocio_c = d[valido][orden]
        for nombre in ("altura_m", "viento_dir", "viento_vel_ms"):
            arr = getattr(self, nombre)
            if arr is not None:
                arr = np.asarray(arr, dtype=float)
                if arr.shape == p.shape:
                    setattr(self, nombre, arr[valido][orden])
                else:
                    setattr(self, nombre, None)

        if not self.indices:
            self.indices = self.calcular_indices()

    # --- indices ----------------------------------------------------------

    def agua_precipitable_mm(self) -> float:
        """PWAT: agua total de la columna, en mm.

            PWAT = (1/(rho_w g)) integral q dp

        Es la cota superior natural de cuanto puede llover: no puede
        precipitar mas agua de la que hay, aunque la convergencia de humedad
        pueda reponerla durante el evento.
        """
        p_pa = self.presion_hpa * 100.0
        r = razon_mezcla(self.presion_hpa, self.rocio_c)
        q = r / (1.0 + r)                      # humedad especifica
        # Integral por trapecios en presion (decreciente hacia arriba).
        dp = -np.diff(p_pa)
        q_medio = (q[:-1] + q[1:]) / 2.0
        return float((q_medio * dp).sum() / (DENSIDAD_AGUA * G) * 1000.0)

    def _altura_estimada(self):
        """Altura por la hipsometrica si el sondeo no la trae."""
        if self.altura_m is not None:
            return self.altura_m
        t_k = self.temperatura_c + CERO_C
        r = razon_mezcla(self.presion_hpa, self.rocio_c)
        tv = t_k * (1.0 + 0.61 * r)             # temperatura virtual
        z = np.zeros_like(self.presion_hpa)
        for i in range(1, z.size):
            tv_medio = (tv[i] + tv[i - 1]) / 2.0
            z[i] = z[i - 1] + (RD * tv_medio / G) * math.log(
                self.presion_hpa[i - 1] / self.presion_hpa[i]
            )
        return z

    def cape_cin(self, usar_capa_mezclada: bool = True) -> tuple:
        """CAPE y CIN de la parcela, en J/kg.

            CAPE = integral g (Tp - Te)/Te dz   sobre las capas con Tp > Te
            CIN  = lo mismo donde Tp < Te, por debajo del nivel de conveccion

        La parcela se levanta conservando theta_e (pseudoadiabatica), que es
        el metodo estandar. Por defecto se usa la media de los primeros 500 m
        ("capa mezclada"), que es mas representativa que el nivel de
        superficie: una lectura de superficie puede estar contaminada por
        calentamiento local del suelo y da CAPE irrealmente alto.

        SIMPLIFICACION DECLARADA: la flotabilidad se calcula con temperatura y
        no con temperatura virtual, lo que subestima el CAPE entre 5% y 10%.
        Va en direccion conservadora.
        """
        z = self._altura_estimada()
        p, t, td = self.presion_hpa, self.temperatura_c, self.rocio_c

        if usar_capa_mezclada and z.max() > 500:
            capa = z <= 500.0
            if capa.sum() < 2:
                capa = np.zeros_like(z, dtype=bool)
                capa[0] = True
            p0 = float(p[capa].mean())
            t0 = float(t[capa].mean())
            td0 = float(td[capa].mean())
        else:
            p0, t0, td0 = float(p[0]), float(t[0]), float(td[0])

        te_parcela = float(theta_e(p0, t0, td0))

        # Temperatura de la parcela a cada nivel. Debajo del LCL el ascenso es
        # seco (theta constante); arriba, saturado (theta_e constante).
        theta_seca = float(temperatura_potencial(p0, t0))
        t_lcl = float(temperatura_lcl_k(t0, td0))
        # Presion del LCL: donde el ascenso seco alcanza T = T_lcl.
        p_lcl = p0 * (t_lcl / (t0 + CERO_C)) ** (CPD / RD)

        tp = np.empty_like(p)
        for i, pi in enumerate(p):
            if pi >= p_lcl:
                tp[i] = theta_seca * (pi / 1000.0) ** (RD / CPD) - CERO_C
            else:
                tp[i] = temperatura_parcela_saturada(float(pi), te_parcela) - CERO_C

        te = t
        flotabilidad = G * (tp - te) / (te + CERO_C)

        cape = 0.0
        cin = 0.0
        hallado_positivo = False
        for i in range(1, p.size):
            dz = z[i] - z[i - 1]
            if dz <= 0:
                continue
            f_medio = (flotabilidad[i] + flotabilidad[i - 1]) / 2.0
            if f_medio > 0:
                cape += f_medio * dz
                hallado_positivo = True
            elif not hallado_positivo:
                # CIN: solo la parte negativa ANTES del primer nivel de
                # flotabilidad libre. Lo negativo de arriba es la tapa, no la
                # inhibicion.
                cin += f_medio * dz
        return float(max(0.0, cape)), float(abs(min(0.0, cin)))

    def nivel(self, presion_hpa: float) -> dict:
        """Temperatura y rocio interpolados a un nivel de presion."""
        p = self.presion_hpa
        if presion_hpa > p[0] or presion_hpa < p[-1]:
            return {"t": float("nan"), "td": float("nan")}
        # np.interp necesita x creciente: se invierte el orden.
        return {
            "t": float(np.interp(presion_hpa, p[::-1], self.temperatura_c[::-1])),
            "td": float(np.interp(presion_hpa, p[::-1], self.rocio_c[::-1])),
        }

    def indice_k(self) -> float:
        """K index. Mide inestabilidad y humedad en capas bajas y medias."""
        n850, n700, n500 = self.nivel(850), self.nivel(700), self.nivel(500)
        return ((n850["t"] - n500["t"]) + n850["td"]
                - (n700["t"] - n700["td"]))

    def total_totals(self) -> float:
        """Total Totals: (T850 - T500) + (Td850 - T500)."""
        n850, n500 = self.nivel(850), self.nivel(500)
        return (n850["t"] - n500["t"]) + (n850["td"] - n500["t"])

    def calcular_indices(self) -> dict:
        cape, cin = self.cape_cin()
        z = self._altura_estimada()
        t0, td0 = float(self.temperatura_c[0]), float(self.rocio_c[0])
        t_lcl = float(temperatura_lcl_k(t0, td0))
        p_lcl = float(self.presion_hpa[0] * (t_lcl / (t0 + CERO_C)) ** (CPD / RD))
        return {
            "cape_j_kg": round(cape, 1),
            "cin_j_kg": round(cin, 1),
            "pwat_mm": round(self.agua_precipitable_mm(), 2),
            "lcl_hpa": round(p_lcl, 1),
            "lcl_m": round(float(np.interp(-p_lcl, -self.presion_hpa, z)), 1),
            "indice_k": round(self.indice_k(), 1),
            "total_totals": round(self.total_totals(), 1),
            "niveles": int(self.presion_hpa.size),
            "tope_hpa": round(float(self.presion_hpa[-1]), 1),
            "tope_m": round(float(z[-1]), 1),
            "t_superficie_c": round(t0, 1),
            "td_superficie_c": round(td0, 1),
        }

    def procedencia(self) -> Procedencia:
        return Procedencia(
            fuente=("globo sonda propio" if self.es_propio
                    else "sondeo {}".format(self.fuente)),
            nivel=NIVEL_OBSERVADO,
            resolucion_nativa="perfil puntual, {} niveles".format(
                self.presion_hpa.size),
            cadencia="por lanzamiento",
            licencia="dato propio" if self.es_propio else "segun el proveedor",
            atribucion=("Globo sonda de El Ojo de Tlaloc" if self.es_propio
                        else "Sondeo de {}".format(self.fuente)),
            nota=("perfil valido para 0-72 h; la informacion de un sondeo "
                  "decae en dos o tres dias"),
        )

    def resumen(self) -> dict:
        return {
            "estacion": self.estacion,
            "fecha": self.fecha,
            "fuente": self.fuente,
            "es_propio": self.es_propio,
            "indices": self.indices,
            "interpretacion": interpretar_indices(self.indices),
            "avisos": validar_indices(self.indices),
            "cobertura_vertical": evaluar_cobertura_vertical(self.indices),
        }


# --- lectura de formatos ---------------------------------------------------


def leer_texto_wyoming(texto: str, estacion: str = "", fecha: str = "") -> PerfilAtmosferico:
    """Lee el formato de tabla de sondeo de la Universidad de Wyoming / IGRA.

    Es el formato en el que se publican los sondeos del SMN y los archivos
    historicos. Las columnas son de ancho fijo:

        PRES   HGHT   TEMP   DWPT   RELH   MIXR   DRCT   SKNT  ...
        hPa     m      C      C      %     g/kg    deg   knot

    Se toleran lineas incompletas, que son normales: arriba de cierto nivel el
    sensor de humedad deja de reportar.
    """
    filas = []
    for linea in texto.splitlines():
        cabeza = linea.strip().split()
        if len(cabeza) < 4 or not _es_numero(cabeza[0]):
            continue

        # El formato de Wyoming es de ancho fijo, columnas de 7 caracteres:
        #   PRES HGHT TEMP DWPT RELH MIXR DRCT SKNT THTA THTE THTV
        #   0-7  7-14 14-21 21-28 28-35 35-42 42-49 49-56 ...
        # El ancho fijo es necesario y no un capricho: cuando un nivel no
        # reporta humedad, esa columna queda EN BLANCO, y un split por
        # espacios desalinearia todo lo que sigue.
        if len(linea) >= 28:
            pres = _flotante(linea[0:7])
            hght = _flotante(linea[7:14])
            temp = _flotante(linea[14:21])
            dwpt = _flotante(linea[21:28])
            drct = _flotante(linea[42:49]) if len(linea) >= 49 else float("nan")
            sknt = _flotante(linea[49:56]) if len(linea) >= 56 else float("nan")
        else:
            # Sondeo recortado a las primeras columnas: ahi si se puede
            # dividir por espacios porque no hay huecos intermedios.
            pres, hght, temp, dwpt = (_flotante(v) for v in cabeza[:4])
            drct = sknt = float("nan")

        if not (math.isfinite(pres) and math.isfinite(temp)
                and math.isfinite(dwpt)):
            continue
        filas.append((pres, hght, temp, dwpt, drct, sknt))

    if len(filas) < 5:
        raise ErrorFuente(
            "no se reconocieron niveles en el texto del sondeo "
            "({} filas utiles)".format(len(filas))
        )
    a = np.array(filas, dtype=float)
    return PerfilAtmosferico(
        presion_hpa=a[:, 0], altura_m=a[:, 1],
        temperatura_c=a[:, 2], rocio_c=a[:, 3],
        viento_dir=a[:, 4], viento_vel_ms=a[:, 5] * 0.514444,   # nudos a m/s
        estacion=estacion, fecha=fecha, fuente="Wyoming/IGRA",
    )


#: Nombres de columna que se aceptan en el CSV del globo propio. La sonda
#: casera la arma quien la arma, asi que se admiten varias convenciones en
#: lugar de obligar a un formato.
ALIAS_COLUMNAS = {
    "presion": ("presion", "presion_hpa", "pressure", "pres", "p", "hpa",
                "presion_mbar", "mbar"),
    "temperatura": ("temperatura", "temperatura_c", "temp", "temp_c", "t",
                    "tair", "bme_temp"),
    "humedad": ("humedad", "humedad_rel", "humedad_relativa", "hr", "rh",
                "humidity", "relh", "bme_hum"),
    "rocio": ("rocio", "rocio_c", "dewpoint", "dwpt", "td", "punto_rocio"),
    "altura": ("altura", "altura_m", "altitud", "alt", "height", "hght",
               "gps_alt", "msl"),
    "viento_vel": ("viento_vel", "viento", "velocidad", "ws", "sknt",
                   "wind_speed", "vel_viento"),
    "viento_dir": ("viento_dir", "direccion", "drct", "wind_dir", "dir"),
}


def leer_csv_globo(texto: str, estacion: str = "globo propio",
                   fecha: str = "") -> PerfilAtmosferico:
    """Lee el CSV crudo de una sonda propia.

    Lo que escribe una sonda casera con BME280 (presion, temperatura, humedad
    relativa) y GPS. Convierte humedad relativa a rocio si no viene el rocio, y
    ordena por presion, asi que da igual si el registro es del ascenso, del
    descenso o de los dos (en ese caso se quedan los dos y el perfil queda mas
    denso, que no estorba).

    Si el vuelo es de globo cautivo, el perfil solo cubre la capa limite: los
    indices de altura (CAPE, K, Total Totals) van a salir NaN y eso es
    correcto, no un fallo. El viento y la temperatura de los primeros cientos
    de metros si quedan, que es justo lo que se necesita para obra.
    """
    # Las lineas de comentario se quitan ANTES de buscar el encabezado. La
    # estacion de tierra del CanSat escribe comentarios con '#' para anotar
    # que sensor se detecto y cuantos paquetes se perdieron, y sin esto el
    # lector tomaba el primer comentario como encabezado de columnas.
    # Documentar el vuelo dentro del propio archivo es buena practica; el
    # que tiene que ser tolerante es el lector.
    limpio = "\n".join(
        linea for linea in texto.splitlines()
        if linea.strip() and not linea.lstrip().startswith(("#", "//"))
    )
    if not limpio.strip():
        raise ErrorFuente("el CSV no tiene ninguna linea de datos")

    muestra = limpio[:4096]
    try:
        dialecto = csv.Sniffer().sniff(muestra, delimiters=",;\t")
    except csv.Error:
        dialecto = csv.excel
    lector = csv.DictReader(io.StringIO(limpio), dialect=dialecto)
    if not lector.fieldnames:
        raise ErrorFuente("el CSV no tiene encabezado de columnas")

    mapa = {}
    for canonico, alias in ALIAS_COLUMNAS.items():
        for campo in lector.fieldnames:
            if campo and campo.strip().lower().replace(" ", "_") in alias:
                mapa[canonico] = campo
                break

    if "presion" not in mapa:
        raise ErrorFuente(
            "el CSV necesita una columna de presion. Se reconocen estos "
            "nombres: {}. Columnas encontradas: {}".format(
                ", ".join(ALIAS_COLUMNAS["presion"]), lector.fieldnames
            )
        )
    if "temperatura" not in mapa:
        raise ErrorFuente("el CSV necesita una columna de temperatura")
    if "humedad" not in mapa and "rocio" not in mapa:
        raise ErrorFuente(
            "el CSV necesita humedad relativa o temperatura de rocio: sin "
            "humedad no se puede calcular agua precipitable ni CAPE"
        )

    filas = []
    n_con_pt = 0          # filas con presion y temperatura validas
    for fila in lector:
        p = _flotante(fila.get(mapa["presion"]))
        t = _flotante(fila.get(mapa["temperatura"]))
        if not (math.isfinite(p) and math.isfinite(t)):
            continue
        n_con_pt += 1
        if "rocio" in mapa:
            td = _flotante(fila.get(mapa["rocio"]))
        else:
            hr = _flotante(fila.get(mapa["humedad"]))
            td = (float(rocio_desde_humedad(t, hr)) if math.isfinite(hr)
                  else float("nan"))
        if not math.isfinite(td):
            continue
        filas.append((
            p, t, td,
            _flotante(fila.get(mapa["altura"])) if "altura" in mapa else float("nan"),
            _flotante(fila.get(mapa["viento_dir"])) if "viento_dir" in mapa else float("nan"),
            _flotante(fila.get(mapa["viento_vel"])) if "viento_vel" in mapa else float("nan"),
        ))

    if len(filas) < 5:
        # Caso concreto del CanSat con BMP180: la columna de humedad existe
        # pero viene vacia en todas las filas, porque ese sensor no la mide.
        # Sin ese mensaje el error decia "0 filas utiles" y mandaba a buscar
        # el problema en el lugar equivocado.
        if n_con_pt >= 5:
            raise ErrorFuente(
                "el CSV trae {} filas con presion y temperatura, pero ninguna "
                "con humedad ni rocio utilizables. Sin humedad no se puede "
                "calcular rocio, agua precipitable, LCL ni CAPE: el sensor "
                "tiene que medirla (el BMP180 no lo hace, el BME280 si)."
                .format(n_con_pt)
            )
        raise ErrorFuente(
            "el CSV tiene {} filas utiles; se necesitan al menos 5".format(len(filas))
        )
    a = np.array(filas, dtype=float)
    altura = a[:, 3] if np.isfinite(a[:, 3]).all() else None
    return PerfilAtmosferico(
        presion_hpa=a[:, 0], temperatura_c=a[:, 1], rocio_c=a[:, 2],
        altura_m=altura, viento_dir=a[:, 4], viento_vel_ms=a[:, 5],
        estacion=estacion, fecha=fecha, fuente="globo propio", es_propio=True,
    )


def leer_sondeo(texto: str, **kw) -> PerfilAtmosferico:
    """Detecta el formato y lee. Es la puerta de entrada unica.

    Asi el resto del sistema no sabe —ni le importa— si el perfil vino de una
    estacion del SMN o del globo que lanzo el equipo.
    """
    primeras = "\n".join(texto.strip().splitlines()[:5]).lower()
    if "," in primeras or ";" in primeras or "\t" in primeras:
        if any(a in primeras for a in ("pres", "hpa", "mbar", "presion")):
            return leer_csv_globo(texto, **kw)
    return leer_texto_wyoming(texto, **kw)


# --- de los indices a la media del campo latente ---------------------------

#: Rangos fisicamente posibles. Fuera de aqui el perfil tiene un error de
#: unidades o de sensor, y es mejor avisar que calcular con basura.
#: El CAPE mas alto medido en la Tierra ronda los 8000 J/kg (Grandes Llanuras
#: de EEUU en supercelda); en el tropico marino es raro pasar de 4000.
RANGOS_POSIBLES = {
    "cape_j_kg": (0.0, 8000.0),
    "cin_j_kg": (0.0, 600.0),
    "pwat_mm": (2.0, 80.0),
    "indice_k": (-20.0, 50.0),
    "total_totals": (20.0, 70.0),
    "lcl_m": (0.0, 6000.0),
}

#: Valores de referencia para normalizar. Clima tropical humedo costero.
#:
#: El CAPE se normaliza por su RAIZ y no directo. No es un truco: la velocidad
#: vertical maxima de una parcela es w = sqrt(2 CAPE), asi que la raiz es la
#: cantidad con significado fisico lineal. Normalizar el CAPE crudo hacia que
#: un valor comun de tarde de verano (3000 J/kg) diera z = 3.7 y saturara la
#: media del campo por si solo; con la raiz, z = 1.4, que es lo que
#: corresponde a "una tarde convectiva, no un evento historico".
REFERENCIA_INDICES = {
    "raiz_cape": (30.0, 14.0),      # sqrt(J/kg): 30 -> 900 J/kg, 44 -> 1950
    "cin_j_kg": (50.0, 60.0),
    "pwat_mm": (45.0, 9.0),
    "indice_k": (32.0, 6.0),
    "total_totals": (43.0, 4.0),
}

#: Coeficientes PROVISIONALES de la regresion probit. El signo y el orden de
#: magnitud salen de la relacion conocida de cada indice con la conveccion;
#: los valores se deben estimar con `calibrar_probit()` sobre sondeos
#: historicos y lluvia observada. Mientras no se calibren, el sistema los
#: reporta como provisionales y no los presenta como ajustados.
COEFICIENTES_PROBIT_PROVISIONALES = {
    "intercepto": 0.0,
    "raiz_cape": 0.45,
    "pwat_mm": 0.55,
    "cin_j_kg": -0.30,
}


def evaluar_cobertura_vertical(indices: dict) -> dict:
    """Que indices son confiables segun hasta donde llego el perfil.

    Un globo cautivo a 300 m y una radiosonda a 20 km producen los dos un
    perfil valido, y de uno se puede calcular CAPE y del otro no. Sin esta
    funcion, el CAPE truncado de un perfil corto sale con la misma pinta que
    el de un perfil completo, y eso es justo el tipo de dato que lleva a una
    conclusion equivocada con cara de medicion.

    Devuelve por indice si es confiable, mas el aviso en lenguaje claro.
    """
    tope = indices.get("tope_hpa")
    if tope is None or not np.isfinite(tope):
        return {"tope_hpa": None, "confiables": {}, "avisos": [],
                "vuelo": "desconocido"}
    tope = float(tope)

    confiables = {
        nombre: tope <= requerido
        for nombre, requerido in TOPE_REQUERIDO_HPA.items()
        if nombre != "cape_parcial"
    }
    # El LCL no se juzga con un umbral fijo sino con el LCL calculado: si el
    # perfil pasa de ese nivel, el dato esta dentro y es valido. En clima
    # tropical humedo el LCL anda por 900-950 hPa, asi que hasta un vuelo de
    # capa limite lo alcanza, y un umbral fijo de 800 hPa lo descartaba mal.
    lcl = indices.get("lcl_hpa")
    if lcl is not None and np.isfinite(lcl):
        confiables["lcl"] = bool(tope <= float(lcl))

    if tope <= 200.0:
        vuelo = "radiosonda completa"
    elif tope <= 400.0:
        vuelo = "radiosonda parcial"
    elif tope <= 700.0:
        vuelo = "perfil de troposfera baja"
    else:
        vuelo = "capa limite (globo cautivo)"

    avisos = []
    if not confiables.get("cape_j_kg", False):
        if tope <= TOPE_REQUERIDO_HPA["cape_parcial"]:
            avisos.append({
                "indice": "cape_j_kg",
                "gravedad": "parcial",
                "mensaje": (
                    "el perfil termina a {:.0f} hPa y el nivel de equilibrio "
                    "tropical esta entre 150 y 200 hPa: el CAPE esta truncado "
                    "y subestima la energia disponible. Es el caso tipico del "
                    "BME280, que especifica presion hasta 300 hPa."
                ).format(tope),
            })
        else:
            avisos.append({
                "indice": "cape_j_kg",
                "gravedad": "no usable",
                "mensaje": (
                    "el perfil termina a {:.0f} hPa: el CAPE no se puede "
                    "calcular de forma util. Hace falta un sensor de presion "
                    "que llegue debajo de 200 hPa (el BME280 corta en 300)."
                ).format(tope),
            })

    if not confiables.get("pwat", False):
        fraccion = _fraccion_pwat_bajo(tope)
        avisos.append({
            "indice": "pwat_mm",
            "gravedad": "parcial",
            "mensaje": (
                "el perfil cubre cerca del {:.0%} del agua de la columna "
                "(termina a {:.0f} hPa): el PWAT es un piso, no el total."
            ).format(fraccion, tope),
        })

    for nombre in ("indice_k", "total_totals"):
        if not confiables.get(nombre, False):
            avisos.append({
                "indice": nombre,
                "gravedad": "no usable",
                "mensaje": ("necesita el nivel de 500 hPa y el perfil termina "
                            "a {:.0f} hPa.").format(tope),
            })

    return {
        "tope_hpa": round(tope, 1),
        "tope_km_aprox": round(_altura_aproximada_de(tope), 1),
        "vuelo": vuelo,
        "confiables": confiables,
        "avisos": avisos,
    }


def _fraccion_pwat_bajo(presion_hpa: float) -> float:
    """Fraccion del agua de la columna que queda por debajo de ese nivel.

    np.interp exige x creciente, y `niveles` ordenado de menor a mayor presion
    ya trae su fraccion correspondiente en el mismo orden: a 200 hPa queda el
    99.5% del agua debajo, y a 850 hPa solo el 60%. No hay que invertir nada
    (la primera version lo invirtio y daba 100% de cobertura para un perfil
    que terminaba a 850 hPa, o sea lo contrario de la verdad).
    """
    niveles = sorted(FRACCION_PWAT_BAJO)
    fracciones = [FRACCION_PWAT_BAJO[n] for n in niveles]
    return float(np.interp(presion_hpa, niveles, fracciones))


def _altura_aproximada_de(presion_hpa: float) -> float:
    """Altura en km por la atmosfera estandar. Solo para mostrar al usuario."""
    p = max(1e-3, float(presion_hpa))
    return 44.3308 * (1.0 - (p / 1013.25) ** 0.190263)


def validar_indices(indices: dict) -> list:
    """Avisos sobre indices fuera del rango fisicamente posible.

    Una fuente que valida su propio dato vale mucho mas que una que entrega
    numeros. Un CAPE de 18000 J/kg no es una tormenta historica: es un perfil
    mal construido, un error de unidades o un sensor descompuesto.
    """
    avisos = []
    for nombre, (bajo, alto) in RANGOS_POSIBLES.items():
        v = indices.get(nombre)
        if v is None or not np.isfinite(v):
            continue
        if not (bajo <= float(v) <= alto):
            avisos.append({
                "indice": nombre,
                "valor": round(float(v), 1),
                "rango_posible": [bajo, alto],
                "mensaje": ("{} = {:.1f} esta fuera del rango fisicamente "
                            "posible [{:.0f}, {:.0f}]: revisa unidades del "
                            "sensor y el orden de los niveles"
                            ).format(nombre, float(v), bajo, alto),
            })
    return avisos


def normalizar_indices(indices: dict, referencia=None) -> dict:
    """Pasa los indices a unidades de desviacion estandar.

    El CAPE entra como `raiz_cape` = sqrt(CAPE), por la razon fisica que
    explica REFERENCIA_INDICES.
    """
    referencia = referencia or REFERENCIA_INDICES
    ampliado = dict(indices)
    cape = indices.get("cape_j_kg")
    if cape is not None and np.isfinite(cape) and cape >= 0:
        ampliado["raiz_cape"] = math.sqrt(float(cape))
    z = {}
    for nombre, (media, desv) in referencia.items():
        v = ampliado.get(nombre)
        if v is None or not np.isfinite(v):
            continue
        z[nombre] = (float(v) - media) / max(1e-6, desv)
    return z


def media_campo_latente(indices: dict, coeficientes=None, referencia=None,
                        tope: float = 1.5) -> dict:
    """`mu` para el campo latente del modelo, a partir de los indices.

    Devuelve `mu` y el desglose de cuanto aporto cada indice, porque un numero
    solo no se puede defender ante una pregunta.

    `mu` se acota a +-1.5 desviaciones. El tope no es timidez: `mu` desplaza la
    probabilidad de lluvia de TODO el dominio, y con `mu = 3` la probabilidad
    se pega a 1 en todas las celdas, lo que destruye la dispersion del ensamble
    y con ella la unica salida util del sistema.
    """
    coeficientes = coeficientes or COEFICIENTES_PROBIT_PROVISIONALES
    z = normalizar_indices(indices, referencia)
    aportes = {}
    mu = float(coeficientes.get("intercepto", 0.0))
    for nombre, beta in coeficientes.items():
        if nombre == "intercepto" or nombre not in z:
            continue
        aporte = beta * z[nombre]
        aportes[nombre] = round(aporte, 4)
        mu += aporte
    mu_acotada = float(np.clip(mu, -tope, tope))
    avisos = validar_indices(indices)
    cobertura = evaluar_cobertura_vertical(indices)
    # El CAPE es el indice que mas pesa en mu. Si viene truncado por un perfil
    # corto, mu sale sesgada hacia abajo y hay que decirlo: una mu baja por
    # falta de sensor se ve igual que una mu baja por atmosfera estable.
    cape_truncado = not cobertura["confiables"].get("cape_j_kg", True)
    return {
        "mu": round(mu_acotada, 4),
        "mu_sin_acotar": round(mu, 4),
        "acotada": abs(mu) > tope,
        "aportes": aportes,
        "z": {k: round(v, 3) for k, v in z.items()},
        "coeficientes_provisionales": coeficientes is COEFICIENTES_PROBIT_PROVISIONALES,
        "avisos": avisos,
        "confiable": not avisos,
        "cobertura_vertical": cobertura,
        "cape_truncado": bool(cape_truncado),
        "nota_cobertura": (
            "el CAPE esta truncado por un perfil que termina a {:.0f} hPa, "
            "asi que mu subestima la inestabilidad".format(cobertura["tope_hpa"])
            if cape_truncado and cobertura["tope_hpa"] else None
        ),
    }


def calibrar_probit(indices_historicos, ocurrencia, referencia=None,
                    iteraciones: int = 50) -> dict:
    """Estima los coeficientes del probit por maxima verosimilitud.

    indices_historicos  lista de dicts de indices, uno por sondeo
    ocurrencia          array binario: llovio (1) o no (0) ese dia

    Modelo: P(lluvia) = Phi(b0 + sum b_j z_j). Se resuelve por Newton-Raphson
    con la matriz de informacion, que para probit converge en pocas vueltas.
    Devuelve coeficientes, errores estandar y el log-verosimilitud, para poder
    decir si un indice aporta o no.

    Esto es lo que convierte el globo de anecdota a dato: con cien sondeos y su
    lluvia observada, los coeficientes dejan de ser supuestos.
    """
    from ..estadistica import norm_cdf

    if len(indices_historicos) != len(ocurrencia):
        raise ValueError("indices y ocurrencia deben tener el mismo largo")
    y = np.asarray(ocurrencia, dtype=float)
    if not np.all(np.isin(y, (0.0, 1.0))):
        raise ValueError("ocurrencia debe ser binaria")
    if y.size < 30:
        raise ValueError(
            "con {} casos no se puede estimar nada util; se necesitan al "
            "menos 30 y de preferencia cientos".format(y.size)
        )

    nombres = [n for n in ("raiz_cape", "pwat_mm", "cin_j_kg", "indice_k")
               if all(n in normalizar_indices(ix, referencia)
                      for ix in indices_historicos)]
    if not nombres:
        raise ValueError("ningun indice esta presente en todos los sondeos")

    filas = []
    for ix in indices_historicos:
        z = normalizar_indices(ix, referencia)
        filas.append([1.0] + [z[n] for n in nombres])
    x = np.asarray(filas, dtype=float)

    beta = np.zeros(x.shape[1])
    for _ in range(iteraciones):
        eta = x @ beta
        phi = np.exp(-0.5 * eta ** 2) / math.sqrt(2 * math.pi)
        p = np.clip(np.asarray(norm_cdf(eta), dtype=float), 1e-9, 1 - 1e-9)
        # Gradiente y matriz de informacion del probit.
        peso = phi / (p * (1 - p))
        gradiente = x.T @ (peso * (y - p))
        info = (x * (phi * peso)[:, None]).T @ x
        try:
            paso = np.linalg.solve(info, gradiente)
        except np.linalg.LinAlgError:
            break
        beta = beta + paso
        if np.abs(paso).max() < 1e-8:
            break

    eta = x @ beta
    p = np.clip(np.asarray(norm_cdf(eta), dtype=float), 1e-9, 1 - 1e-9)
    log_vero = float((y * np.log(p) + (1 - y) * np.log(1 - p)).sum())
    try:
        errores = np.sqrt(np.diag(np.linalg.inv(info)))
    except np.linalg.LinAlgError:
        errores = np.full(beta.size, np.nan)

    coeficientes = {"intercepto": float(beta[0])}
    detalle = {}
    for i, nombre in enumerate(nombres, start=1):
        coeficientes[nombre] = float(beta[i])
        detalle[nombre] = {
            "coeficiente": round(float(beta[i]), 4),
            "error_estandar": round(float(errores[i]), 4),
            "z": round(float(beta[i] / errores[i]), 2) if errores[i] > 0 else None,
            "significativo_95": bool(errores[i] > 0
                                     and abs(beta[i] / errores[i]) > 1.96),
        }

    tasa = float(y.mean())
    log_vero_base = float(y.size * (tasa * math.log(max(tasa, 1e-9))
                                    + (1 - tasa) * math.log(max(1 - tasa, 1e-9))))
    return {
        "coeficientes": coeficientes,
        "indices_usados": nombres,
        "detalle": detalle,
        "casos": int(y.size),
        "tasa_base": round(tasa, 4),
        "log_verosimilitud": round(log_vero, 3),
        "pseudo_r2_mcfadden": round(1.0 - log_vero / log_vero_base, 4)
        if log_vero_base != 0 else None,
    }


def interpretar_indices(indices: dict) -> dict:
    """Traduccion de los indices a lenguaje operativo.

    Los cortes son los de uso comun en pronostico operativo. Sirven para que
    la interfaz pueda explicar, no solo mostrar numeros.
    """
    cape = indices.get("cape_j_kg", float("nan"))
    cin = indices.get("cin_j_kg", float("nan"))
    pwat = indices.get("pwat_mm", float("nan"))
    k = indices.get("indice_k", float("nan"))

    def rango(v, cortes, etiquetas):
        if not np.isfinite(v):
            return "sin dato"
        return etiquetas[int(np.digitize(v, cortes))]

    return {
        "inestabilidad": rango(
            cape, (300, 1000, 2500),
            ("estable", "inestabilidad debil", "inestabilidad moderada",
             "inestabilidad fuerte")),
        "inhibicion": rango(
            cin, (25, 100, 200),
            ("sin tapa", "tapa debil", "tapa moderada",
             "tapa fuerte: cuesta arrancar")),
        "humedad_columna": rango(
            pwat, (30, 45, 55),
            ("columna seca", "humedad normal", "columna humeda",
             "columna muy humeda: lluvia eficiente")),
        "potencial_tormenta": rango(
            k, (20, 30, 35, 40),
            ("nulo", "bajo", "moderado", "alto", "muy alto")),
    }


# --- utilidades ------------------------------------------------------------


def _flotante(texto) -> float:
    if texto is None:
        return float("nan")
    try:
        return float(str(texto).strip())
    except (TypeError, ValueError):
        return float("nan")


def _es_numero(texto: str) -> bool:
    return math.isfinite(_flotante(texto))
