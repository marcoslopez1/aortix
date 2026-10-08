"""
Aplicación con ventanas para analizar imágenes de Doppler continuo aórtico.
Se abre con doble clic en "2_ANALIZAR_IMAGEN.bat" (Windows).

1. Botón "Analizar imagen…": eliges uno o varios archivos (DICOM, PNG o JPG).
2. Si la imagen no trae calibración (PNG/JPG o DICOM sin ella), se abre una ventana
   que te pide 6 clics sobre la imagen.
3. Se procesa y se abre la figura de control. Los resultados quedan en la carpeta "resultados".
"""
import json
import os
import sys
import threading
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog

from PIL import Image, ImageTk

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import procesar as P  # noqa: E402

SALIDA = os.path.join(AQUI, "resultados")

PASOS = [
    ("Clic en la esquina SUPERIOR IZQUIERDA del espectro\n"
     "(un poco por encima de la línea de base; sin incluir los números de la escala)"),
    "Clic en la esquina INFERIOR DERECHA del espectro\n(sin incluir los números de la escala)",
    "Clic exactamente sobre la LÍNEA DE BASE (0 m/s)",
    "Clic sobre la marca de la ESCALA DE VELOCIDAD más alejada de la base que veas\n(por ejemplo, la de −4 o −5 m/s)",
    ("TIEMPO · Clic sobre una marca del eje de tiempo (las rayitas de abajo)\n"
     "o sobre el pico de una onda R del ECG"),
    "TIEMPO · Clic sobre OTRA marca de tiempo (o la siguiente onda R), lo más lejos posible",
]
COLORES = ["#ff5a36", "#ff5a36", "#2fb5ff", "#ffd23f", "#3ddc84", "#3ddc84"]


def abrir(ruta):
    try:
        if sys.platform.startswith("win"):
            os.startfile(ruta)  # noqa
        elif sys.platform == "darwin":
            os.system(f'open "{ruta}"')
        else:
            os.system(f'xdg-open "{ruta}" >/dev/null 2>&1 &')
    except Exception:
        pass


ULTIMA = os.path.join(AQUI, "ultima_calibracion.json")


def guardar_ultima(calib):
    with open(ULTIMA, "w") as f:
        json.dump(calib, f, indent=2)


def leer_ultima():
    try:
        with open(ULTIMA) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def cargar(ruta):
    """Imagen como PIL (también DICOM)."""
    if P._es_dicom(ruta):
        return Image.fromarray(P.pixeles_dicom(ruta)[0])
    return Image.open(ruta).convert("RGB")


def tamano(ruta):
    try:
        return list(cargar(ruta).size)
    except Exception:
        return None


def necesita_calibracion(ruta):
    if os.path.exists(os.path.splitext(ruta)[0] + "_calibracion.json"):
        return False
    try:
        P.leer_imagen(ruta)
        return False
    except ValueError:
        return True


class Calibrador(tk.Toplevel):
    """Ventana de calibración por clics. Guarda <imagen>_calibracion.json."""

    def __init__(self, master, ruta):
        super().__init__(master)
        self.ruta, self.ok = ruta, False
        self.title(f"Calibración · {os.path.basename(ruta)}")
        self.configure(bg="#111")
        img = cargar(ruta)
        self.w0, self.h0 = img.size
        sw, sh = self.winfo_screenwidth() - 80, self.winfo_screenheight() - 260
        self.esc = min(1.0, sw / self.w0, sh / self.h0)
        self.foto = ImageTk.PhotoImage(img.resize((int(self.w0 * self.esc), int(self.h0 * self.esc))))

        self.lbl = tk.Label(self, font=("Segoe UI", 13, "bold"), fg="white", bg="#111", justify="left")
        self.lbl.pack(fill="x", padx=12, pady=(10, 4))
        self.cv = tk.Canvas(self, width=self.foto.width(), height=self.foto.height(),
                            highlightthickness=0, cursor="crosshair", bg="black")
        self.cv.pack(padx=12)
        self.cv.create_image(0, 0, anchor="nw", image=self.foto)
        barra = tk.Frame(self, bg="#111")
        barra.pack(fill="x", padx=12, pady=8)
        tk.Button(barra, text="↶ Deshacer último clic", command=self.deshacer).pack(side="left")
        tk.Button(barra, text="Cancelar", command=self.destroy).pack(side="right")
        self.cv.bind("<Button-1>", self.clic)
        self.cv.bind("<Motion>", self.mover)
        self.cruz = []
        self.pts, self.items = [], []
        self.valor_ms = self.segundos = None
        self.actualizar()
        self.grab_set()

    # coordenadas de pantalla -> imagen original
    def a_img(self, x, y):
        return x / self.esc, y / self.esc

    def mover(self, e):
        for i in self.cruz:
            self.cv.delete(i)
        self.cruz = [self.cv.create_line(0, e.y, self.foto.width(), e.y, fill="#ffffff", dash=(2, 4)),
                     self.cv.create_line(e.x, 0, e.x, self.foto.height(), fill="#ffffff", dash=(2, 4))]

    def actualizar(self):
        n = len(self.pts)
        self.lbl.config(text=f"Paso {n + 1} de {len(PASOS)} · {PASOS[n]}" if n < len(PASOS) else "")

    def clic(self, e):
        n = len(self.pts)
        if n >= len(PASOS):
            return
        x, y = self.a_img(e.x, e.y)
        c = COLORES[n]
        grupo = [self.cv.create_oval(e.x - 5, e.y - 5, e.x + 5, e.y + 5, outline=c, width=2)]
        if n == 1:
            x0, y0 = self.pts[0][0] * self.esc, self.pts[0][1] * self.esc
            grupo.append(self.cv.create_rectangle(x0, y0, e.x, e.y, outline=c, width=2))
        if n in (2, 3):
            grupo.append(self.cv.create_line(0, e.y, self.foto.width(), e.y, fill=c, width=1))
        if n in (4, 5):
            grupo.append(self.cv.create_line(e.x, 0, e.x, self.foto.height(), fill=c, width=1))
        self.pts.append((x, y))
        self.items.append(grupo)
        if n == 3:
            v = simpledialog.askfloat("Escala de velocidad",
                                      "¿Qué valor tiene la marca en la que has hecho clic? (en m/s)\n"
                                      "Ejemplo: −4  (el signo da igual)", parent=self)
            if v is None or v == 0:
                self.deshacer()
                return
            self.valor_ms = abs(v)
        if n == 5:
            s = simpledialog.askfloat(
                "Tiempo",
                "¿Cuántos SEGUNDOS hay entre tus dos clics de tiempo?\n\n"
                "· Si son marcas del eje: cuenta las marcas (suelen ser de 0,1 o 0,2 s).\n"
                "· Si son dos ondas R seguidas: 60 ÷ frecuencia cardiaca\n"
                "   (p. ej. 84 lpm → 0,714 s).\n\nEscribe el número con punto decimal (0.714).",
                parent=self)
            if s is None or s <= 0:
                self.deshacer()
                return
            self.segundos = s
            self.guardar()
            return
        self.actualizar()

    def deshacer(self):
        if self.pts:
            self.pts.pop()
            for i in self.items.pop():
                self.cv.delete(i)
        self.actualizar()

    def guardar(self):
        (xa, ya), (xb, yb), (_, ybase), (_, ymarca), (xt1, _), (xt2, _) = self.pts
        calib = dict(region=dict(x0=int(round(min(xa, xb))), y0=int(round(min(ya, yb))),
                                 x1=int(round(max(xa, xb))), y1=int(round(max(ya, yb)))),
                     linea_base_y=int(round(ybase)),
                     px_por_ms=abs(ymarca - ybase) / self.valor_ms,
                     px_por_s=abs(xt2 - xt1) / self.segundos)
        if calib["px_por_ms"] < 5 or calib["px_por_s"] < 20:
            messagebox.showerror("Calibración", "La calibración no parece correcta "
                                 "(los clics de escala o de tiempo están demasiado juntos). Repite los pasos.",
                                 parent=self)
            while self.pts:
                self.deshacer()
            return
        calib["tamano_imagen"] = [self.w0, self.h0]
        with open(os.path.splitext(self.ruta)[0] + "_calibracion.json", "w") as f:
            json.dump(calib, f, indent=2)
        guardar_ultima(calib)
        self.ok = True
        self.destroy()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Doppler continuo · Estenosis aórtica")
        self.geometry("760x520")
        tk.Label(self, text="Análisis de Doppler continuo aórtico", font=("Segoe UI", 16, "bold")).pack(pady=(16, 2))
        tk.Label(self, text="Elige una o varias imágenes (DICOM, PNG o JPG). "
                            "Al terminar se abre la figura de control.", font=("Segoe UI", 10)).pack()
        f = tk.Frame(self)
        f.pack(pady=12)
        self.b1 = tk.Button(f, text="📂  Analizar imagen…", font=("Segoe UI", 12, "bold"),
                            width=22, height=2, command=self.elegir)
        self.b1.grid(row=0, column=0, padx=6)
        tk.Button(f, text="Abrir carpeta de resultados", font=("Segoe UI", 11), width=24, height=2,
                  command=lambda: (os.makedirs(SALIDA, exist_ok=True), abrir(SALIDA))).grid(row=0, column=1, padx=6)
        self.reusar = tk.BooleanVar(value=True)
        tk.Checkbutton(self, text="Usar la misma calibración que la imagen anterior "
                                  "(mismo ecógrafo y mismos ajustes de escala y barrido)",
                       variable=self.reusar).pack(anchor="w", padx=14)
        self.recal = tk.BooleanVar(value=False)
        tk.Checkbutton(self, text="Volver a calibrar aunque ya exista una calibración",
                       variable=self.recal).pack(anchor="w", padx=14)
        self.log = tk.Text(self, height=16, font=("Consolas", 10), bg="#f6f6f6")
        self.log.pack(fill="both", expand=True, padx=12, pady=10)
        self.escribir("Listo. Pulsa «Analizar imagen…».\n")

    def escribir(self, txt):
        self.log.insert("end", txt)
        self.log.see("end")
        self.update_idletasks()

    def elegir(self):
        rutas = filedialog.askopenfilenames(
            title="Elige las imágenes",
            filetypes=[("Imágenes Doppler", "*.dcm *.DCM *.png *.PNG *.jpg *.jpeg *.JPG *.JPEG *.dicom"),
                       ("Todos los archivos", "*.*")])
        if not rutas:
            return
        self.abrir_figura = len(rutas) == 1
        for r in rutas:
            cal = os.path.splitext(r)[0] + "_calibracion.json"
            if self.recal.get() and os.path.exists(cal):
                os.remove(cal)
            if necesita_calibracion(r) and self.reusar.get() and not self.recal.get() and self.reutilizar(r):
                pass
            elif necesita_calibracion(r):
                self.escribir(f"\n· {os.path.basename(r)}: necesita calibración, sigue los pasos de la ventana…\n")
                c = Calibrador(self, r)
                try:
                    self.wait_window(c)
                except tk.TclError:
                    pass  # la ventana ya se había cerrado
                if not c.ok:
                    self.escribir("  Calibración cancelada.\n")
                    continue
            self.analizar(r)
        if len(rutas) > 1:
            self.escribir("\nLote terminado. Abro la carpeta de resultados.\n")
            abrir(SALIDA)

    def reutilizar(self, ruta):
        """Copia la última calibración a esta imagen si tiene el mismo tamaño. Devuelve True si lo hace."""
        ult = leer_ultima()
        if not ult:
            return False
        tam = tamano(ruta)
        if ult.get("tamano_imagen") and tam and ult["tamano_imagen"] != tam:
            self.escribir(f"\n· {os.path.basename(ruta)}: tiene distinto tamaño que la imagen calibrada "
                          "antes; hay que calibrarla.\n")
            return False
        with open(os.path.splitext(ruta)[0] + "_calibracion.json", "w") as f:
            json.dump(ult, f, indent=2)
        self.escribir(f"\n· {os.path.basename(ruta)}: uso la calibración de la imagen anterior.\n")
        return True

    def analizar(self, ruta):
        os.makedirs(SALIDA, exist_ok=True)
        self.escribir(f"· Analizando {os.path.basename(ruta)}…\n")
        self.b1.config(state="disabled")
        try:
            res, df, _ = P.procesar(ruta, SALIDA)
            if res["n_latidos"] == 0:
                self.escribir("  No se detectó ningún latido completo. Revisa la figura de control "
                              "o repite la calibración.\n")
            else:
                self.escribir(
                    f"  {res['n_latidos']} latidos · Vmax {res['vmax_ms']:.2f} m/s · "
                    f"grad. medio {res['grad_medio_mmHg']:.1f} mmHg · VTI {res['vti_cm']:.1f} cm · "
                    f"AT/ET {res['at_et']:.2f}\n")
            self.actualizar_resumen(res)
            fig = os.path.join(SALIDA, f"{res['imagen']}_control.png")
            self.escribir(f"  Figura de control: {fig}\n")
            if getattr(self, "abrir_figura", True):
                abrir(fig)
        except Exception as ex:
            self.escribir(f"  ERROR: {ex}\n")
            with open(os.path.join(SALIDA, "errores.log"), "a", encoding="utf-8") as f:
                f.write(f"\n=== {ruta}\n{traceback.format_exc()}")
        finally:
            self.b1.config(state="normal")

    def actualizar_resumen(self, res):
        import pandas as pd
        ruta = os.path.join(SALIDA, "resumen_imagenes.csv")
        d = pd.read_csv(ruta) if os.path.exists(ruta) else pd.DataFrame()
        if len(d) and "imagen" in d:
            d = d[d["imagen"] != res["imagen"]]
        d = pd.concat([d, pd.DataFrame([res])], ignore_index=True)
        d.to_csv(ruta, index=False)


if __name__ == "__main__":
    try:
        App().mainloop()
    except Exception:
        messagebox.showerror("Error", traceback.format_exc())
