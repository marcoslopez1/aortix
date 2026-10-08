"""
Calibración AUTOMÁTICA de capturas PNG/JPG de Doppler continuo (y de DICOM sin calibración).

Busca en la propia imagen:
  - la línea de base (línea horizontal naranja de los equipos Philips; si no, la fila con el rótulo de unidades),
  - la región espectral (el rectángulo con textura alrededor de la línea de base),
  - la escala de velocidad (lee los números de la regla de la derecha con reconocimiento de texto),
  - la escala de tiempo (las marcas del eje inferior: las más altas están separadas 1 segundo).
Como comprobación cruzada compara la frecuencia cardiaca de las ondas R del ECG con la que marca la pantalla.

Si algo no cuadra devuelve None y la aplicación pide la calibración manual.

Uso (prueba):
    python autocalibrar.py imagen.png [más imágenes]
"""
import json
import os
import re
import sys

import cv2
import numpy as np

_OCR = None


def _lector():
    """Lector de texto (RapidOCR). Se carga una sola vez; None si no está instalado."""
    global _OCR
    if _OCR is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
            _OCR = RapidOCR()
        except Exception:
            _OCR = False
    return _OCR or None


def _leer_textos(rgb, x0, y0, x1, y1):
    """Textos de un recorte: lista de (texto, x_izq, y_centro) en coordenadas de la imagen."""
    ocr = _lector()
    if ocr is None:
        return None
    rec = np.ascontiguousarray(rgb[y0:y1, x0:x1, ::-1])  # el lector espera BGR
    res, _ = ocr(rec)
    out = []
    for caja, txt, conf in res or []:
        if conf < 0.6:
            continue
        xs, ys = [p[0] for p in caja], [p[1] for p in caja]
        out.append((txt.strip(), x0 + min(xs), y0 + (min(ys) + max(ys)) / 2))
    return out


def _numero(txt):
    m = re.search(r"\d+(?:[.,]\d+)?", txt)
    return float(m.group().replace(",", ".")) if m else None


# -----------------------------------------------------------------------------
def linea_base(rgb):
    """Fila y extensión horizontal de la línea de base naranja. None si no hay."""
    c = rgb.astype(np.int16)
    R, G, B = c[..., 0], c[..., 1], c[..., 2]
    naranja = (R > 110) & (R - B > 60) & (R > G + 25)
    cnt = naranja.sum(1)
    yb = int(cnt.argmax())
    if cnt[yb] < 0.25 * rgb.shape[1]:
        return None
    xs = np.flatnonzero(naranja[max(yb - 1, 0):yb + 2].any(0))
    return yb, int(xs.min()), int(xs.max())


def region_espectral(rgb, yb, xa, xb):
    """Rectángulo del espectro alrededor de la línea de base (x0, y0, x1, y1)."""
    gris = rgb.mean(-1)
    h = rgb.shape[0]
    # columnas: textura justo por debajo y por encima de la línea de base
    banda = np.vstack([gris[max(yb - 12, 0):yb - 3], gris[yb + 4:yb + 30]])
    cols = (banda > 8).mean(0) > 0.6
    cols[:max(xa - 15, 0)] = False
    cols[xb + 15:] = False
    idx = np.flatnonzero(cols)
    x0, x1 = (int(idx.min()), int(idx.max()) + 1) if idx.size else (xa, xb + 1)
    frac = (gris[:, x0:x1] > 8).mean(1)
    # hacia arriba: mientras la mayoría de la fila tenga textura
    y0 = yb
    while y0 > 0 and frac[y0 - 1] > 0.6:
        y0 -= 1
    return x0, y0, x1, h  # el borde inferior lo fija el eje de tiempo


def escala_tiempo(rgb, y_desde):
    """Marcas del eje de tiempo. Devuelve (px_por_s, fila_superior_de_las_marcas, detalle) o None."""
    h = rgb.shape[0]
    c = rgb.astype(np.int16)
    blanco = (c.mean(-1) > 150) & (c.max(-1) - c.min(-1) < 40)
    zona = blanco[y_desde:].astype(np.uint8)
    n, _, st, _ = cv2.connectedComponentsWithStats(zona, 8)
    marcas = [(st[i, 0] + st[i, 2] / 2, st[i, 1] + y_desde, st[i, 3]) for i in range(1, n)
              if st[i, 2] <= 5 and 3 <= st[i, 3] <= 30]
    if len(marcas) < 4:
        return None
    # las marcas comparten el borde inferior
    fondos = np.array([y + alto for _, y, alto in marcas])
    vals, cuenta = np.unique(fondos, return_counts=True)
    fondo = vals[cuenta.argmax()]
    marcas = [m for m, f in zip(marcas, fondos) if abs(f - fondo) <= 1]
    if len(marcas) < 4:
        return None
    alto_max = max(a for _, _, a in marcas)
    grandes = sorted(x for x, _, a in marcas if a >= alto_max - 1)
    if len(grandes) < 2:
        return None
    d = np.diff(grandes)
    if d.size > 1 and d.std() / d.mean() > 0.03:
        return None
    y_marcas = min(y for _, y, _ in marcas)
    return float(np.median(d)), int(y_marcas), dict(marcas_1s=[round(x, 1) for x in grandes], n_marcas=len(marcas))


def escala_velocidad(rgb, yb, y0, y1):
    """px por m/s a partir de los números de la regla de la derecha. Devuelve (px_por_ms, detalle) o None."""
    h, w = rgb.shape[:2]
    textos = _leer_textos(rgb, int(w * 0.85), 0, w, h)
    if textos is None:
        return None, "lector de texto no instalado"
    nums = [(t, x, y, _numero(t)) for t, x, y in textos
            if y0 - 5 <= y <= y1 + 5 and _numero(t) and not re.search(r"bpm|mm|hz", t, re.I)]
    nums = [(t, x, y, v) for t, x, y, v in nums if v > 0 and abs(y - yb) > 10]
    if len(nums) < 2:
        return None, "no se leen al menos dos números de la escala"
    # unidades: el rótulo "m/s" o "cm/s" más cercano a la línea de base, en la columna de la escala
    x_escala = np.median([x for _, x, _, _ in nums])
    unidades = [(abs(y - yb), t) for t, x, y in textos if "m/s" in t.lower() and abs(x - x_escala) < 40]
    if not unidades:
        return None, "no se encuentra el rótulo de unidades (m/s o cm/s)"
    cm = "cm" in min(unidades)[1].lower()
    ratios = np.array([abs(y - yb) / (v / 100 if cm else v) for _, _, y, v in nums])
    med = np.median(ratios)
    buenos = np.abs(ratios / med - 1) < 0.04
    if buenos.sum() < 2:
        return None, "los números de la escala no son coherentes entre sí"
    px = float(ratios[buenos].mean())
    det = dict(unidades="cm/s" if cm else "m/s",
               marcas=[(t, round(y)) for (t, _, y, _), b in zip(nums, buenos) if b])
    return px, det


def fc_pantalla(rgb):
    """Frecuencia cardiaca que muestra el ecógrafo (texto "NNbpm"), o None."""
    h, w = rgb.shape[:2]
    textos = _leer_textos(rgb, int(w * 0.6), int(h * 0.85), w, h) or []
    for t, _, _ in textos:
        m = re.search(r"(\d{2,3})\s*bpm", t, re.I)
        if m:
            return float(m.group(1))
    return None


def fc_ecg(rgb, cal):
    """Frecuencia cardiaca a partir de las ondas R del ECG verde (con la calibración propuesta)."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import procesar as P
    try:
        _, ecg, _ = P.preprocesar(rgb, cal)
        r = P.ecg_r(ecg, cal)
    except Exception:
        return None
    if len(r) < 2:
        return None
    return 60 / (np.median(np.diff(r)) / cal["px_por_s"])


# -----------------------------------------------------------------------------
def autocalibrar(rgb):
    """Devuelve (calibración, informe). La calibración es None si no se ha podido hacer.

    La calibración tiene el mismo formato que <imagen>_calibracion.json."""
    inf = dict(avisos=[])
    lb = linea_base(rgb)
    if lb is None:
        inf["error"] = "no se encuentra la línea de base"
        return None, inf
    yb, xa, xb = lb
    x0, y0, x1, _ = region_espectral(rgb, yb, xa, xb)
    t = escala_tiempo(rgb, yb + 20)
    if t is None:
        inf["error"] = "no se encuentran las marcas del eje de tiempo"
        return None, inf
    px_s, y_marcas, inf["tiempo"] = t
    y1 = y_marcas - 2
    px_ms, det = escala_velocidad(rgb, yb, y0, y1)
    if px_ms is None:
        inf["error"] = det
        return None, inf
    inf["velocidad"] = det
    cal = dict(region=dict(x0=x0, y0=y0, x1=x1, y1=y1), linea_base_y=yb,
               px_por_ms=round(px_ms, 3), px_por_s=round(px_s, 2),
               tamano_imagen=[rgb.shape[1], rgb.shape[0]], fuente="automática")
    # comprobaciones de plausibilidad
    v_max_escala = (y1 - yb) / px_ms
    if not (1.5 <= v_max_escala <= 15):
        inf["error"] = f"escala de velocidad poco creíble (hasta {v_max_escala:.1f} m/s)"
        return None, inf
    if not (40 <= px_s <= 2000):
        inf["error"] = f"escala de tiempo poco creíble ({px_s:.0f} px/s)"
        return None, inf
    # comprobación cruzada con la frecuencia cardiaca (solo aviso)
    fcp = fc_pantalla(rgb)
    plano = dict(x0=x0, y0=y0, x1=x1, y1=y1, linea_base_y=yb, px_por_ms=px_ms, px_por_s=px_s)
    fce = fc_ecg(rgb, plano)
    inf["fc_pantalla"], inf["fc_ecg"] = fcp, (round(fce) if fce else None)
    if fcp and fce and abs(fce / fcp - 1) > 0.15:
        inf["avisos"].append(f"la FC del ECG ({fce:.0f} lpm) no coincide con la de la pantalla ({fcp:.0f} lpm): "
                             "revisa la escala de tiempo o el ritmo")
    cal["comprobacion"] = dict(fc_pantalla=fcp, fc_ecg=inf["fc_ecg"],
                               escala=inf["velocidad"]["unidades"])
    return cal, inf


def leer_rgb(ruta):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import procesar as P
    if P._es_dicom(ruta):
        return P.pixeles_dicom(ruta)[0]
    return cv2.cvtColor(cv2.imread(ruta, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)


def main():
    for ruta in sys.argv[1:]:
        cal, inf = autocalibrar(leer_rgb(ruta))
        print(f"\n== {os.path.basename(ruta)}")
        if cal is None:
            print("  NO SE PUEDE:", inf.get("error"))
            continue
        print(f"  región {cal['region']} · base {cal['linea_base_y']} · "
              f"{cal['px_por_ms']:.1f} px/(m/s) · {cal['px_por_s']:.1f} px/s")
        print("  ", json.dumps({k: v for k, v in inf.items()}, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
