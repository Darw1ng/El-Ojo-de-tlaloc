# 0002 — Malla hexagonal propia en vez de H3

**Fecha:** 10-oct-2026 · **Estado:** aceptada

## Contexto

Se pidió colorear el mapa "por hexágonos a escala 1:16". Hay que elegir cómo
se indexan y generan esos hexágonos.

## Alternativas

1. **H3** (Uber), el estándar de facto para mallas hexagonales globales.
2. **Malla propia** en coordenadas axiales sobre una proyección local.

## Decisión

Malla propia.

## Por qué

- **La escala.** H3 subdivide en razón 1:7 por resolución, así que no existe
  un nivel que dé "16 hexágonos a lo ancho" del área de interés: hay que
  conformarse con la resolución que más se acerque. Con malla propia la escala
  es el parámetro, y 1:16 es exactamente 1:16.
- **La orientación.** Las celdas de H3 se orientan según el icosaedro global,
  no según el área de trabajo, y sus celdas no son hexágonos perfectamente
  regulares (hay 12 pentágonos en el planeta y distorsión creciente con la
  distancia a los vértices). Para un dominio de 90 km una proyección local da
  hexágonos regulares de verdad.
- **El tamaño del problema.** Lo que se necesita de una librería de indexación
  —centros, vértices, vecinos, id estable— son unas 40 líneas de geometría
  axial en un dominio plano. No justifica una dependencia binaria más, sobre
  todo con Python 3.14, donde las ruedas precompiladas de paquetes con
  extensiones en C todavía van llegando.
- **Interoperabilidad.** No se pierde: la salida es GeoJSON estándar, que
  cualquier herramienta lee.

## Consecuencias

- Los ids `OT<nivel>.<q>.<r>` son nuestros y no se pueden cruzar con datasets
  publicados en índices H3. Si algún día hace falta, se agrega un adaptador
  que mapee centros a celdas H3; es una función.
- La jerarquía de niveles es 1:4 en área (duplicar a lo ancho), no la 1:7 de
  H3. Para este proyecto es mejor: 1:4 es una subdivisión más fina y dos
  niveles dan exactamente 1:16 en área.
- Hay que probar la geometría nosotros. Está hecho: vecindad recíproca,
  equidistancia de los 6 vecinos, regularidad de los vértices, cobertura del
  bbox y validez del GeoJSON.
