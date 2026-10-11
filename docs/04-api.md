# API — contrato para el frontend

Base: `http://localhost:8000` · documentación interactiva en `/docs` ·
OpenAPI en `/openapi.json`.

El diseño lo hace otra persona, así que esto es el contrato: **todo lo que
está aquí es estable**, lo que no está aquí es interno y puede cambiar.

## El patrón de uso

```
1. GET  /api/area                       centra el mapa
2. GET  /api/malla                      una sola vez: la geometría (87 KB)
3. GET  /api/escalas                    una sola vez: rangos de color
4. POST /api/pronostico                 corre el ensamble -> id_corrida
5. GET  /api/corrida/{id}/capa          una capa por día (4 KB) -> se colorea
6. GET  /api/corrida/{id}/celda/{celda} serie con bandas -> panel lateral
```

**La geometría se pide una vez.** Las capas viajan como arrays de valores
alineados con `ids_celdas`, no como GeoJSON: así mover la barra de tiempo
cuesta 4 KB en vez de 72 KB. Si de todas formas conviene el GeoJSON completo
(por ejemplo para pasárselo directo a una capa de MapLibre), está
`?geojson=true`.

| Respuesta | Tamaño medido |
|---|---|
| `GET /api/malla` | 87.2 KB |
| `GET .../capa` (ligera) | 4.1 KB |
| `GET .../capa?geojson=true` | 72.1 KB |
| `GET .../celda/{id}` (14 días) | 11.5 KB |

## Endpoints

### Sistema

| | |
|---|---|
| `GET /salud` | `{ok, version, corridas_en_memoria}` |
| `GET /api/area` | centro, bbox, zoom, enlace de OSM, mosaico sugerido y **atribución** |
| `GET /api/escalas` | dominios y paletas sugeridas por variable, lista de estadísticos y umbrales |

`GET /api/escalas` existe por una razón concreta: si el front elige el rango
de color de cada capa por su cuenta, dos días dejan de ser comparables y el
usuario no puede ver que el jueves llueve más que el martes. Los dominios son
fijos y declarados.

### Malla

```
GET /api/malla?nivel=0&incluir_geografia=true
```

`FeatureCollection` con un `Polygon` por hexágono. `nivel` 0 = escala 1:16
(221 celdas), 1 = 1:32 (825), 2 = 1:64 (3 055).

Propiedades por celda: `id`, `q`, `r`, `lat`, `lon` y, con geografía:
`elevacion_m`, `es_tierra` (0/1), `dist_costa_km`, `capacidad_suelo_mm`.

`metadata` trae `escala`, `n_celdas`, `arista_km`, `ancho_celda_km`,
`area_celda_km2` y `bbox`.

```
GET /api/climatologia?nivel=0&mes=9     (mes=0 devuelve el resumen anual)
```

Contra qué se compara el pronóstico. La respuesta anual incluye un campo
`nota` que declara que la climatología es sintética; **no quitarlo de la
interfaz**.

### Pronóstico

```
POST /api/pronostico
{
  "fecha_inicio": "2026-09-15",   // YYYY-MM-DD
  "dias": 14,                     // 1..60
  "miembros": 200,                // 2..1000
  "nivel": 0,                     // 0..2
  "semilla": 20261114,            // null = aleatoria
  "humedad_inicial": null,        // 0..1, o null
  "id_asimilacion": null          // de POST /api/asimilar
}
```

Respuesta:

```
{
  "id_corrida": "2026-09-15-d346382eb5",
  "aviso": null,
  "resumen": {
    "dias": 14, "miembros": 200, "celdas": 221,
    "fecha_inicio": "2026-09-15", "fecha_fin": "2026-09-28",
    "fechas": ["2026-09-15", ...],
    "semilla": 20261114, "escala": "1:16",
    "lluvia_total_mm": {"p10": 84.3, "p50": 173.2, "p90": 286.6},
    "dia_mas_lluvioso": 13,
    "tmax_p90_c": 31.8,
    "humedad_suelo_p50_final": 0.831,
    "segundos_calculo": 0.314, "memoria_mb": 14.2,
    "asimilacion_aplicada": false
  },
  "malla": { ...metadata... }
}
```

**El `id_corrida` es determinista**: la misma petición con la misma semilla da
el mismo id. Sirve para cachear del lado del front y para que una URL
compartida reproduzca la vista exacta.

Las corridas viven en memoria con tope de 8 (LRU). Si se pide una que expiró,
la respuesta es `404` con instrucción de volver a correr el pronóstico: hay
que manejar ese caso en el front, no asumir que el id vive para siempre.

### Capas

```
GET /api/corrida/{id}/capa?variable=lluvia&dia=0&estadistico=p50&geojson=false
```

- `variable`: `lluvia` · `tmax` · `tmin` · `humedad_suelo` · `escurrimiento` · `et0`
- `dia`: índice dentro del horizonte, 0 = primer día
- `estadistico`: `media` · `p10` · `p25` · `p50` · `p75` · `p90` · `p99` · `desv` · `rango`

`rango` es el ancho del intervalo central del 80% (P90 − P10): la medida de
incertidumbre que conviene enseñarle al usuario, porque responde "qué tan
seguro está el modelo".

```
GET /api/corrida/{id}/probabilidad?variable=lluvia&dia=0&umbral=50&ventana_dias=3
```

`P(variable > umbral)` por celda. Para lluvia, escurrimiento y et0 la ventana
**acumula**; para variables de estado (temperatura, humedad) toma el
**máximo**, porque sumar temperaturas de tres días no significa nada. El campo
`modo` dice cuál se usó.

```
GET /api/corrida/{id}/riesgo?dia=0&ventana_dias=3&umbral_mm=60
```

Capa de alerta: probabilidad de que el escurrimiento acumulado pase el umbral,
más `categoria` (0 bajo, 1 moderado, 2 alto, 3 muy alto) y
`etiqueta_categoria`.

### ⚠️ Lo más importante para el frontend: `null` no es `0`

`humedad_suelo` y `escurrimiento` **no existen sobre el mar**: valen `null` en
el JSON (`NaN` internamente), y en la capa de riesgo esas celdas llevan
`categoria: -1` con etiqueta `"no aplica"`.

**No convertir esos `null` en ceros.** Un 0 de escurrimiento se pinta igual
que "sin riesgo" y haría que el océano se vea como zona segura en un mapa de
inundación. Esas celdas se dejan sin pintar, o con un relleno neutro
distinguible de la escala de valores. `metadata.categoria_sin_dominio` trae el
valor y la etiqueta para que el front no los adivine.

`lluvia`, `tmax`, `tmin` y `et0` sí están definidas en todo el dominio: en el
mar también llueve.

### Serie de una celda

```
GET /api/corrida/{id}/celda/OT0.0.0
```

```
{
  "id_celda": "OT0.0.0",
  "fechas": [...],
  "variables": {
    "lluvia": {
      "unidad": "mm/dia",
      "media": [...], "p10": [...], "p25": [...], "p50": [...],
      "p75": [...], "p90": [...], "p99": [...],
      "miembros_muestra": [[...], ...]   // 20 trayectorias individuales
    },
    "tmax": {...}, "tmin": {...}, "humedad_suelo": {...}
  },
  "geografia": {"lat":..., "lon":..., "elevacion_m":..., "es_tierra":..., "dist_costa_km":...}
}
```

`miembros_muestra` son 20 trayectorias sueltas del ensamble. Vale la pena
dibujarlas: **un abanico de líneas comunica la incertidumbre mucho mejor que
una banda sombreada**, porque se ve que cada trayectoria es un futuro posible
y coherente, no un intervalo abstracto.

### Asimilación

```
POST /api/asimilar
{
  "fecha": "2026-09-14",
  "nivel": 0,
  "por_celda": {"OT0.0.0": 0.25, ...},   // saturación 0-1
  "unidad": "saturacion",                 // o "volumetrica" (m3/m3)
  "textura": "franco",
  "sigma": 0.13,
  "miembros": 200,
  "semilla": 20261114,
  "sintetica": false                      // true genera una obs falsa de prueba
}
```

También acepta píxeles sueltos con `puntos_lat` / `puntos_lon` /
`puntos_valor`, que el backend promedia al hexágono que les toca.

Respuesta: `id_asimilacion`, `diagnostico` y los tres vectores
`humedad_previa` / `humedad_observada` / `humedad_posterior`.

**El `diagnostico` es material de presentación**, no de depuración: muestra
que el dato de radar de verdad movió el pronóstico.

```
"diagnostico": {
  "fuente": "sintetico (no es NISAR)",
  "celdas_observadas": 105, "celdas_totales": 221,
  "ganancia_media": 0.5252,              // el peso que se le dio al radar
  "incremento_medio": -0.1365,           // cuánto corrigió al modelo
  "incremento_absoluto_max": 0.1828,
  "reduccion_varianza_media": 0.5248,    // cuánta incertidumbre quitó
  "dispersion_previa_media": 0.1375,
  "dispersion_posterior_media": 0.1028
}
```

El `id_asimilacion` se pasa luego a `POST /api/pronostico` para arrancar desde
el suelo corregido. Si la asimilación y el pronóstico usan distinto número de
miembros, la respuesta trae un `aviso` explicando que se usó la media del
estado asimilado: para conservar el ensamble, corre los dos con el mismo
número.

Cuando la fuente dice `sintetico (no es NISAR)`, **hay que mostrarlo en la
interfaz**. No se puede presentar un dato inventado como observación de
satélite.

## Códigos de error

| | |
|---|---|
| `400` | variable, estadístico, día o cuerpo inválidos (el `detail` dice cuáles son válidos) |
| `404` | corrida expirada, celda inexistente, `id_asimilacion` desconocido |
| `409` | la asimilación es de un nivel de malla distinto al del pronóstico |
| `413` | la petición excede el tope de memoria (512 MB) |
| `422` | tipos o rangos fuera de lo que declara el esquema |

## CORS y despliegue

Hoy `allow_origins=["*"]` para que el front corra en otro puerto sin fricción.
**Antes de publicar hay que cerrarlo al dominio real.**

El mosaico de OSM que sugiere `/api/area` exige mostrar la atribución
`© OpenStreetMap contributors (ODbL)`: viene en la respuesta y no es opcional,
es la licencia.
