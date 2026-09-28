"""
Flatfield.py -- shared illumination correction for the OpenFlexure cell counter.

Used by BOTH Server_Workflow.py and Local_Workflow.py so the two backends see
identically corrected images. Cell_Counter_Main.py needs no changes.

Why the correction happens on the Pi rather than on the server
--------------------------------------------------------------
The flat-field reference describes THIS microscope's illumination, condenser
alignment and camera. It is a property of the instrument, not of the analysis
server. Correcting on the Pi means:

  * the server stays stateless and microscope-agnostic, so several microscopes
    can share one server without any risk of applying the wrong reference;
  * the reference travels with the instrument it belongs to;
  * both backends share one code path, so local and server counts stay
    comparable.

The compute cost is one divide over ~2 megapixels, a few tens of milliseconds
on a Pi 4B with the reference cached in memory. That is negligible next to
segmentation or network transfer, so the correctness argument wins.

Compatible with Python 3.7. Requires OpenCV and numpy only.
"""

from __future__ import print_function

import os

import cv2
import numpy as np

DEFAULT_FLATFIELD_PATH = os.path.join(
    "/home/openflexure/Applications/Cell_Counter", "calibration", "flatfield.tiff")

# Target mean level of the corrected image. Chosen so corrected pixels sit
# comfortably inside 0-255 without clipping highlights.
TARGET_MEAN = 180.0

_cache = {}


class FlatfieldError(RuntimeError):
    pass


def load_reference(path=None):
    """
    Load and cache the flat-field reference as float32 grayscale.

    Returns None if no reference exists, so callers can carry on uncorrected
    rather than failing.
    """
    path = path or DEFAULT_FLATFIELD_PATH
    if path in _cache:
        return _cache[path]
    if not os.path.exists(path):
        _cache[path] = None
        return None

    ref = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if ref is None:
        _cache[path] = None
        return None

    ref = ref.astype(np.float32)

    # Smooth the reference. A single captured frame carries its own shot
    # noise, and dividing by a noisy reference INJECTS that noise into every
    # corrected image. Illumination varies smoothly, so light blurring costs
    # nothing real and measurably improves output SNR.
    ref = cv2.GaussianBlur(ref, (0, 0), 3.0)

    ref = np.maximum(ref, 1.0)
    _cache[path] = ref
    return ref


def apply(gray, path=None, grid=None):
    """
    Divide out the illumination profile.

    `gray`  : 2D uint8/float image, either a single field or an NxN mosaic.
    `grid`  : mosaic size. If None it is inferred from the reference shape.

    The reference is normally a SINGLE field of view, while the image being
    corrected is a 2x2 mosaic of that same field -- every tile shares one
    illumination pattern, so the reference is applied tile by tile.

    Returns float32, same shape. If no reference is available, returns the
    input unchanged.
    """
    ref = load_reference(path)
    if ref is None:
        return gray.astype(np.float32)

    g = gray.astype(np.float32)
    gh, gw = g.shape[:2]
    rh, rw = ref.shape[:2]

    if grid is None:
        if (gh, gw) == (rh, rw):
            grid = 1
        elif gh % rh == 0 and gw % rw == 0 and gh // rh == gw // rw:
            grid = gh // rh
        else:
            raise FlatfieldError(
                "Flat-field reference %dx%d does not tile into image %dx%d. "
                "Capture the reference with the same camera settings as your "
                "samples." % (rw, rh, gw, gh))

    if grid == 1 and (gh, gw) != (rh, rw):
        raise FlatfieldError("Reference shape %s != image shape %s"
                             % ((rh, rw), (gh, gw)))

    scale = TARGET_MEAN / float(np.mean(ref))
    out = np.empty_like(g)
    th, tw = gh // grid, gw // grid
    for r in range(grid):
        for c in range(grid):
            sl = (slice(r * th, (r + 1) * th), slice(c * tw, (c + 1) * tw))
            out[sl] = g[sl] / ref * (np.mean(ref) * scale)
    return out


def apply_uint8(gray, path=None, grid=None):
    """As apply(), but returned as uint8 ready to save or upload."""
    out = apply(gray, path, grid)
    return np.clip(out, 0, 255).astype(np.uint8)


def is_available(path=None):
    return load_reference(path) is not None


def describe(path=None):
    """Diagnostics for the calibration step."""
    ref = load_reference(path)
    if ref is None:
        return "No flat-field reference found at %s" % (path or DEFAULT_FLATFIELD_PATH)
    centre = ref[ref.shape[0] // 3:2 * ref.shape[0] // 3,
                 ref.shape[1] // 3:2 * ref.shape[1] // 3].mean()
    lo = float(ref.min())
    return ("Flat-field reference %dx%d: centre %.0f, darkest %.0f, "
            "falloff %.0f%%" % (ref.shape[1], ref.shape[0], centre, lo,
                                100 * (1 - lo / centre)))
