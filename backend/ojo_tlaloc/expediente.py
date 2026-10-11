"""El expediente del hexagono: donde todas las fuentes se funden.

La idea
-------
Un hexagono deja de ser "una celda con pronostico" y pasa a ser un objeto con
expediente, como un predio con escritura. Cada celda acumula cuatro clases de
atributo, y cada atributo sabe de donde vino:

    ESTATICOS      terreno y ciudad. Elevacion, pendiente, uso de suelo,
                   impermeabilidad, cauces, infraestructura critica.
                   Fuente: OpenStreetMap, DEM.

    CLIMATOLOGICOS lo normal para la epoca. Lluvia, dias humedos, temperatura.
                   Fuente: NASA POWER.

    OBSERVADOS     el estado de hoy. Humedad de suelo del radar, lluvia
                   reciente, perfil atmosferico.
                   Fuente: NISAR, SMAP, IMERG, globo sonda.

    DERIVADOS      lo que se calcula de los anteriores. Riesgo, exposicion,
                   aptitud, ventanas de obra.

El pronostico estocastico es **uno de los consumidores** de este expediente,
no el centro del sistema. Esa es la diferencia entre un modelo con datos
pegados por fuera y una plataforma de fusion: con el expediente se pueden
construir productos que no son predictivos (diagnostico del estado actual,
analisis historico, aptitud de terreno, exposicion) usando las mismas capas.

Por que funciona
----------------
Porque la malla hexagonal es el indice espacial comun. Vectores de OSM,
rejillas de satelite y un perfil puntual de globo terminan todos en el mismo
hexagono, con el mismo id, y quedan comparables. Esa decision estaba tomada
desde el primer dia y es la que permite todo lo demas.

Procedencia hasta el final
--------------------------
El expediente nunca entrega un numero pelado: entrega el numero con su
`Procedencia`. Asi la interfaz puede rotular que es observado y que es
sintetico, cumplir la atribucion de ODbL, y el filtro de Kalman puede
ponderar por la incertidumbre que cada fuente declara.
"""

from __future__ import annotations

import numpy as np

from .fuentes.base import (
    NIVEL_DERIVADO,
    NIVEL_OBSERVADO,
    NIVEL_REANALISIS,
    NIVEL_SINTETICO,
    CapaFuente,
    ErrorFuente,
    Procedencia,
)

#: Clasificacion de las capas por su papel en el sistema. Sirve para que la
#: interfaz agrupe y para saber que falta.
FAMILIAS = {
    "estatico": (
        "elevacion_m", "pendiente_grados", "es_tierra", "dist_costa_km",
        "fraccion_impermeable", "fraccion_construida", "fraccion_pavimento",
        "fraccion_agua", "impermeabilidad_uso_suelo", "impermeabilidad_proxy_vial",
        "cobertura_uso_suelo", "densidad_vial", "densidad_cauces", "edificios",
        "area_pisos", "infraestructura_critica", "peso_critico",
        "capacidad_suelo_mm",
    ),
    "climatologico": (
        "lluvia_anual_power_mm", "dias_lluvia_power", "lluvia_anual_mm",
        "prob_lluvia_mes", "tmax_mes", "tmin_mes",
    ),
    "observado": (
        "humedad_suelo_obs", "lluvia_reciente_mm", "deformacion_mm_ano",
        "temperatura_superficie_c", "ndvi",
    ),
    "derivado": (
        "riesgo_escurrimiento", "indice_exposicion", "aptitud_constructiva",
        "dias_trabajables",
    ),
}


class Expediente:
    """Capas de todas las fuentes, alineadas a la malla, con procedencia."""

    def __init__(self, malla) -> None:
        self.malla = malla
        self.capas: dict[str, CapaFuente] = {}
        self.advertencias: list[dict] = []
        self.perfil_atmosferico = None     # el sondeo, si hay
        self.series_climatologicas = None  # las 12 series mensuales, si hay
        #: Desglose de equipamientos por celda: {indice: {"hospital": 4, ...}}.
        #: Lo llena el adaptador de OSM y lo usa la capa de exposicion para
        #: poder decir QUE hay en riesgo, no solo cuanto.
        self.detalle_critico = None

    # --- ingesta ----------------------------------------------------------

    def agregar(self, capa: CapaFuente, sobrescribir: bool = True) -> "Expediente":
        if len(capa.valores) != self.malla.n_celdas:
            raise ValueError(
                "la capa '{}' tiene {} valores y la malla {} celdas".format(
                    capa.nombre, len(capa.valores), self.malla.n_celdas
                )
            )
        if capa.nombre in self.capas and not sobrescribir:
            return self
        self.capas[capa.nombre] = capa
        return self

    def agregar_muchas(self, capas, sobrescribir: bool = True) -> "Expediente":
        for capa in (capas.values() if isinstance(capas, dict) else capas):
            self.agregar(capa, sobrescribir)
        return self

    def agregar_advertencias(self, advertencias) -> "Expediente":
        """Las fuentes declaran sus propios sesgos; aqui se acumulan."""
        for a in advertencias or ():
            if a not in self.advertencias:
                self.advertencias.append(a)
        return self

    # --- consulta ---------------------------------------------------------

    def tiene(self, nombre: str) -> bool:
        return nombre in self.capas

    def valores(self, nombre: str, defecto=None):
        """Array de una capa. `defecto` evita tener que preguntar antes."""
        if nombre in self.capas:
            return self.capas[nombre].valores
        if defecto is None:
            raise KeyError(
                "el expediente no tiene la capa '{}'. Tiene: {}".format(
                    nombre, ", ".join(sorted(self.capas))
                )
            )
        if np.isscalar(defecto):
            return np.full(self.malla.n_celdas, float(defecto))
        return np.asarray(defecto, dtype=float)

    def celda(self, celda) -> dict:
        """El expediente completo de un hexagono.

        Es la respuesta a "que se sabe de este pedazo de territorio", y es lo
        que alimenta el panel de detalle de la interfaz.
        """
        i = (self.malla.indice(celda) if isinstance(celda, str) else int(celda))
        if not 0 <= i < self.malla.n_celdas:
            raise IndexError("indice de celda fuera de rango")

        por_familia: dict[str, dict] = {f: {} for f in FAMILIAS}
        por_familia["otros"] = {}
        for nombre, capa in sorted(self.capas.items()):
            familia = next((f for f, nombres in FAMILIAS.items()
                            if nombre in nombres), "otros")
            v = float(capa.valores[i])
            por_familia[familia][nombre] = {
                "valor": None if not np.isfinite(v) else round(v, 4),
                "unidad": capa.unidad,
                "fuente": capa.procedencia.fuente,
                "nivel": capa.procedencia.nivel,
            }

        return {
            "id_celda": self.malla.ids[i],
            "geografia": {
                "lat": round(float(self.malla.lat[i]), 6),
                "lon": round(float(self.malla.lon[i]), 6),
                "area_km2": round(self.malla.area_celda_km2, 3),
                "escala": "1:{}".format(self.malla.n_ancho),
            },
            "datos": {f: d for f, d in por_familia.items() if d},
            "atmosfera": (self.perfil_atmosferico.resumen()
                          if self.perfil_atmosferico else None),
        }

    # --- calidad y procedencia -------------------------------------------

    def atribuciones(self) -> list:
        """Textos de atribucion que la interfaz DEBE mostrar.

        No es cortesia: ODbL de OpenStreetMap lo exige. Si esto no se muestra,
        se incumple la licencia.
        """
        vistas = []
        for capa in self.capas.values():
            texto = capa.procedencia.atribucion
            if texto and texto not in vistas:
                vistas.append(texto)
        if self.perfil_atmosferico:
            texto = self.perfil_atmosferico.procedencia().atribucion
            if texto and texto not in vistas:
                vistas.append(texto)
        return vistas

    def procedencias(self) -> dict:
        return {nombre: capa.procedencia.a_dict()
                for nombre, capa in sorted(self.capas.items())}

    def conteo_por_nivel(self) -> dict:
        conteo = {n: 0 for n in (NIVEL_OBSERVADO, NIVEL_REANALISIS,
                                 NIVEL_DERIVADO, NIVEL_SINTETICO)}
        for capa in self.capas.values():
            conteo[capa.procedencia.nivel] = conteo.get(
                capa.procedencia.nivel, 0) + 1
        return conteo

    def capas_sinteticas(self) -> list:
        """Que capas NO son dato. Lo que la interfaz tiene que rotular."""
        return sorted(n for n, c in self.capas.items()
                      if c.procedencia.nivel == NIVEL_SINTETICO)

    def faltantes(self) -> dict:
        """Que capas de cada familia no estan todavia, para la hoja de ruta."""
        return {
            familia: [n for n in nombres if n not in self.capas]
            for familia, nombres in FAMILIAS.items()
        }

    def resumen(self) -> dict:
        return {
            "celdas": self.malla.n_celdas,
            "escala": "1:{}".format(self.malla.n_ancho),
            "capas": len(self.capas),
            "por_nivel": self.conteo_por_nivel(),
            "sinteticas": self.capas_sinteticas(),
            "tiene_perfil_atmosferico": self.perfil_atmosferico is not None,
            "advertencias": len(self.advertencias),
            "atribuciones": self.atribuciones(),
            "detalle_capas": [c.resumen() for c in self.capas.values()],
        }

    # --- salida -----------------------------------------------------------

    def a_geojson(self, capas=None) -> dict:
        """GeoJSON con las capas pedidas como propiedades."""
        nombres = list(self.capas) if capas is None else list(capas)
        faltan = [n for n in nombres if n not in self.capas]
        if faltan:
            raise KeyError("el expediente no tiene: {}".format(", ".join(faltan)))
        props = {n: self.capas[n].valores for n in nombres}
        gj = self.malla.a_geojson(props)
        gj["procedencia"] = {n: self.capas[n].procedencia.a_dict() for n in nombres}
        gj["atribuciones"] = self.atribuciones()
        return gj


# --- construccion ----------------------------------------------------------


def construir_expediente(
    malla,
    clima=None,
    usar_osm: bool = True,
    usar_power: bool = True,
    sondeo_texto: str | None = None,
    tolerar_fallos: bool = True,
) -> Expediente:
    """Arma el expediente con todas las fuentes disponibles.

    `tolerar_fallos=True` es el comportamiento por defecto y es deliberado: si
    Overpass esta saturado o no hay internet, el sistema tiene que seguir
    funcionando con lo que tenga y **decir que le falto**, no caerse. Una
    plataforma de fusion que exige todas sus fuentes para arrancar no sirve en
    campo.

    Devuelve el expediente; lo que no se pudo traer queda en
    `expediente.advertencias`.
    """
    from .climatologia import Climatologia
    from .fuentes.base import NIVEL_SINTETICO

    exp = Expediente(malla)

    # --- geografia de la climatologia (sintetica o real)
    clima = clima if clima is not None else Climatologia.sintetica(malla)
    proc_sint = Procedencia(
        fuente="climatologia sintetica de El Ojo de Tlaloc",
        nivel=NIVEL_SINTETICO,
        nota=("derivada de las normales del puerto de Veracruz mas gradientes; "
              "NO es dato observado"),
    )
    exp.agregar_muchas([
        CapaFuente("elevacion_m", clima.elevacion_m, "m", proc_sint),
        CapaFuente("es_tierra", clima.es_tierra.astype(float), "0/1", proc_sint),
        CapaFuente("dist_costa_km", clima.dist_costa_km, "km", proc_sint),
        CapaFuente("capacidad_suelo_mm", clima.capacidad_suelo_mm, "mm", proc_sint),
    ])

    # --- OpenStreetMap
    if usar_osm:
        try:
            from .fuentes.osm import FuenteOSM

            fuente = FuenteOSM()
            exp.agregar_muchas(fuente.capas(malla))
            exp.detalle_critico = getattr(fuente, "detalle_critico", None)
        except (ErrorFuente, OSError) as e:
            _anotar_fallo(exp, "OpenStreetMap", e,
                          "sin impermeabilidad real ni capa de exposicion")

    # --- NASA POWER
    if usar_power:
        try:
            from .fuentes.power import FuentePOWER

            fuente = FuentePOWER()
            fuente.calibrar_umbral_por_dias(malla)
            paquete = fuente.series_para_malla(malla)
            exp.agregar_muchas(paquete["capas"])
            exp.agregar_advertencias(paquete["advertencias"])
            exp.series_climatologicas = paquete["series"]
        except (ErrorFuente, OSError) as e:
            _anotar_fallo(exp, "NASA POWER", e,
                          "la climatologia se queda sintetica")

    # --- perfil atmosferico
    if sondeo_texto:
        try:
            from .fuentes.sondeo import leer_sondeo

            exp.perfil_atmosferico = leer_sondeo(sondeo_texto)
            avisos = exp.perfil_atmosferico.resumen().get("avisos") or []
            for a in avisos:
                exp.agregar_advertencias([{
                    "variable": a["indice"],
                    "sesgo": "valor fuera de rango fisico",
                    "detalle": a["mensaje"],
                    "como_se_corrige": "revisar el sensor o el formato del perfil",
                }])
        except (ErrorFuente, ValueError) as e:
            _anotar_fallo(exp, "sondeo atmosferico", e,
                          "el modelo se queda climatologico, sin informacion "
                          "del dia")

    return exp


def _anotar_fallo(exp: Expediente, fuente: str, error, consecuencia: str) -> None:
    exp.agregar_advertencias([{
        "variable": fuente,
        "sesgo": "fuente no disponible",
        "detalle": str(error)[:400],
        "consecuencia": consecuencia,
        "como_se_corrige": "revisar conexion o credenciales y volver a construir",
    }])
