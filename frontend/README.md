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
