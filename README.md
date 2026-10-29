# Programa Publifoto

Maqueta automáticamente los productos de fútbol (cartas, imanes, llaveros,
calendarios de pared y de sobremesa, 15×20 con logo) **sin Adobe**.

## Uso

1. Doble clic en `Publifoto.bat`.
2. Arrastra la carpeta de fotos ARREGLADAS. El programa pide el nombre del equipo.
3. Para CARTAS, arrastra también la carpeta RECORTADAS (PNG sin fondo, con el
   mismo nombre de archivo que la foto arreglada).
4. Revisa la clasificación (jugador / entrenador / foto de equipo) y marca los productos.
   Elige el **escudo del club** (la primera vez, «Añadir logos…» con la carpeta de escudos:
   el nombre de cada archivo es el del club). Sale en 15 x 20, calendario de pared y
   calendario de sobremesa (marca de agua); en los imanes va el nombre del club y la temporada.
5. Opcional: **Revisión rápida de encuadres** (flechas, rueda del ratón o + / −).
   Si un jugador sale torcido, **↺ / ↻** (o las teclas `[` y `]`) lo giran en pasos de 0,5°.
   El giro vale para todos los productos y el encuadre se recalcula para que tenga las
   mismas medidas que los demás. En los llaveros la cabeza ya sale enderezada sola; se puede
   quitar con la casilla «Enderezar la cabeza automáticamente».
6. **Generar**.

Resultado:

```
<carpeta de resultados>/<EQUIPO>/
├── <PRODUCTO>/IMPRESION/   archivos para imprimir (PDF, JPG, TIFF)
├── <PRODUCTO>/EDITABLE/    PSD por capas o PDF por capas
└── <EQUIPO>.publifoto      proyecto: "Abrir proyecto…" para corregir y regenerar
```

| Producto | Impresión | Editable | Quién sale |
|---|---|---|---|
| CARTAS | TIFF CMYK FOGRA39, una por jugador | PSD (fondo, jugador, logo y textos) | jugadores, necesita recorte |
| IMANES | PDF + JPG RGB, 12 por hoja | PDF por capas | jugadores |
| LLAVEROS | JPG RGB, 5 por hoja y repetidos | PSD por capas | jugadores |
| CALENDARIOS PARED | TIFF CMYK, uno por persona | un PSD con una capa por persona | jugadores y entrenadores |
| CALENDARIOS SOBREMESA | PDF CMYK FOGRA39, 2 por hoja; foto = marco rojo exacto; si son impares, media hoja en blanco | PDF por capas + FOTOS/ (recortes y _DALT) | jugadores |
| 15 X 20 CON LOGO | JPG RGB, uno por jugador | PSD por foto | jugadores |

## Plantillas de cada año

«Plantillas…» → «Actualizar…» y se elige el archivo original nuevo (calendario de sobremesa:
el PDF exportado de InDesign; imanes: el .ai; pared y 15 x 20: el TIFF con capas). El programa
lo convierte, lo prueba generando el producto con figuras dibujadas y solo entonces lo usa.
Se guarda en la carpeta de datos del usuario (`%LOCALAPPDATA%\Publifoto\datos` en Windows,
`~/Library/Application Support/Publifoto` en Mac), igual que los escudos; «Volver a la
original» recupera la que viene con el programa. Cartas aún no se actualiza desde aquí.

## Revisores automáticos

Al arrastrar las fotos y al generar, unos revisores repasan todo sin internet (MediaPipe y
OpenCV en el propio PC; las fotos no salen del ordenador). Corrigen solos lo que tienen claro
y en la ventana solo aparece la lista de cosas para mirar (doble clic para verlas):

| Revisor | Qué hace |
|---|---|
| Silueta | Compara la silueta con los puntos de la cara; si la silueta mide mal la cabeza (balón, brazos, pelo), la corrige con la cara. |
| Inclinación | Endereza la cabeza en los **primeros planos** (llaveros): giro = 0,30 × inclinación de la cara − 0,8°, hasta ±4°. En los productos de cuerpo entero no gira: los jueces lo rechazaron. Avisa si la cara está de perfil. |
| Clasificación | Jugador / entrenador / foto de equipo por la ropa (comparada con la del resto del equipo), la ropa gris, el tamaño del iris (más grande en niños) y el orden de las fotos (los entrenadores se hacen seguidos). Las dudas se marcan en amarillo. |
| Encuadre | Por producto: cara y pelo dentro del recorte, sin salirse de la foto (lo que falta se rellena con el reflejo del borde, como en los aprobados). |
| Calidad | Cara no encontrada, varias caras, ojos cerrados. |
| Presencia | En todos los productos, cada persona que se va a imprimir sale una vez y entera: tiene hueco en su hoja y ninguna otra foto la tapa (en los imanes cuenta el círculo, el resto es sangrado). Se mira antes de generar (reparto en las hojas) y después (fotos de verdad en cada página del PDF y capas de los PSD). Las plantillas con marcos repetidos se limpian solas al cargarlas. |
| Salida | Después de generar: están todos los archivos y todas las personas, tamaño y CMYK correctos, páginas de los PDF. |

Calibrado con los 14 equipos de AMPOSTA (169 retratos):
- **Clasificación:** acierta las 169 (15 marcadas como duda para comprobar).
- **Giro de los llaveros:** el giro del programa es aceptable para los jueces en el 93,5 % (validación dejando fuera cada equipo); sin girar, el 70 %.
- **Silueta:** corrige las 2 fotos en las que la silueta medía mal la cabeza.

## Cómo funciona

- `analisis.py`: silueta del jugador (rembg, `u2net_human_seg`), alto de la cabeza,
  cuello y centro. Entrenadores: ropa gris. Foto de equipo: foto horizontal.
- `encuadre.py`: cada producto encuadra con tres números (margen sobre la cabeza,
  alto del hueco en alturas de cabeza y centrado), medidos sobre los trabajos ya
  aprobados del equipo S11 A.
- `productos.py`, `cartas.py`: componen cada producto sobre su plantilla abierta.
- `color.py`: conversión sRGB → Coated FOGRA39 con LittleCMS (colorimétrico relativo
  con compensación de punto negro, como Photoshop).

## Plantillas

Las plantillas abiertas están en `publifoto/plantillas/`. Se generan **una sola vez**
desde los originales de Adobe (no hace falta Adobe para leerlos):

```
python -m publifoto.herramientas.preparar_plantillas "<carpeta con IMANS FUTBOL.ai, CAL PARET.tif...>"
python -m publifoto.herramientas.preparar_carta "<...>/AMPOSTAPLANTILLA2026.tif"
```

`herramientas/tiff_capas.py` lee las capas de los TIFF de Photoshop sin Adobe.

## Programa montado (Mac y Windows)

`empaquetar/` monta el programa con todo dentro (plantillas, letras, perfil FOGRA39 y
modelos de silueta, cara y cuerpo), sin Python ni descargas en el ordenador del cliente:

- Mac: `bash empaquetar/construir_mac.sh` en un Mac → `dist/Publifoto.app` y
  `dist/Publifoto.dmg` (firma y notarización opcionales). Ver `empaquetar/INSTRUCCIONES_MAC.txt`.
- Windows: `empaquetar\construir_windows.bat` → `dist\Publifoto\Publifoto.exe`.
- `Publifoto --comprobar` prueba la instalación sin fotos; `Publifoto --prueba <fotos>
  <salida> [equipo]` genera un equipo sin ventana para comparar ordenadores.
  En Windows el programa montado da exactamente lo mismo que el normal.

Las letras de los imanes (nombre del equipo, del club y temporada) son Source Sans 3 (libre,
OFL, en `recursos/fuentes`): la original es Myriad Pro, de Adobe, y no se puede repartir.

## Pendiente

- Editable del calendario de sobremesa en IDML; ahora es un PDF por capas.
- Instalador y licencia.
- Probar con más equipos y ajustar los umbrales (entrenadores, encuadres).
