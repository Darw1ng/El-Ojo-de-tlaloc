# Bitácora

Paso a paso de la construcción, con las decisiones y los tropiezos. Lo que no
funcionó también está anotado: es la parte útil.

---

## 10-oct-2026 — Sesión 1: el núcleo del modelo

Punto de partida: repositorio vacío (creado ese mismo día, 0 commits). Encargo:
el modelo de predicción estocástica primero, backend antes que nada, monorepo,
mapa de OSM centrado en `11/19.1704/-96.1654` coloreado por hexágonos a escala
1:16. El diseño lo hace otra persona.

### 1. Área de interés

El bbox se derivó del enlace de OSM, no a ojo. Con zoom 11 y un viewport de
1280×800:

```
resolución = 156543.03392 · cos(19.1704) / 2¹¹ = 72.2 m/px
ancho = 1280 px → 92.4 km → 0.879° de longitud
alto  =  800 px → 57.7 km → 0.522° de latitud
```

Resultado: 18.91–19.43 N, 96.60–95.73 W. Cubre el puerto de Veracruz, Boca del
Río, la cuenca baja del Jamapa y del río La Antigua.

### 2. Proyección

Un hexágono regular en grados no es regular sobre el terreno (un grado de
longitud aquí mide 105 km y uno de latitud 111 km). Se metió una
equirectangular local escalada por `cos(lat₀)`.

**Medido:** error máximo del 0.16% contra haversine sobre 300 pares al azar.
El docstring decía al principio "menor al 0.1%" y la prueba lo desmintió: se
corrigió el docstring en vez de relajar la prueba en silencio.

### 3. Malla hexagonal, escala 1:16

Se definió la escala como *cuántos hexágonos caben a lo ancho del área*, que
es la lectura directa de "1:16" y la que deja todo determinado sin parámetros
libres: 5.77 km de ancho por celda, 28.8 km², **221 celdas**.

Como la otra lectura posible era 1:16 en área, también quedó cubierta: cada
nivel duplica a lo ancho y cuartea el área, así que dos niveles dan 1:16
exacto en área. Las dos están probadas.

**Descartado H3** ([adr/0002](adr/0002-malla-propia-vs-h3.md)): subdivide 1:7,
no da 1:16 limpio, orienta por el icosaedro global y añade una dependencia
binaria para 40 líneas de geometría.

### 4. Base estadística sin scipy

Se necesitaban `Φ`, `Φ⁻¹`, una distribución de cola pesada con inversa, y
Cholesky. Se implementaron las tres primeras
([adr/0003](adr/0003-sin-scipy.md)) y se verificaron contra `math.erfc` y
contra valores publicados.

**Tropiezo:** la primera versión de `erfc` mezclaba dos variantes de
Numerical Recipes — evaluaba el polinomio de `erfcc` (que va en `t`) sobre la
variable de `erfccheb` (que va en `4t−2`). Daba resultados plausibles pero
mal. Lo cazó la comparación contra `math.erfc`: de ahí la regla de verificar
siempre contra algo independiente.

### 5. Campo gaussiano correlacionado

La pieza que hace que esto no sea ruido blanco: covarianza `exp(−d/L)`
factorizada con Cholesky, más AR(1) temporal con el factor `sqrt(1−φ²)` que
conserva la varianza marginal en 1.

**Medido:** correlación empírica a 0.055 de la objetivo con 4 000 muestras;
AR(1) lag-1 de 0.707 contra 0.700 pedido; varianza marginal 1.009.

### 6. Climatología

Normales mensuales del puerto de Veracruz (≈1 656 mm/año, ≈115 días con
lluvia) más gradientes espaciales. La calibración de la cadena de Markov salió
elegante: con `p01 = π(1−ρ)` y `p11 = π + (1−π)ρ` la estacionaria es
exactamente `π`, así que se puede pedir la frecuencia climatológica *y* la
persistencia sin que una estropee a la otra. **Error medido: 2.2e-16.**

**Tropiezo grande:** el primer perfil de elevación sintético ponía 1 204 m en
el extremo oeste del bbox y producía 2 812 mm/año de lluvia ahí. Falso: la
zona es planicie costera y el ascenso real a la sierra empieza al oeste de
96.7 W, ya fuera del dominio. Se rehízo con un perfil conservador (máximo
368 m dentro del bbox, lluvia anual media 1 734 mm) y se dejó una prueba que
falla si alguien vuelve a inventar montañas.

### 7. El simulador

Cinco pasos por día: campo latente → ocurrencia Markov → intensidad por cópula
gaussiana sobre Weibull → temperatura → balance de agua con ET0 de Hargreaves.
Detalle en [03-modelo-estocastico](03-modelo-estocastico.md).

El bucle itera sobre **días** y vectoriza sobre `(miembros, celdas)`:
**0.30 s** para 200 miembros × 14 días × 221 celdas.

**Medido de entrada:**

| | |
|---|---|
| Acumulado de septiembre, celda al nivel del mar | 369 mm contra 350 objetivo (+5%) |
| Correlación de lluvia entre vecinas (5.8 km) | 0.75 |
| Correlación entre lejanas (> 60 km) | 0.04 |
| Rangos físicos | tmax 20–37 °C, ET0 3.3 mm/día, suelo 0.1–1.0 |

### 8. Asimilación

Filtro de Kalman de ensamble escalar por celda con observaciones perturbadas.
Se verificó la fórmula a mano en una celda: Kalman teórico 0.573, obtenido
0.570.

La perturbación de la observación no es opcional: sin ella el ensamble
colapsa y el pronóstico se vuelve sobreconfiado. Hay una prueba dedicada.

### 9. Métricas

CRPS (estimador justo), Brier, confiabilidad, descomposición de Murphy,
dispersión contra error, tabla de contingencia.

**Dos correcciones de rigor:**

- El docstring del CRPS afirmaba que el estimador clásico *premia* a los
  ensambles chicos. Es al revés: divide entre `m²`, subestima `E|X−X'|` y deja
  el CRPS más alto, o sea los castiga. Corregido.
- La descomposición de Murphy no cerraba (0.166189 contra 0.166951). No era un
  bug: con probabilidades continuas hay que agrupar en cajas y aparece el
  residuo intra-caja de Stephenson. Se expone como `residuo_intracaja` en vez
  de esconder la diferencia.

### 10. API

16 endpoints. El patrón: la geometría se pide una vez (87 KB) y las capas
viajan como arrays alineados (4 KB), para que mover la barra de tiempo no
vuelva a bajar el GeoJSON.

**Tropiezo:** con `from __future__ import annotations`, importar los esquemas
pydantic *dentro* de `crear_app()` hace que FastAPI no pueda resolver las
anotaciones (las busca en el scope del módulo) y trate el cuerpo como
parámetro de query: `422 Field required`. Se movieron los imports al módulo.

### 11. Pruebas, y los bugs que encontraron

153 pruebas. Cuatro fallos en la primera corrida completa, con cuatro
diagnósticos distintos:

| Fallo | Qué era |
|---|---|
| `norm_cdf(0) ≠ 0.5` a 1e-9 | prueba demasiado estricta: la erfc de NR da 1e-7. Se ajustó la prueba y se documentó la precisión real |
| error de proyección 0.154% > 0.1% | el docstring prometía más precisión de la que hay. Se corrigió el docstring, tope de la prueba a 0.3% |
| `amenaza_critica` 0.3333 ≠ 1/3 | las métricas se redondean a 4 decimales para JSON. Tolerancia de la prueba a 1e-4 |
| `escurrimiento.min()` es NaN | **bug real**: la convención de qué variables existen sobre el mar no estaba definida ni era consistente |

El cuarto se arregló definiendo la convención explícita (lluvia, temperaturas y
ET0 en todo el dominio; suelo y escurrimiento sólo en tierra, `NaN` en el mar)
y arrastró dos bugs más, que son los peores del día:

1. **El océano salía clasificado como "riesgo muy alto"**, porque
   `np.digitize` manda los `NaN` al último cajón. Se agregó la categoría `-1`
   con etiqueta `"no aplica"`.
2. **La probabilidad en el mar salía 0 en vez de `NaN`**, porque
   `NaN > umbral` es `False`. Un 0 de escurrimiento se pinta igual que "sin
   riesgo": en un mapa de inundación, el océano se habría visto como zona
   segura.

Los dos eran invisibles en los números y sólo se notan en el mapa. Quedó
anotado en grande en [04-api](04-api.md): **`null` no es `0`**.

### 12. Validación

Medido con verdad sintética (un miembro como realidad, climatología de marzo
como referencia):

| Métrica | Valor |
|---|---|
| CRPSS vs. climatología de temporada seca | 0.20 |
| Razón dispersión/error | 1.06 (consistente) |
| BSS para P(lluvia > 20 mm) | **−0.02** |

El BSS negativo se dejó en la documentación en vez de buscar un umbral que
diera bonito. La explicación está en [06-validacion](06-validacion.md): en un
mes homogéneo el modelo asigna probabilidades parecidas a todas las celdas,
así que tiene calibración buena y **resolución pobre**, y sin resolución no hay
skill sobre la tasa base. Es la descomposición de Murphy en acción, y señala
dónde sí está el valor: en el contraste que mete el estado del suelo.

---

## Pendientes

En orden de lo que más mueve la aguja:

1. **Granulos reales de NISAR** — descarga por `asf_search`, recorte y
   *retrieval* de humedad. Los pasos 4 a 7 de la cadena ya están hechos; falta
   el 1 al 3 ([05-datos-y-nisar](05-datos-y-nisar.md)).
2. **DEM real** (SRTM 30 m) para quitar el perfil de elevación sintético.
3. **Normales reales** de CHIRPS / ERA5-Land / CONAGUA — son 12 listas de
   números, la interfaz ya está.
4. **Línea de costa real** de Natural Earth u OSM.
5. **Textura de suelo por celda** (INEGI / SoilGrids) para quitar el sesgo de
   la conversión volumétrica.
6. **Un caso histórico** con lluvia observada para medir habilidad de verdad.
7. **Frontend** — lo hace otra persona; el contrato está en
   [04-api](04-api.md).

## Decisiones que conviene revisar más adelante

- Si se mete un pronóstico determinista (GFS/ECMWF) como media condicionante
  del campo latente, el modelo pasa de climatológico a sinóptico sin cambiar
  la arquitectura. Es la mejora de mayor impacto después de los datos reales.
- La persistencia está repartida entre `φ` del campo y `p01/p11` de la cadena.
  Con datos reales hay que calibrarlas juntas.
- Corridas en memoria con tope de 8: suficiente para la demo, insuficiente si
  queda público.
