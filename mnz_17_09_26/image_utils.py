"""
image_utils.py
 
Helper functions for:
  1.1  Scanning a directory for images (and converting to PNG using os + PIL)
  1.4.2 Pixelating an image (downsize -> upsize with nearest-neighbour resampling)
  Color quantization (used both for the pixel-art look and to build the
  numbered paint palette used in the Paint tab).
  Advanced Pixelate: brightness/contrast/saturation/grayscale/invert
  adjustments and true black & white thresholding, applied before the
  downsize + quantize steps above (see AdjustmentOptions).
"""
 
import hashlib
import os
import tempfile
from dataclasses import dataclass
from random import shuffle
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageOps
 
# Extensions we are willing to treat as "images"
SUPPORTED_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tiff", ".tif")
 
# Where converted / cached PNGs are stored (1.1.1 - "extracting to png files").
# Lives in the system temp folder rather than inside the user's own image
# directory, so nothing gets written into their photo folders at all, and
# the OS cleans it up on its own over time.
CACHE_DIR_NAME = "pixelpaint_png_cache"


@dataclass
class AdjustmentOptions:
    """
    Settings for the Advanced Pixelate dialog. All defaults are no-ops, so
    passing a fresh AdjustmentOptions() (or None) through the pixelate
    functions below reproduces the plain, pre-Advanced-Pixelate behavior.
    """
    brightness: float = 1.0    # PIL ImageEnhance factor: 1.0 = unchanged
    contrast: float = 1.0
    saturation: float = 1.0    # 0.0 = grayscale, 1.0 = unchanged, >1.0 = more saturated
    grayscale: bool = False
    invert: bool = False
    black_and_white: bool = False   # hard black/white threshold - see threshold_black_and_white
    bw_threshold: int = 128         # 0-255; pixels at/above this become white
    dither: bool = True             # Floyd-Steinberg dithering when reducing to `num_colors`


def apply_color_adjustments(image, adjustments):
    """
    Apply brightness/contrast/saturation/grayscale/invert, in that fixed
    order, ahead of the downsize + quantize steps. Black & white
    thresholding is handled separately by threshold_black_and_white()
    since it replaces color quantization entirely rather than adjusting
    the colors that feed into it.
    """
    rgb = image.convert("RGB")

    if adjustments.grayscale or adjustments.black_and_white:
        rgb = ImageOps.grayscale(rgb).convert("RGB")

    if adjustments.brightness != 1.0:
        rgb = ImageEnhance.Brightness(rgb).enhance(adjustments.brightness)

    if adjustments.contrast != 1.0:
        rgb = ImageEnhance.Contrast(rgb).enhance(adjustments.contrast)

    # Saturation is moot once the image is already grayscale/B&W.
    if adjustments.saturation != 1.0 and not (adjustments.grayscale or adjustments.black_and_white):
        rgb = ImageEnhance.Color(rgb).enhance(adjustments.saturation)

    if adjustments.invert:
        rgb = ImageOps.invert(rgb)

    return rgb


def threshold_black_and_white(image, threshold=128):
    """
    Reduce `image` to pure black/white with a hard brightness cutoff - a
    genuinely 2-color (0,0,0)/(255,255,255) result, which is what testers
    asking for "only black and white" actually wanted, as distinct from
    just setting Colors=2 (quantization there could land on two arbitrary
    shades rather than true black and white).
    """
    gray = image.convert("L")
    bw = gray.point(lambda p: 255 if p >= threshold else 0)
    return bw.convert("RGB")

 
 
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
 
    # return sorted(found, key=lambda p: os.path.basename(p).lower())
    shuffle(found)
    return found
 
 
def _cache_dir_for(directory):
    """
    Build a stable cache subfolder for a given source directory, inside
    the system temp folder rather than inside the user's own image
    folder. Namespaced by a short hash of the directory's absolute path,
    since two different picked folders could otherwise both contain a
    same-named file (e.g. "photo.jpg") and collide with each other.
    """
    normalized = os.path.normcase(os.path.abspath(directory))
    dir_hash = hashlib.md5(normalized.encode("utf-8")).hexdigest()[:16]
    return os.path.join(tempfile.gettempdir(), CACHE_DIR_NAME, dir_hash)


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
 
    cache_dir = _cache_dir_for(directory)
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
 
 
def quantize_colors(image, num_colors, dither=True):
    """
    Reduce an image to `num_colors` distinct colors. Used both to give the
    pixel-art a limited palette and to build the numbered palette in the
    Paint tab.
    Returns an RGB Image using at most num_colors colors.
    """
    num_colors = max(1, min(256, int(num_colors)))
    rgb = image.convert("RGB")
    dither_mode = Image.FLOYDSTEINBERG if dither else Image.NONE
    quantized = rgb.quantize(colors=num_colors, method=Image.MEDIANCUT, dither=dither_mode)
    return quantized.convert("RGB")
 
 
def compute_pixel_grid(image, pixel_size, num_colors=None, adjustments=None):
    """
    1.4.2.1.1 / 1.4.2.1.2 Downsize the image so every block of `pixel_size`
    source pixels becomes exactly one pixel in the returned "grid" image.
    This small grid IS the pixel-art / paint-by-numbers canvas: each pixel
    in it corresponds 1:1 with one paintable block.

    `adjustments` (an AdjustmentOptions, optional) applies the Advanced
    Pixelate brightness/contrast/saturation/grayscale/invert adjustments
    to the source before downsizing, then either:
      - hard black & white thresholding (if adjustments.black_and_white),
        which replaces quantization entirely, or
      - the normal quantize down to `num_colors` distinct colors.
    """
    pixel_size = max(1, int(pixel_size))
    rgb = image.convert("RGB")

    if adjustments is not None:
        rgb = apply_color_adjustments(rgb, adjustments)

    width, height = rgb.size
 
    small_w = max(1, width // pixel_size)
    small_h = max(1, height // pixel_size)
 
    small = rgb.resize((small_w, small_h), resample=Image.BILINEAR)
    # small = rgb.resize((small_w, small_h), resample=Image.Resampling.NEAREST)
 
    if adjustments is not None and adjustments.black_and_white:
        small = threshold_black_and_white(small, adjustments.bw_threshold)
    elif num_colors:
        dither = adjustments.dither if adjustments is not None else True
        small = quantize_colors(small, num_colors, dither=dither)
 
    return small
 
 
def pixelate_image(image, pixel_size, num_colors=None, adjustments=None):
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
    small = compute_pixel_grid(rgb, pixel_size, num_colors, adjustments)
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


def render_numbered_template(target_image, color_to_number, cell_size=40,
                              grid_color=(205, 205, 205), number_color=(90, 90, 90)):
    """
    Render a full-resolution, printable "paint by numbers" template: every
    cell of the small `target_image` grid is blown up to `cell_size` x
    `cell_size` pixels, drawn blank-white with its palette number and a thin
    grid border - i.e. exactly what the Paint tab shows for an *unpainted*
    cell, but rasterized at full size instead of on-screen at zoom level.

    This is what you'd hand to a friend (printed or as an image) alongside
    the palette, so they can paint the picture by hand.
    """
    width, height = target_image.size
    pixels = target_image.load()

    out = Image.new("RGB", (width * cell_size, height * cell_size), (255, 255, 255))
    draw = ImageDraw.Draw(out)
    font = ImageFont.load_default(size=max(8, int(cell_size * 0.5)))

    for gy in range(height):
        for gx in range(width):
            color = pixels[gx, gy]
            number = color_to_number.get(color, "?")
            x0, y0 = gx * cell_size, gy * cell_size
            x1, y1 = x0 + cell_size - 1, y0 + cell_size - 1

            draw.rectangle((x0, y0, x1, y1), outline=grid_color, width=1)

            text = str(number)
            bbox = draw.textbbox((0, 0), text, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            tx = x0 + (cell_size - tw) / 2 - bbox[0]
            ty = y0 + (cell_size - th) / 2 - bbox[1]
            draw.text((tx, ty), text, fill=number_color, font=font)

    return out