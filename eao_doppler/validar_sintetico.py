"""
Validación del procesado con imágenes sintéticas de valores conocidos.

Genera varias imágenes por caso (severa / moderada / leve) con distinta semilla
(ruido, variabilidad latido a latido), las procesa y compara cada latido medido con
su valor real. Resume error medio (sesgo), límites de acuerdo de Bland-Altman y
error relativo; y guarda una figura de Bland-Altman.

Uso:
    python validar_sintetico.py --n 5 --salida validacion
"""
import argparse
import os

import cv2
import numpy as np
import pandas as pd

import procesar as P
import sintetico as G

MEDIDAS = [("vmax_ms", "Vmax (m/s)"), ("grad_medio_mmHg", "Gradiente medio (mmHg)"),
           ("grad_pico_mmHg", "Gradiente pico (mmHg)"), ("vti_cm", "VTI (cm)"),
           ("at_ms", "AT (ms)"), ("et_ms", "ET (ms)"), ("at_et", "AT/ET")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=5, help="imágenes por caso")
    ap.add_argument("--salida", default="validacion")
    a = ap.parse_args()
    dir_img = os.path.join(a.salida, "imagenes")
    dir_res = os.path.join(a.salida, "procesado")
    os.makedirs(dir_img, exist_ok=True)
    os.makedirs(dir_res, exist_ok=True)

    filas, resumen_img = [], []
    for caso in ("severa", "moderada", "leve"):
        for semilla in range(a.n):
            rgb, meta = G.generar(caso, semilla)
            ruta = os.path.join(dir_img, f"{caso}_{semilla}.dcm")
            G.guardar_dicom(rgb, meta, ruta)
            res, df, _ = P.procesar(ruta, dir_res, ruta_verdad=None)
            res["caso"] = caso
            resumen_img.append(res)
            for i, b in P.emparejar(df, meta):
                for col, _ in MEDIDAS:
                    filas.append(dict(caso=caso, semilla=semilla, latido=int(df.loc[i, "latido"]),
                                      medida=col, medido=float(df.loc[i, col]), real=float(b[col])))
            n_real = len(meta["latidos"])
            print(f"{caso:9s} semilla {semilla}: {len(df)} latidos detectados / {n_real} reales")

    d = pd.DataFrame(filas)
    d["error"] = d["medido"] - d["real"]
    d["error_rel_%"] = d["error"] / d["real"] * 100
    d.to_csv(os.path.join(a.salida, "comparacion_latidos.csv"), index=False)

    tabla = []
    for col, nombre in MEDIDAS:
        x = d[d.medida == col]
        sesgo, sd = x["error"].mean(), x["error"].std()
        icc = icc_absoluto(x["medido"].to_numpy(), x["real"].to_numpy())
        tabla.append({"Medida": nombre, "n latidos": len(x), "Sesgo": round(sesgo, 3),
                      "LdA inferior": round(sesgo - 1.96 * sd, 3), "LdA superior": round(sesgo + 1.96 * sd, 3),
                      "Error relativo medio (%)": round(x["error_rel_%"].mean(), 2),
                      "Error absoluto medio (%)": round(x["error_rel_%"].abs().mean(), 2),
                      "ICC(2,1)": round(icc, 4)})
    t = pd.DataFrame(tabla)
    t.to_csv(os.path.join(a.salida, "resumen_validacion.csv"), index=False)
    print()
    print(t.to_string(index=False))

    # forma: ¿separa severa de no severa? (orientativo)
    r = pd.DataFrame(resumen_img)
    cols = ["vmax_ms", "at_et", "forma_u_pico", "forma_area_norm", "forma_asimetria",
            "forma_anchura_80", "forma_curvatura_pico", "tex_velocidad_modal_rel"]
    g = r.groupby("caso")[cols].mean().round(3)
    g.to_csv(os.path.join(a.salida, "forma_por_caso.csv"))
    print()
    print(g.to_string())
    bland_altman(d, os.path.join(a.salida, "bland_altman.png"))


def icc_absoluto(x, y):
    """ICC(2,1) de acuerdo absoluto (Shrout & Fleiss) entre dos 'observadores'."""
    m = np.column_stack([x, y])
    n, k = m.shape
    gm = m.mean()
    msr = k * ((m.mean(1) - gm) ** 2).sum() / (n - 1)
    msc = n * ((m.mean(0) - gm) ** 2).sum() / (k - 1)
    sse = ((m - m.mean(1, keepdims=True) - m.mean(0, keepdims=True) + gm) ** 2).sum()
    mse = sse / ((n - 1) * (k - 1))
    return (msr - mse) / (msr + (k - 1) * mse + k * (msc - mse) / n)


def bland_altman(d, ruta):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    colores = {"severa": "#c2410c", "moderada": "#2563eb", "leve": "#059669"}
    fig, axs = plt.subplots(1, 3, figsize=(15, 4.6))
    for ax, (col, nombre) in zip(axs, [MEDIDAS[0], MEDIDAS[1], MEDIDAS[6]]):
        x = d[d.medida == col]
        media = (x["medido"] + x["real"]) / 2
        for caso, c in colores.items():
            s = x.caso == caso
            ax.scatter(media[s], x["error"][s], s=18, color=c, alpha=0.8, label=caso)
        b, sd = x["error"].mean(), x["error"].std()
        for yv, ls in ((b, "-"), (b + 1.96 * sd, "--"), (b - 1.96 * sd, "--")):
            ax.axhline(yv, color="#444", ls=ls, lw=1)
        ax.axhline(0, color="#999", lw=0.6)
        ax.set_title(f"{nombre}\nsesgo {b:+.3f} · LdA [{b - 1.96 * sd:+.3f}, {b + 1.96 * sd:+.3f}]", fontsize=10)
        ax.set_xlabel("media (automático + real) / 2")
        ax.set_ylabel("automático − real")
        ax.grid(alpha=0.3)
    axs[0].legend(frameon=False, fontsize=9)
    fig.suptitle("Bland-Altman: medición automática frente a valor real (imágenes sintéticas)", x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(ruta, dpi=110)
    plt.close(fig)


if __name__ == "__main__":
    main()
