/*
 * El Ojo de Tlaloc - estacion de tierra (receptor)
 * NASA Space Apps Challenge 2026
 *
 * Recibe la telemetria del CanSat y la escribe por el puerto serie en el
 * formato CSV que el backend YA sabe leer:
 *
 *     presion_hpa,temp_c,humedad_rel,altura_m
 *
 * Esas son exactamente las columnas que reconoce `leer_csv_globo()` en
 * backend/ojo_tlaloc/fuentes/sondeo.py, asi que la cadena completa queda:
 *
 *     CanSat -> nRF24 -> esta estacion -> CSV -> POST /api/sondeo
 *                                             -> indices (PWAT, LCL, CAPE)
 *                                             -> mu del campo latente
 *                                             -> POST /api/pronostico/fusion
 *
 * Capturar el vuelo a archivo es tan simple como redirigir el puerto serie:
 *
 *     python -m serial.tools.miniterm COM4 115200 > vuelo.csv
 *
 * o con el script que acompana a este firmware.
 */

#include <SPI.h>
#include <RF24.h>

#define PIN_CE   9
#define PIN_CSN 10

const uint8_t CANAL_RF = 76;   // tiene que ser el mismo que el emisor

byte direcciones[][6] = {"1Node", "2Node"};

struct Telemetria {
  float presion_hpa;
  float temp_sensor_c;
  float temp_aire_c;
  float humedad_rel;
  float altitud_m;
  float voltaje_v;
  float segundos;
  uint16_t contador;
  uint8_t banderas;
};

RF24 radio(PIN_CE, PIN_CSN);
Telemetria paquete;

uint16_t recibidos = 0;
uint16_t ultimo_contador = 0;
uint16_t perdidos = 0;
bool primero = true;
unsigned long ultimo_dato_ms = 0;

/*
 * Imprime un float o vacio si es NAN. Dejar la celda VACIA y no un cero es
 * importante: el backend trata la celda vacia como "sin dato" y un cero como
 * una medicion de cero. Confundirlos con la humedad arruinaria el rocio.
 */
void imprimir_valor(float v, uint8_t decimales) {
  if (isnan(v)) return;
  Serial.print(v, decimales);
}

void setup() {
  Serial.begin(115200);

  if (!radio.begin()) {
    Serial.println(F("# ERROR: el nRF24L01 no responde (revisa 3.3V y SPI)"));
  }
  radio.setChannel(CANAL_RF);
  radio.setPALevel(RF24_PA_HIGH);
  radio.setDataRate(RF24_250KBPS);
  radio.setRetries(5, 15);
  radio.openWritingPipe(direcciones[0]);
  radio.openReadingPipe(1, direcciones[1]);
  radio.startListening();

  // Comentarios con '#' para que el CSV siga siendo legible y a la vez
  // documente el vuelo. El lector del backend ignora lo que no parsea.
  Serial.println(F("# El Ojo de Tlaloc - estacion de tierra"));
  Serial.println(F("# columnas compatibles con leer_csv_globo()"));
  Serial.println(F("presion_hpa,temp_c,humedad_rel,altura_m"));
  ultimo_dato_ms = millis();
}

void loop() {
  if (radio.available()) {
    radio.read(&paquete, sizeof(paquete));
    recibidos++;
    ultimo_dato_ms = millis();

    // Cuenta de paquetes perdidos: el contador del emisor es consecutivo, asi
    // que cualquier salto es un paquete que no llego. Saberlo importa porque
    // un perfil con huecos grandes no sirve para integrar CAPE.
    if (!primero) {
      uint16_t salto = paquete.contador - ultimo_contador;
      if (salto > 1) perdidos += (salto - 1);
    }
    primero = false;
    ultimo_contador = paquete.contador;

    /*
     * Se manda la temperatura del TERMISTOR, no la del barometro. El sensor
     * interno del barometro mide su propio encapsulado, calentado por la
     * electronica; el termistor esta afuera y mide el aire. Para un perfil
     * atmosferico la buena es la del termistor.
     */
    float temp = isnan(paquete.temp_aire_c) ? paquete.temp_sensor_c
                                            : paquete.temp_aire_c;

    imprimir_valor(paquete.presion_hpa, 2);
    Serial.print(',');
    imprimir_valor(temp, 2);
    Serial.print(',');
    imprimir_valor(paquete.humedad_rel, 1);
    Serial.print(',');
    imprimir_valor(paquete.altitud_m, 1);
    Serial.println();
  }

  // Aviso de enlace caido, como comentario para no romper el CSV.
  if (millis() - ultimo_dato_ms > 3000) {
    Serial.print(F("# sin senal  recibidos="));
    Serial.print(recibidos);
    Serial.print(F("  perdidos="));
    Serial.println(perdidos);
    ultimo_dato_ms = millis();
  }
}
