"""
pixelate_tab.py

1.4 Show a preview of the image to the user.
    1.4.1 Preview screen
    1.4.2 Pixelate the image using PIL (see image_utils.pixelate_image)
"""

import tkinter as tk
from tkinter import ttk

from PIL import ImageTk

from image_utils import pixelate_image, compute_pixel_grid
from theme import BG_DARK, FG_MUTED

PREVIEW_MAX = (480, 480)


class PixelateTab(ttk.Frame):
    def __init__(self, parent, state_obj):
        super().__init__(parent)
        self.state_obj = state_obj
        self._original_photo = None
        self._pixelated_photo = None
        self._build_ui()

    def _build_ui(self):
        container = ttk.Frame(self, padding=10)
        container.pack(fill=tk.BOTH, expand=True)

        left = ttk.LabelFrame(container, text="Original")
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=8)
        self.original_canvas = tk.Label(left, background=BG_DARK)
        self.original_canvas.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        right = ttk.LabelFrame(container, text="Pixelated preview")
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=8)
        self.pixel_canvas = tk.Label(right, background=BG_DARK)
        self.pixel_canvas.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        hint = ttk.Label(
            self,
            text="Set pixel size / colors in the toolbar above, then click 'Pixelate'.",
            foreground=FG_MUTED,
        )
        hint.pack(side=tk.BOTTOM, pady=6)

    def _to_photo(self, image):
        preview = image.copy()
        preview.thumbnail(PREVIEW_MAX, resample=1)  # 1 = NEAREST, keeps pixel-art crisp
        return ImageTk.PhotoImage(preview)

    def show_original(self):
        image = self.state_obj.original_image
        if image is None:
            return
        self._original_photo = self._to_photo(image)
        self.original_canvas.configure(image=self._original_photo)
        self.pixel_canvas.configure(image="")

    def pixelate(self, pixel_size, num_colors):
        image = self.state_obj.original_image
        if image is None:
            return
        grid = compute_pixel_grid(image, pixel_size, num_colors)
        result = grid.resize(image.size, resample=0)  # 0 = NEAREST
        self.state_obj.pixel_grid_image = grid
        self.state_obj.pixelated_image = result

        self._pixelated_photo = self._to_photo(result)
        self.pixel_canvas.configure(image=self._pixelated_photo)