# Frontend

Esta carpeta es para el diseño y la interfaz, que las hace otra persona del
equipo. El backend no asume nada sobre el framework.

## Lo que necesitas leer

**[docs/04-api.md](../docs/04-api.md)** — el contrato completo. Todo lo que
está ahí es estable.

## Arranque rápido

```bash
cd ../backend
uvicorn ojo_tlaloc.api.app:app --reload --port 8000
```

- Documentación interactiva (puedes probar los endpoints desde el navegador):
  http://localhost:8000/docs
- CORS está abierto, así que el front puede correr en cualquier puerto.

## Las cinco llamadas que arman el tablero

```js
const API = 'http://localhost:8000'

// 1. centrar el mapa
const area = await (await fetch(`${API}/api/area`)).json()

// 2. la geometría de los hexágonos — UNA SOLA VEZ
const malla = await (await fetch(`${API}/api/malla`)).json()

// 3. rangos de color — UNA SOLA VEZ
const escalas = await (await fetch(`${API}/api/escalas`)).json()

// 4. correr el pronóstico
const pron = await (await fetch(`${API}/api/pronostico`, {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({
    fecha_inicio: '2026-09-15', dias: 14, miembros: 200, semilla: 20261114,
  }),
})).json()

// 5. una capa por día — 4 KB, esto es lo que se pide al mover la barra
const capa = await (await fetch(
  `${API}/api/corrida/${pron.id_corrida}/capa?variable=lluvia&dia=3&estadistico=p50`
)).json()

// capa.valores[i] corresponde a capa.ids_celdas[i], que es el mismo orden
// que malla.features[i].properties.id
```

## Tres cosas que no hay que equivocar

### 1. `null` no es `0`

`humedad_suelo` y `escurrimiento` valen `null` sobre el mar porque ahí **no
existen**. En la capa de riesgo esas celdas llevan `categoria: -1` y etiqueta
`"no aplica"`.

No las conviertas en ceros. Un 0 de escurrimiento se pinta igual que "sin
riesgo", y en un mapa de inundación eso haría que el océano se vea como zona
segura. Déjalas sin pintar o con un relleno neutro que no se confunda con la
escala de valores.

`lluvia`, `tmax`, `tmin` y `et0` sí están definidas en todo el dominio.

### 2. Los rangos de color vienen del backend

`GET /api/escalas` trae el dominio de cada variable. Si el front calcula el
rango de cada capa por su cuenta (por ejemplo con el mínimo y máximo del día),
dos días dejan de ser comparables y el usuario no puede ver que el jueves
llueve más que el martes.

### 3. El dato sintético se rotula

Mientras no haya granulos de NISAR descargados, la asimilación usa una
observación sintética y el `diagnostico.fuente` dice literalmente
`"sintetico (no es NISAR)"`. Eso tiene que verse en la pantalla: no se puede
presentar un dato inventado como observación de satélite.

Lo mismo con la climatología: `GET /api/climatologia?mes=0` trae un campo
`nota` que la declara sintética.

## Sugerencias (no son requisitos)

- **El abanico de trayectorias.** `GET /api/corrida/{id}/celda/{celda}`
  devuelve `miembros_muestra` con 20 trayectorias individuales. Dibujarlas
  comunica la incertidumbre mucho mejor que una banda sombreada: se ve que
  cada línea es un futuro posible y coherente, no un intervalo abstracto.
- **El estadístico `rango`** (P90 − P10) es una capa de "qué tan seguro está
  el modelo". Poder alternar entre el valor y su incertidumbre es más honesto
  que mostrar sólo la mediana.
- **El diagnóstico de la asimilación** (`ganancia_media`,
  `reduccion_varianza_media`, `incremento_medio`) es material de presentación:
  muestra que el dato de radar de verdad movió el pronóstico. Vale un panel.
- **Fondo de mapa:** el mosaico de OSM que sugiere `/api/area` exige mostrar
  `© OpenStreetMap contributors` (ODbL). No es opcional, es la licencia.
- La semilla por defecto (`20261114`) hace que la demo sea idéntica cada vez,
  y el `id_corrida` es determinista: una URL compartida puede reproducir la
  vista exacta.

## Nota sobre corridas expiradas

Las corridas viven en memoria con tope de 8. Si pides una que ya expiró, la
respuesta es `404` con el mensaje de volver a llamar `POST /api/pronostico`.
Hay que manejar ese caso: no asumas que el `id_corrida` vive para siempre.

---

## Plataforma de fusión (etapa 2)

El backend dejó de ser sólo un predictor: ahora funde OpenStreetMap, NASA
POWER y perfiles de globo sonda en un expediente por hexágono, y de ahí salen
cinco productos. Lee
[docs/07-plataforma-de-fusion.md](../docs/07-plataforma-de-fusion.md) para el
panorama; aquí va lo que necesitas para consumirlo.

### Endpoints nuevos

```
GET  /api/expediente                    qué capas hay, de dónde vienen, qué falta
GET  /api/expediente/capa?nombre=...    una capa con su procedencia
GET  /api/expediente/celda/{id}         TODO lo que se sabe de un hexágono
GET  /api/expediente/atribuciones       lo que hay que mostrar por licencia
POST /api/sondeo                        texto del perfil → índices y μ
POST /api/sondeo/calibrar               estima el probit con históricos
POST /api/pronostico/fusion             pronóstico con todas las fuentes
GET  /api/aptitud                       aptitud de terreno por hexágono
GET  /api/pendiente                     pendiente aproximada
GET  /api/corrida/{id}/exposicion       quién está en riesgo
GET  /api/corrida/{id}/ventanas         calendario de obra por actividad
GET  /api/actividades                   catálogo de actividades y umbrales
```

### Cuatro reglas que no hay que equivocar

**1. Rotula lo que no es dato.** `GET /api/expediente/atribuciones` devuelve
`capas_sinteticas`: esas las inventamos nosotros (hoy elevación, tierra/mar,
distancia a la costa, capacidad de suelo). No pueden verse igual que una
observación. Cada capa trae `procedencia.nivel`, que es uno de `observado`,
`reanalisis`, `derivado` o `sintetico`.

**2. Muestra las atribuciones.** La ODbL de OpenStreetMap lo exige y NASA
POWER lo pide. Vienen listas en `atribuciones`, no es opcional.

**3. Enseña los sesgos que las fuentes declaran.** `GET /api/expediente`
devuelve `advertencias`: cada una dice qué variable, qué sesgo, el detalle y
cómo se corrige. Por ejemplo, que la temperatura máxima de POWER sale ~3 °C
baja porque su celda nativa mezcla mar y tierra. Un tablero que esconde eso es
peor que uno que no lo sabe.

**4. Las advertencias de aptitud son parte del producto.** `GET /api/aptitud`
trae un array `advertencias` que dice, entre otras cosas, que **no sustituye
un levantamiento topográfico ni un estudio de mecánica de suelos**. Si alguien
decide una nivelación con nuestro número y sale mal, el problema es nuestro.
Esas líneas van visibles, no en un tooltip.

### Lo más vendible para la interfaz

- **El expediente de la celda.** `GET /api/expediente/celda/OT0.0.0` devuelve
  todo agrupado por familia (estático, climatológico, observado, derivado) con
  la fuente de cada dato. Es un panel de detalle que se arma solo.
- **La exposición.** `celdas_prioritarias` trae, por celda, el desglose de
  equipamientos: `{"school": 69, "hospital": 14, "university": 24}`. Decir
  *"60% de probabilidad y hay 14 hospitales"* es otra conversación que decir
  *"60%"*.
- **El calendario de obra.** `GET /api/corrida/{id}/ventanas?id_celda=...`
  devuelve, por actividad, la probabilidad de día trabajable para cada día y
  los días esperados. Es una tabla directa.
- **El diagnóstico del sondeo.** `POST /api/sondeo` devuelve
  `interpretacion` en lenguaje operativo (*"inestabilidad fuerte"*, *"columna
  húmeda"*, *"sin tapa"*) además de los números. Y `mu_campo_latente.aportes`
  dice cuánto aportó cada índice, que es lo que permite explicar el pronóstico
  en vez de sólo mostrarlo.

### Datos de verdad para trabajar sin backend

```bash
cd backend && python demo_fusion.py
```

Deja `datos/salida/demo_fusion.json` con el expediente completo, el
pronóstico, la exposición, la aptitud y las ventanas de obra, todo con datos
reales de OSM y NASA POWER.
