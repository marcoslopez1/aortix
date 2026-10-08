"""
Aplicación con ventanas para analizar imágenes de Doppler continuo aórtico.
Se abre con doble clic en "2_ANALIZAR_IMAGEN.bat" (Windows).

1. Botón "Analizar imágenes…": eliges uno o varios archivos (DICOM, PNG o JPG).
2. La calibración es automática: se usa la del DICOM o, en capturas PNG/JPG, se leen la escala
   de velocidad y las marcas de tiempo de la propia imagen. Solo si eso falla se abre una
   ventana que pide 6 clics sobre la imagen.
3. Se procesa y se abre la figura de control. Los resultados quedan en la carpeta "resultados"
   y en la tabla de la ventana (doble clic en una fila para abrir su figura).
"""
import json
import os
import sys
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

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

# Paleta de la interfaz
C = dict(
    fondo="#eef2f6", tarjeta="#ffffff", borde="#dde3ea",
    cabecera="#0f2a44", cabecera_txt="#ffffff", cabecera_sub="#9fb6cc",
    texto="#1c2733", suave="#6b7a8c",
    primario="#d63c3c", primario_hover="#b92f2f",
    secundario="#e6ebf1", secundario_hover="#d6dee8",
    ok="#1f9d55", error="#d14343", aviso="#c27c0e",
    oscuro="#14181d", oscuro2="#22282f", oscuro_hover="#323a44",
)
FUENTE = "Segoe UI"


def nitidez_windows():
    """Evita que Windows dibuje la ventana borrosa en pantallas con escalado."""
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass


class Boton(tk.Label):
    """Botón plano con cambio de color al pasar el ratón."""

    def __init__(self, master, text, command, fondo, hover, color="#ffffff", tam=11, negrita=False,
                 padx=18, pady=9):
        super().__init__(master, text=text, bg=fondo, fg=color, cursor="hand2", padx=padx, pady=pady,
                         font=(FUENTE, tam, "bold" if negrita else "normal"))
        self.command, self.fondo, self.hover, self.color, self.activo = command, fondo, hover, color, True
        self.bind("<Enter>", lambda e: self.activo and self.config(bg=self.hover))
        self.bind("<Leave>", lambda e: self.config(bg=self.fondo))
        self.bind("<Button-1>", lambda e: self.activo and self.command())

    def activar(self, si):
        self.activo = si
        self.config(cursor="hand2" if si else "watch", fg=self.color if si else "#f0c4c4")


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
    """True si no hay calibración manual, del DICOM ni automática."""
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
        self.configure(bg=C["oscuro"])
        img = cargar(ruta)
        self.w0, self.h0 = img.size
        sw, sh = self.winfo_screenwidth() - 80, self.winfo_screenheight() - 300
        self.esc = min(1.0, sw / self.w0, sh / self.h0)
        self.foto = ImageTk.PhotoImage(img.resize((int(self.w0 * self.esc), int(self.h0 * self.esc))))

        # Cabecera: progreso por pasos + instrucción
        arriba = tk.Frame(self, bg=C["oscuro2"])
        arriba.pack(fill="x")
        fila = tk.Frame(arriba, bg=C["oscuro2"])
        fila.pack(fill="x", padx=16, pady=(12, 4))
        self.paso_lbl = tk.Label(fila, font=(FUENTE, 10, "bold"), fg=C["cabecera_sub"], bg=C["oscuro2"])
        self.paso_lbl.pack(side="left")
        self.puntos = tk.Canvas(fila, width=len(PASOS) * 22, height=14, bg=C["oscuro2"], highlightthickness=0)
        self.puntos.pack(side="left", padx=12)
        self.lbl = tk.Label(arriba, font=(FUENTE, 13, "bold"), fg="white", bg=C["oscuro2"],
                            justify="left", anchor="w")
        self.lbl.pack(fill="x", padx=16, pady=(0, 12))

        self.cv = tk.Canvas(self, width=self.foto.width(), height=self.foto.height(),
                            highlightthickness=0, cursor="crosshair", bg="black")
        self.cv.pack(padx=16, pady=12)
        self.cv.create_image(0, 0, anchor="nw", image=self.foto)
        barra = tk.Frame(self, bg=C["oscuro"])
        barra.pack(fill="x", padx=16, pady=(0, 12))
        Boton(barra, "↶  Deshacer último clic", self.deshacer, C["oscuro2"], C["oscuro_hover"],
              tam=10).pack(side="left")
        Boton(barra, "Cancelar", self.destroy, C["oscuro2"], C["oscuro_hover"], tam=10).pack(side="right")
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
        self.paso_lbl.config(text=f"PASO {min(n + 1, len(PASOS))} DE {len(PASOS)}")
        self.lbl.config(text=PASOS[n] if n < len(PASOS) else "",
                        fg=COLORES[n] if n < len(PASOS) else "white")
        self.puntos.delete("all")
        for i in range(len(PASOS)):
            x = i * 22 + 7
            if i < n:
                self.puntos.create_oval(x - 5, 2, x + 5, 12, fill=COLORES[i], outline="")
            elif i == n:
                self.puntos.create_oval(x - 5, 2, x + 5, 12, outline=COLORES[i], width=2)
            else:
                self.puntos.create_oval(x - 4, 3, x + 4, 11, outline="#4a5560", width=1)

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
                     px_por_s=abs(xt2 - xt1) / self.segundos, fuente="manual")
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
    COLUMNAS = [("imagen", "Imagen", 220, "w"), ("latidos", "Latidos", 70, "center"),
                ("vmax", "Vmax (m/s)", 95, "center"), ("grad", "Grad. medio (mmHg)", 140, "center"),
                ("vti", "VTI (cm)", 85, "center"), ("atet", "AT/ET", 75, "center"),
                ("estado", "Estado", 150, "w")]

    def __init__(self):
        super().__init__()
        self.title("Doppler continuo · Estenosis aórtica")
        self.f = self.winfo_fpixels("1i") / 96  # escalado de Windows (100 %, 125 %, 150 %…)
        self.geometry(f"{self.px(1040)}x{self.px(720)}")
        self.minsize(self.px(860), self.px(560))
        self.configure(bg=C["fondo"])
        self.figuras = {}  # fila de la tabla -> ruta de la figura de control
        self.estilos()

        # Cabecera
        cab = tk.Frame(self, bg=C["cabecera"])
        cab.pack(fill="x")
        tk.Label(cab, text="Doppler continuo aórtico", font=(FUENTE, 18, "bold"),
                 fg=C["cabecera_txt"], bg=C["cabecera"]).pack(anchor="w", padx=28, pady=(18, 0))
        tk.Label(cab, text="Morfología de la curva y textura del espectro · prueba de concepto",
                 font=(FUENTE, 10), fg=C["cabecera_sub"], bg=C["cabecera"]).pack(anchor="w", padx=28, pady=(0, 18))

        cuerpo = tk.Frame(self, bg=C["fondo"])
        cuerpo.pack(fill="both", expand=True, padx=24, pady=20)

        # Tarjeta de acciones
        acc = self.tarjeta(cuerpo)
        acc.pack(fill="x")
        der = tk.Frame(acc, bg=C["tarjeta"])
        der.pack(side="right", padx=20, pady=18)
        self.b1 = Boton(der, "📂   Analizar imágenes…", self.elegir, C["primario"], C["primario_hover"],
                        tam=12, negrita=True, padx=26, pady=12)
        self.b1.pack(fill="x")
        Boton(der, "Abrir carpeta de resultados", lambda: (os.makedirs(SALIDA, exist_ok=True), abrir(SALIDA)),
              C["secundario"], C["secundario_hover"], color=C["texto"], tam=10).pack(fill="x", pady=(8, 0))


        izq = tk.Frame(acc, bg=C["tarjeta"])
        izq.pack(side="left", fill="both", expand=True, padx=20, pady=18)
        tk.Label(izq, text="Analizar imágenes", font=(FUENTE, 13, "bold"), fg=C["texto"],
                 bg=C["tarjeta"]).pack(anchor="w")
        tk.Label(izq, text="DICOM, PNG o JPG. Puedes elegir varias a la vez. "
                           "Al terminar se abre la figura de control.",
                 font=(FUENTE, 10), fg=C["suave"], bg=C["tarjeta"]).pack(anchor="w", pady=(2, 10))
        self.reusar = tk.BooleanVar(value=True)
        ttk.Checkbutton(izq, text="Si la calibración automática falla, usar la manual de la imagen anterior "
                                  "(mismo tamaño)",
                        variable=self.reusar, style="Tarjeta.TCheckbutton").pack(anchor="w", pady=1)
        self.recal = tk.BooleanVar(value=False)
        ttk.Checkbutton(izq, text="Calibrar a mano (no usar la calibración automática)",
                        variable=self.recal, style="Tarjeta.TCheckbutton").pack(anchor="w", pady=1)

        # Tarjeta de resultados
        tab = self.tarjeta(cuerpo)
        tab.pack(fill="both", expand=True, pady=(16, 0))
        cab_tab = tk.Frame(tab, bg=C["tarjeta"])
        cab_tab.pack(fill="x", padx=20, pady=(14, 8))
        tk.Label(cab_tab, text="Resultados de esta sesión", font=(FUENTE, 13, "bold"), fg=C["texto"],
                 bg=C["tarjeta"]).pack(side="left")
        tk.Label(cab_tab, text="Doble clic en una fila para ver su figura de control",
                 font=(FUENTE, 9), fg=C["suave"], bg=C["tarjeta"]).pack(side="right")
        marco = tk.Frame(tab, bg=C["tarjeta"])
        marco.pack(fill="both", expand=True, padx=20)
        self.tabla = ttk.Treeview(marco, columns=[c[0] for c in self.COLUMNAS], show="headings",
                                  style="Resultados.Treeview", height=8)
        for clave, titulo, ancho, alin in self.COLUMNAS:
            self.tabla.heading(clave, text=titulo, anchor=alin)
            self.tabla.column(clave, width=self.px(ancho), anchor=alin, stretch=clave in ("imagen", "estado"))
        self.tabla.tag_configure("ok", foreground=C["texto"])
        self.tabla.tag_configure("aviso", foreground=C["aviso"])
        self.tabla.tag_configure("error", foreground=C["error"])
        self.tabla.tag_configure("par", background="#f7f9fb")
        barra = ttk.Scrollbar(marco, orient="vertical", command=self.tabla.yview)
        self.tabla.configure(yscrollcommand=barra.set)
        self.tabla.pack(side="left", fill="both", expand=True)
        barra.pack(side="right", fill="y")
        self.tabla.bind("<Double-1>", self.ver_figura)

        # Registro de mensajes
        tk.Label(tab, text="Registro", font=(FUENTE, 9, "bold"), fg=C["suave"],
                 bg=C["tarjeta"]).pack(anchor="w", padx=20, pady=(12, 2))
        self.log = tk.Text(tab, height=6, font=("Consolas", 9), bg="#f7f9fb", fg=C["texto"],
                           relief="flat", highlightthickness=1, highlightbackground=C["borde"],
                           padx=10, pady=6, wrap="word")
        self.log.pack(fill="x", padx=20, pady=(0, 16))
        self.log.tag_configure("error", foreground=C["error"])

        # Barra de estado
        self.estado = tk.Label(self, text="Listo", anchor="w", font=(FUENTE, 9), fg=C["suave"],
                               bg=C["fondo"])
        self.estado.pack(side="bottom", fill="x", padx=26, pady=(0, 10), before=cuerpo)
        self.escribir("Listo. Pulsa «Analizar imágenes…».\n")

    def estilos(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("Tarjeta.TCheckbutton", background=C["tarjeta"], foreground=C["texto"], font=(FUENTE, 10))
        s.map("Tarjeta.TCheckbutton", background=[("active", C["tarjeta"])],
              indicatorbackground=[("selected", C["primario"]), ("!selected", C["tarjeta"])],
              indicatorforeground=[("selected", "#ffffff")])
        s.configure("Tarjeta.TCheckbutton", indicatorsize=self.px(13), indicatormargin=(0, 0, self.px(6), 0),
                    bordercolor=C["borde"], upperbordercolor=C["borde"], lowerbordercolor=C["borde"])
        s.configure("Vertical.TScrollbar", background=C["secundario"], troughcolor=C["tarjeta"],
                    bordercolor=C["tarjeta"], arrowcolor=C["suave"], lightcolor=C["secundario"],
                    darkcolor=C["secundario"], gripcount=0)
        s.map("Vertical.TScrollbar", background=[("active", C["secundario_hover"])])
        s.configure("Resultados.Treeview", font=(FUENTE, 10), rowheight=self.px(30), background=C["tarjeta"],
                    fieldbackground=C["tarjeta"], foreground=C["texto"], borderwidth=0)
        s.configure("Resultados.Treeview.Heading", font=(FUENTE, 9, "bold"), background="#f1f4f8",
                    foreground=C["suave"], relief="flat", padding=(8, 6))
        s.map("Resultados.Treeview.Heading", background=[("active", "#e6ebf1")])
        s.map("Resultados.Treeview", background=[("selected", "#dbe7f5")],
              foreground=[("selected", C["texto"])])
        s.layout("Resultados.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])

    def px(self, n):
        return int(round(n * self.f))

    def tarjeta(self, master):
        return tk.Frame(master, bg=C["tarjeta"], highlightthickness=1, highlightbackground=C["borde"])

    def escribir(self, txt, tag=None):
        self.log.insert("end", txt, tag)
        self.log.see("end")
        self.update_idletasks()

    def fila(self, nombre, valores, tag):
        n = len(self.tabla.get_children())
        etiquetas = (tag, "par") if n % 2 else (tag,)
        return self.tabla.insert("", "end", values=[nombre, *valores], tags=etiquetas)

    def ver_figura(self, _e):
        sel = self.tabla.focus()
        if sel and self.figuras.get(sel) and os.path.exists(self.figuras[sel]):
            abrir(self.figuras[sel])

    def elegir(self):
        rutas = filedialog.askopenfilenames(
            title="Elige las imágenes",
            filetypes=[("Imágenes Doppler", "*.dcm *.DCM *.png *.PNG *.jpg *.jpeg *.JPG *.JPEG *.dicom"),
                       ("Todos los archivos", "*.*")])
        if not rutas:
            return
        self.abrir_figura = len(rutas) == 1
        for i, r in enumerate(rutas, 1):
            self.estado.config(text=f"Imagen {i} de {len(rutas)} · {os.path.basename(r)}")
            cal = os.path.splitext(r)[0] + "_calibracion.json"
            if self.recal.get() and os.path.exists(cal):
                os.remove(cal)
            falta = True
            if not self.recal.get():
                self.escribir(f"\n· {os.path.basename(r)}: calibrando…\n")
                self.update()
                falta = necesita_calibracion(r)
                if falta:
                    self.escribir("  La calibración automática no ha funcionado.\n", "error")
            if falta and self.reusar.get() and not self.recal.get() and self.reutilizar(r):
                pass
            elif falta:
                self.escribir(f"  {os.path.basename(r)}: calibración manual, sigue los pasos de la ventana…\n")
                c = Calibrador(self, r)
                try:
                    self.wait_window(c)
                except tk.TclError:
                    pass  # la ventana ya se había cerrado
                if not c.ok:
                    self.escribir("  Calibración cancelada.\n")
                    self.fila(os.path.basename(r), ["–"] * 5 + ["Calibración cancelada"], "aviso")
                    continue
            self.analizar(r)
        self.estado.config(text=f"Terminado · {len(rutas)} imagen(es)")
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
        ult["fuente"] = "manual (reutilizada)"
        with open(os.path.splitext(ruta)[0] + "_calibracion.json", "w") as f:
            json.dump(ult, f, indent=2)
        self.escribir(f"  {os.path.basename(ruta)}: uso la calibración manual de la imagen anterior.\n")
        return True

    def analizar(self, ruta):
        os.makedirs(SALIDA, exist_ok=True)
        self.escribir(f"· Analizando {os.path.basename(ruta)}…\n")
        self.b1.activar(False)
        self.config(cursor="watch")
        self.update()
        try:
            res, df, _ = P.procesar(ruta, SALIDA)
            fig = os.path.join(SALIDA, f"{res['imagen']}_control.png")
            self.escribir(f"  Calibración {res['calibracion']}: {res['px_por_ms']:.1f} px por m/s, "
                          f"{res['px_por_s']:.0f} px por segundo\n")
            if res.get("avisos_calibracion"):
                self.escribir(f"  ⚠ {res['avisos_calibracion']}\n", "error")
            if res["n_latidos"] == 0:
                self.escribir("  No se detectó ningún latido completo. Revisa la figura de control "
                              "o repite la calibración.\n", "error")
                fila = self.fila(res["imagen"], ["0", "–", "–", "–", "–", "Sin latidos completos"], "aviso")
            else:
                self.escribir(
                    f"  {res['n_latidos']} latidos · Vmax {res['vmax_ms']:.2f} m/s · "
                    f"grad. medio {res['grad_medio_mmHg']:.1f} mmHg · VTI {res['vti_cm']:.1f} cm · "
                    f"AT/ET {res['at_et']:.2f}\n")
                fila = self.fila(res["imagen"], [
                    res["n_latidos"], f"{res['vmax_ms']:.2f}", f"{res['grad_medio_mmHg']:.1f}",
                    f"{res['vti_cm']:.1f}", f"{res['at_et']:.2f}", "✓ Correcto"], "ok")
            self.figuras[fila] = fig
            self.actualizar_resumen(res)
            self.escribir(f"  Figura de control: {fig}\n")
            if getattr(self, "abrir_figura", True):
                abrir(fig)
        except Exception as ex:
            self.escribir(f"  ERROR: {ex}\n", "error")
            self.fila(os.path.basename(ruta), ["–"] * 5 + ["✗ Error (ver registro)"], "error")
            with open(os.path.join(SALIDA, "errores.log"), "a", encoding="utf-8") as f:
                f.write(f"\n=== {ruta}\n{traceback.format_exc()}")
        finally:
            self.b1.activar(True)
            self.config(cursor="")

    def actualizar_resumen(self, res):
        import pandas as pd
        ruta = os.path.join(SALIDA, "resumen_imagenes.csv")
        d = pd.read_csv(ruta) if os.path.exists(ruta) else pd.DataFrame()
        if len(d) and "imagen" in d:
            d = d[d["imagen"] != res["imagen"]]
        d = pd.concat([d, pd.DataFrame([res])], ignore_index=True)
        d.to_csv(ruta, index=False)


if __name__ == "__main__":
    nitidez_windows()
    try:
        App().mainloop()
    except Exception:
        messagebox.showerror("Error", traceback.format_exc())
