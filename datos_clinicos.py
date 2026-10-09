"""
Datos clínicos y etiqueta de cada paciente, unidos a las medidas de la imagen por el ID (P001…).

- `datos_clinicos.csv`: una fila por paciente con lo que se introduce en la ventana «Datos del paciente».
- `datos_combinados.csv`: `resumen_imagenes.csv` + datos clínicos, una fila por imagen. Es la tabla de análisis.

Nunca se guardan datos identificativos: solo el código del paciente y la edad (no la fecha de nacimiento).
"""
import os
import re

import numpy as np
import pandas as pd

ARCH_CLINICOS = "datos_clinicos.csv"
ARCH_RESUMEN = "resumen_imagenes.csv"
ARCH_COMBINADO = "datos_combinados.csv"

PATRON_ID = re.compile(r"^[A-Za-z]{1,4}\d{1,6}$")  # P001, HUC0123…

SI_NO = {"Sí": 1, "No": 0}

# (clave, etiqueta, tipo, detalle, grupo)
#   tipo "num": detalle = (mínimo, máximo, unidad)
#   tipo "opc": detalle = {texto en pantalla: valor guardado}
CAMPOS = [
    ("edad", "Edad", "num", (18, 110, "años"), "Paciente"),
    ("sexo", "Sexo", "opc", {"Hombre": "hombre", "Mujer": "mujer"}, "Paciente"),
    ("peso_kg", "Peso", "num", (25, 250, "kg"), "Paciente"),
    ("talla_cm", "Talla", "num", (100, 230, "cm"), "Paciente"),
    ("hta", "HTA", "opc", SI_NO, "Factores de riesgo"),
    ("diabetes", "Diabetes", "opc", SI_NO, "Factores de riesgo"),
    ("dislipemia", "Dislipemia", "opc", SI_NO, "Factores de riesgo"),
    ("erc", "ERC", "opc", SI_NO, "Factores de riesgo"),
    ("tabaquismo", "Tabaquismo", "opc", {"Nunca": "nunca", "Exfumador": "exfumador", "Activo": "activo"},
     "Factores de riesgo"),
    ("ritmo", "Ritmo", "opc", {"Sinusal": "sinusal", "FA": "fa", "Otro": "otro"}, "Contexto ecográfico"),
    ("fevi_pct", "FEVI", "num", (5, 90, "%"), "Contexto ecográfico"),
    ("bajo_flujo", "Bajo flujo", "opc", SI_NO, "Contexto ecográfico"),
    ("etiqueta", "Estenosis", "opc", {"Severa": "severa", "No severa": "no severa", "Dudosa": "dudosa"},
     "Etiqueta"),
    ("fuente_etiqueta", "Según", "opc",
     {"Informe eco": "informe", "Área valvular": "ava", "Calcio por TC": "calcio_tc",
      "Eco de estrés": "eco_estres", "TAVI o cirugía": "sustitucion"}, "Etiqueta"),
    ("informe_vmax_ms", "Vmax", "num", (0.5, 7, "m/s"), "Mediciones del informe"),
    ("informe_grad_medio_mmHg", "Grad. medio", "num", (0, 150, "mmHg"), "Mediciones del informe"),
    ("informe_vti_cm", "VTI", "num", (5, 250, "cm"), "Mediciones del informe"),
    ("informe_ava_cm2", "Área valvular", "num", (0.2, 5, "cm²"), "Mediciones del informe"),
]
GRUPOS = list(dict.fromkeys(c[4] for c in CAMPOS))
# Columnas calculadas: superficie corporal (Mosteller) y severa 1/0 (vacía si es dudosa)
COLUMNAS = ["id", *[c[0] for c in CAMPOS], "sc_m2", "severa", "imagenes"]


def id_desde_nombre(nombre):
    """P001 a partir de «P001», «P001_cw2.png»…; cadena vacía si el nombre no empieza por un código."""
    m = re.match(r"([A-Za-z]{1,4}\d{1,6})(?![A-Za-z\d])", os.path.basename(nombre))
    return m.group(1).upper() if m else ""


def leer_clinicos(carpeta):
    ruta = os.path.join(carpeta, ARCH_CLINICOS)
    if not os.path.exists(ruta):
        return pd.DataFrame(columns=COLUMNAS)
    return pd.read_csv(ruta, dtype={"id": str, "imagenes": str})


def ficha(carpeta, id_paciente):
    """Datos guardados de un paciente como diccionario (vacío si no hay)."""
    d = leer_clinicos(carpeta)
    fila = d[d["id"] == id_paciente]
    if not len(fila):
        return {}
    return {k: v for k, v in fila.iloc[0].items() if not (isinstance(v, float) and np.isnan(v))}


def guardar_ficha(carpeta, valores, imagen=None):
    """Guarda (o sustituye) la fila del paciente y regenera la tabla combinada."""
    os.makedirs(carpeta, exist_ok=True)
    d = leer_clinicos(carpeta)
    pid = valores["id"]
    previa = d[d["id"] == pid]
    imgs = []
    if len(previa) and isinstance(previa.iloc[0].get("imagenes"), str):
        imgs = [i for i in previa.iloc[0]["imagenes"].split(";") if i]
    if imagen and imagen not in imgs:
        imgs.append(imagen)
    # una imagen pertenece a un solo paciente: si estaba asignada a otro, se le quita
    if imagen:
        for i, f in d[d["id"] != pid].iterrows():
            otras = [x for x in str(f.get("imagenes") or "").split(";") if x and x != "nan"]
            if imagen in otras:
                d.at[i, "imagenes"] = ";".join(x for x in otras if x != imagen)

    fila = {c: valores.get(c, np.nan) for c in COLUMNAS}
    try:
        fila["sc_m2"] = round(float(np.sqrt(valores["peso_kg"] * valores["talla_cm"] / 3600)), 2)
    except (KeyError, TypeError):
        fila["sc_m2"] = np.nan
    fila["severa"] = {"severa": 1, "no severa": 0}.get(valores.get("etiqueta"), np.nan)
    fila["imagenes"] = ";".join(imgs)

    d = d[d["id"] != pid]
    d = pd.concat([d.astype(object), pd.DataFrame([fila]).astype(object)], ignore_index=True)
    d = d.sort_values("id", ignore_index=True)[COLUMNAS]
    d.to_csv(os.path.join(carpeta, ARCH_CLINICOS), index=False)
    combinar(carpeta)


def combinar(carpeta):
    """Une resumen_imagenes.csv con los datos clínicos. Devuelve la tabla (vacía si no hay imágenes)."""
    ruta = os.path.join(carpeta, ARCH_RESUMEN)
    if not os.path.exists(ruta):
        return pd.DataFrame()
    res = pd.read_csv(ruta)
    cli = leer_clinicos(carpeta)
    # imagen -> paciente: primero lo asignado en la ventana; si no, el código del nombre del archivo
    asignadas = {}
    for _, f in cli.iterrows():
        for img in str(f.get("imagenes") or "").split(";"):
            if img and img != "nan":
                asignadas[img] = f["id"]
    ids = pd.Series([asignadas.get(i, id_desde_nombre(str(i))) for i in res["imagen"]], dtype=str, name="id")
    res = pd.concat([ids, res], axis=1)
    cli = cli.drop(columns=["imagenes"]).astype({"id": str})
    comb = res.merge(cli, on="id", how="left")
    comb["id"] = comb["id"].replace("", np.nan)
    # columnas clínicas justo después del ID, antes de las ~130 variables de la imagen
    clin = [c for c in COLUMNAS if c not in ("id", "imagenes")]
    orden = ["imagen", "id", *clin, *[c for c in res.columns if c not in ("imagen", "id")]]
    comb = comb[orden]
    comb.to_csv(os.path.join(carpeta, ARCH_COMBINADO), index=False)
    return comb
