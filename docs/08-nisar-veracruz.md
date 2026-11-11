# NISAR sobre la zona conurbada

Este documento cubre la parte del proyecto que contesta el reto tal como está
escrito: **usar datos de NISAR para rastrear y visualizar cambio de
superficie**. El resultado es la historia interactiva de `frontend/nisar/`
(«El baile del agua»), construida con diez pasadas reales del radar sobre
Veracruz y Boca del Río durante la temporada de lluvias de 2026.

## Los datos

| | |
|---|---|
| Producto | NISAR L2 **GCOV** (covarianza geocodificada, retrodispersión γ⁰ con corrección radiométrica de terreno), versión provisional `PR` |
| Pista | 163 ascendente, cuadro 11, modo 4005 (frecuencia A, 40 MHz) |
| Polarizaciones | HH y HV |
| Píxel | 10 m, UTM 15N (EPSG:32615) |
| Fechas | 25 jun, 7 jul, 19 jul, 12 ago, 24 ago, 5 sep, 17 sep, 29 sep, 11 oct y 23 oct de 2026 (falta la del 31 jul) |
| Hora | 11:49 UTC, 05:49 hora local |
| Zona | 19.03–19.24 N, 96.26–96.06 O: Veracruz, Boca del Río, aeropuerto, desembocadura del Jamapa, norte de Mandinga |

Hay más datos sobre la zona que no se usan todavía: otra serie completa en la
pista 084 descendente (10 fechas), la pista 163 en modo 2005 y **36
interferogramas GUNW** para medir deformación. Los identificadores exactos de
los gránulos usados están en `frontend/nisar/datos/meta.json`.

## Cómo se bajan sin bajar 47 GB

Cada gránulo GCOV pesa unos 4.8 GB y cubre más de 200 km. La zona conurbada son
2 148 × 2 365 píxeles de ese archivo. `scripts/nisar_gcov.py` abre el HDF5
remoto con `earthaccess` y lee **sólo la ventana** de la zona (el archivo está
en bloques de 512 × 512), así que las diez fechas salen en unos ocho minutos.

```bash
cd backend && pip install -r ../scripts/requirements-nisar.txt
export EARTHDATA_TOKEN=...            # urs.earthdata.nasa.gov → Generate Token
python ../scripts/nisar_gcov.py buscar           # catálogo de ASF, sin cuenta
python ../scripts/nisar_gcov.py vista            # vistas previas públicas, sin cuenta
python ../scripts/nisar_gcov.py extraer --pista 163A011 --modo 4005
python ../scripts/nisar_productos.py             # todo lo que usa la historia
python ../scripts/nisar_assets.py                # time-lapse, GIF y portadas
```

Las salidas crudas (GeoTIFF por fecha con HH y HV en γ⁰ lineal) van a
`datos/salida/nisar/`, que no se versiona. Lo que consume la web va a
`frontend/nisar/datos/`.

## El procesamiento, paso por paso

1. **Moteado.** Filtro de Lee de 5 × 5 en intensidad lineal, por fecha y por
   polarización.
2. **Calibración relativa.** Los productos de 2026 son provisionales y la
   serie lo delató: los blancos urbanos más brillantes (mediana HH > −2 dB),
   que no deberían cambiar, oscilaban ~1 dB entre pasadas con el mismo patrón
   que el campo. Se normaliza cada fecha restando la desviación de esos
   blancos respecto a su promedio. Ajustes: +0.48, −0.38, +0.07, −0.32,
   +0.30, −0.48, +0.52, +0.37, −0.14, −0.42 dB.
3. **Agua abierta.** Umbral en el **valle del histograma** de la serie:
   HH < −14.8 dB y HV < −19.8 dB. Otsu daba −11.3 dB y metía campos lisos y
   secos como agua; se notaba porque «el agua» bajaba cuando llovía (el suelo
   mojado brilla más). Limpieza morfológica de objetos de menos de 3 000 m².
4. **Mar, playa y pistas.** El mar es la región oscura conectada al borde
   oriental; se excluye además una franja de 150 m de playa (arena mojada y
   rompiente) y las pistas del aeropuerto de OSM con 100 m de margen.
5. **Permanencia.** Fracción de fechas con agua por píxel: permanente ≥ 0.8,
   estacional 0.2–0.8, ocasional < 0.2.
6. **Cambio.** Diferencia en dB de cada fecha contra la mediana de la
   temporada. Oscurecer es agua o superficie más lisa; aclarar es suelo más
   húmedo, vegetación inundada o cultivo que creció.
7. **Humedad del suelo por detección de cambio.** Para cada píxel de suelo
   (sin ciudad, sin agua): `(HH − 2.º mínimo) / (2.º máximo − 2.º mínimo)` de
   su propia serie, suavizado a 90 m. Es un índice **relativo** de 0 a 1, de
   la familia del método de TU Wien, no humedad volumétrica.
8. **Lagunas.** Para cada laguna, estanque o humedal de OSM, mediana de HH y
   HV por fecha y una firma: agua abierta si HH queda bajo el umbral de agua,
   vegetación sobre agua si HV > −17 dB, mixta en otro caso.
9. **Exposición.** Escuelas, clínicas y servicios de emergencia de OSM a
   200 m o menos de agua temporal, y agregación de todo a la malla hexagonal
   del proyecto (nivel 2, hexágonos de 1.44 km).
10. **Lluvia.** NASA POWER diario (`PRECTOTCORR`) en 19.15 N, 96.15 O, con
    acumulados de 3 y 7 días antes de cada pasada.

## Lo que salió

| | |
|---|---|
| Agua abierta en tierra por fecha | 1.09 a 2.16 km² |
| Agua permanente / estacional / ocasional | 1.07 / 1.36 / 1.47 km² |
| Zona donde más cambia el agua | norte del sistema lagunar de Mandinga: 1.0 a 1.45 km² |
| Índice de humedad medio | de 0.39 (12 ago) a 0.59 (17 sep) |
| Correlación humedad vs. lluvia de 3 días | r = 0.36 |
| Lagunas de OSM con firma de agua abierta | 0 de 58 (29 vegetación sobre agua, 29 mixtas) |
| Laguna de Tarimoya | se aclara 2.3 dB de junio a finales de septiembre |
| Escuelas / salud / emergencia a ≤ 200 m de agua temporal | 0 / 0 / 0 (de 553 / 61 / 22) |

## Lo que no se puede afirmar

- **Calibración.** La normalización contra la ciudad corrige el desfase entre
  fechas pero también borra cualquier señal que afecte a toda la escena por
  igual, incluida una humedad general real.
- **Lluvia.** Es un solo punto de NASA POWER con resolución de medio grado.
  Por eso la correlación de 0.36 se lee como señal y no como prueba; con GPM
  IMERG de media hora (ya hay credenciales) se puede afinar.
- **Humedad.** El índice es relativo a la propia temporada de cada píxel. No
  dice cuántos m³/m³ hay; para eso hace falta la textura del suelo y
  validación en campo.
- **Lagunas con vegetación.** La firma es consistente con tule o lirio sobre
  el agua, pero es una hipótesis hasta verlo en campo.
- **Inundación urbana.** Diez fechas a las 5:49 con revisita de 12 días no
  captan encharcamientos que duran horas, y entre edificios el agua se mezcla
  con el doble rebote. El cero de exposición dice eso, no que la ciudad no se
  inunde.

## Cómo se conecta con el resto del proyecto

El índice de humedad por hexágono (`hex.geojson`, campo `humedad_idx`) es la
condición inicial que `asimilacion.py` esperaba de NISAR y que hasta ahora era
sintética. Lo siguiente es convertirlo a saturación con la textura de suelo
por celda y asimilarlo con el filtro de Kalman de ensamble que ya existe.
