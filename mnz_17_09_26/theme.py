"""
theme.py

A small, centralized dark-mode color palette + the ttk.Style setup that
applies it, shared by every tab. ttk widgets (Frame, Label, Button, Scale,
Notebook, ...) pick up their look from the ttk.Style configured here, but
plain tk widgets (Canvas, Menu, Label-used-as-image-holder) don't participate
in ttk styling at all - those are colored by hand in each tab using the same
constants imported from this module, so everything actually matches.
"""

from tkinter import ttk

BG_DARK = "#1e1e1e"    # outermost window background, big image-preview canvases
BG_PANEL = "#2b2b2b"   # frames / side panels / toolbar
BG_FIELD = "#3c3c3c"   # entries, sliders, buttons, scrollbars, canvas swatches
FG_TEXT = "#e6e6e6"    # primary text
FG_MUTED = "#9a9a9a"   # secondary / hint text (replaces the old light-mode "#666"/"#888")
ACCENT = "#4a90d9"     # selection / active highlight


def apply_dark_theme(root):
    """
    Configure ttk's styling engine for dark mode and darken the root window
    itself. Must be called once, early - before building the widgets that
    should pick up these styles.
    """
    root.configure(background=BG_DARK)

    style = ttk.Style(root)
    # 'clam' is the most stylable of Tk's built-in themes on every platform;
    # the default/native themes largely ignore custom colors.
    style.theme_use("clam")

    style.configure(
        ".",
        background=BG_PANEL,
        foreground=FG_TEXT,
        fieldbackground=BG_FIELD,
        troughcolor=BG_FIELD,
        bordercolor=BG_FIELD,
        lightcolor=BG_PANEL,
        darkcolor=BG_PANEL,
    )

    style.configure("TFrame", background=BG_PANEL)
    style.configure("TLabel", background=BG_PANEL, foreground=FG_TEXT)

    style.configure("TButton", background=BG_FIELD, foreground=FG_TEXT, bordercolor=BG_FIELD)
    style.map(
        "TButton",
        background=[("active", ACCENT), ("pressed", ACCENT)],
        foreground=[("active", "#ffffff"), ("pressed", "#ffffff")],
    )

    style.configure(
        "TMenubutton", background=BG_PANEL, foreground=FG_TEXT, bordercolor=BG_PANEL,
        arrowcolor=FG_TEXT, relief="flat",
    )
    style.map(
        "TMenubutton",
        background=[("active", ACCENT)],
        foreground=[("active", "#ffffff")],
    )

    style.configure("TCheckbutton", background=BG_PANEL, foreground=FG_TEXT)
    style.map("TCheckbutton", background=[("active", BG_PANEL)])

    style.configure("TEntry", fieldbackground=BG_FIELD, foreground=FG_TEXT, insertcolor=FG_TEXT)

    style.configure("TScale", background=BG_PANEL, troughcolor=BG_FIELD)

    style.configure("TSeparator", background=BG_FIELD)

    style.configure("TNotebook", background=BG_PANEL, bordercolor=BG_PANEL)
    style.configure("TNotebook.Tab", background=BG_FIELD, foreground=FG_TEXT, padding=(10, 4))
    style.map(
        "TNotebook.Tab",
        background=[("selected", ACCENT)],
        foreground=[("selected", "#ffffff")],
    )

    style.configure(
        "TLabelframe", background=BG_PANEL, foreground=FG_TEXT, bordercolor=BG_FIELD
    )
    style.configure("TLabelframe.Label", background=BG_PANEL, foreground=FG_TEXT)

    style.configure(
        "TScrollbar", background=BG_FIELD, troughcolor=BG_PANEL, arrowcolor=FG_TEXT, bordercolor=BG_PANEL
    )

    return style


def tk_menu_colors():
    """Color kwargs for plain tk.Menu widgets, which don't use ttk styling.
    (Note: on macOS the native menu bar ignores these colors - an OS
    limitation outside the app's control.)"""
    return dict(
        background=BG_PANEL,
        foreground=FG_TEXT,
        activebackground=ACCENT,
        activeforeground="#ffffff",
    )