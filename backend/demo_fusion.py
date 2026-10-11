"""Demostracion de la plataforma de fusion completa.

    python demo_fusion.py

Baja datos reales de OpenStreetMap y de NASA POWER, lee un perfil de globo
sonda, arma el expediente del territorio y produce los cinco productos:
diagnostico, pronostico, exposicion, aptitud y ventanas de obra.

La primera corrida tarda unos minutos porque descarga; despues sale del cache
en segundos. Deja `datos/salida/demo_fusion.json` con todo, para que quien
haga el frontend trabaje con datos de verdad sin levantar el backend.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
warnings.filterwarnings("ignore", category=RuntimeWarning)

from ojo_tlaloc import __version__
from ojo_tlaloc.analisis import (
    aptitud_constructiva,
    exposicion_por_riesgo,
    pendiente_desde_elevacion,
    resumen_exposicion,
    ventanas_de_obra,
)
from ojo_tlaloc.analisis.ventanas import calendario_celda
from ojo_tlaloc.climatologia import Climatologia, MESES
from ojo_tlaloc.config import SEMILLA_DEFECTO
from ojo_tlaloc.ensamble import riesgo
from ojo_tlaloc.expediente import construir_expediente
from ojo_tlaloc.fuentes.sondeo import media_campo_latente
from ojo_tlaloc.malla import MallaHexagonal
from ojo_tlaloc.modelo import ParametrosModelo, SimuladorEstocastico

FECHA = dt.date(2026, 9, 15)
SALIDA = Path(__file__).resolve().parents[1] / "datos" / "salida" / "demo_fusion.json"

#: Perfil de ejemplo con la forma que escribe una sonda casera: presion,
#: temperatura y humedad relativa del BME280, mas altura del GPS.
SONDEO_EJEMPLO = """presion_hpa,temp_c,humedad_rel,altura_m
1008,29.5,78,20
1000,28.9,80,90
950,25.1,85,540
900,21.8,88,1010
850,18.2,84,1500
800,14.9,75,2010
700,8.1,60,3100
600,1.2,45,4300
500,-7.5,35,5700
400,-18.9,30,7300
300,-34.2,25,9400
200,-54.1,20,12200
"""


def titulo(t: str) -> None:
    print()
    print("=" * 74)
    print("  " + t)
    print("=" * 74)


def main() -> None:
    print("El Ojo de Tlaloc v{} - plataforma de fusion".format(__version__))
    print("Area: enlace OSM 11/19.1704/-96.1654 | fecha {} | semilla {}"
          .format(FECHA, SEMILLA_DEFECTO))

    # ------------------------------------------------------------ expediente
    titulo("1. EXPEDIENTE DEL TERRITORIO")
    malla = MallaHexagonal()
    print("malla: {} hexagonos a escala 1:{} ({:.2f} km2 cada uno)".format(
        malla.n_celdas, malla.n_ancho, malla.area_celda_km2))
    print("bajando OpenStreetMap y NASA POWER (se cachea en disco)...")
    t0 = time.perf_counter()
    exp = construir_expediente(malla, sondeo_texto=SONDEO_EJEMPLO)
    print("listo en {:.1f} s".format(time.perf_counter() - t0))

    r = exp.resumen()
    print()
    print("{} capas: {}".format(r["capas"], r["por_nivel"]))
    print()
    print("{:<30} {:<10} {:>9} {:>9} {:>9}".format(
        "capa", "nivel", "min", "media", "max"))
    for d in sorted(r["detalle_capas"], key=lambda x: (x["nivel"], x["nombre"])):
        print("{:<30} {:<10} {:>9} {:>9} {:>9}".format(
            d["nombre"][:30], d["nivel"][:10],
            _fmt(d["min"]), _fmt(d["media"]), _fmt(d["max"])))

    print()
    print("ATRIBUCIONES que la interfaz debe mostrar:")
    for a in exp.atribuciones():
        print("  - " + a)
    print()
    print("CAPAS SINTETICAS que hay que rotular (no son dato):")
    print("  " + ", ".join(exp.capas_sinteticas()))
    print()
    print("SESGOS que las fuentes declaran de si mismas:")
    for a in exp.advertencias:
        print("  [{}] {}".format(a["variable"], a["sesgo"]))
        print("      se corrige con: {}".format(a.get("como_se_corrige", "?")))

    # ------------------------------------------- diagnostico del territorio
    titulo("2. DIAGNOSTICO (no es pronostico: es que hay aqui)")
    imperm = exp.valores("fraccion_impermeable", defecto=0.0)
    vial = exp.valores("densidad_vial", defecto=0.0)
    critica = exp.valores("infraestructura_critica", defecto=0.0)
    es_tierra = exp.valores("es_tierra") > 0.5
    pend = pendiente_desde_elevacion(malla, exp.valores("elevacion_m"))

    print("impermeabilidad en tierra: media {:.1%}, maxima {:.1%}".format(
        float(np.nanmean(imperm[es_tierra])), float(np.nanmax(imperm))))
    print("pendiente: media {:.2f} grados, maxima {:.2f}".format(
        float(pend["pendiente_max_grados"].mean()),
        float(pend["pendiente_max_grados"].max())))
    print("equipamientos criticos mapeados: {:.0f} en {} celdas".format(
        critica.sum(), int((critica > 0).sum())))
    print()
    print("las 5 celdas mas urbanizadas:")
    print("  {:<12} {:>7} {:>8} {:>10} {:>9}".format(
        "celda", "imperm", "vial", "edificios", "criticos"))
    for i in np.argsort(-np.nan_to_num(imperm))[:5]:
        i = int(i)
        print("  {:<12} {:>6.1%} {:>7.1f} {:>10.0f} {:>9.0f}".format(
            malla.ids[i], imperm[i], vial[i],
            exp.valores("edificios", defecto=0.0)[i], critica[i]))

    # --------------------------------------------------- clima y pronostico
    titulo("3. CLIMATOLOGIA REAL Y PRONOSTICO")
    if exp.series_climatologicas:
        clima = Climatologia.desde_normales(malla, **exp.series_climatologicas)
        print("climatologia: NASA POWER, 21 anos de datos diarios")
    else:
        clima = Climatologia.sintetica(malla)
        print("climatologia: SINTETICA (POWER no respondio)")

    print("{:<12} {:>10} {:>10} {:>8}".format("mes", "lluvia mm", "dias %", "k"))
    for m in range(1, 13):
        s = exp.series_climatologicas
        print("{:<12} {:>10.1f} {:>9.0f}% {:>8.2f}".format(
            MESES[m - 1],
            s["lluvia_mensual_mm"][m - 1] if s else 0.0,
            (s["frac_dias_lluvia"][m - 1] * 100) if s else 0.0,
            s["weibull_forma"][m - 1] if s else 0.0))

    perfil = exp.perfil_atmosferico
    mu = media_campo_latente(perfil.indices) if perfil else None
    if mu:
        print()
        print("perfil atmosferico ({}):".format(perfil.procedencia().fuente))
        for k in ("cape_j_kg", "cin_j_kg", "pwat_mm", "lcl_m", "indice_k"):
            print("  {:<12} {}".format(k, perfil.indices[k]))
        for k, v in perfil.resumen()["interpretacion"].items():
            print("  {:<18} {}".format(k, v))
        print("  mu del campo latente: {:+.3f} (aportes: {})".format(
            mu["mu"], mu["aportes"]))

    sim = SimuladorEstocastico(
        malla, clima, ParametrosModelo(fraccion_impermeable=imperm))
    sin_sondeo = sim.simular(FECHA, n_dias=10, n_miembros=200,
                             semilla=SEMILLA_DEFECTO)
    con_sondeo = sim.simular(FECHA, n_dias=10, n_miembros=200,
                             semilla=SEMILLA_DEFECTO,
                             mu_campo=(mu["mu"] if mu and mu["confiable"] else None))

    print()
    print("acumulado de 10 dias (mediana espacial de tierra):")
    for nombre, res in (("climatologico (sin sondeo)", sin_sondeo),
                        ("con el perfil del globo", con_sondeo)):
        acum = res.lluvia_mm[:, :, es_tierra].sum(axis=1).mean(axis=1)
        print("  {:<28} p10 {:6.1f}  p50 {:6.1f}  p90 {:6.1f} mm".format(
            nombre, *np.percentile(acum, [10, 50, 90])))
    print("  -> el perfil vertical es lo que convierte la climatologia en")
    print("     pronostico del dia. Ninguna otra fuente da eso.")

    # ---------------------------------------------------------- exposicion
    titulo("4. EXPOSICION (quien esta en riesgo)")
    alerta = riesgo(con_sondeo, dia=0, ventana_dias=3, umbral_mm=60.0)
    expo = exposicion_por_riesgo(malla, exp, alerta["valores"], corte=0.3)
    print(resumen_exposicion(expo))
    print()
    for capa, d in expo["elementos"].items():
        print("  {:<26} {:>10.0f} de {:>10.0f}  ({})".format(
            d["etiqueta"][:26], d["expuesto"], d["total_dominio"],
            "{:.0%}".format(d["fraccion"]) if d["fraccion"] else "-"))
    print()
    print("celdas prioritarias:")
    for f in expo["celdas_prioritarias"][:5]:
        print("  {:<12} indice {:.3f}  p {:.0%}  {}".format(
            f["id_celda"], f["indice_exposicion"], f["probabilidad"],
            f.get("equipamientos", {})))

    # ------------------------------------------------------------- aptitud
    titulo("5. APTITUD DE TERRENO (tamiz, no dictamen)")
    apt = aptitud_constructiva(malla, exp, alerta["valores"])
    print("pesos: {}".format(apt["pesos_usados"]))
    print()
    print("  {:<12} {:>8} {:>10} {:>8} {:>7} {:>8} {:>7}".format(
        "celda", "aptitud", "no_inund", "pend", "firme", "accesos", "dispon"))
    for i in np.argsort(-np.nan_to_num(apt["aptitud"], nan=-1))[:6]:
        i = int(i)
        c = apt["criterios"]
        print("  {:<12} {:>8.3f} {:>10.2f} {:>8.2f} {:>7.2f} {:>8.2f} {:>7.2f}".format(
            malla.ids[i], apt["aptitud"][i], c["no_inundable"][i],
            c["pendiente"][i], c["suelo_firme"][i], c["accesos"][i],
            c["disponible"][i]))
    print()
    for a in apt["advertencias"]:
        print("  ! " + a)

    # ------------------------------------------------------------ ventanas
    titulo("6. VENTANAS DE OBRA")
    ven = ventanas_de_obra(con_sondeo, es_tierra=es_tierra)
    i_urb = int(np.argmax(np.nan_to_num(imperm)))
    cal = calendario_celda(ven, i_urb)
    print("celda {} (la mas urbanizada), horizonte de {} dias:".format(
        malla.ids[i_urb], cal["horizonte_dias"]))
    print()
    print("  {:<32} {:<32} {}".format("actividad", "P(trabajable) por dia %",
                                      "dias"))
    for f in cal["actividades"]:
        barra = " ".join("{:>2.0f}".format(v * 100) if v is not None else " -"
                         for v in f["por_dia"])
        print("  {:<32} {:<32} {:.1f}".format(
            f["etiqueta"][:32], barra, f["dias_trabajables_esperados"]))
    print()
    for o in ven["omitidas"]:
        print("  omitida: {} ({})".format(o["etiqueta"], o["motivo"]))

    # -------------------------------------------------------------- salida
    paquete = {
        "generado": dt.datetime.now().isoformat(timespec="seconds"),
        "version": __version__,
        "advertencia": ("capas sinteticas: {}. El perfil atmosferico es un "
                        "ejemplo, no una medicion real."
                        .format(", ".join(exp.capas_sinteticas()))),
        "atribuciones": exp.atribuciones(),
        "malla": malla.metadata,
        "ids_celdas": list(malla.ids),
        "expediente": {
            "resumen": exp.resumen(),
            "advertencias": exp.advertencias,
            "capas": {n: _lista(c.valores) for n, c in exp.capas.items()},
            "procedencias": exp.procedencias(),
        },
        "atmosfera": (perfil.resumen() if perfil else None),
        "mu_campo_latente": mu,
        "pronostico": {
            "fechas": con_sondeo.fechas,
            "lluvia_p50": [_lista(np.nanpercentile(
                con_sondeo.lluvia_mm[:, d, :], 50, axis=0))
                for d in range(con_sondeo.n_dias)],
            "riesgo_dia0": {
                "probabilidad": _lista(alerta["valores"]),
                "categoria": [int(k) for k in alerta["categoria"]],
                "etiqueta": list(alerta["etiqueta_categoria"]),
            },
        },
        "exposicion": {
            "resumen": resumen_exposicion(expo),
            "elementos": expo["elementos"],
            "celdas_prioritarias": expo["celdas_prioritarias"],
            "indice": _lista(expo["indice_exposicion"]),
        },
        "aptitud": {
            "indice": _lista(apt["aptitud"]),
            "criterios": {k: _lista(v) for k, v in apt["criterios"].items()},
            "pesos": apt["pesos_usados"],
            "advertencias": apt["advertencias"],
        },
        "ventanas_obra": {
            "fechas": ven["fechas"],
            "actividades": {
                n: {
                    "etiqueta": b["etiqueta"],
                    "dias_trabajables": _lista(b["dias_trabajables_esperados"]),
                }
                for n, b in ven["actividades"].items()
            },
            "omitidas": ven["omitidas"],
        },
    }
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps(paquete, indent=1, ensure_ascii=False),
                      encoding="utf-8")
    titulo("LISTO")
    print("  {}  ({:.0f} KB)".format(SALIDA, SALIDA.stat().st_size / 1024))
    print()
    print("  Cinco productos de las mismas capas: diagnostico, pronostico,")
    print("  exposicion, aptitud y ventanas de obra. El predictor es uno de")
    print("  ellos, no el centro.")


def _lista(a) -> list:
    a = np.asarray(a, dtype=float)
    return [None if not np.isfinite(v) else round(float(v), 4) for v in a]


def _fmt(v) -> str:
    return "-" if v is None else "{:.4g}".format(v)


if __name__ == "__main__":
    main()
