/*
 * El Ojo de Tlaloc - CanSat (emisor)
 * NASA Space Apps Challenge 2026
 *
 * Lee presion, temperatura y (si hay sensor) humedad, y los manda por
 * nRF24L01 a la estacion de tierra.
 *
 * QUE CAMBIA RESPECTO AL CODIGO ORIGINAL
 * --------------------------------------
 * La compensacion del BMP180 ya no se calcula a mano. En el monitor serial
 * del vuelo anterior se veia "Pres= 150.40 KPa, Alt= -3460.00 m.s.n.m.", que
 * es imposible: al nivel del mar son ~101.3 kPa. El sensor respondia, lo que
 * fallaba era la aritmetica de compensacion, que tenia cuatro problemas
 * clasicos (ver firmware/README.md). Ahora la hace la libreria oficial.
 *
 * Tambien soporta BME280 ademas de BMP180. Esa es la mejora mas barata del
 * proyecto: mismo bus, mismo tamano, casi el mismo precio, y agrega HUMEDAD.
 * Sin humedad no hay rocio, ni agua precipitable, ni LCL, ni CAPE, o sea el
 * 80% de lo que el modelo sabe hacer con un perfil vertical.
 *
 * CONEXIONES
 *   BMP180 / BME280 (I2C)   SDA -> A4,  SCL -> A5,  VCC -> 3.3V
 *   Termistor 47k           A0, con resistor de 10k 1% a GND (divisor)
 *   Medicion de bateria     A1
 *   nRF24L01+               CE -> D9, CSN -> D10, SCK -> D13,
 *                           MOSI -> D11, MISO -> D12, VCC -> 3.3V
 *
 * El nRF24L01+PA+LNA necesita 3.3 V con buena corriente de pico: el AMS1117
 * del kit sirve, pero hay que ponerle un capacitor de 10 uF lo mas cerca
 * posible del modulo o el radio se reinicia al transmitir.
 */

#include <SPI.h>
#include <Wire.h>
#include <RF24.h>
#include <Adafruit_BMP085.h>
#include <Adafruit_BME280.h>

// --- configuracion ---------------------------------------------------------

#define PIN_CE            9
#define PIN_CSN          10
#define PIN_TERMISTOR    A0
#define PIN_BATERIA      A1

// Divisor del termistor: 47k NTC arriba, 10k al 1% abajo.
const float TERMISTOR_R_NOMINAL   = 47000.0;  // ohms a 25 C
const float TERMISTOR_T_NOMINAL   = 25.0;     // grados C
const float TERMISTOR_BETA        = 4090.0;   // coeficiente beta del kit
const float TERMISTOR_R_SERIE     = 10000.0;  // el resistor de 10k 1%

// Divisor para medir la bateria de 9 V hacia un ADC de 5 V.
// Si no hay divisor, deja FACTOR en 1.0 y no conectes 9 V al ADC: lo quema.
const float BATERIA_FACTOR        = 1.0;

const uint8_t  CANAL_RF           = 76;       // lejos del wifi de 2.4 GHz
const float    PRESION_NIVEL_MAR  = 1013.25;  // hPa, referencia de altitud

/*
 * MUESTREO ADAPTATIVO
 *
 * Todavia no esta decidido que va a sostener la capsula ni cuanto tiempo
 * tiene que aguantar. En vez de elegir un periodo fijo y equivocarse, el
 * firmware mira si la presion esta cambiando y se ajusta solo:
 *
 *   se esta MOVIENDO (sube o baja)  -> muestreo rapido: es un PERFIL y cada
 *                                      muestra es una altura distinta, asi
 *                                      que aqui es donde hay que gastar
 *                                      bateria y ancho de banda
 *   esta QUIETO a altura fija       -> muestreo lento: es una serie en el
 *                                      tiempo, y 10 muestras por segundo del
 *                                      mismo punto no agregan informacion,
 *                                      solo vacian la pila
 *
 * Con esto el mismo codigo sirve para globo cautivo, globo libre, dron o
 * cohete con paracaidas, y en todos aprovecha la bateria donde importa.
 * El umbral son 0.08 hPa entre muestras, que a nivel del mar es menos de un
 * metro: suficiente para distinguir movimiento real del ruido del sensor.
 */
const unsigned long PERIODO_RAPIDO_MS = 250;   // ascenso o descenso
const unsigned long PERIODO_LENTO_MS  = 2000;  // estacionario
const float UMBRAL_MOVIMIENTO_HPA     = 0.08;
const uint8_t MUESTRAS_PARA_QUIETO    = 8;     // seguidas sin moverse

byte direcciones[][6] = {"1Node", "2Node"};

// --- estado ---------------------------------------------------------------

RF24 radio(PIN_CE, PIN_CSN);
Adafruit_BMP085 bmp180;
Adafruit_BME280 bme280;

bool hay_bme280 = false;
bool hay_bmp180 = false;

/*
 * Paquete de telemetria. El nRF24L01 manda hasta 32 bytes por paquete:
 * 7 floats = 28 bytes, mas 2 de contador y 1 de banderas = 31. Cabe justo.
 *
 * Mandar humedad como NAN cuando no hay sensor es deliberado: asi la estacion
 * de tierra distingue "no hay dato" de "humedad cero", que son cosas muy
 * distintas y confundirlas arruinaria el calculo de rocio.
 */
struct Telemetria {
  float presion_hpa;
  float temp_sensor_c;    // del barometro (mide su propio encapsulado)
  float temp_aire_c;      // del termistor externo: esta es la buena
  float humedad_rel;      // NAN si no hay BME280
  float altitud_m;
  float voltaje_v;
  float segundos;
  uint16_t contador;
  uint8_t banderas;       // b0 humedad, b1 barometro, b2 en movimiento
};

Telemetria paquete;
uint16_t contador = 0;

// Estado del muestreo adaptativo.
float presion_anterior = NAN;
uint8_t muestras_quieto = 0;
bool en_movimiento = true;    // se arranca rapido hasta saber que pasa
unsigned long periodo_ms = PERIODO_RAPIDO_MS;

// --- sensores --------------------------------------------------------------

void actualizar_ritmo();   // prototipo: se usa antes de definirse

/*
 * Temperatura del termistor por la ecuacion beta.
 *
 *   1/T = 1/T0 + (1/beta) ln(R/R0)
 *
 * El divisor tiene el NTC arriba y el resistor fijo abajo, asi que la
 * resistencia del NTC se despeja de la lectura del ADC.
 */
float leer_termistor() {
  int lectura = analogRead(PIN_TERMISTOR);
  if (lectura <= 0 || lectura >= 1023) {
    return NAN;   // divisor abierto o en corto: mejor nada que un numero falso
  }
  float r_ntc = TERMISTOR_R_SERIE * (1023.0 / (float)lectura - 1.0);
  float inv_t = 1.0 / (TERMISTOR_T_NOMINAL + 273.15)
              + (1.0 / TERMISTOR_BETA) * log(r_ntc / TERMISTOR_R_NOMINAL);
  return 1.0 / inv_t - 273.15;
}

float leer_bateria() {
  return (analogRead(PIN_BATERIA) / 1023.0) * 5.0 * BATERIA_FACTOR;
}

void iniciar_sensores() {
  Wire.begin();
  // Se intenta primero el BME280, que es el que trae humedad.
  if (bme280.begin(0x76) || bme280.begin(0x77)) {
    hay_bme280 = true;
    // Modo de muestreo continuo y filtro, que es lo adecuado en vuelo.
    bme280.setSampling(Adafruit_BME280::MODE_NORMAL,
                       Adafruit_BME280::SAMPLING_X2,   // temperatura
                       Adafruit_BME280::SAMPLING_X16,  // presion
                       Adafruit_BME280::SAMPLING_X1,   // humedad
                       Adafruit_BME280::FILTER_X4,
                       Adafruit_BME280::STANDBY_MS_0_5);
  } else if (bmp180.begin()) {
    hay_bmp180 = true;
  }
}

void leer_sensores() {
  paquete.banderas = 0;
  paquete.humedad_rel = NAN;

  if (hay_bme280) {
    paquete.presion_hpa   = bme280.readPressure() / 100.0;   // Pa -> hPa
    paquete.temp_sensor_c = bme280.readTemperature();
    paquete.humedad_rel   = bme280.readHumidity();
    paquete.banderas |= 0x01;   // hay humedad
    paquete.banderas |= 0x02;   // barometro vivo
  } else if (hay_bmp180) {
    paquete.presion_hpa   = bmp180.readPressure() / 100.0;
    paquete.temp_sensor_c = bmp180.readTemperature();
    paquete.banderas |= 0x02;
  } else {
    paquete.presion_hpa   = NAN;
    paquete.temp_sensor_c = NAN;
  }

  /*
   * Altitud barometrica por la formula de la atmosfera estandar. No es la
   * altura real sobre el terreno: es la que corresponde a esa presion
   * suponiendo atmosfera estandar, y cambia con el clima. Para medir cuanto
   * SUBIO el cohete, lo correcto es restar la altitud del momento del
   * despegue, no leer este numero en absoluto.
   */
  if (!isnan(paquete.presion_hpa)) {
    paquete.altitud_m = 44330.0
        * (1.0 - pow(paquete.presion_hpa / PRESION_NIVEL_MAR, 0.1903));
  } else {
    paquete.altitud_m = NAN;
  }

  paquete.temp_aire_c = leer_termistor();
  paquete.voltaje_v   = leer_bateria();
  paquete.segundos    = millis() / 1000.0;
  paquete.contador    = contador++;

  actualizar_ritmo();
  if (en_movimiento) paquete.banderas |= 0x04;
}

/*
 * Decide si la capsula se esta moviendo en la vertical y ajusta el ritmo.
 *
 * Se exigen varias muestras seguidas sin movimiento antes de bajar el ritmo,
 * para que una racha de viento o un poco de ruido no lo haga oscilar. En
 * cambio basta UNA muestra con movimiento para volver al ritmo rapido: es
 * mejor desperdiciar unas muestras que perderse el unico ascenso del vuelo.
 */
void actualizar_ritmo() {
  if (isnan(paquete.presion_hpa)) return;

  if (!isnan(presion_anterior)) {
    float cambio = fabs(paquete.presion_hpa - presion_anterior);
    if (cambio >= UMBRAL_MOVIMIENTO_HPA) {
      muestras_quieto = 0;
      en_movimiento = true;
    } else if (muestras_quieto < 255) {
      muestras_quieto++;
    }
    if (muestras_quieto >= MUESTRAS_PARA_QUIETO) {
      en_movimiento = false;
    }
  }
  presion_anterior = paquete.presion_hpa;
  periodo_ms = en_movimiento ? PERIODO_RAPIDO_MS : PERIODO_LENTO_MS;
}

// --- programa --------------------------------------------------------------

void setup() {
  Serial.begin(115200);
  Serial.println(F("# El Ojo de Tlaloc - CanSat emisor"));

  iniciar_sensores();
  if (hay_bme280) {
    Serial.println(F("# sensor: BME280 (presion + temperatura + HUMEDAD)"));
  } else if (hay_bmp180) {
    Serial.println(F("# sensor: BMP180 (presion + temperatura, SIN humedad)"));
    Serial.println(F("# sin humedad no hay rocio, PWAT, LCL ni CAPE"));
  } else {
    Serial.println(F("# ERROR: no se detecto barometro en el bus I2C"));
  }

  if (!radio.begin()) {
    Serial.println(F("# ERROR: el nRF24L01 no responde (revisa 3.3V y SPI)"));
  }
  radio.setChannel(CANAL_RF);
  radio.setPALevel(RF24_PA_HIGH);
  radio.setDataRate(RF24_250KBPS);   // menos velocidad, mas alcance
  radio.setRetries(5, 15);
  radio.openWritingPipe(direcciones[1]);
  radio.openReadingPipe(1, direcciones[0]);
  radio.stopListening();
}

void loop() {
  static unsigned long anterior = 0;
  unsigned long ahora = millis();
  if (ahora - anterior < periodo_ms) {
    return;
  }
  anterior = ahora;

  leer_sensores();
  bool enviado = radio.write(&paquete, sizeof(paquete));

  /*
   * Se imprime tambien por el puerto serie del CanSat. Si el radio falla en
   * vuelo, al recuperar la capsula todavia se puede revisar que el firmware
   * estaba leyendo bien. Para registro de verdad hace falta tarjeta SD.
   */
  Serial.print(paquete.contador);
  Serial.print(F(" p=")); Serial.print(paquete.presion_hpa, 2);
  Serial.print(F(" hPa  tAire=")); Serial.print(paquete.temp_aire_c, 2);
  Serial.print(F(" C  hr="));
  if (isnan(paquete.humedad_rel)) Serial.print(F("--"));
  else Serial.print(paquete.humedad_rel, 1);
  Serial.print(F("  alt=")); Serial.print(paquete.altitud_m, 1);
  Serial.print(F(" m  ")); Serial.print(en_movimiento ? F("[mov]") : F("[fijo]"));
  Serial.print(F("  bat=")); Serial.print(paquete.voltaje_v, 2);
  Serial.print(F(" V  rf=")); Serial.println(enviado ? F("ok") : F("FALLO"));
}
