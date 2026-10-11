# La plataforma de fusión

Este documento responde a la pregunta que define la segunda etapa del
proyecto: *¿se puede unir OpenStreetMap, los datos de la NASA y datos
recolectados en bruto, y hacer más que un modelo predictivo?*

Sí. Y la pieza que lo hace posible ya estaba construida.

## La malla hexagonal es el índice espacial común

Esa es toda la idea. Vectores de OSM, rejillas de satélite de 50 km y un
perfil puntual de globo sonda son objetos geométricamente incompatibles. Pero
los tres se pueden **agregar al mismo hexágono**, y una vez ahí quedan
comparables, consultables juntos y combinables.

```
   FUENTES                    AGREGACIÓN              EXPEDIENTE
   ───────                    ──────────              ──────────
   OSM (vectores)   ─┐
   NASA (rejillas)   ├──►  malla hexagonal  ──►   un objeto por celda
   globo (perfil)   ─┘      (índice común)         con procedencia
                                                         │
                          ┌──────────────────────────────┤
                          ▼              ▼               ▼
                     diagnóstico    pronóstico    análisis derivados
                     (qué hay)      (qué viene)   (exposición, aptitud,
                                                   ventanas de obra)
```

El modelo estocástico pasa a ser **uno de los consumidores** del expediente,
no el centro del sistema. Esa es la diferencia entre un modelo con datos
pegados por fuera y una plataforma.

## El expediente del hexágono

Cada celda acumula cuatro familias de atributo, y cada atributo sabe de dónde
vino:

| Familia | Qué es | Fuente |
|---|---|---|
| **estático** | terreno y ciudad: elevación, pendiente, impermeabilidad, cauces, infraestructura | OSM, DEM |
| **climatológico** | lo normal para la época | NASA POWER |
| **observado** | el estado de hoy: humedad del suelo, perfil atmosférico | NISAR, SMAP, globo |
| **derivado** | lo que se calcula de los anteriores | el propio sistema |

`GET /api/expediente/celda/OT0.0.0` devuelve todo eso agrupado, con la fuente
y el nivel de cada dato. Es la respuesta a *"qué se sabe de este pedazo de
territorio"*.

## Procedencia hasta el final

El expediente nunca entrega un número pelado. Cada capa viaja con su
`Procedencia`: fuente, nivel, resolución nativa, cadencia, incertidumbre,
licencia, atribución y nota. No es burocracia, resuelve cuatro problemas
concretos:

1. **Honestidad.** Un valor sintético y una observación de satélite no pueden
   verse iguales en la interfaz.
2. **Licencias.** OSM es ODbL y exige atribución visible. Si el dato no sabe
   de dónde viene, la atribución se pierde y se incumple la licencia.
3. **Incertidumbre.** El filtro de Kalman necesita la varianza de la
   observación; si cada fuente la declara, la asimilación pondera sola.
4. **Reproducibilidad.** Saber qué gránulo y qué fecha produjo un mapa.

Hay cuatro niveles declarados: `observado` (medición real), `reanalisis`
(modelo alimentado con observaciones), `derivado` (calculado) y `sintetico`
(inventado por nosotros). `GET /api/expediente/atribuciones` entrega la lista
de capas sintéticas que la interfaz **tiene que rotular**.

### Las fuentes declaran sus propios sesgos

Una fuente que conoce sus límites vale mucho más que una que entrega números
sin contexto. NASA POWER devuelve, junto con los datos, esto:

| Variable | Sesgo | Se corrige con |
|---|---|---|
| `weibull_forma` | cola subestimada: MERRA-2 tiene celdas de 50 km y suaviza los máximos | GPM IMERG |
| `frac_dias_lluvia` | sesgo de llovizna — **ya corregido** | ya aplicado |
| `tmax_mensual` | máxima ~3 °C baja: la celda nativa mezcla mar y tierra | estación del SMN |

Eso viaja hasta la API y puede llegar a la pantalla.

## Las tres fuentes conectadas hoy

### OpenStreetMap: datos del territorio, no fondo de mapa

Un satélite ve reflectancia; OSM sabe **qué es** cada cosa. Vía Overpass se
bajan edificios, uso de suelo, agua, cauces, vialidad e infraestructura
crítica, y se agregan al hexágono con tres estrategias según el tamaño del
polígono frente a la celda (5.8 km):

| Caso | Método |
|---|---|
| polígono mucho menor (edificios, 10–50 m) | área exacta por el teorema del área, al hexágono del centroide |
| polígono comparable (uso de suelo, agua) | muestreo por puntos, rejilla de 200 m |
| polilínea (vialidad, cauces) | longitud por segmento al hexágono del punto medio |

**Capas que produce:** `fraccion_impermeable`, `fraccion_construida`,
`fraccion_pavimento`, `fraccion_agua`, `impermeabilidad_uso_suelo`,
`cobertura_uso_suelo`, `impermeabilidad_proxy_vial`, `densidad_vial`,
`densidad_cauces`, `edificios`, `area_pisos`, `infraestructura_critica`,
`peso_critico`.

#### El problema de cobertura, y cómo se resolvió sin inventar

Medido el 10-oct-2026 en el área: **5 603 edificios** para una zona
metropolitana de cerca de 900 mil habitantes, y sólo el **10% del uso de suelo
mapeado** en la celda del puerto. OSM está muy incompleto aquí.

Contar área de edificios daba **1.9%** de ocupación en el centro de Veracruz,
que es imposible. La vialidad, en cambio, sí está bien mapeada (32 422 vías).
Así que la impermeabilidad se estima por **tres vías independientes y se toma
el máximo**:

```
imperm = max( edificios + pavimento,
              uso de suelo,
              proxy de densidad vial ) · (1 - fracción de agua)
```

No es arbitrario: las tres subestiman por construcción (lo que no está mapeado
no suma), así que la mayor es la menos mala. El proxy vial está calibrado
contra los rangos de la hidrología urbana y **se declara como proxy**, con
`incertidumbre: 0.15` y una nota que dice que no es una medición:

| Densidad vial | Zona | Impermeabilidad |
|---|---|---|
| 0–1 km/km² | rural | 0.00–0.10 |
| 5–10 | suburbano | 0.32–0.51 |
| > 15 | urbano denso | 0.63–0.78 |

Resultado medido: puerto de Veracruz **69%**, zona urbana contigua 48–65%,
media del dominio 12%. Ese es el orden correcto.

### NASA POWER: la climatología deja de ser sintética

POWER (MERRA-2) es la fuente de la NASA más fácil de enchufar: API abierta,
sin credenciales. Pero la decisión que importa fue **no usar su endpoint de
climatología**: las doce medias mensuales no permiten separar frecuencia de
intensidad, y 100 mm al mes pueden ser 20 días de 5 mm o 2 días de 50 mm. Para
riesgo de inundación son dos mundos.

Así que se bajan **21 años de datos diarios** (7 670 días en 9 puntos de
rejilla) y la climatología se calcula aquí: frecuencia de días húmedos,
acumulado, forma de la Weibull, persistencia de la cadena de Markov y
temperaturas. Eso reemplaza las seis series que estaban escritas a mano.

**Validación cruzada:** POWER da **1 706 mm/año** y mi climatología sintética
daba 1 656. Coinciden al 3%, lo que confirma que los valores sintéticos
estaban en el orden correcto.

**Y corrige un error mío:** POWER pone el pico de temperatura en **mayo**, no
en agosto. Tiene razón — en el trópico húmedo la nubosidad de la temporada de
lluvias baja la máxima. Mi climatología sintética tenía el patrón invertido.

#### Dos sesgos encontrados y qué se hizo

**Sesgo de llovizna.** Con el umbral de 1 mm de la OMM, POWER daba **195 días
de lluvia al año** contra los 115–130 de las normales. Es el sesgo documentado
de los reanálisis: reparten la precipitación en demasiados días con poca
intensidad. Corrección por mapeo de frecuencia:

| Umbral | días/año | % del acumulado |
|---|---|---|
| 1.0 mm | 195.1 | 97.8% |
| **3.7 mm** | **125** | **~89%** |
| 5.0 mm | 101.3 | 83.2% |

Se calibra el umbral a 3.7 mm y **el acumulado NO se recorta**: se pasa
completo, y la climatología redistribuye la misma masa de agua entre menos
días con más intensidad. Conservar el agua importa más que conservar la
intensidad por evento cuando se calcula escurrimiento.

**Cola subestimada.** El método de momentos daba forma de Weibull de 1.0–1.9,
por encima del 0.7–0.9 de la literatura. Dos causas: el truncamiento por el
umbral reduce el coeficiente de variación, y MERRA-2 suaviza los máximos (un
evento de 150 mm sobre 20 km² se diluye en 3 000 km²). Se cambió a **ajuste
por cuantiles**, que tiene solución cerrada y preserva la cola alta:

```
k = ln( ln(1-p_alto) / ln(1-p_bajo) ) / ln( x_alto / x_bajo )
```

Con p = 0.5 y 0.99, la forma bajó a 0.99–1.57. Lo que queda por encima es el
suavizado de MERRA-2, y está **declarado como sesgo** con su corrección
(IMERG).

### El globo sonda: lo que convierte climatología en pronóstico

Este es el aporte conceptual más grande. El modelo, tal como estaba, es
climatológico: sabe que en septiembre llueve mucho en Veracruz, **no sabe si
llueve el jueves**. Ni OSM ni un satélite de superficie arreglan eso. Lo
arregla saber cómo está la atmósfera en la vertical.

De un perfil se calculan CAPE, CIN, agua precipitable, LCL y los índices K y
Total Totals. Y entran al modelo por el lugar correcto: **la media del campo
latente**.

```
w_t = μ_t + φ (w_{t-1} - μ_{t-1}) + sqrt(1-φ²) A z_t
μ_t = b₀ + b₁·z(√CAPE) + b₂·z(PWAT) - b₃·z(CIN)
```

Y como la ocurrencia es `w > τ` con `w ~ N(μ, 1)`, entonces
`P(lluvia) = Φ(μ − τ)`: **ajustar μ desde los índices es literalmente una
regresión probit**. No es un factor de corrección inventado, es un modelo
estadístico con coeficientes estimables por máxima verosimilitud, con error
estándar y prueba de significancia. Está implementado en `calibrar_probit()` y
verificado: recupera coeficientes conocidos a ±0.12 y **no encuentra señal
donde no hay**.

#### Efecto medido

| | días con lluvia | acumulado 10 d (p50) |
|---|---|---|
| sin sondeo (climatológico) | 73% | 111 mm |
| μ = +1.42 (atmósfera inestable) | 98% | **361 mm** |
| μ = −1.42 (atmósfera estable) | 18% | 10 mm |

#### Tres decisiones de diseño del sondeo

1. **El CAPE entra por su raíz.** La velocidad vertical máxima es
   `w = √(2·CAPE)`, así que la raíz es la cantidad con significado lineal. Sin
   esto, un CAPE de tarde de verano (3 000 J/kg) daba z = 3.7 y saturaba μ por
   sí solo; con la raíz da z = 1.4, que es lo que corresponde a "una tarde
   convectiva, no un evento histórico".
2. **μ está acotada a ±1.5.** No es timidez: μ desplaza la probabilidad de
   **todo** el dominio, y con μ = 3 la probabilidad se pega a 1 en todas las
   celdas, lo que destruye la dispersión del ensamble y con ella la única
   salida útil del sistema.
3. **Los perfiles imposibles se descartan, no se usan.** `validar_indices()`
   revisa rangos físicos (el CAPE más alto medido en la Tierra ronda los
   8 000 J/kg) y marca el perfil como no confiable. El endpoint de fusión
   entonces corre climatológico y lo dice, en lugar de mover el pronóstico con
   basura.

#### Un solo perfil alcanza para todo el dominio

Parece poco un punto para 92 km, y no lo es: **la inestabilidad atmosférica es
propiedad de la masa de aire, de escala sinóptica (cientos de km)**, mientras
el campo espacial del modelo tiene longitud de correlación de 30 km. Una μ
común para todo el dominio es físicamente correcta. No hace falta una red de
globos; hace falta uno bien puesto.

#### El límite honesto

La información de un sondeo decae en dos o tres días. El sistema queda con dos
regímenes declarados, que es como funcionan los pronósticos de verdad:

| Horizonte | Qué lo informa |
|---|---|
| 0–3 días | sonda (atmósfera) + radar (suelo) → habilidad real |
| 3–14 días | climatología con incertidumbre creciente |

#### Un parser, dos hardwares

`leer_sondeo()` detecta el formato solo y acepta:

- **tabla de Wyoming / IGRA**, que es como publican los sondeos el SMN y los
  archivos históricos (el SMN-CNA lanza dos veces al día y Veracruz es una de
  las estaciones);
- **CSV crudo del globo propio**, lo que escribe una sonda casera con BME280 y
  GPS, con alias de columna en español y en inglés, conversión de humedad
  relativa a rocío y ordenamiento por presión (da igual si el registro es del
  ascenso o del descenso).

Eso significa que **el modelo no depende de tener hardware**: la regresión
probit se puede calibrar hoy con sondeos históricos, y el globo propio entra
como fuente en vivo y diferenciador. Si el vuelo es de globo cautivo, el
perfil sólo cubre la capa límite: los índices de altura salen `NaN` y eso es
correcto, no un fallo; el viento y la temperatura de los primeros cientos de
metros quedan, que es justo lo que se necesita para obra.

## Lo que la impermeabilidad cambió en el modelo

El escurrimiento pasó de usar un exponente uniforme a usar el modelo de área
impermeable directamente conectada, el estándar de hidrología urbana:

```
escurrimiento = imperm · P + (1 - imperm) · P · S^β
```

Lo pavimentado escurre todo sin importar cómo esté el suelo; lo permeable
escurre según su saturación. Con `imperm = 0` se recupera exactamente el
comportamiento anterior, así que la extensión es retrocompatible.

### El hallazgo

| Estado del suelo | Escurrimiento sin imperm. | Con imperm. 0.54 | Cambio |
|---|---|---|---|
| seco (S = 0.15) | 0.04 mm | 0.27 mm | **+565%** |
| medio (S = 0.45) | 0.68 mm | 1.30 mm | +92% |
| saturado (S = 0.85) | 9.36 mm | 10.33 mm | +10% |

**La impermeabilidad urbana importa cuando el suelo podría absorber, no cuando
ya está saturado.** O sea: la ciudad convierte una tormenta sobre suelo seco en
inundación repentina; en plena temporada de lluvias da casi igual porque ya
escurría todo. Eso explica por qué los encharcamientos urbanos más violentos
suelen ser los de la primera tormenta fuerte de la temporada.

Y hay un efecto que suele olvidarse: en la zona impermeable **el suelo tampoco
se moja**, porque el agua se va por el drenaje antes de infiltrarse. La ciudad
escurre más y se seca más (medido: humedad de suelo urbana 0.72 contra 0.86).

## Los cinco productos de las mismas capas

| Producto | Qué pregunta responde | Es predicción |
|---|---|---|
| **diagnóstico** | qué hay aquí: impermeabilidad, pendiente, cauces, equipamiento | no |
| **pronóstico** | qué viene: probabilidad por celda y día | sí |
| **exposición** | quién está en riesgo | no (cruce) |
| **aptitud de terreno** | dónde conviene construir | no (multicriterio) |
| **ventanas de obra** | cuándo se puede trabajar | traducción |

### Exposición

Convierte un mapa de probabilidad en una lista de afectados. Medido con el
sondeo aplicado y corte de 30%:

> 733 equipamientos críticos y 5 530 edificios en 126 celdas con probabilidad
> mayor o igual a 30%

Y por celda prioritaria, el desglose: `OT0.1.0` tiene 69 escuelas, 14
hospitales, 24 universidades, 7 clínicas, 2 estaciones de bomberos. **Eso es
la diferencia entre un mapa y una decisión**, y sale completo de cruzar el
pronóstico con OSM.

El índice es `probabilidad × consecuencia`, que es la definición operativa de
riesgo en protección civil, con la consecuencia normalizada al máximo del
dominio (sirve para ordenar celdas dentro de esta área, no para comparar con
otra ciudad).

Un detalle de diseño: cuando el corte pedido es inalcanzable, se dice. "Sin
elementos expuestos" y "ninguna celda llega al corte de 90%, el máximo del
dominio es 25%" significan cosas muy distintas, y la segunda no es
tranquilizadora.

### Aptitud de terreno, y su límite legal

Índice multicriterio con **pesos explícitos** (están expuestos para que se
discutan, porque son una opinión y no un cálculo): no inundable 0.30,
pendiente 0.15, suelo firme 0.15, accesos 0.15, disponible 0.15, servicios
0.10.

El criterio `disponible` se agregó porque sin él **el índice premiaba las
celdas más densas del puerto**, que es justo donde no hay terreno que comprar.
Un tamiz para buscar predio tiene que valorar que quede suelo libre.

🚫 **Lo que NO hace, y está escrito en la respuesta de la API:**

- No sustituye levantamiento topográfico. Eso necesita precisión
  centimétrica — GNSS RTK, estación total o LiDAR de dron. Un DEM satelital da
  ±5–10 m vertical y esta malla da 1.4 km de lado en su nivel más fino. **Un
  plano topográfico lo firma un perito con responsabilidad legal.**
- No sustituye mecánica de suelos.
- No sirve para decidir una nivelación, un corte o un relleno.

Lo que sí aporta con rigor en esa línea es el **cambio relativo** de elevación
medido por InSAR: precisión milimétrica en *cuánto se hundió* algo, no en *a
qué altura está*. Para una constructora eso es asentamiento diferencial y
hundimiento regional, y es exactamente lo que el producto GUNW de NISAR hace
mejor que cualquier otra técnica. Esa capa todavía no está conectada.

### Ventanas de obra

Una constructora no necesita saber que van a caer 43 mm; necesita saber si el
jueves se puede colar. Siete actividades con sus umbrales y **su razón**:

| Actividad | Lluvia máx | Suelo | Tmax |
|---|---|---|---|
| colado de concreto | 1.0 mm | — | 35 °C |
| movimiento de tierras | 5.0 mm | < 0.65 | — |
| compactación | 2.0 mm | 0.25–0.55 | — |
| impermeabilización | 0.2 mm | — | 38 °C |
| acabados exteriores | 0.5 mm | — | 36 °C |
| obra exterior general | 10.0 mm | — | 40 °C |
| montaje con grúa | — | — | — |

La probabilidad se evalúa **por miembro del ensamble**, no sobre la mediana:
un día con mediana de 0.5 mm y cola larga puede tener 30% de probabilidad de
pasarse del umbral, y eso es lo que el jefe de obra necesita saber.

**Montaje con grúa se omite a propósito.** Su límite real es el viento a la
altura de la pluma, las grúas torre se ponen fuera de servicio del orden de
45–72 km/h según fabricante, y el modelo no genera viento. Se declara y se
omite en lugar de contestarla con datos que no existen. Es justo lo que
mediría un globo cautivo a 100–300 m — y el viento a 60 m no es el de una
estación a 10 m, hay un perfil logarítmico.

## Buena vecindad con los servicios públicos

Overpass y POWER son gratuitos y de uso comunitario. El cliente:

- se identifica con `User-Agent` (Overpass devuelve `406` sin uno reconocible);
- espera al menos 2 s entre peticiones;
- **cachea en disco** por (capa, bbox), así que la segunda corrida no vuelve a
  descargar: medido, 218 s la primera vez y 6 s después;
- hace **una pasada por todos los espejos antes de insistir en ninguno**, y
  acumula los errores de todos. Esto último arregló un diagnóstico engañoso:
  el servidor principal daba `504` por tasa y el espejo respondía bien, pero
  el mensaje de error culpaba al espejo;
- detecta el campo `remark` de Overpass, que avisa de consultas truncadas por
  memoria devolviendo `200`. Sin esa guarda, datos incompletos entrarían
  silenciosamente al modelo.

## Qué sigue

En orden de lo que más mueve la aguja:

1. **GPM IMERG** — lluvia observada cada 30 min a 11 km. Es lo que convierte
   la validación de "consistencia interna" en habilidad real, y corrige la
   cola de la Weibull. Requiere cuenta Earthdata.
2. **NISAR GCOV + SMAP** — humedad de suelo observada. La cadena de
   asimilación (pasos 4 a 7) ya está hecha y probada; faltan descarga y
   *retrieval*. SMAP complementa a NISAR: uno da cadencia (2–3 días), el otro
   detalle.
3. **DEM real (SRTM 30 m)** — quita la elevación sintética y vuelve creíble la
   pendiente.
4. **Textura de suelo por celda** (INEGI / SoilGrids) — quita el sesgo de la
   conversión volumétrica, que es el error más grande de la cadena de
   asimilación.
5. **Calibrar el probit** con sondeos históricos del SMN y lluvia observada.
   Con eso los coeficientes dejan de ser provisionales.
6. **InSAR / GUNW** — la capa de hundimiento, que es el producto más vendible
   a constructoras y el más defendible técnicamente.
7. **Producto satelital de superficie impermeable** — reemplaza el proxy
   vial.

Las fuentes con credenciales ya tienen su interfaz escrita
(`FuenteConCredenciales`), así que conectarlas es rellenar un método, no
rediseñar.
