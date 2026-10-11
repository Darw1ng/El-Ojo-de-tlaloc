"""Contratos de entrada y salida de la API.

Esto es lo que el front puede dar por estable. Todo lo que no este aqui es
interno y puede cambiar.
"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field

from ..config import (
    HORIZONTE_DEFECTO_DIAS,
    MAX_HORIZONTE_DIAS,
    MAX_MIEMBROS,
    N_MIEMBROS_DEFECTO,
    SEMILLA_DEFECTO,
)


class PeticionPronostico(BaseModel):
    """Parametros de una corrida del ensamble."""

    fecha_inicio: dt.date = Field(
        default_factory=lambda: dt.date.today(),
        description="Primer dia del pronostico (YYYY-MM-DD).",
    )
    dias: int = Field(
        HORIZONTE_DEFECTO_DIAS, ge=1, le=MAX_HORIZONTE_DIAS,
        description="Horizonte en dias.",
    )
    miembros: int = Field(
        N_MIEMBROS_DEFECTO, ge=2, le=MAX_MIEMBROS,
        description="Trayectorias del ensamble. Mas miembros = probabilidades "
                    "mas finas y mas tiempo de calculo.",
    )
    nivel: int = Field(
        0, ge=0, le=2,
        description="Nivel de la malla. 0 = escala 1:16 (~29 km2 por celda), "
                    "1 = 1:32, 2 = 1:64.",
    )
    semilla: int | None = Field(
        SEMILLA_DEFECTO,
        description="Fija la corrida para que sea reproducible. null = aleatoria.",
    )
    humedad_inicial: float | None = Field(
        None, ge=0.0, le=1.0,
        description="Saturacion del suelo al arrancar el calentamiento. "
                    "null usa el valor por defecto del modelo. Para usar el "
                    "dato de radar, primero POST /api/asimilar.",
    )
    id_asimilacion: str | None = Field(
        None,
        description="Id devuelto por /api/asimilar: arranca el pronostico "
                    "desde el estado del suelo corregido con la observacion.",
    )


class RespuestaPronostico(BaseModel):
    id_corrida: str
    resumen: dict
    malla: dict
    aviso: str | None = None


class PeticionAsimilacion(BaseModel):
    """Observacion de humedad de suelo para asimilar.

    Dos formas de mandarla:
      - `por_celda`: dict id_celda -> saturacion (0-1). Lo normal si el
        preprocesamiento del granulo de NISAR ya se hizo fuera.
      - `puntos`: listas lat/lon/valor de pixeles sueltos; el backend los
        promedia al hexagono que les toca.
    """

    fecha: dt.date = Field(default_factory=lambda: dt.date.today())
    nivel: int = Field(0, ge=0, le=2)
    por_celda: dict[str, float] | None = None
    puntos_lat: list[float] | None = None
    puntos_lon: list[float] | None = None
    puntos_valor: list[float] | None = None
    unidad: str = Field(
        "saturacion",
        description="'saturacion' (0-1) o 'volumetrica' (m3/m3, se convierte "
                    "con la textura indicada).",
    )
    textura: str = Field("franco", description="Textura del suelo para la conversion.")
    sigma: float = Field(
        0.13, gt=0.0, le=1.0,
        description="Incertidumbre de la observacion en saturacion relativa.",
    )
    miembros: int = Field(N_MIEMBROS_DEFECTO, ge=2, le=MAX_MIEMBROS)
    semilla: int | None = SEMILLA_DEFECTO
    sintetica: bool = Field(
        False,
        description="true genera una observacion falsa para probar la cadena "
                    "sin granulos de NISAR descargados.",
    )
