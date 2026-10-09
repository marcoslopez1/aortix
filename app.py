"""
Aplicación con ventanas para analizar imágenes de Doppler continuo aórtico.
Se abre con doble clic en "2_ANALIZAR_IMAGEN.bat" (Windows).

1. Botón "Analizar imágenes": eliges uno o varios archivos (DICOM, PNG o JPG).
2. La calibración es automática: se usa la del DICOM o, en capturas PNG/JPG, se leen la escala
   de velocidad y las marcas de tiempo de la propia imagen. Solo si eso falla se abre una
   ventana que pide 6 clics sobre la imagen.
3. Se procesa y se abre la figura de control. Los resultados quedan en la carpeta "resultados"
   y en la tabla de la ventana (doble clic en una fila para abrir su figura).
4. Se abre la ventana «Datos del paciente» (edad, sexo, factores de riesgo, etiqueta severa / no severa
   y mediciones del informe). Todo es opcional salvo el código del paciente.
5. La pestaña «Datos» muestra las tablas guardadas (solo lectura).
"""
import json
import os
import sys
import traceback
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, simpledialog, ttk

from PIL import Image, ImageDraw, ImageTk

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import datos_clinicos as D  # noqa: E402
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
    primario="#1f6feb", primario_hover="#1858c4", primario_off="#b9cdf0",
    secundario="#e6ebf1", secundario_hover="#d6dee8",
    ok="#1f9d55", error="#d14343", aviso="#c27c0e",
    oscuro="#14181d", oscuro2="#22282f", oscuro_hover="#323a44",
)
FUENTE = "Segoe UI"

# Iconos: fuente de iconos de Windows (Segoe Fluent Icons en Windows 11, MDL2 en Windows 10);
# si no está, un símbolo Unicode parecido.
ICONOS = {
    "abrir": ("", "📂"), "carpeta": ("", "📁"), "paciente": ("", "👤"),
    "guardar": ("", "✔"), "cerrar": ("", "✕"), "deshacer": ("", "↶"),
    "recargar": ("", "⟳"), "analisis": ("", "📈"), "tabla": ("", "☰"),
}
_FUENTE_ICONOS = []


def fuente_iconos():
    if not _FUENTE_ICONOS:
        familias = set(tkfont.families())
        _FUENTE_ICONOS.append(next((f for f in ("Segoe Fluent Icons", "Segoe MDL2 Assets") if f in familias), None))
    return _FUENTE_ICONOS[0]


def nitidez_windows():
    """Evita que Windows dibuje la ventana borrosa en pantallas con escalado."""
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass


class Boton(tk.Frame):
    """Botón plano con icono y cambio de color al pasar el ratón."""

    def __init__(self, master, text, command, fondo, hover, color="#ffffff", tam=11, negrita=False,
                 padx=18, pady=9, icono=None, apagado=None):
        super().__init__(master, bg=fondo, cursor="hand2")
        self.command, self.fondo, self.hover, self.color, self.activo = command, fondo, hover, color, True
        self.apagado = apagado or C["suave"]
        interior = tk.Frame(self, bg=fondo)
        interior.pack(padx=padx, pady=pady)
        self.partes = [self, interior]
        if icono:
            glifo, alternativo = ICONOS[icono]
            fi = fuente_iconos()
            ico = tk.Label(interior, text=glifo if fi else alternativo, bg=fondo, fg=color,
                           font=(fi, tam) if fi else (FUENTE, tam))
            ico.pack(side="left", padx=(0, 10))
            self.partes.append(ico)
        txt = tk.Label(interior, text=text, bg=fondo, fg=color, font=(FUENTE, tam, "bold" if negrita else "normal"))
        txt.pack(side="left")
        self.partes.append(txt)
        for w in self.partes:
            w.bind("<Enter>", lambda e: self.activo and self._fondo(self.hover))
            w.bind("<Leave>", lambda e: self._fondo(self.fondo))
            w.bind("<Button-1>", lambda e: self.activo and self.command())

    def _fondo(self, color):
        for w in self.partes:
            w.config(bg=color)

    def activar(self, si):
        self.activo = si
        for w in self.partes:
            w.config(cursor="hand2" if si else "watch")
            if isinstance(w, tk.Label):
                w.config(fg=self.color if si else self.apagado)


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
        Boton(barra, "Deshacer último clic", self.deshacer, C["oscuro2"], C["oscuro_hover"],
              tam=10, icono="deshacer").pack(side="left")
        Boton(barra, "Cancelar", self.destroy, C["oscuro2"], C["oscuro_hover"], tam=10,
              icono="cerrar").pack(side="right")
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


class FichaPaciente(tk.Toplevel):
    """Ventana «Datos del paciente»: datos clínicos y etiqueta. Guarda en resultados/datos_clinicos.csv."""

    def __init__(self, master, imagen):
        super().__init__(master)
        self.imagen, self.ok, self.cargado = imagen, False, None
        self.title(f"Datos del paciente · {imagen}")
        self.configure(bg=C["fondo"])
        self.resizable(False, False)
        self.transient(master)

        cab = tk.Frame(self, bg=C["cabecera"])
        cab.pack(fill="x")
        tk.Label(cab, text="Datos del paciente", font=(FUENTE, 15, "bold"), fg=C["cabecera_txt"],
                 bg=C["cabecera"]).pack(anchor="w", padx=22, pady=(14, 0))
        tk.Label(cab, text=f"Imagen {imagen} · todo es opcional salvo el código. "
                           "No escribas nombres ni números de historia.",
                 font=(FUENTE, 9), fg=C["cabecera_sub"], bg=C["cabecera"]).pack(anchor="w", padx=22, pady=(0, 14))

        cuerpo = tk.Frame(self, bg=C["fondo"])
        cuerpo.pack(fill="both", padx=18, pady=14)

        # Código del paciente: el asignado antes a esta imagen o el del nombre del archivo
        fila_id = master.tarjeta(cuerpo)
        fila_id.grid(row=0, column=0, columnspan=2, sticky="ew", padx=4, pady=4)
        tk.Label(fila_id, text="Código del paciente", font=(FUENTE, 10, "bold"), fg=C["texto"],
                 bg=C["tarjeta"]).pack(side="left", padx=(14, 10), pady=10)
        self.v_id = tk.StringVar(value=self.id_inicial())
        e = ttk.Entry(fila_id, textvariable=self.v_id, width=12, font=(FUENTE, 11), style="Ficha.TEntry")
        e.pack(side="left", pady=10)
        e.bind("<FocusOut>", lambda _e: self.cargar(self.v_id.get().strip().upper()))
        tk.Label(fila_id, text="p. ej. P001", font=(FUENTE, 9), fg=C["suave"],
                 bg=C["tarjeta"]).pack(side="left", padx=10)

        self.vars = {}
        for g, grupo in enumerate(D.GRUPOS):
            caja = master.tarjeta(cuerpo)
            caja.grid(row=1 + g // 2, column=g % 2, sticky="nsew", padx=4, pady=4)
            tk.Label(caja, text=grupo.upper(), font=(FUENTE, 8, "bold"), fg=C["suave"],
                     bg=C["tarjeta"]).grid(row=0, column=0, columnspan=3, sticky="w", padx=14, pady=(10, 4))
            campos = [c for c in D.CAMPOS if c[4] == grupo]
            for i, (clave, etiqueta, tipo, detalle, _) in enumerate(campos, 1):
                tk.Label(caja, text=etiqueta, font=(FUENTE, 10), fg=C["texto"], bg=C["tarjeta"],
                         anchor="w", width=12).grid(row=i, column=0, sticky="w", padx=(14, 6), pady=3)
                v = tk.StringVar()
                if tipo == "num":
                    w = ttk.Entry(caja, textvariable=v, width=9, font=(FUENTE, 10), style="Ficha.TEntry")
                    unidad = detalle[2]
                else:
                    w = ttk.Combobox(caja, textvariable=v, values=["", *detalle], state="readonly", width=14,
                                     font=(FUENTE, 10), style="Ficha.TCombobox")
                    unidad = ""
                w.grid(row=i, column=1, sticky="w", pady=3)
                tk.Label(caja, text=unidad, font=(FUENTE, 9), fg=C["suave"], bg=C["tarjeta"],
                         anchor="w", width=6).grid(row=i, column=2, sticky="w", padx=(6, 14))
                self.vars[clave] = v
            if grupo == "Paciente":
                self.sc = tk.Label(caja, font=(FUENTE, 9), fg=C["suave"], bg=C["tarjeta"])
                self.sc.grid(row=len(campos) + 1, column=0, columnspan=3, sticky="w", padx=14)
            tk.Frame(caja, bg=C["tarjeta"], height=8).grid(row=99, column=0)
        for k in ("peso_kg", "talla_cm"):
            self.vars[k].trace_add("write", lambda *_: self.actualizar_sc())

        botones = tk.Frame(self, bg=C["fondo"])
        botones.pack(fill="x", padx=22, pady=(0, 16))
        Boton(botones, "Guardar", self.guardar, C["primario"], C["primario_hover"], tam=11, negrita=True,
              icono="guardar").pack(side="right")
        Boton(botones, "Ahora no", self.destroy, C["secundario"], C["secundario_hover"], color=C["texto"],
              tam=10, icono="cerrar").pack(side="right", padx=(0, 10))

        self.cargar(self.v_id.get())
        self.bind("<Return>", lambda _e: self.guardar())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.lift()
        self.attributes("-topmost", True)
        self.after(300, lambda: self.attributes("-topmost", False))
        e.focus_set()
        self.grab_set()

    def id_inicial(self):
        for _, f in D.leer_clinicos(SALIDA).iterrows():
            if self.imagen in str(f.get("imagenes") or "").split(";"):
                return f["id"]
        return D.id_desde_nombre(self.imagen)

    def cargar(self, pid):
        """Rellena la ventana con lo ya guardado para ese paciente."""
        if not pid or pid == self.cargado:
            return
        datos = D.ficha(SALIDA, pid)
        if not datos:
            return
        self.cargado = pid
        for clave, _, tipo, detalle, _ in D.CAMPOS:
            val = datos.get(clave)
            if val is None:
                txt = ""
            elif tipo == "num":
                txt = f"{float(val):g}".replace(".", ",")
            else:
                inverso = {str(v): k for k, v in detalle.items()}
                txt = inverso.get(str(val), inverso.get(str(val).split(".")[0], ""))
            self.vars[clave].set(txt)

    def actualizar_sc(self):
        try:
            p = float(self.vars["peso_kg"].get().replace(",", "."))
            t = float(self.vars["talla_cm"].get().replace(",", "."))
            self.sc.config(text=f"Superficie corporal: {(p * t / 3600) ** 0.5:.2f} m²".replace(".", ","))
        except ValueError:
            self.sc.config(text="")

    def guardar(self):
        pid = self.v_id.get().strip().upper()
        if not D.PATRON_ID.match(pid):
            messagebox.showerror("Código del paciente",
                                 "Escribe un código del tipo P001 (letras seguidas de números, sin espacios).",
                                 parent=self)
            return
        valores = {"id": pid}
        for clave, etiqueta, tipo, detalle, _ in D.CAMPOS:
            txt = self.vars[clave].get().strip()
            if not txt:
                continue
            if tipo == "opc":
                valores[clave] = detalle[txt]
                continue
            try:
                num = float(txt.replace(",", "."))
            except ValueError:
                messagebox.showerror("Dato no válido", f"{etiqueta}: «{txt}» no es un número.", parent=self)
                return
            mini, maxi, unidad = detalle
            if not mini <= num <= maxi:
                messagebox.showerror("Dato no válido",
                                     f"{etiqueta}: {txt} {unidad} está fuera del rango esperado "
                                     f"({mini:g}-{maxi:g} {unidad}).", parent=self)
                return
            valores[clave] = num
        D.guardar_ficha(SALIDA, valores, self.imagen)
        self.ok = True
        self.destroy()


class App(tk.Tk):
    COLUMNAS = [("imagen", "Imagen", 220, "w"), ("latidos", "Latidos", 70, "center"),
                ("vmax", "Vmax (m/s)", 95, "center"), ("grad", "Grad. medio (mmHg)", 140, "center"),
                ("vti", "VTI (cm)", 85, "center"), ("atet", "AT/ET", 75, "center"),
                ("estado", "Estado", 190, "w")]

    def __init__(self):
        super().__init__()
        self.title("Doppler continuo · Estenosis aórtica")
        self.f = self.winfo_fpixels("1i") / 96  # escalado de Windows (100 %, 125 %, 150 %…)
        # sin pasar del alto útil de la pantalla (descontando la barra de tareas)
        self.geometry(f"{self.px(1040)}x{min(self.px(780), self.winfo_screenheight() - self.px(90))}+40+20")
        self.minsize(self.px(860), self.px(700))
        self.configure(bg=C["fondo"])
        self.figuras = {}  # fila de la tabla -> ruta de la figura de control
        self.imagenes = {}  # fila de la tabla -> nombre de la imagen
        self.estilos()

        # Cabecera
        cab = tk.Frame(self, bg=C["cabecera"])
        cab.pack(fill="x")
        tk.Label(cab, text="Doppler continuo aórtico", font=(FUENTE, 18, "bold"),
                 fg=C["cabecera_txt"], bg=C["cabecera"]).pack(anchor="w", padx=28, pady=(18, 0))
        tk.Label(cab, text="Morfología de la curva y textura del espectro · prueba de concepto",
                 font=(FUENTE, 10), fg=C["cabecera_sub"], bg=C["cabecera"]).pack(anchor="w", padx=28, pady=(0, 10))

        # Pestañas
        barra_p = tk.Frame(cab, bg=C["cabecera"])
        barra_p.pack(anchor="w", padx=20)
        self.pestanas = {}
        for clave, texto, icono in (("analisis", "Análisis", "analisis"), ("datos", "Datos", "tabla")):
            caja = tk.Frame(barra_p, bg=C["cabecera"], cursor="hand2")
            caja.pack(side="left", padx=(0, 6))
            fila = tk.Frame(caja, bg=C["cabecera"])
            fila.pack(padx=10, pady=(4, 6))
            fi = fuente_iconos()
            glifo, alternativo = ICONOS[icono]
            ico = tk.Label(fila, text=glifo if fi else alternativo, font=(fi, 11) if fi else (FUENTE, 11),
                           bg=C["cabecera"])
            ico.pack(side="left", padx=(0, 8))
            txt = tk.Label(fila, text=texto, font=(FUENTE, 11, "bold"), bg=C["cabecera"])
            txt.pack(side="left")
            raya = tk.Frame(caja, height=3, bg=C["cabecera"])
            raya.pack(fill="x")
            for w in (caja, fila, ico, txt):
                w.bind("<Button-1>", lambda _e, k=clave: self.mostrar(k))
            self.pestanas[clave] = (ico, txt, raya)

        cuerpo = tk.Frame(self, bg=C["fondo"])
        self.vistas = {"analisis": cuerpo}

        # Tarjeta de acciones
        acc = self.tarjeta(cuerpo)
        acc.pack(fill="x")
        der = tk.Frame(acc, bg=C["tarjeta"])
        der.pack(side="right", anchor="n", padx=20, pady=18)
        # Mismo tamaño de letra y relleno: los dos botones miden lo mismo; el principal se distingue por el color
        self.b1 = Boton(der, "Analizar imágenes", self.elegir, C["primario"], C["primario_hover"],
                        tam=11, negrita=True, padx=22, pady=11, icono="abrir", apagado=C["primario_off"])
        self.b1.pack(fill="x")
        Boton(der, "Abrir carpeta de resultados", self.abrir_salida, C["secundario"], C["secundario_hover"],
              color=C["texto"], tam=11, padx=22, pady=11, icono="carpeta").pack(fill="x", pady=(8, 0))

        izq = tk.Frame(acc, bg=C["tarjeta"])
        izq.pack(side="left", fill="both", expand=True, padx=20, pady=18)
        tk.Label(izq, text="Analizar imágenes", font=(FUENTE, 13, "bold"), fg=C["texto"],
                 bg=C["tarjeta"]).pack(anchor="w")
        tk.Label(izq, text="DICOM, PNG o JPG. Puedes elegir varias a la vez. "
                           "Al terminar se abre la figura de control.",
                 font=(FUENTE, 10), fg=C["suave"], bg=C["tarjeta"]).pack(anchor="w", pady=(2, 0))

        self.seccion(izq, "Calibración")
        self.modo = tk.StringVar(value="auto")
        for valor, texto in (
                ("auto", "Automática; si falla, calibrar a mano"),
                ("manual", "Calibrar a mano (sin calibración automática)"),
                ("anterior", "Misma calibración manual que la imagen anterior")):
            ttk.Radiobutton(izq, text=texto, value=valor, variable=self.modo,
                            style="Tarjeta.TRadiobutton").pack(anchor="w", pady=1)

        self.seccion(izq, "Datos del paciente")
        self.pedir = tk.BooleanVar(value=True)
        ttk.Checkbutton(izq, text="Pedir los datos del paciente (clínicos y etiqueta) después de cada imagen",
                        variable=self.pedir, style="Tarjeta.TCheckbutton").pack(anchor="w", pady=1)

        # Tarjeta de resultados
        tab = self.tarjeta(cuerpo)
        tab.pack(fill="both", expand=True, pady=(16, 0))
        cab_tab = tk.Frame(tab, bg=C["tarjeta"])
        cab_tab.pack(fill="x", padx=20, pady=(14, 8))
        tk.Label(cab_tab, text="Resultados de esta sesión", font=(FUENTE, 13, "bold"), fg=C["texto"],
                 bg=C["tarjeta"]).pack(side="left")
        Boton(cab_tab, "Datos del paciente", self.editar_ficha, C["secundario"], C["secundario_hover"],
              color=C["texto"], tam=9, padx=12, pady=5, icono="paciente").pack(side="right")
        tk.Label(cab_tab, text="Latido más desfavorable · doble clic en una fila para ver su figura",
                 font=(FUENTE, 9), fg=C["suave"], bg=C["tarjeta"]).pack(side="right", padx=12)
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
        # (se empaqueta antes que la tabla para que la tabla no lo aplaste en ventanas bajas)
        self.log = tk.Text(tab, height=6, font=("Consolas", 9), bg="#f7f9fb", fg=C["texto"],
                           relief="flat", highlightthickness=1, highlightbackground=C["borde"],
                           padx=10, pady=6, wrap="word")
        self.log.pack(side="bottom", fill="x", padx=20, pady=(0, 16), before=marco)
        tk.Label(tab, text="Registro", font=(FUENTE, 9, "bold"), fg=C["suave"],
                 bg=C["tarjeta"]).pack(side="bottom", anchor="w", padx=20, pady=(12, 2), before=marco)
        self.log.tag_configure("error", foreground=C["error"])

        # Barra de estado
        self.estado = tk.Label(self, text="Listo", anchor="w", font=(FUENTE, 9), fg=C["suave"],
                               bg=C["fondo"])
        self.estado.pack(side="bottom", fill="x", padx=26, pady=(0, 10))
        self.vistas["datos"] = self.vista_datos()
        self.mostrar("analisis")
        self.escribir("Listo. Pulsa «Analizar imágenes».\n")

    # ---- pestañas ----
    def mostrar(self, clave):
        for k, v in self.vistas.items():
            v.pack_forget()
            ico, txt, raya = self.pestanas[k]
            activa = k == clave
            for w in (ico, txt):
                w.config(fg=C["cabecera_txt"] if activa else C["cabecera_sub"])
            raya.config(bg=C["primario"] if activa else C["cabecera"])
        self.vistas[clave].pack(fill="both", expand=True, padx=24, pady=20, after=self.estado)
        if clave == "datos":
            self.cargar_tabla()

    TABLAS = {"Combinada: imágenes + datos clínicos": D.ARCH_COMBINADO,
              "Imágenes (medidas de la curva)": D.ARCH_RESUMEN,
              "Datos clínicos y etiqueta": D.ARCH_CLINICOS}

    def vista_datos(self):
        cuerpo = tk.Frame(self, bg=C["fondo"])
        t = self.tarjeta(cuerpo)
        t.pack(fill="both", expand=True)
        cab = tk.Frame(t, bg=C["tarjeta"])
        cab.pack(fill="x", padx=20, pady=(14, 4))
        tk.Label(cab, text="Datos guardados", font=(FUENTE, 13, "bold"), fg=C["texto"],
                 bg=C["tarjeta"]).pack(side="left")
        Boton(cab, "Abrir carpeta", self.abrir_salida, C["secundario"], C["secundario_hover"],
              color=C["texto"], tam=9, padx=12, pady=5, icono="carpeta").pack(side="right")
        Boton(cab, "Actualizar", self.cargar_tabla, C["secundario"], C["secundario_hover"],
              color=C["texto"], tam=9, padx=12, pady=5, icono="recargar").pack(side="right", padx=(0, 8))
        self.v_tabla = tk.StringVar(value=next(iter(self.TABLAS)))
        cb = ttk.Combobox(cab, textvariable=self.v_tabla, values=list(self.TABLAS), state="readonly",
                          width=34, font=(FUENTE, 10), style="Ficha.TCombobox")
        cb.pack(side="right", padx=(0, 12))
        cb.bind("<<ComboboxSelected>>", lambda _e: self.cargar_tabla())
        self.info_tabla = tk.Label(t, font=(FUENTE, 9), fg=C["suave"], bg=C["tarjeta"], anchor="w")
        self.info_tabla.pack(fill="x", padx=20, pady=(0, 8))

        marco = tk.Frame(t, bg=C["tarjeta"])
        marco.pack(fill="both", expand=True, padx=20, pady=(0, 16))
        self.datos = ttk.Treeview(marco, show="headings", style="Resultados.Treeview", selectmode="browse")
        bv = ttk.Scrollbar(marco, orient="vertical", command=self.datos.yview)
        bh = ttk.Scrollbar(marco, orient="horizontal", command=self.datos.xview)
        self.datos.configure(yscrollcommand=bv.set, xscrollcommand=bh.set)
        self.datos.grid(row=0, column=0, sticky="nsew")
        bv.grid(row=0, column=1, sticky="ns")
        bh.grid(row=1, column=0, sticky="ew")
        marco.rowconfigure(0, weight=1)
        marco.columnconfigure(0, weight=1)
        self.datos.tag_configure("par", background="#f7f9fb")
        return cuerpo

    def cargar_tabla(self):
        """Muestra el CSV elegido (solo lectura)."""
        import pandas as pd
        arch = self.TABLAS[self.v_tabla.get()]
        ruta = os.path.join(SALIDA, arch)
        try:
            if arch == D.ARCH_COMBINADO:
                d = D.combinar(SALIDA)
            elif os.path.exists(ruta):
                d = pd.read_csv(ruta)
            else:
                d = pd.DataFrame()
        except Exception as ex:
            d = pd.DataFrame()
            self.info_tabla.config(text=f"No se ha podido leer {arch}: {ex}", fg=C["error"])
        else:
            if len(d):
                txt = f"{arch} · {len(d)} fila(s) · {len(d.columns)} columnas · solo lectura"
                if "etiqueta" in d:
                    n = d["etiqueta"].value_counts()
                    txt += (f" · severas {n.get('severa', 0)}, no severas {n.get('no severa', 0)}, "
                            f"dudosas {n.get('dudosa', 0)}, sin etiqueta {int(d['etiqueta'].isna().sum())}")
                self.info_tabla.config(text=txt, fg=C["suave"])
            else:
                self.info_tabla.config(text=f"Todavía no hay datos en {arch}.", fg=C["suave"])
        self.datos.delete(*self.datos.get_children())
        cols = list(d.columns)
        self.datos["columns"] = cols
        fuente = tkfont.Font(family=FUENTE, size=10)
        filas = [[self.formato(v) for v in fila] for fila in d.itertuples(index=False)]
        for j, c in enumerate(cols):
            ancho = max([fuente.measure(c)] + [fuente.measure(f[j]) for f in filas[:200]]) + self.px(24)
            self.datos.heading(c, text=c, anchor="w")
            self.datos.column(c, width=min(max(ancho, self.px(60)), self.px(280)), anchor="w", stretch=False)
        for i, f in enumerate(filas):
            self.datos.insert("", "end", values=f, tags=("par",) if i % 2 else ())

    @staticmethod
    def formato(v):
        if isinstance(v, float):
            if v != v:  # NaN
                return ""
            if v.is_integer() and abs(v) < 1e6:
                return str(int(v))
            return f"{v:.3f}".rstrip("0").rstrip(".")
        return str(v)

    def abrir_salida(self):
        os.makedirs(SALIDA, exist_ok=True)
        abrir(SALIDA)

    # ---- datos del paciente ----
    def pedir_ficha(self, imagen):
        f = FichaPaciente(self, imagen)
        try:
            self.wait_window(f)
        except tk.TclError:
            pass
        if f.ok:
            self.escribir(f"  Datos del paciente guardados ({D.ARCH_CLINICOS}).\n")

    def editar_ficha(self):
        sel = self.tabla.focus()
        if not sel or sel not in self.imagenes:
            messagebox.showinfo("Datos del paciente", "Elige primero una imagen analizada en la tabla.",
                                parent=self)
            return
        self.pedir_ficha(self.imagenes[sel])

    def estilos(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        self.indicadores(s)
        s.configure("Vertical.TScrollbar", background=C["secundario"], troughcolor=C["tarjeta"],
                    bordercolor=C["tarjeta"], arrowcolor=C["suave"], lightcolor=C["secundario"],
                    darkcolor=C["secundario"], gripcount=0)
        s.map("Vertical.TScrollbar", background=[("active", C["secundario_hover"])])
        s.configure("Horizontal.TScrollbar", background=C["secundario"], troughcolor=C["tarjeta"],
                    bordercolor=C["tarjeta"], arrowcolor=C["suave"], lightcolor=C["secundario"],
                    darkcolor=C["secundario"], gripcount=0)
        s.map("Horizontal.TScrollbar", background=[("active", C["secundario_hover"])])
        s.configure("Ficha.TEntry", padding=(6, 4), bordercolor=C["borde"], lightcolor=C["borde"],
                    fieldbackground="#ffffff")
        s.map("Ficha.TEntry", bordercolor=[("focus", C["primario"])], lightcolor=[("focus", C["primario"])])
        s.configure("Ficha.TCombobox", padding=(6, 4), bordercolor=C["borde"], lightcolor=C["borde"],
                    arrowcolor=C["suave"], background=C["tarjeta"])
        s.map("Ficha.TCombobox", fieldbackground=[("readonly", "#ffffff")],
              bordercolor=[("focus", C["primario"])], selectbackground=[("readonly", "#ffffff")],
              selectforeground=[("readonly", C["texto"])])
        self.option_add("*TCombobox*Listbox.font", (FUENTE, 10))
        self.option_add("*TCombobox*Listbox.selectBackground", "#dbe7f5")
        self.option_add("*TCombobox*Listbox.selectForeground", C["texto"])
        s.configure("Resultados.Treeview", font=(FUENTE, 10), rowheight=self.px(30), background=C["tarjeta"],
                    fieldbackground=C["tarjeta"], foreground=C["texto"], borderwidth=0)
        s.configure("Resultados.Treeview.Heading", font=(FUENTE, 9, "bold"), background="#f1f4f8",
                    foreground=C["suave"], relief="flat", padding=(8, 6))
        s.map("Resultados.Treeview.Heading", background=[("active", "#e6ebf1")])
        s.map("Resultados.Treeview", background=[("selected", "#dbe7f5")],
              foreground=[("selected", C["texto"])])
        s.layout("Resultados.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])

    def indicadores(self, s):
        """Casilla (marca ✓) y opción excluyente (punto) dibujadas con suavizado, con estado al pasar el ratón
        o al recibir el foco con el teclado."""
        k = 4  # se dibuja a 4× y se reduce para suavizar los bordes
        lado, hueco = self.px(18), self.px(8)
        N, H = lado * k, (lado + hueco) * k
        reposo, linea = "#8a97a6", max(k, int(1.6 * k * self.f))

        def imagen(dibujar):
            im = Image.new("RGBA", (H, N), (0, 0, 0, 0))
            dibujar(ImageDraw.Draw(im))
            return ImageTk.PhotoImage(im.resize((lado + hueco, lado), Image.LANCZOS), master=self)

        def casilla(borde, relleno=None, marca=False):
            def f(d):
                d.rounded_rectangle([k, k, N - k, N - k], radius=4 * k, outline=borde, width=linea,
                                    fill=relleno or C["tarjeta"])
                if marca:
                    d.line([(0.26 * N, 0.52 * N), (0.43 * N, 0.69 * N), (0.75 * N, 0.33 * N)],
                           fill="#ffffff", width=int(2.2 * k * self.f), joint="curve")
            return imagen(f)

        def opcion(borde, punto=False):
            def f(d):
                d.ellipse([k, k, N - k, N - k], outline=borde, width=linea, fill=C["tarjeta"])
                if punto:
                    d.ellipse([0.29 * N, 0.29 * N, 0.71 * N, 0.71 * N], fill=borde)
            return imagen(f)

        P_, PH = C["primario"], C["primario_hover"]
        self._ind = {
            "c_no": casilla(reposo), "c_hover": casilla(P_), "c_si": casilla(P_, P_, True),
            "c_si_hover": casilla(PH, PH, True),
            "r_no": opcion(reposo), "r_hover": opcion(P_), "r_si": opcion(P_, True), "r_si_hover": opcion(PH, True),
        }
        i = self._ind
        s.element_create("Tarjeta.ind_casilla", "image", i["c_no"],
                         ("selected", "active", i["c_si_hover"]), ("selected", i["c_si"]),
                         ("active", i["c_hover"]), ("focus", i["c_hover"]), sticky="w")
        s.element_create("Tarjeta.ind_opcion", "image", i["r_no"],
                         ("selected", "active", i["r_si_hover"]), ("selected", i["r_si"]),
                         ("active", i["r_hover"]), ("focus", i["r_hover"]), sticky="w")
        for estilo, elemento in (("Tarjeta.TCheckbutton", "Tarjeta.ind_casilla"),
                                 ("Tarjeta.TRadiobutton", "Tarjeta.ind_opcion")):
            s.layout(estilo, [("Checkbutton.padding", {"sticky": "nswe", "children": [
                (elemento, {"side": "left", "sticky": ""}),
                ("Checkbutton.label", {"side": "left", "sticky": "nswe"})]})])
            s.configure(estilo, background=C["tarjeta"], foreground=C["texto"], font=(FUENTE, 10), padding=(0, 2))
            s.map(estilo, background=[("active", C["tarjeta"])])

    def px(self, n):
        return int(round(n * self.f))

    def seccion(self, master, titulo):
        tk.Label(master, text=titulo.upper(), font=(FUENTE, 8, "bold"), fg=C["suave"],
                 bg=C["tarjeta"]).pack(anchor="w", pady=(14, 3))

    def tarjeta(self, master):
        return tk.Frame(master, bg=C["tarjeta"], highlightthickness=1, highlightbackground=C["borde"],
                        highlightcolor=C["borde"])

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
            modo = self.modo.get()
            self.escribir(f"\n· {os.path.basename(r)}: calibrando…\n")
            self.update()
            if modo == "manual":
                cal = os.path.splitext(r)[0] + "_calibracion.json"
                if os.path.exists(cal):
                    os.remove(cal)
                falta = True
            elif modo == "anterior":
                # sin calibración anterior o con otro tamaño de imagen: se calibra a mano y pasa a ser la anterior
                falta = not self.reutilizar(r)
            else:
                falta = necesita_calibracion(r)
                if falta:
                    self.escribir("  La calibración automática no ha funcionado.\n", "error")
            if falta:
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
            self.escribir("  Todavía no hay ninguna calibración manual anterior; hay que calibrarla.\n", "error")
            return False
        tam = tamano(ruta)
        if ult.get("tamano_imagen") and tam and ult["tamano_imagen"] != tam:
            self.escribir("  Tiene distinto tamaño que la imagen calibrada antes; hay que calibrarla.\n", "error")
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
                fila = self.fila(res["imagen"], ["0", "–", "–", "–", "–", "Sin latidos válidos"], "aviso")
            else:
                ref = int(res["latido_referencia"])
                self.escribir(
                    f"  {res['n_latidos']} latidos válidos · latido más desfavorable L{ref}: "
                    f"Vmax {res['vmax_ms']:.2f} m/s · grad. medio {res['grad_medio_mmHg']:.1f} mmHg · "
                    f"VTI {res['vti_cm']:.1f} cm · AT/ET {res['at_et']:.2f}\n")
                if res["n_descartados"]:
                    self.escribir(f"  Descartados {res['n_descartados']}: {res['motivos_descarte']}\n")
                estado = f"✓ L{ref} de {res['n_latidos']}"
                if res["n_descartados"]:
                    estado += f" · {res['n_descartados']} descart."
                fila = self.fila(res["imagen"], [
                    res["n_latidos"], f"{res['vmax_ms']:.2f}", f"{res['grad_medio_mmHg']:.1f}",
                    f"{res['vti_cm']:.1f}", f"{res['at_et']:.2f}", estado],
                    "aviso" if res.get("avisos_calibracion") else "ok")
            self.figuras[fila] = fig
            self.imagenes[fila] = res["imagen"]
            self.actualizar_resumen(res)
            self.escribir(f"  Figura de control: {fig}\n")
            if getattr(self, "abrir_figura", True):
                abrir(fig)
            analizada = res["imagen"]
        except Exception as ex:
            analizada = None
            self.escribir(f"  ERROR: {ex}\n", "error")
            self.fila(os.path.basename(ruta), ["–"] * 5 + ["✗ Error (ver registro)"], "error")
            with open(os.path.join(SALIDA, "errores.log"), "a", encoding="utf-8") as f:
                f.write(f"\n=== {ruta}\n{traceback.format_exc()}")
        finally:
            self.b1.activar(True)
            self.config(cursor="")
        if analizada and self.pedir.get():
            self.pedir_ficha(analizada)

    def actualizar_resumen(self, res):
        import pandas as pd
        ruta = os.path.join(SALIDA, "resumen_imagenes.csv")
        d = pd.read_csv(ruta) if os.path.exists(ruta) else pd.DataFrame()
        if len(d) and "imagen" in d:
            d = d[d["imagen"] != res["imagen"]]
        d = pd.concat([d, pd.DataFrame([res])], ignore_index=True)
        d.to_csv(ruta, index=False)
        D.combinar(SALIDA)


if __name__ == "__main__":
    nitidez_windows()
    try:
        App().mainloop()
    except Exception:
        messagebox.showerror("Error", traceback.format_exc())
