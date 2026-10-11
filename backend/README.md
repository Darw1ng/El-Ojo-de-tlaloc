# backend

El modelo y la API. Sólo numpy en el núcleo; FastAPI nada más en `api/`.

## Instalar y correr

```bash
python -m venv .venv
.venv/Scripts/activate                 # Windows
# source .venv/bin/activate            # Linux/Mac
pip install -r requirements.txt -r requirements-dev.txt

uvicorn ojo_tlaloc.api.app:app --reload --port 8000
pytest -q
python demo.py
```

## Usar el modelo sin la API

El núcleo no sabe que existe HTTP, así que se puede usar desde un script o un
notebook:

```python
import datetime as dt
from ojo_tlaloc.malla import MallaHexagonal
from ojo_tlaloc.climatologia import Climatologia
from ojo_tlaloc.modelo import SimuladorEstocastico
from ojo_tlaloc.ensamble import probabilidad_umbral, riesgo

malla = MallaHexagonal()                      # escala 1:16, 221 celdas
clima = Climatologia.sintetica(malla)
sim = SimuladorEstocastico(malla, clima)

r = sim.simular(dt.date(2026, 9, 15), n_dias=14, n_miembros=200,
                semilla=20261114)

p = probabilidad_umbral(r, "lluvia", dia=3, umbral=50.0, ventana_dias=1)
a = riesgo(r, dia=0, ventana_dias=3, umbral_mm=60.0)
```

Con el dato de radar:

```python
from ojo_tlaloc.asimilacion import asimilar, observacion_sintetica

previo = sim.simular(fecha, n_dias=1, n_miembros=200,
                     semilla=1).humedad_suelo[:, 0, :].astype(float)
obs = observacion_sintetica(malla, clima, fecha, semilla=1)
corregido = asimilar(previo, obs)["ensamble"]

r = sim.simular(fecha, n_dias=14, n_miembros=200, semilla=1,
                humedad_inicial=corregido)
```

## Dónde está cada cosa

| Archivo | Qué hay |
|---|---|
| `config.py` | área de interés, topes, umbrales, semilla |
| `geo.py` | proyección local, haversine |
| `malla.py` | malla hexagonal, escala 1:16, GeoJSON |
| `estadistica.py` | normal, Weibull, campos correlacionados |
| `climatologia.py` | parámetros por celda y mes |
| `modelo.py` | **el simulador**, radiación y ET0 |
| `ensamble.py` | capas, series, riesgo, escalas de color |
| `asimilacion.py` | EnKF para el dato de radar |
| `metricas.py` | CRPS, Brier, confiabilidad |
| `api/` | capa HTTP |

Cada módulo arranca con un docstring que explica el *por qué*, no sólo el
*qué*. La matemática completa está en
[docs/03-modelo-estocastico.md](../docs/03-modelo-estocastico.md).
