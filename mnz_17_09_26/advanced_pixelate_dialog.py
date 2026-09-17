"""
advanced_pixelate_dialog.py

The "Advanced Pixelate..." dialog: extra color-adjustment controls
(brightness / contrast / saturation / grayscale / black & white / invert /
dithering) that sit alongside the existing Pixel size and Colors sliders,
for anyone who wants more control than "how many colors" - e.g. a
genuinely black-and-white result, or extra contrast/punch before
quantizing.

Every control is bound directly to the shared AppState variables (the same
ones the toolbar's Pixelate button already reads), so changes apply the
next time anything pixelates - no separate "confirm" step is required.
There's still an "Apply & Pixelate" button for convenience, plus a live
preview (built from the same compute_pixel_grid() pipeline used for the
real thing) so the effect is visible before committing to a full pixelate.
"""

import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageTk

from image_utils import AdjustmentOptions, apply_color_adjustments, compute_pixel_grid
from theme import BG_DARK, BG_PANEL, FG_MUTED

PREVIEW_SIZE = (220, 220)
PREVIEW_DEBOUNCE_MS = 120

DEFAULTS = AdjustmentOptions()  # a fresh, all-defaults instance to reset against


def _format_value(value, integer):
    return str(value) if integer else f"{value:.2f}"


def _read_options(state_obj):
    return AdjustmentOptions(
        brightness=state_obj.brightness.get(),
        contrast=state_obj.contrast.get(),
        saturation=state_obj.saturation.get(),
        grayscale=state_obj.grayscale.get(),
        invert=state_obj.invert.get(),
        black_and_white=state_obj.black_and_white.get(),
        bw_threshold=state_obj.bw_threshold.get(),
        dither=state_obj.dither.get(),
    )


def open_advanced_pixelate_dialog(parent, state_obj, on_apply):
    dialog = tk.Toplevel(parent)
    dialog.title("Advanced Pixelate Options")
    dialog.configure(background=BG_PANEL)
    dialog.transient(parent)
    dialog.resizable(False, False)

    root = ttk.Frame(dialog, padding=12)
    root.pack(fill=tk.BOTH, expand=True)

    # ---------------------------------------------------------------
    # Live preview
    # ---------------------------------------------------------------
    preview_frame = ttk.LabelFrame(root, text="Preview")
    preview_frame.pack(side=tk.LEFT, padx=(0, 16), anchor="n")
    preview_label = tk.Label(preview_frame, background=BG_DARK, width=PREVIEW_SIZE[0], height=PREVIEW_SIZE[1])
    preview_label.pack(padx=8, pady=8)
    preview_state = {"photo": None, "after_id": None}

    preview_source = None
    scale_ratio = 1.0
    if state_obj.original_image is not None:
        original_w, original_h = state_obj.original_image.size
        preview_source = state_obj.original_image.copy()
        preview_source.thumbnail(PREVIEW_SIZE, Image.LANCZOS)
        scale_ratio = preview_source.width / max(1, original_w)
    else:
        ttk.Label(
            preview_frame, text="Choose an image first\nto see a live preview.",
            foreground=FG_MUTED, justify=tk.CENTER, background=BG_PANEL,
        ).pack(padx=8, pady=(0, 8))

    def refresh_preview():
        preview_state["after_id"] = None
        if preview_source is None:
            return
        opts = _read_options(state_obj)
        # Scale the chosen pixel size down to match the shrunk preview, so
        # the block size looks roughly proportional to the real thing -
        # very small at low zoom is expected/fine, this is about the color
        # adjustments, not exact block dimensions.
        pixel_size = max(1, round(state_obj.pixel_size.get() * scale_ratio))
        num_colors = max(1, state_obj.num_colors.get())
        grid = compute_pixel_grid(preview_source, pixel_size, num_colors, opts)
        big = grid.resize(preview_source.size, resample=Image.NEAREST)
        photo = ImageTk.PhotoImage(big)
        preview_state["photo"] = photo  # keep a reference alive
        preview_label.configure(image=photo)

    def schedule_preview():
        if preview_state["after_id"] is not None:
            dialog.after_cancel(preview_state["after_id"])
        preview_state["after_id"] = dialog.after(PREVIEW_DEBOUNCE_MS, refresh_preview)

    # ---------------------------------------------------------------
    # Controls
    # ---------------------------------------------------------------
    controls = ttk.Frame(root)
    controls.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    slider_labels = []  # (label_widget, var, integer) - refreshed on Reset

    def add_slider(label_text, var, frm, to, integer=False):
        frame = ttk.Frame(controls)
        frame.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(frame, text=label_text).pack(side=tk.LEFT)
        value_label = ttk.Label(frame, text=_format_value(var.get(), integer), foreground=FG_MUTED, width=5)
        value_label.pack(side=tk.RIGHT)

        def on_change(v):
            value = int(round(float(v))) if integer else round(float(v), 2)
            var.set(value)
            value_label.config(text=_format_value(value, integer))
            schedule_preview()

        scale = ttk.Scale(controls, variable=var, from_=frm, to=to, orient=tk.HORIZONTAL, command=on_change)
        scale.pack(fill=tk.X, pady=(0, 2))
        slider_labels.append((value_label, var, integer))
        return scale

    ttk.Label(controls, text="Color Adjustments", font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
    add_slider("Brightness", state_obj.brightness, 0.2, 2.0)
    add_slider("Contrast", state_obj.contrast, 0.2, 2.0)
    saturation_slider = add_slider("Saturation", state_obj.saturation, 0.0, 2.0)

    ttk.Separator(controls, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)

    def update_control_states():
        bw_on = state_obj.black_and_white.get()
        gray_on = state_obj.grayscale.get()
        saturation_slider.state(["disabled"] if (bw_on or gray_on) else ["!disabled"])
        bw_threshold_slider.state(["!disabled"] if bw_on else ["disabled"])

    def on_grayscale_toggle():
        if state_obj.grayscale.get():
            state_obj.black_and_white.set(False)
        update_control_states()
        schedule_preview()

    def on_bw_toggle():
        if state_obj.black_and_white.get():
            state_obj.grayscale.set(False)
        update_control_states()
        schedule_preview()

    ttk.Checkbutton(
        controls, text="Grayscale", variable=state_obj.grayscale, command=on_grayscale_toggle
    ).pack(anchor="w")
    ttk.Checkbutton(
        controls, text="Black & white only (no gray)", variable=state_obj.black_and_white, command=on_bw_toggle
    ).pack(anchor="w", pady=(2, 0))
    bw_threshold_slider = add_slider("B&W threshold", state_obj.bw_threshold, 0, 255, integer=True)

    ttk.Separator(controls, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)

    ttk.Checkbutton(
        controls, text="Invert colors", variable=state_obj.invert, command=schedule_preview
    ).pack(anchor="w")
    ttk.Checkbutton(
        controls, text="Smooth color transitions (dithering)", variable=state_obj.dither, command=schedule_preview
    ).pack(anchor="w", pady=(2, 0))

    update_control_states()

    # ---------------------------------------------------------------
    # Buttons
    # ---------------------------------------------------------------
    button_row = ttk.Frame(controls)
    button_row.pack(fill=tk.X, pady=(16, 0))

    def do_reset():
        state_obj.brightness.set(DEFAULTS.brightness)
        state_obj.contrast.set(DEFAULTS.contrast)
        state_obj.saturation.set(DEFAULTS.saturation)
        state_obj.grayscale.set(DEFAULTS.grayscale)
        state_obj.black_and_white.set(DEFAULTS.black_and_white)
        state_obj.bw_threshold.set(DEFAULTS.bw_threshold)
        state_obj.invert.set(DEFAULTS.invert)
        state_obj.dither.set(DEFAULTS.dither)
        for label_widget, var, integer in slider_labels:
            label_widget.config(text=_format_value(var.get(), integer))
        update_control_states()
        schedule_preview()

    def do_apply():
        dialog.destroy()
        on_apply()

    ttk.Button(button_row, text="Reset to Defaults", command=do_reset).pack(side=tk.LEFT)
    ttk.Button(button_row, text="Close", command=dialog.destroy).pack(side=tk.RIGHT)
    ttk.Button(button_row, text="Apply & Pixelate", command=do_apply).pack(side=tk.RIGHT, padx=(0, 6))

    schedule_preview()