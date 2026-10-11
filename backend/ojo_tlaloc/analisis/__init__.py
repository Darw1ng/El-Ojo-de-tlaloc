"""Productos derivados del expediente que NO son pronostico.

El modelo estocastico es uno de los consumidores del expediente, no el unico.
Con las mismas capas se construyen productos que responden preguntas
distintas:

    terreno.py     que hay aqui: pendiente, aptitud constructiva, exposicion
                   a inundacion. Preguntas sobre el espacio, no sobre el
                   tiempo.
    exposicion.py  quien y que esta en las celdas de riesgo. Convierte un
                   mapa de probabilidad en una lista de afectados.
    ventanas.py    cuando se puede trabajar. Traduce el pronostico a
                   decisiones de obra por actividad.

Los tres comparten una regla: declaran sus supuestos y sus limites en la
respuesta, no en un documento aparte. Un indice de aptitud sin su advertencia
de que no sustituye un estudio de mecanica de suelos es un riesgo legal.
"""

from .exposicion import exposicion_por_riesgo, resumen_exposicion
from .terreno import aptitud_constructiva, pendiente_desde_elevacion
from .ventanas import ACTIVIDADES, ventanas_de_obra

__all__ = [
    "pendiente_desde_elevacion", "aptitud_constructiva",
    "exposicion_por_riesgo", "resumen_exposicion",
    "ventanas_de_obra", "ACTIVIDADES",
]
