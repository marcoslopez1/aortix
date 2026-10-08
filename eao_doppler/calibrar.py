"""
Calibración de una imagen PNG/JPG de Doppler continuo (capturas de pantalla o figuras
de artículos), que no traen la calibración DICOM.

Crea "<imagen>_calibracion.json" con:
  - la región espectral (rectángulo),
  - la fila de la línea de base (0 m/s),
  - píxeles por m/s (a partir de una marca de la escala de velocidad),
  - píxeles por segundo (a partir de dos marcas de tiempo, o de la velocidad de barrido).

Modo interactivo (abre una ventana; haz clic donde se indique):
    python calibrar.py figura.jpg

Modo por argumentos (sin ventana; coordenadas en píxeles de la imagen):
    python calibrar.py figura.jpg --region 60 300 980 735 --base 362 \\
        --marca 602 -4 --tiempo 100 400 1.0
    (marca: fila de la marca y su valor en m/s; tiempo: dos columnas y los segundos entre ellas)
    Alternativa al tiempo: --px-por-s 300
"""
import argparse
import json
import os
import sys

import cv2


def interactivo(ruta):
    import matplotlib.pyplot as plt
    img = cv2.cvtColor(cv2.imread(ruta), cv2.COLOR_BGR2RGB)
    fig, ax = plt.subplots(figsize=(12, 8))
    ax.imshow(img)

    def pedir(n, texto):
        ax.set_title(texto, fontsize=11)
        fig.canvas.draw()
        pts = plt.ginput(n, timeout=0)
        for x, y in pts:
            ax.plot(x, y, "+", color="#ff5a36", ms=14, mew=2)
        return pts

    (x0, y0), (x1, y1) = pedir(2, "1/4 · Clic en la esquina SUPERIOR-IZQUIERDA y luego INFERIOR-DERECHA del espectro")
    (_, yb), = pedir(1, "2/4 · Clic sobre la LÍNEA DE BASE (0 m/s)")
    (_, ym), = pedir(1, "3/4 · Clic sobre una MARCA DE LA ESCALA de velocidad (lo más lejos posible de la base)")
    valor = float(input("   ¿Qué velocidad indica esa marca? (m/s, p. ej. -4): ").replace(",", "."))
    modo = input("   Tiempo: ¿(a) dos marcas de tiempo o (b) velocidad de barrido conocida en px/s? [a/b]: ").strip().lower()
    if modo == "b":
        px_s = float(input("   px por segundo: ").replace(",", "."))
    else:
        (xa, _), (xb, _) = pedir(2, "4/4 · Clic en DOS MARCAS DE TIEMPO (p. ej. dos ondas R o dos marcas del eje)")
        seg = float(input("   ¿Cuántos segundos hay entre esas dos marcas?: ").replace(",", "."))
        px_s = abs(xb - xa) / seg
    plt.close(fig)
    return dict(region=dict(x0=int(min(x0, x1)), y0=int(min(y0, y1)), x1=int(max(x0, x1)), y1=int(max(y0, y1))),
                linea_base_y=int(round(yb)), px_por_ms=abs(ym - yb) / abs(valor), px_por_s=px_s)


def main():
    ap = argparse.ArgumentParser(description="Calibración de imágenes PNG/JPG de Doppler")
    ap.add_argument("imagen")
    ap.add_argument("--region", nargs=4, type=int, metavar=("X0", "Y0", "X1", "Y1"))
    ap.add_argument("--base", type=float, help="fila de la línea de base (0 m/s)")
    ap.add_argument("--marca", nargs=2, type=float, metavar=("FILA", "VALOR_MS"))
    ap.add_argument("--tiempo", nargs=3, type=float, metavar=("COL_A", "COL_B", "SEGUNDOS"))
    ap.add_argument("--px-por-s", type=float)
    a = ap.parse_args()

    if a.region is None:
        calib = interactivo(a.imagen)
    else:
        if a.base is None or a.marca is None or (a.tiempo is None and a.px_por_s is None):
            sys.exit("Faltan argumentos: --base, --marca y (--tiempo o --px-por-s).")
        px_s = a.px_por_s if a.px_por_s else abs(a.tiempo[1] - a.tiempo[0]) / a.tiempo[2]
        x0, y0, x1, y1 = a.region
        calib = dict(region=dict(x0=x0, y0=y0, x1=x1, y1=y1), linea_base_y=int(round(a.base)),
                     px_por_ms=abs(a.marca[0] - a.base) / abs(a.marca[1]), px_por_s=px_s)
    salida = os.path.splitext(a.imagen)[0] + "_calibracion.json"
    with open(salida, "w") as f:
        json.dump(calib, f, indent=2)
    print("Calibración guardada en", salida)
    print(json.dumps(calib, indent=2))


if __name__ == "__main__":
    main()
