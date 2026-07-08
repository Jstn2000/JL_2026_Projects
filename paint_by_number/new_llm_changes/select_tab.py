"""
select_tab.py

1.2 Choose an image from the directory to process.
    1.2.1 Preselection UI
        1.2.1.1 A list of all image options with a preview + title beneath
        1.2.1.2 Click, mouse-scroll, or Shift+scroll to choose an image

Thumbnail loading is done on a background thread and streamed into the UI
incrementally so that large directories don't freeze or crash the app:
    - scanning + thumbnail decoding happens off the main thread
    - decoded thumbnails (small PIL Images) are pushed onto a queue and
      drained a few at a time via `after()`, so the UI stays responsive
    - a single unreadable/corrupt file is skipped instead of aborting
      the whole load

Gallery rendering is VIRTUALIZED: with directories of hundreds or
thousands of images, creating a permanent Tk widget + PhotoImage per
thumbnail eventually exhausts the display server's image resources -
thumbnails silently stop appearing partway through, which looks just
like "some images are missing". Instead, only the thumbnails currently
scrolled into view (plus a small buffer) ever exist as live canvas
items; everything else is just a decoded PIL Image sitting in memory,
cheap to redraw the moment it scrolls back into view. This also means
there's no need to artificially cap how many images get decoded up
front ("Load more" is gone - decoding just keeps going in the
background until the whole directory is done).

The gallery also lays itself out in as many columns as actually fit the
current canvas width (recomputed on resize), instead of a hardcoded
column count that only ever used the left part of the window.
"""

import os
import queue
import threading
import tkinter as tk
from tkinter import ttk

from PIL import ImageTk

from image_utils import scan_directory_for_images, make_thumbnail
from theme import BG_DARK, FG_TEXT, FG_MUTED, ACCENT

THUMB_SIZE = (140, 140)
DECODE_CHUNK = 150       # how many thumbnails a background thread decodes per chunk
QUEUE_POLL_MS = 30       # how often we drain the background queue into the UI
QUEUE_DRAIN_PER_TICK = 12

CARD_PAD = 10
TITLE_AREA_H = 46
CELL_W = THUMB_SIZE[0] + 2 * CARD_PAD
CELL_H = THUMB_SIZE[1] + TITLE_AREA_H + 2 * CARD_PAD
BUFFER_ROWS = 3          # extra rows rendered above/below the visible viewport
SELECTION_COLOR = ACCENT


class SelectTab(ttk.Frame):
    def __init__(self, parent, state_obj, on_image_chosen):
        super().__init__(parent)
        self.state_obj = state_obj
        self.on_image_chosen = on_image_chosen

        self.titles = []          # ordered list of image titles actually shown
        self.paths = []           # ordered list of matching source paths
        self.thumb_images = []    # ordered list of decoded PIL thumbnails (index-aligned)
        self.current_index = -1

        self._all_paths = []           # every image path found in the directory
        self._next_unloaded_index = 0  # cursor into _all_paths for chunked decoding
        self._load_generation = 0      # bumped whenever a new directory load starts,
                                        # lets us ignore stale background results
        self._thumb_queue = queue.Queue()
        self._loader_thread = None

        # Virtualized-gallery layout state
        self.columns = 1
        self._effective_col_w = CELL_W
        self._total_rows = 0
        self._rendered = {}   # index -> {"rect", "image", "text", "photo"}

        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self):
        top = ttk.Frame(self, padding=8)
        top.pack(side=tk.TOP, fill=tk.X)

        ttk.Label(top, text="Select an image:").pack(side=tk.LEFT)

        self.hint_label = ttk.Label(top, text="(Use File > Open Directory to load images)", foreground=FG_MUTED)
        self.hint_label.pack(side=tk.LEFT, padx=10)

        self.selection_label = ttk.Label(top, text="No image selected")
        self.selection_label.pack(side=tk.RIGHT, padx=(10, 0))

        self.progress_label = ttk.Label(top, text="", foreground=FG_MUTED)
        self.progress_label.pack(side=tk.RIGHT)

        # Scrollable thumbnail gallery, drawn directly on the canvas -----
        gallery_container = ttk.Frame(self)
        gallery_container.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8, pady=8)

        self.canvas = tk.Canvas(gallery_container, borderwidth=0, highlightthickness=0, background=BG_DARK)
        v_scroll = ttk.Scrollbar(gallery_container, orient=tk.VERTICAL, command=self._on_vscroll)
        self.canvas.configure(yscrollcommand=v_scroll.set)

        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.canvas.bind("<Button-1>", self._on_canvas_click)

        # Mouse wheel over the gallery scrolls the view.
        self.canvas.bind("<Enter>", self._bind_wheel)
        self.canvas.bind("<Leave>", self._unbind_wheel)
        # Linux mouse wheel events (no <MouseWheel>/delta there)
        self.canvas.bind("<Button-4>", lambda e: self._scroll_units(-1))
        self.canvas.bind("<Button-5>", lambda e: self._scroll_units(1))
        # 1.2.1.2 Shift+wheel steps through images one at a time (quick "choice" scroll)
        self.canvas.bind("<Shift-Button-4>", lambda e: self._step_selection(-1))
        self.canvas.bind("<Shift-Button-5>", lambda e: self._step_selection(1))

    # ------------------------------------------------------------------
    # Layout / virtualization
    # ------------------------------------------------------------------
    def _on_canvas_resize(self, event):
        self._reflow_layout()

    def _reflow_layout(self):
        canvas_w = max(1, self.canvas.winfo_width())
        new_columns = max(1, canvas_w // CELL_W)
        columns_changed = new_columns != self.columns
        self.columns = new_columns
        self._effective_col_w = canvas_w / self.columns  # stretch columns to fill full width

        if columns_changed:
            self._clear_all_rendered()

        self._update_scrollregion()
        self._refresh_visible()

    def _update_scrollregion(self):
        canvas_w = max(1, self.canvas.winfo_width())
        canvas_h = max(1, self.canvas.winfo_height())
        total_items = len(self.titles)
        self._total_rows = (total_items + self.columns - 1) // self.columns if total_items else 0
        total_h = self._total_rows * CELL_H
        self.canvas.configure(scrollregion=(0, 0, canvas_w, max(total_h, canvas_h)))

    def _clear_all_rendered(self):
        for ids in self._rendered.values():
            self.canvas.delete(ids["rect"], ids["image"], ids["text"])
        self._rendered.clear()

    def _visible_range(self):
        if self.columns <= 0 or self._total_rows <= 0:
            return 0, 0
        total_h = self._total_rows * CELL_H
        if total_h <= 0:
            return 0, 0
        y0f, y1f = self.canvas.yview()
        top_px = y0f * total_h
        bottom_px = y1f * total_h
        first_row = max(0, int(top_px // CELL_H) - BUFFER_ROWS)
        last_row = min(self._total_rows - 1, int(bottom_px // CELL_H) + BUFFER_ROWS)
        start = first_row * self.columns
        end = min(len(self.titles), (last_row + 1) * self.columns)
        return start, end

    def _refresh_visible(self):
        if not self.titles:
            self._clear_all_rendered()
            return

        start, end = self._visible_range()
        wanted = set(range(start, end))

        for idx in list(self._rendered.keys()):
            if idx not in wanted:
                ids = self._rendered.pop(idx)
                self.canvas.delete(ids["rect"], ids["image"], ids["text"])

        for idx in wanted:
            if idx not in self._rendered and idx < len(self.thumb_images):
                self._render_card(idx)

    def _render_card(self, idx):
        row = idx // self.columns
        col = idx % self.columns
        cx = col * self._effective_col_w + self._effective_col_w / 2
        top_y = row * CELL_H

        photo = ImageTk.PhotoImage(self.thumb_images[idx])
        img_y = top_y + CARD_PAD + THUMB_SIZE[1] / 2
        image_id = self.canvas.create_image(cx, img_y, image=photo, anchor="center")

        text_y = top_y + CARD_PAD + THUMB_SIZE[1] + 6
        text_id = self.canvas.create_text(
            cx, text_y, text=self.titles[idx], width=THUMB_SIZE[0] + 20, anchor="n", fill=FG_TEXT
        )

        rect_w = THUMB_SIZE[0] + 2 * CARD_PAD
        rect_h = CELL_H - 6
        rect_id = self.canvas.create_rectangle(
            cx - rect_w / 2, top_y + 2, cx + rect_w / 2, top_y + rect_h,
            outline=SELECTION_COLOR if idx == self.current_index else "",
            width=2,
        )
        self.canvas.tag_lower(rect_id)

        self._rendered[idx] = {"rect": rect_id, "image": image_id, "text": text_id, "photo": photo}

    def _scroll_to_index(self, index):
        if self.columns <= 0 or self._total_rows <= 0:
            return
        total_h = self._total_rows * CELL_H
        if total_h <= 0:
            return
        row = index // self.columns
        row_top = row * CELL_H
        row_bottom = row_top + CELL_H

        y0f, y1f = self.canvas.yview()
        view_top = y0f * total_h
        view_bottom = y1f * total_h

        if row_top < view_top:
            self.canvas.yview_moveto(max(0.0, row_top / total_h))
        elif row_bottom > view_bottom:
            new_top = row_bottom - (view_bottom - view_top)
            self.canvas.yview_moveto(max(0.0, new_top / total_h))

    # ------------------------------------------------------------------
    # Scrolling / input
    # ------------------------------------------------------------------
    def _bind_wheel(self, event):
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind_all("<Shift-MouseWheel>", self._on_shift_mousewheel)

    def _unbind_wheel(self, event):
        self.canvas.unbind_all("<MouseWheel>")
        self.canvas.unbind_all("<Shift-MouseWheel>")

    def _scroll_units(self, direction):
        self.canvas.yview_scroll(direction, "units")
        self._refresh_visible()

    def _on_mousewheel(self, event):
        # Windows/macOS: event.delta is +/-120 per notch.
        direction = -1 if event.delta > 0 else 1
        self._scroll_units(direction)

    def _on_shift_mousewheel(self, event):
        direction = -1 if event.delta > 0 else 1
        self._step_selection(direction)

    def _on_vscroll(self, *args):
        self.canvas.yview(*args)
        self._refresh_visible()

    def _step_selection(self, direction):
        if not self.titles:
            return
        new_index = min(max(self.current_index + direction, 0), len(self.titles) - 1)
        self._select_index(new_index)

    def _on_canvas_click(self, event):
        if not self.titles or self.columns <= 0:
            return
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        col = int(cx // self._effective_col_w)
        row = int(cy // CELL_H)
        if col < 0 or col >= self.columns or row < 0:
            return
        index = row * self.columns + col
        if 0 <= index < len(self.titles):
            self._select_index(index)

    # ------------------------------------------------------------------
    # Directory loading
    # ------------------------------------------------------------------
    def load_directory(self, directory):
        """1.1 Scan a directory and (re)build the thumbnail gallery, in the background."""
        # Invalidate any load already in progress so its results get ignored.
        self._load_generation += 1
        generation = self._load_generation

        self._clear_all_rendered()
        self.titles.clear()
        self.paths.clear()
        self.thumb_images.clear()
        self.current_index = -1
        self._next_unloaded_index = 0
        self._total_rows = 0
        self._update_scrollregion()

        # Fast, cheap directory listing happens on the main thread - it's
        # just filenames, not decoding - so no need to background it.
        self._all_paths = scan_directory_for_images(directory)

        if not self._all_paths:
            self.hint_label.config(text="No supported images were found in that directory.")
            self.progress_label.config(text="")
            return

        self.hint_label.config(text=f"{len(self._all_paths)} image(s) found")
        self._load_next_chunk(generation)

    def _load_next_chunk(self, generation):
        """Kick off a background thread that decodes thumbnails for the next chunk."""
        if generation != self._load_generation:
            return  # a newer directory load has superseded this one

        start = self._next_unloaded_index
        end = min(start + DECODE_CHUNK, len(self._all_paths))
        if start >= end:
            return

        chunk_paths = self._all_paths[start:end]
        self._next_unloaded_index = end

        self.progress_label.config(text=f"Loading {start + 1}-{end} of {len(self._all_paths)}...")

        thread = threading.Thread(
            target=self._decode_thumbnails_worker,
            args=(chunk_paths, generation),
            daemon=True,
        )
        self._loader_thread = thread
        thread.start()
        self.after(QUEUE_POLL_MS, self._drain_queue, generation)

    def _decode_thumbnails_worker(self, chunk_paths, generation):
        """Runs on a background thread: decode each thumbnail, skip failures."""
        for path in chunk_paths:
            if generation != self._load_generation:
                return  # stale load, abandon early
            title = os.path.splitext(os.path.basename(path))[0]
            try:
                thumb_image = make_thumbnail(path, THUMB_SIZE)
            except Exception:
                # Corrupt / unsupported file - skip it, don't crash the load
                continue
            self._thumb_queue.put((generation, title, path, thumb_image))
        self._thumb_queue.put((generation, "__CHUNK_DONE__", None, None))

    def _drain_queue(self, generation):
        if generation != self._load_generation:
            return  # ignore results from a superseded directory load

        added = 0
        chunk_done = False
        try:
            while added < QUEUE_DRAIN_PER_TICK:
                item_generation, title, path, thumb_image = self._thumb_queue.get_nowait()
                if item_generation != generation:
                    continue  # leftover result from a directory load we've since abandoned
                if title == "__CHUNK_DONE__":
                    chunk_done = True
                    break
                self._add_thumbnail_data(title, path, thumb_image)
                added += 1
        except queue.Empty:
            pass

        if chunk_done:
            self._on_chunk_finished(generation)
        else:
            if (self._loader_thread and self._loader_thread.is_alive()) or not self._thumb_queue.empty():
                self.after(QUEUE_POLL_MS, self._drain_queue, generation)
            else:
                self._on_chunk_finished(generation)

    def _on_chunk_finished(self, generation):
        remaining = len(self._all_paths) - self._next_unloaded_index
        if remaining > 0:
            self.progress_label.config(
                text=f"Loaded {self._next_unloaded_index} of {len(self._all_paths)}..."
            )
            self._load_next_chunk(generation)  # keep going automatically, no button needed
        else:
            self.progress_label.config(text=f"Loaded all {len(self._all_paths)} image(s)")

    def _add_thumbnail_data(self, title, path, thumb_image):
        self.titles.append(title)
        self.paths.append(path)
        self.thumb_images.append(thumb_image)
        self._update_scrollregion()
        self._refresh_visible()

    # ------------------------------------------------------------------
    def _select_index(self, index):
        if not self.titles or index < 0 or index >= len(self.titles):
            return

        old_index = self.current_index
        self.current_index = index

        if old_index in self._rendered:
            self.canvas.itemconfigure(self._rendered[old_index]["rect"], outline="")

        self._scroll_to_index(index)
        self._refresh_visible()

        if index in self._rendered:
            self.canvas.itemconfigure(self._rendered[index]["rect"], outline=SELECTION_COLOR)

        title = self.titles[index]
        path = self.paths[index]
        self.selection_label.config(text=f"Selected: {title}")
        self.on_image_chosen(title, path)