"""
make_flatfield.py -- build a low-noise flat-field reference.

Averaging matters. A single captured frame carries its own photon shot noise,
and because correction DIVIDES by the reference, that noise is injected into
every image you subsequently correct. On the test data, correcting with a
single frame measurably reduced signal-to-noise in the well-lit centre of the
field even while it improved uniformity.

Averaging N frames reduces the reference's noise by sqrt(N). 16 frames is
usually plenty.

Usage
-----
Capture live from the microscope (focus on a clean, empty region of a slide
with mounting medium but no cells):

    python3 make_flatfield.py --capture 16

Or average frames you already have:

    python3 make_flatfield.py --from-files blank_*.tiff

Compatible with Python 3.7.
"""

from __future__ import print_function

import argparse
import glob
import os
import sys
import FreeSimpleGUI as sg

import cv2
import numpy as np

OUT_PATH = os.path.join(
    "/home/openflexure/Applications/Cell_Counter", "calibration", "flatfield.tiff")


def summarise(ref):
    h, w = ref.shape[:2]
    centre = ref[h // 3:2 * h // 3, w // 3:2 * w // 3].mean()
    print("  size            : %d x %d" % (w, h))
    print("  centre level    : %.0f" % centre)
    print("  darkest point   : %.0f" % ref.min())
    print("  falloff         : %.0f%%" % (100 * (1 - ref.min() / centre)))
    sat = 100.0 * (ref >= 254).mean()
    print("  near-saturated  : %.3f%%" % sat)
    if sat > 0.1:
        print("  WARNING: reference is clipping. Reduce exposure and recapture —")
        print("           a clipped reference under-corrects the bright centre.")
    if centre < 120:
        print("  WARNING: reference is dim. Increase exposure so the centre sits")
        print("           around 200-240, well exposed but not clipping.")


def from_files(patterns):
    paths = []
    for p in patterns:
        paths.extend(sorted(glob.glob(p)))
    if not paths:
        raise SystemExit("No files matched: %s" % " ".join(patterns))
    print("Averaging %d file(s)..." % len(paths))
    acc = None
    for p in paths:
        img = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
        if img is None:
            print("  skipped unreadable file: %s" % p)
            continue
        f = img.astype(np.float64)
        acc = f if acc is None else acc + f
    if acc is None:
        raise SystemExit("No readable images.")
    return acc / len(paths)


def from_capture(n):
    """Capture n frames from the microscope via the OpenFlexure client."""
    try:
        from openflexure_microscope_client import MicroscopeClient
    except ImportError:
        raise SystemExit(
            "openflexure_microscope_client not available. Capture blank frames "
            "with the normal GUI instead, then use --from-files.")
    import io
    from PIL import Image

    print("Connecting to microscope...")
    scope = MicroscopeClient("microscope.local")
    print("Capturing %d frames. Do not touch the stage or focus." % n)
    acc = None
    for i in range(n):
        img = scope.capture_image()
        if not isinstance(img, Image.Image):
            img = Image.open(io.BytesIO(img))
        f = np.asarray(img.convert("L")).astype(np.float64)
        acc = f if acc is None else acc + f
        sys.stdout.write("\r  %d/%d" % (i + 1, n))
        sys.stdout.flush()
    print()
    return acc / n


def main():
    
    layout = [[sg.Text('Please press Ok when in defocus on clean slide with media'), sg.B('Ok')]] #define window layout
    window = sg.Window('Flatfield Generator', layout) # save window layout into object with title
    
    while True:
        event, values = window.read() ## show window
        if event == sg.WIN_CLOSED:
            sys.exit() # terminate script
        elif event == 'Ok': # Normally name of button corresponds to its event name, if no key is given
            break
    window.close()
    
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=False)
    g.add_argument("--capture", type=int, metavar="N",
                   help="Capture and average N frames from the microscope")
    g.add_argument("--from-files", nargs="+", metavar="GLOB",
                   help="Average existing blank-field images")
    ap.add_argument("-o", "--output", default=OUT_PATH)
    args = ap.parse_args()
    
    if args.from_files:
        ref = from_files(args.from_files)
    else:
        num_frames = args.capture if args.capture is not None else 16
        ref = from_capture(num_frames) 

    print()
    print("Flat-field reference:")
    summarise(ref)

    out_dir = os.path.dirname(args.output)
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    cv2.imwrite(args.output, np.clip(ref, 0, 255).astype(np.uint8))
    print()
    print("Saved to %s" % args.output)
    print("Both Local_Workflow.py and Server_Workflow.py will now use it "
          "automatically.")
    print("Recapture whenever you change illumination, objective or exposure.")
    
    layout = [[sg.Text("Flatfield Generated. Recapture whenever you fiddle with microscope optics"), sg.B('Ok')]] #define window layout
    window = sg.Window('Flatfield Generator', layout)
    
    while True:
        event, values = window.read() ## show window
        if event == sg.WIN_CLOSED:
            sys.exit() # terminate script
        elif event == 'Ok': # Normally name of button corresponds to its event name, if no key is given
            break
    window.close()

if __name__ == "__main__":
    main()
