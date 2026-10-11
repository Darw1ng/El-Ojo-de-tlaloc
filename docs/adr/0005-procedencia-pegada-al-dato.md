# 0005 — La procedencia viaja pegada al dato

**Fecha:** 10-oct-2026 · **Estado:** aceptada

## Contexto

Al fusionar fuentes, el sistema empieza a mezclar cosas que **no son
equivalentes**: una medición de radar, un reanálisis que es un modelo, un
valor derivado y un placeholder que nos inventamos. Todos salen como un
`float` por celda y en el mapa se ven idénticos.

## Decisión

Ninguna capa entra al sistema sin una `Procedencia`: fuente, nivel
(`observado` / `reanalisis` / `derivado` / `sintetico`), resolución nativa,
cadencia, incertidumbre, licencia, atribución y nota. Y viaja pegada al dato
hasta la respuesta de la API.

Además, las fuentes declaran sus propios sesgos conocidos en un campo
`advertencias`, con el detalle y cómo se corrige cada uno.

## Por qué

Cuatro problemas concretos, no uno estético:

1. **Honestidad.** Nuestra climatología sintética y una observación de NISAR
   no pueden verse iguales. `capas_sinteticas()` es la lista que la interfaz
   tiene que rotular, y el endpoint de asimilación devuelve literalmente
   `"sintetico (no es NISAR)"` cuando el dato es de prueba.
2. **Licencias.** OpenStreetMap es ODbL y exige atribución visible. Si el dato
   no sabe de dónde viene, la atribución se pierde en la primera
   transformación y se incumple la licencia. `atribuciones()` la recupera
   siempre.
3. **Incertidumbre.** El filtro de Kalman necesita la varianza de la
   observación para calcular la ganancia. Si cada fuente la declara, la
   asimilación pondera sola y no hay que cablear constantes.
4. **Reproducibilidad.** Saber qué fuente, con qué resolución y en qué fecha
   produjo un mapa que alguien va a usar para decidir algo.

## Consecuencias

- Hay más código de metadatos que de cálculo en los adaptadores de fuente. Es
  el precio y vale la pena.
- Las respuestas de la API son más grandes. Se compensa separando la geometría
  (una vez) de los valores (por petición).
- Obliga a decidir el nivel de cada capa, y esa decisión es incómoda a
  propósito: clasificar NASA POWER como `reanalisis` y no como `observado`
  es lo correcto —MERRA-2 es un modelo alimentado con observaciones— y
  cambiarlo requeriría justificarlo.
- Se gana algo que no se buscaba: `faltantes()` sale gratis del mismo
  esquema, y es la hoja de ruta del proyecto generada por el propio sistema.
