# El modelo estocástico

Este es el corazón del proyecto. Si sólo se va a leer un documento, es este.

## Qué clase de modelo es

**No** es un modelo numérico de la atmósfera: no resuelve ecuaciones de
fluidos ni toma condiciones de frontera de un modelo global. Eso no cabe en un
hackathon ni corre en un servidor chico.

**Sí** es un *generador estocástico de clima* (weather generator) de la familia
Richardson/WGEN, con dos cosas que los generadores clásicos no tienen:

1. un **campo gaussiano latente** que hace que las celdas vecinas estén
   correlacionadas, y
2. **asimilación** del estado del suelo observado por radar.

Produce, por celda y por día, un ensamble de trayectorias posibles. De ahí
salen probabilidades, que es la salida que sirve para decidir: no *"van a
caer 43 mm"* sino *"hay 23% de probabilidad de pasar de 50 mm"*.

## Variables

| Variable | Unidad | Dominio |
|---|---|---|
| `lluvia` | mm/día | todo |
| `tmax`, `tmin` | °C | todo |
| `et0` | mm/día | todo |
| `humedad_suelo` | saturación 0–1 | sólo tierra |
| `escurrimiento` | mm/día | sólo tierra |

## Los cinco pasos de cada día

### 1. Campo latente gaussiano

Una tormenta cubre decenas de kilómetros, no una celda aislada. Para eso hay
un campo gaussiano con covarianza exponencial sobre la distancia entre centros
de hexágono:

```
Cov(i, j) = exp( -d_ij / L )
```

`L` es la longitud de correlación: **30 km** para lluvia (tamaño típico de un
sistema convectivo) y **90 km** para temperatura (los campos térmicos son
mucho más suaves). Se factoriza una vez con Cholesky, `Σ = A·Aᵀ`, y entonces
`w = A·z` con `z ~ N(0, I)` tiene exactamente esa correlación.

La persistencia día a día se mete con un AR(1) sobre el campo:

```
w_t = φ·w_{t-1} + sqrt(1 - φ²) · A·z_t
```

El factor `sqrt(1-φ²)` no es cosmético: mantiene la **varianza marginal en 1**,
de modo que el campo sigue siendo normal estándar en todo el horizonte y los
umbrales calibrados en unidades de normal estándar siguen siendo válidos el
día 14. Si se usara `φ·w + A·z` la varianza crecería y el modelo se iría
volviendo más y más lluvioso con el horizonte. Probado en
`test_la_serie_ar1_conserva_varianza_marginal`.

Con `φ = 0.55` salen rachas de 2 a 3 días, que es lo que se observa en
temporada de lluvias.

### 2. Ocurrencia: cadena de Markov acoplada en el espacio

Llueve en la celda `c` si `w_t(c) > τ(c)`, con el umbral dependiendo de lo que
pasó ayer:

```
τ = Φ⁻¹(1 - p01)   si ayer estuvo seco
τ = Φ⁻¹(1 - p11)   si ayer llovió
```

Es una cadena de Markov de primer orden **por celda**, acoplada entre celdas
por el campo `w`. La calibración es la parte bonita: dada la probabilidad
marginal objetivo `π` (la fracción climatológica de días con lluvia) y un
exceso de persistencia `ρ`, se define

```
p01 = π · (1 - ρ)
p11 = π + (1 - π) · ρ
```

y entonces la distribución estacionaria de la cadena es **exactamente** `π`:

```
π_estacionaria = p01 / (1 + p01 - p11)
1 + p01 - p11  = 1 + π - πρ - π - ρ + πρ = 1 - ρ
p01 / (1 - ρ)  = π(1-ρ)/(1-ρ) = π            ✓
```

O sea: se puede pedir la frecuencia climatológica *y* la persistencia sin que
una estropee a la otra. Se verifica numéricamente para los 12 meses y todas
las celdas con error < 1e-12 en
`test_la_cadena_de_markov_reproduce_la_probabilidad_marginal`.

`ρ` va de 0.30 (marzo, seco) a 0.50 (septiembre, temporada convectiva).

### 3. Intensidad: cópula gaussiana sobre Weibull

Dado que llueve, ¿cuánto? Se usa **el mismo** `w` mediante una cópula
gaussiana:

```
u      = ( Φ(w) - (1 - p) ) / p        ∈ (0, 1)
lluvia = Weibull⁻¹(u) = λ · ( -ln(1-u) )^(1/k)
```

Esto es lo que hace que el modelo se parezca a una tormenta de verdad: el
centro de la mancha (donde `w` es alto) es también **donde más llueve**. Sin
la cópula, la ocurrencia sería espacialmente coherente pero la intensidad
sería ruido blanco, y el mapa mostraría celdas de 80 mm pegadas a celdas de
2 mm.

Se eligió Weibull y no Gamma por dos razones:

- **Inversa en forma cerrada**, que es lo que permite la cópula sin necesitar
  la inversa de la gamma incompleta (y sin scipy, ver
  [adr/0003](adr/0003-sin-scipy.md)).
- Con **forma k < 1** reproduce la cola pesada de la lluvia convectiva, que es
  justo lo que importa para el riesgo de inundación. `k` va de 0.78
  (septiembre) a 0.95 (invierno, lluvia de nortes, más uniforme).

Wilks (1999) compara gamma, Weibull y exponencial mixta para lluvia diaria:
las tres ajustan de forma comparable, la Weibull gana en costo.

La escala `λ` se calibra **exigiendo que el acumulado mensual cuadre con la
normal climatológica**: `media_por_día_lluvioso = acumulado / (días · π)` y
para la Weibull `media = λ · Γ(1 + 1/k)`.

### 4. Temperatura

Anomalía AR(1) con su propio campo espacial (más suave), más el efecto de la
lluvia:

```
tmax = tmax_climatológica(mes) + anomalía - 2.2·[llueve]
tmin = tmin_climatológica(mes) + 0.7·anomalía + 0.8·[llueve]
```

Los días de lluvia bajan la máxima por nubosidad y suben la mínima porque las
nubes atrapan el calor nocturno. Se garantiza `tmax > tmin` con una brecha
mínima de 1 °C.

### 5. Balance de agua en el suelo

Depósito de una capa, tipo Manabe:

```
escurrimiento = P · S^β                 β = 1.5
ET real       = ET0 · S
S_{t+1}       = S_t + (P - escurrimiento - ET) / capacidad
exceso        = lo que pase de S = 1 se va como percolación y suma al escurrimiento
```

`S` es la saturación relativa en [0, 1] y `capacidad` va de 60 a 180 mm según
la elevación (en pendiente el suelo es más delgado). El exponente β controla
lo que todo el proyecto quiere mostrar: **suelo seco absorbe, suelo saturado
escurre**.

`ET0` se calcula por **Hargreaves-Samani**:

```
ET0 = 0.0023 · Ra · (Tmed + 17.8) · sqrt(Tmax - Tmin)
```

con `Ra` la radiación extraterrestre (FAO-56 ec. 21), que sólo depende de
latitud y día del año y se precalcula por celda. Se usa Hargreaves y no
Penman-Monteith porque sólo necesita temperatura: el pronóstico no produce
viento ni humedad relativa por celda. El sesgo típico es 10-15% en clima
húmedo, aceptable para un balance de agua. La radiación se verifica contra una
identidad analítica exacta en el equinoccio
(`test_radiacion_extraterrestre_identidad_del_equinoccio`).

## Asimilación del dato de radar

La humedad del suelo `S` es la variable que conecta con NISAR. Se corrige con
un **filtro de Kalman de ensamble escalar por celda, con observaciones
perturbadas**:

```
K       = var_modelo / (var_modelo + var_obs)
S_i⁺    = S_i + K·(y + ε_i - S_i),     ε_i ~ N(0, var_obs)
```

La varianza del modelo es la dispersión del propio ensamble, así que la
ganancia se ajusta sola: cuando el modelo está seguro, el dato pesa poco.

La perturbación `ε_i` es lo que mantiene la dispersión correcta después de
actualizar. **Sin ella el ensamble colapsa** —todos los miembros terminan en
el mismo valor— y el pronóstico se vuelve sobreconfiado, que es exactamente lo
que no debe pasar en una capa de alerta. Probado en
`test_el_ensamble_no_colapsa`.

El dato llega como humedad volumétrica (m³/m³) y el modelo trabaja en
saturación relativa, así que hay una conversión por textura de suelo:
`S = (θ - θ_res)/(θ_sat - θ_res)`. **Esa conversión es la fuente de error más
grande de toda la cadena** y está explícita, no escondida: usar una textura
única para todo el dominio mete un sesgo de hasta 0.15 de saturación.

## Reproducibilidad

Todo cuelga de `numpy.random.default_rng(semilla)`. La misma petición con la
misma semilla da bit por bit el mismo resultado, y el `id_corrida` de la API
es un hash determinista de los parámetros: una URL compartida reproduce la
vista exacta. La semilla por defecto es `20261114`, la fecha del hackathon.

## Rendimiento

Nivel 0 (221 celdas), medido:

| Miembros × días | Tiempo | Memoria |
|---|---|---|
| 50 × 7 | 0.08 s | 1.8 MB |
| 200 × 14 | **0.30 s** | 14.2 MB |
| 500 × 14 | 1.00 s | 35.4 MB |
| 200 × 30 | 0.39 s | 30.3 MB |
| 1000 × 14 | 2.65 s | 70.8 MB |

El truco está en el orden del bucle: se itera sobre **días** (14 pasos) y
dentro cada operación es vectorizada sobre `(miembros, celdas)` a la vez. El
costo dominante es el producto `A·z` del campo espacial, que numpy resuelve
como un GEMM. La API rechaza con `413` cualquier petición que pase de 512 MB.

## Límites conocidos

Escritos aquí, no escondidos. Son las preguntas que un jurado puede hacer y
conviene tener la respuesta antes:

1. **La persistencia vive en dos lados.** `φ` del campo y `p01/p11` de la
   cadena se solapan: los dos generan rachas. Con datos reales hay que
   calibrarlos conjuntamente, no por separado.
2. **La escala Weibull se calibra por acumulado, no por frecuencia.** Con
   `k ≈ 0.8` eso hace que ~10% de los días húmedos salgan por debajo de 1 mm,
   así que el conteo de "días con lluvia apreciable" queda un poco por debajo
   de la normal mientras el acumulado cuadra (medido: 0.58 contra 0.67
   objetivo en septiembre). Se eligió cuadrar el acumulado porque es lo que
   manda en riesgo de inundación.
3. **La climatología es estacionaria.** No hay tendencia de cambio climático
   ni ENSO. Para horizontes de días no importa; para proyecciones a años, sí.
4. **La memoria del suelo dura días, no meses.** Con 90 días de calentamiento
   el estado inicial deja de importar (probado en
   `test_el_calentamiento_olvida_la_humedad_inicial`). Eso **acota cuánto vale
   la asimilación**: corrige el arranque del pronóstico, no lo determina para
   siempre. Decirlo es más honesto que vender el radar como oráculo.
5. **El acumulado simulado sale ~5% arriba de la climatología objetivo** por el
   condicionamiento de Markov combinado con la cópula. Está dentro de la
   tolerancia que piden las pruebas (12%) y es una dirección conservadora para
   una alerta.
6. **No hay topografía real ni cuenca hidrológica.** El escurrimiento es
   puntual por celda: no se enruta agua de una celda a otra. Para pasar de
   "escurre mucho aquí" a "el río sube tanto allá" hace falta un modelo de
   cuenca con el DEM y aforos.

## Referencias

- Richardson (1981), *Stochastic simulation of daily precipitation,
  temperature and solar radiation*.
- Wilks (1998), *Multisite generalization of a daily stochastic precipitation
  generation model* — el campo latente gaussiano.
- Wilks (1999), *Interannual variability and extreme-value characteristics of
  several stochastic daily precipitation models*.
- Allen et al. (1998), *FAO-56 Crop evapotranspiration* — Ra y Hargreaves.
- Evensen (2003), *The Ensemble Kalman Filter* — EnKF con observaciones
  perturbadas.
- Manabe (1969) — el depósito de una capa para el balance de agua.
