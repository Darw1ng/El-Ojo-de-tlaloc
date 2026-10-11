# Bitácora

Paso a paso de la construcción, con las decisiones y los tropiezos. Lo que no
funcionó también está anotado: es la parte útil.

---

## 10-oct-2026 — Sesión 1: el núcleo del modelo

Punto de partida: repositorio vacío (creado ese mismo día, 0 commits). Encargo:
el modelo de predicción estocástica primero, backend antes que nada, monorepo,
mapa de OSM centrado en `11/19.1704/-96.1654` coloreado por hexágonos a escala
1:16. El diseño lo hace otra persona.

### 1. Área de interés

El bbox se derivó del enlace de OSM, no a ojo. Con zoom 11 y un viewport de
1280×800:

```
resolución = 156543.03392 · cos(19.1704) / 2¹¹ = 72.2 m/px
ancho = 1280 px → 92.4 km → 0.879° de longitud
alto  =  800 px → 57.7 km → 0.522° de latitud
```

Resultado: 18.91–19.43 N, 96.60–95.73 W. Cubre el puerto de Veracruz, Boca del
Río, la cuenca baja del Jamapa y del río La Antigua.

### 2. Proyección

Un hexágono regular en grados no es regular sobre el terreno (un grado de
longitud aquí mide 105 km y uno de latitud 111 km). Se metió una
equirectangular local escalada por `cos(lat₀)`.

**Medido:** error máximo del 0.16% contra haversine sobre 300 pares al azar.
El docstring decía al principio "menor al 0.1%" y la prueba lo desmintió: se
corrigió el docstring en vez de relajar la prueba en silencio.

### 3. Malla hexagonal, escala 1:16

Se definió la escala como *cuántos hexágonos caben a lo ancho del área*, que
es la lectura directa de "1:16" y la que deja todo determinado sin parámetros
libres: 5.77 km de ancho por celda, 28.8 km², **221 celdas**.

Como la otra lectura posible era 1:16 en área, también quedó cubierta: cada
nivel duplica a lo ancho y cuartea el área, así que dos niveles dan 1:16
exacto en área. Las dos están probadas.

**Descartado H3** ([adr/0002](adr/0002-malla-propia-vs-h3.md)): subdivide 1:7,
no da 1:16 limpio, orienta por el icosaedro global y añade una dependencia
binaria para 40 líneas de geometría.

### 4. Base estadística sin scipy

Se necesitaban `Φ`, `Φ⁻¹`, una distribución de cola pesada con inversa, y
Cholesky. Se implementaron las tres primeras
([adr/0003](adr/0003-sin-scipy.md)) y se verificaron contra `math.erfc` y
contra valores publicados.

**Tropiezo:** la primera versión de `erfc` mezclaba dos variantes de
Numerical Recipes — evaluaba el polinomio de `erfcc` (que va en `t`) sobre la
variable de `erfccheb` (que va en `4t−2`). Daba resultados plausibles pero
mal. Lo cazó la comparación contra `math.erfc`: de ahí la regla de verificar
siempre contra algo independiente.

### 5. Campo gaussiano correlacionado

La pieza que hace que esto no sea ruido blanco: covarianza `exp(−d/L)`
factorizada con Cholesky, más AR(1) temporal con el factor `sqrt(1−φ²)` que
conserva la varianza marginal en 1.

**Medido:** correlación empírica a 0.055 de la objetivo con 4 000 muestras;
AR(1) lag-1 de 0.707 contra 0.700 pedido; varianza marginal 1.009.

### 6. Climatología

Normales mensuales del puerto de Veracruz (≈1 656 mm/año, ≈115 días con
lluvia) más gradientes espaciales. La calibración de la cadena de Markov salió
elegante: con `p01 = π(1−ρ)` y `p11 = π + (1−π)ρ` la estacionaria es
exactamente `π`, así que se puede pedir la frecuencia climatológica *y* la
persistencia sin que una estropee a la otra. **Error medido: 2.2e-16.**

**Tropiezo grande:** el primer perfil de elevación sintético ponía 1 204 m en
el extremo oeste del bbox y producía 2 812 mm/año de lluvia ahí. Falso: la
zona es planicie costera y el ascenso real a la sierra empieza al oeste de
96.7 W, ya fuera del dominio. Se rehízo con un perfil conservador (máximo
368 m dentro del bbox, lluvia anual media 1 734 mm) y se dejó una prueba que
falla si alguien vuelve a inventar montañas.

### 7. El simulador

Cinco pasos por día: campo latente → ocurrencia Markov → intensidad por cópula
gaussiana sobre Weibull → temperatura → balance de agua con ET0 de Hargreaves.
Detalle en [03-modelo-estocastico](03-modelo-estocastico.md).

El bucle itera sobre **días** y vectoriza sobre `(miembros, celdas)`:
**0.30 s** para 200 miembros × 14 días × 221 celdas.

**Medido de entrada:**

| | |
|---|---|
| Acumulado de septiembre, celda al nivel del mar | 369 mm contra 350 objetivo (+5%) |
| Correlación de lluvia entre vecinas (5.8 km) | 0.75 |
| Correlación entre lejanas (> 60 km) | 0.04 |
| Rangos físicos | tmax 20–37 °C, ET0 3.3 mm/día, suelo 0.1–1.0 |

### 8. Asimilación

Filtro de Kalman de ensamble escalar por celda con observaciones perturbadas.
Se verificó la fórmula a mano en una celda: Kalman teórico 0.573, obtenido
0.570.

La perturbación de la observación no es opcional: sin ella el ensamble
colapsa y el pronóstico se vuelve sobreconfiado. Hay una prueba dedicada.

### 9. Métricas

CRPS (estimador justo), Brier, confiabilidad, descomposición de Murphy,
dispersión contra error, tabla de contingencia.

**Dos correcciones de rigor:**

- El docstring del CRPS afirmaba que el estimador clásico *premia* a los
  ensambles chicos. Es al revés: divide entre `m²`, subestima `E|X−X'|` y deja
  el CRPS más alto, o sea los castiga. Corregido.
- La descomposición de Murphy no cerraba (0.166189 contra 0.166951). No era un
  bug: con probabilidades continuas hay que agrupar en cajas y aparece el
  residuo intra-caja de Stephenson. Se expone como `residuo_intracaja` en vez
  de esconder la diferencia.

### 10. API

16 endpoints. El patrón: la geometría se pide una vez (87 KB) y las capas
viajan como arrays alineados (4 KB), para que mover la barra de tiempo no
vuelva a bajar el GeoJSON.

**Tropiezo:** con `from __future__ import annotations`, importar los esquemas
pydantic *dentro* de `crear_app()` hace que FastAPI no pueda resolver las
anotaciones (las busca en el scope del módulo) y trate el cuerpo como
parámetro de query: `422 Field required`. Se movieron los imports al módulo.

### 11. Pruebas, y los bugs que encontraron

153 pruebas. Cuatro fallos en la primera corrida completa, con cuatro
diagnósticos distintos:

| Fallo | Qué era |
|---|---|
| `norm_cdf(0) ≠ 0.5` a 1e-9 | prueba demasiado estricta: la erfc de NR da 1e-7. Se ajustó la prueba y se documentó la precisión real |
| error de proyección 0.154% > 0.1% | el docstring prometía más precisión de la que hay. Se corrigió el docstring, tope de la prueba a 0.3% |
| `amenaza_critica` 0.3333 ≠ 1/3 | las métricas se redondean a 4 decimales para JSON. Tolerancia de la prueba a 1e-4 |
| `escurrimiento.min()` es NaN | **bug real**: la convención de qué variables existen sobre el mar no estaba definida ni era consistente |

El cuarto se arregló definiendo la convención explícita (lluvia, temperaturas y
ET0 en todo el dominio; suelo y escurrimiento sólo en tierra, `NaN` en el mar)
y arrastró dos bugs más, que son los peores del día:

1. **El océano salía clasificado como "riesgo muy alto"**, porque
   `np.digitize` manda los `NaN` al último cajón. Se agregó la categoría `-1`
   con etiqueta `"no aplica"`.
2. **La probabilidad en el mar salía 0 en vez de `NaN`**, porque
   `NaN > umbral` es `False`. Un 0 de escurrimiento se pinta igual que "sin
   riesgo": en un mapa de inundación, el océano se habría visto como zona
   segura.

Los dos eran invisibles en los números y sólo se notan en el mapa. Quedó
anotado en grande en [04-api](04-api.md): **`null` no es `0`**.

### 12. Validación

Medido con verdad sintética (un miembro como realidad, climatología de marzo
como referencia):

| Métrica | Valor |
|---|---|
| CRPSS vs. climatología de temporada seca | 0.20 |
| Razón dispersión/error | 1.06 (consistente) |
| BSS para P(lluvia > 20 mm) | **−0.02** |

El BSS negativo se dejó en la documentación en vez de buscar un umbral que
diera bonito. La explicación está en [06-validacion](06-validacion.md): en un
mes homogéneo el modelo asigna probabilidades parecidas a todas las celdas,
así que tiene calibración buena y **resolución pobre**, y sin resolución no hay
skill sobre la tasa base. Es la descomposición de Murphy en acción, y señala
dónde sí está el valor: en el contraste que mete el estado del suelo.

---

## 10-oct-2026 — Sesión 2: de modelo a plataforma de fusión

Encargo: *"¿no puedes hacer que se enriquezca de todos los ángulos, con la
info que proporciona StreetMap, por lo de la NASA y datos recolectados en
bruto? ¿No podrías unir todo eso y hacer más que sólo un modelo predictivo?"*

Sí, y la pieza que lo permite ya estaba hecha: **la malla hexagonal es el
índice espacial común**. Todo lo demás se construyó encima sin tocar el
comportamiento del modelo (las 153 pruebas de la sesión 1 siguieron verdes
todo el tiempo).

### 13. Procedencia antes que datos

Primero el esqueleto: cada capa que entra al sistema trae fuente, nivel
(`observado` / `reanalisis` / `derivado` / `sintetico`), resolución, cadencia,
incertidumbre, licencia y atribución. No es burocracia
([adr/0005](adr/0005-procedencia-pegada-al-dato.md)): sin eso, nuestra
climatología inventada y una observación de NISAR se ven iguales en el mapa, y
la atribución que exige la ODbL de OSM se pierde en la primera
transformación.

### 14. OpenStreetMap, con datos reales

**Tropiezo 1 — el 406.** Overpass rechaza peticiones sin `User-Agent`
reconocible. Con `curl` funcionaba y desde Python no.

**Tropiezo 2 — el diagnóstico engañoso.** Mi cliente agotaba 3 reintentos en
el servidor principal antes de probar el espejo, y sólo reportaba el último
error. El principal daba `504` por tasa y el espejo respondía bien, pero el
mensaje culpaba al espejo. Se rediseñó: **una pasada por todos los espejos
antes de insistir en ninguno**, acumulando los errores de todos.

**Bug conceptual serio.** La primera versión promediaba la impermeabilidad
*sólo entre los puntos con uso de suelo mapeado*. Resultado: una celda rural
con un polígono industrial diminuto salía al **85% de impermeable, con 0
edificios y casi sin vialidad**, por encima del puerto de Veracruz. Lo que se
necesita es la **fracción de área** de toda la celda, no el promedio
condicionado. Corregido, el ranking quedó geográficamente correcto: la celda
más impermeable es `OT0.0.0`, que es el centro del enlace de OSM.

**Problema de cobertura, resuelto sin inventar.** Medido: 5 603 edificios para
una zona metropolitana de ~900 mil habitantes, y 10% del uso de suelo mapeado
en la celda del puerto. Contar edificios daba **1.9%** de ocupación en el
centro de la ciudad, imposible. La vialidad sí está bien mapeada (32 422
vías), así que se agregó un **proxy calibrado por densidad vial**, declarado
como proxy con su incertidumbre, y la impermeabilidad final toma el máximo de
las tres vías. Resultado: puerto 69%, zona urbana 48–65%.

### 15. NASA POWER, y dos sesgos que contradijeron mis supuestos

Decisión: **no usar el endpoint de climatología** (doce medias mensuales no
permiten separar frecuencia de intensidad) sino bajar **21 años de datos
diarios** y calcular aquí las seis series.

| Lo que confirmó | Lo que contradijo |
|---|---|
| acumulado: 1 706 mm/año contra mis 1 656 sintéticos | **195 días de lluvia/año** contra mis 117 |
| patrón estacional jun–oct | el **pico de temperatura está en mayo, no en agosto** |

El primero es el **sesgo de llovizna** de los reanálisis. Se corrigió
calibrando el umbral de día húmedo a 3.7 mm, **sin recortar el acumulado**: la
masa de agua es lo que el reanálisis mide bien, la distribución en días es lo
que se corrige.

El segundo era un error mío: en el trópico húmedo la nubosidad de la temporada
de lluvias baja la máxima, así que el pico es antes. POWER tenía razón.

**Tercer hallazgo.** La forma de Weibull por el método de momentos daba
k = 1.0–1.9, muy por encima del 0.7–0.9 de la literatura. Dos causas: el
truncamiento por el umbral reduce el coeficiente de variación, y MERRA-2
suaviza los máximos. Se cambió a **ajuste por dos cuantiles**, que tiene
solución cerrada y preserva la cola alta —que es la parte con la que se
decide. Bajó a 0.99–1.57; lo que queda es el suavizado del reanálisis, y se
dejó **declarado como sesgo** con su corrección (IMERG).

De ahí salió un patrón que vale la pena: **las fuentes declaran sus propios
sesgos** en un campo `advertencias` que viaja hasta la API.

### 16. El globo sonda

La pieza con más física y el aporte conceptual más grande. Se implementaron
CAPE, CIN, agua precipitable, LCL y los índices K y Total Totals, verificados
contra tablas termodinámicas (es(T) al 0.01 hPa, rocío 13.87 contra 13.9 de
tabla, CAPE de atmósfera isoterma ≈ 0).

Y entran al modelo por el lugar correcto: **la media del campo latente**. Como
`P(lluvia) = Φ(μ − τ)`, ajustar μ desde los índices **es una regresión
probit**. La calibración por máxima verosimilitud está implementada y
verificada en los dos sentidos: recupera coeficientes conocidos a ±0.12 **y no
encuentra señal donde no hay**.

**Dos correcciones al vuelo:**

- El CAPE saturaba μ por sí solo (3 000 J/kg daba z = 3.7). Se normaliza por
  su **raíz**, que es lo físicamente lineal: `w = √(2·CAPE)`.
- Los perfiles irreales pasaban sin aviso. Se agregó `validar_indices()` con
  rangos físicos; un perfil con PWAT de 340 mm queda marcado como no
  confiable y el endpoint de fusión lo **descarta en lugar de usarlo**.

**Dos bugs en el parser de Wyoming**, cazados por los tests: usé mal los
índices de columna (el formato es de 7 caracteres exactos, y DRCT/SKNT están
en 42–49 y 49–56, no donde los puse) y descartaba líneas de sondeos recortados
por un filtro de longitud demasiado estricto.

**Efecto medido:** sin sondeo 73% de días con lluvia y 111 mm en 10 días; con
μ = +1.42, 98% y **361 mm**. Con μ = −1.42, 18% y 10 mm.

### 17. El escurrimiento con impermeabilidad real

Se cambió a área impermeable directamente conectada,
`escurr = imperm·P + (1−imperm)·P·S^β`, retrocompatible (con `imperm = 0` es
el comportamiento anterior).

Primera medición: el efecto era de **+0.6%** en celdas urbanas. Pareció un
bug y no lo era: en septiembre el suelo está saturado y ya escurría el 80%. Al
medir por estado del suelo salió el hallazgo:

| Suelo | Cambio |
|---|---|
| seco (S = 0.15) | **+565%** |
| medio (S = 0.45) | +92% |
| saturado (S = 0.85) | +10% |

**La ciudad amplifica la tormenta sólo cuando el suelo podría absorber.** Y
hay un efecto que suele olvidarse: en zona impermeable el suelo tampoco se
moja (0.72 contra 0.86), porque el agua se va por el drenaje.

### 18. Los productos que no son pronóstico

Con el expediente armado, tres productos más de las mismas capas:

- **exposición** — cruce con OSM: *"733 equipamientos críticos y 5 530
  edificios en 126 celdas"*, y por celda el desglose (`OT0.1.0`: 69 escuelas,
  14 hospitales, 24 universidades). Eso es la diferencia entre un mapa y una
  decisión.
- **aptitud de terreno** — multicriterio con pesos explícitos. La primera
  versión **premiaba las celdas más densas del puerto**, que es justo donde no
  hay terreno que comprar; se agregó el criterio `disponible`. Y lleva
  advertencias en la propia respuesta de la API: no sustituye levantamiento
  topográfico ni mecánica de suelos.
- **ventanas de obra** — siete actividades con sus umbrales y su razón.
  *Montaje con grúa se omite a propósito*: su límite real es el viento a
  altura de pluma y el modelo no genera viento. Se declara y se omite en lugar
  de contestar con datos que no existen.

### 19. Pruebas: 153 → 306

Las nuevas incluyen varias que cazan bugs concretos que ya ocurrieron:

- `test_la_celda_del_puerto_es_la_mas_urbana` falla si la agregación espacial
  se rompe otra vez;
- `test_el_truncamiento_sesga_los_momentos_y_no_los_cuantiles` protege la
  decisión de ajustar la Weibull por cuantiles;
- `test_el_probit_no_encuentra_senal_donde_no_hay` es la mitad que suele
  faltar en una prueba de calibración;
- `test_la_aptitud_advierte_que_no_sustituye_un_topografo` trata la
  advertencia legal como parte del producto.

Las que necesitan red se **saltan** si no hay caché, en lugar de fallar: un CI
sin internet no debería reportar rojo, y pegarle a Overpass en cada corrida
sería abusar de un servicio gratuito.

---

## Pendientes

En orden de lo que más mueve la aguja:

1. **GPM IMERG** — lluvia observada cada 30 min a 11 km. Cierra el hueco de
   validación (hoy las métricas son de consistencia interna) y corrige la cola
   de la Weibull. Requiere cuenta Earthdata.
2. **Gránulos reales de NISAR (GCOV) + SMAP** — humedad de suelo observada.
   Los pasos 4 a 7 de la cadena ya están hechos y probados; faltan descarga y
   *retrieval* ([05-datos-y-nisar](05-datos-y-nisar.md)). SMAP complementa a
   NISAR: uno da cadencia, el otro detalle.
3. **DEM real** (SRTM 30 m) para quitar la elevación sintética y volver
   creíble la pendiente.
4. **Textura de suelo por celda** (INEGI / SoilGrids) — es el error más grande
   de la cadena de asimilación.
5. **Calibrar el probit** con sondeos históricos del SMN y lluvia observada:
   los coeficientes dejan de ser provisionales.
6. **InSAR / GUNW** — la capa de hundimiento, el producto más vendible a
   constructoras y el más defendible técnicamente.
7. **Línea de costa real** de Natural Earth u OSM.
8. **Un caso histórico** con lluvia observada para medir habilidad de verdad.
9. **Frontend** — lo hace otra persona; el contrato está en
   [04-api](04-api.md) y [07-plataforma-de-fusion](07-plataforma-de-fusion.md).

Decisión tomada sobre el globo: **sondeos públicos primero.** El SMN-CNA lanza
dos veces al día y Veracruz es una de las estaciones, con archivo histórico en
NCAR, así que la regresión probit se puede calibrar ya. El globo propio entra
como fuente en vivo y diferenciador, sin bloquear el modelo ni depender de
permisos. El parser acepta los dos formatos, así que el hardware no condiciona
el software. ⚠️ Antes de comprar nada hay que verificar el trámite de la AFAC
para globos libres no tripulados: la normativa específica no apareció buscando
y no hay que inventarla.

## Decisiones que conviene revisar más adelante

- Si se mete un pronóstico determinista (GFS/ECMWF) como media condicionante
  del campo latente, el modelo pasa de climatológico a sinóptico sin cambiar
  la arquitectura. Es la mejora de mayor impacto después de los datos reales.
- La persistencia está repartida entre `φ` del campo y `p01/p11` de la cadena.
  Con datos reales hay que calibrarlas juntas.
- Corridas en memoria con tope de 8: suficiente para la demo, insuficiente si
  queda público.
