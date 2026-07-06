
"""
image_utils.py
 
Helper functions for:
  1.1  Scanning a directory for images (and converting to PNG using os + PIL)
  1.4.2 Pixelating an image (downsize -> upsize with nearest-neighbour resampling)
  Color quantization (used both for the pixel-art look and to build the
  numbered paint palette used in the Paint tab).
"""
 
import os
from PIL import Image
 
# Extensions we are willing to treat as "images"
SUPPORTED_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tiff")
 
# Where converted / cached PNGs are stored (1.1.1 - "extracting to png files")
CACHE_DIR_NAME = ".pixelpaint_png_cache"
 
 
def scan_directory_for_images(directory):
    """
    1.1 Search a given path to find all images in a directory.
    Returns a sorted list of absolute file paths for every supported
    image found directly inside `directory` (non-recursive).
    """
    if not directory or not os.path.isdir(directory):
        return []
 
    found = []
    for entry in os.listdir(directory):
        full_path = os.path.join(directory, entry)
        if os.path.isfile(full_path) and entry.lower().endswith(SUPPORTED_EXTENSIONS):
            found.append(full_path)
 
    return sorted(found, key=lambda p: os.path.basename(p).lower())
 
 
def ensure_png(src_path, directory):
    """
    1.1.1 Lazily convert a single image to PNG using os + PIL, on demand
    (e.g. once the user actually picks that image to work with), instead
    of converting an entire directory up front. Returns the PNG path.
    """
    base_name = os.path.basename(src_path)
    name_no_ext, ext = os.path.splitext(base_name)
 
    if ext.lower() == ".png":
        return src_path
 
    cache_dir = os.path.join(directory, CACHE_DIR_NAME)
    os.makedirs(cache_dir, exist_ok=True)
    png_path = os.path.join(cache_dir, name_no_ext + ".png")
 
    if not os.path.exists(png_path):
        with Image.open(src_path) as img:
            img.convert("RGBA").save(png_path, "PNG")
 
    return png_path
 
 
def make_thumbnail(image_path, size=(140, 140)):
    """
    1.2.1.1 Load an image and return a PIL thumbnail (caller wraps in PhotoImage).
    Works directly on the source file (no PNG conversion needed just to preview).
    Uses JPEG "draft mode" when available, which decodes at a reduced
    resolution straight from the file - much faster than a full decode
    followed by a resize, and is the main fix for slow large-directory loads.
    """
    img = Image.open(image_path)
    try:
        img.draft("RGB", size)  # no-op / ignored for formats that don't support it
    except Exception:
        pass
    img = img.convert("RGBA")
    img.thumbnail(size, Image.LANCZOS)
    return img
 
 
def quantize_colors(image, num_colors):
    """
    Reduce an image to `num_colors` distinct colors. Used both to give the
    pixel-art a limited palette and to build the numbered palette in the
    Paint tab.
    Returns an RGB Image using at most num_colors colors.
    """
    num_colors = max(1, min(256, int(num_colors)))
    rgb = image.convert("RGB")
    quantized = rgb.quantize(colors=num_colors, method=Image.MEDIANCUT)
    return quantized.convert("RGB")
 
 
def compute_pixel_grid(image, pixel_size, num_colors=None):
    """
    1.4.2.1.1 / 1.4.2.1.2 Downsize the image so every block of `pixel_size`
    source pixels becomes exactly one pixel in the returned "grid" image.
    This small grid IS the pixel-art / paint-by-numbers canvas: each pixel
    in it corresponds 1:1 with one paintable block. Optionally quantized
    down to `num_colors` distinct colors.
    """
    pixel_size = max(1, int(pixel_size))
    rgb = image.convert("RGB")
    width, height = rgb.size
 
    small_w = max(1, width // pixel_size)
    small_h = max(1, height // pixel_size)
 
    small = rgb.resize((small_w, small_h), resample=Image.BILINEAR)
 
    if num_colors:
        small = quantize_colors(small, num_colors)
 
    return small
 
 
def pixelate_image(image, pixel_size, num_colors=None):
    """
    1.4.2 Pixelate the image using PIL.
        1.4.2.1.1 Downsize and then resize back up (nearest neighbour) for
                   the blocky look.
        1.4.2.1.2 The downsize scaler is derived directly from the user's
                   requested pixel size (bigger pixel_size -> fewer, bigger blocks).
    Returns the full-resolution pixelated preview image.
    """
    rgb = image.convert("RGB")
    width, height = rgb.size
    small = compute_pixel_grid(rgb, pixel_size, num_colors)
    pixelated = small.resize((width, height), resample=Image.NEAREST)
    return pixelated
 
 
def grid_to_full_size(grid_image, target_size):
    """Upscale the small paint grid back to full resolution (NEAREST) for saving."""
    return grid_image.resize(target_size, resample=Image.NEAREST)
 
 
def get_palette_colors(image, max_colors=256):
    """
    Return an ordered list of unique RGB tuples present in `image`,
    sorted by frequency (most used first). Used to build the numbered
    color buttons in the Paint tab (2.1.1.1 / 2.1.1.2).
    """
    rgb = image.convert("RGB")
    colors = rgb.getcolors(maxcolors=rgb.width * rgb.height)
    if colors is None:
        return []
    colors.sort(key=lambda c: c[0], reverse=True)
    palette = [color for _, color in colors]
    return palette[:max_colors]
 

