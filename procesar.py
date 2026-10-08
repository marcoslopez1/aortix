"""
Procesado de imágenes de Doppler continuo (CW) aórtico — Paso 4 de la prueba de concepto.

Para cada imagen:
  1. Lee el DICOM (o PNG/JPG + archivo de calibración) y localiza la región espectral.
  2. Recorta la región, separa la traza de ECG y elimina anotaciones de color y la línea de base.
  3. Filtra el ruido y extrae la envolvente de la curva (con precisión subpíxel).
  4. Separa los latidos y marca inicio y fin de la eyección.
  5. Calcula las medidas clásicas: Vmax, VTI, gradiente medio y pico, AT, ET, AT/ET.
  6. Normaliza cada curva (tiempo / ET y velocidad / Vmax) y extrae características de
     forma y de textura del espectro (incluida PyRadiomics, si está instalada).
  7. Genera una figura de control con la envolvente dibujada encima.

Uso:
    python procesar.py imagen.dcm --salida resultados
    python procesar.py carpeta_con_imagenes/ --salida resultados
    python procesar.py captura.png --calibracion captura_calibracion.json --salida resultados

Para PNG/JPG se busca automáticamente "<nombre>_calibracion.json" junto a la imagen
(se puede crear con calibrar.py).
"""
import argparse
import glob
import json
import os
import warnings

import cv2
import numpy as np
import pandas as pd
from scipy import ndimage, signal, stats

warnings.filterwarnings("ignore", category=RuntimeWarning)

# Parámetros ajustables ---------------------------------------------------------
PARAM = dict(
    umbral_ruido=3.0,         # señal mínima, en desviaciones del ruido de fondo de cada profundidad
    umbral_relativo=1.0,      # multiplicador del umbral (bajar a 0,8 si la envolvente queda corta)
    suavizado_t=0.002,        # s: suavizado temporal del granulado
    suavizado_v=0.03,         # m/s: suavizado en velocidad del granulado
    mediana_t=0.005,          # s: filtro de mediana sobre la envolvente
    nivel_borde=0.5,          # punto del borde (0 = fondo, 1 = interior) donde se sitúa la envolvente
    v_min_latido=0.6,         # m/s: velocidad mínima para considerar que hay eyección
    nivel_inicio_fin=0.05,    # inicio/fin de eyección: cruce del 5 % de Vmax (sobre el nivel diastólico)
    et_min=0.15, et_max=0.60, # s: duración aceptable de una eyección
    anchura_clic=0.02,        # s: estructuras más estrechas (clics valvulares) se eliminan
    n_puntos_norm=101,        # muestras de la curva normalizada
    tam_img_norm=128,         # tamaño de la imagen normalizada de cada latido (para textura / CNN)
)


# =============================================================================
# 1. Lectura y calibración
# =============================================================================
def leer_imagen(ruta, ruta_calib=None):
    """Devuelve (rgb uint8 HxWx3, calibración dict).

    Si existe "<imagen>_calibracion.json" (o se pasa ruta_calib) se usa esa calibración;
    si no, en un DICOM se lee la de la "Sequence of Ultrasound Regions"."""
    if ruta_calib is None:
        cand = os.path.splitext(ruta)[0] + "_calibracion.json"
        ruta_calib = cand if os.path.exists(cand) else None
    dicom = _es_dicom(ruta)
    if dicom and ruta_calib is None:
        return _leer_dicom(ruta)
    rgb = pixeles_dicom(ruta)[0] if dicom else cv2.cvtColor(cv2.imread(ruta, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
    if ruta_calib is None:
        raise ValueError(f"{ruta}: imagen sin calibración; hay que calibrarla.")
    with open(ruta_calib) as f:
        c = json.load(f)
    return rgb, dict(x0=c["region"]["x0"], y0=c["region"]["y0"], x1=c["region"]["x1"],
                     y1=c["region"]["y1"], linea_base_y=c["linea_base_y"],
                     px_por_ms=c["px_por_ms"], px_por_s=c["px_por_s"], fuente="calibración manual")


def _es_dicom(ruta):
    try:
        with open(ruta, "rb") as f:
            f.seek(128)
            return f.read(4) == b"DICM"
    except OSError:
        return False


def pixeles_dicom(ruta):
    """Píxeles de un DICOM como RGB uint8 (última trama si es multitrama) y el dataset."""
    import pydicom
    ds = pydicom.dcmread(ruta)
    arr = ds.pixel_array
    if getattr(ds, "NumberOfFrames", 1) > 1:
        arr = arr[-1]  # en registros espectrales congelados la última trama suele ser la completa
    pi = str(ds.get("PhotometricInterpretation", "RGB"))
    if pi.startswith("YBR"):
        from pydicom.pixels import convert_color_space
        arr = convert_color_space(arr, pi, "RGB")
    if arr.ndim == 2:
        arr = np.stack([arr] * 3, -1)
    if arr.dtype != np.uint8:
        arr = cv2.normalize(arr, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    return arr, ds


def _leer_dicom(ruta):
    arr, ds = pixeles_dicom(ruta)
    regiones = list(ds.get("SequenceOfUltrasoundRegions", []))
    espectrales = [r for r in regiones if int(r.get("RegionSpatialFormat", 0)) == 3]
    if not espectrales:
        raise ValueError(f"{ruta}: el DICOM no tiene región espectral calibrada "
                         "(Sequence of Ultrasound Regions). Usa calibrar.py.")
    # preferimos CW (RegionDataType 3); si no, la espectral más grande
    cw = [r for r in espectrales if int(r.get("RegionDataType", 0)) == 3]
    r = (cw or espectrales)[0] if len(cw or espectrales) == 1 else max(
        cw or espectrales, key=lambda r: (r.RegionLocationMaxX1 - r.RegionLocationMinX0)
        * (r.RegionLocationMaxY1 - r.RegionLocationMinY0))
    ux, uy = int(r.PhysicalUnitsXDirection), int(r.PhysicalUnitsYDirection)
    if ux != 4 or uy not in (7,):
        raise ValueError(f"Unidades no esperadas en la región (X={ux}, Y={uy}); se esperaba s y cm/s.")
    calib = dict(
        x0=int(r.RegionLocationMinX0), y0=int(r.RegionLocationMinY0),
        x1=int(r.RegionLocationMaxX1) + 1, y1=int(r.RegionLocationMaxY1) + 1,
        linea_base_y=int(r.RegionLocationMinY0) + int(r.ReferencePixelY0),
        px_por_ms=100.0 / abs(float(r.PhysicalDeltaY)),
        px_por_s=1.0 / abs(float(r.PhysicalDeltaX)),
        tipo="CW" if int(r.get("RegionDataType", 0)) == 3 else f"tipo {r.get('RegionDataType')}",
        fabricante=str(ds.get("Manufacturer", "")), fuente="DICOM")
    return arr, calib


# =============================================================================
# 2. Preprocesado: recorte, ECG, anotaciones
# =============================================================================
def preprocesar(rgb, cal):
    reg = rgb[cal["y0"]:cal["y1"], cal["x0"]:cal["x1"]].astype(np.int16)
    sat = reg.max(-1) - reg.min(-1)
    color = sat > 40                                    # ECG, cursores y texto en color
    verde = color & (reg[..., 1] > reg[..., 0] + 30) & (reg[..., 1] > reg[..., 2] + 30)

    # ECG: fila media de los píxeles verdes en cada columna (más arriba = más positivo)
    ecg = np.full(reg.shape[1], np.nan)
    filas = np.arange(reg.shape[0])[:, None]
    cnt = verde.sum(0)
    ok = cnt > 0
    ecg[ok] = -((filas * verde).sum(0)[ok] / cnt[ok])
    ecg = pd.Series(ecg).interpolate(limit_direction="both").to_numpy() if ok.mean() > 0.5 else None

    gris = reg.mean(-1).astype(np.float32)
    # eliminar línea de base y píxeles de color (inpainting)
    mascara = cv2.dilate(color.astype(np.uint8), np.ones((3, 3), np.uint8))
    yb = cal["linea_base_y"] - cal["y0"]
    mascara[max(yb - 1, 0):yb + 2, :] = 1
    gris = cv2.inpaint(gris.astype(np.uint8), mascara, 3, cv2.INPAINT_TELEA).astype(np.float32)
    return gris, ecg, yb


def lado_del_flujo(gris, yb, cal):
    """Devuelve el semiespectro con más energía a alta velocidad (filas = velocidad desde la línea de base)."""
    abajo = gris[yb + 1:, :]
    arriba = gris[:yb, :][::-1, :]
    k = int(1.5 * cal["px_por_ms"])  # mirar por encima de 1,5 m/s
    e_ab = np.percentile(abajo[k:], 99) if abajo.shape[0] > k else 0
    e_ar = np.percentile(arriba[k:], 99) if arriba.shape[0] > k else 0
    if e_ab >= e_ar:
        return abajo, "alejándose (por debajo de la línea de base)"
    return arriba, "acercándose (por encima de la línea de base)"


# =============================================================================
# 3. Envolvente
# =============================================================================
def extraer_envolvente(S, cal, p=PARAM):
    """S: semiespectro (fila 0 = línea de base). Devuelve velocidad de la envolvente (m/s) por columna.

    Umbral adaptativo por profundidad: en cada fila (cada velocidad) se estima el fondo y su
    ruido con la mediana y la MAD a lo largo del tiempo (el chorro ocupa menos de la mitad del
    registro), así que una banda brillante de baja velocidad no "ciega" la detección del chorro."""
    s_t = max(1.0, p["suavizado_t"] * cal["px_por_s"])
    s_v = max(1.0, p["suavizado_v"] * cal["px_por_ms"])
    Sf = cv2.GaussianBlur(cv2.medianBlur(S.astype(np.uint8), 3).astype(np.float32), (0, 0),
                          sigmaX=s_t, sigmaY=s_v)
    Sf, _ = quitar_clics(Sf, cal, p)
    med = np.median(Sf, axis=1, keepdims=True)
    mad = 1.4826 * np.median(np.abs(Sf - med), axis=1, keepdims=True)
    mad = np.maximum(ndimage.uniform_filter1d(mad[:, 0], 9)[:, None], 1.0)
    med = ndimage.uniform_filter1d(med[:, 0], 9)[:, None]
    D = (Sf - med) / mad                                    # señal en unidades de ruido
    b = D > p["umbral_ruido"] * p["umbral_relativo"]
    # eliminar estructuras estrechas (clics) y rellenar huecos del granulado
    kw = max(3, int(round(p["anchura_clic"] * cal["px_por_s"])) | 1)
    b = cv2.morphologyEx(b.astype(np.uint8), cv2.MORPH_OPEN, np.ones((1, kw), np.uint8))
    kv = max(3, int(round(0.1 * cal["px_por_ms"])) | 1)
    b = cv2.morphologyEx(b, cv2.MORPH_CLOSE, np.ones((kv, 3), np.uint8)).astype(bool)
    b = _quitar_pequenos(b, int(0.002 * b.size))

    fondo = float(np.median(Sf[~b])) if (~b).any() else 0.0
    n_f, n_c = Sf.shape
    env_px = np.zeros(n_c)
    for c in range(n_c):
        filas = np.flatnonzero(b[:, c])
        if filas.size < 3:
            continue
        fin = int(filas[-1])
        # tramo continuo que termina en el borde exterior
        ini = fin
        while ini > 0 and b[ini - 1, c]:
            ini -= 1
        if fin - ini < 3:
            continue
        # refinamiento subpíxel: cruce del nivel intermedio entre interior y fondo (en unidades de ruido)
        perfil = D[:, c]
        interior = float(np.median(perfil[ini + (fin - ini) // 2:fin + 1]))
        nivel = p["nivel_borde"] * interior
        hi = min(fin + 6, n_f - 2)
        dentro = np.flatnonzero(perfil[ini:hi] >= nivel)
        cruce = None
        if dentro.size:
            i = ini + int(dentro[-1])       # última fila por encima del nivel
            cruce = i + (perfil[i] - nivel) / max(perfil[i] - perfil[i + 1], 1e-6)
            cruce = min(cruce, i + 1)
        env_px[c] = cruce if cruce is not None else fin
    v = env_px / cal["px_por_ms"]
    v = ndimage.median_filter(v, max(3, int(round(p["mediana_t"] * cal["px_por_s"])) | 1))
    w = max(5, int(round(0.015 * cal["px_por_s"])) | 1)
    v = signal.savgol_filter(v, w, 2)
    return np.clip(v, 0, None), Sf, b, fondo


def quitar_clics(Sf, cal, p=PARAM):
    """Detecta los clics valvulares (líneas verticales finas) y los sustituye por interpolación."""
    kw = max(3, int(round(p["anchura_clic"] * cal["px_por_s"])))
    perfil = Sf.mean(0)
    th = perfil - ndimage.grey_opening(perfil, size=3 * kw)
    mad = np.median(np.abs(th - np.median(th))) + 1e-6
    clic = th > np.median(th) + 6 * mad
    clic = ndimage.binary_dilation(clic, iterations=2)
    # solo estructuras estrechas
    lab, n = ndimage.label(clic)
    for k in range(1, n + 1):
        if (lab == k).sum() > 2 * kw:
            clic[lab == k] = False
    if clic.any() and (~clic).sum() > 2:
        x = np.arange(Sf.shape[1])
        buenos = np.flatnonzero(~clic)
        Sf = Sf.copy()
        for f in range(Sf.shape[0]):
            Sf[f, clic] = np.interp(x[clic], buenos, Sf[f, buenos])
    return Sf, clic


def _quitar_pequenos(b, minimo):
    n, lab, st, _ = cv2.connectedComponentsWithStats(b.astype(np.uint8), 8)
    keep = np.zeros(n, bool)
    keep[1:] = st[1:, cv2.CC_STAT_AREA] >= minimo
    return keep[lab]


# =============================================================================
# 4. Latidos
# =============================================================================
def separar_latidos(v, cal, p=PARAM):
    fs = cal["px_por_s"]
    activo = v > max(p["v_min_latido"], 0.15 * np.percentile(v, 99))
    activo = ndimage.binary_closing(activo, np.ones(max(3, int(0.05 * fs)), bool))
    lab, n = ndimage.label(activo)
    v_diast = float(np.percentile(v[~activo], 50)) if (~activo).any() else 0.0
    latidos = []
    for k in range(1, n + 1):
        idx = np.flatnonzero(lab == k)
        a, z = idx[0], idx[-1]
        if a <= 2 or z >= len(v) - 3:
            continue  # latido cortado por el borde de la imagen
        seg = v[a:z + 1]
        ipk = a + int(np.argmax(seg))
        vpk = v[ipk]
        # inicio y fin: cruce (subpíxel) de un nivel bajo: 5 % de Vmax o, si el fondo
        # diastólico es alto, 0,1 m/s por encima de ese fondo
        nivel = max(p["nivel_inicio_fin"] * vpk, v_diast + 0.1)
        t_on = _cruce(v, ipk, nivel, lado=-1)
        t_off = _cruce(v, ipk, nivel, lado=+1)
        if t_on is None or t_off is None or t_on < 3 or t_off > len(v) - 4:
            continue
        et = (t_off - t_on) / fs
        if not (p["et_min"] <= et <= p["et_max"]):
            continue
        if latidos and t_on < latidos[-1]["i_off"]:
            if vpk <= v[latidos[-1]["i_pk"]]:
                continue
            latidos.pop()
        latidos.append(dict(i_on=t_on, i_off=t_off, i_pk=ipk))
    return latidos


def _cruce(v, ipk, nivel, lado):
    """Posición subpíxel donde la envolvente cae por debajo de 'nivel' desde el pico hacia 'lado'."""
    i = ipk
    while 0 < i < len(v) - 1:
        i += lado
        if v[i] < nivel:
            return i - lado * (nivel - v[i]) / (v[i - lado] - v[i] + 1e-9)
    return None


def curva_latido(v, lat, cal, dt=0.001):
    """Curva del latido remuestreada a 1 ms, con rampas lineales hasta cero en los extremos."""
    fs = cal["px_por_s"]
    t0, t1 = lat["i_on"] / fs, lat["i_off"] / fs
    t = np.arange(t0, t1 + dt / 2, dt)
    tc = np.arange(len(v)) / fs
    vv = np.interp(t, tc, v)
    # extremos: rampa lineal hasta cero desde el primer/último punto por encima del 5 % de Vmax
    vpk = vv.max()
    on_ramp = np.flatnonzero(vv >= PARAM["nivel_inicio_fin"] * vpk)
    if on_ramp.size:
        a, z = on_ramp[0], on_ramp[-1]
        vv[:a] = np.linspace(0, vv[a], a, endpoint=False) if a > 0 else vv[:a]
        if z < len(vv) - 1:
            vv[z + 1:] = np.linspace(vv[z], 0, len(vv) - z - 1)
    return t - t0, np.clip(vv, 0, None)


# =============================================================================
# 5-6. Medidas clásicas, forma normalizada y textura
# =============================================================================
def medidas_clasicas(t, vv):
    ipk = int(np.argmax(vv))
    if 2 <= ipk <= len(vv) - 3:  # ajuste parabólico del pico
        y = vv[ipk - 2:ipk + 3]
        c = np.polyfit(np.arange(-2, 3), y, 2)
        off = -c[1] / (2 * c[0]) if c[0] < 0 else 0
        vmax = float(np.polyval(c, off)) if abs(off) < 2 else float(vv[ipk])
    else:
        vmax = float(vv[ipk])
    # tiempo al pico: máximo de la curva suavizada con una ventana de ~20 ms (estable si el pico es plano)
    dt = t[1] - t[0]
    vs = ndimage.uniform_filter1d(vv, max(3, int(round(0.02 / dt))))
    tpk = float(t[int(np.argmax(vs))])
    et = float(t[-1])
    return dict(
        vmax_ms=vmax, grad_pico_mmHg=4 * vmax ** 2,
        grad_medio_mmHg=float(np.mean(4 * vv ** 2)),
        v_media_ms=float(np.mean(vv)),
        vti_cm=float(np.trapezoid(vv, t) * 100),
        at_ms=float(tpk * 1000), et_ms=et * 1000, at_et=float(tpk / et),
        aceleracion_ms2=vmax / max(tpk, 1e-3), desaceleracion_ms2=vmax / max(et - tpk, 1e-3))


def forma_normalizada(t, vv, n=PARAM["n_puntos_norm"]):
    u = np.linspace(0, 1, n)
    f = np.interp(u * t[-1], t, vv) / max(vv.max(), 1e-6)
    du = u[1] - u[0]
    area = np.trapezoid(f, u)
    w = f / area
    mu = np.trapezoid(u * w, u)
    var = np.trapezoid((u - mu) ** 2 * w, u)
    ipk = int(np.argmax(f))
    df = np.gradient(f, du)
    sobre = lambda nivel: float(np.mean(f >= nivel))  # fracción de la eyección por encima del nivel
    # curvatura en el pico (ajuste cuadrático ±10 % de ET)
    vent = slice(max(ipk - 10, 0), min(ipk + 11, n))
    curv = float(np.polyfit(u[vent] - u[ipk], f[vent], 2)[0] * 2)
    fft = np.abs(np.fft.rfft(f - f.mean()))
    fft = fft / (np.sum(fft) + 1e-9)
    feats = dict(
        forma_u_pico=float(u[ipk]),
        forma_area_norm=float(area),               # factor de forma (= VTI / (Vmax · ET))
        forma_centroide=float(mu),
        forma_dispersion=float(np.sqrt(var)),
        forma_asimetria=float(np.trapezoid(((u - mu) / np.sqrt(var)) ** 3 * w, u)),
        forma_curtosis=float(np.trapezoid(((u - mu) / np.sqrt(var)) ** 4 * w, u)),
        forma_anchura_50=sobre(0.5), forma_anchura_80=sobre(0.8), forma_anchura_90=sobre(0.9),
        forma_pend_subida_max=float(df[:ipk + 1].max()) if ipk > 0 else np.nan,
        forma_pend_bajada_max=float(-df[ipk:].min()),
        forma_curvatura_pico=curv,
        forma_ratio_areas=float(np.trapezoid(f[:ipk + 1], u[:ipk + 1]) /
                                max(np.trapezoid(f[ipk:], u[ipk:]), 1e-6)),
    )
    for k in range(1, 5):
        feats[f"forma_fourier_{k}"] = float(fft[k])
    return u, f, feats


def imagen_normalizada(Sf, v_env, lat, cal, tam=PARAM["tam_img_norm"]):
    """Recorta el latido y lo remuestrea a una rejilla tam x tam en (t/ET, v/Vmax), con margen 20 %."""
    a, z = int(np.floor(lat["i_on"])), int(np.ceil(lat["i_off"]))
    vpk = v_env[lat["i_pk"]]
    filas_max = int(min(Sf.shape[0], np.ceil(1.2 * vpk * cal["px_por_ms"])))
    sub = Sf[:filas_max, max(a, 0):z + 1]
    img = cv2.resize(sub, (tam, int(round(tam * 1.2))), interpolation=cv2.INTER_AREA)
    # máscara: por debajo de la envolvente normalizada
    env_sub = v_env[max(a, 0):z + 1] / vpk
    env_r = np.interp(np.linspace(0, 1, tam), np.linspace(0, 1, len(env_sub)), env_sub)
    filas = np.linspace(0, 1.2, img.shape[0])[:, None]
    mask = (filas <= env_r[None, :]) & (filas > 0.03)
    return img, mask


def textura(Sf, v_env, lat, cal, fondo, img_n, mask_n):
    a, z = int(np.ceil(lat["i_on"])), int(np.floor(lat["i_off"]))
    vpk = v_env[lat["i_pk"]]
    cols = range(a, z + 1)
    modal, iqr, conc, nitidez, pluma = [], [], [], [], []
    for c in cols:
        e = v_env[c] * cal["px_por_ms"]
        if v_env[c] < 0.3 * vpk or e < 8:
            continue
        p = Sf[2:int(e), c] - fondo
        p = np.clip(p, 0, None)
        if p.sum() <= 0:
            continue
        vr = (np.arange(2, int(e)) / e)  # velocidad relativa a la envolvente
        modal.append(vr[int(np.argmax(ndimage.gaussian_filter1d(p, 2)))])
        cdf = np.cumsum(p) / p.sum()
        iqr.append(np.interp(0.75, cdf, vr) - np.interp(0.25, cdf, vr))
        conc.append([p[(vr >= lo) & (vr < lo + 0.25)].mean() / p.mean() for lo in (0, .25, .5, .75)])
        # borde: pendiente máxima y anchura 90 %->10 % alrededor de la envolvente
        ie = int(round(e))
        w = Sf[max(ie - 15, 0):min(ie + 25, Sf.shape[0]), c]
        if len(w) > 5:
            g = -np.gradient(ndimage.gaussian_filter1d(w, 1))
            nitidez.append(g.max() / max(w.max() - fondo, 1e-6) * cal["px_por_ms"])  # 1/(m/s)
            hi, lo = fondo + 0.9 * (w.max() - fondo), fondo + 0.1 * (w.max() - fondo)
            ih = np.flatnonzero(w >= hi)
            il = np.flatnonzero(w <= lo)
            if ih.size and il.size and il[il > ih[-1]].size:
                pluma.append((il[il > ih[-1]][0] - ih[-1]) / cal["px_por_ms"])
    conc = np.array(conc) if conc else np.full((1, 4), np.nan)
    vals = img_n[mask_n]
    rel = vals / (np.median(vals) + 1e-6)
    hist, _ = np.histogram(vals, bins=32, range=(0, 255))
    pr = hist / max(hist.sum(), 1)
    feats = dict(
        tex_intensidad_media=float(vals.mean()), tex_intensidad_cv=float(vals.std() / (vals.mean() + 1e-6)),
        tex_asimetria=float(stats.skew(rel)), tex_curtosis=float(stats.kurtosis(rel)),
        tex_entropia=float(-(pr[pr > 0] * np.log2(pr[pr > 0])).sum()),
        tex_velocidad_modal_rel=float(np.nanmedian(modal)) if modal else np.nan,
        tex_ensanchamiento_iqr_rel=float(np.nanmedian(iqr)) if iqr else np.nan,
        tex_densidad_0_25=float(np.nanmean(conc[:, 0])), tex_densidad_25_50=float(np.nanmean(conc[:, 1])),
        tex_densidad_50_75=float(np.nanmean(conc[:, 2])), tex_densidad_75_100=float(np.nanmean(conc[:, 3])),
        tex_nitidez_borde=float(np.nanmedian(nitidez)) if nitidez else np.nan,
        tex_anchura_pluma_ms=float(np.nanmedian(pluma)) if pluma else np.nan,
    )
    feats.update(_glcm(img_n, mask_n))
    feats.update(_pyradiomics(img_n, mask_n))
    return feats


def _glcm(img, mask, niveles=32):
    from skimage.feature import graycomatrix, graycoprops
    q = (np.clip(img, 0, 255) / 256 * (niveles - 1)).astype(np.uint8) + 1
    q[~mask] = 0
    m = graycomatrix(q, [1, 2], [0, np.pi / 2], levels=niveles, symmetric=True, normed=False)
    m = m[1:, 1:].astype(float)
    m /= m.sum(axis=(0, 1), keepdims=True) + 1e-9
    out = {}
    for prop in ("contrast", "homogeneity", "energy", "correlation", "dissimilarity"):
        out[f"glcm_{prop}"] = float(graycoprops(m, prop).mean())
    return out


def _pyradiomics(img, mask):
    try:
        import SimpleITK as sitk
        from radiomics import featureextractor, logger
        logger.setLevel(40)
    except ImportError:
        return {}
    ext = featureextractor.RadiomicsFeatureExtractor(force2D=True, binWidth=8, label=1)
    ext.disableAllFeatures()
    for clase in ("firstorder", "glcm", "glrlm", "glszm"):
        ext.enableFeatureClassByName(clase)
    im = sitk.GetImageFromArray(img.astype(np.float32)[None])
    ma = sitk.GetImageFromArray(mask.astype(np.uint8)[None])
    try:
        res = ext.execute(im, ma)
    except Exception:
        return {}
    return {"rad_" + k.replace("original_", ""): float(v) for k, v in res.items()
            if k.startswith("original_")}


def ecg_r(ecg, cal):
    if ecg is None:
        return []
    x = ecg - np.median(ecg)
    if x.max() <= 0:
        return []
    picos, _ = signal.find_peaks(x, height=0.5 * x.max(), distance=int(0.3 * cal["px_por_s"]))
    return list(picos)


# =============================================================================
# 7. Pipeline completo + figura de control
# =============================================================================
def procesar(ruta, salida, ruta_calib=None, ruta_verdad=None, p=PARAM, nombre=None):
    nombre = nombre or os.path.splitext(os.path.basename(ruta))[0]
    rgb, cal = leer_imagen(ruta, ruta_calib)
    gris, ecg, yb = preprocesar(rgb, cal)
    S, direccion = lado_del_flujo(gris, yb, cal)
    v, Sf, binaria, fondo = extraer_envolvente(S, cal, p)
    lats = separar_latidos(v, cal, p)
    r_peaks = ecg_r(ecg, cal)

    filas, curvas, imgs = [], [], []
    for k, lat in enumerate(lats, 1):
        t, vv = curva_latido(v, lat, cal)
        m = medidas_clasicas(t, vv)
        u, f, fm = forma_normalizada(t, vv)
        img_n, mask_n = imagen_normalizada(Sf, v, lat, cal)
        tx = textura(Sf, v, lat, cal, fondo, img_n, mask_n)
        previos = [r for r in r_peaks if r < lat["i_on"]]
        r_on = (lat["i_on"] - previos[-1]) / cal["px_por_s"] * 1000 if previos else np.nan
        filas.append(dict(imagen=nombre, latido=k, inicio_s=lat["i_on"] / cal["px_por_s"],
                          r_a_inicio_ms=r_on, **m, **fm, **tx))
        curvas.append(f)
        imgs.append(img_n)
        cv2.imwrite(os.path.join(salida, f"{nombre}_latido{k}_normalizado.png"),
                    np.clip(img_n, 0, 255).astype(np.uint8))

    df = pd.DataFrame(filas)
    if len(r_peaks) > 1:
        fc = 60 / (np.median(np.diff(r_peaks)) / cal["px_por_s"])
    elif len(lats) > 1:
        fc = 60 / (np.median(np.diff([l["i_on"] for l in lats])) / cal["px_por_s"])
    else:
        fc = np.nan
    resumen = dict(imagen=nombre, n_latidos=len(lats), fc_lpm=fc, direccion_flujo=direccion,
                   calibracion=cal.get("fuente"), px_por_ms=cal["px_por_ms"], px_por_s=cal["px_por_s"])
    if len(df):
        num = df.select_dtypes("number").drop(columns=["latido", "inicio_s"])
        resumen.update(num.mean().to_dict())
        for col in ("vmax_ms", "grad_medio_mmHg", "vti_cm", "at_et"):
            resumen[f"cv_{col}"] = float(df[col].std() / df[col].mean()) if len(df) > 1 else np.nan
        curva_media = np.mean(curvas, 0)
        np.savetxt(os.path.join(salida, f"{nombre}_curva_normalizada.csv"),
                   np.column_stack([np.linspace(0, 1, len(curva_media)), curva_media, *curvas]),
                   delimiter=",", header="u,media," + ",".join(f"latido{i+1}" for i in range(len(curvas))),
                   comments="")
    df.to_csv(os.path.join(salida, f"{nombre}_latidos.csv"), index=False)

    verdad = None
    if ruta_verdad is None:
        cand = os.path.splitext(ruta)[0] + "_verdad.json"
        ruta_verdad = cand if os.path.exists(cand) else None
    if ruta_verdad:
        with open(ruta_verdad) as fh:
            verdad = json.load(fh)
    figura_control(rgb, cal, S, v, lats, curvas, r_peaks, direccion, df, resumen, verdad,
                   os.path.join(salida, f"{nombre}_control.png"))
    return resumen, df, verdad


def emparejar(df, verdad, tol=0.06):
    """Empareja latidos medidos y reales por el instante de inicio (tolerancia en s)."""
    pares = []
    for i, row in df.iterrows():
        cand = [b for b in verdad["latidos"] if abs(b["inicio_s"] - row["inicio_s"]) < tol]
        if cand:
            pares.append((i, min(cand, key=lambda b: abs(b["inicio_s"] - row["inicio_s"]))))
    return pares


def figura_control(rgb, cal, S, v, lats, curvas, r_peaks, direccion, df, resumen, verdad, ruta):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    fs, pm = cal["px_por_s"], cal["px_por_ms"]
    fig = plt.figure(figsize=(15, 9.5))
    gs = fig.add_gridspec(2, 3, height_ratios=[1, 1.05], width_ratios=[1.1, 1.3, 1])
    ax0 = fig.add_subplot(gs[0, 0])
    ax0.imshow(rgb)
    ax0.add_patch(Rectangle((cal["x0"], cal["y0"]), cal["x1"] - cal["x0"], cal["y1"] - cal["y0"],
                            fill=False, ec="#ff5a36", lw=1.5))
    ax0.axhline(cal["linea_base_y"], color="#2fb5ff", lw=0.8, ls="--")
    ax0.set_title("Imagen original · región espectral", fontsize=10)
    ax0.axis("off")

    ax1 = fig.add_subplot(gs[0, 1:])
    t = np.arange(S.shape[1]) / fs
    vmax_vis = S.shape[0] / pm
    ax1.imshow(S, cmap="gray", aspect="auto", extent=[0, t[-1], vmax_vis, 0])
    ax1.plot(t, v, color="#ff5a36", lw=1.2, label="envolvente")
    for k, lat in enumerate(lats, 1):
        ax1.axvline(lat["i_on"] / fs, color="#3ddc84", lw=0.9)
        ax1.axvline(lat["i_off"] / fs, color="#2fb5ff", lw=0.9)
        ax1.plot(lat["i_pk"] / fs, v[lat["i_pk"]], "o", ms=4, color="#ffd23f")
        ax1.text(lat["i_pk"] / fs, v[lat["i_pk"]] + 0.25, f"L{k}", color="#ffd23f", ha="center", fontsize=8)
    for r in r_peaks:
        ax1.plot(r / fs, 0.08, "v", color="#3ddc84", ms=5)
    ax1.set_ylim(vmax_vis, 0)
    ax1.set_xlabel("tiempo (s)")
    ax1.set_ylabel("velocidad (m/s)")
    ax1.set_title(f"Semiespectro del flujo aórtico ({direccion}) · verde = inicio, azul = fin, ▼ = onda R", fontsize=10)

    ax2 = fig.add_subplot(gs[1, 0])
    u = np.linspace(0, 1, PARAM["n_puntos_norm"])
    for k, f in enumerate(curvas, 1):
        ax2.plot(u, f, lw=1, alpha=0.6, label=f"L{k}")
    if curvas:
        ax2.plot(u, np.mean(curvas, 0), color="black", lw=2, label="media")
    ax2.set_xlabel("tiempo / ET")
    ax2.set_ylabel("velocidad / Vmax")
    ax2.set_title("Curvas normalizadas (forma pura)", fontsize=10)
    ax2.legend(fontsize=8, frameon=False)
    ax2.grid(alpha=0.3)

    ax3 = fig.add_subplot(gs[1, 1:])
    ax3.axis("off")
    if len(df):
        claves = [("Vmax (m/s)", "vmax_ms", "{:.2f}"), ("Grad. medio (mmHg)", "grad_medio_mmHg", "{:.1f}"),
                  ("Grad. pico (mmHg)", "grad_pico_mmHg", "{:.1f}"), ("VTI (cm)", "vti_cm", "{:.1f}"),
                  ("AT (ms)", "at_ms", "{:.0f}"), ("ET (ms)", "et_ms", "{:.0f}"), ("AT/ET", "at_et", "{:.3f}")]
        verdad_k = {"vmax_ms": "vmax_ms", "grad_medio_mmHg": "grad_medio_mmHg", "grad_pico_mmHg": "grad_pico_mmHg",
                    "vti_cm": "vti_cm", "at_ms": "at_ms", "et_ms": "et_ms", "at_et": "at_et"}
        cab = ["Medida"] + [f"L{k}" for k in df["latido"]] + ["Media", "CV"]
        if verdad:
            cab += ["Real (media)", "Error %"]
        celdas = []
        for lab, col, fmt in claves:
            fila = [lab] + [fmt.format(x) for x in df[col]] + [fmt.format(df[col].mean()),
                                                               f"{df[col].std() / df[col].mean() * 100:.1f} %" if len(df) > 1 else "–"]
            if verdad:
                emparejados = emparejar(df, verdad)
                if not emparejados:
                    fila += ["–", "–"]
                    celdas.append(fila)
                    continue
                medido = np.mean([df.loc[i, col] for i, _ in emparejados])
                real = np.mean([b[verdad_k[col]] for _, b in emparejados])
                fila[-2] = fmt.format(medido)
                fila += [fmt.format(real), f"{(medido - real) / real * 100:+.1f} %"]
            celdas.append(fila)
        tb = ax3.table(cellText=celdas, colLabels=cab, loc="upper center", cellLoc="center")
        tb.auto_set_font_size(False)
        tb.set_fontsize(9)
        tb.scale(1, 1.45)
        extra = (f"Latidos analizados: {len(df)}   ·   FC: {resumen['fc_lpm']:.0f} lpm   ·   "
                 f"Calibración: {resumen['calibracion']} ({cal['px_por_ms']:.1f} px/(m/s), {cal['px_por_s']:.0f} px/s)\n"
                 f"Forma: pico en {df['forma_u_pico'].mean():.2f}·ET · factor de forma {df['forma_area_norm'].mean():.3f} · "
                 f"asimetría {df['forma_asimetria'].mean():+.3f} · anchura al 80 % {df['forma_anchura_80'].mean():.2f}\n"
                 f"Espectro: velocidad modal {df['tex_velocidad_modal_rel'].mean():.2f}·envolvente · "
                 f"ensanchamiento IQR {df['tex_ensanchamiento_iqr_rel'].mean():.2f} · "
                 f"anchura del plumeado {df['tex_anchura_pluma_ms'].mean():.2f} m/s")
        ax3.text(0.5, 0.08, extra, ha="center", va="bottom", fontsize=9, transform=ax3.transAxes)
    else:
        ax3.text(0.5, 0.5, "No se detectaron latidos completos", ha="center", fontsize=12)
    fig.suptitle(f"Control de calidad · {os.path.basename(ruta).replace('_control.png', '')}", fontsize=12, x=0.02, ha="left")
    fig.tight_layout()
    fig.savefig(ruta, dpi=110)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description="Procesado de Doppler continuo aórtico")
    ap.add_argument("entradas", nargs="+", help="archivos DICOM/PNG/JPG o carpetas")
    ap.add_argument("--salida", default="resultados")
    ap.add_argument("--calibracion", help="JSON de calibración (solo para una imagen PNG/JPG)")
    a = ap.parse_args()
    os.makedirs(a.salida, exist_ok=True)
    rutas = []
    for e in a.entradas:
        if os.path.isdir(e):
            for patron in ("*.dcm", "*.png", "*.jpg", "*.jpeg"):
                rutas += [r for r in glob.glob(os.path.join(e, patron)) if "_control" not in r]
        else:
            rutas.append(e)
    resumenes = []
    raices = [os.path.splitext(os.path.basename(r))[0] for r in rutas]
    for r in sorted(rutas):
        raiz, ext = os.path.splitext(os.path.basename(r))
        nombre = f"{raiz}_{ext[1:]}" if raices.count(raiz) > 1 else raiz
        try:
            res, df, _ = procesar(r, a.salida, a.calibracion if len(rutas) == 1 else None, nombre=nombre)
            resumenes.append(res)
            print(f"OK  {os.path.basename(r)}: {res['n_latidos']} latidos, "
                  f"Vmax {res.get('vmax_ms', float('nan')):.2f} m/s, "
                  f"grad. medio {res.get('grad_medio_mmHg', float('nan')):.1f} mmHg, "
                  f"AT/ET {res.get('at_et', float('nan')):.3f}")
        except Exception as ex:
            print(f"ERROR {os.path.basename(r)}: {ex}")
            resumenes.append(dict(imagen=os.path.basename(r), error=str(ex)))
    pd.DataFrame(resumenes).to_csv(os.path.join(a.salida, "resumen_imagenes.csv"), index=False)
    print("Resultados en", a.salida)


if __name__ == "__main__":
    main()
