# Procesado de Doppler continuo aórtico — prueba de concepto (paso 4)

Código para extraer de **una sola imagen de Doppler continuo (CW)** la envolvente de la curva,
las medidas clásicas y las características de forma y textura que alimentarán el modelo.

## Contenido

| Archivo | Para qué sirve |
|---|---|
| `1_INSTALAR.bat` · `2_ANALIZAR_IMAGEN.bat` | **Doble clic**: instalar (una vez) y analizar imágenes. |
| `app.py` | La aplicación con ventanas que abre `2_ANALIZAR_IMAGEN.bat`. |
| `datos_clinicos.py` | Guarda los datos clínicos y la etiqueta de cada paciente y los une a las medidas de la imagen. |
| `procesar.py` | El procesado completo (pasos 4.1 a 4.7). Acepta DICOM, PNG o JPG, o una carpeta entera. |
| `autocalibrar.py` | Calibración **automática** de capturas PNG/JPG: lee la escala de velocidad, las marcas de tiempo y la línea de base de la propia imagen. |
| `calibrar.py` | Calibración manual por línea de comandos (uso avanzado). |
| `sintetico.py` | Genera imágenes **sintéticas** de CW con valores conocidos, para probar el código. |
| `validar_sintetico.py` | Compara la medición automática con los valores reales (Bland-Altman, ICC). |
| `datos_sinteticos/` | 3 imágenes de ejemplo (severa, moderada, leve) en DICOM y PNG. |
| `resultados/` | Salida del procesado de esas imágenes. |
| `validacion/` | Resultado de la validación con 15 imágenes sintéticas (50 latidos). |
| `ejemplo_real/` | La imagen real que enviaste, calibrada y procesada. |
| `muestras/` | Imágenes reales de prueba. **Solo en tu ordenador**: no se suben al repositorio. |

## 1. Uso con doble clic (Windows)

1. **Solo la primera vez:** doble clic en **`1_INSTALAR.bat`**. Se abre una ventana negra que instala todo y termina con «LISTO». Si no tienes Python, te dirá dónde descargarlo; al instalarlo marca *«Add Python to PATH»*.
2. **Cada vez que quieras analizar:** doble clic en **`2_ANALIZAR_IMAGEN.bat`** → botón **«Analizar imágenes»** → eliges la imagen (o varias).
3. **La calibración es automática.** Los DICOM traen la suya. En las capturas PNG/JPG el programa lee de la propia imagen:
   - la línea de base (la línea naranja) y la región del espectro;
   - la escala de velocidad: lee los números de la regla de la derecha, en cm/s o m/s;
   - la escala de tiempo: las marcas más altas del eje inferior están separadas 1 segundo.

   Como comprobación compara la FC de las ondas R del ECG con la que marca la pantalla. Si no coinciden, lo avisa en rojo.
   Solo si la calibración automática falla se abre la ventana de **6 clics** (esquinas del espectro · línea de base · una marca de la escala · dos marcas de tiempo).
   En la sección **Calibración** se elige una de tres opciones:
   - **Automática; si falla, calibrar a mano** (la habitual).
   - **Calibrar a mano**: abre siempre la ventana de 6 clics, aunque la automática funcione.
   - **Misma calibración manual que la imagen anterior**: útil para varias capturas del mismo equipo y ajuste.
     Si todavía no hay ninguna o la imagen tiene otro tamaño, se pide calibrarla a mano y esa pasa a ser la anterior.

   La calibración manual se guarda junto a la imagen y tiene prioridad en adelante.
   Puedes elegir varias imágenes a la vez: se procesan seguidas y al final se abre la carpeta de resultados.
4. Al terminar se abre la **figura de control**. Todo queda en la carpeta **`resultados`** (botón «Abrir carpeta de resultados»).
5. Después se abre la ventana **«Datos del paciente»**: código (P001…), edad, sexo, peso y talla, factores de riesgo, ritmo, FEVI, bajo flujo,
   la **etiqueta** (severa / no severa / dudosa y de dónde sale) y las mediciones del informe (Vmax, gradiente medio, VTI, área valvular).
   Todo es opcional salvo el código. «Ahora no» la cierra sin guardar; luego se puede rellenar con el botón **«Datos del paciente»**
   (eligiendo antes la imagen en la tabla). La casilla «Pedir los datos del paciente…» (sección Datos del paciente) desactiva esta ventana.
   **No escribas nombres ni números de historia**: solo el código y la edad.
6. La pestaña **«Datos»** muestra las tablas guardadas (solo lectura): la combinada, la de imágenes y la de datos clínicos.

En `ejemplo_real/` está la figura del JASE 2017 (Philips, 150 mm/s) ya calibrada y procesada: Vmax 4,30 m/s, gradiente medio 45 mmHg, ET ≈ 275-280 ms (la figura marca ≈ 279 ms).

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
  - el espectro con la curva medida en rojo, el inicio (verde) y el fin (azul) de la eyección, las ondas R (▼) y el latido más desfavorable (★);
  - en gris, los latidos **descartados** (reverberaciones, curvas cortadas, formas que no son de eyección), con el motivo debajo de la tabla;
  - las curvas normalizadas;
  - una tabla de medidas por latido, con el más desfavorable, la media y el CV.
- **`<imagen>_latidos.csv`**: una fila por latido con todas las variables.
- **`<imagen>_curva_normalizada.csv`**: la curva de cada latido y la media, en 101 puntos (tiempo/ET frente a velocidad/Vmax). Es la entrada para el PCA funcional.
- **`<imagen>_latidoN_normalizado.png`**: el espectro de cada latido reescalado a 128×128 en coordenadas normalizadas. Es la entrada para textura o redes neuronales.

Para el conjunto: **`resumen_imagenes.csv`**, con una fila por imagen. Es la tabla que se une a la hoja de recogida de datos por el ID del paciente.

- Las columnas principales (`vmax_ms`, `grad_medio_mmHg`, `forma_*`…) son las del **latido más desfavorable**. Es el latido válido con mayor Vmax; si el ritmo es irregular, se excluyen los latidos tras una pausa larga, cuya velocidad está aumentada.
- Las columnas `media_*` son la media de todos los latidos válidos y las columnas `cv_*` son el coeficiente de variación entre latidos.
- `latido_referencia`, `n_descartados` y `motivos_descarte` indican qué latido se ha usado y qué se ha descartado.
- `calibracion`, `fc_pantalla_lpm` y `avisos_calibracion` indican el origen de la calibración y el resultado de la comprobación con la FC.

Datos del paciente (se crean desde la aplicación):

- **`datos_clinicos.csv`**: una fila por paciente con lo introducido en la ventana. Las variables sí/no se guardan como 1/0;
  `severa` vale 1 (severa), 0 (no severa) o queda vacía (dudosa o sin etiqueta); `sc_m2` es la superficie corporal (Mosteller);
  `imagenes` lista las imágenes asignadas a ese paciente.
- **`datos_combinados.csv`**: `resumen_imagenes.csv` + datos clínicos, una fila por imagen. Es la tabla para el análisis.
  Las columnas `informe_*` permiten comparar lo que mide el programa con lo que midió el ecocardiografista.

### Control de calidad de cada latido

Un latido se descarta si:
- su duración está fuera de 150-600 ms;
- su pico está en un extremo de la eyección;
- pasa mucho tiempo a baja velocidad tras el pico (típico de una reverberación pegada a la curva);
- se aparta mucho de una curva que sube hasta el pico y luego baja;
- está cortado por el borde de la imagen;
- con ECG disponible, no empieza en los 300 ms siguientes a una onda R o dura más del 75 % del ciclo.

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

**Imagen real** (`ejemplo_real/`): la envolvente sigue el borde del chorro en los dos latidos; ET medido ≈ 275-280 ms frente a ≈ 279 ms marcados en la propia figura.

**Calibración automática** (4 capturas reales Philips, en `muestras/`): las cuatro se calibran solas. La FC calculada con la escala de tiempo detectada coincide con la de la pantalla (74/74, 63/60, 57/58 y 76/76 lpm).
Las calibraciones manuales anteriores de P003 y P004 tenían mal la escala de tiempo (213 y 151 px/s frente a los 355 y 252 px/s reales). Por eso los ET y los VTI salían imposibles.

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
- `hampel_t`, `hueco_max`, `tramo_min`: limpieza de la envolvente. Eliminan los picos aislados, rellenan los huecos del granulado dentro del chorro e ignoran las manchas sueltas fuera de él.
- `suavizado_cima` (30 ms): suavizado de la parte alta de cada latido. No toca el inicio ni el fin, que son bruscos de verdad.
- `cola_max`, `irregularidad_max`, `u_pico_min/max`, `r_inicio_max`, `et_max_rr`: los criterios del control de calidad de cada latido.
- `pausa_rr` (1,2): a partir de qué RR previo (× mediana) un latido se considera «tras pausa» y no se usa como referencia.

## 6. Limitaciones conocidas

- Las anotaciones grabadas **dentro** del espectro (calipers, trazados del operador) solo se eliminan si son de color. Las que son blancas o grises se confunden con señal. Lo mejor es exportar las imágenes sin medir.
- La calibración automática está hecha y probada con capturas de **Philips**. Se basa en la línea de base naranja, la regla de velocidad a la derecha y las marcas de 1 s abajo. Con otros equipos lo normal es que falle y pida la calibración manual. Los DICOM con calibración propia no tienen este problema.
- Cuando la punta del chorro es muy tenue y con rayas verticales, la envolvente sigue el borde denso y no el plumeado. La Vmax puede quedar algo por debajo de la que trazaría a mano el ecocardiografista. Hay que contrastarla con el informe.
- En una sola imagen solo se analizan los latidos completos. En fibrilación auricular conviene que haya al menos 5.
- Con figuras de artículos, que suelen ser JPEG pequeños y recortados, la precisión es menor. Sirven para probar el código, no para el estudio.
