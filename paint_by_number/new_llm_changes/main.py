"""
PixelPaint - entry point.

Run with:  python3 main.py

A small desktop app that lets you:
  1. Pick a directory of images and browse them as thumbnails
  2. Pixelate the chosen image (custom pixel size + color count)
  3. Paint on the pixelated grid, paint-by-numbers style, with
     single-pixel / fill / "magic pencil" tools, zoom and pan.
"""

from app import main

if __name__ == "__main__":
    main()
