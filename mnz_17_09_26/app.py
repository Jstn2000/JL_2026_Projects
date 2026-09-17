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
from tkinter import ttk, filedialog, messagebox, simpledialog

from select_tab import SelectTab
from pixelate_tab import PixelateTab
from paint_tab import PaintTab
from theme import apply_dark_theme, tk_menu_colors, FG_MUTED
from keybindings import KeyBindings
from keybindings_dialog import open_keybindings_dialog
from help_dialog import open_help_dialog

# Bounds for the "Pixel size" slider.
MIN_PIXEL_SIZE = 1
MAX_PIXEL_SIZE = 50

# Bounds for the "Colors" slider. Capped at 64 because that's also the
# palette's own display cap (see get_palette_colors' max_colors) - going
# higher never showed more swatches anyway, it just risked an overloaded
# palette panel, so the slider simply can't ask for more than can be shown.
MIN_NUM_COLORS = 2
MAX_NUM_COLORS = 64

# Icons for the fullscreen/windowed toggle button - shows the icon for the
# action a click will perform (i.e. shows the "windowed" icon while
# fullscreen, since clicking switches TO windowed mode, and vice versa).
FULLSCREEN_ICON = "\u26F6"  # enter fullscreen
WINDOWED_ICON = "\u25A2"    # exit fullscreen / restore to a normal window


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

        self.pixel_size = tk.IntVar(value=4)
        self.num_colors = tk.IntVar(value=16)


class PixelPaintApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PixelPaint")
        self.geometry("1100x750")
        self.minsize(800, 600)

        # Start in fullscreen by default; Esc exits the application.
        try:
            self.attributes("-fullscreen", True)
            self._was_fullscreen = True
        except tk.TclError:
            self.state("zoomed")  # fallback for platforms without -fullscreen support
            self._was_fullscreen = False
        self.bind("<Map>", self._on_window_state_change)
        self.bind("<Escape>", lambda event: self.close_app())
        self.protocol("WM_DELETE_WINDOW", self.close_app)

        apply_dark_theme(self)

        self.state_obj = AppState()
        self.keybindings = KeyBindings()
        self._bound_root_seqs = {}  # action -> seq currently bound at the root, for clean re-binding

        # Off by default - some testers found an always-on "save before you
        # close?" prompt annoying, so it's opt-in via Settings > "Prompt to
        # save unsaved painting on exit".
        self.prompt_save_on_exit = tk.BooleanVar(value=False)

        self._build_menubar()
        self._build_toolbar()
        self._build_tabs()
        self._apply_keybindings()

        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

    # ------------------------------------------------------------------
    # 1.3.1 Menubar
    # ------------------------------------------------------------------
    def _build_menubar(self):
        # A custom row of ttk.Menubuttons instead of the native tk menu bar
        # (self.config(menu=...)) - the native one can't host extra widgets
        # alongside it, and the minimize/close buttons need to sit at this
        # same height rather than down in the toolbar.
        menu_colors = tk_menu_colors()
        bar = ttk.Frame(self, padding=(6, 3))
        bar.pack(side=tk.TOP, fill=tk.X)

        def add_menu(label):
            menu = tk.Menu(bar, tearoff=0, **menu_colors)
            ttk.Menubutton(bar, text=label, menu=menu).pack(side=tk.LEFT, padx=(0, 2))
            return menu

        file_menu = add_menu("File")
        file_menu.add_command(label="Open Directory...", command=self.choose_directory)   # 1.3.1.1
        file_menu.add_command(label="Save Image...", command=self.save_image)             # 1.3.1.4
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.close_app)                       # 1.3.1.2

        image_menu = add_menu("Image")
        image_menu.add_command(label="Pixelate", command=self.pixelate_current_image)     # 1.3.1.3

        project_menu = add_menu("Project")
        project_menu.add_command(label="Save Progress...", command=self.save_progress)
        project_menu.add_command(label="Load Progress...", command=self.load_progress)
        project_menu.add_separator()
        project_menu.add_command(label="Export Numbered Template...", command=self.export_numbered_template)

        settings_menu = add_menu("Settings")
        settings_menu.add_command(label="Keyboard Shortcuts...", command=self.open_keybindings_dialog)
        settings_menu.add_separator()
        settings_menu.add_checkbutton(
            label="Prompt to save unsaved painting on exit",
            variable=self.prompt_save_on_exit,
        )

        # A plain button rather than a dropdown menu - it's a single action
        # (open the reference window), not a list of choices. Holds the
        # mouse/keyboard control reminders that used to be small-print
        # labels cluttering the Paint tab's side panel.
        ttk.Button(bar, text="Help", command=lambda: open_help_dialog(self)).pack(side=tk.LEFT, padx=(6, 0))

        # Window controls, at the same height as the menu buttons above -
        # the app runs fullscreen by default, which hides the OS window
        # chrome (title bar, minimize/close buttons) entirely, so these are
        # an always-visible alternative to Esc. Packed close-first, since
        # side=RIGHT widgets stack inward from the edge in packing order -
        # that gives the on-screen left-to-right order [minimize][windowed][close].
        window_controls = ttk.Frame(bar)
        window_controls.pack(side=tk.RIGHT)
        ttk.Button(window_controls, text="\u2715", width=3, command=self.close_app).pack(side=tk.RIGHT, padx=(4, 0))
        self.fullscreen_button = ttk.Button(
            window_controls, text=WINDOWED_ICON if self._was_fullscreen else FULLSCREEN_ICON,
            width=3, command=self.toggle_fullscreen_mode,
        )
        self.fullscreen_button.pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(window_controls, text="\u2013", width=3, command=self.minimize_app).pack(side=tk.RIGHT)

    # ------------------------------------------------------------------
    # Toolbar: houses the pixel-size / color-count textfields since Tk
    # menus can't host Entry widgets directly (1.3.1.5 / 1.3.1.6)
    # ------------------------------------------------------------------
    def _build_toolbar(self):
        bar = ttk.Frame(self, padding=(8, 4))
        bar.pack(side=tk.TOP, fill=tk.X)

        ttk.Button(bar, text="Open Directory", command=self.choose_directory).pack(side=tk.LEFT, padx=4)

        ttk.Label(bar, text="Pixel size:").pack(side=tk.LEFT, padx=(16, 2))
        self.pixel_size_slider = ttk.Scale(
            bar,
            from_=MIN_PIXEL_SIZE,
            to=MAX_PIXEL_SIZE,
            orient=tk.HORIZONTAL,
            length=120,
            command=self._on_pixel_size_slider_change,
        )
        self.pixel_size_slider.pack(side=tk.LEFT, padx=(0, 4))

        # Scroll-wheel over the slider nudges the value by 1, same as Colors.
        self.pixel_size_slider.bind("<MouseWheel>", self._on_pixel_size_slider_wheel)  # Windows / macOS
        self.pixel_size_slider.bind("<Button-4>", self._on_pixel_size_slider_wheel)    # Linux scroll up
        self.pixel_size_slider.bind("<Button-5>", self._on_pixel_size_slider_wheel)    # Linux scroll down

        self.pixel_size_entry_var = tk.StringVar(value=str(self.state_obj.pixel_size.get()))
        digits_vcmd = (self.register(self._validate_digits_entry), "%P")
        self.pixel_size_entry = ttk.Entry(
            bar, textvariable=self.pixel_size_entry_var, width=4,
            validate="key", validatecommand=digits_vcmd,
        )
        self.pixel_size_entry.pack(side=tk.LEFT)
        self.pixel_size_entry.bind("<Return>", self._commit_pixel_size_entry)
        self.pixel_size_entry.bind("<FocusOut>", self._commit_pixel_size_entry)

        # Set the initial position last, now that _on_pixel_size_slider_change's
        # target widgets all exist (this fires the command immediately).
        self.pixel_size_slider.set(self.state_obj.pixel_size.get())

        ttk.Label(bar, text="Colors:").pack(side=tk.LEFT, padx=(16, 2))
        self.color_slider = ttk.Scale(
            bar,
            from_=MIN_NUM_COLORS,
            to=MAX_NUM_COLORS,
            orient=tk.HORIZONTAL,
            length=120,
            command=self._on_color_slider_change,
        )
        self.color_slider.pack(side=tk.LEFT, padx=(0, 4))

        # Scroll-wheel over the slider nudges the value by 1, so you don't
        # have to drag a tiny handle to dial in an exact number.
        self.color_slider.bind("<MouseWheel>", self._on_color_slider_wheel)   # Windows / macOS
        self.color_slider.bind("<Button-4>", self._on_color_slider_wheel)     # Linux scroll up
        self.color_slider.bind("<Button-5>", self._on_color_slider_wheel)     # Linux scroll down

        self.color_entry_var = tk.StringVar(value=str(self.state_obj.num_colors.get()))
        self.color_entry = ttk.Entry(
            bar, textvariable=self.color_entry_var, width=4,
            validate="key", validatecommand=digits_vcmd,
        )
        self.color_entry.pack(side=tk.LEFT)
        self.color_entry.bind("<Return>", self._commit_color_entry)
        self.color_entry.bind("<FocusOut>", self._commit_color_entry)

        # Set the initial position last, now that _on_color_slider_change's
        # target widgets all exist (this fires the command immediately).
        self.color_slider.set(self.state_obj.num_colors.get())

        ttk.Button(bar, text="Pixelate", command=self.pixelate_current_image).pack(side=tk.LEFT, padx=(16, 4))
        ttk.Button(bar, text="Save Image", command=self.save_image).pack(side=tk.LEFT, padx=4)
        ttk.Button(bar, text="Save Progress", command=self.save_progress).pack(side=tk.LEFT, padx=4)
        ttk.Button(bar, text="Load Progress", command=self.load_progress).pack(side=tk.LEFT, padx=4)

        self.dir_label = ttk.Label(bar, text="No directory selected", foreground=FG_MUTED)
        self.dir_label.pack(side=tk.RIGHT, padx=8)

    def minimize_app(self):
        # Some window managers won't minimize a window that still has the
        # fullscreen attribute set, so drop it first; it's reapplied when
        # the window is restored (see _on_window_state_change).
        try:
            self.attributes("-fullscreen", False)
        except tk.TclError:
            pass
        self.iconify()

    def _on_window_state_change(self, event):
        if self.state() == "normal" and self._was_fullscreen:
            try:
                self.attributes("-fullscreen", True)
            except tk.TclError:
                pass

    def toggle_fullscreen_mode(self):
        """The button between minimize and close - lets testers who don't
        want a fullscreen-only app switch to a normal, resizable window
        (and back)."""
        try:
            self.attributes("-fullscreen", not self._was_fullscreen)
        except tk.TclError:
            # -fullscreen isn't supported on this platform - fall back to
            # toggling maximized/normal instead (matches the startup fallback).
            self.state("normal" if self._was_fullscreen else "zoomed")
        self._was_fullscreen = not self._was_fullscreen
        self.fullscreen_button.config(text=WINDOWED_ICON if self._was_fullscreen else FULLSCREEN_ICON)

    # ------------------------------------------------------------------
    # 1.6.1 Tabs
    # ------------------------------------------------------------------
    def _build_tabs(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self.select_tab = SelectTab(
            self.notebook, self.state_obj, on_image_chosen=self._on_image_chosen, keybindings=self.keybindings
        )
        self.pixelate_tab = PixelateTab(self.notebook, self.state_obj)
        self.paint_tab = PaintTab(self.notebook, self.state_obj, keybindings=self.keybindings)

        self.notebook.add(self.select_tab, text="1. Select Image")
        self.notebook.add(self.pixelate_tab, text="2. Pixelate / Preview")
        self.notebook.add(self.paint_tab, text="3. Paint")

    # ------------------------------------------------------------------
    # 1.3.1.5 Pixel size slider (+ its editable textfield twin)
    # ------------------------------------------------------------------
    def _on_pixel_size_slider_change(self, value):
        n = int(round(float(value)))
        self.state_obj.pixel_size.set(n)
        self.pixel_size_entry_var.set(str(n))

    def _on_pixel_size_slider_wheel(self, event):
        if getattr(event, "num", None) in (4, 5):
            step = 1 if event.num == 4 else -1
        else:
            step = 1 if event.delta > 0 else -1
        new_value = min(MAX_PIXEL_SIZE, max(MIN_PIXEL_SIZE, self.state_obj.pixel_size.get() + step))
        self.pixel_size_slider.set(new_value)  # triggers _on_pixel_size_slider_change via its command
        return "break"

    def _commit_pixel_size_entry(self, event=None):
        """Read whatever's typed in the pixel-size field, clamp it to the
        slider's range, and push it back through the slider - which keeps
        the slider position, the IntVar, and the field itself all in sync
        from one place rather than three."""
        try:
            value = int(self.pixel_size_entry_var.get())
        except ValueError:
            value = self.state_obj.pixel_size.get()
        value = max(MIN_PIXEL_SIZE, min(MAX_PIXEL_SIZE, value))
        self.pixel_size_slider.set(value)

    # ------------------------------------------------------------------
    # 1.3.1.6 Colors slider (+ its editable textfield twin)
    # ------------------------------------------------------------------
    def _on_color_slider_change(self, value):
        n = int(round(float(value)))
        self.state_obj.num_colors.set(n)
        self.color_entry_var.set(str(n))

    def _on_color_slider_wheel(self, event):
        # Windows/macOS deliver <MouseWheel> with event.delta in multiples
        # of 120; Linux instead sends separate <Button-4> (up) / <Button-5>
        # (down) events with no delta - normalize both into a +-1 step.
        if getattr(event, "num", None) in (4, 5):
            step = 1 if event.num == 4 else -1
        else:
            step = 1 if event.delta > 0 else -1
        new_value = min(MAX_NUM_COLORS, max(MIN_NUM_COLORS, self.state_obj.num_colors.get() + step))
        self.color_slider.set(new_value)  # triggers _on_color_slider_change via its command
        return "break"

    def _commit_color_entry(self, event=None):
        try:
            value = int(self.color_entry_var.get())
        except ValueError:
            value = self.state_obj.num_colors.get()
        value = max(MIN_NUM_COLORS, min(MAX_NUM_COLORS, value))
        self.color_slider.set(value)

    @staticmethod
    def _validate_digits_entry(proposed):
        """Tk entry 'validate=key' callback for both textfields above -
        digits only, but an empty field is allowed too (so you can select
        all + delete before typing a new number)."""
        return proposed == "" or proposed.isdigit()

    # ------------------------------------------------------------------
    # Customizable keyboard shortcuts (tab switching + pixelate act app-wide,
    # so they're bound at the root window rather than any one tab's widget).
    # ------------------------------------------------------------------
    def _apply_keybindings(self):
        for seq in self._bound_root_seqs.values():
            self.unbind(seq)
        self._bound_root_seqs = {}

        bindings = {
            "goto_select_tab": lambda e: self.notebook.select(self.select_tab),
            "goto_pixelate_tab": lambda e: self.notebook.select(self.pixelate_tab),
            "goto_paint_tab": lambda e: self.notebook.select(self.paint_tab),
            "pixelate_image": lambda e: self.pixelate_current_image(),
        }
        for action, handler in bindings.items():
            seq = self.keybindings.sequence(action)
            self.bind(seq, self._skip_while_typing(handler))
            self._bound_root_seqs[action] = seq

        # Tab-specific shortcuts (arrow-key gallery nav, the hint flash)
        # live on those tabs' own widgets - just re-apply them here.
        self.select_tab.apply_keybindings()
        self.paint_tab.apply_keybindings()

    def _skip_while_typing(self, handler):
        """Wrap a root-level shortcut handler so it's a no-op while a text
        entry has keyboard focus - otherwise a shortcut like "1" (goto
        Select tab) would fire on every digit typed into the pixel-size /
        colors fields instead of letting the digit reach the field."""
        def wrapped(event):
            focused = self.focus_get()
            if isinstance(focused, (tk.Entry, ttk.Entry, tk.Text)):
                return None
            return handler(event)
        return wrapped

    def open_keybindings_dialog(self):
        open_keybindings_dialog(self, self.keybindings, on_saved=self._apply_keybindings)

    def _on_tab_changed(self, event):
        """Hand keyboard focus to whichever tab just became active, so its
        shortcuts (arrow-key gallery nav, WASD panning, hint flash, ...)
        work immediately without requiring a mouse hover first."""
        current = self.notebook.select()
        if current == str(self.select_tab):
            self.select_tab.focus_default()
        elif current == str(self.paint_tab):
            self.paint_tab.focus_default()

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

    def save_progress(self):
        """Returns True if a project file was actually written, so callers
        like close_app() can tell a real save apart from "no painting yet"
        or the user cancelling the file dialog."""
        if not self.paint_tab.has_painting():
            messagebox.showinfo("PixelPaint", "There is no painting in progress to save yet.")
            return False
        path = filedialog.asksaveasfilename(
            defaultextension=".ppzip",
            filetypes=[("PixelPaint project", "*.ppzip")],
            title="Save progress as...",
        )
        if not path:
            return False
        try:
            self.paint_tab.save_project(path)
        except Exception as e:
            messagebox.showerror("PixelPaint", f"Could not save progress:\n{e}")
            return False
        messagebox.showinfo("PixelPaint", f"Progress saved to:\n{path}")
        return True

    def load_progress(self):
        path = filedialog.askopenfilename(
            filetypes=[("PixelPaint project", "*.ppzip"), ("All files", "*.*")],
            title="Load progress...",
        )
        if not path:
            return
        try:
            self.paint_tab.load_project(path)
        except Exception as e:
            messagebox.showerror("PixelPaint", f"Could not load progress:\n{e}")
            return
        self.notebook.select(self.paint_tab)

    def export_numbered_template(self):
        if not self.paint_tab.has_painting():
            messagebox.showinfo("PixelPaint", "Please pixelate an image first (tab 2) before exporting a template.")
            return
        cell_size = simpledialog.askinteger(
            "Export Numbered Template",
            "Cell size in pixels (bigger = larger, more printable file):",
            initialvalue=40,
            minvalue=10,
            maxvalue=200,
            parent=self,
        )
        if not cell_size:
            return
        image = self.paint_tab.get_numbered_template(cell_size=cell_size)
        if image is None:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG image", "*.png")],
            title="Export numbered template as...",
        )
        if not path:
            return
        image.save(path, "PNG")
        messagebox.showinfo("PixelPaint", f"Saved numbered template to:\n{path}")

    def close_app(self):
        if self.prompt_save_on_exit.get() and self.paint_tab.has_unsaved_progress():
            response = messagebox.askyesnocancel(
                "PixelPaint",
                "You have an unfinished painting that hasn't been saved.\n\n"
                "Save your progress before closing?",
            )
            if response is None:
                return  # Cancel - leave the app open
            if response and not self.save_progress():
                return  # chose Yes, but the save was cancelled/failed - stay open
        self.destroy()


def main():
    app = PixelPaintApp()
    app.mainloop()


if __name__ == "__main__":
    main()