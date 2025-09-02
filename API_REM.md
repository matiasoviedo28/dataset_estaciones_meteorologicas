# API REM – Red de Estaciones Meteorológicas de San Luis

La **Red de Estaciones Meteorológicas (REM)** de la Provincia de San Luis ofrece datos meteorológicos y ambientales históricos a través de su sitio web oficial.
Si bien la interfaz es web, existe un endpoint público que permite automatizar la descarga de datos en formato **CSV**.

---

## Endpoint

```
https://clima.sanluis.gob.ar/ObtenerCsv.aspx
```

---

## Parámetros requeridos

* **tipo**: siempre `"Periodo"`.
* **Estacion**: identificador numérico de la estación.
* **fechaDesde**: fecha de inicio en formato `YYYYMMDD`.
* **fechahasta**: fecha de fin en formato `YYYYMMDD`.

Ejemplo:

```
https://clima.sanluis.gob.ar/ObtenerCsv.aspx?tipo=Periodo&Estacion=27&fechaDesde=20250801&fechahasta=20250831
```

Este enlace devuelve un archivo CSV con los datos de la estación **Merlo (id=27)** para agosto de 2025.

---

## Identificadores de estaciones

Cada estación tiene un **id numérico** y un **tipo** entre paréntesis:

* **REM** → estaciones meteorológicas clásicas (precipitación, temperatura, humedad, viento, etc.).
* **SLA** → estaciones de diques y agua (nivel del agua en metros).
* **PRONO** → estaciones de pronóstico (no devuelven datos históricos).
* **TEST / variantes** → entradas de prueba (no útiles).

Ejemplo de listado (parcial):

```
27   Merlo (REM)
42   Villa Mercedes (REM)
90   Dique Antonio E. Aguero-Río Grande (SLA)
84   La Candelaria (PRONO)
```

---

## Respuesta

* **Formato**: CSV delimitado por `;`.
* **Codificación**: Windows-1252 (debe convertirse a UTF-8 para uso general).
* **Decimales**: coma `,` (ej. `12,34`).
* **Cabeceras**: varían según el tipo de estación.

Ejemplos de encabezados:

* **REM (meteorológica con viento y humedad):**

  ```
  "Fecha/Hora";"Precipitacion (mm)";"Temperatura (°C)";"Humedad (%)";"Dir. Del Viento (°)";"Int. del Viento (m/s)"
  ```

* **REM (con presión atmosférica):**

  ```
  "Fecha/Hora";"Precipitacion (mm)";"Temperatura (°C)";"Humedad (%)";"Presión (hPa)";"Dir. Del Viento (°)";"Int. del Viento (m/s)"
  ```

* **SLA (dique):**

  ```
  "Fecha/Hora";"Nivel Agua (mts)"
  ```

* **PRONO (pronóstico):**
  Devuelven HTML en lugar de CSV (no compatible con este endpoint).

---

## Limitaciones

* Las respuestas pueden estar **vacías** (sólo encabezado, sin datos).
* Los encabezados no son uniformes entre estaciones.
* Rangos de fechas demasiado largos pueden generar errores (recomendado consultar **por mes**).
* Se recomienda filtrar y trabajar sólo con estaciones **REM** o **SLA**.

---

## Ejemplos de uso

### Descarga con `curl`

```bash
curl -G \
  --data-urlencode "tipo=Periodo" \
  --data-urlencode "Estacion=27" \
  --data-urlencode "fechaDesde=20250801" \
  --data-urlencode "fechahasta=20250831" \
  "https://clima.sanluis.gob.ar/ObtenerCsv.aspx" -o Merlo_2025-08.csv
```

### Lectura en Python con `pandas`

```python
import pandas as pd

df = pd.read_csv(
    "Merlo_2025-08.csv",
    sep=";",
    encoding="cp1252",   # convertir a UTF-8 si se desea
    decimal=","
)

print(df.head())
```

---

## Recomendaciones de uso

* **Iterar por meses** desde 2007 hasta la fecha actual para obtener la serie completa.
* **Convertir a UTF-8** y normalizar decimales a punto para facilitar análisis.
* **Registrar encabezados** de cada estación, ya que pueden variar.
* **Excluir PRONO/TEST** de la descarga, pues no entregan datos útiles.