# 0003 — Sin scipy en el núcleo

**Fecha:** 10-oct-2026 · **Estado:** aceptada

## Contexto

El modelo necesita la CDF y la inversa de la normal, una distribución de cola
pesada con inversa para la cópula, y la factorización de una matriz de
covarianza.

## Decisión

Sólo numpy. Las funciones que faltan se implementan con aproximaciones
publicadas y se verifican contra la stdlib.

| Necesidad | Solución | Precisión | Verificación |
|---|---|---|---|
| `Φ(x)` | erfc de Numerical Recipes | 1.2e-7 fraccional | contra `math.erfc` en 1 201 puntos |
| `Φ⁻¹(p)` | algoritmo de Acklam / AS241 | ~1.15e-9 relativo | valores publicados e ida-vuelta |
| intensidad | Weibull (CDF e inversa cerradas) | exacta | ida-vuelta y mediana analítica |
| covarianza | `numpy.linalg.cholesky` | — | correlación empírica contra la objetivo |

## Por qué

- El backend tiene que arrancar en una máquina limpia y en el contenedor del
  hackathon **sin compilar nada**. scipy son ~90 MB y, en Python 3.14 recién
  salido, una fuente probable de problemas de ruedas precompiladas.
- La precisión de 1e-7 en `Φ` es irrelevante para el modelo: se usa para
  umbrales de ocurrencia y para la cópula, donde el ruido de Monte Carlo del
  ensamble es cinco órdenes de magnitud mayor.
- Elegir Weibull en lugar de Gamma no es una concesión: la Gamma habría
  necesitado la inversa de la gamma incompleta (que sí exige scipy o mucho
  código), y para lluvia diaria las dos ajustan de forma comparable según
  Wilks (1999).

## Consecuencias

- La prueba de `norm_cdf` tiene tolerancia 1e-7, no 1e-9: `norm_cdf(0)` da
  0.50000002. Está escrito en el test para que nadie lo "arregle" apretando la
  tolerancia.
- Si en el futuro se necesitan ajustes de máxima verosimilitud o
  distribuciones de valores extremos, probablemente sí convenga scipy. En ese
  momento se revisa esta decisión; entra como dependencia de calibración
  (offline), no del servidor.
