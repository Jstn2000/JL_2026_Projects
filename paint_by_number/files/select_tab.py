"""
select_tab.py

1.2 Choose an image from the directory to process.
    1.2.1 Preselection UI
        1.2.1.1 A list of all image options with a preview + title beneath
        1.2.1.2 A slider and mouse-scroll option for the image choice

Thumbnail loading is done on a background thread and streamed into the UI
incrementally so that large directories don't freeze or crash the app:
    - scanning + thumbnail decoding happens off the main thread
    - results are pushed onto a queue and drained a few at a time via
      `after()`, so the UI stays responsive throughout
    - a single unreadable/corrupt file is skipped instead of aborting
      the whole load
    - very large directories are capped with a "Load more" button so we
      don't create thousands of widgets (and thousands of PhotoImages) at once
"""

import os
import queue
import threading
import tkinter as tk
from tkinter import ttk

from PIL import ImageTk

from image_utils import scan_directory_for_images, make_thumbnail

THUMB_SIZE = (140, 140)
BATCH_SIZE = 60           # how many thumbnails to reveal per page / per "Load more" click
QUEUE_POLL_MS = 30        # how often we drain the background queue into the UI
QUEUE_DRAIN_PER_TICK = 8  # how many finished thumbnails to add to the UI per poll


class SelectTab(ttk.Frame):
    def __init__(self, parent, state_obj, on_image_chosen):
        super().__init__(parent)
        self.state_obj = state_obj
        self.on_image_chosen = on_image_chosen

        self.titles = []          # ordered list of image titles actually shown
        self.paths = []           # ordered list of matching source paths
        self.thumbnails = []      # keep PhotoImage refs alive
        self.card_widgets = []    # frame per thumbnail, for highlighting
        self.current_index = -1

        self._all_paths = []           # every image path found in the directory
        self._next_unloaded_index = 0  # cursor into _all_paths for pagination
        self._load_generation = 0      # bumped whenever a new directory load starts,
                                        # lets us ignore stale background results
        self._thumb_queue = queue.Queue()
        self._loader_thread = None
        self._more_button = None

        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self):
        top = ttk.Frame(self, padding=8)
        top.pack(side=tk.TOP, fill=tk.X)

        ttk.Label(top, text="Select an image:").pack(side=tk.LEFT)

        self.hint_label = ttk.Label(top, text="(Use File > Open Directory to load images)", foreground="#888")
        self.hint_label.pack(side=tk.LEFT, padx=10)

        self.progress_label = ttk.Label(top, text="", foreground="#888")
        self.progress_label.pack(side=tk.RIGHT)

        # Scrollable thumbnail gallery ----------------------------------
        gallery_container = ttk.Frame(self)
        gallery_container.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8, pady=8)

        self.canvas = tk.Canvas(gallery_container, borderwidth=0, highlightthickness=0)
        v_scroll = ttk.Scrollbar(gallery_container, orient=tk.VERTICAL, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=v_scroll.set)

        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.gallery_frame = ttk.Frame(self.canvas)
        self.gallery_window = self.canvas.create_window((0, 0), window=self.gallery_frame, anchor="nw")

        self.gallery_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._on_canvas_resize)

        # Mouse wheel over the gallery scrolls the view (this was broken -
        # it used to jump the *selection* instead of scrolling, so you could
        # never scroll down to thumbnails below the fold).
        self.canvas.bind("<Enter>", self._bind_wheel)
        self.canvas.bind("<Leave>", self._unbind_wheel)
        # Linux mouse wheel events (no <MouseWheel>/delta there)
        self.canvas.bind("<Button-4>", lambda e: self.canvas.yview_scroll(-1, "units"))
        self.canvas.bind("<Button-5>", lambda e: self.canvas.yview_scroll(1, "units"))
        # 1.2.1.2 Shift+wheel steps through images one at a time (quick "choice" scroll)
        self.canvas.bind("<Shift-Button-4>", lambda e: self._step_selection(-1))
        self.canvas.bind("<Shift-Button-5>", lambda e: self._step_selection(1))

        # 1.2.1.2 Slider to pick the image by index -----------------------
        bottom = ttk.Frame(self, padding=8)
        bottom.pack(side=tk.BOTTOM, fill=tk.X)

        ttk.Label(bottom, text="Browse:").pack(side=tk.LEFT)
        self.slider = ttk.Scale(bottom, from_=0, to=0, orient=tk.HORIZONTAL, command=self._on_slider_move)
        self.slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)

        self.selection_label = ttk.Label(bottom, text="No image selected")
        self.selection_label.pack(side=tk.RIGHT)

    def _on_canvas_resize(self, event):
        self.canvas.itemconfig(self.gallery_window, width=event.width)

    def _bind_wheel(self, event):
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind_all("<Shift-MouseWheel>", self._on_shift_mousewheel)

    def _unbind_wheel(self, event):
        self.canvas.unbind_all("<MouseWheel>")
        self.canvas.unbind_all("<Shift-MouseWheel>")

    def _on_mousewheel(self, event):
        # Windows/macOS: event.delta is +/-120 per notch. Scroll the gallery.
        direction = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(direction, "units")

    def _on_shift_mousewheel(self, event):
        # 1.2.1.2 Shift+wheel steps through images one at a time
        direction = -1 if event.delta > 0 else 1
        self._step_selection(direction)

    def _step_selection(self, direction):
        if not self.titles:
            return
        new_index = min(max(self.current_index + direction, 0), len(self.titles) - 1)
        self.slider.set(new_index)  # triggers _on_slider_move -> _select_index

    def _on_slider_move(self, value):
        index = int(round(float(value)))
        self._select_index(index)

    # ------------------------------------------------------------------
    # Directory loading
    # ------------------------------------------------------------------
    def load_directory(self, directory):
        """1.1 Scan a directory and (re)build the thumbnail gallery, in the background."""
        # Invalidate any load already in progress so its results get ignored.
        self._load_generation += 1
        generation = self._load_generation

        for child in self.gallery_frame.winfo_children():
            child.destroy()
        self.titles.clear()
        self.paths.clear()
        self.thumbnails.clear()
        self.card_widgets.clear()
        self.current_index = -1
        self._next_unloaded_index = 0
        self._more_button = None

        # Fast, cheap directory listing happens on the main thread - it's
        # just filenames, not decoding - so no need to background it.
        self._all_paths = scan_directory_for_images(directory)

        if not self._all_paths:
            self.hint_label.config(text="No supported images were found in that directory.")
            self.progress_label.config(text="")
            self.slider.configure(to=0)
            return

        self.hint_label.config(text=f"{len(self._all_paths)} image(s) found")
        self._load_next_batch(generation)

    def _load_next_batch(self, generation):
        """Kick off a background thread that decodes thumbnails for the next batch."""
        if generation != self._load_generation:
            return  # a newer directory load has superseded this one

        start = self._next_unloaded_index
        end = min(start + BATCH_SIZE, len(self._all_paths))
        if start >= end:
            return

        batch_paths = self._all_paths[start:end]
        self._next_unloaded_index = end

        self.progress_label.config(text=f"Loading {start + 1}-{end} of {len(self._all_paths)}...")

        thread = threading.Thread(
            target=self._decode_thumbnails_worker,
            args=(batch_paths, generation),
            daemon=True,
        )
        self._loader_thread = thread
        thread.start()
        self.after(QUEUE_POLL_MS, self._drain_queue, generation)

    def _decode_thumbnails_worker(self, batch_paths, generation):
        """Runs on a background thread: decode each thumbnail, skip failures."""
        for path in batch_paths:
            if generation != self._load_generation:
                return  # stale load, abandon early
            title = os.path.splitext(os.path.basename(path))[0]
            try:
                thumb_image = make_thumbnail(path, THUMB_SIZE)
            except Exception:
                # Corrupt / unsupported file - skip it, don't crash the load
                continue
            self._thumb_queue.put((generation, title, path, thumb_image))
        self._thumb_queue.put((generation, "__BATCH_DONE__", None, None))

    def _drain_queue(self, generation):
        if generation != self._load_generation:
            return  # ignore results from a superseded directory load

        added = 0
        batch_done = False
        try:
            while added < QUEUE_DRAIN_PER_TICK:
                item_generation, title, path, thumb_image = self._thumb_queue.get_nowait()
                if item_generation != generation:
                    continue  # leftover result from a directory load we've since abandoned
                if title == "__BATCH_DONE__":
                    batch_done = True
                    break
                self._add_thumbnail_card(title, path, thumb_image)
                added += 1
        except queue.Empty:
            pass

        if batch_done:
            self._on_batch_finished(generation)
        else:
            # still more items in this batch (or still running) - keep polling
            if (self._loader_thread and self._loader_thread.is_alive()) or not self._thumb_queue.empty():
                self.after(QUEUE_POLL_MS, self._drain_queue, generation)
            else:
                self._on_batch_finished(generation)

    def _on_batch_finished(self, generation):
        remaining = len(self._all_paths) - self._next_unloaded_index
        if remaining > 0:
            self.progress_label.config(
                text=f"Loaded {self._next_unloaded_index} of {len(self._all_paths)}"
            )
            self._show_load_more_button(remaining, generation)
        else:
            self.progress_label.config(text=f"Loaded all {len(self._all_paths)} image(s)")

        if self.current_index == -1 and self.titles:
            self._select_index(0)

    def _show_load_more_button(self, remaining, generation):
        if self._more_button is not None:
            self._more_button.destroy()

        columns = 4
        row = len(self.titles) // columns + 1
        self._more_button = ttk.Button(
            self.gallery_frame,
            text=f"Load {min(BATCH_SIZE, remaining)} more ({remaining} remaining)...",
            command=lambda: self._on_load_more_clicked(generation),
        )
        self._more_button.grid(row=row, column=0, columnspan=columns, pady=10)

    def _on_load_more_clicked(self, generation):
        if self._more_button is not None:
            self._more_button.destroy()
            self._more_button = None
        self._load_next_batch(generation)

    def _add_thumbnail_card(self, title, path, thumb_image):
        index = len(self.titles)
        self.titles.append(title)
        self.paths.append(path)

        columns = 4
        card = ttk.Frame(self.gallery_frame, padding=6, relief=tk.FLAT, borderwidth=2)
        card.grid(row=index // columns, column=index % columns, padx=6, pady=6, sticky="n")

        thumb = ImageTk.PhotoImage(thumb_image)
        self.thumbnails.append(thumb)  # keep alive

        img_label = tk.Label(card, image=thumb, cursor="hand2")
        img_label.pack()
        title_label = ttk.Label(card, text=title, wraplength=THUMB_SIZE[0])
        title_label.pack()

        for widget in (card, img_label, title_label):
            widget.bind("<Button-1>", lambda e, idx=index: self._select_index(idx))

        self.card_widgets.append(card)
        self.slider.configure(to=max(0, len(self.titles) - 1))

    # ------------------------------------------------------------------
    def _select_index(self, index):
        if not self.titles or index < 0 or index >= len(self.titles):
            return
        self.current_index = index

        # highlight selected card
        for i, card in enumerate(self.card_widgets):
            card.configure(relief=tk.SOLID if i == index else tk.FLAT)

        # Keep slider in sync, but avoid re-triggering _on_slider_move
        # (which would call back into this method) when the value hasn't changed.
        if int(round(float(self.slider.get()))) != index:
            self.slider.set(index)

        title = self.titles[index]
        path = self.paths[index]
        self.selection_label.config(text=f"Selected: {title}")
        self.on_image_chosen(title, path)