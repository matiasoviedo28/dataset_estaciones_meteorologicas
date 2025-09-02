# 📡 Datos de la REM San Luis

Repositorio con scripts en Python para descargar datos históricos de la **Red de Estaciones Meteorológicas (REM)** de la Provincia de San Luis, Argentina. Clonando este repo podés generar tus propios datasets listos para analizar o para usar en proyectos educativos.

## 🛠 Requisitos
- [Python 3](https://www.python.org/) (no se necesitan librerías externas).

## 🚀 Uso rápido
1. Cloná el repositorio y entrá a la carpeta:
   ```bash
   git clone https://github.com/matiasoviedo28/dataset_estaciones_meteorologicas.git
   cd dataset_estaciones_meteorologicas
   ```
2. Descarga masiva de todas las estaciones REM y SLA:
   ```bash
   python descarga_masiva.py
   ```
   Genera un CSV por estación en `datos_masivos/`.
3. Actualización incremental de los archivos existentes:
   ```bash
   python descarga_incremental.py
   ```
4. Obtención de coordenadas y altitud de cada estación:
   ```bash
   python descarga_coordenadas.py
   ```

## 🔍 API pública de la REM
La REM expone un endpoint sencillo para obtener los datos en formato CSV.

### Endpoint
```
https://clima.sanluis.gob.ar/ObtenerCsv.aspx
```

### Parámetros
- `tipo`: siempre `Periodo`.
- `Estacion`: identificador numérico de la estación.
- `fechaDesde`: fecha inicio `YYYYMMDD`.
- `fechahasta`: fecha fin `YYYYMMDD`.

Ejemplo:
```
https://clima.sanluis.gob.ar/ObtenerCsv.aspx?tipo=Periodo&Estacion=27&fechaDesde=20250801&fechahasta=20250831
```
Devuelve un CSV con los datos de **Merlo (id=27)** para agosto de 2025.

### Identificadores de estaciones
Las estaciones poseen un ID numérico y un tipo entre paréntesis:
- **REM** → estaciones meteorológicas clásicas.
- **SLA** → estaciones de diques y agua.
- **PRONO** → pronóstico (no devuelven datos históricos).
- **TEST / variantes** → registros de prueba.

### Respuesta
- Formato: CSV delimitado por `;`.
- Codificación: Windows-1252 (conviene convertir a UTF-8).
- Decimales: coma `,`.
- Encabezados: varían según el tipo de estación.

Ejemplos de encabezados:
- **REM**: `"Fecha/Hora";"Precipitacion (mm)";"Temperatura (°C)";"Humedad (%)";...`
- **SLA**: `"Fecha/Hora";"Nivel Agua (mts)"`

### Limitaciones
- Consultas muy largas pueden fallar; se recomienda iterar **mes a mes**.
- Las respuestas pueden venir vacías (solo cabecera).
- No conviene usar estaciones `PRONO` o `TEST`.

### Ejemplos
Descarga con `curl`:
```bash
curl -G \
  --data-urlencode "tipo=Periodo" \
  --data-urlencode "Estacion=27" \
  --data-urlencode "fechaDesde=20250801" \
  --data-urlencode "fechahasta=20250831" \
  "https://clima.sanluis.gob.ar/ObtenerCsv.aspx" -o Merlo_2025-08.csv
```
Lectura rápida en Python con `pandas`:
```python
import pandas as pd

df = pd.read_csv(
    "Merlo_2025-08.csv",
    sep=";",
    encoding="cp1252",
    decimal="," 
)
print(df.head())
```

## 📂 Estructura del proyecto
```
descarga_masiva.py        # baja el histórico completo por estación
descarga_incremental.py   # actualiza los CSV ya generados
descarga_coordenadas.py   # obtiene lat/lon/alt de cada estación
datos_masivos/            # carpeta generada automaticamente para almacenar los CSV descargados
```

## 🔗 Fuentes y créditos
- **REM San Luis**: [clima.sanluis.gob.ar](https://clima.sanluis.gob.ar)

📌 Este proyecto es de uso educativo y no tiene relación oficial con la REM.