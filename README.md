# El Ojo de Tláloc

**Plataforma de fusión de datos del territorio** sobre una malla hexagonal:
OpenStreetMap, satélites de la NASA y datos propios de globo sonda, con un
modelo estocástico de clima como uno de sus productos.

NASA Space Apps Challenge 2026 · reto [Dancing with the SARs](https://www.spaceappschallenge.org/2026/challenges/dancing-with-the-sars/) ·
equipo Amigos de Timmy (Universal Event) · entrega **15-nov-2026**.

---

## La idea en un párrafo

NISAR no mide la lluvia de mañana: mide el **estado de la superficie** hoy, con
banda L, cada 12 días, de día o de noche y atravesando las nubes. Y ese estado
es justo la condición inicial que le falta a cualquier pronóstico de
inundación, porque **60 mm de lluvia sobre suelo seco se infiltran y 60 mm
sobre suelo saturado corren al río**. Es la misma lluvia y no es el mismo
riesgo.

Pero el radar es sólo una de las piezas. La malla hexagonal funciona como
**índice espacial común**, así que vectores de OpenStreetMap, rejillas de
satélite y un perfil puntual de globo sonda se agregan todos al mismo hexágono
y quedan comparables. De esa fusión salen cinco productos, y el predictor es
uno de ellos, no el centro:

| Producto | Qué pregunta responde |
|---|---|
| **diagnóstico** | qué hay aquí: impermeabilidad, pendiente, cauces, equipamiento |
| **pronóstico** | qué viene: probabilidad por celda y día |
| **exposición** | quién está en riesgo: *69 escuelas y 14 hospitales en esta celda* |
| **aptitud de terreno** | dónde conviene construir (tamiz, no dictamen) |
| **ventanas de obra** | cuándo se puede colar, excavar, compactar |

El detalle completo está en
[07-plataforma-de-fusion](docs/07-plataforma-de-fusion.md).

## Área de interés

Centrada en el enlace que define el proyecto:
[OpenStreetMap 11/19.1704/-96.1654](https://www.openstreetmap.org/#map=11/19.1704/-96.1654) —
puerto de Veracruz, Boca del Río, cuenca baja del Jamapa y del río La Antigua.

| | |
|---|---|
| Caja | 18.91 – 19.43 N, 96.60 – 95.73 W (92 × 58 km) |
| Escala base | **1:16** — 16 hexágonos a lo ancho, 5.77 km por celda, 28.8 km² |
| Celdas | 221 (126 de tierra, 95 de mar) |
| Niveles | 1:16 (221 celdas) · 1:32 (825) · 1:64 (3 055) |

Ver [docs/02-malla-hexagonal.md](docs/02-malla-hexagonal.md) para por qué
hexágonos y qué significa exactamente la escala 1:16.

## Estado

| Parte | Estado |
|---|---|
| Núcleo del modelo estocástico | **listo**, con μ del sondeo e impermeabilidad por celda |
| Malla hexagonal y geometría | **listo** |
| **Fusión: expediente con procedencia** | **listo**, 19 capas |
| **OpenStreetMap (Overpass)** | **listo, datos reales**: 5 603 edificios, 32 422 vías, 747 equipamientos |
| **NASA POWER** | **listo, datos reales**: 21 años de series diarias |
| **Globo sonda (CAPE/CIN/PWAT → μ)** | **listo**, acepta sondeo público y CSV propio |
| **Análisis: exposición, aptitud, ventanas** | **listo** |
| Asimilación de humedad de suelo | **listo** (con observación sintética; falta enchufar gránulos de NISAR) |
| Métricas de verificación | **listo** (CRPS, Brier, confiabilidad, dispersión) |
| API HTTP | **listo**, 23 endpoints documentados en OpenAPI |
| GPM IMERG, SMAP, NISAR, DEM | interfaz escrita, **faltan credenciales Earthdata** |
| Elevación y textura de suelo | **sintéticas** — [qué dataset las reemplaza](docs/05-datos-y-nisar.md) |
| Frontend | lo hace otra persona — contrato en [docs/04-api.md](docs/04-api.md) |

**306 pruebas en verde.** Las que necesitan red se saltan si no hay caché.

## Arrancar

```bash
# backend
cd backend
python -m venv .venv && .venv/Scripts/activate      # Windows
pip install -r requirements.txt -r requirements-dev.txt
uvicorn ojo_tlaloc.api.app:app --reload --port 8000
```

- Documentación interactiva: http://localhost:8000/docs
- Pruebas: `cd backend && pytest -q`
- Demo del modelo: `python backend/demo.py`
- **Demo de la fusión: `python backend/demo_fusion.py`** — baja OSM y NASA
  POWER de verdad, lee un perfil de sonda y produce los cinco productos. La
  primera corrida tarda unos minutos; después sale del caché en segundos.

## Monorepo

```
backend/            el modelo y la API (Python, solo numpy + FastAPI)
  ojo_tlaloc/
    config.py       área de interés, topes, umbrales
    geo.py          proyección local plana
    malla.py        malla hexagonal y escala 1:16
    estadistica.py  normal, Weibull y campos gaussianos correlacionados
    climatologia.py parámetros por celda y mes
    modelo.py       el simulador estocástico
    ensamble.py     resumen probabilístico (lo que se colorea)
    asimilacion.py  filtro de Kalman de ensamble para el dato de radar
    metricas.py     CRPS, Brier, confiabilidad
    expediente.py   la fusión: capas de todas las fuentes con procedencia
    fuentes/        adaptadores
      base.py       procedencia, caché, espejos, buena vecindad
      geometria.py  polígonos y polilíneas en numpy puro
      osm.py        Overpass → impermeabilidad, cauces, exposición
      power.py      NASA POWER → climatología real de 21 años
      sondeo.py     perfil atmosférico → CAPE/CIN/PWAT → μ del modelo
    analisis/       productos que NO son pronóstico
      terreno.py    pendiente y aptitud constructiva
      exposicion.py quién está en riesgo
      ventanas.py   calendario de obra por actividad
    api/            capa HTTP
  tests/            306 pruebas
frontend/           lo hace diseño; aquí sólo el contrato
docs/               un documento por decisión, más la bitácora
datos/              entrada y salida (no se versiona el contenido)
```

## Documentación

| Documento | De qué trata |
|---|---|
| [00-vision-y-alcance](docs/00-vision-y-alcance.md) | qué resuelve, qué no, y cómo encaja en el reto |
| [01-arquitectura](docs/01-arquitectura.md) | piezas, dependencias y por qué el núcleo no sabe de HTTP |
| [02-malla-hexagonal](docs/02-malla-hexagonal.md) | hexágonos, la escala 1:16, niveles |
| [03-modelo-estocastico](docs/03-modelo-estocastico.md) | **la matemática del modelo**, paso por paso |
| [04-api](docs/04-api.md) | contrato para el frontend |
| [05-datos-y-nisar](docs/05-datos-y-nisar.md) | qué es sintético hoy y qué dataset lo sustituye |
| [06-validacion](docs/06-validacion.md) | métricas medidas, con los números flojos incluidos |
| **[07-plataforma-de-fusion](docs/07-plataforma-de-fusion.md)** | **OSM + NASA + globo sonda: cómo se unen y qué sale** |
| [bitacora](docs/bitacora.md) | el paso a paso de la construcción |
| [adr/](docs/adr/) | decisiones con su alternativa descartada |

## Dos hallazgos del camino

**La ciudad amplifica la tormenta sólo cuando el suelo está seco.** Con la
impermeabilidad real de OSM, el escurrimiento sube **+565%** en suelo seco,
+92% en medio y sólo +10% en saturado: en plena temporada ya escurría casi
todo. Eso explica por qué los encharcamientos urbanos más violentos son los de
la primera tormenta fuerte del año.

**El perfil vertical es lo que convierte climatología en pronóstico.** Con
μ = +1.42 del sondeo, el acumulado de 10 días pasa de 111 a 361 mm y los días
con lluvia de 73% a 98%. Ninguna otra fuente —ni OSM, ni un satélite de
superficie— da esa información.

## Lo que este sistema no es

No es un modelo numérico de la atmósfera. No resuelve ecuaciones de fluidos,
no asimila condiciones de frontera de un modelo global y no compite con el
pronóstico del Servicio Meteorológico Nacional. Es un generador estocástico
calibrado a la climatología local, que produce **incertidumbre honesta** a
escala de hexágono y sabe incorporar lo que el radar observa del suelo.

Y **no sustituye a un topógrafo.** El tamiz de terreno sirve para decidir qué
predios vale la pena medir, no para decidir si se construye: un levantamiento
de obra necesita precisión centimétrica y un plano lo firma un perito. Lo que
sí aporta con rigor en esa línea es el *cambio relativo* de elevación por
InSAR —precisión milimétrica en cuánto se hundió algo, no en a qué altura
está—, que es asentamiento diferencial y hundimiento regional.

Los límites están escritos, no escondidos:
[03-modelo-estocastico](docs/03-modelo-estocastico.md#limites-conocidos) y
[07-plataforma-de-fusion](docs/07-plataforma-de-fusion.md).
