# Datos: qué es real, qué es sintético y qué lo reemplaza

Este documento existe para que nadie —ni el equipo, ni el jurado— se confunda
sobre qué parte del sistema está alimentada con datos y qué parte está
alimentada con supuestos.

## Tabla de honestidad

| Pieza | Hoy | Con qué se reemplaza | Esfuerzo |
|---|---|---|---|
| Geometría de la malla | **real** (derivada del bbox) | — | — |
| Proyección y distancias | **real** | — | — |
| Normales mensuales de lluvia y temperatura | valores de referencia del puerto de Veracruz, escritos a mano en `climatologia.py` | CHIRPS, ERA5-Land o normales de CONAGUA/SMN | bajo: son 12 listas de números |
| Gradientes espaciales (orografía, costa) | sintéticos, conservadores | DEM real (SRTM 30 m / Copernicus GLO-30) | medio |
| Línea de costa | 3 puntos interpolados | Natural Earth o extracto de OSM | bajo |
| Textura del suelo | una sola (`franco`) para todo | INEGI serie edafológica o SoilGrids | medio |
| Humedad de suelo observada | **sintética** (`observacion_sintetica`) | NISAR GCOV banda L | alto: descarga y preprocesamiento |
| Capacidad de agua del suelo | función de la elevación | tabla por textura y profundidad | bajo |

Las dos filas que importan para el reto son la de humedad de suelo observada
y la de normales. Todo lo demás es andamio.

## Por qué la climatología sintética no es trampa

El modelo estocástico **no depende** de que las normales sean las correctas:
depende de que exista una climatología. `Climatologia.desde_normales()` recibe
las 12 series mensuales y aplica los gradientes; cambiar de datos sintéticos a
datos reales es pasar otras doce listas:

```python
clima = Climatologia.desde_normales(
    malla,
    frac_dias_lluvia=[...],      # 12 valores, de CHIRPS o del SMN
    lluvia_mensual_mm=[...],     # 12 valores
    tmax_mensual=[...],
    tmin_mensual=[...],
    elevacion_m=dem_por_celda,   # del DEM real
)
```

Eso está probado: `test_se_puede_calibrar_con_otras_normales` mete unas
normales de clima seco y verifica que el modelo las reproduce.

Los valores sintéticos **están calibrados contra las normales reales del
puerto** (≈1 656 mm/año, ≈115 días con lluvia, temporada jun–oct), y el modelo
los reproduce al 3% en una celda a nivel del mar. No son números inventados al
azar: son el orden de magnitud correcto de la zona.

El resumen anual que devuelve `GET /api/climatologia?mes=0` incluye un campo
`nota` que declara que la climatología es sintética. **No se quita de la
interfaz.**

## NISAR

### Qué producto se necesita

| Producto | Qué trae | Para qué |
|---|---|---|
| **GCOV** (L2, geocoded covariance) | retrodispersión polarimétrica geocodificada | **humedad de suelo** — es el que se necesita |
| GUNW (L2, unwrapped interferogram) | desplazamiento del terreno, ya desenvuelto | hundimiento, deslizamientos |
| GSLC / RSLC | SLC geocodificado / crudo | procesamiento propio, no hace falta |

Para humedad de suelo el camino es GCOV. Para el otro gancho del reto
(cambio de superficie) el GUNW ya viene desenvuelto, que es lo que evita tener
que hacer *phase unwrapping* —una decisión tomada desde el principio y que
sigue en pie.

### Estado de los datos a octubre de 2026

- Banda L **provisional** disponible desde el 20-jul-2026 (adquisiciones desde
  el 17-jun-2026).
- Lote **beta** de oct-2025 a ene-2026, **sin calibrar**: no sirve para
  humedad.
- Descarga por ASF (Vertex o la librería `asf_search`), requiere cuenta
  Earthdata.
- Banda S sólo por Bhoonidhi (ISRO).

El ciclo de repetición es de **12 días**, y eso marca el diseño: la
asimilación corrige el arranque del pronóstico cada vez que pasa el satélite,
no todos los días.

### El camino de GCOV a saturación relativa

```
1. descarga      asf_search -> granulo GCOV (HDF5) que cubra el bbox
2. recorte       al área de interés
3. retrieval     retrodispersión -> humedad volumétrica θ (m³/m³)
4. agregación    agregar_a_malla(): píxeles -> promedio por hexágono
5. conversión    volumetrica_a_saturacion(θ, textura) -> S en [0,1]
6. asimilación   asimilar() -> estado corregido
7. pronóstico    simular(humedad_inicial=estado corregido)
```

Los pasos 4 a 7 **ya están implementados y probados**. Los pasos 1 a 3 son el
trabajo pendiente, y el 3 es el difícil: pasar de retrodispersión a humedad
necesita corregir por rugosidad y vegetación. Opciones, de menos a más
trabajo:

- usar el producto de humedad de suelo de NISAR cuando esté publicado (es un
  producto de misión, no hay que inventarlo);
- un modelo de cambio temporal (la diferencia de retrodispersión entre dos
  pasadas se relaciona con el cambio de humedad, y así se cancela buena parte
  del efecto de rugosidad);
- ajustar localmente contra estaciones del SMN si hay alguna en el dominio.

### La incertidumbre que se le asigna al dato

`SIGMA_OBS_DEFECTO = 0.13` en saturación relativa. Viene del requisito de
misión de NISAR para humedad de suelo (del orden de 0.06 m³/m³) convertido con
una porosidad típica de 0.45. Es un parámetro de la API (`sigma`), así que se
puede ajustar cuando haya una cifra mejor.

### La trampa de la textura

La conversión de volumétrica a saturación es **la fuente de error más grande
de toda la cadena**. La misma lectura de 0.25 m³/m³ da:

| Textura | Saturación |
|---|---|
| arena | 0.53 |
| franco | 0.49 |
| arcilla | 0.58 |

Usar una textura única para todo el dominio mete un sesgo sistemático que
puede llegar a 0.15 de saturación en suelos muy arenosos o muy arcillosos. Con
el mapa de suelos por celda el sesgo se va. Está probado que la textura cambia
el resultado (`test_la_textura_cambia_el_resultado`), para que nadie asuma que
da igual.

## La observación sintética

Mientras no haya granulos descargados, `observacion_sintetica()` permite
demostrar el ciclo completo. Tiene tres salvaguardas deliberadas:

1. El campo `fuente` dice literalmente `"sintetico (no es NISAR)"`, y la API
   lo devuelve tal cual en el `diagnostico`.
2. No observa el mar (como el radar, que ahí no mide humedad de suelo).
3. Simula los huecos de cobertura (`cobertura=0.85`): agua, vegetación densa y
   sombra de radar dejan celdas sin dato, y el sistema tiene que funcionar con
   huecos. Las celdas sin observación no se tocan
   (`test_las_celdas_sin_observacion_no_se_tocan`).

**Si esto llega a una demo, el rótulo de "sintético" va en la pantalla.**

## Fondo de mapa

El mosaico de OpenStreetMap (`tile.openstreetmap.org`) exige mostrar
`© OpenStreetMap contributors` bajo licencia ODbL. Viene en la respuesta de
`GET /api/area` y no es opcional. Para producción conviene un proveedor de
mosaicos con términos de uso para aplicaciones (el servidor público de OSM
pide no usarlo para tráfico alto).
