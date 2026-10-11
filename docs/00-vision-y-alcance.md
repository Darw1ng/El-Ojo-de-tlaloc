# Visión y alcance

## El reto, textual

> *Earth's surface is an endless dance of natural processes and human
> activities, but these changes are often difficult to visualize, understand,
> and communicate. (…) Your challenge is to build an interactive application
> that uses radar remote sensing data from the NASA-ISRO Synthetic Aperture
> Radar (NISAR) mission to track and visualize one or more types of surface
> change at locations around the world.*
>
> — [Dancing with the SARs](https://www.spaceappschallenge.org/2026/challenges/dancing-with-the-sars/), dificultad Advanced/Intermediate, Earth Science

Lo que pide el reto es **una aplicación interactiva que rastree y visualice
cambio de superficie usando NISAR**. El enunciado completo con datasets sale
el 28-oct-2026; esto se construyó con el resumen.

## Nuestra lectura

Casi cualquier equipo va a hacer un visor de cambio de superficie: un
"antes y después" con datos de radar. Es lo que pide el reto y está bien.

Nuestra apuesta es pasar de **observar el cambio** a **anticipar sus
consecuencias**, y el puente es una sola idea física:

> 60 mm de lluvia sobre suelo seco se infiltran.
> 60 mm de lluvia sobre suelo saturado corren al río.
> Es la misma lluvia y no es el mismo riesgo.

NISAR no mide la lluvia de mañana. Mide el estado de la superficie hoy —entre
otras cosas la humedad del suelo, con banda L, cada 12 días, de día o de noche
y atravesando las nubes— y ese estado es exactamente la condición inicial que
le falta a cualquier pronóstico de inundación.

Así que el sistema tiene dos mitades que se necesitan:

1. un **modelo estocástico** que propone cientos de trayectorias posibles de
   lluvia y temperatura, espacialmente coherentes, y
2. la **asimilación del radar**, que corrige sobre qué suelo van a caer.

La salida no es un número, es una probabilidad por hexágono. Eso es lo que
permite decidir algo.

## Alcance

### Dentro

- Malla hexagonal a escala 1:16 sobre el área de interés, con niveles de
  acercamiento.
- Generador estocástico de lluvia, temperatura, evapotranspiración, humedad de
  suelo y escurrimiento, con ensamble Monte Carlo.
- Asimilación de humedad de suelo por filtro de Kalman de ensamble.
- Capas de probabilidad y de alerta por escurrimiento acumulado.
- Métricas de verificación probabilística.
- API HTTP con contrato estable para el frontend.

### Fuera, y a propósito

- **Modelo numérico de la atmósfera.** No se resuelven ecuaciones de fluidos.
  Ver [adr/0001](adr/0001-generador-estocastico-vs-modelo-numerico.md).
- **Phase unwrapping de interferogramas.** Si se usa deformación del terreno,
  se consume el producto GUNW de nivel 2 que ya viene desenvuelto.
- **Enrutamiento hidrológico.** El escurrimiento es puntual por celda; no se
  transporta agua de una celda a otra. Pasar de "escurre mucho aquí" a "el río
  sube tanto allá" necesita un modelo de cuenca con DEM y aforos.
- **Pronóstico operativo.** Esto no compite con el Servicio Meteorológico
  Nacional ni pretende sustituir un aviso oficial.
- **Frontend.** Lo hace otra persona del equipo.

## Por qué Veracruz central

El área sale del enlace que define el proyecto
([OSM 11/19.1704/-96.1654](https://www.openstreetmap.org/#map=11/19.1704/-96.1654)),
y resulta ser un buen caso:

- **El problema es real.** El puerto de Veracruz y Boca del Río se inundan con
  lluvia intensa; la cuenca baja del Jamapa y del río La Antigua desborda.
- **Hay contraste en 90 km:** mancha urbana impermeable, zona agrícola,
  humedal y planicie costera. Celdas que reciben la misma lluvia y responden
  distinto, que es justo lo que el modelo puede mostrar.
- **Es temporada.** Junio a octubre concentra el 80% de los 1 650 mm anuales.
- **El radar aporta donde el óptico no.** En temporada de lluvias hay nubes
  casi permanentes; un sensor óptico no ve el suelo y el radar sí.

## Criterio de éxito

Que se pueda contestar, señalando un hexágono:

1. ¿Qué probabilidad hay de que aquí pase de 50 mm el jueves?
2. ¿Qué tan seguro está el modelo, y por qué?
3. ¿Qué cambia si el radar dice que el suelo ya está saturado?
4. ¿Qué tan bueno es este pronóstico, con un número?

Las cuatro tienen respuesta hoy en la API. La cuarta tiene la respuesta
incómoda incluida, que está en [06-validacion](06-validacion.md).
