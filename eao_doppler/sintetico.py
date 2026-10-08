"""
Generador de imágenes SINTÉTICAS de Doppler continuo (CW) aórtico.

Sirve para probar el procesado con valores conocidos (Vmax, VTI, gradiente
medio, AT, ET) antes de usar imágenes reales. Produce:
  - un DICOM con la calibración en "Sequence of Ultrasound Regions"
  - un PNG equivalente (como si fuera una captura de pantalla)
  - un JSON con la "verdad" (valores reales de cada latido)

Uso:
    python sintetico.py --caso severa  --salida datos_sinteticos
    python sintetico.py --caso moderada --salida datos_sinteticos
"""
import argparse
import json
import os

import cv2
import numpy as np

# ---------------------------------------------------------------- geometría
W, H = 1024, 768
REG_X0, REG_X1 = 60, 980          # región espectral (columnas)
REG_Y0, REG_Y1 = 300, 735         # región espectral (filas)
BASELINE_Y = 362                  # fila de la línea de base
PX_PER_MS = 60.0                  # píxeles por m/s
PX_PER_S = 300.0                  # píxeles por segundo (barrido ~100 mm/s)

CASOS = {
    # vmax (m/s), ET (s), u_pico = AT/ET, redondez (<1 = pico más redondeado, >1 = más triangular)
    "severa":   dict(vmax=4.6, et=0.330, u_pico=0.42, redondez=0.75, hr=68),
    "moderada": dict(vmax=3.3, et=0.300, u_pico=0.30, redondez=1.25, hr=72),
    "leve":     dict(vmax=2.5, et=0.290, u_pico=0.25, redondez=1.40, hr=75),
}


def perfil(u, u_pico, redondez):
    """Forma normalizada (0..1) de la velocidad durante la eyección, u = t/ET en [0,1].

    Seno con el tiempo deformado para que el pico caiga en u_pico; el exponente
    controla lo redondeado (severa) o triangular (no severa) de la curva."""
    u = np.clip(u, 0, 1)
    g = np.where(u < u_pico, 0.5 * u / u_pico, 0.5 + 0.5 * (u - u_pico) / (1 - u_pico))
    return np.sin(np.pi * g) ** redondez


def ecg_template(t):
    """Complejo PQRST simplificado; t en segundos relativo a la onda R."""
    g = lambda mu, s, a: a * np.exp(-((t - mu) ** 2) / (2 * s ** 2))
    return (g(-0.16, 0.025, 0.12) + g(-0.025, 0.008, -0.12) + g(0, 0.010, 1.0)
            + g(0.025, 0.010, -0.25) + g(0.25, 0.045, 0.30))


def generar(caso, semilla=0):
    rng = np.random.default_rng(semilla)
    p = CASOS[caso]
    rw, rh = REG_X1 - REG_X0, REG_Y1 - REG_Y0
    t_cols = np.arange(rw) / PX_PER_S                         # tiempo de cada columna
    v_rows = (np.arange(rh) + REG_Y0 - BASELINE_Y) / PX_PER_MS  # velocidad de cada fila (+ = hacia abajo = alejándose)

    # ------------------------------------------------ latidos (R-R con variabilidad)
    rr_med = 60.0 / p["hr"]
    t_r = 0.22
    latidos, r_times = [], []
    while t_r < t_cols[-1] + 0.5:
        r_times.append(t_r)
        onset = t_r + 0.065
        et = p["et"] * rng.normal(1, 0.02)
        vmax = p["vmax"] * rng.normal(1, 0.02)
        latidos.append(dict(onset=onset, et=et, vmax=vmax))
        t_r += rr_med * rng.normal(1, 0.03)

    # envolvente verdadera a alta resolución para la "verdad"
    verdad = []
    for b in latidos:
        if b["onset"] < 0 or b["onset"] + b["et"] > t_cols[-1]:
            continue  # latido incompleto: no cuenta
        tt = np.linspace(0, b["et"], 4001)
        vv = b["vmax"] * perfil(tt / b["et"], p["u_pico"], p["redondez"])
        ipk = int(np.argmax(vv))
        verdad.append(dict(
            inicio_s=round(b["onset"], 4), vmax_ms=round(float(vv.max()), 3),
            vti_cm=round(float(np.trapezoid(vv, tt) * 100), 2),
            grad_medio_mmHg=round(float(np.mean(4 * vv ** 2)), 2),
            grad_pico_mmHg=round(float(4 * vv.max() ** 2), 2),
            at_ms=round(float(tt[ipk] * 1000), 1), et_ms=round(b["et"] * 1000, 1),
            at_et=round(float(tt[ipk] / b["et"]), 3)))

    # ------------------------------------------------ espectro
    spec = np.zeros((rh, rw), np.float32)
    V = v_rows[:, None]
    for b in latidos:
        u = (t_cols - b["onset"]) / b["et"]
        on = (u >= 0) & (u <= 1)
        if not on.any():
            continue
        env = np.zeros(rw)
        env[on] = b["vmax"] * perfil(u[on], p["u_pico"], p["redondez"])
        E = env[None, :]
        cols = on[None, :]
        # relleno del espectro CW (todas las velocidades entre 0 y la envolvente)
        fill = 0.45 + 0.25 * (V / np.maximum(E, 1e-3))
        # banda densa del flujo del TSVI (~1 m/s)
        vl = 0.24 * E + 0.05
        fill += 0.55 * np.exp(-((V - vl) ** 2) / (2 * 0.12 ** 2))
        # borde suave + "plumeado" por encima de la envolvente
        borde = 1 / (1 + np.exp((V - E) / 0.035))
        pluma = 0.22 * np.exp(-np.clip(V - E, 0, None) / 0.08) * (1 - borde)
        jet = (fill * borde + pluma) * cols * (V > 0)
        spec += jet
        # clics de apertura y cierre valvular (líneas verticales finas)
        for tc, a in ((b["onset"], 0.7), (b["onset"] + b["et"] + 0.01, 1.0)):
            c = int(round(tc * PX_PER_S))
            if 0 <= c < rw:
                w = np.exp(-(np.arange(rw) - c) ** 2 / (2 * 1.2 ** 2))[None, :]
                spec += a * w * np.exp(-np.abs(V) / 0.35)  # como en registros reales: el clic se limita a baja velocidad
        # flujo mitral diastólico, débil, por encima de la línea de base (velocidad negativa)
        tm = b["onset"] + b["et"] + 0.09
        for dt, vm, a in ((0.0, 0.9, 0.22), (rr_med - 0.62, 0.6, 0.18)):
            uu = (t_cols - (tm + dt)) / 0.16
            m = np.where((uu >= 0) & (uu <= 1), vm * np.sin(np.pi * np.clip(uu, 0, 1)) ** 1.3, 0)
            spec += a * ((-V) < m[None, :]) * (V < 0) * 1.0

    # granulado (speckle) y ruido de fondo
    speckle = rng.exponential(1.0, spec.shape).astype(np.float32)
    speckle = cv2.GaussianBlur(speckle, (0, 0), sigmaX=0.6, sigmaY=1.2)
    spec = spec * (0.55 + 0.45 * speckle)
    spec += 0.035 * rng.exponential(1.0, spec.shape)
    # compresión logarítmica + ganancia
    img = np.log1p(6 * spec) / np.log1p(6 * 1.6)
    img = np.clip(img, 0, 1)
    gris = (img * 235).astype(np.uint8)

    # ------------------------------------------------ montaje de la pantalla
    canvas = np.zeros((H, W, 3), np.uint8)
    canvas[REG_Y0:REG_Y1, REG_X0:REG_X1] = gris[..., None]
    # línea de base
    cv2.line(canvas, (REG_X0, BASELINE_Y), (REG_X1 - 1, BASELINE_Y), (150, 150, 150), 1)
    # escala de velocidad a la derecha
    for k in range(-1, 7):
        y = int(BASELINE_Y + k * PX_PER_MS)
        if REG_Y0 <= y < REG_Y1:
            cv2.line(canvas, (REG_X1 + 2, y), (REG_X1 + 10, y), (200, 200, 200), 1)
            cv2.putText(canvas, f"{-k}", (REG_X1 + 13, y + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)
    cv2.putText(canvas, "m/s", (REG_X1 + 5, REG_Y0 - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)
    # ECG (verde) en la parte inferior de la región
    t_hr = t_cols
    ecg = np.zeros_like(t_hr)
    for tr in r_times:
        ecg += ecg_template(t_hr - tr)
    ecg += 0.02 * rng.normal(size=ecg.shape)
    ys = (REG_Y1 - 22 - ecg * 26).astype(int)
    pts = np.stack([np.arange(rw) + REG_X0, ys], 1).reshape(-1, 1, 2)
    cv2.polylines(canvas, [pts], False, (40, 220, 40), 1)
    # cabecera con texto (como en un ecógrafo; se eliminará al recortar)
    cv2.putText(canvas, "HOSPITAL DEMO   ID: ANONIMIZADO   CW  AV", (12, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (230, 230, 230), 1)
    cv2.putText(canvas, f"AV Vmax {verdad[0]['vmax_ms']:.2f} m/s", (12, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (230, 230, 120), 1)
    # miniatura 2D con cursor CW
    sector = np.zeros((230, 300), np.uint8)
    cv2.ellipse(sector, (150, 0), (220, 220), 90, -35, 35, 255, -1)
    tex = (rng.random((230, 300)) * 120).astype(np.uint8)
    sector = cv2.bitwise_and(tex, tex, mask=sector)
    canvas[55:285, 360:660] = sector[..., None]
    cv2.line(canvas, (510, 55), (530, 280), (90, 220, 255), 1)

    meta = dict(
        caso=caso, semilla=semilla,
        region=dict(x0=REG_X0, y0=REG_Y0, x1=REG_X1, y1=REG_Y1),
        linea_base_y=BASELINE_Y, px_por_ms=PX_PER_MS, px_por_s=PX_PER_S,
        parametros=p, latidos=verdad)
    return canvas, meta


def guardar_dicom(rgb, meta, ruta):
    import pydicom
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid

    fm = FileMetaDataset()
    fm.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.6.1"  # Ultrasound Image Storage
    fm.MediaStorageSOPInstanceUID = generate_uid()
    fm.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = Dataset()
    ds.file_meta = fm
    ds.SOPClassUID = fm.MediaStorageSOPClassUID
    ds.SOPInstanceUID = fm.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID, ds.SeriesInstanceUID = generate_uid(), generate_uid()
    ds.PatientName, ds.PatientID = "ANON^SINTETICO", "P000"
    ds.Modality, ds.Manufacturer = "US", "SINTETICO"
    ds.Rows, ds.Columns = rgb.shape[:2]
    ds.SamplesPerPixel, ds.PhotometricInterpretation, ds.PlanarConfiguration = 3, "RGB", 0
    ds.BitsAllocated, ds.BitsStored, ds.HighBit, ds.PixelRepresentation = 8, 8, 7, 0
    ds.PixelData = rgb.tobytes()

    r = meta["region"]
    reg = Dataset()
    reg.RegionSpatialFormat = 3        # espectral
    reg.RegionDataType = 3             # Doppler continuo (CW)
    reg.RegionFlags = 0
    reg.RegionLocationMinX0, reg.RegionLocationMinY0 = r["x0"], r["y0"]
    reg.RegionLocationMaxX1, reg.RegionLocationMaxY1 = r["x1"] - 1, r["y1"] - 1
    reg.PhysicalUnitsXDirection = 4    # segundos
    reg.PhysicalUnitsYDirection = 7    # cm/s
    reg.PhysicalDeltaX = 1.0 / meta["px_por_s"]
    reg.PhysicalDeltaY = -100.0 / meta["px_por_ms"]   # negativo: por debajo de la línea de base = alejándose
    reg.ReferencePixelX0 = 0
    reg.ReferencePixelY0 = meta["linea_base_y"] - r["y0"]
    reg.ReferencePixelPhysicalValueX = 0.0
    reg.ReferencePixelPhysicalValueY = 0.0
    ds.SequenceOfUltrasoundRegions = [reg]
    ds.save_as(ruta, enforce_file_format=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--caso", choices=list(CASOS), default="severa")
    ap.add_argument("--semilla", type=int, default=0)
    ap.add_argument("--salida", default="datos_sinteticos")
    a = ap.parse_args()
    os.makedirs(a.salida, exist_ok=True)
    rgb, meta = generar(a.caso, a.semilla)
    base = os.path.join(a.salida, f"sintetico_{a.caso}")
    cv2.imwrite(base + ".png", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    guardar_dicom(rgb, meta, base + ".dcm")
    # calibración para el PNG (en una captura no hay metadatos DICOM)
    calib = dict(region=meta["region"], linea_base_y=meta["linea_base_y"],
                 px_por_ms=meta["px_por_ms"], px_por_s=meta["px_por_s"])
    with open(base + "_calibracion.json", "w") as f:
        json.dump(calib, f, indent=2)
    with open(base + "_verdad.json", "w") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    print("Generado:", base + ".{png,dcm}", "| latidos completos:", len(meta["latidos"]))


if __name__ == "__main__":
    main()
