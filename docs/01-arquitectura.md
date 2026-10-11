# Arquitectura

## Principio

**El núcleo no sabe que existe HTTP.** `malla`, `estadistica`,
`climatologia`, `modelo`, `ensamble`, `asimilacion` y `metricas` sólo importan
numpy. FastAPI vive en `api/` y es una capa delgada de traducción.

Esto no es purismo: es lo que permite correr el modelo desde un notebook, un
script o una prueba sin levantar un servidor, y lo que deja cambiar la capa
HTTP sin tocar la física.

## Dependencias entre módulos

```
config  ─────────────────────────────┐
  │                                  │
geo ──> malla ──┬──> climatologia ──┐│
                │                   ││
estadistica ────┴──> modelo <───────┘│
                       │             │
                       ├──> ensamble │
                       ├──> asimilacion
                       └──> metricas │
                              │      │
                            api/ <───┘
```

No hay ciclos. Cada módulo se puede probar solo.

## Qué hace cada pieza

| Módulo | Responsabilidad | Dependencias |
|---|---|---|
| `config.py` | área de interés, topes, umbrales, semilla por defecto | — |
| `geo.py` | proyección local plana, haversine para validarla | numpy |
| `malla.py` | malla hexagonal, escala, vecindad, distancias, GeoJSON | geo |
| `estadistica.py` | normal (cdf/ppf), Weibull, campos gaussianos correlacionados | numpy |
| `climatologia.py` | parámetros por celda y mes; tierra/mar; elevación | malla, estadistica |
| `modelo.py` | **el simulador estocástico**; radiación y ET0 | climatologia, estadistica, malla |
| `ensamble.py` | resumen probabilístico: capas, series, riesgo, escalas de color | modelo |
| `asimilacion.py` | EnKF escalar, agregación de píxeles, conversión de unidades | malla |
| `metricas.py` | CRPS, Brier, confiabilidad, dispersión, contingencia | numpy |
| `api/app.py` | 16 endpoints, caché de corridas, validación de límites | todo lo anterior |
| `api/esquemas.py` | contratos pydantic de entrada | config |

## Decisiones que explican la forma

### Sólo numpy en el núcleo

No se usa scipy. Lo que se necesitaba de `scipy.stats` son cuatro funciones, y
las cuatro tienen forma cerrada o una aproximación racional publicada y
verificable contra la stdlib. Razón: el backend tiene que arrancar en una
máquina limpia y en el contenedor del hackathon sin compilar nada.
Ver [adr/0003](adr/0003-sin-scipy.md).

### Malla propia en vez de H3

H3 es la opción obvia para indexar hexágonos, y se descartó: subdivide en
razón 1:7 (no da una escala 1:16 limpia), orienta las celdas según el
icosaedro global en vez del área de interés, y añade una dependencia binaria
para resolver un problema que en un dominio de 90 km son 40 líneas de
geometría. Ver [adr/0002](adr/0002-malla-propia-vs-h3.md).

### El orden del bucle

El simulador itera sobre **días** y vectoriza sobre `(miembros, celdas)`. Con
14 días eso son 14 iteraciones de Python y el resto es numpy; el producto del
campo espacial se convierte en un GEMM. Si el bucle fuera sobre miembros
serían 200 iteraciones haciendo trabajo chico, y tardaría un orden de magnitud
más.

### Las innovaciones del campo se generan por día, no por adelantado

Precalcular todas las innovaciones sería un solo GEMM grande, más rápido, pero
costaría `miembros × días × celdas × 8` bytes: con 1 000 miembros y 60 días son
212 MB sólo de ruido. Generarlas día por día deja la memoria en
`O(miembros × celdas)` sin perder velocidad medible.

### Caché de simuladores por nivel

Construir un `SimuladorEstocastico` factoriza la covarianza espacial con
Cholesky: 12 ms en nivel 0 y 1.5 s en nivel 2. Se cachea por nivel en el
estado del proceso, así se paga una vez.

### Corridas en memoria con tope LRU

8 corridas, descartando la más vieja. Para el hackathon alcanza y evita I/O.
El `id_corrida` es un hash determinista de los parámetros, así que cuando esto
pase a Redis o a disco el id ya es la llave de caché. El front tiene que
manejar el `404` de corrida expirada.

### Topes explícitos

`MAX_CELDAS = 4096`, `MAX_MIEMBROS = 1000`, `MAX_HORIZONTE_DIAS = 60`,
`MAX_MEMORIA_ENSAMBLE_MB = 512`. La API estima la memoria antes de correr y
responde `413` con el número concreto y qué bajar. Sin eso, una petición de
nivel 2 con 1 000 miembros y 60 días pide 4.2 GB y tumba el proceso.

## Qué falta para producción

| Hoy | Para producción |
|---|---|
| CORS `*` | cerrar al dominio real |
| Corridas en memoria | Redis o disco, con TTL |
| Cálculo sincrónico | tarea en segundo plano si se suben los tamaños |
| Sin autenticación | según dónde se publique |
| Sin límite de tasa | necesario si queda público |
| Climatología sintética | [05-datos-y-nisar](05-datos-y-nisar.md) |
