# Procesado de Doppler continuo aórtico — prueba de concepto (paso 4)

Código para extraer de **una sola imagen de Doppler continuo (CW)** la envolvente de la curva,
las medidas clásicas y las características de forma y textura que alimentarán el modelo.

## Contenido

| Archivo | Para qué sirve |
|---|---|
| `1_INSTALAR.bat` · `2_ANALIZAR_IMAGEN.bat` | **Doble clic**: instalar (una vez) y analizar imágenes. |
| `app.py` | La aplicación con ventanas que abre `2_ANALIZAR_IMAGEN.bat`. |
| `procesar.py` | El procesado completo (pasos 4.1 a 4.7). Acepta DICOM, PNG o JPG, o una carpeta entera. |
| `calibrar.py` | Calibra imágenes PNG/JPG (capturas o figuras de artículos), que no traen la calibración del DICOM. |
| `sintetico.py` | Genera imágenes **sintéticas** de CW con valores conocidos, para probar el código. |
| `validar_sintetico.py` | Compara la medición automática con los valores reales (Bland-Altman, ICC). |
| `datos_sinteticos/` | 3 imágenes de ejemplo (severa, moderada, leve) en DICOM y PNG. |
| `resultados/` | Salida del procesado de esas imágenes. |
| `validacion/` | Resultado de la validación con 15 imágenes sintéticas (50 latidos). |
| `ejemplo_real/` | La imagen real que enviaste, calibrada y procesada. |

## 1. Uso con doble clic (Windows)

1. **Solo la primera vez:** doble clic en **`1_INSTALAR.bat`**. Se abre una ventana negra que instala todo y termina con «LISTO». Si no tienes Python, te dirá dónde descargarlo; al instalarlo marca *«Add Python to PATH»*.
2. **Cada vez que quieras analizar:** doble clic en **`2_ANALIZAR_IMAGEN.bat`** → botón **«Analizar imagen…»** → eliges la imagen (o varias).
3. Si la imagen es PNG/JPG (o un DICOM sin calibración) se abre una ventana que te pide **6 clics**:
   esquina superior izquierda y esquina inferior derecha del espectro · línea de base · una marca de la escala (te pregunta su valor, p. ej. −4) · dos marcas de tiempo (te pregunta los segundos entre ellas).
   La calibración se guarda junto a la imagen y no se vuelve a pedir.
   Con la casilla **«Usar la misma calibración que la imagen anterior»** (activada por defecto) solo calibras la primera imagen: las siguientes del mismo tamaño usan esa misma calibración, también en otra sesión. Desactívala si cambias de ecógrafo, de escala de velocidad o de velocidad de barrido. Los DICOM con calibración propia nunca la piden.
   Puedes elegir varias imágenes a la vez: se procesan seguidas y al final se abre la carpeta de resultados.
4. Al terminar se abre la **figura de control**. Todo queda en la carpeta **`resultados`** (botón «Abrir carpeta de resultados»).

En `ejemplo_real/` está la figura del JASE 2017 (Philips, 150 mm/s) ya calibrada y procesada: Vmax 4,29 m/s, gradiente medio 46 mmHg, ET ≈ 275 ms (la figura marca ≈ 279 ms).

## 2. Uso avanzado (terminal, opcional)

```bash
.venv\Scripts\activate
python procesar.py carpeta_con_imagenes --salida resultados
python calibrar.py figura.jpg --region X0 Y0 X1 Y1 --base Y --marca Y VALOR --tiempo XA XB SEGUNDOS
```

## 3. Qué genera

Para cada imagen:

- **`<imagen>_control.png`**: la figura de control de calidad, que es lo que debe revisar el ecocardiografista. Muestra:
  - la imagen original con la región detectada;
  - el espectro con la envolvente en rojo, el inicio (verde) y el fin (azul) de la eyección, y las ondas R;
  - las curvas normalizadas;
  - una tabla de medidas por latido.
- **`<imagen>_latidos.csv`**: una fila por latido con todas las variables.
- **`<imagen>_curva_normalizada.csv`**: la curva de cada latido y la media, en 101 puntos (tiempo/ET frente a velocidad/Vmax). Es la entrada para el PCA funcional.
- **`<imagen>_latidoN_normalizado.png`**: el espectro de cada latido reescalado a 128×128 en coordenadas normalizadas. Es la entrada para textura o redes neuronales.

Para el conjunto: **`resumen_imagenes.csv`**, con una fila por imagen (media de los latidos) y el coeficiente de variación entre latidos. Es la tabla que se une a la hoja de recogida de datos por el ID del paciente.

### Variables extraídas (unas 130 por imagen)

**Medidas clásicas**

- `vmax_ms`, `grad_pico_mmHg`, `grad_medio_mmHg`, `v_media_ms`, `vti_cm`
- `at_ms`, `et_ms`, `at_et`
- `aceleracion_ms2`, `desaceleracion_ms2`
- `r_a_inicio_ms`: retraso desde la onda R hasta el inicio de la eyección.

**Forma de la curva normalizada** (`forma_*`). No dependen de la altura de la curva.

- `forma_u_pico`: posición del pico.
- `forma_area_norm`: factor de forma, es decir, VTI / (Vmax·ET). Vale 0,5 en un triángulo y más en una curva redondeada.
- `forma_centroide`, `forma_dispersion`, `forma_asimetria`, `forma_curtosis`: momentos de la curva.
- `forma_anchura_50/80/90`: fracción de la eyección por encima del 50, 80 y 90 % de Vmax. Miden lo redondeado del pico.
- `forma_curvatura_pico`, `forma_pend_subida_max`, `forma_pend_bajada_max`, `forma_ratio_areas`.
- `forma_fourier_1..4`: componentes armónicas de la curva.

**Interior del espectro** (`tex_*`, `glcm_*`, `rad_*`)

- Velocidad modal relativa: dónde está la banda más densa.
- Ensanchamiento espectral (rango intercuartílico).
- Distribución de la densidad por cuartos de la envolvente.
- Nitidez del borde y anchura del "plumeado".
- Entropía y matriz de co-ocurrencia (GLCM).
- Unas 74 variables de PyRadiomics: primer orden, GLCM, GLRLM y GLSZM.

## 4. Validación

**Imagen real** (`ejemplo_real/`): la envolvente sigue el borde del chorro en los dos latidos; ET medido ≈ 270-280 ms frente a ≈ 279 ms marcados en la propia figura.

**Imágenes sintéticas** (`python validar_sintetico.py --n 5`; 15 imágenes, 50 latidos):

| Medida | Sesgo | Límites de acuerdo 95 % | Error absoluto medio | ICC |
|---|---|---|---|---|
| Vmax | +0,06 m/s | +0,05 a +0,08 | 1,9 % | 0,998 |
| Gradiente medio | −0,7 mmHg | −2,4 a +1,1 | 2,2 % | 0,997 |
| VTI | +4,3 cm | +3,3 a +5,4 | 7,4 % | 0,987 |
| AT | +14 ms | +7 a +21 | 16 % | 0,87 |
| ET | +26 ms | +19 a +34 | 8,6 % | 0,51* |
| AT/ET | +0,018 | −0,015 a +0,051 | 7,7 % | 0,93 |

Vmax, gradientes, VTI, ET y AT/ET cumplen el criterio de la prueba de concepto (< 5-10 %). **El AT no lo cumple todavía (16 %)**: el inicio de la eyección se adelanta cuando el clic de apertura valvular queda pegado al flujo. Es lo siguiente a afinar, con imágenes reales.
\* ICC bajo del ET porque los ET simulados son muy parecidos entre sí; el error es constante (+26 ms).

## 5. Ajustes

Al principio de `procesar.py`, en el diccionario `PARAM`:

- `umbral_relativo`: bájalo (0,8) si la envolvente queda por dentro de la curva, y súbelo (1,3) si se va al ruido.
- `umbral_ruido` (3): cuánta señal sobre el ruido de cada profundidad se considera chorro.
- `nivel_borde` (0,5): dónde se coloca la envolvente dentro del borde difuso. Los valores bajos siguen el "plumeado" y los altos el borde denso.
- `v_min_latido`, `et_min`, `et_max`: los criterios para aceptar un latido.
- `nivel_inicio_fin` (5 % de Vmax): el umbral que define el inicio y el fin de la eyección.

## 6. Limitaciones conocidas

- Las anotaciones grabadas **dentro** del espectro (calipers, trazados del operador) solo se eliminan si son de color. Las que son blancas o grises se confunden con señal. Lo mejor es exportar las imágenes sin medir.
- Los ecógrafos que no guardan la *Sequence of Ultrasound Regions* en el DICOM necesitan pasar por `calibrar.py`.
- En una sola imagen solo se analizan los latidos completos. En fibrilación auricular conviene que haya al menos 5.
- Con figuras de artículos, que suelen ser JPEG pequeños y recortados, la precisión es menor. Sirven para probar el código, no para el estudio.
