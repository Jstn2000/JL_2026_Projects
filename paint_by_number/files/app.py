"""
app.py

Main application window.
    1.3.1 Menubar (+ toolbar for text-entry controls, since native tk menus
          cannot embed Entry widgets):
        1.3.1.1 Directory selection
        1.3.1.2 Close application
        1.3.1.3 Pixelate the image
        1.3.1.4 Save the image
        1.3.1.5 Pixel size textfield
        1.3.1.6 Number of colors textfield
    1.6.1 Tab system to swap between image choice / pixelate / paint screens
"""

import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from select_tab import SelectTab
from pixelate_tab import PixelateTab
from paint_tab import PaintTab


class AppState:
    """Shared state passed around between tabs."""

    def __init__(self):
        self.directory = None
        self.png_images = {}          # title -> png path
        self.selected_title = None
        self.selected_path = None

        self.original_image = None    # PIL Image, full res, RGB
        self.pixelated_image = None   # PIL Image after pixelate step (full res preview)
        self.pixel_grid_image = None  # small PIL Image, one pixel per paintable block

        self.pixel_size = tk.IntVar(value=10)
        self.num_colors = tk.IntVar(value=8)


class PixelPaintApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PixelPaint")
        self.geometry("1100x750")
        self.minsize(800, 600)

        # Start in fullscreen by default; Esc exits the application.
        try:
            self.attributes("-fullscreen", True)
        except tk.TclError:
            self.state("zoomed")  # fallback for platforms without -fullscreen support
        self.bind("<Escape>", lambda event: self.close_app())

        self.state_obj = AppState()

        self._build_menubar()
        self._build_toolbar()
        self._build_tabs()

    # ------------------------------------------------------------------
    # 1.3.1 Menubar
    # ------------------------------------------------------------------
    def _build_menubar(self):
        menubar = tk.Menu(self)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open Directory...", command=self.choose_directory)   # 1.3.1.1
        file_menu.add_command(label="Save Image...", command=self.save_image)             # 1.3.1.4
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.close_app)                       # 1.3.1.2
        menubar.add_cascade(label="File", menu=file_menu)

        image_menu = tk.Menu(menubar, tearoff=0)
        image_menu.add_command(label="Pixelate", command=self.pixelate_current_image)     # 1.3.1.3
        menubar.add_cascade(label="Image", menu=image_menu)

        self.config(menu=menubar)

    # ------------------------------------------------------------------
    # Toolbar: houses the pixel-size / color-count textfields since Tk
    # menus can't host Entry widgets directly (1.3.1.5 / 1.3.1.6)
    # ------------------------------------------------------------------
    def _build_toolbar(self):
        bar = ttk.Frame(self, padding=(8, 4))
        bar.pack(side=tk.TOP, fill=tk.X)

        ttk.Button(bar, text="Open Directory", command=self.choose_directory).pack(side=tk.LEFT, padx=4)

        ttk.Label(bar, text="Pixel size:").pack(side=tk.LEFT, padx=(16, 2))
        pixel_entry = ttk.Entry(bar, width=5, textvariable=self.state_obj.pixel_size)
        pixel_entry.pack(side=tk.LEFT)

        ttk.Label(bar, text="Colors:").pack(side=tk.LEFT, padx=(16, 2))
        color_entry = ttk.Entry(bar, width=5, textvariable=self.state_obj.num_colors)
        color_entry.pack(side=tk.LEFT)

        ttk.Button(bar, text="Pixelate", command=self.pixelate_current_image).pack(side=tk.LEFT, padx=(16, 4))
        ttk.Button(bar, text="Save Image", command=self.save_image).pack(side=tk.LEFT, padx=4)

        self.dir_label = ttk.Label(bar, text="No directory selected", foreground="#666")
        self.dir_label.pack(side=tk.RIGHT, padx=8)

    # ------------------------------------------------------------------
    # 1.6.1 Tabs
    # ------------------------------------------------------------------
    def _build_tabs(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self.select_tab = SelectTab(self.notebook, self.state_obj, on_image_chosen=self._on_image_chosen)
        self.pixelate_tab = PixelateTab(self.notebook, self.state_obj)
        self.paint_tab = PaintTab(self.notebook, self.state_obj)

        self.notebook.add(self.select_tab, text="1. Select Image")
        self.notebook.add(self.pixelate_tab, text="2. Pixelate / Preview")
        self.notebook.add(self.paint_tab, text="3. Paint")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def choose_directory(self):
        directory = filedialog.askdirectory(title="Choose a directory of images")
        if not directory:
            return
        self.state_obj.directory = directory
        self.dir_label.config(text=directory)
        self.select_tab.load_directory(directory)
        self.notebook.select(self.select_tab)

    def _on_image_chosen(self, title, path):
        self.state_obj.selected_title = title
        from PIL import Image
        from image_utils import ensure_png

        # Lazily convert just this one image to PNG (fast - only happens
        # for the image the user actually picked, not the whole folder).
        try:
            png_path = ensure_png(path, self.state_obj.directory)
        except Exception:
            png_path = path  # fall back to opening the original directly

        self.state_obj.selected_path = png_path
        self.state_obj.original_image = Image.open(png_path).convert("RGB")
        self.pixelate_tab.show_original()
        self.notebook.select(self.pixelate_tab)

    def pixelate_current_image(self):
        if self.state_obj.original_image is None:
            messagebox.showinfo("PixelPaint", "Please choose an image first (tab 1).")
            return
        try:
            pixel_size = int(self.state_obj.pixel_size.get())
            num_colors = int(self.state_obj.num_colors.get())
            if pixel_size < 1 or num_colors < 1:
                raise ValueError
        except (tk.TclError, ValueError):
            messagebox.showerror("PixelPaint", "Pixel size and colors must be positive whole numbers.")
            return

        self.pixelate_tab.pixelate(pixel_size, num_colors)
        self.paint_tab.load_pixelated_image()
        self.notebook.select(self.pixelate_tab)

    def save_image(self):
        image = self.paint_tab.get_full_size_image() or self.state_obj.pixelated_image
        if image is None:
            messagebox.showinfo("PixelPaint", "There is no image to save yet.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG image", "*.png")],
            title="Save image as...",
        )
        if not path:
            return
        image.save(path, "PNG")
        messagebox.showinfo("PixelPaint", f"Saved to:\n{path}")

    def close_app(self):
        self.destroy()


def main():
    app = PixelPaintApp()
    app.mainloop()


if __name__ == "__main__":
    main()