"""
keybindings.py

Centralized, user-customizable keyboard shortcuts.

Bindings are stored as simple "action = key" pairs in a small property-file
(default: ~/.pixelpaint/keybindings.cfg), one per line, e.g.:

    goto_select_tab = 1
    goto_pixelate_tab = 2
    goto_paint_tab = 3
    pixelate_image = p
    toggle_help_mode = h
    select_confirm = Return
    select_move_up = Up
    select_move_down = Down
    select_move_left = Left
    select_move_right = Right

Key names are plain Tk "keysyms" - exactly what you'd write inside a Tk
bind() sequence like "<KeySym>" (lowercase letters for the plain key, e.g.
"p"; specials use their normal Tk names, e.g. "Return", "Escape", "F1").
This module only supports single-keysym shortcuts (no modifier combos like
"Control-s") to keep both the config file and the in-app editor simple -
that's enough for every shortcut PixelPaint currently exposes.

If the file doesn't exist yet, it's created from the defaults the first
time the app runs, so there's always something on disk to look at / edit
by hand, even for someone who never opens the in-app "Keyboard
Shortcuts..." dialog.
"""

import os

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".pixelpaint")
CONFIG_PATH = os.path.join(CONFIG_DIR, "keybindings.cfg")

# action_id -> (default key, human-readable label, group heading)
# Groups are just used to organize the customization dialog.
ACTIONS = {
    "goto_select_tab":   ("1",      "Go to \"1. Select Image\" tab",        "Navigation"),
    "goto_pixelate_tab": ("2",      "Go to \"2. Pixelate / Preview\" tab",  "Navigation"),
    "goto_paint_tab":    ("3",      "Go to \"3. Paint\" tab",               "Navigation"),
    "pixelate_image":    ("p",      "Pixelate the selected image",         "Actions"),
    "toggle_help_mode":  ("h",      "Flash hint for the selected color",   "Paint tab"),
    "select_confirm":    ("Return", "Confirm the highlighted image",       "Select tab"),
    "select_move_up":    ("Up",     "Move the image selection up",         "Select tab"),
    "select_move_down":  ("Down",   "Move the image selection down",       "Select tab"),
    "select_move_left":  ("Left",   "Move the image selection left",       "Select tab"),
    "select_move_right": ("Right",  "Move the image selection right",      "Select tab"),
}


def _defaults():
    return {action: spec[0] for action, spec in ACTIONS.items()}


class KeyBindings:
    """
    Loads/saves the user's keybinding overrides from the property file and
    hands out the current key for each action, falling back to the
    built-in default for anything missing, blank, or not yet set.
    """

    def __init__(self, path=CONFIG_PATH):
        self.path = path
        self.bindings = _defaults()
        self.load()

    def load(self):
        if not os.path.exists(self.path):
            self.save()  # first run - write the defaults out so there's something to edit
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    action, _, key = line.partition("=")
                    action = action.strip()
                    key = key.strip()
                    if action in ACTIONS and key:
                        self.bindings[action] = key
        except OSError:
            pass  # can't read it - just fall back to defaults silently

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        lines = [
            '# PixelPaint keybindings - one "action = key" pair per line.',
            "# Keys are Tk keysyms (e.g. Return, Escape, Up, F1, or a plain",
            "# letter/digit like p or 1). Delete a line (or the whole file)",
            "# to fall back to that shortcut's default.",
            "",
        ]
        for action in ACTIONS:
            lines.append(f"{action} = {self.bindings.get(action, ACTIONS[action][0])}")
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    def get(self, action):
        return self.bindings.get(action, ACTIONS[action][0])

    def set(self, action, key):
        if action in ACTIONS:
            self.bindings[action] = key

    def reset_to_defaults(self):
        self.bindings = _defaults()

    def sequence(self, action):
        """
        The key wrapped as a Tk bind() sequence. Deliberately uses the
        explicit "Key-" event-type prefix (e.g. '<Key-1>', '<Key-Return>')
        rather than the bare '<1>' shorthand - Tk reserves bare '<1>',
        '<2>', '<3>' for mouse buttons (Button-1/2/3), so a bare digit here
        would silently bind to mouse clicks instead of the digit key.
        """
        return f"<Key-{self.get(action)}>"
