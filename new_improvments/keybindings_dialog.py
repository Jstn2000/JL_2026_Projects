"""
keybindings_dialog.py

A small modal dialog (Project/Settings > Keyboard Shortcuts...) that lets
the user see and customize the keybindings defined in keybindings.py.

Each shortcut gets a "Press a key..." capture button: click it, then press
the key you want, and it's recorded immediately (no typing key names by
hand). Nothing is written to disk / re-applied to the running app until
"Save" is clicked - "Cancel" discards any in-progress changes.
"""

import tkinter as tk
from tkinter import ttk

from keybindings import ACTIONS
from theme import BG_PANEL, FG_MUTED, ACCENT

# Modifier-only keysyms - pressing just Shift/Ctrl/Alt on their own while
# "listening" for a shortcut isn't a usable binding, so we ignore these and
# keep waiting for the actual key instead of capturing a useless modifier.
_MODIFIER_KEYSYMS = {
    "Shift_L", "Shift_R", "Control_L", "Control_R",
    "Alt_L", "Alt_R", "Caps_Lock", "Num_Lock", "Super_L", "Super_R",
}


def open_keybindings_dialog(parent, keybindings, on_saved):
    """
    Show the dialog. `keybindings` is the app's live KeyBindings instance;
    `on_saved` is called with no arguments after the user clicks Save, so
    the caller can re-apply the new shortcuts to the running app.
    """
    dialog = tk.Toplevel(parent)
    dialog.title("Keyboard Shortcuts")
    dialog.configure(background=BG_PANEL)
    dialog.transient(parent)
    dialog.grab_set()
    dialog.resizable(False, False)

    # Work on a scratch copy so Cancel is a true no-op.
    pending = dict(keybindings.bindings)
    key_buttons = {}  # action -> button widget, so we can update its label

    container = ttk.Frame(dialog, padding=12)
    container.pack(fill=tk.BOTH, expand=True)

    ttk.Label(
        container,
        text="Click a shortcut, then press the key you want to use for it.",
        foreground=FG_MUTED,
    ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

    row = 1
    current_group = None
    for action, (default_key, label, group) in ACTIONS.items():
        if group != current_group:
            current_group = group
            ttk.Label(container, text=group, font=("TkDefaultFont", 10, "bold")).grid(
                row=row, column=0, columnspan=2, sticky="w", pady=(8, 2)
            )
            row += 1

        ttk.Label(container, text=label).grid(row=row, column=0, sticky="w", padx=(8, 20), pady=2)

        button = ttk.Button(container, text=pending.get(action, default_key), width=14)
        button.configure(command=lambda a=action, b=button: _start_listening(dialog, pending, a, b, key_buttons))
        button.grid(row=row, column=1, sticky="w", pady=2)
        key_buttons[action] = button
        row += 1

    button_row = ttk.Frame(container)
    button_row.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(14, 0))

    def do_reset():
        for action, (default_key, _label, _group) in ACTIONS.items():
            pending[action] = default_key
            key_buttons[action].configure(text=default_key)

    def do_save():
        for action, key in pending.items():
            keybindings.set(action, key)
        keybindings.save()
        dialog.destroy()
        on_saved()

    def do_cancel():
        dialog.destroy()

    ttk.Button(button_row, text="Reset to Defaults", command=do_reset).pack(side=tk.LEFT)
    ttk.Button(button_row, text="Cancel", command=do_cancel).pack(side=tk.RIGHT, padx=(6, 0))
    ttk.Button(button_row, text="Save", command=do_save).pack(side=tk.RIGHT)

    dialog.protocol("WM_DELETE_WINDOW", do_cancel)


def _start_listening(dialog, pending, action, button, key_buttons):
    """Put one button into "listening" mode and capture the next real key
    press anywhere in the dialog as this action's new shortcut."""
    button.configure(text="Press a key...")

    def on_key(event):
        if event.keysym in _MODIFIER_KEYSYMS:
            return  # a bare modifier isn't a usable shortcut - keep listening
        dialog.unbind("<KeyPress>")
        pending[action] = event.keysym
        button.configure(text=event.keysym)

    dialog.bind("<KeyPress>", on_key)
