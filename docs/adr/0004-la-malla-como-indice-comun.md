# 0004 — La malla hexagonal es el índice espacial común

**Fecha:** 10-oct-2026 · **Estado:** aceptada

## Contexto

Hay que fusionar tres clases de dato geométricamente incompatibles:

- **vectores** de OpenStreetMap (polígonos de metros, polilíneas de km)
- **rejillas** de satélite (de 9 km de SMAP a 50 km de MERRA-2)
- un **perfil puntual** de globo sonda

Y de esa fusión tienen que salir productos que no son todos predictivos.

## Alternativas

1. Una base de datos geoespacial (PostGIS) con cada fuente en su geometría
   nativa, y consultas espaciales al momento.
2. Una rejilla raster común a la resolución más fina, y remuestrear todo.
3. **La malla hexagonal existente como índice espacial común**: toda fuente se
   agrega al hexágono al ingresar.

## Decisión

La 3.

## Por qué

- **Ya estaba construida.** La malla se hizo para el modelo, pero resulta ser
  exactamente lo que se necesita: un índice espacial estable, con ids
  reproducibles, vecindad uniforme y un hexágono que es su propia celda de
  Voronoi (asignar un píxel "al centro más cercano" es asignarlo "al hexágono
  que lo contiene", sin ambigüedad).
- **La agregación se hace una vez, no en cada consulta.** PostGIS resolvería
  mejor el caso general, pero aquí el dominio es fijo y las consultas son
  siempre "dame esta variable por celda". Agregar al ingresar deja las
  consultas en acceso a un array.
- **Comparabilidad inmediata.** Dos capas de fuentes distintas quedan alineadas
  por índice, así que combinarlas es aritmética de numpy y no un *join*
  espacial.
- **Una sola unidad de discurso.** Toda la interfaz, el pronóstico, el
  expediente y los análisis hablan de `OT0.0.0`. El usuario señala un hexágono
  y el sistema tiene una respuesta para cada pregunta.
- Contra la 2: una rejilla a la resolución más fina obligaría a remuestrear
  hacia arriba datos de 50 km, inventando detalle que la fuente no tiene. Con
  hexágonos de 5.8 km el remuestreo es hacia abajo y queda explícito.

## Consecuencias

- **La resolución del sistema es la del hexágono**, no la de la fuente más
  fina. Un edificio de 40 m² se convierte en una fracción de área de una celda
  de 28.8 km². Para los productos que se construyen (hidrología, exposición,
  tamiz de terreno) es lo adecuado; para cualquier cosa que necesite el
  edificio individual, no sirve y hay que ir a la fuente.
- Cambiar de nivel de malla obliga a reagregar todas las fuentes. Por eso el
  expediente se cachea por nivel, y por eso la API devuelve `409` si se cruzan
  una corrida y un análisis de niveles distintos.
- La agregación tiene su propio error, y hay que medirlo: el muestreo por
  puntos con paso de 200 m da unos 4 puntos porcentuales sobre hexágonos de
  28.8 km². Está documentado en `fuentes/geometria.py`.
