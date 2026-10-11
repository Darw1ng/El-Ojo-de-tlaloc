# Validación

Un pronóstico probabilístico no se evalúa con error medio absoluto. Si el
modelo dice "60% de probabilidad de lluvia" y llueve, no acertó ni falló: hay
que medir, sobre muchos casos, si de los días a los que les puso 60% llovió en
el 60%.

Este documento tiene los números **medidos**, incluidos los que salen flojos.

## Qué se puede validar hoy y qué no

| Pregunta | Se puede responder | Con qué |
|---|---|---|
| ¿El modelo reproduce la climatología que se le dio? | **sí** | acumulados y frecuencias contra las normales |
| ¿Es espacialmente coherente? | **sí** | correlación vecinos vs. lejanos |
| ¿Tiene rachas, no días independientes? | **sí** | P(llueve hoy \| llovió ayer) |
| ¿Está bien dispersado? | **sí** | razón dispersión/error |
| ¿Le gana a la climatología? | **parcialmente** | CRPSS con verdad sintética |
| ¿Acierta el clima de verdad? | **no todavía** | hace falta una serie observada |

La última fila es la honesta: sin observaciones reales no se puede afirmar
habilidad de pronóstico. Las métricas están construidas y probadas para que el
día que haya una serie observada sea cuestión de pasarla, no de escribir
código.

## Consistencia interna del modelo

### Reproduce la climatología

Celda a nivel del mar, acumulado mensual simulado contra la normal de entrada:

| | Normal | Modelo |
|---|---|---|
| Septiembre | 350 mm | 350.1 mm |
| Anual | 1 656 mm | 1 656.6 mm |

Con 200 miembros × 30 días en septiembre el acumulado simulado queda **+5%**
sobre el objetivo (369 contra 350), por el condicionamiento de Markov
combinado con la cópula. Es una dirección conservadora para una alerta y está
dentro de la tolerancia de las pruebas.

La calibración de la cadena de Markov es **exacta**: la distribución
estacionaria coincide con la probabilidad objetivo con error < 1e-12 para los
12 meses y las 221 celdas.

### Frecuencia de días con lluvia

| | Septiembre |
|---|---|
| Objetivo climatológico (π) | 0.67 |
| Modelo, lluvia > 0 mm | 0.64 |
| Modelo, lluvia ≥ 1 mm | 0.58 |

La brecha del ≥ 1 mm es el **límite documentado** de calibrar la Weibull por
acumulado: con forma 0.8, ~10% de los días húmedos caen por debajo de 1 mm.
Se eligió cuadrar el acumulado porque es lo que manda en inundación.

### Coherencia espacial

Correlación de la lluvia diaria entre celdas, 20 días × 100 miembros:

| Separación | Correlación |
|---|---|
| Vecinas (5.8 km) | **0.75** |
| Lejanas (> 60 km) | **0.04** |

Esto es lo que aporta el campo latente gaussiano. Sin él, la lluvia sería
ruido blanco celda por celda y el mapa no se parecería a una tormenta. La
prueba `test_coherencia_espacial_vecinos_contra_lejanos` exige > 0.5 para
vecinas y < 0.2 para lejanas.

### Persistencia

`P(llueve hoy | llovió ayer)` supera la probabilidad marginal por más de 0.05,
o sea hay rachas. Probado en
`test_hay_rachas_de_lluvia_no_dias_independientes`.

### La incertidumbre crece con el horizonte

La dispersión del ensamble sobre la lluvia acumulada es monótona creciente a
lo largo de 12 días. Un pronóstico que no se vuelve más incierto con el
horizonte está mintiendo; la prueba
`test_la_dispersion_del_ensamble_crece_con_el_horizonte` lo verifica.

## Métricas probabilísticas

Prueba de consistencia interna: se toma un miembro del ensamble como "la
realidad" y se verifica el resto contra él, con la climatología de marzo (mes
seco) como pronóstico de referencia.

| Métrica | Valor | Lectura |
|---|---|---|
| **CRPSS** vs. climatología de temporada seca | **0.20** | el modelo distingue septiembre de marzo |
| **Razón dispersión/error** | **1.06** | dispersión consistente con el error |
| **BSS** para P(lluvia > 20 mm) | **−0.02** | ver abajo |

### El número flojo, y por qué está aquí

El **BSS negativo** para el umbral de 20 mm no es un error de
implementación: es un diagnóstico correcto y vale más que esconderlo.

El Brier Skill Score mide habilidad contra "decir siempre la frecuencia
histórica". En esta prueba, todas las celdas de tierra en septiembre están en
condiciones parecidas, así que el modelo les asigna probabilidades muy
similares (entre 0.18 y 0.25 según el diagrama de confiabilidad). Un
pronóstico que siempre dice casi lo mismo tiene **resolución** cercana a cero,
y sin resolución no hay skill sobre la tasa base, aunque la calibración sea
perfecta.

Es la descomposición de Murphy en acción: `BS = fiabilidad − resolución +
incertidumbre`. Aquí la fiabilidad es buena y la resolución es pobre.

Qué significa en la práctica: **el valor del sistema no está en el día a día
de un mes homogéneo**, está en (a) distinguir situaciones con contraste
espacial o temporal real, y (b) la capa de escurrimiento, donde el estado del
suelo sí separa celdas que reciben la misma lluvia. Ese es exactamente el
argumento de la asimilación de NISAR.

### Confiabilidad medida

| Probabilidad pronosticada | Frecuencia observada | Casos |
|---|---|---|
| 0.18 | 0.29 | 207 |
| 0.23 | 0.19 | 667 |

Pocas cajas pobladas, otra vez por la falta de dispersión en las
probabilidades. Con una serie observada y varios meses, este diagrama es lo
primero que hay que mirar.

## Las métricas implementadas

Todas en `metricas.py`, todas verificadas contra algo independiente:

| Función | Verificación |
|---|---|
| `crps` | valor analítico de la normal (0.23369) y degeneración a \|x−y\| con 1 miembro |
| `crpss` | ~0 cuando el pronóstico es la referencia, > 0.5 cuando es mejor |
| `brier` | valores a mano |
| `brier_skill` | > 0.25 con un pronóstico calibrado, cae con uno exagerado |
| `confiabilidad` | un pronóstico calibrado cae sobre la diagonal a < 0.03 |
| `descomposicion_brier` | la identidad de Murphy cierra con el residuo intra-caja |
| `dispersion_vs_error` | detecta sub y sobre-dispersión construidas a propósito |
| `tabla_contingencia` | conteos a mano; subir el corte baja la detección |

Dos detalles de rigor que vale la pena conocer:

- **CRPS justo.** El estimador clásico divide la suma de pares entre `m²`, que
  incluye los pares `i=i` y por lo tanto subestima `E|X−X'|`, dejando el CRPS
  más alto de lo que corresponde. El sesgo crece con ensambles chicos. El
  estimador justo divide entre `m(m−1)` y es insesgado; es el que se usa por
  defecto.
- **Residuo de Murphy.** La identidad `BS = fiabilidad − resolución +
  incertidumbre` es exacta sólo si el pronóstico toma valores discretos. Con
  probabilidades continuas hay que agruparlas en cajas y aparece un residuo
  (la varianza intra-caja). Se devuelve como `residuo_intracaja` en vez de
  esconderlo: si crece frente al Brier, hay que subir el número de cajas.

## Pruebas

```
cd backend && pytest -q
153 passed
```

| Archivo | Qué cubre |
|---|---|
| `test_malla.py` | proyección contra haversine, geometría del hexágono, vecindad recíproca, escala, GeoJSON, topes |
| `test_estadistica.py` | erfc contra `math.erfc`, ppf contra valores publicados, Weibull, correlación y AR(1) del campo |
| `test_modelo.py` | calibración de Markov, acumulados contra normales, radiación contra identidad del equinoccio, rangos físicos, balance de agua, coherencia espacial, reproducibilidad |
| `test_ensamble.py` | orden de percentiles, probabilidades en rango, convención de dominio, todas las métricas |
| `test_asimilacion.py` | fórmula de Kalman, no colapso del ensamble, agregación de píxeles, ciclo completo observar→asimilar→pronosticar |
| `test_api.py` | 16 endpoints, errores 400/404/409/413/422, contrato de `null` vs `0` |

Las pruebas están escritas para **poder fallar**. Varias tienen una razón
explícita en el docstring de por qué existen y qué bug cazarían: por ejemplo
`test_elevacion_sintetica_es_conservadora` falla si alguien mete montañas de
1 000 m en una planicie costera, y
`test_la_probabilidad_es_nan_donde_la_variable_no_existe` falla si alguien
convierte los `NaN` del océano en ceros.

## Bugs que las pruebas encontraron

Para que conste que no son decorativas:

1. **El océano salía como "riesgo muy alto".** Al marcar el escurrimiento
   marino como `NaN`, `np.digitize` mandaba esos valores al último cajón.
   Arreglado con la categoría `-1` / `"no aplica"`.
2. **La probabilidad en el mar salía 0 en vez de `NaN`.** `NaN > umbral` es
   `False`, así que el océano aparecía con probabilidad 0, que en un mapa se
   lee como "seguro".
3. **Una afirmación invertida en la documentación del CRPS**, que decía que el
   estimador clásico premia a los ensambles chicos cuando es al revés.
4. **El perfil de elevación sintético inventaba 1 200 m de sierra** donde la
   zona es planicie costera, y producía 2 812 mm/año de lluvia en celdas que
   deberían andar en 1 700.
