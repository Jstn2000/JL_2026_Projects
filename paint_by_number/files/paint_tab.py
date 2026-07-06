"""
paint_tab.py

Paint-by-numbers style painting UI.

    - The canvas starts completely WHITE.
    - Every unpainted cell shows a small number, telling you which
      palette color belongs there (2.1.1.2).
    - Selecting a color (2.1.1.1) highlights every unpainted cell that
      wants that color in light grey, so you can see where to paint.
    - Painting a cell (single pixel / fill / magic pencil) replaces the
      white + number with the actual chosen color.
    - A cell painted with the WRONG color gets a thin red outline, so
      mistakes are visible instead of silently blending in.
    - A live counter shows how many cells of the selected color are
      correctly painted vs. still left.
    - A small preview in the bottom-right corner shows the whole painting
      as it currently stands.

Internally there are two same-sized grids:
    self.target_image  - the "answer key": the quantized pixel-art colors
                          computed by the Pixelate tab. Read-only; used to
                          look up each cell's number and for highlighting.
    self.canvas_image  - what the user has actually painted so far. Starts
                          all white; this is what gets displayed (with the
                          numbers/highlight/mistake-outline drawn on top)
                          and what gets exported/saved.

Performance note: repainting used to redraw the *entire* grid (every cell,
including a font-rendered number) on every single click or drag-motion
event, which is why painting felt laggy. Now a persistent raster
(`self._display_image`) is kept around and only the cells that actually
changed are redrawn into it; that small patch is then blitted directly
onto the live Tk image via the photo image's low-level "put" command
instead of rebuilding/reassigning the whole image. A full rebuild only
happens on load, zoom change, or "Clear painting".
"""

import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageDraw, ImageFont, ImageTk

from image_utils import get_palette_colors, grid_to_full_size

SWATCH_SIZE = 28
MIN_ZOOM = 4.0
MAX_ZOOM = 40.0

WHITE = (255, 255, 255)
HIGHLIGHT = (222, 222, 222)      # light grey highlight for the selected color's cells
NUMBER_COLOR = (90, 90, 90)
GRID_LINE_COLOR = (205, 205, 205)
MISTAKE_COLOR = (215, 30, 30)     # outline color for a cell painted the wrong color

MIN_ZOOM_FOR_NUMBERS = 12        # below this cell size, numbers would be unreadable clutter
MIN_ZOOM_FOR_GRIDLINES = 5
PAN_STEP = 40                     # pixels moved per WASD / arrow key press
MINIMAP_MAX_SIZE = 170


def _rgb_to_hex(rgb):
    return "#%02x%02x%02x" % rgb


class PaintTab(ttk.Frame):
    def __init__(self, parent, state_obj):
        super().__init__(parent)
        self.state_obj = state_obj

        self.target_image = None     # PIL Image, read-only "answer key" colors
        self.target_pixels = None    # .load() access into target_image
        self.canvas_image = None     # PIL Image, the user's actual painted result
        self.canvas_pixels = None    # .load() access into canvas_image
        self.painted = set()         # {(x, y)} cells that have been painted
        self.grid_w = 0
        self.grid_h = 0

        self.color_to_number = {}         # target color -> palette number (1-based)
        self.color_to_positions = {}      # target color -> list[(x, y)], built once per image
        self._font_cache = {}

        self.zoom = 16.0
        self.show_numbers = True
        self.show_gridlines = True
        self._active_font = None

        self.mode = tk.StringVar(value="pixel")   # "pixel" or "fill"
        self.magic_pencil = tk.BooleanVar(value=False)
        self.selected_color = (0, 0, 0)

        self._display_image = None   # persistent full raster mirroring what's on screen
        self.photo_image = None      # keep PhotoImage reference alive
        self.minimap_photo = None    # keep minimap PhotoImage reference alive

        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self):
        root = ttk.Frame(self)
        root.pack(fill=tk.BOTH, expand=True)

        # 2.1.1 Left side panel -----------------------------------------
        side = ttk.Frame(root, padding=8, relief=tk.GROOVE, borderwidth=1)
        side.pack(side=tk.LEFT, fill=tk.Y)

        ttk.Label(side, text="Palette", font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
        self.palette_frame = ttk.Frame(side)
        self.palette_frame.pack(fill=tk.X, pady=(4, 12))

        ttk.Separator(side, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=6)

        ttk.Label(side, text="Brush mode", font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
        mode_frame = ttk.Frame(side)
        mode_frame.pack(fill=tk.X, pady=4)
        ttk.Radiobutton(mode_frame, text="Single pixel", value="pixel", variable=self.mode).pack(anchor="w")
        ttk.Radiobutton(mode_frame, text="Fill (bucket)", value="fill", variable=self.mode).pack(anchor="w")

        ttk.Checkbutton(
            side, text="Magic pencil (paint all matching numbers)", variable=self.magic_pencil
        ).pack(anchor="w", pady=(8, 0))  # 2.1.1.4

        ttk.Separator(side, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=6)

        ttk.Label(side, text="Zoom", font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
        self.zoom_slider = ttk.Scale(
            side, from_=MIN_ZOOM, to=MAX_ZOOM, orient=tk.HORIZONTAL, command=self._on_zoom_change
        )
        self.zoom_slider.set(self.zoom)
        self.zoom_slider.pack(fill=tk.X, pady=4)

        ttk.Button(side, text="Clear painting", command=self._clear_painting).pack(fill=tk.X, pady=(8, 0))

        ttk.Separator(side, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=6)

        # 3. Per-color progress counter
        self.color_progress_label = ttk.Label(side, text="", justify=tk.LEFT, wraplength=160)
        self.color_progress_label.pack(anchor="w")

        self.progress_label = ttk.Label(side, text="", justify=tk.LEFT)
        self.progress_label.pack(anchor="w", pady=(4, 0))

        self.status_label = ttk.Label(side, text="Pixel: -, -\nNumber: -", justify=tk.LEFT)
        self.status_label.pack(anchor="w", pady=(12, 0))

        # 2.2 Main canvas area --------------------------------------------
        main = ttk.Frame(root)
        main.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.main_frame = main

        h_scroll = ttk.Scrollbar(main, orient=tk.HORIZONTAL)
        v_scroll = ttk.Scrollbar(main, orient=tk.VERTICAL)

        self.canvas = tk.Canvas(
            main,
            background="#333333",
            xscrollcommand=h_scroll.set,
            yscrollcommand=v_scroll.set,
        )
        h_scroll.config(command=self._on_hscroll)
        v_scroll.config(command=self._on_vscroll)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        v_scroll.grid(row=0, column=1, sticky="ns")
        h_scroll.grid(row=1, column=0, sticky="ew")
        main.rowconfigure(0, weight=1)
        main.columnconfigure(0, weight=1)

        self.image_id = None

        # 2.3 mouse as brush
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<B1-Motion>", self._on_drag_paint)
        self.canvas.bind("<Motion>", self._on_mouse_move)

        # 2.2.1.2 movement controls: middle-mouse-drag panning
        self.canvas.bind("<ButtonPress-2>", self._on_pan_start)
        self.canvas.bind("<B2-Motion>", self._on_pan_move)
        # Also support right-click drag panning for mice without a middle button
        self.canvas.bind("<ButtonPress-3>", self._on_pan_start)
        self.canvas.bind("<B3-Motion>", self._on_pan_move)

        # 2.2.1.2 WASD keyboard panning. The canvas needs keyboard focus to
        # receive these, so grab focus on hover/click rather than binding
        # globally (which would steal "w"/"a"/"s"/"d" from text fields elsewhere).
        self.canvas.bind("<Enter>", lambda e: self.canvas.focus_set())
        self.canvas.bind("<KeyPress-w>", lambda e: self._pan_by_pixels(0, -PAN_STEP))
        self.canvas.bind("<KeyPress-s>", lambda e: self._pan_by_pixels(0, PAN_STEP))
        self.canvas.bind("<KeyPress-a>", lambda e: self._pan_by_pixels(-PAN_STEP, 0))
        self.canvas.bind("<KeyPress-d>", lambda e: self._pan_by_pixels(PAN_STEP, 0))
        # Arrow keys do the same, as a discoverable alternative to WASD
        self.canvas.bind("<Up>", lambda e: self._pan_by_pixels(0, -PAN_STEP))
        self.canvas.bind("<Down>", lambda e: self._pan_by_pixels(0, PAN_STEP))
        self.canvas.bind("<Left>", lambda e: self._pan_by_pixels(-PAN_STEP, 0))
        self.canvas.bind("<Right>", lambda e: self._pan_by_pixels(PAN_STEP, 0))

        # mouse-wheel zoom (Ctrl+wheel) as a bonus zoom control
        self.canvas.bind("<Control-MouseWheel>", self._on_ctrl_wheel_zoom)

        # 4. Minimap preview, floating over the bottom-right corner of the canvas
        self.minimap_label = tk.Label(main, background="#111111", borderwidth=1, relief=tk.SOLID)
        self.minimap_label.place(relx=1.0, rely=1.0, anchor="se", x=-14, y=-14)
        self.minimap_label.lift()

    # ------------------------------------------------------------------
    # Loading a freshly pixelated image into the paint grid
    # ------------------------------------------------------------------
    def load_pixelated_image(self):
        target = self.state_obj.pixel_grid_image
        if target is None:
            return

        self.target_image = target.copy()
        self.target_pixels = self.target_image.load()
        self.grid_w, self.grid_h = self.target_image.size

        self.canvas_image = Image.new("RGB", (self.grid_w, self.grid_h), WHITE)
        self.canvas_pixels = self.canvas_image.load()
        self.painted = set()

        self._build_color_positions()
        self._build_palette()
        self._rebuild_full()
        self._update_progress()
        self._update_color_progress()

    def _build_color_positions(self):
        """One-time index: target color -> every (x, y) cell that wants it.
        Makes fill/magic-pencil/progress-counting fast without rescanning
        the whole grid on every action."""
        positions = {}
        for gy in range(self.grid_h):
            for gx in range(self.grid_w):
                color = self.target_pixels[gx, gy]
                positions.setdefault(color, []).append((gx, gy))
        self.color_to_positions = positions

    def _clear_painting(self):
        if self.canvas_image is None:
            return
        self.canvas_image = Image.new("RGB", (self.grid_w, self.grid_h), WHITE)
        self.canvas_pixels = self.canvas_image.load()
        self.painted = set()
        self._rebuild_full()
        self._update_progress()
        self._update_color_progress()

    # 2.1.1.1 / 2.1.1.2 Build one button + number label per palette color
    def _build_palette(self):
        for child in self.palette_frame.winfo_children():
            child.destroy()
        self.color_to_number = {}

        colors = get_palette_colors(self.target_image, max_colors=64)
        colors.sort(key=lambda color: sum(color))

        if colors:
            self.selected_color = colors[0]

        for index, color in enumerate(colors, start=1):
            self.color_to_number[color] = index

            cell = ttk.Frame(self.palette_frame)
            cell.grid(row=(index - 1) // 4, column=(index - 1) % 4, padx=2, pady=2)

            swatch = tk.Button(
                cell,
                bg=_rgb_to_hex(color),
                activebackground=_rgb_to_hex(color),
                width=3,
                height=1,
                relief=tk.RIDGE,
                command=lambda c=color: self._select_color(c),
            )
            swatch.pack()
            ttk.Label(cell, text=str(index), font=("TkDefaultFont", 8)).pack()

    def _select_color(self, color):
        old_color = self.selected_color
        self.selected_color = color
        self._update_status()
        self._update_color_progress()

        # Only the cells whose highlight state can change need to be
        # redrawn: the ones wanting the old color (losing highlight) and
        # the ones wanting the new color (gaining highlight). This avoids
        # a full-grid rebuild just for a palette click.
        changed_cells = []
        for c in (old_color, color):
            if c == old_color and c == color:
                continue
            for pos in self.color_to_positions.get(c, ()):
                if pos not in self.painted:
                    changed_cells.append(pos)
        self._update_cells(changed_cells)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def _get_font(self, size):
        font = self._font_cache.get(size)
        if font is None:
            font = ImageFont.load_default(size=size)
            self._font_cache[size] = font
        return font

    def _draw_cell(self, draw, gx, gy):
        """Draw exactly one cell's content into `draw` at the current zoom."""
        zoom = self.zoom
        x0, y0 = gx * zoom, gy * zoom
        x1, y1 = x0 + zoom, y0 + zoom
        box = (x0, y0, x1, y1)

        if (gx, gy) in self.painted:
            color = self.canvas_pixels[gx, gy]
            draw.rectangle(box, fill=color)
            target_color = self.target_pixels[gx, gy]
            if color != target_color:
                # 1. Mark mistakes: thin red outline on a wrongly-painted cell
                border_w = max(1, int(zoom * 0.12))
                draw.rectangle(
                    (x0 + border_w / 2, y0 + border_w / 2, x1 - border_w / 2, y1 - border_w / 2),
                    outline=MISTAKE_COLOR,
                    width=border_w,
                )
        else:
            target_color = self.target_pixels[gx, gy]
            bg = HIGHLIGHT if target_color == self.selected_color else WHITE
            if bg != WHITE:
                draw.rectangle(box, fill=bg)
            if self.show_numbers:
                number = self.color_to_number.get(target_color, "?")
                text = str(number)
                bbox = draw.textbbox((0, 0), text, font=self._active_font)
                tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
                tx = x0 + (zoom - tw) / 2 - bbox[0]
                ty = y0 + (zoom - th) / 2 - bbox[1]
                draw.text((tx, ty), text, fill=NUMBER_COLOR, font=self._active_font)

        if self.show_gridlines:
            draw.rectangle(box, outline=GRID_LINE_COLOR, width=1)

    def _rebuild_full(self):
        """Full re-render of every cell. Used on load, zoom change, and clear -
        infrequent actions, so the O(grid size) cost here is fine."""
        if self.target_image is None:
            return

        zoom = self.zoom
        disp_w = max(1, int(self.grid_w * zoom))
        disp_h = max(1, int(self.grid_h * zoom))

        self.show_numbers = zoom >= MIN_ZOOM_FOR_NUMBERS
        self.show_gridlines = zoom >= MIN_ZOOM_FOR_GRIDLINES
        self._active_font = self._get_font(max(6, int(zoom * 0.6))) if self.show_numbers else None

        self._display_image = Image.new("RGB", (disp_w, disp_h), WHITE)
        draw = ImageDraw.Draw(self._display_image)
        for gy in range(self.grid_h):
            for gx in range(self.grid_w):
                self._draw_cell(draw, gx, gy)

        self.photo_image = ImageTk.PhotoImage(self._display_image)
        if self.image_id is None:
            self.image_id = self.canvas.create_image(0, 0, image=self.photo_image, anchor="nw")
        else:
            self.canvas.itemconfig(self.image_id, image=self.photo_image)
        self.canvas.config(scrollregion=(0, 0, disp_w, disp_h))

        self._update_minimap()

    def _update_cells(self, cells):
        """Fast path: redraw only the given (x, y) cells and blit just that
        patch onto the live Tk image, instead of rebuilding everything."""
        if not cells or self._display_image is None:
            return

        zoom = self.zoom
        draw = ImageDraw.Draw(self._display_image)
        xs, ys = [], []
        for (gx, gy) in cells:
            self._draw_cell(draw, gx, gy)
            xs.append(gx)
            ys.append(gy)

        disp_w, disp_h = self._display_image.size
        x0 = max(0, int(min(xs) * zoom))
        y0 = max(0, int(min(ys) * zoom))
        x1 = min(disp_w, int((max(xs) + 1) * zoom) + 1)
        y1 = min(disp_h, int((max(ys) + 1) * zoom) + 1)

        self._blit_patch(x0, y0, x1, y1)
        self._update_minimap()

    def _blit_patch(self, x0, y0, x1, y1):
        """Push a small rectangular region of self._display_image straight
        onto the live Tk photo image, without recreating the PhotoImage or
        touching the canvas item - this is what makes single-cell edits fast."""
        if self.photo_image is None or x1 <= x0 or y1 <= y0:
            return
        patch = self._display_image.crop((x0, y0, x1, y1))
        px = patch.load()
        w, h = patch.size
        rows = []
        for yy in range(h):
            row = "{" + " ".join("#%02x%02x%02x" % px[xx, yy] for xx in range(w)) + "}"
            rows.append(row)
        data = " ".join(rows)
        self.canvas.tk.call(str(self.photo_image), "put", data, "-to", x0, y0)

    # 4. Live minimap preview -------------------------------------------
    def _update_minimap(self):
        if self.canvas_image is None:
            return
        w, h = self.canvas_image.size
        scale = min(MINIMAP_MAX_SIZE / w, MINIMAP_MAX_SIZE / h, 1.0) if w and h else 1.0
        new_size = (max(1, int(w * scale)), max(1, int(h * scale)))

        mini = self.canvas_image.resize(new_size, Image.NEAREST)
        draw = ImageDraw.Draw(mini)

        # Outline the currently visible viewport so the minimap doubles as a
        # navigation aid alongside WASD / zoom.
        try:
            x0f, x1f = self.canvas.xview()
            y0f, y1f = self.canvas.yview()
            rx0, ry0 = x0f * new_size[0], y0f * new_size[1]
            rx1, ry1 = x1f * new_size[0], y1f * new_size[1]
            if (rx1 - rx0) < new_size[0] - 0.5 or (ry1 - ry0) < new_size[1] - 0.5:
                draw.rectangle(
                    [rx0, ry0, max(rx0 + 1, rx1 - 1), max(ry0 + 1, ry1 - 1)],
                    outline=(230, 30, 30),
                    width=1,
                )
        except Exception:
            pass

        self.minimap_photo = ImageTk.PhotoImage(mini)
        self.minimap_label.configure(image=self.minimap_photo)
        self.minimap_label.lift()

    def _update_progress(self):
        total = self.grid_w * self.grid_h
        done = len(self.painted)
        self.progress_label.config(text=f"Painted: {done} / {total} pixels")

    # 3. Per-selected-color progress counter -----------------------------
    def _update_color_progress(self):
        color = self.selected_color
        positions = self.color_to_positions.get(color, [])
        total = len(positions)
        correct = sum(1 for pos in positions if self.canvas_pixels[pos] == color)
        remaining = total - correct
        number = self.color_to_number.get(color, "?")
        self.color_progress_label.config(
            text=f"Color #{number}: {correct} painted, {remaining} left (of {total})"
        )

    # 2.2.1.1 Zoom control
    def _on_zoom_change(self, value):
        self.zoom = float(value)
        self._rebuild_full()

    def _on_ctrl_wheel_zoom(self, event):
        step = 2.0 if event.delta > 0 else -2.0
        new_zoom = min(MAX_ZOOM, max(MIN_ZOOM, self.zoom + step))
        self.zoom_slider.set(new_zoom)  # triggers _on_zoom_change

    # 2.2.1.2 Panning
    def _on_pan_start(self, event):
        self.canvas.scan_mark(event.x, event.y)

    def _on_pan_move(self, event):
        self.canvas.scan_dragto(event.x, event.y, gain=1)
        self._update_minimap()

    def _on_hscroll(self, *args):
        self.canvas.xview(*args)
        self._update_minimap()

    def _on_vscroll(self, *args):
        self.canvas.yview(*args)
        self._update_minimap()

    def _pan_by_pixels(self, dx, dy):
        """Nudge the view by a fixed pixel amount - used by WASD / arrow keys."""
        if self.target_image is None:
            return
        disp_w = max(1, int(self.grid_w * self.zoom))
        disp_h = max(1, int(self.grid_h * self.zoom))

        if dx:
            first, last = self.canvas.xview()
            span = last - first
            new_first = min(max(first + dx / disp_w, 0.0), max(0.0, 1.0 - span))
            self.canvas.xview_moveto(new_first)
        if dy:
            first, last = self.canvas.yview()
            span = last - first
            new_first = min(max(first + dy / disp_h, 0.0), max(0.0, 1.0 - span))
            self.canvas.yview_moveto(new_first)
        self._update_minimap()

    # ------------------------------------------------------------------
    # 2.3 Mouse as brush tool
    # ------------------------------------------------------------------
    def _canvas_to_grid_coords(self, event):
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        gx = int(cx // self.zoom)
        gy = int(cy // self.zoom)
        return gx, gy

    def _on_mouse_move(self, event):
        if self.target_image is None:
            return
        gx, gy = self._canvas_to_grid_coords(event)
        if 0 <= gx < self.grid_w and 0 <= gy < self.grid_h:
            target_color = self.target_pixels[gx, gy]
            number = self.color_to_number.get(target_color, "?")
            if (gx, gy) in self.painted:
                state = "correct" if self.canvas_pixels[gx, gy] == target_color else "WRONG"
            else:
                state = "unpainted"
            self.status_label.config(text=f"Pixel: {gx}, {gy}\nNumber: {number} ({state})")

    def _update_status(self):
        first_line = self.status_label.cget("text").split("\n")[0]
        number = self.color_to_number.get(self.selected_color, "?")
        self.status_label.config(text=f"{first_line}\nBrush: #{number} rgb{self.selected_color}")

    def _on_click(self, event):
        self.canvas.focus_set()
        self._paint_at(event)

    def _on_drag_paint(self, event):
        # Continuous painting only makes sense in single-pixel mode;
        # fill / magic pencil are one-shot actions per click.
        if self.mode.get() == "pixel" and not self.magic_pencil.get():
            self._paint_at(event)

    def _paint_at(self, event):
        if self.target_image is None:
            return
        gx, gy = self._canvas_to_grid_coords(event)
        if not (0 <= gx < self.grid_w and 0 <= gy < self.grid_h):
            return

        if self.target_pixels[gx, gy] == self.selected_color:
            if self.magic_pencil.get():
                changed = self._magic_pencil_swap(gx, gy)
            elif self.mode.get() == "fill":
                changed = self._flood_fill(gx, gy)
            else:
                changed = self._paint_single(gx, gy)

        if changed:
            self._update_cells(changed)
            self._update_progress()
            self._update_color_progress()

    def _paint_single(self, x, y):
        if self.canvas_pixels[x, y] == self.selected_color and (x, y) in self.painted:
            return []  # nothing actually changed - skip redundant redraw
        self.canvas_pixels[x, y] = self.selected_color
        self.painted.add((x, y))
        return [(x, y)]

    # 2.1.1.3 Fill mode: flood-fill every contiguous cell that wants the
    # same number as the one clicked, painting them all with the brush color.
    def _flood_fill(self, x, y):
        target_color = self.target_pixels[x, y]

        stack = [(x, y)]
        visited = set()
        changed = []
        while stack:
            cx, cy = stack.pop()
            if (cx, cy) in visited:
                continue
            if not (0 <= cx < self.grid_w and 0 <= cy < self.grid_h):
                continue
            if self.target_pixels[cx, cy] != target_color:
                continue

            self.canvas_pixels[cx, cy] = self.selected_color
            self.painted.add((cx, cy))
            visited.add((cx, cy))
            changed.append((cx, cy))
            stack.extend([(cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)])
        return changed

    # 2.1.1.4 Magic pencil: paint every cell (anywhere in the image) that
    # shares the clicked cell's number, not just a contiguous region.
    def _magic_pencil_swap(self, x, y):
        target_color = self.target_pixels[x, y]
        changed = []
        for pos in self.color_to_positions.get(target_color, ()):
            self.canvas_pixels[pos] = self.selected_color
            self.painted.add(pos)
            changed.append(pos)
        return changed

    # ------------------------------------------------------------------
    # Exporting
    # ------------------------------------------------------------------
    def get_current_image(self):
        """The small working canvas (white where unpainted, painted color elsewhere)."""
        return self.canvas_image

    def get_full_size_image(self):
        """Upscaled version matching the original photo's resolution, for saving."""
        if self.canvas_image is None:
            return None
        original = self.state_obj.original_image
        target_size = original.size if original is not None else (
            self.grid_w * 10, self.grid_h * 10
        )
        return grid_to_full_size(self.canvas_image, target_size)