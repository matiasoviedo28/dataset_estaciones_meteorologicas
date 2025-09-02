#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
descarga_incremental.py
-----------------------
Actualiza de forma incremental los CSV masivos existentes en la carpeta 'datos_masivos/'.

Supuestos coherentes con 'descarga_masiva.py':
- Un archivo por estación: {id}_{Nombre}.csv en UTF-8, delimitado por ';', decimales con coma.
- Primera columna (o al menos una columna) llamada "Fecha/Hora" (con comillas en el CSV original).
- Cada mes se descarga desde el endpoint:
  https://clima.sanluis.gob.ar/ObtenerCsv.aspx?tipo=Periodo&Estacion={id}&fechaDesde=YYYYMMDD&fechahasta=YYYYMMDD

Comportamiento:
- Si 'datos_masivos/' no existe => error personalizado y termina.
- Para cada archivo: obtiene la última fecha/hora y descarga lo faltante (mes a mes) hasta hoy.
- Evita duplicados: descarta filas con Fecha/Hora <= última fecha consolidada.
- Mantiene el encabezado original (no lo repite al anexar).

Requisitos: Python 3 estándar (sin dependencias externas).
"""

import sys
import os
import re
import io
import csv
import time
from glob import glob
from datetime import date, datetime, timedelta
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# =========================
# Configuración
# =========================

URL_CSV = "https://clima.sanluis.gob.ar/ObtenerCsv.aspx"
DIR_MASIVOS = "datos_masivos"

REINTENTOS = 3
BACKOFF_BASE = 0.8
RATE_LIMIT_S = 0.25
UA = "Mozilla/5.0 (REM-incremental)"

# =========================
# Excepciones personalizadas
# =========================

class DatosMasivosNoExistenError(Exception):
    """La carpeta datos_masivos/ no existe o no es un directorio."""
    pass

class DescargaError(Exception):
    """Falla en la descarga de un período."""
    def __init__(self, estacion_id, url, status, mensaje="Error de descarga"):
        super().__init__(f"{mensaje} | estacion={estacion_id} status={status} url={url}")
        self.estacion_id = estacion_id
        self.url = url
        self.status = status

# =========================
# Utilidades de fechas
# =========================

def mes_rango(y: int, m: int):
    """Devuelve (primer_dia, ultimo_dia) de un mes (objetos date)."""
    first = date(y, m, 1)
    last = date(y + (m == 12), (m % 12) + 1, 1) - timedelta(days=1)
    return first, last

def yyyymmdd(d: date) -> str:
    return d.strftime("%Y%m%d")

# =========================
# HTTP / Endpoint
# =========================

def construir_url_csv(estacion_id: str, fd: str, fh: str) -> str:
    params = {
        "tipo": "Periodo",
        "Estacion": estacion_id,
        "fechaDesde": fd,
        "fechahasta": fh,
    }
    return f"{URL_CSV}?{urlencode(params)}"

def es_html(data: bytes) -> bool:
    head = data[:256].lower()
    return b"<!doctype html" in head or b"<html" in head

def solicitar(url: str, intentos: int = REINTENTOS) -> bytes:
    backoff = BACKOFF_BASE
    for i in range(intentos):
        try:
            req = Request(url, headers={"User-Agent": UA})
            with urlopen(req, timeout=45) as resp:
                status = getattr(resp, "status", 200)
                data = resp.read()
                if status != 200:
                    raise DescargaError("?", url, status)
                return data
        except (HTTPError, URLError) as e:
            if i == intentos - 1:
                raise DescargaError("?", url, getattr(e, "code", "URLError"), str(e))
            time.sleep(backoff)
            backoff *= 1.8
    raise DescargaError("?", url, -1, "Fallo inesperado en reintentos")

def descargar_mes_texto(estacion_id: str, y: int, m: int) -> str:
    """Devuelve el CSV crudo como texto UTF-8 (decodificado desde cp1252). Si es HTML o vacío, retorna ''."""
    first, last = mes_rango(y, m)
    fd, fh = yyyymmdd(first), yyyymmdd(last)
    url = construir_url_csv(estacion_id, fd, fh)
    data = solicitar(url)
    if es_html(data):
        sys.stderr.write(f"[INFO] HTML recibido (omitido) | est={estacion_id} y={y} m={m:02d}\n")
        return ""
    text = data.decode("cp1252", errors="replace")
    # ¿al menos header + 1 dato?
    if text.count("\n") < 1:
        return ""
    return text

# =========================
# CSV / Parsing
# =========================

def extraer_id_de_archivo(nombre_archivo: str) -> str:
    """
    Espera nombres como '27_Merlo.csv' o '90_Dique_Algo.csv'.
    Devuelve la parte numérica inicial como string (sin validar que exista en web).
    """
    base = os.path.basename(nombre_archivo)
    m = re.match(r"^(\d+)_", base)
    return m.group(1) if m else ""

def detectar_idx_fecha(header: str) -> int:
    """
    Dado un header de CSV (línea completa), detecta el índice de la columna 'Fecha/Hora'
    tolerando comillas y variaciones de espaciado/case.
    """
    # Limpiar \r y dividir por ';'
    cols = [c.strip().strip('"').strip("'") for c in header.replace("\r", "").split(";")]
    for i, c in enumerate(cols):
        if c.lower().replace(" ", "") in ("fechahora", "fecha/hora", "fecha_hora"):
            return i
    # fallback: primera columna
    return 0

def parsear_fecha_hora(cadena: str) -> datetime:
    """
    Convierte 'dd/mm/YYYY HH:MM:SS' a datetime. Tolerante a comillas/espacios.
    """
    s = cadena.strip().strip('"').strip("'")
    return datetime.strptime(s, "%d/%m/%Y %H:%M:%S")

def obtener_ultima_fecha_existente(ruta_csv: str) -> tuple[datetime, str]:
    """
    Escanea el archivo para encontrar la última Fecha/Hora válida.
    Retorna (dt_ultima, header_line). Si no hay datos, dt_ultima=None.
    """
    ultima_dt = None
    header = None
    idx_fecha = None

    with io.open(ruta_csv, "r", encoding="utf-8", errors="replace") as f:
        for n, line in enumerate(f):
            line = line.rstrip("\n")
            if n == 0:
                header = line
                idx_fecha = detectar_idx_fecha(header)
                continue
            if not line.strip():
                continue
            partes = line.split(";")
            if idx_fecha >= len(partes):
                continue
            try:
                dt = parsear_fecha_hora(partes[idx_fecha])
                if (ultima_dt is None) or (dt > ultima_dt):
                    ultima_dt = dt
            except Exception:
                # línea malformada, la ignoramos
                continue
    return ultima_dt, header or ""

def generar_meses_desde_hasta(desde: date, hasta: date):
    """Genera (año, mes) desde el mes de 'desde' hasta el mes de 'hasta' (inclusive)."""
    y, m = desde.year, desde.month
    while (y < hasta.year) or (y == hasta.year and m <= hasta.month):
        yield (y, m)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)

# =========================
# Lógica principal
# =========================

def actualizar_archivo_estacion(ruta_csv: str) -> int:
    """
    Actualiza (si corresponde) un archivo de estación existente.
    - Detecta última fecha.
    - Descarga meses necesarios.
    - Anexa sin duplicar.
    Devuelve la cantidad de filas nuevas añadidas.
    """
    estacion_id = extraer_id_de_archivo(ruta_csv)
    if not estacion_id:
        sys.stderr.write(f"[WARN] No se pudo inferir id de estación desde nombre: {ruta_csv}\n")
        return 0

    ultima_dt, header_existente = obtener_ultima_fecha_existente(ruta_csv)
    if ultima_dt is None:
        sys.stderr.write(f"[INFO] Archivo sin datos (o sólo cabecera), se intentará reconstruir desde su creación): {ruta_csv}\n")
        # Si no hay fecha, empezamos desde hace 60 días (conservador) para rellenar algo razonable:
        desde = date.today() - timedelta(days=60)
    else:
        # día siguiente a la última observación:
        desde = (ultima_dt + timedelta(days=1)).date()

    hoy = date.today()
    if desde > hoy:
        # Nada para hacer
        return 0

    # Vamos a anexar: abrimos en modo append
    filas_nuevas = 0
    idx_fecha_existente = detectar_idx_fecha(header_existente)

    with io.open(ruta_csv, "a", encoding="utf-8", newline="") as out:
        for y, m in generar_meses_desde_hasta(desde, hoy):
            try:
                texto = descargar_mes_texto(estacion_id, y, m)
            except DescargaError as e:
                sys.stderr.write(f"[WARN] {e}\n")
                time.sleep(RATE_LIMIT_S)
                continue

            if not texto:
                time.sleep(RATE_LIMIT_S)
                continue

            lineas = texto.splitlines()
            if not lineas:
                time.sleep(RATE_LIMIT_S)
                continue

            header_nuevo = lineas[0].replace("\r", "")
            # No reescribimos header (ya existe). Si difiere, sólo avisamos.
            if header_existente and header_nuevo != header_existente:
                sys.stderr.write(
                    f"[WARN] Encabezado distinto detectado en est={estacion_id} {y}-{m:02d}. "
                    f"Se anexan datos sin duplicar encabezado.\n"
                )

            # Anexar sólo filas nuevas (Fecha/Hora > ultima_dt)
            for fila in lineas[1:]:
                if not fila.strip():
                    continue
                partes = fila.split(";")
                # seguridad: si el índice no existe, anexo igual (mejor no perder datos)
                if idx_fecha_existente < len(partes):
                    try:
                        dt = parsear_fecha_hora(partes[idx_fecha_existente])
                        if (ultima_dt is not None) and (dt <= ultima_dt):
                            continue  # duplicado o más viejo
                    except Exception:
                        # si no pude parsear fecha, anexo por no perder registros
                        pass
                out.write(fila.rstrip("\r") + "\n")
                filas_nuevas += 1

            time.sleep(RATE_LIMIT_S)

    return filas_nuevas

def main():
    # 1) Validación de carpeta
    if not os.path.exists(DIR_MASIVOS) or not os.path.isdir(DIR_MASIVOS):
        raise DatosMasivosNoExistenError(
            f"No se encontró la carpeta '{DIR_MASIVOS}'. "
            "Primero generá los datos con descarga_masiva.py"
        )

    # 2) Buscar archivos {id}_{Nombre}.csv
    patrones = os.path.join(DIR_MASIVOS, "*.csv")
    archivos = sorted(glob(patrones))
    if not archivos:
        raise DatosMasivosNoExistenError(
            f"No se hallaron CSVs en '{DIR_MASIVOS}'. "
            "Asegurate de haber corrido descarga_masiva.py y de que el patrón sea {id}_{Nombre}.csv"
        )

    print(f"== Incremental REM == Archivos a revisar: {len(archivos)}")
    total_nuevas = 0
    con_cambios = 0

    for i, ruta in enumerate(archivos, 1):
        print(f"[{i}/{len(archivos)}] {os.path.basename(ruta)} ...", end="", flush=True)
        try:
            n = actualizar_archivo_estacion(ruta)
            if n > 0:
                con_cambios += 1
                total_nuevas += n
                print(f" +{n} filas nuevas")
            else:
                print(" sin cambios")
        except DescargaError as e:
            print(f" ERROR descarga: {e}", file=sys.stderr)
        except Exception as e:
            print(f" ERROR: {e}", file=sys.stderr)

    print("\n== Resumen incremental ==")
    print(f"Archivos revisados:     {len(archivos)}")
    print(f"Archivos actualizados:  {con_cambios}")
    print(f"Filas nuevas totales:   {total_nuevas}")

if __name__ == "__main__":
    try:
        main()
    except DatosMasivosNoExistenError as e:
        # Error personalizado (lo que pediste)
        print(f"[ERROR DATOS MASIVOS] {e}", file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        print("\nInterrumpido por el usuario.", file=sys.stderr)
        sys.exit(130)
