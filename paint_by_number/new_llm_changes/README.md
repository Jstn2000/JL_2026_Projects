# PixelPaint

A small desktop app (Tkinter + Pillow) that turns a photo into pixel art and
lets you paint on it, paint-by-numbers style.

## Requirements

- Python 3.8+
- Tkinter (bundled with most Python installs; on Debian/Ubuntu if missing: `sudo apt install python3-tk`)
- Pillow: `pip install Pillow`

## Run

```bash
python3 main.py
```

## Controls

- The app opens in **fullscreen** by default. Press **Esc** anywhere to exit.
- In the Paint tab, pan the image with **WASD** or the **arrow keys** (once
  the canvas has focus - just hover over or click it), by dragging with the
  middle/right mouse button, or via the scrollbars.

## Workflow

1. **Select Image** tab
   - `File > Open Directory...` (or the toolbar button) picks a folder of images.
   - All supported images (`png, jpg, jpeg, bmp, gif, webp, tiff`) are found and,
     if needed, converted to PNG into a small `.pixelpaint_png_cache` folder.
   - Click a thumbnail, drag the slider, or scroll your mouse wheel over the
     gallery to browse and pick an image.

2. **Pixelate / Preview** tab
   - Set **Pixel size** and **Colors** in the toolbar at the top of the window.
   - Click **Pixelate** (toolbar button or `Image > Pixelate`) to see a
     side-by-side original vs. pixelated preview.

3. **Paint** tab
   - The canvas starts **completely white**, with a small number in every
     cell showing which palette color belongs there.
   - Left panel: click a palette swatch to select it as your brush color
     (colors are ordered darkest to lightest). Every unpainted cell that
     wants that color lights up **light grey** so you can see exactly
     where to paint, and a counter shows how many cells of that color are
     correctly painted vs. still left.
   - **Left-click paints with Fill (bucket)**, **right-click paints Single
     pixel** - no mode buttons to toggle, the mouse button you use is the
     mode.
   - Enable **Magic pencil** to auto-paint whatever you click/drag over
     with *its own correct color*, without needing that color
     pre-selected: right-click auto-colors just that cell, left-click
     auto-colors *every* cell sharing that number, anywhere in the image.
   - Once a cell is painted, its number/highlight disappears and it shows
     the real color. You can only paint a cell with its correct color -
     picking the wrong color and clicking just does nothing, so mistakes
     aren't possible. "Clear painting" resets the canvas back to blank.
   - A small live preview in the **bottom-right corner** shows the whole
     painting as it stands, with a red box marking your current viewport.
   - Zoom with the slider (or Ctrl + mouse wheel over the canvas) -
     whatever's centered in view stays centered as you zoom. **"Fit to
     window"** zooms out to show the whole picture at once.
   - Pan by dragging with the **middle mouse button**, using WASD /
     arrow keys, or the scrollbars. A **middle-click without dragging
     resets the zoom** back to default.
   - The status box shows the pixel coordinate, its number, and whether
     it's been painted yet.

4. `File > Save Image...` (or the toolbar button) exports your painted
   result as a PNG at the original photo's resolution.

## Project layout

- `main.py` – entry point
- `app.py` – main window, menubar/toolbar, tab wiring, save/pixelate actions
- `image_utils.py` – directory scanning, PNG conversion, pixelation & color quantization
- `select_tab.py` – image browsing/selection UI
- `pixelate_tab.py` – pixelation preview screen
- `paint_tab.py` – painting UI (palette, zoom/pan, brush tools)


BUGS & NEW FEATURES

- directory read bugged ✅
- zoom in paint option should zoom to the middle per default
- zoom out to see full picture
- magic pen in single mode switches between colors as you draw ✅
- magic pen in bucket mode fills all elements of the same number ✅
- add control: leftclick bucket mode, rightclick single mode ✅
- move preview screen to bottom right to not upstruckt vision on the paint screen
- add color selected panel ✅
- show clearer how many are left and when you completed one color
<!-- - add help mode (flash uncolored missing from the color) -->
- extend image select to entire canvas (only uses left side at the moment) ✅
- add control middle mouse button reset zoom
- randomize png preselectrion so the user doesnthave to scroll so much to see new images ✅
<!-- - add save functionality for images with numbers on them -->
<!-- - add save functionality to save partially completed paintings -->
<!-- - add saturation option for pixelating images -->
<!-- - show preview of pixelated image only in greyscale  -->
<!-- - save location for images should be the project folder (or a folder in it) -->

- mouse hold click mode ✅