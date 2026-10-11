"""Fixtures compartidas.

La malla y el simulador se construyen una sola vez por sesion de pruebas: el
Cholesky de la covarianza espacial es lo mas caro del arranque y no cambia.
"""

import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ojo_tlaloc.climatologia import Climatologia  # noqa: E402
from ojo_tlaloc.malla import MallaHexagonal  # noqa: E402
from ojo_tlaloc.modelo import SimuladorEstocastico  # noqa: E402

FECHA_PRUEBA = dt.date(2026, 9, 15)
SEMILLA = 20261114


@pytest.fixture(scope="session")
def malla():
    return MallaHexagonal()


@pytest.fixture(scope="session")
def clima(malla):
    return Climatologia.sintetica(malla)


@pytest.fixture(scope="session")
def simulador(malla, clima):
    return SimuladorEstocastico(malla, clima)


@pytest.fixture(scope="session")
def corrida(simulador):
    """Un ensamble chico pero no trivial, reutilizado por varias pruebas."""
    return simulador.simular(
        fecha_inicio=FECHA_PRUEBA, n_dias=10, n_miembros=120, semilla=SEMILLA
    )
