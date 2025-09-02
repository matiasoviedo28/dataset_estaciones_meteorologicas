#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, re, csv, time, json
from html import unescape
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

BASE = "https://clima.sanluis.gob.ar"
URL_INDEX = f"{BASE}/Index.aspx"
R_TIMEOUT = 20
RETRIES = 3
SLEEP_BETWEEN = 0.2  # cortesía con el servidor

def http_get(url: str, tries: int = RETRIES, timeout: int = R_TIMEOUT) -> str:
    ua = "Mozilla/5.0 (compatible; CoordenadasBot/1.0; +bomberos.ar)"
    req = Request(url, headers={"User-Agent": ua})
    last_err = None
    for _ in range(tries):
        try:
            with urlopen(req, timeout=timeout) as r:
                data = r.read()
            return data.decode("utf-8", errors="ignore")
        except (URLError, HTTPError) as e:
            last_err = e
            time.sleep(0.5)
    raise last_err

def descubrir_estaciones():
    """Devuelve dict {id:int -> nombre:str} desde Index.aspx (REM + SLA)."""
    html = http_get(URL_INDEX)
    estaciones = {}
    for m in re.finditer(r"href=['\"]/Estacion\.aspx\?Estacion=(\d+)['\"]>([^<]+)</a>", html):
        est_id = int(m.group(1))
        nombre = unescape(m.group(2)).strip()
        if nombre:
            estaciones[est_id] = nombre
    return estaciones

def js_var(html: str, name: str, pat=r"(.+?)"):
    m = re.search(rf"var\s+{name}\s*=\s*{pat};", html)
    return m.group(1) if m else None

def dms_to_decimal(txt: str):
    """
    Convierte '33º 50' 15,2160'' Sur' -> -33.83756
    Retorna (float|None).
    """
    try:
        if not txt:
            return None
        t = unescape(txt).strip()
        hem_m = re.search(r"(Sur|Norte|Oeste|Este)", t, flags=re.I)
        if not hem_m:
            return None
        hem = hem_m.group(1).lower()

        deg_m = re.search(r"^\s*(\d+)", t)
        min_m = re.search(r"^\s*\d+\D+(\d+)", t)
        sec_m = re.search(r"\d+\D+\d+\D+(\d+[.,]?\d*)", t)  # segundos con coma o punto

        if not (deg_m and min_m and sec_m):
            return None

        d = float(deg_m.group(1))
        m = float(min_m.group(1))
        s = float(sec_m.group(1).replace(",", "."))

        dec = d + m/60.0 + s/3600.0
        if hem in ("sur", "oeste"):
            dec = -dec
        return dec
    except Exception:
        return None

def extraer_lat_lon_alt(html: str):
    """Intenta DMS; si falla, cae a JS. Devuelve (lat, lon, alt_m)."""
    lat_dec = lon_dec = alt_m = None

    # DMS en DOM
    lat_txt_m = re.search(r'id="ContentPlaceHolder1_lblLatitud"[^>]*>([^<]+)</label>', html)
    lon_txt_m = re.search(r'id="ContentPlaceHolder1_lblLongitud"[^>]*>([^<]+)</label>', html)
    alt_txt_m = re.search(r'id="ContentPlaceHolder1_lblAltura"[^>]*>([^<]+)</label>', html)

    if lat_txt_m and lon_txt_m:
        lat_dec = dms_to_decimal(lat_txt_m.group(1))
        lon_dec = dms_to_decimal(lon_txt_m.group(1))

    # Fallback: variables JS en decimal
    if lat_dec is None or lon_dec is None:
        lat_js = js_var(html, "EstacionLat", r"(-?\d+\.\d+)")
        lon_js = js_var(html, "EstacionLon", r"(-?\d+\.\d+)")
        try:
            if lat_dec is None and lat_js:
                lat_dec = float(lat_js)
            if lon_dec is None and lon_js:
                lon_dec = float(lon_js)
        except ValueError:
            pass

    # Altitud numérica (si está)
    if alt_txt_m:
        alt_txt = unescape(alt_txt_m.group(1)).strip()
        mnum = re.search(r"(\d+[.,]?\d*)", alt_txt.replace(",", "."))
        if mnum:
            try:
                alt_m = float(mnum.group(1))
            except ValueError:
                alt_m = None

    return lat_dec, lon_dec, alt_m

def extraer_nombre(html: str):
    """Nombre desde H1 o var JS."""
    m = re.search(r'id="ContentPlaceHolder1_Titulo"[^>]*>\s*([^<]+)\s*</h1>', html)
    if m:
        t = unescape(m.group(1)).strip()
        t = re.sub(r"^Datos de la estación:\s*", "", t, flags=re.I)
        t = t.replace(",", " ")
        if t:
            return t
    nom_js = js_var(html, "EstacionNombre", r'(".*?")')
    if nom_js:
        try:
            return json.loads(nom_js).replace(",", " ")
        except Exception:
            pass
    return ""

def procesar_estacion(est_id: int):
    """Devuelve tuple (id, nombre, lat, lon, alt_m) con None/'' si faltan."""
    url = f"{BASE}/Estacion.aspx?Estacion={est_id}"
    try:
        html = http_get(url)
    except Exception:
        return str(est_id), "", None, None, None

    nombre = extraer_nombre(html) or ""
    lat, lon, alt_m = extraer_lat_lon_alt(html)
    return str(est_id), nombre, lat, lon, alt_m

def main():
    estaciones = descubrir_estaciones()
    if not estaciones:
        # aún así crear archivo vacío con header
        os.makedirs("datos_masivos", exist_ok=True)
        with open("datos_masivos/coordenadas.csv", "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(["id", "nombre", "lat", "lon", "altitud_m"])
        return

    os.makedirs("datos_masivos", exist_ok=True)
    path_csv = os.path.join("datos_masivos", "coordenadas.csv")

    with open(path_csv, "w", newline="", encoding="utf-8") as fcsv:
        w = csv.writer(fcsv)
        w.writerow(["id", "nombre", "lat", "lon", "altitud_m"])

        for est_id in sorted(estaciones.keys()):
            time.sleep(SLEEP_BETWEEN)
            id_str, nombre, lat, lon, alt_m = procesar_estacion(est_id)

            lat_str = f"{lat:.6f}" if isinstance(lat, (int, float)) else ""
            lon_str = f"{lon:.6f}" if isinstance(lon, (int, float)) else ""
            alt_str = f"{alt_m:.2f}" if isinstance(alt_m, (int, float)) else ""

            w.writerow([id_str, nombre, lat_str, lon_str, alt_str])

    print(f"OK -> {path_csv}")

if __name__ == "__main__":
    main()
