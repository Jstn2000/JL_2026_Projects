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
     if needed, converted to PNG on demand. The converted copies are cached in
     your system's temp folder, not in the picked folder itself - nothing gets
     written next to your original photos.
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
   - **Brush size** (1x1 / 2x2 / 3x3 / 4x4) controls how many cells the
     single-pixel tool (right-click) paints at once, centered on the
     cursor. It only applies to single-pixel painting - bucket fill
     already covers a whole region on its own.
   - Enable **Magic pencil** to auto-paint whatever you click/drag over
     with *its own correct color*, without needing that color
     pre-selected: right-click auto-colors just that cell (or the whole
     brush footprint), left-click auto-colors *every* cell sharing that
     number, anywhere in the image.
   - Once a cell is painted, its number/highlight disappears and it shows
     the real color. You can only paint a cell with its correct color -
     picking the wrong color and clicking just does nothing, so mistakes
     aren't possible. "Clear painting" resets the canvas back to blank.
   - A big counter in the side panel always shows how many pixels are
     still uncolored overall, alongside the per-color "N left" counts
     under each swatch.
   - Click **Hint** (or press the hint shortcut, default `h`, while
     hovering the canvas) to briefly flash every uncolored cell of the
     currently selected color, so it's easy to spot where to paint next.
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

5. `Project` menu (also mirrored as toolbar buttons):
   - **Save Progress...** saves your partially-completed painting to a
     `.ppzip` project file - your progress, the numbered "answer key",
     and your brush/magic-pencil settings all in one file.
   - **Load Progress...** reopens a `.ppzip` file later, or lets someone
     else continue your painting on their own machine.
   - **Export Numbered Template...** saves a full-resolution, printable
     PNG of the blank numbered template (not your progress) - the thing
     you'd print out or send to a friend, alongside the palette, so they
     can paint it by hand. You choose how large each numbered cell should
     be when prompted.

## Keyboard shortcuts

- **Esc** - exit the app (always fixed).
- **1 / 2 / 3** - jump to the Select / Pixelate / Paint tab (from anywhere).
- **p** - pixelate the currently selected image, same as the toolbar button.
- In the **Select Image** tab: **arrow keys** move the highlighted image,
  **Enter** opens the highlighted one (mouse click still selects and opens
  in one step, as before).
- In the **Paint** tab: **h** (while hovering the canvas) triggers the Hint
  flash for the currently selected color. WASD / arrow-key panning and the
  other mouse controls are unchanged.

All of the shortcuts above except Esc can be customized from
`Settings > Keyboard Shortcuts...` in the menu bar, or by editing
`~/.pixelpaint/keybindings.cfg` directly (one `action = key` pair per
line - the file is created with the defaults the first time you run the
app, and any line you delete just falls back to its default).

## Project layout

- `main.py` – entry point
- `app.py` – main window, menubar/toolbar, tab wiring, save/pixelate actions
- `image_utils.py` – directory scanning, PNG conversion, pixelation & color quantization
- `select_tab.py` – image browsing/selection UI
- `pixelate_tab.py` – pixelation preview screen
- `paint_tab.py` – painting UI (palette, zoom/pan, brush tools, hint flash)
- `keybindings.py` – default shortcuts + the `~/.pixelpaint/keybindings.cfg` load/save
- `keybindings_dialog.py` – in-app "Keyboard Shortcuts..." customization dialog


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
- add save functionality for images with numbers on them ✅
- add save functionality to save partially completed paintings ✅
- add adjustable brush size (2x2, 3x3, 4x4) for single-pixel painting ✅
<!-- - add saturation option for pixelating images -->
<!-- - show preview of pixelated image only in greyscale  -->
<!-- - save location for images should be the project folder (or a folder in it) -->

- mouse hold click mode ✅
- add hint button that flashes uncolored cells of the selected color ✅
- add big counter for how many pixels are still uncolored ✅
- add keyboard shortcuts: toggle hint, pixelate, arrow+enter select, switch tabs ✅
- add customizable keybindings + a property file for them ✅