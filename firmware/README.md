# Firmware del CanSat

Firmware para el CanSat de telemetría que ya voló (Universidad Cristóbal
Colón, 2023), adaptado para que alimente directamente a El Ojo de Tláloc.

## Qué hardware es

Lo que ya existe, según el kit:

| Pieza | Para qué |
|---|---|
| Arduino UNO ×2 | CanSat (emisor) y estación de tierra (receptor) |
| nRF24L01+ PA+LNA 2.4 GHz ×2 | enlace de telemetría |
| BMP180 | presión y temperatura |
| Termistor 47 kΩ + resistor 10 k 1% | temperatura del aire (divisor) |
| AMS1117 3.3 V | alimentación del radio |
| Li-ion 9 V | batería |
| Cilindro PLA 66 × 88 mm | estructura |

## El bug que hay que arreglar primero

En la captura del monitor serial se ve esto:

```
Tbmp180= 28.70 C, Pres= 150.40 KPa, Alt= -3460.00 m.s.n.m.
```

**Esos números son imposibles.** Al nivel del mar la presión es ~101.3 kPa, no
150.4, y la altitud de Veracruz no es −3 460 m. El sensor responde (los
valores cambian en el último dígito), así que no está desconectado: lo que
está mal es **la compensación del BMP180**, que en el código original se
calcula a mano.

El BMP180 no entrega presión directamente: entrega un valor crudo que hay que
compensar con once coeficientes de calibración y una secuencia de operaciones
con enteros muy específica. En esa implementación a mano hay cuatro puntos
donde se rompe, y **cualquiera de ellos explica el síntoma**:

1. **Orden de evaluación no garantizado.** `AC1 = Wire.read()<<8 | Wire.read();`
   El estándar de C++ no define cuál de las dos llamadas se ejecuta primero,
   así que los bytes se pueden leer invertidos y los once coeficientes salen
   basura. Es el error más común en código de Arduino y el sospechoso
   principal.
2. **Desbordamiento de 16 bits.** `AC1*4` con `int AC1` — en AVR `int` son 16
   bits, y si AC1 pasa de 8 191 el producto desborda y se vuelve negativo. La
   fórmula oficial usa `(long)AC1*4`.
3. **`pow()` mezclado con aritmética entera.** `b6*b6/pow(2,12)` hace división
   en punto flotante donde la hoja de datos pide un desplazamiento de bits con
   truncamiento. Los resultados divergen.
4. **Resta sin signo.** `b7 = (UP-b3)*50000` con `UP` sin signo: si `b3` llega
   a superar a `UP`, la resta da la vuelta a un número enorme.

**No vale la pena parchear los cuatro.** La compensación del BMP180 es código
resuelto hace quince años: se usa la librería oficial y desaparece toda esa
clase de error de un golpe. Eso es lo que hace este firmware.

> No pude probarlo en hardware porque no lo tengo enfrente. La aritmética de
> compensación ahora la hace la librería (probada por miles de proyectos) y el
> resto está comentado para que se pueda revisar línea por línea. La
> validación real es conectarlo y ver que la presión dé ~101 kPa y la altitud
> ~0–20 m en Veracruz.

## Lo que falta para que alimente al modelo

El modelo de El Ojo de Tláloc calcula CAPE, agua precipitable, LCL y los
índices de inestabilidad a partir de un perfil vertical. Para eso necesita
tres cosas, y el CanSat actual tiene una y media:

| Variable | ¿La hay? | Sin ella no se puede calcular |
|---|---|---|
| presión | sí (BMP180) | nada |
| temperatura | sí (termistor, que es lo correcto) | nada |
| **humedad** | **no** | **rocío, PWAT, LCL, CAPE, índice K** |
| posición (GPS) | no | georreferenciar y recuperar |

**La humedad es el hueco crítico.** Sin ella el perfil sirve para temperatura
y presión, y nada más: el 80% de lo que el modelo sabe hacer con un perfil
necesita humedad.

### La mejora más barata que existe

Cambiar el **BMP180 por un BME280**. Es el mismo bus I²C, el mismo tamaño,
casi el mismo precio, y añade humedad relativa. Una línea de código distinta y
el CanSat pasa de dar dos variables a dar las tres que el modelo necesita.

Este firmware soporta **los dos sensores**: si encuentra un BME280 lo usa con
humedad, y si no, cae al BMP180 y marca la humedad como no disponible. Así se
puede volar hoy con lo que hay y mejorar después sin tocar nada más.

### Sobre el termistor: está bien puesto

Usar un termistor externo para la temperatura del aire **en lugar** del sensor
interno del barómetro es la decisión correcta, y conviene saber por qué: el
sensor del BMP180 mide la temperatura de su propio encapsulado, que está
caliente por la electrónica de la placa. Para temperatura del aire hay que
tener el sensor afuera y ventilado. Eso ya lo hicieron bien.

## Qué altura alcanza y qué significa

Un cohete de agua con botellas de PET llega a decenas de metros, no a
kilómetros. En términos del modelo eso es un perfil de **capa límite**, y el
sistema lo clasifica solo:

```
GET /api/sondeo  ->  cobertura_vertical.vuelo = "capa limite (globo cautivo)"
```

Con ese alcance **no se puede calcular CAPE** y el backend lo dice en lugar de
entregar un número truncado. Lo que sí sale, y vale:

- perfil de temperatura de los primeros metros (inversiones térmicas)
- presión de referencia en superficie
- con humedad: rocío y LCL, que sí están en capa baja
- el ciclo completo de telemetría probado, que es lo que luego se reusa en un
  vuelo más alto

## Archivos

```
cansat_emisor/cansat_emisor.ino     va en el CanSat
estacion_tierra/estacion_tierra.ino va en la estación de tierra
```

La estación escribe por el puerto serie **exactamente el CSV que el backend ya
sabe leer**, así que la cadena completa es:

```
CanSat → nRF24 → estación de tierra → CSV por serial → POST /api/sondeo
                                                     → índices y μ
                                                     → POST /api/pronostico/fusion
```

## Compilar y cargar

Con `arduino-cli` (se puede hacer desde la terminal, sin abrir el IDE):

```bash
arduino-cli core install arduino:avr
arduino-cli lib install "RF24" "Adafruit BMP085 Library" "Adafruit BME280 Library" "Adafruit Unified Sensor"

arduino-cli compile --fqbn arduino:avr:uno cansat_emisor
arduino-cli upload  --fqbn arduino:avr:uno -p COM3 cansat_emisor

arduino-cli compile --fqbn arduino:avr:uno estacion_tierra
arduino-cli upload  --fqbn arduino:avr:uno -p COM4 estacion_tierra
```

Cambia `COM3`/`COM4` por los puertos que aparezcan en `arduino-cli board list`.

## Prueba antes de volar

1. **Presión en reposo.** En Veracruz debe marcar entre **100 y 103 kPa**, y
   altitud entre **0 y 50 m**. Si sale 150 kPa o altitud negativa, la
   compensación sigue mal.
2. **Termistor.** Debe coincidir con la temperatura del sensor del barómetro
   dentro de ~2 °C en reposo. Si difieren mucho, revisa el divisor y el valor
   de beta.
3. **Alcance del radio.** Prueba el enlace a la distancia máxima esperada
   antes de volar, con las antenas en la orientación que van a tener.
4. **Escaleras.** Sube y baja dos pisos con el CanSat encendido: la altitud
   tiene que moverse unos 3 m por piso. Es la verificación más rápida de que
   el barómetro está bien.
