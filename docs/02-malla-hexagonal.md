# La malla hexagonal y la escala 1:16

## Por qué hexágonos y no una cuadrícula

Tres razones, en orden de importancia para este proyecto:

1. **Vecindad uniforme.** Un hexágono tiene 6 vecinos y los 6 están a la misma
   distancia. En una cuadrícula los 4 vecinos ortogonales están a 1 paso y los
   4 diagonales a 1.41, así que cualquier modelo de vecindad —difusión,
   propagación, correlación espacial— queda deformado por la geometría de la
   rejilla y no por la física. El modelo estocástico usa distancias entre
   centros para construir la covarianza espacial, y con hexágonos esa matriz
   es limpia.
2. **Cada hexágono es su propia celda de Voronoi.** Asignar un píxel de radar
   "al centro más cercano" es exactamente asignarlo "al hexágono que lo
   contiene". Eso hace que agregar observaciones a la malla sea una operación
   sin ambigüedad (está probado en `test_cada_punto_va_a_su_celda_mas_cercana`).
3. **Lectura.** Una cuadrícula produce escaleras y bordes rectos artificiales;
   el hexágono reparte el error de borde en 6 direcciones y se lee como un
   campo continuo.

## Qué significa "escala 1:16"

En este proyecto la escala es **cuántos hexágonos caben a lo ancho del área de
interés**:

```
1:16  ->  16 hexágonos cubren los 92.4 km de ancho del bbox
```

De ahí sale todo lo demás, sin ningún parámetro libre:

```
ancho_hexágono = 92.4 km / 16          = 5.77 km
arista         = ancho / sqrt(3)       = 3.33 km
área           = 1.5 · sqrt(3) · a²    = 28.82 km²
celdas         = 221 (126 tierra, 95 mar)
```

**Es factible y además cae en el lugar correcto.** 5.8 km por celda es la
resolución típica de un modelo regional de precipitación (los operativos
andan entre 3 y 10 km). Más fino que eso sería fingir detalle que la
climatología de entrada no tiene; más grueso perdería el contraste entre la
mancha urbana del puerto y la zona agrícola.

### La otra lectura de 1:16

Si lo que se buscaba era 1:16 **en área** y no a lo ancho, también está
cubierto: cada nivel duplica los hexágonos a lo ancho y por lo tanto cuartea
el área, así que dos niveles abajo del base dan exactamente 1/16 del área por
celda. Los dos caminos existen en el código y los dos están probados
(`test_dos_niveles_arriba_es_1_a_16_en_area`).

| Nivel | Escala | Celdas | Ancho de celda | Área de celda | Cholesky |
|---|---|---|---|---|---|
| 0 | 1:16 | 221 | 5.769 km | 28.820 km² | 12 ms |
| 1 | 1:32 | 825 | 2.884 km | 7.205 km² | 101 ms |
| 2 | 1:64 | 3 055 | 1.442 km | 1.801 km² | 1 463 ms |

El nivel 2 está cerca del techo útil: la factorización de la covarianza
espacial es O(n³) y a 3 055 celdas ya cuesta 1.5 s (se cachea por nivel, así
que se paga una vez por proceso). El tope duro está en `config.MAX_CELDAS =
4096`; para pasar de ahí hay que cambiar a descomposición espectral truncada.

## Geometría

Hexágonos **pointy-top** (vértice arriba) en coordenadas axiales `(q, r)`:

```
separación horizontal = sqrt(3) · a
separación vertical   = 1.5 · a
centro(q, r)          = ( a·sqrt(3)·(q + r/2),  a·1.5·r )
vecinos               = (+1,0) (+1,-1) (0,-1) (-1,0) (-1,+1) (0,+1)
```

El origen `(0, 0)` se ancla en el centro del bbox, que es el punto del enlace
de OSM: la celda `OT0.0.0` es exactamente la del centro del mapa.

### Identificador de celda

```
OT<nivel>.<q>.<r>        ejemplo: OT0.0.0, OT0.-5.-6, OT1.3.-2
```

Es **estable y reproducible**: dos construcciones de la misma malla dan los
mismos ids en el mismo orden (`test_ids_estables_entre_construcciones`). Eso
importa porque el frontend guarda celdas seleccionadas por id y porque las
URLs compartibles los llevan dentro.

## Proyección

Los hexágonos tienen que ser regulares **sobre el terreno**, no en grados: un
grado de longitud a esta latitud mide 105 km y uno de latitud 111 km, así que
un hexágono "regular" en grados saldría achatado. Se usa una equirectangular
local centrada en el área:

```
x = R · (lon - lon0) · cos(lat0)
y = R · (lat - lat0)
```

Error máximo frente a la geodésica, medido sobre 300 pares al azar dentro del
dominio: **0.16%** (170 m en el par más separado, que está a 110 km). Contra
hexágonos de 5.8 km es despreciable. La prueba
`test_proyeccion_error_despreciable_en_el_dominio` pone el tope en 0.3%: si
alguien agranda el bbox lo suficiente para pasarse, falla y avisa que hay que
cambiar a UTM 14N o a una azimutal equidistante.

## Tierra y mar

El 43% del área de interés es océano. Las celdas se clasifican con una línea
de costa aproximada por tres puntos conocidos (Chachalacas, puerto de
Veracruz, Antón Lizardo) interpolados por latitud.

Eso tiene una consecuencia de diseño que recorre todo el sistema: **humedad de
suelo y escurrimiento no existen sobre el mar y valen `NaN`, no `0`**. Un cero
de escurrimiento se pinta igual que "sin riesgo" y eso sería engañoso; el
`NaN` le dice al frontend "no pintes esta celda". La capa de riesgo marca esas
celdas con categoría `-1` y etiqueta `"no aplica"`.

> La costa aproximada es un placeholder honesto. La real se carga de Natural
> Earth o de un extracto de OSM; ver [05-datos-y-nisar](05-datos-y-nisar.md).

## Salida

`MallaHexagonal.a_geojson(propiedades)` devuelve un `FeatureCollection` con un
`Polygon` de 7 puntos por celda (6 vértices + cierre), coordenadas en orden
`(lon, lat)` como manda GeoJSON, y las propiedades que se le pasen alineadas
por índice de celda. Pesa 87 KB con geografía incluida, y se pide **una sola
vez**: las capas de pronóstico viajan como arrays de valores (4 KB) alineados
con `ids_celdas`, para que mover la barra de tiempo no vuelva a bajar la
geometría.
