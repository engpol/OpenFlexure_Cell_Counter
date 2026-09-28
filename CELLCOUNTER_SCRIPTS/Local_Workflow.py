"""
Local_Workflow.py -- on-device cell counting

A drop-in alternative to Server_Workflow.py.

Uses classical computer vision (illumination correction -> gradient energy ->
seeded watershed) rather than deep learning. This runs in a few seconds on a
Raspberry Pi 4B.

Dependencies: OpenCV and numpy only

    sudo apt install python3-opencv python3-numpy

Compatible with Python 3.7.
"""

from __future__ import print_function

import os
import time

import cv2
import numpy as np

# --------------------------------------------------------------------------
# Paths -- identical to Server_Workflow.py
# --------------------------------------------------------------------------
BASE_DIR = "/home/openflexure/Applications/Cell_Counter"
LOCAL_IMAGE_PATH = os.path.join(BASE_DIR, "chosen_image", "chosen_image.tiff")
PROCESSED_IMAGE_PATH = os.path.join(BASE_DIR, "workflow_files", "image_mask.png")
PROCESSED_TEXT_PATH = os.path.join(BASE_DIR, "workflow_files", "cell_number.txt")

CONFIG_PATH = os.path.expanduser("~/.cell_counter/local.conf")

# Flat-field correction is handled by the shared Flatfield module, so this
# backend and the server backend see identically corrected images.
try:
    import Flatfield
except ImportError:
    Flatfield = None

DEFAULTS = {
    "cell_diameter": 30.0,   # cell size in pixels
    "sensitivity": 1.5,      # local SDs above local background (see _segment_tile)
    "min_circularity": 0.15,
    "grid": 2,               # mosaic is 2x2 - this will probably always stay unless i decide we need more fov
    "flatfield": True,       # apply illumination correction
    "flatfield_path": "",    # blank = Flatfield.DEFAULT_FLATFIELD_PATH
    "save_corrected": True,  # keep an inspectable corrected copy
    "contrast_norm": "on",   # on | off | auto -- "on" is right in almost all cases
    "blur_factor": 6.0,      # gradient blur sigma = cell_diameter / blur_factor
    "min_diameter": 0.0,     # px; 0 = 0.6 x cell_diameter
    "max_diameter": 0.0,     # px; 0 = 1.9 x cell_diameter
}


class LocalCountError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
def load_config():
    cfg = dict(DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip().lower()
                if k not in cfg:
                    continue
                v = v.strip()
                default = DEFAULTS[k]
                try:
                    if isinstance(default, bool):
                        # bool("false") is True, so parse booleans explicitly.
                        cfg[k] = v.lower() not in ("0", "false", "no", "off")
                    else:
                        cfg[k] = type(default)(v)
                except ValueError:
                    pass
    return cfg


# --------------------------------------------------------------------------
# Image processing (OpenCV only)
# --------------------------------------------------------------------------
def _local_contrast_norm(t, sigma=50.0):
    """
    Normalise brightness AND contrast.

    Dividing only by the illumination fixes mean level but not signal
    amplitude, so cells in vignetted corners stay faint and get missed.
    Dividing by the local standard deviation equalises detectability across
    the field.
    """
    t = t.astype(np.float32)
    mu = cv2.GaussianBlur(t, (0, 0), sigma)
    var = cv2.GaussianBlur((t - mu) * (t - mu), (0, 0), sigma)
    sd = np.sqrt(np.maximum(var, 1e-6))
    return (t - mu) / np.maximum(sd, 1.0)


def _fill_holes(mask):
    """
    Binary hole fill using flood fill from outside the image (no scipy).

    The mask is padded with a one-pixel background border first. Seeding the
    flood fill at (0, 0) of the UNPADDED mask is a trap: if foreground touches
    that corner the fill cannot propagate, bitwise_not returns everything, and
    the "filled" mask becomes the entire image. Padding guarantees the seed is
    background.
    """
    padded = cv2.copyMakeBorder(mask, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
    flood = padded.copy()
    h, w = padded.shape
    scratch = np.zeros((h + 2, w + 2), np.uint8)
    cv2.floodFill(flood, scratch, (0, 0), 255)
    filled = padded | cv2.bitwise_not(flood)
    return filled[1:-1, 1:-1]


def _local_maxima(dist, min_distance):
    """Peak detection via grey dilation (no scikit-image)."""
    ksz = int(max(3, 2 * int(min_distance) + 1))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ksz, ksz))
    dil = cv2.dilate(dist, kernel)
    return ((dist >= dil - 1e-5) & (dist > 0)).astype(np.uint8)


def _segment_tile(t, cell_d, sensitivity, min_circ, contrast_norm=True,
                  blur_factor=6.0, min_d=0.0, max_d=0.0):
    # Local contrast normalisation exists to rescue cells from vignetted
    # corners. On an image that has ALREADY been flat-field corrected there is
    # no vignetting left to rescue, and applying it anyway amplifies noise in
    # empty regions -- which raises the detection threshold and loses faint
    # cells. Measured on real data: skipping it improved separation between
    # cells and background by ~50%.
    z = _local_contrast_norm(t) if contrast_norm else t

    gx = cv2.Scharr(z, cv2.CV_32F, 1, 0)
    gy = cv2.Scharr(z, cv2.CV_32F, 0, 1)
    # These cells are ANNULI -- a bright rim with an interior close to
    # background. The blur has to be wide enough to close the ring into a solid
    # disc, otherwise fill_holes has nothing enclosed to fill and each cell
    # fragments into arcs. Roughly cell_diameter/3 works; /6 is too tight.
    mag = cv2.GaussianBlur(cv2.magnitude(gx, gy), (0, 0), cell_d / blur_factor)

    # Scharr produces a spurious high-gradient ring at the image border.
    # Left in, it merges with real objects and corrupts the hole fill.
    b = max(2, int(cell_d / 4))
    mag[:b, :] = 0
    mag[-b:, :] = 0
    mag[:, :b] = 0
    mag[:, -b:] = 0

    # Spatially adaptive threshold.
    #
    # A single global threshold per tile assumes the background noise is
    # uniform. After flat-field correction it is NOT: dividing by a small
    # number in the previously-vignetted corners amplifies noise there as much
    # as signal. A global threshold low enough to catch faint cells in the
    # bright centre therefore fires constantly on noise in the corners.
    #
    # Estimating background level and spread LOCALLY makes the threshold track
    # the noise, so one sensitivity value behaves consistently across the field.
    win = max(31, int(cell_d * 4) | 1)
    local_med = cv2.blur(mag, (win, win))
    local_mad = cv2.blur(np.abs(mag - local_med), (win, win)) * 1.4826
    mask = (mag > local_med + sensitivity * local_mad).astype(np.uint8) * 255

    mask = _fill_holes(mask)
    mask = cv2.morphologyEx(
        mask, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))

    dist = cv2.distanceTransform((mask > 0).astype(np.uint8), cv2.DIST_L2, 5)
    peaks = _local_maxima(dist, cell_d * 0.45) & (mask > 0).astype(np.uint8)
    n_seeds, seeds = cv2.connectedComponents(peaks)
    if n_seeds <= 1:
        return np.zeros(t.shape, np.int32), []

    # cv2.watershed floods markers into regions labelled 0 ("unknown").
    # Background must be its own label, seeds get 2..N, and the rest of the
    # mask MUST stay 0 -- otherwise there is nothing to flood into and the
    # regions never grow beyond the seed pixels themselves.
    markers = np.zeros(t.shape, np.int32)
    markers[mask == 0] = 1                       # background
    markers[peaks > 0] = seeds[peaks > 0] + 1    # seeds -> 2..N
    rgb = cv2.cvtColor(
        cv2.normalize(dist, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8),
        cv2.COLOR_GRAY2BGR)
    cv2.watershed(rgb, markers)
    markers[markers <= 1] = 0
    markers[mask == 0] = 0

    # Accepted size range, stated as DIAMETERS in pixels -- much easier to
    # reason about than the area factors this replaced, which looked like radii
    # but actually scaled diameter (0.30 meant 0.6x, not 0.3x).
    lo = min_d if min_d > 0 else 0.6 * cell_d
    hi = max_d if max_d > 0 else 1.9 * cell_d
    amin = np.pi * (lo / 2.0) ** 2
    amax = np.pi * (hi / 2.0) ** 2

    out = np.zeros(t.shape, np.int32)
    diams = []
    idx = 0
    for lab in np.unique(markers):
        if lab <= 0:
            continue
        sub = (markers == lab).astype(np.uint8)
        area = int(sub.sum())
        if not (amin <= area <= amax):
            continue
        cnts = cv2.findContours(sub, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cnts = cnts[0] if len(cnts) == 2 else cnts[1]   # OpenCV 3 vs 4
        if not cnts:
            continue
        per = cv2.arcLength(cnts[0], True)
        if per <= 0 or 4 * np.pi * area / (per * per) < min_circ:
            continue
        idx += 1
        out[sub > 0] = idx
        diams.append(2.0 * np.sqrt(area / np.pi))
    return out, diams


def apply_flatfield(gray, cfg):
    """
    Correct illumination, reporting plainly what happened.

    Returns (corrected_uint8, applied_bool). Every outcome is logged: a silent
    fallback would let you believe correction was happening when it was not.
    """
    if not cfg.get("flatfield", True):
        print("  [flat-field] DISABLED in %s" % CONFIG_PATH)
        return gray, False

    if Flatfield is None:
        print("  [flat-field] SKIPPED: Flatfield.py not importable from %s"
              % os.path.dirname(os.path.abspath(__file__)))
        return gray, False

    path = cfg.get("flatfield_path") or Flatfield.DEFAULT_FLATFIELD_PATH
    if not os.path.exists(path):
        print("  [flat-field] SKIPPED: no reference at %s" % path)
        print("               Create one with: python3 make_flatfield.py --capture 16")
        return gray, False

    try:
        before = float(cv2.GaussianBlur(gray.astype(np.float32), (0, 0), 40).std())
        corrected = Flatfield.apply_uint8(gray, path=cfg.get("flatfield_path") or None)
        after = float(cv2.GaussianBlur(corrected.astype(np.float32), (0, 0), 40).std())
        print("  [flat-field] APPLIED using %s" % path)
        print("               background variation %.1f -> %.1f (%.1fx flatter)"
              % (before, after, before / max(after, 1e-6)))
        return corrected, True
    except Exception as exc:
        print("  [flat-field] SKIPPED: %s. Counting the raw image." % exc)
        return gray, False


def needs_contrast_norm(gray, threshold=8.0):
    """
    Decide whether local contrast normalisation is worth applying.

    Measures how much the background level still varies across the image. A
    flat-field corrected image scores ~2; an uncorrected one scores ~50.
    """
    bg = cv2.GaussianBlur(gray.astype(np.float32), (0, 0), 40)
    return float(bg.std()) > threshold


def count_image(gray, cfg):
    """
    Process the mosaic tile-by-tile: avoids seams and per-tile vignetting.

    Expects an ALREADY-CORRECTED image -- call apply_flatfield() first.
    Process_Images() does this for you.
    """
    g = gray.astype(np.float32)
    n = int(cfg["grid"])

    mode = str(cfg.get("contrast_norm", "on")).lower()
    if mode == "auto":
        lcn = needs_contrast_norm(gray)
    else:
        lcn = mode not in ("0", "false", "no", "off")
    h, w = g.shape
    th, tw = h // n, w // n
    total = 0
    all_d = []
    labels = np.zeros((h, w), np.int32)
    for r in range(n):
        for c in range(n):
            sl = (slice(r * th, (r + 1) * th), slice(c * tw, (c + 1) * tw))
            lab, d = _segment_tile(g[sl], cfg["cell_diameter"],
                                   cfg["sensitivity"], cfg["min_circularity"],
                                   contrast_norm=lcn,
                                   blur_factor=float(cfg.get("blur_factor", 6.0)),
                                   min_d=float(cfg.get("min_diameter", 0.0)),
                                   max_d=float(cfg.get("max_diameter", 0.0)))
            lab[lab > 0] += total
            labels[sl] = lab
            total += len(d)
            all_d += d
    return total, all_d, labels


def _outlines(mask):
    o = np.zeros(mask.shape, dtype=bool)
    v = mask[:-1, :] != mask[1:, :]
    hh = mask[:, :-1] != mask[:, 1:]
    o[:-1, :] |= v
    o[1:, :] |= v
    o[:, :-1] |= hh
    o[:, 1:] |= hh
    return o & (mask > 0)


# --------------------------------------------------------------------------
# Public API -- matches Server_Workflow.Process_Images
# --------------------------------------------------------------------------
def Process_Images(image_path=None, status_callback=None):
    image_path = image_path or LOCAL_IMAGE_PATH
    if not os.path.exists(image_path):
        raise LocalCountError("Image not found: %s" % image_path)

    cfg = load_config()
    t0 = time.time()

    colour = cv2.imread(image_path, cv2.IMREAD_COLOR)
    if colour is None:
        raise LocalCountError("Could not read image: %s" % image_path)
    gray = cv2.cvtColor(colour, cv2.COLOR_BGR2GRAY)

    if status_callback:
        status_callback("Correcting illumination...")
    corrected, applied = apply_flatfield(gray, cfg)

    if status_callback:
        status_callback("Counting locally...")
    count, diams, labels = count_image(corrected, cfg)

    out_dir = os.path.dirname(PROCESSED_IMAGE_PATH)
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir)

    # Draw outlines on the image that was actually analysed, so the overlay
    # shows what the algorithm saw. This matches the server backend, which
    # returns a mask rendered over the corrected image it received.
    base = cv2.cvtColor(corrected, cv2.COLOR_GRAY2BGR) if applied else colour.copy()
    base[_outlines(labels)] = (0, 0, 255)
    cv2.imwrite(PROCESSED_IMAGE_PATH, base)

    # Keep an inspectable corrected copy, in workflow_files/ rather than beside
    # chosen_image.tiff -- stray files in the capture directory could confuse
    # anything that lists it. The RAW image is never overwritten.
    if applied and cfg.get("save_corrected", True):
        cv2.imwrite(os.path.join(out_dir, "chosen_image_corrected.tiff"), corrected)

    with open(PROCESSED_TEXT_PATH, "w") as fh:
        fh.write(str(count))

    med = float(np.median(diams)) if diams else float("nan")
    print("Counted %d cells locally in %.2f s (median diameter %.1f px)"
          % (count, time.time() - t0, med))
    if diams and abs(med - cfg["cell_diameter"]) > 0.3 * cfg["cell_diameter"]:
        print("  WARNING: measured diameter (%.0f px) differs markedly from the "
              "configured value (%.0f px). Update cell_diameter in %s."
              % (med, cfg["cell_diameter"], CONFIG_PATH))

    if status_callback:
        status_callback("Done: %d cells" % count)
    return count


if __name__ == "__main__":
    import sys
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    path = args[0] if args else LOCAL_IMAGE_PATH
    if "--check" in sys.argv and Flatfield is not None:
        # Side-by-side before/after, same as Flatfield.py --check
        Flatfield.check(path)
        raise SystemExit(0)
    Process_Images(image_path=path, status_callback=lambda m: print("  [%s]" % m))
