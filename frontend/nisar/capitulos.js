/* Capitulos de la historia "El baile del agua": temporada de lluvias 2026 en
   Veracruz-Boca del Rio vista por NISAR. Cada capitulo fija camara, capa, fecha,
   grafica y cifras; los numeros salen de datos/meta.json (scripts/nisar_productos.py).
   Texto en espanol e ingles. */
window.CAPITULOS = [
  {
    id: 'intro',
    titulo: { es: 'Una ciudad entre el mar, el río y las lagunas', en: 'A city between the sea, the river and the lagoons' },
    texto: {
      es: '<p>Veracruz y Boca del Río viven rodeados de agua: el Golfo al oriente, el río Jamapa al sur y, hacia el poniente, un sistema de lagunas entre dunas que es sitio Ramsar desde 2005.</p><p>Entre el 25 de junio y el 23 de octubre de 2026, el radar <strong>NISAR</strong> pasó diez veces sobre la zona, siempre a las 5:49 de la mañana. Ve de día o de noche y atraviesa las nubes de la temporada de lluvias. Esta es la temporada contada por esas diez pasadas.</p>',
      en: '<p>Veracruz and Boca del Río live surrounded by water: the Gulf to the east, the Jamapa River to the south and, to the west, a system of lagoons between dunes that has been a Ramsar site since 2005.</p><p>Between June 25 and October 23, 2026, the <strong>NISAR</strong> radar flew over the area ten times, always at 5:49 a.m. It sees day or night and through the clouds of the rainy season. This is the season told by those ten passes.</p>'
    },
    camara: { center: [-96.16, 19.135], zoom: 11.3, pitch: 0, bearing: 0 },
    capa: 'rgb', fecha: 'animar', grafica: null, comparar: null, pois: false, zona: null,
    etiquetas: [
      { lon: -96.128, lat: 19.205, texto: { es: 'Puerto de Veracruz', en: 'Port of Veracruz' } },
      { lon: -96.105, lat: 19.098, texto: { es: 'Boca del Río', en: 'Boca del Río' } },
      { lon: -96.187, lat: 19.145, texto: { es: 'Aeropuerto', en: 'Airport' } }
    ],
    cifras: [
      { valor: 10, unidad: { es: 'pasadas', en: 'passes' }, texto: { es: 'de NISAR en 120 días', en: 'of NISAR in 120 days' } },
      { valor: 10, unidad: { es: 'm', en: 'm' }, texto: { es: 'por píxel, banda L', en: 'per pixel, L-band' } },
      { valor: 750, unidad: { es: 'mm', en: 'mm' }, texto: { es: 'de lluvia en la temporada (NASA POWER)', en: 'of rain in the season (NASA POWER)' } }
    ]
  },
  {
    id: 'oscuro',
    titulo: { es: 'Para el radar, el agua quieta es oscura', en: 'To radar, still water is dark' },
    texto: {
      es: '<p>NISAR no toma fotos: lanza pulsos de microondas y mide cuánto regresa. Una superficie lisa como el agua refleja el pulso lejos del satélite, como un espejo, y por eso el mar se ve negro.</p><p>La ciudad hace lo contrario. Las paredes y el suelo forman esquinas que devuelven la señal casi intacta (<em>doble rebote</em>): los muelles y las calles brillan. Esta capa es <strong>HH</strong>: el radar emite y recibe en polarización horizontal.</p>',
      en: '<p>NISAR does not take photos: it sends microwave pulses and measures how much comes back. A smooth surface like water reflects the pulse away from the satellite, like a mirror, which is why the sea looks black.</p><p>The city does the opposite. Walls and ground form corners that send the signal straight back (<em>double bounce</em>): docks and streets shine. This layer is <strong>HH</strong>: the radar transmits and receives horizontally polarized waves.</p>'
    },
    camara: { center: [-96.138, 19.192], zoom: 13.2, pitch: 0, bearing: 0 },
    capa: 'hh', fecha: 4, grafica: null, comparar: null, pois: false, zona: null,
    etiquetas: [
      { lon: -96.118, lat: 19.208, texto: { es: 'Muelles: doble rebote', en: 'Docks: double bounce' } },
      { lon: -96.105, lat: 19.19, texto: { es: 'Mar: reflexión especular', en: 'Sea: specular reflection' } },
      { lon: -96.0925, lat: 19.1745, texto: { es: 'Isla de Sacrificios', en: 'Sacrificios Island' } }
    ],
    cifras: []
  },
  {
    id: 'verde',
    titulo: { es: 'Lo verde es lo que tiene volumen', en: 'Green is what has volume' },
    texto: {
      es: '<p>Cuando el pulso entra a un follaje, rebota muchas veces entre hojas y tallos y sale con la polarización girada. Esa señal cruzada, <strong>HV</strong>, mide volumen: cañaverales, potreros con árboles, manglar.</p><p>En el compuesto de color, rojo es HH, verde es HV y azul es la diferencia entre ambas. La ciudad sale rosada, el campo verde amarillento y el agua oscura.</p>',
      en: '<p>When the pulse enters foliage it bounces many times between leaves and stems and comes back with its polarization rotated. That cross-polarized signal, <strong>HV</strong>, measures volume: sugarcane, pastures with trees, mangrove.</p><p>In the color composite, red is HH, green is HV and blue is the difference between them. The city comes out pink, the countryside yellow-green and water dark.</p>'
    },
    camara: { center: [-96.2, 19.12], zoom: 12.2, pitch: 30, bearing: -10 },
    capa: 'hv', fecha: 6, grafica: 'polarizaciones', comparar: null, pois: false, zona: null,
    etiquetas: [],
    cifras: []
  },
  {
    id: 'calibrar',
    titulo: { es: 'Antes de comparar, calibrar', en: 'Before comparing, calibrate' },
    texto: {
      es: '<p>Los productos de NISAR de 2026 todavía son provisionales. Al revisar la serie vimos que hasta la ciudad, que no debería cambiar, subía y bajaba cerca de 1 dB entre pasadas.</p><p>Por eso usamos los edificios más brillantes como regla fija: en cada fecha restamos lo que se desvía la ciudad de su promedio. El ajuste fue de <strong>±0.5 dB</strong>. Sin este paso, lo que parecía agua apareciendo y desapareciendo era en realidad un cambio de calibración.</p>',
      en: '<p>NISAR products from 2026 are still provisional. Looking at the series we noticed that even the city, which should not change, went up and down by about 1 dB between passes.</p><p>So we used the brightest buildings as a fixed ruler: on each date we subtract how far the city deviates from its average. The adjustment was <strong>±0.5 dB</strong>. Without this step, what looked like water appearing and disappearing was really a calibration shift.</p>'
    },
    camara: { center: [-96.14, 19.17], zoom: 12.6, pitch: 0, bearing: 0 },
    capa: 'hh', fecha: 6, grafica: 'calibracion', comparar: null, pois: false, zona: null,
    etiquetas: [],
    cifras: [
      { valor: 0.5, unidad: { es: 'dB', en: 'dB' }, texto: { es: 'ajuste máximo por fecha', en: 'largest adjustment per date' } }
    ]
  },
  {
    id: 'respira',
    titulo: { es: 'El suelo respira con la lluvia', en: 'The soil breathes with the rain' },
    texto: {
      es: '<p>El agua cambia la <em>constante dieléctrica</em> del suelo: un campo mojado devuelve más señal que uno seco. Si comparamos cada píxel contra su propia temporada, del día más seco al más húmedo, obtenemos un índice de humedad de 0 a 1.</p><p>El campo se humedece en las pasadas que siguieron a días de lluvia: el 19 de julio y el 17 y 29 de septiembre. La relación con la lluvia de los tres días previos es moderada (<strong>r = 0.36</strong>). Es una sola estación de lluvia de referencia y diez fechas, así que lo leemos como señal, no como prueba.</p>',
      en: '<p>Water changes the soil\'s <em>dielectric constant</em>: a wet field returns more signal than a dry one. Comparing every pixel against its own season, from its driest to its wettest date, gives a moisture index from 0 to 1.</p><p>The countryside gets wetter on the passes that followed rainy days: July 19 and September 17 and 29. The relationship with the previous three days of rain is moderate (<strong>r = 0.36</strong>). It is a single rain reference and ten dates, so we read it as a signal, not as proof.</p>'
    },
    camara: { center: [-96.2, 19.11], zoom: 11.9, pitch: 0, bearing: 0 },
    capa: 'humedad', fecha: 'animar', grafica: 'humedad', comparar: null, pois: false, zona: null,
    etiquetas: [],
    cifras: [
      { valor: 0.59, unidad: { es: '', en: '' }, texto: { es: 'índice medio el 17 de septiembre', en: 'mean index on September 17' } },
      { valor: 0.39, unidad: { es: '', en: '' }, texto: { es: 'índice medio el 12 de agosto', en: 'mean index on August 12' } }
    ]
  },
  {
    id: 'antes-despues',
    titulo: { es: 'Agosto contra septiembre', en: 'August versus September' },
    texto: {
      es: '<p>Desliza para comparar. El 12 de agosto llegó tras tres días con apenas 10 mm de lluvia; el 17 de septiembre, tras cuatro días seguidos de lluvia.</p><p>Esta es la pieza que le falta a cualquier pronóstico de inundación: <strong>60 mm sobre suelo seco se infiltran; 60 mm sobre suelo saturado corren a la calle</strong>. Es la misma lluvia y no es el mismo riesgo.</p>',
      en: '<p>Slide to compare. August 12 came after three days with barely 10 mm of rain; September 17, after four rainy days in a row.</p><p>This is the piece any flood forecast is missing: <strong>60 mm on dry soil soak in; 60 mm on saturated soil run into the street</strong>. Same rain, different risk.</p>'
    },
    camara: { center: [-96.19, 19.115], zoom: 12.4, pitch: 0, bearing: 0 },
    capa: 'humedad', fecha: 6, grafica: null, comparar: [3, 6], pois: false, zona: null,
    etiquetas: [],
    cifras: []
  },
  {
    id: 'lagunas',
    titulo: { es: 'Las lagunas que el radar ve verdes', en: 'The lagoons the radar sees green' },
    texto: {
      es: '<p>El Sistema de Lagunas Interdunarias suma 18 lagunas y 140.6 ha protegidas. En OpenStreetMap están dibujadas 58 lagunas y estanques en la zona, con 127 ha. Para NISAR, <strong>ninguna tiene firma de agua abierta</strong> en la mediana de la temporada: 29 tienen firma de vegetación sobre el agua (HV alto) y 29 son mixtas.</p><p>La banda L penetra el follaje: cuando hay agua debajo de tules o lirio, el pulso rebota entre el agua y los tallos y regresa con fuerza. La laguna de Tarimoya se aclaró <strong>2.3 dB</strong> entre junio y finales de septiembre. Nuestra hipótesis es que subió el agua bajo la vegetación; falta comprobarlo en campo.</p>',
      en: '<p>The Interdune Lagoon System has 18 lagoons and 140.6 protected hectares. OpenStreetMap maps 58 lagoons and ponds in the area, 127 ha in total. To NISAR, <strong>none has an open-water signature</strong> over the season median: 29 show a vegetation-over-water signature (high HV) and 29 are mixed.</p><p>L-band goes through foliage: when there is water under reeds or water hyacinth, the pulse bounces between water and stems and comes back strong. Tarimoya lagoon brightened <strong>2.3 dB</strong> from June to late September. Our hypothesis is that water rose under the vegetation; it still needs field checking.</p>'
    },
    camara: { center: [-96.175, 19.18], zoom: 13.6, pitch: 45, bearing: -20 },
    capa: 'lagunas', fecha: 7, grafica: 'laguna', laguna: 'Laguna de Tarimoya', comparar: null, pois: false, zona: null,
    etiquetas: [
      { lon: -96.1803, lat: 19.1978, texto: { es: 'Laguna de Tarimoya', en: 'Tarimoya lagoon' } },
      { lon: -96.1813, lat: 19.1847, texto: { es: 'Laguna Las Conchas', en: 'Las Conchas lagoon' } }
    ],
    cifras: [
      { valor: 0, unidad: { es: 'de 58', en: 'of 58' }, texto: { es: 'lagunas con firma de agua abierta', en: 'lagoons with an open-water signature' } },
      { valor: 140.6, unidad: { es: 'ha', en: 'ha' }, texto: { es: 'sitio Ramsar 1450', en: 'Ramsar site 1450' } }
    ]
  },
  {
    id: 'mandinga',
    titulo: { es: 'Mandinga: donde el agua sí se mueve', en: 'Mandinga: where the water does move' },
    texto: {
      es: '<p>Al sur de Boca del Río empieza el sistema lagunar de Mandinga. Ahí está casi todo el agua abierta que cambia en la zona: entre <strong>1.0 y 1.45 km²</strong> según la pasada, con 0.5 km² que solo aparecen en algunas fechas, sobre todo en las orillas del humedal de Isla de las Conchas.</p><p>Es un estuario: lo mueven la marea, el viento y lo que baja por el Jamapa. A menos de un kilómetro están fraccionamientos como Real Mandinga y Residencial Puerto Condesa.</p>',
      en: '<p>South of Boca del Río begins the Mandinga lagoon system. Almost all the open water that changes in the area is here: between <strong>1.0 and 1.45 km²</strong> depending on the pass, with 0.5 km² that only shows up on some dates, mostly along the edges of the Isla de las Conchas wetland.</p><p>It is an estuary, moved by tides, wind and what flows down the Jamapa. Less than a kilometer away are housing developments such as Real Mandinga and Residencial Puerto Condesa.</p>'
    },
    camara: { center: [-96.074, 19.045], zoom: 13.6, pitch: 40, bearing: 15 },
    capa: 'agua', fecha: 'animar', grafica: 'agua', comparar: null, pois: false, zona: 'z1',
    etiquetas: [
      { lon: -96.0677, lat: 19.0325, texto: { es: 'Isla de las Conchas', en: 'Isla de las Conchas' } },
      { lon: -96.0731, lat: 19.0486, texto: { es: 'Mandinga y Matoza', en: 'Mandinga y Matoza' } }
    ],
    cifras: [
      { valor: 1.45, unidad: { es: 'km²', en: 'km²' }, texto: { es: 'agua abierta máxima (11 de octubre)', en: 'peak open water (October 11)' } }
    ]
  },
  {
    id: 'estanques',
    titulo: { es: 'El campo guarda agua en charcos y bordos', en: 'The countryside stores water in ponds' },
    texto: {
      es: '<p>Contando cuántas veces aparece agua en cada píxel sale un mapa de permanencia. En azul profundo, lo que siempre es agua; en cian, lo que lo es en parte de la temporada; en amarillo, lo ocasional.</p><p>Al poniente, entre potreros y cañaverales, aparecen bordos y estanques que se llenan y se vacían. En total hay 1.07 km² de agua permanente en tierra, 1.36 km² estacional y 1.47 km² ocasional.</p>',
      en: '<p>Counting how often each pixel is water gives a permanence map. Deep blue is always water; cyan is water for part of the season; yellow is occasional.</p><p>To the west, among pastures and sugarcane, ponds and small reservoirs fill and empty. Overall there are 1.07 km² of permanent inland water, 1.36 km² seasonal and 1.47 km² occasional.</p>'
    },
    camara: { center: [-96.23, 19.1], zoom: 12.7, pitch: 0, bearing: 0 },
    capa: 'frecuencia', fecha: 9, grafica: null, comparar: null, pois: false, zona: null,
    etiquetas: [],
    cifras: [
      { valor: 1.36, unidad: { es: 'km²', en: 'km²' }, texto: { es: 'de agua estacional en tierra', en: 'of seasonal inland water' } }
    ]
  },
  {
    id: 'exposicion',
    titulo: { es: '¿Y las inundaciones en la ciudad?', en: 'And the floods in the city?' },
    texto: {
      es: '<p>Cruzamos el agua temporal con 553 escuelas y universidades, 61 clínicas y hospitales y 22 servicios de emergencia de OpenStreetMap. <strong>Ninguno quedó a menos de 200 m de agua abierta</strong> en las diez pasadas.</p><p>Eso no significa que la ciudad no se inunde. Un encharcamiento urbano dura horas y NISAR pasa cada 12 días a las 5:49 de la mañana. Además, entre edificios el agua se mezcla con el doble rebote. Lo que el radar sí mide bien es la humedad del suelo, y los hexágonos muestran dónde coinciden suelo húmedo y escuelas.</p>',
      en: '<p>We crossed temporary water with 553 schools and universities, 61 clinics and hospitals and 22 emergency services from OpenStreetMap. <strong>None was within 200 m of open water</strong> on any of the ten passes.</p><p>That does not mean the city never floods. Urban flooding lasts hours and NISAR comes by every 12 days at 5:49 a.m. Between buildings, water also blends into the double bounce. What radar does measure well is soil moisture, and the hexagons show where wet soil and schools overlap.</p>'
    },
    camara: { center: [-96.15, 19.15], zoom: 12.1, pitch: 50, bearing: -25 },
    capa: 'hex', fecha: 6, grafica: null, comparar: null, pois: true, zona: null,
    etiquetas: [],
    cifras: [
      { valor: 553, unidad: { es: 'escuelas', en: 'schools' }, texto: { es: 'en la zona conurbada', en: 'in the metro area' } },
      { valor: 0, unidad: { es: 'a ≤200 m', en: 'within 200 m' }, texto: { es: 'de agua abierta temporal', en: 'of temporary open water' } }
    ]
  },
  {
    id: 'hipotesis',
    titulo: { es: 'Lo que creemos que está pasando', en: 'What we think is happening' },
    texto: {
      es: '<p>El mapa de cambio compara cada pasada con la mediana de la temporada. En cian, lo que se oscureció (más liso o con agua); en naranja, lo que se aclaró (suelo mojado, vegetación inundada, cultivos que crecieron).</p><p><strong>1.</strong> La lluvia de los días previos humedece el campo y lo aclara. <strong>2.</strong> Las lagunas interdunarias están cubiertas de vegetación y el agua sube debajo de ella. <strong>3.</strong> Mandinga responde a la marea, al viento y al Jamapa. <strong>4.</strong> Las inundaciones urbanas son más rápidas que la revisita del satélite.</p>',
      en: '<p>The change map compares each pass with the season median. Cyan is what got darker (smoother or flooded); orange is what got brighter (wet soil, flooded vegetation, growing crops).</p><p><strong>1.</strong> Rain in the previous days wets the fields and brightens them. <strong>2.</strong> The interdune lagoons are covered by vegetation and water rises beneath it. <strong>3.</strong> Mandinga responds to tides, wind and the Jamapa. <strong>4.</strong> Urban floods are faster than the satellite\'s revisit.</p>'
    },
    camara: { center: [-96.16, 19.135], zoom: 11.6, pitch: 0, bearing: 0 },
    capa: 'cambio', fecha: 'animar', grafica: null, comparar: null, pois: false, zona: null,
    etiquetas: [],
    cifras: []
  },
  {
    id: 'sigue',
    titulo: { es: 'Del radar al pronóstico', en: 'From radar to forecast' },
    texto: {
      es: '<p>El Ojo de Tláloc ya tiene un modelo que simula cientos de lluvias posibles por hexágono y sabe recibir la humedad del suelo como condición inicial. Con NISAR, ese dato deja de ser un supuesto: cada 12 días el radar dice sobre qué suelo va a caer la siguiente tormenta.</p><p>Lo que sigue: asimilar este índice en el modelo, medir hundimiento del terreno con los interferogramas GUNW que NISAR ya publica para la zona y acumular años de pasadas para separar la temporada normal de una extraordinaria.</p>',
      en: '<p>El Ojo de Tláloc already has a model that simulates hundreds of possible rainfalls per hexagon and can take soil moisture as its initial condition. With NISAR that input stops being an assumption: every 12 days the radar tells us what soil the next storm will fall on.</p><p>Next steps: assimilate this index into the model, measure land subsidence with the GUNW interferograms NISAR already publishes for the area, and build up years of passes to tell a normal season from an extraordinary one.</p>'
    },
    camara: { center: [-96.16, 19.135], zoom: 11.4, pitch: 35, bearing: -15 },
    capa: 'humedad', fecha: 9, grafica: null, comparar: null, pois: false, zona: null,
    etiquetas: [],
    cifras: [
      { valor: 12, unidad: { es: 'días', en: 'days' }, texto: { es: 'entre una medición y la siguiente', en: 'between one measurement and the next' } }
    ]
  }
];
