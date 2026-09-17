"""
paint_tab.py

Paint-by-numbers style painting UI.

    - The canvas starts completely WHITE.
    - Every unpainted cell shows a small number, telling you which
      palette color belongs there (2.1.1.2).
    - Selecting a color (2.1.1.1) highlights every unpainted cell that
      wants that color in light grey, so you can see where to paint.
    - Painting a cell (single pixel / fill / magic pencil) replaces the
      white + number with the actual chosen color. You can only paint a
      cell with its correct color - selecting the wrong color and
      clicking simply does nothing, so mistakes can't happen.
    - A live counter shows how many cells of the selected color are
      painted vs. still left.
    - A small preview in the bottom-right corner shows the whole painting
      as it currently stands.

Internally there are two same-sized grids:
    self.target_image  - the "answer key": the quantized pixel-art colors
                          computed by the Pixelate tab. Read-only; used to
                          look up each cell's number and for highlighting.
    self.canvas_image  - what the user has actually painted so far. Starts
                          all white; this is what gets displayed (with the
                          numbers/highlight drawn on top) and what gets
                          exported/saved.

Performance note: repainting used to redraw the *entire* grid (every cell,
including a font-rendered number) on every single click or drag-motion
event, which is why painting felt laggy. Now a persistent raster
(`self._display_image`) is kept around and only the cells that actually
changed are redrawn into it; that small patch is then blitted directly
onto the live Tk image via the photo image's low-level "put" command
instead of rebuilding/reassigning the whole image. A full rebuild only
happens on load, zoom change, or "Clear painting".
"""

import io
import json
import zipfile

import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageDraw, ImageFont, ImageTk

from image_utils import get_palette_colors, grid_to_full_size, render_numbered_template
from theme import BG_DARK, BG_PANEL, FG_MUTED, ACCENT

SWATCH_SIZE = 30        # diameter of each round palette swatch
BIG_SWATCH_SIZE = 56    # diameter of the "currently selected color" circle
MIN_ZOOM = 1.0   # 1 screen pixel per cell - the lowest this renderer can go
MAX_ZOOM = 40.0

# Brush sizes available for single-pixel painting (right-click / magic
# pencil single mode). Bucket fill already covers a whole region on its
# own, so brush size only applies to the single-pixel tool.
BRUSH_SIZES = (1, 2, 3, 4)

# Bump this if the on-disk project format ever changes shape, so future
# versions of the app can decide whether/how to handle older save files.
PROJECT_FORMAT_VERSION = 1

# The palette panel is capped to this height and becomes scrollable beyond
# it, so a large color count (many rows of swatches) can never push the
# rest of the side panel (magic pencil, zoom controls, etc.) off screen.
PALETTE_MAX_HEIGHT = 230

WHITE = (255, 255, 255)
HIGHLIGHT = (222, 222, 222)      # light grey highlight for the selected color's cells
FLASH_COLOR = (255, 176, 46)     # bright amber "hint" flash for the selected color's cells
NUMBER_COLOR = (90, 90, 90)
GRID_LINE_COLOR = (205, 205, 205)

FLASH_TICKS = 6           # number of on/off toggles the hint flash does
FLASH_INTERVAL_MS = 180   # time between each toggle

RULER_THICKNESS = 28          # px, thickness of each ruler strip
RULER_MIN_LABEL_SPACING = 36  # px, minimum gap wanted between adjacent ruler labels
RULER_LABEL_STEPS = (1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000, 10000)

MIN_ZOOM_FOR_NUMBERS = 12        # below this cell size, numbers would be unreadable clutter
MIN_ZOOM_FOR_GRIDLINES = 5
PAN_STEP = 40                     # pixels moved per WASD / arrow key press
MINIMAP_MAX_SIZE = 170
DEFAULT_ZOOM = 16.0
MIDDLE_CLICK_DRAG_THRESHOLD = 4   # px of movement before a middle-click counts as a drag/pan


def _rgb_to_hex(rgb):
    return "#%02x%02x%02x" % rgb


class PaintTab(ttk.Frame):
    def __init__(self, parent, state_obj, keybindings=None):
        super().__init__(parent)
        self.state_obj = state_obj
        self.keybindings = keybindings
        self._bound_seqs = {}  # action -> seq currently bound, so re-binding can clean up first

        self.target_image = None     # PIL Image, read-only "answer key" colors
        self.target_pixels = None    # .load() access into target_image
        self.canvas_image = None     # PIL Image, the user's actual painted result
        self.canvas_pixels = None    # .load() access into canvas_image
        self.painted = set()         # {(x, y)} cells that have been painted
        self.grid_w = 0
        self.grid_h = 0

        self.color_to_number = {}         # target color -> palette number (1-based)
        self.color_to_positions = {}      # target color -> list[(x, y)], built once per image
        self.color_remaining = {}         # target color -> count of cells not yet painted
        self.color_swatches = {}          # target color -> palette swatch Canvas widget
        self.color_remaining_labels = {}  # target color -> "N left" Label widget
        self._font_cache = {}

        self.zoom = DEFAULT_ZOOM
        self._izoom = int(DEFAULT_ZOOM)
        self.show_numbers = True
        self.show_gridlines = True
        self._active_font = None
        self._tile_cache = {}
        self._zoom_after_id = None

        self.magic_pencil = tk.BooleanVar(value=False)
        self.brush_size = tk.IntVar(value=1)
        self.selected_color = (0, 0, 0)
        self.ordered_palette_colors = []  # filled in by _build_palette; used to step brush color

        self._display_image = None   # persistent full raster mirroring what's on screen
        self.photo_image = None      # keep PhotoImage reference alive
        self.minimap_photo = None    # keep minimap PhotoImage reference alive

        self._middle_press_pos = None
        self._middle_dragged = False

        # Space + left-click-drag panning (MS Paint / Photoshop-style
        # temporary pan tool) - held independently of which mouse button
        # started the drag, so releasing Space mid-drag doesn't cut it off.
        self._space_held = False
        self._space_pan_dragging = False

        # Hint flash: briefly pulses every unpainted cell of the currently
        # selected color between the normal highlight and FLASH_COLOR, so
        # it's easy to spot where to paint next in a busy image.
        self._flash_on = False
        self._flash_after_id = None
        self._flash_positions = []
        self._flash_count = 0

        # Ruler strips (Excel-style column/row headers) - which grid cell
        # is under the mouse right now, and the last-known scroll offset in
        # display pixels (cached so the cheap hover-only redraw doesn't need
        # to re-query the canvas's xview/yview on every mouse-move event).
        self._hover_gx = None
        self._hover_gy = None
        self._ruler_view_x = 0
        self._ruler_view_y = 0

        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self):
        root = ttk.Frame(self)
        root.pack(fill=tk.BOTH, expand=True)

        # 2.1.1 Left side panel -----------------------------------------
        side = ttk.Frame(root, padding=8, relief=tk.GROOVE, borderwidth=1)
        side.pack(side=tk.LEFT, fill=tk.Y)

        # Big, hard-to-miss counter for how many pixels are still uncolored
        # overall - the per-color "N left" counts under each swatch are
        # useful once you've picked a color, but this is the "am I nearly
        # done?" number at a glance.
        self.remaining_big_label = ttk.Label(
            side, text="", font=("TkDefaultFont", 20, "bold"), foreground=ACCENT, anchor="center",
        )
        self.remaining_big_label.pack(fill=tk.X, pady=(0, 2))
        ttk.Label(side, text="pixels left", foreground=FG_MUTED, anchor="center").pack(fill=tk.X)

        ttk.Separator(side, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=6)

        # 4. Live preview of the whole painting, kept on the left side panel
        # (rather than floating over the canvas) so it never obstructs the
        # view of the artwork you're actively working on.
        ttk.Label(side, text="Preview", font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
        self.minimap_label = tk.Label(side, background=BG_DARK, borderwidth=1, relief=tk.SOLID)
        self.minimap_label.pack(pady=(4, 12))

        ttk.Separator(side, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=6)

        # Big circle showing the currently selected brush color at a glance.
        ttk.Label(side, text="Selected Color", font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
        self.selected_canvas = tk.Canvas(
            side, width=BIG_SWATCH_SIZE, height=BIG_SWATCH_SIZE, highlightthickness=0, bd=0, background=BG_PANEL
        )
        self.selected_canvas.pack(pady=(6, 2))
        pad = 2
        self.selected_oval = self.selected_canvas.create_oval(
            pad, pad, BIG_SWATCH_SIZE - pad, BIG_SWATCH_SIZE - pad,
            fill=BG_PANEL, outline=FG_MUTED, width=2,
        )
        self.selected_indicator_label = ttk.Label(side, text="", font=("TkDefaultFont", 9))
        self.selected_indicator_label.pack(pady=(0, 6))

        self.hint_button = ttk.Button(side, text="Hint (flash cells)", command=self.flash_hint)
        self.hint_button.pack(pady=(0, 2))
        self.hint_hotkey_label = ttk.Label(side, text="", foreground=FG_MUTED)
        self.hint_hotkey_label.pack(pady=(0, 12))

        ttk.Label(side, text="Palette", font=("TkDefaultFont", 10, "bold")).pack(anchor="w")

        # The palette can hold up to 64 swatches, which is far more than
        # fits in the side panel - so it lives in its own small scrollable
        # area (fixed height + scrollbar) instead of a plain Frame that
        # would just keep growing and shove everything below it (magic
        # pencil, zoom controls, ...) out of the visible window.
        palette_container = ttk.Frame(side)
        palette_container.pack(fill=tk.X, pady=(4, 12))

        self.palette_canvas = tk.Canvas(
            palette_container,
            background=BG_PANEL,
            highlightthickness=0,
            height=PALETTE_MAX_HEIGHT,
        )
        palette_scroll = ttk.Scrollbar(
            palette_container, orient=tk.VERTICAL, command=self.palette_canvas.yview
        )
        self.palette_canvas.configure(yscrollcommand=palette_scroll.set)

        self.palette_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        palette_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.palette_frame = ttk.Frame(self.palette_canvas)
        self._palette_window_id = self.palette_canvas.create_window(
            (0, 0), window=self.palette_frame, anchor="nw"
        )

        # Keep the scrollregion in sync with the palette's actual content
        # size, and keep the embedded frame's width matched to the canvas's
        # (so swatches lay out to the panel's width rather than to some
        # arbitrary default).
        self.palette_frame.bind("<Configure>", self._on_palette_frame_configure)
        self.palette_canvas.bind("<Configure>", self._on_palette_canvas_configure)

        # Mouse-wheel scrolling only while the cursor is actually over the
        # palette area - bound/unbound on Enter/Leave of the *container*
        # (not the canvas) so it doesn't fight the main paint canvas's own
        # wheel-pan binding, and so it also works for the scrollbar itself.
        palette_container.bind("<Enter>", lambda e: self._bind_palette_wheel())
        palette_container.bind("<Leave>", lambda e: self._unbind_palette_wheel())

        ttk.Separator(side, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=6)

        ttk.Checkbutton(
            side, text="Magic pencil (auto-detects the right color)", variable=self.magic_pencil
        ).pack(anchor="w", pady=(4, 0))  # 2.1.1.4

        # Brush size only affects the single-pixel tool (right-click) -
        # bucket fill already covers a whole region on its own, so a
        # brush size there wouldn't mean anything extra.
        ttk.Label(side, text="Brush size (right-click only):", foreground=FG_MUTED).pack(
            anchor="w", pady=(10, 0)
        )
        brush_row = ttk.Frame(side)
        brush_row.pack(anchor="w", pady=(2, 0))
        for size in BRUSH_SIZES:
            ttk.Radiobutton(
                brush_row, text=f"{size}x{size}", variable=self.brush_size, value=size
            ).pack(side=tk.LEFT, padx=(0, 6))

        ttk.Separator(side, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=6)

        ttk.Label(side, text="Zoom", font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
        self.zoom_slider = ttk.Scale(
            side, from_=MIN_ZOOM, to=MAX_ZOOM, orient=tk.HORIZONTAL, command=self._on_zoom_change
        )
        self.zoom_slider.set(self.zoom)
        self.zoom_slider.pack(fill=tk.X, pady=4)

        zoom_buttons = ttk.Frame(side)
        zoom_buttons.pack(fill=tk.X)
        ttk.Button(zoom_buttons, text="Fit to window", command=self._zoom_to_fit).pack(side=tk.LEFT, fill=tk.X, expand=True)

        ttk.Button(side, text="Clear painting", command=self._clear_painting).pack(fill=tk.X, pady=(8, 0))

        # 2.2 Main canvas area --------------------------------------------
        main = ttk.Frame(root)
        main.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.main_frame = main

        h_scroll = ttk.Scrollbar(main, orient=tk.HORIZONTAL)
        v_scroll = ttk.Scrollbar(main, orient=tk.VERTICAL)

        self.canvas = tk.Canvas(
            main,
            background=BG_DARK,
            xscrollcommand=h_scroll.set,
            yscrollcommand=v_scroll.set,
        )
        h_scroll.config(command=self._on_hscroll)
        v_scroll.config(command=self._on_vscroll)

        # Excel-style column/row rulers, plus a small blank corner square
        # where they meet, so it's easy to tell exactly which column/row a
        # pixel is in once you're zoomed in. They track the main canvas's
        # scroll position and always highlight whichever cell is under the
        # mouse (see _update_rulers / _update_ruler_hover).
        corner = tk.Canvas(
            main, width=RULER_THICKNESS, height=RULER_THICKNESS,
            background=BG_PANEL, highlightthickness=0,
        )
        self.h_ruler = tk.Canvas(main, height=RULER_THICKNESS, background=BG_PANEL, highlightthickness=0)
        self.v_ruler = tk.Canvas(main, width=RULER_THICKNESS, background=BG_PANEL, highlightthickness=0)

        corner.grid(row=0, column=0, sticky="nsew")
        self.h_ruler.grid(row=0, column=1, sticky="ew")
        self.v_ruler.grid(row=1, column=0, sticky="ns")
        self.canvas.grid(row=1, column=1, sticky="nsew")
        v_scroll.grid(row=1, column=2, sticky="ns")
        h_scroll.grid(row=2, column=1, sticky="ew")
        main.rowconfigure(1, weight=1)
        main.columnconfigure(1, weight=1)

        self.h_ruler.bind("<Configure>", lambda e: self._update_rulers())
        self.v_ruler.bind("<Configure>", lambda e: self._update_rulers())

        self.image_id = None

        # 2.3 mouse as brush: left-click = fill (bucket), right-click = single pixel
        self.canvas.bind("<Button-1>", lambda e: self._on_click(e, "fill"))
        self.canvas.bind("<B1-Motion>", lambda e: self._on_drag_paint(e, "fill"))
        self.canvas.bind("<ButtonRelease-1>", self._on_left_release)
        self.canvas.bind("<Button-3>", lambda e: self._on_click(e, "pixel"))
        self.canvas.bind("<B3-Motion>", lambda e: self._on_drag_paint(e, "pixel"))
        self.canvas.bind("<Motion>", self._on_mouse_move)
        self.canvas.bind("<Leave>", self._on_canvas_leave, add="+")
        self.canvas.bind("<Configure>", lambda e: self._update_rulers(), add="+")

        # 2.2.1.2 movement controls: middle-mouse-drag panning. A middle
        # click *without* a drag resets the zoom instead (see _on_pan_release).
        self.canvas.bind("<ButtonPress-2>", self._on_pan_start)
        self.canvas.bind("<B2-Motion>", self._on_pan_move)
        self.canvas.bind("<ButtonRelease-2>", self._on_pan_release)

        # Space + left-click-drag: MS Paint/Photoshop-style temporary pan
        # tool. Held down, it turns the very next left-click-drag into a
        # pan instead of a paint stroke (see _on_click/_on_drag_paint).
        self.canvas.bind("<KeyPress-space>", self._on_space_press)
        self.canvas.bind("<KeyRelease-space>", self._on_space_release)

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

        # Alt+wheel steps the selected brush color to the next/previous
        # palette swatch, instead of panning - bound the same way as
        # Control-MouseWheel above, so Tk picks this more specific pattern
        # over the plain pan binding below whenever Alt is actually held.
        self.canvas.bind("<Alt-MouseWheel>", self._on_alt_wheel_select_color)
        self.canvas.bind("<Alt-Button-4>", self._on_alt_wheel_select_color)
        self.canvas.bind("<Alt-Button-5>", self._on_alt_wheel_select_color)

        # Plain scroll wheel (no Ctrl) pans vertically, like a normal
        # scrollable view - Tk picks the more specific Control-MouseWheel
        # binding above whenever Ctrl is actually held, so the two never
        # conflict. Button-4/5 cover Linux, which has no <MouseWheel>/delta.
        self.canvas.bind("<MouseWheel>", self._on_wheel_pan)
        self.canvas.bind("<Button-4>", self._on_wheel_pan)
        self.canvas.bind("<Button-5>", self._on_wheel_pan)

        self.apply_keybindings()

    # ------------------------------------------------------------------
    # Customizable keyboard shortcuts (currently just the hint flash;
    # WASD/arrow panning stay fixed since they're already discoverable
    # via the on-screen labels and aren't worth the extra config surface).
    # ------------------------------------------------------------------
    def apply_keybindings(self):
        if self.keybindings is None:
            return

        for seq in self._bound_seqs.values():
            self.canvas.unbind(seq)
        self._bound_seqs = {}

        seq = self.keybindings.sequence("toggle_help_mode")
        self.canvas.bind(seq, lambda e: self.flash_hint())
        self._bound_seqs["toggle_help_mode"] = seq

        key = self.keybindings.get("toggle_help_mode")
        self.hint_hotkey_label.config(text=f"Shortcut: {key} (while hovering canvas)")

    def focus_default(self):
        """Grab keyboard focus for this tab's canvas - called by app.py
        whenever the notebook switches to this tab, so WASD/arrow panning
        and the hint hotkey work immediately without a mouse hover first."""
        self.canvas.focus_set()

    def _on_alt_wheel_select_color(self, event):
        if not self.ordered_palette_colors:
            return "break"
        if getattr(event, "num", None) in (4, 5):
            delta = -1 if event.num == 4 else 1
        else:
            delta = -1 if event.delta > 0 else 1

        try:
            current_index = self.ordered_palette_colors.index(self.selected_color)
        except ValueError:
            current_index = 0
        # Wraps around at either end, so scrolling is a continuous cycle
        # through the palette rather than stopping at the first/last color.
        new_index = (current_index + delta) % len(self.ordered_palette_colors)
        self._select_color(self.ordered_palette_colors[new_index])
        return "break"  # don't also let the plain-wheel pan binding fire

    # ------------------------------------------------------------------
    # Scrollable palette panel plumbing
    # ------------------------------------------------------------------
    def _on_palette_frame_configure(self, event):
        # Content size changed (e.g. palette rebuilt with a different
        # number of colors) - grow/shrink the scrollable region to match.
        self.palette_canvas.configure(scrollregion=self.palette_canvas.bbox("all"))

    def _on_palette_canvas_configure(self, event):
        # Keep the embedded frame exactly as wide as the visible canvas so
        # the swatch grid uses the full side-panel width rather than
        # whatever width it happened to need at creation time.
        self.palette_canvas.itemconfig(self._palette_window_id, width=event.width)

    def _bind_palette_wheel(self):
        self.palette_canvas.bind_all("<MouseWheel>", self._on_palette_wheel)
        self.palette_canvas.bind_all("<Button-4>", self._on_palette_wheel)
        self.palette_canvas.bind_all("<Button-5>", self._on_palette_wheel)

    def _unbind_palette_wheel(self):
        self.palette_canvas.unbind_all("<MouseWheel>")
        self.palette_canvas.unbind_all("<Button-4>")
        self.palette_canvas.unbind_all("<Button-5>")

    def _on_palette_wheel(self, event):
        if getattr(event, "num", None) in (4, 5):
            delta = -1 if event.num == 4 else 1
        else:
            delta = -1 if event.delta > 0 else 1
        self.palette_canvas.yview_scroll(delta, "units")
        return "break"

    # ------------------------------------------------------------------
    # Loading a freshly pixelated image into the paint grid
    # ------------------------------------------------------------------
    def load_pixelated_image(self):
        target = self.state_obj.pixel_grid_image
        if target is None:
            return
        self._cancel_flash()

        self.target_image = target.copy()
        self.target_pixels = self.target_image.load()
        self.grid_w, self.grid_h = self.target_image.size

        self.canvas_image = Image.new("RGB", (self.grid_w, self.grid_h), WHITE)
        self.canvas_pixels = self.canvas_image.load()
        self.painted = set()

        self._build_color_positions()
        self.color_remaining = {color: len(positions) for color, positions in self.color_to_positions.items()}
        self._build_palette()
        self._rebuild_full()
        self._update_progress()
        self._update_palette_progress()

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
        self._cancel_flash()
        self.canvas_image = Image.new("RGB", (self.grid_w, self.grid_h), WHITE)
        self.canvas_pixels = self.canvas_image.load()
        self.painted = set()
        self.color_remaining = {color: len(positions) for color, positions in self.color_to_positions.items()}
        self._rebuild_full()
        self._update_progress()
        self._update_palette_progress()

    # 2.1.1.1 / 2.1.1.2 Build one round swatch + number + "N left" label
    # per palette color.
    def _build_palette(self):
        for child in self.palette_frame.winfo_children():
            child.destroy()
        self.color_to_number = {}
        self.color_swatches = {}
        self.color_remaining_labels = {}

        colors = get_palette_colors(self.target_image, max_colors=64)
        colors.sort(key=lambda color: sum(color))
        self.ordered_palette_colors = colors  # used to step the brush color with Alt+scroll

        if colors:
            self.selected_color = colors[0]

        for index, color in enumerate(colors, start=1):
            self.color_to_number[color] = index
            hex_color = _rgb_to_hex(color)

            cell = ttk.Frame(self.palette_frame)
            cell.grid(row=(index - 1) // 4, column=(index - 1) % 4, padx=3, pady=3)

            swatch = tk.Canvas(
                cell, width=SWATCH_SIZE, height=SWATCH_SIZE, highlightthickness=0, bd=0, cursor="hand2",
                background=BG_PANEL,
            )
            pad = 2
            swatch.create_oval(
                pad, pad, SWATCH_SIZE - pad, SWATCH_SIZE - pad,
                fill=hex_color, outline=hex_color, width=2, tags="circle",
            )
            swatch.bind("<Button-1>", lambda event, c=color: self._select_color(c))
            swatch.pack()
            self.color_swatches[color] = swatch

            ttk.Label(cell, text=str(index), font=("TkDefaultFont", 8), width=3, anchor="center").pack()

            remaining_label = ttk.Label(
                cell, text="", font=("TkDefaultFont", 8), foreground=FG_MUTED, width=7, anchor="center"
            )
            remaining_label.pack()
            self.color_remaining_labels[color] = remaining_label

        self._update_swatch_highlight()
        self._update_selected_indicator()

    def _select_color(self, color):
        self._cancel_flash()
        old_color = self.selected_color
        self.selected_color = color
        self._update_swatch_highlight()
        self._update_selected_indicator()

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

    def _update_swatch_highlight(self):
        """Draw a dark ring around whichever swatch is currently selected,
        so the active color is obvious at a glance in the palette itself."""
        for color, canvas in self.color_swatches.items():
            is_selected = color == self.selected_color
            outline = "#222222" if is_selected else _rgb_to_hex(color)
            width = 3 if is_selected else 2
            canvas.itemconfig("circle", outline=outline, width=width)

    def _update_selected_indicator(self):
        """Refresh the big circle (+ number) showing the current brush color."""
        color = self.selected_color
        hex_color = _rgb_to_hex(color) if color else "#ffffff"
        self.selected_canvas.itemconfig(self.selected_oval, fill=hex_color, outline=hex_color)
        number = self.color_to_number.get(color, "?")
        self.selected_indicator_label.config(text=f"Color #{number}")

    # ------------------------------------------------------------------
    # Hint: flash every uncolored cell that wants the currently selected
    # color, so it's easy to spot where to paint next in a busy image.
    # ------------------------------------------------------------------
    def _cancel_flash(self):
        if self._flash_after_id is not None:
            self.after_cancel(self._flash_after_id)
            self._flash_after_id = None
        if self._flash_on:
            self._flash_on = False
            self._update_cells(self._flash_positions)
        self._flash_positions = []

    def flash_hint(self):
        if self.target_image is None or not self.selected_color:
            return
        if self._flash_after_id is not None:
            return  # already mid-flash - ignore repeat presses/clicks

        positions = [
            pos for pos in self.color_to_positions.get(self.selected_color, ())
            if pos not in self.painted
        ]
        if not positions:
            return  # nothing left of this color to point out

        self._flash_positions = positions
        self._flash_count = 0
        self._flash_on = False
        self._do_flash_tick()

    def _do_flash_tick(self):
        self._flash_on = not self._flash_on
        self._update_cells(self._flash_positions)
        self._flash_count += 1
        if self._flash_count < FLASH_TICKS:
            self._flash_after_id = self.after(FLASH_INTERVAL_MS, self._do_flash_tick)
        else:
            # Always finish back on the normal (non-flash) highlight state.
            self._flash_on = False
            self._update_cells(self._flash_positions)
            self._flash_after_id = None

    def _update_palette_progress(self, colors=None):
        """Refresh the 'N left' label under each palette swatch. Pass a
        specific iterable of colors to cheaply refresh just those (the
        normal case, right after a paint action); omit it to refresh every
        swatch (load, clear painting)."""
        if colors is None:
            colors = list(self.color_remaining_labels.keys())
        for color in colors:
            label = self.color_remaining_labels.get(color)
            if label is None:
                continue
            remaining = self.color_remaining.get(color, 0)
            label.config(text=f"{remaining} left")

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def _get_font(self, size):
        font = self._font_cache.get(size)
        if font is None:
            font = ImageFont.load_default(size=size)
            self._font_cache[size] = font
        return font

    def _get_unpainted_tile(self, target_color, mode):
        """Pre-rendered zoom x zoom tile for an unpainted cell (background +
        number + grid border). Built once per (color, mode) pair and
        reused - this is what makes highlighting/flashing a whole color's
        worth of cells fast: no per-cell font rendering, just a cheap
        paste(). `mode` is one of "normal", "highlight", or "flash"."""
        key = ("u", target_color, mode)
        tile = self._tile_cache.get(key)
        if tile is None:
            size = self._izoom
            bg = FLASH_COLOR if mode == "flash" else HIGHLIGHT if mode == "highlight" else WHITE
            tile = Image.new("RGB", (size, size), bg)
            draw = ImageDraw.Draw(tile)
            if self.show_numbers:
                number = self.color_to_number.get(target_color, "?")
                text = str(number)
                bbox = draw.textbbox((0, 0), text, font=self._active_font)
                tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
                tx = (size - tw) / 2 - bbox[0]
                ty = (size - th) / 2 - bbox[1]
                draw.text((tx, ty), text, fill=NUMBER_COLOR, font=self._active_font)
            if self.show_gridlines:
                draw.rectangle((0, 0, size - 1, size - 1), outline=GRID_LINE_COLOR, width=1)
            self._tile_cache[key] = tile
        return tile

    def _get_painted_tile(self, color):
        """Pre-rendered zoom x zoom tile for a cell painted with `color`."""
        key = ("p", color)
        tile = self._tile_cache.get(key)
        if tile is None:
            size = self._izoom
            tile = Image.new("RGB", (size, size), color)
            if self.show_gridlines:
                draw = ImageDraw.Draw(tile)
                draw.rectangle((0, 0, size - 1, size - 1), outline=GRID_LINE_COLOR, width=1)
            self._tile_cache[key] = tile
        return tile

    def _draw_cell(self, gx, gy):
        """Paste the correct pre-rendered tile for one cell into the display
        image - fast, since the expensive font rendering already happened
        once when the tile was first built."""
        if (gx, gy) in self.painted:
            tile = self._get_painted_tile(self.canvas_pixels[gx, gy])
        else:
            target_color = self.target_pixels[gx, gy]
            if target_color != self.selected_color:
                mode = "normal"
            elif self._flash_on:
                mode = "flash"
            else:
                mode = "highlight"
            tile = self._get_unpainted_tile(target_color, mode)
        self._display_image.paste(tile, (gx * self._izoom, gy * self._izoom))

    def _rebuild_full(self):
        """Full re-render of every cell. Used on load, zoom change, and clear -
        infrequent actions, so the O(grid size) cost here is fine (and cheap
        anyway now, since it's just pasting cached tiles)."""
        if self.target_image is None:
            return

        self._izoom = max(1, round(self.zoom))
        disp_w = max(1, self.grid_w * self._izoom)
        disp_h = max(1, self.grid_h * self._izoom)

        self.show_numbers = self._izoom >= MIN_ZOOM_FOR_NUMBERS
        self.show_gridlines = self._izoom >= MIN_ZOOM_FOR_GRIDLINES
        self._active_font = self._get_font(max(6, int(self._izoom * 0.6))) if self.show_numbers else None
        self._tile_cache = {}  # tile size/content depends on zoom - stale cache would look wrong

        self._display_image = Image.new("RGB", (disp_w, disp_h), WHITE)
        for gy in range(self.grid_h):
            for gx in range(self.grid_w):
                self._draw_cell(gx, gy)

        self.photo_image = ImageTk.PhotoImage(self._display_image)
        if self.image_id is None:
            self.image_id = self.canvas.create_image(0, 0, image=self.photo_image, anchor="nw")
        else:
            self.canvas.itemconfig(self.image_id, image=self.photo_image)
        self.canvas.config(scrollregion=(0, 0, disp_w, disp_h))

        self._update_minimap()

    def _update_cells(self, cells):
        """Fast path: redraw only the given (x, y) cells. For a handful of
        cells (a single click, a small fill) this blits just their own small
        regions onto the live Tk image. For a large batch (e.g. highlighting
        every cell of a very common color), it's cheaper to do one single
        full PhotoImage rebuild than many separate patch updates."""
        if not cells or self._display_image is None:
            return

        for (gx, gy) in cells:
            self._draw_cell(gx, gy)

        disp_w, disp_h = self._display_image.size
        izoom = self._izoom

        if len(cells) * izoom * izoom > self.PATCH_PIXEL_THRESHOLD:
            self.photo_image = ImageTk.PhotoImage(self._display_image)
            self.canvas.itemconfig(self.image_id, image=self.photo_image)
            self._update_minimap()
            return

        # Merge cells into contiguous horizontal spans per row, so a solid
        # fill/magic-pencil region blits as a handful of wide patches
        # instead of one patch per cell.
        by_row = {}
        for (gx, gy) in cells:
            by_row.setdefault(gy, []).append(gx)

        for gy, xs in by_row.items():
            xs.sort()
            run_start = xs[0]
            prev = xs[0]
            for gx in xs[1:]:
                if gx == prev + 1:
                    prev = gx
                    continue
                self._blit_cell_span(run_start, prev, gy, izoom, disp_w, disp_h)
                run_start = gx
                prev = gx
            self._blit_cell_span(run_start, prev, gy, izoom, disp_w, disp_h)

        self._update_minimap()

    def _blit_cell_span(self, gx_start, gx_end, gy, izoom, disp_w, disp_h):
        x0 = max(0, gx_start * izoom)
        y0 = max(0, gy * izoom)
        x1 = min(disp_w, (gx_end + 1) * izoom)
        y1 = min(disp_h, (gy + 1) * izoom)
        self._blit_patch(x0, y0, x1, y1)

    # Below this many pixels, a manual per-pixel "put" patch is faster than
    # rebuilding the whole PhotoImage; above it, Pillow's own (C-level)
    # PhotoImage constructor easily wins over our pure-Python hex loop.
    PATCH_PIXEL_THRESHOLD = 20000

    def _blit_patch(self, x0, y0, x1, y1):
        """Push a rectangular region of self._display_image onto the live
        canvas image, choosing whichever update method is faster for the
        size of the change."""
        if self.photo_image is None or x1 <= x0 or y1 <= y0:
            return

        area = (x1 - x0) * (y1 - y0)
        if area > self.PATCH_PIXEL_THRESHOLD:
            self.photo_image = ImageTk.PhotoImage(self._display_image)
            self.canvas.itemconfig(self.image_id, image=self.photo_image)
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
        if self.canvas_image is not None:
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

        # Every place that calls _update_minimap() represents "the view
        # changed" (scrolled, panned, zoomed, ...), so piggyback the ruler
        # refresh here too rather than hunting down each call site.
        self._update_rulers()

    # ------------------------------------------------------------------
    # Excel-style column/row rulers along the top/left of the canvas.
    # ------------------------------------------------------------------
    def _label_stride(self, cell_px):
        """How many columns/rows to skip between labeled ticks so labels
        stay at least RULER_MIN_LABEL_SPACING px apart at the current zoom."""
        for step in RULER_LABEL_STEPS:
            if cell_px * step >= RULER_MIN_LABEL_SPACING:
                return step
        return RULER_LABEL_STEPS[-1]

    def _update_rulers(self):
        """Full redraw of both ruler strips' tick marks/labels - cheap
        enough for scroll/zoom/resize events, but NOT meant to run on every
        mouse-move (see _update_ruler_hover for that lightweight path)."""
        if self.target_image is None or self._izoom <= 0:
            self.h_ruler.delete("all")
            self.v_ruler.delete("all")
            return

        izoom = self._izoom
        first_x, _ = self.canvas.xview()
        first_y, _ = self.canvas.yview()
        self._ruler_view_x = first_x * self.grid_w * izoom
        self._ruler_view_y = first_y * self.grid_h * izoom

        self._draw_ruler_axis(self.h_ruler, horizontal=True, view_offset=self._ruler_view_x,
                               grid_count=self.grid_w, izoom=izoom)
        self._draw_ruler_axis(self.v_ruler, horizontal=False, view_offset=self._ruler_view_y,
                               grid_count=self.grid_h, izoom=izoom)
        self._update_ruler_hover()

    def _draw_ruler_axis(self, ruler, horizontal, view_offset, grid_count, izoom):
        ruler.delete("ticks")
        length_px = ruler.winfo_width() if horizontal else ruler.winfo_height()
        if length_px <= 1 or grid_count <= 0:
            return

        stride = self._label_stride(izoom)
        first_index = max(0, int(view_offset // izoom))
        last_index = min(grid_count - 1, int((view_offset + length_px) // izoom) + 1)
        # Align the first labeled tick down to a stride boundary so labels
        # stay put as you scroll, rather than jittering position.
        start = (first_index // stride) * stride

        for gi in range(start, last_index + 1, stride):
            if gi < 0:
                continue
            pos = gi * izoom - view_offset
            center = pos + izoom / 2
            if horizontal:
                ruler.create_line(pos, RULER_THICKNESS - 6, pos, RULER_THICKNESS, fill=FG_MUTED, tags="ticks")
                ruler.create_text(
                    center, RULER_THICKNESS / 2, text=str(gi), fill=FG_MUTED,
                    font=("TkDefaultFont", 8), tags="ticks",
                )
            else:
                ruler.create_line(RULER_THICKNESS - 6, pos, RULER_THICKNESS, pos, fill=FG_MUTED, tags="ticks")
                ruler.create_text(
                    RULER_THICKNESS / 2, center, text=str(gi), fill=FG_MUTED,
                    font=("TkDefaultFont", 8), tags="ticks",
                )

    def _update_ruler_hover(self):
        """Cheap redraw of just the hover highlight - a filled rectangle +
        bold label marking the exact column/row under the cursor. Kept
        separate from the full tick redraw above so it's fast enough to run
        on every mouse-move while exploring a zoomed-in image."""
        self.h_ruler.delete("hover")
        self.v_ruler.delete("hover")
        if self.target_image is None or self._izoom <= 0:
            return
        if self._hover_gx is None or self._hover_gy is None:
            return

        izoom = self._izoom
        if 0 <= self._hover_gx < self.grid_w:
            pos = self._hover_gx * izoom - self._ruler_view_x
            self.h_ruler.create_rectangle(
                pos, 0, pos + izoom, RULER_THICKNESS, fill=ACCENT, outline="", tags="hover"
            )
            self.h_ruler.create_text(
                pos + izoom / 2, RULER_THICKNESS / 2, text=str(self._hover_gx),
                fill="#ffffff", font=("TkDefaultFont", 8, "bold"), tags="hover",
            )
        if 0 <= self._hover_gy < self.grid_h:
            pos = self._hover_gy * izoom - self._ruler_view_y
            self.v_ruler.create_rectangle(
                0, pos, RULER_THICKNESS, pos + izoom, fill=ACCENT, outline="", tags="hover"
            )
            self.v_ruler.create_text(
                RULER_THICKNESS / 2, pos + izoom / 2, text=str(self._hover_gy),
                fill="#ffffff", font=("TkDefaultFont", 8, "bold"), tags="hover",
            )

    def _update_progress(self):
        total = self.grid_w * self.grid_h
        done = len(self.painted)
        self.remaining_big_label.config(text=str(total - done))

    # 2.2.1.1 Zoom control. The zoom slider fires continuously while being
    # dragged; a full rebuild is cheap now (tile-cached), but still not
    # worth doing on every intermediate tick, so we debounce to the last
    # value once the slider settles for a moment. Whatever's centered in
    # the viewport before zooming stays centered afterward.
    def _on_zoom_change(self, value):
        self.zoom = float(value)
        if self._zoom_after_id is not None:
            self.after_cancel(self._zoom_after_id)
        self._zoom_after_id = self.after(80, self._commit_zoom)

    def _current_view_center_in_grid(self):
        """The grid coordinate currently centered in the viewport, using the
        raster as it exists right now (i.e. before any pending rebuild)."""
        if not self.grid_w or not self.grid_h or not self._izoom:
            return 0, 0
        first_x, last_x = self.canvas.xview()
        first_y, last_y = self.canvas.yview()
        disp_w = self.grid_w * self._izoom
        disp_h = self.grid_h * self._izoom
        center_grid_x = (first_x + last_x) / 2 * disp_w / self._izoom
        center_grid_y = (first_y + last_y) / 2 * disp_h / self._izoom
        return center_grid_x, center_grid_y

    def _center_view_on(self, grid_x, grid_y):
        if not self.grid_w or not self.grid_h:
            return
        disp_w = self.grid_w * self._izoom
        disp_h = self.grid_h * self._izoom
        view_w = max(1, self.canvas.winfo_width())
        view_h = max(1, self.canvas.winfo_height())
        target_px_x = grid_x * self._izoom
        target_px_y = grid_y * self._izoom

        first_x = (target_px_x - view_w / 2) / disp_w
        first_y = (target_px_y - view_h / 2) / disp_h
        first_x = min(max(first_x, 0.0), max(0.0, 1.0 - view_w / disp_w))
        first_y = min(max(first_y, 0.0), max(0.0, 1.0 - view_h / disp_h))
        self.canvas.xview_moveto(first_x)
        self.canvas.yview_moveto(first_y)
        self._update_minimap()

    def _commit_zoom(self, center_override=None):
        self._zoom_after_id = None
        center = center_override if center_override is not None else self._current_view_center_in_grid()
        self._rebuild_full()
        self._center_view_on(*center)

    def _on_ctrl_wheel_zoom(self, event):
        step = 2.0 if event.delta > 0 else -2.0
        new_zoom = min(MAX_ZOOM, max(MIN_ZOOM, self.zoom + step))
        self.zoom_slider.set(new_zoom)  # triggers _on_zoom_change

    # Plain (non-Ctrl) scroll wheel: pan the view up/down.
    def _on_wheel_pan(self, event):
        if getattr(event, "num", None) in (4, 5):
            # Linux: Button-4 = scroll up, Button-5 = scroll down, no delta
            direction = -1 if event.num == 4 else 1
        else:
            # Windows/macOS: event.delta is +/-120 per notch
            direction = -1 if event.delta > 0 else 1
        self._pan_by_pixels(0, direction * PAN_STEP)
        return "break"

    def _zoom_to_fit(self):
        """Zoom out (or in) just enough to see the whole picture at once."""
        if not self.grid_w or not self.grid_h:
            return
        self.canvas.update_idletasks()
        view_w = max(1, self.canvas.winfo_width())
        view_h = max(1, self.canvas.winfo_height())
        fit_zoom = min(view_w / self.grid_w, view_h / self.grid_h)
        fit_zoom = max(MIN_ZOOM, min(MAX_ZOOM, fit_zoom))

        if self._zoom_after_id is not None:
            self.after_cancel(self._zoom_after_id)
            self._zoom_after_id = None
        self.zoom = fit_zoom
        self.zoom_slider.set(fit_zoom)
        self._commit_zoom(center_override=(self.grid_w / 2, self.grid_h / 2))

    def _reset_zoom(self):
        """Middle-click (without dragging) resets back to the default zoom,
        centered on the middle of the picture."""
        if not self.grid_w or not self.grid_h:
            return
        if self._zoom_after_id is not None:
            self.after_cancel(self._zoom_after_id)
            self._zoom_after_id = None
        self.zoom = DEFAULT_ZOOM
        self.zoom_slider.set(DEFAULT_ZOOM)
        self._commit_zoom(center_override=(self.grid_w / 2, self.grid_h / 2))

    # 2.2.1.2 Panning. Middle-click-drag pans; a middle click released
    # without much movement is treated as "reset zoom" instead.
    def _on_pan_start(self, event):
        self._middle_press_pos = (event.x, event.y)
        self._middle_dragged = False
        self.canvas.scan_mark(event.x, event.y)

    def _on_pan_move(self, event):
        if self._middle_press_pos is not None:
            dx = event.x - self._middle_press_pos[0]
            dy = event.y - self._middle_press_pos[1]
            if abs(dx) > MIDDLE_CLICK_DRAG_THRESHOLD or abs(dy) > MIDDLE_CLICK_DRAG_THRESHOLD:
                self._middle_dragged = True
        self.canvas.scan_dragto(event.x, event.y, gain=1)
        self._update_minimap()

    def _on_pan_release(self, event):
        if not self._middle_dragged:
            self._reset_zoom()
        self._middle_press_pos = None
        self._middle_dragged = False

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
        disp_w = max(1, self.grid_w * self._izoom)
        disp_h = max(1, self.grid_h * self._izoom)

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
        gx = int(cx // self._izoom)
        gy = int(cy // self._izoom)
        return gx, gy

    def _track_hover(self, event):
        """Update which grid cell the ruler should highlight. Needs to run
        from both plain hover (<Motion>) AND while a button is held down
        (<B1-Motion>/<B3-Motion> while painting) - Tk delivers those as
        separate event sequences, plain <Motion> does NOT fire while a
        button is pressed, so relying on it alone left the ruler frozen
        during click-and-drag painting."""
        if self.target_image is None:
            return
        gx, gy = self._canvas_to_grid_coords(event)
        in_bounds = 0 <= gx < self.grid_w and 0 <= gy < self.grid_h
        self._hover_gx = gx if in_bounds else None
        self._hover_gy = gy if in_bounds else None
        self._update_ruler_hover()

    def _on_mouse_move(self, event):
        self._track_hover(event)

    def _on_canvas_leave(self, event):
        self._hover_gx = None
        self._hover_gy = None
        self._update_ruler_hover()

    def _on_click(self, event, mode):
        self.canvas.focus_set()
        if self._space_held:
            self._start_space_pan(event)
            return
        self._track_hover(event)
        self._paint_at(event, mode)

    def _on_drag_paint(self, event, mode):
        if self._space_pan_dragging:
            self._continue_space_pan(event)
            return
        self._track_hover(event)
        self._paint_at(event, mode)

    def _on_left_release(self, event):
        if self._space_pan_dragging:
            self._end_space_pan()

    # ------------------------------------------------------------------
    # Space + left-click-drag panning
    # ------------------------------------------------------------------
    def _on_space_press(self, event):
        if not self._space_held:
            self._space_held = True
            self.canvas.configure(cursor="fleur")

    def _on_space_release(self, event):
        self._space_held = False
        if not self._space_pan_dragging:
            self.canvas.configure(cursor="")

    def _start_space_pan(self, event):
        self._space_pan_dragging = True
        self.canvas.scan_mark(event.x, event.y)

    def _continue_space_pan(self, event):
        self.canvas.scan_dragto(event.x, event.y, gain=1)
        self._update_minimap()
        self._track_hover(event)

    def _end_space_pan(self):
        self._space_pan_dragging = False
        if not self._space_held:
            self.canvas.configure(cursor="")

    def _paint_at(self, event, mode):
        if self.target_image is None:
            return
        gx, gy = self._canvas_to_grid_coords(event)
        if not (0 <= gx < self.grid_w and 0 <= gy < self.grid_h):
            return

        if self.magic_pencil.get():
            # Magic pencil auto-detects the correct color for whatever you
            # click on, rather than requiring it to already be selected.
            auto_color = self.target_pixels[gx, gy]
            if auto_color != self.selected_color:
                self._select_color(auto_color)
            if mode == "fill":
                changed = self._magic_pencil_fill(gx, gy)
            else:
                changed = self._magic_pencil_single(gx, gy)
        elif mode == "fill":
            changed = self._flood_fill(gx, gy)
        else:
            changed = self._paint_single(gx, gy)

        if changed:
            # Most paint modes only ever touch cells wanting one specific
            # color per call, but a multi-cell brush in magic-pencil
            # single mode can span several different target colors at
            # once - so tally remaining-counts per color rather than
            # assuming they're all the same.
            color_counts = {}
            for (cx, cy) in changed:
                c = self.target_pixels[cx, cy]
                color_counts[c] = color_counts.get(c, 0) + 1
            for c, count in color_counts.items():
                self.color_remaining[c] = self.color_remaining.get(c, 0) - count
            self._update_cells(changed)
            self._update_progress()
            self._update_palette_progress(list(color_counts.keys()))

    def _brush_cells(self, cx, cy):
        """
        The set of in-bounds grid cells covered by the current brush size,
        centered on (cx, cy). Size 1 is just the clicked cell itself; for
        even sizes the extra row/column lands to the bottom-right, same as
        most paint programs' brush cursors.
        """
        size = self.brush_size.get()
        if size <= 1:
            return [(cx, cy)]
        half = size // 2
        start_x = cx - half
        start_y = cy - half
        cells = []
        for dy in range(size):
            for dx in range(size):
                gx, gy = start_x + dx, start_y + dy
                if 0 <= gx < self.grid_w and 0 <= gy < self.grid_h:
                    cells.append((gx, gy))
        return cells

    def _paint_single(self, x, y):
        changed = []
        for (gx, gy) in self._brush_cells(x, y):
            if self.target_pixels[gx, gy] != self.selected_color:
                continue  # wrong color for this cell - painting is disabled
            if (gx, gy) in self.painted:
                continue  # already correctly painted - nothing changed
            self.canvas_pixels[gx, gy] = self.selected_color
            self.painted.add((gx, gy))
            changed.append((gx, gy))
        return changed

    # 2.1.1.3 Fill mode: flood-fill every contiguous cell that wants the
    # same number as the one clicked, painting them all with the brush color.
    # Only fires if the brush color actually matches the clicked cell's number.
    def _flood_fill(self, x, y):
        target_color = self.target_pixels[x, y]
        if target_color != self.selected_color:
            return []  # wrong color selected for this region - do nothing
        if (x, y) in self.painted:
            return []  # this region's already done - skip re-flooding it

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

            visited.add((cx, cy))
            if (cx, cy) not in self.painted:
                self.canvas_pixels[cx, cy] = self.selected_color
                self.painted.add((cx, cy))
                changed.append((cx, cy))
            stack.extend([(cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)])
        return changed

    # 2.1.1.4 Magic pencil, single-pixel mode: auto-paints just the one
    # cell under the cursor with ITS OWN correct color as you click/drag,
    # no need to have that color pre-selected.
    def _magic_pencil_single(self, x, y):
        changed = []
        for (gx, gy) in self._brush_cells(x, y):
            if (gx, gy) in self.painted:
                continue
            target_color = self.target_pixels[gx, gy]
            self.canvas_pixels[gx, gy] = target_color
            self.painted.add((gx, gy))
            changed.append((gx, gy))
        return changed

    # 2.1.1.4 Magic pencil, fill mode: paints every cell (anywhere in the
    # image) that shares the clicked cell's number with ITS OWN correct
    # color, not just a contiguous region.
    def _magic_pencil_fill(self, x, y):
        target_color = self.target_pixels[x, y]
        changed = []
        for pos in self.color_to_positions.get(target_color, ()):
            if pos not in self.painted:
                self.canvas_pixels[pos] = target_color
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

    def get_numbered_template(self, cell_size=40):
        """
        A full-resolution, printable rendering of the blank numbered
        template (not the user's progress) - the thing you'd hand to a
        friend, along with the palette, so they can paint it by hand.
        """
        if self.target_image is None:
            return None
        return render_numbered_template(self.target_image, self.color_to_number, cell_size=cell_size)

    # ------------------------------------------------------------------
    # Save / load partially completed paintings
    # ------------------------------------------------------------------
    def has_painting(self):
        return self.target_image is not None

    def has_unsaved_progress(self):
        """True if there's a painting loaded with at least one cell painted
        but not yet finished - i.e. something meaningful would be lost by
        closing without saving. Used for the (opt-in) exit-save prompt;
        deliberately doesn't fire for an untouched or already-completed
        painting, since there'd be nothing worth nagging about either way."""
        if self.target_image is None:
            return False
        total = self.grid_w * self.grid_h
        done = len(self.painted)
        return 0 < done < total

    def save_project(self, path):
        """
        Save the current in-progress painting to a self-contained project
        file (a small zip under the hood) so it can be reopened later, or
        handed to someone else to continue on their own machine.

        Stored inside:
            meta.json   - grid size + a few UI preferences (brush size etc.)
            target.png  - the "answer key" grid (palette colors + numbers)
            canvas.png  - the user's painted result so far
            mask.png    - which cells are actually painted (white=painted),
                          since a painted cell's color could coincidentally
                          match the blank-white background otherwise.
        """
        if self.target_image is None:
            raise RuntimeError("There is no painting in progress to save yet.")

        mask = Image.new("L", (self.grid_w, self.grid_h), 0)
        mask_pixels = mask.load()
        for (gx, gy) in self.painted:
            mask_pixels[gx, gy] = 255

        meta = {
            "version": PROJECT_FORMAT_VERSION,
            "grid_w": self.grid_w,
            "grid_h": self.grid_h,
            "brush_size": self.brush_size.get(),
            "magic_pencil": bool(self.magic_pencil.get()),
            "selected_color": list(self.selected_color) if self.selected_color else None,
            "original_size": list(self.state_obj.original_image.size)
            if self.state_obj.original_image is not None else None,
        }

        target_buf = io.BytesIO()
        self.target_image.save(target_buf, "PNG")
        canvas_buf = io.BytesIO()
        self.canvas_image.save(canvas_buf, "PNG")
        mask_buf = io.BytesIO()
        mask.save(mask_buf, "PNG")

        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("meta.json", json.dumps(meta))
            zf.writestr("target.png", target_buf.getvalue())
            zf.writestr("canvas.png", canvas_buf.getvalue())
            zf.writestr("mask.png", mask_buf.getvalue())

    def load_project(self, path):
        """Reopen a project file saved by save_project() above."""
        self._cancel_flash()
        with zipfile.ZipFile(path, "r") as zf:
            meta = json.loads(zf.read("meta.json").decode("utf-8"))
            target = Image.open(io.BytesIO(zf.read("target.png"))).convert("RGB")
            canvas = Image.open(io.BytesIO(zf.read("canvas.png"))).convert("RGB")
            mask = Image.open(io.BytesIO(zf.read("mask.png"))).convert("L")

        self.target_image = target
        self.target_pixels = self.target_image.load()
        self.grid_w, self.grid_h = target.size

        self.canvas_image = canvas
        self.canvas_pixels = self.canvas_image.load()

        mask_pixels = mask.load()
        self.painted = set()
        for gy in range(self.grid_h):
            for gx in range(self.grid_w):
                if mask_pixels[gx, gy] >= 128:
                    self.painted.add((gx, gy))

        # Keep the shared app state's grid image in sync too, so other
        # tabs / actions (like "Save Image") that read from it still work
        # correctly against the reloaded project.
        self.state_obj.pixel_grid_image = self.target_image

        self._build_color_positions()
        self.color_remaining = {
            color: sum(1 for pos in positions if pos not in self.painted)
            for color, positions in self.color_to_positions.items()
        }

        if meta.get("brush_size") in BRUSH_SIZES:
            self.brush_size.set(meta["brush_size"])
        self.magic_pencil.set(bool(meta.get("magic_pencil", False)))

        self._build_palette()
        saved_color = meta.get("selected_color")
        if saved_color is not None:
            saved_color_t = tuple(saved_color)
            if saved_color_t in self.color_to_number:
                self.selected_color = saved_color_t
                self._update_swatch_highlight()
                self._update_selected_indicator()

        self._rebuild_full()
        self._update_progress()
        self._update_palette_progress()