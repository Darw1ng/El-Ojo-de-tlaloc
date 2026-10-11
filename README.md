# El Ojo de Tláloc

Sistema de **predicción estocástica de clima** sobre una malla hexagonal, con
asimilación de humedad de suelo observada por radar.

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

El Ojo de Tláloc junta las dos mitades: un generador estocástico propone
cientos de trayectorias posibles de lluvia y temperatura, el radar corrige
sobre qué suelo van a caer, y el resultado no es un número sino una
**probabilidad por hexágono**: *"P(escurrimiento en 72 h > 60 mm) = 0.23 en esta
celda"*.

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
| Núcleo del modelo estocástico | **listo**, 153 pruebas en verde |
| Malla hexagonal y geometría | **listo** |
| Asimilación de humedad de suelo | **listo** (con observación sintética; falta enchufar granulos de NISAR) |
| Métricas de verificación | **listo** (CRPS, Brier, confiabilidad, dispersión) |
| API HTTP | **listo**, 16 endpoints documentados en OpenAPI |
| Climatología | **sintética**, calibrada a las normales del puerto — [qué dataset la reemplaza](docs/05-datos-y-nisar.md) |
| Frontend | lo hace otra persona — contrato en [docs/04-api.md](docs/04-api.md) |

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
- Demo sin frontend: `python backend/demo.py` (escribe `datos/salida/demo.json`)

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
    api/            capa HTTP
  tests/            153 pruebas
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
| [bitacora](docs/bitacora.md) | el paso a paso de la construcción |
| [adr/](docs/adr/) | decisiones con su alternativa descartada |

## Lo que este sistema no es

No es un modelo numérico de la atmósfera. No resuelve ecuaciones de fluidos,
no asimila condiciones de frontera de un modelo global y no compite con el
pronóstico del Servicio Meteorológico Nacional. Es un generador estocástico
calibrado a la climatología local, que produce **incertidumbre honesta** a
escala de hexágono y sabe incorporar lo que el radar observa del suelo. Los
límites están escritos, no escondidos:
[03-modelo-estocastico](docs/03-modelo-estocastico.md#limites-conocidos).
