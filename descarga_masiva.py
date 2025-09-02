#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
descarga_masiva.py
------------------
Descarga masiva de datos históricos de la REM (San Luis, AR) para todas las estaciones
válidas (REM y SLA), y guarda un CSV por estación en la carpeta 'datos_masivos'.

Características:
- Descubre estaciones desde la página InformePorPeriodo.aspx
- Endpoint CSV: ObtenerCsv.aspx?tipo=Periodo&Estacion={id}&fechaDesde=YYYYMMDD&fechahasta=YYYYMMDD
- Paginado mensual (2007 -> hoy) con reintentos y rate limit suave
- Salta HTML/errores y períodos vacíos
- Convierte a UTF-8 y escribe un único archivo por estación: {id}_{Nombre}.csv
- Manejo de encabezados: escribe 1 sola cabecera; si cambia, avisa por stderr y continúa

Requisitos: Python 3 estándar (sin dependencias externas)
"""

import sys
import os
import re
import io
import csv
import time
from datetime import date, timedelta
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# =========================
# Configuración general
# =========================

URL_PAGINA = "https://clima.sanluis.gob.ar/InformePorPeriodo.aspx"
URL_CSV = "https://clima.sanluis.gob.ar/ObtenerCsv.aspx"
SALIDA_DIR = "datos_masivos"

ANIO_INICIO = 2007           # Histórico aproximado de inicio de la REM
REINTENTOS = 3               # Reintentos por request
BACKOFF_BASE = 0.8           # Backoff exponencial base (segundos)
RATE_LIMIT_S = 0.25          # Pausa entre requests (evitar ser agresivos)

# Por defecto, incluimos solo tipos con datos útiles en este endpoint
TAGS_PERMITIDOS = {"REM", "SLA"}
TAGS_EXCLUIR = {"PRONO", "TEST", "TEST1", "REM1", "SLA1"}  # variantes de prueba/pronóstico

UA = "Mozilla/5.0 (REM-mass-downloader)"  # User-Agent inocuo


# =========================
# Excepciones personalizadas
# =========================

class RemError(Exception):
    """Error base para el downloader REM."""
    pass

class DescargaError(RemError):
    """Falla al descargar un período para una estación."""
    def __init__(self, estacion_id, url, status, mensaje="Error de descarga"):
        super().__init__(f"{mensaje} | estacion={estacion_id} status={status} url={url}")
        self.estacion_id = estacion_id
        self.url = url
        self.status = status

class EstacionSinDatosError(RemError):
    """La estación no devolvió ningún dato útil en todo el rango."""
    def __init__(self, estacion_id, nombre):
        super().__init__(f"Estación sin datos en todo el rango: {estacion_id} - {nombre}")
        self.estacion_id = estacion_id
        self.nombre = nombre


# =========================
# Utilidades
# =========================

def sanitizar_nombre_archivo(texto: str) -> str:
    """Convierte el nombre de estación a algo seguro para usar en un archivo."""
    # Reemplazar espacios por _
    out = re.sub(r"\s+", "_", texto.strip())
    # Quitar caracteres problemáticos
    out = re.sub(r"[^\w\-_.áéíóúÁÉÍÓÚñÑ]", "", out)
    # Evitar nombres excesivos
    return out[:100]

def mes_rango(y: int, m: int):
    """Devuelve primer y último día (date) de un mes."""
    first = date(y, m, 1)
    if m == 12:
        last = date(y + 1, 1, 1) - timedelta(days=1)
    else:
        last = date(y, m + 1, 1) - timedelta(days=1)
    return first, last

def yyyymmdd(d: date) -> str:
    return d.strftime("%Y%m%d")

def es_html(data: bytes) -> bool:
    """Heurística simple para detectar HTML en lugar de CSV."""
    head = data[:256].lower()
    return b"<!doctype html" in head or b"<html" in head

def decodificar_cp1252(b: bytes) -> str:
    """Convierte bytes cp1252 a str UTF-8 (python maneja internamente UTF-8)."""
    return b.decode("cp1252", errors="replace")

def tiene_datos(csv_text: str) -> bool:
    """Retorna True si el CSV parece tener algo más que la cabecera."""
    # Contar líneas. Si <=1, sólo header o vacío
    if not csv_text:
        return False
    lineas = csv_text.splitlines()
    return len(lineas) > 1

def solicitar(url: str, intentos: int = REINTENTOS) -> bytes:
    """GET simple con reintentos y backoff exponencial."""
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
                # último intento: propagar error
                raise DescargaError("?", url, getattr(e, "code", "URLError"), str(e))
            time.sleep(backoff)
            backoff *= 1.8
    # teóricamente no llega acá
    raise DescargaError("?", url, -1, "Fallo inesperado en reintentos")


# =========================
# Descubrimiento de estaciones
# =========================

def obtener_estaciones():
    """
    Lee la página InformePorPeriodo.aspx y devuelve una lista de dicts:
    [{id:'27', nombre:'Merlo', tag:'REM'}, ...]
    """
    html = solicitar(URL_PAGINA)
    text = html.decode("utf-8", errors="ignore")

    # Extraer todos los <option value='NNN'>TEXTO</option>
    pattern = re.compile(
        r"<option[^>]*value\s*=\s*['\"]?(\d+)['\"]?[^>]*>\s*([^<]+)",
        re.IGNORECASE | re.DOTALL
    )
    estaciones = []
    for est_id, nombre_crudo in pattern.findall(text):
        # Normalizar espacios
        nombre_crudo = re.sub(r"\s+", " ", nombre_crudo).strip()
        tag = ""
        m = re.search(r"\(([^()]*)\)\s*$", nombre_crudo)
        if m:
            tag = m.group(1).strip()
            nombre = re.sub(r"\s*\([^()]*\)\s*$", "", nombre_crudo).strip()
        else:
            nombre = nombre_crudo

        estaciones.append({"id": est_id, "nombre": nombre, "tag": tag})

    # Filtrar por tags permitidos
    filtradas = []
    for e in estaciones:
        tag_upper = e["tag"].upper().strip()
        if tag_upper in TAGS_EXCLUIR:
            continue
        if TAGS_PERMITIDOS and tag_upper not in TAGS_PERMITIDOS:
            continue
        filtradas.append(e)

    # Orden estable por id
    filtradas.sort(key=lambda x: int(x["id"]))
    return filtradas


# =========================
# Descarga por estación
# =========================

def construir_url_csv(estacion_id: str, fd: str, fh: str) -> str:
    """Construye URL del endpoint CSV con parámetros de período."""
    params = {
        "tipo": "Periodo",
        "Estacion": estacion_id,
        "fechaDesde": fd,
        "fechahasta": fh,
    }
    return f"{URL_CSV}?{urlencode(params)}"

def descargar_mes(estacion_id: str, y: int, m: int) -> str:
    """
    Descarga un mes para una estación y retorna el CSV como texto UTF-8.
    Si el contenido es HTML o está vacío, retorna cadena vacía.
    """
    first, last = mes_rango(y, m)
    fd, fh = yyyymmdd(first), yyyymmdd(last)
    url = construir_url_csv(estacion_id, fd, fh)

    # Reintentos con backoff ya dentro de 'solicitar'
    data = solicitar(url)

    if es_html(data):
        # HTML devuelto (p.ej. PRONO o errores)
        sys.stderr.write(f"[INFO] HTML recibido (omitido) | est={estacion_id} y={y} m={m}\n")
        return ""

    text = decodificar_cp1252(data)

    # Verificar si hay datos reales (más que header)
    if not tiene_datos(text):
        return ""

    return text

def guardar_estacion_csv(est: dict, base_dir: str) -> int:
    """
    Descarga todo el histórico de una estación (por meses) y guarda un único CSV.
    Devuelve la cantidad de filas (excluyendo cabecera) escritas.
    """
    est_id = est["id"]
    nombre = est["nombre"]
    tag = est["tag"]

    nombre_archivo = f"{est_id}_{sanitizar_nombre_archivo(nombre)}.csv"
    ruta = os.path.join(base_dir, nombre_archivo)
    os.makedirs(base_dir, exist_ok=True)

    hoy = date.today()
    y, m = ANIO_INICIO, 1

    header_escrito = False
    filas_escritas = 0
    header_referencia = None

    with io.open(ruta, "w", encoding="utf-8", newline="") as out:
        while (y < hoy.year) or (y == hoy.year and m <= hoy.month):
            try:
                csv_text = descargar_mes(est_id, y, m)
            except DescargaError as e:
                sys.stderr.write(f"[WARN] {e}\n")
                # Continuar con el siguiente mes
                y, m = (y + 1, 1) if m == 12 else (y, m + 1)
                time.sleep(RATE_LIMIT_S)
                continue

            if csv_text:
                lineas = csv_text.splitlines()
                # Normalizar fin de línea CRLF -> LF ya lo maneja splitlines()
                header_actual = lineas[0].replace("\r", "")
                datos = lineas[1:]  # resto de filas

                if not header_escrito:
                    out.write(header_actual + "\n")
                    header_escrito = True
                    header_referencia = header_actual
                else:
                    # Si el encabezado cambió, avisar y continuar (se escriben solo datos)
                    if header_actual != header_referencia:
                        sys.stderr.write(
                            f"[WARN] Encabezado distinto en {est_id}-{nombre} {y}-{m:02d}. "
                            f"Se omite nuevo encabezado y se anexan datos.\n"
                        )

                # Escribir filas de datos
                for row in datos:
                    if row.strip():
                        out.write(row.rstrip("\r") + "\n")
                        filas_escritas += 1

            # rate limit
            time.sleep(RATE_LIMIT_S)

            # avanzar mes
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)

    if filas_escritas == 0:
        # No quedó nada útil
        # Borrar archivo vacío/casi vacío (solo header) si existiera
        try:
            if os.path.exists(ruta) and os.path.getsize(ruta) <= 128:
                os.remove(ruta)
        except OSError:
            pass
        raise EstacionSinDatosError(est_id, nombre)

    return filas_escritas


# =========================
# Programa principal
# =========================

def main():
    print("== Descubrimiento de estaciones ==")
    estaciones = obtener_estaciones()
    if not estaciones:
        print("No se encontraron estaciones válidas (REM/SLA).", file=sys.stderr)
        sys.exit(2)

    print(f"Estaciones a procesar: {len(estaciones)}")
    os.makedirs(SALIDA_DIR, exist_ok=True)

    tot_est = len(estaciones)
    ok = 0
    skipped = 0

    for idx, est in enumerate(estaciones, start=1):
        est_id = est["id"]
        nombre = est["nombre"]
        tag = est["tag"]
        print(f"[{idx}/{tot_est}] {est_id} - {nombre} ({tag}) ...", flush=True)
        try:
            filas = guardar_estacion_csv(est, SALIDA_DIR)
            print(f"  -> OK, filas escritas: {filas}")
            ok += 1
        except EstacionSinDatosError as e:
            print(f"  -> SIN DATOS ({e})", file=sys.stderr)
            skipped += 1
        except DescargaError as e:
            print(f"  -> ERROR de descarga: {e}", file=sys.stderr)
            skipped += 1
        except Exception as e:
            print(f"  -> ERROR inesperado: {e}", file=sys.stderr)
            skipped += 1

    print("\n== Resumen ==")
    print(f"Estaciones procesadas: {tot_est}")
    print(f"Con datos (OK):       {ok}")
    print(f"Sin datos/errores:    {skipped}")
    print(f"Carpeta de salida:    {SALIDA_DIR}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrumpido por el usuario.", file=sys.stderr)
        sys.exit(130)
