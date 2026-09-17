"""
help_dialog.py

A simple, read-only "How to Use PixelPaint" reference window, opened from
the Help button in the top menu row. Holds the mouse/keyboard control
reminders that used to live as small-print labels directly in the Paint
tab's side panel, before that got too crowded to show everything at once.
"""

import tkinter as tk
from tkinter import ttk

from theme import BG_PANEL, BG_FIELD, FG_TEXT

HELP_TEXT = """PAINTING

Left-click: Fill (bucket) - paints the whole connected region that shares the clicked cell's color/number.

Right-click: Single pixel - paints just the cell(s) under the brush (see Brush size, below).

Magic pencil: auto-detects each cell's correct color as you click/drag, without needing it pre-selected. Left-click still fills, right-click still paints a single cell - just with whichever color is correct for it.

Brush size: only affects the single-pixel (right-click) tool - bucket fill already covers a whole connected region on its own.

Hint button (or its shortcut): flashes every uncolored cell of the currently selected color, so it's easy to spot where to paint next.

Clear painting: resets the canvas back to blank.


VIEW / NAVIGATION

Middle-click + drag: pan the canvas.
Middle-click (no drag): reset zoom back to the default.
Scroll wheel: pan vertically.
Ctrl + scroll wheel: zoom in/out.
Alt + scroll wheel: step the selected brush color through the palette.
WASD / Arrow keys: pan (once the canvas has focus - hover over or click it).
Fit to window: zoom out just enough to see the whole picture at once.

Rulers along the top/left of the canvas show the column and row of the pixel currently under your cursor - handy once you're zoomed in.


ELSEWHERE IN THE APP

Select Image tab: arrow keys move the highlighted image, Enter opens it.
Toolbar: Pixel size / Colors sliders and the Pixelate button (tab 2).
Settings menu: customize keyboard shortcuts, and toggle whether closing
the app with an unfinished painting asks you to save first.
"""


def open_help_dialog(parent):
    dialog = tk.Toplevel(parent)
    dialog.title("How to Use PixelPaint")
    dialog.configure(background=BG_PANEL)
    dialog.transient(parent)
    dialog.geometry("560x520")
    dialog.minsize(420, 300)

    container = ttk.Frame(dialog, padding=12)
    container.pack(fill=tk.BOTH, expand=True)

    text_frame = ttk.Frame(container)
    text_frame.pack(fill=tk.BOTH, expand=True)

    scroll = ttk.Scrollbar(text_frame, orient=tk.VERTICAL)
    text = tk.Text(
        text_frame, wrap="word",
        background=BG_FIELD, foreground=FG_TEXT, relief=tk.FLAT,
        borderwidth=0, padx=10, pady=10, yscrollcommand=scroll.set,
    )
    scroll.config(command=text.yview)
    text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scroll.pack(side=tk.RIGHT, fill=tk.Y)

    text.tag_configure("heading", font=("TkDefaultFont", 10, "bold"))
    for line in HELP_TEXT.split("\n"):
        if line.isupper() and line.strip():
            text.insert(tk.END, line + "\n", "heading")
        else:
            text.insert(tk.END, line + "\n")
    text.configure(state="disabled")

    ttk.Button(container, text="Close", command=dialog.destroy).pack(pady=(10, 0))