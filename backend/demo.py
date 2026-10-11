"""Demostracion de la cadena completa, sin frontend y sin servidor.

    python demo.py

Corre todo lo que hace el sistema y lo imprime: malla, climatologia,
pronostico, probabilidades, asimilacion del dato de radar y metricas. Deja un
JSON en datos/salida/demo.json con las capas del primer dia, para que quien
haga el frontend tenga datos de verdad con los que trabajar sin levantar el
backend.

Sirve para tres cosas: revisar de un golpe que nada se rompio, tener los
numeros a mano para la presentacion, y ensenar que la asimilacion de verdad
mueve el pronostico.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np

# Las celdas de mar son NaN completo en humedad y escurrimiento (es la
# convencion, ver modelo.ResultadoSimulacion). Promediar sobre ellas avisa por
# slice vacio y devuelve NaN, que es justo lo que se quiere: aqui el aviso solo
# ensucia la salida de la demo.
warnings.filterwarnings("ignore", category=RuntimeWarning)

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ojo_tlaloc import __version__
from ojo_tlaloc.asimilacion import asimilar, observacion_sintetica
from ojo_tlaloc.climatologia import Climatologia, LLUVIA_MENSUAL_MM, MESES
from ojo_tlaloc.config import SEMILLA_DEFECTO
from ojo_tlaloc.ensamble import capa, probabilidad_umbral, resumen_dominio, riesgo
from ojo_tlaloc.malla import MallaHexagonal
from ojo_tlaloc.metricas import crpss, dispersion_vs_error
from ojo_tlaloc.modelo import SimuladorEstocastico

FECHA = dt.date(2026, 9, 15)
SALIDA = Path(__file__).resolve().parents[1] / "datos" / "salida" / "demo.json"


def titulo(texto: str) -> None:
    print()
    print("=" * 72)
    print("  " + texto)
    print("=" * 72)


def main() -> None:
    print("El Ojo de Tlaloc v{} - demostracion de la cadena completa".format(__version__))
    print("Fecha del pronostico: {}  |  semilla: {}".format(FECHA, SEMILLA_DEFECTO))

    # ------------------------------------------------------------------ malla
    titulo("1. MALLA HEXAGONAL (escala 1:16)")
    t0 = time.perf_counter()
    malla = MallaHexagonal()
    clima = Climatologia.sintetica(malla)
    sim = SimuladorEstocastico(malla, clima)
    print("construccion (incluye Cholesky de la covarianza): {:.0f} ms"
          .format((time.perf_counter() - t0) * 1000))
    for k, v in malla.metadata.items():
        print("  {:18s} {}".format(k, v))
    print("  celda del centro del mapa: {}".format(malla.ids[malla.indice("OT0.0.0")]))

    # ---------------------------------------------------------- climatologia
    titulo("2. CLIMATOLOGIA (sintetica, calibrada a las normales del puerto)")
    for k, v in clima.resumen().items():
        print("  {:24s} {}".format(k, v))
    costa = int(np.argmin(np.where(clima.es_tierra, clima.elevacion_m, 1e9)))
    print()
    print("  Acumulado mensual en {} (elevacion {:.0f} m):"
          .format(malla.ids[costa], clima.elevacion_m[costa]))
    print("  {:12s} {:>8s} {:>8s}".format("mes", "normal", "modelo"))
    for mes in range(1, 13):
        print("  {:12s} {:8.0f} {:8.1f}".format(
            MESES[mes - 1], LLUVIA_MENSUAL_MM[mes - 1],
            float(clima.lluvia_mensual_esperada(mes)[costa])))

    # ------------------------------------------------------------ pronostico
    titulo("3. PRONOSTICO (200 miembros x 14 dias)")
    t0 = time.perf_counter()
    r = sim.simular(FECHA, n_dias=14, n_miembros=200, semilla=SEMILLA_DEFECTO)
    print("calculo: {:.2f} s  |  memoria: {:.1f} MB"
          .format(time.perf_counter() - t0, sim.memoria_estimada_mb(14, 200)))
    for k, v in resumen_dominio(r, clima.es_tierra).items():
        print("  {:24s} {}".format(k, v))

    print()
    print("  Lluvia por dia (mediana espacial de tierra, mm):")
    print("  {:12s} {:>7s} {:>7s} {:>7s}".format("fecha", "p10", "p50", "p90"))
    for d in range(r.n_dias):
        vals = [float(np.nanmedian(capa(r, "lluvia", d, q)["valores"][clima.es_tierra]))
                for q in ("p10", "p50", "p90")]
        print("  {:12s} {:7.1f} {:7.1f} {:7.1f}".format(r.fechas[d], *vals))

    # --------------------------------------------------------- probabilidades
    titulo("4. PROBABILIDADES Y ALERTA")
    tierra = clima.es_tierra
    for umbral in (1.0, 20.0, 50.0, 70.0):
        p = probabilidad_umbral(r, "lluvia", 0, umbral, ventana_dias=3)["valores"]
        print("  P(lluvia 72 h > {:5.0f} mm)   media {:.3f}   max {:.3f}"
              .format(umbral, float(np.nanmean(p[tierra])), float(np.nanmax(p[tierra]))))
    print()
    a = riesgo(r, dia=0, ventana_dias=3, umbral_mm=60.0)
    print("  {}".format(a["escala"]["etiqueta"]))
    etiquetas, conteos = np.unique(a["etiqueta_categoria"], return_counts=True)
    for e, c in zip(etiquetas, conteos):
        print("    {:12s} {:4d} celdas".format(e, int(c)))

    # ------------------------------------------------------------ asimilacion
    titulo("5. ASIMILACION DEL DATO DE RADAR")
    previo = sim.simular(FECHA, n_dias=1, n_miembros=200,
                         semilla=SEMILLA_DEFECTO).humedad_suelo[:, 0, :].astype(float)
    obs = observacion_sintetica(malla, clima, FECHA - dt.timedelta(days=1),
                                saturacion_base=0.30, semilla=SEMILLA_DEFECTO)
    res = asimilar(previo, obs, rng=np.random.default_rng(SEMILLA_DEFECTO))
    for k, v in res["diagnostico"].items():
        print("  {:28s} {}".format(k, v))

    print()
    print("  Efecto en el pronostico (mismo clima, distinto suelo inicial):")
    seco = sim.simular(FECHA, n_dias=3, n_miembros=200, semilla=7,
                       humedad_inicial=0.10, dias_calentamiento=0)
    mojado = sim.simular(FECHA, n_dias=3, n_miembros=200, semilla=7,
                         humedad_inicial=0.90, dias_calentamiento=0)
    print("    misma lluvia en los dos casos: {}"
          .format(bool(np.allclose(seco.lluvia_mm, mojado.lluvia_mm))))
    print("    escurrimiento dia 1, suelo seco:    {:6.2f} mm"
          .format(float(np.nanmean(seco.escurrimiento_mm[:, 0, tierra]))))
    print("    escurrimiento dia 1, suelo mojado:  {:6.2f} mm"
          .format(float(np.nanmean(mojado.escurrimiento_mm[:, 0, tierra]))))
    print("    -> esto es lo que aporta NISAR: la misma lluvia, otro riesgo")

    # --------------------------------------------------------------- metricas
    titulo("6. VERIFICACION (verdad sintetica: un miembro como realidad)")
    verdad = r.lluvia_mm[0][:, tierra].ravel()
    ens = r.lluvia_mm[1:][:, :, tierra].reshape(199, -1)
    ref = sim.simular(dt.date(2026, 3, 1), n_dias=14, n_miembros=199,
                      semilla=32).lluvia_mm[:, :, tierra].reshape(199, -1)
    print("  CRPSS contra climatologia de temporada seca: {:.4f}"
          .format(crpss(ens, verdad, ref)))
    d = dispersion_vs_error(ens, verdad)
    print("  razon dispersion/error: {}  ->  {}"
          .format(d["razon_dispersion_error"], d["diagnostico"]))
    print()
    print("  Nota: estas metricas son de consistencia interna. La habilidad")
    print("  real necesita una serie observada; ver docs/06-validacion.md.")

    # ----------------------------------------------------------------- salida
    paquete = {
        "generado": dt.datetime.now().isoformat(timespec="seconds"),
        "version": __version__,
        "advertencia": ("climatologia sintetica y observacion de humedad "
                        "sintetica; no son datos de NISAR"),
        "malla": malla.metadata,
        "ids_celdas": list(malla.ids),
        "geografia": {
            "lat": [round(float(v), 6) for v in malla.lat],
            "lon": [round(float(v), 6) for v in malla.lon],
            "es_tierra": [bool(v) for v in clima.es_tierra],
            "elevacion_m": _lista(clima.elevacion_m),
        },
        "pronostico": {
            "fecha_inicio": FECHA.isoformat(),
            "fechas": r.fechas,
            "semilla": r.semilla,
            "capas_dia_0": {
                nombre: _lista(capa(r, var, 0, est)["valores"])
                for nombre, var, est in (
                    ("lluvia_p50", "lluvia", "p50"),
                    ("lluvia_p90", "lluvia", "p90"),
                    ("lluvia_rango", "lluvia", "rango"),
                    ("tmax_p50", "tmax", "p50"),
                    ("humedad_suelo_p50", "humedad_suelo", "p50"),
                    ("escurrimiento_p50", "escurrimiento", "p50"),
                )
            },
            "prob_lluvia_72h_mayor_50mm": _lista(
                probabilidad_umbral(r, "lluvia", 0, 50.0, 3)["valores"]
            ),
            "riesgo": {
                "probabilidad": _lista(a["valores"]),
                "categoria": [int(k) for k in a["categoria"]],
                "etiqueta": list(a["etiqueta_categoria"]),
            },
        },
        "asimilacion": {
            "diagnostico": res["diagnostico"],
            "humedad_previa": _lista(np.nanmean(previo, axis=0)),
            "humedad_observada": _lista(obs.valores),
            "humedad_posterior": _lista(np.nanmean(res["ensamble"], axis=0)),
        },
    }
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps(paquete, indent=1, ensure_ascii=False),
                      encoding="utf-8")
    titulo("LISTO")
    print("  {}  ({:.0f} KB)".format(SALIDA, SALIDA.stat().st_size / 1024))


def _lista(a) -> list:
    a = np.asarray(a, dtype=float)
    return [None if not np.isfinite(v) else round(float(v), 4) for v in a]


if __name__ == "__main__":
    main()
