# 0001 — Generador estocástico, no modelo numérico de la atmósfera

**Fecha:** 10-oct-2026 · **Estado:** aceptada

## Contexto

Se necesita "predecir el clima variado" sobre el área de interés con
horizonte de días y resolución de pocos kilómetros.

## Alternativas

1. **Modelo numérico (WRF, MPAS).** Resolver las ecuaciones de la atmósfera.
2. **Descarga de un pronóstico ajeno (GFS, ECMWF) y reescalado.**
3. **Generador estocástico calibrado a la climatología local.**

## Decisión

La 3, con campo latente gaussiano para coherencia espacial.

## Por qué

La 1 está fuera de alcance: WRF necesita condiciones de frontera de un modelo
global, horas de cómputo por corrida y un equipo dedicado a la configuración.
No corre en un servidor chico ni se calibra en cinco semanas.

La 2 es razonable y vale como trabajo futuro, pero tiene dos problemas para
este reto: depende de un servicio externo en el momento de la demo, y deja al
proyecto en el papel de visualizador de un pronóstico ajeno. Además un
pronóstico determinista no da la probabilidad por celda, que es la salida que
justifica el sistema.

La 3 produce incertidumbre honesta a escala de hexágono, corre en 0.3 s, es
reproducible con una semilla, y **se puede acoplar a la asimilación de radar**,
que es el centro de la propuesta. El costo es claro: no tiene habilidad de
pronóstico sinóptico (no sabe que viene un frente), sólo climatológica
condicionada al estado del suelo.

## Consecuencias

- Hay que ser explícitos en que esto no es un pronóstico meteorológico
  operativo. Está en el README, en los docstrings y en la visión.
- La vía de mejora está abierta: si se mete un pronóstico determinista como
  media condicionante del campo latente, el modelo pasa de climatológico a
  sinóptico sin cambiar la arquitectura.
