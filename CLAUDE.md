# Proyecto: severidad de la estenosis aórtica a partir de una imagen de Doppler continuo

## Objetivo clínico
Estudio de investigación para estimar la **probabilidad de que una estenosis aórtica sea severa** a partir de
**una sola imagen de Doppler continuo (CW)** a través de la válvula aórtica, más unas pocas variables
demográficas y clínicas (edad, sexo, HTA, diabetes, dislipemia, ERC…).

La hipótesis es que la **morfología de la curva** y la **textura del espectro** contienen información que no
se ve a simple vista ni con las mediciones clásicas (Vmax, gradiente medio, VTI).

El usuario es cardiólogo (ecocardiografía), **no programador**. Usa Windows y trabaja con doble clic
(`1_INSTALAR.bat` / `2_ANALIZAR_IMAGEN.bat`), no con la terminal. Explicaciones en español, breves y sin jerga.

## Decisiones de diseño (no cambiar sin hablarlo)
- **Evitar la circularidad.** La severidad se define con la propia Vmax y el gradiente. Por eso el valor
  del proyecto está en la **forma normalizada** (tiempo/ET, velocidad/Vmax) y en el **valor incremental**
  sobre Vmax y gradiente, sobre todo en la zona gris (Vmax 3-4 m/s) y en el bajo flujo-bajo gradiente.
- **Etiqueta** (severa / no severa): sale del informe ecocardiográfico, nunca de la imagen procesada.
  Alternativa más robusta: sustitución valvular (TAVI o cirugía) durante el seguimiento.
- **Fuga de información.** Hay que eliminar las mediciones grabadas en la imagen (calipers, texto). El código
  quita las anotaciones de color, pero las blancas o grises no.
- **Modelo final previsto:** regresión logística (probabilidad calibrada), comparando tres modelos:
  solo clínico, solo imagen y combinado. División por paciente, validación cruzada anidada, AUC,
  calibración y Brier. Publicación según TRIPOD+AI.
- **Fase actual:** prueba de concepto con 10-20 imágenes. El objetivo es comprobar que el procesado mide
  bien. Con esta muestra no se entrena ningún modelo.

## Estructura del código
| Archivo | Función |
|---|---|
| `procesar.py` | Pipeline: lectura DICOM/PNG/JPG + calibración → recorte → ECG → envolvente (umbral adaptativo por profundidad, mediana/MAD por fila) → latidos → medidas clásicas → forma normalizada → textura (GLCM + PyRadiomics opcional) → figura de control. Parámetros en `PARAM`. |
| `app.py` | Interfaz tkinter: elegir imágenes, calibración con 6 clics (`Calibrador`), reutilizar la última calibración, procesar y abrir resultados. |
| `calibrar.py` | Calibración por línea de comandos (uso avanzado). |
| `sintetico.py` | Generador de imágenes CW sintéticas con verdad conocida (`*_verdad.json`). |
| `validar_sintetico.py` | Validación: Bland-Altman e ICC frente a la verdad sintética. |
| `ejemplo_real/` | Figura real (JASE 2017, Philips, 150 mm/s) ya calibrada. Es la referencia para casos reales. |
| `1_INSTALAR.bat`, `2_ANALIZAR_IMAGEN.bat` | Lanzadores de Windows. Deben tener finales de línea CRLF. |

Salidas en `resultados/`:
- `<imagen>_control.png`
- `<imagen>_latidos.csv`
- `<imagen>_curva_normalizada.csv`
- `<imagen>_latidoN_normalizado.png`
- `resumen_imagenes.csv`, con una fila por imagen, que se une a la hoja de recogida de datos por el ID (P001…).

## Cómo comprobar cambios
Después de tocar `procesar.py`:
1. `python validar_sintetico.py --n 5 --salida validacion`. Criterio: error inferior al 5-10 % e ICC superior a 0,9 en Vmax, gradiente medio, VTI y AT/ET.
2. `python procesar.py ejemplo_real/jase2017_cw.png --salida ejemplo_real/resultados` y **mirar la figura de control**. Referencias: Vmax ≈ 4,2-4,3 m/s, gradiente medio ≈ 46 mmHg, ET ≈ 270-280 ms (la figura marca unos 279 ms).
3. Las imágenes reales mandan sobre las sintéticas: no ajustes el código solo para que pase la validación sintética.

## Problemas conocidos / pendientes
- **AT:** sale unos 14 ms largo (16 % en los sintéticos) porque el clic de apertura valvular adelanta el inicio de la eyección.
- **ET:** sale unos 26 ms largo.
- Un intento de detectar "mesetas" de clic en `_cruce` empeoró la imagen real y se revirtió.
- Pendiente: script de anonimización DICOM (etiquetas y texto grabado), análisis de concordancia con las mediciones del informe, PCA funcional de las curvas normalizadas y comparación exploratoria entre severas y no severas.

## Normas
- **Nunca** guardar datos identificativos de pacientes en el proyecto. Solo códigos (P001…) e imágenes anonimizadas.
- No romper el flujo de doble clic. Si añades dependencias, actualiza `requirements.txt` y `1_INSTALAR.bat`.
- PyRadiomics es opcional; todo debe funcionar sin ella.
- Código y comentarios en español, como el resto del proyecto. Actualiza el `README.md` si cambia el uso o los resultados de la validación.
