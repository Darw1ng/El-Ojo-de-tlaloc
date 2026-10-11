"""Protocolo comun de las fuentes de datos, con procedencia y cache.

La idea que sostiene todo el sistema
------------------------------------
La malla hexagonal es el **indice espacial comun**. Cualquier fuente
—vectores de OpenStreetMap, rejillas de satelite de la NASA, un perfil crudo
de globo sonda— se agrega al mismo hexagono y queda comparable con las demas.
Eso es lo que permite que el proyecto sea una plataforma de fusion y no un
modelo con datos pegados por fuera.

Procedencia
-----------
Cada dato que entra al sistema trae una `Procedencia`: de donde viene, cuando
se obtuvo, con que resolucion nativa, con que incertidumbre y bajo que
licencia. No es burocracia:

1. **Honestidad.** Un valor sintetico y una observacion de satelite no pueden
   verse iguales en la interfaz. La procedencia es lo que permite rotular.
2. **Licencias.** OSM es ODbL y exige atribucion. Si el dato no sabe de donde
   viene, la atribucion se pierde y se incumple la licencia.
3. **Incertidumbre.** El filtro de Kalman necesita la varianza de la
   observacion. Si cada fuente la declara, la asimilacion pondera sola.
4. **Reproducibilidad.** Saber que granulo y que fecha produjo un mapa.

Cache
-----
Las fuentes externas se bajan una vez y se guardan en `datos/entrada/cache/`.
Overpass y NASA POWER son servicios publicos y gratuitos: pegarles en cada
peticion seria abusar de ellos, aparte de lento. El cache es parte del
contrato de buena vecindad con esos servicios.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

#: Identificacion del cliente ante servicios publicos. Overpass rechaza
#: peticiones sin User-Agent reconocible (devuelve 406).
USER_AGENT = "ElOjoDeTlaloc/0.1 (NASA Space Apps 2026; https://github.com/Darw1ng/El-Ojo-de-tlaloc)"

#: Donde se guarda lo descargado.
RAIZ_CACHE = Path(__file__).resolve().parents[3] / "datos" / "entrada" / "cache"

#: Calidad del dato, para que la interfaz pueda rotular sin adivinar.
NIVEL_OBSERVADO = "observado"      # medicion real
NIVEL_REANALISIS = "reanalisis"    # modelo alimentado con observaciones
NIVEL_DERIVADO = "derivado"        # calculado a partir de otras capas
NIVEL_SINTETICO = "sintetico"      # inventado por nosotros, no es dato

NIVELES = (NIVEL_OBSERVADO, NIVEL_REANALISIS, NIVEL_DERIVADO, NIVEL_SINTETICO)


@dataclass
class Procedencia:
    """De donde salio un dato. Viaja pegado al dato hasta la interfaz."""

    fuente: str                       # "OpenStreetMap", "NASA POWER", "NISAR GCOV"
    nivel: str = NIVEL_SINTETICO      # uno de NIVELES
    obtenido: str = ""                # ISO 8601
    resolucion_nativa: str = ""       # "30 m", "0.5 grados", "puntual"
    cadencia: str = ""                # "12 dias", "30 min", "climatologia"
    incertidumbre: float | None = None  # en unidades de la variable
    licencia: str = ""
    atribucion: str = ""              # texto que la interfaz DEBE mostrar
    url: str = ""
    nota: str = ""

    def __post_init__(self) -> None:
        if self.nivel not in NIVELES:
            raise ValueError(
                "nivel '{}' invalido; validos: {}".format(self.nivel, NIVELES)
            )
        if not self.obtenido:
            self.obtenido = time.strftime("%Y-%m-%dT%H:%M:%S")

    @property
    def es_dato_real(self) -> bool:
        """False para lo sintetico. La interfaz lo usa para rotular."""
        return self.nivel != NIVEL_SINTETICO

    def a_dict(self) -> dict:
        return asdict(self)


@dataclass
class CapaFuente:
    """Una variable agregada a la malla, con su procedencia.

    valores  (n_celdas,) float, NaN donde la fuente no tiene dato
    """

    nombre: str
    valores: np.ndarray
    unidad: str
    procedencia: Procedencia
    cobertura: np.ndarray | None = field(default=None)  # (n,) int, conteo de aportes

    def __post_init__(self) -> None:
        self.valores = np.asarray(self.valores, dtype=float)
        if self.valores.ndim != 1:
            raise ValueError("valores debe ser (n_celdas,)")

    @property
    def n_con_dato(self) -> int:
        return int(np.isfinite(self.valores).sum())

    @property
    def fraccion_cubierta(self) -> float:
        return self.n_con_dato / max(1, self.valores.size)

    def resumen(self) -> dict:
        v = self.valores[np.isfinite(self.valores)]
        return {
            "nombre": self.nombre,
            "unidad": self.unidad,
            "fuente": self.procedencia.fuente,
            "nivel": self.procedencia.nivel,
            "celdas_con_dato": self.n_con_dato,
            "fraccion_cubierta": round(self.fraccion_cubierta, 4),
            "min": None if not v.size else round(float(v.min()), 4),
            "media": None if not v.size else round(float(v.mean()), 4),
            "max": None if not v.size else round(float(v.max()), 4),
        }


class ErrorFuente(RuntimeError):
    """La fuente no pudo entregar datos. El mensaje dice que falta."""


class FuenteRemota:
    """Base de las fuentes que bajan de internet, con cache en disco."""

    nombre = "generica"

    def __init__(self, cache: Path | None = None, forzar_descarga: bool = False) -> None:
        self.cache = Path(cache) if cache else RAIZ_CACHE / self.nombre
        self.forzar_descarga = forzar_descarga
        self.cache.mkdir(parents=True, exist_ok=True)

    # --- cache ------------------------------------------------------------

    def _ruta_cache(self, clave: str, ext: str = "json") -> Path:
        h = hashlib.sha1(clave.encode("utf-8")).hexdigest()[:16]
        return self.cache / "{}.{}".format(h, ext)

    def _leer_cache(self, clave: str):
        ruta = self._ruta_cache(clave)
        if ruta.exists() and not self.forzar_descarga:
            try:
                return json.loads(ruta.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return None
        return None

    def _escribir_cache(self, clave: str, datos) -> None:
        self._ruta_cache(clave).write_text(
            json.dumps(datos, ensure_ascii=False), encoding="utf-8"
        )

    # --- red --------------------------------------------------------------

    #: Codigos que significan "estoy ocupado, vuelve luego" y no "tu peticion
    #: esta mal". Overpass devuelve 429 por tasa y 504 cuando esta saturado.
    CODIGOS_TRANSITORIOS = frozenset({429, 500, 502, 503, 504})

    #: Espera minima entre peticiones consecutivas al mismo servicio. Overpass
    #: y POWER son publicos y gratuitos: pegarles en rafaga es abusar de ellos
    #: y ademas provoca justo los 429/504 que luego hay que reintentar.
    espera_entre_peticiones = 2.0
    _ultima_peticion = 0.0

    def _esperar_turno(self) -> None:
        falta = self.espera_entre_peticiones - (time.time() - self._ultima_peticion)
        if falta > 0:
            time.sleep(falta)

    def _pedir_una_vez(self, url: str, cuerpo: bytes | None,
                       tiempo_limite: float) -> str:
        """Una peticion, sin reintentos. Lanza para que decida quien llama."""
        self._esperar_turno()
        peticion = urllib.request.Request(
            url, data=cuerpo, headers={"User-Agent": USER_AGENT}
        )
        try:
            with urllib.request.urlopen(peticion, timeout=tiempo_limite) as r:
                return r.read().decode("utf-8", errors="replace")
        finally:
            FuenteRemota._ultima_peticion = time.time()

    def _pedir(
        self,
        url: str | tuple | list,
        datos: dict | str | None = None,
        rondas: int = 3,
        espera: float = 8.0,
        tiempo_limite: float = 180.0,
    ) -> str:
        """POST o GET con User-Agent, espejos y espera creciente.

        `url` puede ser un espejo o varios. La estrategia es **una pasada por
        todos los espejos antes de insistir en ninguno**: si el principal esta
        saturado, el siguiente suele responder de inmediato, y agotar
        reintentos en el primero solo lo castiga mas y tarda mas. Si toda la
        ronda falla, espera y repite.

        Se acumulan los errores de todos los espejos, porque reportar solo el
        ultimo esconde la causa real (medido: el principal daba 504 por tasa y
        el espejo respondia bien, pero el mensaje culpaba al espejo).
        """
        espejos = (url,) if isinstance(url, str) else tuple(url)
        cuerpo = None
        if isinstance(datos, dict):
            cuerpo = urllib.parse.urlencode(datos).encode("utf-8")
        elif isinstance(datos, str):
            cuerpo = datos.encode("utf-8")

        fallos: list[str] = []
        for ronda in range(rondas):
            transitorio = False
            for espejo in espejos:
                try:
                    return self._pedir_una_vez(espejo, cuerpo, tiempo_limite)
                except urllib.error.HTTPError as e:
                    fallos.append("{} -> HTTP {} {}".format(espejo, e.code, e.reason))
                    if e.code in self.CODIGOS_TRANSITORIOS:
                        transitorio = True
                        reintentar_en = e.headers.get("Retry-After")
                        if reintentar_en:
                            try:
                                time.sleep(min(60.0, float(reintentar_en)))
                            except (TypeError, ValueError):
                                pass
                except (urllib.error.URLError, TimeoutError, OSError) as e:
                    fallos.append("{} -> {}".format(espejo, e))
                    transitorio = True
            if not transitorio:
                break   # el problema es la peticion, no el servidor
            if ronda < rondas - 1:
                time.sleep(espera * (ronda + 1))

        raise ErrorFuente(
            "{}: ningun espejo respondio.\n  {}".format(
                self.nombre, "\n  ".join(fallos)
            )
        )


class FuenteConCredenciales(FuenteRemota):
    """Fuentes que necesitan login de Earthdata (IMERG, SMAP, NISAR, DEM).

    No se implementa la descarga porque requiere credenciales que no estan en
    el repositorio. Lo que si esta es la interfaz y el mensaje de que falta,
    para que el dia que haya cuenta sea rellenar un metodo y no rediseniar.
    """

    nombre = "earthdata"
    variable = ""
    como_obtener = ""

    def __init__(self, usuario: str | None = None, clave: str | None = None,
                 **kw) -> None:
        super().__init__(**kw)
        self.usuario = usuario
        self.clave = clave

    @property
    def tiene_credenciales(self) -> bool:
        return bool(self.usuario and self.clave)

    def exigir_credenciales(self) -> None:
        if not self.tiene_credenciales:
            raise ErrorFuente(
                "{} necesita credenciales de Earthdata y no las tiene.\n"
                "Como obtenerlas: {}".format(self.nombre, self.como_obtener)
            )
